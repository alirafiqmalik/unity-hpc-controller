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
| ``POST evaluations/prepare-matrix`` · ``POST evaluations/launch-matrix`` | freeze dataset plans · explicitly approve their frozen variants |
| ``DELETE evaluations`` | hide selected finished evaluations while retaining evidence and receipts |
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
    body = _read_json(req) if method in ("POST", "PATCH", "DELETE") else {}
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
                                                limit=_int(req, "limit", 50, 1, 500), search=_q(req, "search", "") or "",
                                                subset=_q(req, "subset", "") or "", split=_q(req, "split", "") or ""))
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
        if method == "DELETE":
            from controller import genai_evaluations
            return _json(200, genai_evaluations.delete(slug, body))
    if parts == ["evaluations", "prepare-matrix"] and method == "POST":
        return _json(200, _prepare_matrix(slug, body))
    if parts == ["evaluations", "launch-matrix"] and method == "POST":
        return _json(202, _launch_matrix(slug, body))
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
    experiments = {x["id"]: x for x in store.listing(slug, "experiment")}
    aliases = (genai.connector(genai.project(slug)).get("launch") or {}).get("model_aliases") or {}
    hidden = set(genai.hidden_evaluations(genai.project(slug))["execution_ids"])
    for item in items:
        if item["id"] in hidden:
            continue
        try:
            plan = store.read(slug, "plan", item.get("plan_id") or item["id"])
        except Exception:
            plan = {}
        parameters = plan.get("config", {}).get("parameters", {})
        variants = plan.get("variants", [])
        models = list(dict.fromkeys(str(v.get("parameters", {}).get("model") or v.get("parameters", {}).get("original_model") or v.get("parameters", {}).get("model_id") or "") for v in variants))
        experiment = experiments.get(item.get("experiment_id"), {})
        stages = [{"id": s.get("id"), "state": s.get("state"), "location": s.get("location"),
                   "job_ids": s.get("job_ids", []), "completeness": s.get("completeness"),
                   "jobs": [{"job_id": j.get("job_id"), "status": j.get("status")}
                            for j in s.get("jobs", []) if j.get("job_id") in s.get("job_ids", [])]}
                  for s in item.get("stages", [])]
        out.append({"id": item.get("id"), "state": item.get("state"), "experiment_id": item.get("experiment_id"),
                    "approved_at": item.get("approved_at"), "updated_at": item.get("updated_at"),
                    "kind": item.get("kind"), "stages": stages, "name": experiment.get("name") or item["id"],
                    "scheduler_observation": item.get("scheduler_observation"),
                    "dataset": parameters.get("dataset") or parameters.get("benchmark") or ("tlaibench" if str(plan.get("config", {}).get("workflow", "")).startswith("tlaibench") else ""),
                    "models": [aliases.get(m, m) for m in models if m]})
    out.sort(key=lambda e: e.get("approved_at") or "", reverse=True)
    return out[:50]


