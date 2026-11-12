"""Raw telemetry, a legacy archive, and table dumps for the Telemetry archive golden test.

The fixtures were written once by the code before the archive module existed:
    python3 -B tests/archive_golden.py --write
Never regenerate them with newer code; that would make the comparison circular.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "telemetry-archive"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "cluster-intel"))

import rollup  # noqa: E402

NOW = {"fresh": "2026-07-22T00:00:00Z", "extend": "2026-07-23T00:00:00Z",
       "legacy": "2026-07-22T00:00:00Z"}


def _jsonl(path: Path, records: list[dict], extra: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records) + extra)


def _slots(day, count, kind, rid, start=0, **fields):
    out = []
    for i in range(start, start + count):
        rec = {"ts": f"{day}T{i // 4:02d}:{(i % 4) * 15:02d}:{i % 3:02d}Z",
               "kind": kind, "resource_id": rid}
        rec.update({k: (v(i) if callable(v) else v) for k, v in fields.items()})
        out.append(rec)
    return out


def _run(job, state, day, **over):
    record = {"job_id": job, "state": state, "partition": "gpu", "gpu_type": "a100",
              "submit": f"{day}T01:00:00Z", "start": f"{day}T01:02:30Z", "end": None,
              "req": {"cpus": 4, "gpus": 1},
              "used": {"elapsed_s": 600.0, "cpu_eff_pct": None, "mem_eff_pct": None,
                       "max_rss_mb": None},
              "exit_code": None, "project": "llm", "skill": "run", "campaign": "study",
              "user": "alice", "account": "lab", "node_list": "gpu013", "job_name": "t",
              "qos": "normal", "constraints": "a100-80g", "accounting_version": 2}
    record.update(over)
    return record


def write_raw_a(data: Path) -> None:
    """First raw state: every rollup path from an empty archive."""
    mirror, imported, day = data / "telemetry", data / "telemetry-imported", "2026-07-20"
    resource = (
        _slots(day, 8, "gpu_type", "rtx_8000", alloc=lambda i: 0 if i in (2, 3, 4) else i, total=8)
        + _slots(day, 4, "gpu_type", "a100", alloc=3, total=4)
        + _slots(day, 6, "partition", "gpu", gpus_total=16, gpus_alloc=lambda i: i)
        + _slots(day, 6, "partition", "cpu", cpus_total=64, cpus_alloc=lambda i: 8 * i)
        + _slots(day, 5, "node", "gpu013", cpus_total=32, cpus_idle=lambda i: 32 - 4 * i)
        + _slots(day, 3, "storage", "work", start=40)
        + [{"kind": "gpu_type", "resource_id": "a100", "alloc": 1, "total": 4}])
    _jsonl(mirror / day / "resource_state.jsonl", resource, extra="{not json\n")
    _jsonl(mirror / day / "events.jsonl", [
        {"ts": f"{day}T00:30:00Z", "event": "node_state_change", "resource_id": "gpu013", "to": "down"},
        {"ts": f"{day}T00:30:00Z", "event": "node_state_change", "resource_id": "gpu013", "to": "down"},
        {"ts": f"{day}T00:45:00Z", "event": "node_state_change", "resource_id": "gpu013", "to": "idle"},
        {"ts": f"{day}T01:00:00Z", "event": "preemption", "job_id": "999", "partition": "gpu-preempt"},
        {"ts": None, "event": "note", "resource_id": None}])
    _jsonl(mirror / day / "task_runs.jsonl", [
        _run("1001", "RUNNING", day),
        _run("1002", "COMPLETED", day, partition="cpu", gpu_type=None, req={"cpus": 2},
             project=None, skill=None, campaign=None, end=f"{day}T01:12:30Z", exit_code=0,
             used={"elapsed_s": 600.0, "cpu_eff_pct": 12.5, "mem_eff_pct": 3.0, "max_rss_mb": 100.0}),
        _run("1003", "COMPLETED", day, gpu_type="RTX_8000", end=f"{day}T02:00:00Z", exit_code=0,
             used={"elapsed_s": 3450.0, "cpu_eff_pct": 40.0, "mem_eff_pct": 20.0, "max_rss_mb": 2048.0}),
        _run("1004", "FAILED", day, gpu_type=None, end=f"{day}T01:03:00Z", exit_code=1),
        _run("1005", "RUNNING", day, partition="gpu-preempt")], extra="garbage\n")
    _jsonl(mirror / "2026-07-17" / "resource_state.jsonl",
           _slots("2026-07-17", 4, "gpu_type", "l40s", alloc=2, total=8))
    _jsonl(imported / "2026-07-19" / "resource_state.jsonl",
           _slots("2026-07-19", 96, "gpu_type", "a100", alloc=lambda i: i % 5, total=4))
    _jsonl(imported / "2026-07-19" / "task_runs.jsonl",
           [_run("0901", "COMPLETED", "2026-07-19", exit_code=0, end="2026-07-19T03:00:00Z")])
    _jsonl(imported / "2026-07-18" / "task_runs.jsonl",
           [_run("0801", "TIMEOUT", "2026-07-18", exit_code=0, end="2026-07-18T03:00:00Z",
                 accounting_version=1)])


def write_raw_b(data: Path) -> None:
    """Second raw state on top of write_raw_a: upserts, overlap, and a pruned raw day."""
    mirror, day = data / "telemetry", "2026-07-20"
    _jsonl(mirror / day / "resource_state.jsonl", _slots(day, 2, "gpu_type", "a100", alloc=1, total=4))
    _jsonl(mirror / day / "task_runs.jsonl", [
        _run("1001", "COMPLETED", day, end=f"{day}T02:00:00Z", exit_code=0, accounting_version=3,
             used={"elapsed_s": 3450.0, "cpu_eff_pct": 55.5, "mem_eff_pct": 10.0, "max_rss_mb": 900.0}),
        {"job_id": "1003", "state": "COMPLETED", "partition": "gpu", "gpu_type": "rtx8000",
         "submit": f"{day}T01:00:00Z", "start": f"{day}T01:02:30Z", "end": f"{day}T02:00:00Z",
         "exit_code": 0, "used": {"elapsed_s": 3450.0}},
        _run("1004", "RUNNING", day, gpu_type=None)])
    (mirror / day / "events.jsonl").unlink()
    _jsonl(mirror / "2026-07-21" / "task_runs.jsonl",
           [_run("1005", "COMPLETED", "2026-07-21", partition="gpu-preempt",
                 end="2026-07-21T05:00:00Z", exit_code=0)])
    _jsonl(mirror / "2026-07-21" / "resource_state.jsonl",
           _slots("2026-07-21", 3, "gpu_type", "a100", alloc=4, total=4))
    _jsonl(mirror / "2026-07-19" / "task_runs.jsonl", [_run("0902", "CANCELLED by 123", "2026-07-19")])
    shutil.rmtree(mirror / "2026-07-17")


# An archive written by a rollup before `partition`, `campaign`, and
# `task_accounting` existed. Hand-written on purpose: it is old data.
LEGACY_ARCHIVE = """
CREATE TABLE hourly_resource(resource_kind TEXT, resource_id TEXT, hour_utc TEXT, util_min REAL, util_mean REAL, util_max REAL, util_p95 REAL, free_ratio REAL, samples INTEGER, PRIMARY KEY(resource_kind, resource_id, hour_utc));
CREATE TABLE daily_resource(resource_kind TEXT, resource_id TEXT, day_utc TEXT, free_seconds_total REAL, longest_free_window_s INTEGER, outage_count INTEGER, preemption_count INTEGER, samples INTEGER, PRIMARY KEY(resource_kind, resource_id, day_utc));
CREATE TABLE task_run(job_id TEXT PRIMARY KEY, project TEXT, skill TEXT, hardware TEXT, submit TEXT, start TEXT, "end" TEXT, elapsed_s REAL, wait_s REAL, cpu_eff REAL, mem_eff REAL, max_rss_mb REAL, state TEXT, exit_code INTEGER, day_utc TEXT);
CREATE TABLE task_profile(project TEXT, skill TEXT, hardware TEXT, n INTEGER, runtime_p50 REAL, runtime_p90 REAL, runtime_p95 REAL, wait_p50 REAL, wait_p90 REAL, cpu_eff_p50 REAL, mem_eff_p50 REAL, max_rss_p95 REAL, success_rate REAL, PRIMARY KEY(project, skill, hardware));
CREATE TABLE events(ts TEXT, event TEXT, resource_id TEXT, job_id TEXT, detail TEXT, PRIMARY KEY(ts, event, resource_id, job_id, detail));
CREATE TABLE day_index(day_utc TEXT PRIMARY KEY, slots_ingested INTEGER, rows_emitted INTEGER, events_promoted INTEGER, task_runs_promoted INTEGER, fully_summarised INTEGER, first_seen_utc TEXT, last_rollup_utc TEXT);
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
INSERT INTO task_run VALUES('0001','unknown','unknown','a100','2026-07-01T00:00:00Z','2026-07-01T00:10:00Z','2026-07-01T01:00:00Z',3000.0,600.0,NULL,NULL,NULL,'COMPLETED',0,'2026-07-01');
INSERT INTO day_index VALUES('2026-07-01',10,10,1,1,1,'2026-07-02T00:00:00Z','2026-07-02T00:00:00Z');
INSERT INTO meta VALUES('schema_version','1');
INSERT INTO meta VALUES('raw_pruned_through','2026-07-01');
"""


def write_legacy_archive(db: Path) -> None:
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    try:
        con.executescript(LEGACY_ARCHIVE)
    finally:
        con.close()


def dump(db: Path) -> dict:
    """Schema and every row of every table, with rowid, in rowid order."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        schema = [list(r) for r in con.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name")]
        tables = {}
        for (name,) in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
            cur = con.execute(f'SELECT rowid, * FROM "{name}" ORDER BY rowid')
            tables[name] = {"columns": [d[0] for d in cur.description],
                            "rows": [list(r) for r in cur]}
    finally:
        con.close()
    return {"schema": schema, "tables": tables}


