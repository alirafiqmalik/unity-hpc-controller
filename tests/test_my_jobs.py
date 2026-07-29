import importlib.util
import json
import sqlite3
import sys
import types as pytypes
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


class _Tool:
    """Stand-in for mcp.types.Tool that keeps its kwargs inspectable."""

    def __init__(self, name=None, description=None, inputSchema=None):
        self.name = name
        self.description = description
        self.inputSchema = inputSchema or {}


class _TextContent:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _Server:
    def __init__(self, *args, **kwargs):
        pass

    def list_tools(self):
        return lambda fn: fn

    def call_tool(self):
        return lambda fn: fn


def _install_mcp_stubs(monkeypatch):
    """hpc_server.py does `import mcp.server.stdio`, `import mcp.types as types`
    and `from mcp.server import Server`. Provide just enough for it to import."""
    mcp_mod = pytypes.ModuleType("mcp")
    types_mod = pytypes.ModuleType("mcp.types")
    types_mod.Tool = _Tool
    types_mod.TextContent = _TextContent

    server_mod = pytypes.ModuleType("mcp.server")
    server_mod.Server = _Server

    stdio_mod = pytypes.ModuleType("mcp.server.stdio")
    stdio_mod.stdio_server = lambda *a, **k: None

    server_mod.stdio = stdio_mod
    mcp_mod.server = server_mod
    mcp_mod.types = types_mod

    for name, mod in (
        ("mcp", mcp_mod),
        ("mcp.types", types_mod),
        ("mcp.server", server_mod),
        ("mcp.server.stdio", stdio_mod),
    ):
        monkeypatch.setitem(sys.modules, name, mod)


@pytest.fixture
def server(monkeypatch):
    """Import mcp/hpc_server.py without the real `mcp` package installed."""
    _install_mcp_stubs(monkeypatch)
    spec = importlib.util.spec_from_file_location(
        "hpc_server", REPO_ROOT / "mcp" / "hpc_server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_campaign(state_dir, job_ids):
    state_dir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(state_dir / "c1.db")
    con.execute("CREATE TABLE jobs(job_id TEXT, exp TEXT, partition TEXT, "
                "status TEXT, attempt INTEGER)")
    con.executemany("INSERT INTO jobs VALUES(?,?,?,?,?)",
                    [(j, "exp1", "gpu", "COMPLETED", 1) for j in job_ids])
    con.commit()
    con.close()


def _seed_task_run(db, rows):
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.execute('CREATE TABLE task_run(job_id TEXT PRIMARY KEY, project TEXT, '
                'skill TEXT, hardware TEXT, submit TEXT, start TEXT, "end" TEXT, '
                'elapsed_s REAL, wait_s REAL, cpu_eff REAL, mem_eff REAL, '
                'max_rss_mb REAL, state TEXT, exit_code INTEGER, day_utc TEXT)')
    con.executemany('INSERT INTO task_run(job_id, hardware, elapsed_s, state) '
                    'VALUES(?,?,?,?)', rows)
    con.commit()
    con.close()


def test_enriches_own_jobs_and_marks_uncollected_pending(server, tmp_project,
                                                         tmp_data_dir, monkeypatch):
    from lib import paths
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    _seed_campaign(tmp_project / ".unity_state", ["A", "B"])
    _seed_task_run(paths.summaries_db(), [("A", "a100", 120.0, "COMPLETED")])
    out = json.loads(server._unity_my_jobs())
    jobs = {j["job_id"]: j for j in out["jobs"]}
    assert jobs["A"]["hardware"] == "a100" and jobs["A"]["elapsed_s"] == 120.0
    assert jobs["B"]["telemetry"] == "pending"       # in campaign, not yet in task_run


def test_no_summaries_lists_pending_with_guidance(server, tmp_project,
                                                  tmp_data_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    _seed_campaign(tmp_project / ".unity_state", ["A"])
    out = json.loads(server._unity_my_jobs())          # no summaries.db
    assert out["jobs"][0]["telemetry"] == "pending"
    assert "hpc-sync-telemetry" in out.get("note", "")


def test_empty_project_is_clean(server, tmp_project, monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    out = json.loads(server._unity_my_jobs())
    assert out["jobs"] == []


def test_my_jobs_tool_is_registered_and_dispatched(server, tmp_project, monkeypatch):
    import asyncio

    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    tools = asyncio.run(server.list_tools())
    assert "unity_my_jobs" in {t.name for t in tools}
    out = json.loads(asyncio.run(server._dispatch("unity_my_jobs", {})))
    assert out["jobs"] == []
