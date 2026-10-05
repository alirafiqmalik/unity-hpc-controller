"""Indexed project summaries and versioned human research metadata."""
from __future__ import annotations

import copy
from urllib.parse import urlencode

from controller import workspace as service, workspace_store as store
from controller.workspace_connection import load_connection, digest


def _context(con, connection):
    try:
        return store.get(con, 'research-context', 'context')
    except store.Missing:
        pass
    try:
        observed = store.get(con, 'research-origin', 'manifest')
    except store.Missing:
        observed = {'id': 'manifest', 'question': '', 'declaration_digest': None}
    manifest = connection.get('manifest') or {}
    if 'research_question' in manifest:
        observed.update(question=manifest['research_question'], declaration_digest=connection.get('digest'))
        store.put(con, 'research-origin', observed)
    return {'id': 'context', 'version': 0, 'question': observed['question'], 'hypothesis': '',
            'outcome_metric_ref': None, 'baseline_ref': None, 'updated_at': None,
            'origin': 'manifest', 'declaration_digest': observed['declaration_digest']}


def _read_context(slug, conn):
    try:
        return store.read(slug, 'research-context', 'context')
    except store.Missing:
        pass
    try:
        observed = store.read(slug, 'research-origin', 'manifest')
    except store.Missing:
        observed = {'question': '', 'declaration_digest': None}
    manifest = conn.get('manifest') or {}
    return {'id': 'context', 'version': 0, 'question': manifest.get('research_question', observed['question']),
            'hypothesis': '', 'outcome_metric_ref': None, 'baseline_ref': None, 'updated_at': None,
            'origin': 'manifest', 'declaration_digest': conn.get('digest', observed.get('declaration_digest'))}


def context(slug):
    conn = load_connection(service.project(slug)['path'], resolve_choices=False)
    return _read_context(slug, conn)


def update_context(slug, body):
    conn = load_connection(service.project(slug)['path'], resolve_choices=False)
    body = copy.deepcopy(body)
    if body.get('baseline_ref'):
        from controller.workspace_results import validate_references
        body['baseline_ref'] = validate_references(slug, [body['baseline_ref']])[0]
    if body.get('outcome_metric_ref') and body['outcome_metric_ref'] not in (conn.get('manifest') or {}).get('metrics', {}):
        raise store.WorkspaceError('Select a declared outcome metric')
    with store.transaction(slug) as con:
        current = _context(con, conn)
        if body.get('expected_version') != current['version']:
            raise store.Conflict('Research question changed in another editor. Keep your text and reload the saved revision.',
                                 current_version=current['version'], expected_version=body.get('expected_version'))
        for field in ('question', 'hypothesis'):
            if field in body and (not isinstance(body[field], str) or len(body[field]) > 20000):
                raise store.WorkspaceError(f'{field} must be text of at most 20000 characters')
        store.put(con, 'research-history', {**current, 'id': f"context-v{current['version']}"})
        value = {**current, **{k: body[k] for k in ('question', 'hypothesis', 'outcome_metric_ref', 'baseline_ref') if k in body},
                 'version': current['version'] + 1, 'origin': 'workspace', 'updated_at': store.now(), 'actor': 'local operator'}
        return store.put(con, 'research-context', value)


def save_evidence(slug, kind, body, identity=None):
    if kind not in ('note', 'pin'):
        raise store.WorkspaceError('Unsupported research metadata kind')
    from controller.workspace_results import validate_references
    refs = body.get('evidence', []) if kind == 'note' else [body.get('reference')]
    if not isinstance(refs, list):
        raise store.WorkspaceError('Evidence must be a list of exact references')
    frozen = validate_references(slug, refs) if refs else []
    text = body.get('text' if kind == 'note' else 'label', '')
    if not isinstance(text, str) or len(text) > 20000 or (kind == 'note' and not text.strip()):
        raise store.WorkspaceError('Supply text of at most 20000 characters')
    with store.transaction(slug) as con:
        current = store.get(con, 'evidence-' + kind, identity) if identity else {'id': store.new_id(kind), 'version': 0}
        if body.get('expected_version') != current['version']:
            raise store.Conflict('Evidence metadata changed. Reload its revision without discarding your edits.',
                                 current_version=current['version'], expected_version=body.get('expected_version'))
        if current['version']:
            store.put(con, 'evidence-history', {**current, 'id': current['id'] + '-v' + str(current['version']), 'entity_id': current['id']})
        value = {**current, 'version': current['version'] + 1, 'text': text, 'evidence': frozen,
                 'actor': 'local operator', 'updated_at': store.now()}
        return store.put(con, 'evidence-' + kind, value)


