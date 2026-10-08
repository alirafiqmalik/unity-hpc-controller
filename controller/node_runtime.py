"""Stage a pinned external runtime in an allocation-owned local directory."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

try:
    from .runtime_integrity import file_digest, verify_tree
except ImportError:
    from runtime_integrity import file_digest, verify_tree

MARKER = ".tracebench-runtime-owner.json"
LOCAL_FILESYSTEMS = {"ext4", "xfs", "btrfs", "zfs"}


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def local_capacity(path: Path, required: int) -> dict:
    if not path.is_dir() or not os.access(path, os.W_OK | os.X_OK):
        raise ValueError("temporary directory is absent or unwritable")
    rows = subprocess.check_output(["df", "-PT", str(path)], text=True, timeout=15).splitlines()
    fields = rows[-1].split()
    filesystem = fields[1]
    free = shutil.disk_usage(path).free
    if filesystem not in LOCAL_FILESYSTEMS:
        raise ValueError(f"temporary filesystem {filesystem} is not an approved disk filesystem")
    if free < required:
        raise ValueError("temporary filesystem has insufficient free capacity")
    return {"path": str(path.resolve()), "filesystem": filesystem, "device": fields[0],
            "free_bytes": free, "required_bytes": required}


def choose_local_root(required: int, explicit: Path | None = None) -> tuple[Path, dict]:
    candidates = [explicit] if explicit else [Path(value) for value in
        (os.environ.get("SLURM_TMPDIR"), os.environ.get("TMPDIR"), "/tmp", "/var/tmp") if value]
    failures, seen = [], set()
    for candidate in candidates:
        if str(candidate) in seen:
            continue
        seen.add(str(candidate))
        try:
            return candidate, local_capacity(candidate, required)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            failures.append({"path": str(candidate), "error": str(error)})
    raise ValueError(f"no suitable allocation-local disk directory: {failures}")


def cleanup(root: Path) -> None:
    if root.is_symlink() or not root.name.startswith("tracebench-runtime-") or not root.is_dir():
        raise ValueError("cleanup requires an owned runtime directory")
    if root.stat().st_uid != os.getuid():
        raise ValueError("runtime directory belongs to another user")
    marker = root / MARKER
    if marker.is_symlink() or not marker.is_file():
        raise ValueError("runtime ownership marker is absent or unsafe")
    owner = json.loads(marker.read_text())
    if owner.get("uid") != os.getuid() or owner.get("job_id") != os.environ.get("SLURM_JOB_ID"):
        raise ValueError("runtime ownership marker belongs to another allocation")
    if owner.get("runtime_root") != str(root.resolve()):
        raise ValueError("runtime ownership marker names another directory")
    shutil.rmtree(root)


def stage(shared: Path, lock_path: Path, manifest: Path, output: Path,
          *, workers: int = 1, temporary_parent: Path | None = None) -> dict:
    lock = json.loads(lock_path.read_text())
    archive_lock_path = lock_path.parent / "archive-lock.json"
    archives = json.loads(archive_lock_path.read_text())
    if file_digest(manifest) != lock["files_manifest_sha256"]:
        raise ValueError("runtime file manifest differs from its frozen lock")
    if archives["source"]["sha256"] != lock["source_archive_sha256"]:
        raise ValueError("source archive lock differs from the runtime lock")
    if archives["source"]["size_bytes"] != lock["source_archive_size_bytes"]:
        raise ValueError("source archive size differs from the runtime lock")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(lock_path, output / "runtime-lock.json")
    started = time.monotonic()
    parent, capacity = choose_local_root(int(lock["total_bytes"] * 1.2), temporary_parent)
    root = Path(tempfile.mkdtemp(prefix="tracebench-runtime-", dir=parent)).resolve()
    root.chmod(0o700)
    write_json(root / MARKER, {"uid": os.getuid(), "job_id": os.environ.get("SLURM_JOB_ID"),
                             "runtime_root": str(root)})
    profile = {"schema_version": 1, "runtime_root": str(root), "source_root": str(root / "source"),
               "lean_environment_path": str((output / "lean-environment.json").resolve()),
               "node": socket.gethostname(), "job_id": os.environ.get("SLURM_JOB_ID"),
               "capacity": capacity, "archives": archives, "phases": [], "verified": False}

    def phase(name, action):
        begin, cpu = time.monotonic(), time.process_time()
        print(json.dumps({"phase": name, "state": "started"}), flush=True)
        try:
            return action()
        finally:
            profile["phases"].append({"phase": name, "wall_seconds": round(time.monotonic() - begin, 3),
                "python_cpu_seconds": round(time.process_time() - cpu, 3)})
            write_json(output / "runtime-staging.json", profile)
            print(json.dumps(profile["phases"][-1]), flush=True)

    def check_archive(name):
        entry = archives[name]
        path = shared / f"{name}.tar.gz"
        if path.is_symlink() or path.stat().st_size != entry["size_bytes"] or file_digest(path) != entry["sha256"]:
            raise ValueError(f"{name} archive differs from its frozen digest or size")

    def unpack(name):
        destination = root / name
        destination.mkdir()
        # The archives are produced from the locked trees, and their exact bytes
        # are checked before GNU tar receives them. Full tree checks follow.
        subprocess.run(["tar", "-xzf", str(shared / f"{name}.tar.gz"), "--no-same-owner", "-C", str(destination)], check=True)

    try:
        for name in ("lean", "source"):
            phase(f"verify_{name}_archive", lambda name=name: check_archive(name))
            phase(f"extract_{name}", lambda name=name: unpack(name))
        evidence = phase("verify_full_runtime", lambda: verify_tree(root, manifest, lock["files_manifest_sha256"], workers=workers))
        checks = {}
        if evidence["verified"]:
            checks["lean_version"] = subprocess.check_output([str(root / "lean/bin/lean"), "--version"], text=True, timeout=30).strip()
            checks["source_commit"] = subprocess.check_output(["git", "-C", str(root / "source"), "rev-parse", "HEAD"], text=True, timeout=30).strip()
            checks["mathlib_revision"] = subprocess.check_output(["git", "-C", str(root / "source/.lake/packages/mathlib"), "rev-parse", "HEAD"], text=True, timeout=30).strip()
            checks["lean_toolchain"] = (root / "source/lean-toolchain").read_text().strip()
            checks["lake_manifest_sha256"] = file_digest(root / "source/lake-manifest.json")
        evidence["verified"] = (evidence["verified"] and all(checks[key] == lock[key] for key in checks)
            and len(checks) == 5 and evidence["files_checked"] == lock["file_count"]
            and evidence["total_bytes"] == lock["total_bytes"])
        evidence.update(checks=checks, expected=lock, node=socket.gethostname(), job_id=os.environ.get("SLURM_JOB_ID"))
        write_json(output / "runtime-verification.json", evidence)
        if not evidence["verified"]:
            raise ValueError("allocation-local runtime did not pass every frozen file and version check")
        environment = {**os.environ, "PATH": str(root / "lean/bin") + os.pathsep + os.environ.get("PATH", "")}
        phase("prepare_lean_environment", lambda: subprocess.run([sys.executable, str(lock_path.parent / "lean-launcher.py"),
            "--prepare", str(root / "source"), "--cache", str(output / "lean-environment.json"),
            "--lake", str(root / "lean/bin/lake")], env=environment, check=True, timeout=120))
        profile.update(verified=True, elapsed_seconds=round(time.monotonic() - started, 3),
                       runtime_lock_sha256=file_digest(lock_path), archive_lock_sha256=file_digest(archive_lock_path))
        write_json(output / "runtime-staging.json", profile)
        return profile
    except BaseException as error:
        profile.update(error=str(error), elapsed_seconds=round(time.monotonic() - started, 3))
        write_json(output / "runtime-staging.json", profile)
        cleanup(root)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cleanup-root", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--files", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--temp-root", type=Path)
    parser.add_argument("--workers", type=int, default=1, choices=range(1, 9))
    args = parser.parse_args()
    if args.cleanup_root:
        cleanup(args.cleanup_root)
        return 0
    if not all((args.runtime_root, args.lock, args.files, args.output)):
        parser.error("staging requires --runtime-root, --lock, --files, and --output")
    stage(args.runtime_root, args.lock, args.files, args.output, workers=args.workers, temporary_parent=args.temp_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
