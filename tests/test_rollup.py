import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ROLLUP = REPO_ROOT / "cluster-intel" / "rollup.py"
sys.path.insert(0, str(REPO_ROOT / "cluster-intel"))

import rollup  # noqa: E402
from lib import paths  # noqa: E402


def _write_day(tree: Path, day: str, resource=None, events=None, task_runs=None):
    d = tree / day
    d.mkdir(parents=True, exist_ok=True)
    if resource is not None:
        (d / "resource_state.jsonl").write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in resource))
    if events is not None:
        (d / "events.jsonl").write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in events))
    if task_runs is not None:
        (d / "task_runs.jsonl").write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in task_runs))


def _slots_for_day(day, n, kind="gpu_type", rid="a100"):
    """n distinct 15-min slots, each a gpu_type sample at 50% util."""
    recs = []
    for i in range(n):
        hh = f"{i // 4:02d}"
        mm = f"{(i % 4) * 15:02d}"
        recs.append({"ts": f"{day}T{hh}:{mm}:00Z", "kind": kind,
                     "resource_id": rid, "alloc": 50, "total": 100})
    return recs


def _dump(table):
    con = sqlite3.connect(paths.summaries_db())
    con.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in con.execute(
            f"SELECT * FROM {table} ORDER BY 1,2,3")]
    finally:
        con.close()
    return json.dumps(rows, sort_keys=True)


def test_rollup_is_deterministic(tmp_data_dir):
    _write_day(paths.telemetry_dir(), "2026-07-20", resource=_slots_for_day("2026-07-20", 96))
    rollup.run()
    first = _dump("hourly_resource")
    paths.summaries_db().unlink()
    rollup.run()
    assert _dump("hourly_resource") == first, "same raw -> byte-identical rows"


def test_rollup_is_deterministic_via_copy_base_and_upsert(tmp_data_dir):
    # Production path: roll up once (creates the DB), then roll up the SAME
    # raw again WITHOUT deleting the DB, exercising the copy-base +
    # ON CONFLICT DO UPDATE path production actually runs every 15 min.
    _write_day(paths.telemetry_dir(), "2026-07-20", resource=_slots_for_day("2026-07-20", 96))
    rollup.run()
    first_hourly = _dump("hourly_resource")
    first_daily = _dump("daily_resource")
    assert paths.summaries_db().exists(), "sanity: DB persisted after first run"

    rollup.run()  # same raw, DB left in place: copy-base + upsert path
    assert _dump("hourly_resource") == first_hourly, \
        "copy-base + upsert re-run must be byte-identical to the first run"
    assert _dump("daily_resource") == first_daily, \
        "copy-base + upsert re-run must be byte-identical to the first run"


def test_full_day_is_marked_fully_summarised(tmp_data_dir):
    _write_day(paths.telemetry_dir(), "2026-07-20", resource=_slots_for_day("2026-07-20", 96))
    rollup.run()
    con = sqlite3.connect(paths.summaries_db())
    row = con.execute("SELECT slots_ingested, rows_emitted, fully_summarised "
                      "FROM day_index WHERE day_utc='2026-07-20'").fetchone()
    con.close()
    assert row == (96, 96, 1)


def test_short_day_is_fully_summarised_once_processed(tmp_data_dir):
    # 12 slots (collector started mid-day). Denominator is observed, not 96.
    _write_day(paths.telemetry_dir(), "2026-07-20", resource=_slots_for_day("2026-07-20", 12))
    rollup.run()
    con = sqlite3.connect(paths.summaries_db())
    row = con.execute("SELECT slots_ingested, fully_summarised FROM day_index "
                      "WHERE day_utc='2026-07-20'").fetchone()
    con.close()
    assert row == (12, 1), "a short day must summarise fully, not wedge on a fixed 96"


