"""The telemetry retrieval controls: state, on-demand runs, and the schedule.

Nothing here touches a socket or a cluster. The retrieval script is replaced by
a stub, so the tests hold this module's own behaviour: what it reports, what it
refuses, and what it does about the sync lock.
"""

import fcntl
import json
import os
import subprocess
import sqlite3
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

from controller import http as chttp
from controller import telemetry
from lib import paths

# A stub that stands in for scripts/hpc-sync-telemetry. It writes what it was
# told to write and exits with the code the environment names.
STUB = """#!/usr/bin/env bash
printf '%s\\n' "${STUB_SAY:-sync: done}"
printf 'src=%s\\n' "$UNITY_TELEMETRY_SRC"
exit "${STUB_RC:-0}"
"""


@pytest.fixture(autouse=True)
def clean_module(tmp_data_dir, monkeypatch):
    """A fresh data directory, no in-flight run, no schedule thread."""
    monkeypatch.delenv("UNITY_TELEMETRY_SRC", raising=False)
    telemetry.stop_scheduler()
    telemetry._in_flight = None
    yield
    telemetry.stop_scheduler()
    telemetry._in_flight = None


@pytest.fixture
def stub_script(tmp_path, monkeypatch):
    """Point the module at a stub retrieval script."""
    script = tmp_path / "stub-sync"
    script.write_text(STUB)
    script.chmod(0o755)
    monkeypatch.setattr(telemetry, "SYNC_SCRIPT", script)
    return script


def _req(method, url, body=None):
    raw = json.dumps(body).encode() if body is not None else b""
    return chttp.handle(chttp.parse_raw(method, url, raw))


def _payload(resp):
    return json.loads(resp.body.decode())


# --------------------------------------------------------------------------
# settings


def test_settings_start_at_the_documented_defaults():
    cfg = telemetry.settings()
    assert cfg["source"] == ""
    assert cfg["schedule_enabled"] is False
    assert cfg["interval_minutes"] == 60


def test_settings_round_trip_through_the_data_directory():
    telemetry.save_settings(source="unity:/work/a/b/telemetry/",
                            interval_minutes=15, schedule_enabled=True)
    assert telemetry.settings_path().is_file()
    cfg = telemetry.settings()
    assert cfg["source"] == "unity:/work/a/b/telemetry/"
    assert cfg["interval_minutes"] == 15
    assert cfg["schedule_enabled"] is True


def test_settings_live_under_unity_hpc_data_not_the_browser(tmp_data_dir):
    telemetry.save_settings(source="unity:/work/a/b/telemetry/")
    assert telemetry.settings_path().parent == tmp_data_dir / "controller"


@pytest.mark.parametrize("minutes", [0, 4, 1441, "soon", None])
def test_an_interval_outside_the_bounds_is_refused(minutes):
    with pytest.raises(ValueError):
        telemetry.save_settings(interval_minutes=minutes)


def test_an_unknown_setting_is_refused():
    with pytest.raises(ValueError, match="unknown setting"):
        telemetry.save_settings(bind="0.0.0.0")


def test_a_multi_line_source_is_refused():
    with pytest.raises(ValueError, match="one line"):
        telemetry.save_settings(source="unity:/a/\nunity:/b/")


def test_a_corrupt_settings_file_reads_as_the_defaults():
    path = telemetry.settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ this is not JSON")
    assert telemetry.settings() == dict(telemetry.DEFAULTS)


def test_turning_the_schedule_on_starts_its_clock_now():
    before = telemetry.settings()["schedule_since_utc"]
    cfg = telemetry.save_settings(schedule_enabled=True)
    assert before == ""
    assert cfg["schedule_since_utc"]


# --------------------------------------------------------------------------
# source resolution


def test_the_saved_setting_wins_over_the_environment(monkeypatch):
    monkeypatch.setenv("UNITY_TELEMETRY_SRC", "unity:/from/env/")
    telemetry.save_settings(source="unity:/from/settings/")
    src = telemetry.resolve_source()
    assert src == {"value": "unity:/from/settings/", "origin": "settings",
                   "configured": True}


def test_the_environment_is_used_when_nothing_is_saved(monkeypatch):
    monkeypatch.setenv("UNITY_TELEMETRY_SRC", "unity:/from/env/")
    src = telemetry.resolve_source()
    assert src["value"] == "unity:/from/env/"
    assert src["origin"] == "environment"


