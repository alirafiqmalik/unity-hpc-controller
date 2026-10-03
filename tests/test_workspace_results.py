import copy
import json
import pytest
from controller import workspace_artifacts as files, workspace_results as results, workspace_store as store
from test_workspace_artifacts import artifact_project, artifact


def test_four_conditions_keep_caps_and_scoped_sample_ids(artifact_project):
    root,_,_=artifact_project
    artifacts=[files.preserve_artifact('artifacts',artifact(root,str(i),cap=cap)) for i,cap in enumerate([128,256,128,256])]
    samples=[results.samples('artifacts',{'artifact':a['id']})['samples'][0] for a in artifacts]
    assert len({s['id'] for s in samples})==4 and {s['effective_cap'] for s in samples}=={128,256}
    comparison=results.compare('artifacts',{'artifact_ids':[a['id'] for a in artifacts],'baseline':artifacts[0]['id']})
    assert comparison['coverage']['matched']==1 and comparison['paired_deltas_enabled']
    export=results.export_comparison('artifacts',comparison['id'])
    assert len(export['artifact_references'])==4 and len(export['comparison']['conditions'])==4


def test_mismatch_and_missing_provenance_disable_delta(artifact_project):
    root,_,_=artifact_project;a=files.preserve_artifact('artifacts',artifact(root,'a'));b=artifact(root,'b');b['provenance']['evaluator_version']='different';b=files.preserve_artifact('artifacts',b)
    c=results.compare('artifacts',{'artifact_ids':['a','b'],'baseline':'a'})
    assert c['compatibility']=='different' and not c['paired_deltas_enabled']
    b=artifact(root,'c');b['provenance']['dataset_revision']=None;files.preserve_artifact('artifacts',b)
    assert results.compare('artifacts',{'artifact_ids':['a','c'],'baseline':'a'})['compatibility']=='unknown'


def test_schema_and_metric_versions_frozen_before_declaration_edits(artifact_project):
    root,_,m=artifact_project;a=files.preserve_artifact('artifacts',artifact(root))
    m['result_schemas']['fixture']['fields']['effective_cap']='wrong';m['metrics']['tokens']['field']='missing';(root/'unityHPC/project.json').write_text(json.dumps(m))
    assert results.samples('artifacts',{'artifact':a['id']})['samples'][0]['effective_cap']==128
    assert results.metrics('artifacts',{'artifact_ids':[a['id']]})['metrics'][0]['value']==128


def test_smoke_excluded_and_missing_values_not_zero(artifact_project):
    root,_,_=artifact_project;files.preserve_artifact('artifacts',artifact(root,'smoke',purpose='smoke-test'))
    a=files.preserve_artifact('artifacts',artifact(root,'research',rows=[{'item':'a','dataset':'d'}]))
    assert [x['id'] for x in results.query('artifacts',{})['artifacts']]==['research']
    m=results.metrics('artifacts',{'artifact_ids':['research']})['metrics'][0]
    assert m['value'] is None and m['denominator']==0 and m['excluded']==1


def test_ambiguous_join_blocks_paired_delta_and_keeps_unmatched(artifact_project):
    root,_,_=artifact_project
    r={'dataset':'d','item':'one','stage':'t1','seed':1,'tokens':5}
    files.preserve_artifact('artifacts',artifact(root,'a',rows=[r,r,{**r,'item':'unmatched'}]))
    files.preserve_artifact('artifacts',artifact(root,'b',rows=[r]))
    c=results.compare('artifacts',{'artifact_ids':['a','b'],'baseline':'a'})
    assert not c['paired_deltas_enabled'] and c['coverage']['unmatched']['a']==1 and c['conditions'][0]['duplicates']==1


def test_samples_bounded_pages_and_reference_conflict(artifact_project):
    root,_,_=artifact_project
    a=files.preserve_artifact('artifacts',artifact(root,rows=[{'item':str(i),'tokens':i} for i in range(120)]))
    p=results.samples('artifacts',{'artifact':a['id']});assert len(p['samples'])==100 and p['next_cursor']
    next_page=results.samples('artifacts',{'artifact':a['id'],**p['next_cursor']});assert len(next_page['samples'])==20
    assert results.sample('artifacts',p['samples'][0]['id'])['item']=='0'
    with pytest.raises(store.Conflict):results.validate_references('artifacts',[{'kind':'artifact','id':a['id'],'version':'wrong'}])


def test_typed_plot_points_and_saved_exports_keep_exact_cohort(artifact_project):
    root,_,_=artifact_project;a=files.preserve_artifact('artifacts',artifact(root))
    p=results.points('artifacts',{'artifact_ids':[a['id']],'metrics':['tokens']})
    assert p['points'][0]['tokens']==128 and p['points'][0]['sample_id']
    view=results.save_view('artifacts',{'references':[{'kind':'artifact','id':a['id']}],'metrics':['tokens'],'form':'histogram'})
    assert view['data']['points']==p['points'] and view['data']['definitions']['tokens']['unit']=='tokens'


