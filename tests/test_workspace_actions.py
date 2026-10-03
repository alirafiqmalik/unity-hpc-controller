"""Exact management scopes use fake schedulers, never live cluster workloads."""
import pytest
from controller import workspace_actions as actions, workspace_store as store, workspace_worker as worker
from controller.workspace_contracts import version_token
from test_workspace_execution import harness
from test_workspace_planner import connected, draft


def preview(h, ex, stage_ids=None, **extra):
    current = h.execution(ex['id'])
    return actions.prepare('study', {'execution_id': ex['id'], 'expected_version': version_token(current),
                           'stage_ids': stage_ids or [current['stages'][0]['id']], **extra})


def apply(value, key='cancel-one'):
    return actions.apply('study', value['id'], {'expected_version': value['version'], 'review_digest': value['review_digest'], 'idempotency_key': key})


class FakeScheduler:
    version = 'fixture-1'
    def __init__(self):
        self.calls = []; self.running = False; self.refuse = set(); self.race = False
    def capabilities(self):
        return {'cancel': {'supported': True, 'exact_array_tasks': True}, 'pending-change': {'supported': True, 'fields': ['walltime'], 'exact_array_tasks': True}}
    def observe(self, target):
        return {'authoritative': True, 'token': 'running' if self.running else 'pending', 'state': 'RUNNING' if self.running else 'PENDING'}
    def apply(self, kind, target, proposed, token):
        if self.race:
            return {'state': 'rejected', 'reason': 'State changed at scheduler boundary'}
        self.calls.append((kind, [j['job_id'] for j in target['jobs']], proposed))
        if target['id'] in self.refuse:
            return {'state': 'rejected', 'reason': 'Fixture permission refusal'}
        return {'state': 'accepted', 'reason': 'Acknowledged; termination is not yet observed'}


def test_waiting_cancel_fences_dependents_without_dispatch(harness):
    h = harness; _, _, ex = h.start(draft(variant_parameters={}, stages=['t1','t2','analyze']))
    value = preview(h, ex); operation = apply(value)
    assert operation['state'] == 'succeeded'
    h.tick()
    assert h.calls == []
    assert {s['state'] for s in h.execution(ex['id'])['stages']} == {'cancelled'}
    assert apply(value)['id'] == operation['id']
    with pytest.raises(store.Conflict, match='different'):
        actions.apply('study',value['id'],{'idempotency_key':'cancel-one','expected_version':1,'review_digest':'changed'})


def test_unsupported_exact_scope_fails_closed(harness):
    h = harness; _, _, ex = h.start(); h.tick()
    with pytest.raises(store.Conflict, match='capability gate'):
        preview(h, ex)


def test_partial_cancel_preserves_receipts_and_never_broadens(harness, monkeypatch):
    h = harness; _, _, ex = h.start(draft(variant_parameters={'model':['small','large']}, stages=['t1'], variant_concurrency=4)); h.tick()
    fake = FakeScheduler(); monkeypatch.setattr(actions,'get_adapter',lambda slug:fake)
    ids = [s['id'] for s in h.execution(ex['id'])['stages']]; fake.refuse.add(ids[1])
    value = preview(h, ex, ids); result = apply(value)
    assert result['state'] == 'partial'
    assert [t['state'] for t in result['targets']] == ['accepted','rejected']
    assert len(fake.calls) == 2 and all(len(call[1]) == 1 for call in fake.calls)
    assert all(s['state'] == 'accepted' for s in h.execution(ex['id'])['stages'])


def test_pending_running_race_rejects_and_plan_stays_frozen(harness, monkeypatch):
    h = harness; _, plan, ex = h.start(); h.tick()
    fake = FakeScheduler(); monkeypatch.setattr(actions,'get_adapter',lambda slug:fake)
    value = preview(h, ex, kind='pending-change', proposed={'walltime':'00:10:00'})
    assert 'earlier start' in value['warnings'][0]
    fake.race = True
    result = apply(value)
    assert result['state'] == 'failed' and not fake.calls
    assert store.read('study','plan',plan['id']) == plan


def test_scope_race_requires_review(harness):
    h = harness; _, _, ex = h.start(); value = preview(h, ex)
    h.tick()
    with pytest.raises(store.Conflict, match='scope changed'):
        apply(value)


