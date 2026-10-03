"""HTTP invariants with a tiny local scientific operation and isolated registry."""
import json
from pathlib import Path

import pytest

from controller import http, registry, workspace, workspace_store as store, workspace_worker as worker


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv('UNITY_HPC_DATA', str(tmp_path / 'controller'))
    root = tmp_path / 'project'
    (root / 'unityHPC').mkdir(parents=True)
    (root / 'science.py').write_text('import pathlib,sys\np=pathlib.Path(sys.argv[1]);p.mkdir(parents=True,exist_ok=True);(p/"result.txt").write_text("negative scientific result is complete")\n')
    manifest = {'schema_version': 1, 'application': 'ml', 'default_primitive': 'multi-gpu',
                'default_mode': 'independent', 'source_paths': ['science.py'], 'parameters': {},
                'operations': {'collect': {'argv': ['python3', 'science.py', {'context': 'output_dir'}],
                                          'location': 'controller', 'version': '1'},
                               'analyze': {'argv': ['python3', 'science.py', {'context': 'output_dir'}],
                                           'location': 'controller', 'version': '1',
                                           'outputs': [{'id': 'report', 'path': 'result.txt', 'schema': 'report', 'version': 1}]}},
                'workflows': {'local': {'parameters': [], 'stages': [
                    {'id': 'collect', 'operation': 'collect', 'purpose': 'experiment',
                     'outputs': [{'id': 'result', 'path': 'result.txt', 'schema': 'result', 'version': 1}]}]}},
                'metrics': {}, 'analysis_operations': ['analyze']}
    (root / 'unityHPC/project.json').write_text(json.dumps(manifest))
    registry.attach('demo', root)
    return root


def call(method, route, body=None):
    response = http.handle(http.parse_raw(method, '/api/v1/projects/demo/workspace/' + route,
                                         json.dumps(body).encode() if body is not None else b''))
    return response.status, json.loads(response.body)


def create_plan():
    status, experiment = call('POST', 'experiments', {'workflow': 'local'})
    assert status == 201, experiment
    status, plan = call('POST', f"experiments/{experiment['id']}/plans")
    assert status == 201, plan
    return experiment, plan


def test_autosave_conflict_retains_saved_values_and_has_no_execution(project):
    _, exp = call('POST', 'experiments', {'workflow': 'local'})
    draft = {**exp['draft'], 'name': 'Saved science'}
    assert call('PATCH', f"experiments/{exp['id']}", {'expected_version': 1, 'draft': draft})[0] == 200
    status, error = call('PATCH', f"experiments/{exp['id']}", {'expected_version': 1, 'draft': {**draft, 'name': 'Stale'}})
    assert status == 409
    assert call('GET', f"experiments/{exp['id']}")[1]['name'] == 'Saved science'
    assert call('GET', 'executions')[1]['executions'] == []


def test_exact_review_idempotency_archive_and_local_completion(project):
    exp, plan = create_plan()
    status, execution = call('POST', f"plans/{plan['id']}/dispatch", {'idempotency_key': 'first-click'})
    assert status == 202, execution
    assert call('POST', f"plans/{plan['id']}/dispatch", {'idempotency_key': 'second-click'})[1]['id'] == execution['id']
    assert call('DELETE', f"experiments/{exp['id']}")[0] == 409
    assert call('POST', f"experiments/{exp['id']}/archive")[0] == 200
    assert call('GET', 'experiments')[1]['experiments'] == []
    assert call('GET', 'experiments?archived=true')[1]['experiments'][0]['id'] == exp['id']
    # Later project source edits cannot change approved execution.
    (project / 'science.py').write_text('raise Exception("must not execute mutable source")')
    worker.tick('demo')
    completed = call('GET', f"executions/{execution['id']}")[1]
    assert completed['state'] == 'completed', completed
    assert not completed['stages'][0]['job_ids']
    artifact = call('GET', 'artifacts')[1]['artifacts'][0]
    assert artifact['complete'] and artifact['purpose'] == 'experiment'
    assert (project / artifact['path']).read_text() == 'negative scientific result is complete'
    assert call('POST', f"experiments/{exp['id']}/restore")[0] == 200
    status, repeated = call('POST', f"experiments/{exp['id']}/plans")
    assert status == 201, repeated
    assert any(d['field'] == 'source_digest' for d in repeated['differences'])


