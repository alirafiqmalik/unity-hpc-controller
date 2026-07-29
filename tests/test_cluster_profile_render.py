import importlib.util
import json
import sys
import types as pytypes
from pathlib import Path

import pytest

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


def test_empty_state_names_recon(server, tmp_data_dir):
    out = server._unity_cluster_profile()
    assert "cluster-config.json" in out
    assert "/unity-hpc:recon" in out


def test_renders_partitions_and_gpu_fleet_as_markdown(server, tmp_data_dir):
    (tmp_data_dir / "cluster-config.json").write_text(json.dumps({
        "schema_version": 1, "cluster": "unity", "slurm_version": "25.11.6",
        "partitions": {"gpu": {"nodes": 145, "gpu_types": ["a100", "l40s"],
                               "max_walltime": "24:00:00", "access": "open"}},
        "gpu_fleet": {"a100": {"total_accessible": 157, "vram_gb": [80, 40],
                               "compute_capability": 8.0}},
        "account_limits": {"account": "pi_yourlab_umass_edu",
                           "qos": [{"name": "short", "max_wall": "04:00:00"}]},
        "provenance": {"last_writer": "esim-fv", "writers_seen": ["esim-fv"]},
    }))
    out = server._unity_cluster_profile()
    assert out.lstrip().startswith("#")
    assert "gpu" in out and "a100" in out
    assert "157" in out
    assert "24:00:00" in out
    assert "esim-fv" in out
    assert "{" not in out, "must be rendered markdown, not raw JSON"


def test_render_is_robust_to_missing_sections(server):
    out = server._render_cluster_config({"schema_version": 1, "cluster": "unity"})
    assert "unity" in out  # no KeyError on absent partitions/gpu_fleet
