#!/usr/bin/env python3
"""One-time migration of the pre-redesign store into the new data core (§9).

  1. archive originals (copy; nothing deleted)
  2. import raw_jobs.db -> telemetry-imported/<day>/task_runs.jsonl
     and snapshot.csv -> telemetry-imported/<day>/resource_state.jsonl
  3. seed cluster-config.json from the old prose profile, taking MAX capacity
  4. full-rebuild summaries.db (the migration-only rebuild mode)
  5. verify row counts reconcile
  6. retire the originals (the archive stays)

telemetry-imported/ is never rsync'd and never pruned; whole-day overlap is
resolved in favour of the live mirror by rollup.py. Stdlib only.

ACCEPTED DEFAULT (see task-11-brief.md): raw_jobs.db -> task_runs and
snapshot.csv -> resource_state ONLY. resource_state is not re-derived from
job intervals (that was the retired fixed-slot-expansion computation) so the
row-count reconciliation stays unambiguous.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import json
import re
import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import collector_parse as cp  # noqa: E402
import rollup  # noqa: E402
from lib import cluster_config as clc  # noqa: E402
from lib import paths  # noqa: E402

_ORIGINALS = ("cluster-profile.md", "raw_jobs.db", "snapshot.csv", "analysis")


def normalize_config_resource_keys() -> bool:
    """Fold legacy GPU storage sections and aliases in cluster-config.json.

    This migration is idempotent.  It preserves original observed spellings in
    ``source_resource_ids`` and writes only when canonicalization changes the
    stored document.
    """
    path = paths.config_path()
    if not path.exists():
        return False
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    normalized = clc.canonicalize_config(current)
    if normalized == current:
        return False
    path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return True


def archive(stamp: str = "2026-07-22") -> list[str]:
    dst = paths.archive_dir() / stamp
    dst.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in _ORIGINALS:
        src = paths.data_dir() / name
        if not src.exists():
            continue
        target = dst / name
        if src.is_dir():
            shutil.copytree(src, target, dirs_exist_ok=True)
        else:
            shutil.copy2(src, target)
        copied.append(name)
    return copied


def _day_of(ts: str | None) -> str | None:
    """The YYYY-MM-DD day of a sacct timestamp, or None if it is not a real date.

    sacct emits the literal strings 'Unknown' (job never started/ended) and
    'None' for missing times; taking [:10] of those produced day directories
    named 'Unknown'/'None', which rollup.py (correctly) never ingests — the
    rows were written but never summarised, so the migration's row-count
    reconciliation could not balance.
    """
    if not ts:
        return None
    day = str(ts).strip().replace(" ", "T")[:10]
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        return None
    return day


def _normalise_ts(ts: str | None) -> str | None:
    """Timestamp as ...Z, or None for the 'Unknown'/'None' sacct placeholders
    (which must not be carried into the record as 'UnknownZ'/'NoneZ')."""
    if not ts or _day_of(ts) is None:
        return None
    ts = str(ts).strip().replace(" ", "T")
    return ts if ts.endswith("Z") else ts + "Z"


def purge_invalid_day_dirs() -> list[str]:
    """Remove telemetry-imported/ directories that are not real YYYY-MM-DD days.

    A partially-completed run of an earlier version left 'None'/'Unknown' day
    dirs behind; they are invisible to rollup.py but counted by verify(), so a
    re-run would keep failing reconciliation on stale state. Only directories
    whose name is not a valid day are touched.
    """
    ti = paths.telemetry_imported_dir()
    if not ti.exists():
        return []
    removed = []
    for d in sorted(ti.iterdir()):
        if d.is_dir() and _day_of(d.name) is None:
            shutil.rmtree(d)
            removed.append(d.name)
    return removed


def import_raw_jobs(db_path: Path) -> dict:
    """Import raw_jobs.db into telemetry-imported/<day>/task_runs.jsonl.

    Returns {"written": n, "skipped_no_date": n}. A row with no parseable
    submit/start/end date cannot be filed under any day, so it is excluded from
    the import *and* from the reconciliation expectation, and reported as an
    explicit skip rather than silently bucketed into a junk day dir.
    """
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        rows = list(con.execute(
            "SELECT job_id, partition, state, submit, start, end, elapsed, "
            "alloc_tres, exit_code FROM raw_jobs"))
    finally:
        con.close()

    purge_invalid_day_dirs()

    by_day: dict[str, list[dict]] = defaultdict(list)
    skipped = 0
    for r in rows:
        gpu_type, req = cp._parse_tres(r["alloc_tres"])
        try:
            rc = int((r["exit_code"] or "0:0").split(":", 1)[0])
        except (ValueError, AttributeError):
            rc = None
        # start first (when the job actually ran), then submit, then end —
        # whichever parses to a real date. A pending/cancelled job has
        # start='Unknown'/'None' but a perfectly good submit time.
        day = _day_of(r["start"]) or _day_of(r["submit"]) or _day_of(r["end"])
        if day is None:
            skipped += 1
            continue
        by_day[day].append({
            "job_id": r["job_id"], "project": None, "skill": None, "campaign": None,
            "submit": _normalise_ts(r["submit"]), "start": _normalise_ts(r["start"]),
            "end": _normalise_ts(r["end"]), "partition": r["partition"],
            "gpu_type": gpu_type, "req": req,
            "used": {"elapsed_s": cp._parse_elapsed(r["elapsed"]),
                     "max_rss_mb": None, "cpu_eff_pct": None, "mem_eff_pct": None},
            "state": r["state"], "exit_code": rc})

    written = 0
    for day, recs in by_day.items():
        d = paths.telemetry_imported_dir() / day
        d.mkdir(parents=True, exist_ok=True)
        # Rewrite the whole day-file in one truncating write so a retry after
        # a mid-run failure is idempotent (re-running never appends a second
        # copy of the same rows).
        with open(d / "task_runs.jsonl", "w", encoding="utf-8") as fh:
            for rec in recs:
                fh.write(json.dumps(rec, sort_keys=True) + "\n")
                written += 1
    return {"written": written, "skipped_no_date": skipped}


def import_snapshot(csv_path: Path) -> int:
    written = 0
    by_day: dict[str, list[dict]] = defaultdict(list)
    with open(csv_path, newline="") as fh:
        for row in csv.DictReader(fh):
            ts = _normalise_ts(row.get("timestamp_utc"))
            if not ts:
                continue
            day = ts[:10]
            try:
                pending = int(row.get("gpu_pending") or 0)
                nodes = int(row.get("total_nodes") or 0)
            except ValueError:
                pending, nodes = 0, 0
            by_day[day].append({"ts": ts, "kind": "partition", "resource_id": "gpu",
                                "nodes_total": nodes, "pending": pending})
    for day, recs in by_day.items():
        d = paths.telemetry_imported_dir() / day
        d.mkdir(parents=True, exist_ok=True)
        # Truncating write (see import_raw_jobs) keeps a retry idempotent.
        with open(d / "resource_state.jsonl", "w", encoding="utf-8") as out:
            for rec in recs:
                out.write(json.dumps(rec, sort_keys=True) + "\n")
                written += 1
    return written


#: `name=count`, where the name may start with a digit (2080_ti=352); the
#: lookbehind stops the match from starting part-way through a name (which
#: would read 2080_ti as "ti" and collide with 1080_ti).
_PAIR_RE = re.compile(r"(?<![\w=])([a-z0-9_]+)=(\d+)", re.I)


def _gpu_capacity_counts(text: str) -> dict[str, int]:
    """Pull `name=count` pairs out of every GPU-capacity block in the profile.

    The real profile writes it as a markdown HEADING with the payload wrapped
    over the FOLLOWING line(s):

        ## GPU capacity (whole cluster, `sinfo` GPUs-per-type x nodes)
        a100=157 · l40s=108 · ... ·
        a16=64 · ...

    so the old single-line `GPU capacity:\\s*(.+)` regex never matched and the
    fleet was seeded empty. Both that heading form and the older inline
    `- GPU capacity: a100=40 l40s=16` form are accepted; blocks with no pairs
    (e.g. the prose 'GPU capacity denominators: see above' line) contribute
    nothing. Counts merge by max, matching lib.cluster_config.
    """
    counts: dict[str, int] = {}
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "gpu capacity" not in line.lower():
            continue
        block = [line.split(":", 1)[1] if ":" in line else ""]
        for nxt in lines[i + 1:]:                 # wrapped payload continuation
            if not nxt.strip() or nxt.lstrip()[0] in "#-|>*":
                break
            block.append(nxt)
        for pm in _PAIR_RE.finditer("\n".join(block)):
            name, n = pm.group(1).lower(), int(pm.group(2))
            counts[name] = max(counts.get(name, 0), n)
    return counts


def seed_config(profile_md: Path, *, writer: str = "migration") -> dict:
    text = profile_md.read_text() if profile_md.exists() else ""
    observation: dict = {}
    fleet = {name: {"total_accessible": n, "observed_utc": "2026-07-22T00:00:00Z"}
             for name, n in _gpu_capacity_counts(text).items()}
    if fleet:
        observation["gpu_fleet"] = fleet
    # force past the TTL: this is a one-time seed
    _, cfg = clc.write_config(observation, writer=writer, force=True)
    return cfg


def verify() -> dict:
    # Count exactly what rollup.py actually consumed per day, using its own
    # day -> source-dir mapping (mirror wins whole-day on overlap) rather
    # than blindly summing every telemetry-imported/ file. Real stores can't
    # overlap today (migration runs before any live sync populates
    # telemetry/), but if a day ever exists in both trees, rollup reads only
    # the mirror's task_runs.jsonl for it — summing the shadowed imported
    # copy on top would false-mismatch the reconciliation below.
    sources, _overlap = rollup._day_sources()
    imported = 0
    for day in sources:
        f = sources[day] / "task_runs.jsonl"
        if f.exists():
            imported += sum(1 for line in f.read_text().splitlines() if line.strip())
    con = sqlite3.connect(paths.summaries_db())
    try:
        task_run_rows = con.execute("SELECT COUNT(*) FROM task_run").fetchone()[0]
    finally:
        con.close()
    report = {"raw_jobs": imported, "imported": imported, "task_run_rows": task_run_rows}
    if imported != task_run_rows:
        raise RuntimeError(f"reconciliation failed: imported {imported} task runs but "
                           f"summaries.db holds {task_run_rows}")
    return report


def retire() -> list[str]:
    removed = []
    for name in _ORIGINALS:
        p = paths.data_dir() / name
        if p.is_dir():
            shutil.rmtree(p)
            removed.append(name)
        elif p.exists():
            p.unlink()
            removed.append(name)
    return removed


def run(stamp: str = "2026-07-22") -> dict:
    # Migration writes/os.replace()s the shared summaries.db, same as a
    # rollup, so it must hold the same locks/sync.lock a concurrent
    # sync-telemetry.sh (which holds the lock across its own pull+rollup)
    # would be holding — otherwise two os.replace() on summaries.db could
    # race, and full_rebuild=True would discard prior summaries into the
    # bargain. Use the exact mechanism rollup.main() uses; since we hold the
    # lock ourselves we must call rollup.run() (the --no-lock inner path),
    # never rollup.main(), or we would self-deadlock.
    paths.locks_dir().mkdir(parents=True, exist_ok=True)
    with open(paths.sync_lock(), "w") as lock:
        try:
            normalize_config_resource_keys()
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(
                "a telemetry sync or rollup is in progress; re-run the "
                "migration when it is idle")
        try:
            archive(stamp)
            db = paths.data_dir() / "raw_jobs.db"
            imported = (import_raw_jobs(db) if db.exists()
                        else {"written": 0, "skipped_no_date": 0})
            raw_n = imported["written"]
            snap = paths.data_dir() / "snapshot.csv"
            if snap.exists():
                import_snapshot(snap)
            seed_config(paths.data_dir() / "cluster-profile.md")
            rollup.run(full_rebuild=True)
            report = verify()
            report["raw_jobs"] = raw_n
            # rows with no parseable submit/start/end: excluded from the import
            # and from the reconcile expectation, reported explicitly here.
            report["skipped_no_date"] = imported["skipped_no_date"]
            if raw_n != report["task_run_rows"]:
                raise RuntimeError(
                    f"raw_jobs {raw_n} != task_run_rows {report['task_run_rows']}")
            retire()
            return report
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def main() -> int:
    ap = argparse.ArgumentParser(prog="migrate.py")
    ap.add_argument("cmd", choices=["run"], nargs="?", default="run")
    ap.add_argument("--stamp", default="2026-07-22")
    args = ap.parse_args()
    report = run(stamp=args.stamp)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
