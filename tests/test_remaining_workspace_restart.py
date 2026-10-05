"""Composition receipts and scheduled approval races use the shared coordinator."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import threading

import pytest

from controller import workspace, workspace_local as local, workspace_schedules as schedules
from controller import workspace_store as store, workspace_worker as worker
from controller.workspace_contracts import version_token
from test_workspace_execution import harness  # noqa: F401
from test_workspace_planner import connected, draft, write_manifest  # noqa: F401
from test_workspace_schedules import setup_schedule


def test_composed_graph_restart_consumes_receipt_and_preserves_four_variants(harness, monkeypatch):
    h = harness
    h.manifest['required_features'] = {'composition': 1}
    for name, op in h.manifest['operations'].items():
        op.update(location='controller', write_scope='output_dir', timeout_seconds=30,
                  input_ports={} if name == 'collect' else {'corpus': {'schema': 'records', 'version': 1, 'cardinality': 'many', 'purposes': ['experiment']}},
                  output_ports={'corpus' if name == 'collect' else 'report': {'schema': 'records' if name == 'collect' else 'report', 'version': 1, 'path': 'record.json', 'cardinality': 'one'}})
    write_manifest(h.root, h.manifest)
    graph = {'nodes': [{'id': 'collection', 'operation': 'collect', 'operation_version': '1', 'scope': 'per_variant'},
                       {'id': 'analysis', 'operation': 'analyze', 'operation_version': '1', 'scope': 'reduce_selected'}],
             'edges': [{'from_node': 'collection', 'output': 'corpus', 'to_node': 'analysis', 'input': 'corpus'}]}
    item = workspace.create('study', {'workflow': '__composition__', 'draft': draft(workflow='__composition__', graph=graph)})
    plan = workspace.plan('study', item['id'])
    execution = workspace.dispatch_plan('study', plan['id'], 'composed-restart')
    actual = worker.run_local
    calls = []
    def crash_after_receipt(argv, *args, **kwargs):
        calls.append(argv[3])
        result = actual(argv, *args, **kwargs)
        assert result['ok']
        raise KeyboardInterrupt('fixture controller crash after durable local receipt')
    monkeypatch.setattr(worker, 'run_local', crash_after_receipt)
    with pytest.raises(KeyboardInterrupt):
        worker.tick('study')
    first = store.read('study', 'execution', execution['id'])['stages'][0]
    assert first['state'] == 'running'
    receipt_path, _ = local.receipt_paths(h.root, first['attempts'][0]['id'])
    assert json.loads(receipt_path.read_text())['ok']
    output = h.root / plan['stages'][0]['outputs'][0]['path']
    original_hash = hashlib.sha256(output.read_bytes()).hexdigest()
    def continue_once(argv, *args, **kwargs):
        calls.append(argv[3])
        return actual(argv, *args, **kwargs)
    monkeypatch.setattr(worker, 'run_local', continue_once)
    worker.tick('study')
    worker.tick('study')
    final = store.read('study', 'execution', execution['id'])
    assert final['state'] == 'completed'
    assert len(calls) == len(set(calls)) == 5
    assert hashlib.sha256(output.read_bytes()).hexdigest() == original_hash
    assert not h.calls
    artifacts = store.listing('study', 'artifact')
    collected = [a for a in artifacts if a['output_id'] == 'corpus']
    assert len(collected) == 4
    assert {a['parameters']['token_cap'] for a in collected} == {128, 256}
    assert len({a['variant_id'] for a in collected}) == 4
    assert all(not stage['job_ids'] for stage in final['stages'])


@pytest.mark.parametrize('winner', ['due', 'cancel'])
def test_schedule_cancel_and_due_worker_contend_without_false_cancel(harness, monkeypatch, winner):
    _, _, item = setup_schedule(harness)
    entered, release = threading.Event(), threading.Event()
    due = datetime(2030, 1, 1, 12, 30, tzinfo=timezone.utc)
    if winner == 'due':
        actual = schedules._validate
        def hold(*args):
            entered.set()
            assert release.wait(5)
            return actual(*args)
        monkeypatch.setattr(schedules, '_validate', hold)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(schedules.tick, 'study', due)
            try:
                assert entered.wait(5)
                with pytest.raises(store.Conflict, match='due worker'):
                    schedules.update('study', item['id'], {'expected_version': 1}, cancel=True)
            finally:
                release.set()
            future.result(timeout=5)
        current = store.read('study', 'schedule', item['id'])
        assert current['state'] == 'dispatched'
        assert len(store.listing('study', 'execution')) == 1
        with pytest.raises(store.Conflict, match='Dispatch intent'):
            schedules.update('study', item['id'], {'expected_version': current['version']}, cancel=True)
    else:
        actual = store.put
        def hold(con, kind, value):
            result = actual(con, kind, value)
            if kind == 'schedule' and value['state'] == 'cancelled':
                entered.set()
                assert release.wait(5)
            return result
        monkeypatch.setattr(store, 'put', hold)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(schedules.update, 'study', item['id'], {'expected_version': 1}, True)
            try:
                assert entered.wait(5)
                schedules.tick('study', due)
            finally:
                release.set()
            assert future.result(timeout=5)['state'] == 'cancelled'
        schedules.tick('study', due)
        assert not store.listing('study', 'execution')
    assert not harness.calls


def test_scheduled_analysis_rejects_changed_frozen_input_before_dispatch(harness):
    h = harness
    outputs = [{'id': 'report', 'path': 'record.json', 'schema': 'report', 'version': 1}]
    h.manifest['analysis_operations'] = ['analyze']
    h.manifest['operations']['analyze']['outputs'] = outputs
    h.manifest['analyses'] = {'report': {'operation': 'analyze', 'input_schema': 'records', 'input_version': 1, 'outputs': outputs}}
    write_manifest(h.root, h.manifest)
    _, source_plan, _ = h.start()
    h.tick(); h.finish_jobs(source_plan); h.tick()
    artifact = store.listing('study', 'artifact')[0]
    plan = workspace.analysis('study', {'analysis': 'report', 'artifact_ids': [artifact['id']]})
    scheduled = schedules.create('study', {'plan_id': plan['id'], 'expected_version': version_token(plan),
        'approved': True, 'idempotency_key': 'scheduled-analysis', 'timezone': 'UTC', 'earliest_dispatch': '2030-01-01T12:00:00+00:00'})
    before = {e['id'] for e in store.listing('study', 'execution')}
    selected = plan['artifacts'][0]['files'][0]
    (h.root / selected.get('frozen_path', selected['path'])).write_text('changed selected bytes')
    schedules.tick('study', datetime(2030, 1, 1, 12, 30, tzinfo=timezone.utc))
    current = store.read('study', 'schedule', scheduled['id'])
    assert current['state'] == 'blocked'
    assert not current['approval']['active'] and current['invalidated_at']
    assert {e['id'] for e in store.listing('study', 'execution')} == before
    assert len(h.calls) == 1
