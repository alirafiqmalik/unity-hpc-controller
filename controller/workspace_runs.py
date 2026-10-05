"""Read-only execution projections and exact, bounded attempt streams."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

from controller import workspace_store as store
from controller.workspace_contracts import observation, version_token
from lib import campaign

ACTIVE = {'submitting', 'accepted', 'running', 'fetching'}
ATTENTION = {'failed', 'rejected', 'uncertain', 'blocked'}
TERMINAL = {'completed', 'failed', 'rejected', 'cancelled', 'superseded', 'skipped'}
LIMIT = 65536


def scheduler_reference(project, execution, row):
    identity = str(row['job_id'])
    parent, _, task = identity.partition('_')
    return {'cluster': project.get('unity_host') or 'unity', 'campaign': execution['campaign'],
            'job_id': identity, 'parent_id': parent if task else None, 'task_id': task or None,
            'submitted_at': row.get('submitted_utc'), 'ledger_reference': f"{execution['campaign']}:{identity}",
            'restart_count': row.get('restart_count'), 'attribution': 'known' if row.get('restart_count') is not None else 'restart-history-unknown'}



def _collections(slug, execution, plan):
    from controller.workspace_results import field
    params = [plan.get('config', {}).get('parameters', {}), *[v.get('parameters', {}) for v in plan.get('variants', [])]]
    values = {str(p.get('collection') or p.get('family')) for p in params if p.get('collection') or p.get('family')}
    if plan.get('config', {}).get('collection'):
        values.add(str(plan['config']['collection']))
    artifacts = [a for a in store.listing(slug, 'artifact') if a.get('execution_id') == execution['id']]
    artifacts += plan.get('artifacts', [])
    for artifact in artifacts:
        value = artifact.get('collection') or field(artifact, artifact.get('result_schema', {}).get('family_path', 'provenance.parameters.family'))
        if value:
            values.add(str(value))
    return sorted(values) or ['unknown']


def _date_matches(stamp, date_filter):
    """Filter approval/submission UTC dates, with inclusive ISO date endpoints."""
    if not date_filter:
        return True
    from datetime import date, datetime, timezone
    try:
        parts = date_filter.split('/')
        if len(parts) not in (1, 2):
            raise ValueError()
        first = date.fromisoformat(parts[0]); last = date.fromisoformat(parts[-1])
        if last < first:
            raise ValueError()
    except (ValueError, TypeError):
        raise store.WorkspaceError('Date filter must be YYYY-MM-DD or an inclusive YYYY-MM-DD/YYYY-MM-DD range') from None
    if not stamp:
        return False
    try:
        current = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return first <= current.astimezone(timezone.utc).date() <= last
    except (ValueError, TypeError):
        return False


def _matches_execution(item, filters):
    aliases = {'execution': 'id', 'experiment': 'experiment_id', 'state': 'summary'}
    for field, value in filters.items():
        if not value:
            continue
        key = aliases.get(field, field)
        if key in ('id', 'experiment_id', 'summary', 'campaign') and item.get(key) != value:
            return False
        if key == 'collection' and value not in item['collections']:
            return False
        if key == 'date' and not _date_matches(item.get('approved_at'), value):
            return False
        if key == 'search' and value.casefold() not in json.dumps({k:item.get(k) for k in ('id','experiment_id','experiment_name','stages','campaign')}, ensure_ascii=False).casefold():
            return False
        if key == 'purpose' and not any(s.get('purpose', 'unclassified') == value for s in item['stages']):
            return False
        if key in ('stage', 'variant', 'attempt'):
            if not any((s['id'] == value if key == 'stage' else s.get('variant_id') == value if key == 'variant' else any(a['id'] == value for a in s.get('attempts', []))) for s in item['stages']):
                return False
        if key == 'attention' and not (item['attention_count'] > 0 if value == 'needs_attention' else item['uncertain_count'] > 0 if value == 'uncertain' else any(s['state'] == value for s in item['stages'])):
            return False
    return True

def project_execution(slug, execution):
    from controller.workspace import project
    from controller.workspace_actions import allowed_actions
    rec = project(slug)
    value = copy.deepcopy(execution)
    plan = store.read(slug, 'plan', execution['plan_id'])
    specs = {s['id']: s for s in plan['stages']}
    observed = execution.get('scheduler_observation') or {}
    freshness = observation('scheduler', observed.get('checked_at'), availability='unavailable' if observed.get('error') else 'available')
    if observed.get('error'):
        freshness['error'] = observed['error']
    counts = Counter(s['state'] for s in execution['stages'])
    active = sum(counts[s] for s in ACTIVE)
    attention = sum(counts[s] for s in ATTENTION)
    unresolved_actions = [o for o in store.listing(slug, 'operation') if o.get('execution_id') == execution['id'] and (o['state'] in ('applying', 'uncertain', 'partial', 'failed') or any(t.get('state') == 'uncertain' for t in o.get('targets', [])))]
    attention += len(unresolved_actions)
    uncertain_count = counts['uncertain'] + sum(o['state'] == 'uncertain' for o in unresolved_actions)
    waits = counts['waiting']
    if active:
        summary = 'active'
    elif attention and waits:
        summary = 'needs-attention'
    elif waits:
        summary = 'waiting'
    elif all(s['state'] in ('completed', 'skipped', 'superseded') for s in execution['stages']):
        summary = 'succeeded'
    elif counts['cancelled'] == len(execution['stages']):
        summary = 'cancelled'
    elif counts['failed'] + counts['rejected'] == len(execution['stages']):
        summary = 'failed'
    elif counts['uncertain'] or counts['blocked']:
        summary = 'needs-attention'
    else:
        summary = 'partial-success'
    value['collections'] = _collections(slug, execution, plan)
    if execution.get('experiment_id'):
        try:
            value['experiment_name'] = store.read(slug, 'experiment', execution['experiment_id']).get('name')
        except store.Missing:
            value['experiment_name'] = None
    value.update(has_scheduler_work=any(s.get('location') == 'cluster' for s in execution['stages']), project_slug=slug, version=version_token(execution), source_revision=plan.get('source', {}).get('digest'),
                 summary=summary, counts=dict(counts), active_count=active, attention_count=attention, uncertain_count=uncertain_count,
                 freshness={'scheduler': freshness, 'execution': observation('controller-store', store.now(), stale_after=60)})
    ledger = {r['job_id']: r for r in campaign.jobs(Path(rec['path']), execution['campaign'])}
    for stage in value['stages']:
        spec = specs[stage['id']]
        state = stage['state']
        stage.update(depends_on=spec.get('depends_on', []), operation=spec['operation'], declared_stage_id=spec.get('stage_id', stage['id']),
                     parameters=spec.get('parameters', {}), resources=spec.get('resources', {}), output_dir=spec.get('output_dir'),
                     inputs=spec.get('inputs', []), scope='variant' if stage.get('variant_id') else 'shared',
                     completeness={'incomplete': 'partial'}.get(stage.get('completeness'), stage.get('completeness', 'unknown')))
        family = spec.get('parameters', {}).get('collection') or spec.get('parameters', {}).get('family')
        stage['collections'] = [str(family)] if family else value['collections']
        stage['submission'] = state if state in ('waiting', 'submitting', 'accepted', 'rejected', 'uncertain') else ('accepted' if stage.get('job_ids') else 'waiting')
        if stage.get('location') == 'controller':
            stage['submission'] = 'not-applicable'
        stage['lifecycle'] = {'completed': 'succeeded', 'accepted': 'active', 'running': 'active', 'fetching': 'active', 'rejected': 'failed', 'uncertain': 'blocked', 'superseded': 'skipped'}.get(state, state)
        stage['retrieval'] = {'not-requested': 'not_requested', 'retrieving': 'running', 'fetched': 'complete'}.get(stage.get('fetch_state'), stage.get('fetch_state', 'not_requested'))
        stage['progress'] = stage.get('progress')  # Unknown does not mean zero.
        stage['scheduler_references'] = [scheduler_reference(rec, execution, ledger[j]) for j in stage.get('job_ids', []) if j in ledger]
        stage['jobs'] = [ledger[j] for j in stage.get('job_ids', []) if j in ledger]
        stage['allowed_actions'] = allowed_actions(slug, execution, stage)
    return value


def executions(slug, filters=None):
    filters = filters or {}
    items = [project_execution(slug, e) for e in store.listing(slug, 'execution')]
    if filters.get('date'):
        _date_matches(None, filters['date'])
    items = [item for item in items if _matches_execution(item, filters)]
    items.sort(key=lambda e: e.get('updated_at', ''), reverse=True)
    items.sort(key=lambda e: not bool(e['active_count']))
    return {'executions': items}


def queue(slug, filters=None):
    filters = filters or {}
    if filters.get('date'):
        _date_matches(None, filters['date'])
    from controller.workspace import project
    rec = project(slug)
    executions_ = executions(slug)['executions']
    indexed = {(e['campaign'], j): (e, s) for e in executions_ for s in e['stages'] for j in s.get('job_ids', [])}
    rows = []
    for name in campaign.campaigns(Path(rec['path'])):
        for job in campaign.jobs(Path(rec['path']), name):
            match = indexed.get((name, job['job_id']))
            e, stage = match if match else ({'campaign': name}, {})
            rows.append({**job, 'campaign': name, 'collections': stage.get('collections', e.get('collections', ['unknown'])), 'execution_summary': e.get('summary'), 'scheduler_reference': scheduler_reference(rec, e, job), 'execution_id': e.get('id'),
                         'experiment_id': e.get('experiment_id'), 'variant_id': stage.get('variant_id'), 'stage_id': stage.get('id'), 'attempt_id': (stage.get('attempts') or [{}])[-1].get('id'),
                         'purpose': stage.get('purpose', 'unclassified'), 'resources': stage.get('effective_resources_by_job', {}).get(job['job_id'], stage.get('effective_resources') or stage.get('resources')),
                         'freshness': observation('scheduler-ledger', job.get('updated_utc'))})
    aliases = {'execution':'execution_id','experiment':'experiment_id','stage':'stage_id','variant':'variant_id','attempt':'attempt_id'}
    for key, value in filters.items():
        if not value:
            continue
        if key in aliases or key in ('campaign','purpose'):
            rows = [r for r in rows if r.get(aliases.get(key,key)) == value]
        elif key == 'state':
            rows = [r for r in rows if str(r.get('status','')).split('+')[0].upper() == value.upper()]
        elif key == 'collection':
            rows = [r for r in rows if value in r['collections']]
        elif key == 'date':
            rows = [r for r in rows if _date_matches(r.get('submitted_utc'), value)]
        elif key == 'search':
            rows = [r for r in rows if value.casefold() in json.dumps(r,ensure_ascii=False).casefold()]
    return {'jobs': rows}


def find_attempt(slug, attempt_id):
    store.safe_id(attempt_id)
    for execution in store.listing(slug, 'execution'):
        for stage in execution['stages']:
            for attempt in stage.get('attempts', []):
                if attempt['id'] == attempt_id:
                    return execution, stage, attempt
    raise store.Missing('Unknown attempt ' + attempt_id)


def _cursor(data):
    return base64.urlsafe_b64encode(json.dumps(data, sort_keys=True).encode()).decode()


def logs(slug, attempt_id, stream='stdout', offset=None, cursor=None, limit=LIMIT, job_id=None):
    from controller.workspace import project
    if stream not in ('stdout', 'stderr', 'wrapper', 'controller'):
        raise store.WorkspaceError('Unknown log stream')
    try:
        limit = min(LIMIT, max(1, int(limit)))
        offset = None if offset is None else max(0, int(offset))
    except (ValueError, TypeError):
        raise store.WorkspaceError('Log offsets and limits must be integers') from None
    execution, stage, attempt = find_attempt(slug, attempt_id)
    root = Path(project(slug)['path']).resolve()
    identity = f'{attempt_id}:{stream}'
    result = {'attempt_id': attempt_id, 'execution_id': execution['id'], 'stage_id': stage['id'],
              'purpose': stage.get('purpose', 'unclassified'), 'stream': stream, 'stream_id': identity,
              'retrieval_supported': False, 'encoding': 'utf-8', 'text': '', 'offset': 0, 'next_offset': 0, 'cursor': None, 'boundary': None}
    if stream == 'wrapper' and not attempt.get('wrapper_events'):
        return {**result, 'availability': 'not-created', 'reason': 'This approved wrapper has no separate event stream. Controller events and stdout/stderr retain their own identities.', 'freshness': observation('wrapper-events', None, availability='unavailable')}
    if stage.get('location') == 'controller' and stream in ('stdout', 'stderr'):
        path = root / '.unity-workspace/receipts' / (attempt_id + '.' + stream)
    elif stream in ('stdout', 'stderr'):
        jobs = attempt.get('job_ids', stage.get('job_ids', []))
        if job_id is None and len(jobs) == 1:
            job_id = jobs[0]
        if not job_id or job_id not in jobs:
            if not jobs:
                return {**result, 'availability': 'not-created', 'reason': 'Not created yet', 'freshness': observation('log', None)}
            raise store.WorkspaceError('Select one exact job belonging to this attempt')
        store.safe_id(job_id)
        identity += ':' + job_id
        result['stream_id'] = identity
        stem = execution['campaign'] if '_' in job_id else attempt['exp']
        path = root / '_results' / execution['campaign'] / f"{stem}-{job_id}.{'out' if stream == 'stdout' else 'err'}"
    else:
        raw = json.dumps({'state': attempt.get('state'), 'error': attempt.get('error'), 'result': attempt.get('result'),
                          'created_at': attempt.get('created_at'), 'updated_at': attempt.get('updated_at')}, indent=2).encode()
        start = offset if offset is not None else max(0, len(raw) - limit)
        data = raw[start:start + limit]
        return {**result, 'availability': 'available', 'text': data.decode(errors='replace'), 'offset': start,
                'next_offset': start + len(data), 'size': len(raw), 'freshness': observation('controller-store', attempt.get('updated_at'))}
    remote_error = None
    if stage.get('location') != 'controller' and stream in ('stdout', 'stderr'):
        try:
            previous = None
            remote_offset = offset if offset is not None else -1
            if cursor:
                previous = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                if previous['stream'] != identity:
                    raise store.WorkspaceError('Invalid cursor for this attempt stream')
                remote_offset = int(previous['offset'])
            remote = _remote_transport(slug, execution, job_id, stream, offset=remote_offset, limit=limit)
            result['retrieval_supported'] = remote.get('availability') == 'available'
            if remote.get('availability') != 'available':
                if path.is_file():
                    result['remote_availability'] = remote.get('availability')
                    raise store.WorkspaceError(remote.get('reason') or 'Remote stream unavailable; preserved cached bytes remain readable')
                return {**result, **remote, 'freshness': observation('remote-log', remote.get('observed_at'))}
            file_id = 'remote:' + remote['file_id']
            if previous and (previous['file'] != file_id or remote['size'] < remote_offset or (previous['prefix_size'] == remote['prefix_size'] and previous['prefix'] != remote['prefix'])):
                result['boundary'] = 'rotated-or-truncated'
                remote = _remote_transport(slug, execution, job_id, stream, offset=0, limit=limit)
                file_id = 'remote:' + remote['file_id']
            data = base64.b64decode(remote['data'], validate=True)
            if len(data) > limit:
                raise store.WorkspaceError('Remote log response exceeded its byte limit')
            binary = b'\0' in data
            return {**result, 'availability': 'available', 'encoding': 'binary' if binary else 'utf-8',
                    'text': None if binary else data.decode(errors='replace'), 'offset': remote['offset'],
                    'next_offset': remote['next_offset'], 'size': remote['size'], 'remote': True,
                    'cursor': _cursor({'stream': identity, 'file': file_id, 'offset': remote['next_offset'], 'prefix': remote['prefix'], 'prefix_size': remote['prefix_size']}),
                    'freshness': observation('remote-log', remote['observed_at']), 'has_more': remote['next_offset'] < remote['size']}
        except store.WorkspaceError as exc:
            remote_error = str(exc)
            result['retrieval_supported'] = not isinstance(exc, store.Conflict) and result.get('remote_availability') != 'not-created'
            result['retrieval_reason'] = str(exc)
        except (ValueError, KeyError, TypeError) as exc:
            raise store.WorkspaceError('Invalid remote stream or cursor: ' + str(exc)) from None
    if not path.resolve().is_relative_to(root) or path.is_symlink():
        raise store.WorkspaceError('Log path escapes the registered project or is a symlink')
    if not path.is_file():
        pending = stage['state'] == 'waiting' or any(j.get('status') == 'PENDING' for j in stage.get('jobs', []))
        return {**result, 'availability': 'not-created' if pending else 'remote-unavailable',
                'reason': 'Not created yet' if pending else (remote_error or 'Remote unavailable. Retrieve this exact log to inspect cached bytes.'),
                'freshness': observation('local-log', None, availability='unavailable')}
    with path.open('rb') as handle:
        stat = os.fstat(handle.fileno())
        prefix = hashlib.sha256(handle.read(min(4096, stat.st_size))).hexdigest()
        token = f'{stat.st_dev}:{stat.st_ino}'
        start = offset if offset is not None else max(0, stat.st_size - limit)
        if cursor:
            try:
                previous = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                if previous['stream'] != identity:
                    raise ValueError('stream mismatch')
                start = int(previous['offset'])
                if previous['file'] != token or stat.st_size < start or (previous['prefix_size'] == min(4096, stat.st_size) and previous['prefix'] != prefix):
                    result['boundary'] = 'rotated-or-truncated'
                    start = 0
            except (ValueError, KeyError, TypeError):
                raise store.WorkspaceError('Invalid cursor for this attempt stream') from None
        handle.seek(start)
        data = handle.read(limit)
    binary = b'\0' in data
    from datetime import datetime, timezone
    observed = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
    return {**result, 'availability': 'available', 'encoding': 'binary' if binary else 'utf-8',
            'text': None if binary else data.decode('utf-8', errors='replace'), 'offset': start,
            'next_offset': start + len(data), 'size': stat.st_size, 'path': str(path.relative_to(root)),
            'cursor': _cursor({'stream': identity, 'file': token, 'offset': start + len(data), 'prefix': prefix, 'prefix_size': min(4096, stat.st_size)}),
            'freshness': observation('local-log', observed), 'remote_error': remote_error, 'has_more': start + len(data) < stat.st_size}


def _remote_transport(slug, execution, job_id, stream, *, offset=-1, limit=LIMIT, fetch=False):
    from controller import dispatch
    from controller.workspace import project
    rec = project(slug)
    root = Path(rec['path'])
    plan = store.read(slug, 'plan', execution['plan_id'])
    runner = root / '.unity-workspace/plans' / plan['id'] / 'source/unityHPC/run.sh'
    expected = next((f.get('sha256') for f in plan.get('source', {}).get('files', []) if f.get('path') == 'unityHPC/run.sh'), None)
    if runner.is_file() and (not expected or hashlib.sha256(runner.read_bytes()).hexdigest() != expected):
        raise store.Conflict('Reviewed log dispatcher failed integrity checks. Inspect the approved bundle before remote access.')
    if not runner.is_file() or 'cmd_log_read()' not in runner.read_text(errors='replace'):
        raise store.Conflict('Reviewed dispatcher lacks exact bounded log transport. Update the scaffold through reviewed maintenance for future plans; cached logs remain readable.')
    argv = ['log-fetch' if fetch else 'log-read', '--campaign', execution['campaign'], '--job', job_id,
            '--stream', 'out' if stream == 'stdout' else 'err']
    if not fetch:
        argv += ['--offset', str(offset), '--limit', str(limit)]
    try:
        result = dispatch._run({**rec, **plan.get('runtime_connection', {})}, argv,
                               env_overrides=plan.get('runtime_overrides') or None,
                               runner_path=runner, timeout=120 if fetch else 30)
    except dispatch.DispatchError as exc:
        raise store.WorkspaceError('Remote log unavailable: ' + str(exc)) from None
    if not result['ok']:
        raise store.WorkspaceError(result['output'][-2000:])
    try:
        value = json.loads(result['output'])
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise store.WorkspaceError('Exact log adapter returned an invalid receipt') from None


def retrieve_log(slug, attempt_id, body):
    from controller.workspace_worker import project_lock
    with project_lock(slug) as acquired:
        if not acquired:
            raise store.Conflict('Project worker is busy. Retry exact log retrieval.')
        if any(a.get('state') in ('applying', 'checking', 'recovery_required') for a in store.listing(slug, 'maintenance-action')):
            raise store.Conflict('Reconcile maintenance before log retrieval')
        return _retrieve_log(slug, attempt_id, body)


def _retrieve_log(slug, attempt_id, body):
    from controller.workspace import project
    execution, stage, attempt = find_attempt(slug, attempt_id)
    stream = body.get('stream', 'stdout')
    if stream not in ('stdout', 'stderr'):
        raise store.WorkspaceError('Only stdout and stderr have file retrieval')
    jobs = attempt.get('job_ids', stage.get('job_ids', []))
    job_id = body.get('job_id') or (jobs[0] if len(jobs) == 1 else None)
    if stage.get('location') == 'controller':
        return logs(slug, attempt_id, stream)
    if job_id not in jobs:
        raise store.WorkspaceError('Select one exact job belonging to this attempt')
    receipt = _remote_transport(slug, execution, job_id, stream, fetch=True)
    root = Path(project(slug)['path']).resolve()
    path = Path(receipt['path']).resolve()
    if not path.is_relative_to(root / '_results' / execution['campaign']):
        raise store.WorkspaceError('Retrieved log receipt escaped its exact campaign cache')
    return {**receipt, 'path': str(path.relative_to(root)), 'attempt_id': attempt_id,
            'purpose': stage.get('purpose', 'unclassified'), 'stream': stream}
