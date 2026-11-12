"""The Telemetry archive: `summaries.db`.

This module owns the schema and the `ensure` step, the dated tables and how a
day's rows are selected (`task_accounting` rows go with their day's `task_run`
rows), the content of a per-day summary backup and the prune that local
retention uses, the `task_profile` rebuild, and the reads that production
uses. Rollup computes rows from raw days and is the one other writer.
Readers open the database read-only. Stdlib only; imports no controller or
rollup code.
"""

from __future__ import annotations

import json
import sqlite3
import statistics

from lib import paths


SCHEMA = """
CREATE TABLE IF NOT EXISTS hourly_resource(
  resource_kind TEXT, resource_id TEXT, hour_utc TEXT,
  util_min REAL, util_mean REAL, util_max REAL, util_p95 REAL,
  free_ratio REAL, samples INTEGER,
  PRIMARY KEY(resource_kind, resource_id, hour_utc));
CREATE TABLE IF NOT EXISTS daily_resource(
  resource_kind TEXT, resource_id TEXT, day_utc TEXT,
  free_seconds_total REAL, longest_free_window_s INTEGER,
  outage_count INTEGER, preemption_count INTEGER, samples INTEGER,
  PRIMARY KEY(resource_kind, resource_id, day_utc));
CREATE TABLE IF NOT EXISTS task_run(
  job_id TEXT PRIMARY KEY, project TEXT, campaign TEXT, skill TEXT, hardware TEXT,
  submit TEXT, start TEXT, "end" TEXT, elapsed_s REAL, wait_s REAL,
  cpu_eff REAL, mem_eff REAL, max_rss_mb REAL, state TEXT,
  exit_code INTEGER, day_utc TEXT, partition TEXT);
CREATE TABLE IF NOT EXISTS task_profile(
  project TEXT, skill TEXT, hardware TEXT, n INTEGER,
  runtime_p50 REAL, runtime_p90 REAL, runtime_p95 REAL,
  wait_p50 REAL, wait_p90 REAL, cpu_eff_p50 REAL, mem_eff_p50 REAL,
  max_rss_p95 REAL, success_rate REAL,
  PRIMARY KEY(project, skill, hardware));
CREATE TABLE IF NOT EXISTS task_accounting(
  job_id TEXT PRIMARY KEY, user TEXT, account TEXT, node_list TEXT,
  job_name TEXT, qos TEXT, constraints TEXT, accounting_version INTEGER,
  details_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS task_accounting_user ON task_accounting(user);
CREATE INDEX IF NOT EXISTS task_accounting_account ON task_accounting(account);
CREATE TABLE IF NOT EXISTS events(
  ts TEXT, event TEXT, resource_id TEXT, job_id TEXT, detail TEXT,
  PRIMARY KEY(ts, event, resource_id, job_id, detail));
CREATE TABLE IF NOT EXISTS day_index(
  day_utc TEXT PRIMARY KEY, slots_ingested INTEGER, rows_emitted INTEGER,
  events_promoted INTEGER, task_runs_promoted INTEGER,
  fully_summarised INTEGER, first_seen_utc TEXT, last_rollup_utc TEXT);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


# The dated tables and the column that holds each row's UTC day.
DATED_TABLES = {
    "hourly_resource": "hour_utc",
    "daily_resource": "day_utc",
    "task_run": "day_utc",
    "events": "ts",
    "day_index": "day_utc",
}


def ensure(conn) -> None:
    """Create missing tables and add task_run columns an older rollup lacked.

    On a current archive this writes nothing.
    """
    conn.executescript(SCHEMA)
    have = {r[1] for r in conn.execute("PRAGMA table_info(task_run)")}
    if "partition" not in have:
        conn.execute("ALTER TABLE task_run ADD COLUMN partition TEXT")
    if "campaign" not in have:
        conn.execute("ALTER TABLE task_run ADD COLUMN campaign TEXT")


def pctl(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return round(float(s[0]), 6)
    pos = q * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (pos - lo), 6)


def rebuild_profile(conn) -> None:
    """Recompute task_profile from every task_run row of `conn`."""
    groups: dict[tuple, list[dict]] = {}
    for r in conn.execute("SELECT project, skill, hardware, elapsed_s, wait_s, "
                          "cpu_eff, mem_eff, max_rss_mb, state, exit_code FROM task_run"):
        groups.setdefault((r[0], r[1], r[2]), []).append({
            "elapsed": r[3], "wait": r[4], "cpu": r[5], "mem": r[6],
            "rss": r[7], "state": r[8], "rc": r[9]})
    for (proj, skill, hw), rows in sorted(groups.items()):
        rt = [x["elapsed"] for x in rows if x["elapsed"] is not None]
        wt = [x["wait"] for x in rows if x["wait"] is not None]
        cpu = [x["cpu"] for x in rows if x["cpu"] is not None]
        mem = [x["mem"] for x in rows if x["mem"] is not None]
        rss = [x["rss"] for x in rows if x["rss"] is not None]
        succ = [1 if (x["state"] == "COMPLETED" and x["rc"] == 0) else 0 for x in rows]
        conn.execute(
            "INSERT INTO task_profile VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(project,skill,hardware) DO UPDATE SET n=excluded.n, "
            "runtime_p50=excluded.runtime_p50, runtime_p90=excluded.runtime_p90, "
            "runtime_p95=excluded.runtime_p95, wait_p50=excluded.wait_p50, "
            "wait_p90=excluded.wait_p90, cpu_eff_p50=excluded.cpu_eff_p50, "
            "mem_eff_p50=excluded.mem_eff_p50, max_rss_p95=excluded.max_rss_p95, "
            "success_rate=excluded.success_rate",
            (proj, skill, hw, len(rows), pctl(rt, 0.5), pctl(rt, 0.9), pctl(rt, 0.95),
             pctl(wt, 0.5), pctl(wt, 0.9), pctl(cpu, 0.5), pctl(mem, 0.5),
             pctl(rss, 0.95), round(statistics.fmean(succ), 6) if succ else None))


def _accounting_of_days(count: int) -> str:
    """Select accounting whose job has a task_run on the given days."""
    return ("job_id IN (SELECT job_id FROM task_run WHERE substr(day_utc,1,10) IN ("
            + ",".join("?" * count) + "))")


def _has_accounting(con) -> bool:
    """An archive that predates enriched accounting has no such table."""
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_accounting'"
    ).fetchone() is not None


def _copy_rows(archive, rows, table) -> int:
    insert = f"INSERT INTO {table} VALUES({','.join('?' * len(rows.description))})"
    count = 0
    while batch := rows.fetchmany(1000):
        archive.executemany(insert, batch)
        count += len(batch)
    return count


def dated_days_before(con, cutoff: str) -> set[str]:
    """Every distinct day value before `cutoff` in the dated tables."""
    found: set[str] = set()
    for table, column in DATED_TABLES.items():
        rows = con.execute(
            f"SELECT DISTINCT substr({column},1,10) FROM {table} "
            f"WHERE substr({column},1,10) < ?", (cutoff,),
        )
        found.update(day for (day,) in rows)
    return found


def write_day(live, archive, day: str, orphan_ids=()) -> int:
    """Copy `day` from `live` into the empty per-day database `archive`.

    Copies the day's rows of every dated table, the day's accounting rows and
    the accounting rows named in `orphan_ids`, the live meta with
    `archive_day`, and a profile of the day's task rows. Returns the number of
    dated and accounting rows copied. The caller commits.
    """
    count = 0
    for table, column in DATED_TABLES.items():
        schema = live.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()[0]
        archive.execute(schema)
        rows = live.execute(
            f"SELECT * FROM {table} WHERE substr({column},1,10)=?", (day,),
        )
        count += _copy_rows(archive, rows, table)
    if _has_accounting(live):
        archive.execute(live.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='task_accounting'"
        ).fetchone()[0])
        count += _copy_rows(archive, live.execute(
            f"SELECT * FROM task_accounting WHERE {_accounting_of_days(1)}", (day,)
        ), "task_accounting")
        for start in range(0, len(orphan_ids), 500):
            chunk = orphan_ids[start:start + 500]
            marks = ",".join("?" * len(chunk))
            count += _copy_rows(archive, live.execute(
                f"SELECT * FROM task_accounting WHERE job_id IN ({marks})", chunk
            ), "task_accounting")
    for table in ("task_profile", "meta"):
        schema = live.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()[0]
        archive.execute(schema)
    archive.executemany("INSERT INTO meta VALUES(?,?)", live.execute(
        "SELECT key, value FROM meta"
    ))
    archive.execute(
        "INSERT OR REPLACE INTO meta VALUES('archive_day',?)", (day,)
    )
    rebuild_profile(archive)
    return count


def orphan_accounting(con) -> set[str]:
    """Accounting job ids that have no task_run row."""
    if not _has_accounting(con):
        return set()
    return {job for (job,) in con.execute(
        "SELECT job_id FROM task_accounting WHERE job_id NOT IN (SELECT job_id FROM task_run)"
    )}


def task_run_job_ids(con) -> set[str]:
    """Every task_run job id (used on a decompressed per-day backup)."""
    return {job for (job,) in con.execute("SELECT job_id FROM task_run")}


def prune_days(con, days: list[str], orphan_ids=()) -> None:
    """Delete `days` and their accounting, then rebuild the profile. The caller commits."""
    accounting = _has_accounting(con)
    for batch_start in range(0, len(days), 500):
        batch = days[batch_start:batch_start + 500]
        marks = ",".join("?" * len(batch))
        if accounting:
            # Before task_run: the selection needs that day's task rows.
            con.execute(f"DELETE FROM task_accounting WHERE {_accounting_of_days(len(batch))}", batch)
        for table, column in DATED_TABLES.items():
            con.execute(
                f"DELETE FROM {table} WHERE substr({column},1,10) IN ({marks})",
                batch,
            )
    for start in range(0, len(orphan_ids) if accounting else 0, 500):
        chunk = orphan_ids[start:start + 500]
        marks = ",".join("?" * len(chunk))
        con.execute(f"DELETE FROM task_accounting WHERE job_id IN ({marks}) AND job_id NOT IN (SELECT job_id FROM task_run)", chunk)
    con.execute("DELETE FROM task_profile")
    # task_profile is derived from task_run. Rebuild it after the cut.
    rebuild_profile(con)


def is_fully_summarised(day: str) -> bool:
    """True iff summaries.db has a day_index row for `day` with fully_summarised=1."""
    db = paths.summaries_db()
    if not db.exists():
        return False
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            row = con.execute(
                "SELECT fully_summarised FROM day_index WHERE day_utc=?", (day,)
            ).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        # Missing table, corrupt/truncated DB, or any open failure: this helper
        # gates deletion, so fail safe to "not summarised" rather than raise.
        return False
    return bool(row and row[0])


def historical_accounting(*, user=None, account=None, partition=None, gpu_type=None,
                          since=None, until=None, limit=100, offset=0) -> list[dict]:
    """Read a bounded history page. Time filters use UTC Slurm Submit timestamps."""
    db = paths.summaries_db()
    if not db.exists():
        return []
    limit, offset = min(max(int(limit), 1), 1000), max(int(offset), 0)
    conditions, arguments = [], []
    for column, value in (("a.user", user), ("a.account", account),
                          ("t.partition", partition), ("t.hardware", gpu_type)):
        if value is not None:
            conditions.append(f"{column}=?")
            arguments.append(value)
    for operator, value in ((">=", since), ("<", until)):
        if value is not None:
            conditions.append(f"t.submit{operator}?")
            arguments.append(value)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "SELECT a.details_json FROM task_accounting a JOIN task_run t USING(job_id)"
                + where + " ORDER BY t.submit DESC,a.job_id LIMIT ? OFFSET ?",
                [*arguments, limit, offset],
            ).fetchall()
        finally:
            con.close()
        return [json.loads(raw) for (raw,) in rows]
    except (sqlite3.Error, ValueError):
        return []


def completed_runs(partition, hardware):
    """(wait_s, elapsed_s, max_rss_mb) of the newest 500 COMPLETED runs of 30 days.

    None when summaries.db is absent or task_run lacks the needed columns.
    A SQLite error propagates to the caller.
    """
    database = paths.summaries_db()
    if not database.is_file():
        return None
    con = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        fields = {row[1] for row in con.execute("PRAGMA table_info(task_run)")}
        if not {"partition", "hardware", "wait_s", "elapsed_s", "state"} <= fields:
            return None
        rss = "max_rss_mb" if "max_rss_mb" in fields else "NULL"
        date_filter = " AND day_utc>=date('now','-30 days')" if "day_utc" in fields else ""
        return con.execute(f"SELECT wait_s,elapsed_s,{rss} FROM task_run WHERE partition=? AND hardware=? AND state='COMPLETED'{date_filter} ORDER BY rowid DESC LIMIT 500", (partition, hardware)).fetchall()
    finally:
        con.close()

def read_meta() -> dict | None:
    """The meta key/value pairs; None when summaries.db is absent or unreadable."""
    db = paths.summaries_db()
    if not db.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return dict(con.execute("SELECT key, value FROM meta").fetchall())
        finally:
            con.close()
    except sqlite3.Error:
        return None