def test_parent_resolution_never_substitutes_another_variant(artifact_project):
    root,_,m=artifact_project;m['result_schemas']['fixture']['fields']['parent_record_id']='parent_record_id';(root/'unityHPC/project.json').write_text(json.dumps(m))
    files.preserve_artifact('artifacts',artifact(root,'parent'))
    child=artifact(root,'child',rows=[{'record_id':'child','parent_record_id':'same-across-conditions'}]);child['provenance']['parent']={'execution_id':'execution-parent','variant_id':'wrong-variant'}
    a=files.preserve_artifact('artifacts',child);s=results.samples('artifacts',{'artifact':a['id']})['samples'][0]
    assert not results.parent('artifacts',s['id'])['available']


def test_metric_definition_mismatch_disables_paired_deltas(artifact_project):
    root,_,m=artifact_project;files.preserve_artifact('artifacts',artifact(root,'a'))
    m['metrics']['tokens']['unit']='seconds';(root/'unityHPC/project.json').write_text(json.dumps(m));files.preserve_artifact('artifacts',artifact(root,'b'))
    c=results.compare('artifacts',{'artifact_ids':['a','b'],'baseline':'a'})
    assert not c['paired_deltas_enabled'] and 'Metric definitions' in c['paired_delta_reason']


def test_sample_cursor_continues_into_next_jsonl_member(artifact_project):
    root,_,_=artifact_project;a=artifact(root,rows=[{'item':str(i),'tokens':i} for i in range(101)])
    other=root/a['path']/'z.jsonl';other.write_text('{"item":"next-file"}\n')
    a['files'].append({'path':str(other.relative_to(root)),'sha256':files.digest(other),'size':other.stat().st_size});a['digest']=files.fingerprint(a['files'])
    a=files.preserve_artifact('artifacts',a);p=results.samples('artifacts',{'artifact':a['id']});p=results.samples('artifacts',{'artifact':a['id'],**p['next_cursor']})
    assert [r['item'] for r in p['samples']]==['100','next-file']


def test_actual_project_t3_mapping_preserves_turns_applicability_and_actual_parent(artifact_project):
    from pathlib import Path
    root,_,m=artifact_project
    project=Path('/home/ahm/Desktop/project/research/ai-ml/experiments/llm-thinking-trace')
    declared=json.loads((project/'unityHPC/project.json').read_text())
    mapping=declared['result_schemas']['llm-thinking-trace.corpus'];m['result_schemas']['fixture']=mapping
    (root/'unityHPC/project.json').write_text(json.dumps(m))
    parent=artifact(root,'parent',rows=[{'record_id':'actual-parent','benchmark':'tlaibench','item_id':'puzzle::0','benchmark_meta':{'stage':'t2','sample_k':0}}]);files.preserve_artifact('artifacts',parent)
    record={'record_id':'child','benchmark':'tlaibench','item_id':'puzzle::0','model_id':'model','thinking_trace':'emitted rationale','prompt_raw':'',
      'benchmark_meta':{'stage':'t3','sample_k':0,'parent_record_id':'actual-parent','gen_params_effective':{'max_tokens':8192},
        'phase_results':[{'phase':'Refinement','applicable':False,'skipped_reason':'gold_lacks_operator'}],
        'turns':[{'turn_idx':0,'thinking_trace_unclosed':True,'hit_max_tokens':True,'tool_calls':[{'directive':'<script>not executable</script>'}]}]}}
    child=artifact(root,'child',rows=[record]);child['provenance']['parent']={'execution_id':'execution-parent','variant_id':'parent'}
    a=files.preserve_artifact('artifacts',child);s=results.samples('artifacts',{'artifact':a['id']})['samples'][0]
    assert s['effective_cap']==8192 and s['recorded_fields']['prompt']=='recorded-empty' and s['recorded_fields']['formatted_prompt']=='not-recorded'
    assert s['turns'][0]['thinking_trace_unclosed'] and not s['phases'][0]['applicable']
    resolved=results.parent('artifacts',s['id']);assert resolved['available'] and resolved['sample']['record_id']=='actual-parent'


from test_workspace_api import project, call, create_plan


def test_missing_collector_field_rejected_before_any_analysis_dispatch(project):
    from controller import workspace_worker as worker
    _,plan=create_plan();call('POST',f"plans/{plan['id']}/dispatch",{'idempotency_key':'collect'});worker.tick('demo')
    artifact=store.listing('demo','artifact')[0]
    declaration=project/'unityHPC/project.json';m=json.loads(declaration.read_text())
    m['metrics']['new-measurement']={'type':'number','source':'missing.json','field':'new_collector_value','unit':'units','aggregation':'mean','missing':'error'}
    declaration.write_text(json.dumps(m))
    before=len(store.listing('demo','execution'))
    status,response=call('POST','analysis',{'operation':'analyze','artifact_ids':[artifact['id']],'metrics':['new-measurement']})
    assert status==409 and 'new_collector_value' in response['error'] and 'collection plan' in response['error']
    assert len(store.listing('demo','execution'))==before


