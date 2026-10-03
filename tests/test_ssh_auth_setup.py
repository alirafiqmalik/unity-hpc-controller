"""The one-time SSH setup changes only the selected Host block."""

import runpy
from pathlib import Path

import pytest


_setup = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                            "scripts" / "hpc-ssh-auth-setup"))
with_agent_config = _setup["with_agent_config"]


def test_setup_keeps_other_hosts_and_is_idempotent():
    original = (
        "Host other\n  IdentityFile ~/.ssh/other\n"
        "Host unity\n  HostName login.example.edu\n"
        "  ForwardAgent yes\n  IdentityFile ~/.ssh/unity\n"
        "Host archive\n  HostName archive.example.edu\n"
    )
    socket = "/run/user/1000/ssh-agent.socket"
    updated = with_agent_config(original, "unity", socket)
    assert "Host other\n  IdentityFile ~/.ssh/other\n" in updated
    assert "Host archive\n  HostName archive.example.edu\n" in updated
    assert "  IdentityAgent /run/user/1000/ssh-agent.socket\n" in updated
    assert "  ForwardAgent no\n" in updated
    assert "  ForwardAgent yes\n" not in updated
    assert updated == with_agent_config(updated, "unity", socket)


def test_setup_refuses_ambiguous_alias():
    with pytest.raises(ValueError, match="one exact"):
        with_agent_config("Host unity\nHost unity\n", "unity", "/tmp/agent")
