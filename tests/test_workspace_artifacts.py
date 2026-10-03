"""Version, boundary, and transfer fault checks with isolated local fixtures."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from controller import registry, workspace_store as store, workspace_artifacts as files


@pytest.fixture
def artifact_project(tmp_path, monkeypatch):
    monkeypatch.setenv('UNITY_HPC_DATA', str(tmp_path/'state'))
    root=tmp_path/'project'; (root/'unityHPC').mkdir(parents=True)
    remote=tmp_path/'remote';remote.mkdir()
    manifest={'schema_version':1,'application':'test','default_primitive':'cpu','default_mode':'single','source_paths':[],
              'operations':{},'workflows':{},'parameters':{},'metrics':{'tokens':{'type':'number','field':'tokens','source':'corpus/*.jsonl','unit':'tokens','aggregation':'mean'}},
              'result_schemas':{'fixture':{'version':1,'fields':{'record_id':'record_id','dataset':'dataset','item':'item','model':'model','stage':'stage','sample_index':'seed','effective_cap':'cap','tokens':'tokens'},
                   'join_fields':['dataset','item','stage','sample_index'],'compatibility_fields':['dataset_revision','evaluator_version'],
                   'compatibility':{'dataset_revision':'provenance.dataset_revision','evaluator_version':'provenance.evaluator_version'}}},
              'retrieval':{'version':1,'adapter':'local-copy','source_root':str(remote)}}
    (root/'unityHPC/project.json').write_text(json.dumps(manifest));registry.attach('artifacts',root)
    return root, remote, manifest


def artifact(root, identity='evidence', *, rows=None, cap=128, complete=True, purpose='experiment'):
    directory=root/'.unity-workspace/outputs'/identity/'variant'/'stage';directory.mkdir(parents=True,exist_ok=True)
    path=directory/'samples.jsonl'
    rows=rows if rows is not None else [{'record_id':'same-across-conditions','dataset':'fixture','item':'item-1','model':'model','stage':'t1','seed':0,'cap':cap,'tokens':cap}]
    path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    members=[{'path':str(path.relative_to(root)),'sha256':files.digest(path),'size':path.stat().st_size}]
    return dict(id=identity,execution_id='execution-'+identity,variant_id=identity,stage_id='t1',attempt_id='attempt',purpose=purpose,
                schema='fixture',version=1,path=str(directory.relative_to(root)),files=members,digest=files.fingerprint(members),complete=complete,
                provenance={'dataset_revision':'dataset-v1','evaluator_version':'evaluator-v1'},parameters={'cap':cap})


def test_immutable_copies_preserve_prior_versions_and_download(artifact_project):
    root,_,_=artifact_project
    first=files.preserve_artifact('artifacts',artifact(root))
    old=files.download('artifacts',first['id'],first['files'][0]['path'])[0]
    second=files.preserve_artifact('artifacts',artifact(root,cap=256))
    assert second['id'] != first['id'] and second['logical_id']==first['id']
    assert files.download('artifacts',first['id'],first['files'][0]['path'])[0]==old
    assert len(store.listing('artifacts','artifact'))==2
    assert files.freeze_inputs('artifacts',[first['id']])[0]['id']==first['id']


def test_legacy_artifact_freeze_keeps_identity(artifact_project):
    root,_,_=artifact_project;value=artifact(root)
    with store.transaction('artifacts') as con: store.put(con,'artifact',value)
    assert files.freeze_inputs('artifacts',[value['id']])[0]['id']==value['id']


def test_browse_rejects_secrets_symlinks_traversal_and_special_files(artifact_project):
    root,_,_=artifact_project;(root/'.env').write_text('SECRET');(root/'escape').symlink_to(root.parent);(root/'innocent.txt').symlink_to(root/'.env')
    for relative in ['.env','../state','escape','innocent.txt']:
        with pytest.raises(store.WorkspaceError): files.preview('artifacts',{'root':'source','path':relative})
    assert '.env' not in [e['name'] for e in files.browse('artifacts',{})['entries']]
    assert next(e for e in files.browse('artifacts',{})['entries'] if e['name']=='escape')['availability']=='unavailable'


def test_preview_budget_parse_error_and_change_conflict(artifact_project):
    root,_,_=artifact_project;(root/'large.txt').write_text('line\n'*10000)
    p=files.preview('artifacts',{'path':'large.txt','limit':99999999})
    assert p['loaded_bytes']<=files.MAX_BYTES and len(p['text'].splitlines())==2000 and p['next_offset']
    (root/'large.txt').write_text('changed')
    with pytest.raises(store.Conflict): files.preview('artifacts',{'path':'large.txt','version':p['version']})
    (root/'bad.json').write_text('{"broken"')
    p=files.preview('artifacts',{'path':'bad.json'});assert p['text']=='{"broken"' and p['parse_error']


def test_preview_literal_markup_and_immutable_stat_check(artifact_project):
    root,_,_=artifact_project; a=files.preserve_artifact('artifacts',artifact(root))
    path=root/a['files'][0]['frozen_path'];path.write_text('<script>alert(1)</script>')
    with pytest.raises(store.Conflict): files.preview('artifacts',{'artifact':a['id'],'path':a['files'][0]['path']})
    (root/'literal.html').write_text('<script>alert(1)</script>')
    assert files.preview('artifacts',{'path':'literal.html'})['text']=='<script>alert(1)</script>'


def remote_artifact(root, remote):
    a=artifact(remote);a['availability']='remote';a['remote_files']=a['files'];a['files']=[]
    with store.transaction('artifacts') as con:store.put(con,'artifact',a)
    return a


def test_partial_transfer_quarantines_bytes_and_preserves_destination(artifact_project):
    root,remote,_=artifact_project;a=remote_artifact(root,remote)
    original=root/a['path'];original.mkdir(parents=True);(original/'samples.jsonl').write_text('unrelated prior bytes')
    preview=files.prepare_transfer('artifacts',{'artifact_ids':[a['id']]})
    (remote/a['remote_files'][0]['path']).write_text('remote changed after review')
    receipt=files.commit_transfer('artifacts',preview['id'],'transfer',background=False)
    assert receipt['state']=='failed' and receipt['members'][0]['state']=='failed'
    assert (original/'samples.jsonl').read_text()=='unrelated prior bytes'
    assert list((root/'.unity-workspace/transfers'/receipt['id']/'partial').iterdir())
    assert store.read('artifacts','artifact',a['id'])['availability']=='remote'


def test_successful_retrieval_does_not_promote_incomplete_science(artifact_project):
    root,remote,_=artifact_project;a=remote_artifact(root,remote);a['complete']=False
    with store.transaction('artifacts') as con:store.put(con,'artifact',a)
    preview=files.prepare_transfer('artifacts',{'artifact_ids':[a['id']]})
    t=files.commit_transfer('artifacts',preview['id'],'once',background=False)
    assert t['state']=='succeeded'
    assert not store.read('artifacts','artifact',a['id'])['complete']
    assert files.commit_transfer('artifacts',preview['id'],'once')['id']==t['id']


def test_transfer_restart_reconciles_before_retry(artifact_project):
    root,remote,_=artifact_project;a=remote_artifact(root,remote)
    preview=files.prepare_transfer('artifacts',{'artifact_ids':[a['id']]})
    t=files.commit_transfer('artifacts',preview['id'],'once',background=False)
    with store.transaction('artifacts') as con:t['state']='uncertain';store.put(con,'transfer',t)
    retry=files.prepare_transfer('artifacts',{'artifact_ids':[a['id']]})
    with pytest.raises(store.Conflict):files.commit_transfer('artifacts',retry['id'],'again',background=False)
    assert files.reconcile_transfer('artifacts',t['id'])['state']=='succeeded'


def test_unknown_adapter_cannot_call_legacy_hook(artifact_project):
    root,_,m=artifact_project;m.pop('retrieval');(root/'unityHPC/project.json').write_text(json.dumps(m))
    with pytest.raises(store.WorkspaceError,match='legacy corpus hook'):files.prepare_transfer('artifacts',{'artifact_ids':['missing']})


def test_complete_observation_same_bytes_keeps_prior_check_history(artifact_project):
    root,_,_=artifact_project;a=artifact(root,complete=False);first=files.preserve_artifact('artifacts',a)
    a['complete']=True;a['evidence']={'complete':True,'expected':1,'observed':1}
    second=files.preserve_artifact('artifacts',a)
    assert second['id']==first['id'] and second['complete'] and second['completeness_history'][-1]['complete']


def test_retry_selects_only_failed_members_and_cancel_never_touches_execution(artifact_project):
    root,remote,_=artifact_project;a=remote_artifact(root,remote)
    preview=files.prepare_transfer('artifacts',{'artifact_ids':[a['id']]})
    t=files.commit_transfer('artifacts',preview['id'],'once',background=False)
    with pytest.raises(store.WorkspaceError,match='no exact remote member'):files.prepare_transfer('artifacts',{'artifact_ids':[a['id']],'prior_transfer_id':t['id']})
    files.cancel_transfer('artifacts',t['id'])
    assert store.listing('artifacts','execution')==[]


def test_partial_retry_preserves_successes_and_freezes_full_corpus(artifact_project,monkeypatch):
    root,remote,_=artifact_project;a=remote_artifact(root,remote)
    extra=remote/a['path']/'extra.txt';extra.write_text('checked second file')
    a['remote_files'].append({'path':str(extra.relative_to(remote)),'sha256':files.digest(extra),'size':extra.stat().st_size})
    with store.transaction('artifacts') as con:store.put(con,'artifact',a)
    original=files._copy_member
    def fail_second(slug,t,m,tmp):
        if m['path'].endswith('extra.txt'):raise OSError('fixture connection interrupted')
        return original(slug,t,m,tmp)
    monkeypatch.setattr(files,'_copy_member',fail_second)
    p=files.prepare_transfer('artifacts',{'artifact_ids':[a['id']]});first=files.commit_transfer('artifacts',p['id'],'first',background=False)
    assert first['state']=='partial'
    with pytest.raises(store.Conflict,match='partly available'):files.freeze_inputs('artifacts',[a['id']])
    monkeypatch.setattr(files,'_copy_member',original)
    p=files.prepare_transfer('artifacts',{'artifact_ids':[a['id']],'prior_transfer_id':first['id']})
    assert len(p['members'])==1 and p['members'][0]['path'].endswith('extra.txt')
    assert files.commit_transfer('artifacts',p['id'],'retry',background=False)['state']=='succeeded'
    complete=store.read('artifacts','artifact',a['id']);assert len(complete['files'])==2
    frozen=files.freeze_inputs('artifacts',[a['id']])[0]
    assert (root/frozen['frozen_path']/'extra.txt').read_text()=='checked second file'


def test_cancel_running_transfer_terminates_only_its_process(artifact_project,monkeypatch):
    import os,subprocess,sys,threading,time
    root,remote,m=artifact_project;a=remote_artifact(root,remote)
    m['retrieval']={'version':1,'adapter':'rsync-files','host':'fixture'};(root/'unityHPC/project.json').write_text(json.dumps(m))
    registry.update('artifacts',remote_dir='/fixture')
    spawned=[];ready=threading.Event();original=subprocess.Popen
    def fake_remote_command(command,**kwargs):
        process=original([sys.executable,'-c','import time; time.sleep(60)'],**kwargs)
        spawned.append(process);ready.set();return process
    monkeypatch.setattr(files.subprocess,'Popen',fake_remote_command)
    p=files.prepare_transfer('artifacts',{'artifact_ids':[a['id']]});t=files.commit_transfer('artifacts',p['id'],'cancel-active')
    assert ready.wait(3)
    files.cancel_transfer('artifacts',t['id'])
    thread=files._TRANSFER_THREADS[('artifacts',t['id'])];thread.join(4)
    assert not thread.is_alive() and spawned[0].poll() is not None
    receipt=store.read('artifacts','transfer',t['id']);assert receipt['state']=='cancelled'
    assert store.listing('artifacts','execution')==[]


def test_snapshot_destination_symlink_cannot_escape_project(artifact_project):
    root,_,_=artifact_project;a=artifact(root);outside=root.parent/'outside';outside.mkdir()
    (root/'.unity-workspace/artifacts').symlink_to(outside)
    with pytest.raises(store.WorkspaceError,match='escapes'):files.preserve_artifact('artifacts',a)
    assert not list(outside.iterdir())


def test_retrieval_review_invalidated_by_connection_change(artifact_project):
    root,remote,_=artifact_project;a=remote_artifact(root,remote)
    p=files.prepare_transfer('artifacts',{'artifact_ids':[a['id']]})
    registry.update('artifacts',remote_dir='/different-reviewed-root')
    with pytest.raises(store.Conflict,match='connection changed'):files.commit_transfer('artifacts',p['id'],'changed',background=False)
    assert not store.listing('artifacts','transfer')


def test_structured_preview_png_bounds_and_producer_metadata(artifact_project):
    import base64,struct
    root,_,_=artifact_project
    (root/'records.jsonl').write_text('{"key":"<script>literal</script>"}\n')
    (root/'table.csv').write_text('id,value\n01,0002\n')
    assert files.preview('artifacts',{'path':'records.jsonl'})['records'][0]['value']['key']=='<script>literal</script>'
    assert files.preview('artifacts',{'path':'table.csv'})['rows'][1]==['01','0002']
    png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/2S8AAAAASUVORK5CYII=')
    (root/'tiny.png').write_bytes(png);p=files.preview('artifacts',{'path':'tiny.png'})
    assert p['kind']=='image' and p['width']==1 and p['height']==1
    (root/'huge.png').write_bytes(png[:16]+struct.pack('>II',9000,9000)+png[24:]);p=files.preview('artifacts',{'path':'huge.png'})
    assert p['kind']=='binary' and 'dimensions' in p['reason']
    a=files.preserve_artifact('artifacts',artifact(root));q=files.browse('artifacts',{'root':'outputs','execution':a['execution_id'],'purpose':'experiment'})
    assert q['entries'][0]['execution_ids']==[a['execution_id']] and q['entries'][0]['purposes']==['experiment']


def test_remote_known_output_tree_browses_metadata_without_transfer(artifact_project):
    root,remote,_=artifact_project;a=remote_artifact(root,remote)
    listing=files.browse('artifacts',{'root':'outputs'})
    assert listing['entries'][0]['availability']=='remote' and listing['entries'][0]['kind']=='directory'
    relative=str(Path(a['path']).relative_to('.unity-workspace/outputs'))
    leaf=files.browse('artifacts',{'root':'outputs','path':relative})
    assert leaf['entries'][0]['name']=='samples.jsonl' and leaf['entries'][0]['availability']=='remote'
    assert not store.listing('artifacts','transfer') and not (root/'.unity-workspace/outputs').exists()


def test_changed_source_filter_does_not_change_frozen_evidence(artifact_project):
    root,_,_=artifact_project;a=files.preserve_artifact('artifacts',artifact(root));before=files.download('artifacts',a['id'],a['files'][0]['path'])[0]
    (root/a['files'][0]['path']).write_text('later mutable output')
    relative=str(Path(a['path']).relative_to('.unity-workspace/outputs'))
    listing=files.browse('artifacts',{'root':'outputs','path':relative,'changed':'true'})
    assert listing['entries'][0]['integrity']=='changed'
    assert files.download('artifacts',a['id'],a['files'][0]['path'])[0]==before


def test_secret_alias_in_non_source_root_is_denied_everywhere(artifact_project):
    root,_,m=artifact_project;outputs=root/'.unity-workspace/outputs';outputs.mkdir(parents=True)
    private=outputs/'private.txt';private.write_text('protected bytes');(outputs/'alias.txt').symlink_to(private)
    m['environment']={'secret_paths':['.unity-workspace/outputs/private.txt']};(root/'unityHPC/project.json').write_text(json.dumps(m))
    for operation in [files.preview,files.download_source]:
        with pytest.raises(store.WorkspaceError,match='excluded'):operation('artifacts',{'root':'outputs','path':'alias.txt'})
    entries=files.browse('artifacts',{'root':'outputs'})['entries']
    assert next(row for row in entries if row['name']=='alias.txt')['availability']=='unavailable'
    assert not any(row['name']=='private.txt' for row in entries)


def test_csv_partial_pages_never_fabricate_multiline_or_split_rows(artifact_project):
    root,_,_=artifact_project
    payload=('id,value\n1,"'+('part\n'*105)+'end"\n2,done\n').encode()
    (root/'multiline.csv').write_bytes(payload)
    first=files.preview('artifacts',{'path':'multiline.csv'})
    assert first['truncated'] and 'rows' not in first and 'logical record boundaries' in first['reason']
    second=files.preview('artifacts',{'path':'multiline.csv','offset':first['next_offset'],'version':first['version']})
    assert 'rows' not in second
    assert (first['text']+second['text']).encode()==payload
    (root/'split.csv').write_bytes('id,value\n1,café\n'.encode())
    split=files.preview('artifacts',{'path':'split.csv','limit':14})
    assert split['truncated'] and 'rows' not in split and split['loaded_bytes']==14
    (root/'bad.csv').write_text('id,value\n1,"unterminated')
    invalid=files.preview('artifacts',{'path':'bad.csv'})
    assert 'rows' not in invalid and 'cannot be parsed safely' in invalid['reason']


def test_file_scope_conflicts_return_actual_concurrency_tokens(artifact_project):
    root,_,_=artifact_project
    (root/'version.txt').write_text('current bytes')
    for function,query,current in [
        (files.browse,{'version':'stale'},files.browse('artifacts',{})['version']),
        (files.preview,{'path':'version.txt','version':'stale'},files.preview('artifacts',{'path':'version.txt'})['version']),
        (files.download_source,{'path':'version.txt','version':'stale'},files.preview('artifacts',{'path':'version.txt'})['version']),
    ]:
        with pytest.raises(store.Conflict) as error: function('artifacts',query)
        assert error.value.current_version==current and error.value.expected_version=='stale'


@pytest.mark.parametrize('constant',['NaN','Infinity','-Infinity','1e999'])
def test_nonfinite_json_stays_raw_and_never_poison_response(artifact_project,constant):
    root,_,_=artifact_project
    raw='{"scientific":'+constant+'}'
    for name in ('invalid-number.json','invalid-number.jsonl'):
        (root/name).write_text(raw)
        response=files.preview('artifacts',{'path':name})
        assert response['text']==raw
        assert 'structured' not in response
        if name.endswith('.jsonl'):assert 'error' in response['records'][0]
        else:assert response['parse_error']['message']
        json.dumps(response,allow_nan=False)
