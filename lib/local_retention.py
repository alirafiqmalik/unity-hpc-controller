"""Move old telemetry into compressed local backups under the sync lock."""

from __future__ import annotations

import fcntl
import gzip
import hashlib
import os
import re
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from lib import paths

TABLE_DATES = {
    "hourly_resource": "hour_utc",
    "daily_resource": "day_utc",
    "task_run": "day_utc",
    "events": "ts",
    "day_index": "day_utc",
}
RAW_TREES = ("telemetry", "telemetry-imported")
DAY_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _accounting_of_days(count: int) -> str:
    """Select accounting whose job has a task_run on the given days."""
    return ("job_id IN (SELECT job_id FROM task_run WHERE substr(day_utc,1,10) IN ("
            + ",".join("?" * count) + "))")


def _has_accounting(con) -> bool:
    """An archive that predates enriched accounting has no such table."""
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_accounting'"
    ).fetchone() is not None


def _copy_rows(archive, rows, table) -> int:
    insert = f"INSERT INTO {table} VALUES({','.join('?' * len(rows.description))})"
    count = 0
    while batch := rows.fetchmany(1000):
        archive.executemany(insert, batch)
        count += len(batch)
    return count


def _valid_day(value: str) -> bool:
    if not DAY_NAME.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def cutoff_day(days: int, today: date | None = None) -> str:
    if not 1 <= days <= 3650:
        raise ValueError("retention days must be between 1 and 3650")
    return ((today or datetime.now(timezone.utc).date())
            - timedelta(days=days)).isoformat()


def _archive_root() -> Path:
    return paths.archive_dir() / "telemetry-retention"


def _candidate_days(con: sqlite3.Connection, cutoff: str) -> list[str]:
    found: set[str] = set()
    for table, column in TABLE_DATES.items():
        rows = con.execute(
            f"SELECT DISTINCT substr({column},1,10) FROM {table} "
            f"WHERE substr({column},1,10) < ?", (cutoff,),
        )
        found.update(day for (day,) in rows if _valid_day(day))
    for tree in RAW_TREES:
        root = paths.data_dir() / tree
        if root.is_dir():
            found.update(
                p.name for p in root.iterdir()
                if p.is_dir() and not p.is_symlink()
                and _valid_day(p.name) and p.name < cutoff
            )
    return sorted(found)


def _fsync_dir(folder: Path) -> None:
    fd = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _store_gzip(tmp: Path, folder: Path, stem: str, suffix: str) -> Path:
    with tmp.open("rb") as fh:
        digest = hashlib.file_digest(fh, "sha256").hexdigest()[:16]
    target = folder / f"{stem}-{digest}.{suffix}"
    if target.exists():
        with target.open("rb") as fh:
            existing = hashlib.file_digest(fh, "sha256").hexdigest()[:16]
        if existing != digest:
            raise OSError(f"backup changed on disk: {target}")
        tmp.unlink()
    else:
        os.replace(tmp, target)
        _fsync_dir(folder)
    return target


def _backup_raw(day: str, tree: str, folder: Path) -> Path | None:
    source = paths.data_dir() / tree / day
    if not source.is_dir() or source.is_symlink():
        return None
    fd, name = tempfile.mkstemp(prefix=f".{tree}-", suffix=".tmp", dir=folder)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as out:
            with gzip.GzipFile(filename="", mode="wb", fileobj=out, mtime=0) as gz:
                with tarfile.open(mode="w", fileobj=gz) as tar:
                    tar.add(source, arcname=f"{tree}/{day}")
            out.flush()
            os.fsync(out.fileno())
        with tarfile.open(tmp, "r:gz") as check:
            check.getmembers()
        stem = "raw-mirror" if tree == "telemetry" else "raw-imported"
        return _store_gzip(tmp, folder, stem, "tar.gz")
    finally:
        tmp.unlink(missing_ok=True)


def _backup_summary(con: sqlite3.Connection, day: str, folder: Path, orphan_ids=()) -> Path | None:
    fd, db_name = tempfile.mkstemp(prefix=".summary-", suffix=".sqlite", dir=folder)
    os.close(fd)
    db_tmp = Path(db_name)
    try:
        archive = sqlite3.connect(db_tmp)
        count = 0
        try:
            for table, column in TABLE_DATES.items():
                schema = con.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()[0]
                archive.execute(schema)
                rows = con.execute(
                    f"SELECT * FROM {table} WHERE substr({column},1,10)=?", (day,),
                )
                count += _copy_rows(archive, rows, table)
            if _has_accounting(con):
                archive.execute(con.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='task_accounting'"
                ).fetchone()[0])
                count += _copy_rows(archive, con.execute(
                    f"SELECT * FROM task_accounting WHERE {_accounting_of_days(1)}", (day,)
                ), "task_accounting")
                for start in range(0, len(orphan_ids), 500):
                    chunk = orphan_ids[start:start + 500]
                    marks = ",".join("?" * len(chunk))
                    count += _copy_rows(archive, con.execute(
                        f"SELECT * FROM task_accounting WHERE job_id IN ({marks})", chunk
                    ), "task_accounting")
            for table in ("task_profile", "meta"):
                schema = con.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()[0]
                archive.execute(schema)
            archive.executemany("INSERT INTO meta VALUES(?,?)", con.execute(
                "SELECT key, value FROM meta"
            ))
            archive.execute(
                "INSERT OR REPLACE INTO meta VALUES('archive_day',?)", (day,)
            )
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cluster-intel"))
            import rollup
            rollup._rebuild_task_profile(archive)
            archive.commit()
            if archive.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("summary backup failed integrity check")
        finally:
            archive.close()
        if not count:
            return None
        fd, gz_name = tempfile.mkstemp(prefix=".summary-", suffix=".tmp", dir=folder)
        tmp = Path(gz_name)
        try:
            with os.fdopen(fd, "wb") as out, db_tmp.open("rb") as src:
                with gzip.GzipFile(filename="", mode="wb", fileobj=out, mtime=0) as gz:
                    shutil.copyfileobj(src, gz)
                out.flush()
                os.fsync(out.fileno())
            with gzip.open(tmp, "rb") as check:
                while check.read(1024 * 1024):
                    pass
            return _store_gzip(tmp, folder, "summary", "sqlite.gz")
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        db_tmp.unlink(missing_ok=True)


