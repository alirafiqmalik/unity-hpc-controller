"""Integration gates over shared contracts and the existing execution coordinator."""
import sqlite3
import json

import pytest

from controller import workspace, workspace_store as store
from controller.workspace_contracts import observation, version_token
from lib import paths
from test_workspace_execution import harness  # noqa: F401
from test_workspace_planner import connected, draft  # noqa: F401
from test_workspace_api import project  # noqa: F401


def test_history_reads_are_passive_and_unknown_store_writes_fail_closed(tmp_data_dir):
    assert store.listing('new-project', 'execution') == []
    assert not (paths.controller_dir() / 'workspaces').exists()
    item = store.create_experiment('old-project', {'workflow': 'local'})
    database = paths.controller_dir() / 'workspaces/old-project.db'
    with sqlite3.connect(database) as con:
        con.execute('PRAGMA user_version=99')
    assert store.read('old-project', 'experiment', item['id']) == item
    with pytest.raises(store.WorkspaceError, match='unsupported'):
        store.update_experiment('old-project', item['id'], {'expected_version': 1, 'draft': item['draft']})
    with sqlite3.connect(database) as con:
        assert con.execute('PRAGMA user_version').fetchone()[0] == 99


def test_observation_age_is_not_reset_and_schema_version_is_not_record_version():
    result = observation('ledger', '2000-01-01T00:00:00Z')
    assert result['state'] == 'stale'
    assert result['observed_at'] == '2000-01-01T00:00:00Z'
    assert observation('remote', None, availability='unavailable')['state'] == 'unavailable'
    assert version_token({'id': 'draft', 'version': 3}) == 3
    assert version_token({'id': 'a'}) != version_token({'id': 'b'})


def test_checked_output_recovery_keeps_failed_producer_and_new_dependents(harness):
    h = harness
    _, plan, execution = h.start(draft(variant_parameters={}, stages=['t1', 't2']))
    h.tick()
    h.finish_jobs(plan, {h.execution(execution['id'])['stages'][0]['job_ids'][0]: 'FAILED'})
    h.tick()
    original = h.execution(execution['id'])
    assert original['stages'][0]['state'] == 'failed'
    recovered = workspace.recovery('study', execution['id'], {
        'stage_ids': [plan['stages'][0]['id']], 'mode': 'checked-outputs'})
    assert [s['stage_id'] for s in recovered['stages']] == ['t2']
    assert recovered['artifacts'][0]['stage_id'] == plan['stages'][0]['id']
    workspace.dispatch_plan('study', recovered['id'], 'checked-output-approval')
    after = h.execution(execution['id'])
    assert after['stages'][0]['state'] == 'failed'
    assert after['stages'][1]['continued_by'] == recovered['id']
    assert recovered['stages'][0]['output_dir'] != plan['stages'][1]['output_dir']


def test_replacement_rejects_active_writer_and_freezes_resource_difference(harness):
    h = harness
    _, plan, execution = h.start()
    h.tick()
    body = {'stage_ids': [plan['stages'][0]['id']], 'mode': 'replace',
            'resources': {'t1': {'walltime': '00:10:00'}}}
    with pytest.raises(store.Conflict, match='accepted'):
        workspace.recovery('study', execution['id'], body)
    h.finish_jobs(plan, {h.execution(execution['id'])['stages'][0]['job_ids'][0]: 'FAILED'})
    h.tick()
    replacement = workspace.recovery('study', execution['id'], body)
    assert replacement['stages'][0]['resources']['walltime'] == '00:10:00'
    assert store.read('study', 'plan', plan['id'])['stages'][0]['resources']['walltime'] != '00:10:00'
    approved = workspace.dispatch_plan('study', replacement['id'], 'replacement')
    assert approved['stages'][0]['attempts'][0]['previous_attempt_id'] == execution['stages'][0]['attempts'][0]['id']