def _rows_for_day(table, day):
    day_col = "hour_utc" if table == "hourly_resource" else "day_utc"
    like = day + "%"
    con = sqlite3.connect(paths.summaries_db())
    con.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in con.execute(
            f"SELECT * FROM {table} WHERE {day_col} LIKE ? ORDER BY 1,2,3", (like,))]
    finally:
        con.close()
    return json.dumps(rows, sort_keys=True)


def test_cumulative_rows_survive_raw_deletion_and_no_delete_issued(tmp_data_dir):
    import shutil
    _write_day(paths.telemetry_dir(), "2026-07-19", resource=_slots_for_day("2026-07-19", 96))
    _write_day(paths.telemetry_dir(), "2026-07-20", resource=_slots_for_day("2026-07-20", 96))
    rollup.run()

    # snapshot the soon-to-age-out day's summary rows BEFORE deleting its raw
    before_hourly = _rows_for_day("hourly_resource", "2026-07-19")
    before_daily = _rows_for_day("daily_resource", "2026-07-19")
    assert before_hourly != "[]" and before_daily != "[]", "sanity: rows exist before deletion"

    # age out the oldest day's raw
    shutil.rmtree(paths.telemetry_dir() / "2026-07-19")

    # Capture every SQL statement the next rollup issues, in-process, by wrapping
    # sqlite3.connect with a trace callback. A routine rollup must issue no DELETE.
    issued = []
    monkey = sqlite3.connect

    def traced(*a, **k):
        con = monkey(*a, **k)
        con.set_trace_callback(lambda s: issued.append(s))
        return con

    sqlite3.connect = traced
    try:
        rollup.run()
    finally:
        sqlite3.connect = monkey

    # 2026-07-19 rows persist unchanged even though its raw is gone (I9)
    assert '"day_utc": "2026-07-19"' in _dump("daily_resource")
    assert not any(s.strip().upper().startswith("DELETE") for s in issued), \
        "a routine rollup must never DELETE summary rows"

    # the aged-out day's rows are still present AND byte-identical (proves
    # I9 persistence, not merely "some rows exist")
    after_hourly = _rows_for_day("hourly_resource", "2026-07-19")
    after_daily = _rows_for_day("daily_resource", "2026-07-19")
    assert after_hourly == before_hourly, \
        "hourly_resource rows for the aged-out day must be byte-identical"
    assert after_daily == before_daily, \
        "daily_resource rows for the aged-out day must be byte-identical"

    con = sqlite3.connect(paths.summaries_db())
    persisted = con.execute("SELECT COUNT(*) FROM hourly_resource "
                            "WHERE resource_id='a100'").fetchone()[0]
    con.close()
    assert persisted > 0


def test_no_deadlock_aged_out_day_stays_fully_summarised(tmp_data_dir):
    import shutil
    _write_day(paths.telemetry_dir(), "2026-06-01", resource=_slots_for_day("2026-06-01", 96))
    rollup.run()
    shutil.rmtree(paths.telemetry_dir() / "2026-06-01")
    rollup.run()  # its raw is gone; day_index must still say fully_summarised
    con = sqlite3.connect(paths.summaries_db())
    fs = con.execute("SELECT fully_summarised FROM day_index "
                     "WHERE day_utc='2026-06-01'").fetchone()[0]
    pruned = con.execute("SELECT value FROM meta WHERE key='raw_pruned_through'").fetchone()
    con.close()
    assert fs == 1
    assert pruned and pruned[0] == "2026-06-01"


def test_import_overlap_uses_mirror_ignores_imported_whole(tmp_data_dir, capsys):
    # same day in both trees: mirror wins entirely
    _write_day(paths.telemetry_dir(), "2026-07-20",
               resource=_slots_for_day("2026-07-20", 96, rid="a100"))
    _write_day(paths.telemetry_imported_dir(), "2026-07-20",
               resource=_slots_for_day("2026-07-20", 96, rid="IMPORTED"))
    rollup.run()
    con = sqlite3.connect(paths.summaries_db())
    ids = {r[0] for r in con.execute("SELECT DISTINCT resource_id FROM hourly_resource")}
    con.close()
    assert "a100" in ids and "IMPORTED" not in ids, "overlap must consume the mirror only"


