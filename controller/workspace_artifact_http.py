"""Files and Results routes consumed by the central workspace router."""
from controller import workspace_artifacts as artifacts, workspace_results as results, workspace_store as store


def route(method, slug, rest, req):
    from controller.http import _json, _read_json, _q, Response
    parts = rest.strip('/').split('/')
    if parts[0] not in ('files', 'transfers', 'results'):
        return None
    body = _read_json(req) if method in ('POST', 'PATCH') else {}
    keys = ('root', 'path', 'version', 'offset', 'limit', 'artifact', 'name', 'purpose', 'collection', 'execution',
            'variant', 'stage', 'attempt', 'experiment', 'campaign', 'analysis', 'superseded', 'selection_fingerprint', 'completeness', 'currency', 'kind', 'location', 'integrity', 'changed')
    query = {k: _q(req, k) for k in keys if _q(req, k) not in (None, '')}
    if method == 'GET':
        if rest == 'files/roots': return _json(200, artifacts.roots(slug))
        if rest == 'files': return _json(200, artifacts.browse(slug, query))
        if rest == 'files/download':
            data, name = artifacts.download_source(slug, query)
            from urllib.parse import quote
            return Response(200, data, 'application/octet-stream', {'Content-Disposition': "attachment; filename*=UTF-8''" + quote(name), 'Content-Security-Policy': 'sandbox', 'X-Content-Type-Options': 'nosniff'})
        if rest == 'files/preview': return _json(200, artifacts.preview(slug, query))
        if rest == 'transfers': return _json(200, {'transfers': [artifacts.transfer_projection(slug, t) for t in store.listing(slug, 'transfer')], 'capability': artifacts.transfer_capability(slug)})
        if len(parts) == 2 and parts[0] == 'transfers': return _json(200, artifacts.transfer_projection(slug, store.read(slug, 'transfer', parts[1])))
        if rest == 'results': return _json(200, results.query(slug, query))
        if rest == 'results/samples': return _json(200, results.samples(slug, query))
        if len(parts) == 4 and parts[1] == 'samples' and parts[3] == 'parent': return _json(200, results.parent(slug, parts[2]))
        if len(parts) == 3 and parts[1] == 'samples': return _json(200, results.sample(slug, parts[2]))
        if rest == 'results/comparisons': return _json(200, {'comparisons': store.listing(slug, 'comparison')})
        if len(parts) >= 3 and parts[1] == 'comparisons':
            return _json(200, results.export_comparison(slug, parts[2]) if len(parts) == 4 and parts[3] == 'export' else store.read(slug, 'comparison', parts[2]))
        if rest == 'results/views': return _json(200, {'views': store.listing(slug, 'saved_view')})
        if len(parts) >= 3 and parts[1] == 'views': return _json(200, store.read(slug, 'saved_view', parts[2]))
    if method == 'POST':
        if rest == 'transfers/preview': return _json(201, artifacts.prepare_transfer(slug, body))
        if rest == 'transfers': return _json(202, artifacts.commit_transfer(slug, body.get('preview_id'), body.get('idempotency_key')))
        if len(parts) == 3 and parts[0] == 'transfers':
            if parts[2] == 'cancel': return _json(200, artifacts.cancel_transfer(slug, parts[1]))
            if parts[2] == 'reconcile': return _json(200, artifacts.reconcile_transfer(slug, parts[1]))
        if rest == 'results/comparisons': return _json(201, results.compare(slug, body))
        if rest == 'results/views': return _json(201, results.save_view(slug, body))
        if rest == 'results/points': return _json(200, results.points(slug, body))
        if rest == 'results/metrics': return _json(200, results.metrics(slug, body))
    return _json(404, {'error': 'Unknown artifact or results route'})