def canonical(value: dict) -> str:
    """JSON text that tells 1 from 1.0 and keeps every float exactly."""
    return json.dumps(value, sort_keys=True)


def rollup_at(now: str) -> None:
    """One rollup of $UNITY_HPC_DATA with the clock fixed at `now`."""
    saved = rollup._now_iso
    rollup._now_iso = lambda: now
    try:
        rollup.run()
    finally:
        rollup._now_iso = saved


def _write_fixtures(work: Path) -> None:
    golden_path, phase1 = FIXTURES / "golden.json", FIXTURES / "phase1-before.sqlite"
    if golden_path.exists() or phase1.exists():
        raise SystemExit("fixtures exist; they are written once, by the code before the change")
    golden = {}
    a, legacy = work / "a", work / "legacy"
    write_raw_a(a)
    os.environ["UNITY_HPC_DATA"] = str(a)
    rollup_at(NOW["fresh"])
    golden["fresh"] = dump(a / "summaries.db")
    FIXTURES.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(a / "summaries.db", phase1)
    write_raw_b(a)
    rollup_at(NOW["extend"])
    golden["extend"] = dump(a / "summaries.db")
    write_raw_a(legacy)
    write_legacy_archive(legacy / "summaries.db")
    os.environ["UNITY_HPC_DATA"] = str(legacy)
    rollup_at(NOW["legacy"])
    golden["legacy"] = dump(legacy / "summaries.db")
    golden_path.write_text(json.dumps(golden, sort_keys=True, indent=1) + "\n")


if __name__ == "__main__":
    if sys.argv[1:] != ["--write"]:
        raise SystemExit("usage: python3 -B tests/archive_golden.py --write")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        _write_fixtures(Path(tmp))