def test_task_runs_promote_into_task_profile(tmp_data_dir):
    runs = [{"job_id": "1", "project": "llm", "skill": "run", "partition": "gpu",
             "gpu_type": "a100", "submit": "2026-07-20T10:00:00Z",
             "start": "2026-07-20T10:05:00Z", "end": "2026-07-20T10:45:00Z",
             "req": {"cpus": 8}, "used": {"elapsed_s": 2400, "max_rss_mb": 1000,
                                          "cpu_eff_pct": 11.0, "mem_eff_pct": 6.0},
             "state": "COMPLETED", "exit_code": 0}]
    _write_day(paths.telemetry_dir(), "2026-07-20",
               resource=_slots_for_day("2026-07-20", 4), task_runs=runs)
    rollup.run()
    con = sqlite3.connect(paths.summaries_db())
    row = con.execute("SELECT n, runtime_p50, success_rate FROM task_profile "
                      "WHERE project='llm' AND skill='run' AND hardware='a100'").fetchone()
    tp = con.execute("SELECT task_runs_promoted FROM day_index "
                     "WHERE day_utc='2026-07-20'").fetchone()[0]
    con.close()
    assert row == (1, 2400.0, 1.0)
    assert tp == 1


def _one_run(**over):
    r = {"job_id": "62145001", "project": "llm", "skill": "run", "partition": "gpu",
         "gpu_type": "a100", "submit": "2026-07-20T03:00:00Z",
         "start": "2026-07-20T03:01:00Z", "end": None,
         "req": {"cpus": 8}, "used": {"elapsed_s": 60, "max_rss_mb": None,
                                      "cpu_eff_pct": None, "mem_eff_pct": None},
         "state": "RUNNING", "exit_code": None}
    r.update(over)
    return r


def _task_row(job_id="62145001"):
    con = sqlite3.connect(paths.summaries_db())
    con.row_factory = sqlite3.Row
    try:
        row = con.execute("SELECT * FROM task_run WHERE job_id=?", (job_id,)).fetchone()
    finally:
        con.close()
    return dict(row) if row else None


def test_upsert_upgrades_non_terminal_row_to_terminal(tmp_data_dir):
    # Job first seen RUNNING, later observed COMPLETED with enrichment. The
    # stale non-terminal row must be upgraded, not frozen at first sight.
    _write_day(paths.telemetry_dir(), "2026-07-20",
               resource=_slots_for_day("2026-07-20", 4), task_runs=[_one_run()])
    rollup.run()
    assert _task_row()["state"] == "RUNNING"

    _write_day(paths.telemetry_dir(), "2026-07-20",
               resource=_slots_for_day("2026-07-20", 4),
               task_runs=[_one_run(state="COMPLETED", end="2026-07-20T03:40:00Z",
                                   used={"elapsed_s": 2340, "max_rss_mb": 1002,
                                         "cpu_eff_pct": 55.0, "mem_eff_pct": 12.0},
                                   exit_code=0)])
    rollup.run()
    row = _task_row()
    assert row["state"] == "COMPLETED"
    assert row["elapsed_s"] == 2340 and row["cpu_eff"] == 55.0
    assert row["end"] == "2026-07-20T03:40:00Z"


def test_upsert_never_downgrades_terminal_to_non_terminal(tmp_data_dir):
    _write_day(paths.telemetry_dir(), "2026-07-20",
               resource=_slots_for_day("2026-07-20", 4),
               task_runs=[_one_run(state="COMPLETED", end="2026-07-20T03:40:00Z",
                                   exit_code=0)])
    rollup.run()
    # A stale/out-of-order RUNNING re-observation must NOT clobber the terminal row.
    _write_day(paths.telemetry_dir(), "2026-07-20",
               resource=_slots_for_day("2026-07-20", 4), task_runs=[_one_run()])
    rollup.run()
    assert _task_row()["state"] == "COMPLETED"


