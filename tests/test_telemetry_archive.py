"""The Telemetry archive module: rollup output, ensure, retention coverage, reads."""

import gzip
import json
import shutil
import sqlite3
from datetime import date

import pytest

import archive_golden
from archive_golden import FIXTURES, NOW, canonical, dump, rollup_at, write_raw_a, write_raw_b
from controller.http import Request, handle
from lib import local_retention, paths, telemetry_archive

GOLDEN = json.loads((FIXTURES / "golden.json").read_text())


@pytest.mark.parametrize("scenario", ["fresh", "extend_old", "extend_new", "legacy"])
def test_rollup_output_matches_the_archive_written_before_the_module(tmp_data_dir, scenario):
    db = paths.summaries_db()
    write_raw_a(tmp_data_dir)
    if scenario == "fresh":
        rollup_at(NOW["fresh"])
        expected = GOLDEN["fresh"]
    elif scenario == "extend_old":
        write_raw_b(tmp_data_dir)
        shutil.copyfile(FIXTURES / "phase1-before.sqlite", db)
        rollup_at(NOW["extend"])
        expected = GOLDEN["extend"]
    elif scenario == "extend_new":
        rollup_at(NOW["fresh"])
        write_raw_b(tmp_data_dir)
        rollup_at(NOW["extend"])
        expected = GOLDEN["extend"]
    else:
        archive_golden.write_legacy_archive(db)
        rollup_at(NOW["legacy"])
        expected = GOLDEN["legacy"]
    assert canonical(dump(db)) == canonical(expected)


@pytest.mark.parametrize("source", ["ensure", "old_rollup"])
def test_ensure_writes_nothing_on_a_current_archive(tmp_path, source):
    db = tmp_path / "summaries.db"
    if source == "ensure":
        con = sqlite3.connect(db)
        telemetry_archive.ensure(con)
        con.commit()
        con.close()
    else:
        shutil.copyfile(FIXTURES / "phase1-before.sqlite", db)
    before = db.read_bytes()
    con = sqlite3.connect(db)
    issued = []
    con.set_trace_callback(issued.append)
    telemetry_archive.ensure(con)
    assert con.total_changes == 0
    assert not con.in_transaction
    con.close()
    assert db.read_bytes() == before
    allowed = ("CREATE TABLE IF NOT EXISTS ", "CREATE INDEX IF NOT EXISTS ",
               "PRAGMA table_info(task_run)", "COMMIT")
    assert issued and all(s.strip().startswith(allowed) for s in issued), issued


