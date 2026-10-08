"""One tmux session on the login node, opened by the controller.

The session is how a scheduled sample runs. It is not a resident collector.
The shell's TMOUT is one and a half times the schedule interval, so a 30
minute schedule closes the session after 45 minutes with no command. ADR 0004.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from lib import paths

SESSION_NAME = "unity-hpc"
#: Scripts the panel and the schedule may run. `loop` stays manual.
MODES = ("once", "sample", "prune")
#: How long one sample may run before the SSH call gives up, in seconds.
SAMPLE_WAIT_S = 600
#: How long a panel "Test ssh" probe may run.
PROBE_WAIT_S = 15
_MIN_INTERVAL_MINUTES = 5
_MAX_INTERVAL_MINUTES = 1440
_MARK = "/tmp/unity-hpc-sample.rc"
_LOG = "/tmp/unity-hpc-sample.log"
_LOG_START = "--- unity-hpc-session-log ---"
_LOG_END = "--- unity-hpc-session-log-end ---"
SESSION_LOG_KEEP = 50
#: An SSH config Host alias. No user@host, no options, no spaces.
_HOST_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SESSION_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_restore_lock = threading.Lock()
_last_restore_attempt: dict[str, float] = {}
_RESTORE_RETRY_S = 30


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


def clean_ssh_host(value) -> str:
    """An SSH config alias such as `unity`. Empty becomes the default."""
    text = str(value or "").strip()
    if not text:
        return "unity"
    if len(text) > 64 or not _HOST_OK.fullmatch(text):
        raise ValueError("ssh_host must be an SSH config alias")
    return text


def clean_ssh_identity(value) -> str:
    """A path to an identity file, or empty to use the SSH config as written."""
    text = str(value or "").strip()
    if not text:
        return ""
    if any(ch in text for ch in "\n\r\t\0"):
        raise ValueError("ssh_identity must be one line")
    if len(text) > 512:
        raise ValueError("ssh_identity is too long")
    return text


def ssh_argv(host: str, identity: str = "") -> list[str]:
    """The ssh invocation. The host is an SSH config alias (e.g. `unity`).

    Use the configured alias and its SSH settings. Command-line -o options
    override individual config values; they do not bypass ~/.ssh/config.
    """
    dest = clean_ssh_host(host)
    ident = clean_ssh_identity(identity)
    cmd = ["ssh"]
    if ident:
        cmd.extend(["-i", ident])
    cmd.append(dest)
    return cmd


def ssh_command(host: str, identity: str = "") -> str:
    """The same command a person would type, for the panel to show."""
    return " ".join(ssh_argv(host, identity))


def resolve_identity(host: str, identity: str = "") -> str:
    """The key file `ssh <alias>` will use. Empty when none can be named."""
    ident = clean_ssh_identity(identity)
    if ident:
        return str(Path(ident).expanduser())
    try:
        proc = subprocess.run(
            ["ssh", "-G", clean_ssh_host(host)],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    for line in proc.stdout.splitlines():
        if not line.lower().startswith("identityfile "):
            continue
        path = str(Path(line.split(" ", 1)[1].strip()).expanduser())
        if Path(path).is_file():
            return path
    return ""


def _first_fp(text: str) -> str:
    for part in str(text or "").split():
        if part.startswith("SHA256:"):
            return part
    return ""


def _run(argv, run=None, **kwargs):
    if run is not None:
        return run(argv, **kwargs)
    return subprocess.run(argv, capture_output=True, text=True, **kwargs)


def _agent_env(host: str) -> dict[str, str]:
    """Use the socket selected by SSH's Host entry when it names one."""
    env = dict(os.environ)
    try:
        proc = subprocess.run(
            ["ssh", "-G", clean_ssh_host(host)],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return env
    for line in proc.stdout.splitlines():
        if line.lower().startswith("identityagent "):
            socket = line.split(" ", 1)[1].strip()
            if socket.startswith("/") or socket.startswith("~/"):
                env["SSH_AUTH_SOCK"] = str(Path(socket).expanduser())
            break
    return env


def agent_status(host: str, identity: str = "", run=None) -> dict:
    """Whether the alias key is loaded. A missing load is a passphrase prompt."""
    path = resolve_identity(host, identity) if identity else (
        resolve_identity(host, identity) if run is None else ""
    )
    if identity:
        path = str(Path(clean_ssh_identity(identity)).expanduser())
    exists = bool(path) and Path(path).is_file()
    empty = {
        "key_path": path, "unlocked": False,
        "needs_passphrase": False, "agent": False,
    }
    try:
        listed = _run(["ssh-add", "-l"], run=run,
                      env=_agent_env(host) if run is None else None)
    except OSError:
        empty["needs_passphrase"] = exists
        return empty
    agent = listed.returncode in (0, 1)
    loaded = set()
    if listed.returncode == 0:
        for line in (listed.stdout or "").splitlines():
            fp = _first_fp(line)
            if fp:
                loaded.add(fp)
    unlocked = False
    if exists and loaded:
        try:
            shown = _run(["ssh-keygen", "-l", "-f", path], run=run)
            key_fp = _first_fp(shown.stdout or "")
            unlocked = bool(key_fp) and key_fp in loaded
        except OSError:
            unlocked = False
    return {
        "key_path": path,
        "unlocked": unlocked,
        "needs_passphrase": exists and not unlocked,
        "agent": agent,
    }


def _wipe(path: str) -> None:
    try:
        size = os.path.getsize(path)
        with open(path, "r+b") as fh:
            fh.write(b"\0" * size)
            fh.flush()
            os.fsync(fh.fileno())
        os.unlink(path)
    except OSError:
        pass


def _ensure_agent(env: dict[str, str] | None = None) -> bool:
    """Reuse an agent, including an empty one; start one only if absent."""
    env = env if env is not None else os.environ
    try:
        listed = subprocess.run(
            ["ssh-add", "-l"], capture_output=True, text=True, timeout=5,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        listed = None
    # ssh-add returns 1 when the agent is healthy but contains no keys.
    if listed is not None and listed.returncode in (0, 1):
        return True
    # An explicit IdentityAgent cannot be replaced with a private process.
    if env.get("SSH_AUTH_SOCK") and env is not os.environ:
        return False
    try:
        proc = subprocess.run(
            ["ssh-agent", "-s"], capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    for line in (proc.stdout or "").splitlines():
        if line.startswith("SSH_AUTH_SOCK="):
            env["SSH_AUTH_SOCK"] = line.split("=", 1)[1].split(";")[0]
        elif line.startswith("SSH_AGENT_PID="):
            env["SSH_AGENT_PID"] = line.split("=", 1)[1].split(";")[0]
    if env is not os.environ:
        os.environ.update({k: env[k] for k in ("SSH_AUTH_SOCK", "SSH_AGENT_PID") if k in env})
    return bool(env.get("SSH_AUTH_SOCK"))


def _identity_fingerprint(path: str) -> str:
    try:
        proc = subprocess.run(
            ["ssh-keygen", "-l", "-f", path],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return _first_fp(proc.stdout) if proc.returncode == 0 else ""


def _keyring_args(fingerprint: str) -> list[str]:
    # libsecret attributes are not encrypted, so they identify only a public key.
    return ["application", "unity-hpc", "ssh-key-fingerprint", fingerprint]


def keyring_unlocked() -> bool:
    """Do not let an unattended lookup open a desktop unlock prompt."""
    try:
        proc = subprocess.run([
            "busctl", "--user", "get-property", "org.freedesktop.secrets",
            "/org/freedesktop/secrets/aliases/default",
            "org.freedesktop.Secret.Collection", "Locked",
        ], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and proc.stdout.strip() == "b false"


def _keyring_lookup(fingerprint: str) -> str:
    try:
        proc = subprocess.run(
            ["secret-tool", "lookup", *_keyring_args(fingerprint)],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout.rstrip("\n") if proc.returncode == 0 else ""


def _keyring_store(fingerprint: str, passphrase: str) -> bool:
    if not keyring_unlocked():
        return False
    try:
        proc = subprocess.run(
            ["secret-tool", "store", "--label=Unity HPC SSH key",
             *_keyring_args(fingerprint)],
            input=passphrase, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def restore_identity(host: str, identity: str = "") -> bool:
    """Load a remembered key after an agent or controller restart."""
    with _restore_lock:
        if agent_status(host, identity)["unlocked"]:
            return True
        path = resolve_identity(host, identity)
        if not path or not Path(path).is_file() or not keyring_unlocked():
            return False
        fingerprint = _identity_fingerprint(path)
        if not fingerprint:
            return False
        now = time.monotonic()
        if now - _last_restore_attempt.get(fingerprint, float("-inf")) < _RESTORE_RETRY_S:
            return False
        _last_restore_attempt[fingerprint] = now
        phrase = _keyring_lookup(fingerprint)
        if not phrase:
            return False
        return bool(unlock_identity(path, phrase, host=host, remember=False).get("ok"))


def unlock_identity(identity: str, passphrase: str, host: str = "unity",
                    run=None, remember: bool = True) -> dict:
    """Load the key into the agent. The passphrase is never returned."""
    phrase = str(passphrase or "").split("\n", 1)[0].strip("\r")
    if not phrase:
        raise ValueError("passphrase is empty")
    if "\x00" in phrase:
        raise ValueError("passphrase is invalid")
    path = resolve_identity(host, identity)
    if not path or not Path(path).is_file():
        return {"ok": False, "error": "identity file is missing",
                "key_path": path or "", "unlocked": False}
    if run is not None:
        proc = run(["ssh-add", path], env={})
        ok = getattr(proc, "returncode", 1) == 0
        return {"ok": ok, "key_path": path, "unlocked": ok,
                "output": ((getattr(proc, "stdout", "") or "")
                           + (getattr(proc, "stderr", "") or "")).strip()[-300:]}
    env = _agent_env(host)
    if not _ensure_agent(env):
        return {"ok": False, "error": "configured SSH agent is unavailable",
                "key_path": path, "unlocked": False}
    secret = None
    helper = None
    try:
        memory_dir = "/dev/shm" if Path("/dev/shm").is_dir() else None
        fd, secret = tempfile.mkstemp(prefix="unity-askpass-", dir=memory_dir)
        os.write(fd, phrase.encode())
        os.close(fd)
        os.chmod(secret, 0o600)
        fd, helper = tempfile.mkstemp(prefix="unity-askpass-sh-")
        os.write(fd, (
            b"#!/bin/sh\n"
            b"case \"$*\" in\n"
            b"  *[Bb]ad*|*try\\ again*) exit 1 ;;\n"
            b"esac\n"
            b"cat \"$UNITY_HPC_ASKPASS_FILE\"\n"
        ))
        os.close(fd)
        os.chmod(helper, 0o700)
        env["UNITY_HPC_ASKPASS_FILE"] = secret
        env["SSH_ASKPASS"] = helper
        env["SSH_ASKPASS_REQUIRE"] = "force"
        env.setdefault("DISPLAY", ":0")
        proc = subprocess.run(
            ["ssh-add", path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            timeout=15,
            start_new_session=True,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc), "key_path": path,
                "unlocked": False}
    finally:
        if secret:
            _wipe(secret)
        if helper:
            try:
                os.unlink(helper)
            except OSError:
                pass
    ok = proc.returncode == 0
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if not ok and not out:
        out = "bad passphrase or the agent refused the key"
    remembered = False
    if ok and remember:
        fingerprint = _identity_fingerprint(path)
        remembered = bool(fingerprint) and _keyring_store(fingerprint, phrase)
        if fingerprint:
            _last_restore_attempt.pop(fingerprint, None)
    return {
        "ok": ok,
        "key_path": path,
        "unlocked": ok,
        "remembered": remembered,
        "output": out[-300:],
    }


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


def ssh_run(host: str, script: str, timeout_s: int,
            identity: str = "") -> subprocess.CompletedProcess:
    """Run an unattended command through the configured alias and key."""
    return subprocess.run(
        [
            "timeout", "--foreground", str(int(timeout_s)),
            *ssh_argv(host, identity)[:-1],
            "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3",
            clean_ssh_host(host),
            "bash", "-s",
        ],
        input=script,
        capture_output=True,
        text=True,
    )


def probe(host: str, identity: str = "", run=None) -> dict:
    """One `echo` on the alias, so the panel can test the saved access."""
    dest = clean_ssh_host(host)
    ident = clean_ssh_identity(identity)
    argv = [
        "timeout", "--foreground", str(PROBE_WAIT_S),
        *ssh_argv(dest, ident)[:-1],
        "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", dest,
        "echo", "unity-ok",
    ]
    runner = run or (lambda cmd: subprocess.run(
        cmd, capture_output=True, text=True,
    ))
    try:
        proc = runner(argv)
    except OSError as exc:
        return {
            "ok": False, "command": ssh_command(dest, ident),
            "error": str(exc), "output": str(exc), "rc": -1,
        }
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    ok = proc.returncode == 0 and "unity-ok" in (proc.stdout or "")
    return {
        "ok": ok,
        "command": ssh_command(dest, ident),
        "output": out[-500:],
        "rc": proc.returncode,
    }


def collect(cfg: dict, source: str, mode: str = "once", run=None) -> dict:
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
        host = clean_ssh_host(cfg.get("ssh_host") or "unity")
        identity = clean_ssh_identity(cfg.get("ssh_identity") or "")
        session = clean_session_name(cfg.get("session_name"))
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    chosen = clean_mode(mode)
    timeout_s = inactivity_timeout_s(cfg.get("interval_minutes"))
    script = remote_invocation(session, cid, timeout_s, mode=chosen)
    runner = run or (lambda h, s, t: ssh_run(h, s, t, identity=identity))
    try:
        proc = runner(host, script, SAMPLE_WAIT_S + 30)
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


def close_session(source: str, run=None, host: str | None = None,
                  identity: str = "", session_name: str = SESSION_NAME) -> dict:
    """End the cluster session. A missing session is already closed."""
    parsed = parse_remote_source(source)
    if parsed is None:
        return {"ok": True, "skipped": "local"}
    try:
        dest = clean_ssh_host(host or "unity")
        ident = clean_ssh_identity(identity)
        session = clean_session_name(session_name)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    qname = shlex.quote(session)
    mark, log = _session_files(session)
    script = (
        f"tmux kill-session -t {qname} 2>/dev/null || true\n"
        f"rm -f {mark} {log}\n"
    )
    runner = run or (lambda h, s, t: ssh_run(h, s, t, identity=ident))
    try:
        proc = runner(dest, script, 30)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    if proc.returncode != 0:
        err = ((proc.stderr or "") + (proc.stdout or "")).strip()
        return {"ok": False, "error": err[-500:], "rc": proc.returncode}
    return {"ok": True, "session": session, "closed": True}
