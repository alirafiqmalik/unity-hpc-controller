"""Remove evaluations from application lists while retaining durable evidence."""
from __future__ import annotations

import json
import os
import uuid

from controller import genai, workspace_store as store
from controller.workspace_worker import project_lock
from lib import campaign

_TERMINAL = {'completed', 'failed', 'cancelled', 'canceled', 'rejected', 'superseded', 'paused'}
_LIVE_STAGE = {'submitting', 'accepted', 'running', 'uncertain', 'fetching', 'submitted'}


def delete(slug: str, body: dict) -> dict:
    """Validate the selection, then hide rows without removing engine records."""
    ids = body.get('ids', [])
    execution_ids = body.get('execution_ids', [])
    if not isinstance(ids, list) or not isinstance(execution_ids, list) or not (ids or execution_ids):
        raise genai.GenAIError('Select evaluations or finished executions to remove')
    if len(ids) + len(execution_ids) > 10000 or any(not isinstance(x, str) for x in [*ids, *execution_ids]):
        raise genai.GenAIError('Invalid evaluation selection')
    with project_lock(slug) as acquired:
        if not acquired:
            raise genai.GenAIError('Project is busy. Retry removal.', 409)
        return _delete(slug, set(ids), set(execution_ids))


def _delete(slug: str, ids: set[str], execution_ids: set[str]) -> dict:
    rec = genai.project(slug)
    root = genai.root_of(rec)
    conn = genai.connector(rec)
    records = [(hit, genai._evaluation_record(rec, conn, hit)) for hit in genai._scan_roots(rec, conn)]
    selected = [(hit, row) for hit, row in records if row['id'] in ids or row.get('execution_id') in execution_ids]
    if ids - {row['id'] for _, row in selected}:
        raise genai.GenAIError('Some selected evaluations are no longer available. Refresh the list.', 409)
    executions = {item['id']: item for item in store.listing(slug, 'execution')}
    if execution_ids - executions.keys():
        raise genai.GenAIError('Some selected executions are no longer available. Refresh the list.', 409)
    selected_ids = {row['id'] for _, row in selected}
    linked = {row['execution_id'] for _, row in selected if row.get('execution_id')}
    for identity in linked:
        if identity in executions and all(row['id'] in selected_ids for _, row in records if row.get('execution_id') == identity):
            execution_ids.add(identity)
    for identity in linked | execution_ids:
        execution = executions.get(identity)
        if execution and (execution.get('state') not in _TERMINAL or any(stage.get('state') in _LIVE_STAGE for stage in execution.get('stages', []))):
            raise genai.GenAIError(f'Execution {identity} is active. Cancel it and wait for it to stop before removal.', 409)
    raw_names = {row['name'] for _, row in selected if not row.get('execution_id')} | {hit['folder'].name for hit, row in selected if not row.get('execution_id')}
    for campaign_name in campaign.campaigns(root):
        if any(job.get('exp') in raw_names and job.get('status') not in campaign.TERMINAL for job in campaign.jobs(root, campaign_name)):
            raise genai.GenAIError('A selected evaluation still has live scheduler jobs. Cancel them before removal.', 409)
    for identity in execution_ids:
        execution = executions[identity]
        if any(job.get('status') not in campaign.TERMINAL for job in campaign.jobs(root, execution.get('campaign') or identity)):
            raise genai.GenAIError(f'Execution {identity} still has live scheduler jobs. Cancel them before removal.', 409)
    hidden = genai.hidden_evaluations(rec)
    paths = set(hidden['paths']) | {str(hit['folder'].relative_to(root)) for hit, _ in selected}
    hidden_ids = set(hidden['execution_ids']) | execution_ids
    marker = genai._inside(root, '.unity-workspace/deleted-evaluations.json')
    marker.parent.mkdir(parents=True, exist_ok=True)
    temporary = marker.with_name(marker.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps({'schema_version': 1, 'paths': sorted(paths), 'execution_ids': sorted(hidden_ids)}, indent=2) + '\n')
        os.replace(temporary, marker)
    finally:
        temporary.unlink(missing_ok=True)
    return {'ok': True, 'deleted': len(selected), 'deleted_executions': len(execution_ids), 'deleted_artifacts': 0,
            'note': 'Removed from evaluation lists. Source, results, plans, receipts and execution history are retained.'}
