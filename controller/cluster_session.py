"""One tmux session on the login node, opened by the controller.

The session is how a scheduled sample runs. It is not a resident collector.
The shell's TMOUT is one and a half times the schedule interval, so a 30
minute schedule closes the session after 45 minutes with no command. ADR 0004.
"""

from __future__ import annotations

import shlex
import subprocess

SESSION_NAME = "unity-hpc"
#: How long one sample may run before the SSH call gives up, in seconds.
SAMPLE_WAIT_S = 600
_MIN_INTERVAL_MINUTES = 5
_MAX_INTERVAL_MINUTES = 1440
_MARK = "/tmp/unity-hpc-sample.rc"
_LOG = "/tmp/unity-hpc-sample.log"


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


def remote_invocation(session: str, cid: str, timeout_s: int, wait_s: int = SAMPLE_WAIT_S) -> str:
    """One remote shell script: open the session, run `once`, wait for it.

    The sample runs inside the tmux session, so the idle timer resets when
    the command starts and starts again when the prompt returns. The SSH
    call waits for the exit file so the local pull does not race the sample.
    """
    qname = shlex.quote(session)
    line = (
        f"export TMOUT={int(timeout_s)}; "
        f"UNITY_CID={shlex.quote(cid)} "
        f"bash {shlex.quote(cid + '/collector.sh')} once "
        f"> {_LOG} 2>&1; echo $? > {_MARK}"
    )
    qline = shlex.quote(line)
    return "\n".join([
        f"rm -f {_MARK}",
        f"tmux has-session -t {qname} 2>/dev/null || tmux new-session -d -s {qname}",
        f"tmux send-keys -t {qname} {qline} Enter",
        (
            f"i=0; while [ ! -f {_MARK} ] && [ \"$i\" -lt {int(wait_s)} ]; "
            "do sleep 1; i=$((i+1)); done"
        ),
        f"if [ ! -f {_MARK} ]; then echo timeout; exit 124; fi",
        f"rc=$(cat {_MARK}); echo rc=$rc; exit \"$rc\"",
    ])


def ssh_run(host: str, script: str, timeout_s: int) -> subprocess.CompletedProcess:
    """Run `script` on `host`. BatchMode so a missing key fails instead of asking."""
    return subprocess.run(
        [
            "timeout", "--foreground", str(int(timeout_s)),
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            host, "bash", "-s",
        ],
        input=script,
        capture_output=True,
        text=True,
    )


def collect(cfg: dict, source: str, run=None) -> dict:
    """Run one sample in the cluster session.

    A local source has no login node, so this is a no-op success and the
    caller pulls the fixture directly. A remote failure is `ok: False` and
    does not raise.
    """
    parsed = parse_remote_source(source)
    if parsed is None:
        return {"ok": True, "skipped": "local"}
    host, cid = parsed
    timeout_s = inactivity_timeout_s(cfg.get("interval_minutes"))
    script = remote_invocation(SESSION_NAME, cid, timeout_s)
    runner = run or ssh_run
    try:
        proc = runner(host, script, SAMPLE_WAIT_S + 30)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    if proc.returncode != 0:
        err = ((proc.stderr or "") + (proc.stdout or "")).strip()
        return {"ok": False, "error": err[-500:], "rc": proc.returncode}
    return {
        "ok": True,
        "timeout_s": timeout_s,
        "session": SESSION_NAME,
        "host": host,
    }
