"""Cluster access through stubbed identity tools and a local shell."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from controller import cluster_access


def test_ssh_argv_is_the_config_alias_with_no_extra_options():
    """The panel and the schedule run `ssh unity`, the same command a shell does.

    Per-call options may override individual settings, but retain the Host
    entry's hostname, user, key, and agent selection.
    """
    assert cluster_access.ssh_argv("unity") == ["ssh", "unity"]
    assert "BatchMode" not in cluster_access.ssh_argv("unity")
    assert cluster_access.ssh_command("unity") == "ssh unity"


def test_ssh_argv_can_pin_an_identity_file():
    assert cluster_access.ssh_argv("unity", "~/.ssh/cluster") == [
        "ssh", "-i", "~/.ssh/cluster", "unity",
    ]


def test_ssh_host_must_be_an_alias():
    try:
        cluster_access.clean_ssh_host("user@login.example.edu")
    except ValueError as exc:
        assert "alias" in str(exc)
    else:
        raise AssertionError("a user@host value was accepted")
    assert cluster_access.clean_ssh_host("") == "unity"
    assert cluster_access.clean_ssh_host("unity") == "unity"


def test_unlock_refuses_an_empty_passphrase(tmp_path):
    key = tmp_path / "cluster"
    key.write_text("dummy-key\n")
    try:
        cluster_access.unlock_identity(str(key), "")
    except ValueError as exc:
        assert "empty" in str(exc)
    else:
        raise AssertionError("an empty passphrase was accepted")


@pytest.fixture
def key(tmp_path):
    key = tmp_path / "cluster"
    key.write_text("dummy-key\n")
    return key


def argv(ssh_tools):
    return [c["argv"] for c in ssh_tools.calls()]


def prepare_unlock(ssh_tools, fingerprint):
    ssh_tools.respond("ssh-add -l", {"rc": 1})
    ssh_tools.respond("ssh-add", {"stdout": "Identity added\n"})
    ssh_tools.respond("ssh-keygen", {"stdout": f"256 {fingerprint} cluster (ED25519)\n"})
    ssh_tools.respond("busctl", {"stdout": "b false\n"})
    ssh_tools.respond("secret-tool store", {"rc": 0})


def test_a_key_not_in_the_agent_needs_a_passphrase(ssh_tools, key):
    ssh_tools.respond("ssh-add -l", {"rc": 1})
    status = cluster_access.identity_status("unity", str(key))
    assert status["needs_passphrase"] is True
    assert status["unlocked"] is False
    assert status["key_path"] == str(key)
    assert argv(ssh_tools) == [["ssh", "-G", "unity"], ["ssh-add", "-l"]]


def test_a_key_already_in_the_agent_does_not_need_a_passphrase(ssh_tools, key):
    reply = {"stdout": "256 SHA256:t2 cluster (ED25519)\n"}
    ssh_tools.respond("ssh-add -l", reply)
    ssh_tools.respond("ssh-keygen", reply)
    status = cluster_access.identity_status("unity", str(key))
    assert status["unlocked"] is True
    assert status["needs_passphrase"] is False
    assert argv(ssh_tools) == [["ssh", "-G", "unity"], ["ssh-add", "-l"], ["ssh-keygen", "-l", "-f", str(key)]]


def test_unlock_adds_the_key_and_never_returns_the_passphrase(ssh_tools, key, tmp_path):
    socket = str(tmp_path / "agent.sock")
    ssh_tools.respond("ssh -G", {"stdout": "identityagent " + socket + "\n"})
    prepare_unlock(ssh_tools, "SHA256:t3")
    ssh_tools.forbid_in_env("secret-pass")
    report = cluster_access.unlock_identity(str(key), "secret-pass", host="unity")
    assert report["ok"] is True
    assert report["remembered"] is True
    assert "secret-pass" not in str(report)
    calls = ssh_tools.calls()
    # The whole environment of every tool call, not only the recorded keys.
    assert calls and all(call["env_leaks"] == [] for call in calls)
    added = next(c for c in calls if c["argv"] == ["ssh-add", str(key)])
    assert added["askpass"] == "secret-pass"
    assert added["env"]["SSH_ASKPASS_REQUIRE"] == "force"
    assert added["env"]["SSH_AUTH_SOCK"] == socket
    assert all("secret-pass" not in str(c["argv"]) for c in calls)
    assert not Path(added["env"]["UNITY_HPC_ASKPASS_FILE"]).exists()
    assert not Path(added["env"]["SSH_ASKPASS"]).exists()
    stored = next(c for c in calls if c["argv"][:2] == ["secret-tool", "store"])
    assert stored["argv"] == ["secret-tool", "store", "--label=Unity HPC SSH key", "application", "unity-hpc", "ssh-key-fingerprint", "SHA256:t3"]
    assert stored["stdin"] == "secret-pass"


def test_existing_empty_agent_is_reused(ssh_tools, key):
    prepare_unlock(ssh_tools, "SHA256:t5")
    assert cluster_access.unlock_identity(str(key), "pw")["ok"]
    assert not any(c[0] == "ssh-agent" for c in argv(ssh_tools))


def test_remembered_key_is_restored_into_the_agent(ssh_tools, key):
    prepare_unlock(ssh_tools, "SHA256:t6")
    ssh_tools.respond("ssh-add -l", {"rc": 1}, {"rc": 1}, {"stdout": "256 SHA256:t6 k (ED25519)\n"})
    ssh_tools.respond("secret-tool lookup", {"stdout": "remembered\n"})
    cluster_access.restore_identity("unity", str(key))
    assert ["secret-tool", "lookup", "application", "unity-hpc", "ssh-key-fingerprint", "SHA256:t6"] in argv(ssh_tools)
    assert next(c for c in ssh_tools.calls() if c["argv"] == ["ssh-add", str(key)])["askpass"] == "remembered"
    assert not any(c[:2] == ["secret-tool", "store"] for c in argv(ssh_tools))


def test_locked_keyring_does_not_try_to_lookup_a_secret(ssh_tools, key):
    prepare_unlock(ssh_tools, "SHA256:t7")
    ssh_tools.respond("busctl", {"stdout": "b true\n"})
    cluster_access.restore_identity("unity", str(key))
    assert not any(c[0] == "secret-tool" or c == ["ssh-add", str(key)] for c in argv(ssh_tools))


def test_unlock_remembers_the_passphrase_only_in_an_unlocked_keyring(ssh_tools, key):
    prepare_unlock(ssh_tools, "SHA256:t8")
    ssh_tools.respond("busctl", {"stdout": "b true\n"})
    assert cluster_access.unlock_identity(str(key), "pw")["remembered"] is False
    assert not any(c[:2] == ["secret-tool", "store"] for c in argv(ssh_tools))


def test_a_configured_agent_that_is_down_is_not_replaced(ssh_tools, key):
    ssh_tools.respond("ssh -G", {"stdout": "identityagent /tmp/t9-agent.sock\n"})
    ssh_tools.respond("ssh-add -l", {"rc": 2})
    before = os.environ.get("SSH_AUTH_SOCK")
    report = cluster_access.unlock_identity(str(key), "pw")
    assert report["error"] == "configured SSH agent is unavailable"
    assert not any(c[0] == "ssh-agent" for c in argv(ssh_tools))
    assert os.environ.get("SSH_AUTH_SOCK") == before


def test_restore_tries_the_keyring_once_in_thirty_seconds(ssh_tools, key):
    prepare_unlock(ssh_tools, "SHA256:t10")
    ssh_tools.respond("secret-tool lookup", {"stdout": "remembered\n"})
    ssh_tools.respond("ssh-add", {"rc": 1})
    cluster_access.restore_identity("unity", str(key))
    cluster_access.restore_identity("unity", str(key))
    assert sum(c[:2] == ["secret-tool", "lookup"] for c in argv(ssh_tools)) == 1


def test_a_missing_identity_file_is_reported_without_loading(ssh_tools, tmp_path):
    report = cluster_access.unlock_identity(str(tmp_path / "absent"), "pw")
    assert report["ok"] is False
    assert report["error"] == "identity file is missing"
    assert ssh_tools.calls() == []


def test_local_shell_runs_a_remote_command_in_local_bash(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    tool = bin_dir / "hpc-fake"
    tool.write_text("#!/bin/sh\necho fake\n")
    tool.chmod(0o755)
    result = cluster_access.LocalShell(path=[bin_dir]).run('printf "%s\\n" "$(cat)"; hpc-fake', timeout=10, input="body")
    assert result.returncode == 0
    assert result.stdout == "body\nfake\n"


def test_local_shell_bounds_a_remote_command_like_ssh():
    with pytest.raises(subprocess.TimeoutExpired):
        cluster_access.LocalShell().run("sleep 5", timeout=1)


def test_local_shell_runs_a_script_on_bash_stdin():
    shell = cluster_access.LocalShell()
    result = shell.run_script("echo ok; exit 3", timeout=10)
    assert result.returncode == 3
    assert result.stdout == "ok\n"
    assert shell.run_script("sleep 5", timeout=1).returncode == 124


@pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync is not installed")
def test_local_shell_transfers_with_the_production_filters(tmp_path):
    shell = cluster_access.LocalShell()
    source = tmp_path / "source"
    source.mkdir()
    (source / "keep.txt").write_text("keep")
    (source / "other.txt").write_text("other")
    remote = tmp_path / "remote"
    remote.mkdir()
    assert shell.transfer(source / "keep.txt", str(remote / "nested.txt")).returncode == 0
    assert (remote / "nested.txt").read_text() == "keep"
    dest = tmp_path / "pulled"
    assert shell.transfer(dest, str(source) + "/", pull=True, include=["/keep.txt"]).returncode == 0
    assert sorted(p.name for p in dest.iterdir()) == ["keep.txt"]


def test_rsync_rsh_expands_the_identity_and_quotes_it(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cluster_access.rsync_rsh("~/k x") == "ssh -i '" + str(tmp_path) + "/k x' -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=3"
    assert "-i" not in cluster_access.rsync_rsh("")


def test_building_a_transport_runs_nothing(ssh_tools):
    from controller.campaign_slurm import SlurmAdapter
    cluster_access.Ssh("unity", "~/.ssh/k")
    SlurmAdapter({"ssh_host": "unity"})
    assert ssh_tools.calls() == []
    with pytest.raises(ValueError, match="alias"):
        cluster_access.Ssh("user@host")
    assert ssh_tools.calls() == []
