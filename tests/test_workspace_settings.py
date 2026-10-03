"""Maintenance faults, protected bytes and exact optimistic updates in isolation."""
import json
import sqlite3
from pathlib import Path

import pytest

from controller import registry, workspace_settings as settings, workspace_store as store
from controller.workspace_connection import load_connection
from lib import campaign, paths


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv('UNITY_HPC_DATA', str(tmp_path / 'data'))
    root = tmp_path / 'project'
    (root / 'unityHPC').mkdir(parents=True)
    (root / 'science.py').write_text('print("science")')
    (root / 'unityHPC/fetch.sh').write_text('custom fetch preserved\n')
    (root / 'unityHPC/sync.sh').write_text('custom sync preserved\n')
    manifest = {'schema_version': 1, 'source_paths': ['science.py'], 'research_question': 'Original question', 'custom': {'keep': True},
                'parameters': {}, 'operations': {'work': {'argv': ['python3', 'science.py'], 'location': 'controller'}},
                'workflows': {'study': {'stages': [{'id': 'work', 'operation': 'work'}]}}, 'metrics': {}}
    (root / 'unityHPC/project.json').write_text(json.dumps(manifest))
    registry.attach('demo', root, primitive='ml', sync_policy='disabled')
    return root


def preview(action='defaults', patch=None):
    state = settings.snapshot('demo')
    return settings.preview_maintenance('demo', {'action': action, 'patch': patch or {'application': 'ml'},
                'expected_version': state['version'], 'declaration_digest': state['declaration_digest'], 'file_digest': state['file_digest']})


def test_external_edit_conflict_preserves_unknown_fields_and_drafts(project):
    draft = store.create_experiment('demo', {'workflow': 'study', 'resources': {}})
    p = preview()
    path = project / 'unityHPC/project.json'
    manifest = json.loads(path.read_text()); manifest['external'] = 'keep'; path.write_text(json.dumps(manifest))
    with pytest.raises(store.Conflict):
        settings.apply_maintenance('demo', p['id'], {'idempotency_key': 'conflict'})
    assert json.loads(path.read_text())['external'] == 'keep'
    p = preview()
    action = settings.apply_maintenance('demo', p['id'], {'idempotency_key': 'save'})
    assert action['state'] == 'succeeded'
    assert json.loads(path.read_text())['custom'] == {'keep': True}
    saved = store.read('demo', 'experiment', draft['id'])
    assert saved['draft']['resources']['work']['cpus'] == 1
    assert saved['version'] == 2 and saved['draft']['defaults_digest']
    assert registry.get('demo')['sync_policy'] == 'disabled'
    assert (project / 'unityHPC/fetch.sh').read_text() == 'custom fetch preserved\n'
    assert settings.apply_maintenance('demo', p['id'], {'idempotency_key': 'save'})['id'] == action['id']


@pytest.mark.parametrize('step', ['backup', 'drafts', 'declaration', 'registry', 'metadata'])
def test_each_activation_fault_reconciles_exactly_once(project, step):
    p = preview('migration')
    def fault(current):
        if current == step:
            raise RuntimeError('injected crash')
    with pytest.raises(RuntimeError):
        settings.apply_maintenance('demo', p['id'], {'idempotency_key': 'activate'}, fault=fault)
    action = store.listing('demo', 'maintenance-action')[0]
    assert action['state'] == 'recovery_required'
    assert settings.maintenance_blocked('demo')
    final = settings.reconcile_maintenance('demo', action['id'])
    assert final['state'] == 'succeeded'
    assert len(final['completed_steps']) == len(set(final['completed_steps'])) == 5
    assert registry.get('demo')['primitive'] == 'ml'
    assert json.loads((project / 'unityHPC/project.json').read_text())['default_mode'] == 'coordinated'
    assert settings.snapshot('demo')['version'] == 1


