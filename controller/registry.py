"""Attached-project registry. Flock + atomic replace (I4). Stdlib only.

A project that is not in this file is a project the controller cannot name.
The ledger stays in the project directory; this file only stores the path.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from lib import paths
from lib.scaffold import TYPES

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

_FIELDS = (
    "slug", "path", "primitive", "remote_dir", "unity_host",
    "campaign", "attached_utc", "overrides",
)


class RegistryError(ValueError):
    """Caller-facing registry failure (bad slug, missing path, …)."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _empty() -> dict:
    return {"projects": []}


def _read_unlocked(path: Path) -> dict:
    if not path.exists():
        return _empty()
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return _empty()
    if not isinstance(data, dict) or not isinstance(data.get("projects"), list):
        return _empty()
    return data


def _write_unlocked(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, indent=2, sort_keys=True) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=".projects.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _with_lock(write: bool, fn):
    lock_path = paths.projects_lock()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.touch(exist_ok=True)
    flags = os.O_RDWR if write else os.O_RDONLY
    fd = os.open(lock_path, flags)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX if write else fcntl.LOCK_SH)
        return fn()
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _validate_slug(slug: str) -> str:
    s = (slug or "").strip().lower()
    if not SLUG_RE.match(s):
        raise RegistryError(
            f"invalid slug {slug!r}: use [a-z0-9][a-z0-9_-]{{0,63}}"
        )
    return s


def _normalise(record: dict) -> dict:
    out = {k: record.get(k, "" if k != "overrides" else {}) for k in _FIELDS}
    if not isinstance(out["overrides"], dict):
        out["overrides"] = {}
    return out


def list_projects() -> list[dict]:
    def _read():
        data = _read_unlocked(paths.projects_registry())
        return [_normalise(p) for p in data["projects"] if isinstance(p, dict)]
    return _with_lock(False, _read)


def get(slug: str) -> dict | None:
    slug = (slug or "").strip().lower()
    for project in list_projects():
        if project["slug"] == slug:
            return project
    return None


def attach(
    slug: str,
    path: str | Path,
    primitive: str = "cpu",
    remote_dir: str = "",
    unity_host: str = "unity",
    campaign: str = "",
    overrides: dict | None = None,
) -> dict:
    """Register or update an attached project. Returns the stored record."""
    slug = _validate_slug(slug)
    project_dir = Path(path).expanduser().resolve()
    if not project_dir.is_dir():
        raise RegistryError(f"not a directory: {project_dir}")
    if primitive not in TYPES:
        raise RegistryError(
            f"unknown primitive {primitive!r}; expected one of {', '.join(TYPES)}"
        )
    record = {
        "slug": slug,
        "path": str(project_dir),
        "primitive": primitive,
        "remote_dir": remote_dir or "",
        "unity_host": unity_host or "unity",
        "campaign": campaign or "",
        "attached_utc": _now(),
        "overrides": dict(overrides or {}),
    }

    def _write():
        store = paths.projects_registry()
        data = _read_unlocked(store)
        projects = [p for p in data["projects"] if p.get("slug") != slug]
        existing = next((p for p in data["projects"] if p.get("slug") == slug), None)
        if existing and existing.get("attached_utc"):
            record["attached_utc"] = existing["attached_utc"]
        projects.append(record)
        projects.sort(key=lambda p: p.get("slug", ""))
        _write_unlocked(store, {"projects": projects})
        return record

    return _with_lock(True, _write)


def update(slug: str, **fields) -> dict:
    """Patch an attached project. Unknown slugs raise RegistryError."""
    current = get(slug)
    if current is None:
        raise RegistryError(f"unknown project {slug!r}")
    allowed = {
        "path", "primitive", "remote_dir", "unity_host", "campaign", "overrides",
    }
    unknown = sorted(k for k in fields if k not in allowed)
    if unknown:
        raise RegistryError(f"unknown fields: {', '.join(unknown)}")
    merged = dict(current)
    merged.update({k: v for k, v in fields.items() if v is not None})
    return attach(
        merged["slug"],
        merged["path"],
        primitive=merged["primitive"],
        remote_dir=merged["remote_dir"],
        unity_host=merged["unity_host"],
        campaign=merged["campaign"],
        overrides=merged.get("overrides") or {},
    )


def detach(slug: str) -> bool:
    """Remove an attached project. Returns True if it was present."""
    slug = (slug or "").strip().lower()

    def _write():
        store = paths.projects_registry()
        data = _read_unlocked(store)
        kept = [p for p in data["projects"] if p.get("slug") != slug]
        if len(kept) == len(data["projects"]):
            return False
        _write_unlocked(store, {"projects": kept})
        return True

    return _with_lock(True, _write)
