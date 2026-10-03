"""Frozen exact management scopes, durable fences, and per-target receipts.

Site adapters must establish conditional mutation semantics before becoming
available. The default adapter deliberately cannot mutate a scheduler.
"""
from __future__ import annotations

import copy
import hashlib
import json

from controller import workspace_store as store
from controller.workspace_contracts import version_token

TERMINAL = {'completed', 'failed', 'rejected', 'cancelled', 'superseded', 'skipped'}


class UnavailableAdapter:
    version = 'unavailable-v1'

    def capabilities(self):
        return {'cancel': {'supported': False, 'reason': 'Site exact-scope cancellation has not passed its scheduler capability gate.'},
                'pending-change': {'supported': False, 'reason': 'No scheduler adapter proves atomic pending-state updates; prepare a replacement.'}}


def get_adapter(slug):
    """Replace only with an audited adapter; scheduler fixtures inject this seam."""
    return UnavailableAdapter()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _connection_binding(rec):
    from pathlib import Path
    declaration = Path(rec['path']) / 'unityHPC/project.json'
    return digest({'registry': {k: rec.get(k) for k in ('path', 'remote_dir', 'unity_host', 'overrides')},
                   'declaration': hashlib.sha256(declaration.read_bytes()).hexdigest() if declaration.is_file() else None})


def allowed_actions(slug, execution, stage):
    adapter = get_adapter(slug)
    caps = adapter.capabilities()
    waiting = stage['state'] in ('waiting', 'submitting', 'uncertain')
    local = stage.get('location') == 'controller'
    return {'cancel': {'supported': waiting or local or caps['cancel']['supported'],
                       'reason': None if waiting or local else caps['cancel'].get('reason')},
            'pending-change': caps['pending-change'],
            'retry': {'supported': stage['state'] in ('failed', 'rejected', 'cancelled', 'waiting', 'blocked'),
                      'reason': 'Recovery requires terminal, known work and a separate reviewed plan.'},
            'reconcile': {'supported': stage['state'] in ('submitting', 'uncertain')}}


def _scope(execution, plan, selected):
    stages = {s['id']: s for s in execution['stages']}
    if not isinstance(selected, list) or not selected or any(not isinstance(s, str) or s not in stages for s in selected):
        raise store.WorkspaceError('Select explicit stage_ids in this execution')
    if len(set(selected)) != len(selected):
        raise store.WorkspaceError('Repeated stage identities are not permitted')
    affected = set(selected)
    while True:
        expanded = affected | {s['id'] for s in plan['stages'] if set(s.get('depends_on', [])).intersection(affected)}
        if expanded == affected:
            break
        affected = expanded
    return stages, [s['id'] for s in execution['stages'] if s['id'] in affected]


