"""Agent tools submit through the real HTTP seam without project wiring."""

import asyncio
import importlib.util
import json
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
    """hpc_server.py imports `mcp.server.stdio`, `mcp.types` and `mcp.server.Server`.
    Provide just enough for it to import without the SDK installed."""
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
    for name, mod in (("mcp", mcp_mod), ("mcp.types", types_mod),
                      ("mcp.server", server_mod), ("mcp.server.stdio", stdio_mod)):
        monkeypatch.setitem(sys.modules, name, mod)


@pytest.fixture
def server(monkeypatch):
    """Import mcp/hpc_server.py without the real `mcp` package installed."""
    _install_mcp_stubs(monkeypatch)
    spec = importlib.util.spec_from_file_location("hpc_server", REPO_ROOT / "mcp" / "hpc_server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_tool_is_a_controller_client(server):
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert names == {"unity_campaign_plan", "unity_campaign_submit", "unity_campaign_status",
                     "unity_campaign_results", "unity_campaign_cancel", "unity_backend",
                     "unity_accounting", "unity_doctor"}
    source = (REPO_ROOT / "mcp" / "hpc_server.py").read_text()
    assert "subprocess" not in source and "unityHPC" not in source and "sqlite3" not in source
    result = json.loads(asyncio.run(server._dispatch("unity_submit", {"exp": "example"})))
    assert result["ok"] is False


def test_accounting_tool_forwards_only_known_filters(server, monkeypatch):
    calls = []
    monkeypatch.setattr(server, "_controller_request", lambda *args: calls.append(args) or "{}")
    asyncio.run(server._dispatch("unity_accounting", {"gpu_type": "a100", "limit": 5, "bogus": "x", "user": ""}))
    assert calls == [("GET", "/api/v1/telemetry/accounting?gpu_type=a100&limit=5")]


def test_doctor_reports_controller_health_and_plugin_version(server, monkeypatch):
    monkeypatch.setattr(server, "_controller_request", lambda *args: json.dumps({"ok": True, "mode": "backend"}))
    report = json.loads(asyncio.run(server._dispatch("unity_doctor", {})))
    assert report["ok"] is True and report["controller"]["mode"] == "backend"
    assert report["plugin"]["version"] and report["plugin"]["code_stale"] is False


def test_runner_file_is_sent_exactly_to_controller(server, tmp_path, monkeypatch, tmp_data_dir):
    from controller.http import Request, handle

    spec = {"schema_version": 1, "campaign_id": "fixture"}
    path = tmp_path / "campaign.json"
    path.write_text(json.dumps(spec))
    requests = []

    def request(method, route, payload=None):
        requests.append((method, route, payload))
        response = handle(Request(method, route, body=json.dumps(payload).encode()))
        return response.body.decode()

    monkeypatch.setattr(server, "_controller_request", request)
    result = json.loads(asyncio.run(server._dispatch("unity_campaign_plan", {"specification_path": str(path)})))
    assert requests == [("POST", "/api/v1/campaigns/plan", spec)]
    assert result["ok"] is False, "an incomplete declaration must be rejected by the controller"


def test_cursor_results_preserve_identity_and_bounds(server, monkeypatch):
    calls = []
    monkeypatch.setattr(server, "_controller_request", lambda *args: calls.append(args) or '{}')
    asyncio.run(server._dispatch("unity_campaign_results", {"campaign_id": "study", "after": 19, "limit": 50}))
    assert calls == [("GET", "/api/v1/campaigns/study/results?after=19&limit=50")]
    calls.clear()
    result = json.loads(asyncio.run(server._dispatch("unity_campaign_results", {"campaign_id": "study", "limit": 1001})))
    assert result["ok"] is False
    assert not calls


def test_bad_json_never_submits(server, tmp_path, monkeypatch):
    path = tmp_path / "campaign.json"
    path.write_text('[]')
    monkeypatch.setattr(server, "_controller_request", lambda *args: (_ for _ in ()).throw(AssertionError("must not submit")))
    result = json.loads(asyncio.run(server._dispatch("unity_campaign_submit", {"specification_path": str(path)})))
    assert result["ok"] is False
