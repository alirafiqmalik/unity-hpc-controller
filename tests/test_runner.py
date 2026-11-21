"""Runner interface checks using a real isolated workflow and durable worker."""
import json

from controller import http, workspace_store as store, workspace_worker as worker
from test_workspace_api import project  # noqa: F401


def call(method, path, body=None):
    response = http.handle(http.parse_raw(method, '/api/v1/projects/demo/runner/' + path,
                                         json.dumps(body).encode() if body is not None else b''))
    return response.status, json.loads(response.body)


def test_prepare_requires_explicit_approval_and_runs_frozen_source(project):
    status, catalog = call('GET', 'workflows')
    assert status == 200 and catalog['valid']
    assert catalog['workflows'][0]['stages'][0]['location'] == 'controller'
    assert store.listing('demo', 'experiment') == []
    status, prepared = call('POST', 'plans', {'workflow': 'local', 'name': 'Runner smoke'})
    assert status == 201 and prepared['ok'], prepared
    plan_id = prepared['plan_id']
    assert call('GET', f'plans/{plan_id}')[1]['source']['digest']
    assert call('GET', 'executions')[1]['total'] == 0
    status, execution = call('POST', f'plans/{plan_id}/approve', {'idempotency_key': 'first'})
    assert status == 202, execution
    assert call('POST', f'plans/{plan_id}/approve', {'idempotency_key': 'second'})[1]['id'] == execution['id']
    (project / 'science.py').write_text('raise Exception("mutable source must not execute")')
    worker.tick('demo')
    status, completed = call('GET', f"executions/{execution['id']}")
    assert status == 200 and completed['state'] == 'completed', completed
    assert completed['artifacts'][0]['complete']
    assert call('GET', 'executions?state=succeeded&limit=1')[1]['total'] == 1
    assert call('GET', 'executions?state=failed')[1]['total'] == 0
    attempt = completed['stages'][0]['attempts'][0]['id']
    assert call('GET', f"executions/{execution['id']}/logs?attempt={attempt}&stream=stdout")[0] == 200
    assert call('GET', f"executions/{execution['id']}/logs?attempt=another-execution")[0] == 400


def test_approval_refuses_source_changes_and_missing_key(project):
    _, prepared = call('POST', 'plans', {'workflow': 'local'})
    route = f"plans/{prepared['plan_id']}/approve"
    assert call('POST', route, {})[0] == 400
    (project / 'science.py').write_text('print("changed after review")')
    assert call('POST', route, {'idempotency_key': 'changed'})[0] == 409
    assert call('GET', 'executions')[1]['total'] == 0


def test_invalid_setup_cannot_create_work_and_reads_are_passive(project):
    for setup in ({'workflow': 'missing'}, {'workflow': 'local', 'parameters': []},
                  {'workflow': 'local', 'parameters': {'undeclared': 1}},
                  {'workflow': 'local', 'variant_parameters': []}):
        assert call('POST', 'plans', setup)[0] == 400
    assert store.listing('demo', 'experiment') == []
    assert call('GET', 'executions?limit=invalid&offset=-4')[1]['executions'] == []
    assert call('GET', 'unknown')[0] == 404
    response = http.handle(http.parse_raw('GET', '/api/v1/projects/missing/runner/workflows'))
    assert response.status == 404


def test_document_uses_only_declared_path_and_preserves_version(project):
    (project / 'README.md').write_text('# Workflow documentation\nRead-only project text.\n')
    (project / '.env').write_text('secret-value')
    status, document = call('GET', 'document?path=.env')
    assert status == 200 and '# Workflow documentation' in document['text']
    assert 'secret-value' not in document['text']
    (project / 'README.md').write_text('changed document')
    assert call('GET', 'document?version=' + document['version'])[0] == 409
