"""hpc-tmux must not let a session name reach the remote shell as syntax.

A session name is interpolated into the single remote-command string that ssh
sends, so `kill 'safe;rm -rf ~'` would run on the shared login node. The name is
gated by an allowlist; the session command stays arbitrary but quoted.

Driven against a stub `ssh` on PATH, in the shape tests/test_dispatcher_ledger.py
uses.
"""

import os
import shlex
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "hpc-tmux"

STUB_SSH = r"""#!/usr/bin/env bash
# stub ssh: last argument is the remote command
cmd="${!#}"
echo "$cmd" >>"$STUB_LOG"
case "$cmd" in
    *has-session*) echo started ;;
    *)             exit 0 ;;
esac
"""

STUB_TIMEOUT = r"""#!/usr/bin/env bash
# stub timeout: drop the duration, run the rest
shift
exec "$@"
"""


@pytest.fixture
def run_tmux(tmp_path):
    """hpc-tmux driven against a stub ssh that logs each remote command."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("ssh", STUB_SSH), ("timeout", STUB_TIMEOUT)):
        p = bin_dir / name
        p.write_text(body)
        p.chmod(0o755)

    log = tmp_path / "stub.log"
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["STUB_LOG"] = str(log)
    # Pin the project dir, so the script cannot source a stray .env from cwd.
    env["HPC_PROJECT_DIR"] = str(tmp_path)

    def run(*args):
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            capture_output=True, text=True, env=env, cwd=str(tmp_path),
        )

    run.log = log
    return run


def test_rejects_shell_metacharacters_in_session_name(run_tmux):
    result = run_tmux("kill", "safe;touch /tmp/pwned")
    assert result.returncode == 2
    assert "invalid session name" in result.stderr
    # Rejected before ssh is reached, not merely mangled on the way through.
    assert not run_tmux.log.exists()


@pytest.mark.parametrize("name", ["-rf", ".hidden", "a" * 65])
def test_rejects_the_same_names_the_dispatcher_rejects(run_tmux, name):
    result = run_tmux("kill", name)
    assert result.returncode == 2
    assert not run_tmux.log.exists()


def test_an_arbitrary_command_reaches_the_remote_shell_as_one_argument(run_tmux):
    result = run_tmux("start", "research_1", "python train.py --name 'a b'")
    assert result.returncode == 0
    # Assert the argv the remote shell would build, not the escaping style: the
    # property is "one argument, unchanged", whatever quoting produced it.
    argv = shlex.split(run_tmux.log.read_text().strip())
    assert argv[:5] == ["tmux", "has-session", "-t", "research_1", "2>/dev/null"]
    assert "python train.py --name 'a b'" in argv


def test_start_uses_one_ssh_round_trip(run_tmux):
    """The login node is shared — probe and create go in one connection."""
    result = run_tmux("start", "research_1")
    assert result.returncode == 0
    assert len(run_tmux.log.read_text().splitlines()) == 1
