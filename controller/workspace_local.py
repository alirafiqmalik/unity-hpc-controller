"""Durable receipts for controller-host stages, without scheduler identities."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile


def receipt_paths(root: Path, attempt_id: str):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", attempt_id):
        raise ValueError("invalid local attempt identity")
    directory = root / ".unity-workspace" / "receipts"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / (attempt_id + ".json"), directory / (attempt_id + ".lock")


def _write(path: Path, result: dict):
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(result, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def interrupted_receipt(root: Path, attempt_id: str):
    """Return completion, keep live work running, or fence an unstarted attempt.

    The same lock guards both the supervisor and this restart probe. A failure
    receipt written before a delayed supervisor starts prevents it from running.
    The scientific child inherits the lock so supervisor death alone does not
    make a still-running operation appear safe to retry.
    """
    receipt, lock_path = receipt_paths(root, attempt_id)
    with lock_path.open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return None
        if receipt.exists():
            try:
                result = json.loads(receipt.read_text())
                if not isinstance(result.get("ok"), bool) or not isinstance(result.get("returncode"), int):
                    raise ValueError("invalid receipt")
                return result
            except (ValueError, OSError, TypeError):
                result = {"ok": False, "returncode": 125, "output": "", "error": "Local completion receipt is invalid; inspect saved outputs before recovery"}
        else:
            result = {"ok": False, "returncode": 125, "output": "", "interrupted": True,
                      "error": "Controller-host attempt was interrupted without a completion receipt; review saved outputs before recovery"}
        _write(receipt, result)
        return result


def supervise(root: Path, attempt_id: str, command: list[str]):
    receipt, lock_path = receipt_paths(root, attempt_id)
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if receipt.exists():
            result = json.loads(receipt.read_text())
        else:
            try:
                stdout_path = receipt.with_suffix('.stdout')
                stderr_path = receipt.with_suffix('.stderr')
                with stdout_path.open('wb') as stdout, stderr_path.open('wb') as stderr:
                    process = subprocess.Popen(command, cwd=root, stdout=stdout, stderr=stderr,
                                               pass_fds=(lock.fileno(),))
                    process_file = receipt.with_suffix('.process.json')
                    _write(process_file, {"pid": process.pid, "pgid": os.getpgid(process.pid),
                                          "start_token": _process_token(process.pid), "attempt_id": attempt_id})
                    returncode = process.wait()
                def tail(path):
                    with path.open('rb') as stream:
                        stream.seek(max(0, path.stat().st_size - 50000))
                        return stream.read(50000).decode(errors='replace')
                result = {"ok": returncode == 0, "returncode": returncode,
                          "output": tail(stdout_path) + tail(stderr_path)}
            except Exception as exc:
                result = {"ok": False, "returncode": 125, "output": "", "error": str(exc)}
            _write(receipt, result)
    try:
        sys.stdout.write(result.get("output", ""))
        if result.get("error"):
            sys.stderr.write(result["error"] + "\n")
    except BrokenPipeError:
        # The controller may have restarted; the durable receipt is authoritative.
        pass
    return result["returncode"] if 0 <= result["returncode"] <= 255 else 125


def _process_token(pid):
    # Linux start ticks prevent PID reuse from authorizing an unrelated signal.
    return Path(f'/proc/{int(pid)}/stat').read_text().rsplit(')', 1)[1].split()[19]


def cancel(root, attempt_id):
    receipt, _ = receipt_paths(Path(root), attempt_id)
    if receipt.exists():
        return {"state": "skipped", "reason": "Already terminal"}
    path = receipt.with_suffix('.process.json')
    if not path.is_file():
        return {"state": "uncertain", "reason": "Process ownership is not yet observable; dependent work is fenced"}
    try:
        record = json.loads(path.read_text())
        pid, group = int(record['pid']), int(record['pgid'])
        if record.get('attempt_id') != attempt_id or _process_token(pid) != record['start_token'] or os.getpgid(pid) != group or group == os.getpgrp():
            return {"state": "uncertain", "reason": "Process ownership changed; no signal was sent"}
        os.killpg(group, signal.SIGTERM)
        return {"state": "accepted", "reason": "Cancellation requested; waiting for terminal receipt"}
    except (OSError, ValueError, KeyError):
        return {"state": "uncertain", "reason": "Process exited or ownership could not be confirmed; reconcile its receipt"}


if __name__ == "__main__":
    raise SystemExit(supervise(Path(sys.argv[1]), sys.argv[2], json.loads(sys.argv[3])))
