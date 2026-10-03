"""Versioned defaults and journaled, quiescent attachment maintenance.

Scientific files and the scheduler ledger are never rewritten by this module.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from controller import registry, workspace as service, workspace_store as store
from controller.workspace_connection import digest, load_connection, validate_connection
from controller.workspace_worker import project_lock
from lib import paths

DEFAULT_KEYS = {'application', 'default_primitive', 'default_mode', 'resource_defaults', 'variant_concurrency'}
PROTECTED = ['scientific source', 'custom runners', 'tests', 'analyses', 'plots', 'unityHPC/.env', 'unityHPC/bootstrap.sh', 'unityHPC/fetch.sh', 'unityHPC/sync.sh', '.unity_state', '.unity-workspace/outputs']
TERMINAL = {'completed', 'failed', 'rejected', 'cancelled', 'superseded', 'blocked', 'stopped'}


def _raw(root):
    path = Path(root) / 'unityHPC/project.json'
    try:
        raw = path.read_bytes()
        return path, raw, json.loads(raw)
    except (OSError, ValueError) as exc:
        raise store.WorkspaceError('Project declaration is unavailable: ' + str(path)) from exc


def _atomic(path, data):
    path = Path(path)
    fd, temp = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def _revision(con):
    try:
        return store.get(con, 'settings', 'current')
    except store.Missing:
        return {'id': 'current', 'version': 0}


def maintenance_blocked(slug):
    return [a for a in store.listing(slug, 'maintenance-action') if a['state'] in ('applying', 'checking', 'recovery_required')]


def blockers(slug):
    values = []
    for execution in store.listing(slug, 'execution'):
        for stage in execution.get('stages', []):
            if stage.get('state') not in TERMINAL:
                values.append({'id': execution['id'] + ':' + stage['id'], 'state': stage.get('state'), 'href': f"/projects/{slug}/runs?execution={execution['id']}&stage={stage['id']}"})
    for schedule in store.listing(slug, 'schedule'):
        if schedule.get('state') not in {'cancelled', 'dispatched', 'expired', 'missed', 'invalidated', 'completed'}:
            values.append({'id': schedule['id'], 'state': schedule.get('state'), 'href': f'/projects/{slug}/runs?view=schedules'})
    for action in [*store.listing(slug, 'operation'), *store.listing(slug, 'transfer')]:
        if action.get('state') in {'applying', 'uncertain', 'pending', 'running', 'transferring', 'accepted', 'queued'} or (action.get('kind') == 'cancel' and any(t.get('state') == 'accepted' and not t.get('observed_state') for t in action.get('targets', []))):
            values.append({'id': action['id'], 'state': action['state'], 'href': f'/projects/{slug}/runs'})
    from lib import campaign
    rec = registry.get(slug)
    if rec:
        root = Path(rec['path'])
        for name in campaign.campaigns(root):
            for job in campaign.jobs(root, name):
                if job.get('status') not in campaign.TERMINAL:
                    values.append({'id': str(job['job_id']), 'state': job.get('status'), 'campaign': name,
                                   'href': f'/projects/{slug}/runs?view=queue&campaign={name}'})
    return values


def capability_rows(connection):
    manifest = connection.get('manifest') or {}
    rows = []
    for category in ('operations', 'workflows', 'metrics', 'collectors', 'plots', 'analyses'):
        entries = manifest.get(category, {})
        if not isinstance(entries, dict):
            continue
        for identity, item in entries.items():
            available = connection['valid'] and isinstance(item, dict)
            rows.append({'id': category + ':' + identity, 'category': category, 'declared_version': item.get('version', 1) if isinstance(item, dict) else None,
                         'supported_version': 1, 'availability': 'available' if available else 'unavailable',
                         'reason': None if available else 'Declaration validation failed', 'dependencies': [], 'scope': 'project'})
    from controller.workspace_composition import capability
    rows.append(capability(manifest))
    for identity, supported, reason in (
        ('retrieval', any(s.get('fetch_operation') for w in manifest.get('workflows', {}).values() for s in w.get('stages', [])), 'No scoped retrieval operation is declared'),
        ('recovery', bool(manifest.get('resume')), 'No checkpoint compatibility and resume operation is declared'),
        ('pending_changes', False, 'Site field/state/scope adapter has not been verified; use a reviewed replacement'),
        ('remote_probe', True, None)):
        rows.append({'id': identity, 'declared_version': 1 if supported else None, 'supported_version': 1,
                     'availability': 'available' if supported and connection['valid'] else 'unavailable',
                     'reason': reason if not supported else None, 'dependencies': [], 'scope': 'project'})
    return rows


def _facts(rec, conn):
    stamp = store.now()
    root = Path(rec['path'])
    result = []
    for identity, passed, reason in (
        ('local_path', root.is_dir(), 'Controller-host directory is unavailable'),
        ('declaration', conn['valid'], json.dumps(conn.get('errors', []))),
        ('runner', (root / 'unityHPC/run.sh').is_file(), 'Project dispatcher is unavailable')):
        result.append({'id': identity, 'status': 'ready' if passed else 'unavailable', 'source': 'controller local read',
                       'observed_at': stamp, 'expires_at': (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(),
                       'error_code': None if passed else identity + '_unavailable', 'reason': None if passed else reason,
                       'remediation': f"/projects/{rec['slug']}/settings"})
    return result


def snapshot(slug):
    rec = service.project(slug)
    conn = load_connection(rec['path'], resolve_choices=False)
    manifest = conn.get('manifest') or {}
    try:
        revision = store.read(slug, 'settings', 'current')
    except store.Missing:
        revision = {'version': 0}
    checks = store.listing(slug, 'connection-check')
    actions = store.listing(slug, 'maintenance-action')
    defaults = {k: copy.deepcopy(manifest[k]) for k in DEFAULT_KEYS if k in manifest}
    defaults.setdefault('default_primitive', 'multi-gpu' if rec['primitive'] == 'ml' else rec['primitive'])
    defaults.setdefault('default_mode', 'coordinated' if rec['primitive'] == 'ml' else 'independent' if rec['primitive'] in ('multi-gpu', 'multi-cpu') else 'single')
    defaults.setdefault('variant_concurrency', 1)
    facts = _facts(rec, conn)
    previous = checks[0] if checks else None
    for identity in ('ssh_access', 'remote_root', 'scheduler_commands'):
        facts.append(next((f for f in (previous or {}).get('facts', []) if f['id'] == identity),
                          {'id': identity, 'status': 'unknown', 'source': 'explicit read-only probe required', 'observed_at': None, 'expires_at': None, 'reason': 'Not checked'}))
    try:
        raw_digest = hashlib.sha256((Path(rec['path']) / 'unityHPC/project.json').read_bytes()).hexdigest()
    except OSError:
        raw_digest = None
    store_version = store.SCHEMA_VERSION
    database = paths.controller_dir() / 'workspaces' / (slug + '.db')
    if database.exists():
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
            store_version = db.execute('PRAGMA user_version').fetchone()[0]
    return {'version': revision['version'], 'project': rec, 'declaration_digest': conn.get('digest'), 'file_digest': raw_digest,
            'registry_version': digest(rec), 'defaults': defaults,
            'origins': {k: 'project declaration' if k in manifest else 'attachment compatibility value' if k.startswith('default_') else 'controller policy' for k in defaults},
            'facts': facts, 'capabilities': capability_rows(conn), 'protected_files': PROTECTED,
            'compatibility': {'manifest_schema': manifest.get('schema_version'), 'store_schema': store_version,
                              'controller_contract': 1, 'declaration_state': 'compatible' if conn['valid'] else 'unsupported' if manifest.get('schema_version', 1) != 1 else 'invalid',
                              'legacy_primitive': rec['primitive'], 'historical_values_preserved': True},
            'actions': actions, 'blockers': blockers(slug), 'errors': conn['errors'], 'observed_at': store.now()}


def materialize_defaults(manifest, draft):
    """Called only when creating a draft or explicitly adopting changed defaults."""
    from controller.workspace_planner import _resources
    draft = copy.deepcopy(draft)
    draft['defaults_snapshot'] = {k: copy.deepcopy(manifest[k]) for k in DEFAULT_KEYS if k in manifest}
    resources, origins = {}, {}
    for stage in manifest.get('workflows', {}).get(draft.get('workflow'), {}).get('stages', []):
        op = manifest['operations'][stage['operation']]
        defaults = manifest.get('resource_defaults', {})
        profile = defaults.get(stage['id'], defaults.get('controller' if op['location'] == 'controller' else 'cluster', {}))
        effective = {**profile, **stage.get('resources', {}), **draft.get('resources', {}).get(stage['id'], {})}
        resources[stage['id']], errors = _resources(manifest, stage, op, {**draft, 'resources': {stage['id']: effective}})
        if errors:
            raise store.WorkspaceError('Invalid default resource profile: ' + '; '.join(errors))
        origins[stage['id']] = {k: ('explicit stage override' if k in draft.get('resources', {}).get(stage['id'], {}) else 'saved workflow value' if k in stage.get('resources', {}) else 'project declaration' if k in profile else 'controller policy') for k in resources[stage['id']]}
    draft.update(resources=resources, resource_origins=origins, defaults_digest=digest({k: manifest.get(k) for k in DEFAULT_KEYS}))
    draft.setdefault('variant_concurrency', manifest.get('variant_concurrency', 1))
    return draft


def adoption(slug, identity, body):
    conn = load_connection(service.project(slug)['path'], resolve_choices=False)
    if not conn['valid']:
        raise store.WorkspaceError('A valid declaration is required to adopt defaults')
    item = store.read(slug, 'experiment', identity)
    proposed = materialize_defaults(conn['manifest'], {**item['draft'], 'resources': {}, 'variant_concurrency': conn['manifest'].get('variant_concurrency', 1)})
    preview = {'experiment_id': identity, 'expected_version': item['version'], 'declaration_digest': conn['digest'],
               'draft': proposed, 'differences': service._differences(item['draft'], proposed)}
    if body.get('apply'):
        if body.get('declaration_digest') != conn['digest'] or body.get('expected_version') != item['version']:
            raise store.Conflict('Draft or declaration changed after defaults preview',
                                 current_version=item['version'], expected_version=body.get('expected_version'))
        return store.update_experiment(slug, identity, {'expected_version': item['version'], 'draft': proposed})
    return preview


def _validate_patch(root, manifest, patch):
    if not isinstance(patch, dict) or not patch or set(patch) - DEFAULT_KEYS:
        raise store.WorkspaceError('Only application, primitive, mode, resource defaults, and variant concurrency can change here')
    changed = {**manifest, **copy.deepcopy(patch)}
    if changed.get('default_primitive', 'cpu') not in {'cpu', 'gpu', 'multi-cpu', 'multi-gpu'}:
        raise store.WorkspaceError('Select a supported workspace primitive')
    if changed.get('default_mode', 'single') not in {'single', 'independent', 'coordinated'}:
        raise store.WorkspaceError('Select single, independent, or coordinated mode')
    if not isinstance(changed.get('application', ''), str):
        raise store.WorkspaceError('Application must be text')
    concurrency = changed.get('variant_concurrency', 1)
    if not isinstance(concurrency, int) or isinstance(concurrency, bool) or not 1 <= concurrency <= 1000:
        raise store.WorkspaceError('Variant concurrency must be an integer from 1 to 1000')
    if not isinstance(changed.get('resource_defaults', {}), dict):
        raise store.WorkspaceError('Resource defaults must contain named profiles')
    errors = validate_connection(Path(root), changed)
    if errors:
        raise store.WorkspaceError('Invalid declaration: ' + json.dumps(errors))
    for workflow in changed.get('workflows', {}):
        materialize_defaults(changed, {'workflow': workflow})
    return changed


def update_defaults(slug, body):
    preview = preview_maintenance(slug, {**body, 'action': 'defaults', 'patch': body.get('patch')})
    return apply_maintenance(slug, preview['id'], {'idempotency_key': body.get('idempotency_key', preview['id'])})


def check_connection(slug, body, *, probe=None):
    rec = service.project(slug)
    proposed = body.get('proposed', {})
    if not isinstance(proposed, dict) or set(proposed) - {'unity_host', 'remote_dir'}:
        raise store.WorkspaceError('Proposed probe accepts SSH alias and remote root only')
    rec = {**rec, **proposed}
    conn = load_connection(rec['path'], resolve_choices=False)
    facts = _facts(rec, conn)
    if body.get('remote'):
        host, remote = rec.get('unity_host', ''), rec.get('remote_dir', '')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@-]*', host) or not remote or '\x00' in remote:
            raise store.WorkspaceError('A valid SSH alias and remote root are required')
        commands = [('ssh_access', 'true'), ('remote_root', 'test -d ' + shlex.quote(remote) + ' && test -r ' + shlex.quote(remote)),
                    ('scheduler_commands', 'command -v sbatch >/dev/null && command -v squeue >/dev/null && command -v sacct >/dev/null')]
        for identity, command in commands:
            try:
                result = (probe or subprocess.run)(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', host, command], capture_output=True, text=True, timeout=8)
                ready = result.returncode == 0
                reason = None if ready else 'Read-only probe failed; check controller-wide SSH access or site commands'
            except subprocess.TimeoutExpired:
                ready, reason = False, 'Read-only probe exceeded its 8 second deadline'
            except OSError:
                ready, reason = False, 'SSH executable unavailable on controller host'
            facts.append({'id': identity, 'status': 'ready' if ready else 'unavailable', 'source': 'explicit read-only SSH probe',
                          'observed_at': store.now(), 'expires_at': (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(),
                          'deadline_seconds': 8, 'error_code': None if ready else 'probe_failed', 'reason': reason, 'remediation': '/settings/config'})
    result = {'id': store.new_id('check'), 'facts': facts, 'state': 'ready' if all(f['status'] == 'ready' for f in facts) and body.get('remote') else 'degraded', 'created_at': store.now(),
              'not_run': [] if body.get('remote') else ['ssh_access', 'remote_root', 'scheduler_commands'], 'connection_digest': digest(rec)}
    with store.transaction(slug) as con:
        store.put(con, 'connection-check', result)
        manifest = conn.get('manifest') or {}
        if 'research_question' in manifest:
            store.put(con, 'research-origin', {'id': 'manifest', 'question': manifest['research_question'], 'declaration_digest': conn.get('digest')})
    return result


def _relocation(rec, target):
    root = Path(target).expanduser().resolve()
    conn = load_connection(root, resolve_choices=False)
    old = load_connection(rec['path'], resolve_choices=False)
    expected = old.get('digest')
    if expected is None:
        revisions = store.listing(rec['slug'], 'settings')
        plans = store.listing(rec['slug'], 'plan')
        expected = next((r.get('declaration_digest') for r in revisions if r.get('declaration_digest')), None)
        if expected is None:
            expected = next((p.get('connection_digest') for p in sorted(plans, key=lambda p:p.get('created_at',''), reverse=True) if p.get('connection_digest')), None)
    if not conn['valid'] or expected is None or conn.get('digest') != expected:
        raise store.WorkspaceError('Relocation requires a valid declaration matching a retained connection or reviewed plan digest')
    checked = []
    for artifact in store.listing(rec['slug'], 'artifact'):
        for file in artifact.get('files', []):
            path = (root / file.get('frozen_path', file['path'])).resolve()
            if not path.is_relative_to(root) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != file['sha256']:
                raise store.WorkspaceError('Relocation target lacks artifact bytes: ' + artifact['id'])
            checked.append({'artifact_id': artifact['id'], 'original_locator': str(Path(rec['path']) / file.get('frozen_path', file['path'])), 'local_locator': str(path), 'sha256': file['sha256']})
    for plan in store.listing(rec['slug'], 'plan'):
        source = Path(rec['path']) / '.unity-workspace/plans' / plan['id']
        dest = root / '.unity-workspace/plans' / plan['id']
        if not source.exists():
            from controller.workspace_planner import verify_snapshot
            verification = verify_snapshot(root, plan)
            if not verification['valid']:
                raise store.WorkspaceError('Relocation target does not match retained plan evidence: ' + plan['id'])
            continue
        for file in source.rglob('*'):
            if file.is_file() and (file.is_symlink() or not (dest / file.relative_to(source)).is_file() or hashlib.sha256(file.read_bytes()).digest() != hashlib.sha256((dest / file.relative_to(source)).read_bytes()).digest()):
                raise store.WorkspaceError('Relocation target lacks identical frozen plan: ' + plan['id'])
    ledger_root = Path(rec['path']) / '.unity_state'
    if ledger_root.exists():
        for ledger in ledger_root.glob('*.db'):
            target = root / '.unity_state' / ledger.name
            if not target.is_file() or hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(ledger.read_bytes()).digest():
                raise store.WorkspaceError('Relocation target lacks identical historical ledger: ' + ledger.name)
    if not Path(rec['path']).exists():
        from lib import campaign
        for execution in store.listing(rec['slug'], 'execution'):
            known = {row['job_id'] for row in campaign.jobs(root, execution.get('campaign'))}
            required = {identity for stage in execution.get('stages', []) for identity in stage.get('job_ids', [])}
            if not required.issubset(known):
                raise store.WorkspaceError('Relocation target lacks retained execution ledger identities: ' + execution['id'])
    return root, checked


def preview_maintenance(slug, body):
    rec = service.project(slug)
    action = body.get('action')
    unavailable_root = not Path(rec['path']).exists()
    if unavailable_root and action == 'relocate':
        target, _ = _relocation(rec, body.get('patch', {}).get('path', ''))
        path, raw, manifest = _raw(target)
    else:
        path, raw, manifest = _raw(rec['path'])
    if manifest.get('schema_version') != 1:
        raise store.WorkspaceError('Unsupported declaration schema; maintenance cannot guess its meaning')
    if action not in {'defaults', 'migration', 'relocate', 'connection', 'detach', 'reload'}:
        raise store.WorkspaceError('Select defaults, migration, relocate, connection, detach, or reload')
    patch = body.get('patch', {})
    after_manifest, after_registry, mappings = copy.deepcopy(manifest), copy.deepcopy(rec), []
    if action == 'defaults':
        after_manifest = _validate_patch(rec['path'], manifest, patch)
    elif action == 'migration':
        primitive = 'multi-gpu' if rec['primitive'] == 'ml' else rec['primitive']
        mode = 'coordinated' if rec['primitive'] == 'ml' else 'independent' if primitive in {'multi-cpu', 'multi-gpu'} else 'single'
        if slug == 'llm-thinking-trace':
            primitive, mode = 'multi-gpu', 'independent'
        after_manifest = _validate_patch(rec['path'], manifest, {'default_primitive': manifest.get('default_primitive', primitive), 'default_mode': manifest.get('default_mode', mode)})
    elif action in {'relocate', 'connection'}:
        if not isinstance(patch, dict) or set(patch) - {'path', 'unity_host', 'remote_dir'}:
            raise store.WorkspaceError('Connection patch may change path, SSH alias, and remote directory only')
        after_registry.update(patch)
        if 'path' in patch:
            target, mappings = _relocation(rec, patch['path'])
            after_registry['path'] = str(target)
        if {'unity_host', 'remote_dir'} & patch.keys():
            checks = store.listing(slug, 'connection-check')
            check = next((c for c in checks if c.get('connection_digest') == digest(after_registry)), None)
            if not check or check.get('state') != 'ready' or any(datetime.fromisoformat(f['expires_at']) < datetime.now(timezone.utc) for f in check['facts']):
                raise store.WorkspaceError('Run a fresh read-only probe of the proposed SSH alias and remote root before preview')
    observed_blockers = blockers(slug) if action != 'defaults' else []
    with store.transaction(slug) as con:
        revision = _revision(con)
        if body.get('expected_version') != revision['version'] or (body.get('declaration_digest') != digest(manifest) and not (unavailable_root and action == 'relocate' and body.get('declaration_digest') is None)):
            raise store.Conflict('Settings or declaration changed; reload and preserve your staged patch',
                                 current_version=revision['version'], expected_version=body.get('expected_version'))
        if body.get('file_digest') and body['file_digest'] != hashlib.sha256(raw).hexdigest():
            raise store.Conflict('Declaration bytes changed externally')
        preview = {'id': store.new_id('maintenance-preview'), 'action': action, 'unavailable_root': unavailable_root, 'version': 1, 'expected_version': revision['version'],
                   'registry_version': digest(rec), 'declaration_digest': digest(manifest), 'file_digest': hashlib.sha256(raw).hexdigest(),
                   'store_version': store.SCHEMA_VERSION, 'patch': patch, 'before_registry': rec, 'after_registry': after_registry,
                   'before_manifest': manifest, 'after_manifest': after_manifest, 'relocation_map': mappings,
                   'protected_files': PROTECTED, 'affected_plans': [p['id'] for p in store.list_records(con, 'plan') if not p.get('execution_id')],
                   'blockers': observed_blockers, 'state': 'blocked' if observed_blockers else 'ready', 'created_at': store.now(),
                   'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(), 'historical_values_preserved': True}
        return store.put(con, 'maintenance-preview', preview)


def _save_action(slug, value):
    value['updated_at'] = store.now()
    value['version'] += 1
    with store.transaction(slug) as con:
        store.put(con, 'maintenance-action', value)


def _backup(slug, action, preview):
    directory = paths.controller_dir() / 'maintenance' / slug / action['id']
    directory.mkdir(parents=True, exist_ok=True)
    with store.transaction(slug) as con:
        rows = [{'kind': kind, 'id': identity, 'body': json.loads(body)} for kind, identity, body in con.execute('SELECT kind,id,body FROM records') if kind not in ('maintenance-action', 'maintenance-preview')]
    root = Path(preview['after_registry']['path'] if preview.get('unavailable_root') else preview['before_registry']['path'])
    files = {'project.json': (root / 'unityHPC/project.json').read_bytes(), 'registry.json': _json_bytes(preview['before_registry']), 'records.json': _json_bytes(rows)}
    for name, raw in files.items():
        _atomic(directory / name, raw)
    for relative in ('.unity-workspace', '.unity_state'):
        source = root / relative
        target = directory / relative
        if source.exists():
            if any(p.is_symlink() for p in source.rglob('*')):
                raise store.WorkspaceError('Workspace backup refuses symbolic links; resolve the exact ownership before migration')
            partial = directory / (relative + '.partial')
            if partial.exists():
                shutil.rmtree(partial)
            shutil.copytree(source, partial)
            expected = {p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}
            copied = {p.relative_to(partial).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in partial.rglob('*') if p.is_file()}
            if expected != copied:
                raise store.WorkspaceError('Workspace changed during backup; no activation can proceed')
            if target.exists():
                shutil.rmtree(target)
            os.replace(partial, target)
    evidence = {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file() and p.name != 'backup.json'}
    _atomic(directory / 'backup.json', _json_bytes(evidence))
    if any(hashlib.sha256((directory / name).read_bytes()).hexdigest() != sha for name, sha in evidence.items()):
        raise store.WorkspaceError('Backup readback verification failed')
    action['backup'] = {'path': str(directory), 'files': evidence, 'verified_at': store.now()}


def _registry_compare(slug, before, after, detach=False):
    def change():
        data = registry._read_unlocked(paths.projects_registry())
        current = next((p for p in data['projects'] if p.get('slug') == slug), None)
        expected = registry._normalise(before)
        if current is None and detach:
            return
        if current is not None and registry._normalise(current) == registry._normalise(after) and not detach:
            return
        if current is None or registry._normalise(current) != expected:
            raise store.Conflict('Registry changed externally during maintenance')
        data['projects'] = [p for p in data['projects'] if p.get('slug') != slug]
        if not detach:
            data['projects'].append(after)
        registry._write_unlocked(paths.projects_registry(), data)
    registry._with_lock(True, change)


def _advance(slug, action, preview, fault=None):
    def done(step):
        action['completed_steps'].append(step)
        _save_action(slug, action)
        if fault:
            fault(step)
    try:
        root = Path(preview['after_registry']['path'] if preview.get('unavailable_root') else preview['before_registry']['path'])
        if 'backup' not in action['completed_steps']:
            _backup(slug, action, preview)
            done('backup')
        if 'drafts' not in action['completed_steps']:
            frozen = list(action.get('frozen_drafts', []))
            with store.transaction(slug) as con:
                for experiment in store.list_records(con, 'experiment'):
                    if not experiment['draft'].get('defaults_digest'):
                        before = copy.deepcopy(experiment)
                        experiment['draft'] = materialize_defaults(preview['before_manifest'], experiment['draft'])
                        experiment['version'] += 1
                        experiment['readiness'] = 'unchecked'
                        experiment['updated_at'] = store.now()
                        experiment['defaults_migration'] = action['id']
                        store.put(con, 'experiment', experiment)
                        frozen.append({'before': before, 'after': copy.deepcopy(experiment)})
                action['frozen_drafts'] = frozen
                store.put(con, 'maintenance-action', action)
            done('drafts')
        if 'declaration' not in action['completed_steps']:
            path, raw, current = _raw(root)
            if current != preview['after_manifest']:
                if hashlib.sha256(raw).hexdigest() != preview['file_digest']:
                    raise store.Conflict('Declaration changed externally during maintenance')
                _atomic(path, _json_bytes(preview['after_manifest']))
            done('declaration')
        if 'registry' not in action['completed_steps']:
            _registry_compare(slug, preview['before_registry'], preview['after_registry'], preview['action'] == 'detach')
            done('registry')
        if 'metadata' not in action['completed_steps']:
            with store.transaction(slug) as con:
                revision = _revision(con)
                if revision.get('action_id') != action['id']:
                    if revision['version'] != preview['expected_version']:
                        raise store.Conflict('Settings revision changed during activation',
                                             current_version=revision['version'], expected_version=preview['expected_version'])
                    store.put(con, 'settings', {'id': 'current', 'version': revision['version'] + 1, 'action_id': action['id'],
                                               'declaration_digest': digest(preview['after_manifest']), 'actor': 'local operator', 'updated_at': store.now()})
                for i, mapping in enumerate(preview['relocation_map']):
                    store.put(con, 'artifact-relocation', {**mapping, 'id': action['id'] + '-' + str(i), 'connection_revision': revision['version'] + 1})
            done('metadata')
        action['state'] = 'succeeded'
        action['remaining_steps'] = []
        action['targets'] = [{'id': slug, 'state': 'accepted'}]
        _save_action(slug, action)
        return action
    except Exception as exc:
        action['state'] = 'recovery_required'
        action['error'] = str(exc)
        action['remaining_steps'] = [s for s in ('backup', 'drafts', 'declaration', 'registry', 'metadata') if s not in action['completed_steps']]
        _save_action(slug, action)
        raise


def apply_maintenance(slug, identity, body, *, fault=None):
    key = body.get('idempotency_key')
    if not isinstance(key, str) or not key or len(key) > 200:
        raise store.WorkspaceError('Maintenance activation requires an idempotency key')
    with project_lock(slug) as acquired:
        if not acquired:
            raise store.Conflict('Execution worker or maintenance owns this project; retry later')
        with store.transaction(slug) as con:
            prior = next((a for a in store.list_records(con, 'maintenance-action') if a['idempotency_key'] == key), None)
            if prior:
                if prior['preview_id'] != identity:
                    raise store.Conflict('Idempotency key already names another preview')
                return prior
            if any(a['state'] in ('applying', 'checking', 'recovery_required') for a in store.list_records(con, 'maintenance-action')):
                raise store.Conflict('Reconcile the unfinished maintenance action before another write')
            preview = store.get(con, 'maintenance-preview', identity)
            revision = _revision(con)
            if revision['version'] != preview['expected_version']:
                raise store.Conflict('Settings changed after preview', current_version=revision['version'],
                                     expected_version=preview['expected_version'])
        if datetime.fromisoformat(preview['expires_at']) < datetime.now(timezone.utc):
            raise store.Conflict('Maintenance preview expired')
        rec = service.project(slug)
        _, raw, _ = _raw(preview['after_registry']['path'] if preview.get('unavailable_root') else rec['path'])
        if digest(rec) != preview['registry_version'] or hashlib.sha256(raw).hexdigest() != preview['file_digest']:
            raise store.Conflict('Connection or declaration changed after preview')
        blocking = blockers(slug) if preview['action'] != 'defaults' else []
        if blocking:
            raise store.Conflict('Project is not quiescent: ' + json.dumps(blocking))
        if preview['action'] == 'connection' and any(preview['before_registry'].get(k) != preview['after_registry'].get(k) for k in ('unity_host', 'remote_dir')):
            checks = store.listing(slug, 'connection-check')
            check = next((c for c in checks if c.get('connection_digest') == digest(preview['after_registry'])), None)
            if not check or check['state'] != 'ready' or any(datetime.fromisoformat(f['expires_at']) < datetime.now(timezone.utc) for f in check['facts']):
                raise store.Conflict('Proposed connection probe expired; check and review again')
        if preview['action'] == 'relocate':
            _relocation(rec, preview['after_registry']['path'])
        action = {'id': store.new_id('maintenance'), 'kind': 'maintenance', 'version': 1, 'preview_id': identity,
                  'idempotency_key': key, 'state': 'applying', 'created_at': store.now(), 'updated_at': store.now(),
                  'actor': 'local operator', 'completed_steps': [], 'remaining_steps': ['backup', 'drafts', 'declaration', 'registry', 'metadata'],
                  'targets': [{'id': slug, 'state': 'uncertain'}]}
        with store.transaction(slug) as con:
            store.put(con, 'maintenance-action', action)
        return _advance(slug, action, preview, fault)


def reconcile_maintenance(slug, identity):
    with project_lock(slug) as acquired:
        if not acquired:
            raise store.Conflict('Project is busy')
        action = store.read(slug, 'maintenance-action', identity)
        if action['state'] in ('succeeded', 'rolled_back'):
            return action
        preview = store.read(slug, 'maintenance-preview', action['preview_id'])
        return _rollback_advance(slug, action, preview) if action.get('phase') == 'rollback' else _advance(slug, action, preview)


def rollback(slug, identity, *, fault=None):
    with project_lock(slug) as acquired:
        if not acquired:
            raise store.Conflict('Project is busy')
        action = store.read(slug, 'maintenance-action', identity)
        if action['state'] == 'rolled_back':
            return action
        if blockers(slug):
            raise store.Conflict('Rollback requires a quiet project')
        preview = store.read(slug, 'maintenance-preview', action['preview_id'])
        if action.get('phase') != 'rollback':
            if not Path(preview['before_registry']['path']).is_dir():
                raise store.Conflict('Original directory is unavailable. Restore it from the checked backup before rolling back its registration.')
            backup = action.get('backup')
            if not backup:
                raise store.Conflict('A checked backup is required')
            directory = Path(backup['path'])
            if any(hashlib.sha256((directory / name).read_bytes()).hexdigest() != sha for name, sha in backup['files'].items()):
                raise store.Conflict('Backup integrity check failed')
            original = json.loads((directory / 'records.json').read_text())
            protected = {(r['kind'], r['id']): r['body'] for r in original if r['kind'] not in {'settings', 'connection-check'}}
            with store.transaction(slug) as con:
                current = {(kind, identity): json.loads(body) for kind, identity, body in con.execute('SELECT kind,id,body FROM records') if kind not in {'settings', 'connection-check', 'maintenance-action', 'maintenance-preview', 'artifact-relocation'}}
            for frozen in action.get('frozen_drafts', []):
                protected[('experiment', frozen['after']['id'])] = frozen['after']
            if current != protected:
                raise store.Conflict('Post-migration records exist. Preserve them separately before operator rollback; nothing was deleted.')
            action.update(phase='rollback', rollback_steps=[], state='applying')
            _save_action(slug, action)
        return _rollback_advance(slug, action, preview, fault)


def _rollback_advance(slug, action, preview, fault=None):
    directory = Path(action['backup']['path'])
    original = json.loads((directory / 'records.json').read_text())
    def done(step):
        action['rollback_steps'].append(step)
        _save_action(slug, action)
        if fault:
            fault(step)
    try:
        # The journal is durable before the first rollback write. Both activation
        # and rollback states fence dispatch until all steps reconcile.
        root = Path(preview['before_registry']['path'])
        if 'declaration' not in action['rollback_steps']:
            _, _, manifest = _raw(root)
            if manifest != preview['before_manifest']:
                if manifest != preview['after_manifest']:
                    raise store.Conflict('Declaration changed after maintenance; rollback cannot overwrite it')
                _atomic(root / 'unityHPC/project.json', (directory / 'project.json').read_bytes())
            done('declaration')
        if 'registry' not in action['rollback_steps']:
            if preview['action'] != 'detach':
                _registry_compare(slug, preview['after_registry'], preview['before_registry'])
            else:
                def restore_registration():
                    data = registry._read_unlocked(paths.projects_registry())
                    current = next((r for r in data['projects'] if r.get('slug') == slug), None)
                    if current:
                        if registry._normalise(current) != registry._normalise(preview['before_registry']):
                            raise store.Conflict('Project was reattached after detach; preserve current registration')
                        return
                    data['projects'].append(preview['before_registry'])
                    registry._write_unlocked(paths.projects_registry(), data)
                registry._with_lock(True, restore_registration)
            done('registry')
        if 'metadata' not in action['rollback_steps']:
            with store.transaction(slug) as con:
                current = _revision(con)
                if current.get('rollback_of') != action['id']:
                    prior = next((r['body'] for r in original if r['kind'] == 'settings' and r['id'] == 'current'), {'id': 'current', 'version': 0})
                    prior.update(version=current['version'] + 1, rollback_of=action['id'], updated_at=store.now())
                    store.put(con, 'settings', prior)
            done('metadata')
        action.update(state='rolled_back', remaining_steps=[])
        _save_action(slug, action)
        return action
    except Exception as exc:
        action.update(state='recovery_required', error=str(exc), remaining_steps=[s for s in ('declaration', 'registry', 'metadata') if s not in action['rollback_steps']])
        _save_action(slug, action)
        raise
