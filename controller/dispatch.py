"""Dispatch, cancel, fetch, sync — by calling the attached project's run.sh.

The controller never sbatch's itself. A job that is not recorded by run.sh
is a job the project cannot name.
"""

from __future__ import annotations

import fcntl
import os
import re
import signal
import subprocess
from contextlib import contextmanager
from pathlib import Path

from controller import events
from controller import registry
from controller import cluster_session, telemetry
from lib import paths

_SAFE_NAME = re.compile(r"^[A-Za-z0-9._+-]+$")
_TIMEOUT = 120


class DispatchError(ValueError):
    """Caller-facing dispatch failure."""


class OperationBusy(DispatchError):
    """Another request is still running this project operation."""


@contextmanager
def _operation(rec: dict, group: str):
    """Reject overlapping operations, including across controller processes."""
    lock_dir = paths.controller_dir() / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{rec['slug']}.{group}.lock"
    with lock_path.open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise OperationBusy(
                f"{rec['slug']} already has a {group} in progress; wait for it to finish"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _project(slug: str) -> dict:
    rec = registry.get(slug)
    if rec is None:
        raise DispatchError(f"unknown project {slug!r}")
    return rec


def _runner(rec: dict) -> Path:
    runner = Path(rec["path"]) / "unityHPC" / "run.sh"
    if not runner.is_file():
        raise DispatchError(
            f"no unityHPC/run.sh in {rec['path']}; run /unity-hpc:connect first"
        )
    return runner


def _overridable(runner: Path) -> set[str]:
    text = runner.read_text(errors="replace")
    # Current scaffolds use a shell array; older attached projects use a
    # multiline quoted string. Both declare the same allowlist contract.
    match = re.search(r'^UNITY_OVERRIDABLE=(?:\((.*?)\)|"(.*?)")',
                      text, re.S | re.M)
    if not match:
        return set()
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*",
                          match.group(1) or match.group(2)))


def _require_safe(value: str, kind: str) -> str:
    if not value or not _SAFE_NAME.match(value):
        raise DispatchError(f"unsafe {kind} {value!r}")
    return value


def _run(
    rec: dict,
    argv: list[str],
    env_overrides: dict | None = None,
    timeout: int = _TIMEOUT,
    runner_path: Path | None = None,
) -> dict:
    runner = _runner(rec) if runner_path is None else runner_path.resolve()
    if runner_path is not None and (not runner.is_relative_to(Path(rec["path"]).resolve() / ".unity-workspace/plans") or not runner.is_file()):
        raise DispatchError("reviewed dispatcher must belong to a project plan snapshot")
    if "--dry-run" not in argv and argv[0] not in ("render", "jobs"):
        cfg = telemetry.settings()
        cluster_session.restore_identity(cfg["ssh_host"], cfg["ssh_identity"])
    call_env = dict(os.environ)
    # A background controller cannot answer a GUI/askpass prompt.
    call_env["SSH_ASKPASS_REQUIRE"] = "never"
    if runner_path is not None:
        call_env["UNITY_WORKSPACE_PROJECT_DIR"] = str(Path(rec["path"]).resolve())
    if env_overrides:
        allowed = _overridable(runner)
        if not allowed:
            raise DispatchError(
                "run.sh does not declare UNITY_OVERRIDABLE; re-scaffold"
            )
        unknown = sorted(k for k in env_overrides if k not in allowed)
        if unknown:
            raise DispatchError(
                f"run.sh does not accept {', '.join(unknown)} as overrides"
            )
        call_env.update({k: str(v) for k, v in env_overrides.items()})
    stored = rec.get("overrides") or {}
    if stored:
        allowed = _overridable(runner)
        for key, value in stored.items():
            if allowed and key in allowed and key not in (env_overrides or {}):
                call_env[key] = str(value)
    try:
        proc = subprocess.run(
            ["bash", str(runner), *argv],
            capture_output=True,
            text=True,
            cwd=str(rec["path"]),
            env=call_env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise DispatchError(
            f"run.sh timed out after {timeout}s ({' '.join(argv)})"
        ) from exc
    output = (proc.stdout + proc.stderr).strip()
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "output": output,
        "dry_run": "[dry-run]" in output,
        "argv": argv,
        "slug": rec["slug"],
    }


def run(
    slug: str,
    exp: str,
    campaign: str | None = None,
    dry_run: bool = False,
    overrides: dict | None = None,
    extra_args: str = "",
    runner_path: Path | None = None,
) -> dict:
    rec = _project(slug)
    exp = _require_safe(exp, "exp")
    argv = ["run", exp]
    if campaign:
        argv += ["--campaign", _require_safe(campaign, "campaign")]
    elif rec.get("campaign"):
        argv += ["--campaign", _require_safe(rec["campaign"], "campaign")]
    if dry_run:
        argv.append("--dry-run")
    if extra_args:
        argv += extra_args.split()
    with _operation(rec, "launch"):
        result = _run(rec, argv, env_overrides=overrides, **({"runner_path": runner_path} if runner_path is not None else {}))
    events.record(
        "dispatch" if not dry_run else "dry-run",
        f"{slug} run {exp}" + (" (dry-run)" if dry_run else ""),
        slug=slug,
        exp=exp,
        ok=result["ok"],
    )
    return result


