"""Real project adapter through the API and worker; bounded CPU-only integration.

Set UNITY_PROJECT_MOCK_SOURCE to the llm-thinking-trace checkout when it is not
beside this plugin's workflow directory. No cluster transport is permitted.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil

import pytest

from controller.http import Request, handle
from controller import workspace_store as store
from controller import workspace_worker as worker


def request(method, path, body=None):
    response = handle(Request(method=method, path=path, body=json.dumps(body).encode() if body is not None else b''))
    return response.status, json.loads(response.body) if response.body else {}


@pytest.fixture
def connected_project(tmp_path, tmp_data_dir, monkeypatch):
    repository = Path(__file__).resolve().parents[1]
    source = Path(os.environ.get('UNITY_PROJECT_MOCK_SOURCE', repository.parents[2] / 'research/ai-ml/experiments/llm-thinking-trace'))
    if not (source / 'unityHPC/project.json').is_file():
        pytest.skip('project-owned adapter checkout is unavailable; set UNITY_PROJECT_MOCK_SOURCE')
    declaration = json.loads((source / 'unityHPC/project.json').read_text())
    project = tmp_path / 'project'
    project.mkdir()
    for relative in [*declaration['source_paths'], 'unityHPC/project.json']:
        origin, destination = source / relative, project / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if origin.is_dir():
            shutil.copytree(origin, destination, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        else:
            shutil.copy2(origin, destination)
    (project / 'unityHPC/.env').write_text('UNITY_HOST=invalid-test-host\nREMOTE_DIR=/work/fixture\n')
    (project / 'unityHPC/run.sh').write_text('#!/bin/sh\nexit 97\n')
    monkeypatch.setattr(worker, '_ledger', lambda *_: [])
    def forbidden(*args, **kwargs):
        pytest.fail('a CPU mock integration attempted cluster transport')
    monkeypatch.setattr(worker.transport, 'stage_bundle', forbidden)
    monkeypatch.setattr(worker.transport, 'submit', forbidden)
    status, value = request('POST','/api/v1/projects',{'slug':'fixture','path':str(project),'primitive':'gpu','remote_dir':'/work/fixture'})
    assert status == 201, value
    return project


def test_project_mock_api_dispatch_artifacts_and_reanalysis(connected_project):
    project = connected_project
    base = '/api/v1/projects/fixture/workspace'
    status, connection = request('GET',base+'/connection')
    assert status == 200 and connection['valid'], connection
    assert connection['migration']['legacy']['primitive'] == 'gpu'
    assert connection['migration']['workspace']['primitive'] == 'multi-gpu'
    status, experiment = request('POST',base+'/experiments',{'workflow':'tlaibench-smoke','draft':{
        'variant_parameters':{'model':['r1-distill-qwen-1.5b','qwen3-1.7b'],'token_cap':[128,256]}}})
    assert status == 201, experiment
    status, checked = request('POST',base+'/experiments/'+experiment['id']+'/check',{})
    assert status == 200 and checked['valid'], checked
    status, plan = request('POST',base+'/experiments/'+experiment['id']+'/plans',{})
    assert status == 201 and len(plan['variants']) == 4, plan
    status, execution = request('POST',base+'/plans/'+plan['id']+'/dispatch',{'idempotency_key':'mock-intent'})
    assert status == 202, execution
    worker.tick('fixture')
    finished = store.read('fixture','execution',execution['id'])
    assert finished['state'] == 'completed', finished
    smoke = store.listing('fixture','artifact')
    assert len(smoke) == 4 and all(a['complete'] and a['purpose']=='smoke-test' for a in smoke)
    assert {a['parameters']['token_cap'] for a in smoke} == {128,256}
    status, rejected = request('POST',base+'/analyses',{'operation':'analyze','artifact_ids':[a['id'] for a in smoke]})
    assert status == 409, rejected
    # Test research reanalysis using separate explicitly synthetic research
    # fixtures with valid runner records. The stored Smoke artifacts stay intact.
    fixtures=[]
    for index, original in enumerate(smoke):
        fixture = copy.deepcopy(original)
        # This is a new synthetic corpus, not a new alias for frozen Smoke bytes.
        for key in ('frozen_path', 'logical_id', 'content_version', 'locations', 'supersedes', 'snapshot_files'):
            fixture.pop(key, None)
        fixture['id'] = 'research-fixture-'+str(index)
        fixture['execution_id'] = 'synthetic-research-fixture'
        fixture['purpose'] = 'experiment'
        directory = Path('.unity-workspace/outputs/research-fixture') / str(index) / 't1'
        shutil.copytree(project/original['output_dir'],project/directory)
        companion=project/directory/'workspace-artifact.json'
        metadata=json.loads(companion.read_text());metadata.update(purpose='experiment',synthetic_test_fixture=True)
        companion.write_text(json.dumps(metadata))
        fixture['path']=fixture['output_dir']=str(directory)
        fixture['files']=[{'path':str(p.relative_to(project)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'size':p.stat().st_size}
                          for p in sorted((project/directory).rglob('*')) if p.is_file()]
        fixture['digest']=hashlib.sha256(json.dumps(fixture['files'],sort_keys=True).encode()).hexdigest()
        with store.transaction('fixture') as con:
            store.put(con,'artifact',fixture)
        fixtures.append(fixture)
    previous=None
    for revision in [1,2]:
        status, analysis = request('POST',base+'/analyses',{'operation':'analyze','artifact_ids':[a['id'] for a in fixtures]})
        assert status == 201, analysis
        assert analysis['analysis_revision'] == revision
        status, approved = request('POST',base+'/plans/'+analysis['id']+'/dispatch',{'idempotency_key':'analysis-'+str(revision)})
        assert status == 202, approved
        worker.tick('fixture')
        finished=store.read('fixture','execution',approved['id'])
        assert finished['state']=='completed',finished
        reports=[a for a in store.listing('fixture','artifact') if a['execution_id']==approved['id']]
        assert len(reports)==1 and reports[0]['complete'],reports
        report=json.loads((project/reports[0]['output_dir']/'analysis.json').read_text())
        assert len(report['inputs'])==4
        assert {i['parameters']['max_tokens_per_turn'] for i in report['inputs']}=={128,256}
        if previous:
            assert previous[0].read_bytes()==previous[1]
        path=project/reports[0]['output_dir']/'analysis.json';previous=(path,path.read_bytes())
    assert all(store.read('fixture','artifact',a['id'])['purpose']=='smoke-test' for a in smoke)


def test_project_interrupted_mock_resume_uses_fresh_attempt(connected_project):
    project=connected_project
    adapter=project/'unityHPC/workspace_adapter.py'
    text=adapter.read_text()
    # This deterministic interruption belongs only to the temporary test
    # project's source and is frozen identically into both reviewed plans.
    fixture='''if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'collect':
        from tlaibench import run_traces as fixture_runner
        fixture_append = fixture_runner.append_record
        fixture_count = [0]
        def fixture_interrupt(path, record):
            if fixture_count[0]:
                raise RuntimeError('deterministic fixture interruption')
            fixture_count[0] += 1
            return fixture_append(path, record)
        fixture_runner.append_record = fixture_interrupt
    raise SystemExit(main())
'''
    text=text.replace("if __name__ == '__main__':\n    raise SystemExit(main())\n",fixture)
    adapter.write_text(text)
    manifest_path=project/'unityHPC/project.json'
    declaration=json.loads(manifest_path.read_text())
    declaration['operations']['mock-analysis']=copy.deepcopy(declaration['operations']['analyze'])
    declaration['operations']['mock-analysis']['argv'] += ['--include-smoke','true']
    declaration['workflows']['tlaibench-smoke']['stages'].append({
        'id':'analysis','operation':'mock-analysis','depends_on':['t1'],'purpose':'smoke-test',
        'resources':{'primitive':'cpu','mode':'single','gpus':0},
        'check_operation':'report-check','outputs':declaration['analysis_outputs'],
        'inputs':[{'from_stage':'t1','output':'corpus','schema':'llm-thinking-trace.corpus','version':1}]})
    manifest_path.write_text(json.dumps(declaration))
    base='/api/v1/projects/fixture/workspace'
    status, experiment=request('POST',base+'/experiments',{'workflow':'tlaibench-smoke','draft':{'parameters':{'n_items':2}}})
    assert status==201,experiment
    status, plan=request('POST',base+'/experiments/'+experiment['id']+'/plans',{})
    assert status==201,plan
    status, execution=request('POST',base+'/plans/'+plan['id']+'/dispatch',{'idempotency_key':'interrupt'})
    assert status==202,execution
    worker.tick('fixture')
    failed=store.read('fixture','execution',execution['id'])
    assert failed['state'] in ('failed','paused','attention'),failed
    artifacts=[a for a in store.listing('fixture','artifact') if a['execution_id']==execution['id']]
    assert len(artifacts)==1 and not artifacts[0]['complete'],artifacts
    prior=project/artifacts[0]['output_dir']
    original={str(p.relative_to(prior)):p.read_bytes() for p in prior.rglob('*') if p.is_file()}
    status, resumed_plan=request('POST',base+'/executions/'+execution['id']+'/recovery',{'mode':'resume','stage_ids':[failed['stages'][0]['id']]})
    assert status==201,resumed_plan
    status, resumed=request('POST',base+'/plans/'+resumed_plan['id']+'/dispatch',{'idempotency_key':'resume'})
    assert status==202,resumed
    worker.tick('fixture')
    finished=store.read('fixture','execution',resumed['id'])
    assert finished['state']=='completed',finished
    outputs=[a for a in store.listing('fixture','artifact') if a['execution_id']==resumed['id']]
    assert len(outputs)==2 and all(a['complete'] for a in outputs),outputs
    assert {s['stage_id'] for s in resumed_plan['stages']}=={'t1','analysis'}
    corpus=next(a for a in outputs if a['schema']=='llm-thinking-trace.corpus')
    assert corpus['output_dir']!=artifacts[0]['output_dir']
    assert original=={str(p.relative_to(prior)):p.read_bytes() for p in prior.rglob('*') if p.is_file()}
    companion=json.loads((project/corpus['output_dir']/'workspace-artifact.json').read_text())
    assert companion['resumed_from']['execution_id']==execution['id']
    assert companion['resumed_from']['preserved_records']==1
