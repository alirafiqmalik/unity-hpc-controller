"""The dashboard must never call an old snapshot live.

`snapshot.csv` having rows says only that the collector ran once. When the
collector stops, the newest row keeps its value and the numbers stay on screen.
Reporting that as "live sync" invites a scheduling decision on data that is
weeks old, so freshness is decided here, where the timestamp's zone is known.
"""

import csv
from datetime import datetime, timedelta, timezone

import pytest

from controller import snapshot

COLUMNS = [
    "timestamp_utc", "gpu_running", "gpu_pending", "gpu_preempt_running",
    "gpu_preempt_pending", "total_nodes", "free_nodes", "gpu_types_free",
]


def _write(tmp_path, monkeypatch, stamps):
    """Write a snapshot.csv whose rows carry `stamps`, and point paths at it."""
    monkeypatch.setenv("UNITY_HPC_DATA", str(tmp_path))
    target = tmp_path / "snapshot.csv"
    with target.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        for stamp in stamps:
            writer.writerow([stamp, 10, 5, 1, 1, 155, 12, "m40:12"])
    return target


def _stamp(**delta):
    """A collector-style stamp: UTC, a space, and no zone marker."""
    when = datetime.now(timezone.utc) - timedelta(**delta)
    return when.strftime("%Y-%m-%d %H:%M:%S")


def test_a_recent_snapshot_is_fresh(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, [_stamp(seconds=30)])
    live = snapshot.live_snapshot()
    assert live["available"] is True
    assert live["fresh"] is True
    assert live["age_s"] < 120


def test_a_weeks_old_snapshot_is_available_but_not_fresh(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, [_stamp(days=59)])
    live = snapshot.live_snapshot()
    assert live["available"] is True, "the rows are real and still worth showing"
    assert live["fresh"] is False, "but they are history, not the live cluster"
    assert live["age_s"] > 58 * 86400


@pytest.mark.parametrize("age_s, fresh", [
    (0, True),
    (snapshot.LIVE_MAX_AGE_S - 60, True),
    (snapshot.LIVE_MAX_AGE_S + 60, False),
])
def test_freshness_turns_over_at_the_documented_limit(tmp_path, monkeypatch, age_s, fresh):
    _write(tmp_path, monkeypatch, [_stamp(seconds=age_s)])
    assert snapshot.live_snapshot()["fresh"] is fresh


def test_a_missing_snapshot_is_neither_available_nor_fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("UNITY_HPC_DATA", str(tmp_path))
    live = snapshot.live_snapshot()
    assert live["available"] is False
    assert live["fresh"] is False
    assert live["age_s"] is None


def test_an_unreadable_timestamp_is_not_fresh(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, ["not-a-timestamp"])
    live = snapshot.live_snapshot()
    assert live["fresh"] is False
    assert live["age_s"] is None


def test_the_collector_stamp_is_read_as_utc_not_local_time():
    """
    The collector writes `2026-07-24 03:24:21` with no zone marker. Reading it
    as local time is wrong by the host's offset, which on a half-hour zone is
    enough to move a job's reported wait. Two stamps one hour apart must differ
    by exactly one hour, whatever the host zone is.
    """
    older = snapshot._age_seconds(_stamp(hours=2))
    newer = snapshot._age_seconds(_stamp(hours=1))
    assert older is not None and newer is not None
    assert abs((older - newer) - 3600) <= 2


def test_age_never_runs_negative():
    """A clock skew that puts the newest row in the future must not wrap."""
    ahead = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    assert snapshot._age_seconds(ahead) == 0