def array(
    slug: str,
    manifest: str,
    campaign: str | None = None,
    extra_args: str = "",
) -> dict:
    rec = _project(slug)
    man = Path(manifest)
    if not man.is_file():
        # allow a path relative to the project
        man = Path(rec["path"]) / manifest
    if not man.is_file():
        raise DispatchError(f"manifest not found: {manifest}")
    argv = ["array", str(man)]
    if campaign:
        argv += ["--campaign", _require_safe(campaign, "campaign")]
    elif rec.get("campaign"):
        argv += ["--campaign", _require_safe(rec["campaign"], "campaign")]
    if extra_args:
        argv += extra_args.split()
    with _operation(rec, "launch"):
        result = _run(rec, argv)
    events.record("dispatch", f"{slug} array {man.name}", slug=slug, ok=result["ok"])
    return result


def cancel(slug: str, campaign: str | None = None, job: str | None = None) -> dict:
    rec = _project(slug)
    argv = ["cancel"]
    if campaign:
        argv += ["--campaign", _require_safe(campaign, "campaign")]
    elif rec.get("campaign"):
        argv += ["--campaign", _require_safe(rec["campaign"], "campaign")]
    if job:
        argv += ["--job", _require_safe(job, "job")]
    result = _run(rec, argv)
    events.record("cancel", f"{slug} cancel", slug=slug, job=job, ok=result["ok"])
    return result


def fetch(slug: str, campaign: str | None = None) -> dict:
    rec = _project(slug)
    argv = ["fetch"]
    if campaign:
        argv += ["--campaign", _require_safe(campaign, "campaign")]
    with _operation(rec, "fetch"):
        result = _run(rec, argv, timeout=300)
        hook = artifact_fetch_hook(rec)
        if hook is not None:
            artifact = _artifact_fetch(rec, hook)
            result = {
                **result,
                "ok": result["ok"] and artifact["ok"],
                "output": "\n".join(filter(None, (
                    f"Scheduler logs: {result['output']}",
                    f"Project artifacts: {artifact['output']}",
                ))),
                "logs": result,
                "artifacts": artifact,
            }
    events.record("fetch", f"{slug} fetch", slug=slug, ok=result["ok"])
    return result


def artifact_fetch_hook(rec: dict) -> Path | None:
    """Locate an optional project-owned pull script without following escapes."""
    root = Path(rec["path"]).resolve()
    candidate = root / "unityHPC" / "fetch.sh"
    if not candidate.exists():
        return None
    hook = candidate.resolve()
    if not hook.is_relative_to(root) or not hook.is_file():
        raise DispatchError("artifact fetch hook must be a file inside the project")
    return hook


def _artifact_fetch(rec: dict, hook: Path) -> dict:
    """Run the project hook after scheduler logs, with a bounded process group."""
    argv = ["bash", str(hook)]
    env = dict(os.environ)
    env["SSH_ASKPASS_REQUIRE"] = "never"
    proc = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        cwd=rec["path"], env=env, start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=1800)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            stdout, stderr = proc.communicate()
        return {"ok": False, "returncode": 124,
                "output": (stdout + stderr).strip() + "\nartifact fetch timed out after 1800s",
                "argv": argv}
    return {"ok": proc.returncode == 0, "returncode": proc.returncode,
            "output": (stdout + stderr).strip(), "argv": argv}


def sync(slug: str) -> dict:
    rec = _project(slug)
    if rec.get("sync_policy") == "disabled":
        raise DispatchError(
            f"sync is disabled for {slug}; use this project's documented safe sync workflow"
        )
    with _operation(rec, "sync"):
        result = _run(rec, ["sync"], timeout=300)
    events.record("sync", f"{slug} sync", slug=slug, ok=result["ok"])
    return result


def status(slug: str, campaign: str | None = None) -> dict:
    rec = _project(slug)
    argv = ["status"]
    if campaign:
        argv += ["--campaign", _require_safe(campaign, "campaign")]
    elif rec.get("campaign"):
        argv += ["--campaign", _require_safe(rec["campaign"], "campaign")]
    return _run(rec, argv, timeout=60)


def catalog_script(
    rec: dict, path: str, args: list[str], dry_run_arg: str | None,
    dry_run: bool,
) -> dict:
    """Run a fixed project-owned wrapper declared in experiments.json.

    The wrapper is responsible for calling run.sh, preserving its job ledger.
    No script path or arguments come from the HTTP launch request.
    """
    if not isinstance(path, str) or not path or Path(path).is_absolute():
        raise DispatchError("catalog script path must be relative to the project")
    if not isinstance(args, list) or any(not isinstance(arg, str) or "\x00" in arg for arg in args):
        raise DispatchError("catalog script args must be strings")
    root = Path(rec["path"]).resolve()
    script = (root / path).resolve()
    if not script.is_relative_to(root) or not script.is_file() or script.suffix != ".sh":
        raise DispatchError("catalog script must be a .sh file inside the project")
    if dry_run:
        if not isinstance(dry_run_arg, str) or not dry_run_arg.startswith("--"):
            raise DispatchError("catalog script has no dry-run argument")
        args = [*args, dry_run_arg]
    elif dry_run_arg is not None and not isinstance(dry_run_arg, str):
        raise DispatchError("dry_run_arg must be a string")
    argv = ["bash", str(script), *args]
    if not dry_run:
        cfg = telemetry.settings()
        cluster_session.restore_identity(cfg["ssh_host"], cfg["ssh_identity"])
    env = dict(os.environ)
    env["SSH_ASKPASS_REQUIRE"] = "never"
    with _operation(rec, "launch"):
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, cwd=str(root),
                env=env, timeout=300,
            )
        except subprocess.TimeoutExpired as exc:
            raise DispatchError("catalog script timed out after 300s") from exc
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "output": (proc.stdout + proc.stderr).strip(),
        "dry_run": dry_run,
        "argv": argv,
        "slug": rec["slug"],
    }