def test_active_uncertain_scheduled_and_legacy_jobs_block_detach(project):
    with store.transaction('demo') as con:
        store.put(con, 'execution', {'id': 'plan-active', 'stages': [{'id': 's', 'state': 'uncertain'}]})
        store.put(con, 'schedule', {'id': 'schedule-one', 'state': 'scheduled'})
        store.put(con, 'operation', {'id': 'cancel-one', 'state': 'uncertain'})
    campaign.record(project, 'legacy', '123', 'old', 'gpu')
    blocked = settings.blockers('demo')
    assert {'plan-active:s', 'schedule-one', 'cancel-one', '123'} <= {b['id'] for b in blocked}
    p = preview('detach')
    assert p['state'] == 'blocked'
    with pytest.raises(store.Conflict):
        settings.apply_maintenance('demo', p['id'], {'idempotency_key': 'detach'})


def test_rollback_preserves_history_and_refuses_new_records(project):
    p = preview('migration')
    action = settings.apply_maintenance('demo', p['id'], {'idempotency_key': 'migration'})
    store.create_experiment('demo', {'workflow': 'study'})
    before = (project / 'unityHPC/project.json').read_bytes()
    with pytest.raises(store.Conflict, match='Post-migration'):
        settings.rollback('demo', action['id'])
    assert (project / 'unityHPC/project.json').read_bytes() == before
    assert store.listing('demo', 'experiment')


def test_checked_backup_restores_declaration(project):
    before = (project / 'unityHPC/project.json').read_bytes()
    p = preview('migration'); action = settings.apply_maintenance('demo', p['id'], {'idempotency_key': 'migration'})
    assert settings.rollback('demo', action['id'])['state'] == 'rolled_back'
    assert (project / 'unityHPC/project.json').read_bytes() == before


def test_unknown_store_schema_still_shows_settings(project):
    with store.transaction('demo'):
        pass
    db = paths.controller_dir() / 'workspaces/demo.db'
    with sqlite3.connect(db) as con:
        con.execute('PRAGMA user_version=99')
    assert settings.snapshot('demo')['project']['slug'] == 'demo'


def test_probe_partial_failure_and_timeout_are_independent(project):
    import subprocess
    from types import SimpleNamespace
    registry.update('demo', remote_dir='/work/example')
    def fake(argv, **kwargs):
        assert argv[0] == 'ssh' and kwargs['timeout'] == 8
        if argv[-1] == 'true':
            return SimpleNamespace(returncode=255)
        if 'test -d' in argv[-1]:
            raise subprocess.TimeoutExpired(argv, 8)
        return SimpleNamespace(returncode=0)
    result = settings.check_connection('demo', {'remote': True}, probe=fake)
    facts = {f['id']: f for f in result['facts']}
    assert result['state'] == 'degraded'
    assert facts['ssh_access']['status'] == 'unavailable'
    assert facts['remote_root']['deadline_seconds'] == 8
    assert facts['scheduler_commands']['status'] == 'ready'


def test_proposed_connection_requires_its_own_fresh_probe(project):
    from types import SimpleNamespace
    (project / 'unityHPC/run.sh').write_text('#!/bin/sh\n')
    patch = {'unity_host': 'new-alias', 'remote_dir': '/work/new-root'}
    with pytest.raises(store.WorkspaceError, match='fresh read-only probe'):
        preview('connection', patch)
    check = settings.check_connection('demo', {'remote': True, 'proposed': patch}, probe=lambda *_args, **_kwargs: SimpleNamespace(returncode=0))
    assert check['state'] == 'ready'
    p = preview('connection', patch)
    settings.apply_maintenance('demo', p['id'], {'idempotency_key': 'activate-new-alias'})
    assert registry.get('demo')['unity_host'] == 'new-alias'


