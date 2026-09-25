"""The cluster session: idle timeout, and the remote command the schedule sends.

No SSH. The runner is a fake, so these tests hold the command the controller
would send and the decision to skip a local source.
"""

import os
import subprocess
from pathlib import Path

from controller import cluster_session


def test_thirty_minutes_closes_the_session_after_forty_five():
    assert cluster_session.inactivity_timeout_s(30) == 45 * 60


def test_the_timeout_is_one_and_a_half_intervals():
    assert cluster_session.inactivity_timeout_s(60) == 90 * 60
    assert cluster_session.inactivity_timeout_s(5) == 450


def test_a_remote_source_splits_into_host_and_cluster_dir():
    assert cluster_session.parse_remote_source(
        "unity:/work/a/b/telemetry/"
    ) == ("unity", "/work/a/b")


def test_ssh_argv_is_the_config_alias_with_no_extra_options():
    """The panel and the schedule run `ssh unity`, the same command a shell does.

    BatchMode and ConnectTimeout overrode the user's ~/.ssh/config Host
    entry and produced Permission denied against the resolved FQDN.
    """
    assert cluster_session.ssh_argv("unity") == ["ssh", "unity"]
    assert "BatchMode" not in cluster_session.ssh_argv("unity")
    assert cluster_session.ssh_command("unity") == "ssh unity"


def test_ssh_argv_can_pin_an_identity_file():
    assert cluster_session.ssh_argv("unity", "~/.ssh/cluster") == [
        "ssh", "-i", "~/.ssh/cluster", "unity",
    ]


def test_ssh_host_must_be_an_alias():
    try:
        cluster_session.clean_ssh_host("user@login.example.edu")
    except ValueError as exc:
        assert "alias" in str(exc)
    else:
        raise AssertionError("a user@host value was accepted")
    assert cluster_session.clean_ssh_host("") == "unity"
    assert cluster_session.clean_ssh_host("unity") == "unity"


def test_a_local_source_has_no_session():
    assert cluster_session.parse_remote_source("/tmp/telemetry") is None
    assert cluster_session.parse_remote_source("") is None


def test_the_remote_command_samples_once_and_sets_the_idle_timer():
    script = cluster_session.remote_invocation("unity-hpc", "/work/a/b", 2700)
    assert "tmux has-session -t unity-hpc" in script
    assert "tmux new-session -d -s unity-hpc" in script
    assert "export TMOUT=2700" in script
    assert "collector.sh once" in script
    assert "loop" not in script
    assert "rm -f /tmp/unity-hpc-sample.rc /tmp/unity-hpc-sample.log" in script
    assert "--- unity-hpc-session-log ---" in script


def test_a_remote_timeout_reports_the_partial_log_and_removes_temp_files(
    tmp_path, monkeypatch,
):
    mark = tmp_path / "sample.rc"
    log = tmp_path / "sample.log"
    monkeypatch.setattr(cluster_session, "_MARK", str(mark))
    monkeypatch.setattr(cluster_session, "_LOG", str(log))
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    tmux = fake_bin / "tmux"
    tmux.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = send-keys ]; then\n"
        "  printf 'sacct is still running\\n' > \"$FAKE_LOG\"\n"
        "fi\n"
    )
    tmux.chmod(0o755)
    script = cluster_session.remote_invocation(
        "unity-hpc", str(tmp_path), 900, wait_s=0,
    )
    proc = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True,
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}",
             "FAKE_LOG": str(log)},
    )
    assert proc.returncode == 124
    assert "timeout" in proc.stdout
    assert cluster_session.extract_session_log(proc.stdout) == (
        "sacct is still running\n"
    )
    assert not mark.exists()
    assert not log.exists()


def test_the_remote_command_can_run_sample_or_prune():
    sample = cluster_session.remote_invocation("unity-hpc", "/work/a/b", 2700, mode="sample")
    prune = cluster_session.remote_invocation("unity-hpc", "/work/a/b", 2700, mode="prune")
    assert "collector.sh sample" in sample
    assert "collector.sh prune" in prune
    assert "collector.sh once" not in sample


def test_loop_is_not_a_panel_script():
    try:
        cluster_session.clean_mode("loop")
    except ValueError as exc:
        assert "once, sample, or prune" in str(exc)
    else:
        raise AssertionError("loop was accepted")


def test_collect_skips_a_local_source_without_calling_ssh():
    calls = []
    report = cluster_session.collect(
        {"interval_minutes": 30}, "/tmp/telemetry",
        run=lambda *args: calls.append(args),
    )
    assert report == {"ok": True, "skipped": "local"}
    assert calls == []


def test_collect_reports_a_remote_failure():
    def run(host, script, timeout_s):
        assert host == "unity"
        assert "TMOUT=2700" in script
        return type("P", (), {"returncode": 255, "stdout": "", "stderr": "no route"})()

    report = cluster_session.collect(
        {"interval_minutes": 30}, "unity:/work/a/b/telemetry/", run=run,
    )
    assert report["ok"] is False
    assert report["rc"] == 255
    assert "no route" in report["error"]


