import hashlib
import json

import pytest

from controller.runtime_integrity import file_digest, verify_tree


@pytest.mark.parametrize("workers", [1, 4])
def test_runtime_verification_detects_same_size_corruption_and_changed_symlink(tmp_path, workers):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    binary = runtime / "binary"
    binary.write_bytes(b"pinned binary")
    link = runtime / "launcher"
    link.symlink_to("binary")
    manifest = tmp_path / "files.jsonl"
    manifest.write_text("\n".join(json.dumps(row) for row in (
        {"path": "binary", "size_bytes": binary.stat().st_size, "sha256": file_digest(binary)},
        {"path": "launcher", "symlink": "binary"},
    )) + "\n")
    locked_digest = file_digest(manifest)
    assert verify_tree(runtime, manifest, locked_digest, workers=workers)["verified"]
    binary.write_bytes(b"alterd binary")
    link.unlink()
    link.symlink_to("elsewhere")
    evidence = verify_tree(runtime, manifest, locked_digest, workers=workers)
    assert not evidence["verified"]
    assert evidence["files_checked"] == 2
    assert {row["error"] for row in evidence["mismatches"]} == {"file digest mismatch", "symlink target mismatch"}


@pytest.mark.parametrize("workers", [1, 4])
def test_manifest_tampering_or_parent_traversal_never_reads_external_files(tmp_path, workers):
    manifest = tmp_path / "files.jsonl"
    manifest.write_text('{"path":"../secret","size_bytes":0,"sha256":"irrelevant"}\n')
    with pytest.raises(ValueError, match="manifest digest"):
        verify_tree(tmp_path, manifest, hashlib.sha256(b"different manifest").hexdigest(), workers=workers)
    with pytest.raises(ValueError, match="unsafe"):
        verify_tree(tmp_path, manifest, file_digest(manifest), workers=workers)


def test_parallel_checks_count_all_failures_and_keep_manifest_order(tmp_path):
    manifest = tmp_path / "files.jsonl"
    rows = [{"path": f"missing-{index}", "size_bytes": 1, "sha256": "unused"} for index in range(50)]
    manifest.write_text("".join(json.dumps(row) + "\n" for row in rows))
    serial = verify_tree(tmp_path, manifest, file_digest(manifest))
    parallel = verify_tree(tmp_path, manifest, file_digest(manifest), workers=4)
    assert not parallel["verified"]
    assert parallel["files_checked"] == parallel["mismatch_count"] == 50
    assert parallel["total_bytes"] == 50
    assert parallel["mismatches"] == serial["mismatches"]
    assert [failure["path"] for failure in parallel["mismatches"]] == [row["path"] for row in rows[:20]]


@pytest.mark.parametrize("workers", [True, 0, 9, 1.5])
def test_invalid_concurrency_fails_before_reading_manifest(tmp_path, workers):
    with pytest.raises(ValueError, match="workers"):
        verify_tree(tmp_path, tmp_path / "absent.jsonl", "unused", workers=workers)
