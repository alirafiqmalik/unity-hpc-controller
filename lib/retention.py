"""Retention gate: decide whether an rsync --delete is safe (I8).

The mirror shrinks only when the cluster's own 35-day prune propagates via
rsync --delete. We withhold --delete for the WHOLE run unless every day it would
remove is fully summarised, or summaries.db is absent (fail-safe: withhold).
Stdlib only.
"""

from __future__ import annotations

import re
from typing import Iterable

from lib import paths, queries

_DAY = re.compile(r"^(?:telemetry/)?(\d{4}-\d{2}-\d{2})(?:/|$)")


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