def test_collect_uses_the_configured_ssh_alias_not_the_source_prefix():
    seen = []

    def run(host, script, timeout_s):
        seen.append(host)
        return type("P", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    report = cluster_session.collect(
        {"interval_minutes": 30, "ssh_host": "unity"},
        "other:/work/a/b/telemetry/",
        run=run,
    )
    assert report["ok"] is True
    assert report["host"] == "unity"
    assert seen == ["unity"]


def test_a_key_not_in_the_agent_needs_a_passphrase(tmp_path):
    key = tmp_path / "cluster"
    key.write_text("dummy-key\n")

    def run(argv, **_kwargs):
        if argv[:2] == ["ssh-add", "-l"]:
            return type("P", (), {
                "returncode": 1, "stdout": "",
                "stderr": "The agent has no identities.\n",
            })()
        raise AssertionError(argv)

    status = cluster_session.agent_status("unity", str(key), run=run)
    assert status["needs_passphrase"] is True
    assert status["unlocked"] is False
    assert status["key_path"] == str(key)


def test_a_key_already_in_the_agent_does_not_need_a_passphrase(tmp_path):
    key = tmp_path / "cluster"
    key.write_text("dummy-key\n")

    def run(argv, **_kwargs):
        if argv[:2] == ["ssh-add", "-l"]:
            return type("P", (), {
                "returncode": 0,
                "stdout": "256 SHA256:abc cluster (ED25519)\n",
                "stderr": "",
            })()
        if argv[:2] == ["ssh-keygen", "-l"]:
            return type("P", (), {
                "returncode": 0,
                "stdout": "256 SHA256:abc cluster (ED25519)\n",
                "stderr": "",
            })()
        raise AssertionError(argv)

    status = cluster_session.agent_status("unity", str(key), run=run)
    assert status["needs_passphrase"] is False
    assert status["unlocked"] is True


def test_unlock_adds_the_key_and_never_returns_the_passphrase(tmp_path):
    key = tmp_path / "cluster"
    key.write_text("dummy-key\n")
    seen = []

    def run(argv, **kwargs):
        seen.append(argv)
        env = kwargs.get("env") or {}
        assert "secret-pass" not in argv
        assert "secret-pass" not in str(env)
        return type("P", (), {
            "returncode": 0, "stdout": "Identity added: cluster\n", "stderr": "",
        })()

    report = cluster_session.unlock_identity(
        str(key), "secret-pass", run=run,
    )
    assert report["ok"] is True
    assert "secret-pass" not in str(report)
    assert seen[0][0] == "ssh-add"
    assert seen[0][-1] == str(key)


def test_unlock_refuses_an_empty_passphrase(tmp_path):
    key = tmp_path / "cluster"
    key.write_text("dummy-key\n")
    try:
        cluster_session.unlock_identity(str(key), "")
    except ValueError as exc:
        assert "empty" in str(exc)
    else:
        raise AssertionError("an empty passphrase was accepted")


def test_close_session_wipes_the_remote_sample_files():
    seen = []

    def run(host, script, timeout_s):
        seen.append(script)
        return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    report = cluster_session.close_session(
        "unity:/work/a/b/telemetry/", run=run, host="unity",
    )
    assert report["ok"] is True
    assert "rm -f /tmp/unity-hpc-sample.rc /tmp/unity-hpc-sample.log" in seen[0]


def test_collect_keeps_the_sample_log_on_this_machine(tmp_data_dir):
    body = (
        "rc=0\n"
        "--- unity-hpc-session-log ---\n"
        "sampled 12 partitions\n"
        "--- unity-hpc-session-log-end ---\n"
    )

    def run(host, script, timeout_s):
        return type("P", (), {"returncode": 0, "stdout": body, "stderr": ""})()

    report = cluster_session.collect(
        {"interval_minutes": 30}, "unity:/work/a/b/telemetry/", run=run,
    )
    assert report["ok"] is True
    assert report["session_log"]
    saved = Path(report["session_log"])
    assert saved.is_file()
    assert "sampled 12 partitions" in saved.read_text()
    assert "session-logs" in saved.parts


def test_collect_keeps_a_partial_log_when_the_remote_command_times_out(tmp_data_dir):
    body = (
        "timeout\nrc=124\n"
        "--- unity-hpc-session-log ---\n"
        "sacct is still running\n"
        "--- unity-hpc-session-log-end ---\n"
    )

    def run(host, script, timeout_s):
        return type("P", (), {"returncode": 124, "stdout": body, "stderr": ""})()

    report = cluster_session.collect(
        {"interval_minutes": 30}, "unity:/work/a/b/telemetry/", run=run,
    )
    assert report["ok"] is False
    assert report["rc"] == 124
    assert "sacct is still running" in report["error"]
    assert "sacct is still running" in Path(report["session_log"]).read_text()


def test_probe_runs_echo_on_the_alias():
    seen = []

    def run(argv):
        seen.append(argv)
        return type("P", (), {"returncode": 0, "stdout": "unity-ok\n", "stderr": ""})()

    report = cluster_session.probe("unity", run=run)
    assert report["ok"] is True
    assert report["command"] == "ssh unity"
    assert seen[0][-2:] == ["unity", "echo"] or "unity-ok" in " ".join(seen[0])
    assert "ssh" in seen[0]
    assert "unity" in seen[0]
    assert "BatchMode" not in seen[0]