def prepare(slug, body):
    from controller.workspace import project
    from controller.workspace_runs import scheduler_reference
    from lib import campaign
    from pathlib import Path
    kind = body.get('kind', 'cancel')
    if kind not in ('cancel', 'pending-change'):
        raise store.WorkspaceError('Supported management reviews are cancel and pending-change')
    execution = store.read(slug, 'execution', body.get('execution_id'))
    if body.get('expected_version') != version_token(execution):
        raise store.Conflict('Execution changed; refresh its exact scope before review', current_version=version_token(execution), expected_version=body.get('expected_version'))
    plan = store.read(slug, 'plan', execution['plan_id'])
    selected = body.get('stage_ids')
    stages, affected = _scope(execution, plan, selected)
    adapter = get_adapter(slug)
    caps = adapter.capabilities()
    rec = project(slug)
    ledger = {r['job_id']: r for r in campaign.jobs(Path(rec['path']), execution['campaign'])}
    requested_jobs = body.get('job_ids')
    if requested_jobs is not None:
        owned_jobs = {j for sid in selected for j in stages[sid].get('job_ids', [])}
        if not isinstance(requested_jobs, list) or not requested_jobs or any(not isinstance(j, str) or j not in owned_jobs for j in requested_jobs) or len(set(requested_jobs)) != len(requested_jobs):
            raise store.WorkspaceError('Selected job_ids must name exact jobs of the selected stages')
    targets = []
    for sid in selected:
        stage = stages[sid]
        attempt = stage['attempts'][-1]
        if stage['state'] in ('submitting', 'uncertain') and kind != 'cancel':
            raise store.Conflict('Uncertain submission must reconcile before another mutation')
        target = {'id': sid, 'attempt_id': attempt['id'], 'state': stage['state'], 'location': stage.get('location'),
                  'jobs': [scheduler_reference(rec, execution, ledger[j]) for j in stage.get('job_ids', []) if j in ledger],
                  'resources': stage.get('effective_resources') or next(s.get('resources', {}) for s in plan['stages'] if s['id'] == sid)}
        if stage.get('job_ids') and len(target['jobs']) != len(stage['job_ids']):
            raise store.Conflict('Missing ledger identity prevents an exact scheduler action')
        if requested_jobs is not None and target['jobs']:
            target['jobs'] = [j for j in target['jobs'] if j['job_id'] in requested_jobs]
            if not target['jobs']:
                raise store.WorkspaceError('Every selected submitted stage requires an explicit job selection')
        target['effective_resources_by_job'] = {j['job_id']: stage.get('effective_resources_by_job', {}).get(j['job_id'], target['resources']) for j in target['jobs']}
        if len(target['jobs']) == 1:
            target['resources'] = target['effective_resources_by_job'][target['jobs'][0]['job_id']]
        if kind == 'pending-change' and (not caps[kind]['supported'] or stage['state'] not in ('accepted', 'running')):
            raise store.Conflict(caps[kind].get('reason') or 'This state does not support pending changes')
        if target['jobs'] and kind == 'cancel' and not caps[kind]['supported']:
            raise store.Conflict(caps[kind]['reason'])
        if target['jobs']:
            if any(j['task_id'] is not None for j in target['jobs']) and not caps[kind].get('exact_array_tasks'):
                raise store.Conflict('Exact array task scope is unavailable; explicitly review the demonstrated group scope')
            target['observation'] = adapter.observe(target)
            if not target['observation'].get('authoritative'):
                raise store.Conflict('A fresh authoritative scheduler observation is required')
        targets.append(target)
    proposed = body.get('proposed', {})
    if kind == 'pending-change':
        if not proposed or any(k not in caps[kind].get('fields', []) for k in proposed):
            raise store.WorkspaceError('The proposed field is not supported by this adapter')
        for target in targets:
            if target['observation'].get('state') != 'PENDING':
                raise store.Conflict('The job is no longer pending. Review replacement or supported running controls.')
    record = {'id': store.new_id('management'), 'kind': kind, 'version': 1, 'state': 'prepared',
              'execution_id': execution['id'], 'expected_version': version_token(execution), 'plan_id': plan['id'],
              'connection_digest': _connection_binding(rec),
              'plan_digest': digest(plan), 'capability_digest': digest(caps), 'adapter_version': adapter.version,
              'targets': targets, 'stage_ids': selected, 'affected_stage_ids': affected,
              'fence_stage_ids': [s for s in affected if stages[s]['state'] == 'waiting'],
              'unaffected_stage_ids': [s for s in stages if s not in affected], 'proposed': proposed,
              'warnings': ['Cancellation does not delete saved evidence.'] if kind == 'cancel' else ['A shorter walltime can terminate unfinished work. It never guarantees an earlier start.'],
              'created_at': store.now()}
    record['review_digest'] = digest(record)
    with store.transaction(slug) as con:
        store.put(con, 'management-plan', record)
    return record


