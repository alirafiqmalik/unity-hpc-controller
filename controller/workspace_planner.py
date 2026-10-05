"""Compile immutable, inspectable plans without dispatching or scientific inference."""
from __future__ import annotations

import copy
import ast
import hashlib
import itertools
import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from controller.workspace_connection import ConnectionError, digest, load_connection, project_path, bounded_run


class PlanError(ValueError):
    def __init__(self, message, errors=None):
        super().__init__(message)
        self.errors = errors or [{"field": "plan", "message": message}]


def _manifest(connection):
    if "manifest" in connection:
        if not connection.get("valid"):
            raise PlanError("project connection is invalid", connection.get("errors"))
        return connection["manifest"]
    return connection


def _issue(errors, field, message, **scope):
    errors.append({"field": field, "message": message, **scope})


def _typed(value, spec):
    kind = spec.get("type")
    if kind == "integer":
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif kind == "number":
        valid = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif kind == "boolean":
        valid = isinstance(value, bool)
    else:
        valid = isinstance(value, str) and "\x00" not in value
    if not valid:
        return f"expected {kind}"
    if "choices" in spec and value not in spec["choices"]:
        return "value is not among the declared choices"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        import math
        if not math.isfinite(value):
            return "value must be finite"
        if "min" in spec and value < spec["min"]:
            return f"must be at least {spec['min']}"
        if "max" in spec and value > spec["max"]:
            return f"must be at most {spec['max']}"
    return None


def expand_variants(manifest, draft):
    workflow = manifest["workflows"].get(draft.get("workflow"))
    if not workflow:
        raise PlanError("choose a declared workflow", [{"field": "workflow", "message": "unknown workflow"}])
    allowed = workflow.get("parameters", list(manifest.get("parameters", {})))
    base = {key: copy.deepcopy(manifest["parameters"][key]["default"]) for key in allowed if "default" in manifest["parameters"][key]}
    base.update(workflow.get("defaults", {}))
    base.update(draft.get("parameters", {}))
    errors = []
    for key in base:
        if key not in allowed:
            _issue(errors, "parameters." + key, "parameter is not declared for this workflow")
    axes = draft.get("variant_parameters", {})
    for key, values in axes.items():
        if key not in allowed or not manifest["parameters"][key].get("variant_eligible", False):
            _issue(errors, "variant_parameters." + key, "field is not eligible for variant expansion")
        if not isinstance(values, list) or not values:
            _issue(errors, "variant_parameters." + key, "select at least one value")
    if errors:
        return [], errors
    combinations = draft.get("combinations")
    if combinations is None:
        keys = sorted(axes)
        size = 1
        for key in keys:
            size *= len(axes[key])
        if size > 10000:
            return [], [{"field": "variant_parameters", "message": "plan exceeds 10000 variants"}]
        combinations = [dict(zip(keys, values)) for values in itertools.product(*(axes[key] for key in keys))]
    if not isinstance(combinations, list) or not combinations or len(combinations) > 10000:
        return [], [{"field": "combinations", "message": "supply 1–10000 explicit combinations"}]
    variants, seen = [], set()
    excluded = set(draft.get("excluded_variants", []))
    for combination in combinations:
        if not isinstance(combination, dict):
            _issue(errors, "combinations", "each combination must be an object")
            continue
        parameters = {**base, **combination}
        variant_id = "v-" + digest(parameters)[:16]
        if variant_id in seen:
            _issue(errors, "combinations", "duplicate combination", variant_id=variant_id)
            continue
        seen.add(variant_id)
        variant = {"id": variant_id, "parameters": parameters, "excluded": variant_id in excluded}
        variants.append(variant)
        if variant["excluded"]:
            continue
        for key in combination:
            if key not in allowed or not manifest["parameters"][key].get("variant_eligible", False):
                _issue(errors, "combinations." + key, "field is not eligible for explicit combinations", variant_id=variant_id)
        for key in allowed:
            spec = manifest["parameters"][key]
            if key not in parameters:
                if spec.get("required", False):
                    _issue(errors, "parameters." + key, "required value is missing", variant_id=variant_id)
            elif problem := _typed(parameters[key], spec):
                _issue(errors, "parameters." + key, problem, variant_id=variant_id)
    for missing in excluded - seen:
        _issue(errors, "excluded_variants", "excluded variant does not exist: " + missing)
    if not any(not v["excluded"] for v in variants):
        _issue(errors, "variants", "at least one included variant is required")
    return variants, errors


