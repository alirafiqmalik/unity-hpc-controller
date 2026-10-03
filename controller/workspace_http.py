"""Workspace HTTP contract, separate from the legacy fixed launch catalog."""
from __future__ import annotations

import json
import mimetypes

from controller import workspace as service
from controller import workspace_store as store


def route(method, slug, rest, req):
    """Keep domain payloads compatible and add passive response metadata."""
    response = _route(method, slug, rest, req)
    parts = rest.strip('/').split('/')
    artifact_download = len(parts) == 3 and parts[0] == 'artifacts' and parts[2] == 'file'
    if response.content_type == 'application/json' and not artifact_download:
        from controller.workspace_contracts import response_metadata
        payload = json.loads(response.body)
        if isinstance(payload, dict):
            payload['response_metadata'] = response_metadata(payload, rest, store.now())
            response.body = json.dumps(payload, default=str).encode()
    return response


def _route(method, slug, rest, req):
    from controller.http import _json, _read_json, _q, Response
    from controller.workspace_execution_http import route as execution_route
    from controller.workspace_artifact_http import route as artifact_route
    from controller.workspace_settings_http import route as settings_route
    service.project(slug)
    response = execution_route(method, slug, rest, req)
    if response is not None:
        return response
    response = settings_route(method, slug, rest, req)
    if response is not None:
        return response
    response = artifact_route(method, slug, rest, req)
    if response is not None:
        return response
    parts = rest.strip('/').split('/')
    body = _read_json(req) if method in ('POST', 'PATCH') else {}
    if rest == 'connection' and method == 'GET':
        return _json(200, service.connection(slug))
    if rest == 'experiments':
        if method == 'GET':
            items = store.listing(slug, 'experiment')
            archived = _q(req, 'archived', 'false')
            if archived != 'all':
                items = [x for x in items if x['archived'] == (archived == 'true')]
            return _json(200, {'experiments': items})
        if method == 'POST':
            return _json(201, service.create(slug, body))
    if len(parts) >= 2 and parts[0] == 'experiments':
        identity = parts[1]
        if len(parts) == 2:
            if method == 'GET':
                return _json(200, store.read(slug, 'experiment', identity))
            if method == 'PATCH':
                return _json(200, store.update_experiment(slug, identity, body))
            if method == 'DELETE':
                return _json(200, store.experiment_action(slug, identity, 'delete'))
        if len(parts) == 3:
            action = parts[2]
            if action == 'revisions' and method == 'GET':
                return _json(200, {'revisions': [r for r in store.listing(slug, 'revision') if r['experiment_id'] == identity]})
            if method == 'POST':
                if action == 'clone':
                    return _json(201, service.clone(slug, identity, body))
                if action in ('archive', 'restore', 'revisions'):
                    return _json(200, store.experiment_action(slug, identity, action))
                if action == 'check':
                    return _json(200, service.check(slug, identity))
                if action == 'plans':
                    return _json(201, service.plan(slug, identity))
    if len(parts) >= 2 and parts[0] == 'plans':
        if len(parts) == 2 and method == 'GET':
            return _json(200, store.read(slug, 'plan', parts[1]))
        if len(parts) == 3 and method == 'POST':
            if parts[2] == 'dispatch':
                return _json(202, service.dispatch_plan(slug, parts[1], body.get('idempotency_key')))
            if parts[2] == 'custom-script':
                return _json(201, service.custom_script(slug, parts[1], body))
    if rest == 'executions' and method == 'GET':
        items = store.listing(slug, 'execution')
        experiment = _q(req, 'experiment_id')
        if experiment:
            items = [x for x in items if x.get('experiment_id') == experiment]
        return _json(200, {'executions': items})
    if len(parts) >= 2 and parts[0] == 'executions':
        execution = store.read(slug, 'execution', parts[1])
        if len(parts) == 2 and method == 'GET':
            return _json(200, execution)
        if len(parts) == 3:
            if parts[2] == 'recovery' and method == 'POST':
                return _json(201, service.recovery(slug, parts[1], body))
            if parts[2] == 'reconcile' and method == 'POST':
                return _json(200, service.reconcile(slug, parts[1]))
            if parts[2] == 'fetch' and method == 'POST':
                return _json(200, service.fetch_execution(slug, parts[1], body))
            if parts[2] == 'logs' and method == 'GET':
                return _json(200, service.execution_logs(slug, parts[1], _q(req, 'stage_id')))
    if rest == 'artifacts' and method == 'GET':
        items = store.listing(slug, 'artifact')
        execution = _q(req, 'execution_id')
        if execution:
            items = [a for a in items if a['execution_id'] == execution]
        return _json(200, {'artifacts': items})
    if len(parts) >= 2 and parts[0] == 'artifacts' and method == 'GET':
        if len(parts) == 2:
            return _json(200, store.read(slug, 'artifact', parts[1]))
        if len(parts) == 3 and parts[2] == 'file':
            data, suffix = service.artifact_file(slug, parts[1], _q(req, 'path'))
            content_type = mimetypes.types_map.get(suffix, 'application/octet-stream')
            # Project output never inherits the dashboard's origin privileges.
            return Response(200, data, content_type, {'Content-Security-Policy': "sandbox", 'X-Content-Type-Options': 'nosniff'})
    if rest in ('analysis', 'analyses') and method == 'POST':
        return _json(201, service.analysis(slug, body))
    if rest in ('analysis', 'analyses') and method == 'GET':
        return _json(200, {'analyses': [p for p in store.listing(slug, 'plan') if p.get('kind') == 'analysis']})
    return _json(404, {'error': 'Unknown workspace route'})
