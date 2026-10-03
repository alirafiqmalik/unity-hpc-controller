#!/usr/bin/env python3
"""One-shot, cluster-wide GPU allocation history from a single sacct query.

The output records GPU reservations, not GPU compute utilisation or historical
queue depth. It lives beside summaries.db so a later telemetry rollup cannot
overwrite the backfill. Re-running replaces the entire bounded window.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import paths  # noqa: E402
from lib.cluster_config import canonical_gpu_type  # noqa: E402

UTC = timezone.utc
HOUR = timedelta(hours=1)
TYPED_GPU = re.compile(r"(?:^|,)gres/gpu:([^=,]+)=(\d+)(?:,|$)")
ANY_GPU = re.compile(r"(?:^|,)gres/gpu=(\d+)(?:,|$)")


def stamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def slurm_stamp(value: datetime) -> str:
    # Unity's login node uses UTC, and Slurm rejects the ISO trailing Z.
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")


def parse_time(value: str) -> datetime | None:
    if not value or value in {"Unknown", "None"}:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)


def gpu_counts(tres: str) -> dict[str, int]:
    typed: dict[str, int] = defaultdict(int)
    for kind, count in TYPED_GPU.findall(tres):
        typed[canonical_gpu_type(kind)] += int(count)
    match = ANY_GPU.search(tres)
    total = int(match.group(1)) if match else 0
    missing = max(0, total - sum(typed.values()))
    if missing:
        typed["unspecified"] += missing
    return dict(typed)


def collect(lines, start: datetime, end: datetime) -> tuple[dict, int, int]:
    """Allocate each job's GPU-seconds to the hours it overlaps."""
    by_hour: dict[tuple[str, str], float] = defaultdict(float)
    rows_seen = gpu_jobs = 0
    for line in lines:
        fields = line.rstrip("\n").split("|", 3)
        if len(fields) != 4:
            continue
        rows_seen += 1
        job_start, job_end = parse_time(fields[1]), parse_time(fields[2])
        counts = gpu_counts(fields[3])
        if not job_start or not counts:
            continue
        # A running allocation can have End=Unknown. The query's end is the
        # observation time, never an assumed future release time.
        job_end = job_end or end
        left, right = max(job_start, start), min(job_end, end)
        if right <= left:
            continue
        gpu_jobs += 1
        hour = left.replace(minute=0, second=0, microsecond=0)
        while hour < right:
            seconds = (min(right, hour + HOUR) - max(left, hour)).total_seconds()
            key = stamp(hour)
            for kind, count in counts.items():
                by_hour[(key, kind)] += count * seconds
            hour += HOUR
    return by_hour, rows_seen, gpu_jobs


def write_db(target: Path, start: datetime, end: datetime, seconds: dict,
             rows_seen: int, gpu_jobs: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".db.tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    try:
        con.executescript("""
            CREATE TABLE hour_gpu(
                hour_utc TEXT NOT NULL, gpu_type TEXT NOT NULL,
                allocated_avg REAL NOT NULL,
                PRIMARY KEY(hour_utc, gpu_type));
            CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        hour = start.replace(minute=0, second=0, microsecond=0)
        while hour < end:
            left, right = max(hour, start), min(hour + HOUR, end)
            covered = (right - left).total_seconds()
            key = stamp(hour)
            total = 0.0
            for (slot, kind), gpu_seconds in seconds.items():
                if slot != key:
                    continue
                average = gpu_seconds / covered
                total += average
                con.execute("INSERT INTO hour_gpu VALUES(?,?,?)", (key, kind, average))
            con.execute("INSERT INTO hour_gpu VALUES(?,?,?)", (key, "__all__", total))
            hour += HOUR
        con.executemany("INSERT INTO meta VALUES(?,?)", [
            ("start_utc", stamp(start)), ("end_utc", stamp(end)),
            ("collected_utc", stamp(datetime.now(UTC))),
            ("source", "sacct -a -X --array --truncate"),
            ("rows_seen", str(rows_seen)), ("gpu_jobs", str(gpu_jobs)),
        ])
        con.commit()
    finally:
        con.close()
    with tmp.open("rb") as fh:
        os.fsync(fh.fileno())
    os.replace(tmp, target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30, choices=[1, 7, 30])
    parser.add_argument("--host", default="unity")
    parser.add_argument("--input", type=Path, help="parse a saved sacct response instead of SSH")
    parser.add_argument("--start", help="UTC start; for saved input or a fixed window")
    parser.add_argument("--end", help="UTC end; for saved input or a fixed window")
    args = parser.parse_args()
    end = parse_time(args.end) if args.end else datetime.now(UTC)
    start = parse_time(args.start) if args.start else end - timedelta(days=args.days)
    if not start or not end or start >= end or end - start > timedelta(days=31):
        parser.error("window must be valid UTC times covering at most 31 days")
    if not re.fullmatch(r"[A-Za-z0-9_.@-]+", args.host) or args.host.startswith("-"):
        parser.error("invalid SSH host")

    lock_path = paths.locks_dir() / "usage-backfill.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("another usage backfill is running")
        if args.input:
            with args.input.open(encoding="utf-8") as source:
                seconds, rows_seen, gpu_jobs = collect(source, start, end)
        else:
            remote = shlex.join([
                "timeout", "300", "nice", "-n", "19", "sacct", "-a", "-X",
                "--array", "--truncate", "-P", "-n", "-S", slurm_stamp(start),
                "-E", slurm_stamp(end), "-o", "JobID,Start,End,AllocTRES",
            ])
            with subprocess.Popen(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                 args.host, remote], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True,
            ) as proc:
                assert proc.stdout is not None
                seconds, rows_seen, gpu_jobs = collect(proc.stdout, start, end)
                try:
                    _, err = proc.communicate(timeout=330)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate()
                    raise RuntimeError("sacct timed out; history was not replaced")
                if proc.returncode:
                    raise RuntimeError(f"sacct failed ({proc.returncode}): {err[-1000:]}")
        target = paths.historical_usage_db()
        write_db(target, start, end, seconds, rows_seen, gpu_jobs)
    print(json.dumps({"path": str(target), "start_utc": stamp(start),
                      "end_utc": stamp(end), "rows_seen": rows_seen,
                      "gpu_jobs": gpu_jobs}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as exc:
        print(f"backfill_usage: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
