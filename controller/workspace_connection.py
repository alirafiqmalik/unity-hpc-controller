"""Versioned, project-owned declarations for deterministic experiment execution."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}$")
MAX_BYTES = 2 * 1024 * 1024


class ConnectionError(ValueError):
    pass


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def project_path(root: Path, value: str, *, exists: bool = False) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ConnectionError("path must be a nonempty project-relative path")
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ConnectionError(f"path escapes the project: {value}")
    if exists and not path.exists():
        raise ConnectionError(f"declared path does not exist: {value}")
    return path


def _error(errors, field, message):
    errors.append({"field": field, "message": str(message)})


def validate_connection(root: Path, manifest: dict) -> list[dict]:
    errors = []
    if isinstance(manifest, dict):
        from controller.workspace_composition import feature_errors
        errors.extend(feature_errors(manifest))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        return [{"field": "schema_version", "message": "project.json requires schema_version 1"}]
    for key in ("parameters", "operations", "workflows", "metrics"):
        if not isinstance(manifest.get(key, {}), dict):
            _error(errors, key, "must be an object keyed by stable IDs")
    if errors:
        return errors
    for key in ("source_paths", "checks"):
        if not isinstance(manifest.get(key, []), list):
            _error(errors, key, "must be a list")
    for key in ("inputs", "environment", "choice_readers", "analyses", "plots"):
        if not isinstance(manifest.get(key, {}), dict):
            _error(errors, key, "must be an object")
    if errors:
        return errors
    for path in manifest.get("source_paths", []):
        try:
            project_path(root, path, exists=True)
        except ConnectionError as exc:
            _error(errors, "source_paths", exc)
    if not manifest.get("source_paths"):
        _error(errors, "source_paths", "declare the complete project source and configuration closure")
    operations = manifest.get("operations", {})
    for key, operation in operations.items():
        field = f"operations.{key}"
        if not _ID.fullmatch(key) or not isinstance(operation, dict):
            _error(errors, field, "operation needs a stable ID and an object declaration")
            continue
        argv = operation.get("argv")
        if not isinstance(argv, list) or not argv or not isinstance(argv[0], str):
            _error(errors, field + ".argv", "nonempty argument vector with a literal executable is required")
            continue
        for argument in argv:
            if isinstance(argument, str):
                if "\x00" in argument:
                    _error(errors, field + ".argv", "arguments cannot contain NUL")
            elif not isinstance(argument, dict) or len(argument) != 1 or not set(argument) <= {"param", "context"}:
                _error(errors, field + ".argv", "bindings must be {param: name} or {context: name}")
        if operation.get("location") not in {"cluster", "controller"}:
            _error(errors, field + ".location", "declare cluster or controller execution")
        try:
            cwd = project_path(root, operation.get("cwd", "."), exists=True)
            if not cwd.is_dir():
                raise ConnectionError("working directory must be a directory")
            # Script arguments and Python module entrypoints must exist in the declared project.
            if len(argv) > 1 and isinstance(argv[1], str) and argv[1].endswith((".py", ".sh")):
                project_path(root, str(Path(operation.get("cwd", ".")) / argv[1]), exists=True)
            if len(argv) > 2 and argv[1] == "-m" and isinstance(argv[2], str):
                module = Path(*argv[2].split("."))
                if not (cwd / module.with_suffix(".py")).is_file() and not (cwd / module / "__main__.py").is_file():
                    raise ConnectionError(f"project module does not exist: {argv[2]}")
        except ConnectionError as exc:
            _error(errors, field, exc)
    for key, parameter in manifest.get("parameters", {}).items():
        if not isinstance(parameter, dict) or parameter.get("type") not in {"string", "integer", "number", "boolean"}:
            _error(errors, f"parameters.{key}", "declare string, integer, number, or boolean type")
    for key, workflow in manifest.get("workflows", {}).items():
        field = f"workflows.{key}"
        if not _ID.fullmatch(key) or not isinstance(workflow, dict) or not isinstance(workflow.get("stages"), list):
            _error(errors, field, "workflow needs stable ID and stages list")
            continue
        stages = workflow["stages"]
        ids = [stage.get("id") for stage in stages if isinstance(stage, dict)]
        if len(ids) != len(stages) or any(not isinstance(s, str) or not _ID.fullmatch(s) for s in ids) or len(set(ids)) != len(ids):
            _error(errors, field + ".stages", "stage IDs must be unique and stable")
            continue
        for parameter in workflow.get("parameters", []):
            if parameter not in manifest.get("parameters", {}):
                _error(errors, field + ".parameters", f"unknown parameter: {parameter}")
        for stage in stages:
            sf = field + ".stages." + stage["id"]
            if stage.get("operation") not in operations:
                _error(errors, sf, "unknown operation")
            if stage.get("purpose", "experiment") not in {"experiment", "smoke-test"}:
                _error(errors, sf + ".purpose", "declare experiment or smoke-test purpose")
            if stage.get("location", operations.get(stage.get("operation"), {}).get("location")) not in {"cluster", "controller"}:
                _error(errors, sf + ".location", "declare cluster or controller execution")
            if not isinstance(stage.get("depends_on", []), list) or not isinstance(stage.get("inputs", []), list) or not isinstance(stage.get("outputs", []), list):
                _error(errors, sf, "dependencies, inputs, and outputs must be lists")
                continue
            for binding in stage.get("inputs", []):
                if not isinstance(binding, dict) or binding.get("from_stage") not in stage.get("depends_on", []):
                    _error(errors, sf + ".inputs", "artifact inputs must name a declared dependency")
                    continue
                parent = next((item for item in stages if item["id"] == binding["from_stage"]), {})
                output = next((item for item in parent.get("outputs", []) if isinstance(item, dict) and item.get("id") == binding.get("output")), None)
                if output is None or any(binding.get(key) != output.get(key) for key in ("schema", "version")):
                    _error(errors, sf + ".inputs", "input schema/version must match the named dependency output")
            for dependency in stage.get("depends_on", []):
                if dependency not in ids or dependency == stage["id"]:
                    _error(errors, sf, f"invalid dependency: {dependency}")
            for output in stage.get("outputs", []):
                if not isinstance(output, dict) or not all(output.get(k) for k in ("id", "path", "schema", "version")):
                    _error(errors, sf + ".outputs", "outputs require id, path, schema, and version")
                    continue
                try:
                    project_path(root, output["path"])
                except ConnectionError as exc:
                    _error(errors, sf + ".outputs", exc)
        if errors:
            continue
        pending = {stage["id"]: set(stage.get("depends_on", [])) for stage in stages}
        while pending:
            ready = [key for key, deps in pending.items() if not deps.intersection(pending)]
            if not ready:
                _error(errors, field + ".stages", "stage dependencies contain a cycle")
                break
            for node in ready:
                del pending[node]
    return errors



def bounded_run(argv, *, cwd, timeout):
    """Bound command time, process groups, and captured output bytes."""
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(argv, cwd=cwd, stdout=stdout, stderr=stderr, start_new_session=True)
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(argv, timeout)
                if os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size > MAX_BYTES:
                    raise ConnectionError('Declared command output exceeds the 2 MiB limit')
                time.sleep(0.02)
            if os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size > MAX_BYTES:
                raise ConnectionError('Declared command output exceeds the 2 MiB limit')
            stdout.seek(0)
            stderr.seek(0)
            return subprocess.CompletedProcess(argv, process.returncode, stdout.read(MAX_BYTES).decode(errors='replace'), stderr.read(MAX_BYTES).decode(errors='replace'))
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            raise
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def load_connection(root: str | Path, *, resolve_choices: bool = True) -> dict:
    """Read declarations; choice readers are bounded, explicitly declared local commands."""
    root = Path(root).resolve()
    try:
        path = project_path(root, "unityHPC/project.json", exists=True)
        if path.stat().st_size > MAX_BYTES:
            raise ConnectionError("project.json exceeds 2 MiB")
        manifest = json.loads(path.read_text())
        errors = validate_connection(root, manifest)
    except (ConnectionError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return {"valid": False, "errors": [{"field": "connection", "message": str(exc)}], "manifest": None}
    raw_digest = digest(manifest)
    resolved = copy.deepcopy(manifest)
    if not errors and resolve_choices:
        for key, spec in resolved.get("parameters", {}).items():
            reader_id = spec.get("choices_reader")
            if not reader_id:
                continue
            reader = resolved.get("choice_readers", {}).get(reader_id)
            try:
                if not isinstance(reader, dict) or not isinstance(reader.get("argv"), list) or not all(isinstance(a, str) for a in reader["argv"]):
                    raise ConnectionError("choice reader requires a literal argument vector")
                result = bounded_run(reader["argv"], cwd=project_path(root, reader.get("cwd", "."), exists=True), timeout=min(max(reader.get("timeout_seconds", 10), 1), 30))
                result.check_returncode()
                choices = json.loads(result.stdout)
                if not isinstance(choices, list) or not choices or len(choices) > 10000:
                    raise ConnectionError("choice reader must return a nonempty JSON list (maximum 10000 choices)")
                spec["choices"] = choices
            except (ConnectionError, OSError, ValueError, subprocess.SubprocessError) as exc:
                _error(errors, f"parameters.{key}.choices", exc)
    return {"valid": not errors, "errors": errors, "manifest": resolved, "digest": raw_digest,
            "capabilities": {"workflows": list(resolved.get("workflows", {})), "analyses": list(resolved.get("analyses", {})), "plots": list(resolved.get("plots", {}))}}
