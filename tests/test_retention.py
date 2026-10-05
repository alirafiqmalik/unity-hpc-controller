import gzip
import sqlite3
import subprocess
import sys
import tarfile
from datetime import date
from pathlib import Path

import pytest

from lib import local_retention, paths, retention

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI = REPO_ROOT / "scripts" / "hpc-retention-gate"

ITEMIZE = """\
.d..t...... ./
*deleting   2026-05-01/task_runs.jsonl
*deleting   2026-05-01/resource_state.jsonl
*deleting   2026-05-01/
*deleting   2026-05-02/resource_state.jsonl
*deleting   2026-05-02/
>f+++++++++ 2026-07-22/resource_state.jsonl
"""


def _seed_day(day, fully):
    con = sqlite3.connect(paths.summaries_db())
    con.execute("CREATE TABLE IF NOT EXISTS day_index("
                "day_utc TEXT PRIMARY KEY, slots_ingested INTEGER, rows_emitted INTEGER, "
                "events_promoted INTEGER, task_runs_promoted INTEGER, "
                "fully_summarised INTEGER, first_seen_utc TEXT, last_rollup_utc TEXT)")
    con.execute("INSERT OR REPLACE INTO day_index VALUES(?,?,?,?,?,?,?,?)",
                (day, 96, 96, 1, 1, fully, "x", "x"))
    con.commit()
    con.close()


def test_parse_deletions_extracts_day_dirs():
    assert retention.parse_deletions(ITEMIZE.splitlines()) == {"2026-05-01", "2026-05-02"}


def test_parse_deletions_matches_telemetry_prefixed_paths():
    lines = ["*deleting   telemetry/2026-06-01/resource_state.jsonl"]
    assert retention.parse_deletions(lines) == {"2026-06-01"}


def test_parse_deletions_ignores_non_telemetry_deletions():
    lines = [
        "*deleting   telemetry-imported/2026-05-01/x.jsonl",
        "*deleting   summaries.db",
        "*deleting   cluster-config.json",
    ]
    assert retention.parse_deletions(lines) == set()


def test_no_deletions_always_allows(tmp_data_dir):
    assert retention.retention_decision(set()) == (True, [])


def test_absent_summaries_withholds_failsafe(tmp_data_dir):
    allow, warns = retention.retention_decision({"2026-05-01"})
    assert allow is False
    assert any("summaries.db" in w for w in warns)


def test_incomplete_day_withholds_and_names_it(tmp_data_dir):
    _seed_day("2026-05-01", 1)
    _seed_day("2026-05-02", 0)
    allow, warns = retention.retention_decision({"2026-05-01", "2026-05-02"})
    assert allow is False
    assert any("2026-05-02" in w for w in warns)


def test_all_fully_summarised_allows(tmp_data_dir):
    _seed_day("2026-05-01", 1)
    _seed_day("2026-05-02", 1)
    assert retention.retention_decision({"2026-05-01", "2026-05-02"}) == (True, [])


def test_force_overrides(tmp_data_dir):
    allow, warns = retention.retention_decision({"2026-05-01"}, force=True)
    assert allow is True


def _run_cli(env_extra=None):
    import os
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run([sys.executable, str(CLI)], input=ITEMIZE,
                          capture_output=True, text=True, env=env)


def test_cli_withholds_when_incomplete(tmp_data_dir):
    _seed_day("2026-05-01", 0)
    _seed_day("2026-05-02", 0)
    assert _run_cli().returncode == 10


def test_cli_force_prune_env_overrides(tmp_data_dir):
    _seed_day("2026-05-01", 0)
    assert _run_cli({"UNITY_HPC_FORCE_PRUNE": "1"}).returncode == 0


def test_split_source_separates_a_remote_host_from_a_local_path():
    assert retention.split_source("unity:/work/a/telemetry/") == (
        "unity", "/work/a/telemetry",
    )
    assert retention.split_source("/tmp/cluster") == (None, "/tmp/cluster")


