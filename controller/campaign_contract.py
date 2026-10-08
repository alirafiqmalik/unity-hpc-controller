"""Portable campaign declaration and immutable source snapshots.

Callers describe argument vectors and output files. Only the controller knows
SSH, Slurm, or remote paths. Validation and planning never submit work.
"""

from __future__ import annotations

import fnmatch
import hashlib
import io
import json
import os
import re
import tarfile
from pathlib import Path, PurePosixPath

ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$")
TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
ENV = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
BASE_EXCLUDES = (".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
                 ".env", ".env.*", ".ssh", "id_rsa", "id_ed25519", "id_ecdsa", "*.pyc", "*.pem", "*.key")
MAX_BUNDLE_BYTES = 256 * 1024 * 1024


class CampaignError(ValueError):
    status = 400


class Conflict(CampaignError):
    status = 409


def safe_id(value, label="identity"):
    if not isinstance(value, str) or not ID.fullmatch(value) or value in (".", ".."):
        raise CampaignError(f"{label} must contain letters, digits, '.', '_', or '-'")
    return value


def relative(value):
    if not isinstance(value, str) or not value or any(c in value for c in "\0\r\n"):
        raise CampaignError("output paths must be nonempty relative paths")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) == ".":
        raise CampaignError("output paths must stay inside the task output directory")
    return str(path)


def _positive(value, label, maximum, minimum=1):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise CampaignError(f"{label} must be an integer from {minimum} to {maximum}")
    return value


def validate(raw):
    if not isinstance(raw, dict) or type(raw.get("schema_version")) is not int or raw["schema_version"] != 1:
        raise CampaignError("campaign schema_version must be 1")
    value = json.loads(json.dumps(raw))
    safe_id(value.get("campaign_id"), "campaign_id")
    bundle = value.get("bundle")
    if not isinstance(bundle, dict) or not isinstance(bundle.get("path"), str) or not bundle["path"].strip():
        raise CampaignError("bundle.path must name a local source directory")
    source = Path(bundle["path"]).expanduser().resolve()
    if not source.is_dir():
        raise CampaignError("bundle.path must be an existing directory")
    bundle["path"] = str(source)
    exclude = bundle.setdefault("exclude", [])
    if not isinstance(exclude, list) or not all(isinstance(x, str) and x for x in exclude):
        raise CampaignError("bundle.exclude must be a list of patterns")
    tasks = value.get("tasks")
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 10000:
        raise CampaignError("tasks must contain 1 to 10000 tasks")
    seen, locks = set(), {}
    for task in tasks:
        if not isinstance(task, dict):
            raise CampaignError("each task must be an object")
        identity = safe_id(task.get("task_id"), "task_id")
        if identity in seen:
            raise CampaignError(f"duplicate task_id: {identity}")
        seen.add(identity)
        argv = task.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x and "\0" not in x for x in argv):
            raise CampaignError("task.argv must be a nonempty string argument vector")
        env = task.setdefault("env", {})
        if not isinstance(env, dict) or any(not ENV.fullmatch(k) or k.startswith("HPC_") or not isinstance(v, str) or "\0" in v for k, v in env.items()):
            raise CampaignError("task.env must map valid names to strings; HPC_ names are controller-owned")
        outputs = task.get("outputs")
        if not isinstance(outputs, list) or not outputs:
            raise CampaignError("task.outputs must declare at least one required file")
        task["outputs"] = [relative(x) for x in outputs]
        resources = task.setdefault("resources", {})
        if not isinstance(resources, dict):
            raise CampaignError("task.resources must be an object")
        for key, default, maximum, minimum in (("gpu_count", 0, 64, 0), ("cpus", 4, 1024, 1), ("memory_mb", 32768, 4194304, 1), ("walltime_seconds", 3600, 2592000, 1)):
            resources[key] = _positive(resources.get(key, default), key, maximum, minimum)
        partitions = resources.setdefault("partitions", [])
        if not isinstance(partitions, list) or not all(isinstance(p, str) and TOKEN.fullmatch(p) for p in partitions):
            raise CampaignError("resources.partitions must be a list of partition names")
        if resources.get("qos") is not None and (not isinstance(resources["qos"], str) or (resources["qos"] and not TOKEN.fullmatch(resources["qos"]))):
            raise CampaignError("resources.qos must be a Slurm QOS name")
        constraint = resources.setdefault("constraint", "")
        if not isinstance(constraint, str) or (constraint and not re.fullmatch(r"[A-Za-z0-9_.-]+(?:&[A-Za-z0-9_.-]+)*", constraint)):
            raise CampaignError("constraint supports exact features joined with '&'")
        if resources.get("nodelist") is not None and (not isinstance(resources["nodelist"], str) or (resources["nodelist"] and not re.fullmatch(r"[A-Za-z0-9_.\[\],-]+", resources["nodelist"]))):
            raise CampaignError("nodelist must be a Slurm node list")
        if resources.get("expected_gpu_uuid") is not None and (not isinstance(resources["expected_gpu_uuid"], str) or (resources["expected_gpu_uuid"] and not TOKEN.fullmatch(resources["expected_gpu_uuid"]))):
            raise CampaignError("expected_gpu_uuid must be a device identifier")
        if resources["gpu_count"]:
            safe_id(task.get("model_class"), "model_class")
            gpu_type = resources.get("gpu_type")
            if not isinstance(gpu_type, str) or not TOKEN.fullmatch(gpu_type):
                raise CampaignError("GPU tasks require an exact resources.gpu_type")
            expected = resources.get("expected_gpu_name")
            if not isinstance(expected, str) or not expected.strip() or any(c in expected for c in "\0\n\r"):
                raise CampaignError("GPU tasks require expected_gpu_name for in-job attestation")
            resources["expected_gpu_memory_mb"] = _positive(resources.get("expected_gpu_memory_mb"), "expected_gpu_memory_mb", 1048576)
            resources["gpu_memory_tolerance_mb"] = _positive(resources.get("gpu_memory_tolerance_mb", 1024), "gpu_memory_tolerance_mb", 2048, 0)
            fingerprint = hardware_fingerprint(resources)
            cls = task["model_class"]
            if cls in locks and locks[cls] != fingerprint:
                raise Conflict(f"model_class {cls} cannot use different hardware within a campaign")
            locks[cls] = fingerprint
        dependencies = task.setdefault("depends_on", [])
        if not isinstance(dependencies, list) or not all(isinstance(x, str) for x in dependencies):
            raise CampaignError("depends_on must be a list of task identities")
    graph = {t["task_id"]: t["depends_on"] for t in tasks}
    remaining, dependents = {}, {identity: [] for identity in graph}
    for identity, dependencies in graph.items():
        remaining[identity] = len(set(dependencies))
        for dep in set(dependencies):
            if dep not in graph:
                raise CampaignError(f"unknown dependency: {dep}")
            dependents[dep].append(identity)
    ready = [identity for identity, count in remaining.items() if not count]
    visited = 0
    while ready:
        visited += 1
        for identity in dependents[ready.pop()]:
            remaining[identity] -= 1
            if not remaining[identity]:
                ready.append(identity)
    if visited != len(graph):
        raise CampaignError("task dependencies contain a cycle")
    value["max_concurrent"] = _positive(value.get("max_concurrent", 4), "max_concurrent", 128)
    value["max_attempts"] = _positive(value.get("max_attempts", 2), "max_attempts", 10)
    return value


