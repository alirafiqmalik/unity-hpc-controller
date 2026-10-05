"""Runs observations never dispatch and bounded streams retain attempt identity."""
import json
from pathlib import Path
import pytest
from controller import workspace_runs as runs, workspace_store as store
from test_workspace_execution import harness
from test_workspace_planner import connected, draft


@pytest.fixture(autouse=True)
def no_remote_transport(monkeypatch):
    def unavailable(*args, **kwargs):
        raise store.Conflict("Fixture remote unavailable")
    monkeypatch.setattr(runs, "_remote_transport", unavailable)


def test_summary_preserves_attention_beside_active(harness):
    h = harness
    _, plan, ex = h.start(draft(variant_parameters={'model': ['small', 'large']}, stages=['t1'], variant_concurrency=4))
    h.behavior[plan['stages'][1]['id']] = 'uncertain'
    h.tick()
    out = runs.project_execution('study', h.execution(ex['id']))
    assert out['summary'] == 'active' and out['attention_count'] == 1
    assert out['stages'][0]['submission'] == 'accepted'
    assert out['stages'][0]['scheduler_references'][0]['campaign'] == ex['campaign']
    assert out['stages'][0]['progress'] is None
    assert out['freshness']['scheduler']['state'] != 'fresh'
    before = len(h.calls)
    runs.executions('study'); runs.queue('study')
    assert len(h.calls) == before


def test_bounded_logs_rotation_and_attempt_scope(harness):
    h = harness
    _, _, ex = h.start(); h.tick()
    stage = h.execution(ex['id'])['stages'][0]; attempt = stage['attempts'][0]
    dest = h.root / '_results' / ex['campaign']; dest.mkdir(parents=True)
    path = dest / f"{attempt['exp']}-{stage['job_ids'][0]}.out"
    path.write_bytes(b'a' * 100000)
    first = runs.logs('study', attempt['id'], offset=0, limit=1000000)
    assert len(first['text']) == 65536 and first['has_more']
    last = runs.logs('study', attempt['id'], cursor=first['cursor'])
    assert last['next_offset'] == 100000
    path.write_text('new stream')
    rotated = runs.logs('study', attempt['id'], cursor=last['cursor'])
    assert rotated['boundary'] == 'rotated-or-truncated' and rotated['text'] == 'new stream'
    with pytest.raises(store.WorkspaceError, match='cursor'):
        runs.logs('study', attempt['id'], stream='stderr', cursor=last['cursor']) if (dest / path.name.replace('.out','.err')).write_text('err') else None
    path.write_bytes(b'\x00binary')
    assert runs.logs('study', attempt['id'])['encoding'] == 'binary'


def test_missing_and_symlink_log_do_not_follow_remote(harness):
    h = harness; _, _, ex = h.start(); h.tick()
    stage = h.execution(ex['id'])['stages'][0]; attempt = stage['attempts'][0]
    assert runs.logs('study', attempt['id'])['availability'] == 'remote-unavailable'
    dest = h.root / '_results' / ex['campaign']; dest.mkdir(parents=True)
    path = dest / f"{attempt['exp']}-{stage['job_ids'][0]}.out"
    path.symlink_to('/etc/passwd')
    with pytest.raises(store.WorkspaceError, match='escapes'):
        runs.logs('study', attempt['id'])


def test_remote_cursor_is_bounded_and_rotation_does_not_mix_bytes(harness, monkeypatch):
    import base64
    h = harness; _, _, ex = h.start(); h.tick()
    attempt = h.execution(ex['id'])['stages'][0]['attempts'][0]
    changed = [False]
    calls = []
    def remote(slug, execution, job_id, stream, **kwargs):
        calls.append((job_id, stream, kwargs))
        data = b'new' if changed[0] else b'old'
        return {'availability':'available','file_id':'new' if changed[0] else 'old','size':3,
                'offset':0,'next_offset':3,'data':base64.b64encode(data).decode(),'prefix':data.decode(),
                'prefix_size':3,'observed_at':store.now()}
    monkeypatch.setattr(runs,'_remote_transport',remote)
    first = runs.logs('study',attempt['id'])
    changed[0] = True
    second = runs.logs('study',attempt['id'],cursor=first['cursor'])
    assert second['text'] == 'new' and second['boundary'] == 'rotated-or-truncated'
    assert all(c[2]['limit'] == 65536 for c in calls)


def test_controller_stage_does_not_claim_waiting_scheduler_submission(harness):
    from test_workspace_local import _running
    h = harness; _, execution, _ = _running(h)
    projected = runs.project_execution('study', h.execution(execution['id']))
    assert projected['has_scheduler_work'] is False
    assert projected['stages'][0]['submission'] == 'not-applicable'
    with store.transaction('study') as con:
        value = store.get(con,'execution',execution['id'])
        value['stages'][0]['state'] = 'completed'
        store.put(con,'execution',value)
    projected = runs.project_execution('study', h.execution(execution['id']))
    assert projected['stages'][0]['submission'] == 'not-applicable'
    assert projected['stages'][0]['lifecycle'] == 'succeeded'