def test_source_and_draft_edits_require_new_review(project):
    exp, plan = create_plan()
    (project / 'science.py').write_text('print("changed")')
    assert call('POST', f"plans/{plan['id']}/dispatch", {'idempotency_key': 'changed'})[0] == 409
    assert call('GET', 'executions')[1]['executions'] == []
    _, plan2 = call('POST', f"experiments/{exp['id']}/plans")
    call('PATCH', f"experiments/{exp['id']}", {'expected_version': exp['version'], 'draft': {**exp['draft'], 'name': 'edited'}})
    assert call('POST', f"plans/{plan2['id']}/dispatch", {'idempotency_key': 'changed-draft'})[0] == 409


def test_analysis_revision_preserves_collection_and_prior_report(project):
    _, plan = create_plan()
    call('POST', f"plans/{plan['id']}/dispatch", {'idempotency_key': 'collect'})
    worker.tick('demo')
    artifacts = call('GET', 'artifacts')[1]['artifacts']
    status, analysis = call('POST', 'analysis', {'operation': 'analyze', 'artifact_ids': [artifacts[0]['id']]})
    assert status == 201, analysis
    assert len(analysis['stages']) == 1 and analysis['stages'][0]['operation'] == 'analyze'
    status, execution = call('POST', f"plans/{analysis['id']}/dispatch", {'idempotency_key': 'analyze'})
    assert status == 202, execution
    worker.tick('demo')
    completed = call('GET', f"executions/{execution['id']}")[1]
    assert completed['state'] == 'completed', completed
    _, another = call('POST', 'analysis', {'operation': 'analyze', 'artifact_ids': [artifacts[0]['id']]})
    assert another['analysis_revision'] == 2
    assert another['stages'][0]['output_dir'] != analysis['stages'][0]['output_dir']
    assert (project / analysis['stages'][0]['outputs'][0]['path']).is_file()


def test_custom_script_registers_reusable_workflow(project):
    _, plan = create_plan()
    status, custom = call('POST', f"plans/{plan['id']}/custom-script", {'stage_id': plan['stages'][0]['id'], 'path': 'unityHPC/custom/science.sh'})
    assert status == 201, custom
    assert (project / custom['path']).is_file()
    status, exp = call('POST', 'experiments', {'workflow': custom['workflow']})
    assert status == 201, exp
    status, fresh = call('POST', f"experiments/{exp['id']}/plans")
    assert status == 201, fresh
    call('POST', f"plans/{fresh['id']}/dispatch", {'idempotency_key': 'custom'})
    worker.tick('demo')
    actual = call('GET', f"executions/{fresh['id']}")[1]
    assert actual['state'] == 'completed', actual
    assert not (project / plan['stages'][0]['outputs'][0]['path']).exists()


def test_dependent_custom_script_preserves_prerequisite_graph(project):
    manifest_path = project / 'unityHPC/project.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['workflows']['local']['stages'].append({
        'id': 'dependent', 'operation': 'collect', 'depends_on': ['collect'],
        'inputs': [{'from_stage': 'collect', 'output': 'result', 'schema': 'result', 'version': 1}],
        'outputs': [{'id': 'result', 'path': 'result.txt', 'schema': 'result', 'version': 1}]})
    manifest_path.write_text(json.dumps(manifest))
    _, plan = create_plan()
    dependent = next(s for s in plan['stages'] if s['stage_id'] == 'dependent')
    status, custom = call('POST', f"plans/{plan['id']}/custom-script", {'stage_id': dependent['id'], 'path': 'unityHPC/custom/dependent.sh'})
    assert status == 201, custom
    _, exp = call('POST', 'experiments', {'workflow': custom['workflow']})
    status, fresh = call('POST', f"experiments/{exp['id']}/plans")
    assert status == 201, fresh
    assert [s['stage_id'] for s in fresh['stages']] == ['collect', 'dependent']
    assert fresh['stages'][1]['depends_on'] == [fresh['stages'][0]['id']]
    call('POST', f"plans/{fresh['id']}/dispatch", {'idempotency_key': 'dependent-custom'})
    worker.tick('demo')
    assert call('GET', f"executions/{fresh['id']}")[1]['state'] == 'completed'
