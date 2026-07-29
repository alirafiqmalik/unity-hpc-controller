import sqlite3

from lib import paths, queries


def _seed(day, fully):
    con = sqlite3.connect(paths.summaries_db())
    con.execute("CREATE TABLE IF NOT EXISTS day_index("
                "day_utc TEXT PRIMARY KEY, slots_ingested INTEGER, rows_emitted INTEGER, "
                "events_promoted INTEGER, task_runs_promoted INTEGER, "
                "fully_summarised INTEGER, first_seen_utc TEXT, last_rollup_utc TEXT)")
    con.execute("INSERT OR REPLACE INTO day_index VALUES(?,?,?,?,?,?,?,?)",
                (day, 96, 96, 1, 1, fully, "x", "x"))
    con.commit()
    con.close()


def test_absent_db_is_not_fully_summarised(tmp_data_dir):
    assert queries.is_fully_summarised("2026-07-20") is False


def test_absent_day_row_is_not_fully_summarised(tmp_data_dir):
    _seed("2026-07-19", 1)
    assert queries.is_fully_summarised("2026-07-20") is False


def test_fully_summarised_day_is_true(tmp_data_dir):
    _seed("2026-07-20", 1)
    assert queries.is_fully_summarised("2026-07-20") is True


def test_incomplete_day_is_false(tmp_data_dir):
    _seed("2026-07-20", 0)
    assert queries.is_fully_summarised("2026-07-20") is False


def test_absent_table_is_not_fully_summarised(tmp_data_dir):
    con = sqlite3.connect(paths.summaries_db())
    con.execute("CREATE TABLE unrelated(x INTEGER)")
    con.commit()
    con.close()
    assert queries.is_fully_summarised("2026-07-20") is False


def test_corrupt_db_is_not_fully_summarised(tmp_data_dir):
    # A truncated/garbage summaries.db (e.g. from a crashed rollup write) must
    # fail safe to False, not raise — this helper gates raw deletion.
    db = paths.summaries_db()
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b"this is not a valid sqlite database")
    assert queries.is_fully_summarised("2026-07-20") is False