def _operation_state(targets, kind=None):
    states = [t['state'] for t in targets]
    if 'uncertain' in states:
        return 'uncertain'
    if 'rejected' in states:
        return 'partial' if 'accepted' in states or 'skipped' in states else 'failed'
    if kind == 'cancel' and any(t['state'] == 'accepted' and not t.get('observed_state') for t in targets):
        return 'applying'
    return 'succeeded'


def apply(slug, preview_id, body):
    from controller.workspace import project
    preview = store.read(slug, 'management-plan', preview_id)
    key = body.get('idempotency_key')
    if not isinstance(key, str) or not key or len(key) > 200:
        raise store.WorkspaceError('An idempotency key of at most 200 characters is required')
    binding = digest({'preview_id': preview_id, 'review_digest': body.get('review_digest'), 'expected_version': body.get('expected_version')})
    with store.transaction(slug) as con:
        existing = next((r for r in store.list_records(con, 'operation') if r.get('idempotency_key') == key), None)
        if existing:
            if existing.get('request_digest') != binding:
                raise store.Conflict('This idempotency key is bound to a different reviewed action')
            return existing
        if body.get('review_digest') != preview['review_digest'] or body.get('expected_version') != preview['version']:
            raise store.Conflict('Management review changed', current_version=preview['version'], expected_version=body.get('expected_version'))
        execution = store.get(con, 'execution', preview['execution_id'])
        if version_token(execution) != preview['expected_version']:
            raise store.Conflict('Execution scope changed after review', current_version=version_token(execution), expected_version=preview['expected_version'])
        if any((r['state'] in ('applying', 'uncertain') or (r.get('kind') == 'cancel' and any(t['state'] == 'accepted' and not t.get('observed_state') for t in r['targets']))) and r.get('execution_id') == execution['id'] and set(r.get('stage_ids', [])).intersection(preview['affected_stage_ids']) for r in store.list_records(con, 'operation')):
            raise store.Conflict('An overlapping operation must reconcile first')
        rec = project(slug)
        adapter = get_adapter(slug)
        if digest(adapter.capabilities()) != preview['capability_digest'] or adapter.version != preview['adapter_version']:
            raise store.Conflict('Scheduler capabilities changed after review')
        if _connection_binding(rec) != preview['connection_digest'] or digest(store.get(con, 'plan', preview['plan_id'])) != preview['plan_digest']:
            raise store.Conflict('Connection or plan changed after review')
        operation = {'id': store.new_id('operation'), 'kind': preview['kind'], 'version': 1, 'state': 'applying',
                     'execution_id': execution['id'], 'stage_ids': preview['affected_stage_ids'], 'preview_id': preview_id,
                     'idempotency_key': key, 'request_digest': binding, 'created_at': store.now(), 'updated_at': store.now(),
                     'actor': body.get('actor', 'local-human'), 'targets': [{'id': t['id'], 'state': 'uncertain', 'reason': 'Durable intent recorded; awaiting acknowledgement'} for t in preview['targets']]}
        if preview['kind'] == 'cancel':
            execution.setdefault('stop_fences', []).append({'operation_id': operation['id'], 'stage_ids': preview['affected_stage_ids'], 'created_at': store.now()})
            for stage in execution['stages']:
                if stage['id'] in preview['stage_ids'] and stage.get('location') == 'controller' and stage['state'] == 'running':
                    stage['cancel_requested'] = True
                if stage['id'] in preview['fence_stage_ids']:
                    stage.update(state='cancelled', waiting_reason='Stopped by reviewed cancellation', stop_operation_id=operation['id'])
                    stage['attempts'][-1].update(state='cancelled', updated_at=store.now())
            execution['version'] = int(execution.get('version', 0)) + 1
            store.put(con, 'execution', execution)
        store.put(con, 'operation', operation)
    # The intent and fence are durable before an external action can run.
    for index, target in enumerate(preview['targets']):
        outcome = operation['targets'][index]
        try:
            if target['state'] in TERMINAL:
                outcome.update(state='skipped', reason='Already terminal')
            elif target['state'] == 'waiting':
                outcome.update(state='accepted', reason='Unsent work cancelled; dependent submission is fenced', observed_state='cancelled')
            elif target['jobs']:
                observed = adapter.observe(target)
                if not observed.get('authoritative') or observed.get('token') != target['observation'].get('token'):
                    raise store.Conflict('Scheduler observation changed after review; no mutation sent')
                # The audited adapter must compare this token at the scheduler boundary.
                result = adapter.apply(preview['kind'], target, preview['proposed'], observed['token'])
                outcome.update(state=result.get('state', 'uncertain'), reason=result.get('reason'), acknowledgement=result,
                               observed_state=result.get('observed_state'))
            elif target['location'] == 'controller' and target['state'] == 'running':
                from controller.workspace_local import cancel
                outcome.update(cancel(project(slug)['path'], target['attempt_id']))
            else:
                outcome.update(state='uncertain', reason='Submission is unresolved. Further dependent dispatch is fenced; reconcile the original receipt.')
        except store.Conflict as exc:
            outcome.update(state='rejected', reason=str(exc))
        except Exception as exc:
            outcome.update(state='uncertain', reason=str(exc))
        operation.update(state=_operation_state(operation['targets'], operation['kind']), updated_at=store.now(), version=operation['version'] + 1)
        with store.transaction(slug) as con:
            store.put(con, 'operation', operation)
            current = store.get(con, 'execution', preview['execution_id'])
            for stage in current['stages']:
                if stage['id'] == target['id']:
                    stage.setdefault('management_history', []).append({'operation_id': operation['id'], 'kind': preview['kind'],
                        'before': target.get('resources'), 'after': preview['proposed'], 'outcome': copy.deepcopy(outcome), 'at': store.now()})
                    if preview['kind'] == 'cancel' and outcome['state'] == 'accepted' and stage['state'] not in TERMINAL:
                        stage['cancel_requested'] = True
                    if preview['kind'] == 'pending-change' and outcome['state'] == 'accepted':
                        by_job = stage.setdefault('effective_resources_by_job', {})
                        for job in target['jobs']:
                            by_job[job['job_id']] = {**target['effective_resources_by_job'][job['job_id']], **preview['proposed']}
                        effective = [by_job.get(j, target['resources']) for j in stage.get('job_ids', [])]
                        if effective and all(value == effective[0] for value in effective):
                            stage['effective_resources'] = effective[0]
            current['version'] = int(current.get('version', 0)) + 1
            store.put(con, 'execution', current)
    return operation