def test_upsert_terminal_to_terminal_keeps_fresh_seff_enrichment(tmp_data_dir):
    # First terminal observation lacked seff (cpu_eff None); a later terminal
    # observation carries it. Keep the freshest terminal observation.
    _write_day(paths.telemetry_dir(), "2026-07-20",
               resource=_slots_for_day("2026-07-20", 4),
               task_runs=[_one_run(state="COMPLETED", end="2026-07-20T03:40:00Z",
                                   exit_code=0)])
    rollup.run()
    assert _task_row()["cpu_eff"] is None

    _write_day(paths.telemetry_dir(), "2026-07-20",
               resource=_slots_for_day("2026-07-20", 4),
               task_runs=[_one_run(state="COMPLETED", end="2026-07-20T03:40:00Z",
                                   used={"elapsed_s": 2340, "max_rss_mb": 1002,
                                         "cpu_eff_pct": 77.0, "mem_eff_pct": 33.0},
                                   exit_code=0)])
    rollup.run()
    assert _task_row()["cpu_eff"] == 77.0


def test_upsert_keeps_original_day_utc_when_job_spans_day_dirs(tmp_data_dir):
    # RUNNING sample lands in the 07-20 day-dir; the COMPLETED sample lands in
    # the 07-21 day-dir. day_utc must stay the ORIGINAL (07-20) day and not
    # drift to the later observation's day-dir.
    _write_day(paths.telemetry_dir(), "2026-07-20",
               resource=_slots_for_day("2026-07-20", 4), task_runs=[_one_run()])
    _write_day(paths.telemetry_dir(), "2026-07-21",
               resource=_slots_for_day("2026-07-21", 4),
               task_runs=[_one_run(state="COMPLETED", end="2026-07-21T03:40:00Z",
                                   exit_code=0)])
    rollup.run()
    row = _task_row()
    assert row["state"] == "COMPLETED"
    assert row["day_utc"] == "2026-07-20", "day_utc must not drift to the later day-dir"


def test_upsert_of_identical_terminal_row_is_byte_stable(tmp_data_dir):
    # The determinism contract: re-rolling identical raw must yield
    # byte-identical rows even through the terminal->terminal update path.
    runs = [_one_run(state="COMPLETED", end="2026-07-20T03:40:00Z",
                     used={"elapsed_s": 2340, "max_rss_mb": 1002,
                           "cpu_eff_pct": 55.0, "mem_eff_pct": 12.0}, exit_code=0)]
    _write_day(paths.telemetry_dir(), "2026-07-20",
               resource=_slots_for_day("2026-07-20", 4), task_runs=runs)
    rollup.run()
    first = _dump("task_run")
    rollup.run()  # copy-base + upsert of identical data
    assert _dump("task_run") == first, "identical re-upsert must be byte-stable"