def test_remote_bundle_uses_frozen_artifact_members_after_live_bytes_change(tmp_path, monkeypatch):
    import hashlib
    import io
    import tarfile
    from controller import workspace_dispatch as transport
    source = tmp_path / '.unity-workspace/plans/plan-a/source'
    source.mkdir(parents=True)
    (source / 'science.py').write_text('print(1)')
    frozen = tmp_path / '.unity-workspace/artifacts/artifact-a/version-a/records.jsonl'
    frozen.parent.mkdir(parents=True)
    frozen.write_bytes(b'{"condition":"reviewed"}\n')
    live = tmp_path / '.unity-workspace/outputs/old/v/stage/records.jsonl'
    live.parent.mkdir(parents=True)
    live.write_bytes(b'{"condition":"changed"}\n')
    record = {'path': str(live.relative_to(tmp_path)), 'frozen_path': str(frozen.relative_to(tmp_path)),
              'sha256': hashlib.sha256(frozen.read_bytes()).hexdigest()}
    def fake_ssh(argv, **kwargs):
        with tarfile.open(fileobj=io.BytesIO(kwargs['input']), mode='r:gz') as bundle:
            assert record['path'] not in bundle.getnames()
            assert bundle.extractfile(record['frozen_path']).read() == frozen.read_bytes()
        return type('Result', (), {'returncode': 0})()
    monkeypatch.setattr(transport.subprocess, 'run', fake_ssh)
    transport.stage_bundle({'path': str(tmp_path), 'remote_dir': '/fixture', 'unity_host': 'fixture'},
                           {'id': 'plan-a', 'artifacts': [{'files': [record]}]})


def test_operation_only_analysis_cannot_bypass_declared_schema(project):
    from controller import workspace_worker
    exp = workspace.create('demo', {'workflow': 'local'})
    plan = workspace.plan('demo', exp['id'])
    workspace.dispatch_plan('demo', plan['id'], 'collection')
    workspace_worker.tick('demo')
    artifact = store.listing('demo', 'artifact')[0]
    path = project / 'unityHPC/project.json'
    manifest = json.loads(path.read_text())
    manifest['analyses'] = {'scientific': {'operation': 'analyze', 'input_schema': 'different', 'input_version': 1}}
    path.write_text(json.dumps(manifest))
    with pytest.raises(store.Conflict, match='incompatible'):
        workspace.analysis('demo', {'operation': 'analyze', 'artifact_ids': [artifact['id']]})
    manifest['analyses']['second'] = dict(manifest['analyses']['scientific'])
    path.write_text(json.dumps(manifest))
    with pytest.raises(store.WorkspaceError, match='explicit analysis'):
        workspace.analysis('demo', {'operation': 'analyze', 'artifact_ids': [artifact['id']]})
    assert len(store.listing('demo', 'execution')) == 1


def test_concurrent_analysis_revisions_are_unique(project):
    from concurrent.futures import ThreadPoolExecutor
    from controller import workspace_worker
    exp = workspace.create('demo', {'workflow': 'local'})
    plan = workspace.plan('demo', exp['id'])
    workspace.dispatch_plan('demo', plan['id'], 'collection')
    workspace_worker.tick('demo')
    artifact = store.listing('demo', 'artifact')[0]
    with ThreadPoolExecutor(max_workers=2) as pool:
        plans = list(pool.map(lambda _: workspace.analysis('demo', {'operation': 'analyze', 'artifact_ids': [artifact['id']]}), range(2)))
    assert {p['analysis_revision'] for p in plans} == {1, 2}
    first, second = sorted(plans, key=lambda p: p['analysis_revision'])
    assert first['predecessor_plan_id'] is None
    assert second['predecessor_plan_id'] == first['id']
    assert second['source_executions'] == [plan['id']]
    assert len({p['stages'][0]['output_dir'] for p in plans}) == 2
    assert len(store.listing('demo', 'execution')) == 1


def test_checkpoint_fence_releases_only_after_observed_stop(project):
    exp = workspace.create('demo', {'workflow': 'local'})
    plan = workspace.plan('demo', exp['id'])
    plan['stages'][0]['resume_from'] = 'checked-checkpoint'
    workspace._seal_plan(project / '.unity-workspace/plans' / plan['id'], plan)
    prior = {'id': 'previous-resume', 'plan_id': 'previous-plan', 'stages': [{'id': 'old-stage', 'state': 'accepted', 'resume_from': 'checked-checkpoint'}]}
    with store.transaction('demo') as con:
        store.put(con, 'plan', plan)
        store.put(con, 'execution', prior)
    with pytest.raises(store.Conflict, match='active resume'):
        workspace.dispatch_plan('demo', plan['id'], 'new-resume')
    prior['stages'][0]['state'] = 'cancelled'
    with store.transaction('demo') as con:
        store.put(con, 'execution', prior)
    assert workspace.dispatch_plan('demo', plan['id'], 'new-resume')['id'] == plan['id']
