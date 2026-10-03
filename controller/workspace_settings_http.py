"""Settings and research metadata routes, delegated by the workspace router."""
from controller import workspace_settings as settings, workspace_overview as overview, workspace_store as store


def route(method, slug, rest, req):
    from controller.http import _json, _read_json, _q
    parts = rest.strip('/').split('/')
    body = _read_json(req) if method in ('POST', 'PATCH') else {}
    if rest == 'settings':
        if method == 'GET':
            return _json(200, settings.snapshot(slug))
        if method == 'PATCH':
            return _json(200, settings.update_defaults(slug, body))
    if rest == 'connection/checks' and method == 'POST':
        return _json(200, settings.check_connection(slug, body))
    if rest == 'connection/preview' and method == 'POST':
        return _json(201, settings.preview_maintenance(slug, body))
    if parts[0] == 'maintenance' and len(parts) >= 2:
        if len(parts) == 2 and method == 'GET':
            return _json(200, store.read(slug, 'maintenance-action', parts[1]))
        if len(parts) == 3 and method == 'POST':
            if parts[2] == 'activate':
                return _json(200, settings.apply_maintenance(slug, parts[1], body))
            if parts[2] == 'reconcile':
                return _json(200, settings.reconcile_maintenance(slug, parts[1]))
            if parts[2] == 'rollback':
                return _json(200, settings.rollback(slug, parts[1]))
    if len(parts) == 3 and parts[0] == 'experiments' and parts[2] == 'defaults' and method == 'POST':
        return _json(200, settings.adoption(slug, parts[1], body))
    if rest == 'overview' and method == 'GET':
        return _json(200, overview.overview(slug, {k: _q(req, k) for k in ('collection', 'campaign')}, _q(req, 'cursor', '0')))
    if rest == 'overview/context' and method == 'PATCH':
        return _json(200, overview.update_context(slug, body))
    if rest == 'overview/acknowledge' and method == 'POST':
        return _json(200, overview.acknowledge(slug, body))
    if len(parts) in (2, 3) and parts[0] == 'overview' and parts[1] in ('notes', 'pins') and method in ('POST', 'PATCH'):
        return _json(200, overview.save_evidence(slug, 'note' if parts[1] == 'notes' else 'pin', body, parts[2] if len(parts) == 3 else None))
    return None
