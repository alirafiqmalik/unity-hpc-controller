"""One-off frozen approvals with bounded dispatch windows and restart safety."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from controller import workspace_store as store
from controller.workspace_actions import digest
from controller.workspace_contracts import version_token

ACTIVE = {'scheduled', 'due', 'dispatching', 'blocked', 'uncertain'}


def _instant(value, zone):
    if not isinstance(value, str):
        raise store.WorkspaceError('A dispatch instant is required')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        tz = ZoneInfo(zone)
    except (ValueError, ZoneInfoNotFoundError):
        raise store.WorkspaceError('Use an ISO dispatch instant and an IANA timezone') from None
    if parsed.tzinfo is None:
        first = parsed.replace(tzinfo=tz, fold=0)
        second = parsed.replace(tzinfo=tz, fold=1)
        if first.utcoffset() != second.utcoffset():
            raise store.WorkspaceError('Ambiguous or nonexistent local time; select an explicit offset')
        parsed = first
    # Stored UTC timestamps are absolute instants and can round-trip through
    # edit forms while retaining the user's display timezone. Local wall-clock
    # timestamps still require a valid zone offset (including DST overlaps).
    if parsed.utcoffset() == timedelta(0):
        return parsed.astimezone(timezone.utc)
    localized = parsed.astimezone(tz)
    if localized.replace(tzinfo=None) != parsed.replace(tzinfo=None) or localized.utcoffset() != parsed.utcoffset():
        raise store.WorkspaceError('Dispatch time offset does not match its timezone or is nonexistent')
    return parsed.astimezone(timezone.utc)


def _window(body):
    zone = body.get('timezone', 'UTC')
    earliest = _instant(body.get('earliest_dispatch'), zone)
    latest = _instant(body['latest_dispatch'], zone) if body.get('latest_dispatch') else earliest + timedelta(hours=1)
    if latest <= earliest:
        raise store.WorkspaceError('Latest dispatch must be after earliest dispatch')
    return earliest.isoformat(), latest.isoformat(), zone


def _validate(slug, plan):
    from controller.workspace import project
    from controller.workspace_planner import verify_plan
    from pathlib import Path
    rec = project(slug)
    if plan.get('runtime_connection') != {k: rec.get(k) for k in ('path', 'remote_dir', 'unity_host', 'overrides')}:
        raise store.Conflict('Project attachment changed after review')
    if plan.get('experiment_id') and plan.get('kind') != 'recovery':
        experiment = store.read(slug, 'experiment', plan['experiment_id'])
        if experiment['version'] != plan['experiment_version'] or experiment['revision'] != plan['revision']:
            raise store.Conflict('Experiment changed after review', current_version=experiment['version'], expected_version=plan['experiment_version'])
    checked = verify_plan(Path(rec['path']), plan)
    if not checked['valid']:
        raise store.Conflict('Source, inputs, or declaration changed after review')
    if not plan.get('stages'):
        raise store.WorkspaceError('Cannot schedule an empty plan')


def guard_immediate_dispatch(slug, plan_id):
    if any(s['plan_id'] == plan_id and s.get('invalidated_at') for s in store.listing(slug, 'schedule')):
        raise store.Conflict('This scheduled review was invalidated. Check and review a fresh plan before dispatch.')
    if any(s['plan_id'] == plan_id and s['state'] in ACTIVE for s in store.listing(slug, 'schedule')):
        raise store.Conflict('This plan has an active schedule approval. Cancel it before immediate dispatch.')


def create(slug, body):
    from controller.workspace_worker import project_lock
    first, last, zone = _window(body)
    if body.get('approved') is not True:
        raise store.WorkspaceError('Scheduling requires explicit approval of the reviewed plan and dispatch window')
    key = body.get('idempotency_key')
    if not isinstance(key, str) or not key or len(key) > 200:
        raise store.WorkspaceError('Schedule requires an idempotency key of at most 200 characters')
    request_digest = digest(body)
    with project_lock(slug) as acquired:
        if not acquired:
            raise store.Conflict('Execution worker is busy; retry the same schedule approval')
        if any(a.get('state') in ('applying', 'checking', 'recovery_required') for a in store.listing(slug, 'maintenance-action')):
            raise store.Conflict('Reconcile unfinished connection maintenance before approving a schedule')
        existing = next((s for s in store.listing(slug, 'schedule') if s.get('idempotency_key') == key), None)
        if existing:
            if existing['request_digest'] != request_digest:
                raise store.Conflict('Schedule idempotency key is bound to another request')
            return existing
        plan = store.read(slug, 'plan', body.get('plan_id'))
        if body.get('expected_version') != version_token(plan):
            raise store.Conflict('Reviewed plan changed', current_version=version_token(plan), expected_version=body.get('expected_version'))
        _validate(slug, plan)
        guard_immediate_dispatch(slug, plan['id'])
        if any(e['plan_id'] == plan['id'] for e in store.listing(slug, 'execution')):
            raise store.Conflict('This plan already has an execution; repeat through a fresh plan')
        stamp = store.now()
        item = {'id': store.new_id('schedule'), 'version': 1, 'plan_id': plan['id'], 'plan_digest': digest(plan),
                'state': 'scheduled', 'earliest_dispatch': first, 'latest_dispatch': last, 'timezone': zone,
                'approval': {'actor': body.get('actor', 'local-human'), 'approved_at': stamp, 'active': True},
                'idempotency_key': key, 'request_digest': request_digest, 'execution_id': None,
                'created_at': stamp, 'updated_at': stamp, 'history': []}
        item['dispatch_key'] = 'schedule:' + item['id']
        with store.transaction(slug) as con:
            store.put(con, 'schedule', item)
        return item


def update(slug, identity, body, cancel=False):
    from controller.workspace_worker import project_lock
    with project_lock(slug) as acquired:
        if not acquired:
            raise store.Conflict('A due worker owns this project; refresh the schedule before editing')
        if not cancel and any(a.get('state') in ('applying', 'checking', 'recovery_required') for a in store.listing(slug, 'maintenance-action')):
            raise store.Conflict('Reconcile unfinished connection maintenance before changing a schedule')
        item = store.read(slug, 'schedule', identity)
        if body.get('expected_version') != item['version']:
            raise store.Conflict('Schedule changed; reload its current state', current_version=item['version'], expected_version=body.get('expected_version'))
        if not cancel and (item.get('invalidated_at') or item['state'] == 'blocked'):
            raise store.Conflict('This approval was invalidated. Check and review a fresh plan; changing its window cannot reactivate it.')
        if item['state'] in ('dispatched', 'dispatching', 'uncertain') or item.get('execution_id'):
            raise store.Conflict('Dispatch intent already exists. Inspect and cancel exact execution work instead.')
        old = {k: item[k] for k in ('version', 'state', 'earliest_dispatch', 'latest_dispatch', 'approval')}
        item['history'].append(old)
        item['approval'] = {**item['approval'], 'active': False, 'revoked_at': store.now()}
        if cancel:
            item['state'] = 'cancelled'
        else:
            if body.get('approved') is not True:
                raise store.WorkspaceError('A changed window requires a new explicit approval')
            plan = store.read(slug, 'plan', item['plan_id'])
            _validate(slug, plan)
            if digest(plan) != item['plan_digest']:
                raise store.Conflict('Frozen plan changed; check and review a new plan')
            first, last, zone = _window(body)
            item.update(earliest_dispatch=first, latest_dispatch=last, timezone=zone, state='scheduled',
                        approval={'active': True, 'actor': body.get('actor', 'local-human'), 'approved_at': store.now()})
        item.update(version=item['version'] + 1, updated_at=store.now())
        with store.transaction(slug) as con:
            store.put(con, 'schedule', item)
        return item


def tick(slug, now=None):
    from controller.workspace_worker import project_lock
    from controller.workspace import _dispatch_plan
    current = now or datetime.now(timezone.utc)
    with project_lock(slug) as acquired:
        if not acquired:
            return
        if any(a.get('state') in ('applying', 'checking', 'recovery_required') for a in store.listing(slug, 'maintenance-action')):
            return
        for item in store.listing(slug, 'schedule'):
            if item['state'] not in ACTIVE:
                continue
            executions = [e for e in store.listing(slug, 'execution') if e['plan_id'] == item['plan_id']]
            if executions:
                item.update(state='dispatched', execution_id=executions[0]['id'])
            elif current > datetime.fromisoformat(item['latest_dispatch']):
                item.update(state='missed', reason='Dispatch window expired. Check and review a new window; no late execution was created.')
            elif current < datetime.fromisoformat(item['earliest_dispatch']) or item['state'] == 'blocked':
                continue
            else:
                try:
                    plan = store.read(slug, 'plan', item['plan_id'])
                    if not item['approval']['active'] or digest(plan) != item['plan_digest']:
                        raise store.Conflict('Approval or frozen plan binding changed')
                    _validate(slug, plan)
                    item.update(state='dispatching', dispatch_intent_at=item.get('dispatch_intent_at', store.now()), version=item['version'] + 1, updated_at=store.now())
                    with store.transaction(slug) as con:
                        store.put(con, 'schedule', item)
                    execution = _dispatch_plan(slug, item['plan_id'], item['dispatch_key'])
                    item.update(state='dispatched', execution_id=execution['id'], reason=None)
                except store.WorkspaceError as exc:
                    item.update(state='blocked', reason=str(exc), invalidated_at=store.now(), approval={**item['approval'], 'active': False})
                except Exception as exc:
                    item.update(state='uncertain', reason=str(exc))
            item.update(version=item['version'] + 1, updated_at=store.now())
            with store.transaction(slug) as con:
                store.put(con, 'schedule', item)
