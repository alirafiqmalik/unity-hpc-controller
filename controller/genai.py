"""Evaluation reader and dataset writer for LLMs & Agents projects.

An `llms-agents` project opens as an evaluation workspace in the dashboard:
datasets, evaluation runs, traces with assessments, sessions, prompts and
agent versions. This module reads all of that from the attached project
directory. It never talks to the cluster.

The project describes its layout in the ``genai`` block of
``unityHPC/project.json`` (the *connector*). The block is optional. Its
defaults match the layout the ``llms-agents`` scaffold writes:

    dataset/<name>/dataset.json        metadata, tags, schema
    dataset/<name>/records.jsonl       {record_id, inputs, expectations, source, tags}
    evaluations/<run>/manifest.json    one evaluation run
    evaluations/<run>/traces.jsonl     one trace per dataset record

A project with another trace format (llm-thinking-trace keeps its corpus
under ``data/<collection>/<run>/``) maps its own field names onto the
dashboard's columns in the same block. Field paths are dotted:
``token_counts.total_completion``.

Evaluation runs and traces are read-only here. Datasets are the one thing the
dashboard writes: create a dataset, add records, add traces to a dataset.
Every write stays inside ``<datasets_dir>/`` of the project.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from controller import registry
from lib import paths

APPLICATION = "llms-agents"

_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
#: an existing dataset folder: any safe single path part (a vendored `MMLU/` too)
_FOLDER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_MAX_MANIFEST = 4 * 1024 * 1024
_PREVIEW = 240


class GenAIError(ValueError):
    """A malformed connector, a bad request, or a missing object."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------- #
# Connector
# --------------------------------------------------------------------------- #

DEFAULT_CONNECTOR: dict[str, Any] = {
    "schema_version": 1,
    "datasets_dir": "dataset",
    "evaluation_roots": [
        {"path": "evaluations", "manifest": "manifest.json", "traces": "traces.jsonl", "depth": 1,
         "collection": "evaluations", "default": True},
        {"path": ".unity-workspace/outputs", "manifest": "manifest.json", "provenance": "manifest.json",
         "traces": "traces.jsonl", "depth": 6, "collection": "workspace", "default": True},
    ],
    "evaluation_fields": {
        "name": "name",
        "model": "model",
        "dataset": "dataset",
        "started": "started_utc",
        "finished": "finished_utc",
        "n_items": "n_items",
        "trace_count": "counts.done",
        "prompt": "prompt",
        "scorers": "scorers",
        "purpose": "purpose",
        "metrics": {"accuracy": "metrics.accuracy"},
        "agent": {"model": "model", "engine": "engine", "engine_version": "engine_version",
                  "runner": "runner_version"},
    },
    "traces": {
        "fields": {
            "trace_id": "trace_id",
            "request": "request",
            "response": "response",
            "reasoning": "reasoning",
            "request_time": "request_time",
            "duration_s": "duration_s",
            "tokens": "tokens.completion",
            "prompt_tokens": "tokens.prompt",
            "error": "error",
            "state": "state",
            "session": "session",
            "dataset": "dataset",
            "dataset_record": "dataset_record",
            "model": "model",
            "spans": "spans",
            "inputs": "inputs",
            "tags": "tags",
        },
        "assessments": "assessments",
        "expectations": "expectations",
    },
    "prompts_dir": "prompts",
    "launch": {"workflows": []},
    "docs": "README.md",
}


def _deep_merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def project(slug: str) -> dict:
    rec = registry.get(slug)
    if rec is None:
        raise GenAIError(f"unknown project {slug!r}", 404)
    return rec


def root_of(rec: dict) -> Path:
    return Path(rec["path"]).resolve()


def connector(rec: dict) -> dict:
    """The project's genai block over the defaults. Never raises on a bad manifest."""
    try:
        manifest_path = _inside(root_of(rec), "unityHPC/project.json")
    except GenAIError:
        return _deep_merge(DEFAULT_CONNECTOR, {"declared": False})
    block: dict = {}
    if manifest_path.is_file() and manifest_path.stat().st_size <= _MAX_MANIFEST:
        try:
            manifest = json.loads(manifest_path.read_text())
            if isinstance(manifest, dict) and isinstance(manifest.get("genai"), dict):
                block = manifest["genai"]
        except (OSError, ValueError):
            block = {}
    merged = _deep_merge(DEFAULT_CONNECTOR, block)
    if "evaluation_roots" in block:
        merged["evaluation_roots"] = copy.deepcopy(block["evaluation_roots"])
    merged["declared"] = bool(block)
    return merged


def _inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise GenAIError(f"path escapes the project: {relative}")
    return path


def _get(obj: Any, path: Any, default: Any = None) -> Any:
    """Dotted lookup. `a.b.0.c` walks dicts and lists. A list of paths: first hit wins."""
    if isinstance(path, list):
        for candidate in path:
            value = _get(obj, candidate, None)
            if value is not None:
                return value
        return default
    if not path or not isinstance(path, str):
        return default
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            if part not in cur:
                return default
            cur = cur[part]
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return default
        else:
            return default
    return cur


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _preview(value: Any, limit: int = _PREVIEW) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _read_json(path: Path, limit: int = _MAX_MANIFEST, *, root: Path | None = None) -> dict:
    if root is not None and not path.resolve().is_relative_to(root.resolve()):
        return {}
    if not path.is_file() or path.stat().st_size > limit:
        return {}
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _short_id(prefix: str, text: str) -> str:
    return f"{prefix}-{hashlib.sha1(text.encode()).hexdigest()[:12]}"


# --------------------------------------------------------------------------- #
# Datasets
# --------------------------------------------------------------------------- #

def _datasets_dir(rec: dict, conn: dict) -> Path:
    return _inside(root_of(rec), str(conn.get("datasets_dir") or "dataset"))


def _records_file(folder: Path, value: Any) -> str:
    """The records file named by dataset.json. It must stay inside the dataset folder."""
    name = str(value or "records.jsonl")
    rel = Path(name)
    if rel.is_absolute() or ".." in rel.parts or not (folder / rel).resolve().is_relative_to(folder.resolve()):
        raise GenAIError(f"records_file {name!r} must be a path inside the dataset folder")
    return name


def _dataset_folder(rec: dict, conn: dict, dataset_id: str) -> Path:
    """An existing dataset folder. A symlink out of the datasets directory is refused."""
    base = _datasets_dir(rec, conn)
    folder = base / dataset_id
    if not _FOLDER.fullmatch(dataset_id) or not folder.is_dir() or not folder.resolve().is_relative_to(base.resolve()):
        raise GenAIError(f"unknown dataset {dataset_id!r}", 404)
    return folder


