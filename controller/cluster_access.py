"""Cluster access: how the controller reaches the login node.

One SSH alias and identity, the agent that holds the unlocked key, a bounded
remote command, and file transfer. Two transports share one shape: `Ssh`
(OpenSSH and rsync) and `LocalShell` (this machine's bash and rsync, for
tests). Each command line equals the one the controller sent before this
module existed; ARCHITECTURE.md, "Cluster access", says why the variants stay.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Protocol, Sequence

#: Every unattended ssh: never prompt, bound the connect, notice a dead link.
SSH_OPTIONS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3")
#: The panel's SSH test is a 15 second echo; it has never set keep-alive.
_CONNECT_OPTIONS = SSH_OPTIONS[:4]
#: How long the panel's SSH test may run.
PROBE_WAIT_S = 15
#: How long one rsync transfer may run.
TRANSFER_WAIT_S = 300


class Transport(Protocol):
    """What the Slurm protocol and the Cluster session need from the cluster."""
    def run(self, command: str, *, timeout: float, input: str | None = None) -> subprocess.CompletedProcess: ...
    def run_script(self, script: str, *, timeout: int) -> subprocess.CompletedProcess: ...
    def transfer(self, local, remote: str, *, pull: bool = False, include: Sequence[str] = ()) -> subprocess.CompletedProcess: ...


def _ssh_words(identity: str, options=SSH_OPTIONS, *, identity_first: bool = True) -> list[str]:
    """`ssh`, the pinned identity, and the options; the host and command follow."""
    pinned = ["-i", identity] if identity else []
    return ["ssh", *pinned, *options] if identity_first else ["ssh", *options, *pinned]


def _rsync_words(include: Sequence[str]) -> list[str]:
    filters: list[str] = []
    if include:
        for pattern in include:
            filters.extend(["--include", pattern])
        filters.extend(["--exclude", "*"])
    return ["rsync", "-a", "--safe-links", "--protect-args", *filters]


def ssh_argv(host, identity="") -> list[str]:
    return [*_ssh_words(clean_ssh_identity(identity), ()), clean_ssh_host(host)]


def rsync_rsh(identity: str) -> str:
    """The `ssh` command that the telemetry pull's rsync and remote prune use."""
    ident = clean_ssh_identity(identity)
    return shlex.join(_ssh_words(str(Path(ident).expanduser()) if ident else ""))


_HOST_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_restore_lock = threading.Lock()
_last_restore_attempt: dict[str, float] = {}
_RESTORE_RETRY_S = 30


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


def ssh_command(host: str, identity: str = "") -> str:
    """The same command a person would type, for the panel to show."""
    return " ".join(ssh_argv(host, identity))


