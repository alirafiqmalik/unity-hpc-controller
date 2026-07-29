import importlib.util
import json
import sqlite3
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


def _seed_summaries(data_dir):
    con = sqlite3.connect(data_dir / "summaries.db")
    con.executescript(
        "CREATE TABLE hourly_resource(resource_kind TEXT, resource_id TEXT, hour_utc TEXT,"
        " util_min REAL, util_mean REAL, util_max REAL, util_p95 REAL, free_ratio REAL,"
        " samples INTEGER, PRIMARY KEY(resource_kind,resource_id,hour_utc));")
    for h in range(6):
        con.execute("INSERT INTO hourly_resource VALUES('gpu_type','a100',?,?,?,?,?,?,?)",
                    (f"2026-07-20T{h:02d}:00:00Z", 0.4, 0.5, 0.6, 0.58, 0.5, 4))
    con.commit()
    con.close()


def test_unity_usage_reads_summaries_db(server, tmp_data_dir):
    _seed_summaries(tmp_data_dir)
    out = json.loads(server._unity_usage(1000000, None))
    ids = [r["gpu_type"] for r in out["by_gpu_type"]]
    assert "a100" in ids


def test_unity_traffic_reads_summaries_db(server, tmp_data_dir):
    _seed_summaries(tmp_data_dir)
    out = json.loads(server._unity_traffic())
    assert out.get("status") != "no_data"
    assert "best_hours_utc" in out or "by_hour_utc" in out


def test_unity_usage_db_present_but_no_matching_rows(server, tmp_data_dir):
    _seed_summaries(tmp_data_dir)
    # Window that predates all seeded rows -> DB/schema present, zero matching rows.
    out = json.loads(server._unity_usage(1, None))
    assert out["status"] == "no_data"
    assert "hpc-sync-telemetry" in out["message"]


def _seed_unrelated_table(data_dir):
    con = sqlite3.connect(data_dir / "summaries.db")
    con.executescript("CREATE TABLE unrelated(x TEXT);")
    con.commit()
    con.close()


def test_unity_usage_missing_table_gives_populate_guidance(server, tmp_data_dir):
    _seed_unrelated_table(tmp_data_dir)
    out = json.loads(server._unity_usage(168, None))
    assert out["status"] == "no_data"
    assert "hpc-sync-telemetry" in out["message"]
    assert "no such table" not in out["message"]


def test_unity_traffic_missing_table_gives_populate_guidance(server, tmp_data_dir):
    _seed_unrelated_table(tmp_data_dir)
    out = json.loads(server._unity_traffic())
    assert out["status"] == "no_data"
    assert "hpc-sync-telemetry" in out["message"]
    assert "no such table" not in out["message"]


def test_all_readers_empty_state_names_their_command(server, tmp_data_dir):
    # $UNITY_HPC_DATA exists but is empty; nothing must raise, each must guide.
    assert "recon" in server._unity_cluster_profile()
    usage = json.loads(server._unity_usage(168, None))
    assert usage["status"] == "no_data" and "hpc-sync-telemetry" in usage["message"]
    traffic = json.loads(server._unity_traffic())
    assert traffic["status"] == "no_data" and "hpc-sync-telemetry" in traffic["message"]
    # A project that has never submitted must be told how to submit, not handed
    # an internal noun ("campaign DB") it has no way to act on.
    empty = server._unity_status(None)
    assert "No jobs recorded" in empty
    assert "run.sh run" in empty


def test_no_references_to_the_retired_pipeline():
    scan_dirs = ("mcp", "cluster-intel", "skills", "scripts")
    scan_files = (REPO_ROOT / "README.md",)
    offenders = []
    candidates = list(scan_files)
    for top in scan_dirs:
        candidates.extend((REPO_ROOT / top).rglob("*"))
    for p in candidates:
        if not (p.is_file() and p.suffix in {".py", ".sh", ".md"}):
            continue
        if "__pycache__" in p.parts:
            continue
        text = p.read_text(errors="replace")
        for needle in ("build-usage-slots", "analyze-usage", "analyze-backends",
                       "analysis/usage.db"):
            if needle in text:
                offenders.append(f"{p.relative_to(REPO_ROOT)}::{needle}")
    assert not offenders, f"retired-pipeline references remain: {offenders}"


