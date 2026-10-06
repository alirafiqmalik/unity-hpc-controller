"""The management chain: ledger -> telemetry refresh -> status/jobs/logs/results.

Field reports on v0.6.0 found this whole chain broken: it read a campaign DB
nobody wrote, a monitor log that does not exist, and metrics from one ML
project. These tests pin the corrected behaviour, including the legacy ledgers
real projects already have on disk.
"""

import importlib.util
import json
import sqlite3
import sys
import types as pytypes
from pathlib import Path

import pytest

from lib import campaign
from test_dispatcher_ledger import dispatcher

REPO_ROOT = Path(__file__).resolve().parent.parent


def _install_mcp_stubs(monkeypatch):
    mcp_mod = pytypes.ModuleType("mcp")
    types_mod = pytypes.ModuleType("mcp.types")
    types_mod.Tool = lambda **k: types_mod
    types_mod.TextContent = lambda **k: types_mod
    server_mod = pytypes.ModuleType("mcp.server")
    server_mod.Server = lambda *a, **k: pytypes.SimpleNamespace(
        list_tools=lambda: (lambda fn: fn), call_tool=lambda: (lambda fn: fn))
    stdio_mod = pytypes.ModuleType("mcp.server.stdio")
    stdio_mod.stdio_server = lambda *a, **k: None
    server_mod.stdio = stdio_mod
    mcp_mod.server = server_mod
    mcp_mod.types = types_mod
    for name, mod in (("mcp", mcp_mod), ("mcp.types", types_mod),
                      ("mcp.server", server_mod), ("mcp.server.stdio", stdio_mod)):
        monkeypatch.setitem(sys.modules, name, mod)


