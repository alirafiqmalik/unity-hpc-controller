"""Composition uses the accepted planner and durable execution history."""
import copy
import json

import pytest

from controller.workspace_connection import load_connection
from controller.workspace_composition import prepare, supported
from controller.workspace_planner import compile_plan, check_configuration
from tests.test_workspace_planner import connected, draft, write_manifest


@pytest.fixture
def composed(connected):
    root, manifest = connected
    manifest['required_features'] = {'composition': 1}
    for key, op in manifest['operations'].items():
        op.update(write_scope='output_dir', timeout_seconds=30, input_ports={} if key=='collect' else {'corpus': {'schema': 'records', 'version': 1, 'cardinality': 'many', 'purposes': ['experiment']}},
                  output_ports={'corpus' if key=='collect' else 'report': {'schema': 'records' if key=='collect' else 'report', 'version': 1, 'path': 'record.json', 'cardinality': 'one'}})
    write_manifest(root, manifest)
    graph = {'nodes': [{'id': 'collection', 'operation': 'collect', 'operation_version': '1', 'scope': 'per_variant'},
                       {'id': 'analysis', 'operation': 'analyze', 'operation_version': '1', 'scope': 'reduce_selected'}],
             'edges': [{'from_node': 'collection', 'output': 'corpus', 'to_node': 'analysis', 'input': 'corpus'}]}
    return root, manifest, draft(workflow='__composition__', graph=graph)


def test_four_variants_reduce_exact_inputs_and_literal_arguments(composed):
    root, manifest, config = composed
    plan = compile_plan(root, load_connection(root), config, 'composed')
    assert len(plan['variants']) == 4 and len(plan['stages']) == 5
    analysis = next(s for s in plan['stages'] if s['stage_id']=='analysis')
    assert len(analysis['depends_on']) == 4
    inputs = json.loads(analysis['argv'][-1])
    assert len(inputs) == 4 and len(set(inputs)) == 4
    assert {s['parameters']['token_cap'] for s in plan['stages'] if s['stage_id']=='collection'} == {128,256}
    assert "literal; $(touch /bad) ' spaces" in plan['stages'][0]['argv']
    assert len({s['output_dir'] for s in plan['stages']}) == 5


@pytest.mark.parametrize('mutation, message', [
    (lambda m,d: d['graph']['edges'].append({'from_node':'analysis','output':'report','to_node':'collection','input':'missing'}), 'Target input port'),
    (lambda m,d: d['graph']['nodes'][0].update(operation_version='99'), 'Operation version'),
    (lambda m,d: m['operations']['analyze']['input_ports']['corpus'].update(unit='seconds'), 'Incompatible unit'),
    (lambda m,d: d['graph']['nodes'][0].update(purpose='smoke-test'), 'smoke evidence'),
    (lambda m,d: m['composition_limits'] .update(variants=3), 'included variant limit'),
    (lambda m,d: m['operations']['analyze'].update(write_scope='shared-summary'), 'shared mutable writes'),
])
def test_invalid_graphs_block_before_snapshot(composed, mutation, message):
    root, manifest, config = composed
    manifest['composition_limits'] = {}
    mutation(manifest,config)
    write_manifest(root,manifest)
    checked = check_configuration(root,load_connection(root),config)
    assert not checked['valid']
    assert message in json.dumps(checked['errors'])
    assert not (root/'.unity-workspace/plans').exists()


def test_shared_parameter_cannot_vary_and_unknown_feature_blocks_presets(composed):
    root, manifest, config = composed
    config['graph']['nodes'][0]['scope']='shared'
    checked=check_configuration(root,load_connection(root),config)
    assert not checked['valid'] and 'shared stage' in json.dumps(checked['errors'])
    manifest['required_features']['future-science']=7
    conn=write_manifest(root,manifest)
    assert not conn['valid'] and 'Unsupported required feature' in json.dumps(conn['errors'])


def test_old_declarations_retain_workflow_semantics(connected):
    root,manifest=connected
    assert not supported(manifest)
    plan=compile_plan(root,load_connection(root),draft(),'preset')
    assert len(plan['variants'])==4 and len(plan['stages'])==12


# Real project gate uses a copied project and the accepted CPU mock operation.
from tests.test_workspace_project_mock import connected_project, request
from controller import workspace_store as store, workspace_worker as worker


def test_actual_project_four_variant_composed_equivalent(connected_project):
    root=connected_project
    manifest=json.loads((root/'unityHPC/project.json').read_text())
    workflow=manifest['workflows']['tlaibench-smoke']
    nodes=[]
    for stage in workflow['stages']:
        node={k:copy.deepcopy(stage[k]) for k in ('id','operation','purpose','resources','parameters') if k in stage}
        node.update(operation_version=manifest['operations'][stage['operation']]['version'],scope='per_variant')
        nodes.append(node)
    base='/api/v1/projects/fixture/workspace'
    values={'model':['r1-distill-qwen-1.5b','qwen3-1.7b'],'token_cap':[128,256]}
    status,preset=request('POST',base+'/experiments',{'workflow':'tlaibench-smoke','draft':{'variant_parameters':values}})
    assert status==201,preset
    status,preset_plan=request('POST',base+'/experiments/'+preset['id']+'/plans',{})
    assert status==201,preset_plan
    body={'workflow':'__composition__','draft':{'graph':{'nodes':nodes,'edges':[]},'parameters':workflow.get('defaults',{}),'variant_parameters':values,'include_smoke_test':True}}
    status,exp=request('POST',base+'/experiments',body)
    assert status==201,exp
    status,plan=request('POST',base+'/experiments/'+exp['id']+'/plans',{})
    assert status==201,plan
    def identities(value):
        return [(stage['variant_id'],stage['stage_id'],stage['operation'],stage['parameters'],stage['resources'],stage['purpose']) for stage in value['stages']]
    assert identities(plan)==identities(preset_plan)
    assert plan['source']['digest']==preset_plan['source']['digest']
    status,execution=request('POST',base+'/plans/'+plan['id']+'/dispatch',{'idempotency_key':'composed-real-project'})
    assert status==202,execution
    worker.tick('fixture')
    finished=store.read('fixture','execution',execution['id'])
    assert finished['state']=='completed',finished
    artifacts=store.listing('fixture','artifact')
    assert len(artifacts)==4 and all(a['purpose']=='smoke-test' and a['complete'] for a in artifacts)
    assert {a['parameters']['token_cap'] for a in artifacts}=={128,256}
    assert {s['variant_id'] for s in plan['stages']}=={a['variant_id'] for a in artifacts}


