"""A saved sacct response fills the same API window the dashboard reads."""

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from controller import snapshot

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "cluster-intel" / "backfill_usage.py"


def _stamp(value):
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_sacct_backfill_populates_hourly_allocation_and_heatmap(tmp_data_dir):
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=2)
    source = tmp_data_dir / "sacct.txt"
    source.write_text(
        f"100|{_stamp(start)}|{_stamp(end - timedelta(minutes=30))}|"
        "billing=1,gres/gpu=2,gres/gpu:a100=2\n"
        f"101|{_stamp(start + timedelta(hours=1))}|{_stamp(end)}|"
        "billing=1,gres/gpu=1\n"
        "102|Unknown|Unknown|gres/gpu=1\n"
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--input", str(source),
         "--start", _stamp(start), "--end", _stamp(end)],
        text=True, capture_output=True, check=True,
    )
    assert json.loads(result.stdout)["gpu_jobs"] == 2
    con = sqlite3.connect(tmp_data_dir / "historical_usage.db")
    try:
        totals = con.execute(
            "SELECT allocated_avg FROM hour_gpu WHERE gpu_type='__all__' "
            "ORDER BY hour_utc"
        ).fetchall()
    finally:
        con.close()
    assert [round(row[0], 1) for row in totals] == [2.0, 2.0]
    usage = snapshot.usage(24)
    assert usage["source"] == "sacct"
    assert usage["unit"] == "gpus"
    assert usage["gpu_hours"] == 4.0
    assert usage["avg_allocated"] == 2.0
    assert usage["peak_allocated"] == 2.0
    assert usage["window_end_utc"] == _stamp(end)
    assert usage["series"]["a100"] == [2.0, 1.0]
    assert usage["series"]["unspecified"] == [0.0, 1.0]
    assert [cell["value"] for cell in usage["heatmap"]] == [2.0, 2.0]


def test_old_backfill_does_not_replace_the_window_ending_now(tmp_data_dir):
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(days=5)
    start = end - timedelta(hours=24)
    source = tmp_data_dir / "sacct.txt"
    source.write_text(f"1|{_stamp(start)}|{_stamp(end)}|gres/gpu=1\n")
    subprocess.run(
        [sys.executable, str(SCRIPT), "--input", str(source),
         "--start", _stamp(start), "--end", _stamp(end)],
        capture_output=True, check=True,
    )
    usage = snapshot.usage(24)
    assert usage["available"] is False
    assert usage["window"] == "recent"
    assert usage["slots"] == []
    assert usage["source"] == "samples"


def test_type_average_weights_partial_hours_by_their_duration(tmp_data_dir):
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0, minute=45)
    if end > datetime.now(timezone.utc):
        end -= timedelta(hours=1)
    start = end - timedelta(hours=1)
    boundary = start + timedelta(minutes=15)
    source = tmp_data_dir / "sacct.txt"
    source.write_text(
        f"1|{_stamp(start)}|{_stamp(boundary)}|gres/gpu:a40=8\n"
        f"2|{_stamp(boundary)}|{_stamp(end)}|gres/gpu:a40=9\n"
    )
    subprocess.run(
        [sys.executable, str(SCRIPT), "--input", str(source),
         "--start", _stamp(start), "--end", _stamp(end)],
        capture_output=True, check=True,
    )
    usage = snapshot.usage(1)
    assert usage["covered_hours"] == 1
    assert usage["by_type"][0]["gpu_type"] == "a40"
    assert usage["by_type"][0]["avg"] == 8.8
    assert usage["gpu_hours"] == 8.8


def test_failed_backfill_does_not_replace_existing_history(tmp_data_dir):
    source = tmp_data_dir / "sacct.txt"
    source.write_text("1|2026-09-01T00:00:00|2026-09-01T01:00:00|gres/gpu=1\n")
    subprocess.run([sys.executable, str(SCRIPT), "--input", str(source),
                    "--start", "2026-09-01T00:00:00Z",
                    "--end", "2026-09-01T01:00:00Z"], check=True,
                   capture_output=True)
    db = tmp_data_dir / "historical_usage.db"
    before = db.read_bytes()
    result = subprocess.run([sys.executable, str(SCRIPT), "--host", "-bad",
                             "--input", str(source)], capture_output=True)
    assert result.returncode != 0
    assert db.read_bytes() == before


def test_zero_allocations_are_observed_hours_not_missing_hours(tmp_data_dir):
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=3)
    source = tmp_data_dir / "cpu-only.txt"
    source.write_text(
        f"1|{_stamp(start)}|{_stamp(end)}|billing=2,cpu=2,mem=8G\n"
    )
    subprocess.run(
        [sys.executable, str(SCRIPT), "--input", str(source),
         "--start", _stamp(start), "--end", _stamp(end)],
        capture_output=True, check=True,
    )
    usage = snapshot.usage(24)
    assert usage["source"] == "sacct"
    assert usage["heatmap"]
    assert all(cell["value"] == 0 and cell["samples"] == 1
               for cell in usage["heatmap"])
    assert usage["avg_allocated"] == 0