@pytest.fixture
def server(monkeypatch):
    _install_mcp_stubs(monkeypatch)
    spec = importlib.util.spec_from_file_location(
        "hpc_server", REPO_ROOT / "mcp" / "hpc_server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_task_run(db, rows):
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.execute('CREATE TABLE IF NOT EXISTS task_run(job_id TEXT PRIMARY KEY, '
                'project TEXT, skill TEXT, hardware TEXT, submit TEXT, '
                'start TEXT, "end" TEXT, elapsed_s REAL, wait_s REAL, '
                'cpu_eff REAL, mem_eff REAL, max_rss_mb REAL, state TEXT, '
                'exit_code INTEGER, day_utc TEXT)')
    con.executemany('INSERT OR REPLACE INTO task_run(job_id, hardware, elapsed_s, '
                    'state) VALUES(?,?,?,?)', rows)
    con.commit()
    con.close()


def _legacy_ledger(state_dir, rows):
    """A ledger as written by the plugin before hardware/elapsed_s existed."""
    state_dir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(state_dir / "old.db")
    con.execute("CREATE TABLE jobs(job_id TEXT PRIMARY KEY, exp TEXT, "
                "partition TEXT, status TEXT, attempt INTEGER)")
    con.executemany("INSERT INTO jobs VALUES(?,?,?,?,?)", rows)
    con.commit()
    con.close()


# ─── ledger ──────────────────────────────────────────────────────────────────

def test_record_then_read_round_trip(tmp_project):
    campaign.record(tmp_project, "c1", "111", "smoke", "cpu")
    rows = campaign.jobs(tmp_project, "c1")
    assert rows[0]["job_id"] == "111" and rows[0]["status"] == "PENDING"


def test_recording_the_same_job_twice_does_not_duplicate(tmp_project):
    campaign.record(tmp_project, "c1", "111", "smoke", "cpu")
    campaign.record(tmp_project, "c1", "111", "smoke", "cpu")
    assert len(campaign.jobs(tmp_project, "c1")) == 1


def test_terminal_state_is_never_overwritten(tmp_project):
    campaign.record(tmp_project, "c1", "111", "smoke", "cpu")
    campaign.apply_states(tmp_project, "c1", {"111": {"state": "COMPLETED"}})
    campaign.apply_states(tmp_project, "c1", {"111": {"state": "RUNNING"}})
    assert campaign.jobs(tmp_project, "c1")[0]["status"] == "COMPLETED"


def test_refresh_pulls_state_from_shared_telemetry(tmp_project, tmp_data_dir,
                                                   monkeypatch):
    from lib import paths
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    campaign.record(tmp_project, "c1", "111", "smoke", "cpu")
    _seed_task_run(paths.summaries_db(), [("111", "a100", 42.0, "COMPLETED")])
    assert campaign.refresh_from_telemetry(tmp_project, "c1") == 1
    row = campaign.jobs(tmp_project, "c1")[0]
    assert row["status"] == "COMPLETED" and row["hardware"] == "a100"


def test_refresh_without_any_telemetry_store_is_a_no_op(tmp_project, tmp_data_dir):
    campaign.record(tmp_project, "c1", "111", "smoke", "cpu")
    assert campaign.refresh_from_telemetry(tmp_project, "c1") == 0
    assert campaign.jobs(tmp_project, "c1")[0]["status"] == "PENDING"


def test_worker_telemetry_refresh_preserves_live_scheduler_state(
        dispatcher, tmp_data_dir):
    from controller import workspace_worker as worker
    from lib import paths

    root = dispatcher.project
    campaign.record(root, "c1", "12345", "evaluation", "gpu")
    _seed_task_run(paths.summaries_db(), [("12345", "cpu", 0.0, "PENDING")])
    result = dispatcher("status", "--campaign", "c1",
                        STUB_SACCT="12345|RUNNING|gpu|00:00:21")
    assert result.returncode == 0, result.stderr
    observed = campaign.jobs(root, "c1")
    assert observed[0]["status"] == "RUNNING"
    assert observed[0]["hardware"] == "gpu"

    # Polls between live checks must not relabel the running GPU job as queued
    # on a CPU, or stamp the stale observation as a fresh update.
    for _ in range(2):
        assert worker._ledger(root, {"id": "c1"}) == observed

    # A newer authoritative scheduler check can still report a real requeue.
    result = dispatcher("status", "--campaign", "c1",
                        STUB_SACCT="12345|PENDING|gpu|00:00:00")
    assert result.returncode == 0, result.stderr
    assert campaign.jobs(root, "c1")[0]["status"] == "PENDING"


def test_telemetry_still_advances_new_jobs_and_finishes_running_jobs(
        tmp_project, tmp_data_dir):
    from lib import paths

    campaign.record(tmp_project, "c1", "111", "evaluation", "gpu")
    _seed_task_run(paths.summaries_db(), [("111", "a100", 21.0, "RUNNING")])
    assert campaign.refresh_from_telemetry(tmp_project, "c1") == 1
    assert campaign.jobs(tmp_project, "c1")[0]["status"] == "RUNNING"

    # Telemetry-only projects must still learn other active state changes.
    _seed_task_run(paths.summaries_db(), [("111", "a100", 30.0, "SUSPENDED")])
    assert campaign.refresh_from_telemetry(tmp_project, "c1") == 1
    assert campaign.jobs(tmp_project, "c1")[0]["status"] == "SUSPENDED"

    _seed_task_run(paths.summaries_db(), [("111", "a100", 42.0, "COMPLETED")])
    assert campaign.refresh_from_telemetry(tmp_project, "c1") == 1
    terminal = campaign.jobs(tmp_project, "c1")
    assert terminal[0]["status"] == "COMPLETED"
    assert terminal[0]["elapsed_s"] == 42.0

    _seed_task_run(paths.summaries_db(), [("111", "cpu", 0.0, "PENDING")])
    assert campaign.refresh_from_telemetry(tmp_project, "c1") == 0
    assert campaign.jobs(tmp_project, "c1") == terminal


def test_same_state_telemetry_preserves_live_hardware_and_elapsed(
        tmp_project, tmp_data_dir):
    from lib import paths

    campaign.record(tmp_project, "c1", "111", "evaluation", "gpu")
    campaign.apply_states(tmp_project, "c1", {
        "111": {"state": "RUNNING", "hardware": "gpu", "elapsed_s": 21.0}})
    observed = campaign.jobs(tmp_project, "c1")
    _seed_task_run(paths.summaries_db(), [("111", "cpu", 0.0, "RUNNING")])

    assert campaign.refresh_from_telemetry(tmp_project, "c1") == 0
    assert campaign.jobs(tmp_project, "c1") == observed


def test_legacy_ledger_is_upgraded_in_place_not_rejected(tmp_project):
    _legacy_ledger(tmp_project / ".unity_state", [("9", "old-job", "cpu", "RUNNING", 1)])
    rows = campaign.jobs(tmp_project, "old")
    assert rows[0]["job_id"] == "9"
    assert rows[0]["hardware"] is None, "missing columns must read as None, not raise"

    campaign.apply_states(tmp_project, "old", {"9": {"state": "COMPLETED",
                                                     "hardware": "cpu-preempt"}})
    row = campaign.jobs(tmp_project, "old")[0]
    assert row["status"] == "COMPLETED" and row["hardware"] == "cpu-preempt"


def test_a_new_job_can_be_recorded_into_a_legacy_ledger(tmp_project):
    _legacy_ledger(tmp_project / ".unity_state", [("9", "old-job", "cpu", "RUNNING", 1)])
    campaign.record(tmp_project, "old", "10", "new-job", "gpu")
    assert {r["job_id"] for r in campaign.jobs(tmp_project, "old")} == {"9", "10"}


def test_all_job_ids_spans_campaigns(tmp_project):
    campaign.record(tmp_project, "c1", "1", "a", "cpu")
    campaign.record(tmp_project, "c2", "2", "b", "cpu")
    assert sorted(campaign.all_job_ids(tmp_project)) == ["1", "2"]


@pytest.mark.parametrize("text,expected", [
    ("Submitted batch job 12345", "12345"),
    ("Submitted batch job 12345 on cluster unity", "12345"),
    ("Submitted batch job 12345;", "12345"),
    ("sbatch: error: Batch job submission failed: Invalid account", None),
    ("", None),
])
def test_sbatch_reply_parsing(text, expected):
    assert campaign.parse_sbatch_output(text) == expected


def test_sacct_parsing_folds_array_elements_and_normalises_cancelled():
    out = campaign.parse_sacct(
        "123|COMPLETED|cpu|00:00:21\n"
        "124_5|CANCELLED by 12345|gpu|01:02:03\n"
        "125|RUNNING|gpu-preempt|1-02:00:00\n"
        "garbage line\n"
    )
    assert out["123"]["elapsed_s"] == 21.0
    assert out["124"]["state"] == "CANCELLED"
    assert out["125"]["elapsed_s"] == 93600.0
    assert set(out) == {"123", "124", "125"}


# ─── MCP readers ─────────────────────────────────────────────────────────────

def test_status_reports_the_ledger(server, tmp_project, tmp_data_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    campaign.record(tmp_project, "c1", "111", "smoke", "cpu")
    out = server._unity_status(None)
    assert "Campaign: c1" in out and "PENDING" in out


def test_status_folds_in_telemetry_without_ssh(server, tmp_project, tmp_data_dir,
                                               monkeypatch):
    from lib import paths
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    monkeypatch.setattr(server, "_ssh", lambda *a, **k: pytest.fail("must not SSH"))
    campaign.record(tmp_project, "c1", "111", "smoke", "cpu")
    _seed_task_run(paths.summaries_db(), [("111", "a100", 42.0, "COMPLETED")])
    assert "COMPLETED" in server._unity_status(None)


def test_status_hints_at_the_live_check_only_while_jobs_are_active(
        server, tmp_project, tmp_data_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    campaign.record(tmp_project, "c1", "111", "smoke", "cpu")
    assert "run.sh status" in server._unity_status(None)
    campaign.apply_states(tmp_project, "c1", {"111": {"state": "COMPLETED"}})
    assert "run.sh status" not in server._unity_status(None)


def test_jobs_shows_hardware_and_survives_a_legacy_ledger(
        server, tmp_project, tmp_data_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    _legacy_ledger(tmp_project / ".unity_state", [("9", "old", "cpu", "COMPLETED", 1)])
    out = server._unity_jobs(None)
    assert "9" in out and "old" in out


def test_no_ledger_tells_the_user_how_to_create_one(server, tmp_project, monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    for text in (server._unity_status(None), server._unity_jobs(None)):
        assert "run.sh run" in text


def test_results_reports_whatever_the_job_printed(server, tmp_project, monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    campaign.record(tmp_project, "c1", "111", "sim", "cpu")
    out_dir = tmp_project / "_results" / "c1"
    out_dir.mkdir(parents=True)
    (out_dir / "sim-111.out").write_text(
        "starting\nthroughput_ops: 1420.5\nerror_rate: 0.031\ndone\n")
    out = server._unity_results(None)
    assert "throughput_ops" in out and "1420.5" in out
    assert "error_rate" in out


def test_results_does_not_require_ml_metrics(server, tmp_project, monkeypatch):
    """v0.6.0 dropped every job that did not print val_bpb — for a CPU project
    that meant every job."""
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    campaign.record(tmp_project, "c1", "111", "sim", "cpu")
    out_dir = tmp_project / "_results" / "c1"
    out_dir.mkdir(parents=True)
    (out_dir / "sim-111.out").write_text("solver_residual: 1e-9\n")
    assert "solver_residual" in server._unity_results(None)


def test_results_says_so_when_nothing_numeric_was_printed(server, tmp_project,
                                                          monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    campaign.record(tmp_project, "c1", "111", "sim", "cpu")
    out_dir = tmp_project / "_results" / "c1"
    out_dir.mkdir(parents=True)
    (out_dir / "sim-111.out").write_text("PLUGIN_TEST_OK\nall good\n")
    out = server._unity_results(None)
    assert "no" in out.lower() and str(out_dir) in out


def test_results_tsv_is_header_driven(server, tmp_project, monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    (tmp_project / "results.tsv").write_text(
        "commit\tmetric\tstatus\tdescription\n"
        "abc1234\t0.42\tkeep\tfirst try\n")
    out = json.loads(server._unity_results_tsv())
    assert out["columns"] == ["commit", "metric", "status", "description"]
    assert out["rows"][0]["metric"] == "0.42"
    assert out["rows"][0]["description"] == "first try"


def test_results_tsv_keeps_rows_a_fixed_schema_would_have_dropped(
        server, tmp_project, monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    (tmp_project / "results.tsv").write_text("commit\tnote\nabc1234\thello\n")
    out = json.loads(server._unity_results_tsv())
    assert len(out["rows"]) == 1


def test_results_tsv_is_bounded_and_paginates(server, tmp_project, monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    (tmp_project / "results.tsv").write_text(
        "commit\tmetric\n"
        "a\t1\n"
        "b\t2\n"
        "c\t3\n")
    out = json.loads(server._unity_results_tsv(limit=2, offset=1))
    assert [row["commit"] for row in out["rows"]] == ["b", "c"]
    assert out["total_rows"] == 3
    assert out["offset"] == 1
    assert out["limit"] == 2
    assert out["next_offset"] is None


def test_results_tsv_clamps_an_invalid_page(server, tmp_project, monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    (tmp_project / "results.tsv").write_text("commit\na\n")
    out = json.loads(server._unity_results_tsv(limit=0, offset=-4))
    assert out["limit"] == 1
    assert out["offset"] == 0
    assert out["rows"] == [{"commit": "a"}]


def test_logs_reads_the_job_output_not_a_monitor_log(server, tmp_project,
                                                     tmp_data_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    campaign.record(tmp_project, "c1", "111", "sim", "cpu")
    (tmp_project / "unityHPC").mkdir()
    (tmp_project / "unityHPC" / ".env").write_text('REMOTE_DIR="/work/x"\n')
    monkeypatch.setattr(server, "_ssh", lambda cmd, timeout=30: ("hello from the job", "", 0))
    out = server._unity_logs(None, 20)
    assert "hello from the job" in out and "sim-111.out" in out


def test_logs_falls_back_to_the_fetched_copy_when_ssh_fails(
        server, tmp_project, tmp_data_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    campaign.record(tmp_project, "c1", "111", "sim", "cpu")
    (tmp_project / "unityHPC").mkdir()
    (tmp_project / "unityHPC" / ".env").write_text('REMOTE_DIR="/work/x"\n')
    fetched = tmp_project / "_results" / "c1"
    fetched.mkdir(parents=True)
    (fetched / "sim-111.out").write_text("line a\nline b\n")

    def boom(*a, **k):
        raise OSError("ssh down")
    monkeypatch.setattr(server, "_ssh", boom)
    out = server._unity_logs(None, 20)
    assert "line b" in out and "fetched copy" in out


def test_ssh_timeout_is_configurable(server, monkeypatch):
    monkeypatch.delenv("UNITY_SSH_TIMEOUT", raising=False)
    assert server._default_ssh_timeout() == 60
    monkeypatch.setenv("UNITY_SSH_TIMEOUT", "180")
    assert server._default_ssh_timeout() == 180
    monkeypatch.setenv("UNITY_SSH_TIMEOUT", "not-a-number")
    assert server._default_ssh_timeout() == 60


def test_ssh_timeout_message_is_actionable(server, monkeypatch):
    import subprocess

    def timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="ssh", timeout=60)
    monkeypatch.setattr(server, "_ssh", timeout)
    out = server._unity_ssh("sacct -a", None)
    assert "60s" in out and "timeout" in out.lower()


def test_ssh_still_blocks_writes(server):
    assert "Blocked" in server._unity_ssh("rm -rf /work/x", None)


def test_env_value_takes_the_last_assignment_like_sourcing_does(server, tmp_project,
                                                                monkeypatch):
    """The generated .env ships blank placeholders and real values are appended
    below them. Reading the first match returned "" and silently disabled the
    live-log path — the failure only showed as an unexplained fallback."""
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    (tmp_project / "unityHPC").mkdir()
    (tmp_project / "unityHPC" / ".env").write_text(
        'REMOTE_DIR=""\n'
        '# REMOTE_DIR="/work/commented-out"\n'
        'REMOTE_DIR="/work/real/path"\n')
    assert server._env_value("REMOTE_DIR") == "/work/real/path"


def test_env_value_falls_back_to_the_default(server, tmp_project, monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    assert server._env_value("UNITY_HOST", "unity") == "unity"


def _logs_project(tmp_project, monkeypatch, job_id="111", exp="sim"):
    """A project with one recorded job and a stubbed SSH that logs every call."""
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    campaign.record(tmp_project, "c1", job_id, exp, "cpu")
    (tmp_project / "unityHPC").mkdir()
    (tmp_project / "unityHPC" / ".env").write_text(
        'REMOTE_DIR=""\nREMOTE_DIR="/work/real"\n')
    return []


def test_logs_uses_the_live_path_when_remote_dir_is_set(server, tmp_project,
                                                        tmp_data_dir, monkeypatch):
    seen = _logs_project(tmp_project, monkeypatch)

    def fake_ssh(cmd, timeout=30):
        seen.append(cmd)
        return (f"live output for {cmd[-3:]}", "", 0)
    monkeypatch.setattr(server, "_ssh", fake_ssh)
    out = server._unity_logs(None, 5)
    assert "/work/real/_slurm/sim-111.out" in seen[0]
    assert "live" in out


def test_logs_reads_stderr_as_well_as_stdout(server, tmp_project, tmp_data_dir,
                                             monkeypatch):
    """The failure reason lives in .err. A tool that reads only .out can say
    that a job failed but never why -- one field test lost a session to a
    ModuleNotFoundError this tool structurally could not show."""
    seen = _logs_project(tmp_project, monkeypatch)

    def fake_ssh(cmd, timeout=30):
        seen.append(cmd)
        if cmd.endswith(".err"):
            return ("ModuleNotFoundError: No module named 'harness'", "", 0)
        return ("=== done rc=1 ===", "", 0)
    monkeypatch.setattr(server, "_ssh", fake_ssh)

    out = server._unity_logs(None, 5)
    assert "--- sim-111.out" in out
    assert "--- sim-111.err" in out
    assert "ModuleNotFoundError" in out
    assert [c.split("/")[-1] for c in seen] == ["sim-111.out", "sim-111.err"]


@pytest.mark.parametrize("stream,expected", [
    ("out", ["sim-111.out"]),
    ("err", ["sim-111.err"]),
    ("both", ["sim-111.out", "sim-111.err"]),
])
def test_logs_stream_selects_which_files_are_read(server, tmp_project, tmp_data_dir,
                                                  monkeypatch, stream, expected):
    seen = _logs_project(tmp_project, monkeypatch)
    monkeypatch.setattr(server, "_ssh",
                        lambda cmd, timeout=30: (seen.append(cmd), ("text", "", 0))[1])
    server._unity_logs(None, 5, stream)
    assert [c.split("/")[-1] for c in seen] == expected


def test_logs_rejects_an_unknown_stream(server, tmp_project, tmp_data_dir, monkeypatch):
    _logs_project(tmp_project, monkeypatch)
    assert "unknown stream" in server._unity_logs(None, 5, "stdout")


def test_logs_uses_the_array_log_name_for_an_array_task(server, tmp_project,
                                                        tmp_data_dir, monkeypatch):
    """One array script serves every task, so SLURM writes <campaign>-%A_%a --
    not <exp>-<job id>. run.sh's fetch and logs paths already knew this; the
    MCP tool asked for a file that never exists for a sweep."""
    seen = _logs_project(tmp_project, monkeypatch, job_id="12345_0", exp="trial-a")
    monkeypatch.setattr(server, "_ssh",
                        lambda cmd, timeout=30: (seen.append(cmd), ("text", "", 0))[1])
    server._unity_logs(None, 5, "out")
    assert seen == ["tail -n 5 /work/real/_slurm/c1-12345_0.out"]


def test_logs_falls_back_to_the_fetched_copy_per_stream(server, tmp_project,
                                                        tmp_data_dir, monkeypatch):
    _logs_project(tmp_project, monkeypatch)
    fetched = tmp_project / "_results" / "c1"
    fetched.mkdir(parents=True)
    (fetched / "sim-111.err").write_text("Traceback (most recent call last):\n")

    def fake_ssh(cmd, timeout=30):
        return ("", "ssh: connect failed", 255)
    monkeypatch.setattr(server, "_ssh", fake_ssh)

    out = server._unity_logs(None, 5)
    assert "fetched copy" in out
    assert "Traceback" in out


def test_logs_says_nothing_is_there_rather_than_naming_one_stream(
        server, tmp_project, tmp_data_dir, monkeypatch):
    _logs_project(tmp_project, monkeypatch)
    monkeypatch.setattr(server, "_ssh", lambda cmd, timeout=30: ("", "", 1))
    out = server._unity_logs(None, 5)
    assert "sim-111.out" in out and "sim-111.err" in out


@pytest.mark.parametrize("raw,expected", [
    ('"unity"               # ssh alias', "unity"),
    ('"unity"', "unity"),
    ("unity   # ssh alias", "unity"),
    ("unity", "unity"),
    ('"/work/a b/c"  # path with a space', "/work/a b/c"),
    ('"tag#1"', "tag#1"),
    ("", ""),
    ('""', ""),
])
def test_env_values_are_parsed_the_way_bash_would(server, raw, expected):
    """The generated .env documents itself with trailing comments; leaving one
    glued to the value made every SSH-backed tool fail with 'hostname contains
    invalid characters' in a freshly scaffolded cpu project."""
    assert server._parse_env_value(raw) == expected


@pytest.mark.parametrize("ptype", ["cpu", "gpu", "ml"])
def test_every_generated_env_yields_a_usable_ssh_host(server, tmp_project,
                                                      materialise, monkeypatch,
                                                      ptype):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    materialise(tmp_project, ptype)
    host = server._env_value("UNITY_HOST", "unity")
    assert host == "unity", f"{ptype} scaffold yields unusable host {host!r}"
    remote = server._env_value("REMOTE_DIR")
    assert remote.startswith("/") and "#" not in remote


def _stub_runner(unity_dir: Path, output: str, rc: int = 0):
    (unity_dir).mkdir(parents=True, exist_ok=True)
    (unity_dir / "run.sh").write_text(
        f"#!/usr/bin/env bash\ncat <<'EOF'\n{output}\nEOF\nexit {rc}\n")


def test_submit_warns_when_a_real_job_was_not_recorded(server, tmp_project,
                                                       monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    _stub_runner(tmp_project / "unityHPC", "Submitted batch job 999")
    assert "not recorded in the ledger" in server._unity_submit("x", "", None)


def test_submit_does_not_warn_on_a_dry_run(server, tmp_project, monkeypatch):
    """A dry-run records nothing by design; warning about it trains agents to
    ignore the warning that matters."""
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    _stub_runner(tmp_project / "unityHPC", "[dry-run] campaign=c1 exp=x partition=cpu")
    assert "not recorded" not in server._unity_submit("x", "--dry-run", None)


def test_submit_is_quiet_when_the_job_was_recorded(server, tmp_project, monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    _stub_runner(tmp_project / "unityHPC",
                 "Submitted batch job 999\nRecorded job 999 in campaign c1")
    assert "not recorded" not in server._unity_submit("x", "", None)


def test_reading_jobs_does_not_modify_a_ledger_with_no_news(server, tmp_project,
                                                            tmp_data_dir, monkeypatch):
    """A project keeping its ledgers in git saw five tracked files turn modified
    just from listing jobs: the read path migrated the schema even with nothing
    to write."""
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    _legacy_ledger(tmp_project / ".unity_state", [("9", "old", "cpu", "RUNNING", 1)])
    db = tmp_project / ".unity_state" / "old.db"
    before = db.read_bytes()

    server._unity_jobs(None)
    server._unity_status(None)
    server._unity_my_jobs()

    assert db.read_bytes() == before, "a read modified the ledger on disk"


def test_a_read_still_folds_in_telemetry_when_there_is_news(server, tmp_project,
                                                            tmp_data_dir, monkeypatch):
    """The no-op guard must not disable the refresh it guards."""
    from lib import paths
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    campaign.record(tmp_project, "c1", "111", "smoke", "cpu")
    _seed_task_run(paths.summaries_db(), [("111", "a100", 42.0, "COMPLETED")])
    assert "COMPLETED" in server._unity_jobs(None)


def test_apply_states_with_nothing_observed_is_a_no_op(tmp_project):
    campaign.record(tmp_project, "c1", "111", "smoke", "cpu")
    db = tmp_project / ".unity_state" / "c1.db"
    before = db.read_bytes()
    assert campaign.apply_states(tmp_project, "c1", {}) == 0
    assert db.read_bytes() == before
