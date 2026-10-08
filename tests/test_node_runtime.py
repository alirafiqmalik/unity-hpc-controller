import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

import pytest

from controller import node_runtime
from controller.runtime_integrity import file_digest


def test_local_capacity_rejects_shared_filesystem_even_when_free(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs:
        "Filesystem Type 1024-blocks Used Available Capacity Mounted on\nserver:/work nfs 100 0 100 0% /work\n")
    with pytest.raises(ValueError, match="not an approved"):
        node_runtime.local_capacity(tmp_path, 1)


def test_cleanup_requires_current_job_marker_and_refuses_symlink(tmp_path, monkeypatch):
    monkeypatch.setenv("SLURM_JOB_ID", "111")
    root = tmp_path / "tracebench-runtime-owned"
    root.mkdir()
    marker = {"uid": os.getuid(), "job_id": "222", "runtime_root": str(root.resolve())}
    node_runtime.write_json(root / node_runtime.MARKER, marker)
    with pytest.raises(ValueError, match="another allocation"):
        node_runtime.cleanup(root)
    assert root.exists()
    link = tmp_path / "tracebench-runtime-link"
    link.symlink_to(root)
    with pytest.raises(ValueError, match="owned runtime"):
        node_runtime.cleanup(link)
    marker["job_id"] = "111"
    node_runtime.write_json(root / node_runtime.MARKER, marker)
    node_runtime.cleanup(root)
    assert not root.exists()


@pytest.fixture
def assets(tmp_path, monkeypatch):
    shared, assets, tree, output, temporary = [tmp_path / name for name in ("shared", "assets", "tree", "output", "temp")]
    for path in (shared, assets, tree, temporary):
        path.mkdir()
    (tree / "lean/bin").mkdir(parents=True)
    (tree / "lean/bin/lean").write_text("fake pinned lean")
    (tree / "source").mkdir()
    (tree / "source/lean-toolchain").write_text("leanprover/lean4:v4.27.0\n")
    (tree / "source/lake-manifest.json").write_text('{"pinned":true}\n')
    rows = [{"path": path.relative_to(tree).as_posix(), "size_bytes": path.stat().st_size,
             "sha256": file_digest(path)} for path in sorted(tree.rglob("*")) if path.is_file()]
    manifest = assets / "files.jsonl"
    manifest.write_text("".join(json.dumps(row) + "\n" for row in rows))
    archives = {}
    for name in ("lean", "source"):
        archive = shared / f"{name}.tar.gz"
        with tarfile.open(archive, "w:gz") as stream:
            stream.add(tree / name, arcname=".")
        archives[name] = {"sha256": file_digest(archive), "size_bytes": archive.stat().st_size}
    node_runtime.write_json(assets / "archive-lock.json", archives)
    lock = {"files_manifest_sha256": file_digest(manifest), "file_count": len(rows),
        "total_bytes": sum(row["size_bytes"] for row in rows), "lean_version": "Lean pinned",
        "lean_toolchain": "leanprover/lean4:v4.27.0", "source_commit": "source-commit",
        "mathlib_revision": "mathlib-commit", "lake_manifest_sha256": file_digest(tree / "source/lake-manifest.json"),
        "source_archive_sha256": archives["source"]["sha256"], "source_archive_size_bytes": archives["source"]["size_bytes"]}
    node_runtime.write_json(assets / "runtime-lock.json", lock)
    monkeypatch.setattr(node_runtime, "choose_local_root", lambda required, explicit: (temporary, {"filesystem": "ext4", "free_bytes": 100000}))
    monkeypatch.setattr(subprocess, "check_output", lambda argv, **kwargs:
        "Lean pinned\n" if argv[-1] == "--version" else "mathlib-commit\n" if "mathlib" in argv[2] else "source-commit\n")
    original_run = subprocess.run
    def run(argv, **kwargs):
        if argv[0] == "tar":
            return original_run(argv, **kwargs)
        environment = Path(argv[argv.index("--cache") + 1])
        node_runtime.write_json(environment, {"root": argv[argv.index("--prepare") + 1]})
        return subprocess.CompletedProcess(argv, 0)
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setenv("SLURM_JOB_ID", "111")
    return shared, assets, output, temporary


def test_real_archive_stage_checks_every_file_and_copies_exact_lock(assets):
    shared, assets, output, temporary = assets
    profile = node_runtime.stage(shared, assets / "runtime-lock.json", assets / "files.jsonl", output)
    evidence = json.loads((output / "runtime-verification.json").read_text())
    assert evidence["verified"] and evidence["files_checked"] == 3
    assert (output / "runtime-lock.json").read_bytes() == (assets / "runtime-lock.json").read_bytes()
    assert profile["verified"] and Path(profile["source_root"]).exists()
    assert {phase["phase"] for phase in profile["phases"]} == {
        "verify_lean_archive", "extract_lean", "verify_source_archive", "extract_source",
        "verify_full_runtime", "prepare_lean_environment"}
    node_runtime.cleanup(Path(profile["runtime_root"]))
    assert not list(temporary.iterdir())


def test_archive_corruption_fails_before_consumer_and_cleans_owned_tree(assets):
    shared, assets, output, temporary = assets
    archive = shared / "source.tar.gz"
    content = bytearray(archive.read_bytes())
    content[-1] ^= 1
    archive.write_bytes(content)
    with pytest.raises(ValueError, match="archive differs"):
        node_runtime.stage(shared, assets / "runtime-lock.json", assets / "files.jsonl", output)
    profile = json.loads((output / "runtime-staging.json").read_text())
    assert not profile["verified"] and "archive differs" in profile["error"]
    assert not (output / "lean-environment.json").exists()
    assert not list(temporary.iterdir())