def test_remote_prune_uses_the_pull_ssh_transport(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="2026-05-01\n", stderr="")

    monkeypatch.setenv("RSYNC_RSH", "ssh -i '/tmp/key with space' -o BatchMode=yes")
    monkeypatch.setattr(retention.subprocess, "run", fake_run)
    assert retention.list_source_days("unity-alias:/work/a/telemetry/") == {"2026-05-01"}
    assert retention.drop_source_days("unity-alias:/work/a/telemetry/", ["2026-05-01"])["ok"]
    assert all(call[:5] == ["ssh", "-i", "/tmp/key with space", "-o", "BatchMode=yes"]
               for call in calls)
    assert all(call[5:7] == ["unity-alias", "bash"] for call in calls)


def test_remote_prune_keeps_today_and_unarchived_days(tmp_data_dir):
    _seed_day("2026-05-01", 1)
    (paths.telemetry_dir() / "2026-05-01").mkdir(parents=True)
    (paths.telemetry_dir() / "2026-05-01" / "resource_state.jsonl").write_text("{}\n")
    drop, warns = retention.remote_prune_decision(
        {"2026-05-01", "2026-05-02", "2026-09-21"},
        today="2026-09-21",
    )
    assert drop == ["2026-05-01"]
    assert any("2026-05-02" in w and "not archived" in w for w in warns)
    assert any("2026-09-21" in w and "live" in w for w in warns)


def test_remote_prune_withholds_an_incomplete_day(tmp_data_dir):
    _seed_day("2026-05-01", 0)
    (paths.telemetry_dir() / "2026-05-01").mkdir(parents=True)
    (paths.telemetry_dir() / "2026-05-01" / "resource_state.jsonl").write_text("{}\n")
    drop, warns = retention.remote_prune_decision({"2026-05-01"}, today="2026-09-21")
    assert drop == []
    assert any("not fully summarised" in w for w in warns)
    drop, _ = retention.remote_prune_decision(
        {"2026-05-01"}, today="2026-09-21", force=True,
    )
    assert drop == ["2026-05-01"]


def test_drop_source_days_removes_only_the_named_local_day(tmp_path):
    src = tmp_path / "cluster"
    keep = src / "2026-07-20"
    gone = src / "2026-05-01"
    keep.mkdir(parents=True)
    gone.mkdir(parents=True)
    (keep / "keep.txt").write_text("keep")
    (gone / "old.txt").write_text("old")
    result = retention.drop_source_days(str(src), ["2026-05-01", "not-a-day"])
    assert result["ok"] is True
    assert result["dropped"] == ["2026-05-01"]
    assert not gone.exists()
    assert keep.exists()


