"""Actual workspace routes preserve observation age independently of polling."""
import json
import hashlib

from controller import http, workspace_store as store
from controller.workspace_contracts import observation, response_metadata, version_token
from tests.test_workspace_settings import project  # noqa: F401


def get(route):
    response = http.handle(http.parse_raw('GET', '/api/v1/projects/demo/workspace/' + route))
    assert response.status == 200, response.body
    def reject_constant(value):
        raise AssertionError('API emitted invalid JSON constant: ' + value)
    return json.loads(response.body, parse_constant=reject_constant)


def test_read_routes_keep_old_observations_and_stable_versions(project, monkeypatch):
    old = '2000-01-01T00:00:00+00:00'
    with store.transaction('demo') as con:
        store.put(con, 'artifact', {'id': 'old-evidence', 'schema': 'fixture', 'version': 1,
                  'content_version': 'content-a', 'source_digest': 'source-a', 'purpose': 'experiment',
                  'complete': True, 'files': [], 'observed_at': old, 'availability': 'remote'})
        store.put(con, 'connection-check', {'id': 'old-check', 'facts': [
            {'id': 'ssh_access', 'status': 'ready', 'source': 'SSH probe', 'observed_at': old,
             'expires_at': '2000-01-01T00:01:00+00:00'}]})
    monkeypatch.setattr(store, 'now', lambda: '2030-01-01T00:00:00+00:00')
    first = {route: get(route) for route in ('results', 'files', 'settings', 'overview')}
    monkeypatch.setattr(store, 'now', lambda: '2030-01-01T00:00:01+00:00')
    second = {route: get(route) for route in first}
    for route in first:
        a, b = first[route]['response_metadata'], second[route]['response_metadata']
        assert a['version'] == b['version'], route
        assert a['read_at'] != b['read_at']
        assert 'source_revision' in b
        assert all(set(('source', 'observed_at', 'stale_after', 'availability', 'state')) <= set(o)
                   for o in b['observations'].values())
    artifact = second['results']['response_metadata']
    assert artifact['entities']['/artifacts/0']['version'] == 'content-a'
    assert artifact['entities']['/artifacts/0']['source_revision'] == 'source-a'
    assert artifact['observations']['artifacts/artifacts/0']['observed_at'] == old
    assert artifact['observations']['artifacts/artifacts/0']['state'] == 'stale'
    probes = second['settings']['response_metadata']['observations'].values()
    assert any(o['source'] == 'SSH probe' and o['observed_at'] == old and o['state'] == 'stale' for o in probes)
    assert second['files']['response_metadata']['source_revision'] == 'unknown'
    assert second['files']['response_metadata']['observations']['filesystem']['observed_at'] == '2030-01-01T00:00:01+00:00'
    assert second['settings']['version'] == 0  # Existing optimistic contract stays intact.
    assert store.read('demo', 'artifact', 'old-evidence')['observed_at'] == old


def test_unknown_evidence_remains_unknown_and_reads_do_not_create_store(project):
    from lib import paths
    database = paths.controller_dir() / 'workspaces/demo.db'
    assert not database.exists()
    for route in ('results', 'files', 'settings', 'overview'):
        result = get(route)
        assert result['response_metadata']['read_at']
    assert not database.exists()
    metadata = get('results')['response_metadata']
    assert metadata['source_revision'] == 'unknown'
    assert metadata['observations']['artifacts']['observed_at'] is None
    assert metadata['observations']['artifacts']['availability'] == 'unknown'


def test_connection_reports_its_known_declaration_source_revision(project):
    result = get('connection')
    assert result['digest']
    assert result['response_metadata']['source_revision'] == result['digest']


def test_projection_clock_does_not_mask_entity_changes_or_reset_scheduler_age():
    payload = {'id': 'execution-a', 'version': 4, 'source_revision': 'frozen-source',
               'scheduler_observation': {'checked_at': '2000-01-01T00:00:00+00:00'}, 'state': 'active'}
    a = response_metadata(payload, 'executions/execution-a', '2030-01-01T00:00:00+00:00')
    b = response_metadata(payload, 'executions/execution-a', '2030-01-02T00:00:00+00:00')
    assert a['version'] == b['version']
    assert a['entities']['/']['version'] == 4
    assert b['observations']['scheduler']['observed_at'] == '2000-01-01T00:00:00+00:00'
    assert b['observations']['scheduler']['state'] == 'stale'
    changed = response_metadata({**payload, 'state': 'completed'}, 'executions/execution-a', b['read_at'])
    assert changed['version'] != b['version']
    legacy = {'id': 'plan-a', 'source': {'digest': 'frozen'}}
    assert version_token({**legacy, 'response_metadata': a}) == version_token(legacy)


def test_scientific_record_metadata_names_do_not_become_service_observations(project):
    data = {'id': 'scientific-item', 'source': {'digest': {'arbitrary': 'value'}},
            'observed_at': '2000-01-01T00:00:00Z', 'stale_after': 'oops', 'value': 3}
    (project / 'arbitrary.json').write_text(json.dumps(data))
    result = get('files/preview?path=arbitrary.json')
    assert result['structured']['stale_after'] == 'oops'
    metadata = result['response_metadata']
    assert metadata['source_revision'] == 'unknown'
    assert '/structured' not in metadata['entities']
    assert not any('structured' in key for key in metadata['observations'])
    changed = response_metadata({**result, 'structured': {**data, 'observed_at': 'different scientific value'}}, 'files/preview', metadata['read_at'])
    assert changed['version'] != metadata['version']
    for invalid in ('oops', None, True, -1, float('nan'), float('inf'), 10**1000):
        assert observation('fixture', data['observed_at'], invalid)['availability'] == 'unknown'


def test_json_artifact_download_preserves_exact_bytes_without_response_metadata(project):
    data = b'{ "scientific_value": 3 }\n'
    (project / 'saved.json').write_bytes(data)
    with store.transaction('demo') as con:
        store.put(con, 'artifact', {'id': 'saved', 'files': [
            {'path': 'saved.json', 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}]})
    response = http.handle(http.parse_raw('GET', '/api/v1/projects/demo/workspace/artifacts/saved/file?path=saved.json'))
    assert response.status == 200
    assert response.content_type == 'application/json'
    assert response.body == data
