import fcntl
import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "cluster-intel"))

import migrate  # noqa: E402
from lib import paths, cluster_config as cc  # noqa: E402


def _make_raw_jobs(path: Path, n: int):
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE raw_jobs(job_id TEXT PRIMARY KEY, user TEXT, account TEXT,
        partition TEXT, state TEXT, submit TEXT, start TEXT, end TEXT, elapsed TEXT,
        nnodes INTEGER, ncpus INTEGER, req_mem TEXT, alloc_tres TEXT, exit_code TEXT)""")
    for i in range(n):
        con.execute("INSERT INTO raw_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (str(62000000 + i), "u", "acct", "gpu", "COMPLETED",
                     "2026-07-20T10:00:00", "2026-07-20T10:05:00", "2026-07-20T10:45:00",
                     "00:40:00", 1, 8, "16G", "cpu=8,mem=16384M,gres/gpu:a100=1", "0:0"))
    con.commit()
    con.close()


def _insert_row(path: Path, job_id: str, submit, start, end):
    con = sqlite3.connect(path)
    con.execute("INSERT INTO raw_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, "u", "acct", "gpu", "PENDING", submit, start, end,
                 "00:00:00", 1, 8, "16G", "cpu=8,mem=16384M", "0:0"))
    con.commit()
    con.close()


def test_import_raw_jobs_reconciles(tmp_data_dir):
    db = tmp_data_dir / "raw_jobs.db"
    _make_raw_jobs(db, 5)
    report = migrate.import_raw_jobs(db)
    written = report["written"]
    assert written == 5
    assert report["skipped_no_date"] == 0
    lines = (paths.telemetry_imported_dir() / "2026-07-20" / "task_runs.jsonl").read_text().splitlines()
    assert len(lines) == 5
    rec = json.loads(lines[0])
    assert rec["gpu_type"] == "a100"
    assert rec["used"]["elapsed_s"] == 2400
    # telemetry-imported/, never telemetry/ (the rsync mirror): a retire-verify
    # failure must never let migration corrupt the live pull target.
    assert not (paths.telemetry_dir() / "2026-07-20").exists()


def test_import_raw_jobs_is_idempotent_on_retry(tmp_data_dir):
    db = tmp_data_dir / "raw_jobs.db"
    _make_raw_jobs(db, 5)
    day_file = paths.telemetry_imported_dir() / "2026-07-20" / "task_runs.jsonl"

    migrate.import_raw_jobs(db)
    first_lines = day_file.read_text().splitlines()
    assert len(first_lines) == 5

    # Simulate a retry after a mid-run failure (e.g. rollup/verify throwing):
    # re-running the import must rewrite, not append, the day file.
    migrate.import_raw_jobs(db)
    second_lines = day_file.read_text().splitlines()
    assert len(second_lines) == 5, "retry must not double the line count"
    assert second_lines == first_lines, "retry must produce a byte-identical file"


def test_import_raw_jobs_falls_back_when_start_is_unusable(tmp_data_dir):
    """A row whose start is the literal 'None'/'Unknown' sacct placeholder must
    fall back to the next parseable date, never create a day dir named after
    the placeholder (rollup.py only ingests real YYYY-MM-DD dirs, so such rows
    silently vanish and break the reconcile)."""
    db = tmp_data_dir / "raw_jobs.db"
    _make_raw_jobs(db, 1)                                   # dated row -> 2026-07-20
    _insert_row(db, "70000001", "2026-07-18T09:00:00", "None", "2026-07-19T10:00:00")
    _insert_row(db, "70000002", "Unknown", "2026-07-17T08:00:00", "Unknown")
    _insert_row(db, "70000003", "Unknown", "None", "2026-07-16T07:00:00")

    report = migrate.import_raw_jobs(db)
    assert report["written"] == 4
    assert report["skipped_no_date"] == 0

    ti = paths.telemetry_imported_dir()
    days = sorted(d.name for d in ti.iterdir() if d.is_dir())
    assert days == ["2026-07-16", "2026-07-17", "2026-07-18", "2026-07-20"]
    for junk in ("None", "Unknown", "0000-00-00"):
        assert not (ti / junk).exists(), f"day dir named {junk!r} must never be written"

    # start missing -> submit's day; submit unusable -> start's day; only end -> end's day
    assert json.loads((ti / "2026-07-18" / "task_runs.jsonl").read_text())["job_id"] == "70000001"
    assert json.loads((ti / "2026-07-17" / "task_runs.jsonl").read_text())["job_id"] == "70000002"
    assert json.loads((ti / "2026-07-16" / "task_runs.jsonl").read_text())["job_id"] == "70000003"

    # placeholders must not survive into the record as "NoneZ"/"UnknownZ"
    rec = json.loads((ti / "2026-07-18" / "task_runs.jsonl").read_text())
    assert rec["start"] is None


def test_import_raw_jobs_skips_and_counts_undateable_rows(tmp_data_dir):
    """A row with no usable date at all is excluded from the import AND from the
    reconcile expectation, and is reported as an explicit skip."""
    db = tmp_data_dir / "raw_jobs.db"
    _make_raw_jobs(db, 2)
    _insert_row(db, "70000009", "Unknown", "None", None)

    report = migrate.import_raw_jobs(db)
    assert report["written"] == 2, "undateable row must not be imported"
    assert report["skipped_no_date"] == 1
    ti = paths.telemetry_imported_dir()
    assert sorted(d.name for d in ti.iterdir() if d.is_dir()) == ["2026-07-20"]


def test_import_raw_jobs_purges_stale_junk_day_dirs(tmp_data_dir):
    """Re-running after a partial migration must clean up the None/Unknown day
    dirs the previous (buggy) run left behind, so telemetry-imported/ holds only
    real days and verify() counts exactly what rollup.py ingested."""
    ti = paths.telemetry_imported_dir()
    for junk in ("None", "Unknown"):
        (ti / junk).mkdir(parents=True)
        (ti / junk / "task_runs.jsonl").write_text('{"job_id": "stale"}\n')
    (ti / "2026-07-01").mkdir(parents=True)
    (ti / "2026-07-01" / "task_runs.jsonl").write_text('{"job_id": "keep"}\n')

    db = tmp_data_dir / "raw_jobs.db"
    _make_raw_jobs(db, 1)
    migrate.import_raw_jobs(db)

    assert not (ti / "None").exists()
    assert not (ti / "Unknown").exists()
    assert (ti / "2026-07-01" / "task_runs.jsonl").exists(), "real days must be kept"


def test_import_snapshot_is_idempotent_on_retry(tmp_data_dir):
    csv = tmp_data_dir / "snapshot.csv"
    csv.write_text(
        "timestamp_utc,gpu_running,gpu_pending,gpu_preempt_running,gpu_preempt_pending,"
        "total_nodes,free_nodes,gpu_types_free\n"
        "2026-07-19 14:00:00,10,5,2,1,145,20,a100:4\n")
    day_file = paths.telemetry_imported_dir() / "2026-07-19" / "resource_state.jsonl"

    migrate.import_snapshot(csv)
    first_lines = day_file.read_text().splitlines()
    assert len(first_lines) == 1

    migrate.import_snapshot(csv)
    second_lines = day_file.read_text().splitlines()
    assert len(second_lines) == 1, "retry must not double the line count"
    assert second_lines == first_lines, "retry must produce a byte-identical file"


def test_import_snapshot_writes_resource_state(tmp_data_dir):
    csv = tmp_data_dir / "snapshot.csv"
    csv.write_text(
        "timestamp_utc,gpu_running,gpu_pending,gpu_preempt_running,gpu_preempt_pending,"
        "total_nodes,free_nodes,gpu_types_free\n"
        "2026-07-19 14:00:00,10,5,2,1,145,20,a100:4\n")
    assert migrate.import_snapshot(csv) == 1
    day = paths.telemetry_imported_dir() / "2026-07-19" / "resource_state.jsonl"
    rec = json.loads(day.read_text().splitlines()[0])
    assert rec["kind"] == "partition" and rec["resource_id"] == "gpu"
    assert rec["ts"] == "2026-07-19T14:00:00Z"
    assert not (paths.telemetry_dir() / "2026-07-19").exists()


def test_seed_config_takes_max_capacity(tmp_data_dir):
    # a GPU project already recorded a100=157; the old profile has the clobbered 40
    cc.write_config({"gpu_fleet": {"a100": {"total_accessible": 157,
                                            "observed_utc": "2026-07-21T00:00:00Z"}}},
                    writer="esim")
    profile = tmp_data_dir / "cluster-profile.md"
    profile.write_text("# Unity Cluster Profile\n\n## cluster-intel config\n"
                       "- GPU capacity: a100=40 l40s=16\n")
    seeded = migrate.seed_config(profile)
    assert seeded["gpu_fleet"]["a100"]["total_accessible"] == 157, \
        "seeding must take the max, never the clobbered 40"


def test_seed_config_reads_heading_style_gpu_capacity(tmp_data_dir):
    """The real profile writes GPU capacity as a '## ' HEADING (no colon) with the
    `name=count · name=count` payload wrapped over the FOLLOWING line(s)."""
    profile = tmp_data_dir / "cluster-profile.md"
    profile.write_text(
        "# Test Cluster Profile\n\n"
        "## Partitions\n"
        "| Partition | Kind |\n|---|---|\n| `gpu` | GPU |\n\n"
        "## GPU capacity (whole cluster, `sinfo` GPUs-per-type x nodes)\n"
        "gtx_aa=157 · gtx_bb=108 · 3080_ti=88 ·\n"
        "gtx_dd=64 · 4090_ti=303 · gtx_ee=2\n"
        "- **bf16-capable (sm_80+):** gtx_aa, gtx_bb. Others lack bf16.\n\n"
        "## cluster-intel config\n"
        "- SACCT_SCOPE: `-a` (cluster-wide sacct works).\n"
        "- GPU capacity denominators (for utilization %): see the line above.\n")

    seeded = migrate.seed_config(profile)
    fleet = seeded["gpu_fleet"]
    assert set(fleet) == {"gtx_aa", "gtx_bb", "3080_ti", "gtx_dd", "4090_ti", "gtx_ee"}
    assert fleet["gtx_aa"]["total_accessible"] == 157
    assert fleet["gtx_dd"]["total_accessible"] == 64, "wrapped payload line must be read"
    assert fleet["gtx_ee"]["total_accessible"] == 2
    # digit-leading names must stay whole, not collapse to a shared "_ti" key
    assert fleet["3080_ti"]["total_accessible"] == 88
    assert fleet["4090_ti"]["total_accessible"] == 303


def test_seed_config_still_reads_single_line_gpu_capacity(tmp_data_dir):
    profile = tmp_data_dir / "cluster-profile.md"
    profile.write_text("## cluster-intel config\n- GPU capacity: gtx_aa=40 gtx_bb=16\n")
    fleet = migrate.seed_config(profile)["gpu_fleet"]
    assert fleet["gtx_aa"]["total_accessible"] == 40
    assert fleet["gtx_bb"]["total_accessible"] == 16


def test_archive_copies_without_deleting(tmp_data_dir):
    (tmp_data_dir / "cluster-profile.md").write_text("profile")
    (tmp_data_dir / "raw_jobs.db").write_text("db")
    (tmp_data_dir / "analysis").mkdir()
    (tmp_data_dir / "analysis" / "usage.db").write_text("u")
    migrate.archive(stamp="2026-07-22")
    arc = paths.archive_dir() / "2026-07-22"
    assert (arc / "cluster-profile.md").read_text() == "profile"
    assert (arc / "analysis" / "usage.db").read_text() == "u"
    assert (tmp_data_dir / "cluster-profile.md").exists(), "archive must not delete originals"


def test_full_run_reconciles_and_builds_summaries(tmp_data_dir):
    _make_raw_jobs(tmp_data_dir / "raw_jobs.db", 7)
    (tmp_data_dir / "snapshot.csv").write_text(
        "timestamp_utc,gpu_running,gpu_pending,gpu_preempt_running,gpu_preempt_pending,"
        "total_nodes,free_nodes,gpu_types_free\n2026-07-19 14:00:00,10,5,2,1,145,20,a100:4\n")
    (tmp_data_dir / "cluster-profile.md").write_text(
        "## cluster-intel config\n- GPU capacity: a100=157\n")

    report = migrate.run(stamp="2026-07-22")
    assert report["raw_jobs"] == report["task_run_rows"] == 7
    con = sqlite3.connect(paths.summaries_db())
    n = con.execute("SELECT SUM(n) FROM task_profile").fetchone()[0]
    con.close()
    assert n == 7, "every imported task run must reconcile into task_profile"
    # originals retired, archive kept
    assert not (tmp_data_dir / "raw_jobs.db").exists()
    assert (paths.archive_dir() / "2026-07-22" / "raw_jobs.db").exists()
    # the rsync mirror must never receive migrated data: a later
    # `sync-telemetry.sh --delete` pull must not be able to wipe it.
    assert not paths.telemetry_dir().exists() or not (paths.telemetry_dir() / "2026-07-19").exists()


def test_full_run_reconciles_with_undateable_rows(tmp_data_dir):
    """End-to-end: placeholder-dated rows land in a real day and undateable rows
    are reported as skips, so imported rows == task_run rows exactly."""
    db = tmp_data_dir / "raw_jobs.db"
    _make_raw_jobs(db, 3)
    _insert_row(db, "70000001", "2026-07-18T09:00:00", "None", "Unknown")
    _insert_row(db, "70000009", "Unknown", "None", None)
    (tmp_data_dir / "cluster-profile.md").write_text(
        "## GPU capacity (whole cluster)\ngtx_aa=157\n")

    report = migrate.run(stamp="2026-07-22")
    assert report["skipped_no_date"] == 1
    assert report["raw_jobs"] == report["task_run_rows"] == 4
    con = sqlite3.connect(paths.summaries_db())
    days = sorted(r[0] for r in con.execute("SELECT DISTINCT day_utc FROM task_run"))
    con.close()
    assert days == ["2026-07-18", "2026-07-20"]


def test_run_recovers_from_a_partially_failed_previous_run(tmp_data_dir):
    """Re-run after a reconcile failure: archive/ already exists, telemetry-imported/
    is already populated (including junk day dirs), summaries.db and
    cluster-config.json already exist. The re-run must reconcile and retire."""
    db = tmp_data_dir / "raw_jobs.db"
    _make_raw_jobs(db, 3)
    _insert_row(db, "70000001", "2026-07-18T09:00:00", "None", "Unknown")
    (tmp_data_dir / "cluster-profile.md").write_text(
        "## GPU capacity (whole cluster)\ngtx_aa=157\n")

    # leftovers of the failed run
    ti = paths.telemetry_imported_dir()
    (ti / "None").mkdir(parents=True)
    (ti / "None" / "task_runs.jsonl").write_text('{"job_id": "70000001"}\n')
    (ti / "2026-07-20").mkdir(parents=True)
    (ti / "2026-07-20" / "task_runs.jsonl").write_text('{"job_id": "stale"}\n')
    (paths.archive_dir() / "2026-07-22").mkdir(parents=True)
    cc.write_config({"gpu_fleet": {"gtx_aa": {"total_accessible": 157,
                                              "observed_utc": "2026-07-21T00:00:00Z"}}},
                    writer="esim")

    report = migrate.run(stamp="2026-07-22")
    assert report["raw_jobs"] == report["task_run_rows"] == 4
    assert not (ti / "None").exists()
    assert not (tmp_data_dir / "raw_jobs.db").exists(), "originals retired after reconcile"
    assert (paths.archive_dir() / "2026-07-22" / "raw_jobs.db").exists()


def test_verify_does_not_overcount_on_mirror_imported_day_overlap(tmp_data_dir):
    """rollup.py's mirror-wins rule means an imported day shadowed by a mirror
    day of the same name contributes NOTHING from telemetry-imported/ to
    summaries.db — rollup reads the mirror's task_runs.jsonl for that day
    instead. verify()'s expected count must follow the exact same
    day-selection rollup.py uses (mirror wins whole-day), not blindly sum
    every telemetry-imported/ line, or an overlap always false-mismatches.

    Real stores can't overlap today (migration runs before any live sync
    populates telemetry/); this reproduces the overlap directly as a
    correctness guard.
    """
    ti = paths.telemetry_imported_dir()
    tm = paths.telemetry_dir()

    # Imported-only day: both rows are actually consumed by rollup.
    (ti / "2026-07-10").mkdir(parents=True)
    (ti / "2026-07-10" / "task_runs.jsonl").write_text(
        '{"job_id": "imp-1"}\n{"job_id": "imp-2"}\n')

    # Overlapping day: imported side has 3 (shadowed) rows; the mirror side
    # has a different row count (1) and is what rollup actually ingests.
    (ti / "2026-07-11").mkdir(parents=True)
    (ti / "2026-07-11" / "task_runs.jsonl").write_text(
        '{"job_id": "shadowed-1"}\n{"job_id": "shadowed-2"}\n{"job_id": "shadowed-3"}\n')
    (tm / "2026-07-11").mkdir(parents=True)
    (tm / "2026-07-11" / "task_runs.jsonl").write_text('{"job_id": "mirror-1"}\n')

    migrate.rollup.run()

    report = migrate.verify()
    assert report["task_run_rows"] == 3, \
        "2 imported-only rows + rollup's 1 mirror-day row, never the shadowed 3"
    assert report["imported"] == 3
    assert report["imported"] == report["task_run_rows"]


def test_run_declines_while_sync_lock_is_held(tmp_data_dir):
    _make_raw_jobs(tmp_data_dir / "raw_jobs.db", 7)
    (tmp_data_dir / "snapshot.csv").write_text(
        "timestamp_utc,gpu_running,gpu_pending,gpu_preempt_running,gpu_preempt_pending,"
        "total_nodes,free_nodes,gpu_types_free\n2026-07-19 14:00:00,10,5,2,1,145,20,a100:4\n")
    (tmp_data_dir / "cluster-profile.md").write_text(
        "## cluster-intel config\n- GPU capacity: a100=157\n")

    paths.locks_dir().mkdir(parents=True, exist_ok=True)
    lock_path = paths.sync_lock()
    lock_fh = open(lock_path, "w")
    try:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        try:
            migrate.run(stamp="2026-07-22")
            assert False, "migrate.run must not proceed while sync.lock is held"
        except RuntimeError as exc:
            assert "in progress" in str(exc)

        # migration must not have touched anything while declining
        assert not paths.summaries_db().exists()
        assert (tmp_data_dir / "raw_jobs.db").exists(), "originals must be untouched"
        assert not (paths.archive_dir() / "2026-07-22").exists()
    finally:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        lock_fh.close()

    # with the lock free, migration proceeds normally
    report = migrate.run(stamp="2026-07-22")
    assert report["raw_jobs"] == report["task_run_rows"] == 7
