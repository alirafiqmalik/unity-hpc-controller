"""HTTP interface for declared workflow setup and durable execution."""
from urllib.parse import unquote

from controller import runner, workspace, workspace_runs as runs, workspace_store as store


def route(method, slug, rest, req):
    from controller.http import _json, _read_json, _q
    workspace.project(slug)
    parts = [unquote(p) for p in rest.strip('/').split('/') if p]
    body = _read_json(req) if method == 'POST' else {}
    if not isinstance(body, dict):
        return _json(400, {'error': 'Request body must be an object'})

    def number(key, default, high):
        try:
            return min(high, max(0, int(_q(req, key, str(default)))))
        except (TypeError, ValueError):
            return default

    if parts == ['workflows'] and method == 'GET':
        return _json(200, runner.workflows(slug))
    if parts == ['plans'] and method == 'POST':
        result = runner.prepare(slug, body)
        return _json(201 if result['ok'] else 422, result)
    if len(parts) == 2 and parts[0] == 'plans' and method == 'GET':
        return _json(200, store.read(slug, 'plan', parts[1]))
    if len(parts) == 3 and parts[0] == 'plans' and parts[2] == 'approve' and method == 'POST':
        return _json(202, runner.approve(slug, parts[1], body.get('idempotency_key')))
    if parts == ['executions'] and method == 'GET':
        filters = {k: _q(req, k) for k in ('state', 'purpose', 'search', 'campaign')}
        return _json(200, runner.executions(slug, filters, number('offset', 0, 10**9), max(1, number('limit', 50, 200))))
    if len(parts) >= 2 and parts[0] == 'executions':
        value = runner.execution(slug, parts[1])
        if len(parts) == 2 and method == 'GET':
            return _json(200, value)
        if len(parts) == 3 and parts[2] == 'logs' and method == 'GET':
            attempt_id = _q(req, 'attempt')
            attempts = [a['id'] for s in value['stages'] for a in s.get('attempts', [])]
            if attempt_id not in attempts:
                return _json(400, {'error': 'Select an attempt of this execution'})
            return _json(200, runs.logs(slug, attempt_id, stream=_q(req, 'stream', 'stdout'),
                                        offset=_q(req, 'offset'), cursor=_q(req, 'cursor'),
                                        limit=str(max(1, number('limit', 65536, 65536))), job_id=_q(req, 'job_id')))
    if parts == ['document'] and method == 'GET':
        return _json(200, runner.document(slug, number('offset', 0, 10**9), _q(req, 'version')))
    if len(parts) == 2 and parts[0] == 'artifacts' and method == 'GET':
        from controller.http import Response
        data, suffix = workspace.artifact_file(slug, parts[1], _q(req, 'path'))
        import mimetypes
        return Response(200, data, mimetypes.types_map.get(suffix, 'application/octet-stream'),
                        {'Content-Security-Policy': 'sandbox', 'X-Content-Type-Options': 'nosniff',
                         'Content-Disposition': 'attachment'})
    return _json(404, {'error': 'Unknown runner route'})
