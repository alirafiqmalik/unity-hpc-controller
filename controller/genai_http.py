"""HTTP routes of the LLMs & Agents evaluation workspace.

Mounted at ``/api/v1/projects/<slug>/genai/…`` by ``controller.http``.

| Route | Does |
|---|---|
| ``GET  summary`` | counts, assessments over the default collections, connector facts |
| ``GET  datasets`` · ``POST datasets`` | list · create (writes ``<datasets_dir>/<name>/``) |
| ``GET  datasets/<id>`` · ``PATCH`` | records page and linked runs · description and tags |
| ``POST datasets/<id>/records`` | add records, or add traces as records |
| ``GET  evaluations`` · ``GET evaluations/<id>`` | runs on disk, plus pending workspace executions |
| ``GET  launch`` · ``POST evaluations`` | launchable workflows · check and prepare an evaluation plan |
| ``GET  traces`` · ``GET traces/<id>`` | the trace table · one full trace |
| ``GET  sessions`` · ``GET prompts`` · ``GET agent-versions`` | groupings over the same rows |

Reads never shell out. ``POST evaluations`` goes through the reviewed
runner interface (``controller.runner``), so an evaluation run is an ordinary
plan for the user to review and explicitly approve.
"""

from __future__ import annotations

import json
import re
from urllib.parse import unquote

from controller import genai

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def _int(req, key: str, default: int, low: int = 0, high: int = 500) -> int:
    from controller.http import _q
    raw = _q(req, key)
    try:
        value = int(raw) if raw not in (None, "") else default
    except ValueError:
        value = default
    return max(low, min(high, value))


def _flag(req, key: str) -> bool:
    from controller.http import _q
    return (_q(req, key, "") or "").lower() in ("1", "true", "yes")


def route(method: str, slug: str, rest: str, req):
    from controller.http import _json, _read_json, _q
    try:
        return _route(method, slug, rest, req, _json, _read_json, _q)
    except genai.GenAIError as exc:
        return _json(exc.status, {"ok": False, "error": str(exc)})


def _route(method, slug, rest, req, _json, _read_json, _q):
    # api.ts encodes each identifier; split first, then decode (a trace id may hold '/').
    parts = [unquote(p) for p in rest.strip("/").split("/") if p]
    body = _read_json(req) if method in ("POST", "PATCH") else {}
    if not isinstance(body, dict):
        raise genai.GenAIError("Request body must be an object")

    if parts == ["summary"] and method == "GET":
        return _json(200, genai.summary(slug))

    if parts == ["datasets"]:
        if method == "GET":
            return _json(200, genai.datasets(slug))
        if method == "POST":
            return _json(201, genai.create_dataset(slug, body))
    if len(parts) >= 2 and parts[0] == "datasets":
        dataset_id = parts[1]
        if len(parts) == 2:
            if method == "GET":
                return _json(200, genai.dataset(slug, dataset_id, offset=_int(req, "offset", 0, 0, 10**9),
                                                limit=_int(req, "limit", 50, 1, 500), search=_q(req, "search", "") or ""))
            if method == "PATCH":
                return _json(200, genai.update_dataset(slug, dataset_id, body))
        if len(parts) == 3 and parts[2] == "records" and method == "POST":
            return _json(200, genai.merge_records(slug, dataset_id, body))

    if parts == ["evaluations"]:
        if method == "GET":
            answer = genai.evaluations(slug, collection=_q(req, "collection", "all") or "all", index=_flag(req, "index"))
            answer["executions"] = _executions(slug)
            return _json(200, answer)
        if method == "POST":
            prepared = _launch(slug, body)
            return _json(201 if prepared["ok"] else 422, prepared)
    if len(parts) == 2 and parts[0] == "evaluations" and method == "GET":
        return _json(200, genai.evaluation(slug, parts[1]))

    if parts == ["launch"] and method == "GET":
        return _json(200, _launch_options(slug))

    if parts == ["traces"] and method == "GET":
        return _json(200, genai.traces(
            slug,
            evaluation_id=_q(req, "evaluation", "") or "",
            collection=_q(req, "collection", "") or "",
            dataset_name=_q(req, "dataset", "") or "",
            session=_q(req, "session", "") or "",
            state=_q(req, "state", "") or "",
            model=_q(req, "model", "") or "",
            search=_q(req, "search", "") or "",
            assessment=_q(req, "assessment", "") or "",
            assessment_value=_q(req, "assessment_value", "") or "",
            since=_q(req, "since", "") or "",
            purpose=_q(req, "purpose", "") or "",
            include_superseded=_flag(req, "superseded"),
            sort=_q(req, "sort", "request_time") or "request_time",
            descending=(_q(req, "order", "desc") or "desc") != "asc",
            offset=_int(req, "offset", 0, 0, 10**9),
            limit=_int(req, "limit", 50, 1, 500),
        ))
    if len(parts) == 2 and parts[0] == "traces" and method == "GET":
        return _json(200, genai.trace(slug, _q(req, "evaluation", "") or "", parts[1]))

    if parts == ["sessions"] and method == "GET":
        return _json(200, genai.sessions(slug, evaluation_id=_q(req, "evaluation", "") or "",
                                         collection=_q(req, "collection", "") or "", include_superseded=_flag(req, "superseded")))
    if parts == ["prompts"] and method == "GET":
        return _json(200, genai.prompts(slug))
    if parts == ["agent-versions"] and method == "GET":
        return _json(200, genai.agent_versions(slug))

    return _json(404, {"ok": False, "error": f"no route {method} genai/{rest}"})


