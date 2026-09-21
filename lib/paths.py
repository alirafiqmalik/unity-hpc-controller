"""Resolution of the machine-wide unity-hpc data store. Stdlib only.

Data lives in $UNITY_HPC_DATA (default $XDG_DATA_HOME/unity-hpc or
~/.local/share/unity-hpc), OUTSIDE the versioned plugin so it survives updates.
Every path is resolved at call time so tests can repoint via the environment.
"""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    d = os.environ.get("UNITY_HPC_DATA")
    if d:
        return Path(d).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "unity-hpc"


def telemetry_dir() -> Path:
    return data_dir() / "telemetry"


def telemetry_imported_dir() -> Path:
    return data_dir() / "telemetry-imported"


def summaries_db() -> Path:
    return data_dir() / "summaries.db"


def config_path() -> Path:
    return data_dir() / "cluster-config.json"


def locks_dir() -> Path:
    return data_dir() / "locks"


def config_lock() -> Path:
    return locks_dir() / "config.lock"


def sync_lock() -> Path:
    return locks_dir() / "sync.lock"


def archive_dir() -> Path:
    return data_dir() / "archive"


def controller_dir() -> Path:
    return data_dir() / "controller"


def projects_registry() -> Path:
    return controller_dir() / "projects.json"


def projects_lock() -> Path:
    return controller_dir() / "projects.json.lock"


def events_log() -> Path:
    return controller_dir() / "events.jsonl"


def snapshot_csv() -> Path:
    return data_dir() / "snapshot.csv"
