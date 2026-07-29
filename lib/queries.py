"""Read-only helpers over summaries.db. Writers use rollup.py; these never write.

Stdlib only. Every helper fails safe (returns a conservative value) when the
database, table, or row is absent, so callers degrade rather than crash (I6).
"""

from __future__ import annotations

import sqlite3

from lib import paths


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


# task_run columns we surface to per-project readers.
_TASK_RUN_COLS = (
    "job_id", "hardware", "elapsed_s", "wait_s", "cpu_eff", "mem_eff",
    "max_rss_mb", "state", "exit_code", "day_utc",
)

# SQLite's default host-parameter limit is 999; chunk well under it.
_ID_CHUNK = 900


def _pctl(values: list, q: float) -> float | None:
    """Deterministic q-percentile (0..1) via linear interpolation, 6dp."""
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None
    if len(xs) == 1:
        return round(float(xs[0]), 6)
    pos = q * (len(xs) - 1)
    lo = int(pos)
    frac = pos - lo
    hi = min(lo + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * frac, 6)


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
            "runtime_p50": _pctl(elapsed, 0.5),
            "runtime_p90": _pctl(elapsed, 0.9),
            "wait_p50": _pctl(waits, 0.5),
            "success_rate": round(ok / len(runs), 6) if runs else None,
            "cpu_eff_p50": _pctl(cpu, 0.5),
            "mem_eff_p50": _pctl(mem, 0.5),
        })
    return profile
