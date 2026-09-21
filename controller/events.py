"""Append-only controller activity log. Never raises to a caller (I6)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from lib import paths

_KEEP = 200


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record(kind: str, message: str, **extra) -> None:
    path = paths.events_log()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": _now(), "kind": kind, "message": message, **extra}
        with path.open("a") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError:
        return


def recent(limit: int = 50) -> list[dict]:
    path = paths.events_log()
    if not path.exists():
        return []
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in lines[-max(limit, _KEEP):]:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out[-limit:]
