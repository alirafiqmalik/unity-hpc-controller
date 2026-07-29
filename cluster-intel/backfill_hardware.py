#!/usr/bin/env python3
"""One-time repair of `task_run.hardware` (and backfill of `partition`).

`hardware` used to fall back to the partition string whenever sacct had not
recorded a GPU type, so one column held two taxonomies: `a100` (a device) beside
`gpu-preempt` and `gpu,gpu-preempt` (queues, which may themselves be a100s).
Roughly 700k of 830k rows carried a queue name. Anything ranking by hardware —
`task_profile`, `recommend-hardware`, `project_hardware_profile` — was comparing
buckets that are not comparable.

Nothing is guessed here. The raw telemetry keeps `partition`, `gpu_type` and
`req.gpus` per job, so every affected row is re-derived from the same source the
rollup reads, using the same `derive_hardware` the rollup now uses. Jobs with no
raw record are left untouched and counted, not invented.

Idempotent, and safe to re-run after more telemetry arrives.

    python3 cluster-intel/backfill_hardware.py [--dry-run]
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector_parse import derive_hardware  # noqa: E402
from lib import paths  # noqa: E402


def _raw_records() -> dict[str, tuple[str, str | None]]:
    """job_id -> (hardware, partition), from every raw task_runs.jsonl.

    Precedence is per **job**, mirror over imported — deliberately not the
    rollup's per-*day* "mirror wins whole" rule. That rule exists to stop a
    partial mirror day being blended into day-level aggregates; here each record
    describes one job, and both trees describe it identically apart from
    freshness. Using the day rule instead would discard the imported copy of
    every overlapping day and leave ~600k rows unrepairable for no benefit."""
    data = paths.data_dir()
    files: list[Path] = []
    for tree in ("telemetry-imported", "telemetry"):   # mirror second: it wins
        root = data / tree
        if root.is_dir():
            files += sorted(root.glob("*/task_runs.jsonl"))

    out: dict[str, tuple[str, str | None]] = {}
    for f in files:
        with f.open(errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                job_id = rec.get("job_id")
                if not job_id:
                    continue
                out[str(job_id)] = (
                    derive_hardware(rec.get("gpu_type"), rec.get("req")),
                    rec.get("partition") or None,
                )
    return out


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    db = paths.summaries_db()
    if not db.exists():
        print(f"no summaries.db at {db} — nothing to repair")
        return 0

    truth = _raw_records()
    print(f"raw telemetry covers {len(truth)} job_ids")

    con = sqlite3.connect(db, timeout=30)
    try:
        have = {r[1] for r in con.execute("PRAGMA table_info(task_run)")}
        if "partition" not in have:
            if dry_run:
                print("would add task_run.partition")
            else:
                con.execute("ALTER TABLE task_run ADD COLUMN partition TEXT")
                have.add("partition")

        rows = con.execute("SELECT job_id, hardware FROM task_run").fetchall()
        updates, already, uncovered = [], 0, 0
        differing: list[tuple[str, str, str | None]] = []
        for job_id, hardware in rows:
            match = truth.get(str(job_id))
            if match is None:
                uncovered += 1
                continue
            new_hw, part = match
            if new_hw == hardware:
                already += 1
            elif len(differing) < 8:
                differing.append((str(job_id), hardware, new_hw))
            updates.append((new_hw, part, job_id))

        print(f"rows: {len(rows)}  |  re-derivable: {len(updates)}  |  "
              f"already correct: {already}  |  no raw record: {uncovered}")
        for job_id, old_hw, new_hw in differing:
            print(f"  {job_id}: hardware {old_hw!r} -> {new_hw!r}")
        if dry_run:
            print("dry run — nothing written")
            return 0
        changed = updates

        with con:
            con.executemany(
                "UPDATE task_run SET hardware=?, partition=? WHERE job_id=?",
                changed)
            # task_profile is keyed on hardware, so its old buckets are stale.
            con.execute("DELETE FROM task_profile")
        print(f"updated {len(changed)} rows; cleared task_profile "
              f"(the next rollup rebuilds it from the corrected rows)")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
