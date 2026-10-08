#!/usr/bin/env python3
"""rollup.py — cumulative raw-telemetry -> summaries.db.

Reads telemetry/ AND telemetry-imported/ (mirror wins on whole-day overlap) and
UPSERTS summaries.db. A routine run never DELETEs (I9); --full-rebuild discards
prior summaries and is migration-only. Builds summaries.db.tmp then os.replace()
(I3). Serialised by flock on locks/sync.lock unless --no-lock (the sync driver
holds the lock for us). Stdlib only for byte-level determinism.

Note on project/skill: task_runs.project/skill are currently emitted as None
by the cluster-side collector, which has no way to know which plugin project
or skill submitted a given SLURM job. task_profile groups by
(project, skill, hardware) and tolerates None in either column today (an
"unknown" bucket) rather than crashing or fabricating values. Enrichment via
job-name tagging or campaign-DB correlation is a future task; the schema and
grouping already accommodate real values once they arrive.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import sqlite3
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths  # noqa: E402
from lib.cluster_config import canonical_gpu_type  # noqa: E402
from collector_parse import derive_hardware, is_terminal  # noqa: E402

SLOT_SECONDS = 900
FULLY_RATIO = 0.9
_DAY_GLOB = "20*"

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


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def slot_floor(ts: str) -> str:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    minute = (dt.minute // 15) * 15
    return dt.replace(minute=minute, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _util(rec: dict) -> float | None:
    kind = rec.get("kind")
    if kind == "gpu_type":
        tot, al = rec.get("total") or 0, rec.get("alloc") or 0
        return al / tot if tot else None
    if kind == "partition":
        gt, ga = rec.get("gpus_total") or 0, rec.get("gpus_alloc") or 0
        if gt:
            return ga / gt
        ct, ca = rec.get("cpus_total") or 0, rec.get("cpus_alloc") or 0
        return ca / ct if ct else None
    if kind == "node":
        tot, idle = rec.get("cpus_total") or 0, rec.get("cpus_idle") or 0
        return (tot - idle) / tot if tot else None
    return None


def _parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _day_sources() -> tuple[dict[str, Path], list[str]]:
    """Map day -> source dir. Mirror (telemetry/) wins over imported. Returns
    (sources, overlap_days)."""
    sources: dict[str, Path] = {}
    imported = {}
    ti = paths.telemetry_imported_dir()
    if ti.exists():
        for d in ti.glob(_DAY_GLOB):
            if d.is_dir():
                imported[d.name] = d
    mirror = {}
    tm = paths.telemetry_dir()
    if tm.exists():
        for d in tm.glob(_DAY_GLOB):
            if d.is_dir():
                mirror[d.name] = d
    overlap = sorted(set(mirror) & set(imported))
    sources.update(imported)
    sources.update(mirror)  # mirror overrides imported for overlapping days
    return sources, overlap


def _process_day(conn, day: str, src: Path) -> None:
    resource = _read_jsonl(src / "resource_state.jsonl")
    events = _read_jsonl(src / "events.jsonl")
    task_runs = _read_jsonl(src / "task_runs.jsonl")

    # ---- resource: hourly + daily ----
    all_slots: set[str] = set()
    per_res: dict[tuple[str, str], dict[str, list[float]]] = {}
    for rec in resource:
        ts = rec.get("ts")
        if not ts:
            continue
        slot = slot_floor(ts)
        all_slots.add(slot)
        u = _util(rec)
        if u is None:
            continue
        kind = rec.get("kind")
        resource_id = rec.get("resource_id")
        if kind == "gpu_type" and resource_id:
            resource_id = canonical_gpu_type(resource_id)
        key = (kind, resource_id)
        per_res.setdefault(key, {}).setdefault(slot, []).append(u)

    ev_by_res: dict[str, list[dict]] = {}
    preemptions = 0
    for e in events:
        ev_by_res.setdefault(e.get("resource_id") or "", []).append(e)
        if e.get("event") == "preemption":
            preemptions += 1

    emitted_slots: set[str] = set()
    for (kind, rid), slotmap in per_res.items():
        per_slot = {s: round(statistics.fmean(v), 6) for s, v in slotmap.items()}
        emitted_slots |= set(per_slot)

        by_hour: dict[str, list[float]] = {}
        for s, u in per_slot.items():
            by_hour.setdefault(s[:13] + ":00:00Z", []).append(u)
        for hour, utils in sorted(by_hour.items()):
            conn.execute(
                "INSERT INTO hourly_resource VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(resource_kind,resource_id,hour_utc) DO UPDATE SET "
                "util_min=excluded.util_min, util_mean=excluded.util_mean, "
                "util_max=excluded.util_max, util_p95=excluded.util_p95, "
                "free_ratio=excluded.free_ratio, samples=excluded.samples",
                (kind, rid, hour, round(min(utils), 6),
                 round(statistics.fmean(utils), 6), round(max(utils), 6),
                 pctl(utils, 0.95),
                 round(statistics.fmean([1 - u for u in utils]), 6), len(utils)))

        # daily
        slots_sorted = sorted(per_slot)
        free_seconds = round(sum((1 - per_slot[s]) * SLOT_SECONDS for s in slots_sorted), 3)
        longest = cur = 0
        prev_dt = None
        for s in slots_sorted:
            if per_slot[s] <= 1e-9:
                dt = _parse_ts(s)
                if prev_dt is not None and (dt - prev_dt).total_seconds() == SLOT_SECONDS:
                    cur += 1
                else:
                    cur = 1
                longest = max(longest, cur)
                prev_dt = dt
            else:
                cur = 0
                prev_dt = None
        res_events = ev_by_res.get(rid, [])
        outages = sum(1 for e in res_events
                      if e.get("event") == "node_state_change"
                      and e.get("to") in ("down", "drain", "fail", "fail*"))
        # preemption events carry no resource_id in the current schema (spec
        # example keys them by job_id/partition only, and collector_parse does
        # not emit them yet), so they cannot be attributed to this specific
        # (resource_kind, resource_id) row. Leave this row's preemption_count
        # at 0 rather than stamping every resource with the day-wide total;
        # the day-wide total is recorded once below as a cluster-level row.
        conn.execute(
            "INSERT INTO daily_resource VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(resource_kind,resource_id,day_utc) DO UPDATE SET "
            "free_seconds_total=excluded.free_seconds_total, "
            "longest_free_window_s=excluded.longest_free_window_s, "
            "outage_count=excluded.outage_count, "
            "preemption_count=excluded.preemption_count, samples=excluded.samples",
            (kind, rid, day, free_seconds, longest * SLOT_SECONDS,
             outages, 0, len(slots_sorted)))

    if preemptions:
        # Day-wide preemption total, unattributable to a single resource
        # (see comment above). Recorded once as a synthetic cluster-level
        # row rather than duplicated onto every per-resource row, so readers
        # never mistake it for a per-resource count.
        conn.execute(
            "INSERT INTO daily_resource VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(resource_kind,resource_id,day_utc) DO UPDATE SET "
            "preemption_count=excluded.preemption_count",
            ("cluster", "ALL", day, None, None, 0, preemptions, None))

    # ---- events promotion (dedup via PK, NULLs coerced to "") ----
    for e in events:
        conn.execute(
            "INSERT OR IGNORE INTO events VALUES(?,?,?,?,?)",
            (e.get("ts") or "", e.get("event") or "", e.get("resource_id") or "",
             e.get("job_id") or "",
             json.dumps({k: v for k, v in e.items()
                         if k not in ("ts", "event", "resource_id", "job_id")},
                        sort_keys=True)))

    # ---- task_runs promotion into durable task_run table ----
    #
    # Terminal-wins upsert (was INSERT OR IGNORE, which froze a job at its
    # first-seen state forever — a job first sampled RUNNING stayed RUNNING
    # even after it completed). Semantics, keyed on job_id:
    #   - new job_id                       -> insert
    #   - existing NON-terminal, incoming  -> UPDATE all telemetry fields
    #   - existing terminal, incoming NON-terminal -> NO-OP (never downgrade)
    #   - existing terminal, incoming terminal     -> UPDATE (a later
    #     observation can carry seff enrichment the first lacked)
    # day_utc is deliberately NOT in the SET list: it is the record's
    # first-seen day-dir (submission-derived) and must not drift to a later
    # re-observation's day-dir. This is still upsert-with-upgrade, NEVER
    # DELETE (I9). is_terminal is registered as a SQL function so the guard
    # can read both the existing row's state and the incoming (excluded)
    # state; the shared predicate is collector_parse.is_terminal (same set
    # the seff enrichment uses — not a second, forkable list).
    for t in task_runs:
        used = t.get("used") or {}
        submit, start = _parse_ts(t.get("submit")), _parse_ts(t.get("start"))
        wait = (start - submit).total_seconds() if submit and start else None
        hardware = derive_hardware(t.get("gpu_type"), t.get("req"))
        conn.execute(
            'INSERT INTO task_run '
            '(job_id, project, campaign, skill, hardware, submit, start, "end", '
            'elapsed_s, wait_s, cpu_eff, mem_eff, max_rss_mb, state, exit_code, '
            'day_utc, partition) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) '
            'ON CONFLICT(job_id) DO UPDATE SET '
            'project=excluded.project, campaign=excluded.campaign, '
            'skill=excluded.skill, '
            'hardware=excluded.hardware, partition=excluded.partition, '
            'submit=excluded.submit, '
            'start=excluded.start, "end"=excluded."end", '
            'elapsed_s=excluded.elapsed_s, wait_s=excluded.wait_s, '
            'cpu_eff=COALESCE(excluded.cpu_eff,task_run.cpu_eff), '
            'mem_eff=COALESCE(excluded.mem_eff,task_run.mem_eff), '
            'max_rss_mb=COALESCE(excluded.max_rss_mb,task_run.max_rss_mb), state=excluded.state, '
            'exit_code=excluded.exit_code '
            'WHERE is_terminal(task_run.state)=0 OR is_terminal(excluded.state)=1',
            (t.get("job_id"), t.get("project") or "unknown", t.get("campaign") or "",
             t.get("skill") or "unknown",
             hardware, t.get("submit"), t.get("start"), t.get("end"),
             used.get("elapsed_s"), wait, used.get("cpu_eff_pct"),
             used.get("mem_eff_pct"), used.get("max_rss_mb"),
             t.get("state"), t.get("exit_code"), day, t.get("partition")))
        # Keep the existing task_run schema compatible with old readers, while
        # retaining every richer field for planning and historical analysis.
        # Sparse legacy observations cannot erase a newer accounting format.
        current = conn.execute("SELECT state FROM task_run WHERE job_id=?", (t.get("job_id"),)).fetchone()
        if current and current[0] == t.get("state"):
            conn.execute(
                "INSERT INTO task_accounting VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(job_id) DO UPDATE SET user=excluded.user, account=excluded.account, "
                "node_list=excluded.node_list, job_name=excluded.job_name, qos=excluded.qos, "
                "constraints=excluded.constraints, accounting_version=excluded.accounting_version, "
                "details_json=excluded.details_json "
                "WHERE excluded.accounting_version>=task_accounting.accounting_version",
                (t.get("job_id"), t.get("user"), t.get("account"), t.get("node_list"),
                 t.get("job_name"), t.get("qos"), t.get("constraints"),
                 t.get("accounting_version", 1), json.dumps(t, sort_keys=True)),
            )

    # ---- day_index (monotonic slots_ingested AND rows_emitted) ----
    observed = len(all_slots)
    row = conn.execute("SELECT slots_ingested, rows_emitted, first_seen_utc "
                       "FROM day_index WHERE day_utc=?", (day,)).fetchone()
    prev_slots = row[0] if row else 0
    prev_rows = row[1] if row else 0
    first_seen = row[2] if row else _now_iso()
    slots_ingested = max(prev_slots, observed)
    # rows_emitted is monotonic for the same reason slots_ingested is: a later
    # re-observation of the day through a SPARSER source (e.g. a catchup that
    # re-emits only task_runs, making a mirror day shadow a fuller imported
    # day) must never un-summarise a day that was already fully processed —
    # that would flip fully_summarised to 0 and wedge the retention gate.
    # "Fully summarised" means "has ever been fully summarised".
    rows_emitted = max(prev_rows, len(emitted_slots))
    # BOOLEAN promotion flags (0/1), not counts: promotion is synchronous in
    # this function, so a processed day's events/task_runs have, by
    # definition, already been written above (vacuously true if the day has
    # zero events/runs). Kept as explicit flags — rather than inlined
    # literals — and folded into `fully` via AND so the day_index gate
    # matches the three-part spec contract and the Task 9 retention gate
    # keeps reading them as booleans, not counts, even if promotion ever
    # becomes conditional.
    events_promoted = 1
    task_runs_promoted = 1
    # "Fully summarised" = "the retention gate may let this day's raw go".
    # Two independent ways to earn it, either sufficient:
    #   current-run completeness -- THIS run processed everything the day's
    #     current sources contain (vacuously true for a task_runs-only day
    #     with zero resource slots: its runs/events were just promoted, so
    #     deleting the raw loses nothing unsummarised). Also covers a
    #     sparser re-observation shadowing a fuller historical source: the
    #     monotonic slots_ingested then records debt no raw still holds, and
    #     without this term such days could never settle and would wedge the
    #     gate (I8) as they age out.
    #   monotonic completeness -- the day met the ratio against the largest
    #     ingest ever observed (the original three-part contract).
    current_ok = observed == 0 or len(emitted_slots) >= FULLY_RATIO * observed
    monotonic_ok = slots_ingested > 0 and rows_emitted >= FULLY_RATIO * slots_ingested
    fully = int((current_ok or monotonic_ok)
                and events_promoted
                and task_runs_promoted)
    conn.execute(
        "INSERT INTO day_index VALUES(?,?,?,?,?,?,?,?) "
        "ON CONFLICT(day_utc) DO UPDATE SET slots_ingested=excluded.slots_ingested, "
        "rows_emitted=excluded.rows_emitted, events_promoted=excluded.events_promoted, "
        "task_runs_promoted=excluded.task_runs_promoted, "
        "fully_summarised=excluded.fully_summarised, last_rollup_utc=excluded.last_rollup_utc",
        (day, slots_ingested, rows_emitted, events_promoted, task_runs_promoted,
         fully, first_seen, _now_iso()))


def _ensure_task_run_columns(conn) -> None:
    """Add columns a database written by an older rollup does not have."""
    have = {r[1] for r in conn.execute("PRAGMA table_info(task_run)")}
    if "partition" not in have:
        conn.execute("ALTER TABLE task_run ADD COLUMN partition TEXT")
    if "campaign" not in have:
        conn.execute("ALTER TABLE task_run ADD COLUMN campaign TEXT")


def _rebuild_task_profile(conn) -> None:
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


def _update_meta(conn, sources: dict[str, Path]) -> None:
    on_disk = set(sources)
    indexed = {r[0] for r in conn.execute("SELECT day_utc FROM day_index")}
    pruned = sorted(indexed - on_disk)
    conn.execute("INSERT INTO meta VALUES('schema_version','1') "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    conn.execute("INSERT INTO meta VALUES('last_rollup_utc',?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (_now_iso(),))
    if pruned:
        prev = conn.execute("SELECT value FROM meta WHERE key='raw_pruned_through'").fetchone()
        high = max([pruned[-1]] + ([prev[0]] if prev else []))
        conn.execute("INSERT INTO meta VALUES('raw_pruned_through',?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (high,))


def run(*, full_rebuild: bool = False) -> None:
    db = paths.summaries_db()
    db.parent.mkdir(parents=True, exist_ok=True)
    tmp = db.with_suffix(".db.tmp")
    if tmp.exists():
        tmp.unlink()
    if db.exists() and not full_rebuild:
        shutil.copy2(db, tmp)

    conn = sqlite3.connect(tmp)
    # SQL-visible terminal predicate for the task_run upsert guard. Returns
    # 1/0 so the ON CONFLICT ... WHERE clause can compare against it.
    conn.create_function("is_terminal", 1, lambda s: 1 if is_terminal(s) else 0)
    try:
        conn.executescript(SCHEMA)
        _ensure_task_run_columns(conn)
        sources, overlap = _day_sources()
        for day in overlap:
            print(f"[rollup] overlap: {day} present in both trees — using mirror, "
                  f"ignoring imported copy whole")
        for day in sorted(sources):
            _process_day(conn, day, sources[day])
        _rebuild_task_profile(conn)
        _update_meta(conn, sources)
        conn.commit()
    finally:
        conn.close()

    with open(tmp, "rb") as fh:
        os.fsync(fh.fileno())
    os.replace(tmp, db)


def main() -> int:
    ap = argparse.ArgumentParser(prog="rollup.py")
    ap.add_argument("--full-rebuild", action="store_true",
                    help="discard prior summaries and recompute (migration only)")
    ap.add_argument("--no-lock", action="store_true",
                    help="caller already holds locks/sync.lock (sync-telemetry.sh)")
    args = ap.parse_args()

    if args.no_lock:
        run(full_rebuild=args.full_rebuild)
        return 0

    paths.locks_dir().mkdir(parents=True, exist_ok=True)
    with open(paths.sync_lock(), "w") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("sync already running — skipping rollup")
            return 0
        try:
            run(full_rebuild=args.full_rebuild)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