def _resources(manifest, stage, operation, draft):
    manifest = {**manifest, **draft.get('defaults_snapshot', {})}
    location = stage.get("location", operation["location"])
    resources = {"primitive": "cpu" if location == "controller" else manifest.get("default_primitive", "gpu"),
                 "mode": "single" if location == "controller" else manifest.get("default_mode", "independent"),
                 "cpus": 1, "gpus": 0 if location == "controller" else 1, "nodes": 1, "ranks": 1,
                 "memory_gb": 4, "walltime": "00:30:00"}
    profiles = manifest.get('resource_defaults', {})
    resources.update(profiles.get(stage['id'], profiles.get('controller' if location == 'controller' else 'cluster', {})))
    resources.update(stage.get("resources", {}))
    resources.update(draft.get("resources", {}).get(stage["id"], {}))
    errors = []
    allowed = {"primitive", "mode", "cpus", "gpus", "nodes", "ranks", "memory_gb", "walltime", "partition", "gpu_type", "constraint", "account"}
    for key in resources.keys() - allowed:
        errors.append("unsupported resource field: " + key)
    for key in ("partition", "gpu_type", "constraint", "account"):
        if key in resources and (not isinstance(resources[key], str) or not re.fullmatch(r"[a-zA-Z0-9_.:,=&|*+!\[\]-]*", resources[key])):
            errors.append(key + " must be a single scheduler value without whitespace or control characters")
    primitive, mode = resources["primitive"], resources["mode"]
    if primitive not in {"cpu", "gpu", "multi-cpu", "multi-gpu"}:
        errors.append("primitive must be cpu, gpu, multi-cpu, or multi-gpu")
    if mode not in {"single", "independent", "coordinated"}:
        errors.append("mode must be single, independent, or coordinated")
    for key in ("cpus", "nodes", "ranks", "memory_gb", "gpus"):
        value = resources[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < (0 if key == "gpus" else 1):
            errors.append(key + " must be a valid positive integer" if key != "gpus" else "gpus must be a nonnegative integer")
    if primitive in {"cpu", "multi-cpu"} and resources["gpus"] != 0:
        errors.append("CPU stages cannot request GPUs")
    if primitive in {"gpu", "multi-gpu"} and resources["gpus"] == 0:
        errors.append("GPU stages must request GPUs")
    if location == "controller" and (primitive != "cpu" or resources["nodes"] != 1):
        errors.append("controller-host stages require a single CPU node")
    if mode == "coordinated" and (primitive not in {"multi-gpu", "multi-cpu"} or operation.get("launcher") != "srun"):
        errors.append("coordinated stages require a multi primitive and explicit operation launcher=srun")
    if mode != "coordinated" and (resources["nodes"] != 1 or resources["ranks"] != 1):
        errors.append("nodes and ranks greater than one require coordinated mode")
    if not isinstance(resources["walltime"], str) or not re.fullmatch(r"(?:\d+-)?\d{1,3}:\d{2}:\d{2}", resources["walltime"]):
        errors.append("walltime must use [days-]hours:minutes:seconds")
    elif any(int(part) > 59 for part in resources["walltime"].split(":")[-2:]):
        errors.append("walltime minutes and seconds must be from 00 to 59")
    return resources, errors


def _selected_stages(manifest, draft):
    workflow = manifest["workflows"][draft["workflow"]]
    stages = {stage["id"]: stage for stage in workflow["stages"]}
    selected = set(draft.get("stages", [key for key, stage in stages.items() if not stage.get("optional") and stage.get("purpose") != "smoke-test"]))
    unknown = selected - stages.keys()
    if unknown:
        raise PlanError("unknown stage selection: " + ", ".join(sorted(unknown)))
    if draft.get("include_smoke_test") or (workflow.get("smoke_test_required") and draft.get("prerequisites", "add") != "existing"):
        selected.update(key for key, stage in stages.items() if stage.get("purpose") == "smoke-test")
    selected.update(draft.get("collection_stages", []))
    if selected - stages.keys():
        raise PlanError("unknown collection stage")
    if draft.get("prerequisites", "add") == "add":
        pending = list(selected)
        while pending:
            stage = stages[pending.pop()]
            for dep in stage.get("depends_on", []):
                if dep not in selected:
                    if stages[dep].get("purpose") == "smoke-test" and not (draft.get("include_smoke_test") or workflow.get("smoke_test_required")):
                        continue
                    selected.add(dep)
                    pending.append(dep)
    # Topological declaration order, including declarations which were not originally sorted.
    ordered = []
    while selected:
        ready = [stage for key, stage in stages.items() if key in selected and not set(stage.get("depends_on", [])).intersection(selected)]
        if not ready:
            raise PlanError("stage dependencies contain a cycle")
        ordered.extend(ready)
        selected.difference_update(stage["id"] for stage in ready)
    return ordered


def _artifact_for(draft, artifacts, stage_id, variant):
    reference = draft.get("existing_artifacts", {}).get(variant["id"] + ":" + stage_id, draft.get("existing_artifacts", {}).get(stage_id))
    if isinstance(reference, dict):
        # Only index records are trusted, never client-provided completeness assertions.
        reference = reference.get("id")
    return next((item for item in artifacts if item.get("id") == reference), None)



def _metric_ids(manifest, draft):
    defaults = manifest["workflows"][draft["workflow"]].get("metrics", [])
    return draft.get("metrics", [key for key in defaults if not manifest.get("metrics", {}).get(key, {}).get("optional")])



def _measurements(manifest, draft):
    return [{"id": key, **copy.deepcopy(manifest["metrics"][key]),
             "aggregation": draft.get("aggregations", {}).get(key, manifest["metrics"][key].get("aggregation", (manifest["metrics"][key].get("aggregations") or ["none"])[0]))}
            for key in _metric_ids(manifest, draft)]


def _artifact_directory(root, artifact):
    if artifact.get('frozen_path'):
        relative = artifact['frozen_path']
        return relative if project_path(Path(root), relative, exists=True).is_dir() else str(Path(relative).parent)
    return artifact.get('output_dir', str(Path(artifact['path']).parent))


def _verify_artifacts(root, artifacts):
    errors = []
    for artifact in artifacts:
        if not artifact.get("files"):
            _issue(errors, "artifacts." + artifact["id"], "artifact lacks checked file identities")
        if artifact.get("path"):
            try:
                artifact_path = project_path(Path(root), artifact.get("frozen_path", artifact["path"]), exists=True)
                if artifact_path.is_dir():
                    expected = {item.get("frozen_path", item["path"]) for item in artifact.get("files", [])}
                    observed = set()
                    for candidate in artifact_path.rglob("*"):
                        if candidate.is_symlink() and not candidate.resolve().is_relative_to(artifact_path):
                            _issue(errors, "artifacts." + artifact["id"], "artifact symlink escapes its indexed directory")
                        if candidate.is_file():
                            observed.add(candidate.relative_to(Path(root)).as_posix())
                    if observed != expected:
                        _issue(errors, "artifacts." + artifact["id"], "artifact directory file set changed since indexing")
            except (ConnectionError, OSError, KeyError) as exc:
                _issue(errors, "artifacts." + artifact["id"], str(exc))
        for item in artifact.get("files", []):
            try:
                path = project_path(Path(root), item.get("frozen_path", item["path"]), exists=True)
                if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                    _issue(errors, "artifacts." + artifact["id"], "saved artifact changed: " + item["path"])
            except (ConnectionError, OSError, KeyError) as exc:
                _issue(errors, "artifacts." + artifact["id"], str(exc))
    return errors


def check_configuration(root, connection, draft, artifacts=None, *, run_checks=False):
    root = Path(root).resolve()
    artifacts = artifacts or []
    try:
        manifest = _manifest(connection)
        from controller.workspace_composition import prepare
        manifest, draft, composition_errors = prepare(manifest, draft, artifacts)
        if composition_errors:
            return {"valid": False, "errors": composition_errors, "variants": [], "checks": []}
        variants, errors = expand_variants(manifest, draft)
        selected = _selected_stages(manifest, draft)
    except (PlanError, KeyError, TypeError, ValueError) as exc:
        return {"valid": False, "errors": getattr(exc, "errors", [{"field": "draft", "message": str(exc)}]), "variants": [], "checks": []}
    concurrency = draft.get("variant_concurrency", 1)
    if not isinstance(concurrency, int) or isinstance(concurrency, bool) or not 1 <= concurrency <= 10000:
        _issue(errors, "variant_concurrency", "concurrency must be an integer from 1 to 10000")
    selected_ids = {s["id"] for s in selected}
    stages_by_id = {s["id"]: s for s in manifest["workflows"][draft["workflow"]]["stages"]}
    if not selected:
        _issue(errors, "stages", "select at least one stage")
    for stage in selected:
        operation = manifest["operations"][stage["operation"]]
        if stage.get("scope") in ("shared", "reduce_selected"):
            varied = {key for key in manifest.get("parameters", {}) if len({digest(v["parameters"].get(key)) for v in variants if not v["excluded"]}) > 1}
            bound = {arg["param"] for arg in operation["argv"] if isinstance(arg, dict) and "param" in arg}
            for key in (varied & bound) - stage.get("parameters", {}).keys():
                _issue(errors, "stages." + stage["id"], "shared stage cannot bind varying parameter without an explicit stage value: " + key)
        _, problems = _resources(manifest, stage, operation, draft)
        for problem in problems:
            _issue(errors, "resources." + stage["id"], problem, stage_id=stage["id"])
        for variant in variants:
            if variant["excluded"]:
                continue
            effective_parameters = {**variant["parameters"], **stage.get("parameters", {})}
            for parameter, value in effective_parameters.items():
                allowed = manifest.get("parameters", {}).get(parameter, {}).get("allowed_purposes")
                if allowed and value and stage.get("purpose", "experiment") not in allowed:
                    _issue(errors, "parameters." + parameter, "value is not permitted for this stage purpose", stage_id=stage["id"], variant_id=variant["id"])
        for dependency in stage.get("depends_on", []):
            if dependency in selected_ids:
                if stage.get("scope") == "shared" and stages_by_id[dependency].get("scope") != "shared":
                    _issue(errors, "stages", "shared stages may depend only on shared stages", stage_id=stage["id"])
                continue
            parent = stages_by_id[dependency]
            has_gate_reference = any(key == dependency or key.endswith(":" + dependency) for key in draft.get("existing_artifacts", {}))
            if parent.get("purpose") == "smoke-test" and not manifest["workflows"][draft["workflow"]].get("smoke_test_required") and not has_gate_reference:
                continue
            for variant in variants:
                if variant["excluded"]:
                    continue
                artifact = _artifact_for(draft, artifacts, dependency, variant)
                if artifact is None:
                    _issue(errors, "existing_artifacts." + dependency, "select a completed prerequisite artifact or add prerequisite stages", stage_id=stage["id"], variant_id=variant["id"])
                    continue
                smoke_gate = parent.get("purpose") == "smoke-test" and not any(binding.get("from_stage") == dependency for binding in stage.get("inputs", []))
                if smoke_gate:
                    if not artifact.get("complete") or artifact.get("purpose") != "smoke-test" or not (artifact.get("stage_state") == "completed" or artifact.get("scheduler_state") == "COMPLETED"):
                        _issue(errors, "existing_artifacts." + dependency, "smoke gate requires complete evidence from a successfully completed smoke stage", variant_id=variant["id"])
                elif not artifact.get("complete") or artifact.get("purpose") == "smoke-test":
                    _issue(errors, "existing_artifacts." + dependency, "prerequisite must be complete and cannot be smoke-test evidence", variant_id=variant["id"])
                if not artifact.get("execution_id") or not artifact.get("source_digest"):
                    _issue(errors, "existing_artifacts." + dependency, "prerequisite lacks execution/source provenance", variant_id=variant["id"])
                for binding in stage.get("inputs", []):
                    if binding.get("from_stage") == dependency and any(binding.get(k) is not None and binding[k] != artifact.get(k) for k in ("schema", "version")):
                        _issue(errors, "existing_artifacts." + dependency, "artifact schema or version is incompatible", variant_id=variant["id"])
                errors.extend(_verify_artifacts(root, [artifact]))
                compatible = manifest.get("resume", {}).get("compatibility_parameters", [])
                for key in compatible:
                    if artifact.get("parameters", {}).get(key) != variant["parameters"].get(key):
                        _issue(errors, "existing_artifacts." + dependency, "artifact parameter differs: " + key, variant_id=variant["id"])
    metrics = _metric_ids(manifest, draft)
    for metric_id in metrics:
        metric = manifest.get("metrics", {}).get(metric_id)
        if metric is None:
            _issue(errors, "metrics", "unknown declared metric: " + str(metric_id))
            continue
        aggregation = draft.get("aggregations", {}).get(metric_id)
        if aggregation is not None and aggregation not in metric.get("aggregations", [metric.get("aggregation", "none")]):
            _issue(errors, "aggregations." + metric_id, "select a declared supported aggregation")
        for stage in metric.get("collection_stages", []):
            if stage not in draft.get("collection_stages", []):
                _issue(errors, "metrics." + metric_id, "additional collection requires explicit selection: " + stage)
    selected_refs = {value if isinstance(value, str) else value.get("id") for value in [*draft.get("existing_artifacts", {}).values(), *draft.get("resume_artifacts", {}).values()]}
    for variant in variants:
        if variant["excluded"]:
            continue
        for stage in selected:
            reference = draft.get("resume_artifacts", {}).get(variant["id"] + ":" + stage["id"])
            if not reference:
                continue
            artifact = next((item for item in artifacts if item["id"] == reference), None)
            resume_operation = manifest.get("resume", {}).get("operations", {}).get(stage["operation"])
            if not artifact or not resume_operation or resume_operation not in manifest.get("operations", {}):
                _issue(errors, "resume_artifacts", "checkpoint requires a declared resume operation and indexed artifact", variant_id=variant["id"], stage_id=stage["id"])
                continue
            if artifact.get("source_digest") is None or artifact.get("execution_id") is None:
                _issue(errors, "resume_artifacts", "checkpoint lacks source/execution provenance", variant_id=variant["id"])
            for key in manifest.get("resume", {}).get("compatibility_parameters", []):
                if artifact.get("parameters", {}).get(key) != variant["parameters"].get(key):
                    _issue(errors, "resume_artifacts", "checkpoint parameter differs: " + key, variant_id=variant["id"])

    errors.extend(_verify_artifacts(root, [artifact for artifact in artifacts if artifact.get("id") in selected_refs]))
    if selected_refs - {artifact.get("id") for artifact in artifacts}:
        _issue(errors, "existing_artifacts", "selected artifact is not present in this project's index")
    checks = []
    if run_checks and not errors:
        for check in manifest.get("checks", []):
            operation = manifest["operations"].get(check.get("operation"), {})
            if operation.get("location") != "controller":
                _issue(errors, "checks", "bounded setup checks must run on the controller host")
                continue
            context = {"project_root": str(root), "source_root": str(root)}
            try:
                argv = bind_argv(operation, check.get("parameters", {}), context)
                result = bounded_run(argv, cwd=project_path(root, operation.get("cwd", ".")),
                                     timeout=min(max(check.get("timeout_seconds", 30), 1), 120))
                checks.append({"id": check["id"], "passed": result.returncode == 0, "output": (result.stdout + result.stderr)[-16000:], "location": "controller"})
                if result.returncode:
                    _issue(errors, "checks." + check["id"], "declared check failed; inspect its output")
            except (OSError, subprocess.SubprocessError, PlanError) as exc:
                checks.append({"id": check["id"], "passed": False, "output": str(exc), "location": "controller"})
                _issue(errors, "checks." + check["id"], str(exc))
    if run_checks and not errors:
        workflow = manifest["workflows"][draft["workflow"]]
        preflights = workflow.get("preflight_operations", [])
        if workflow.get("preflight_operation"):
            preflights = [*preflights, workflow["preflight_operation"]]
        for operation_id in preflights:
            operation = manifest.get("operations", {}).get(operation_id, {})
            if operation.get("location") != "controller":
                _issue(errors, "preflight", "preflight operations must run on the controller host")
                continue
            for variant in variants:
                if variant["excluded"]:
                    continue
                purpose = "smoke-test" if all(stage.get("purpose") == "smoke-test" for stage in selected) else "experiment"
                context = {"project_root": str(root), "source_root": str(root), "purpose": purpose}
                try:
                    result = bounded_run(bind_argv(operation, variant["parameters"], context), cwd=project_path(root, operation.get("cwd", ".")), timeout=min(max(operation.get("timeout_seconds", 30), 1), 120))
                    checks.append({"id": operation_id, "variant_id": variant["id"], "passed": result.returncode == 0, "output": (result.stdout + result.stderr)[-16000:], "location": "controller"})
                    if result.returncode:
                        _issue(errors, "preflight." + operation_id, "declared input/runtime readiness check failed; inspect its output", variant_id=variant["id"])
                except (OSError, subprocess.SubprocessError, PlanError) as exc:
                    _issue(errors, "preflight." + operation_id, str(exc), variant_id=variant["id"])
    return {"valid": not errors, "errors": errors, "variants": variants, "checks": checks}


def bind_argv(operation, parameters, context):
    argv = []
    for argument in operation["argv"]:
        if isinstance(argument, str):
            argv.append(argument)
        else:
            source, key = next(iter(argument.items()))
            values = parameters if source == "param" else context
            if key not in values:
                raise PlanError("missing argument binding: " + source + ":" + key)
            value = values[key]
            argv.append(str(value).lower() if isinstance(value, bool) else str(value))
    return argv


def source_inventory(root, manifest):
    root = Path(root).resolve()
    paths = set()
    for declaration in [*manifest.get("source_paths", []), "unityHPC/project.json"]:
        path = project_path(root, declaration, exists=True)
        candidates = path.rglob("*") if path.is_dir() else [path]
        for candidate in candidates:
            if any(part in {".git", "__pycache__", ".unity-workspace", ".venv", "node_modules"} for part in candidate.relative_to(root).parts):
                continue
            if candidate.is_file():
                if not candidate.resolve().is_relative_to(root):
                    raise PlanError("source symlink escapes project: " + str(candidate))
                paths.add(candidate.relative_to(root).as_posix())
    # Close ordinary Python imports over project files. Dynamic imports and runtime
    # data still belong in source_paths: this does not infer scientific behavior.
    for operation in manifest.get("operations", {}).values():
        argv = operation.get("argv", [])
        cwd = Path(operation.get("cwd", "."))
        if len(argv) > 1 and isinstance(argv[1], str) and argv[1].endswith((".py", ".sh")):
            paths.add((cwd / argv[1]).as_posix())
        if len(argv) > 2 and argv[1] == "-m" and isinstance(argv[2], str):
            module = cwd / Path(*argv[2].split("."))
            candidate = module.with_suffix(".py") if (root / module.with_suffix(".py")).is_file() else module / "__main__.py"
            paths.add(candidate.as_posix())
    pending = list(paths)
    checked = set()
    while pending:
        name = pending.pop()
        if name in checked or not name.endswith(".py"):
            continue
        checked.add(name)
        path = project_path(root, name, exists=True)
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeError) as exc:
            raise PlanError("cannot inspect Python source closure: " + name) from exc
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend((alias.name, 0) for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append((node.module or "", node.level))
                imports.extend(((node.module + "." if node.module else "") + alias.name, node.level) for alias in node.names if alias.name != "*")
        for module, level in imports:
            bases = [path.parent, root]
            if level:
                base = path.parent
                for _ in range(level - 1):
                    base = base.parent
                bases = [base]
            for base in bases:
                module_path = base.joinpath(*module.split(".")) if module else base
                candidates = [module_path.with_suffix(".py"), module_path / "__init__.py"]
                parent = module_path.parent
                while parent.is_relative_to(root) and parent != root:
                    candidates.append(parent / "__init__.py")
                    parent = parent.parent
                for candidate in candidates:
                    if candidate.is_file() and candidate.is_relative_to(root):
                        candidate = project_path(root, candidate.relative_to(root).as_posix(), exists=True)
                        relative = candidate.relative_to(root).as_posix()
                        if relative not in paths:
                            paths.add(relative)
                            pending.append(relative)
    for name in (".env", "unityHPC/.env", "unityHPC/run.sh", "unityHPC/job_template.sh", "unityHPC/bootstrap.sh"):
        if (root / name).is_file():
            paths.add(name)
    secret_paths = set(manifest.get("environment", {}).get("secret_paths", []))
    for name in secret_paths:
        if project_path(root, name).is_file():
            paths.add(name)
    files = []
    for name in sorted(paths):
        path = project_path(root, name, exists=True)
        redacted = name in secret_paths or path.name == ".env" or path.name.startswith(".env.")
        files.append({"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size, "redacted": redacted, "mode": path.stat().st_mode & 0o777})
    return {"digest": digest(files), "files": files}


def input_inventory(root, manifest):
    records = []
    for key, spec in manifest.get("inputs", {}).items():
        item = {"id": key, **spec}
        path = project_path(Path(root), spec["path"], exists=True)
        if path.is_file():
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if spec.get("sha256") and actual != spec["sha256"]:
                raise PlanError("input checksum differs: " + key)
            item["sha256"] = actual
        elif not (spec.get("version") and spec.get("immutable") is True):
            raise PlanError("large input directories require an immutable version: " + key)
        if not spec.get("immutable"):
            raise PlanError("input must declare an immutable reference: " + key)
        records.append(item)
    return records


def _wrapper(root, plan_id, stage, inputs=()):
    # JSON data is embedded as a Python literal; shell interpolation never touches argv.
    payload = {"argv": stage["argv"], "cwd": stage["cwd"], "output_dir": stage["output_dir"],
               "plan_id": plan_id, "variant_id": stage["variant_id"], "stage_id": stage["stage_id"], "purpose": stage["purpose"], "inputs": list(inputs)}
    return "\n".join([
        "#!/usr/bin/env bash", "set -euo pipefail",
        "export UNITY_PROJECT_ROOT=\"${UNITY_PROJECT_ROOT:-${REMOTE_DIR:-" + str(root).replace('"', '\\"').replace('$', '\\$').replace('`', '\\`') + "}}\"",
        "python3 - <<'UNITY_WORKSPACE_PY'", "import hashlib, json, os, pathlib, subprocess, sys", "p = " + repr(payload),
        "root = pathlib.Path(os.environ['UNITY_PROJECT_ROOT']).resolve()",
        "source = root / '.unity-workspace' / 'plans' / p['plan_id'] / 'source'",
        "def expand(value): return value.replace('__UNITY_PROJECT_ROOT__', str(root)).replace('__UNITY_SOURCE_ROOT__', str(source))",
        "for item in p['inputs']:",
        "    if item.get('sha256') and hashlib.sha256((root / item['path']).read_bytes()).hexdigest() != item['sha256']: raise SystemExit('Immutable input changed: ' + item['id'])",
        "output = root / p['output_dir']", "output.mkdir(parents=True, exist_ok=True)",
        "os.environ.update(UNITY_EXECUTION_ID=p['plan_id'], UNITY_VARIANT_ID=p['variant_id'], UNITY_STAGE_ID=p['stage_id'], UNITY_PURPOSE=p['purpose'], UNITY_OUTPUT_DIR=str(output), UNITY_SOURCE_ROOT=str(source))",
        "purpose_label = 'Smoke test' if p['purpose'] == 'smoke-test' else 'Experiment'",
        "print('Purpose: ' + purpose_label + ' | Execution: ' + p['plan_id'] + ' | Variant: ' + p['variant_id'] + ' | Stage: ' + p['stage_id'], flush=True)",
        "sys.exit(subprocess.call([expand(a) for a in p['argv']], cwd=source / p['cwd']))",
        "UNITY_WORKSPACE_PY", ""])


def compile_plan(root, connection, draft, plan_id, snapshot_dir=None, artifacts=None):
    root = Path(root).resolve()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}", plan_id):
        raise PlanError("plan ID must be safe for paths and scheduler names")
    manifest = _manifest(connection)
    from controller.workspace_composition import prepare
    manifest, draft, composition_errors = prepare(manifest, draft, artifacts)
    if composition_errors:
        raise PlanError("composition is not ready", composition_errors)
    checked = check_configuration(root, connection, draft, artifacts, run_checks=True)
    if not checked["valid"]:
        raise PlanError("configuration is not ready", checked["errors"])
    if digest(json.loads((root / "unityHPC/project.json").read_text())) != connection.get("digest", digest(manifest)):
        raise PlanError("connection changed during checking; reload and review again")
    source = source_inventory(root, manifest)
    inputs = input_inventory(root, manifest)
    selected = _selected_stages(manifest, draft)
    stage_declarations = {s["id"]: s for s in selected}
    stages = []
    seen_shared = set()
    for variant in checked["variants"]:
        if variant["excluded"]:
            continue
        for declaration in selected:
            key = declaration["id"]
            shared = declaration.get("scope") in ("shared", "reduce_selected")
            if shared and key in seen_shared:
                continue
            if shared:
                seen_shared.add(key)
            variant_id = "shared" if shared else variant["id"]
            stage_id = variant_id + "--" + key
            output_dir = f".unity-workspace/outputs/{plan_id}/{variant_id}/{key}"
            context = {"project_root": "__UNITY_PROJECT_ROOT__", "source_root": "__UNITY_SOURCE_ROOT__",
                       "execution_id": plan_id, "variant_id": variant_id, "stage_id": key,
                       "output_dir": "__UNITY_PROJECT_ROOT__/" + output_dir, "relative_output_dir": output_dir,
                       "purpose": declaration.get("purpose", "experiment"),
                       "measurements": json.dumps(_measurements(manifest, draft), sort_keys=True)}
            dependencies = []
            parent_dirs = []
            input_parents = {binding["from_stage"] for binding in declaration.get("inputs", [])}
            for parent_id in declaration.get("depends_on", []):
                if parent_id in stage_declarations:
                    parent = stage_declarations[parent_id]
                    parent_variants = ["shared"] if parent.get("scope") in ("shared", "reduce_selected") else ([v["id"] for v in checked["variants"] if not v["excluded"]] if declaration.get("scope") == "reduce_selected" else [variant_id])
                    for parent_variant in parent_variants:
                        dependencies.append(parent_variant + "--" + parent_id)
                        parent_dir = f".unity-workspace/outputs/{plan_id}/{parent_variant}/{parent_id}"
                        if parent_id in input_parents:
                            context.setdefault("parent_dir", "__UNITY_PROJECT_ROOT__/" + parent_dir)
                            parent_dirs.append("__UNITY_PROJECT_ROOT__/" + parent_dir)
                        for output in parent.get("outputs", []):
                            context[f"parent:{parent_id}:{output['id']}"] = "__UNITY_PROJECT_ROOT__/" + parent_dir + "/" + output["path"]
                else:
                    artifact = _artifact_for(draft, artifacts or [], parent_id, variant)
                    if artifact:
                        project_path(root, artifact.get("frozen_path", artifact["path"]), exists=True)
                        artifact_dir = "__UNITY_PROJECT_ROOT__/" + _artifact_directory(root, artifact)
                        if parent_id in input_parents:
                            context.setdefault("parent_dir", artifact_dir)
                            parent_dirs.append(artifact_dir)
                        context[f"parent:{parent_id}:{artifact.get('output_id', artifact.get('id'))}"] = "__UNITY_PROJECT_ROOT__/" + artifact.get("frozen_path", artifact["path"])
            port_values = {}
            for binding in declaration.get("artifact_inputs", []):
                artifact = next(a for a in artifacts or [] if a['id'] == binding['artifact_id'])
                project_path(root, artifact.get('frozen_path', artifact['path']), exists=True)
                artifact_dir = "__UNITY_PROJECT_ROOT__/" + _artifact_directory(root, artifact)
                parent_dirs.append(artifact_dir)
                context.setdefault('parent_dir', artifact_dir)
                port_values.setdefault(binding['input'], []).append("__UNITY_PROJECT_ROOT__/" + artifact.get('frozen_path', artifact['path']))
            for binding in declaration.get('inputs', []):
                port = binding.get('input_port')
                if not port:
                    continue
                parent = stage_declarations[binding['from_stage']]
                output = next(o for o in parent['outputs'] if o['id'] == binding['output'])
                parent_variants = ['shared'] if parent.get('scope') in ('shared', 'reduce_selected') else ([v['id'] for v in checked['variants'] if not v['excluded']] if declaration.get('scope') == 'reduce_selected' else [variant_id])
                values = [f"__UNITY_PROJECT_ROOT__/.unity-workspace/outputs/{plan_id}/{pv}/{parent['id']}/{output['path']}" for pv in parent_variants]
                port_values.setdefault(port, []).extend(values)
            for port, values in port_values.items():
                many = manifest['operations'][declaration['operation']].get('input_ports', {}).get(port, {}).get('cardinality') == 'many'
                context['input:' + port] = json.dumps(values) if many else values[0]
            context["analysis_input_dirs"] = json.dumps(parent_dirs)
            operation_id = declaration["operation"]
            checkpoint_id = draft.get("resume_artifacts", {}).get(variant_id + ":" + key)
            if checkpoint_id:
                checkpoint = next(item for item in artifacts or [] if item["id"] == checkpoint_id)
                context["checkpoint_dir"] = "__UNITY_PROJECT_ROOT__/" + _artifact_directory(root, checkpoint)
                operation_id = manifest["resume"]["operations"][operation_id]
            operation = manifest["operations"][operation_id]
            parameters = {**variant["parameters"], **declaration.get("parameters", {})}
            for metric_id, metric in manifest.get("metrics", {}).items():
                if metric.get("parameter") in parameters:
                    parameters[metric["parameter"]] = metric_id in _metric_ids(manifest, draft)
            argv = bind_argv(operation, parameters, context)
            resources, _ = _resources(manifest, declaration, operation, draft)
            if resources["mode"] == "coordinated":
                argv = ["srun", "--nodes", str(resources["nodes"]), "--ntasks", str(resources["ranks"]), *argv]
            outputs = [{**copy.deepcopy(output), "path": output_dir + "/" + output["path"], "required": output.get("required", True)} for output in declaration.get("outputs", [])]
            stage = {"id": stage_id, "stage_id": key, "variant_id": variant_id, "operation": operation_id, "resume_from": checkpoint_id,
                     "operation_version": operation.get("version", "1"), "parameters": parameters, "depends_on": dependencies,
                     "argv": argv, "command": shlex.join(argv), "cwd": operation.get("cwd", "."), "resources": resources,
                     "location": declaration.get("location", operation["location"]), "timeout_seconds": operation.get("timeout_seconds", 120), "purpose": declaration.get("purpose", "experiment"), "output_dir": output_dir,
                     "outputs": outputs, "script_path": f".unity-workspace/plans/{plan_id}/scripts/{stage_id}.sh"}
            for field in ("check_operation", "fetch_operation", "timeout_seconds", "completion", "scope", "artifact_inputs", "inputs"):
                if field in declaration:
                    stage[field] = copy.deepcopy(declaration[field])
            stage["script"] = _wrapper(root, plan_id, stage, inputs)
            stages.append(stage)
    connection_digest = connection.get("digest", digest(manifest))
    plan = {"schema_version": 1, "id": plan_id, "valid": True, "workflow": draft["workflow"], "config": copy.deepcopy(draft),
            "draft_digest": digest(draft), "connection_digest": connection_digest, "source": source, "inputs": inputs,
            "variants": checked["variants"], "stages": stages, "checks": checked["checks"],
            "metrics": _measurements(manifest, draft),
            "excluded_variants": draft.get("excluded_variants", []), "variant_concurrency": draft.get("variant_concurrency", 1),
            "artifacts": [copy.deepcopy(a) for a in artifacts or [] if a["id"] in [v if isinstance(v, str) else v.get("id") for v in [*draft.get("existing_artifacts", {}).values(), *draft.get("resume_artifacts", {}).values()]]],
            "operations": copy.deepcopy(manifest.get("operations", {}))}
    plan["fingerprint"] = digest(plan)
    destination = Path(snapshot_dir) if snapshot_dir else root / ".unity-workspace" / "plans" / plan_id
    if destination.exists():
        raise PlanError("plan snapshot already exists; plans are immutable")
    destination.mkdir(parents=True)
    try:
        for item in source["files"]:
            if item["redacted"]:
                continue
            source_path = project_path(root, item["path"], exists=True)
            data = source_path.read_bytes()
            if hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise PlanError("source changed during snapshot; check and review again")
            target = destination / "source" / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(item["mode"] & ~0o222)
        (destination / "scripts").mkdir()
        for stage in stages:
            script = destination / "scripts" / (stage["id"] + ".sh")
            script.write_text(stage["script"])
            script.chmod(0o555)
        (destination / "plan.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
        (destination / "plan.json").chmod(0o444)
    except Exception:
        shutil.rmtree(destination)
        raise
    return plan


def verify_plan(root, plan, draft=None):
    """Verify review freshness and the frozen bytes before a new dispatch intent."""
    errors = []
    connection = load_connection(root)
    if not connection.get("valid"):
        return {"valid": False, "errors": connection["errors"]}
    if connection["digest"] != plan["connection_digest"]:
        _issue(errors, "connection", "connection changed; check and review a new plan")
    try:
        if source_inventory(root, connection["manifest"])["digest"] != plan["source"]["digest"]:
            _issue(errors, "source", "source or environment changed; check and review a new plan")
        if input_inventory(root, connection["manifest"]) != plan.get("inputs", []):
            _issue(errors, "inputs", "inputs changed; check and review a new plan")
        errors.extend(verify_snapshot(root, plan)["errors"])
    except (OSError, ConnectionError, PlanError) as exc:
        _issue(errors, "source", str(exc))
    if draft is not None and digest(draft) != plan["draft_digest"]:
        _issue(errors, "draft", "draft changed; check and review a new plan")
    return {"valid": not errors, "errors": errors}



def verify_snapshot(root, plan):
    """Check frozen bytes only; approved continuation does not consult live source."""
    errors = _verify_artifacts(Path(root), plan.get("artifacts", []))
    try:
        if plan.get("job_template_digest"):
            template = Path(root) / ".unity-workspace" / "plans" / plan["id"] / "job_template.sh"
            if hashlib.sha256(template.read_bytes()).hexdigest() != plan["job_template_digest"]:
                _issue(errors, "job_template", "immutable allocation template was modified")
        for item in plan["source"]["files"]:
            if item["redacted"]:
                continue
            frozen = Path(root) / ".unity-workspace" / "plans" / plan["id"] / "source" / item["path"]
            if hashlib.sha256(frozen.read_bytes()).hexdigest() != item["sha256"]:
                _issue(errors, "source", "immutable snapshot was modified: " + item["path"])
        for stage in plan["stages"]:
            if project_path(Path(root), stage["script_path"], exists=True).read_text() != stage["script"]:
                _issue(errors, "scripts", "immutable wrapper was modified: " + stage["id"])
    except (OSError, ConnectionError) as exc:
        _issue(errors, "source", str(exc))
    return {"valid": not errors, "errors": errors}


def save_custom_script(root, plan, stage_id, relative_path):
    """Create project-owned source exclusively; regeneration never overwrites it."""
    stage = next((stage for stage in plan["stages"] if stage["id"] == stage_id), None)
    if stage is None:
        raise PlanError("unknown stage")
    if not relative_path.startswith("unityHPC/custom/") or not relative_path.endswith(".sh"):
        raise PlanError("custom scripts belong under unityHPC/custom/ and must end in .sh")
    path = project_path(Path(root), relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x") as stream:
            payload = {"argv": stage["argv"], "cwd": stage["cwd"], "plan_id": plan["id"], "variant_id": stage["variant_id"], "stage_id": stage["stage_id"], "output_dir": stage["output_dir"]}
            stream.write("\n".join([
                "#!/usr/bin/env bash", "set -euo pipefail", "# Project-owned custom operation. Run through a reviewed workspace wrapper.",
                "python3 - <<'UNITY_CUSTOM_PY'", "import os, pathlib, subprocess, sys", "p = " + repr(payload),
                "root, source, output = (os.environ[key] for key in ('UNITY_PROJECT_ROOT', 'UNITY_SOURCE_ROOT', 'UNITY_OUTPUT_DIR'))",
                "execution, variant, stage = (os.environ[key] for key in ('UNITY_EXECUTION_ID', 'UNITY_VARIANT_ID', 'UNITY_STAGE_ID'))",
                "def expand(value):",
                "    identities = {p['plan_id']: execution, p['variant_id']: variant, p['stage_id']: stage}",
                "    if value in identities: return identities[value]",
                "    value = value.replace('__UNITY_PROJECT_ROOT__/' + p['output_dir'], output)",
                "    old = '.unity-workspace/outputs/' + p['plan_id'] + '/' + p['variant_id'] + '/'",
                "    new = '.unity-workspace/outputs/' + execution + '/' + variant + '/'",
                "    return value.replace(old, new).replace('__UNITY_PROJECT_ROOT__', root).replace('__UNITY_SOURCE_ROOT__', source)",
                "sys.exit(subprocess.call([expand(a) for a in p['argv']], cwd=pathlib.Path(source) / p['cwd']))",
                "UNITY_CUSTOM_PY", ""]))
    except FileExistsError as exc:
        raise PlanError("custom script already exists; choose a new path") from exc
    path.chmod(0o755)
    return {"path": relative_path, "operation": {"argv": ["bash", relative_path], "cwd": ".", "location": stage["location"], "version": "1"}, "source_plan_id": plan["id"], "source_stage_id": stage_id, "resources": copy.deepcopy(stage["resources"]), "outputs": [{**output, "path": str(Path(output["path"]).relative_to(stage["output_dir"]))} for output in stage["outputs"]]}