def test_relocation_requires_history_and_preserves_origin_identity(project, tmp_path):
    import shutil
    campaign.record(project, 'old', '123', 'historical', 'gpu')
    campaign.apply_states(project, 'old', {'123': {'state': 'COMPLETED'}})
    target = tmp_path / 'relocated'
    shutil.copytree(project, target)
    p = preview('relocate', {'path': str(target)})
    settings.apply_maintenance('demo', p['id'], {'idempotency_key': 'move'})
    assert registry.get('demo')['path'] == str(target)
    assert campaign.jobs(target, 'old')[0]['job_id'] == '123'
    assert project.exists()


def test_explicit_adoption_preserves_old_plan_and_rejects_stale_draft(project):
    from controller import workspace
    item=workspace.create('demo',{'workflow':'study'})
    plan=workspace.plan('demo',item['id'])
    p=preview('defaults',{'resource_defaults':{'controller':{'cpus':3}}})
    settings.apply_maintenance('demo',p['id'],{'idempotency_key':'new-defaults'})
    assert store.read('demo','plan',plan['id'])['stages'][0]['resources']['cpus']==1
    assert store.read('demo','experiment',item['id'])['draft']['resources']['work']['cpus']==1
    proposal=settings.adoption('demo',item['id'],{})
    assert proposal['draft']['resources']['work']['cpus']==3
    with pytest.raises(store.Conflict):
        settings.adoption('demo',item['id'],{'apply':True,'expected_version':-1,'declaration_digest':proposal['declaration_digest']})
    adopted=settings.adoption('demo',item['id'],{'apply':True,'expected_version':proposal['expected_version'],'declaration_digest':proposal['declaration_digest']})
    assert adopted['draft']['resources']['work']['cpus']==3
    new=workspace.create('demo',{'workflow':'study'})
    assert new['draft']['resources']['work']['cpus']==3


@pytest.mark.parametrize('step', ['declaration', 'registry', 'metadata'])
def test_rollback_fault_fences_work_and_reconciles(project, step):
    p=preview('migration');action=settings.apply_maintenance('demo',p['id'],{'idempotency_key':'migrate'})
    def crash(current):
        if current == step:
            raise RuntimeError('rollback crash')
    with pytest.raises(RuntimeError):
        settings.rollback('demo',action['id'],fault=crash)
    assert settings.maintenance_blocked('demo')[0]['phase']=='rollback'
    assert settings.reconcile_maintenance('demo',action['id'])['state']=='rolled_back'
    assert settings.snapshot('demo')['version']==2


def test_backup_contains_exact_artifact_receipt_and_ledger_bytes(project):
    outputs=project/'.unity-workspace/outputs/old';outputs.mkdir(parents=True);(outputs/'report').write_bytes(b'old evidence')
    receipts=project/'.unity-workspace/receipts';receipts.mkdir();(receipts/'attempt.json').write_text('{}')
    p=preview('migration');action=settings.apply_maintenance('demo',p['id'],{'idempotency_key':'migrate'})
    assert '.unity-workspace/outputs/old/report' in action['backup']['files']
    assert '.unity-workspace/receipts/attempt.json' in action['backup']['files']


def test_missing_original_root_relocates_from_retained_plan_identity(project, tmp_path):
    import shutil
    from controller import workspace
    experiment=workspace.create('demo',{'workflow':'study'})
    plan=workspace.plan('demo',experiment['id'])
    target=tmp_path/'retained-project'
    shutil.copytree(project,target)
    shutil.rmtree(project)
    state=settings.snapshot('demo')
    p=settings.preview_maintenance('demo',{'action':'relocate','patch':{'path':str(target)},'expected_version':state['version'],'declaration_digest':state['declaration_digest']})
    assert p['unavailable_root'] and p['state']=='ready'
    settings.apply_maintenance('demo',p['id'],{'idempotency_key':'recover-missing-root'})
    assert registry.get('demo')['path']==str(target)
    assert store.read('demo','plan',plan['id'])['source']==plan['source']
    assert (target/'.unity-workspace/plans'/plan['id']/'plan.json').is_file()
