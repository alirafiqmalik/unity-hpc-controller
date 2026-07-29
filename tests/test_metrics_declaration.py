"""Metric reporting is generic unless a project declares otherwise.

The plugin serves every kind of SLURM job, so it must not know what a good
result looks like. A v0.6.0 field report hit the other side of this: hardcoded
ML-training columns shown to a CPU project that printed none of them.

A project that does have a headline metric declares it in
unityHPC/metrics.json. Absent declaration, nothing is assumed and nothing is
ranked.
"""

import importlib.util
import json
import sys
import types as pytypes
from pathlib import Path

import pytest

from lib import metrics

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


@pytest.fixture
def project_with_output(tmp_project, monkeypatch):
    """A project with one fetched job, ready to have metrics declared or not."""
    from lib import campaign
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    campaign.record(tmp_project, "c1", "111", "run", "cpu")
    (tmp_project / "unityHPC").mkdir(exist_ok=True)
    out = tmp_project / "_results" / "c1"
    out.mkdir(parents=True)

    def add(stem: str, text: str):
        (out / f"{stem}.out").write_text(text)

    add.project = tmp_project
    add.declare = lambda payload: (tmp_project / "unityHPC" / "metrics.json").write_text(
        payload if isinstance(payload, str) else json.dumps(payload))
    return add


# ─── the declaration itself ──────────────────────────────────────────────────

def test_no_declaration_is_the_normal_case(tmp_project):
    assert metrics.load(tmp_project) is None


def test_a_declaration_is_read(tmp_project):
    (tmp_project / "unityHPC").mkdir()
    (tmp_project / "unityHPC" / "metrics.json").write_text(json.dumps(
        {"primary": "val_bpb", "goal": "min", "report": ["val_bpb", "mfu_percent"]}))
    spec = metrics.load(tmp_project)
    assert spec.primary == "val_bpb" and spec.goal == "min"
    assert spec.report == ("val_bpb", "mfu_percent")


def test_primary_is_always_reported_even_if_omitted_from_report(tmp_project):
    (tmp_project / "unityHPC").mkdir()
    (tmp_project / "unityHPC" / "metrics.json").write_text(json.dumps(
        {"primary": "score", "report": ["runtime_s"]}))
    assert metrics.load(tmp_project).report == ("score", "runtime_s")


@pytest.mark.parametrize("payload", [
    "{not json",
    '["a", "b"]',
    '{"goal": "sideways"}',
    '{"report": "val_bpb"}',
    '{"primary": 3}',
])
def test_a_broken_declaration_degrades_to_generic_with_a_reason(tmp_project, payload):
    """Job output is real data — a malformed declaration must never suppress it."""
    (tmp_project / "unityHPC").mkdir()
    (tmp_project / "unityHPC" / "metrics.json").write_text(payload)
    spec, error = metrics.load_with_error(tmp_project)
    assert spec is None and error and "metrics.json" in error


def test_declared_keys_lead_and_undeclared_keys_still_appear():
    spec = metrics.MetricSpec(primary="b", report=("b", "a"))
    assert metrics.order_keys(spec, ["z", "a", "b"]) == ["b", "a", "z"]


def test_keys_nobody_printed_are_reported_as_missing():
    spec = metrics.MetricSpec(report=("val_bpb", "mfu"))
    assert metrics.missing_keys(spec, ["mfu"]) == ["val_bpb"]


@pytest.mark.parametrize("goal,winner", [("min", "a"), ("max", "b")])
def test_best_respects_the_declared_goal(goal, winner):
    spec = metrics.MetricSpec(primary="score", goal=goal)
    rows = {"a": {"score": 1.0}, "b": {"score": 9.0}}
    assert metrics.best(spec, rows)[0] == winner


def test_best_is_none_without_a_primary():
    assert metrics.best(metrics.MetricSpec(), {"a": {"score": 1.0}}) is None


def test_best_is_none_when_no_job_printed_the_primary():
    spec = metrics.MetricSpec(primary="score")
    assert metrics.best(spec, {"a": {"other": 1.0}}) is None


# ─── how results read ────────────────────────────────────────────────────────

def test_generic_project_gets_no_assumed_columns(server, project_with_output):
    project_with_output("sim-111", "throughput_ops: 1420.5\n")
    out = server._unity_results(None)
    assert "throughput_ops" in out
    for ml_column in ("val_bpb", "memory_gb", "mfu_%", "train_s"):
        assert ml_column not in out


def test_generic_project_ranks_nothing(server, project_with_output):
    project_with_output("sim-111", "throughput_ops: 1420.5\n")
    assert "Best by" not in server._unity_results(None)


def test_a_job_printing_nothing_says_so(server, project_with_output):
    project_with_output("sim-111", "hello-hermes\ndone\n")
    out = server._unity_results(None)
    assert "none printed" in out


def test_declaring_a_metric_orders_and_ranks(server, project_with_output):
    project_with_output.declare({"primary": "val_bpb", "goal": "min",
                                 "report": ["val_bpb", "mfu_percent"]})
    project_with_output("a-1", "mfu_percent: 39.8\nval_bpb: 0.9979\nnoise: 3\n")
    project_with_output("b-2", "mfu_percent: 41.2\nval_bpb: 0.9912\nnoise: 4\n")
    out = server._unity_results(None)
    assert out.index("val_bpb") < out.index("mfu_percent"), "declared order wins"
    assert "Best by val_bpb (min): b-2 = 0.9912" in out
    assert "noise" in out, "undeclared metrics stay visible"


def test_a_max_goal_ranks_the_other_way(server, project_with_output):
    project_with_output.declare({"primary": "accuracy", "goal": "max"})
    project_with_output("a-1", "accuracy: 0.81\n")
    project_with_output("b-2", "accuracy: 0.93\n")
    assert "a-1" not in server._unity_results(None).split("Best by")[1]


def test_labels_rename_columns_without_touching_the_data(server, project_with_output):
    project_with_output.declare({"report": ["peak_vram_mb"],
                                 "labels": {"peak_vram_mb": "vram_mb"}})
    project_with_output("a-1", "peak_vram_mb: 44100\n")
    out = server._unity_results(None)
    assert "vram_mb" in out and "44100" in out


def test_declared_but_unprinted_metrics_are_called_out(server, project_with_output):
    """An ML project whose job died before emitting its metric should be told,
    not shown a blank column."""
    project_with_output.declare({"primary": "val_bpb", "report": ["val_bpb"]})
    project_with_output("a-1", "runtime_s: 12\n")
    out = server._unity_results(None)
    assert "Declared but not printed" in out and "val_bpb" in out


def test_declared_metric_missing_entirely_still_reports_the_output(
        server, project_with_output):
    project_with_output.declare({"primary": "val_bpb", "report": ["val_bpb"]})
    project_with_output("a-1", "hello\n")
    out = server._unity_results(None)
    assert "metrics.json" in out and "no job printed them" in out


def test_broken_declaration_still_shows_the_metrics(server, project_with_output):
    project_with_output.declare("{not json")
    project_with_output("a-1", "throughput_ops: 5\n")
    out = server._unity_results(None)
    assert "throughput_ops" in out and "5" in out
    assert "could not be read" in out