def test_failed_analysis_retains_partial_outputs_and_prior_report(project):
    from controller import workspace_worker as worker
    _,plan=create_plan();call('POST',f"plans/{plan['id']}/dispatch",{'idempotency_key':'collect'});worker.tick('demo')
    source=store.listing('demo','artifact')[0]
    status,analysis=call('POST','analysis',{'operation':'analyze','artifact_ids':[source['id']]});assert status==201
    _,execution=call('POST',f"plans/{analysis['id']}/dispatch",{'idempotency_key':'good-report'});worker.tick('demo')
    prior=next(a for a in store.listing('demo','artifact') if a['execution_id']==execution['id']);before=files.download('demo',prior['id'],prior['files'][0]['path'])[0]
    (project/'science.py').write_text('import pathlib,sys\np=pathlib.Path(sys.argv[1]);p.mkdir(parents=True,exist_ok=True);(p/"result.txt").write_text("partial report before failure");sys.exit(1)\n')
    status,failed_plan=call('POST','analysis',{'operation':'analyze','artifact_ids':[source['id']]});assert status==201
    _,failed=call('POST',f"plans/{failed_plan['id']}/dispatch",{'idempotency_key':'failed-report'});worker.tick('demo')
    state=store.read('demo','execution',failed['id']);assert state['stages'][0]['state']=='failed' and state['state']=='paused'
    partial=next(a for a in store.listing('demo','artifact') if a['execution_id']==failed['id'])
    assert b'partial report' in files.download('demo',partial['id'],partial['files'][0]['path'])[0]
    assert files.download('demo',prior['id'],prior['files'][0]['path'])[0]==before
    assert len(store.listing('demo','execution'))==3


from test_workspace_project_mock import connected_project


def test_actual_project_saved_metric_fields_and_optional_capture_gate(connected_project):
    from controller import workspace,workspace_worker as worker
    experiment=workspace.create('fixture',{'workflow':'tlaibench-smoke'})
    plan=workspace.plan('fixture',experiment['id']);execution=workspace.dispatch_plan('fixture',plan['id'],'metric-fields')
    worker.tick('fixture')
    artifact=next(a for a in store.listing('fixture','artifact') if a['execution_id']==execution['id'])
    definitions=artifact['metric_definitions']
    results.check_analysis_metrics('fixture',[artifact],['accuracy','completion_tokens'],definitions)
    with pytest.raises(store.Conflict,match='collector field'):
        results.check_analysis_metrics('fixture',[artifact],['turn_prompts'],definitions)


def test_campaign_scope_filters_artifacts_and_analysis_history(artifact_project):
    root,_,_=artifact_project
    for name in ['one','two']:
        a=files.preserve_artifact('artifacts',artifact(root,name))
        with store.transaction('artifacts') as con:
            store.put(con,'execution',{'id':a['execution_id'],'campaign':'campaign-'+name,'plan_id':'plan-'+name})
            store.put(con,'plan',{'id':'plan-'+name,'kind':'analysis','artifact_ids':[a['id']]})
    q=results.query('artifacts',{'campaign':'campaign-one'})
    assert [a['id'] for a in q['artifacts']]==['one']
    assert [p['id'] for p in q['analyses']]==['plan-one']


def test_large_corpus_scan_budgets_malformed_and_oversized_records(artifact_project):
    import time
    root,_,_=artifact_project
    # More than eight MiB: byte ceiling stops a scan before the record ceiling.
    records=[{'record_id':str(i),'item':str(i),'tokens':i,'text':'x'*2048} for i in range(5001)]
    a=files.preserve_artifact('artifacts',artifact(root,'large',rows=records))
    started=time.monotonic();rows,errors,truncated,cursor=results._scan('artifacts',a);elapsed=time.monotonic()-started
    read_bytes=sum(r['locator']['bytes'] for r in rows)
    assert truncated and cursor and len(rows)<=results.SCAN_RECORDS and read_bytes<=results.SCAN_BYTES
    print(f'large scan: {len(rows)} records, {read_bytes} bytes, {elapsed:.3f} seconds')
    # Small records prove the independent 5,000-record ceiling.
    b=files.preserve_artifact('artifacts',artifact(root,'many',rows=[{'item':str(i)} for i in range(6000)]))
    scanned,_,partial,_=results._scan('artifacts',b);assert len(scanned)==5000 and partial
    c=artifact(root,'malformed',rows=[]);path=root/c['files'][0]['path']
    path.write_bytes(b'{bad json}\n'+json.dumps({'text':'x'*(files.MAX_BYTES+100)}).encode()+b'\n'+b'{"item":"checked-local"}\n')
    c['files'][0].update(sha256=files.digest(path),size=path.stat().st_size);c['digest']=files.fingerprint(c['files']);c=files.preserve_artifact('artifacts',c)
    page=results.samples('artifacts',{'artifact':c['id']});assert len(page['errors'])==2 and page['next_cursor']
    with store.transaction('artifacts') as con:
        c['availability']='remote';c['retrieval']='partial';store.put(con,'artifact',c)
    next_page=results.samples('artifacts',{'artifact':c['id'],**page['next_cursor']})
    assert next_page['samples'][0]['item']=='checked-local'


