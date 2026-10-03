"""Application service for human-reviewed project experiments."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from controller import registry
from controller import workspace_store as store
from controller.workspace_store import WorkspaceError, Conflict, Missing


def project(slug):
    rec = registry.get(slug)
    if rec is None:
        raise Missing(f"unknown project {slug}")
    return rec


def connection(slug):
    from controller.workspace_connection import load_connection
    rec = project(slug)
    result = load_connection(Path(rec['path']))
    result['project'] = {k: rec[k] for k in ('slug', 'path', 'primitive')}
    manifest = result.get('manifest') or {}
    result['migration'] = {
        'schema_version': 1,
        'legacy': {'primitive': rec['primitive']},
        'workspace': {'primitive': manifest.get('default_primitive', 'multi-gpu' if rec['primitive'] == 'ml' else rec['primitive']),
                      'mode': manifest.get('default_mode', 'coordinated' if rec['primitive'] == 'ml' else 'independent'),
                      'application': manifest.get('application', '')},
        'historical_values_preserved': True,
        'activation': 'workspace declaration only; legacy registry and ledger unchanged',
    }
    return result


def _connection(slug):
    value = connection(slug)
    if not value.get('valid'):
        raise WorkspaceError('Project connection is invalid: ' + json.dumps(value.get('errors', [])))
    if 'research_question' in value.get('manifest', {}):
        from controller.workspace_overview import _context
        with store.transaction(slug) as con:
            _context(con, value)
    return value


def create(slug, body):
    from controller.workspace_settings import materialize_defaults
    conn = _connection(slug)
    manifest = conn['manifest']
    workflow = body.get('workflow') or body.get('draft', {}).get('workflow')
    composed = workflow == '__composition__' or bool(body.get('draft', {}).get('graph'))
    if composed:
        from controller.workspace_composition import supported
        if not supported(manifest):
            raise WorkspaceError('Composition requires supported typed operation declarations')
        workflow = '__composition__'
    if not composed and workflow not in manifest['workflows']:
        raise WorkspaceError('Select a declared workflow')
    definition = manifest['workflows'].get(workflow, {'parameters': list(manifest.get('parameters', {})), 'stages': []})
    params = {k: spec['default'] for k, spec in manifest.get('parameters', {}).items()
              if 'default' in spec and k in definition.get('parameters', manifest.get('parameters', {}))}
    params.update(definition.get('defaults', {}))
    draft = dict(name=body.get('name') or definition.get('title', workflow), workflow=workflow,
                 parameters=params, variant_parameters={}, combination_mode='all', excluded_variants=[],
                 prerequisites='add', existing_artifacts={}, resources={},
                 metrics=[m for m in definition.get('metrics', []) if not manifest.get('metrics', {}).get(m, {}).get('optional')], include_smoke_test=bool(definition.get('smoke_test_required')),
                 variant_concurrency=manifest.get('variant_concurrency', 1))
    if composed:
        draft['graph'] = {'nodes': [], 'edges': []}
    draft.update(body.get('draft', {}))
    draft = materialize_defaults(manifest, draft)
    return store.create_experiment(slug, draft)


def check(slug, identity):
    from controller.workspace_planner import check_configuration
    rec = project(slug)
    item = store.read(slug, 'experiment', identity)
    result = check_configuration(Path(rec['path']), _connection(slug), item['draft'],
                                 artifacts=store.listing(slug, 'artifact'), run_checks=True)
    with store.transaction(slug) as con:
        current = store.get(con, 'experiment', identity)
        if current['version'] == item['version']:
            current['readiness'] = 'ready' if result.get('valid', result.get('ok', False)) else 'needs-input'
            current['checks'] = result
            store.put(con, 'experiment', current)
    return result


def plan(slug, identity):
    from controller.workspace_planner import compile_plan
    rec = project(slug)
    item = store.read(slug, 'experiment', identity)
    plan_id = store.new_id('plan')
    folder = Path(rec['path']) / '.unity-workspace' / 'plans' / plan_id
    value = compile_plan(Path(rec['path']), _connection(slug), item['draft'], plan_id, folder,
                         artifacts=store.listing(slug, 'artifact'))
    value.update(id=plan_id, experiment_id=identity, experiment_version=item['version'],
                 revision=item['revision'], created_at=store.now(), kind='experiment')
    value['runtime_connection'] = {k: rec.get(k) for k in ('path', 'remote_dir', 'unity_host', 'overrides')}
    _job_template(folder, value)
    _freeze_runtime(rec, folder, value)
    with store.transaction(slug) as con:
        current = store.get(con, 'experiment', identity)
        if current['version'] != item['version']:
            raise Conflict('Draft changed while the plan was compiled. Review the new draft.',
                           current_version=current['version'], expected_version=item['version'])
        if item['executions']:
            prior = store.get(con, 'execution', item['executions'][-1])
            before = store.get(con, 'plan', prior['plan_id'])
            value['previous_execution_id'] = prior['id']
            value['differences'] = _differences(before.get('config', before.get('draft', {})), item['draft'])
            review_fields = {
                'source_digest': lambda p: p.get('source', {}).get('digest'),
                'input_references': lambda p: p.get('inputs', []),
                'effective_resources': lambda p: [{'variant': s['variant_id'], 'stage': s['stage_id'], 'resources': s['resources']} for s in p['stages']],
                'measurement_definitions': lambda p: p.get('metrics', []),
                'runtime_environment': lambda p: p.get('runtime_overrides', {}),
            }
            value['differences'] += _differences({key: read(before) for key, read in review_fields.items()},
                                                {key: read(value) for key, read in review_fields.items()})
        _seal_plan(folder, value)
        store.put(con, 'plan', value)
    return value


def _differences(before, after):
    return [{'field': key, 'before': before.get(key), 'after': after.get(key)}
            for key in sorted(before.keys() | after.keys()) if before.get(key) != after.get(key)]


def _job_template(folder, value):
    """A frozen generic allocation wrapper. The operation declares rank launch."""
    path = Path(__file__).resolve().parents[1] / 'templates/scaffold/gpu/job_template.sh'
    template = path.read_text()
    source_hook = f'.unity-workspace/plans/{value["id"]}/source/unityHPC/bootstrap.sh'
    template = template.replace('unityHPC/bootstrap.sh', source_hook)
    target = folder / 'job_template.sh'
    target.write_text(template)
    value['job_template_digest'] = hashlib.sha256(target.read_bytes()).hexdigest()


def dispatch_plan(slug, plan_id, key):
    from controller.workspace_worker import project_lock
    from controller.workspace_schedules import guard_immediate_dispatch
    with project_lock(slug) as acquired:
        if not acquired:
            raise Conflict('Execution worker is busy. Retry approval with the same idempotency key.')
        guard_immediate_dispatch(slug, plan_id)
        return _dispatch_plan(slug, plan_id, key)


def _dispatch_plan(slug, plan_id, key):
    from controller.workspace_planner import verify_plan
    from controller.workspace_settings import maintenance_blocked
    if maintenance_blocked(slug):
        raise Conflict('Connection maintenance requires reconciliation before dispatch')
    if not isinstance(key, str) or not key or len(key) > 200:
        raise WorkspaceError('Dispatch requires an idempotency_key of at most 200 characters')
    rec = project(slug)
    with store.transaction(slug) as con:
        found = con.execute('SELECT plan_id,execution_id FROM dispatch_keys WHERE key=?', (key,)).fetchone()
        if found:
            if found[0] != plan_id:
                raise Conflict('This idempotency key already approves a different plan')
            return store.get(con, 'execution', found[1])
        value = store.get(con, 'plan', plan_id)
        existing = next((x for x in store.list_records(con, 'execution') if x['plan_id'] == plan_id), None)
        if existing:
            con.execute('INSERT INTO dispatch_keys VALUES(?,?,?)', (key, plan_id, existing['id']))
            return existing
        item = store.get(con, 'experiment', value['experiment_id']) if value.get('experiment_id') else None
        if item and value.get('kind') != 'recovery' and (item['version'] != value['experiment_version'] or item['revision'] != value['revision']):
            raise Conflict('Draft changed after review. Check and review a new plan.',
                           current_version=item['version'], expected_version=value['experiment_version'])
        if value.get('runtime_connection') != {k: rec.get(k) for k in ('path', 'remote_dir', 'unity_host', 'overrides')}:
            raise Conflict('Project runtime connection changed after review')
        verification = verify_plan(Path(rec['path']), value)
        if verification is False or (isinstance(verification, dict) and not verification.get('valid', verification.get('ok', True))):
            raise Conflict('Source, inputs, or configuration changed after review: ' + json.dumps(verification))
        if not value.get('stages'):
            raise WorkspaceError('The plan has no executable stages')
        checkpoints = {s['resume_from'] for s in value['stages'] if s.get('resume_from')}
        for active in store.list_records(con, 'execution'):
            if any(s.get('resume_from') in checkpoints and s['state'] not in ('completed', 'failed', 'rejected', 'superseded', 'cancelled', 'canceled', 'skipped') for s in active['stages']):
                raise Conflict('A checkpoint already has an active resume attempt')
        stages = []
        for stage in value['stages']:
            attempt = dict(id=store.new_id('attempt'), number=1,
                           exp='ws-' + hashlib.sha256((plan_id + stage['id']).encode()).hexdigest()[:24],
                           state='waiting', job_ids=[], purpose=stage.get('purpose', 'experiment'),
                           created_at=store.now())
            stages.append(dict(id=stage['id'], variant_id=stage.get('variant_id'), purpose=attempt['purpose'],
                               location=stage['location'], resume_from=stage.get('resume_from'), state='waiting', attempts=[attempt],
                               job_ids=[], artifacts=[], fetch_state='not-requested', completeness='unknown'))
        execution = dict(id=plan_id, plan_id=plan_id, experiment_id=value.get('experiment_id'),
                         revision=value.get('revision'), kind=value.get('kind', 'experiment'),
                         state='approved', approved_at=store.now(), updated_at=store.now(),
                         stages=stages, campaign=plan_id, source=value.get('source'),
                         recovery=value.get('recovery'), bundle_uploaded=False)
        if value.get('recovery'):
            parent = store.get(con, 'execution', value['recovery']['execution_id'])
            original_specs = {s['id']: s for s in store.get(con, 'plan', parent['plan_id'])['stages']}
            for stage in execution['stages']:
                match = next((s for s in parent['stages'] if s['variant_id'] == stage['variant_id'] and original_specs[s['id']]['stage_id'] == next(p['stage_id'] for p in value['stages'] if p['id'] == stage['id'])), None)
                if match:
                    if match['state'] not in ('failed', 'rejected', 'waiting', 'blocked', 'cancelled', 'canceled') or match.get('continued_by'):
                        raise Conflict('Recovery scope changed or was already approved. Review again.')
                    stage['attempts'][0].update(previous_attempt_id=match['attempts'][-1]['id'], number=match['attempts'][-1]['number'] + 1)
                    match['continued_by'] = plan_id
                    if match['state'] == 'waiting':
                        match['state'] = 'superseded'
            parent.setdefault('recovery_executions', []).append(plan_id)
            store.put(con, 'execution', parent)
        store.put(con, 'execution', execution)
        con.execute('INSERT INTO dispatch_keys VALUES(?,?,?)', (key, plan_id, plan_id))
        if item:
            item['executions'].append(plan_id)
            item['frozen_revision'] = item['revision']
            store.put(con, 'revision', dict(id=f"{item['id']}-r{item['revision']}",
                                          experiment_id=item['id'], revision=item['revision'], draft=item['draft']))
            store.put(con, 'experiment', item)
    # The durable worker starts on controller startup. Approval only records intent.
    return execution


def clone(slug, identity, body=None):
    item = store.read(slug, 'experiment', identity)
    draft = copy.deepcopy(item['draft'])
    draft.update((body or {}).get('draft', {}))
    draft['name'] = draft.get('name', item['name']) + ' (copy)'
    return store.create_experiment(slug, draft, cloned_from={'experiment_id': identity, 'revision': item['revision']})


def recovery(slug, execution_id, body):
    """Build fresh retry outputs from the exact failed scope and complete parents."""
    from controller.workspace_planner import compile_plan, verify_plan
    rec = project(slug)
    root = Path(rec['path'])
    execution = store.read(slug, 'execution', execution_id)
    original = store.read(slug, 'plan', execution['plan_id'])
    conn = _connection(slug)
    mode = body.get('mode', 'retry')
    if mode not in ('retry', 'resume', 'replace', 'checked-outputs'):
        raise WorkspaceError('Recovery mode must be retry, resume, replace, or checked-outputs')
    if mode == 'resume' and not conn['manifest'].get('resume', {}).get('supported'):
        raise Conflict('This connection has no audited resume operation. Retry creates fresh outputs after compatibility checks.')
    selected = body.get('stage_ids')
    if not isinstance(selected, list) or not selected or any(not isinstance(x, str) for x in selected):
        raise WorkspaceError('Recovery requires explicit stage_ids')
    specs = {s['id']: s for s in original['stages']}
    states = {s['id']: s for s in execution['stages']}
    if any(s not in specs for s in selected):
        raise WorkspaceError('Recovery contains an unknown stage')
    if any(states[s]['state'] not in ('failed', 'rejected', 'waiting', 'blocked', 'cancelled', 'canceled') for s in selected):
        raise Conflict('Recovery cannot resubmit accepted, completed, running, or uncertain work. Reconcile uncertain submissions with the ledger first.')
    compatibility = verify_plan(root, original)
    if not compatibility['valid']:
        raise Conflict('Recovery source or inputs changed. Start a new revision instead: ' + json.dumps(compatibility['errors']))
    requested = list(selected)
    if mode == 'checked-outputs':
        # Explicitly reuse checked producers without rewriting their failed state.
        producers = set(selected)
        evidence = store.listing(slug, 'artifact')
        for key in producers:
            if states[key]['state'] not in ('failed', 'cancelled', 'canceled') or not any(
                a.get('execution_id') == execution_id and a.get('stage_id') == key
                and a.get('complete') and a.get('purpose') == 'experiment' for a in evidence
            ):
                raise Conflict('Use checked outputs requires complete research evidence from a stopped producer')
        selected = [s['id'] for s in original['stages']
                    if states[s['id']]['state'] in ('waiting', 'blocked')
                    and producers.intersection(s.get('depends_on', []))]
        if not selected:
            raise Conflict('No waiting dependent can consume these checked outputs')
    scope = set(selected)
    while True:
        descendants = {s['id'] for s in original['stages'] if states[s['id']]['state'] == 'waiting' and set(s.get('depends_on', [])).intersection(scope)}
        expanded = scope | descendants
        if expanded == scope:
            break
        scope = expanded
    selected = [s['id'] for s in original['stages'] if s['id'] in scope]
    if any(states[s].get('continued_by') for s in selected):
        raise Conflict('This scope already has an approved recovery execution')
    artifacts = store.listing(slug, 'artifact')
    # Compile one exact selection at a time. This avoids a Cartesian stage/variant scope expansion.
    variants = {specs[s]['variant_id'] for s in selected}
    selected_declarations = {specs[s]['stage_id'] for s in selected}
    expected = {s['id'] for s in original['stages'] if s['variant_id'] in variants and s['stage_id'] in selected_declarations}
    if expected != set(selected):
        raise WorkspaceError('Select the same stage scope for each selected variant, or review separate recovery plans')
    draft = copy.deepcopy(original['config'])
    draft.update(combination_mode='explicit', combinations=[{k: val for k, val in v['parameters'].items() if conn['manifest']['parameters'][k].get('variant_eligible')} for v in original['variants'] if v['id'] in variants],
                 variant_parameters={}, excluded_variants=[], stages=sorted(selected_declarations), prerequisites='existing',
                 include_smoke_test=any(specs[s]['purpose'] == 'smoke-test' for s in selected))
    refs = {}
    for key in selected:
        for dependency in specs[key].get('depends_on', []):
            if dependency in selected:
                continue
            parent = next((a for a in artifacts if a['execution_id'] == execution_id and a['stage_id'] == dependency and a['complete'] and (a['purpose'] != 'smoke-test' or (specs[dependency]['purpose'] == 'smoke-test' and states[dependency]['state'] == 'completed'))), None)
            if parent is None:
                raise Conflict(f'Prerequisite {dependency} needs a complete, compatible artifact or explicit inclusion in recovery')
            refs[specs[key]['variant_id'] + ':' + specs[dependency]['stage_id']] = parent['id']
    draft['existing_artifacts'] = refs
    resource_changes = body.get('resources', {})
    if resource_changes and mode != 'replace':
        raise WorkspaceError('Resource changes require a replacement review')
    if not isinstance(resource_changes, dict):
        raise WorkspaceError('Replacement resources must map selected stage IDs to resource fields')
    for key, changes in resource_changes.items():
        if key not in selected_declarations or not isinstance(changes, dict):
            raise WorkspaceError('Replacement resources must address only selected declared stages')
        draft.setdefault('resources', {}).setdefault(key, {}).update(changes)
    if mode == 'resume':
        from controller import workspace_worker as worker
        check_operation = conn['manifest']['resume'].get('check_operation')
        if not check_operation:
            raise Conflict('Resume requires a declared checkpoint compatibility check')
        resume_refs = {}
        for key in requested:
            if states[key]['state'] not in ('failed', 'cancelled', 'canceled'):
                raise Conflict('Resume selects stopped stages with saved checkpoint evidence')
            checkpoint = next((a for a in artifacts if a['execution_id'] == execution_id and a['stage_id'] == key and a.get('files')), None)
            if checkpoint is None:
                raise Conflict('No saved checkpoint exists for ' + key + '. Retrieve its artifacts before resume.')
            result = worker.operation(root, original, check_operation, specs[key])
            try:
                evidence = json.loads(result['output'])
            except ValueError:
                evidence = {}
            if not result['ok'] or not evidence.get('resumable'):
                raise Conflict('Checkpoint is incompatible: ' + result['output'])
            resume_refs[specs[key]['variant_id'] + ':' + specs[key]['stage_id']] = checkpoint['id']
        draft['resume_artifacts'] = resume_refs
    else:
        draft.pop('resume_artifacts', None)
    plan_id = store.new_id('plan')
    folder = root / '.unity-workspace/plans' / plan_id
    value = compile_plan(root, conn, draft, plan_id, folder, artifacts=artifacts)
    value.update(id=plan_id, kind='recovery', experiment_id=original.get('experiment_id'),
                 revision=original.get('revision'), experiment_version=original.get('experiment_version'),
                 created_at=store.now(), recovery={'execution_id': execution_id, 'stage_ids': selected, 'requested_stage_ids': requested, 'mode': mode},
                 differences=[{'field': 'recovery_scope', 'before': execution_id, 'after': selected}],
                 runtime_connection={k: rec.get(k) for k in ('path', 'remote_dir', 'unity_host', 'overrides')})
    value['differences'] += _differences(original['config'].get('resources', {}), draft.get('resources', {}))
    _job_template(folder, value)
    _freeze_runtime(rec, folder, value)
    with store.transaction(slug) as con:
        # Recovery is attached to its original revision, independently of later draft saves.
        value['experiment_version'] = store.get(con, 'experiment', value['experiment_id'])['version'] if value.get('experiment_id') else None
        _seal_plan(folder, value)
        store.put(con, 'plan', value)
    return value


def analysis(slug, body):
    """Compile only a declared analysis operation over explicit complete artifacts."""
    from controller.workspace_planner import compile_plan
    from controller.workspace_artifacts import freeze_inputs
    rec = project(slug)
    root = Path(rec['path'])
    conn = _connection(slug)
    manifest = copy.deepcopy(conn['manifest'])
    declarations = manifest.get('analyses', {})
    analysis_name = body.get('analysis')
    if body.get('analysis') is not None and body['analysis'] not in declarations:
        raise WorkspaceError('Select a declared analysis')
    declaration = declarations.get(body.get('analysis'), {})
    operation_id = body.get('operation') or declaration.get('operation')
    if not declaration and operation_id:
        matching = [(name, d) for name, d in declarations.items() if d.get('operation') == operation_id]
        if len(matching) > 1:
            raise WorkspaceError('Several analyses use this operation. Select an explicit analysis declaration.')
        if matching:
            analysis_name, declaration = matching[0]
    if declaration and declaration.get('operation') != operation_id:
        raise WorkspaceError('Analysis operation does not match its declaration')
    if operation_id not in manifest.get('analysis_operations', []):
        raise WorkspaceError('Select a declared analysis operation')
    selected = body.get('artifact_ids')
    if not isinstance(selected, list) or not selected:
        raise WorkspaceError('Analysis requires selected artifact_ids')
    artifacts = freeze_inputs(slug, selected)
    from controller.workspace_results import check_analysis_metrics
    check_analysis_metrics(slug, artifacts, body.get('metrics', []), manifest.get('metrics', {}))
    selected = [a['id'] for a in artifacts]
    if any(not a['complete'] or a['purpose'] == 'smoke-test' for a in artifacts):
        raise Conflict('Analysis requires complete research artifacts. Missing inputs need an explicit collection plan.')
    if declaration and any(a.get('schema') != declaration.get('input_schema') or a.get('version') != declaration.get('input_version') for a in artifacts):
        raise Conflict('Selected artifacts are incompatible with this analysis schema or version')
    operation = copy.deepcopy(manifest['operations'][operation_id])
    inputs = json.dumps(['__UNITY_PROJECT_ROOT__/' + a.get('frozen_path', a['path']) for a in artifacts])
    operation['argv'] = [inputs if isinstance(a, dict) and a.get('context') == 'analysis_input_dirs' else a for a in operation['argv']]
    manifest['operations'][operation_id] = operation
    outputs = declaration.get('outputs') or operation.get('outputs') or manifest.get('analysis_outputs')
    if not outputs:
        raise WorkspaceError('The analysis operation must declare its outputs')
    manifest['workflows']['saved-analysis'] = {
        'parameters': list(body.get('parameters', {})), 'metrics': body.get('metrics', []),
        'stages': [{'id': 'analysis', 'operation': operation_id, 'purpose': 'experiment', 'outputs': outputs,
                    'check_operation': operation.get('check_operation', ''), 'location': operation['location'],
                    'resources': operation.get('resources', {'primitive': 'cpu', 'mode': 'single', 'gpus': 0})}]}
    draft = {'workflow': 'saved-analysis', 'parameters': body.get('parameters', {}),
             'metrics': body.get('metrics', []), 'variant_concurrency': 1,
             'existing_artifacts': {str(i): a['id'] for i, a in enumerate(artifacts)}}
    plan_id = store.new_id('plan')
    folder = root / '.unity-workspace/plans' / plan_id
    value = compile_plan(root, {**conn, 'manifest': manifest}, draft, plan_id, folder, artifacts=artifacts)
    value.update(id=plan_id, kind='analysis', artifact_ids=selected, created_at=store.now(),
                 analysis_name=analysis_name, analysis_operation=operation_id,
                 source_executions=sorted({a['execution_id'] for a in artifacts if a.get('execution_id')}),
                 runtime_connection={k: rec.get(k) for k in ('path', 'remote_dir', 'unity_host', 'overrides')})
    _job_template(folder, value)
    _freeze_runtime(rec, folder, value)
    with store.transaction(slug) as con:
        earlier = [p for p in store.list_records(con, 'plan') if p.get('kind') == 'analysis']
        value['analysis_revision'] = 1 + max((p.get('analysis_revision', 0) for p in earlier), default=0)
        related = [p for p in earlier if p.get('analysis_name') == analysis_name and
                   (p.get('analysis_operation') or (p.get('stages') or [{}])[0].get('operation')) == operation_id]
        predecessor = max(related, key=lambda p: p.get('analysis_revision', 0), default=None)
        value['predecessor_plan_id'] = predecessor['id'] if predecessor else None
        if predecessor:
            def analysis_basis(p):
                return {'artifact_ids': p.get('artifact_ids'), 'metrics': p.get('metrics'),
                        'parameters': p.get('config', {}).get('parameters'), 'source_digest': p.get('source', {}).get('digest')}
            value['differences'] = _differences(analysis_basis(predecessor), analysis_basis(value))
        _seal_plan(folder, value)
        store.put(con, 'plan', value)
    return value


def artifact_file(slug, identity, relative):
    from controller.workspace_artifacts import download
    return download(slug, identity, relative)


def custom_script(slug, plan_id, body):
    import os
    import fcntl
    from controller.workspace_planner import save_custom_script
    rec = project(slug)
    root = Path(rec['path'])
    plan = store.read(slug, 'plan', plan_id)
    stage = next((s for s in plan['stages'] if s['id'] == body.get('stage_id')), None)
    if stage is None:
        raise WorkspaceError('Select a stage from this plan')
    relative = body.get('path')
    if not isinstance(relative, str):
        raise WorkspaceError('A custom script path is required')
    manifest_path = root / 'unityHPC/project.json'
    with (root / 'unityHPC/.workspace-connection.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        manifest = json.loads(manifest_path.read_text())
        identity = 'custom-' + hashlib.sha256(relative.encode()).hexdigest()[:12]
        if identity in manifest['operations'] or identity in manifest['workflows']:
            raise Conflict('This custom operation is already registered')
        saved = save_custom_script(root, plan, stage['id'], relative)
        manifest['operations'][identity] = saved['operation']
        manifest['source_paths'].append(relative)
        # Keep the prerequisite graph when converting a dependent stage. Its
        # parameters become explicit fixed values; handwritten scripts do not
        # claim that unrelated form edits can reconstruct their behavior.
        required = {stage['id']}
        by_id = {s['id']: s for s in plan['stages']}
        pending = [stage['id']]
        while pending:
            for dependency in by_id[pending.pop()].get('depends_on', []):
                if dependency not in required:
                    required.add(dependency)
                    pending.append(dependency)
        frozen_manifest = json.loads((root / '.unity-workspace/plans' / plan_id / 'source/unityHPC/project.json').read_text())
        original_stages = {s['id']: s for s in frozen_manifest.get('workflows', {}).get(plan['workflow'], {}).get('stages', [])}
        custom_stages = []
        for prior in plan['stages']:
            if prior['id'] not in required:
                continue
            declaration = copy.deepcopy(original_stages.get(prior['stage_id'], {}))
            declaration.update(id=prior['stage_id'], operation=identity if prior['id'] == stage['id'] else prior['operation'],
                               purpose=prior['purpose'], resources=prior['resources'], location=prior['location'],
                               parameters=prior['parameters'], optional=False)
            if prior['id'] == stage['id']:
                declaration['outputs'] = saved['outputs']
            custom_stages.append(declaration)
        manifest['workflows'][identity] = {'title': Path(relative).stem, 'parameters': [], 'metrics': [],
                                           'stages': custom_stages,
                                           'smoke_test_required': any(s['purpose'] == 'smoke-test' for s in custom_stages)}
        temp = manifest_path.with_suffix('.json.tmp')
        try:
            with temp.open('x') as stream:
                json.dump(manifest, stream, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, manifest_path)
        except Exception:
            # Preserve the project-owned script even if registration fails.
            raise Conflict(f'Custom source saved at {relative}, but connection registration failed. Register it in project.json.')
    return {**saved, 'workflow': identity}


def execution_logs(slug, execution_id, stage_id=None):
    from controller import dispatch
    rec = project(slug)
    execution = store.read(slug, 'execution', execution_id)
    stages = []
    for stage in execution['stages']:
        if stage_id and stage['id'] != stage_id:
            continue
        output = stage.get('result', {}).get('output', '')
        for job_id in stage.get('job_ids', []):
            response = dispatch._run(rec, ['logs', '--campaign', execution['campaign'], '--job', job_id, '-n', '100'], timeout=30)
            output += '\n' + response.get('output', '')
        stages.append({'id': stage['id'], 'stage_id': stage['id'], 'purpose': stage['purpose'], 'state': stage['state'],
                       'job_ids': stage.get('job_ids', []), 'output': output, 'attempts': stage['attempts']})
    return {'execution_id': execution_id, 'stages': stages,
            'output': '\n\n'.join(f"Purpose: {s['purpose']} | State: {s['state']} | Stage: {s['id']}\n{s['output']}" for s in stages)}


def reconcile(slug, execution_id):
    from controller import workspace_worker as worker
    root = Path(project(slug)['path'])
    with worker.project_lock(slug) as acquired:
        if not acquired:
            raise Conflict('Execution worker is busy; try reconciliation again')
        execution = store.read(slug, 'execution', execution_id)
        plan = store.read(slug, 'plan', execution['plan_id'])
        rows = worker._ledger(root, plan)
        for stage in execution['stages']:
            if stage['state'] in ('submitting', 'uncertain'):
                worker._reconcile(slug, execution, stage, rows)
        worker._save(slug, execution)
        return execution


def fetch_execution(slug, execution_id, body):
    from controller import workspace_worker as worker
    rec = project(slug)
    selected = body.get('stage_ids')
    if not isinstance(selected, list) or not selected:
        raise WorkspaceError('Select explicit stage_ids to retrieve')
    with worker.project_lock(slug) as acquired:
        if not acquired:
            raise Conflict('Execution worker is busy; try retrieval again')
        execution = store.read(slug, 'execution', execution_id)
        execution['slug'] = slug
        plan = store.read(slug, 'plan', execution['plan_id'])
        from controller.workspace_planner import verify_snapshot
        verification = verify_snapshot(Path(rec['path']), plan)
        if not verification['valid']:
            raise Conflict('Frozen execution inputs changed: ' + json.dumps(verification['errors']))
        specifications = {s['id']: s for s in plan['stages']}
        if any(s not in specifications for s in selected):
            raise WorkspaceError('Unknown stage in retrieval scope')
        for stage in execution['stages']:
            if stage['id'] not in selected:
                continue
            if stage['state'] not in ('failed', 'completed'):
                raise Conflict('Retrieve only completed or failed stages')
            worker._finish(rec, plan, specifications[stage['id']], execution, stage,
                           scheduler_ok=stage.get('scheduler_ok', stage['state'] == 'completed'))
        worker._save(slug, execution)
        return execution


def _seal_plan(folder, value):
    from controller.workspace_connection import digest
    value['fingerprint'] = digest({k: v for k, v in value.items() if k != 'fingerprint'})
    path = folder / 'plan.json'
    path.chmod(0o644)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    path.chmod(0o444)


def _freeze_runtime(rec, folder, value):
    """Read declared public settings and render the exact existing allocation path."""
    import os
    import subprocess
    from controller import workspace_dispatch as transport
    root = Path(rec['path'])
    if not any(stage['location'] == 'cluster' for stage in value['stages']):
        return
    runner = root / 'unityHPC/run.sh'
    if not runner.exists():
        # Deterministic fake-dispatch fixtures have no cluster attachment.
        value['runtime_capability'] = 'dispatcher unavailable'
        return
    result = subprocess.run(['bash', str(runner), 'workspace-env'], cwd=root, capture_output=True,
                            text=True, timeout=15, env=dict(os.environ, SSH_ASKPASS_REQUIRE='never'))
    try:
        defaults = json.loads(result.stdout) if result.returncode == 0 else None
    except ValueError:
        defaults = None
    if not isinstance(defaults, dict):
        raise WorkspaceError('Update run.sh with the workspace environment and reviewed-template capabilities before cluster review')
    allowed = {'SLURM_ACCOUNT', 'SLURM_PARTITION', 'SLURM_GPU_TYPE', 'SLURM_CONSTRAINT', 'REMOTE_DIR',
               'REMOTE_RESULTS_DIR', 'UNITY_HOST', 'VENV_PATH', 'MODULES', 'HF_HOME', 'USER_EMAIL'}
    defaults = {k: str(v) for k, v in defaults.items() if k in allowed}
    defaults.update({k: str(v) for k, v in (rec.get('overrides') or {}).items() if k in allowed})
    if rec.get('remote_dir'):
        defaults['REMOTE_DIR'] = rec['remote_dir']
    if rec.get('unity_host'):
        defaults['UNITY_HOST'] = rec['unity_host']
    value['runtime_overrides'] = defaults
    for stage in value['stages']:
        if stage['location'] != 'cluster':
            continue
        for key, env_name in (('account', 'SLURM_ACCOUNT'), ('partition', 'SLURM_PARTITION')):
            stage['resources'].setdefault(key, defaults.get(env_name, ''))
        attempt = {'exp': 'ws-' + hashlib.sha256((value['id'] + stage['id']).encode()).hexdigest()[:24]}
        overrides = transport.overrides(rec, value, stage)
        response = subprocess.run(['bash', str(runner), 'render', attempt['exp']], cwd=root,
                                  capture_output=True, text=True, timeout=15,
                                  env={**os.environ, **overrides, 'CAMPAIGN': value['id']})
        if response.returncode:
            raise WorkspaceError('Cannot render reviewed allocation: ' + response.stderr[-1000:])
        stage['scheduler_script'] = response.stdout