def test_scheduler_success_with_incomplete_outputs_blocks_only_consumers(harness):
    from test_workspace_planner import write_manifest
    h = harness
    h.manifest['operations']['check-incomplete']={'argv':['python3','-c','print(\'{"complete": false, "errors": ["one expected sample is missing"]}\')'],'location':'controller'}
    h.manifest['check_operation']='check-incomplete'
    write_manifest(h.root,h.manifest)
    _, plan, execution = h.start(draft(variant_parameters={},stages=['t1','t2']))
    h.tick(); h.finish_jobs(plan); h.tick()
    value=runs.project_execution('study',h.execution(execution['id']))
    producer, consumer=value['stages']
    assert producer['state']=='failed'
    assert producer['jobs'][0]['status']=='COMPLETED'
    assert producer['completeness']=='partial'
    assert consumer['state']=='waiting' and 'Prerequisite' in consumer['waiting_reason']
    assert len(h.calls)==1


def test_scoped_execution_and_queue_filters_keep_collection_campaign_and_dates(harness):
    from lib import campaign
    h = harness
    _, plan, first = h.start(); h.tick()
    with store.transaction('study') as con:
        saved=store.get(con,'plan',plan['id']); saved['variants'][0]['parameters']['family']='tlaibench'; store.put(con,'plan',saved)
        current=store.get(con,'execution',first['id']); current['approved_at']='2030-01-02T00:30:00+00:00'; store.put(con,'execution',current)
    # The projection reads the frozen configuration rather than a later live declaration.
    assert [e['id'] for e in runs.executions('study',{'collection':'tlaibench','campaign':first['campaign'],'date':'2030-01-01/2030-01-02'})['executions']]==[first['id']]
    assert runs.executions('study',{'collection':'original'})['executions']==[]
    assert runs.executions('study',{'campaign':'different'})['executions']==[]
    assert runs.executions('study',{'date':'2030-01-03'})['executions']==[]
    assert len(runs.executions('study',{'search':first['id']})['executions'])==1
    assert runs.executions('study',{'search':'no-match'})['executions']==[]
    jobs=runs.queue('study',{'collection':'tlaibench','campaign':first['campaign'],'state':'PENDING'})['jobs']
    assert len(jobs)==1 and jobs[0]['execution_id']==first['id']
    assert runs.queue('study',{'state':'RUNNING'})['jobs']==[]
    assert runs.queue('study',{'collection':'original'})['jobs']==[]
    assert runs.queue('study',{'campaign':'different'})['jobs']==[]
    with pytest.raises(store.WorkspaceError,match='Date filter'):
        runs.executions('study',{'date':'yesterday'})
    with pytest.raises(store.WorkspaceError,match='Date filter'):
        runs.queue('study',{'date':'2030-02-01/2030-01-01'})


def test_remote_timeout_keeps_cached_bytes_and_their_age(harness, monkeypatch):
    h=harness; _,_,execution=h.start();h.tick()
    stage=h.execution(execution['id'])['stages'][0];attempt=stage['attempts'][0]
    path=h.root/'_results'/execution['campaign']/f"{attempt['exp']}-{stage['job_ids'][0]}.out"
    path.parent.mkdir(parents=True);path.write_text('cached evidence')
    import os
    os.utime(path,(1000000000,1000000000))
    def unavailable(*args,**kwargs):raise store.WorkspaceError('Remote log unavailable: fixture timeout')
    monkeypatch.setattr(runs,'_remote_transport',unavailable)
    value=runs.logs('study',attempt['id'])
    assert value['text']=='cached evidence' and value['freshness']['state']=='stale'
    assert 'timeout' in value['remote_error'] and value['retrieval_supported']


def test_missing_remote_stream_does_not_hide_preserved_cached_log(harness, monkeypatch):
    h=harness; _,_,execution=h.start();h.tick()
    stage=h.execution(execution['id'])['stages'][0];attempt=stage['attempts'][0]
    path=h.root/'_results'/execution['campaign']/f"{attempt['exp']}-{stage['job_ids'][0]}.out"
    path.parent.mkdir(parents=True);path.write_text('preserved before remote removal')
    monkeypatch.setattr(runs,'_remote_transport',lambda *a,**k:{'availability':'not-created','reason':'Remote stream is absent'})
    result=runs.logs('study',attempt['id'])
    assert result['text']=='preserved before remote removal'
    assert result['remote_error']=='Remote stream is absent'
    assert not result['retrieval_supported']
