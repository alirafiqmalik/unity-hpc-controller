import sqlite3

from lib import paths, queries


def _seed_task_run(rows):
    db = paths.summaries_db()
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.execute(
        'CREATE TABLE task_run(job_id TEXT PRIMARY KEY, project TEXT, skill TEXT, '
        'hardware TEXT, submit TEXT, start TEXT, "end" TEXT, elapsed_s REAL, '
        'wait_s REAL, cpu_eff REAL, mem_eff REAL, max_rss_mb REAL, state TEXT, '
        'exit_code INTEGER, day_utc TEXT)')
    con.executemany(
        'INSERT INTO task_run(job_id, hardware, elapsed_s, wait_s, cpu_eff, '
        'mem_eff, state) VALUES(?,?,?,?,?,?,?)', rows)
    con.commit()
    con.close()


def test_correlation_scopes_to_the_given_job_ids(tmp_data_dir):
    _seed_task_run([
        ("A", "a100", 100.0, 10.0, 50.0, 40.0, "COMPLETED"),
        ("B", "a100", 200.0, 20.0, None, None, "COMPLETED"),
        ("C", "l40s", 999.0, 5.0, 10.0, 10.0, "FAILED"),  # not ours
    ])
    got = {r["job_id"]: r for r in queries.task_runs_for_jobs(["A", "B"])}
    assert set(got) == {"A", "B"}                 # C excluded
    assert got["A"]["hardware"] == "a100"
    assert got["A"]["elapsed_s"] == 100.0


def test_task_runs_for_jobs_is_fail_safe_when_db_absent(tmp_data_dir):
    assert queries.task_runs_for_jobs(["A"]) == []   # no summaries.db, no raise


def test_task_runs_for_jobs_empty_input(tmp_data_dir):
    _seed_task_run([("A", "a100", 1.0, 1.0, 1.0, 1.0, "COMPLETED")])
    assert queries.task_runs_for_jobs([]) == []


def test_profile_aggregates_by_hardware_and_skips_none_eff(tmp_data_dir):
    _seed_task_run([
        ("A", "a100", 100.0, 10.0, 60.0, 40.0, "COMPLETED"),
        ("B", "a100", 300.0, 30.0, None, None, "COMPLETED"),  # eff None -> skipped
        ("D", "a100", 200.0, 20.0, 20.0, 20.0, "FAILED"),
    ])
    prof = {p["hardware"]: p for p in queries.project_hardware_profile(["A", "B", "D"])}
    a = prof["a100"]
    assert a["n"] == 3
    assert a["n_with_eff"] == 2                     # only A and D had eff
    assert a["runtime_p50"] == 200.0               # median of 100,200,300
    assert a["success_rate"] == round(2 / 3, 6)    # A,B completed; D failed
    assert a["cpu_eff_p50"] == 40.0                # median of 20,60 (B skipped)


def test_profile_handles_hardware_with_no_eff_at_all(tmp_data_dir):
    _seed_task_run([("A", "cpu", 50.0, 5.0, None, None, "COMPLETED")])
    p = queries.project_hardware_profile(["A"])[0]
    assert p["n_with_eff"] == 0
    assert p["cpu_eff_p50"] is None                # not 0
