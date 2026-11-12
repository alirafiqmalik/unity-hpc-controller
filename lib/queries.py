"""Test-only readers over summaries.db, kept until the owner decides their future.

Production reads live in lib/telemetry_archive.py. Stdlib only. Every helper
fails safe (returns a conservative value) when the database, table, or row is
absent, so callers degrade rather than crash (I6).
"""

from __future__ import annotations

import sqlite3
import json

from lib import paths
from lib.telemetry_archive import pctl


# task_run columns we surface to per-project readers.
_TASK_RUN_COLS = (
    "job_id", "hardware", "elapsed_s", "wait_s", "cpu_eff", "mem_eff",
    "max_rss_mb", "state", "exit_code", "day_utc",
)

# SQLite's default host-parameter limit is 999; chunk well under it.
_ID_CHUNK = 900


def task_runs_for_jobs(job_ids: list[str]) -> list[dict]:
    """Read-only per-job telemetry from summaries.db for the given job_ids.

    Returns [] (never raises) if summaries.db / task_run is absent. Chunks the
    IN list to stay under SQLite's parameter limit.
    """
    ids = [j for j in dict.fromkeys(job_ids) if j]  # de-dup, drop empties, keep order
    if not ids:
        return []
    db = paths.summaries_db()
    if not db.exists():
        return []
    cols = ", ".join(f'"{c}"' if c == "end" else c for c in _TASK_RUN_COLS)
    out: list[dict] = []
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            for i in range(0, len(ids), _ID_CHUNK):
                chunk = ids[i:i + _ID_CHUNK]
                ph = ",".join("?" * len(chunk))
                cur = con.execute(
                    f"SELECT {cols} FROM task_run WHERE job_id IN ({ph})", chunk)
                names = [d[0] for d in cur.description]
                out.extend(dict(zip(names, row)) for row in cur.fetchall())
        finally:
            con.close()
    except sqlite3.Error:
        # Absent table, corrupt DB, or any open failure: readers degrade to
        # "no telemetry yet" rather than crash (I6).
        return []
    return out


def project_hardware_profile(job_ids: list[str]) -> list[dict]:
    """Aggregate task_runs_for_jobs by hardware into this project's own profile.

    One row per hardware: n, n_with_eff, runtime_p50/p90, wait_p50,
    success_rate, cpu_eff_p50, mem_eff_p50. Efficiency Nones are skipped, never
    counted as 0. Deterministic; sorted by hardware for stable output.
    """
    by_hw: dict[str, list[dict]] = {}
    for r in task_runs_for_jobs(job_ids):
        by_hw.setdefault(r.get("hardware") or "unknown", []).append(r)
    profile = []
    for hw in sorted(by_hw):
        runs = by_hw[hw]
        elapsed = [r["elapsed_s"] for r in runs if r["elapsed_s"] is not None]
        waits = [r["wait_s"] for r in runs if r["wait_s"] is not None]
        cpu = [r["cpu_eff"] for r in runs if r["cpu_eff"] is not None]
        mem = [r["mem_eff"] for r in runs if r["mem_eff"] is not None]
        ok = sum(1 for r in runs if (r["state"] or "").startswith("COMPLETED"))
        profile.append({
            "hardware": hw,
            "n": len(runs),
            "n_with_eff": len(cpu),
            "runtime_p50": pctl(elapsed, 0.5),
            "runtime_p90": pctl(elapsed, 0.9),
            "wait_p50": pctl(waits, 0.5),
            "success_rate": round(ok / len(runs), 6) if runs else None,
            "cpu_eff_p50": pctl(cpu, 0.5),
            "mem_eff_p50": pctl(mem, 0.5),
        })
    return profile


def job_accounting_for_jobs(job_ids: list[str]) -> list[dict]:
    """Read richer request, allocation, node and step data without SSH or writes."""
    ids = [str(value) for value in dict.fromkeys(job_ids) if value]
    db = paths.summaries_db()
    if not ids or not db.exists():
        return []
    out = []
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            for offset in range(0, len(ids), _ID_CHUNK):
                chunk = ids[offset:offset + _ID_CHUNK]
                placeholders = ",".join("?" for _ in chunk)
                for (raw,) in con.execute(
                    f"SELECT details_json FROM task_accounting WHERE job_id IN ({placeholders}) ORDER BY job_id", chunk
                ):
                    out.append(json.loads(raw))
        finally:
            con.close()
    except (sqlite3.Error, ValueError):
        return []
    return out
