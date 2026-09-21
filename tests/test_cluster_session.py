"""The cluster session: idle timeout, and the remote command the schedule sends.

No SSH. The runner is a fake, so these tests hold the command the controller
would send and the decision to skip a local source.
"""

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
