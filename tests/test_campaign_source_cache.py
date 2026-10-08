"""Execute the staging protocol locally: no SSH, cluster, or compute submission."""
import hashlib
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from controller import campaign_contract as contract, campaign_store as store
from controller.campaign_slurm import SlurmAdapter, remote_root


class ShellAdapter(SlurmAdapter):
    def __init__(self, remote, barrier=None):
        self.settings = {"remote_root": str(remote)}
        self.transfers = 0
        self.barrier = barrier
        self.lose_activation_reply = False

    def command(self, command, **kwargs):
        result = subprocess.run(["bash", "-c", command], capture_output=True, text=True, timeout=10)
        if self.lose_activation_reply and "HPC_SOURCE_CACHE_CREATED" in command and not result.returncode:
            self.lose_activation_reply = False
            return subprocess.CompletedProcess([], 255, result.stdout, "connection lost after activation")
        return result

    def transfer(self, source, remote, **kwargs):
        self.transfers += 1
        if self.barrier:
            self.barrier.wait(timeout=10)
        shutil.copy2(source, remote)


@pytest.fixture
def bundles(tmp_data_dir, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "run.py").write_text("print('pinned scientific command')\n")
    (source / "manifest.json").write_text('{"source":"pinned"}\n')
    declaration = {"path": str(source), "exclude": []}
    inventory = contract.inventory(declaration)
    campaigns = []
    for identity in ("first", "second"):
        archive = store.root(identity) / "bundle.tar.gz"
        archive.parent.mkdir(parents=True)
        contract.snapshot(declaration, inventory, archive)
        campaigns.append({"id": identity, "spec": {"bundle_manifest": inventory}})
    # Different gzip header timestamps preserve the same locked file inventory.
    archive = store.root("second") / "bundle.tar.gz"
    content = bytearray(archive.read_bytes())
    content[4:8] = (123456).to_bytes(4, "little")
    archive.write_bytes(content)
    return campaigns, tmp_path / "remote"


def test_same_manifest_reuses_one_immutable_cache_despite_different_archive_bytes(bundles):
    campaigns, remote = bundles
    adapter = ShellAdapter(remote)
    cold = adapter.stage(campaigns[0])
    warm = adapter.stage(campaigns[1])
    first = Path(remote_root(adapter.settings, campaigns[0])) / "source"
    second = Path(remote_root(adapter.settings, campaigns[1])) / "source"
    assert not cold["cache_hit"] and warm["cache_hit"]
    assert cold["source_manifest_sha256"] == warm["source_manifest_sha256"]
    assert first.is_symlink() and second.is_symlink() and first.resolve() == second.resolve()
    assert (second / "run.py").read_text() == "print('pinned scientific command')\n"
    assert not (second / "run.py").stat().st_mode & 0o222
    assert adapter.transfers == 1


def test_lost_activation_reply_recovers_without_second_transfer_or_source_replacement(bundles):
    campaigns, remote = bundles
    adapter = ShellAdapter(remote)
    adapter.lose_activation_reply = True
    with pytest.raises(RuntimeError, match="connection lost"):
        adapter.stage(campaigns[0])
    source = Path(remote_root(adapter.settings, campaigns[0])) / "source"
    previous = source.lstat().st_ino
    assert adapter.stage(campaigns[0])["cache_hit"]
    assert source.lstat().st_ino == previous and adapter.transfers == 1


def test_corrupt_cache_marker_never_activates_or_replaces_source(bundles):
    campaigns, remote = bundles
    adapter = ShellAdapter(remote)
    cache = Path(adapter.stage(campaigns[0])["cache_path"])
    marker = cache / ".controller-source-manifest-sha256"
    marker.chmod(0o600)
    marker.write_text("different manifest\n")
    with pytest.raises(RuntimeError, match="marker differs"):
        adapter.stage(campaigns[1])
    assert not (Path(remote_root(adapter.settings, campaigns[1])) / "source").exists()
    assert adapter.transfers == 1


def test_existing_reuse_path_rejects_replaced_cache_directory_symlink(bundles):
    campaigns, remote = bundles
    adapter = ShellAdapter(remote)
    cache = Path(adapter.stage(campaigns[0])["cache_path"])
    source = Path(remote_root(adapter.settings, campaigns[0])) / "source"
    previous = source.lstat().st_ino
    moved = cache.with_name(cache.name + "-replaced")
    cache.rename(moved)
    cache.symlink_to(moved, target_is_directory=True)
    with pytest.raises(RuntimeError, match="existing campaign source"):
        adapter.stage(campaigns[0])
    assert source.lstat().st_ino == previous and adapter.transfers == 1


def test_existing_legacy_source_is_preserved_and_reused_only_with_exact_archive_marker(bundles):
    campaigns, remote = bundles
    adapter = ShellAdapter(remote)
    source = Path(remote_root(adapter.settings, campaigns[0])) / "source"
    source.mkdir(parents=True)
    (source / "running-job-evidence").write_text("preserve")
    archive = store.root(campaigns[0]["id"]) / "bundle.tar.gz"
    (source / ".bundle-sha256").write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + "\n")
    inode = source.stat().st_ino
    receipt = adapter.stage(campaigns[0])
    assert receipt["legacy_source"]
    assert receipt["source_path"] == str(source) and receipt["cache_path"] is None
    assert source.stat().st_ino == inode and not source.is_symlink() and adapter.transfers == 0
    (source / ".bundle-sha256").write_text("mismatch")
    with pytest.raises(RuntimeError, match="existing campaign source"):
        adapter.stage(campaigns[0])
    assert (source / "running-job-evidence").read_text() == "preserve"


def test_concurrent_cold_stagers_publish_one_verified_cache(bundles):
    campaigns, remote = bundles
    barrier = threading.Barrier(2)
    adapters = [ShellAdapter(remote, barrier), ShellAdapter(remote, barrier)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda pair: pair[0].stage(pair[1]), zip(adapters, campaigns)))
    assert sum(receipt["cache_hit"] for receipt in receipts) == 1
    assert receipts[0]["cache_path"] == receipts[1]["cache_path"]
    assert not list((remote / "source-cache").glob(".stage-*"))
    for adapter, campaign in zip(adapters, campaigns):
        assert (Path(remote_root(adapter.settings, campaign)) / "source/run.py").is_file()