def _ssh_config(host: str) -> tuple[str, dict[str, str]]:
    """The first existing identity file and the agent selected by the alias."""
    env = dict(os.environ)
    try:
        proc = subprocess.run(
            ["ssh", "-G", clean_ssh_host(host)],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "", env
    key = ""
    agent_seen = False
    for line in proc.stdout.splitlines():
        if not key and line.lower().startswith("identityfile "):
            path = str(Path(line.split(" ", 1)[1].strip()).expanduser())
            if Path(path).is_file():
                key = path
        if not agent_seen and line.lower().startswith("identityagent "):
            agent_seen = True
            socket = line.split(" ", 1)[1].strip()
            if socket.startswith("/") or socket.startswith("~/"):
                env["SSH_AUTH_SOCK"] = str(Path(socket).expanduser())
    return key, env


def _first_fp(text: str) -> str:
    for part in str(text or "").split():
        if part.startswith("SHA256:"):
            return part
    return ""


def identity_status(host: str, identity: str = "") -> dict:
    """Whether the alias key is loaded. A missing load is a passphrase prompt."""
    key, env = _ssh_config(host)
    ident = clean_ssh_identity(identity)
    path = str(Path(ident).expanduser()) if ident else key
    exists = bool(path) and Path(path).is_file()
    empty = {
        "key_path": path, "unlocked": False,
        "needs_passphrase": False, "agent": False,
    }
    try:
        listed = subprocess.run(["ssh-add", "-l"], capture_output=True, text=True, env=env)
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
            shown = subprocess.run(["ssh-keygen", "-l", "-f", path], capture_output=True, text=True)
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


def restore_identity(host: str, identity: str = "") -> dict:
    """Load a remembered key after an agent or controller restart."""
    with _restore_lock:
        status = identity_status(host, identity)
        if status["unlocked"]:
            return status
        path = status["key_path"]
        if not path or not Path(path).is_file() or not keyring_unlocked():
            return status
        fingerprint = _identity_fingerprint(path)
        if not fingerprint:
            return status
        now = time.monotonic()
        if now - _last_restore_attempt.get(fingerprint, float("-inf")) < _RESTORE_RETRY_S:
            return status
        _last_restore_attempt[fingerprint] = now
        phrase = _keyring_lookup(fingerprint)
        if not phrase:
            return status
        if not unlock_identity(path, phrase, host=host, remember=False).get("ok"):
            return status
        return identity_status(host, identity)


def unlock_identity(identity: str, passphrase: str, host: str = "unity",
                    remember: bool = True) -> dict:
    """Load the key into the agent. The passphrase is never returned."""
    phrase = str(passphrase or "").split("\n", 1)[0].strip("\r")
    if not phrase:
        raise ValueError("passphrase is empty")
    if "\x00" in phrase:
        raise ValueError("passphrase is invalid")
    ident = clean_ssh_identity(identity)
    if ident:
        path = str(Path(ident).expanduser())
        if not Path(path).is_file():
            return {"ok": False, "error": "identity file is missing",
                    "key_path": path, "unlocked": False}
        env = _ssh_config(host)[1]
    else:
        path, env = _ssh_config(host)
        if not path or not Path(path).is_file():
            return {"ok": False, "error": "identity file is missing",
                    "key_path": path or "", "unlocked": False}
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


class Ssh:
    """Production transport through one alias and identity.

    The Slurm protocol's commands and transfers put the options before `-i`
    and use the agent socket that the alias names. The Cluster session's
    scripts put `-i` first and inherit this process's environment. Both forms
    are kept so that no command line changed; reorder only after a live check.
    """

    def __init__(self, host, identity=""):
        self.host = clean_ssh_host(host)
        self.identity = clean_ssh_identity(identity)
        self._env = None

    def _agent(self):
        if self._env is None:
            self._env = _ssh_config(self.host)[1]
        return self._env

    def run(self, command, *, timeout, input=None):
        return subprocess.run([*_ssh_words(self.identity, identity_first=False), self.host, command],
                              input=input, capture_output=True, text=True, timeout=timeout, env=self._agent())

    def run_script(self, script, *, timeout):
        return subprocess.run(["timeout", "--foreground", str(int(timeout)), *_ssh_words(self.identity), self.host, "bash", "-s"],
                              input=script, capture_output=True, text=True)

    def transfer(self, local, remote, *, pull=False, include=()):
        remote_spec = self.host + ":" + remote
        endpoints = [remote_spec, str(local)] if pull else [str(local), remote_spec]
        return subprocess.run([*_rsync_words(include), "-e", shlex.join(_ssh_words(self.identity, identity_first=False)), *endpoints],
                              capture_output=True, text=True, timeout=TRANSFER_WAIT_S, env=self._agent())


class LocalShell:
    """Test transport: the login node is this machine (see the module docstring)."""

    def __init__(self, path=()):
        self.path = [str(p) for p in path]

    def _env(self):
        if not self.path:
            return None
        return {**os.environ, "PATH": os.pathsep.join([*self.path, os.environ.get("PATH", "")])}

    def run(self, command, *, timeout, input=None):
        return subprocess.run(["bash", "-c", command], input=input, capture_output=True, text=True, timeout=timeout, env=self._env())

    def run_script(self, script, *, timeout):
        return subprocess.run(["timeout", "--foreground", str(int(timeout)), "bash", "-s"], input=script, capture_output=True, text=True, env=self._env())

    def transfer(self, local, remote, *, pull=False, include=()):
        endpoints = [remote, str(local)] if pull else [str(local), remote]
        return subprocess.run([*_rsync_words(include), *endpoints], capture_output=True, text=True, timeout=TRANSFER_WAIT_S, env=self._env())


def check_access(host: str, identity: str = "") -> dict:
    """One `echo` on the alias, so the panel can test the saved access."""
    dest = clean_ssh_host(host)
    ident = clean_ssh_identity(identity)
    argv = [
        "timeout", "--foreground", str(PROBE_WAIT_S),
        *_ssh_words(ident, _CONNECT_OPTIONS), dest,
        "echo", "unity-ok",
    ]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True)
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