def _dataset_meta(folder: Path) -> dict:
    meta = _read_json(folder / "dataset.json", root=folder)
    records_file = _records_file(folder, meta.get("records_file"))
    return {
        "schema_version": meta.get("schema_version", 1),
        "name": meta.get("name") or folder.name,
        "description": meta.get("description") or "",
        "tags": meta.get("tags") if isinstance(meta.get("tags"), dict) else {},
        "created_utc": meta.get("created_utc") or "",
        "updated_utc": meta.get("updated_utc") or "",
        "source": meta.get("source") if isinstance(meta.get("source"), dict) else {},
        "records_file": records_file,
        "declared": bool(meta),
        "license": meta.get("license") or "",
    }


def _iter_records(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                value.setdefault("record_id", f"line-{line_number + 1}")
                # A hand-written record may carry only inputs; readers expect objects.
                for key in ("inputs", "expectations", "source", "tags"):
                    if not isinstance(value.get(key), dict):
                        value[key] = {}
                yield value


def _record_fingerprint(record: dict) -> str:
    return hashlib.sha256(json.dumps(record.get("inputs", {}), sort_keys=True, default=str).encode()).hexdigest()[:16]


def _profile(records: list[dict]) -> dict:
    inputs: dict[str, int] = {}
    expectations: dict[str, int] = {}
    sources: dict[str, int] = {}
    tags: dict[str, int] = {}
    for record in records:
        for key in (record.get("inputs") or {}):
            inputs[key] = inputs.get(key, 0) + 1
        for key in (record.get("expectations") or {}):
            expectations[key] = expectations.get(key, 0) + 1
        source = (record.get("source") or {}).get("type") or "UNKNOWN"
        sources[source] = sources.get(source, 0) + 1
        for key in (record.get("tags") or {}):
            tags[key] = tags.get(key, 0) + 1
    labeled = sum(1 for r in records if r.get("expectations"))
    return {
        "records": len(records),
        "labeled": labeled,
        "unlabeled": len(records) - labeled,
        "inputs_schema": sorted(inputs),
        "expectations_schema": sorted(expectations),
        "sources": sources,
        "tag_keys": sorted(tags),
    }


def datasets(slug: str) -> dict:
    rec = project(slug)
    conn = connector(rec)
    folder = _datasets_dir(rec, conn)
    items = []
    if folder.is_dir():
        for child in sorted(folder.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            if not child.resolve().is_relative_to(folder.resolve()):
                continue
            try:
                meta = _dataset_meta(child)
            except GenAIError:
                continue
            records = list(_iter_records(child / meta["records_file"]))
            stat = child.stat()
            raw_files = sum(1 for p in child.rglob("*") if p.is_file() and p.name not in ("dataset.json", meta["records_file"]))
            items.append({
                "id": child.name,
                "path": str(child.relative_to(root_of(rec))),
                **{k: meta[k] for k in ("name", "description", "tags", "created_utc", "updated_utc", "source", "declared", "license")},
                "profile": _profile(records),
                "raw_files": raw_files,
                "modified_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
    evals = evaluations(slug)["evaluations"]
    for item in items:
        linked = [e for e in evals if e.get("dataset") == item["name"]]
        item["evaluations"] = len(linked)
        item["last_evaluation_utc"] = max((e.get("started") or "" for e in linked), default="")
    return {"datasets": items, "datasets_dir": str(folder.relative_to(root_of(rec))), "writable": True}


def dataset(slug: str, dataset_id: str, offset: int = 0, limit: int = 50, search: str = "") -> dict:
    rec = project(slug)
    conn = connector(rec)
    folder = _dataset_folder(rec, conn, dataset_id)
    meta = _dataset_meta(folder)
    records = list(_iter_records(folder / meta["records_file"]))
    needle = search.strip().lower()
    if needle:
        records = [r for r in records if needle in json.dumps(r, default=str).lower()]
    page = records[offset: offset + max(1, min(limit, 500))]
    evals = [e for e in evaluations(slug)["evaluations"] if e.get("dataset") == meta["name"]]
    files = []
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            files.append({"path": str(path.relative_to(folder)), "size": path.stat().st_size})
    return {
        "id": dataset_id,
        "path": str(folder.relative_to(root_of(rec))),
        **{k: meta[k] for k in ("name", "description", "tags", "created_utc", "updated_utc", "source", "declared", "license", "records_file")},
        "profile": _profile(records),
        "records": [{**r, "fingerprint": _record_fingerprint(r)} for r in page],
        "total": len(records),
        "offset": offset,
        "limit": limit,
        "evaluations": evals,
        "files": files[:200],
    }


#: dataset writes read, merge and replace files; the HTTP server is threaded
_DATASET_WRITE = threading.Lock()


def _write_dataset_meta(folder: Path, meta: dict) -> None:
    keep = {k: meta[k] for k in ("schema_version", "name", "description", "tags", "created_utc", "updated_utc", "source", "records_file", "license") if k in meta}
    tmp = folder / "dataset.json.tmp"
    tmp.write_text(json.dumps(keep, indent=2, sort_keys=True) + "\n")
    tmp.replace(folder / "dataset.json")


def create_dataset(slug: str, body: dict) -> dict:
    with _DATASET_WRITE:
        return _create_dataset(slug, body)


def _create_dataset(slug: str, body: dict) -> dict:
    rec = project(slug)
    conn = connector(rec)
    name = str(body.get("name") or "").strip().lower().replace(" ", "-")
    if not _NAME.fullmatch(name):
        raise GenAIError("dataset name must be lowercase letters, digits, '.', '_' or '-' (max 64)")
    base = _datasets_dir(rec, conn)
    folder = base / name
    if folder.exists():
        raise GenAIError(f"dataset {name!r} already exists", 409)
    tags = body.get("tags") or {}
    if not isinstance(tags, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in tags.items()):
        raise GenAIError("tags must map strings to strings")
    folder.mkdir(parents=True)
    meta = {
        "schema_version": 1,
        "name": name,
        "description": str(body.get("description") or ""),
        "tags": tags,
        "created_utc": _now(),
        "updated_utc": _now(),
        "source": {"type": "HUMAN", "created_by": "unity-hpc dashboard"},
        "records_file": "records.jsonl",
    }
    _write_dataset_meta(folder, meta)
    (folder / "records.jsonl").write_text("")
    return dataset(slug, name)


def update_dataset(slug: str, dataset_id: str, body: dict) -> dict:
    with _DATASET_WRITE:
        return _update_dataset(slug, dataset_id, body)


def _update_dataset(slug: str, dataset_id: str, body: dict) -> dict:
    rec = project(slug)
    conn = connector(rec)
    folder = _dataset_folder(rec, conn, dataset_id)
    meta = _dataset_meta(folder)
    if "description" in body:
        meta["description"] = str(body["description"] or "")
    if "tags" in body:
        tags = body["tags"] or {}
        if not isinstance(tags, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in tags.items()):
            raise GenAIError("tags must map strings to strings")
        meta["tags"] = tags
    meta["updated_utc"] = _now()
    meta.setdefault("created_utc", meta["updated_utc"])
    _write_dataset_meta(folder, meta)
    return dataset(slug, dataset_id)


def _normalise_record(record: Any) -> dict:
    if not isinstance(record, dict):
        raise GenAIError("each record must be an object")
    inputs = record.get("inputs")
    if not isinstance(inputs, dict) or not inputs:
        raise GenAIError("each record needs a non-empty inputs object")
    expectations = record.get("expectations") or {}
    if not isinstance(expectations, dict):
        raise GenAIError("expectations must be an object")
    source = record.get("source") or {"type": "HUMAN"}
    if not isinstance(source, dict):
        raise GenAIError("source must be an object")
    tags = record.get("tags") or {}
    if not isinstance(tags, dict):
        raise GenAIError("tags must be an object")
    out = {"inputs": inputs, "expectations": expectations, "source": source, "tags": tags}
    out["record_id"] = str(record.get("record_id") or _record_fingerprint(out))
    return out


def merge_records(slug: str, dataset_id: str, body: dict) -> dict:
    """Add records to a dataset, MLflow `merge_records` style.

    A record whose record_id or inputs already exist is not duplicated: its
    expectations and tags take the incoming values, so a later import can label
    an input that was added unlabeled.
    """
    with _DATASET_WRITE:
        return _merge_records(slug, dataset_id, body)


def _merge_records(slug: str, dataset_id: str, body: dict) -> dict:
    rec = project(slug)
    conn = connector(rec)
    folder = _dataset_folder(rec, conn, dataset_id)
    meta = _dataset_meta(folder)
    incoming: list[dict] = []
    for item in body.get("records") or []:
        incoming.append(_normalise_record(item))
    for ref in body.get("traces") or []:
        if not isinstance(ref, dict) or not ref.get("trace_id"):
            raise GenAIError("each trace reference needs trace_id and evaluation_id")
        full = trace(slug, str(ref.get("evaluation_id") or ""), str(ref["trace_id"]))
        incoming.append(_record_from_trace(full, bool(body.get("response_as_expectation"))))
    if not incoming:
        raise GenAIError("nothing to add: give records or trace references")
    if len(incoming) > 5000:
        raise GenAIError("add at most 5000 records per call")
    path = folder / meta["records_file"]
    # Raw lines, so a rewrite changes only the records it updates.
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    parsed: dict[int, dict] = {}
    for index, line in enumerate(lines):
        try:
            value = json.loads(line) if line.strip() else None
        except ValueError:
            value = None
        if isinstance(value, dict):
            parsed[index] = value
    by_id = {str(v.get("record_id") or f"line-{i + 1}"): i for i, v in parsed.items()}
    by_print = {_record_fingerprint(v): i for i, v in parsed.items()}
    added = updated = skipped = 0
    appended: list[str] = []
    for record in incoming:
        fingerprint = _record_fingerprint(record)
        index = by_print.get(fingerprint)
        if index is None and record["record_id"] in by_id:
            # Same id, other inputs (two sources both numbered `line-1`): keep the
            # existing record and its labels rather than relabel a different input.
            skipped += 1
            continue
        if index is None:
            appended.append(json.dumps(record, sort_keys=True, default=str))
            index = len(lines) + len(appended) - 1
            parsed[index] = record
            by_id[record["record_id"]] = by_print[fingerprint] = index
            added += 1
            continue
        target = parsed[index]
        changed = False
        for key in ("expectations", "tags"):
            current = target.get(key) if isinstance(target.get(key), dict) else {}
            merged = {**current, **record[key]}
            if merged != current:
                target[key] = merged
                changed = True
        if not changed:
            skipped += 1
            continue
        if index < len(lines):
            lines[index] = json.dumps(target, sort_keys=True, default=str)
        else:
            appended[index - len(lines)] = json.dumps(target, sort_keys=True, default=str)
        updated += 1
    if updated:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text("".join(line + "\n" for line in lines + appended), encoding="utf-8")
        tmp.replace(path)
    elif appended:
        with path.open("a", encoding="utf-8") as handle:
            handle.writelines(line + "\n" for line in appended)
    meta["updated_utc"] = _now()
    meta.setdefault("created_utc", meta["updated_utc"])
    _write_dataset_meta(folder, meta)
    result = dataset(slug, dataset_id)
    result["added"] = added
    result["updated"] = updated
    result["skipped"] = skipped
    return result


def _record_from_trace(full: dict, response_as_expectation: bool) -> dict:
    inputs = full.get("inputs") if isinstance(full.get("inputs"), dict) and full.get("inputs") else {"request": full.get("request") or ""}
    expectations = dict(full.get("expectations") or {})
    if response_as_expectation and full.get("response"):
        expectations.setdefault("expected_response", full["response"])
    return _normalise_record({
        "record_id": full.get("dataset_record") or full["trace_id"],
        "inputs": inputs,
        "expectations": expectations,
        "source": {"type": "TRACE", "trace_id": full["trace_id"], "evaluation_id": full.get("evaluation_id"),
                   "model": full.get("model")},
        "tags": {k: str(v) for k, v in (full.get("tags") or {}).items()} if isinstance(full.get("tags"), dict) else {},
    })


# --------------------------------------------------------------------------- #
# Evaluation runs
# --------------------------------------------------------------------------- #

def _scan_roots(rec: dict, conn: dict) -> list[dict]:
    """Every directory under an evaluation root that holds a manifest."""
    root = root_of(rec)
    found: list[dict] = []
    for spec in conn.get("evaluation_roots") or []:
        if isinstance(spec, str):
            spec = {"path": spec}
        if not isinstance(spec, dict) or not spec.get("path"):
            continue
        try:
            base = _inside(root, str(spec["path"]))
        except GenAIError:
            continue
        if not base.is_dir():
            continue
        manifest_rel = str(spec.get("manifest") or "manifest.json")
        depth = int(spec.get("depth") or 1)
        stack = [(base, 0)]
        while stack:
            folder, level = stack.pop()
            if not folder.resolve().is_relative_to(base):
                continue
            try:
                manifest_path = _inside(folder.resolve(), manifest_rel)
            except GenAIError:
                continue
            if folder != base and manifest_path.is_file():
                found.append({"folder": folder, "spec": spec, "manifest_path": manifest_path})
                continue
            if level >= depth:
                continue
            try:
                children = sorted(p for p in folder.iterdir() if p.is_dir() and not p.is_symlink()
                                  and (not p.name.startswith(".") or p.name == ".unity-workspace"))
            except OSError:
                continue
            stack.extend((child, level + 1) for child in children)
    return found


def _trace_files(folder: Path, spec: dict) -> list[Path]:
    pattern = str(spec.get("traces") or "traces.jsonl")
    if "/" in pattern:
        sub, _, glob = pattern.rpartition("/")
        try:
            base = _inside(folder.resolve(), sub)
        except GenAIError:
            return []
    else:
        base, glob = folder, pattern
    if not base.is_dir():
        return []
    return sorted(p for p in base.glob(glob) if p.is_file() and p.resolve().is_relative_to(folder.resolve()))


def _dataset_name(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return ""
    if "/" in value:
        return Path(value.rstrip("/")).name
    return value


def _workspace_names(slug: str) -> dict[str, dict]:
    """execution id -> {experiment name, execution state}, from the workspace store."""
    try:
        from controller import workspace_store as store
        experiments = {e["id"]: e for e in store.listing(slug, "experiment")}
        out = {}
        for execution in store.listing(slug, "execution"):
            experiment = experiments.get(execution.get("experiment_id") or "", {})
            out[execution["id"]] = {"name": experiment.get("name") or "", "state": execution.get("state") or "",
                                    "experiment_id": execution.get("experiment_id")}
        return out
    except Exception:  # A project without a workspace store has no executions to name.
        return {}


def _evaluation_record(rec: dict, conn: dict, hit: dict, *, index: bool = False, names: dict | None = None) -> dict:
    """One evaluation run. With ``index`` false, trace files are read only when already cached."""
    root = root_of(rec)
    folder: Path = hit["folder"]
    rel = str(folder.relative_to(root))
    manifest = _read_json(hit["manifest_path"])
    provenance = _read_json(folder / str(hit["spec"].get("provenance")), root=folder) if hit["spec"].get("provenance") else {}
    fields = conn.get("evaluation_fields") or {}
    files = _trace_files(folder, hit["spec"])
    entries = [_rows_for(path, conn, parse=index) for path in files]
    indexed = all(entry is not None for entry in entries)
    rows = [row for entry in entries if entry for row in entry["rows"]]
    if indexed:
        trace_count = len(rows)
    else:
        counted = _get(manifest, fields.get("trace_count"))
        trace_count = int(counted) if isinstance(counted, (int, float)) and not isinstance(counted, bool) else None
        # A manifest written before the shards landed says zero; the files know better.
        if not trace_count and any(path.stat().st_size > 0 for path in files):
            trace_count = None
    started = _get(manifest, fields.get("started")) or _get(provenance, "started_utc") or ""
    finished = _get(manifest, fields.get("finished")) or _get(provenance, "finished_utc") or ""
    name = _get(manifest, fields.get("name")) or provenance.get("variant_id") or folder.name
    workspace_entry = (names or {}).get(str(provenance.get("execution_id") or ""), {}) if provenance else {}
    if workspace_entry.get("name"):
        name = f"{workspace_entry['name']} · {provenance.get('stage_id') or folder.name}"
    dataset_name = _dataset_name(_get(manifest, fields.get("dataset"))) or _dataset_name(_get(provenance, "parameters.dataset")) or ""
    metrics = {}
    for key, path in (fields.get("metrics") or {}).items():
        value = _get(manifest, path)
        if value is None:
            value = _get(provenance, path)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            metrics[key] = value
    for key, value in (provenance.get("measurements") or {}).items():
        if isinstance(value, (int, float)) and not isinstance(value, bool) and key not in metrics:
            metrics[key] = value
    agent = {}
    for key, path in (fields.get("agent") or {}).items():
        value = _get(manifest, path)
        if value is not None:
            agent[key] = value
    superseded = (folder / "SUPERSEDED").exists()
    if superseded:
        state = "superseded"
    elif provenance and provenance.get("runner_exit") not in (None, 0):
        state = "failed"
    elif finished and (trace_count or (trace_count is None and files)):
        state = "complete"
    elif finished:
        state = "empty"
    elif started:
        state = "running"
    else:
        state = "unknown"
    summary = _assessment_summary(rows) if indexed else {}
    return {
        "id": _short_id("ev", rel),
        "path": rel,
        "collection": str(hit["spec"].get("collection") or Path(str(hit["spec"].get("path"))).name),
        "indexed": indexed,
        "name": str(name),
        "model": str(_get(manifest, fields.get("model")) or provenance.get("parameters", {}).get("model") or ""),
        "dataset": dataset_name,
        "started": started,
        "finished": finished,
        "n_items": _get(manifest, fields.get("n_items")),
        "traces": trace_count,
        "metrics": metrics,
        "agent": agent,
        "prompt": _get(manifest, fields.get("prompt")) if isinstance(_get(manifest, fields.get("prompt")), dict) else {},
        "scorers": _get(manifest, fields.get("scorers")) if isinstance(_get(manifest, fields.get("scorers")), list) else [],
        "state": state,
        "purpose": provenance.get("purpose") or _get(manifest, fields.get("purpose")) or "unclassified",
        "source": "workspace" if provenance else "project",
        "execution_id": provenance.get("execution_id"),
        "experiment_id": workspace_entry.get("experiment_id"),
        "variant_id": provenance.get("variant_id"),
        "stage_id": provenance.get("stage_id"),
        "assessments": summary,
        "trace_files": [str(p.relative_to(root)) for p in files],
    }


def _collections(conn: dict) -> list[dict]:
    out = []
    for spec in conn.get("evaluation_roots") or []:
        if isinstance(spec, str):
            spec = {"path": spec}
        if not isinstance(spec, dict) or not spec.get("path"):
            continue
        out.append({"id": str(spec.get("collection") or Path(str(spec["path"])).name), "path": str(spec["path"]),
                    "default": bool(spec.get("default", False)), "label": str(spec.get("label") or spec.get("collection") or Path(str(spec["path"])).name)})
    if out and not any(c["default"] for c in out):
        out[0]["default"] = True
    return out


def _in_scope(hit: dict, conn: dict, collection: str) -> bool:
    """`collection` is a collection id, `all`, or empty for the default collections."""
    spec = hit["spec"]
    own = str(spec.get("collection") or Path(str(spec.get("path"))).name)
    if collection == "all":
        return True
    if collection:
        return own == collection
    defaults = [c["id"] for c in _collections(conn) if c["default"]]
    return own in defaults


def evaluations(slug: str, *, collection: str = "all", index: bool = False) -> dict:
    rec = project(slug)
    conn = connector(rec)
    names = _workspace_names(slug)
    items = [_evaluation_record(rec, conn, hit, index=index, names=names) for hit in _scan_roots(rec, conn) if _in_scope(hit, conn, collection)]
    items.sort(key=lambda e: (e.get("started") or "", e["path"]), reverse=True)
    return {"evaluations": items, "collections": _collections(conn)}


def _find_evaluation(slug: str, evaluation_id: str) -> tuple[dict, dict, dict, dict]:
    rec = project(slug)
    conn = connector(rec)
    names = _workspace_names(slug)
    for hit in _scan_roots(rec, conn):
        rel = str(hit["folder"].relative_to(root_of(rec)))
        if _short_id("ev", rel) == evaluation_id:
            return rec, conn, hit, _evaluation_record(rec, conn, hit, index=True, names=names)
    raise GenAIError(f"unknown evaluation {evaluation_id!r}", 404)


def evaluation(slug: str, evaluation_id: str) -> dict:
    rec, conn, hit, record = _find_evaluation(slug, evaluation_id)
    manifest = _read_json(hit["manifest_path"])
    provenance = _read_json(hit["folder"] / str(hit["spec"].get("provenance"))) if hit["spec"].get("provenance") else {}
    rows = [row for path in _trace_files(hit["folder"], hit["spec"]) for row in _rows_for(path, conn)["rows"]]
    record["manifest"] = manifest
    record["provenance"] = provenance
    record["sessions"] = sorted({r["session"] for r in rows if r.get("session")})
    record["models"] = sorted({r["model"] for r in rows if r.get("model")})
    record["token_total"] = sum(r["tokens"] or 0 for r in rows)
    record["duration_total_s"] = round(sum(r["duration_s"] or 0 for r in rows), 3)
    record["states"] = _count(r["state"] for r in rows)
    return record


# --------------------------------------------------------------------------- #
# Traces
# --------------------------------------------------------------------------- #

_CACHE: dict[str, dict] = {}
_CACHE_LOCK = threading.Lock()
#: Bump when the light-row shape changes, so stale on-disk indexes are rebuilt.
_INDEX_VERSION = 3


def _state_of(record: dict, fields: dict) -> str:
    declared = _get(record, fields.get("state"))
    if isinstance(declared, str) and declared:
        return declared.upper()
    if _get(record, fields.get("error")):
        return "ERROR"
    if _get(record, fields.get("response")) is None and _get(record, fields.get("request_time")) is None:
        return "IN_PROGRESS"
    return "OK"


def _assessments_of(record: dict, spec: Any) -> dict[str, dict]:
    """name -> {value, kind, rationale, source}."""
    out: dict[str, dict] = {}
    if isinstance(spec, str):
        raw = _get(record, spec)
        if isinstance(raw, dict):
            for name, value in raw.items():
                if isinstance(value, dict) and "value" in value:
                    out[name] = {"value": value["value"], "kind": value.get("kind") or _kind_of(value["value"]),
                                 "rationale": value.get("rationale") or "", "source": value.get("source") or ""}
                else:
                    out[name] = {"value": value, "kind": _kind_of(value), "rationale": "", "source": ""}
        return out
    if isinstance(spec, dict):
        for name, mapping in spec.items():
            if isinstance(mapping, str):
                mapping = {"field": mapping}
            if not isinstance(mapping, dict):
                continue
            value = _get(record, mapping.get("field"))
            if value is None:
                continue
            rationale = _get(record, mapping.get("rationale")) if mapping.get("rationale") else ""
            out[name] = {"value": value, "kind": mapping.get("kind") or _kind_of(value),
                         "rationale": rationale if isinstance(rationale, str) else _preview(rationale),
                         "source": mapping.get("source") or ""}
    return out


def _kind_of(value: Any) -> str:
    if isinstance(value, bool):
        return "pass_fail"
    if isinstance(value, (int, float)):
        return "score"
    return "category"


def _expectations_of(record: dict, spec: Any) -> dict[str, Any]:
    if isinstance(spec, str):
        raw = _get(record, spec)
        return dict(raw) if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}
    if isinstance(spec, dict):
        for name, path in spec.items():
            value = _get(record, path if isinstance(path, (str, list)) else (path or {}).get("field"))
            if value in (None, "", [], {}):
                continue
            out[name] = value
    return out


def _light_row(record: dict, conn: dict, file_rel: str) -> dict:
    tconf = conn.get("traces") or {}
    fields = tconf.get("fields") or {}
    assessments = _assessments_of(record, tconf.get("assessments"))
    expectations = _expectations_of(record, tconf.get("expectations"))
    tokens = _get(record, fields.get("tokens"))
    prompt_tokens = _get(record, fields.get("prompt_tokens"))
    duration = _get(record, fields.get("duration_s"))
    trace_id = _get(record, fields.get("trace_id"))
    return {
        "trace_id": str(trace_id) if trace_id is not None else "",
        "request": _preview(_get(record, fields.get("request"))),
        "response": _preview(_get(record, fields.get("response"))),
        "request_time": _get(record, fields.get("request_time")) or "",
        "duration_s": float(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) else None,
        "tokens": int(tokens) if isinstance(tokens, (int, float)) and not isinstance(tokens, bool) else None,
        "prompt_tokens": int(prompt_tokens) if isinstance(prompt_tokens, (int, float)) and not isinstance(prompt_tokens, bool) else None,
        "state": _state_of(record, fields),
        "error": _preview(_get(record, fields.get("error")), 160),
        "session": str(_get(record, fields.get("session")) or ""),
        "dataset_record": str(_get(record, fields.get("dataset_record")) or ""),
        "model": str(_get(record, fields.get("model")) or ""),
        "assessments": {k: {"value": v["value"], "kind": v["kind"]} for k, v in assessments.items()},
        "expectations": {k: _preview(v, 120) for k, v in expectations.items()},
        "file": file_rel,
    }


def _cache_file(key: str) -> Path:
    folder = paths.controller_dir() / "genai-index"
    return folder / (hashlib.sha1(key.encode()).hexdigest() + ".json")


def _rows_for(path: Path, conn: dict, *, parse: bool = True) -> dict | None:
    """Light rows for one trace file, cached in memory and on disk by mtime and size.

    With ``parse`` false an unindexed file answers None instead of being read.
    """
    key = str(path)
    try:
        stat = path.stat()
    except OSError:
        return {"rows": [], "offsets": {}, "count": 0}
    signature = [_INDEX_VERSION, stat.st_mtime_ns, stat.st_size,
                 hashlib.sha1(json.dumps(conn.get("traces"), sort_keys=True).encode()).hexdigest()]
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and cached["signature"] == signature:
            return cached
    disk = _cache_file(key)
    if disk.is_file():
        try:
            stored = json.loads(disk.read_text())
            if stored.get("signature") == signature:
                with _CACHE_LOCK:
                    _CACHE[key] = stored
                return stored
        except (OSError, ValueError):
            pass
    if not parse:
        return None
    rows: list[dict] = []
    offsets: dict[str, int] = {}
    file_rel = key
    with path.open("rb") as handle:
        position = 0
        for line in handle:
            start = position
            position += len(line)
            text = line.strip()
            if not text:
                continue
            try:
                record = json.loads(text)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            row = _light_row(record, conn, file_rel)
            if not row["trace_id"]:
                row["trace_id"] = f"line-{len(rows) + 1}"
            offsets[row["trace_id"]] = start
            rows.append(row)
    entry = {"signature": signature, "rows": rows, "offsets": offsets, "count": len(rows)}
    with _CACHE_LOCK:
        _CACHE[key] = entry
    try:
        disk.parent.mkdir(parents=True, exist_ok=True)
        tmp = disk.with_suffix(".tmp")
        tmp.write_text(json.dumps(entry, default=str))
        tmp.replace(disk)
    except OSError:
        pass
    return entry


def _count(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        out[str(value)] = out.get(str(value), 0) + 1
    return out


def _assessment_summary(rows: list[dict]) -> dict[str, dict]:
    """Per assessment: pass/fail counts, category counts, or score stats."""
    summary: dict[str, dict] = {}
    for row in rows:
        for name, item in (row.get("assessments") or {}).items():
            entry = summary.setdefault(name, {"kind": item["kind"], "count": 0, "pass": 0, "fail": 0, "values": {}, "sum": 0.0})
            value = item["value"]
            if value is None or (entry["kind"] == "score" and not isinstance(value, (int, float))):
                # Not assessed (no expectation, scorer error): out of the denominator.
                entry["unassessed"] = entry.get("unassessed", 0) + 1
                continue
            entry["count"] += 1
            if entry["kind"] == "pass_fail":
                truthy = value is True or (isinstance(value, str) and value.lower() in ("pass", "true", "yes"))
                entry["pass" if truthy else "fail"] += 1
            elif entry["kind"] == "score" and isinstance(value, (int, float)):
                entry["sum"] += float(value)
            else:
                entry["values"][str(value)] = entry["values"].get(str(value), 0) + 1
    for entry in summary.values():
        if entry["kind"] == "pass_fail" and entry["count"]:
            entry["pass_rate"] = round(entry["pass"] / entry["count"], 4)
        if entry["kind"] == "score" and entry["count"]:
            entry["mean"] = round(entry["sum"] / entry["count"], 4)
        entry.pop("sum", None)
    return summary


def _all_rows(slug: str, evaluation_id: str = "", collection: str = "") -> tuple[dict, dict, list[dict]]:
    """Every light row in scope. An evaluation id narrows to one run; else the collection decides."""
    rec = project(slug)
    conn = connector(rec)
    rows: list[dict] = []
    names = _workspace_names(slug)
    for hit in _scan_roots(rec, conn):
        rel = str(hit["folder"].relative_to(root_of(rec)))
        eid = _short_id("ev", rel)
        if evaluation_id:
            if eid != evaluation_id:
                continue
        elif not _in_scope(hit, conn, collection):
            continue
        record = _evaluation_record(rec, conn, hit, index=True, names=names)
        for path in _trace_files(hit["folder"], hit["spec"]):
            entry = _rows_for(path, conn)
            for row in entry["rows"] if entry else []:
                rows.append({**row, "evaluation_id": eid, "evaluation": record["name"], "dataset": record["dataset"],
                             "model": row["model"] or record["model"], "evaluation_state": record["state"],
                             "collection": record["collection"], "purpose": record["purpose"]})
    return rec, conn, rows


_SORT_KEYS = {
    "request_time": lambda r: r.get("request_time") or "",
    "duration_s": lambda r: r.get("duration_s") or 0,
    "tokens": lambda r: r.get("tokens") or 0,
    "state": lambda r: r.get("state") or "",
    "session": lambda r: r.get("session") or "",
    "model": lambda r: r.get("model") or "",
    "trace_id": lambda r: r.get("trace_id") or "",
}


def traces(slug: str, *, evaluation_id: str = "", collection: str = "", dataset_name: str = "", session: str = "",
           state: str = "", model: str = "", search: str = "", assessment: str = "", assessment_value: str = "",
           since: str = "", include_superseded: bool = False, purpose: str = "", sort: str = "request_time",
           descending: bool = True, offset: int = 0, limit: int = 50) -> dict:
    _, conn, rows = _all_rows(slug, evaluation_id, collection)
    if not include_superseded and not evaluation_id:
        rows = [r for r in rows if r.get("evaluation_state") != "superseded"]
    if purpose:
        rows = [r for r in rows if r.get("purpose") == purpose]
    if dataset_name:
        rows = [r for r in rows if r.get("dataset") == dataset_name]
    if session:
        rows = [r for r in rows if r.get("session") == session]
    if state:
        rows = [r for r in rows if r.get("state") == state.upper()]
    if model:
        rows = [r for r in rows if r.get("model") == model]
    if since:
        rows = [r for r in rows if (r.get("request_time") or "") >= since]
    if assessment:
        def matches(row: dict) -> bool:
            item = (row.get("assessments") or {}).get(assessment)
            if item is None:
                return False
            if not assessment_value:
                return True
            value = item["value"]
            if item["kind"] == "pass_fail":
                truthy = value is True or (isinstance(value, str) and value.lower() in ("pass", "true", "yes"))
                return (assessment_value.lower() in ("pass", "true")) == truthy
            return str(value) == assessment_value
        rows = [r for r in rows if matches(r)]
    needle = search.strip().lower()
    if needle:
        rows = [r for r in rows if needle in r["request"].lower() or needle in r["response"].lower()
                or needle in r["trace_id"].lower() or needle in r["session"].lower()]
    key = _SORT_KEYS.get(sort, _SORT_KEYS["request_time"])
    rows.sort(key=key, reverse=descending)
    total = len(rows)
    page = rows[offset: offset + max(1, min(limit, 500))]
    return {
        "traces": page,
        "total": total,
        "offset": offset,
        "limit": limit,
        "assessments": _assessment_summary(rows),
        "expectations": sorted({k for r in rows for k in (r.get("expectations") or {})}),
        "states": _count(r["state"] for r in rows),
        "models": sorted({r["model"] for r in rows if r["model"]}),
        "sessions": len({r["session"] for r in rows if r["session"]}),
        "datasets": sorted({r["dataset"] for r in rows if r["dataset"]}),
        "collections": _collections(conn),
        "collection": collection or "",
    }


def trace(slug: str, evaluation_id: str, trace_id: str) -> dict:
    """The full record for one trace: request, response, reasoning, spans, assessments."""
    rec = project(slug)
    conn = connector(rec)
    for hit in _scan_roots(rec, conn):
        rel = str(hit["folder"].relative_to(root_of(rec)))
        eid = _short_id("ev", rel)
        if evaluation_id and eid != evaluation_id:
            continue
        for path in _trace_files(hit["folder"], hit["spec"]):
            entry = _rows_for(path, conn)
            if trace_id not in entry["offsets"]:
                continue
            with path.open("rb") as handle:
                handle.seek(entry["offsets"][trace_id])
                record = json.loads(handle.readline())
            record_eval = _evaluation_record(rec, conn, hit, index=True, names=_workspace_names(slug))
            return _full_trace(record, conn, eid, record_eval)
    raise GenAIError(f"unknown trace {trace_id!r}", 404)


def _spans_of(record: dict, fields: dict) -> list[dict]:
    raw = _get(record, fields.get("spans"))
    spans: list[dict] = []
    if isinstance(raw, list):
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            spans.append({
                "index": index,
                "name": str(item.get("name") or item.get("type") or f"turn {item.get('turn_idx', index) + 1 if isinstance(item.get('turn_idx'), int) else index + 1}"),
                "type": str(item.get("type") or ("LLM" if "thinking_trace" in item or "raw_completion" in item else "SPAN")),
                "duration_s": item.get("duration_s") if isinstance(item.get("duration_s"), (int, float)) else item.get("wall_s"),
                "tokens": item.get("tokens") if isinstance(item.get("tokens"), (int, dict)) else item.get("completion_tokens"),
                "inputs": item.get("inputs", item.get("prompt")),
                "outputs": item.get("outputs", item.get("raw_completion", item.get("output"))),
                "reasoning": item.get("reasoning", item.get("thinking_trace")),
                "tool_calls": item.get("tool_calls", item.get("directives", item.get("ops"))),
                "tool_results": item.get("tool_results", item.get("tool_output")),
                "status": item.get("status", item.get("outcome")),
                "attributes": {k: v for k, v in item.items() if k not in (
                    "name", "type", "duration_s", "wall_s", "tokens", "completion_tokens", "inputs", "prompt", "outputs",
                    "raw_completion", "output", "reasoning", "thinking_trace", "tool_calls", "directives", "ops",
                    "tool_results", "tool_output", "status", "outcome") and not isinstance(v, (dict, list))},
            })
    return spans


def _full_trace(record: dict, conn: dict, evaluation_id: str, record_eval: dict) -> dict:
    tconf = conn.get("traces") or {}
    fields = tconf.get("fields") or {}
    light = _light_row(record, conn, "")
    reasoning = _get(record, fields.get("reasoning"))
    tags = _get(record, fields.get("tags"))
    inputs = _get(record, fields.get("inputs"))
    hidden: set[str] = set()
    for name in ("spans", "reasoning", "request", "response", "inputs"):
        mapped = fields.get(name)
        # A mapping is one dotted path or a list of them (first hit wins).
        hidden.update(p for p in (mapped if isinstance(mapped, list) else [mapped]) if isinstance(p, str))
    metadata = {}
    for key, value in record.items():
        if key in hidden or isinstance(value, (dict, list)):
            continue
        metadata[key] = value
    nested = {}
    for key, value in record.items():
        if isinstance(value, dict) and key not in hidden:
            nested[key] = {k: v for k, v in value.items() if not isinstance(v, (dict, list))}
    return {
        **light,
        "request": _get(record, fields.get("request")),
        "response": _get(record, fields.get("response")),
        "reasoning": reasoning if isinstance(reasoning, str) else None,
        "inputs": inputs if isinstance(inputs, dict) else None,
        "tags": tags if isinstance(tags, dict) else {},
        "assessments": _assessments_of(record, tconf.get("assessments")),
        "expectations": _expectations_of(record, tconf.get("expectations")),
        "spans": _spans_of(record, fields),
        "metadata": metadata,
        "nested": nested,
        "evaluation_id": evaluation_id,
        "evaluation": record_eval["name"],
        "dataset": record_eval["dataset"],
        "model": light["model"] or record_eval["model"],
    }


# --------------------------------------------------------------------------- #
# Sessions, prompts, agent versions
# --------------------------------------------------------------------------- #

def sessions(slug: str, *, evaluation_id: str = "", collection: str = "", include_superseded: bool = False) -> dict:
    _, conn, rows = _all_rows(slug, evaluation_id, collection)
    if not include_superseded and not evaluation_id:
        rows = [r for r in rows if r.get("evaluation_state") != "superseded"]
    groups: dict[str, dict] = {}
    for row in rows:
        key = row.get("session") or "(no session)"
        group = groups.setdefault(key, {"session": key, "traces": 0, "models": set(), "evaluations": set(), "datasets": set(),
                                        "first": "", "last": "", "tokens": 0, "duration_s": 0.0, "rows": []})
        group["traces"] += 1
        if row.get("model"):
            group["models"].add(row["model"])
        group["evaluations"].add(row["evaluation"])
        if row.get("dataset"):
            group["datasets"].add(row["dataset"])
        when = row.get("request_time") or ""
        group["first"] = min(group["first"] or when, when) if when else group["first"]
        group["last"] = max(group["last"], when)
        group["tokens"] += row.get("tokens") or 0
        group["duration_s"] += row.get("duration_s") or 0
        group["rows"].append(row)
    out = []
    for group in groups.values():
        out.append({
            "session": group["session"],
            "traces": group["traces"],
            "models": sorted(group["models"]),
            "evaluations": sorted(group["evaluations"]),
            "datasets": sorted(group["datasets"]),
            "first": group["first"],
            "last": group["last"],
            "tokens": group["tokens"],
            "duration_s": round(group["duration_s"], 3),
            "states": _count(r["state"] for r in group["rows"]),
            "assessments": _assessment_summary(group["rows"]),
        })
    out.sort(key=lambda s: (-s["traces"], s["session"]))
    return {"sessions": out, "total": len(out), "collections": _collections(conn), "collection": collection or ""}


def prompts(slug: str) -> dict:
    rec = project(slug)
    conn = connector(rec)
    root = root_of(rec)
    files = []
    try:
        folder = _inside(root, str(conn.get("prompts_dir") or "prompts"))
    except GenAIError:
        folder = None
    candidates: list[Path] = []
    if folder and folder.is_file():
        candidates = [folder]
    elif folder and folder.is_dir():
        candidates = [p for p in sorted(folder.rglob("*")) if p.is_file()
                      and p.suffix.lower() in (".md", ".txt", ".j2", ".jinja", ".prompt", ".yaml", ".yml", ".json", ".py")
                      and "__pycache__" not in p.parts]
    for path in candidates[:200]:
        if not path.resolve().is_relative_to(root):
            continue
        data = path.read_bytes()
        files.append({"path": str(path.relative_to(root)), "name": path.stem, "size": len(data),
                      "sha256": hashlib.sha256(data).hexdigest(),
                      "preview": data[:6000].decode("utf-8", "replace")})
    versions: dict[str, dict] = {}
    for item in evaluations(slug)["evaluations"]:
        prompt = item.get("prompt") or {}
        if not prompt:
            continue
        key = json.dumps(prompt, sort_keys=True, default=str)
        entry = versions.setdefault(key, {"prompt": prompt, "evaluations": [], "models": set(), "first": "", "last": ""})
        entry["evaluations"].append({"id": item["id"], "name": item["name"], "started": item["started"]})
        if item.get("model"):
            entry["models"].add(item["model"])
        when = item.get("started") or ""
        entry["first"] = min(entry["first"] or when, when) if when else entry["first"]
        entry["last"] = max(entry["last"], when)
    observed = []
    for entry in versions.values():
        prompt = entry["prompt"]
        observed.append({
            "id": _short_id("prompt", json.dumps(prompt, sort_keys=True, default=str)),
            "version": str(prompt.get("prompt_version") or prompt.get("version") or prompt.get("name") or "unversioned"),
            "sha256": str(prompt.get("prompt_sha256") or prompt.get("sha256") or ""),
            "details": {k: v for k, v in prompt.items() if not isinstance(v, (dict, list))},
            "evaluations": sorted(entry["evaluations"], key=lambda e: e["started"] or "", reverse=True),
            "models": sorted(entry["models"]),
            "first": entry["first"],
            "last": entry["last"],
        })
    observed.sort(key=lambda p: p["last"], reverse=True)
    return {"files": files, "observed": observed, "prompts_dir": str(conn.get("prompts_dir") or "prompts")}


def agent_versions(slug: str) -> dict:
    rec = project(slug)
    root = root_of(rec)
    lock = _read_json(root / "unityHPC" / "model-lock.json", root=root)
    pinned = {}
    for repo, item in (lock.get("models") or {}).items():
        if isinstance(item, dict):
            pinned[repo] = {"revision": item.get("revision") or "", "source": item.get("source") or ""}
    # Default collections are indexed so pass rates are real; the others list as they are.
    indexed = {item["id"]: item for item in evaluations(slug, collection="", index=True)["evaluations"]}
    items = [indexed.get(item["id"], item) for item in evaluations(slug)["evaluations"]]
    groups: dict[str, dict] = {}
    for item in items:
        agent = dict(item.get("agent") or {})
        if not agent.get("model") and item.get("model"):
            agent["model"] = item["model"]
        if not agent:
            continue
        key = json.dumps(agent, sort_keys=True, default=str)
        entry = groups.setdefault(key, {"agent": agent, "evaluations": [], "traces": 0, "first": "", "last": "", "pass": 0, "assessed": 0})
        entry["evaluations"].append({"id": item["id"], "name": item["name"], "started": item["started"], "state": item["state"],
                                     "metrics": item["metrics"], "dataset": item["dataset"]})
        entry["traces"] += item.get("traces") or 0
        when = item.get("started") or ""
        entry["first"] = min(entry["first"] or when, when) if when else entry["first"]
        entry["last"] = max(entry["last"], when)
        for summary in (item.get("assessments") or {}).values():
            if summary.get("kind") == "pass_fail":
                entry["pass"] += summary.get("pass", 0)
                entry["assessed"] += summary.get("count", 0)
    versions = []
    for entry in groups.values():
        agent = entry["agent"]
        model = str(agent.get("model") or "")
        versions.append({
            "id": _short_id("agent", json.dumps(agent, sort_keys=True, default=str)),
            "model": model,
            "details": {k: v for k, v in agent.items() if k != "model"},
            "pinned_revision": pinned.get(model, {}).get("revision", ""),
            "evaluations": sorted(entry["evaluations"], key=lambda e: e["started"] or "", reverse=True),
            "traces": entry["traces"],
            "first": entry["first"],
            "last": entry["last"],
            "pass_rate": round(entry["pass"] / entry["assessed"], 4) if entry["assessed"] else None,
        })
    versions.sort(key=lambda v: v["last"], reverse=True)
    return {"versions": versions, "pinned": pinned}


# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #

def summary(slug: str) -> dict:
    rec = project(slug)
    conn = connector(rec)
    data = datasets(slug)
    evals = evaluations(slug)["evaluations"]
    _, _, rows = _all_rows(slug, "", "")
    live = [r for r in rows if r.get("evaluation_state") != "superseded"]
    root = root_of(rec)
    docs = conn.get("docs") or "README.md"
    docs_path = None
    try:
        candidate = _inside(root, str(docs))
        if candidate.is_file():
            docs_path = str(candidate.relative_to(root))
    except GenAIError:
        docs_path = None
    return {
        "slug": slug,
        "application": rec.get("application") or "",
        "path": rec["path"],
        "connector": {k: v for k, v in conn.items() if k in ("schema_version", "datasets_dir", "evaluation_roots", "prompts_dir", "declared", "launch", "docs")},
        "counts": {
            "datasets": len(data["datasets"]),
            "evaluations": len(evals),
            "evaluations_complete": sum(1 for e in evals if e["state"] == "complete"),
            "traces": len(live),
            "sessions": len({r["session"] for r in live if r["session"]}),
            "models": len({r["model"] for r in live if r["model"]}),
        },
        "assessments": _assessment_summary(live),
        "latest_evaluation": evals[0] if evals else None,
        "docs_path": docs_path,
        "collections": _collections(conn),
    }