def acknowledge(slug, body):
    identity = body.get('observation_id')
    store.safe_id(identity)
    with store.transaction(slug) as con:
        return store.put(con, 'attention-ack', {'id': identity, 'updated_at': store.now()})


def overview(slug, scope=None, cursor=0):
    scope = {k: v for k, v in (scope or {}).items() if v and k in ('collection', 'campaign')}
    rec = service.project(slug)
    conn = load_connection(rec['path'], resolve_choices=False)
    stamp = store.now()
    research = _read_context(slug, conn)
    records, section_errors = {}, {}
    for kind in ('experiment', 'execution', 'artifact', 'plan', 'comparison', 'evidence-note', 'evidence-pin', 'maintenance-action', 'attention-ack', 'operation'):
        try:
            records[kind] = store.listing(slug, kind)
        except (store.WorkspaceError, OSError, ValueError) as exc:
            records[kind] = []
            section_errors[kind] = str(exc)
    plans = {p['id']: p for p in records['plan']}
    def matches(item):
        plan = plans.get(item.get('plan_id', item.get('execution_id')), {})
        config = plan.get('config', item.get('draft', {}))
        from controller.workspace_results import field
        collection = item.get('collection') or field(item, item.get('result_schema', {}).get('family_path', 'provenance.parameters.family')) or config.get('collection') or config.get('parameters', {}).get('collection')
        return all((collection if k == 'collection' else item.get('campaign', plan.get('campaign'))) == v for k, v in scope.items())
    executions = [r for r in records['execution'] if matches(r)]
    artifacts = [a for a in records['artifact'] if matches(a) and a.get('purpose') != 'smoke-test']
    experiments = [e for e in records['experiment'] if matches(e)]
    base = f'/projects/{slug}'
    def link(section, **query):
        return base + '/' + section + ('?' + urlencode({**scope, **query}) if scope or query else '')
    attention, activity = [], []
    ack = {a['id'] for a in records['attention-ack']}
    def add_attention(entity, cause, priority, href, purpose=None):
        observation = 'attention-' + digest([entity['id'], cause, entity.get('updated_at'), entity.get('state')])[:24]
        if observation not in ack:
            attention.append({'id': observation, 'entity_id': entity['id'], 'cause': cause, 'priority': priority,
                              'href': href, 'purpose': purpose, 'observed_at': entity.get('updated_at', stamp)})
    from controller.workspace_runs import ACTIVE, ATTENTION
    active_ids, uncertain_ids, needs_ids = set(), set(), set()
    for execution in executions:
        states = {s.get('state') for s in execution.get('stages', [])}
        if states & ACTIVE:
            active_ids.add(execution['id'])
        if 'uncertain' in states:
            uncertain_ids.add(execution['id'])
        if states & ATTENTION:
            needs_ids.add(execution['id'])
        for stage in execution.get('stages', []):
            if stage.get('state') in ('uncertain', 'submitting', 'failed', 'rejected', 'blocked'):
                add_attention({**stage, 'id': execution['id'] + '--' + stage['id'], 'updated_at': stage.get('updated_at', execution.get('updated_at'))},
                              stage['state'], 0 if stage['state'] in ('uncertain', 'submitting') else 1,
                              link('runs', execution=execution['id'], stage=stage['id']), stage.get('purpose'))
        activity.append({'id': execution['id'], 'kind': 'execution', 'state': execution.get('state'),
                         'updated_at': execution.get('updated_at', execution.get('created_at')), 'href': link('runs', execution=execution['id'])})
    for operation in records['operation']:
        unresolved = operation.get('state') in ('uncertain', 'applying', 'rejected', 'partial') or any(t.get('state') == 'uncertain' for t in operation.get('targets', []))
        if unresolved and operation.get('execution_id') in {e['id'] for e in executions}:
            needs_ids.add(operation['execution_id'])
            if operation.get('state') == 'uncertain' or any(t.get('state') == 'uncertain' for t in operation.get('targets', [])):
                uncertain_ids.add(operation['execution_id'])
            add_attention(operation, 'Unresolved ' + operation.get('kind', 'management') + ' action', 0, link('runs', execution=operation['execution_id']))
    active, uncertain, needs = len(active_ids), len(uncertain_ids), len(needs_ids)
    from controller.workspace_results import project_currency
    for artifact in artifacts:
        artifact.update(project_currency(artifact, {a['id']: a for a in records['artifact']}, {e['id']: e for e in records['execution']}, plans))
    reports = [a for a in artifacts if a.get('schema') == 'report' or a.get('kind') == 'report' or a.get('output_id') == 'report']
    for artifact in artifacts:
        if not artifact.get('complete', artifact.get('completeness') == 'complete'):
            add_attention(artifact, 'incomplete data', 2, link('results', artifact=artifact['id']))
        activity.append({'id': artifact['id'], 'kind': 'retrieval', 'state': artifact.get('fetch_state', artifact.get('availability')),
                         'updated_at': artifact.get('updated_at', artifact.get('created_at')), 'href': link('results', artifact=artifact['id'])})
    for action in records['maintenance-action']:
        activity.append({'id': action['id'], 'kind': 'maintenance', 'state': action.get('state'),
                         'updated_at': action.get('updated_at'), 'href': link('settings', maintenance=action['id'])})
        if action.get('state') in ('recovery_required', 'uncertain'):
            add_attention(action, 'maintenance recovery required', -1, link('settings', maintenance=action['id']))
    if not conn['valid']:
        add_attention({'id': 'connection', 'updated_at': None}, 'Connection declaration needs attention', -1, link('settings'))
    def count(value, predicate, href):
        return {'value': value, 'predicate': predicate, 'observed_at': stamp, 'href': href}
    counts = {
        'experiments': {state: count(sum(e.get('readiness', 'unchecked') == state for e in experiments), 'readiness=' + state, link('experiments', readiness=state)) for state in ('unchecked', 'ready', 'needs-input')},
        'runs': {'active': count(active, 'state=active', link('runs', state='active')),
                 'needs_attention': count(needs, 'attention=needs_attention', link('runs', attention='needs_attention')),
                 'uncertain': count(uncertain, 'attention=uncertain', link('runs', attention='uncertain'))},
        'results': {'current_reports': count(sum(a.get('complete', False) and a.get('currency') == 'current' for a in reports), 'currency=current', link('results', currency='current')),
                    'incomplete': count(sum(not a.get('complete', False) for a in artifacts), 'completeness=incomplete', link('results', completeness='incomplete')),
                    'stale_reports': count(sum(a.get('currency') == 'earlier-inputs' for a in reports), 'currency=newer-inputs', link('results', currency='newer-inputs'))}}
    for category, source in (('experiments', 'experiment'), ('runs', 'execution'), ('results', 'artifact')):
        if source in section_errors:
            for item in counts[category].values():
                item.update(value=None, error=section_errors[source])
    continuations = [{'id': e['id'], 'kind': 'draft', 'title': e.get('name'), 'href': link('experiments/' + e['id']), 'updated_at': e.get('updated_at')} for e in experiments[:5]]
    continuations += [{'id': e['id'], 'kind': 'execution', 'title': e['id'], 'href': link('runs', execution=e['id']), 'updated_at': e.get('updated_at')} for e in executions[:5]]
    continuations += [{'id': c['id'], 'kind': 'comparison', 'title': c.get('name', c['id']), 'href': link('results', comparison=c['id']), 'updated_at': c.get('updated_at')} for c in records['comparison'] if matches(c)][:5]
    activity.sort(key=lambda a: a.get('updated_at') or '', reverse=True)
    cursor = max(0, int(cursor))
    for pin in records['evidence-pin']:
        try:
            from controller.workspace_results import validate_references
            validate_references(slug, pin['evidence'])
            pin['availability'] = 'available'
        except (store.WorkspaceError, OSError, ValueError):
            pin['availability'] = 'unresolved'
    scheduler_times = [(e.get('scheduler_observation') or {}).get('checked_at') for e in executions]
    from controller.workspace_contracts import observation
    sections = {k: observation('workspace indexed metadata', stamp, stale_after=60) for k in ('research', 'experiments', 'results')}
    sections['runs'] = observation('scheduler', min((t for t in scheduler_times if t), default=None))
    for category, source in (('experiments', 'experiment'), ('runs', 'execution'), ('results', 'artifact')):
        if source in section_errors:
            sections[category].update(availability='unavailable', state='unavailable', error=section_errors[source])
    return {'project': rec, 'research_context': research, 'scope': scope, 'counts': counts,
            'attention': sorted(attention, key=lambda a: (a['priority'], a['id'])), 'continuations': continuations,
            'pins': records['evidence-pin'], 'notes': records['evidence-note'], 'activity': activity[cursor:cursor + 20],
            'activity_cursor': cursor + 20 if len(activity) > cursor + 20 else None,
            'sections': sections,
            'collections': [{'id': 'original', 'title': 'Original corpus'}, {'id': 'tlaibench', 'title': 'TLAiBench', 'limitation': 'First numbers; retain declared measurement limitations'}]}
