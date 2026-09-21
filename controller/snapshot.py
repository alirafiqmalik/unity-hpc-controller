"""Cluster and per-project snapshot. Read-only over existing stores (I6)."""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from controller import registry as _registry
from lib import campaign as _campaign
from lib import paths


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(row: dict, key: str) -> int:
    try:
        return int(row.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def cluster_config() -> dict:
    path = paths.config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


#: A snapshot older than this is history, not the live cluster. The collector
#: samples every few seconds, so minutes of silence already mean it stopped.
LIVE_MAX_AGE_S = 900


def _age_seconds(stamp: str) -> int | None:
    """Seconds since `stamp`, read as UTC. None when it cannot be read.

    The collector writes `2026-07-24 03:24:21` with no zone marker. It is UTC,
    but a reader that assumes local time is wrong by the local offset, so the
    zone is applied here and never in the browser.
    """
    if not stamp:
        return None
    text = str(stamp).strip().replace("Z", "").replace("T", " ")
    try:
        when = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    when = when.replace(tzinfo=timezone.utc)
    return int(max(0, (datetime.now(timezone.utc) - when).total_seconds()))


def live_snapshot() -> dict:
    """Latest KPIs from snapshot.csv, plus a short queue trend."""
    empty = {"available": False, "latest": {}, "trend": [],
             "age_s": None, "fresh": False}
    csv_path = paths.snapshot_csv()
    if not csv_path.exists():
        return empty
    try:
        with csv_path.open(newline="") as fh:
            rows = list(csv.DictReader(fh))
    except OSError:
        return empty
    if not rows:
        return empty
    tail = rows[-96:]
    trend = [
        {
            "t": r.get("timestamp_utc", ""),
            "running": _num(r, "gpu_running"),
            "pending": _num(r, "gpu_pending"),
            "preempt_pending": _num(r, "gpu_preempt_pending"),
        }
        for r in tail
    ]
    last = rows[-1]
    latest = {
        "timestamp_utc": last.get("timestamp_utc", "") or _now(),
        "gpu_running": _num(last, "gpu_running"),
        "gpu_pending": _num(last, "gpu_pending"),
        "gpu_preempt_pending": _num(last, "gpu_preempt_pending"),
        "total_nodes": _num(last, "total_nodes"),
        "free_nodes": _num(last, "free_nodes"),
        "gpu_types_free": last.get("gpu_types_free", "") or "",
    }
    age_s = _age_seconds(latest["timestamp_utc"])
    return {
        "available": True,
        "latest": latest,
        "trend": trend,
        "age_s": age_s,
        "fresh": age_s is not None and age_s <= LIVE_MAX_AGE_S,
    }


def partitions() -> list[dict]:
    cfg = cluster_config()
    parts = cfg.get("partitions") or {}
    if not isinstance(parts, dict):
        return []
    out = []
    for name, rec in sorted(parts.items()):
        if not isinstance(rec, dict):
            rec = {}
        out.append({
            "name": name,
            "nodes": rec.get("nodes"),
            "gpu_types": rec.get("gpu_types") or [],
            "max_walltime": rec.get("max_walltime") or rec.get("timelimit") or "",
            "access": rec.get("access") or "",
            "gpus_total": rec.get("gpus_total"),
            "cpus_total": rec.get("cpus_total"),
        })
    return out


def _hours_before(stamp: str, hours: int) -> str:
    """The slot key `hours` before an ISO hour key."""
    try:
        base = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except (TypeError, ValueError):
        return stamp
    return (base - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def usage(hours: int = 24) -> dict:
    """GPU util series from summaries.db. Empty when the rollup is absent.

    The window is the last `hours` up to now. When the rollup holds nothing that
    new — the retrieval has not run for a while, or the cluster-side collector
    stopped — the window slides back to the last `hours` of data that exists,
    and `window` says `latest-available`. The rows are the same real rows
    either way; `freshness_utc` and `stale_s` say how old they are.
    """
    empty = {"available": False, "slots": [], "series": {}, "by_type": [],
             "window": "recent", "hours": hours, "freshness_utc": None,
             "stale_s": None}
    db = paths.summaries_db()
    if not db.exists():
        return empty
    try:
        hours = max(1, min(int(hours), 24 * 3650))
    except (TypeError, ValueError):
        hours = 24
    empty["hours"] = hours
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    window = "recent"
    query = (
        "SELECT hour_utc AS slot, resource_id AS gpu_type, "
        "ROUND(util_mean * 100.0, 1) AS util "
        "FROM hourly_resource "
        "WHERE resource_kind = 'gpu_type' AND hour_utc >= ? "
        "ORDER BY hour_utc, resource_id"
    )
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(query, (cutoff,)).fetchall()
            if not rows:
                newest = con.execute(
                    "SELECT MAX(hour_utc) FROM hourly_resource "
                    "WHERE resource_kind = 'gpu_type'"
                ).fetchone()[0]
                if newest:
                    window = "latest-available"
                    rows = con.execute(
                        query, (_hours_before(newest, hours),)
                    ).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return empty
    if not rows:
        return empty
    slots: list[str] = []
    index: dict[str, int] = {}
    series: dict[str, list] = {}
    for r in rows:
        slot = r["slot"]
        if slot not in index:
            index[slot] = len(slots)
            slots.append(slot)
        series.setdefault(r["gpu_type"] or "cpu", [])
    for gtype in series:
        series[gtype] = [None] * len(slots)
    for r in rows:
        series[r["gpu_type"] or "cpu"][index[r["slot"]]] = r["util"]
    by_type = []
    for gtype, vals in series.items():
        present = [v for v in vals if v is not None]
        if not present:
            continue
        by_type.append({
            "gpu_type": gtype,
            "avg": round(sum(present) / len(present), 1),
            "peak": max(present),
        })
    by_type.sort(key=lambda x: x["avg"], reverse=True)
    newest_slot = slots[-1] if slots else None
    stale_s = None
    if newest_slot:
        try:
            when = datetime.strptime(newest_slot, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            stale_s = int(max(0, (now - when).total_seconds()))
        except ValueError:
            stale_s = None
    return {
        "available": True,
        "slots": slots,
        "series": series,
        "by_type": by_type,
        "window": window,
        "hours": hours,
        "freshness_utc": newest_slot,
        "stale_s": stale_s,
    }


def outcomes() -> dict:
    """Job outcome counts from summaries.db task_run, if present."""
    empty = {"available": False, "counts": {}}
    db = paths.summaries_db()
    if not db.exists():
        return empty
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "SELECT state, COUNT(*) AS n FROM task_run GROUP BY state"
            ).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return empty
    counts = {state or "UNKNOWN": n for state, n in rows}
    return {"available": bool(counts), "counts": counts}


def project_jobs(slug: str, campaign_name: str | None = None) -> list[dict]:
    rec = _registry.get(slug)
    if rec is None:
        return []
    root = Path(rec["path"])
    name = campaign_name or rec.get("campaign") or None
    rows = _campaign.jobs(root, name)
    out = []
    for row in rows:
        item = dict(row)
        item["slug"] = slug
        item["campaign"] = name or _campaign.latest_campaign(root) or ""
        out.append(item)
    return out


def all_jobs() -> list[dict]:
    rows: list[dict] = []
    for rec in _registry.list_projects():
        root = Path(rec["path"])
        if not root.is_dir():
            continue
        for name in _campaign.campaigns(root):
            for row in _campaign.jobs(root, name):
                item = dict(row)
                item["slug"] = rec["slug"]
                item["campaign"] = name
                rows.append(item)
    return rows


def project_detail(slug: str) -> dict | None:
    rec = _registry.get(slug)
    if rec is None:
        return None
    root = Path(rec["path"])
    jobs = project_jobs(slug)
    counts: dict[str, int] = {}
    for job in jobs:
        st = (job.get("status") or "UNKNOWN").upper()
        counts[st] = counts.get(st, 0) + 1
    env_path = root / "unityHPC" / ".env"
    runner = root / "unityHPC" / "run.sh"
    return {
        **rec,
        "scaffold": runner.exists(),
        "env_present": env_path.exists(),
        "campaigns": _campaign.campaigns(root),
        "job_counts": counts,
        "jobs": jobs[-50:],
    }


def cluster() -> dict:
    live = live_snapshot()
    cfg = cluster_config()
    latest = live.get("latest") or {}
    return {
        "generated_utc": _now(),
        "cluster": cfg.get("cluster") or "unity",
        "slurm_version": cfg.get("slurm_version") or "",
        "live": live,
        "partitions": partitions(),
        "kpis": {
            "gpu_running": latest.get("gpu_running", 0),
            "gpu_pending": latest.get("gpu_pending", 0),
            "free_nodes": latest.get("free_nodes", 0),
            "total_nodes": latest.get("total_nodes", 0),
            "gpu_types_free": latest.get("gpu_types_free", ""),
            "attached_projects": len(_registry.list_projects()),
        },
        "config_present": bool(cfg),
    }
