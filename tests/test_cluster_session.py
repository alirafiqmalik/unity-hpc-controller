"""The cluster session: idle timeout, and the remote command the schedule sends.

No SSH. The runner is a fake transport, so these tests hold the command the controller
would send and the decision to skip a local source.
"""

import os
import subprocess
from pathlib import Path

from controller import cluster_session


class Recorded:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr
        self.calls = []

    def run_script(self, script, *, timeout):
        self.calls.append((script, timeout))
        return subprocess.CompletedProcess([], self.returncode, self.stdout, self.stderr)


def test_thirty_minutes_closes_the_session_after_forty_five():
    assert cluster_session.inactivity_timeout_s(30) == 45 * 60


def test_the_timeout_is_one_and_a_half_intervals():
    assert cluster_session.inactivity_timeout_s(60) == 90 * 60
    assert cluster_session.inactivity_timeout_s(5) == 450


def test_a_remote_source_splits_into_host_and_cluster_dir():
    assert cluster_session.parse_remote_source(
        "unity:/work/a/b/telemetry/"
    ) == ("unity", "/work/a/b")


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


def test_controller_sessions_use_separate_remote_completion_files():
    first = cluster_session.remote_invocation("backend-one", "/work/one", 900)
    second = cluster_session.remote_invocation("backend-two", "/work/two", 900)
    assert "/tmp/backend-one-sample.rc" in first
    assert "/tmp/backend-one-sample.log" in first
    assert "backend-two" not in first
    assert "/tmp/backend-two-sample.rc" in second
    assert "/tmp/backend-two-sample.log" in second
    assert "backend-one" not in second
    assert "/tmp/unity-hpc-sample." not in first + second


def test_collect_and_close_use_only_the_configured_session():
    access = Recorded()

    cfg = {"interval_minutes": 15, "session_name": "backend-isolated"}
    report = cluster_session.collect(cfg, "unity:/work/isolated/telemetry", access=access)
    assert report["session"] == "backend-isolated"
    closed = cluster_session.close_session(
        "unity:/work/isolated/telemetry", access=access,
        session_name=cfg["session_name"],
    )
    assert closed["session"] == "backend-isolated"
    assert "tmux kill-session -t backend-isolated" in access.calls[1][0]
    assert "/tmp/backend-isolated-sample.rc" in access.calls[1][0]
    assert "/tmp/unity-hpc-sample." not in "\n".join(script for script, _ in access.calls)


def test_session_names_cannot_inject_commands_or_tmux_targets():
    for value in ("one;echo secret", "../one", "one:2", "one.two", "x" * 65):
        try:
            cluster_session.clean_session_name(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe session accepted: {value}")


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
    class NoAccess:
        def run_script(self, *args, **kwargs):
            raise AssertionError("local source reached cluster access")

    report = cluster_session.collect(
        {"interval_minutes": 30}, "/tmp/telemetry", access=NoAccess(),
    )
    assert report == {"ok": True, "skipped": "local"}


def test_collect_reports_a_remote_failure():
    access = Recorded(returncode=255, stderr="no route")

    report = cluster_session.collect(
        {"interval_minutes": 30}, "unity:/work/a/b/telemetry/", access=access,
    )
    assert "TMOUT=2700" in access.calls[0][0]
    assert access.calls[0][1] == 630
    assert report["ok"] is False
    assert report["rc"] == 255
    assert "no route" in report["error"]


def test_close_session_wipes_the_remote_sample_files():
    access = Recorded()

    report = cluster_session.close_session(
        "unity:/work/a/b/telemetry/", access=access, host="unity",
    )
    assert report["ok"] is True
    assert "rm -f /tmp/unity-hpc-sample.rc /tmp/unity-hpc-sample.log" in access.calls[0][0]


def test_collect_keeps_the_sample_log_on_this_machine(tmp_data_dir):
    body = (
        "rc=0\n"
        "--- unity-hpc-session-log ---\n"
        "sampled 12 partitions\n"
        "--- unity-hpc-session-log-end ---\n"
    )

    access = Recorded(returncode=0, stdout=body)

    report = cluster_session.collect(
        {"interval_minutes": 30}, "unity:/work/a/b/telemetry/", access=access,
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

    access = Recorded(returncode=124, stdout=body)

    report = cluster_session.collect(
        {"interval_minutes": 30}, "unity:/work/a/b/telemetry/", access=access,
    )
    assert report["ok"] is False
    assert report["rc"] == 124
    assert "sacct is still running" in report["error"]
    assert "sacct is still running" in Path(report["session_log"]).read_text()