def test_fence_survives_stale_worker_save(harness):
    h = harness; _, _, ex = h.start(); stale = h.execution(ex['id'])
    apply(preview(h, ex))
    stage = stale['stages'][0]
    worker._change('study', stale, stage, 'submitting')
    assert stage['state'] == 'cancelled'
    h.tick(); assert not h.calls


def test_acknowledged_cancel_blocks_overlapping_change_until_terminal(harness, monkeypatch):
    h = harness; _, plan, ex = h.start(); h.tick()
    fake = FakeScheduler(); monkeypatch.setattr(actions, 'get_adapter', lambda slug: fake)
    action = apply(preview(h, ex))
    assert action['state'] == 'applying'
    next_review = preview(h, ex, kind='pending-change', proposed={'walltime': '00:10:00'})
    with pytest.raises(store.Conflict, match='overlapping'):
        apply(next_review, 'overlapping')
    from lib import campaign
    campaign.apply_states(h.root, plan['id'], {r['job_id']: {'state': 'CANCELLED'} for r in campaign.jobs(h.root, plan['id'])})
    h.tick()
    reconciled = actions.reconcile('study', action['id'])
    assert reconciled['state'] == 'succeeded'
    assert reconciled['targets'][0]['observed_state'] == 'cancelled'


def test_active_local_cancel_uses_owned_process_and_retains_separate_streams(harness):
    import os
    import subprocess
    import sys
    import time
    from test_workspace_local import _running, _supervisor
    from controller import workspace_local as local
    h = harness; _, ex, attempt = _running(h)
    code = 'import sys,time;print("out",flush=True);print("err",file=sys.stderr,flush=True);time.sleep(30)'
    process = subprocess.Popen(_supervisor(h, attempt, [sys.executable, '-c', code]), start_new_session=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        receipt, _ = local.receipt_paths(h.root, attempt)
        deadline = time.monotonic() + 5
        while not receipt.with_suffix('.process.json').exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert receipt.with_suffix('.process.json').exists()
        operation = apply(preview(h, ex))
        assert operation['state'] == 'applying'
        process.wait(timeout=3)
        deadline = time.monotonic() + 3
        while local.interrupted_receipt(h.root, attempt) is None and time.monotonic() < deadline:
            time.sleep(0.01)
        h.tick()
        assert h.execution(ex['id'])['stages'][0]['state'] == 'cancelled'
        assert receipt.with_suffix('.stdout').exists() and receipt.with_suffix('.stderr').exists()
        assert actions.reconcile('study', operation['id'])['state'] == 'succeeded'
    finally:
        if process.poll() is None:
            import signal
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)


def test_unknown_acceptance_fence_reconciles_then_requires_new_exact_review(harness, monkeypatch):
    from lib import campaign
    from controller import workspace
    h = harness; _, plan, ex = h.start()
    h.behavior[plan['stages'][0]['id']] = 'uncertain'; h.tick()
    operation = apply(preview(h, ex))
    assert operation['state'] == 'uncertain'
    stage = h.execution(ex['id'])['stages'][0]
    campaign.record(h.root, plan['id'], '4040', stage['attempts'][0]['exp'])
    workspace.reconcile('study', ex['id'])
    reconciled = actions.reconcile('study', operation['id'])
    assert reconciled['targets'][0]['state'] == 'rejected'
    assert reconciled['targets'][0]['requires_new_review']
    fake = FakeScheduler(); monkeypatch.setattr(actions, 'get_adapter', lambda slug: fake)
    reviewed = preview(h, ex)
    followup = apply(reviewed, 'new-exact-job')
    assert followup['state'] == 'applying'
    assert fake.calls[0][1] == ['4040']


def test_one_array_child_never_expands_to_sibling(harness, monkeypatch):
    from lib import campaign
    h = harness; _, plan, ex = h.start(); h.tick()
    current = h.execution(ex['id']); stage = current['stages'][0]
    for job in ('8080_1', '8080_2'):
        campaign.record(h.root, plan['id'], job, stage['attempts'][0]['exp'])
    stage['job_ids'] = ['8080_1','8080_2']; stage['attempts'][0]['job_ids'] = stage['job_ids']
    with store.transaction('study') as con: store.put(con,'execution',current)
    fake = FakeScheduler(); monkeypatch.setattr(actions,'get_adapter',lambda slug:fake)
    value = preview(h, ex, job_ids=['8080_1'])
    assert [j['job_id'] for j in value['targets'][0]['jobs']] == ['8080_1']
    apply(value)
    assert fake.calls[0][1] == ['8080_1']


