"""Verify a transferred external runtime against its frozen file manifest.

The verifier runs inside an allocation. SSH and runtime installation policy
remain outside this module; files, relative symlinks, and digests are its seam.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath


def file_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            value.update(block)
    return value.hexdigest()


def _check_entry(root: Path, row: dict) -> str | None:
    path = root / row["path"]
    try:
        if "symlink" in row:
            target = row["symlink"]
            if not path.is_symlink() or os.readlink(path) != target:
                return "symlink target mismatch"
            if os.path.isabs(target) or not path.resolve().is_relative_to(root):
                return "symlink escapes runtime root"
        elif not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
            return "file missing or unsafe"
        elif path.stat().st_size != row["size_bytes"]:
            return "file size mismatch"
        elif file_digest(path) != row["sha256"]:
            return "file digest mismatch"
    except OSError as error:
        return f"file unavailable: {error.strerror or type(error).__name__}"
    return None


def verify_tree(root: Path, manifest: Path, expected_digest: str, *, workers: int = 1) -> dict:
    """Verify every entry with at most eight reads and a bounded submission queue.

    Parallel reads are opt-in. The caller must calibrate them inside its CPU
    allocation; this helper never creates or changes scheduler resources.
    """
    if type(workers) is not int or not 1 <= workers <= 8:
        raise ValueError("runtime verification workers must be an integer from 1 to 8")
    root = root.resolve()
    actual = file_digest(manifest)
    if actual != expected_digest:
        raise ValueError("runtime file manifest digest differs from the frozen lock")
    started, checked, total_bytes, mismatch_count = time.monotonic(), 0, 0, 0
    failures, seen = [], set()
    def entries():
        with manifest.open() as stream:
            for line in stream:
                row = json.loads(line)
                relative = PurePosixPath(row["path"])
                if relative.is_absolute() or ".." in relative.parts or not relative.parts or str(relative) in seen:
                    raise ValueError("runtime manifest contains an unsafe or duplicate path")
                seen.add(str(relative))
                yield row

    def retain(row, problem):
        nonlocal checked, total_bytes, mismatch_count
        if problem:
            mismatch_count += 1
            if problem and len(failures) < 20:
                failures.append({"path": row["path"], "error": problem})
        checked += 1
        total_bytes += row.get("size_bytes", 0)

    if workers == 1:
        for row in entries():
            retain(row, _check_entry(root, row))
    else:
        # Executor.map queues the entire iterator on older supported Python
        # versions. Keep only two rows per worker and consume in manifest order.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pending = deque()
            for row in entries():
                pending.append((row, pool.submit(_check_entry, root, row)))
                if len(pending) >= workers * 2:
                    entry, future = pending.popleft()
                    retain(entry, future.result())
            while pending:
                entry, future = pending.popleft()
                retain(entry, future.result())
    return {"schema_version": 1, "verified": not mismatch_count, "files_checked": checked,
            "total_bytes": total_bytes, "files_manifest_sha256": actual,
            "mismatches": failures, "mismatch_count": mismatch_count, "workers": workers,
            "elapsed_seconds": round(time.monotonic() - started, 3)}
