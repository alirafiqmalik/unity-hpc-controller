"""Dispatch, cancel, fetch, sync — by calling the attached project's run.sh.

The controller never sbatch's itself. A job that is not recorded by run.sh
is a job the project cannot name.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from controller import events
from controller import registry

_SAFE_NAME = re.compile(r"^[A-Za-z0-9._+-]+$")
_TIMEOUT = 120


class DispatchError(ValueError):
    """Caller-facing dispatch failure."""


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
    match = re.search(r"^UNITY_OVERRIDABLE=\((.*?)\)", text, re.S | re.M)
    if not match:
        return set()
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", match.group(1)))


def _require_safe(value: str, kind: str) -> str:
    if not value or not _SAFE_NAME.match(value):
        raise DispatchError(f"unsafe {kind} {value!r}")
    return value


def _run(
    rec: dict,
    argv: list[str],
    env_overrides: dict | None = None,
    timeout: int = _TIMEOUT,
) -> dict:
    runner = _runner(rec)
    call_env = dict(os.environ)
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
    result = _run(rec, argv, env_overrides=overrides)
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
    result = _run(rec, argv, timeout=300)
    events.record("fetch", f"{slug} fetch", slug=slug, ok=result["ok"])
    return result


def sync(slug: str) -> dict:
    rec = _project(slug)
    result = _run(rec, ["sync"], timeout=300)
    events.record("sync", f"{slug} sync", slug=slug, ok=result["ok"])
    return result


def status(slug: str) -> dict:
    rec = _project(slug)
    return _run(rec, ["status"], timeout=60)
