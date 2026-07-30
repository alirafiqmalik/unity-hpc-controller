import concurrent.futures
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SYNC = REPO_ROOT / "cluster-intel" / "sync-telemetry.sh"

pytestmark = pytest.mark.skipif(
    subprocess.run(["bash", "-c", "command -v rsync"], capture_output=True).returncode != 0,
    reason="rsync not available")


def _good_slots(day, n=96, rid="a100"):
    return [{"ts": f"{day}T{i // 4:02d}:{(i % 4) * 15:02d}:00Z", "kind": "gpu_type",
             "resource_id": rid, "alloc": 50, "total": 100} for i in range(n)]


def _bad_slots(day, n=96):
    # slots counted (all_slots) but no computable util -> rows_emitted=0 -> not fully
    return [{"ts": f"{day}T{i // 4:02d}:{(i % 4) * 15:02d}:00Z", "kind": "mystery",
             "resource_id": "x"} for i in range(n)]


def _make_day(root: Path, day: str, recs):
    d = root / day
    d.mkdir(parents=True, exist_ok=True)
    (d / "resource_state.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in recs))


def _run(src, data_dir, **env_extra):
    env = dict(os.environ)
    env["UNITY_TELEMETRY_SRC"] = str(src) + "/"
    env["UNITY_HPC_DATA"] = str(data_dir)
    env.update(env_extra)
    return subprocess.run(["bash", str(SYNC)], capture_output=True, text=True, env=env)


def test_mirror_matches_source_and_local_edit_is_discarded(tmp_path):
    src = tmp_path / "cluster"
    data = tmp_path / "data"
    _make_day(src, "2026-07-20", _good_slots("2026-07-20"))
    assert _run(src, data).returncode == 0

    mirrored = data / "telemetry" / "2026-07-20" / "resource_state.jsonl"
    original = (src / "2026-07-20" / "resource_state.jsonl").read_bytes()
    assert mirrored.read_bytes() == original, "mirror must match source byte-for-byte (I2)"

    mirrored.write_bytes(mirrored.read_bytes() + b"tampered\n")
    assert _run(src, data).returncode == 0
    assert mirrored.read_bytes() == original, "a local edit must be discarded by the next pull"


def test_siblings_survive_a_delete_pull(tmp_path):
    src = tmp_path / "cluster"
    data = tmp_path / "data"
    _make_day(src, "2026-07-20", _good_slots("2026-07-20"))
    _make_day(data / "telemetry", "2026-01-01", _good_slots("2026-01-01"))  # to be deleted
    # siblings that must never be touched
    (data / "telemetry-imported").mkdir(parents=True)
    (data / "telemetry-imported" / "keep.txt").write_text("keep")
    (data / "archive").mkdir()
    (data / "archive" / "old.txt").write_text("old")
    (data / "cluster-config.json").write_text('{"schema_version":1}')

    assert _run(src, data, UNITY_HPC_FORCE_PRUNE="1").returncode == 0
    assert not (data / "telemetry" / "2026-01-01").exists(), "pruned day should be gone"
    assert (data / "telemetry-imported" / "keep.txt").read_text() == "keep"
    assert (data / "archive" / "old.txt").read_text() == "old"
    assert (data / "cluster-config.json").read_text() == '{"schema_version":1}'


def test_retention_gate_withholds_then_allows(tmp_path):
    src = tmp_path / "cluster"
    data = tmp_path / "data"
    # cluster has only a recent day; the workstation still holds an un-summarised old day
    _make_day(src, "2026-07-20", _good_slots("2026-07-20"))
    _make_day(data / "telemetry", "2026-05-01", _good_slots("2026-05-01"))

    # Pull #1: summaries.db absent -> fail-safe withhold. Old day survives; rollup then
    # summarises it (it is still present in the mirror because --delete was withheld).
    assert _run(src, data).returncode == 0
    assert (data / "telemetry" / "2026-05-01").exists(), "withheld --delete keeps the day"
    import sqlite3
    con = sqlite3.connect(data / "summaries.db")
    fs = con.execute("SELECT fully_summarised FROM day_index WHERE day_utc='2026-05-01'").fetchone()[0]
    con.close()
    assert fs == 1, "the pull's rollup must summarise the surviving day"

    # Pull #2: the day is now fully summarised -> --delete applies.
    assert _run(src, data).returncode == 0
    assert not (data / "telemetry" / "2026-05-01").exists(), "now safe to prune"
    con = sqlite3.connect(data / "summaries.db")
    pruned = con.execute("SELECT value FROM meta WHERE key='raw_pruned_through'").fetchone()[0]
    con.close()
    assert pruned == "2026-05-01"


def test_broken_source_aborts_without_wiping_mirror(tmp_path):
    # A dry-run rsync that itself FAILS (bad/unreachable source) must never be
    # read as "zero deletions" -> the script must abort before the real
    # --delete pull, leaving the existing local mirror untouched.
    src = tmp_path / "does-not-exist"  # never created: rsync exits non-zero
    data = tmp_path / "data"
    _make_day(data / "telemetry", "2026-07-20", _good_slots("2026-07-20"))
    mirror_file = data / "telemetry" / "2026-07-20" / "resource_state.jsonl"
    before = mirror_file.read_bytes()

    result = _run(src, data)

    assert result.returncode != 0, "a failed dry-run must abort the sync, not succeed"
    assert "pulling" in (result.stdout + result.stderr).lower()
    assert mirror_file.exists(), "the local mirror must not be wiped"
    assert mirror_file.read_bytes() == before, "mirror must be byte-identical (not touched)"


def test_missing_telemetry_source_fails_before_sync(tmp_path):
    env = dict(os.environ, UNITY_HPC_DATA=str(tmp_path / "data"))
    env.pop("UNITY_TELEMETRY_SRC", None)
    result = subprocess.run(["bash", str(SYNC)], capture_output=True, text=True, env=env)
    assert result.returncode == 2
    assert "UNITY_TELEMETRY_SRC" in result.stderr


def test_concurrent_syncs_serialise(tmp_path):
    src = tmp_path / "cluster"
    data = tmp_path / "data"
    _make_day(src, "2026-07-20", _good_slots("2026-07-20"))
    (data / "locks").mkdir(parents=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(lambda _: _run(src, data, UNITY_HPC_SYNC_SLEEP="1"), range(4)))

    outs = [r.stdout + r.stderr for r in results]
    already = sum("already running" in o.lower() for o in outs)
    worked = sum("pulling" in o.lower() for o in outs)
    assert already == 3 and worked == 1, "exactly one may pull; the rest exit cleanly (I7)"
    assert (data / "summaries.db").exists()


SCAN_DIRS = ("cluster-intel", "lib", "scripts", "mcp")
_WRITE_VERBS = ("write_text", "write_bytes", ".unlink(", "rmtree", "os.remove", ".mkdir(", "open(")


def _scan_files():
    for top in SCAN_DIRS:
        for p in (REPO_ROOT / top).rglob("*"):
            if p.is_file() and p.suffix in {".py", ".sh"} and "__pycache__" not in p.parts:
                yield p


def test_only_sync_script_mutates_the_local_telemetry_mirror():
    # (a) No Python file writes to paths.telemetry_dir() (reads/globs are fine).
    #     telemetry_imported_dir() is a DISTINCT name and does not match "telemetry_dir(".
    for p in _scan_files():
        if p.suffix != ".py":
            continue
        for line in p.read_text().splitlines():
            if "telemetry_dir(" in line and any(v in line for v in _WRITE_VERBS):
                raise AssertionError(f"{p.name} mutates the telemetry mirror: {line.strip()}")

    # (b) Only sync-telemetry.sh may rsync into a /telemetry/ destination.
    for p in _scan_files():
        if p.suffix != ".sh":
            continue
        text = p.read_text()
        if "rsync" in text and re.search(r"/telemetry/", text) and p.name != "sync-telemetry.sh":
            raise AssertionError(f"{p.name} rsyncs into telemetry/ but is not the sync driver")