def test_remote_prune_cli_drops_an_archived_day(tmp_data_dir, tmp_path):
    src = tmp_path / "cluster"
    (src / "2026-05-01").mkdir(parents=True)
    (src / "2026-05-01" / "resource_state.jsonl").write_text("{}\n")
    (paths.telemetry_dir() / "2026-05-01").mkdir(parents=True)
    (paths.telemetry_dir() / "2026-05-01" / "resource_state.jsonl").write_text("{}\n")
    _seed_day("2026-05-01", 1)
    cli = REPO_ROOT / "scripts" / "hpc-remote-prune"
    result = subprocess.run(
        [sys.executable, str(cli), str(src)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not (src / "2026-05-01").exists()
    assert (paths.telemetry_dir() / "2026-05-01").exists()


@pytest.fixture
def retention_sample(tmp_data_dir):
    """One expired day and one live day in both raw trees and the summary DB."""
    sys.path.insert(0, str(REPO_ROOT / "cluster-intel"))
    import rollup

    old = "2026-05-01"
    recent = "2026-09-01"
    for tree in (paths.telemetry_dir(), paths.telemetry_imported_dir()):
        for day in (old, recent):
            folder = tree / day
            folder.mkdir(parents=True)
            (folder / "resource_state.jsonl").write_text(f"{day}\n")
    con = sqlite3.connect(paths.summaries_db())
    con.executescript(rollup.SCHEMA)
    for day in (old, recent):
        con.execute("INSERT INTO daily_resource VALUES(?,?,?,?,?,?,?,?)",
                    ("gpu_type", "a100", day, 1, 1, 0, 0, 1))
        con.execute("INSERT INTO task_run (job_id, day_utc, state) VALUES(?,?,?)",
                    (day, day, "COMPLETED"))
        con.execute("INSERT INTO day_index (day_utc, fully_summarised) VALUES(?,1)",
                    (day,))
    con.commit()
    con.close()
    return old, recent


def test_local_retention_preview_lists_only_expired_day(retention_sample):
    old, recent = retention_sample
    preview = local_retention.run(90, today=date(2026, 9, 25), dry_run=True)
    assert preview["days"] == [old]
    assert preview["archived"] is False
    assert (paths.telemetry_dir() / old).exists()
    assert (paths.telemetry_dir() / recent).exists()


def test_local_retention_raw_backups_preserve_bytes_before_removal(retention_sample):
    old, recent = retention_sample
    result = local_retention.run(90, today=date(2026, 9, 25))
    assert result["days"] == [old]
    folder = paths.archive_dir() / "telemetry-retention" / old
    for tree in ("telemetry", "telemetry-imported"):
        stem = "raw-mirror" if tree == "telemetry" else "raw-imported"
        archive = next(folder.glob(f"{stem}-*.tar.gz"))
        with tarfile.open(archive, "r:gz") as tar:
            name = f"{tree}/{old}/resource_state.jsonl"
            assert name in tar.getnames()
            assert tar.extractfile(name).read() == f"{old}\n".encode()
        assert not (paths.data_dir() / tree / old).exists()
        assert (paths.data_dir() / tree / recent).exists()


def test_local_retention_summary_backup_contains_only_expired_day(
    retention_sample, tmp_path,
):
    old, _ = retention_sample
    local_retention.run(90, today=date(2026, 9, 25))
    folder = paths.archive_dir() / "telemetry-retention" / old
    summary = next(folder.glob("summary-*.sqlite.gz"))
    saved_db = tmp_path / "saved.sqlite"
    with gzip.open(summary, "rb") as src, saved_db.open("wb") as dest:
        dest.write(src.read())
    archived = sqlite3.connect(saved_db)
    assert archived.execute("SELECT day_utc FROM task_run").fetchall() == [(old,)]
    assert archived.execute("SELECT day_utc FROM daily_resource").fetchall() == [(old,)]
    assert archived.execute("SELECT value FROM meta WHERE key='archive_day'").fetchone() == (old,)
    assert archived.execute("SELECT n FROM task_profile").fetchall() == [(1,)]
    archived.close()


def test_local_retention_keeps_recent_rows_and_second_run_is_empty(retention_sample):
    _, recent = retention_sample
    local_retention.run(90, today=date(2026, 9, 25))
    live = sqlite3.connect(paths.summaries_db())
    assert live.execute("SELECT day_utc FROM task_run").fetchall() == [(recent,)]
    assert live.execute("SELECT day_utc FROM daily_resource").fetchall() == [(recent,)]
    assert live.execute("SELECT n FROM task_profile").fetchall() == [(1,)]
    live.close()
    assert local_retention.run(90, today=date(2026, 9, 25))["days"] == []


def test_local_retention_keeps_live_data_when_a_backup_fails(
    tmp_data_dir, monkeypatch,
):
    sys.path.insert(0, str(REPO_ROOT / "cluster-intel"))
    import rollup

    day = "2026-05-01"
    raw = paths.telemetry_dir() / day
    raw.mkdir(parents=True)
    (raw / "resource_state.jsonl").write_text("old data\n")
    con = sqlite3.connect(paths.summaries_db())
    con.executescript(rollup.SCHEMA)
    con.execute("INSERT INTO day_index (day_utc) VALUES(?)", (day,))
    con.commit()
    con.close()

    def fail(*_args):
        raise OSError("disk is full")

    monkeypatch.setattr(local_retention, "_backup_summary", fail)
    with pytest.raises(OSError, match="disk is full"):
        local_retention.run(90, today=date(2026, 9, 25))
    assert raw.is_dir()
    con = sqlite3.connect(paths.summaries_db())
    assert con.execute("SELECT day_utc FROM day_index").fetchone() == (day,)
    con.close()
