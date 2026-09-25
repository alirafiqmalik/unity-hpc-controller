"""Automated retrieval of Unity telemetry: state, on-demand runs, and a schedule.

The retrieval itself is `cluster-intel/sync-telemetry.sh` through
`scripts/hpc-sync-telemetry`. That script pulls the raw telemetry, rolls it
up, drops archived days from the cluster, and holds `locks/sync.lock` across
all three. This module does not repeat that lock. It starts the script, reads
the same lock to tell an operator whether a run is in progress, and keeps a
history of the runs it started.

The schedule is a thread in the controller process. It sleeps until the next
run is due, and a settings change wakes it. A due run samples in the cluster
session, then pulls. ADR 0003 put the schedule here. ADR 0004 replaced the
five-second poll and the resident collector.

Stdlib only. No function here raises to an HTTP caller (I6).
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from controller import cluster_session, events, registry
from lib import paths

REPO = Path(__file__).resolve().parent.parent
SYNC_SCRIPT = REPO / "scripts" / "hpc-sync-telemetry"

#: Longest a single retrieval may take before it is killed.
SYNC_TIMEOUT = 3600
#: How long to wait after a missed sample or a busy lock before trying again.
SAMPLE_BACKOFF_S = 30.0
#: How long stop_scheduler waits for the thread to notice.
SCHEDULER_JOIN_S = 2.0
#: Bounds on the schedule interval an operator may set.
MIN_INTERVAL_MINUTES = 5
MAX_INTERVAL_MINUTES = 1440
#: How much of a run's output is kept.
OUTPUT_KEEP = 4000
#: How many runs the history file keeps.
HISTORY_KEEP = 50

DEFAULTS = {
    "source": "",
    "schedule_enabled": False,
    "interval_minutes": 60,
    "schedule_since_utc": "",
    "script_mode": "once",
    "ssh_host": "unity",
    "ssh_identity": "",
}

_lock = threading.Lock()
_in_flight: dict | None = None
_scheduler: threading.Thread | None = None
_scheduler_stop = threading.Event()
_scheduler_wake = threading.Event()


# --------------------------------------------------------------------------
# time and paths


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    text = str(stamp).strip().replace("Z", "+00:00")
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def settings_path() -> Path:
    return paths.controller_dir() / "telemetry.json"


def history_path() -> Path:
    return paths.controller_dir() / "telemetry-runs.jsonl"


# --------------------------------------------------------------------------
# settings


def settings() -> dict:
    """The saved settings, with every default filled in."""
    out = dict(DEFAULTS)
    path = settings_path()
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return out
    if not isinstance(data, dict):
        return out
    for key in DEFAULTS:
        if key in data:
            out[key] = data[key]
    out["source"] = str(out.get("source") or "")
    out["schedule_enabled"] = bool(out.get("schedule_enabled"))
    out["interval_minutes"] = _clean_interval(out.get("interval_minutes"))
    out["schedule_since_utc"] = str(out.get("schedule_since_utc") or "")
    try:
        out["script_mode"] = cluster_session.clean_mode(out.get("script_mode"))
    except ValueError:
        out["script_mode"] = DEFAULTS["script_mode"]
    try:
        out["ssh_host"] = cluster_session.clean_ssh_host(out.get("ssh_host"))
    except ValueError:
        out["ssh_host"] = DEFAULTS["ssh_host"]
    try:
        out["ssh_identity"] = cluster_session.clean_ssh_identity(
            out.get("ssh_identity")
        )
    except ValueError:
        out["ssh_identity"] = DEFAULTS["ssh_identity"]
    return out


def _clean_interval(value) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return DEFAULTS["interval_minutes"]
    return max(MIN_INTERVAL_MINUTES, min(minutes, MAX_INTERVAL_MINUTES))


def clean_source(value) -> str:
    """A source an operator may save. Empty means 'not configured'."""
    text = str(value or "").strip()
    if not text:
        return ""
    if any(ch in text for ch in "\n\r\t\0"):
        raise ValueError("source must be one line")
    if len(text) > 512:
        raise ValueError("source is too long")
    return text


def save_settings(**changes) -> dict:
    """Write the settings an operator changed. Unknown keys are refused."""
    unknown = sorted(k for k in changes if k not in DEFAULTS)
    if unknown:
        raise ValueError(f"unknown setting: {', '.join(unknown)}")
    current = settings()
    if "source" in changes:
        current["source"] = clean_source(changes["source"])
    if "interval_minutes" in changes:
        raw = changes["interval_minutes"]
        try:
            minutes = int(raw)
        except (TypeError, ValueError):
            raise ValueError("interval_minutes must be a whole number") from None
        if not MIN_INTERVAL_MINUTES <= minutes <= MAX_INTERVAL_MINUTES:
            raise ValueError(
                f"interval_minutes must be {MIN_INTERVAL_MINUTES}"
                f"–{MAX_INTERVAL_MINUTES}"
            )
        current["interval_minutes"] = minutes
    if "schedule_enabled" in changes:
        wanted = bool(changes["schedule_enabled"])
        if wanted and not current["schedule_enabled"]:
            # The clock for the first scheduled run starts now, so switching the
            # schedule on does not immediately pull.
            current["schedule_since_utc"] = _iso(_now())
        current["schedule_enabled"] = wanted
    if "schedule_since_utc" in changes:
        current["schedule_since_utc"] = str(changes["schedule_since_utc"] or "")
    if "script_mode" in changes:
        current["script_mode"] = cluster_session.clean_mode(changes["script_mode"])
    if "ssh_host" in changes:
        current["ssh_host"] = cluster_session.clean_ssh_host(changes["ssh_host"])
    if "ssh_identity" in changes:
        current["ssh_identity"] = cluster_session.clean_ssh_identity(
            changes["ssh_identity"]
        )
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)
    # The schedule thread sleeps until the next due time. A write is the
    # signal that the due time may have changed.
    _scheduler_wake.set()
    return current


# --------------------------------------------------------------------------
# source resolution


def _project_source() -> tuple[str, str]:
    """The first UNITY_TELEMETRY_SRC an attached project's .env declares."""
    for rec in registry.list_projects():
        env_file = Path(rec.get("path", "")) / "unityHPC" / ".env"
        try:
            text = env_file.read_text(errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("UNITY_TELEMETRY_SRC"):
                continue
            _, _, value = line.partition("=")
            value = value.split("#", 1)[0].strip().strip("'\"")
            if value:
                return value, f"project:{rec.get('slug', '')}"
    return "", ""


def resolve_source() -> dict:
    """Where the retrieval reads from, and which layer named it.

    Order: the saved controller setting, then the controller's own environment,
    then the first attached project that declares one.
    """
    saved = settings()["source"]
    if saved:
        return {"value": saved, "origin": "settings", "configured": True}
    from_env = str(os.environ.get("UNITY_TELEMETRY_SRC") or "").strip()
    if from_env:
        return {"value": from_env, "origin": "environment", "configured": True}
    value, origin = _project_source()
    if value:
        return {"value": value, "origin": origin, "configured": True}
    return {"value": "", "origin": "none", "configured": False}


# --------------------------------------------------------------------------
# state readers


def sync_running() -> bool:
    """True while something holds locks/sync.lock.

    `sync-telemetry.sh` takes that lock for the pull and the rollup together. A
    separate open here is a separate file description, so the test is honest
    even when the holder is a child of this process.
    """
    lock = paths.sync_lock()
    try:
        fd = os.open(lock, os.O_RDONLY)
    except OSError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def _freshness(path: Path) -> dict:
    out = {"path": str(path), "present": False, "mtime_utc": None,
           "age_s": None, "size_bytes": None}
    try:
        stat = path.stat()
    except OSError:
        return out
    when = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
    out.update({
        "present": True,
        "mtime_utc": _iso(when),
        "age_s": int(max(0, (_now() - when).total_seconds())),
        "size_bytes": stat.st_size,
    })
    return out


def _telemetry_state() -> dict:
    root = paths.telemetry_dir()
    out = {"path": str(root), "present": root.is_dir(), "days": 0,
           "newest_day": None, "mtime_utc": None, "age_s": None}
    if not out["present"]:
        return out
    try:
        days = sorted(p.name for p in root.iterdir() if p.is_dir())
    except OSError:
        return out
    out["days"] = len(days)
    out["newest_day"] = days[-1] if days else None
    newest = 0.0
    for day in days[-3:]:
        try:
            for item in (root / day).iterdir():
                newest = max(newest, item.stat().st_mtime)
        except OSError:
            continue
    if newest:
        when = datetime.fromtimestamp(newest, timezone.utc)
        out["mtime_utc"] = _iso(when)
        out["age_s"] = int(max(0, (_now() - when).total_seconds()))
    return out


def rollup_state() -> dict:
    """What summaries.db says about its own last rollup."""
    import sqlite3

    out = {"last_rollup_utc": None, "age_s": None, "schema_version": None,
           "current": False}
    db = paths.summaries_db()
    if not db.exists():
        return out
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = dict(con.execute("SELECT key, value FROM meta").fetchall())
        finally:
            con.close()
    except sqlite3.Error:
        return out
    out["last_rollup_utc"] = rows.get("last_rollup_utc")
    out["schema_version"] = rows.get("schema_version")
    when = _parse(out["last_rollup_utc"])
    if when is not None:
        out["age_s"] = int(max(0, (_now() - when).total_seconds()))
    return out


def _mark_current(rollup: dict, telemetry: dict) -> dict:
    """The rollup is current when it ran no earlier than the newest raw file."""
    rolled = _parse(rollup.get("last_rollup_utc"))
    raw = _parse(telemetry.get("mtime_utc"))
    if rolled is None:
        rollup["current"] = False
    elif raw is None:
        rollup["current"] = True
    else:
        rollup["current"] = rolled >= raw
    return rollup


# --------------------------------------------------------------------------
# run history


def _append_history(row: dict) -> None:
    path = history_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
        lines = path.read_text(errors="replace").splitlines()
        if len(lines) > HISTORY_KEEP:
            path.write_text("\n".join(lines[-HISTORY_KEEP:]) + "\n")
    except OSError:
        return


def history(limit: int = 10) -> list[dict]:
    """The most recent retrievals, newest first."""
    try:
        limit = max(1, min(int(limit), HISTORY_KEEP))
    except (TypeError, ValueError):
        limit = 10
    path = history_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return []
    rows: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    rows.reverse()
    return rows[:limit]


def last_run() -> dict | None:
    rows = history(1)
    return rows[0] if rows else None


def last_success() -> dict | None:
    for row in history(HISTORY_KEEP):
        if row.get("status") == "ok":
            return row
    return None


# --------------------------------------------------------------------------
# running a retrieval


def _classify(rc: int, output: str) -> str:
    if rc != 0:
        return "failed"
    if "sync already running" in output:
        return "already-running"
    return "ok"


def _execute(run: dict) -> dict:
    """Do one retrieval and record it. Never raises."""
    env = dict(os.environ)
    env["UNITY_TELEMETRY_SRC"] = run["source"]
    env["UNITY_HPC_DATA"] = str(paths.data_dir())
    started = _now()
    try:
        timeout = int(os.environ.get("UNITY_HPC_SYNC_TIMEOUT") or SYNC_TIMEOUT)
    except ValueError:
        timeout = SYNC_TIMEOUT
    try:
        proc = subprocess.run(
            ["bash", str(SYNC_SCRIPT)],
            capture_output=True, text=True, env=env,
            cwd=str(REPO), timeout=timeout,
        )
        rc = proc.returncode
        output = ((proc.stdout or "") + (proc.stderr or "")).strip()
        status = _classify(rc, output)
    except subprocess.TimeoutExpired:
        rc = 124
        output = f"retrieval did not finish in {timeout}s"
        status = "failed"
    except OSError as exc:
        rc = -1
        output = f"could not start {SYNC_SCRIPT}: {exc}"
        status = "failed"
    finished = _now()
    run.update({
        "finished_utc": _iso(finished),
        "duration_s": round((finished - started).total_seconds(), 1),
        "rc": rc,
        "status": status,
        "output": output[-OUTPUT_KEEP:],
    })
    _append_history(run)
    events.record(
        "sync",
        f"telemetry retrieval {status} ({run['reason']})",
        status=status, rc=rc, run_id=run["id"],
    )
    global _in_flight
    with _lock:
        if _in_flight is not None and _in_flight.get("id") == run["id"]:
            _in_flight = None
    return run


def start_sync(reason: str = "manual", background: bool = True) -> dict:
    """Start one retrieval.

    Returns at once. `started` is false when a retrieval is already in flight,
    or when no source is configured.
    """
    global _in_flight
    source = resolve_source()
    if not source["configured"]:
        return {
            "ok": False, "started": False, "status": "unconfigured",
            "message": "no telemetry source is configured",
        }
    with _lock:
        if _in_flight is not None:
            return {
                "ok": True, "started": False, "status": "already-running",
                "message": "a retrieval is already in flight",
                "run": dict(_in_flight),
            }
        if sync_running():
            return {
                "ok": True, "started": False, "status": "already-running",
                "message": "another process holds the sync lock",
            }
        run = {
            "id": uuid.uuid4().hex[:12],
            "reason": str(reason or "manual"),
            "source": source["value"],
            "origin": source["origin"],
            "started_utc": _iso(_now()),
            "status": "running",
        }
        _in_flight = run
    events.record(
        "sync", f"telemetry retrieval started ({run['reason']})", run_id=run["id"]
    )
    if not background:
        return {"ok": True, "started": True, "status": "done",
                "run": _execute(dict(run))}
    thread = threading.Thread(
        target=_execute, args=(dict(run),),
        name=f"unity-telemetry-{run['id']}", daemon=True,
    )
    thread.start()
    return {"ok": True, "started": True, "status": "started", "run": run}


def _finish_script(run: dict, report: dict) -> dict:
    """Record a script that did not run. The pull does not start."""
    finished = _now()
    started = _parse(run.get("started_utc")) or finished
    run.update({
        "finished_utc": _iso(finished),
        "duration_s": round((finished - started).total_seconds(), 1),
        "rc": report.get("rc", 1),
        "status": "failed",
        "output": str(report.get("error") or "script did not run")[-OUTPUT_KEEP:],
    })
    if report.get("session_log"):
        run["session_log"] = report["session_log"]
    _append_history(run)
    events.record(
        "sync",
        f"script {run.get('mode')} failed ({run['reason']})",
        status="failed", rc=run["rc"], run_id=run["id"],
    )
    global _in_flight
    with _lock:
        if _in_flight is not None and _in_flight.get("id") == run["id"]:
            _in_flight = None
    return run


def _execute_script(run: dict) -> dict:
    """Run the saved cluster script, then the local pull. Never raises."""
    try:
        report = cluster_session.collect(
            settings(), run["source"], mode=run.get("mode") or "once",
        )
    except Exception as exc:  # a script fault must not kill the caller (I6)
        report = {"ok": False, "error": str(exc)}
    if not report.get("ok"):
        return _finish_script(run, report)
    return _execute(run)


def start_script(mode: str | None = None, reason: str = "manual",
                 background: bool = True) -> dict:
    """Run one cluster script, then pull.

    `mode` defaults to the saved script. The schedule and the Run button
    share this path. Returns at once when `background` is set.
    """
    global _in_flight
    chosen = cluster_session.clean_mode(mode or settings()["script_mode"])
    source = resolve_source()
    if not source["configured"]:
        return {
            "ok": False, "started": False, "status": "unconfigured",
            "message": "no telemetry source is configured",
        }
    with _lock:
        if _in_flight is not None:
            return {
                "ok": True, "started": False, "status": "already-running",
                "message": "a retrieval is already in flight",
                "run": dict(_in_flight),
            }
        if sync_running():
            return {
                "ok": True, "started": False, "status": "already-running",
                "message": "another process holds the sync lock",
            }
        run = {
            "id": uuid.uuid4().hex[:12],
            "reason": str(reason or "manual"),
            "mode": chosen,
            "source": source["value"],
            "origin": source["origin"],
            "started_utc": _iso(_now()),
            "status": "running",
        }
        _in_flight = run
    events.record(
        "sync", f"script {chosen} started ({run['reason']})",
        run_id=run["id"], mode=chosen,
    )
    if not background:
        finished = _execute_script(dict(run))
        ok = finished.get("status") != "failed"
        return {"ok": ok, "started": ok, "status": finished.get("status"),
                "run": finished}
    thread = threading.Thread(
        target=_execute_script, args=(dict(run),),
        name=f"unity-telemetry-{run['id']}", daemon=True,
    )
    thread.start()
    return {"ok": True, "started": True, "status": "started", "run": run}


def close_session() -> dict:
    """Close the cluster session for the configured source."""
    source = resolve_source()
    if not source["configured"]:
        return {
            "ok": False, "status": "unconfigured",
            "message": "no telemetry source is configured",
        }
    cfg = settings()
    report = cluster_session.close_session(
        source["value"],
        host=cfg.get("ssh_host") or "unity",
        identity=cfg.get("ssh_identity") or "",
    )
    if report.get("ok") and not report.get("skipped"):
        events.record("sync", "cluster session closed", session=report.get("session"))
    return report


# --------------------------------------------------------------------------
# the schedule


def next_run_utc(cfg: dict | None = None) -> str | None:
    """When the schedule fires next, or None when it is off."""
    cfg = cfg or settings()
    if not cfg.get("schedule_enabled"):
        return None
    anchor = _parse(cfg.get("schedule_since_utc"))
    newest = last_run()
    finished = _parse(newest.get("finished_utc")) if newest else None
    started = _parse(newest.get("started_utc")) if newest else None
    last_activity = finished or started
    if last_activity is not None and (anchor is None or last_activity > anchor):
        anchor = last_activity
    if anchor is None:
        anchor = _now()
    return _iso(anchor + timedelta(minutes=_clean_interval(cfg["interval_minutes"])))


def _due(cfg: dict) -> bool:
    when = _parse(next_run_utc(cfg))
    return when is not None and _now() >= when


def _seconds_until_due(cfg: dict) -> float | None:
    """Seconds until the next run, 0 when it is due, None when the schedule is off."""
    when = _parse(next_run_utc(cfg))
    if when is None:
        return None
    return max(0.0, (when - _now()).total_seconds())


def _fire_schedule(cfg: dict) -> bool:
    """Run the saved script in the cluster session, then pull."""
    if not resolve_source()["configured"]:
        return False
    result = start_script(
        mode=cfg.get("script_mode") or "once",
        reason="schedule",
        background=False,
    )
    return bool(result.get("started"))


def _scheduler_loop() -> None:
    """Sleep until the next due time. A settings write or a stop wakes it."""
    while not _scheduler_stop.is_set():
        try:
            delay = _seconds_until_due(settings())
        except Exception:  # a schedule fault must not kill the thread (I6)
            delay = SAMPLE_BACKOFF_S
        if delay is None:
            _scheduler_wake.wait()
            _scheduler_wake.clear()
            continue
        if delay > 0 and _scheduler_wake.wait(delay):
            _scheduler_wake.clear()
            continue
        if _scheduler_stop.is_set():
            return
        try:
            cfg = settings()
            if not _due(cfg):
                continue
            if _in_flight is not None or sync_running():
                _scheduler_wake.wait(SAMPLE_BACKOFF_S)
                _scheduler_wake.clear()
                continue
            if not _fire_schedule(cfg):
                _scheduler_wake.wait(SAMPLE_BACKOFF_S)
                _scheduler_wake.clear()
        except Exception:
            _scheduler_wake.wait(SAMPLE_BACKOFF_S)
            _scheduler_wake.clear()


def start_scheduler() -> bool:
    """Start the schedule thread once. True when this call started it."""
    global _scheduler
    with _lock:
        if _scheduler is not None and _scheduler.is_alive():
            return False
        _scheduler_stop.clear()
        _scheduler_wake.clear()
        _scheduler = threading.Thread(
            target=_scheduler_loop, name="unity-telemetry-schedule", daemon=True
        )
        _scheduler.start()
        return True


def stop_scheduler() -> None:
    global _scheduler
    _scheduler_stop.set()
    _scheduler_wake.set()
    thread = _scheduler
    if thread is not None and thread.is_alive():
        thread.join(timeout=SCHEDULER_JOIN_S)
    if thread is None or not thread.is_alive():
        _scheduler = None


def scheduler_alive() -> bool:
    return _scheduler is not None and _scheduler.is_alive()


# --------------------------------------------------------------------------
# the one payload the dashboard reads


def status(limit: int = 10) -> dict:
    """Everything the automation panel shows."""
    cfg = settings()
    telemetry = _telemetry_state()
    rollup = _mark_current(rollup_state(), telemetry)
    running = sync_running()
    flight = dict(_in_flight) if _in_flight is not None else None
    return {
        "source": resolve_source(),
        "running": bool(running or flight),
        "in_flight": flight,
        "last_run": last_run(),
        "last_success": last_success(),
        "schedule": {
            "enabled": cfg["schedule_enabled"],
            "interval_minutes": cfg["interval_minutes"],
            "next_run_utc": next_run_utc(cfg),
            "thread_alive": scheduler_alive(),
            "min_interval_minutes": MIN_INTERVAL_MINUTES,
            "max_interval_minutes": MAX_INTERVAL_MINUTES,
            "inactivity_timeout_s": cluster_session.inactivity_timeout_s(
                cfg["interval_minutes"]
            ),
            "session": cluster_session.SESSION_NAME,
            "script": cfg["script_mode"],
            "scripts": list(cluster_session.MODES),
        },
        "stores": {
            "summaries_db": _freshness(paths.summaries_db()),
            "snapshot_csv": _freshness(paths.snapshot_csv()),
            "telemetry": telemetry,
        },
        "ssh": ssh_status(),
        "rollup": rollup,
        "history": history(limit),
    }


def probe_ssh() -> dict:
    """Run the saved alias once so the panel can test access."""
    cfg = settings()
    return cluster_session.probe(cfg["ssh_host"], cfg["ssh_identity"])


def ssh_status() -> dict:
    """The saved alias, and whether its key still needs a passphrase."""
    cfg = settings()
    report = cluster_session.agent_status(cfg["ssh_host"], cfg["ssh_identity"])
    report["host"] = cfg["ssh_host"]
    report["identity"] = cfg["ssh_identity"]
    report["command"] = cluster_session.ssh_command(
        cfg["ssh_host"], cfg["ssh_identity"]
    )
    return report


def unlock_ssh(passphrase: str) -> dict:
    """Load the saved identity. The passphrase is never stored or logged."""
    cfg = settings()
    report = cluster_session.unlock_identity(
        cfg["ssh_identity"], passphrase, host=cfg["ssh_host"],
    )
    if report.get("ok"):
        events.record("sync", "cluster key unlocked")
    return report