def test_concurrent_invocation_exits_cleanly(tmp_data_dir):
    import fcntl
    _write_day(paths.telemetry_dir(), "2026-07-20", resource=_slots_for_day("2026-07-20", 4))
    lock = open(paths.sync_lock(), "w")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    try:
        r = subprocess.run([sys.executable, str(ROLLUP)],
                           capture_output=True, text=True)
        assert r.returncode == 0
        assert "already running" in (r.stdout + r.stderr).lower()
        assert not paths.summaries_db().exists(), "must not write while lock held (I7)"
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def test_sparse_reobservation_never_unsummarises_a_day(tmp_data_dir):
    # The catchup-heal scenario: a day fully summarised from the imported tree
    # is later shadowed by a SPARSER mirror copy (mirror wins whole-day, but
    # the mirror day carries only re-emitted task_runs, no resource_state).
    # rows_emitted must be monotonic so fully_summarised never flips back to 0
    # -- a flip would wedge the retention gate when the day enters the delete
    # set (I8), the exact deadlock class the gate exists to prevent.
    day = "2026-07-06"
    _write_day(paths.telemetry_imported_dir(), day,
               resource=_slots_for_day(day, 96))
    rollup.run()
    con = sqlite3.connect(paths.summaries_db())
    before = con.execute("SELECT slots_ingested, rows_emitted, fully_summarised "
                         "FROM day_index WHERE day_utc=?", (day,)).fetchone()
    con.close()
    assert before == (96, 96, 1)

    # Sparse mirror copy appears (catchup healed one old job on that day).
    _write_day(paths.telemetry_dir(), day, task_runs=[{
        "job_id": "60000001", "partition": "cpu", "state": "COMPLETED",
        "submit": f"{day}T01:00:00", "start": f"{day}T01:00:10",
        "end": f"{day}T01:05:00",
        "req": {"cpus": 1, "mem_mb": 1024, "gpus": 0},
        "used": {"elapsed_s": 290.0, "cpu_eff_pct": None, "mem_eff_pct": None,
                 "max_rss_mb": None},
    }])
    rollup.run()
    con = sqlite3.connect(paths.summaries_db())
    after = con.execute("SELECT slots_ingested, rows_emitted, fully_summarised "
                        "FROM day_index WHERE day_utc=?", (day,)).fetchone()
    con.close()
    assert after == (96, 96, 1), \
        "a sparser re-observation must never un-summarise the day"


def _one_task_run(day, jid="60000002"):
    return [{
        "job_id": jid, "partition": "cpu", "state": "COMPLETED",
        "submit": f"{day}T01:00:00", "start": f"{day}T01:00:10",
        "end": f"{day}T01:05:00",
        "req": {"cpus": 1, "mem_mb": 1024, "gpus": 0},
        "used": {"elapsed_s": 290.0, "cpu_eff_pct": None, "mem_eff_pct": None,
                 "max_rss_mb": None},
    }]


def test_task_runs_only_day_is_vacuously_fully_summarised(tmp_data_dir):
    # A day with zero resource slots (e.g. migrated history whose snapshot
    # coverage was thin) still promotes its task_runs/events -- deleting its
    # raw loses nothing unsummarised, so the gate must not hold it hostage
    # to slot coverage that never existed.
    day = "2026-07-02"
    _write_day(paths.telemetry_imported_dir(), day, task_runs=_one_task_run(day))
    rollup.run()
    con = sqlite3.connect(paths.summaries_db())
    row = con.execute("SELECT slots_ingested, fully_summarised FROM day_index "
                      "WHERE day_utc=?", (day,)).fetchone()
    con.close()
    assert row == (0, 1), "zero-slot day must be vacuously fully summarised"


def test_phantom_slot_debt_settles_via_current_run_completeness(tmp_data_dir):
    # Historical source contributed slots (monotonic slots_ingested) but was
    # never fully emitted, then a sparser source shadows it: the current raw
    # holds nothing unprocessed, so the day must settle rather than carry
    # unpayable debt that wedges the retention gate as it ages out.
    day = "2026-07-19"
    _write_day(paths.telemetry_imported_dir(), day,
               resource=_slots_for_day(day, 10))
    rollup.run()
    # Simulate the historical anomaly: force the recorded emission to zero
    # (as observed in the real store), then shadow with a task_runs-only
    # mirror day and re-roll.
    con = sqlite3.connect(paths.summaries_db())
    con.execute("UPDATE day_index SET rows_emitted=0, fully_summarised=0 "
                "WHERE day_utc=?", (day,))
    con.commit(); con.close()
    _write_day(paths.telemetry_dir(), day, task_runs=_one_task_run(day, "60000003"))
    rollup.run()
    con = sqlite3.connect(paths.summaries_db())
    row = con.execute("SELECT slots_ingested, fully_summarised FROM day_index "
                      "WHERE day_utc=?", (day,)).fetchone()
    con.close()
    assert row[0] == 10, "monotonic slots_ingested preserved"
    assert row[1] == 1, "current-run completeness must settle phantom debt"
