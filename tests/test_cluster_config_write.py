import concurrent.futures
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from lib import cluster_config as cc
from lib import paths

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_first_write_creates_valid_json(tmp_data_dir):
    status, cfg = cc.write_config(
        {"partitions": {"gpu": {"nodes": 145, "observed_utc": "2026-07-22T14:00:00Z"}}},
        writer="esim-fv")
    assert status == "written"
    on_disk = json.loads(paths.config_path().read_text())
    assert on_disk["partitions"]["gpu"]["nodes"] == 145
    assert on_disk["schema_version"] == cc.SCHEMA_VERSION
    assert on_disk["provenance"]["last_writer"] == "esim-fv"
    assert "esim-fv" in on_disk["provenance"]["writers_seen"]


def test_ttl_skips_a_fresh_config_byte_for_byte(tmp_data_dir):
    cc.write_config({"cluster": "unity"}, writer="p1")
    before = paths.config_path().read_bytes()
    status, _ = cc.write_config({"cluster": "unity", "slurm_version": "25.11.6"},
                                writer="p2", ttl_seconds=43200)
    assert status == "skipped"
    assert paths.config_path().read_bytes() == before, "a fresh config must be untouched"


def test_force_overrides_the_ttl(tmp_data_dir):
    cc.write_config({"cluster": "unity"}, writer="p1")
    status, cfg = cc.write_config({"slurm_version": "25.11.6"}, writer="p2",
                                  ttl_seconds=43200, force=True)
    assert status == "written"
    assert cfg["slurm_version"] == "25.11.6"


_WRITE = (
    "import json, sys; sys.path.insert(0, sys.argv[1]); "
    "from lib import cluster_config as cc; "
    "cc.write_config(json.loads(sys.stdin.read()), writer=sys.argv[2], force=True)"
)


def _write_in_process(obs, writer):
    """One separate process for each writer, so the file lock is what keeps writes apart."""
    return subprocess.run(
        [sys.executable, "-c", _WRITE, str(REPO_ROOT), writer],
        input=json.dumps(obs), capture_output=True, text=True)


def test_eight_concurrent_writers_lose_nothing(tmp_data_dir):
    def obs(i):
        return {"partitions": {f"p{i}": {"nodes": i,
                                         "observed_utc": f"2026-07-22T14:0{i}:00Z"}},
                "gpu_fleet": {"a100": {"total_accessible": 100 + i,
                                       "observed_utc": f"2026-07-22T14:0{i}:00Z"}}}

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda i: _write_in_process(obs(i), f"w{i}"), range(8)))
    assert all(r.returncode == 0 for r in results), [r.stderr for r in results]

    cfg = json.loads(paths.config_path().read_text())
    # every partition observation survives (union), none lost to a clobber
    for i in range(8):
        assert cfg["partitions"][f"p{i}"]["nodes"] == i
    # capacity is the max across all concurrent observations
    assert cfg["gpu_fleet"]["a100"]["total_accessible"] == 107
    assert sorted(cfg["provenance"]["writers_seen"]) == [f"w{i}" for i in range(8)]


def test_atomic_write_leaves_no_tmp_file(tmp_data_dir):
    cc.write_config({"cluster": "unity"}, writer="p1")
    cc.write_config({"slurm_version": "25.11.6"}, writer="p2", force=True)
    tmp = paths.config_path().with_suffix(".json.tmp")
    assert not tmp.exists(), "the temp file must not survive a successful atomic write"
    # the target itself must always parse: no reader can ever observe a partial write
    json.loads(paths.config_path().read_text())