def test_retention_moves_every_dated_table_and_its_accounting(tmp_data_dir, tmp_path):
    old, recent = "2026-05-01", "2026-09-01"
    con = sqlite3.connect(paths.summaries_db())
    telemetry_archive.ensure(con)
    for day in (old, recent):
        job = "job-" + day
        con.execute("INSERT INTO hourly_resource(resource_kind, resource_id, hour_utc) VALUES('gpu_type','a100',?)", (day + "T03:00:00Z",))
        con.execute("INSERT INTO daily_resource(resource_kind, resource_id, day_utc) VALUES('gpu_type','a100',?)", (day,))
        con.execute("INSERT INTO task_run(job_id, project, skill, hardware, state, day_utc) VALUES(?,'p','s','a100','COMPLETED',?)", (job, day))
        con.execute("INSERT INTO events VALUES(?,'e','r','j','{}')", (day + "T04:00:00Z",))
        con.execute("INSERT INTO day_index(day_utc, fully_summarised) VALUES(?,1)", (day,))
        con.execute("INSERT INTO task_accounting(job_id, details_json) VALUES(?,'{}')", (job,))
    con.commit()
    tables = {name for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    day_linked = set(telemetry_archive.DATED_TABLES) | {"task_accounting"}
    assert tables == day_linked | {"task_profile", "meta"}, "a new table needs a retention rule"

    local_retention.run(90, today=date(2026, 9, 25))

    (summary,) = (local_retention._archive_root() / old).glob("summary-*.sqlite.gz")
    saved = tmp_path / "saved.sqlite"
    saved.write_bytes(gzip.decompress(summary.read_bytes()))

    def days(path):
        con = sqlite3.connect(path)
        try:
            out = {table: [row[0] for row in con.execute(f"SELECT substr({column},1,10) FROM {table}")]
                   for table, column in telemetry_archive.DATED_TABLES.items()}
            out["task_accounting"] = [row[0][4:] for row in con.execute("SELECT job_id FROM task_accounting")]
        finally:
            con.close()
        return out

    assert days(saved) == {table: [old] for table in day_linked}
    assert days(paths.summaries_db()) == {table: [recent] for table in day_linked}


def test_readers_read_an_archive_written_before_the_module_read_only(tmp_data_dir, monkeypatch):
    shutil.copyfile(FIXTURES / "phase1-before.sqlite", paths.summaries_db())
    opened = []
    connect = sqlite3.connect

    def spy(target, *args, **kwargs):
        opened.append((str(target), kwargs.get("uri")))
        return connect(target, *args, **kwargs)

    monkeypatch.setattr(telemetry_archive.sqlite3, "connect", spy)
    assert telemetry_archive.is_fully_summarised("2026-07-19") is True
    assert telemetry_archive.is_fully_summarised("2026-07-20") is False
    assert [r["job_id"] for r in telemetry_archive.historical_accounting(gpu_type="rtx8000")] == ["1003"]
    assert telemetry_archive.completed_runs("gpu", "a100") == []
    assert telemetry_archive.read_meta() == {"schema_version": "1", "last_rollup_utc": NOW["fresh"]}
    assert len(opened) == 5
    assert all(target.startswith("file:") and target.endswith("?mode=ro") and uri
               for target, uri in opened)


def test_accounting_route_reads_through_the_archive(tmp_data_dir):
    write_raw_a(tmp_data_dir)
    rollup_at(NOW["fresh"])
    response = handle(Request("GET", "/api/v1/telemetry/accounting",
                              query={"gpu_type": ["rtx8000"], "limit": ["5"]}))
    assert response.status == 200
    assert [row["job_id"] for row in json.loads(response.body)["accounting"]] == ["1003"]


def _seed(day, fully):
    con = sqlite3.connect(paths.summaries_db())
    telemetry_archive.ensure(con)
    con.execute("INSERT OR REPLACE INTO day_index VALUES(?,?,?,?,?,?,?,?)",
                (day, 96, 96, 1, 1, fully, "x", "x"))
    con.commit()
    con.close()


def test_absent_db_is_not_fully_summarised(tmp_data_dir):
    assert telemetry_archive.is_fully_summarised("2026-07-20") is False


def test_absent_day_row_is_not_fully_summarised(tmp_data_dir):
    _seed("2026-07-19", 1)
    assert telemetry_archive.is_fully_summarised("2026-07-20") is False


def test_fully_summarised_day_is_true(tmp_data_dir):
    _seed("2026-07-20", 1)
    assert telemetry_archive.is_fully_summarised("2026-07-20") is True


def test_incomplete_day_is_false(tmp_data_dir):
    _seed("2026-07-20", 0)
    assert telemetry_archive.is_fully_summarised("2026-07-20") is False


def test_absent_table_is_not_fully_summarised(tmp_data_dir):
    con = sqlite3.connect(paths.summaries_db())
    con.execute("CREATE TABLE unrelated(x INTEGER)")
    con.commit()
    con.close()
    assert telemetry_archive.is_fully_summarised("2026-07-20") is False


def test_corrupt_db_is_not_fully_summarised(tmp_data_dir):
    # A truncated/garbage summaries.db (e.g. from a crashed rollup write) must
    # fail safe to False, not raise — this helper gates raw deletion.
    db = paths.summaries_db()
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b"this is not a valid sqlite database")
    assert telemetry_archive.is_fully_summarised("2026-07-20") is False
