"""Permanent local removal of evaluation evidence and terminal execution history."""
from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path

from controller import genai, workspace_store as store
from controller.workspace_worker import project_lock
from lib import campaign

_TERMINAL = {'completed', 'failed', 'cancelled', 'canceled', 'rejected', 'superseded', 'paused'}
_LIVE_STAGE = {'submitting', 'accepted', 'running', 'uncertain', 'fetching', 'submitted'}


def delete(slug: str, body: dict) -> dict:
    """Validate the entire selection before removing any data; never cancel jobs."""
    ids = body.get('ids', [])
    execution_ids = body.get('execution_ids', [])
    if not isinstance(ids, list) or not isinstance(execution_ids, list) or not (ids or execution_ids):
        raise genai.GenAIError('Select evaluation runs or finished executions to delete')
    if len(ids) + len(execution_ids) > 10000 or any(not isinstance(x, str) for x in [*ids, *execution_ids]):
        raise genai.GenAIError('Invalid evaluation selection')
    with project_lock(slug) as acquired:
        if not acquired:
            raise genai.GenAIError('Project is busy. Retry deletion.', 409)
        return _delete(slug, set(ids), set(execution_ids))


def _delete(slug: str, ids: set[str], execution_ids: set[str]) -> dict:
    rec = genai.project(slug)
    root = genai.root_of(rec)
    conn = genai.connector(rec)
    hits = genai._scan_roots(rec, conn)
    records = [(hit, genai._evaluation_record(rec, conn, hit)) for hit in hits]
    selected = [(hit, row) for hit, row in records if row['id'] in ids or row.get('execution_id') in execution_ids]
    known = {row['id'] for _, row in selected}
    if ids - known:
        raise genai.GenAIError('Some selected evaluation runs are no longer available. Refresh the list.', 409)
    executions = {x['id']: x for x in store.listing(slug, 'execution')}
    if execution_ids - executions.keys():
        raise genai.GenAIError('Some selected executions are no longer available. Refresh the list.', 409)
    # Removing all results of an execution also removes its backing history.
    trace_paths = [path for hit, _ in selected for path in genai._trace_files(hit['folder'], hit['spec'])]
    selected_run_ids = {row['id'] for _, row in selected}
    linked = {row['execution_id'] for _, row in selected if row.get('execution_id')}
    for identity in linked:
        if all(row['id'] in selected_run_ids for _, row in records if row.get('execution_id') == identity):
            execution_ids.add(identity)
    for identity in linked | execution_ids:
        execution = executions.get(identity)
        if execution and (execution.get('state') not in _TERMINAL or any(s.get('state') in _LIVE_STAGE for s in execution.get('stages', []))):
            raise genai.GenAIError(f'Execution {identity} is active. Cancel it and wait for it to stop before deleting.', 409)
    # A disk-only run can have a stale unfinished manifest. A live ledger is the
    # authoritative reason to refuse deleting it, rather than that stale label.
    raw_names = {row['name'] for _, row in selected if not row.get('execution_id')} | {hit['folder'].name for hit, row in selected if not row.get('execution_id')}
    if raw_names:
        for campaign_name in campaign.campaigns(root):
            if any(job.get('exp') in raw_names and job.get('status') not in campaign.TERMINAL for job in campaign.jobs(root, campaign_name)):
                raise genai.GenAIError('A selected evaluation still has live scheduler jobs. Cancel them before deleting.', 409)
    folders = [hit['folder'] for hit, _ in selected]
    plan_ids = {executions[x].get('plan_id', x) for x in execution_ids if x in executions}
    for identity in execution_ids:
        execution = executions.get(identity)
        if not execution:
            continue
        ledger = campaign.jobs(root, execution.get('campaign') or identity)
        if any(row.get('status') not in campaign.TERMINAL for row in ledger):
            raise genai.GenAIError(f'Execution {identity} still has live scheduler jobs. Cancel them before deleting.', 409)
    for identity in execution_ids:
        for stage in executions.get(identity, {}).get('stages', []):
            for attempt in stage.get('attempts', []):
                attempt_id = store.safe_id(attempt['id'])
                folders.extend((root / '.unity-workspace/receipts').glob(attempt_id + '.*'))
    for identity in plan_ids:
        store.safe_id(identity)
        folders += [root / '.unity-workspace' / kind / identity for kind in ('outputs', 'plans')]
    artifacts = store.listing(slug, 'artifact')
    removed_artifacts = {a['id'] for a in artifacts if a.get('execution_id') in execution_ids or any(str(a.get('path') or '') == str(folder.relative_to(root)) or str(a.get('path') or '').startswith(str(folder.relative_to(root)) + '/') for folder in folders)}
    for execution in executions.values():
        if execution['id'] in execution_ids:
            continue
        if (execution.get('recovery') or {}).get('execution_id') in execution_ids:
            raise genai.GenAIError('A recovery execution still references this evaluation. Select both executions.', 409)
        plan = store.read(slug, 'plan', execution.get('plan_id', execution['id']))
        referenced = set(plan.get('artifact_ids', [])) | {x.get('id') for x in plan.get('artifacts', []) if isinstance(x, dict)}
        if removed_artifacts.intersection(referenced) or execution_ids.intersection(plan.get('source_executions', [])):
            raise genai.GenAIError('Another execution uses these results. Select its execution too.', 409)
    # Keep only outermost directories; protect both project data and source paths.
    folders = sorted(set(folder.resolve() for folder in folders), key=lambda x: len(x.parts))
    for folder in folders:
        genai._inside(root, str(folder.relative_to(root)))
        if folder == root or folder == root / conn.get('datasets_dir', 'dataset'):
            raise genai.GenAIError('Refusing to remove project or dataset roots')
    folders = [folder for i, folder in enumerate(folders) if not any(folder.is_relative_to(parent) for parent in folders[:i])]
    marker = root / '.unity-workspace/deleted-evaluations.json'
    previous = marker.read_bytes() if marker.exists() else None
    tombstones = genai._read_json(marker).get('paths', [])
    tombstones = sorted(set(tombstones + [str(folder.relative_to(root)) for folder in folders]))
    staging = root / '.unity-workspace/deletions' / uuid.uuid4().hex
    staging.mkdir(parents=True, exist_ok=True)
    moved: list[tuple[Path, Path]] = []
    try:
        with store.transaction(slug) as db:
            for index, folder in enumerate(folders):
                if folder.exists():
                    destination = staging / str(index)
                    folder.rename(destination)
                    moved.append((folder, destination))
            temporary = marker.with_suffix('.tmp')
            temporary.write_text(json.dumps({'schema_version': 1, 'paths': tombstones}, indent=2) + '\n')
            os.replace(temporary, marker)
            experiment_ids = {executions[x].get('experiment_id') for x in execution_ids if x in executions}
            for kind in ('execution', 'plan', 'artifact', 'action', 'recovery', 'analysis', 'analysis-revision'):
                for item in store.list_records(db, kind):
                    if (kind == 'execution' and item['id'] in execution_ids or kind == 'plan' and item['id'] in plan_ids
                            or kind == 'artifact' and item['id'] in removed_artifacts or item.get('execution_id') in execution_ids):
                        db.execute('DELETE FROM records WHERE kind=? AND id=?', (kind, item['id']))
            for identity in execution_ids:
                db.execute('DELETE FROM dispatch_keys WHERE execution_id=?', (identity,))
            for item in store.list_records(db, 'experiment'):
                if item['id'] not in experiment_ids:
                    continue
                item['executions'] = [x for x in item.get('executions', []) if x not in execution_ids]
                if not item['executions']:
                    db.execute("DELETE FROM records WHERE kind='experiment' AND id=?", (item['id'],))
                    for revision in store.list_records(db, 'revision'):
                        if revision.get('experiment_id') == item['id']:
                            db.execute("DELETE FROM records WHERE kind='revision' AND id=?", (revision['id'],))
                else:
                    store.put(db, 'experiment', item)
    except BaseException:
        for folder, destination in reversed(moved):
            folder.parent.mkdir(parents=True, exist_ok=True)
            destination.rename(folder)
        if previous is None:
            marker.unlink(missing_ok=True)
        else:
            marker.write_bytes(previous)
        raise
    shutil.rmtree(staging)
    for path in trace_paths:
        genai._cache_file(str(path)).unlink(missing_ok=True)
        with genai._CACHE_LOCK:
            genai._CACHE.pop(str(path), None)
    # Plan campaigns own their ledgers; remove terminal rows with their history.
    for identity in execution_ids:
        execution = executions.get(identity)
        if execution:
            campaign.db_path(root, execution.get('campaign') or identity).unlink(missing_ok=True)
    return {'ok': True, 'deleted': len(selected), 'deleted_executions': len(execution_ids), 'deleted_artifacts': len(removed_artifacts)}