def hardware_fingerprint(resources):
    keys = ("gpu_type", "gpu_count", "constraint", "expected_gpu_name", "expected_gpu_memory_mb", "gpu_memory_tolerance_mb", "nodelist", "expected_gpu_uuid")
    return {key: resources.get(key) for key in keys}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def inventory(bundle):
    root = Path(bundle["path"])
    exclusions = (*BASE_EXCLUDES, *bundle.get("exclude", []))
    files, size = [], 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        base = Path(directory).relative_to(root)
        def excluded(name):
            path = str(base / name)
            return any(fnmatch.fnmatch(name, p) or fnmatch.fnmatch(path, p) for p in exclusions)
        dirs[:] = sorted(d for d in dirs if not excluded(d))
        for name in [*dirs, *sorted(names)]:
            path = Path(directory) / name
            if excluded(name):
                continue
            if path.is_symlink():
                raise CampaignError(f"bundle symlinks are unsupported: {path.relative_to(root)}")
            if path.is_file():
                data = path.read_bytes()
                size += len(data)
                if size > MAX_BUNDLE_BYTES:
                    raise CampaignError("bundle exceeds 256 MiB; exclude model caches and large results")
                files.append({"path": str(path.relative_to(root)), "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "mode": path.stat().st_mode & 0o777})
    if not files:
        raise CampaignError("bundle has no files after exclusions")
    return {"sha256": digest(files), "files": files, "size_bytes": size, "exclusions": list(exclusions)}


def snapshot(bundle, manifest, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination, "w:gz") as archive:
        for entry in manifest["files"]:
            path = Path(bundle["path"]) / entry["path"]
            data = path.read_bytes()
            if path.is_symlink() or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise Conflict("source changed during snapshot; retry the campaign request")
            info = tarfile.TarInfo(entry["path"])
            info.size, info.mode = len(data), entry["mode"]
            archive.addfile(info, io.BytesIO(data))
