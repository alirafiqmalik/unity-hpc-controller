"""One-off windows retain a single approval across restarts and competing workers."""
from datetime import datetime, timedelta, timezone
import pytest
from controller import workspace_schedules as schedules, workspace_store as store, workspace
from controller.workspace_contracts import version_token
from test_workspace_execution import harness
from test_workspace_planner import connected, draft


def setup_schedule(h, earliest='2030-01-01T12:00:00+00:00', **extra):
    item = workspace.create('study', {'workflow':'t1','draft':draft(variant_parameters={},stages=['t1'])})
    plan = workspace.plan('study',item['id'])
    body = {'plan_id':plan['id'],'expected_version':version_token(plan),'approved':True,'idempotency_key':'schedule-intent','timezone':'UTC','earliest_dispatch':earliest,**extra}
    return plan, body, schedules.create('study',body)


def test_schedule_window_and_repeated_workers_create_one_execution(harness):
    h = harness; plan, body, item = setup_schedule(h)
    assert not store.listing('study','execution')
    assert schedules.create('study',body)['id'] == item['id']
    due = datetime(2030,1,1,12,30,tzinfo=timezone.utc)
    schedules.tick('study',due); schedules.tick('study',due)
    assert len(store.listing('study','execution')) == 1
    assert store.read('study','schedule',item['id'])['state'] == 'dispatched'
    assert h.calls == []  # Due dispatch records approved intent, worker performs it.
    h.tick(); assert len(h.calls) == 1


def test_missed_window_never_dispatches_late(harness):
    _, _, item = setup_schedule(harness)
    schedules.tick('study',datetime(2030,1,2,tzinfo=timezone.utc))
    assert store.read('study','schedule',item['id'])['state'] == 'missed'
    assert not store.listing('study','execution')


def test_source_change_blocks_then_expires_without_substitution(harness):
    h = harness; _, _, item = setup_schedule(h)
    (h.root/'science/runner.py').write_text('print("changed")')
    schedules.tick('study',datetime(2030,1,1,12,30,tzinfo=timezone.utc))
    assert store.read('study','schedule',item['id'])['state'] == 'blocked'
    schedules.tick('study',datetime(2030,1,1,14,tzinfo=timezone.utc))
    assert store.read('study','schedule',item['id'])['state'] == 'missed'
    assert not store.listing('study','execution')


def test_dst_requires_offset_and_rejects_nonexistent(harness):
    with pytest.raises(store.WorkspaceError, match='Ambiguous'):
        schedules._instant('2030-11-03T01:30:00','America/New_York')
    assert schedules._instant('2030-11-03T01:30:00-04:00','America/New_York').hour == 5
    with pytest.raises(store.WorkspaceError, match='nonexistent'):
        schedules._instant('2030-03-10T02:30:00-05:00','America/New_York')


def test_schedule_edits_version_and_cancel_preserve_approval_history(harness):
    _, _, item = setup_schedule(harness)
    changed = schedules.update('study',item['id'],{'expected_version':1,'approved':True,'earliest_dispatch':'2030-01-01T15:00:00+00:00','timezone':'UTC'})
    assert changed['version'] == 2 and len(changed['history']) == 1
    with pytest.raises(store.Conflict):
        schedules.update('study',item['id'],{'expected_version':1},cancel=True)
    cancelled = schedules.update('study',item['id'],{'expected_version':2},cancel=True)
    assert cancelled['state'] == 'cancelled' and not cancelled['approval']['active']


def test_restart_after_intent_before_link_reconciles_existing_execution(harness, monkeypatch):
    _, _, item = setup_schedule(harness)
    actual = workspace._dispatch_plan
    def crash_after_dispatch(*args):
        actual(*args)
        raise RuntimeError('fixture crash after durable approval')
    monkeypatch.setattr(workspace,'_dispatch_plan',crash_after_dispatch)
    schedules.tick('study',datetime(2030,1,1,12,30,tzinfo=timezone.utc))
    assert store.read('study','schedule',item['id'])['state'] == 'uncertain'
    monkeypatch.setattr(workspace,'_dispatch_plan',actual)
    schedules.tick('study',datetime(2030,1,1,12,31,tzinfo=timezone.utc))
    assert store.read('study','schedule',item['id'])['state'] == 'dispatched'
    assert len(store.listing('study','execution')) == 1


def test_non_utc_schedule_window_round_trips_stored_instants(harness):
    _, _, item = setup_schedule(harness, earliest='2030-01-01T09:00:00-05:00', timezone='America/New_York')
    edited = schedules.update('study', item['id'], {'expected_version': 1, 'approved': True,
        'timezone': item['timezone'], 'earliest_dispatch': item['earliest_dispatch'], 'latest_dispatch': item['latest_dispatch']})
    assert edited['earliest_dispatch'] == item['earliest_dispatch']
    assert edited['timezone'] == 'America/New_York'


def test_two_due_workers_keep_one_durable_execution(harness):
    from concurrent.futures import ThreadPoolExecutor
    _, _, item = setup_schedule(harness)
    due = datetime(2030,1,1,12,30,tzinfo=timezone.utc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: schedules.tick('study', due), range(2)))
    assert len(store.listing('study','execution')) == 1
    assert store.read('study','schedule',item['id'])['state'] == 'dispatched'


def test_invalidated_schedule_cannot_reactivate_old_plan_after_source_restore(harness):
    h = harness; plan, body, item = setup_schedule(h)
    path=h.root/'science/runner.py'; original=path.read_bytes(); path.write_text('changed source')
    schedules.tick('study',datetime(2030,1,1,12,30,tzinfo=timezone.utc))
    blocked=store.read('study','schedule',item['id'])
    assert blocked['state']=='blocked' and not blocked['approval']['active']
    path.write_bytes(original)
    with pytest.raises(store.Conflict,match='fresh plan'):
        schedules.update('study',item['id'],{'expected_version':blocked['version'],'approved':True,
            'timezone':'UTC','earliest_dispatch':'2030-01-02T12:00:00+00:00'})
    schedules.tick('study',datetime(2030,1,2,tzinfo=timezone.utc))
    expired=store.read('study','schedule',item['id'])
    assert expired['state']=='missed'
    schedules.update('study',item['id'],{'expected_version':expired['version']},cancel=True)
    with pytest.raises(store.Conflict,match='fresh plan'):
        workspace.dispatch_plan('study',plan['id'],'old-plan-again')
    with pytest.raises(store.Conflict,match='fresh plan'):
        schedules.create('study',{**body,'idempotency_key':'another-old-plan'})
    assert not store.listing('study','execution')
