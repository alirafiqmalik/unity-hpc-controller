"""Cluster and per-project snapshot. Read-only over existing stores (I6)."""

from __future__ import annotations

import csv
import json
import re
import sqlite3
import threading
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


def _clamp_hours(hours, default: int = 24) -> int:
    """A positive hour count, capped so a bad query cannot scan forever."""
    try:
        value = int(hours)
    except (TypeError, ValueError):
        return default
    return max(1, min(value, 24 * 3650))


def _parse_utc(text: str | None) -> datetime | None:
    """A sacct timestamp as UTC. `Unknown` and `None` are missing, not dates."""
    if text is None:
        return None
    raw = str(text).strip()
    if not raw or raw.lower() in {"unknown", "none", "n/a", "na"}:
        return None
    raw = raw.replace(" ", "T")
    if raw.endswith("Z"):
        raw = raw[:-1]
    try:
        if len(raw) >= 19 and raw[10] == "T":
            return datetime.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        if len(raw) >= 16 and raw[10] == "T":
            return datetime.strptime(raw[:16], "%Y-%m-%dT%H:%M").replace(
                tzinfo=timezone.utc
            )
        return datetime.strptime(raw[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


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


def _csv_live() -> dict | None:
    csv_path = paths.snapshot_csv()
    if not csv_path.exists():
        return None
    try:
        with csv_path.open(newline="") as fh:
            rows = list(csv.DictReader(fh))
    except OSError:
        return None
    if not rows:
        return None
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


def _newest_resource_recs() -> list[dict]:
    """The last collector sample in telemetry/*/resource_state.jsonl."""
    root = paths.telemetry_dir()
    if not root.is_dir():
        return []
    try:
        days = sorted(
            (p for p in root.iterdir() if p.is_dir() and p.name[:1].isdigit()),
            reverse=True,
        )
    except OSError:
        return []
    for day in days[:5]:
        path = day / "resource_state.jsonl"
        try:
            size = path.stat().st_size
            with path.open(errors="replace") as fh:
                if size > 512_000:
                    fh.seek(size - 512_000)
                    fh.readline()
                text = fh.read()
        except OSError:
            continue
        last_ts = None
        recs: list[dict] = []
        for line in reversed(text.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict) or not rec.get("ts"):
                continue
            if last_ts is None:
                last_ts = rec["ts"]
            if rec["ts"] != last_ts:
                break
            recs.append(rec)
        if recs:
            return recs
    return []


def _live_from_resource(recs: list[dict]) -> dict | None:
    if not recs:
        return None
    gpu_running = 0
    gpu_pending = 0
    preempt_pending = 0
    nodes: dict[str, str] = {}
    type_free: list[str] = []
    ts = recs[0].get("ts") or ""
    for rec in recs:
        kind = rec.get("kind")
        if kind == "gpu_type":
            rid = str(rec.get("resource_id") or "")
            gpu_running += _num(rec, "alloc")
            gpu_pending += _num(rec, "pending")
            free = max(0, _num(rec, "total") - _num(rec, "alloc"))
            if rid and free:
                type_free.append(f"{rid}:{free}")
        elif kind == "node":
            name = str(rec.get("resource_id") or "")
            if name:
                nodes[name] = str(rec.get("state") or "")
        elif kind == "partition":
            name = str(rec.get("resource_id") or "")
            if "preempt" in name.lower():
                preempt_pending += _num(rec, "pending")
    free_nodes = sum(
        1 for state in nodes.values() if state.lower().startswith("idle")
    )
    latest = {
        "timestamp_utc": str(ts).replace("T", " ").replace("Z", ""),
        "gpu_running": gpu_running,
        "gpu_pending": gpu_pending,
        "gpu_preempt_pending": preempt_pending,
        "total_nodes": len(nodes),
        "free_nodes": free_nodes,
        "gpu_types_free": "|".join(sorted(type_free)),
    }
    age_s = _age_seconds(latest["timestamp_utc"])
    return {
        "available": True,
        "latest": latest,
        "trend": [{
            "t": latest["timestamp_utc"],
            "running": gpu_running,
            "pending": gpu_pending,
            "preempt_pending": preempt_pending,
        }],
        "age_s": age_s,
        "fresh": age_s is not None and age_s <= LIVE_MAX_AGE_S,
        "source": "resource_state",
    }


def live_snapshot() -> dict:
    """Latest KPIs from snapshot.csv, or a newer collector sample."""
    empty = {"available": False, "latest": {}, "trend": [],
             "age_s": None, "fresh": False}
    from_csv = _csv_live()
    from_tel = _live_from_resource(_newest_resource_recs())
    if from_csv is None and from_tel is None:
        return empty
    if from_tel is None:
        return from_csv
    if from_csv is None:
        return from_tel
    csv_age = from_csv.get("age_s")
    tel_age = from_tel.get("age_s")
    if tel_age is None:
        return from_csv
    if csv_age is None or tel_age < csv_age:
        from_tel["trend"] = from_csv.get("trend") or from_tel["trend"]
        return from_tel
    return from_csv


def gpu_fleet() -> list[dict]:
    """Per-type capacity from cluster-config.json. Empty when recon has not run."""
    cfg = cluster_config()
    fleet = cfg.get("gpu_fleet") or {}
    if not isinstance(fleet, dict):
        return []
    out = []
    for name, rec in sorted(fleet.items()):
        if not isinstance(rec, dict):
            rec = {}
        try:
            total = int(rec.get("total_accessible") or 0)
        except (TypeError, ValueError):
            total = 0
        try:
            allocated = int(rec.get("allocated") or 0)
        except (TypeError, ValueError):
            allocated = 0
        try:
            pending = int(rec.get("pending") or 0)
        except (TypeError, ValueError):
            pending = 0
        out.append({
            "gpu_type": name,
            "total": total,
            "allocated": allocated,
            "pending": pending,
            "free": max(0, total - allocated),
            "vram_gb": rec.get("vram_gb") or [],
        })
    return out


def fairshare() -> dict:
    """This account's fairshare, or an empty record when recon has not seen it."""
    cfg = cluster_config()
    fs = cfg.get("fairshare") or {}
    limits = cfg.get("account_limits") or {}
    if not isinstance(fs, dict):
        fs = {}
    if not isinstance(limits, dict):
        limits = {}
    factor = fs.get("factor")
    usage = fs.get("effective_usage")
    if factor is None and usage is None:
        return {"available": False, "factor": None, "effective_usage": None,
                "observed_utc": None, "account": limits.get("account") or ""}
    return {
        "available": True,
        "factor": factor,
        "effective_usage": usage,
        "observed_utc": fs.get("observed_utc") or "",
        "account": limits.get("account") or "",
    }


def _open_summaries():
    """A read-only summaries.db, or None when it is missing or unreadable."""
    db = paths.summaries_db()
    if not db.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con
    except sqlite3.Error:
        return None


def _state_family(state: str | None) -> str:
    """Collapse `CANCELLED by <uid>` onto CANCELLED. Other states stay as written."""
    text = str(state or "UNKNOWN").strip() or "UNKNOWN"
    if text.upper().startswith("CANCELLED"):
        return "CANCELLED"
    return text


def _partition_util(hours: int | None = None) -> dict[str, float]:
    """Util (0–100) per partition.

    With no `hours`, this is the latest hour. With `hours`, it is the mean
    over that span ending now. An empty span stays empty.
    """
    con = _open_summaries()
    if con is None:
        return {}
    try:
        if hours == "all":
            rows = con.execute(
                "SELECT resource_id, AVG(util_mean) AS util_mean "
                "FROM hourly_resource WHERE resource_kind = 'partition' "
                "GROUP BY resource_id"
            ).fetchall()
        elif hours is None:
            rows = con.execute(
                "SELECT resource_id, util_mean FROM hourly_resource "
                "WHERE resource_kind = 'partition' AND hour_utc = ("
                "  SELECT MAX(hour_utc) FROM hourly_resource "
                "  WHERE resource_kind = 'partition')"
            ).fetchall()
        else:
            span = _clamp_hours(hours)
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=span)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            query = (
                "SELECT resource_id, AVG(util_mean) AS util_mean "
                "FROM hourly_resource "
                "WHERE resource_kind = 'partition' AND hour_utc >= ? "
                "GROUP BY resource_id"
            )
            rows = con.execute(query, (cutoff,)).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        con.close()
    out: dict[str, float] = {}
    for row in rows:
        name = row["resource_id"]
        if not name or row["util_mean"] is None:
            continue
        out[name] = round(float(row["util_mean"]) * 100.0, 1)
    return out


def partitions(hours: int | None = None) -> list[dict]:
    cfg = cluster_config()
    parts = cfg.get("partitions") or {}
    if not isinstance(parts, dict):
        return []
    util = _partition_util(hours)
    rollup = {r["partition"]: r for r in (task_stats(hours).get("by_partition") or [])}
    out = []
    for name, rec in sorted(parts.items()):
        if not isinstance(rec, dict):
            rec = {}
        extra = rollup.get(name) or {}
        item = {
            "name": name,
            "nodes": rec.get("nodes"),
            "gpu_types": rec.get("gpu_types") or [],
            "max_walltime": rec.get("max_walltime") or rec.get("timelimit") or "",
            "access": rec.get("access") or "",
            "gpus_total": rec.get("gpus_total"),
            "cpus_total": rec.get("cpus_total"),
            "util": util.get(name),
            "wait_s_avg": extra.get("wait_s_avg"),
            "jobs": extra.get("runs"),
            "gpu_hours": extra.get("gpu_hours"),
        }
        out.append(item)
    return out


def usage(hours: int | str | None = 24) -> dict:
    """GPU allocation history, or sampled utilisation when no backfill exists.

    The window is the last `hours` ending now. It never slides back to an
    older file. A backfill that does not reach now is ignored, so live
    samples stay visible. `partial` is true when those samples do not cover
    the whole window; missing hours stay empty.
    """
    unbounded = hours == "all"
    empty = {"available": False, "slots": [], "series": {}, "by_type": [],
             "heatmap": [], "window": "all" if unbounded else "recent",
             "partial": False,
             "hours": None if unbounded else hours,
             "freshness_utc": None, "stale_s": None, "unit": "percent",
             "source": "samples", "window_start_utc": None,
             "window_end_utc": None}
    if not unbounded:
        hours = _clamp_hours(hours)
        empty["hours"] = hours
    now = datetime.now(timezone.utc)
    if unbounded:
        empty["window_end_utc"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        empty["window_start_utc"] = (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        empty["window_end_utc"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    historical = _historical_usage(None if unbounded else hours)
    if historical is not None:
        return historical
    db = paths.summaries_db()
    if not db.exists():
        return empty
    if unbounded:
        cutoff = "0001-01-01T00:00:00Z"
        window = "all"
    else:
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
        ranked = sorted(present)
        mid = len(ranked) // 2
        if len(ranked) % 2:
            median = ranked[mid]
        else:
            median = (ranked[mid - 1] + ranked[mid]) / 2
        by_type.append({
            "gpu_type": gtype,
            "avg": round(sum(present) / len(present), 1),
            "peak": max(present),
            "median": round(median, 1),
        })
    by_type.sort(key=lambda x: x["avg"], reverse=True)
    newest_slot = slots[-1] if slots else None
    window_end = now
    if unbounded and slots:
        window_end = datetime.strptime(slots[-1], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        ) + timedelta(hours=1)
    stale_s = None
    newest_at = None
    if newest_slot:
        try:
            newest_at = datetime.strptime(newest_slot, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            stale_s = int(max(0, (now - newest_at).total_seconds()))
        except ValueError:
            newest_at = None
    partial = False
    if not unbounded and slots and newest_at is not None:
        oldest = datetime.strptime(slots[0], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        window_start = now - timedelta(hours=hours)
        partial = (
            oldest > window_start + timedelta(hours=1)
            or newest_at < now - timedelta(hours=2)
            or len(slots) < int(hours) - 1
        )
    return {
        "available": True,
        "slots": slots,
        "series": series,
        "by_type": by_type,
        "heatmap": _heatmap(slots, series, _gpu_capacity()),
        "window": window,
        "partial": partial,
        "hours": None if unbounded else hours,
        "freshness_utc": newest_slot,
        "stale_s": stale_s,
        "unit": "percent",
        "source": "samples",
        "window_start_utc": slots[0] if unbounded and slots else (
            window_end - timedelta(hours=hours)
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_end_utc": window_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _gpu_capacity() -> dict[str, int]:
    fleet = cluster_config().get("gpu_fleet") or {}
    if not isinstance(fleet, dict):
        return {}
    return {name: int(rec["total_accessible"])
            for name, rec in fleet.items() if isinstance(rec, dict)
            and isinstance(rec.get("total_accessible"), (int, float))
            and rec["total_accessible"] > 0}


def _historical_usage(hours: int | None) -> dict | None:
    """Use a sacct backfill only when that file still reaches now.

    A backfill that stopped earlier must not hide newer live samples, and
    must not move the selected window onto itself. `hours` None keeps every
    stored hour.
    """
    db = paths.historical_usage_db()
    if not db.exists():
        return None
    now = datetime.now(timezone.utc)
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            meta = dict(con.execute("SELECT key,value FROM meta").fetchall())
            start = datetime.fromisoformat(meta["start_utc"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(meta["end_utc"].replace("Z", "+00:00"))
            # Hour buckets close on the hour, so a backfill collected during
            # this hour has an end up to an hour behind the clock. Older than
            # that, it is not the live window: leave the answer to samples.
            if hours is not None and end < now - timedelta(hours=2):
                return None
            window_end = min(now, end)
            cutoff = start if hours is None else window_end - timedelta(hours=hours)
            rows = con.execute(
                "SELECT hour_utc,gpu_type,allocated_avg FROM hour_gpu "
                "WHERE hour_utc >= ? AND hour_utc < ? ORDER BY hour_utc,gpu_type",
                (cutoff.strftime("%Y-%m-%dT%H:00:00Z"),
                 window_end.strftime("%Y-%m-%dT%H:%M:%SZ"))
            ).fetchall()
        finally:
            con.close()
    except (sqlite3.Error, KeyError, ValueError):
        return None
    if not rows:
        return None
    slots = sorted({row["hour_utc"] for row in rows})
    kinds = sorted({row["gpu_type"] for row in rows if row["gpu_type"] != "__all__"})
    values = {(row["hour_utc"], row["gpu_type"]): round(float(row["allocated_avg"]), 2)
              for row in rows}
    series = {kind: [values.get((slot, kind), 0.0) for slot in slots] for kind in kinds}
    totals = [values.get((slot, "__all__"), 0.0) for slot in slots]
    durations = []
    for slot in slots:
        when = datetime.fromisoformat(slot.replace("Z", "+00:00"))
        durations.append(max(0.0, (min(when + timedelta(hours=1), window_end) -
                                    max(when, start, cutoff)).total_seconds() / 3600))
    covered_hours = sum(durations)
    by_type = []
    for kind, numbers in series.items():
        ranked = sorted(numbers)
        mid = len(ranked) // 2
        median = (ranked[mid] if len(ranked) % 2 else
                  (ranked[mid - 1] + ranked[mid]) / 2)
        weighted_avg = (sum(number * duration for number, duration in zip(numbers, durations))
                        / covered_hours if covered_hours else 0)
        by_type.append({"gpu_type": kind, "avg": round(weighted_avg, 1),
                        "peak": round(max(numbers), 1), "median": round(median, 1)})
    by_type.sort(key=lambda row: row["avg"], reverse=True)
    cells: dict[tuple[int, int], list[float]] = {}
    gpu_hours = 0.0
    for slot, total, duration in zip(slots, totals, durations):
        when = datetime.fromisoformat(slot.replace("Z", "+00:00"))
        cells.setdefault((when.weekday(), when.hour), []).append(total)
        gpu_hours += total * duration
    heatmap = [{"dow": day, "hour": hour, "value": round(sum(nums) / len(nums), 1),
                "samples": len(nums)}
               for (day, hour), nums in sorted(cells.items())]
    age = max(0, int((now - end).total_seconds()))
    return {"available": True, "slots": slots, "series": series,
            "by_type": by_type, "heatmap": heatmap,
            "window": "all" if hours is None else "recent",
            "partial": False if hours is None else covered_hours + 1e-6 < float(hours),
            "hours": hours, "freshness_utc": meta.get("end_utc"), "stale_s": age,
            "window_start_utc": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "window_end_utc": window_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "unit": "gpus", "source": "sacct", "covered_hours": round(covered_hours, 2),
            "gpu_hours": round(gpu_hours, 1),
            "avg_allocated": round(gpu_hours / covered_hours, 1) if covered_hours else 0,
            "peak_allocated": round(max(totals), 1) if totals else 0}


def _heatmap(slots: list[str], series: dict[str, list],
             capacity: dict[str, int]) -> list[dict]:
    """Capacity-weighted GPU allocation percentage by weekday and UTC hour."""
    per_slot: dict[str, float] = {}
    for index, slot in enumerate(slots):
        measured = [(float(vals[index]), capacity[name])
                    for name, vals in series.items()
                    if name in capacity and vals[index] is not None]
        if measured:
            per_slot[slot] = sum(value * size for value, size in measured) / sum(
                size for _, size in measured)
    cells: dict[tuple[int, int], list[float]] = {}
    for slot, total in per_slot.items():
        try:
            when = datetime.strptime(slot, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
        except (TypeError, ValueError):
            continue
        cells.setdefault((when.weekday(), when.hour), []).append(total)
    return [
        {"dow": dow, "hour": hour, "value": round(sum(vals) / len(vals), 1),
         "samples": len(vals)}
        for (dow, hour), vals in sorted(cells.items())
    ]


def _cutoff_day(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d")


def _task_groups(hours: int | None = None) -> list[tuple]:
    """One row per (state family, hardware, partition) in the window."""
    con = _open_summaries()
    if con is None:
        return []
    query = (
        "SELECT state, hardware, partition, COUNT(*) AS n, "
        "SUM(elapsed_s) AS elapsed, AVG(wait_s) AS wait "
        "FROM task_run"
    )
    try:
        if hours is None or hours == "all":
            rows = con.execute(query + " GROUP BY 1, 2, 3").fetchall()
        else:
            try:
                hours = max(1, min(int(hours), 24 * 3650))
            except (TypeError, ValueError):
                hours = 24
            cutoff = _cutoff_day(hours)
            rows = con.execute(
                query + " WHERE day_utc >= ? GROUP BY 1, 2, 3", (cutoff,)
            ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    out = []
    for row in rows:
        out.append((
            _state_family(row["state"]),
            row["hardware"] or "unknown",
            row["partition"] or "unspecified",
            int(row["n"] or 0),
            float(row["elapsed"] or 0.0),
            None if row["wait"] is None else float(row["wait"]),
        ))
    return out


_EMPTY_STATS = {
    "available": False, "runs": 0, "gpu_hours": None,
    "wait_s_avg": None, "wait_s_gpu_avg": None,
    "counts": {}, "by_hardware": [], "by_partition": [],
}

# (db path, mtime, hours) -> payload. The rollup replaces summaries.db, so a
# change of mtime is a new answer. The 10s dashboard poll must not scan again.
_stats_memo: dict[tuple, dict] = {}


def task_stats(hours: int | None = None) -> dict:
    """Cluster-wide job totals from task_run. Empty when the rollup is absent."""
    db = paths.summaries_db()
    try:
        mtime = db.stat().st_mtime
    except OSError:
        return dict(_EMPTY_STATS)
    key = (str(db), mtime, hours)
    cached = _stats_memo.get(key)
    if cached is not None:
        return cached
    rows = _task_groups(hours)
    if not rows:
        _stats_memo[key] = dict(_EMPTY_STATS)
        return _stats_memo[key]
    counts: dict[str, int] = {}
    by_hw: dict[str, dict] = {}
    by_part: dict[str, dict] = {}
    runs = 0
    elapsed = 0.0
    wait_w = 0.0
    wait_n = 0
    wait_gpu_w = 0.0
    wait_gpu_n = 0

    def _acc(bucket: dict, name: str, n: int, el: float, wait) -> None:
        rec = bucket.setdefault(name, {
            "runs": 0, "elapsed_s": 0.0, "wait_w": 0.0, "wait_n": 0,
        })
        rec["runs"] += n
        rec["elapsed_s"] += el
        if wait is not None:
            rec["wait_w"] += wait * n
            rec["wait_n"] += n

    for state, hardware, part, n, el, wait in rows:
        runs += n
        counts[state] = counts.get(state, 0) + n
        elapsed += el
        if wait is not None:
            wait_w += wait * n
            wait_n += n
            if "gpu" in part.lower() or (hardware and hardware != "cpu"):
                wait_gpu_w += wait * n
                wait_gpu_n += n
        _acc(by_hw, hardware, n, el, wait)
        _acc(by_part, part, n, el, wait)

    def _finish(name_key: str, name: str, rec: dict) -> dict:
        return {
            name_key: name,
            "runs": rec["runs"],
            "gpu_hours": round(rec["elapsed_s"] / 3600.0, 1),
            "wait_s_avg": (round(rec["wait_w"] / rec["wait_n"], 1)
                           if rec["wait_n"] else None),
        }

    payload = {
        "available": True,
        "runs": runs,
        "gpu_hours": round(elapsed / 3600.0, 1),
        "wait_s_avg": round(wait_w / wait_n, 1) if wait_n else None,
        "wait_s_gpu_avg": (round(wait_gpu_w / wait_gpu_n, 1)
                           if wait_gpu_n else None),
        "counts": counts,
        "by_hardware": sorted(
            (_finish("hardware", name, rec) for name, rec in by_hw.items()),
            key=lambda r: r["gpu_hours"], reverse=True,
        ),
        "by_partition": sorted(
            (_finish("partition", name, rec) for name, rec in by_part.items()),
            key=lambda r: r["gpu_hours"], reverse=True,
        ),
    }
    _stats_memo[key] = payload
    return payload


def outcomes(hours: int | None = None) -> dict:
    """Job outcome counts from task_run. `CANCELLED by <uid>` is CANCELLED."""
    stats = task_stats(hours)
    counts = stats.get("counts") or {}
    return {"available": bool(counts), "counts": counts}


def project_jobs(slug: str, campaign_name: str | None = None) -> list[dict]:
    rec = _registry.get(slug)
    if rec is None:
        return []
    root = Path(rec["path"])
    name = campaign_name or rec.get("campaign") or None
    _campaign.refresh_from_telemetry(root, name)
    rows = _campaign.jobs(root, name, include_hidden=False)
    from controller.workspace_worker import job_metadata
    metadata = job_metadata(slug)
    out = []
    for row in rows:
        item = dict(row)
        item["slug"] = slug
        item["campaign"] = name or _campaign.latest_campaign(root) or ""
        item.update({"purpose": "unclassified"}, **metadata.get((item["campaign"], item["job_id"]), {}))
        out.append(item)
    return out


def all_jobs() -> list[dict]:
    rows: list[dict] = []
    for rec in _registry.list_projects():
        root = Path(rec["path"])
        if not root.is_dir():
            continue
        from controller.workspace_worker import job_metadata
        metadata = job_metadata(rec["slug"])
        for name in _campaign.campaigns(root):
            _campaign.refresh_from_telemetry(root, name)
            for row in _campaign.jobs(root, name, include_hidden=False):
                item = dict(row)
                item["slug"] = rec["slug"]
                item["campaign"] = name
                item.update({"purpose": "unclassified"}, **metadata.get((name, item["job_id"]), {}))
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
    from controller import experiments
    from controller import dispatch
    catalog = experiments.read(slug)
    try:
        artifact_fetch = dispatch.artifact_fetch_hook(rec) is not None
    except dispatch.DispatchError:
        artifact_fetch = False
    return {
        **rec,
        **catalog,
        "artifact_fetch": artifact_fetch,
        "scaffold": runner.exists(),
        "env_present": env_path.exists(),
        "campaigns": _campaign.campaigns(root),
        "job_counts": counts,
        "jobs": jobs[-50:],
    }


# A collected sacct pull looks back at most this far. Coverage of a selected
# window is the union of those pulls, not the frozen archive.
_SACCT_LOOKBACK = timedelta(days=7)
_USER_INDEX_SCHEMA = "1"
_TERMINAL_STATES = frozenset({
    "COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY",
    "NODE_FAIL", "PREEMPTED", "BOOT_FAIL", "DEADLINE", "REVOKED",
})
_index_lock = threading.Lock()


def _user_index_path() -> Path:
    return paths.data_dir() / "user_jobs.db"


def _task_run_files() -> list[Path]:
    root = paths.telemetry_dir()
    if not root.is_dir():
        return []
    return sorted(path for path in root.glob("*/task_runs.jsonl") if path.is_file())


def _format_elapsed(seconds) -> str:
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return ""
    if total < 0:
        total = 0
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _terminal_state(state: str) -> int:
    token = (state or "").strip().split()
    if not token:
        return 0
    if token[0].upper() == "CANCELLED":
        return 1
    return 1 if token[0].upper() in _TERMINAL_STATES else 0


def _job_tuple(rec: dict) -> tuple | None:
    """One task_runs.jsonl object as a row the user tally already understands."""
    user = str(rec.get("user") or "").strip()
    job_id = str(rec.get("job_id") or "").strip()
    if not user or not job_id:
        return None
    req = rec.get("req") if isinstance(rec.get("req"), dict) else {}
    used = rec.get("used") if isinstance(rec.get("used"), dict) else {}
    gpu_type = str(rec.get("gpu_type") or "").strip()
    parts: list[str] = []
    ncpus = req.get("cpus")
    nnodes = req.get("nodes")
    try:
        ncpus = None if ncpus is None else int(ncpus)
    except (TypeError, ValueError):
        ncpus = None
    try:
        nnodes = None if nnodes is None else int(nnodes)
    except (TypeError, ValueError):
        nnodes = None
    if ncpus:
        parts.append(f"cpu={ncpus}")
    if nnodes:
        parts.append(f"node={nnodes}")
    mem_mb = req.get("mem_mb")
    req_mem = ""
    try:
        if mem_mb:
            mem_mb = int(round(float(mem_mb)))
            req_mem = f"{mem_mb}M"
            parts.append(f"mem={req_mem}")
    except (TypeError, ValueError):
        req_mem = ""
    gpus = req.get("gpus")
    try:
        gpus = int(gpus) if gpus else 0
    except (TypeError, ValueError):
        gpus = 0
    if gpus and gpu_type:
        parts.append(f"gres/gpu:{gpu_type}={gpus}")
    elif gpus:
        parts.append(f"gres/gpu={gpus}")
    elif gpu_type and gpu_type.lower() not in {"cpu", "cpu-only"}:
        parts.append(f"gres/gpu:{gpu_type}=1")
    account = str(rec.get("account") or "").strip()
    state = str(rec.get("state") or "").strip()
    return (
        job_id, user, account,
        str(rec.get("partition") or "").strip(), state,
        rec.get("submit"), rec.get("start"), rec.get("end"),
        _format_elapsed(used.get("elapsed_s")),
        nnodes, ncpus, req_mem, ",".join(parts),
        _terminal_state(state),
    )


def _open_user_index() -> sqlite3.Connection:
    path = _user_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    version = None
    try:
        version = con.execute(
            "SELECT value FROM meta WHERE key = 'schema'"
        ).fetchone()
    except sqlite3.Error:
        version = None
    if version is None or version[0] != _USER_INDEX_SCHEMA:
        con.executescript(
            "DROP TABLE IF EXISTS jobs; DROP TABLE IF EXISTS files; "
            "DROP TABLE IF EXISTS meta;"
        )
        con.executescript(
            """
            CREATE TABLE jobs(
              job_id TEXT PRIMARY KEY, user TEXT NOT NULL, account TEXT,
              partition TEXT, state TEXT, submit TEXT, start TEXT, end TEXT,
              elapsed TEXT, nnodes INTEGER, ncpus INTEGER, req_mem TEXT,
              alloc_tres TEXT, terminal INTEGER NOT NULL);
            CREATE TABLE files(path TEXT PRIMARY KEY, offset INTEGER NOT NULL);
            CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
            """
        )
        con.execute(
            "INSERT INTO meta(key, value) VALUES('schema', ?)",
            (_USER_INDEX_SCHEMA,),
        )
    return con


def _ingest_task_runs(con: sqlite3.Connection, path: Path) -> None:
    rel = str(path.relative_to(paths.telemetry_dir()))
    row = con.execute("SELECT offset FROM files WHERE path = ?", (rel,)).fetchone()
    offset = int(row[0]) if row else 0
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size < offset:
        offset = 0
    if size == offset:
        return
    sql = (
        "INSERT INTO jobs(job_id, user, account, partition, state, submit, "
        "start, end, elapsed, nnodes, ncpus, req_mem, alloc_tres, terminal) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(job_id) DO UPDATE SET "
        "user=excluded.user, account=excluded.account, partition=excluded.partition, "
        "state=excluded.state, submit=excluded.submit, start=excluded.start, "
        "end=excluded.end, elapsed=excluded.elapsed, nnodes=excluded.nnodes, "
        "ncpus=excluded.ncpus, req_mem=excluded.req_mem, "
        "alloc_tres=excluded.alloc_tres, terminal=excluded.terminal "
        "WHERE jobs.terminal = 0 OR excluded.terminal = 1"
    )
    batch: list[tuple] = []
    pos = offset
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(offset)
        while True:
            line = handle.readline()
            if not line:
                break
            if not line.endswith("\n"):
                break
            pos = handle.tell()
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            item = _job_tuple(rec)
            if item is None:
                continue
            batch.append(item)
            if len(batch) >= 2000:
                con.executemany(sql, batch)
                batch.clear()
    if batch:
        con.executemany(sql, batch)
    con.execute(
        "INSERT INTO files(path, offset) VALUES(?, ?) "
        "ON CONFLICT(path) DO UPDATE SET offset = excluded.offset",
        (rel, pos),
    )


def _sync_user_index() -> None:
    """Fold new task_runs lines into the local job index. Later samples win."""
    with _index_lock:
        con = _open_user_index()
        try:
            for path in _task_run_files():
                _ingest_task_runs(con, path)
            con.commit()
        finally:
            con.close()


def _coverage_intervals(now: datetime) -> list[tuple[datetime, datetime]]:
    """Spans sacct was asked about. A fresh file extends coverage up to now."""
    spans: list[tuple[datetime, datetime]] = []
    newest: datetime | None = None
    for path in _task_run_files():
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        except OSError:
            continue
        spans.append((mtime - _SACCT_LOOKBACK, mtime))
        if newest is None or mtime > newest:
            newest = mtime
    if newest is not None and (now - newest).total_seconds() <= LIVE_MAX_AGE_S:
        spans.append((newest, now))
    spans.sort()
    merged: list[tuple[datetime, datetime]] = []
    for start, end in spans:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def _interval_covers(intervals: list[tuple[datetime, datetime]],
                     start: datetime, end: datetime) -> bool:
    cursor = start
    for left, right in intervals:
        if right <= cursor:
            continue
        if left > cursor:
            return False
        cursor = max(cursor, right)
        if cursor >= end:
            return True
    return cursor >= end


def _live_job_rows() -> list:
    _sync_user_index()
    path = _user_index_path()
    if not path.is_file():
        return []
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(
            "SELECT user, account, partition, state, submit, start, end, "
            "elapsed, nnodes, ncpus, req_mem, alloc_tres FROM jobs "
            "WHERE user IS NOT NULL AND user != ''"
        ).fetchall()
    finally:
        con.close()


def _elapsed_hours(text: str | None) -> float:
    """SLURM elapsed (`D-HH:MM:SS` / `HH:MM:SS`) as hours."""
    if not text:
        return 0.0
    raw = str(text).strip()
    days = 0
    if "-" in raw:
        head, raw = raw.split("-", 1)
        try:
            days = int(head)
        except ValueError:
            days = 0
    parts = raw.split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return float(days * 24)
    if len(nums) == 3:
        hours, minutes, seconds = nums
    elif len(nums) == 2:
        hours, minutes, seconds = 0.0, nums[0], nums[1]
    else:
        return float(days * 24)
    return days * 24.0 + hours + minutes / 60.0 + seconds / 3600.0


_EMPTY_USERS = {
    "available": False, "rows": [], "source": None, "partial": False,
    "window": "recent", "hours": None,
    "covered_start_utc": None, "covered_end_utc": None,
    "window_start_utc": None, "window_end_utc": None,
}
_users_memo: dict[tuple, dict] = {}
# Hard failures. Timeout, out-of-memory, and preemption are their own buckets
# because each one is a different thing an operator does next.
_HARD_FAIL = frozenset({
    "FAILED", "NODE_FAIL", "BOOT_FAIL", "DEADLINE", "REVOKED",
})
_OUTCOMES = (
    "completed", "failed", "timeout", "oom", "preempted", "cancelled",
    "running", "pending", "requeued", "other",
)
_GPU_TYPED = re.compile(r"gres/gpu:([A-Za-z0-9_]+)=(\d+)")
_GPU_PLAIN = re.compile(r"(?:^|,)gres/gpu=(\d+)", re.I)
_CPU_TRES = re.compile(r"(?:^|,)cpu=(\d+)", re.I)
_NODE_TRES = re.compile(r"(?:^|,)node=(\d+)", re.I)
_MEM_TRES = re.compile(r"(?:^|,)mem=(\d+(?:\.\d+)?)([KMGT]?)", re.I)
_MEM_REQ = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([KMGT]?)")
# Slurm's bare memory unit is megabytes. Suffixes are binary steps up from that.
_MEM_GB = {"": 1 / 1024, "K": 1 / (1024 * 1024), "M": 1 / 1024, "G": 1.0, "T": 1024.0}


def _job_stamp(row) -> datetime | None:
    keys = set(row.keys())
    for name in ("end", "start", "submit"):
        if name not in keys:
            continue
        stamp = _parse_utc(row[name])
        if stamp is not None:
            return stamp
    return None


def _row_text(row, name: str) -> str:
    if name not in row.keys():
        return ""
    value = row[name]
    return "" if value is None else str(value).strip()


def _positive_int(value) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _state_token(state: str) -> str:
    """The first sacct state word, with `CANCELLED by <uid>` folded in."""
    text = (state or "").strip().upper()
    if not text:
        return ""
    if text.startswith("CANCELLED"):
        return "CANCELLED"
    return text.split()[0]


def _gpus(tres: str) -> tuple[int, str]:
    """Allocated GPU count, and the type that appears most often in the string."""
    typed = list(_GPU_TYPED.finditer(tres or ""))
    if typed:
        names = [match.group(1).lower() for match in typed]
        top = max(set(names), key=lambda name: (names.count(name), name))
        return sum(int(match.group(2)) for match in typed), top
    plain = _GPU_PLAIN.search(tres or "")
    if plain:
        return int(plain.group(1)), ""
    if "gres/gpu" in (tres or "").lower():
        return 1, ""
    return 0, ""


def _count(column: int, tres: str, pattern: re.Pattern[str]) -> int:
    """The dedicated column when sacct filled it, otherwise the TRES field."""
    if column > 0:
        return column
    match = pattern.search(tres or "")
    return int(match.group(1)) if match else 0


def _mem_gb(amount: str, unit: str) -> float:
    try:
        return float(amount) * _MEM_GB.get((unit or "").upper(), 0.0)
    except ValueError:
        return 0.0


def _alloc_mem_gb(tres: str, req_mem: str) -> float:
    """Allocated memory when sacct recorded it, otherwise the request."""
    match = _MEM_TRES.search(tres or "")
    if match:
        return _mem_gb(match.group(1), match.group(2))
    requested = _MEM_REQ.match(req_mem or "")
    if not requested:
        return 0.0
    return _mem_gb(requested.group(1), requested.group(2))


def _blank_user(name: str) -> dict:
    rec = {
        "user": name,
        "jobs": 0,
        "hours": 0.0,
        "gpu_jobs": 0,
        "gpu_hours": 0.0,
        "gpu_elapsed": 0.0,
        "cpu_hours": 0.0,
        "cpu_known": False,
        "node_hours": 0.0,
        "node_known": False,
        "mem_gb_hours": 0.0,
        "mem_known": False,
        "wait_s_sum": 0.0,
        "wait_n": 0,
        "last_seen": None,
        "accounts": {},
        "partitions": {},
        "gpu_types": {},
    }
    for outcome in _OUTCOMES:
        rec[outcome] = 0
    return rec


def _outcome(state: str) -> str:
    """One bucket per job, so the buckets add up to the job count.

    `CANCELLED by <uid>` is cancelled. A missing state is `other`, not a
    completed job.
    """
    token = _state_token(state)
    if token == "COMPLETED":
        return "completed"
    if token == "CANCELLED":
        return "cancelled"
    if token == "TIMEOUT":
        return "timeout"
    if token == "OUT_OF_MEMORY":
        return "oom"
    if token == "PREEMPTED":
        return "preempted"
    if token == "RUNNING":
        return "running"
    if token == "PENDING":
        return "pending"
    if token == "REQUEUED":
        return "requeued"
    if token in _HARD_FAIL:
        return "failed"
    return "other"


def _bump(counts: dict[str, int], key: str) -> None:
    if key:
        counts[key] = counts.get(key, 0) + 1


def _ranked(counts: dict[str, int]) -> list[str]:
    """Most frequent first. Equal counts break toward the earlier name."""
    return sorted(counts, key=lambda key: (-counts[key], key))


def _publish_user(rec: dict) -> dict:
    accounts = _ranked(rec.pop("accounts"))
    partitions = _ranked(rec.pop("partitions"))
    gpu_types = _ranked(rec.pop("gpu_types"))
    wait_n = rec.pop("wait_n")
    wait_sum = rec.pop("wait_s_sum")
    seen = rec.pop("last_seen")
    raw_hours = rec["hours"]
    raw_cpu = rec["cpu_hours"]
    raw_gpu = rec["gpu_hours"]
    cpu_known = rec.pop("cpu_known")
    node_known = rec.pop("node_known")
    mem_known = rec.pop("mem_known")
    gpu_elapsed = rec.pop("gpu_elapsed")
    # Settled jobs only. A running or pending job has not succeeded or failed.
    terminal = (
        rec["completed"] + rec["failed"] + rec["timeout"] + rec["oom"]
        + rec["preempted"] + rec["cancelled"]
    )
    rec["hours"] = round(raw_hours, 1)
    rec["gpu_hours"] = round(raw_gpu, 1)
    rec["cpu_hours"] = round(raw_cpu, 1) if cpu_known else None
    rec["node_hours"] = round(rec["node_hours"], 1) if node_known else None
    rec["mem_gb_hours"] = round(rec["mem_gb_hours"], 1) if mem_known else None
    rec["avg_cpus"] = round(raw_cpu / raw_hours, 1) if cpu_known and raw_hours else None
    rec["avg_gpus"] = round(raw_gpu / gpu_elapsed, 1) if gpu_elapsed else None
    rec["account"] = accounts[0] if accounts else ""
    rec["accounts"] = accounts
    rec["partition"] = partitions[0] if partitions else ""
    rec["partitions"] = partitions
    rec["gpu_type"] = gpu_types[0] if gpu_types else ""
    rec["avg_wait_s"] = round(wait_sum / wait_n) if wait_n else None
    rec["success_pct"] = (
        round(100.0 * rec["completed"] / terminal, 1) if terminal else None
    )
    rec["last_seen"] = seen.strftime("%Y-%m-%dT%H:%M:%SZ") if seen else None
    return rec


def _tally_users(rows, cutoff: datetime | None) -> tuple[dict, int, datetime | None]:
    acc: dict[str, dict] = {}
    kept = 0
    newest: datetime | None = None
    for row in rows:
        stamp = _job_stamp(row)
        if stamp is not None and (newest is None or stamp > newest):
            newest = stamp
        if cutoff is not None and (stamp is None or stamp < cutoff):
            continue
        name = _row_text(row, "user")
        if not name:
            continue
        rec = acc.setdefault(name, _blank_user(name))
        rec["jobs"] += 1
        elapsed = _elapsed_hours(_row_text(row, "elapsed"))
        rec["hours"] += elapsed
        tres = _row_text(row, "alloc_tres")
        gpus, gpu_type = _gpus(tres)
        if gpus:
            rec["gpu_jobs"] += 1
            rec["gpu_hours"] += gpus * elapsed
            rec["gpu_elapsed"] += elapsed
            _bump(rec["gpu_types"], gpu_type)
        cpus = row["ncpus"] if "ncpus" in row.keys() else None
        nodes = row["nnodes"] if "nnodes" in row.keys() else None
        if cpus is not None or _CPU_TRES.search(tres):
            rec["cpu_known"] = True
            rec["cpu_hours"] += _count(_positive_int(cpus), tres, _CPU_TRES) * elapsed
        if nodes is not None or _NODE_TRES.search(tres):
            rec["node_known"] = True
            rec["node_hours"] += _count(_positive_int(nodes), tres, _NODE_TRES) * elapsed
        if _MEM_TRES.search(tres) or _MEM_REQ.match(_row_text(row, "req_mem")):
            rec["mem_known"] = True
            rec["mem_gb_hours"] += _alloc_mem_gb(tres, _row_text(row, "req_mem")) * elapsed
        rec[_outcome(_row_text(row, "state"))] += 1
        start = _parse_utc(_row_text(row, "start"))
        submit = _parse_utc(_row_text(row, "submit"))
        if start is not None and submit is not None and start >= submit:
            rec["wait_s_sum"] += (start - submit).total_seconds()
            rec["wait_n"] += 1
        if stamp is not None and (rec["last_seen"] is None or stamp > rec["last_seen"]):
            rec["last_seen"] = stamp
        _bump(rec["accounts"], _row_text(row, "account"))
        _bump(rec["partitions"], _row_text(row, "partition"))
        kept += 1
    return acc, kept, newest


def _stamp_iso(stamp: datetime | None) -> str | None:
    if stamp is None:
        return None
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def _rows_in_window(rows, start: datetime | None, end: datetime | None) -> list:
    if start is None and end is None:
        return list(rows)
    kept = []
    for row in rows:
        stamp = _job_stamp(row)
        if stamp is None:
            continue
        if start is not None and stamp < start:
            continue
        if end is not None and stamp > end:
            continue
        kept.append(row)
    return kept


def users(hours: int | None = None) -> dict:
    """People and their usage from live sacct samples.

    Each person is one row. `hours` is wall-clock elapsed. `gpu_hours`,
    `cpu_hours`, `node_hours`, and `mem_gb_hours` multiply that elapsed
    time by the GPUs, CPUs, nodes, and gigabytes the job allocated.
    A missing allocation stays null, which the page renders as a dash.
    `account` is the account with the most jobs; `accounts` lists every
    account, and `partition` / `partitions` do the same for partitions.
    Outcome counts are exclusive and sum to `jobs`. `success_pct` is
    completed jobs over the settled outcomes, and `avg_wait_s` is the
    mean delay from submit to start. `last_seen` is the newest end,
    else start, else submit.

    The window is the last `hours` ending now. It never slides back to
    an older archive. `partial` is true when the collected samples do
    not cover that whole span; the rows then count only the sampled
    part. Omit `hours` to count every live job.
    """
    span = None if hours is None or hours == "all" else _clamp_hours(hours)
    window = "all" if span is None else "recent"
    files = _task_run_files()
    if not files:
        payload = dict(_EMPTY_USERS)
        payload["hours"] = span
        payload["window"] = window
        return payload
    try:
        fingerprint = tuple(
            (str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in files
        )
    except OSError:
        return dict(_EMPTY_USERS)
    key = (fingerprint, span)
    cached = _users_memo.get(key)
    if cached is not None:
        return cached
    now = datetime.now(timezone.utc)
    window_end = now
    window_start = None if span is None else now - timedelta(hours=span)
    intervals = _coverage_intervals(now)
    covered_start = intervals[0][0] if intervals else None
    covered_end = intervals[-1][1] if intervals else None
    partial = bool(
        span is not None and window_start is not None
        and not _interval_covers(intervals, window_start, window_end)
    )
    try:
        rows = _rows_in_window(_live_job_rows(), window_start, window_end)
    except sqlite3.Error:
        return dict(_EMPTY_USERS)
    acc, _kept, _newest = _tally_users(rows, None)
    out = [_publish_user(rec) for rec in acc.values()]
    for rec in out:
        rec["partial"] = partial
    out.sort(key=lambda r: (r["hours"], r["jobs"]), reverse=True)
    payload = {
        "available": True,
        "rows": out,
        "source": "telemetry/task_runs",
        "hours": span,
        "window": window,
        "partial": partial,
        "covered_start_utc": _stamp_iso(covered_start),
        "covered_end_utc": _stamp_iso(covered_end),
        "window_start_utc": _stamp_iso(window_start),
        "window_end_utc": _stamp_iso(window_end),
    }
    stale = [item for item in _users_memo if item[0] != fingerprint]
    for item in stale:
        del _users_memo[item]
    _users_memo[key] = payload
    return payload


def cluster(hours: int | None = None) -> dict:
    live = live_snapshot()
    cfg = cluster_config()
    latest = live.get("latest") or {}
    fleet = gpu_fleet()
    stats = task_stats(hours)
    gpus_total = sum(g["total"] for g in fleet)
    gpus_allocated = sum(g["allocated"] for g in fleet)
    gpus_free = sum(g["free"] for g in fleet)
    return {
        "generated_utc": _now(),
        "cluster": cfg.get("cluster") or "unity",
        "slurm_version": cfg.get("slurm_version") or "",
        "live": live,
        "partitions": partitions(hours),
        "gpu_fleet": fleet,
        "fairshare": fairshare(),
        "users": users(hours),
        "stats": stats,
        "kpis": {
            "gpu_running": latest.get("gpu_running", 0),
            "gpu_pending": latest.get("gpu_pending", 0),
            "free_nodes": latest.get("free_nodes", 0),
            "total_nodes": latest.get("total_nodes", 0),
            "gpu_types_free": latest.get("gpu_types_free", ""),
            "attached_projects": len(_registry.list_projects()),
            "gpus_total": gpus_total,
            "gpus_allocated": gpus_allocated,
            "gpus_free": gpus_free,
            "gpu_types_busy": sum(1 for g in fleet if g["allocated"] > 0),
        },
        "config_present": bool(cfg),
    }