def reconcile(slug, identity):
    operation = store.read(slug, 'operation', identity)
    preview = store.read(slug, 'management-plan', operation['preview_id'])
    adapter = get_adapter(slug)
    execution = store.read(slug, 'execution', operation['execution_id'])
    states = {s['id']: s for s in execution['stages']}
    for target, outcome in zip(preview['targets'], operation['targets']):
        if outcome['state'] != 'uncertain' and not (operation['kind'] == 'cancel' and outcome['state'] == 'accepted'):
            continue
        stage = states[target['id']]
        if stage['state'] in TERMINAL:
            outcome.update(state='accepted', observed_state=stage['state'], reason='Terminal state observed')
        elif not target['jobs'] and stage.get('job_ids'):
            outcome.update(state='rejected', reason='Submission now has a ledger receipt. The newly known job was not cancelled; prepare a new exact cancellation review.', requires_new_review=True)
        elif target['jobs'] and hasattr(adapter, 'reconcile'):
            result = adapter.reconcile(operation['kind'], target, preview['proposed'])
            outcome.update(result)
    operation.update(state=_operation_state(operation['targets'], operation['kind']), updated_at=store.now(), version=operation['version'] + 1)
    with store.transaction(slug) as con:
        store.put(con, 'operation', operation)
    return operation
