"""unity_doctor: what is this server process actually running?

A field report traced a bug to source code that was already fixed. The session
was talking to a server started before the upgrade — reading the file on disk
could never reveal that, because the file was correct. Only the running process
knows which version it loaded.
"""

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


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    """Keep the developer's own installed plugins out of these assertions.

    Without this, every test here reads the real
    ~/.claude/plugins/installed_plugins.json, so the whole file passes or fails
    depending on which version happens to be installed on the machine running
    it. Bumping the plugin version turned that latent coupling into three
    failures that had nothing to do with the change. A missing registry is
    already a supported state: unknown installed version is not staleness."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "empty-claude"))


@pytest.fixture
def registry(tmp_path, monkeypatch, isolated_registry):
    """A stand-in ~/.claude/plugins/installed_plugins.json."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    path = tmp_path / "claude" / "plugins" / "installed_plugins.json"
    path.parent.mkdir(parents=True)

    def write(version, project_path="/", install_path=None):
        path.write_text(json.dumps({"plugins": {"unity-hpc@phd-agentic-tools": [
            {"scope": "local", "projectPath": project_path, "version": version,
             "installPath": install_path or f"/cache/unity-hpc/{version}"}]}}))
    return write


def _doctor(server) -> dict:
    return json.loads(server._unity_doctor())


def test_healthy_server_reports_ok(server, tmp_project, tmp_data_dir, monkeypatch,
                                   registry):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    registry(server._plugin_version(REPO_ROOT))
    report = _doctor(server)
    assert report["status"] == "ok"
    assert report["problems"] == []


