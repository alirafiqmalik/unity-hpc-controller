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


def _partition_util() -> dict[str, float]:
    """Latest hourly util (0–100) per partition. Empty when the rollup has none."""
    con = _open_summaries()
    if con is None:
        return {}
    try:
        rows = con.execute(
            "SELECT resource_id, util_mean FROM hourly_resource "
            "WHERE resource_kind = 'partition' AND hour_utc = ("
            "  SELECT MAX(hour_utc) FROM hourly_resource "
            "  WHERE resource_kind = 'partition')"
        ).fetchall()
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


def partitions() -> list[dict]:
    cfg = cluster_config()
    parts = cfg.get("partitions") or {}
    if not isinstance(parts, dict):
        return []
    util = _partition_util()
    rollup = {r["partition"]: r for r in (task_stats().get("by_partition") or [])}
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
             "heatmap": [], "window": "recent", "hours": hours,
             "freshness_utc": None, "stale_s": None}
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
        "heatmap": _heatmap(slots, series),
        "window": window,
        "hours": hours,
        "freshness_utc": newest_slot,
        "stale_s": stale_s,
    }


def _heatmap(slots: list[str], series: dict[str, list]) -> list[dict]:
    """Average total GPU util per (day-of-week × hour), from the usage series."""
    per_slot: dict[str, float] = {}
    for name, vals in series.items():
        del name
        for slot, value in zip(slots, vals):
            if value is None:
                continue
            per_slot[slot] = per_slot.get(slot, 0.0) + float(value)
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
        {"dow": dow, "hour": hour, "value": round(sum(vals) / len(vals), 1)}
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
        if hours is None:
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
            if not rows:
                newest = con.execute(
                    "SELECT MAX(day_utc) FROM task_run"
                ).fetchone()[0]
                if newest:
                    try:
                        end = datetime.strptime(newest, "%Y-%m-%d").replace(
                            tzinfo=timezone.utc
                        )
                    except ValueError:
                        end = datetime.now(timezone.utc)
                    start = (end - timedelta(hours=hours)).strftime("%Y-%m-%d")
                    rows = con.execute(
                        query + " WHERE day_utc >= ? GROUP BY 1, 2, 3",
                        (start,),
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


def _raw_jobs_db() -> Path | None:
    """The archived sacct dump, if a migration left one."""
    root = paths.archive_dir()
    if not root.is_dir():
        return None
    found = sorted(p for p in root.glob("*/raw_jobs.db") if p.is_file())
    return found[-1] if found else None


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


_EMPTY_USERS = {"available": False, "rows": [], "source": None}
_users_memo: dict[tuple, dict] = {}


def users() -> dict:
    """Cluster accounts and their usage, from the archived sacct dump.

    The live rollup never stored a username — sacct's User column was
    dropped. The pre-redesign `raw_jobs.db` still has it, so the Users
    tab reads that store. Empty when the archive is absent (I6).
    """
    db = _raw_jobs_db()
    if db is None:
        return dict(_EMPTY_USERS)
    try:
        mtime = db.stat().st_mtime
    except OSError:
        return dict(_EMPTY_USERS)
    key = (str(db), mtime)
    cached = _users_memo.get(key)
    if cached is not None:
        return cached
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                "SELECT user, account, elapsed, alloc_tres FROM raw_jobs "
                "WHERE user IS NOT NULL AND user != ''"
            ).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return dict(_EMPTY_USERS)
    if not rows:
        payload = dict(_EMPTY_USERS)
        payload["source"] = str(db)
        _users_memo[key] = payload
        return payload
    acc: dict[str, dict] = {}
    for row in rows:
        name = str(row["user"]).strip()
        if not name:
            continue
        rec = acc.setdefault(name, {
            "user": name, "jobs": 0, "hours": 0.0,
            "gpu_jobs": 0, "gpu_hours": 0.0, "accounts": {},
        })
        rec["jobs"] += 1
        hours = _elapsed_hours(row["elapsed"])
        rec["hours"] += hours
        tres = str(row["alloc_tres"] or "")
        if "gres/gpu" in tres.lower():
            rec["gpu_jobs"] += 1
            rec["gpu_hours"] += hours
        acct = str(row["account"] or "").strip()
        if acct:
            rec["accounts"][acct] = rec["accounts"].get(acct, 0) + 1
    out = []
    for rec in acc.values():
        accounts = rec.pop("accounts")
        rec["hours"] = round(rec["hours"], 1)
        rec["gpu_hours"] = round(rec["gpu_hours"], 1)
        rec["account"] = max(accounts, key=accounts.get) if accounts else ""
        out.append(rec)
    out.sort(key=lambda r: (r["hours"], r["jobs"]), reverse=True)
    payload = {"available": True, "rows": out, "source": "archive/raw_jobs"}
    _users_memo[key] = payload
    return payload


def cluster() -> dict:
    live = live_snapshot()
    cfg = cluster_config()
    latest = live.get("latest") or {}
    fleet = gpu_fleet()
    stats = task_stats()
    gpus_total = sum(g["total"] for g in fleet)
    gpus_allocated = sum(g["allocated"] for g in fleet)
    gpus_free = sum(g["free"] for g in fleet)
    return {
        "generated_utc": _now(),
        "cluster": cfg.get("cluster") or "unity",
        "slurm_version": cfg.get("slurm_version") or "",
        "live": live,
        "partitions": partitions(),
        "gpu_fleet": fleet,
        "fairshare": fairshare(),
        "users": users(),
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
