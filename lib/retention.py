"""Retention: the local tree is the archive; the cluster is staging (I8).

A pull never deletes a local day. After the rollup, days that are present
locally, fully summarised, and not today may leave the cluster. summaries.db
absent withholds that remote prune. UNITY_HPC_FORCE_PRUNE=1 skips the
summarised check only. Stdlib only.
"""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from lib import paths, queries

_DAY = re.compile(r"^(?:telemetry/)?(\d{4}-\d{2}-\d{2})(?:/|$)")
_DAY_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def parse_deletions(itemize_lines: Iterable[str]) -> set[str]:
    """Day-directories a real --delete would remove, from --itemize-changes output.

    rsync prints '*deleting   <path>' for each removed entry. We collect the
    leading YYYY-MM-DD component so per-file deletions collapse to their day.

    Input contract: paths are relative to the transfer root, so either a bare
    ``YYYY-MM-DD/...`` (sync-telemetry.sh rsyncs `.../telemetry/` as the
    transfer root, so this is the real-world form) or the same day-dir carrying
    a single defensive ``telemetry/`` prefix. The match is start-anchored, so
    ``telemetry-imported/2026-05-01/...`` and ``summaries.db`` never match —
    only genuine ``telemetry/`` day-dirs are gated."""
    days: set[str] = set()
    for line in itemize_lines:
        line = line.strip()
        if not line.startswith("*deleting"):
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        m = _DAY.match(parts[1].strip())
        if m:
            days.add(m.group(1))
    return days


def retention_decision(delete_days: set[str], *, force: bool = False) -> tuple[bool, list[str]]:
    """Return (allow_delete, warnings). All-or-nothing (rsync --delete is)."""
    if force or not delete_days:
        return True, []
    if not paths.summaries_db().exists():
        return False, ["retention inactive: summaries.db absent — withholding "
                       "--delete until a rollup has run (set UNITY_HPC_FORCE_PRUNE=1 "
                       "to override)"]
    not_ready = sorted(d for d in delete_days if not queries.is_fully_summarised(d))
    if not_ready:
        return False, [f"withholding --delete for the whole run: not fully "
                       f"summarised yet: {', '.join(not_ready)}"]
    return True, []


def split_source(source: str) -> tuple[str | None, str]:
    """`(host, path)` for `host:/abs/telemetry`, or `(None, path)` when local."""
    text = str(source or "").strip().rstrip("/")
    if not text:
        raise ValueError("source is empty")
    if ":" in text:
        host, _, path = text.partition(":")
        host = host.strip()
        path = path.strip()
        if host and path.startswith("/"):
            return host, path
    return None, text


def local_day_present(day: str) -> bool:
    """True when the local archive holds at least one file for `day`."""
    if not _DAY_NAME.fullmatch(day):
        return False
    folder = paths.telemetry_dir() / day
    if not folder.is_dir():
        return False
    try:
        return any(folder.iterdir())
    except OSError:
        return False


def remote_prune_decision(
    remote_days: set[str],
    *,
    today: str | None = None,
    force: bool = False,
) -> tuple[list[str], list[str]]:
    """Days that may leave the cluster staging tree.

    Today's live day never goes. A day that is not on this machine never goes.
    `force` skips only the summarised check.
    """
    live = today or today_utc()
    warnings: list[str] = []
    drop: list[str] = []
    if not paths.summaries_db().exists() and not force:
        return [], ["retention inactive: summaries.db absent — withholding "
                    "remote prune until a rollup has run (set UNITY_HPC_FORCE_PRUNE=1 "
                    "to override)"]
    for day in sorted(remote_days):
        if not _DAY_NAME.fullmatch(day):
            continue
        if day == live:
            warnings.append(f"keeping live day {day} on the cluster")
            continue
        if not local_day_present(day):
            warnings.append(f"withholding {day}: not archived locally")
            continue
        if not force and not queries.is_fully_summarised(day):
            warnings.append(f"withholding {day}: not fully summarised")
            continue
        drop.append(day)
    return drop, warnings


def list_source_days(source: str, run=None) -> set[str]:
    """YYYY-MM-DD directories on the telemetry source."""
    host, path = split_source(source)
    if host is None:
        root = Path(path)
        if not root.is_dir():
            return set()
        try:
            return {p.name for p in root.iterdir()
                    if p.is_dir() and _DAY_NAME.fullmatch(p.name)}
        except OSError:
            return set()
    script = f"ls -1 {shlex.quote(path)}\n"
    runner = run or (lambda h, s: subprocess.run(
        ["ssh", h, "bash", "-s"],
        input=s, capture_output=True, text=True,
    ))
    try:
        proc = runner(host, script)
    except OSError:
        return set()
    if getattr(proc, "returncode", 1) != 0:
        return set()
    days: set[str] = set()
    for line in (getattr(proc, "stdout", "") or "").splitlines():
        name = line.strip().rstrip("/")
        if _DAY_NAME.fullmatch(name):
            days.add(name)
    return days


def drop_source_days(source: str, days: list[str], run=None) -> dict:
    """Remove validated day directories from the source. Never touches local."""
    safe = [d for d in days if _DAY_NAME.fullmatch(d)]
    if not safe:
        return {"ok": True, "dropped": []}
    host, path = split_source(source)
    if host is None:
        root = Path(path)
        dropped: list[str] = []
        for day in safe:
            target = root / day
            if target.is_dir():
                shutil.rmtree(target)
                dropped.append(day)
        return {"ok": True, "dropped": dropped}
    targets = " ".join(shlex.quote(f"{path}/{day}") for day in safe)
    script = f"rm -rf -- {targets}\n"
    runner = run or (lambda h, s: subprocess.run(
        ["ssh", h, "bash", "-s"],
        input=s, capture_output=True, text=True,
    ))
    try:
        proc = runner(host, script)
    except OSError as exc:
        return {"ok": False, "dropped": [], "error": str(exc)}
    if getattr(proc, "returncode", 1) != 0:
        err = ((getattr(proc, "stderr", "") or "")
               + (getattr(proc, "stdout", "") or "")).strip()
        return {"ok": False, "dropped": [], "error": err[-500:]}
    return {"ok": True, "dropped": safe}


def prune_source(source: str, *, today: str | None = None,
                 force: bool = False, run=None) -> dict:
    """Drop archived days from the cluster staging tree."""
    remote_days = list_source_days(source, run=run)
    drop, warnings = remote_prune_decision(
        remote_days, today=today, force=force,
    )
    result = drop_source_days(source, drop, run=run)
    result["warnings"] = warnings
    return result