def test_analysis_deep_link_selects_exact_revision_and_page_identity_is_stable(artifact_project):
    root,_,_=artifact_project
    for name in ['one','two']:
        a=files.preserve_artifact('artifacts',artifact(root,name))
        with store.transaction('artifacts') as con:
            store.put(con,'execution',{'id':a['execution_id'],'campaign':'campaign','plan_id':'plan-'+name})
            store.put(con,'plan',{'id':'plan-'+name,'kind':'analysis','analysis_revision':1 if name=='one' else 2,'artifact_ids':[]})
    q=results.query('artifacts',{'analysis':'plan-one'})
    assert [a['id'] for a in q['artifacts']]==['one'] and [p['id'] for p in q['analyses']]==['plan-one']
    first=results.query('artifacts',{'limit':1});second=results.query('artifacts',{'limit':1,'offset':1,'selection_fingerprint':first['selection_fingerprint']})
    assert first['result_set_id']==second['result_set_id'] and first['index_version']=='bounded-scan-v1'


def test_declared_coverage_stays_per_artifact_without_cross_stage_double_count(artifact_project):
    root,_,_=artifact_project;a=artifact(root);a['evidence']={'coverage':{'expected':5,'observed':4,'assessed':3,'duplicates':0,'exclusions':1}}
    files.preserve_artifact('artifacts',a);q=results.query('artifacts',{})
    assert q['coverage']['by_artifact'][0]['expected']==5 and q['coverage']['by_artifact'][0]['observed']==4
    assert q['coverage']['expected_items'] is None and q['coverage']['count_scope'].startswith('per artifact')


def test_line_plot_requires_declared_unique_step_and_retains_conditions(artifact_project):
    root,_,m=artifact_project
    m['metrics']['step']={'source':'*.jsonl','field':'step','type':'integer','unit':'step','axis':'step','aggregation':'none'}
    (root/'unityHPC/project.json').write_text(json.dumps(m))
    a=files.preserve_artifact('artifacts',artifact(root,rows=[{'step':1,'tokens':4},{'step':2,'tokens':5}]))
    v=results.save_view('artifacts',{'references':[{'kind':'artifact','id':a['id']}],'form':'line','metrics':['step','tokens'],'step_field':'step'})
    assert len(v['data']['points'])==2 and v['step_field']=='step'
    b=files.preserve_artifact('artifacts',artifact(root,'ambiguous',rows=[{'step':1,'tokens':4},{'step':1,'tokens':5}]))
    with pytest.raises(store.Conflict,match='multiple observations'):results.save_view('artifacts',{'references':[{'kind':'artifact','id':b['id']}],'form':'line','metrics':['step','tokens'],'step_field':'step'})


def test_result_reference_and_scope_conflicts_expose_actual_tokens(artifact_project):
    root,_,_=artifact_project
    saved=files.preserve_artifact('artifacts',artifact(root))
    checks=[
        (lambda:results.validate_references('artifacts',[{'kind':'artifact','id':saved['id'],'version':'stale'}]),saved['content_version']),
        (lambda:results.samples('artifacts',{'artifact':saved['id'],'version':'stale'}),saved['content_version']),
        (lambda:results.query('artifacts',{'selection_fingerprint':'stale'}),results.query('artifacts',{})['selection_fingerprint']),
    ]
    for function,current in checks:
        with pytest.raises(store.Conflict) as error:function()
        assert error.value.current_version==current and error.value.expected_version=='stale'


def test_nonfinite_scientific_records_excluded_before_browser_response(artifact_project):
    root,_,_=artifact_project
    a=artifact(root,rows=[{'record_id':'bad','item':'bad','tokens':float('nan')},{'record_id':'good','item':'good','tokens':128}])
    saved=files.preserve_artifact('artifacts',a)
    response=results.samples('artifacts',{'artifact':saved['id']})
    assert len(response['samples'])==1 and response['samples'][0]['item']=='good'
    assert len(response['errors'])==1 and 'Non-finite' in response['errors'][0]['reason']
    json.dumps(response,allow_nan=False)
