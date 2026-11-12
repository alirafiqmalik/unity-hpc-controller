"""One tmux session on the login node, opened by the controller.

The session is how a scheduled sample runs. It is not a resident collector.
The shell's TMOUT is one and a half times the schedule interval, so a 30
minute schedule closes the session after 45 minutes with no command. ADR 0004.
"""

from __future__ import annotations

import os
import re
import shlex
from datetime import datetime, timezone

from lib import paths
from controller import cluster_access

SESSION_NAME = "unity-hpc"
#: Scripts the panel and the schedule may run. `loop` stays manual.
MODES = ("once", "sample", "prune")
#: How long one sample may run before the SSH call gives up, in seconds.
SAMPLE_WAIT_S = 600
_MIN_INTERVAL_MINUTES = 5
_MAX_INTERVAL_MINUTES = 1440
_MARK = "/tmp/unity-hpc-sample.rc"
_LOG = "/tmp/unity-hpc-sample.log"
_LOG_START = "--- unity-hpc-session-log ---"
_LOG_END = "--- unity-hpc-session-log-end ---"
SESSION_LOG_KEEP = 50
_SESSION_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def inactivity_timeout_s(interval_minutes: int) -> int:
    """Quiet time before the session closes, in seconds.

    One and a half intervals. 30 minutes becomes 45 minutes (2700 seconds).
    """
    try:
        minutes = int(interval_minutes)
    except (TypeError, ValueError):
        minutes = 60
    minutes = max(_MIN_INTERVAL_MINUTES, min(minutes, _MAX_INTERVAL_MINUTES))
    return minutes * 90


def parse_remote_source(source: str) -> tuple[str, str] | None:
    """`(host, cluster_dir)` for `host:/path/telemetry`, or None when local.

    `cluster_dir` is the parent of the telemetry directory. That is where
    `collector.sh` is copied.
    """
    text = str(source or "").strip()
    if ":" not in text:
        return None
    host, _, path = text.partition(":")
    host = host.strip()
    path = path.strip().rstrip("/")
    if not host or not path.startswith("/"):
        return None
    if path.endswith("/telemetry"):
        path = path[: -len("/telemetry")]
    if not path:
        return None
    return host, path


def clean_mode(mode: str | None) -> str:
    """`once`, `sample`, or `prune`. Anything else is refused."""
    text = str(mode or "once").strip()
    if text not in MODES:
        raise ValueError("script must be once, sample, or prune")
    return text


def clean_session_name(value) -> str:
    """A separate tmux namespace for each controller deployment."""
    text = str(value or SESSION_NAME).strip()
    if not _SESSION_OK.fullmatch(text):
        raise ValueError("session_name must use 1–64 letters, digits, underscores, or hyphens")
    return text


def _session_files(session: str) -> tuple[str, str]:
    session = clean_session_name(session)
    if session == SESSION_NAME:
        return _MARK, _LOG
    return f"/tmp/{session}-sample.rc", f"/tmp/{session}-sample.log"


def remote_invocation(
    session: str, cid: str, timeout_s: int, mode: str = "once",
    wait_s: int = SAMPLE_WAIT_S,
) -> str:
    """One remote shell script: open the session, run one mode, wait for it.

    The sample runs inside the tmux session, so the idle timer resets when
    the command starts and starts again when the prompt returns. The SSH
    call waits for the exit file so the local pull does not race the sample.
    """
    chosen = clean_mode(mode)
    session = clean_session_name(session)
    mark, log = _session_files(session)
    qname = shlex.quote(session)
    line = (
        f"export TMOUT={int(timeout_s)}; "
        f"UNITY_CID={shlex.quote(cid)} "
        f"bash {shlex.quote(cid + '/collector.sh')} {chosen} "
        f"> {log} 2>&1; echo $? > {mark}"
    )
    qline = shlex.quote(line)
    return "\n".join([
        f"rm -f {mark}",
        f"tmux has-session -t {qname} 2>/dev/null || tmux new-session -d -s {qname}",
        f"tmux send-keys -t {qname} {qline} Enter",
        (
            f"i=0; while [ ! -f {mark} ] && [ \"$i\" -lt {int(wait_s)} ]; "
            "do sleep 1; i=$((i+1)); done"
        ),
        f"if [ -f {mark} ]; then rc=$(cat {mark}); else rc=124; echo timeout; fi",
        'echo "rc=$rc"',
        f"echo {shlex.quote(_LOG_START)}",
        f"cat {log} 2>/dev/null || true",
        f"echo {shlex.quote(_LOG_END)}",
        f"rm -f {mark} {log}",
        f"exit \"$rc\"",
    ])