def test_an_attached_project_env_is_the_last_resort(tmp_path):
    from controller import registry

    project = tmp_path / "proj"
    (project / "unityHPC").mkdir(parents=True)
    (project / "unityHPC" / ".env").write_text(
        'SLURM_ACCOUNT="pi_x"\n'
        'UNITY_TELEMETRY_SRC="unity:/from/project/telemetry/"  # comment\n'
    )
    registry.attach(slug="proj", path=str(project), primitive="cpu")
    src = telemetry.resolve_source()
    assert src["value"] == "unity:/from/project/telemetry/"
    assert src["origin"] == "project:proj"


def test_an_empty_project_value_is_not_a_source(tmp_path):
    from controller import registry

    project = tmp_path / "proj"
    (project / "unityHPC").mkdir(parents=True)
    (project / "unityHPC" / ".env").write_text('UNITY_TELEMETRY_SRC=""\n')
    registry.attach(slug="proj", path=str(project), primitive="cpu")
    assert telemetry.resolve_source()["configured"] is False


# --------------------------------------------------------------------------
# the sync lock


def test_sync_running_follows_the_shared_lock(tmp_data_dir):
    lock = paths.sync_lock()
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.touch()
    assert telemetry.sync_running() is False
    with lock.open("w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        assert telemetry.sync_running() is True
    assert telemetry.sync_running() is False


def test_sync_running_is_false_when_the_lock_file_is_absent():
    assert telemetry.sync_running() is False


def test_a_held_lock_refuses_a_new_retrieval(monkeypatch, stub_script):
    telemetry.save_settings(source="unity:/work/a/b/telemetry/")
    lock = paths.sync_lock()
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.touch()
    with lock.open("w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        answer = telemetry.start_sync()
    assert answer["started"] is False
    assert answer["status"] == "already-running"


# --------------------------------------------------------------------------
# running a retrieval


def test_a_retrieval_without_a_source_is_refused(stub_script):
    answer = telemetry.start_sync()
    assert answer == {
        "ok": False, "started": False, "status": "unconfigured",
        "message": "no telemetry source is configured",
    }


def test_a_retrieval_passes_the_resolved_source_to_the_script(stub_script):
    telemetry.save_settings(source="unity:/work/a/b/telemetry/")
    answer = telemetry.start_sync(background=False)
    assert answer["run"]["status"] == "ok"
    assert "src=unity:/work/a/b/telemetry/" in answer["run"]["output"]


def test_a_failing_script_is_recorded_as_failed(stub_script, monkeypatch):
    monkeypatch.setenv("STUB_RC", "3")
    monkeypatch.setenv("STUB_SAY", "sync: dry-run rsync failed")
    telemetry.save_settings(source="unity:/work/a/b/telemetry/")
    run = telemetry.start_sync(background=False)["run"]
    assert run["status"] == "failed"
    assert run["rc"] == 3
    assert "dry-run rsync failed" in run["output"]


def test_the_scripts_own_skip_message_is_reported_as_already_running(
        stub_script, monkeypatch):
    monkeypatch.setenv("STUB_SAY", "sync already running — skipping pull and rollup")
    telemetry.save_settings(source="unity:/work/a/b/telemetry/")
    run = telemetry.start_sync(background=False)["run"]
    assert run["status"] == "already-running"
    assert run["rc"] == 0


def test_a_missing_script_fails_without_raising(monkeypatch, tmp_path):
    monkeypatch.setattr(telemetry, "SYNC_SCRIPT", tmp_path / "gone")
    telemetry.save_settings(source="unity:/work/a/b/telemetry/")
    run = telemetry.start_sync(background=False)["run"]
    assert run["status"] == "failed"


def test_a_background_retrieval_returns_before_the_script_ends(tmp_path, monkeypatch):
    slow = tmp_path / "slow-sync"
    slow.write_text("#!/usr/bin/env bash\nsleep 1\necho 'sync: done'\n")
    slow.chmod(0o755)
    monkeypatch.setattr(telemetry, "SYNC_SCRIPT", slow)
    telemetry.save_settings(source="unity:/work/a/b/telemetry/")
    start = time.monotonic()
    answer = telemetry.start_sync()
    assert answer["started"] is True
    assert time.monotonic() - start < 0.5, "the HTTP path must not block"
    assert telemetry.status()["running"] is True
    for _ in range(80):
        if telemetry._in_flight is None:
            break
        time.sleep(0.1)
    assert telemetry.last_run()["status"] == "ok"


def test_two_retrievals_do_not_overlap(tmp_path, monkeypatch):
    slow = tmp_path / "slow-sync"
    slow.write_text("#!/usr/bin/env bash\nsleep 1\n")
    slow.chmod(0o755)
    monkeypatch.setattr(telemetry, "SYNC_SCRIPT", slow)
    telemetry.save_settings(source="unity:/work/a/b/telemetry/")
    assert telemetry.start_sync()["started"] is True
    second = telemetry.start_sync()
    assert second["started"] is False
    assert second["status"] == "already-running"
    for _ in range(80):
        if telemetry._in_flight is None:
            break
        time.sleep(0.1)


def test_a_retrieval_that_overruns_its_timeout_is_killed(tmp_path, monkeypatch):
    slow = tmp_path / "slow-sync"
    slow.write_text("#!/usr/bin/env bash\nsleep 30\n")
    slow.chmod(0o755)
    monkeypatch.setattr(telemetry, "SYNC_SCRIPT", slow)
    monkeypatch.setenv("UNITY_HPC_SYNC_TIMEOUT", "1")
    telemetry.save_settings(source="unity:/work/a/b/telemetry/")
    run = telemetry.start_sync(background=False)["run"]
    assert run["status"] == "failed"
    assert run["rc"] == 124


# --------------------------------------------------------------------------
# history


def test_history_is_newest_first_and_capped(stub_script):
    telemetry.save_settings(source="unity:/work/a/b/telemetry/")
    for _ in range(3):
        telemetry.start_sync(background=False)
    rows = telemetry.history(10)
    assert len(rows) == 3
    stamps = [r["started_utc"] for r in rows]
    assert stamps == sorted(stamps, reverse=True)
    telemetry._append_history({"id": "x", "status": "ok"})
    assert len(telemetry.history(telemetry.HISTORY_KEEP)) == 4


def test_history_survives_a_damaged_line(stub_script):
    telemetry.save_settings(source="unity:/work/a/b/telemetry/")
    telemetry.start_sync(background=False)
    with telemetry.history_path().open("a") as fh:
        fh.write("not json at all\n")
    assert len(telemetry.history(10)) == 1


def test_last_success_skips_the_failures(stub_script, monkeypatch):
    telemetry.save_settings(source="unity:/work/a/b/telemetry/")
    telemetry.start_sync(background=False)
    good = telemetry.last_run()["id"]
    monkeypatch.setenv("STUB_RC", "9")
    telemetry.start_sync(background=False)
    assert telemetry.last_run()["status"] == "failed"
    assert telemetry.last_success()["id"] == good


# --------------------------------------------------------------------------
# the schedule


def test_the_schedule_is_off_until_an_operator_turns_it_on():
    assert telemetry.next_run_utc() is None
    assert telemetry.status()["schedule"]["enabled"] is False


def test_the_first_scheduled_run_is_one_interval_away():
    telemetry.save_settings(schedule_enabled=True, interval_minutes=30)
    when = datetime.strptime(telemetry.next_run_utc(), "%Y-%m-%dT%H:%M:%SZ")
    when = when.replace(tzinfo=timezone.utc)
    gap = when - datetime.now(timezone.utc)
    assert timedelta(minutes=29) < gap <= timedelta(minutes=30)


def test_the_next_run_counts_from_the_last_retrieval(stub_script):
    telemetry.save_settings(source="unity:/work/a/b/telemetry/",
                            schedule_enabled=True, interval_minutes=10)
    telemetry.start_sync(background=False)
    started = telemetry.last_run()["started_utc"]
    when = datetime.strptime(telemetry.next_run_utc(), "%Y-%m-%dT%H:%M:%SZ")
    expect = datetime.strptime(started, "%Y-%m-%dT%H:%M:%SZ") + timedelta(minutes=10)
    assert when == expect


def test_the_schedule_thread_starts_once_and_stops():
    assert telemetry.start_scheduler() is True
    assert telemetry.scheduler_alive() is True
    assert telemetry.start_scheduler() is False, "a second call must not add a thread"
    telemetry.stop_scheduler()
    assert telemetry.scheduler_alive() is False


def test_the_schedule_thread_fires_a_due_retrieval(stub_script, monkeypatch):
    monkeypatch.setattr(telemetry, "TICK_SECONDS", 0.05)
    telemetry.save_settings(source="unity:/work/a/b/telemetry/",
                            schedule_enabled=True, interval_minutes=5)
    # Backdate the clock so the first run is already due.
    past = datetime.now(timezone.utc) - timedelta(minutes=10)
    telemetry.save_settings(schedule_since_utc=past.strftime("%Y-%m-%dT%H:%M:%SZ"))
    telemetry.start_scheduler()
    for _ in range(100):
        if telemetry.last_run():
            break
        time.sleep(0.1)
    telemetry.stop_scheduler()
    run = telemetry.last_run()
    assert run is not None and run["reason"] == "schedule"


def test_the_schedule_does_nothing_while_it_is_off(stub_script, monkeypatch):
    monkeypatch.setattr(telemetry, "TICK_SECONDS", 0.05)
    telemetry.save_settings(source="unity:/work/a/b/telemetry/")
    telemetry.start_scheduler()
    time.sleep(0.5)
    telemetry.stop_scheduler()
    assert telemetry.last_run() is None


# --------------------------------------------------------------------------
# the status payload


def test_status_reports_every_store_the_panel_shows(tmp_data_dir):
    payload = telemetry.status()
    assert set(payload) == {
        "source", "running", "in_flight", "last_run", "last_success",
        "schedule", "stores", "rollup", "history",
    }
    assert set(payload["stores"]) == {"summaries_db", "snapshot_csv", "telemetry"}
    assert payload["stores"]["summaries_db"]["present"] is False


def test_status_reads_the_rollup_stamp_out_of_summaries_db(tmp_data_dir):
    db = paths.summaries_db()
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    con.execute("INSERT INTO meta VALUES('last_rollup_utc','2026-07-30T12:00:00Z')")
    con.execute("INSERT INTO meta VALUES('schema_version','1')")
    con.commit()
    con.close()
    rollup = telemetry.status()["rollup"]
    assert rollup["last_rollup_utc"] == "2026-07-30T12:00:00Z"
    assert rollup["schema_version"] == "1"
    assert rollup["age_s"] > 0


def test_a_rollup_older_than_the_raw_files_is_not_current(tmp_data_dir):
    db = paths.summaries_db()
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    con.execute("INSERT INTO meta VALUES('last_rollup_utc','2020-01-01T00:00:00Z')")
    con.commit()
    con.close()
    day = paths.telemetry_dir() / "2026-07-30"
    day.mkdir(parents=True)
    (day / "resource_state.jsonl").write_text("{}\n")
    payload = telemetry.status()
    assert payload["stores"]["telemetry"]["days"] == 1
    assert payload["stores"]["telemetry"]["newest_day"] == "2026-07-30"
    assert payload["rollup"]["current"] is False


def test_status_never_raises_on_a_damaged_database(tmp_data_dir):
    paths.summaries_db().write_bytes(b"this is not a database")
    assert telemetry.status()["rollup"]["last_rollup_utc"] is None


# --------------------------------------------------------------------------
# HTTP


def test_the_telemetry_endpoint_answers_with_the_status_payload():
    resp = _req("GET", "/api/v1/telemetry")
    assert resp.status == 200
    assert "telemetry" in _payload(resp)


def test_a_sync_post_without_a_source_answers_200_and_says_why():
    resp = _req("POST", "/api/v1/telemetry/sync", {})
    body = _payload(resp)
    assert resp.status == 200
    assert body["status"] == "unconfigured"


def test_a_started_sync_answers_202(stub_script):
    telemetry.save_settings(source="unity:/work/a/b/telemetry/")
    resp = _req("POST", "/api/v1/telemetry/sync", {"reason": "manual"})
    assert resp.status == 202
    assert _payload(resp)["started"] is True
    for _ in range(80):
        if telemetry._in_flight is None:
            break
        time.sleep(0.1)


def test_settings_patch_saves_and_answers_with_the_new_state():
    resp = _req("PATCH", "/api/v1/telemetry/settings", {
        "source": "unity:/work/a/b/telemetry/",
        "schedule_enabled": True,
        "interval_minutes": 20,
    })
    assert resp.status == 200
    body = _payload(resp)
    assert body["settings"]["interval_minutes"] == 20
    assert body["telemetry"]["schedule"]["enabled"] is True
    assert telemetry.settings()["source"] == "unity:/work/a/b/telemetry/"


def test_a_bad_interval_answers_400_and_changes_nothing():
    resp = _req("PATCH", "/api/v1/telemetry/settings", {"interval_minutes": 2})
    assert resp.status == 400
    assert telemetry.settings()["interval_minutes"] == 60


def test_a_setting_the_api_does_not_own_is_ignored():
    _req("PATCH", "/api/v1/telemetry/settings", {"schedule_since_utc": "bogus"})
    assert telemetry.settings()["schedule_since_utc"] == ""


def test_an_unknown_telemetry_route_is_a_404():
    assert _req("GET", "/api/v1/telemetry/nope").status == 404


# --------------------------------------------------------------------------
# the whole path, against a local fixture source


def _slots(day, rid="a100", n=96):
    return [
        {"ts": f"{day}T{i // 4:02d}:{(i % 4) * 15:02d}:00Z", "kind": "gpu_type",
         "resource_id": rid, "alloc": 40 + (i % 20), "total": 100}
        for i in range(n)
    ]


@pytest.mark.skipif(
    subprocess.run(["bash", "-c", "command -v rsync"],
                   capture_output=True).returncode != 0,
    reason="rsync not available")
def test_a_real_retrieval_fills_the_charts_end_to_end(tmp_path, tmp_data_dir):
    """The controller path, the real script, a local fixture source.

    A path with no ':' is a supported local source, so this exercises
    scripts/hpc-sync-telemetry, sync-telemetry.sh, the retention gate and
    rollup.py — everything but the network.
    """
    from controller import snapshot

    day = (datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    src = tmp_path / "cluster" / "telemetry"
    (src / day).mkdir(parents=True)
    (src / day / "resource_state.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in _slots(day)))
    (tmp_path / "cluster" / "snapshot.csv").write_text(
        "timestamp_utc,gpu_running,gpu_pending,gpu_preempt_pending,"
        "total_nodes,free_nodes,gpu_types_free\n"
        f"{day}T00:00:00Z,12,4,1,544,31,a100 a40\n")

    assert snapshot.usage(24)["available"] is False

    _req("PATCH", "/api/v1/telemetry/settings", {"source": str(src) + "/"})
    run = telemetry.start_sync(background=False)["run"]
    assert run["status"] == "ok", run["output"]

    assert (paths.telemetry_dir() / day).is_dir()
    assert paths.summaries_db().exists()
    assert paths.snapshot_csv().exists(), "the sibling snapshot.csv must come too"

    usage = snapshot.usage(24)
    assert usage["available"] is True
    assert "a100" in usage["series"]
    assert usage["window"] == "recent"

    live = snapshot.live_snapshot()
    assert live["available"] is True
    assert live["latest"]["gpu_running"] == 12

    payload = telemetry.status()
    assert payload["rollup"]["last_rollup_utc"]
    assert payload["rollup"]["current"] is True
    assert payload["stores"]["summaries_db"]["present"] is True
    assert payload["history"][0]["status"] == "ok"


@pytest.mark.skipif(
    subprocess.run(["bash", "-c", "command -v rsync"],
                   capture_output=True).returncode != 0,
    reason="rsync not available")
def test_a_source_with_no_sibling_snapshot_still_succeeds(tmp_path, tmp_data_dir):
    day = (datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    src = tmp_path / "cluster" / "telemetry"
    (src / day).mkdir(parents=True)
    (src / day / "resource_state.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in _slots(day)))

    telemetry.save_settings(source=str(src) + "/")
    run = telemetry.start_sync(background=False)["run"]
    assert run["status"] == "ok", run["output"]
    assert not paths.snapshot_csv().exists()


@pytest.mark.skipif(
    subprocess.run(["bash", "-c", "command -v rsync"],
                   capture_output=True).returncode != 0,
    reason="rsync not available")
def test_the_snapshot_pull_can_be_turned_off(tmp_path, tmp_data_dir, monkeypatch):
    day = (datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    src = tmp_path / "cluster" / "telemetry"
    (src / day).mkdir(parents=True)
    (src / day / "resource_state.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in _slots(day)))
    (tmp_path / "cluster" / "snapshot.csv").write_text("timestamp_utc\n")

    monkeypatch.setenv("UNITY_SNAPSHOT_SRC", "")
    telemetry.save_settings(source=str(src) + "/")
    run = telemetry.start_sync(background=False)["run"]
    assert run["status"] == "ok", run["output"]
    assert not paths.snapshot_csv().exists()


def test_the_schedule_opens_no_port_and_no_remote_process():
    """The schedule is a thread on this machine, not a daemon on the cluster."""
    source = Path(telemetry.__file__).read_text()
    for banned in ("0.0.0.0", "socket", "tailscale funnel", "tmux", "ssh "):
        assert banned not in source, f"telemetry.py must not use {banned!r}"
