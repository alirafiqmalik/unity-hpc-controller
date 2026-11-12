import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """A fresh $UNITY_HPC_DATA with a locks/ subdir. Readers resolve it at call time."""
    d = tmp_path / "data"
    (d / "locks").mkdir(parents=True)
    monkeypatch.setenv("UNITY_HPC_DATA", str(d))
    return d


import json
import os


_RECORDER = r'''
import json
import os
import subprocess
import sys
from pathlib import Path

d = Path(os.environ["UNITY_TEST_TOOLS"])
name, args = sys.argv[1], sys.argv[2:]
config = json.loads((d / "config.json").read_text())
key = f"{name} {args[0]}" if args and f"{name} {args[0]}" in config else name
replies = config.get(key, [{"rc": 0}])
counter = d / ("count-" + key.replace(" ", "_"))
i = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(i + 1))
reply = replies[min(i, len(replies) - 1)]
stdin = "" if os.isatty(0) else sys.stdin.read()
needle = (d / "forbidden-in-env").read_text() if (d / "forbidden-in-env").exists() else ""
leaks = sorted(key for key, value in os.environ.items() if needle and needle in value)
askpass = ""
if name == "ssh-add" and args and args[0] != "-l" and os.environ.get("SSH_ASKPASS"):
    askpass = subprocess.run([os.environ["SSH_ASKPASS"], "Enter passphrase for key:"], capture_output=True, text=True).stdout
record = {"argv": [name, *args], "stdin": stdin,
          "env": {k: os.environ[k] for k in ("SSH_AUTH_SOCK", "SSH_AGENT_PID", "SSH_ASKPASS", "SSH_ASKPASS_REQUIRE", "DISPLAY", "UNITY_HPC_ASKPASS_FILE", "RSYNC_RSH") if k in os.environ},
          "askpass": askpass, "env_leaks": leaks}
with (d / "calls.jsonl").open("a") as log:
    log.write(json.dumps(record) + "\n")
sys.stdout.write(reply.get("stdout", ""))
sys.stderr.write(reply.get("stderr", ""))
sys.exit(reply.get("rc", 0))
'''


class SshTools:
    def __init__(self, directory):
        self.directory = directory
        (directory / "recorder.py").write_text(_RECORDER)
        self.config = {}

    def respond(self, key, *replies):
        self.config[key] = list(replies)
        (self.directory / "config.json").write_text(json.dumps(self.config))
        (self.directory / ("count-" + key.replace(" ", "_"))).unlink(missing_ok=True)

    def record(self, *names):
        for name in names:
            stub = self.directory / name
            stub.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{self.directory}/recorder.py" "{name}" "$@"\n')
            stub.chmod(0o755)

    def forbid_in_env(self, text):
        """Every later tool call reports the names of environment variables that hold this text."""
        (self.directory / "forbidden-in-env").write_text(text)

    def calls(self):
        log = self.directory / "calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def clear(self):
        (self.directory / "calls.jsonl").unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def ssh_tools(tmp_path_factory, monkeypatch):
    d = tmp_path_factory.mktemp("ssh-tools")
    handle = SshTools(d)
    defaults = {
        "ssh -G": {"rc": 0},
        "ssh": {"rc": 255, "stderr": "ssh: no cluster in tests\n"},
        "ssh-add": {"rc": 2, "stderr": "Could not open a connection to your authentication agent.\n"},
        "ssh-keygen": {"rc": 1}, "ssh-agent": {"rc": 1},
        "busctl": {"rc": 1}, "secret-tool": {"rc": 1},
    }
    for key, reply in defaults.items():
        handle.respond(key, reply)
    handle.record("ssh", "ssh-add", "ssh-keygen", "ssh-agent", "busctl", "secret-tool")
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("UNITY_TEST_TOOLS", str(d))
    return handle