# --------------------------------------------------------------------------- #
# Launching an evaluation through the workspace
# --------------------------------------------------------------------------- #

def _executions(slug: str) -> list[dict]:
    """Workspace executions, newest first, trimmed to what the runs list shows."""
    try:
        from controller import workspace_store as store
        items = store.listing(slug, "execution")
    except Exception:  # The workspace store is optional for a read-only project.
        return []
    out = []
    for item in items:
        stages = [{"id": s.get("id"), "state": s.get("state"), "location": s.get("location"),
                   "job_ids": s.get("job_ids", []), "completeness": s.get("completeness")}
                  for s in item.get("stages", [])]
        out.append({"id": item.get("id"), "state": item.get("state"), "experiment_id": item.get("experiment_id"),
                    "approved_at": item.get("approved_at"), "updated_at": item.get("updated_at"),
                    "kind": item.get("kind"), "stages": stages})
    out.sort(key=lambda e: e.get("approved_at") or "", reverse=True)
    return out[:50]


def _launch_options(slug: str) -> dict:
    from controller import workspace
    rec = genai.project(slug)
    conn = genai.connector(rec)
    connection = workspace.connection(slug)
    manifest = connection.get("manifest") or {}
    launch = conn.get("launch") or {}
    allowed = launch.get("workflows") or []
    dataset_names = [d["name"] for d in genai.datasets(slug)["datasets"]]
    bindings = launch.get("workflow_datasets") if isinstance(launch.get("workflow_datasets"), dict) else {}
    workflows = []
    for key, definition in (manifest.get("workflows") or {}).items():
        if allowed and key not in allowed:
            continue
        names = definition.get("parameters") or list(manifest.get("parameters", {}))
        # Which dataset does this workflow evaluate? A declared binding wins; else a
        # parameter whose choices are dataset names picks it; else the name says.
        bound = bindings.get(key)
        dataset_parameter = launch.get("dataset_parameter")
        if not bound:
            for name in names:
                choices = (manifest.get("parameters") or {}).get(name, {}).get("choices") or []
                if choices and set(map(str, choices)) & set(dataset_names):
                    dataset_parameter = name
                    break
            else:
                haystack = f"{key} {definition.get('title') or ''}".lower()
                bound = next((d for d in sorted(dataset_names, key=len, reverse=True) if d in haystack), None)
        parameters = []
        for name in names:
            spec = (manifest.get("parameters") or {}).get(name) or {}
            parameters.append({
                "name": name,
                "label": spec.get("label") or name,
                "type": spec.get("type") or "string",
                "default": (definition.get("defaults") or {}).get(name, spec.get("default")),
                "choices": spec.get("choices"),
                "min": spec.get("min"),
                "max": spec.get("max"),
                "unit": spec.get("unit"),
                "allowed_purposes": spec.get("allowed_purposes"),
            })
        stages = [{"id": s.get("id"), "operation": s.get("operation"), "purpose": s.get("purpose", "experiment"),
                   "location": s.get("location") or (manifest.get("operations", {}).get(s.get("operation"), {}) or {}).get("location"),
                   "resources": s.get("resources") or {}} for s in definition.get("stages", [])]
        workflows.append({
            "id": key,
            "title": definition.get("title") or key,
            "parameters": parameters,
            "stages": stages,
            "metrics": definition.get("metrics") or [],
            "smoke_test_required": bool(definition.get("smoke_test_required")),
            "purpose": "smoke-test" if all(s["purpose"] == "smoke-test" for s in stages) and stages else "experiment",
            "dataset": bound if bound in dataset_names else None,
            "dataset_parameter": dataset_parameter if not bound else None,
        })
    return {
        "valid": bool(connection.get("valid")),
        "errors": connection.get("errors") or [],
        "workflows": workflows,
        "datasets": dataset_names,
        "dataset_parameter": launch.get("dataset_parameter"),
        "scorers": manifest.get("metrics") or {},
    }


def _launch(slug: str, body: dict) -> dict:
    """Prepare a frozen evaluation plan for a separate review and approval."""
    from controller import runner
    from controller.workspace_store import WorkspaceError
    workflow = str(body.get("workflow") or "")
    if not _ID.fullmatch(workflow):
        raise genai.GenAIError("workflow is required")
    rec = genai.project(slug)
    conn = genai.connector(rec)
    allowed = (conn.get("launch") or {}).get("workflows") or []
    if allowed and workflow not in allowed:
        raise genai.GenAIError(f"workflow {workflow!r} is not an evaluation workflow of this project")
    parameters = body.get("parameters") or {}
    if not isinstance(parameters, dict):
        raise genai.GenAIError("parameters must be an object")
    draft: dict = {"parameters": parameters}
    dataset_parameter = body.get("dataset_parameter") or (conn.get("launch") or {}).get("dataset_parameter")
    if body.get("dataset") and isinstance(dataset_parameter, str) and _ID.fullmatch(dataset_parameter):
        draft["parameters"][dataset_parameter] = body["dataset"]
    if isinstance(body.get("variant_parameters"), dict) and body["variant_parameters"]:
        draft["variant_parameters"] = body["variant_parameters"]
    name = str(body.get("name") or "").strip()
    try:
        prepared = runner.prepare(slug, {"workflow": workflow, "name": name or None, **draft})
    except WorkspaceError as exc:
        raise genai.GenAIError(str(exc), getattr(exc, "status", 400) or 400) from exc
    return prepared
