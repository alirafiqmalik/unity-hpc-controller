import sqlite3
import subprocess
import sys
from pathlib import Path

from lib import paths, retention

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