def test_cycle_and_explicit_collector_are_rejected(composed):
    root, manifest, config = composed
    manifest['operations']['collect']['input_ports'] = {'report': {'schema':'report','version':1,'cardinality':'one'}}
    config['graph']['edges'].append({'from_node':'analysis','output':'report','to_node':'collection','input':'report'})
    write_manifest(root,manifest)
    checked=check_configuration(root,load_connection(root),config)
    assert not checked['valid'] and 'cycle' in json.dumps(checked['errors'])
    config['graph']['edges'].pop();manifest['operations']['collect']['input_ports']={}
    manifest['metrics']['instrument']={'collector':'instrument-op','source_field':'measurement','unit':'count'}
    config['metrics']=['instrument']
    write_manifest(root,manifest)
    checked=check_configuration(root,load_connection(root),config)
    assert not checked['valid'] and 'explicitly added collector' in json.dumps(checked['errors'])


def test_saved_complete_artifact_binding_freezes_identity(composed):
    import hashlib
    root, manifest, config=composed
    file=root/'prior.json';file.write_text('immutable prior output')
    artifact={'id':'saved','path':'prior.json','output_dir':'.','schema':'records','version':1,'purpose':'experiment','complete':True,'source_digest':'source','execution_id':'old',
              'files':[{'path':'prior.json','sha256':hashlib.sha256(file.read_bytes()).hexdigest()}]}
    config['graph']['nodes']=[config['graph']['nodes'][1]]
    config['graph']['edges']=[{'artifact_id':'saved','to_node':'analysis','input':'corpus'}]
    config['variant_parameters']={}
    plan=compile_plan(root,load_connection(root),config,'selected',None,[artifact])
    assert len(plan['stages'])==1 and plan['artifacts'][0]['id']=='saved'
    assert plan['stages'][0]['artifact_inputs']==[{'input':'corpus','artifact_id':'saved'}]
    assert 'prior.json' in plan['artifacts'][0]['files'][0]['path']


def test_many_saved_bindings_keep_exact_selected_members(composed):
    import hashlib
    root,manifest,config=composed
    manifest['operations']['analyze']['argv']=['python3','science/runner.py',{'context':'output_dir'},{'context':'input:corpus'}]
    write_manifest(root,manifest)
    artifacts=[]
    for identity in ['one','two']:
        path=root/(identity+'.json');path.write_text(identity)
        artifacts.append({'id':identity,'path':path.name,'schema':'records','version':1,'purpose':'experiment','complete':True,'source_digest':'source','execution_id':'old',
                          'files':[{'path':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}]})
    config['graph']['nodes']=[config['graph']['nodes'][1]]
    config['graph']['edges']=[{'artifact_id':a['id'],'to_node':'analysis','input':'corpus'} for a in artifacts]
    config['variant_parameters']={}
    plan=compile_plan(root,load_connection(root),config,'selected-many',artifacts=artifacts)
    inputs=json.loads(plan['stages'][0]['argv'][-1])
    assert inputs==['__UNITY_PROJECT_ROOT__/one.json','__UNITY_PROJECT_ROOT__/two.json']
    assert [a['id'] for a in plan['artifacts']]==['one','two']


def test_choice_output_is_bounded_before_parsing(composed):
    root,manifest,_=composed
    manifest['choice_readers']={'oversized':{'argv':['python3','-c','print("x" * 2200000)']}}
    manifest['parameters']['model']['choices_reader']='oversized'
    write_manifest(root,manifest)
    conn=load_connection(root)
    assert not conn['valid'] and '2 MiB limit' in json.dumps(conn['errors'])


def test_node_parameter_cannot_bypass_purpose_guard(composed):
    root,manifest,config=composed
    manifest['parameters']['restricted']={'type':'boolean','default':False,'allowed_purposes':['smoke-test']}
    manifest['operations']['collect']['argv'].append({'param':'restricted'})
    config['graph']['nodes'][0]['parameters']={'restricted':True}
    write_manifest(root,manifest)
    checked=check_configuration(root,load_connection(root),config)
    assert not checked['valid'] and 'not permitted for this stage purpose' in json.dumps(checked['errors'])


def test_reducer_port_limit_sums_all_expanded_bindings(composed):
    root,manifest,config=composed
    second=copy.deepcopy(config['graph']['nodes'][0]);second['id']='second-collection';config['graph']['nodes'].insert(1,second)
    config['graph']['edges'].append({'from_node':'second-collection','output':'corpus','to_node':'analysis','input':'corpus'})
    manifest['composition_limits']={'artifacts_per_port':6}
    write_manifest(root,manifest)
    checked=check_configuration(root,load_connection(root),config)
    assert not checked['valid'] and 'across all bindings' in json.dumps(checked['errors'])
