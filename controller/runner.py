"""Workflow setup and reviewed execution over the durable workspace engine."""
from __future__ import annotations

import copy
import time

from controller import workspace, workspace_runs as runs, workspace_store as store
from controller.workspace_store import Conflict, WorkspaceError


def workflows(slug):
    connection = workspace.connection(slug)
    manifest = connection.get('manifest') or {}
    if not connection.get('valid'):
        return {'valid': False, 'errors': connection.get('errors', []), 'workflows': [],
                'application': manifest.get('application', '') if isinstance(manifest, dict) else ''}
    items = []
    for identity, definition in manifest.get('workflows', {}).items():
        names = definition.get('parameters', list(manifest.get('parameters', {})))
        parameters = []
        for name in names:
            spec = manifest.get('parameters', {}).get(name, {})
            parameters.append({**copy.deepcopy(spec), 'name': name, 'label': spec.get('label', name),
                               'default': definition.get('defaults', {}).get(name, spec.get('default'))})
        stages = []
        for stage in definition.get('stages', []):
            operation = manifest.get('operations', {}).get(stage.get('operation'), {})
            stages.append({**copy.deepcopy(stage), 'location': stage.get('location') or operation.get('location', 'cluster')})
        items.append({'id': identity, 'title': definition.get('title', identity), 'parameters': parameters,
                      'stages': stages, 'metrics': definition.get('metrics', []),
                      'purpose': 'smoke-test' if stages and all(s.get('purpose') == 'smoke-test' for s in stages) else 'experiment'})
    return {'valid': bool(connection.get('valid')), 'errors': connection.get('errors', []),
            'workflows': items, 'application': manifest.get('application', '')}


def prepare(slug, body):
    if not isinstance(body, dict):
        raise WorkspaceError('Workflow setup must be an object')
    workflow = body.get('workflow')
    catalog = workflows(slug)
    if not catalog['valid']:
        return {'ok': False, 'valid': False, 'stage': 'connection', 'checks': {'errors': catalog['errors']},
                'error': 'Project connection is invalid'}
    definition = next((one for one in catalog['workflows'] if one['id'] == workflow), None)
    if definition is None:
        raise WorkspaceError('Select a declared workflow')
    parameters = body.get('parameters', {})
    if not isinstance(parameters, dict):
        raise WorkspaceError('parameters must be an object')
    unknown = set(parameters) - {one['name'] for one in definition['parameters']}
    if unknown:
        raise WorkspaceError('Unknown workflow parameters: ' + ', '.join(sorted(unknown)))
    name = body.get('name')
    if name is not None and (not isinstance(name, str) or len(name) > 200):
        raise WorkspaceError('Run name must be a string of at most 200 characters')
    draft = {'parameters': copy.deepcopy(parameters)}
    variants = body.get('variant_parameters')
    if variants is not None:
        if not isinstance(variants, dict):
            raise WorkspaceError('variant_parameters must be an object')
        if set(variants) - {one['name'] for one in definition['parameters']}:
            raise WorkspaceError('Unknown workflow variant parameters')
        draft['variant_parameters'] = copy.deepcopy(variants)
    experiment = workspace.create(slug, {'workflow': workflow, 'name': name, 'draft': draft})
    checks = workspace.check(slug, experiment['id'])
    if not checks.get('valid', checks.get('ok', False)):
        return {'ok': False, 'valid': False, 'stage': 'check', 'experiment_id': experiment['id'],
                'checks': checks, 'error': "The configuration did not pass the project's checks"}
    plan = workspace.plan(slug, experiment['id'])
    return {'ok': True, 'valid': True, 'experiment_id': experiment['id'], 'plan_id': plan['id'],
            'checks': checks, 'plan': plan}


def approve(slug, plan_id, key):
    if not isinstance(key, str) or not key or len(key) > 200:
        raise WorkspaceError('Approval requires an idempotency_key of at most 200 characters')
    for attempt in range(10):
        try:
            return workspace.dispatch_plan(slug, plan_id, key)
        except Conflict as exc:
            if 'busy' not in str(exc) or attempt == 9:
                raise
            time.sleep(0.5)
    raise AssertionError('unreachable')


def executions(slug, filters, offset=0, limit=50):
    workspace.project(slug)
    items = runs.executions(slug, filters)['executions']
    return {'executions': items[offset:offset + limit], 'total': len(items),
            'next_offset': offset + limit if offset + limit < len(items) else None}


def execution(slug, identity):
    workspace.project(slug)
    value = runs.project_execution(slug, store.read(slug, 'execution', identity))
    value['artifacts'] = [a for a in store.listing(slug, 'artifact') if a.get('execution_id') == identity]
    return value


def document(slug, offset=0, version=None):
    from controller import workspace_artifacts as artifacts
    rec = workspace.project(slug)
    manifest = workspace.connection(slug).get('manifest') or {}
    path = manifest.get('docs') or 'README.md'
    if rec.get('application') == 'llms-agents':
        from controller import genai
        path = genai.connector(rec).get('docs') or path
    return artifacts.preview(slug, {'root': 'source', 'path': path, 'offset': offset,
                                    'version': version, 'limit': 65536})