def extract_session_log(output: str) -> str:
    """The sample log the remote command printed between the markers."""
    text = str(output or "")
    if _LOG_START not in text or _LOG_END not in text:
        return ""
    _, _, rest = text.partition(_LOG_START)
    body, _, _ = rest.partition(_LOG_END)
    body = body.lstrip("\n")
    if not body.strip():
        return ""
    return body if body.endswith("\n") else body + "\n"


def save_session_log(output: str) -> str:
    """Write a remote sample log to the local session store.

    Returns the path, or empty when there was nothing to keep. A write
    fault is swallowed (I6): the pull still runs.
    """
    body = extract_session_log(output)
    if not body:
        return ""
    dest = paths.session_logs_dir()
    try:
        dest.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        path = dest / f"{stamp}.log"
        if path.exists():
            path = dest / f"{stamp}-{os.getpid()}.log"
        path.write_text(body)
        logs = sorted(p for p in dest.glob("*.log") if p.is_file())
        for old in logs[:-SESSION_LOG_KEEP]:
            try:
                old.unlink()
            except OSError:
                pass
        return str(path)
    except OSError:
        return ""


def collect(cfg: dict, source: str, mode: str = "once", access=None) -> dict:
    """Run one sample in the cluster session.

    A local source has no login node, so this is a no-op success and the
    caller pulls the fixture directly. A remote failure is `ok: False` and
    does not raise. The SSH host is the saved alias (`unity`), not the
    prefix of the rsync source.
    """
    parsed = parse_remote_source(source)
    if parsed is None:
        return {"ok": True, "skipped": "local"}
    _src_host, cid = parsed
    try:
        host = cluster_access.clean_ssh_host(cfg.get("ssh_host") or "unity")
        identity = cluster_access.clean_ssh_identity(cfg.get("ssh_identity") or "")
        session = clean_session_name(cfg.get("session_name"))
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    chosen = clean_mode(mode)
    timeout_s = inactivity_timeout_s(cfg.get("interval_minutes"))
    script = remote_invocation(session, cid, timeout_s, mode=chosen)
    if access is None:
        access = cluster_access.Ssh(host, identity)
    try:
        proc = access.run_script(script, timeout=SAMPLE_WAIT_S + 30)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    log_path = save_session_log(proc.stdout or "")
    if proc.returncode != 0:
        err = ((proc.stderr or "") + (proc.stdout or "")).strip()
        return {"ok": False, "error": err[-500:], "rc": proc.returncode,
                "session_log": log_path}
    return {
        "ok": True,
        "mode": chosen,
        "timeout_s": timeout_s,
        "session": session,
        "host": host,
        "session_log": log_path,
    }


def close_session(source: str, access=None, host: str | None = None,
                  identity: str = "", session_name: str = SESSION_NAME) -> dict:
    """End the cluster session. A missing session is already closed."""
    parsed = parse_remote_source(source)
    if parsed is None:
        return {"ok": True, "skipped": "local"}
    try:
        dest = cluster_access.clean_ssh_host(host or "unity")
        ident = cluster_access.clean_ssh_identity(identity)
        session = clean_session_name(session_name)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    qname = shlex.quote(session)
    mark, log = _session_files(session)
    script = (
        f"tmux kill-session -t {qname} 2>/dev/null || true\n"
        f"rm -f {mark} {log}\n"
    )
    if access is None:
        access = cluster_access.Ssh(dest, ident)
    try:
        proc = access.run_script(script, timeout=30)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    if proc.returncode != 0:
        err = ((proc.stderr or "") + (proc.stdout or "")).strip()
        return {"ok": False, "error": err[-500:], "rc": proc.returncode}
    return {"ok": True, "session": session, "closed": True}