def test_doctor_names_the_version_and_source_it_is_running(server, tmp_project,
                                                           tmp_data_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    report = _doctor(server)
    assert report["running"]["version"] == server._plugin_version(REPO_ROOT)
    assert report["running"]["source"].endswith("hpc_server.py")


def test_code_replaced_after_start_is_reported_as_stale(server, tmp_project,
                                                        tmp_data_dir, monkeypatch):
    """The exact field scenario: the fix is on disk, the process predates it."""
    monkeypatch.setattr(server, "_LOADED_AT", 0.0)   # process started long ago
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    report = _doctor(server)
    assert report["status"] == "stale"
    issues = [p["issue"] for p in report["problems"]]
    assert "server_code_changed_after_start" in issues
    assert any("/reload-plugins" in p["fix"] for p in report["problems"])


def test_version_mismatch_against_the_registry_is_reported(server, tmp_project,
                                                           tmp_data_dir,
                                                           monkeypatch, registry):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    registry("99.0.0")
    report = _doctor(server)
    assert report["status"] == "stale"
    assert "version_mismatch" in [p["issue"] for p in report["problems"]]
    assert report["installed"]["version"] == "99.0.0"


def test_registry_entry_for_this_project_wins(server, tmp_path, tmp_data_dir,
                                              monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    path = tmp_path / "claude" / "plugins" / "installed_plugins.json"
    path.parent.mkdir(parents=True)
    mine = tmp_path / "mine"
    mine.mkdir()
    path.write_text(json.dumps({"plugins": {"unity-hpc@phd-agentic-tools": [
        {"projectPath": "/somewhere/else", "version": "1.0.0", "installPath": "/a"},
        {"projectPath": str(mine), "version": "2.0.0", "installPath": "/b"}]}}))
    monkeypatch.setenv("PROJECT_DIR", str(mine))
    assert _doctor(server)["installed"]["version"] == "2.0.0"


def test_a_missing_registry_is_not_an_error(server, tmp_project, tmp_data_dir,
                                            tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "nonexistent"))
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    report = _doctor(server)
    assert report["installed"]["version"] is None
    assert report["status"] == "ok", "unknown installed version is not staleness"


def test_a_corrupt_registry_is_not_an_error(server, tmp_project, tmp_data_dir,
                                            tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    path = tmp_path / "claude" / "plugins" / "installed_plugins.json"
    path.parent.mkdir(parents=True)
    path.write_text("{ broken")
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    assert _doctor(server)["status"] == "ok"


def test_doctor_reports_project_state(server, tmp_project, tmp_data_dir,
                                      materialise, monkeypatch):
    from lib import campaign
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    materialise(tmp_project, "cpu")
    campaign.record(tmp_project, "c1", "111", "run", "cpu")
    report = _doctor(server)
    assert report["project"]["scaffold"] is True
    assert report["project"]["recorded_jobs"] == 1
    assert report["project"]["campaigns"] == ["c1"]
    assert report["project"]["unity_host"] == "unity"


def test_doctor_reports_no_metric_declaration_as_normal(server, tmp_project,
                                                        tmp_data_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    declaration = _doctor(server)["metrics_declaration"]
    assert declaration["declared"] is False
    assert "whatever jobs print" in declaration["note"]


def test_doctor_reports_a_metric_declaration(server, tmp_project, tmp_data_dir,
                                             monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    (tmp_project / "unityHPC").mkdir()
    (tmp_project / "unityHPC" / "metrics.json").write_text(
        json.dumps({"primary": "val_bpb", "goal": "min"}))
    declaration = _doctor(server)["metrics_declaration"]
    assert declaration["declared"] is True and declaration["primary"] == "val_bpb"


def test_doctor_works_in_a_bare_directory(server, tmp_path, monkeypatch):
    """It is the tool people reach for when things are broken; it must not be
    the tool that breaks."""
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    report = _doctor(server)
    assert report["project"]["scaffold"] is False
    assert report["project"]["recorded_jobs"] == 0


# ─── scaffold drift ──────────────────────────────────────────────────────────
#
# Two field workers independently hit this: a documented per-invocation override
# silently did nothing, because unityHPC/run.sh is a COPY in the project and a
# plugin upgrade never touches it. unity_doctor reported "ok" the whole time.

def test_a_freshly_generated_scaffold_is_not_stale(server, tmp_project,
                                                   tmp_data_dir, materialise,
                                                   monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    materialise(tmp_project, "cpu")
    report = _doctor(server)
    assert report["project"]["scaffold_version"] == server._plugin_version(REPO_ROOT)
    assert "scaffold_stale" not in [p["issue"] for p in report["problems"]]


def test_an_unstamped_scaffold_is_reported_stale(server, tmp_project,
                                                 tmp_data_dir, monkeypatch):
    """Exactly the llmttl/hermes case: a dispatcher generated before stamping."""
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    unity = tmp_project / "unityHPC"
    unity.mkdir()
    (unity / "run.sh").write_text("#!/usr/bin/env bash\nset -a; . .env; set +a\n")
    report = _doctor(server)
    # A stale dispatcher is a real problem, but it is not this process running
    # code that is no longer on disk -- which is what "stale" is reserved for.
    assert report["status"] == "degraded"
    assert report["code_stale"] is False
    stale = [p for p in report["problems"] if p["issue"] == "scaffold_stale"]
    assert stale, report["problems"]
    assert "unstamped" in stale[0]["detail"]
    assert "setup" in stale[0]["fix"]
    assert report["project"]["scaffold_version"] is None


def test_an_older_stamped_scaffold_is_reported_stale(server, tmp_project,
                                                     tmp_data_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    unity = tmp_project / "unityHPC"
    unity.mkdir()
    (unity / "run.sh").write_text(
        '#!/usr/bin/env bash\nUNITY_SCAFFOLD_VERSION="0.1.0"\n')
    report = _doctor(server)
    stale = [p for p in report["problems"] if p["issue"] == "scaffold_stale"]
    assert stale and "0.1.0" in stale[0]["detail"]


def test_a_release_that_leaves_the_template_alone_does_not_cry_wolf(
        server, tmp_project, tmp_data_dir, materialise, monkeypatch):
    """Drift is judged by content, not version equality. A server-only release
    must not mark every project stale -- that is how a real staleness signal
    gets ignored."""
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    unity = materialise(tmp_project, "cpu")
    text = (unity / "run.sh").read_text()
    # same dispatcher, generated by an earlier release of the same template
    (unity / "run.sh").write_text(text.replace(
        f'UNITY_SCAFFOLD_VERSION="{server._plugin_version(REPO_ROOT)}"',
        'UNITY_SCAFFOLD_VERSION="0.0.1"'))
    report = _doctor(server)
    assert "scaffold_stale" not in [p["issue"] for p in report["problems"]]


def test_a_hand_edited_dispatcher_is_reported(server, tmp_project, tmp_data_dir,
                                              materialise, monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    unity = materialise(tmp_project, "cpu")
    (unity / "run.sh").write_text(
        (unity / "run.sh").read_text() + "\n# local edit\n")
    stale = [p for p in _doctor(server)["problems"]
             if p["issue"] == "scaffold_stale"]
    assert stale and "edited it deliberately" in stale[0]["detail"]


def test_a_project_with_no_scaffold_is_not_called_stale(server, tmp_project,
                                                        tmp_data_dir, monkeypatch):
    """Not every project uses the generated dispatcher; absence is not drift."""
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    report = _doctor(server)
    assert "scaffold_stale" not in [p["issue"] for p in report["problems"]]


def test_doctor_reports_unmarked_unity_guidance_as_stale(server, tmp_project,
                                                         tmp_data_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    path = tmp_project / "CLAUDE.md"
    path.write_text("# Unity Cluster\nUse unityHPC/run.sh run job.\n")
    report = _doctor(server)
    stale = [p for p in report["problems"] if p["issue"] == "claude_guidance_stale"]
    assert stale and str(path) in stale[0]["detail"]
    # The fix must name a command that can actually resolve this finding.
    # --write-guidance only acts when CLAUDE.md is absent, and this finding only
    # fires when it exists, so the old advice was a provable no-op.
    assert "--refresh-guidance-marker" in stale[0]["fix"]
    assert "--write-guidance" not in stale[0]["fix"]
    # Missing prose in a project file is not the server running dead code.
    assert report["status"] == "degraded" and report["code_stale"] is False


def test_a_cosmetic_finding_does_not_read_as_code_staleness(server, tmp_project,
                                                            tmp_data_dir, monkeypatch):
    """Both conditions produced the identical headline string, so an agent told
    to call unity_doctor first could not tell "your server is running dead code"
    from "your CLAUDE.md lacks a marker" without walking problems[]."""
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    (tmp_project / "CLAUDE.md").write_text("# Unity Cluster\nunityHPC/run.sh\n")
    cosmetic = _doctor(server)

    monkeypatch.setattr(server, "_LOADED_AT", 0.0)
    real = _doctor(server)

    assert cosmetic["status"] == "degraded" and real["status"] == "stale"
    assert cosmetic["status"] != real["status"]
    assert cosmetic["code_stale"] is False and real["code_stale"] is True


def test_doctor_accepts_current_version_marked_guidance(server, tmp_project,
                                                        tmp_data_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_project))
    version = server._plugin_version(REPO_ROOT)
    (tmp_project / "CLAUDE.md").write_text(
        f"# Unity Cluster\n<!-- unity-hpc-guidance: {version} -->\nunityHPC\n")
    report = _doctor(server)
    assert "claude_guidance_stale" not in [p["issue"] for p in report["problems"]]
