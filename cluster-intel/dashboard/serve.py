#!/usr/bin/env python3
"""
serve.py — tiny, dependency-free web server for the Unity cluster monitor.

Reads the data cluster-intel already collects and serves a single dashboard
page + one JSON endpoint. Stdlib only (http.server, sqlite3, csv, json) — no
Flask, no pandas, no pyarrow. Meant to be run on a machine on your tailnet and
viewed from your laptop/phone over Tailscale.

    python3 serve.py                 # http://0.0.0.0:8787
    python3 serve.py --port 9000
    python3 serve.py --host 100.x.y.z # bind a specific tailnet address

Data sources live in the shared, version-independent data dir $UNITY_HPC_DATA
(default ~/.local/share/unity-hpc). The historical panels currently read the
pre-redesign snapshot archived under archive/ (see dashboard/README.md);
the live summaries.db rollup.
    snapshot.csv               live queue signal (15-min poller)
    cluster-profile.md         shared cluster profile (header context)

Everything degrades gracefully: a missing source becomes an empty section on
the page, never a crash. This is a proof-of-concept — small on purpose so it is
easy to read and edit.
"""

import argparse
import errno
import csv
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HERE = Path(__file__).resolve().parent


def data_dir() -> Path:
    """Machine-wide cluster-intel data root — shared by every project and
    independent of the plugin version. Override with $UNITY_HPC_DATA; default
    $XDG_DATA_HOME/unity-hpc or ~/.local/share/unity-hpc."""
    d = os.environ.get("UNITY_HPC_DATA")
    if d:
        return Path(d).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "unity-hpc"


DATA = data_dir()
SUMMARY_DB = DATA / "summaries.db"
SNAPSHOT_CSV = DATA / "snapshot.csv"
SUMMARY_JSON = DATA / "analysis" / "usage_summary.json"
PROFILE_MD = DATA / "cluster-profile.md"

DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ─── data assembly ────────────────────────────────────────────────────────────

def _parse_slot(s: str) -> datetime | None:
    """Parse a slot_start_utc like 2026-01-01T00:00:00Z."""
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def historical(hours: int, project: str | None = None,
               campaign: str | None = None) -> dict:
    """Read GPU usage and task metrics from the live summaries database."""
    empty = {"available": False, "series": {}, "slots": [],
             "heatmap": [], "by_type": [], "task_stats": {},
             "freshness_utc": None, "span": None}
    if not SUMMARY_DB.exists():
        return empty

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    con = sqlite3.connect(SUMMARY_DB)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT hour_utc AS slot_start_utc, resource_id AS gpu_type, "
            "ROUND(util_mean * 100.0, 1) AS gpus "
            "FROM hourly_resource "
            "WHERE resource_kind = 'gpu_type' AND hour_utc >= ? "
            "ORDER BY hour_utc, resource_id",
            (cutoff,),
        ).fetchall()
    except sqlite3.OperationalError:
        con.close()
        return empty

    if not rows:
        con.close()
        return empty

    # ── time series: one line per gpu_type, aligned on a shared slot axis ──
    slots: list[str] = []
    slot_index: dict[str, int] = {}
    series: dict[str, list] = {}          # gpu_type -> gpus per slot (None = gap)
    per_slot_total: dict[str, float] = {}  # slot -> total gpus (for heatmap)

    for r in rows:
        slot, gtype = r["slot_start_utc"], (r["gpu_type"] or "cpu-only")
        if slot not in slot_index:
            slot_index[slot] = len(slots)
            slots.append(slot)
        per_slot_total[slot] = per_slot_total.get(slot, 0) + (r["gpus"] or 0)
        series.setdefault(gtype, [None] * 0)

    for gtype in series:
        series[gtype] = [None] * len(slots)
    for r in rows:
        gtype = r["gpu_type"] or "cpu-only"
        series[gtype][slot_index[r["slot_start_utc"]]] = r["gpus"] or 0

    # ── heatmap: average total GPU usage per (day-of-week × hour) ──
    cells: dict[tuple, list] = {}
    for slot, total in per_slot_total.items():
        dt = _parse_slot(slot)
        if dt is None:
            continue
        cells.setdefault((dt.weekday(), dt.hour), []).append(total)
    heatmap = [
        {"dow": d, "hour": h, "value": round(sum(v) / len(v), 1)}
        for (d, h), v in cells.items()
    ]

    # ── per-type summary: avg / peak / median GPU usage over the window ──
    by_type = []
    for gtype, vals_full in series.items():
        vals = [v for v in vals_full if v is not None]
        if not vals:
            continue
        s = sorted(vals)
        median = s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2
        by_type.append({
            "gpu_type": gtype,
            "avg": round(sum(vals) / len(vals), 1),
            "peak": max(vals),
            "median": round(median, 1),
        })
    by_type.sort(key=lambda x: x["avg"], reverse=True)

    task_stats = {}
    try:
        clauses = ["submit >= ?"]
        params: list[str] = [cutoff]
        if project:
            clauses.append("project = ?")
            params.append(project)
        if campaign:
            clauses.append("campaign = ?")
            params.append(campaign)
        task = con.execute(
            "SELECT COUNT(*) AS n, AVG(wait_s) AS wait_s, "
            "AVG(CASE WHEN state = 'COMPLETED' THEN 1.0 ELSE 0.0 END) AS success_rate "
            "FROM task_run WHERE " + " AND ".join(clauses), params
        ).fetchone()
        if task and task["n"]:
            task_stats = {
                "runs": task["n"],
                "wait_s_avg": round(task["wait_s"], 1) if task["wait_s"] is not None else None,
                "success_rate": round(task["success_rate"] or 0, 3),
            }
    except sqlite3.OperationalError:
        pass
    finally:
        con.close()

    return {
        "available": True,
        "slots": slots,
        "series": series,
        "heatmap": heatmap,
        "by_type": by_type,
        "task_stats": task_stats,
        "freshness_utc": slots[-1],
        "span": {"from": slots[0], "to": slots[-1], "count": len(slots)},
    }


