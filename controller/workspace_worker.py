"""Advance durable, approved graphs without browser sessions or workflow models."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from controller import registry
from controller import workspace_dispatch as transport
from controller import workspace_store as store
from lib import campaign, paths

_ACTIVE = {'accepted', 'running', 'submitting', 'fetching'}
_FAILURE = {'failed', 'rejected', 'uncertain', 'blocked'}
_stop = threading.Event()
_thread = None
_observations = {}
_observed_at = {}


def _save(slug, execution):
    # Actions can persist a stop fence while a local operation is running.
    # Merge those controller-owned fields instead of overwriting a new fence
    # with the worker's earlier in-memory snapshot.
    with store.transaction(slug) as con:
        current = store.get(con, 'execution', execution['id'])
        execution['stop_fences'] = current.get('stop_fences', [])
        by_id = {s['id']: s for s in current['stages']}
        for stage in execution['stages']:
            saved = by_id.get(stage['id'], {})
            for field in ('management_history', 'cancel_requested', 'effective_resources', 'effective_resources_by_job', 'stop_operation_id'):
                if field in saved:
                    stage[field] = saved[field]
            if saved.get('state') == 'cancelled' and stage['state'] in ('waiting', 'submitting', 'running') and not stage.get('job_ids'):
                stage.update(state='cancelled', waiting_reason=saved.get('waiting_reason'))
                stage['attempts'][-1]['state'] = 'cancelled'
        states = [s['state'] for s in execution['stages']]
        if all(s == 'completed' for s in states):
            execution['state'] = 'completed'
        elif any(s in _ACTIVE for s in states):
            execution['state'] = 'active'
        elif all(s in ('cancelled', 'superseded', 'skipped') for s in states):
            execution['state'] = 'cancelled'
        elif any(s in _FAILURE or s == 'cancelled' for s in states):
            execution['state'] = 'paused'
        else:
            execution['state'] = 'approved'
        before = {k: v for k, v in current.items() if k not in ('version', 'updated_at')}
        after = {k: v for k, v in execution.items() if k not in ('version', 'updated_at')}
        changed = before != after
        execution['updated_at'] = store.now() if changed else current.get('updated_at', store.now())
        execution['version'] = int(current.get('version', 0)) + (1 if changed else 0)
        if changed:
            store.put(con, 'execution', execution)


def _change(slug, execution, stage, state, **fields):
    stage.update(state=state, **fields)
    stage['attempts'][-1].update(state=state, updated_at=store.now(), **fields)
    _save(slug, execution)


def run_local(argv, cwd, env=None, timeout=60):
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            out, err = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, err = proc.communicate()
        return {'ok': False, 'output': (out + err)[-100000:], 'returncode': 124,
                'error': f'Controller operation exceeded {timeout} seconds'}
    return {'ok': proc.returncode == 0, 'returncode': proc.returncode, 'output': (out + err)[-100000:]}


def _snapshot(root, plan):
    return root / '.unity-workspace' / 'plans' / plan['id'] / 'source'


def _safe_output(root, value):
    path = (root / value).resolve()
    allowed = (root / '.unity-workspace' / 'outputs').resolve()
    if not path.is_relative_to(allowed):
        raise store.WorkspaceError('Output must stay in the workspace output directory')
    return path


def operation(root, plan, operation_id, stage):
    """Call a frozen declared adapter with concrete contexts and literal arguments."""
    source = _snapshot(root, plan)
    manifest = json.loads((source / 'unityHPC/project.json').read_text())
    definition = manifest['operations'][operation_id]
    output = _safe_output(root, stage['output_dir'])
    context = dict(project_root=str(root), source_root=str(source), output_dir=str(output),
                   relative_output_dir=stage['output_dir'], execution_id=plan['id'],
                   variant_id=stage.get('variant_id', ''), stage_id=stage['id'], purpose=stage.get('purpose', 'experiment'))
    context.update(stage.get('context', {}))
    args = []
    for arg in definition['argv']:
        if isinstance(arg, str):
            args.append(arg)
        elif 'context' in arg:
            value = context[arg['context']]
            args.append(json.dumps(value) if isinstance(value, (list, dict)) else str(value))
        else:
            args.append(str(stage.get('parameters', {})[arg['param']]))
    cwd = (source / definition.get('cwd', '.')).resolve()
    if not cwd.is_relative_to(source.resolve()):
        raise store.WorkspaceError('Adapter working directory escapes snapshot')
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', UNITY_PROJECT_ROOT=str(root))
    return run_local(args, cwd, env, min(int(definition.get('timeout_seconds', 60)), 1800))


def _manifest(root, plan):
    return json.loads((_snapshot(root, plan) / 'unityHPC/project.json').read_text())


def _collect_artifacts(root, plan, specification, stage, execution):
    """Index only declared output trees, including complete evidence after failure."""
    manifest = _manifest(root, plan)
    validator = specification.get('check_operation', manifest.get('check_operation'))
    evidence = None
    if validator and specification.get('outputs'):
        result = operation(root, plan, validator, specification)
        try:
            evidence = json.loads(result['output'])
        except (ValueError, TypeError):
            evidence = {'complete': False, 'errors': [result.get('error') or result['output']]}
        if not result['ok']:
            evidence['complete'] = False
    artifacts = []
    for output in specification.get('outputs', []):
        output_path = output.get('path', specification['output_dir'])
        if not str(output_path).startswith('.unity-workspace/'):
            output_path = str(Path(specification['output_dir']) / output_path)
        path = _safe_output(root, output_path)
        files = []
        errors = []
        if not path.exists():
            errors.append('Declared output is missing')
        elif path.is_file():
            files.append({'path': str(path.relative_to(root)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size': path.stat().st_size})
        else:
            for file in sorted(path.rglob('*')):
                if file.is_symlink() and not file.resolve().is_relative_to(path):
                    errors.append('Artifact symlink escapes its output directory')
                    continue
                if file.is_file():
                    files.append({'path': str(file.relative_to(root)), 'sha256': hashlib.sha256(file.read_bytes()).hexdigest(), 'size': file.stat().st_size})
        for required in output.get('completeness', {}).get('required_files', []):
            if not (path / required).is_file():
                errors.append(f'Missing required file: {required}')
        complete = not errors and (bool(evidence.get('complete')) if evidence is not None else bool(files))
        identity = 'artifact-' + hashlib.sha256((plan['id'] + stage['id'] + output['id']).encode()).hexdigest()[:24]
        artifact = dict(id=identity, execution_id=execution['id'], experiment_id=execution.get('experiment_id'),
                        stage_id=stage['id'], declared_stage_id=specification.get('stage_id', stage['id'].split(':')[-1]),
                        variant_id=stage.get('variant_id'), attempt_id=stage['attempts'][-1]['id'],
                        output_id=output['id'], purpose=stage['purpose'], schema=output['schema'], version=output['version'],
                        path=str(path.relative_to(root)), output_dir=specification['output_dir'],
                        complete=complete, files=files, errors=errors, evidence=evidence,
                        parameters=specification.get('parameters', {}), provenance=(evidence or {}).get('provenance', {}),
                        source_digest=plan.get('source', {}).get('digest'), created_at=store.now(),
                        stage_state='completed' if complete and stage.get('scheduler_ok') else 'failed',
                        execution_location=specification.get('location'),
                        operation_outcome=('succeeded' if stage.get('scheduler_ok') else 'failed') if specification.get('location') == 'controller' else None,
                        scheduler_state=None if specification.get('location') == 'controller' else ('COMPLETED' if stage.get('scheduler_ok') else (stage.get('jobs') or [{}])[0].get('status', 'UNKNOWN')),
                        reports=[f['path'] for f in files if f['path'].endswith(('.md', '.html', '.svg', '.png', '.pdf'))])
        artifact['digest'] = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
        from controller.workspace_artifacts import preserve_artifact
        artifact = preserve_artifact(execution['slug'], artifact)
        artifacts.append(artifact)
    stage['artifacts'] = [a['id'] for a in artifacts]
    stage['completeness'] = 'complete' if all(a['complete'] for a in artifacts) else 'incomplete'
    return all(a['complete'] for a in artifacts)


def _finish(project, plan, specification, execution, stage, scheduler_ok=True):
    root = Path(project['path'])
    slug = project['slug']
    manifest = _manifest(root, plan)
    stage['scheduler_ok'] = scheduler_ok
    fetch_operation = specification.get('fetch_operation', manifest.get('fetch_operation'))
    if specification['location'] == 'cluster' and fetch_operation:
        _change(slug, execution, stage, 'fetching', fetch_state='retrieving')
        result = operation(root, plan, fetch_operation, specification)
        stage['fetch_result'] = result
        if not result['ok']:
            _change(slug, execution, stage, 'failed', fetch_state='failed', error='Artifact retrieval failed')
            return
        stage['fetch_state'] = 'fetched'
    complete = _collect_artifacts(root, plan, specification, stage, execution)
    if scheduler_ok and complete:
        _change(slug, execution, stage, 'completed', completed_at=store.now())
    else:
        _change(slug, execution, stage, 'failed', error='Scheduler failure; review saved evidence' if not scheduler_ok else 'Output completeness check failed')


def _ledger(root, plan):
    campaign.refresh_from_telemetry(root, plan['id'])
    rows = campaign.jobs(root, plan['id'])
    key = (str(root), plan['id'])
    frozen_runner = _snapshot(root, plan) / 'unityHPC/run.sh'
    if (any(r['status'] not in campaign.TERMINAL for r in rows) and frozen_runner.is_file()
            and time.monotonic() - _observed_at.get(key, 0) >= 30):
        from controller import dispatch
        rec = next((p for p in registry.list_projects() if Path(p['path']).resolve() == root.resolve()), None)
        if rec:
            _observed_at[key] = time.monotonic()
            try:
                result = dispatch._run(rec, ['status', '--campaign', plan['id']],
                                       env_overrides=plan.get('runtime_overrides') or None,
                                       runner_path=frozen_runner, timeout=60)
                error = None if result['ok'] and 'sacct failed' not in result['output'] else result['output']
            except Exception as exc:
                error = str(exc)
            _observations[key] = {'checked_at': store.now(), 'error': error}
            rows = campaign.jobs(root, plan['id'])
    return rows


def _reconcile(slug, execution, stage, rows):
    attempt = stage['attempts'][-1]
    matches = [r for r in rows if r.get('exp') == attempt['exp']]
    if matches:
        _change(slug, execution, stage, 'accepted', job_ids=[r['job_id'] for r in matches], error=None)
        return True
    return False


def tick(slug):
    """One deterministic pass. Safe to call in tests with a fake transport."""
    project = registry.get(slug)
    if project is None:
        return
    root = Path(project['path'])
    lock_dir = paths.controller_dir() / 'locks'
    lock_dir.mkdir(parents=True, exist_ok=True)
    with (lock_dir / f'{store.safe_id(slug)}.workspace.lock').open('a+b') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        if any(a.get('state') in ('applying', 'checking', 'recovery_required') for a in store.listing(slug, 'maintenance-action')):
            return
        for execution in store.listing(slug, 'execution'):
            if execution['state'] == 'completed':
                continue
            execution['slug'] = slug
            plan = store.read(slug, 'plan', execution['plan_id'])
            from controller.workspace_planner import verify_snapshot
            verification = verify_snapshot(root, plan)
            template = root / '.unity-workspace/plans' / plan['id'] / 'job_template.sh'
            if not verification['valid'] or not template.is_file() or hashlib.sha256(template.read_bytes()).hexdigest() != plan.get('job_template_digest'):
                execution['integrity_error'] = verification.get('errors') or ['Reviewed allocation template changed']
                _save(slug, execution)
                continue
            execution.pop('integrity_error', None)
            project = {**project, **plan.get('runtime_connection', {})}
            specifications = {s['id']: s for s in plan['stages']}
            stages = {s['id']: s for s in execution['stages']}
            rows = _ledger(root, plan)
            execution['scheduler_observation'] = _observations.get((str(root), plan['id']))
            for stage in execution['stages']:
                spec = specifications[stage['id']]
                state = stage['state']
                if spec['location'] == 'controller' and state in ('running', 'uncertain'):
                    from controller.workspace_local import interrupted_receipt
                    result = interrupted_receipt(root, stage['attempts'][-1]['id'])
                    if result is None:
                        continue
                    stage['result'] = result
                    if result['ok']:
                        _finish(project, plan, spec, execution, stage)
                    else:
                        _collect_artifacts(root, plan, spec, stage, execution)
                        _change(slug, execution, stage, 'cancelled' if stage.get('cancel_requested') else 'failed', error=result.get('error', 'Controller-host operation failed'))
                    continue
                if state in ('submitting', 'uncertain'):
                    if not _reconcile(slug, execution, stage, rows):
                        if state == 'submitting':
                            _change(slug, execution, stage, 'uncertain', error='Controller stopped during submission. Reconcile with the ledger before recovery.')
                        continue
                if stage['state'] == 'accepted':
                    jobs = [r for r in rows if r['job_id'] in stage['job_ids']]
                    stage['jobs'] = jobs
                    if jobs and all(r['status'] in campaign.TERMINAL for r in jobs):
                        if any(r['status'] == 'CANCELLED' for r in jobs):
                            _collect_artifacts(root, plan, spec, stage, execution)
                            _change(slug, execution, stage, 'cancelled', completed_at=store.now())
                            continue
                        _finish(project, plan, spec, execution, stage, all(r['status'] == 'COMPLETED' for r in jobs))
                    continue
                if stage['state'] == 'fetching':
                    _finish(project, plan, spec, execution, stage, stage.get('scheduler_ok', False))
                    continue
                if stage['state'] != 'waiting':
                    continue
                if any(stage['id'] in f.get('stage_ids', []) for f in execution.get('stop_fences', [])):
                    _change(slug, execution, stage, 'cancelled', waiting_reason='Stopped by reviewed cancellation')
                    continue
                dependencies = [stages[d] for d in spec.get('depends_on', [])]
                if any(d['state'] in _FAILURE for d in dependencies):
                    # Keep waiting so a separately approved recovery can make the prerequisite available.
                    stage['waiting_reason'] = 'Prerequisite requires human review'
                    continue
                if not all(d['state'] == 'completed' for d in dependencies):
                    continue
                active_variants = {s.get('variant_id') for s in execution['stages'] if s['state'] in _ACTIVE}
                concurrency = plan.get('variant_concurrency', plan.get('config', {}).get('variant_concurrency', 1))
                if stage.get('variant_id') not in active_variants and len(active_variants) >= concurrency:
                    continue
                try:
                    if spec['location'] == 'controller':
                        _change(slug, execution, stage, 'running', started_at=store.now())
                        if stage['state'] == 'cancelled':
                            continue
                        env = dict(os.environ, UNITY_PROJECT_ROOT=str(root), PYTHONDONTWRITEBYTECODE='1')
                        supervisor = Path(__file__).with_name('workspace_local.py')
                        command = ['bash', str(root / spec['script_path'])]
                        result = run_local([sys.executable, str(supervisor), str(root), stage['attempts'][-1]['id'], json.dumps(command)], root, env,
                                           min(int(spec.get('timeout_seconds', 300)), 1800))
                        stage['result'] = result
                        if result['ok']:
                            _finish(project, plan, spec, execution, stage)
                        else:
                            _collect_artifacts(root, plan, spec, stage, execution)
                            _change(slug, execution, stage, 'cancelled' if store.read(slug, 'execution', execution['id'])['stages'][execution['stages'].index(stage)].get('cancel_requested') else 'failed', error=result.get('error', 'Declared operation failed'))
                    else:
                        for source in plan['source']['files']:
                            if source.get('redacted') and hashlib.sha256((root / source['path']).read_bytes()).hexdigest() != source['sha256']:
                                raise store.Conflict('Runtime environment reference changed after approval; review a recovery plan')
                        if not execution.get('bundle_uploaded'):
                            transport.stage_bundle(project, plan)
                            execution['bundle_uploaded'] = True
                            _save(slug, execution)
                        _change(slug, execution, stage, 'submitting', submitted_at=store.now())
                        if stage['state'] == 'cancelled':
                            continue
                        result = transport.submit(project, plan, spec, stage['attempts'][-1])
                        stage['result'] = result
                        rows = _ledger(root, plan)
                        if not _reconcile(slug, execution, stage, rows):
                            _change(slug, execution, stage, 'rejected' if result.get('submission_outcome') == 'rejected' else 'uncertain',
                                    error='No ledger receipt for this submission. ' + result.get('output', ''))
                except Exception as exc:
                    _change(slug, execution, stage, 'uncertain' if stage['state'] in ('submitting', 'running') else 'failed', error=str(exc))
            _save(slug, execution)


def job_metadata(slug):
    """Join explicit purpose and provenance by campaign plus ledger identity."""
    result = {}
    # Reads of legacy projects must not create a workspace database.
    if not (paths.controller_dir() / 'workspaces' / f'{slug}.db').is_file():
        return result
    for execution in store.listing(slug, 'execution'):
        for stage in execution['stages']:
            for attempt in stage['attempts']:
                for job_id in attempt.get('job_ids', []):
                    result[(execution['campaign'], job_id)] = {
                        'purpose': stage['purpose'], 'execution_id': execution['id'],
                        'stage_id': stage['id'], 'attempt_id': attempt['id'],
                        'experiment_id': execution.get('experiment_id')}
    return result


def _loop():
    while not _stop.is_set():
        for project in registry.list_projects():
            if _stop.is_set():
                return
            if not (paths.controller_dir() / 'workspaces' / f"{project['slug']}.db").is_file():
                continue
            try:
                from controller.workspace_schedules import tick as schedule_tick
                schedule_tick(project['slug'])
                tick(project['slug'])
            except Exception as exc:
                from controller import events
                events.record('workspace-error', str(exc), slug=project['slug'], ok=False)
        _stop.wait(2)


def start():
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name='workspace-executions', daemon=True)
    _thread.start()


def stop():
    _stop.set()
    if _thread:
        _thread.join(timeout=3)


@contextmanager
def project_lock(slug):
    directory = paths.controller_dir() / 'locks'
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f'{store.safe_id(slug)}.workspace.lock').open('a+b') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