def _launch_options(slug: str) -> dict:
    from controller import workspace
    rec = genai.project(slug)
    conn = genai.connector(rec)
    connection = workspace.connection(slug)
    manifest = connection.get("manifest") or {}
    if not connection.get("valid"):
        return {"valid": False, "errors": connection.get("errors") or [], "workflows": [],
                "datasets": [], "dataset_options": {}, "model_aliases": {}, "scorers": {}}
    launch = conn.get("launch") or {}
    allowed = launch.get("workflows") or []
    dataset_summaries = genai.datasets(slug)["datasets"]
    dataset_names = [d["id"] for d in dataset_summaries]
    dataset_options = {d["id"]: genai.dataset(slug, d["id"], limit=1).get("viewer", {}) for d in dataset_summaries}
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
                "variant_eligible": bool(spec.get("variant_eligible")),
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
            "model_parameter": next((p["name"] for p in parameters if p["name"] in ("model", "original_model", "model_id")), None),
            "supported_datasets": [bound] if bound in dataset_names else [d for d in dataset_names if not dataset_parameter or not next((p["choices"] for p in parameters if p["name"] == dataset_parameter), None) or d in next((p["choices"] for p in parameters if p["name"] == dataset_parameter), [])],
        })
    return {
        "valid": bool(connection.get("valid")),
        "errors": connection.get("errors") or [],
        "workflows": workflows,
        "datasets": dataset_names,
        "dataset_options": dataset_options,
        "model_aliases": launch.get("model_aliases") or {},
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


def _prepare_matrix(slug: str, body: dict) -> dict:
    """Prepare one immutable multi-model plan per dataset, without dispatching."""
    from controller import runner
    from controller.workspace_store import WorkspaceError
    catalog = _launch_options(slug)
    if not catalog['valid']:
        raise genai.GenAIError('Project connection is invalid')
    selections = body.get('datasets')
    models = body.get('models')
    shared = body.get('parameters') or {}
    if not isinstance(models, list) or not models or len(models) > 64 or any(not isinstance(x, str) or not x for x in models) or len(set(models)) != len(models):
        raise genai.GenAIError('Select 1–64 distinct models')
    if not isinstance(selections, list) or not selections or len(selections) > 64:
        raise genai.GenAIError('Select 1–64 datasets')
    if not isinstance(shared, dict):
        raise genai.GenAIError('parameters must be an object')
    workflows = {w['id']: w for w in catalog['workflows']}
    aliases = catalog['model_aliases']
    drafts = []
    seen = set()
    for selection in selections:
        if not isinstance(selection, dict):
            raise genai.GenAIError('Each dataset selection must be an object')
        name = selection.get('dataset')
        if not isinstance(name, str) or not name:
            raise genai.GenAIError('Dataset name must be a string')
        workflow_id = selection.get('workflow') or body.get('workflow')
        if not isinstance(workflow_id, str):
            raise genai.GenAIError('Workflow must be a string')
        workflow = workflows.get(workflow_id)
        if name in seen:
            raise genai.GenAIError('Select each dataset once')
        seen.add(name)
        if not workflow or name not in workflow['supported_datasets']:
            raise genai.GenAIError(f'Workflow does not support dataset {name!r}')
        parameter_names = {p['name'] for p in workflow['parameters']}
        model_parameter = workflow['model_parameter']
        if not model_parameter:
            raise genai.GenAIError('Workflow does not declare a model parameter')
        parameters = {key: value for key, value in shared.items() if key in parameter_names}
        per_dataset = selection.get('parameters') or {}
        if not isinstance(per_dataset, dict) or set(per_dataset) - parameter_names:
            raise genai.GenAIError('Invalid dataset parameters')
        parameters.update(per_dataset)
        if workflow['dataset_parameter']:
            parameters[workflow['dataset_parameter']] = name
        viewer = catalog['dataset_options'].get(name, {})
        subset = selection.get('subset', viewer.get('selected_subset', 'default'))
        split = selection.get('split', viewer.get('selected_split', 'local'))
        if not isinstance(subset, str) or not isinstance(split, str):
            raise genai.GenAIError('Dataset subset and split must be strings')
        partitions = viewer.get('subsets') or []
        selected_partitions = [x for x in partitions if not subset or x['name'] == subset]
        selected_splits = [s for p in selected_partitions for s in p.get('splits', [])]
        if partitions and (not selected_partitions or (split and split not in [x['name'] for x in selected_splits])):
            raise genai.GenAIError(f'Unknown subset or split for {name}')
        for key, value, candidates in [('subset', subset, ('dataset_subset', 'subset', 'config')), ('split', split, ('dataset_split', 'split'))]:
            target = next((x for x in candidates if x in parameter_names), None)
            if target:
                parameters[target] = value
            elif partitions and (len(partitions) > 1 if key == 'subset' else len({x['name'] for x in selected_splits}) > 1):
                raise genai.GenAIError(f'Workflow must declare a dataset {key} parameter to select this partition')
        partition_rows = sum(x['rows'] for x in selected_splits if not split or x['name'] == split) if partitions else None
        offset = parameters.get('dataset_offset', 0)
        item_limit = parameters.get('n_items')
        if isinstance(partition_rows, int) and isinstance(offset, int) and not isinstance(offset, bool) and offset >= 0:
            available = max(0, partition_rows - offset)
            if not available:
                raise genai.GenAIError(f'No records remain in the selected {name} partition at this offset')
            if isinstance(item_limit, int) and not isinstance(item_limit, bool) and item_limit > 0:
                parameters['n_items'] = min(item_limit, available)
        spec = next(p for p in workflow['parameters'] if p['name'] == model_parameter)
        choices = list(map(str, spec.get('choices') or []))
        values = []
        for model in models:
            candidates = [model, aliases.get(model)]
            candidates += [key for key, value in aliases.items() if value == model]
            selected = next((x for x in candidates if x and (not choices or x in choices)), None)
            if selected is None:
                raise genai.GenAIError(f'Model {model!r} is unavailable for {workflow["title"]}')
            values.append(selected)
        if len(set(values)) != len(values):
            raise genai.GenAIError('Model aliases selected the same model twice')
        parameters[model_parameter] = values[0]
        if len(values) > 1 and not spec.get('variant_eligible'):
            raise genai.GenAIError('Workflow model parameter does not support multi-model evaluation')
        drafts.append({'workflow': workflow['id'], 'name': f'{body.get("name") or "Model comparison"} · {name}',
                       'parameters': parameters, 'variant_parameters': {model_parameter: values} if len(values) > 1 else {},
                       '_summary': {'dataset': name, 'workflow': workflow['id'], 'models': values, 'subset': subset, 'split': split,
                                    'rows': partition_rows,
                                    'parameters': parameters}})
    prepared = []
    try:
        for draft in drafts:
            summary = draft.pop('_summary')
            answer = runner.prepare(slug, draft)
            if not answer.get('ok'):
                return {**answer, 'ok': False, 'prepared': prepared, 'dataset': summary['dataset']}
            plan = answer['plan']
            prepared.append({**summary, 'experiment_id': answer['experiment_id'], 'plan_id': answer['plan_id'],
                             'plan': plan, 'checks': answer.get('checks'),
                             'stages': [{'id': x['id'], 'purpose': x.get('purpose'), 'location': x.get('location'),
                                         'resources': x.get('resources', {}), 'parameters': x.get('parameters', {})} for x in plan.get('stages', [])]})
    except WorkspaceError as exc:
        raise genai.GenAIError(str(exc), getattr(exc, 'status', 400)) from exc
    return {'ok': True, 'prepared': prepared, 'evaluations': len(models) * len(selections),
            'note': 'Plans checked and frozen. Review the matrix, then launch.'}


def _launch_matrix(slug: str, body: dict) -> dict:
    from controller import runner, workspace_store as store
    from controller.workspace_planner import verify_plan
    from controller.workspace_store import WorkspaceError
    identities = body.get('plan_ids')
    if not isinstance(identities, list) or not identities or len(identities) > 64 or any(not isinstance(x, str) or not _ID.fullmatch(x) for x in identities) or len(set(identities)) != len(identities):
        raise genai.GenAIError('Select checked evaluation plans to launch')
    approved = {item.get('plan_id') for item in store.listing(slug, 'execution')}
    pending = [identity for identity in identities if identity not in approved]
    workflows = {x['id'] for x in _launch_options(slug)['workflows']} if pending else set()
    root = genai.root_of(genai.project(slug))
    # Check unapproved snapshots before the first approval. Existing approvals
    # are resolved by the engine before it checks current declarations or inputs.
    try:
        for identity in pending:
            plan = store.read(slug, 'plan', identity)
            if plan.get('config', {}).get('workflow') not in workflows:
                raise genai.GenAIError('Plan is not an evaluation workflow')
            verification = verify_plan(root, plan)
            if not verification.get('valid', verification.get('ok', False)):
                raise genai.GenAIError('A checked plan changed. Prepare the evaluation matrix again.', 409)
        launched = []
        for identity in identities:
            try:
                execution = runner.approve(slug, identity, 'genai-' + identity)
            except WorkspaceError as exc:
                return {'ok': False, 'error': str(exc), 'launched': launched, 'pending_plan_ids': [x for x in identities if x not in [r['plan_id'] for r in launched]]}
            launched.append({'plan_id': identity, 'execution': execution})
    except WorkspaceError as exc:
        raise genai.GenAIError(str(exc), getattr(exc, 'status', 400)) from exc
    return {'ok': True, 'launched': launched, 'note': 'Approved all dataset comparisons. Monitor their executions and open results as they arrive.'}