# --- collector -> rollup -> reader, with no hand-written summaries.db ---------

def test_collector_output_reaches_unity_usage_and_traffic(server, tmp_data_dir):
    """Full path: the collector's own build_resource_state output -> rollup ->
    a real (non-no_data) unity_usage/unity_traffic. Guards the gap where the
    collector emitted only node/partition records, so both readers answered
    no_data forever after a successful sync."""
    sys.path.insert(0, str(REPO_ROOT / "cluster-intel"))
    import collector_parse  # noqa: E402
    import rollup  # noqa: E402

    gpu_text = (
        " h100         [##################] 8/8          1         80        9.0     \n"
        " h200_nvl     [##################] 8/8          0         143       9.0     \n"
        " a100         [###############   ] 148/157       12        80        8.0     \n"
        " l40s         [################# ] 10/108        3         48        8.9     \n"
        "18 nodes are inacessible and are not counted in the above numbers.\n"
    )
    nodes_text = "gpu|gpu001|mix|48/16/0/64|515000|120000|gpu:a100:4|gpu:a100:3\n"
    partitions_text = "gpu|up|1|48/16/0/64|gpu:a100:4\n"

    day = "2026-07-20"
    d = tmp_data_dir / "telemetry" / day
    d.mkdir(parents=True)
    recs = []
    for i in range(8):
        ts = f"{day}T{i // 4:02d}:{(i % 4) * 15:02d}:00Z"
        recs += collector_parse.build_resource_state(
            ts, partitions_text, "", gpu_text, nodes_text)
    (d / "resource_state.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in recs))

    kinds = {r["kind"] for r in recs}
    assert "gpu_type" in kinds, "collector must emit gpu_type records"

    rollup.run()

    usage = json.loads(server._unity_usage(24 * 3650, None))
    assert usage.get("status") != "no_data", usage
    by_type = {r["gpu_type"]: r for r in usage["by_gpu_type"]}
    assert {"a100", "h100", "h200_nvl", "l40s"} <= set(by_type)
    assert by_type["a100"]["avg_util"] == round(148 / 157, 3)
    assert by_type["h100"]["avg_util"] == 1.0
    assert by_type["a100"]["samples"] == 8

    traffic = json.loads(server._unity_traffic())
    assert traffic["status"] == "ok", traffic
    assert traffic["by_hour_utc"], traffic


def test_node_gres_only_collector_output_still_reaches_the_readers(server, tmp_data_dir):
    """Same path with a SILENT unity-slurm-gpu-usage — the deployed failure
    mode. Per-node GRES must still yield gpu_type rows the readers match."""
    sys.path.insert(0, str(REPO_ROOT / "cluster-intel"))
    import collector_parse  # noqa: E402
    import rollup  # noqa: E402

    nodes_text = ("gpu|gpu001|mix|48/16/0/64|515000|120000|gpu:a100:4|gpu:a100:3\n"
                  "gpu|gpu002|mix|48/16/0/64|515000|120000|gpu:l40s:8|gpu:l40s:2\n")
    day = "2026-07-20"
    d = tmp_data_dir / "telemetry" / day
    d.mkdir(parents=True)
    recs = []
    for i in range(4):
        ts = f"{day}T00:{i * 15:02d}:00Z"
        recs += collector_parse.build_resource_state(ts, "", "", "", nodes_text)
    (d / "resource_state.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in recs))

    rollup.run()
    usage = json.loads(server._unity_usage(24 * 3650, None))
    assert usage.get("status") != "no_data", usage
    by_type = {r["gpu_type"]: r for r in usage["by_gpu_type"]}
    assert set(by_type) == {"a100", "l40s"}
    assert by_type["a100"]["avg_util"] == 0.75
    assert json.loads(server._unity_traffic())["status"] == "ok"
