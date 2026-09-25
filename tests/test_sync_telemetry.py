import concurrent.futures
import gzip
import json
import os
import re
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SYNC = REPO_ROOT / "cluster-intel" / "sync-telemetry.sh"


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

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


def test_pull_matches_source_and_local_edit_is_discarded(tmp_path):
    src = tmp_path / "cluster"
    data = tmp_path / "data"
    day = _today()
    _make_day(src, day, _good_slots(day))
    assert _run(src, data).returncode == 0

    archived = data / "telemetry" / day / "resource_state.jsonl"
    original = (src / day / "resource_state.jsonl").read_bytes()
    assert archived.read_bytes() == original, "archive must match source byte-for-byte (I2)"
    assert (src / day).exists(), "today stays on the cluster"

    archived.write_bytes(archived.read_bytes() + b"tampered\n")
    assert _run(src, data).returncode == 0
    assert archived.read_bytes() == original, "a local edit must be discarded by the next pull"


def test_local_only_old_days_are_backed_up_and_siblings_survive_a_pull(tmp_path):
    src = tmp_path / "cluster"
    data = tmp_path / "data"
    _make_day(src, "2026-07-20", _good_slots("2026-07-20"))
    _make_day(data / "telemetry", "2026-01-01", _good_slots("2026-01-01"))
    (data / "telemetry-imported").mkdir(parents=True)
    (data / "telemetry-imported" / "keep.txt").write_text("keep")
    (data / "archive").mkdir()
    (data / "archive" / "old.txt").write_text("old")
    (data / "cluster-config.json").write_text('{"schema_version":1}')

    assert _run(src, data).returncode == 0
    archive = next((data / "archive" / "telemetry-retention" / "2026-01-01")
                   .glob("raw-mirror-*.tar.gz"))
    with tarfile.open(archive, "r:gz") as tar:
        assert "telemetry/2026-01-01/resource_state.jsonl" in tar.getnames()
    assert not (data / "telemetry" / "2026-01-01").exists()
    assert (data / "telemetry-imported" / "keep.txt").read_text() == "keep"
    assert (data / "archive" / "old.txt").read_text() == "old"
    assert (data / "cluster-config.json").read_text() == '{"schema_version":1}'


def test_archived_days_leave_the_cluster_and_remain_in_local_backups(tmp_path):
    src = tmp_path / "cluster"
    data = tmp_path / "data"
    _make_day(src, "2026-05-01", _good_slots("2026-05-01"))

    result = _run(src, data)
    assert result.returncode == 0, result.stderr
    assert not (data / "telemetry" / "2026-05-01").exists()
    folder = data / "archive" / "telemetry-retention" / "2026-05-01"
    assert next(folder.glob("raw-mirror-*.tar.gz"))
    assert not (src / "2026-05-01").exists(), "the cluster staging day must go after rollup"
    import sqlite3
    summary = next(folder.glob("summary-*.sqlite.gz"))
    saved = tmp_path / "old-summary.sqlite"
    with gzip.open(summary, "rb") as src_file:
        saved.write_bytes(src_file.read())
    con = sqlite3.connect(saved)
    fs = con.execute(
        "SELECT fully_summarised FROM day_index WHERE day_utc='2026-05-01'"
    ).fetchone()[0]
    con.close()
    assert fs == 1


def test_incomplete_remote_day_stays_until_summarised(tmp_path):
    src = tmp_path / "cluster"
    data = tmp_path / "data"
    _make_day(src, "2026-05-01", _bad_slots("2026-05-01"))

    assert _run(src, data).returncode == 0
    assert (src / "2026-05-01").exists(), "an unsummarised day must stay on the cluster"
    folder = data / "archive" / "telemetry-retention" / "2026-05-01"
    assert next(folder.glob("raw-mirror-*.tar.gz"))

    assert _run(src, data, UNITY_HPC_FORCE_PRUNE="1").returncode == 0
    assert not (src / "2026-05-01").exists(), "force may drop an incomplete remote day"
    assert next(folder.glob("raw-mirror-*.tar.gz")), "the local backup survives"


def test_broken_source_aborts_without_wiping_archive(tmp_path):
    # A dry-run rsync that itself FAILS (bad/unreachable source) must abort
    # before the real pull, leaving the existing local archive untouched.
    src = tmp_path / "does-not-exist"  # never created: rsync exits non-zero
    data = tmp_path / "data"
    _make_day(data / "telemetry", "2026-07-20", _good_slots("2026-07-20"))
    archive_file = data / "telemetry" / "2026-07-20" / "resource_state.jsonl"
    before = archive_file.read_bytes()

    result = _run(src, data)

    assert result.returncode != 0, "a failed dry-run must abort the sync, not succeed"
    assert "pulling" in (result.stdout + result.stderr).lower()
    assert archive_file.exists(), "the local archive must not be wiped"
    assert archive_file.read_bytes() == before, "archive must be byte-identical (not touched)"


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


def test_only_sync_script_mutates_the_local_telemetry_archive():
    # (a) No Python file writes to paths.telemetry_dir() (reads/globs are fine).
    #     telemetry_imported_dir() is a DISTINCT name and does not match "telemetry_dir(".
    for p in _scan_files():
        if p.suffix != ".py":
            continue
        for line in p.read_text().splitlines():
            if "telemetry_dir(" in line and any(v in line for v in _WRITE_VERBS):
                raise AssertionError(f"{p.name} mutates the telemetry archive: {line.strip()}")

    # (b) Only sync-telemetry.sh may rsync into a /telemetry/ destination.
    for p in _scan_files():
        if p.suffix != ".sh":
            continue
        text = p.read_text()
        if "rsync" in text and re.search(r"/telemetry/", text) and p.name != "sync-telemetry.sh":
            raise AssertionError(f"{p.name} rsyncs into telemetry/ but is not the sync driver")