def test_unchanged_worker_poll_keeps_review_version_valid(harness, monkeypatch):
    h = harness; _, _, ex = h.start(); h.tick()
    fake = FakeScheduler(); monkeypatch.setattr(actions,'get_adapter',lambda slug:fake)
    # One observation pass attaches ledger detail; later identical polls are no-ops.
    h.tick()
    value = preview(h, ex)
    h.tick(); h.tick()
    assert apply(value)['state'] == 'applying'


def test_refused_cancellation_never_dispatches_replacement(harness, monkeypatch):
    from controller import workspace
    h = harness; _, plan, execution = h.start(); h.tick()
    fake=FakeScheduler(); fake.refuse.add(plan['stages'][0]['id'])
    monkeypatch.setattr(actions,'get_adapter',lambda slug:fake)
    cancelled=apply(preview(h,execution))
    assert cancelled['state']=='failed' and cancelled['targets'][0]['state']=='rejected'
    with pytest.raises(store.Conflict,match='accepted'):
        workspace.recovery('study',execution['id'],{'stage_ids':[plan['stages'][0]['id']],'mode':'replace','resources':{'t1':{'walltime':'00:10:00'}}})
    assert len(store.listing('study','execution'))==1 and len(h.calls)==1
    assert h.execution(execution['id'])['stages'][0]['state']=='accepted'


def test_failed_replacement_does_not_restart_cancelled_original(harness, monkeypatch):
    from controller import workspace
    from lib import campaign
    h = harness; _, plan, execution = h.start(); h.tick()
    fake=FakeScheduler(); monkeypatch.setattr(actions,'get_adapter',lambda slug:fake)
    receipt=apply(preview(h,execution)); assert receipt['state']=='applying'
    campaign.apply_states(h.root,plan['id'],{r['job_id']:{'state':'CANCELLED'} for r in campaign.jobs(h.root,plan['id'])})
    h.tick(); actions.reconcile('study',receipt['id'])
    replacement=workspace.recovery('study',execution['id'],{'stage_ids':[plan['stages'][0]['id']],'mode':'replace','resources':{'t1':{'walltime':'00:10:00'}}})
    approved=workspace.dispatch_plan('study',replacement['id'],'replacement-after-stop')
    h.behavior[replacement['stages'][0]['id']]='reject'; h.tick(); h.tick()
    assert h.execution(approved['id'])['stages'][0]['state']=='rejected'
    assert h.execution(execution['id'])['stages'][0]['state']=='cancelled'
    assert len(h.calls)==2


def test_pending_array_child_change_retains_sibling_effective_resources(harness, monkeypatch):
    from lib import campaign
    h = harness; _, plan, ex = h.start(); h.tick()
    current=h.execution(ex['id']); stage=current['stages'][0]
    for job in ('9090_1','9090_2'): campaign.record(h.root,plan['id'],job,stage['attempts'][0]['exp'])
    stage['job_ids']=['9090_1','9090_2']; stage['attempts'][0]['job_ids']=stage['job_ids']
    with store.transaction('study') as con:store.put(con,'execution',current)
    fake=FakeScheduler(); monkeypatch.setattr(actions,'get_adapter',lambda slug:fake)
    first=preview(h,ex,job_ids=['9090_1'],kind='pending-change',proposed={'walltime':'00:10:00'})
    apply(first)
    sibling=preview(h,ex,job_ids=['9090_2'],kind='pending-change',proposed={'walltime':'00:20:00'})
    assert sibling['targets'][0]['resources']['walltime']==plan['stages'][0]['resources']['walltime']
    saved=h.execution(ex['id'])['stages'][0]
    assert saved['effective_resources_by_job']['9090_1']['walltime']=='00:10:00'
    assert '9090_2' not in saved['effective_resources_by_job']
