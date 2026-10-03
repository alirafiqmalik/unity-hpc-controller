"""Research context survives migration, edits, unavailable declarations and conflicts."""
import json

import pytest

from controller import workspace_overview as overview, workspace_store as store
from tests.test_workspace_settings import project


def test_manifest_question_save_clear_and_conflict(project):
    assert overview.context('demo')['question'] == 'Original question'
    saved = overview.update_context('demo', {'expected_version': 0, 'question': '', 'hypothesis': 'human hypothesis'})
    assert saved['version'] == 1
    path = project / 'unityHPC/project.json'
    manifest = json.loads(path.read_text()); manifest['research_question'] = 'Changed declared question'; path.write_text(json.dumps(manifest))
    assert overview.context('demo')['question'] == ''
    with pytest.raises(store.Conflict):
        overview.update_context('demo', {'expected_version': 0, 'question': 'conflicting text'})
    path.unlink()
    assert overview.overview('demo')['research_context']['hypothesis'] == 'human hypothesis'


def test_zeroes_attention_purpose_and_failed_complete_evidence(project):
    empty = overview.overview('demo')
    assert empty['counts']['runs']['active']['value'] == 0
    with store.transaction('demo') as con:
        store.put(con, 'execution', {'id': 'run', 'state': 'paused', 'stages': [{'id': 'smoke', 'purpose': 'smoke-test', 'state': 'failed'}, {'id': 'collect', 'purpose': 'experiment', 'state': 'blocked'}]})
        store.put(con, 'artifact', {'id': 'complete-behind-failure', 'execution_id': 'run', 'purpose': 'experiment', 'complete': True})
    data = overview.overview('demo')
    assert data['counts']['runs']['needs_attention']['value'] == 1
    assert data['counts']['results']['incomplete']['value'] == 0
    smoke = next(a for a in data['attention'] if a['purpose'] == 'smoke-test')
    overview.acknowledge('demo', {'observation_id': smoke['id']})
    assert smoke['id'] not in {a['id'] for a in overview.overview('demo')['attention']}
    assert store.read('demo', 'execution', 'run')['stages'][0]['state'] == 'failed'


def test_human_note_without_evidence_is_allowed(project):
    note = overview.save_evidence('demo', 'note', {'expected_version': 0, 'text': 'A human conclusion', 'evidence': []})
    assert note['actor'] == 'local operator'
    assert overview.overview('demo')['notes'][0]['text'] == 'A human conclusion'


def test_failed_result_index_does_not_hide_question_or_runs(project, monkeypatch):
    original = store.listing
    def unavailable(slug, kind):
        if kind == 'artifact':
            raise store.WorkspaceError('Index temporarily unavailable')
        return original(slug, kind)
    monkeypatch.setattr(store, 'listing', unavailable)
    result = overview.overview('demo')
    assert result['research_context']['question'] == 'Original question'
    assert result['counts']['runs']['active']['value'] == 0
    assert result['counts']['results']['incomplete']['value'] is None
    assert result['sections']['results']['availability'] == 'unavailable'


def test_report_currency_matches_results_without_changing_old_pin(project):
    from controller import workspace_results as results
    with store.transaction('demo') as con:
        store.put(con,'artifact',{'id':'input-old','purpose':'experiment','complete':True,'content_version':'v1'})
        store.put(con,'plan',{'id':'analysis-plan','kind':'analysis','artifact_ids':['input-old'],'analysis_revision':1})
        store.put(con,'execution',{'id':'analysis-run','plan_id':'analysis-plan','state':'completed','stages':[],'scheduler_observation':None})
        store.put(con,'artifact',{'id':'report-old','execution_id':'analysis-run','output_id':'report','purpose':'experiment','complete':True,'content_version':'r1'})
    pin=overview.save_evidence('demo','pin',{'expected_version':0,'reference':{'kind':'artifact','id':'report-old'},'label':'Original report'})
    assert overview.overview('demo')['counts']['results']['current_reports']['value']==1
    with store.transaction('demo') as con:
        store.put(con,'artifact',{'id':'input-new','purpose':'experiment','complete':True,'content_version':'v2','supersedes':'input-old'})
    data=overview.overview('demo')
    assert data['counts']['results']['current_reports']['value']==0
    assert data['counts']['results']['stale_reports']['value']==1
    assert results.query('demo',{'currency':'newer-inputs'})['total']==1
    assert data['pins'][0]['evidence']==pin['evidence']