def _summary_backups() -> list[tuple[str, Path]]:
    root = _archive_root()
    if not root.exists():
        return []
    return [(folder.name, path) for folder in sorted(root.iterdir())
            if folder.is_dir() and not folder.is_symlink() and _valid_day(folder.name)
            for path in sorted(folder.glob("summary-*.sqlite.gz"))]


def _attribute_orphans(con) -> dict[str, list[str]]:
    if not _has_accounting(con):
        return {}
    orphans = {job for (job,) in con.execute(
        "SELECT job_id FROM task_accounting WHERE job_id NOT IN (SELECT job_id FROM task_run)"
    )}
    backups = _summary_backups() if orphans else []
    if not backups:
        return {}
    owner = {}
    with tempfile.TemporaryDirectory(prefix=".orphans-", dir=_archive_root()) as tmp:
        db = Path(tmp) / "backup.sqlite"
        for day, path in backups:
            try:
                with gzip.open(path, "rb") as src, db.open("wb") as out:
                    shutil.copyfileobj(src, out)
                backup = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
                try:
                    ids = {job for (job,) in backup.execute("SELECT job_id FROM task_run")}
                finally:
                    backup.close()
                for job in ids & orphans:
                    owner[job] = day
            except (OSError, EOFError, sqlite3.DatabaseError):
                continue
            finally:
                db.unlink(missing_ok=True)
    grouped = {}
    for job, day in owner.items():
        grouped.setdefault(day, []).append(job)
    return {day: sorted(jobs) for day, jobs in grouped.items()}


def _prune_db(days: list[str], orphan_ids=()) -> None:
    db = paths.summaries_db()
    tmp = db.with_suffix(".retention.tmp")
    tmp.unlink(missing_ok=True)
    shutil.copy2(db, tmp)
    try:
        con = sqlite3.connect(tmp)
        try:
            accounting = _has_accounting(con)
            for batch_start in range(0, len(days), 500):
                batch = days[batch_start:batch_start + 500]
                marks = ",".join("?" * len(batch))
                if accounting:
                    # Before task_run: the selection needs that day's task rows.
                    con.execute(f"DELETE FROM task_accounting WHERE {_accounting_of_days(len(batch))}", batch)
                for table, column in TABLE_DATES.items():
                    con.execute(
                        f"DELETE FROM {table} WHERE substr({column},1,10) IN ({marks})",
                        batch,
                    )
            for start in range(0, len(orphan_ids) if accounting else 0, 500):
                chunk = orphan_ids[start:start + 500]
                marks = ",".join("?" * len(chunk))
                con.execute(f"DELETE FROM task_accounting WHERE job_id IN ({marks}) AND job_id NOT IN (SELECT job_id FROM task_run)", chunk)
            con.execute("DELETE FROM task_profile")
            # task_profile is derived from task_run. Rebuild it after the cut.
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cluster-intel"))
            import rollup
            rollup._rebuild_task_profile(con)
            con.commit()
            con.execute("VACUUM")
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("retained database failed integrity check")
        finally:
            con.close()
        with tmp.open("rb") as fh:
            os.fsync(fh.fileno())
        os.replace(tmp, db)
        _fsync_dir(db.parent)
    finally:
        tmp.unlink(missing_ok=True)


def run(days: int = 90, *, today: date | None = None, dry_run: bool = False,
        no_lock: bool = False) -> dict:
    """Back up and remove complete calendar days older than the live window."""
    cutoff = cutoff_day(days, today)
    if no_lock:
        return _run_locked(cutoff, dry_run)
    paths.locks_dir().mkdir(parents=True, exist_ok=True)
    with paths.sync_lock().open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _run_locked(cutoff, dry_run)


def _run_locked(cutoff: str, dry_run: bool) -> dict:
    db = paths.summaries_db()
    if not db.is_file():
        raise FileNotFoundError("summaries.db is required for local retention")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        days = _candidate_days(con, cutoff)
        if dry_run or not days:
            return {"cutoff": cutoff, "days": days, "archived": False}
        orphans_by_day = _attribute_orphans(con)
        for day in days:
            folder = _archive_root() / day
            folder.mkdir(parents=True, exist_ok=True)
            for tree in RAW_TREES:
                _backup_raw(day, tree, folder)
            _backup_summary(con, day, folder, orphans_by_day.get(day, ()))
        for day in sorted(set(orphans_by_day) - set(days)):
            _backup_summary(con, day, _archive_root() / day, orphans_by_day[day])
    finally:
        con.close()
    _prune_db(days, sorted(j for ids in orphans_by_day.values() for j in ids))
    for day in days:
        for tree in RAW_TREES:
            source = paths.data_dir() / tree / day
            if source.is_dir() and not source.is_symlink():
                shutil.rmtree(source)
    return {"cutoff": cutoff, "days": days, "archived": True}
