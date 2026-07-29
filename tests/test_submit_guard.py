import asyncio
import importlib.util
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


def test_missing_scaffold_gives_actionable_message(server, tmp_project, monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    out = server._unity_submit("baseline", "")
    assert "No such file or directory" not in out
    assert "/unity-hpc:setup" in out
    assert "unityHPC/run.sh" in out


def test_present_scaffold_is_invoked(server, tmp_project, materialise, monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    unity = materialise(tmp_project, "cpu")
    unity.joinpath("run.sh").write_text(
        '#!/usr/bin/env bash\necho "SUBMITTED $2"\n')
    out = server._unity_submit("baseline", "")
    assert "SUBMITTED baseline" in out


def test_extra_args_are_forwarded(server, tmp_project, materialise, monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    unity = materialise(tmp_project, "cpu")
    unity.joinpath("run.sh").write_text(
        '#!/usr/bin/env bash\necho "ARGS $*"\n')
    out = server._unity_submit("baseline", "--hold --qos short")
    assert "--hold" in out and "--qos" in out and "short" in out


def test_submit_tool_is_not_ml_specific(server):
    tools = asyncio.run(server.list_tools())
    submit = next(t for t in tools if t.name == "unity_submit")

    described = submit.description.lower()
    for banned in ("train", "torchrun"):
        assert banned not in described, f"description must not mention {banned}"

    exp_desc = submit.inputSchema["properties"]["exp"]["description"].lower()
    assert "experiment name/path" not in exp_desc, \
        "the exp field must not presuppose an experiment-shaped project"
