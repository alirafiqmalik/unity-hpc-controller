"""Command lines recorded before Cluster access: literals are the contract."""

import shlex
import subprocess
from pathlib import Path

import pytest

from controller import cluster_access, cluster_session, telemetry
from controller.campaign_slurm import SlurmAdapter


O = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3"]


@pytest.fixture
def recorded(ssh_tools, monkeypatch, tmp_path, tmp_data_dir):
    ssh_tools.record("timeout", "rsync")
    ssh_tools.respond("ssh -G", {"stdout": "identityagent /tmp/rec-agent.sock\n"})
    ssh_tools.respond("ssh", {"rc": 0})
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/rec-inherited.sock")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    seen = []
    real_run = subprocess.run

    def spy(argv, **kw):
        seen.append({"tool": argv[0], "timeout": kw.get("timeout"),
                     "env": "agent" if kw.get("env") is not None else "inherited",
                     "input": kw.get("input")})
        return real_run(argv, **kw)

    monkeypatch.setattr(subprocess, "run", spy)
    return ssh_tools, seen


@pytest.mark.parametrize("operation", ["collect", "close", "check", "slurm_input", "slurm_cancel", "push", "pull", "pull_env"])
@pytest.mark.parametrize("identity", ["", "~/.ssh/k x"], ids=["config-identity", "saved-identity"])
def test_command_line_is_unchanged(recorded, operation, identity, tmp_path, monkeypatch):
    ssh_tools, seen = recorded
    P = ["-i", identity] if identity else []
    inherited = "/tmp/rec-inherited.sock"
    agent = "/tmp/rec-agent.sock"
    ssh_tools.clear()
    seen.clear()
    expected = []
    spies = []
    if operation == "collect":
        cluster_session.collect({"ssh_host": "alias-x", "ssh_identity": identity, "interval_minutes": 30, "session_name": "unity-hpc"}, "src-host:/work/x/telemetry/")
        script = cluster_session.remote_invocation("unity-hpc", "/work/x", 2700)
        expected = [(["timeout", "--foreground", "630", "ssh", *P, *O, "alias-x", "bash", "-s"], script, inherited)]
        spies = [("timeout", None, "inherited", script)]
    elif operation == "close":
        cluster_session.close_session("src-host:/work/x/telemetry/", host="alias-x", identity=identity)
        script = "tmux kill-session -t unity-hpc 2>/dev/null || true\nrm -f /tmp/unity-hpc-sample.rc /tmp/unity-hpc-sample.log\n"
        expected = [(["timeout", "--foreground", "30", "ssh", *P, *O, "alias-x", "bash", "-s"], script, inherited)]
        spies = [("timeout", None, "inherited", script)]
    elif operation == "check":
        cluster_access.check_access("alias-x", identity)
        expected = [(["timeout", "--foreground", "15", "ssh", *P, *O[:4], "alias-x", "echo", "unity-ok"], "", inherited)]
        spies = [("timeout", None, "inherited", None)]
    elif operation == "pull_env":
        stub = tmp_path / "sync"
        stub.write_text('printf "rsh=%s\\nsrc=%s\\n" "$RSYNC_RSH" "$UNITY_TELEMETRY_SRC"\n')
        monkeypatch.setattr(telemetry, "SYNC_SCRIPT", stub)
        telemetry.save_settings(source="src-host:/work/x/telemetry/", ssh_host="alias-x", ssh_identity=identity)
        ssh_tools.clear()
        seen.clear()
        report = telemetry.start_sync(background=False)
        output = report["run"]["output"].splitlines()
        assert output == [
            "rsh=" + shlex.join(["ssh", *(["-i", str(Path(identity).expanduser())] if identity else []), *O]),
            "src=alias-x:/work/x/telemetry/",
        ]
        return
    else:
        adapter = SlurmAdapter({"ssh_host": "alias-x", "ssh_identity": identity})
        assert ssh_tools.calls() == []
        assert seen == []
        expected = [(["ssh", "-G", "alias-x"], "", inherited)]
        spies = [("ssh", 5, "inherited", None)]
        if operation == "slurm_input":
            adapter.command("echo hi", timeout=7, input="BODY")
            expected.append((["ssh", *O, *P, "alias-x", "export PAGER=NONE TZ=UTC LC_ALL=C; echo hi"], "BODY", agent))
            spies.append(("ssh", 7, "agent", "BODY"))
        elif operation == "slurm_cancel":
            adapter.cancel(["1", "2"])
            expected.append((["ssh", *O, *P, "alias-x", "export PAGER=NONE TZ=UTC LC_ALL=C; timeout 20 scancel 1 2"], "", agent))
            spies.append(("ssh", 30, "agent", None))
        elif operation == "push":
            adapter.transfer(tmp_path / "f", "/r/x")
            expected.append((["rsync", "-a", "--safe-links", "--protect-args", "-e", shlex.join(["ssh", *O, *P]), str(tmp_path / "f"), "alias-x:/r/x"], "", agent))
            spies.append(("rsync", 300, "agent", None))
        elif operation == "pull":
            adapter.transfer(tmp_path / "d", "/r/out/", pull=True, include=["/a/", "/a/b.json"])
            expected.append((["rsync", "-a", "--safe-links", "--protect-args", "--include", "/a/", "--include", "/a/b.json", "--exclude", "*", "-e", shlex.join(["ssh", *O, *P]), "alias-x:/r/out/", str(tmp_path / "d")], "", agent))
            spies.append(("rsync", 300, "agent", None))
    calls = ssh_tools.calls()
    assert [(c["argv"], c["stdin"], c["env"].get("SSH_AUTH_SOCK")) for c in calls] == expected
    assert [(c["tool"], c["timeout"], c["env"], c["input"]) for c in seen] == spies
    assert all("src-host" not in c["argv"] for c in calls)