def live(max_points: int = 96) -> dict:
    """Latest KPIs + a recent queue trend from snapshot.csv (default ~last 24h)."""
    empty = {"available": False, "latest": {}, "trend": []}
    if not SNAPSHOT_CSV.exists():
        return empty
    try:
        with SNAPSHOT_CSV.open(newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except OSError:
        return empty
    if not rows:
        return empty

    def num(row, key):
        try:
            return int(row.get(key, 0) or 0)
        except ValueError:
            return 0

    tail = rows[-max_points:]
    trend = [
        {
            "t": r.get("timestamp_utc", ""),
            "running": num(r, "gpu_running"),
            "pending": num(r, "gpu_pending"),
            "preempt_pending": num(r, "gpu_preempt_pending"),
        }
        for r in tail
    ]
    last = rows[-1]
    latest = {
        "timestamp_utc": last.get("timestamp_utc", ""),
        "gpu_running": num(last, "gpu_running"),
        "gpu_pending": num(last, "gpu_pending"),
        "gpu_preempt_pending": num(last, "gpu_preempt_pending"),
        "total_nodes": num(last, "total_nodes"),
        "free_nodes": num(last, "free_nodes"),
        "gpu_types_free": last.get("gpu_types_free", ""),
    }
    return {"available": True, "latest": latest, "trend": trend}


def summary() -> dict:
    if SUMMARY_JSON.exists():
        try:
            return json.loads(SUMMARY_JSON.read_text())
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def profile_meta() -> dict:
    """The shared cluster profile (written by unity-hpc:recon), if present. Returns the
    full markdown so the page can render it as a visible panel, plus the
    'last updated' line for the header."""
    if not PROFILE_MD.exists():
        return {}
    text = PROFILE_MD.read_text(errors="replace")
    updated = ""
    for line in text.splitlines():
        if line.lower().startswith("_last updated"):
            updated = line.strip("_ ")
            break
    return {"present": True, "updated": updated, "markdown": text[:20000]}


def build_payload(hours: int, project: str | None = None,
                  campaign: str | None = None) -> dict:
    return {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "window_hours": hours,
        "historical": historical(hours, project, campaign),
        "live": live(),
        "summary": summary(),
        "profile": profile_meta(),
    }


# ─── http ─────────────────────────────────────────────────────────────────────

CONTENT_TYPES = {".html": "text/html", ".js": "application/javascript",
                 ".css": "text/css"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):  # keep the console quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path

        if route == "/api/data":
            qs = parse_qs(parsed.query)
            try:
                hours = max(1, min(int(qs.get("hours", ["168"])[0]), 24 * 3650))
            except ValueError:
                hours = 168
            body = json.dumps(build_payload(
                hours, qs.get("project", [None])[0], qs.get("campaign", [None])[0]
            )).encode()
            return self._send(200, body, "application/json")

        # static files, restricted to this directory
        rel = "index.html" if route == "/" else route.lstrip("/")
        target = (HERE / rel).resolve()
        if HERE not in target.parents or not target.is_file():
            return self._send(404, b"not found", "text/plain")
        ctype = CONTENT_TYPES.get(target.suffix, "application/octet-stream")
        return self._send(200, target.read_bytes(), ctype)


def main():
    ap = argparse.ArgumentParser(description="Unity cluster monitor (Tailscale-friendly).")
    ap.add_argument("--host", default="0.0.0.0", help="bind address (default 0.0.0.0)")
    ap.add_argument("--port", type=int, default=8787, help="port (default 8787)")
    args = ap.parse_args()

    try:
        srv = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print(f"Dashboard cannot bind {args.host}:{args.port}: address already in use. "
                  f"Stop the existing server or choose --port <unused-port>.", file=sys.stderr)
            return 2
        raise
    print(f"Unity cluster monitor → http://{args.host}:{args.port}")
    print(f"  summaries.db: {'ok' if SUMMARY_DB.exists() else 'MISSING'}  ({SUMMARY_DB})")
    print(f"  snapshot   : {'ok' if SNAPSHOT_CSV.exists() else 'MISSING'}  ({SNAPSHOT_CSV})")
    print("  Ctrl-C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
