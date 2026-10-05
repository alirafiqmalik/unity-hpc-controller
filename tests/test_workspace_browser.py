"""Real browser checks against a deterministic HTTP fixture; no dispatcher or SSH."""
import copy
import json
import os
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest

from tests.cdp import Browser, find_chrome

DIST = Path(os.environ.get("UNITY_HPC_TEST_UI_DIR", Path(__file__).resolve().parents[1] / "controller/web/dist"))
pytestmark = pytest.mark.skipif(find_chrome() is None or not (DIST / 'index.html').exists(),
                                reason='requires built dashboard and Chrome')


@pytest.fixture
def workspace_browser_server():
    draft = {'name': 'Token cap comparison', 'workflow': 't1', 'parameters': {'model': 'small', 'token_cap': 64},
             'variant_parameters': {}, 'metrics': ['success'], 'include_smoke_test': False}
    experiment = {'id': 'exp-one', 'name': draft['name'], 'workflow': 't1', 'archived': False,
                  'draft': draft, 'version': 1, 'revision': 1, 'executions': [], 'updated_at': '2026-10-03'}
    manifest = {'schema_version': 1, 'application': 'ml', 'default_primitive': 'multi-gpu',
                'default_mode': 'independent', 'research_question': 'Does token budget change outcomes?',
                'parameters': {'model': {'type': 'string', 'default': 'small', 'choices': ['small', 'large'], 'variant_eligible': True},
                               'token_cap': {'type': 'integer', 'min': 1, 'max': 1024, 'default': 64, 'variant_eligible': True}},
                'operations': {'collect': {'location': 'cluster'}},
                'workflows': {'t1': {'title': 'T1 corpus', 'parameters': ['model', 'token_cap'], 'metrics': ['success'],
                                    'stages': [{'id': 'collect', 'operation': 'collect', 'purpose': 'experiment', 'resources': {'primitive': 'multi-gpu', 'mode': 'independent'}}]}},
                'metrics': {'success': {'source_field': 'correct', 'unit': 'fraction', 'definition': 'Correct records / completed records', 'denominator': 'Completed records'}}}
    plan = {'id': 'plan-one', 'valid': True, 'experiment_id': 'exp-one', 'revision': 1, 'config': draft,
            'source': {'digest': 'source-sha256', 'files': {'runner.py': 'runner-sha256'}},
            'variants': [{'id': 'v-one', 'parameters': draft['parameters']}], 'excluded_variants': [],
            'metrics': [manifest['metrics']['success']], 'checks': {'valid': True},
            'stages': [{'id': 'v-one:collect', 'stage_id': 'collect', 'variant_id': 'v-one', 'purpose': 'experiment',
                        'location': 'cluster', 'depends_on': [], 'resources': {'primitive': 'multi-gpu', 'mode': 'independent'},
                        'output_dir': '.unity-workspace/outputs/plan-one', 'outputs': [], 'argv': ['python', 'runner.py'],
                        'script': '#!/bin/bash\npython runner.py', 'script_path': 'collect.sh'}]}
    execution = {'id': 'execution-one', 'experiment_id': 'exp-one', 'revision': 1, 'plan_id': 'plan-one', 'state': 'partial',
                 'stages': [{'id': 'v-one:smoke', 'purpose': 'smoke-test', 'state': 'failed', 'attempts': [], 'job_ids': ['41'], 'error': 'Fixture failure'},
                            {'id': 'v-one:collect', 'purpose': 'experiment', 'state': 'blocked', 'attempts': [], 'job_ids': []}]}
    state = {'experiment': experiment, 'manifest': manifest, 'plan': plan, 'execution': execution,
             'requests': [], 'conflict': False, 'executions': [], 'artifacts': []}
    project = {'slug': 'demo', 'path': '/fixture/demo', 'primitive': 'multi-gpu'}

    def projected_executions():
        items = copy.deepcopy(state['executions'])
        for item in items:
            observed = item.get('scheduler_observation') or {}
            item.update(has_scheduler_work=any(s.get('location', 'cluster') == 'cluster' for s in item['stages']), version=1, summary='needs-attention', active_count=0, attention_count=1,
                        collections=['unknown'], uncertain_count=0,
                        freshness={'scheduler': {'state': 'stale', 'observed_at': observed.get('checked_at'), 'error': observed.get('error')}},
                        updated_at='2026-10-03T12:00:00Z')
            for stage in item['stages']:
                stage.setdefault('attempts', [])
                if not stage['attempts']:
                    stage['attempts'] = [{'id': stage['id'].replace(':', '-') + '-attempt', 'number': 1, 'state': stage['state'], 'job_ids': stage.get('job_ids', [])}]
                stage.update(lifecycle=stage['state'], submission=stage['state'], completeness='unknown', retrieval=stage.get('fetch_state', 'not_requested'))
                # Match workspace_runs.project_execution's required read-model fields.
                for key, value in {'collections': ['unknown'], 'declared_stage_id': 'collect', 'depends_on': [], 'jobs': [], 'artifacts': [], 'resources': {}, 'operation': 'collect', 'output_dir': 'output', 'location': 'cluster', 'stage_id': 'collect'}.items():
                    stage.setdefault(key, value)
                stage['allowed_actions'] = {kind: {'supported': False, 'reason': 'Fixture capability unavailable'} for kind in ('cancel', 'pending-change')}
        return items

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(DIST), **kwargs)

        def log_message(self, *_args):
            pass

        def answer(self, payload, status=200):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            route = urlparse(self.path).path
            if not route.startswith('/api/'):
                if not route.startswith('/assets/'):
                    self.path = '/index.html'
                return super().do_GET()
            payload = {}
            if route.endswith('/workspace/connection'):
                payload = {'valid': True, 'errors': [], 'manifest': state['manifest']}
            elif route.endswith('/workspace/experiments'):
                payload = {'experiments': [state['experiment']]}
            elif route.endswith('/workspace/experiments/exp-one'):
                payload = state['experiment']
            elif route.endswith('/workspace/plans/plan-one'):
                payload = state['plan']
            elif route.endswith('/workspace/executions'):
                payload = {'executions': projected_executions()}
            elif route.endswith('/workspace/queue'):
                payload = {'jobs': []}
            elif route.endswith('/workspace/overview'):
                payload = {'research_context': {'question': manifest['research_question'], 'hypothesis': '', 'version': 1, 'origin': 'declaration'}, 'counts': {'experiments': {}, 'runs': {}, 'results': {}}, 'attention': [], 'continuations': [], 'activity': [], 'activity_cursor': None, 'sections': {}, 'pins': [], 'notes': []}
            elif route.endswith('/workspace/artifacts'):
                payload = {'artifacts': state['artifacts']}
            elif route.endswith('/logs'):
                payload = {'purpose': 'smoke-test', 'text': 'Fixture failure', 'stage_id': 'v-one:smoke', 'stream_id': 'fixture-attempt:stdout', 'availability': 'available', 'encoding': 'utf-8', 'offset': 0, 'next_offset': 15, 'freshness': {'state': 'fresh'}}
            elif route == '/api/v1/projects/demo':
                payload = {'project': project}
            elif route == '/api/v1/projects':
                payload = {'projects': [project]}
            elif route == '/api/v1/jobs':
                payload = {'jobs': [{'job_id': '41', 'slug': 'demo', 'purpose': 'smoke-test', 'status': 'FAILED'},
                                    {'job_id': '42', 'slug': 'demo', 'status': 'COMPLETED'}]}
            elif route == '/api/v1/events':
                payload = {'events': []}
            return self.answer(payload)

        def do_PATCH(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['requests'].append(('PATCH', self.path, body))
            if state['conflict']:
                return self.answer({'error': 'Draft version conflict: another editor saved version 2'}, 409)
            assert body['expected_version'] == state['experiment']['version']
            state['experiment']['draft'] = body['draft']
            state['experiment']['name'] = body['draft'].get('name', state['experiment']['name'])
            state['experiment']['version'] += 1
            return self.answer(state['experiment'])

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['requests'].append(('POST', self.path, body))
            if self.path.endswith('/check'):
                return self.answer({'valid': True, 'errors': [], 'checks': [], 'variants': state['plan']['variants']})
            if self.path.endswith('/plans'):
                state['plan']['config'] = copy.deepcopy(state['experiment']['draft'])
                return self.answer(state['plan'])
            if self.path.endswith('/dispatch'):
                assert body == {'idempotency_key': 'review:plan-one'}
                state['executions'] = [state['execution']]
                return self.answer(state['execution'])
            if self.path.endswith('/archive') or self.path.endswith('/restore'):
                state['experiment']['archived'] = self.path.endswith('/archive')
                return self.answer(state['experiment'])
            if self.path.endswith('/fetch'):
                return self.answer(state['execution'])
            return self.answer({'error': 'Unexpected fixture action'}, 400)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_address[1]}', state
    finally:
        server.shutdown()
        server.server_close()


def click(browser, label):
    browser.eval(f"[...document.querySelectorAll('button')].find(b => b.textContent.trim() === {json.dumps(label)}).click()")
    time.sleep(.15)


def fill(browser, label, value):
    browser.eval(f"""(() => {{
      const node=document.querySelector('[aria-label={json.dumps(label)}]');
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(node,{json.dumps(value)});
      node.dispatchEvent(new Event('input',{{bubbles:true}}));
    }})()""")


def capture_browser_errors(browser):
    browser.call('Page.addScriptToEvaluateOnNewDocument', source="window.__workspaceErrors=[];addEventListener('error',event=>window.__workspaceErrors.push(event.error?.stack || event.message));")


def test_routes_autosave_exact_review_dispatch_purpose_and_conflict(workspace_browser_server):
    url, state = workspace_browser_server
    with Browser(width=1400, height=1000) as browser:
        capture_browser_errors(browser)
        browser.goto(url + '/jobs/project?search=demo', settle=1)
        browser.eval("document.querySelector('[aria-label=\"Open project demo\"]').click()")
        time.sleep(.3)
        assert browser.eval('location.pathname') == '/projects/demo/overview'
        assert browser.eval("document.querySelector('h1').textContent") == 'Overview'
        assert browser.eval("document.querySelector('[aria-label=\"Home — Projects\"]').getAttribute('href')") == '/jobs/project?search=demo'
        assert browser.eval("document.querySelector('nav').textContent.includes('Job Monitor')") is False
        assert 'Does token budget' in browser.eval('document.body.textContent')
        browser.goto(url + '/projects/demo/experiments/exp-one', settle=.6)
        assert browser.eval("[...document.querySelectorAll('button')].some(b => b.textContent === 'Dispatch this plan')") is False
        fill(browser, 'Name', 'Changed study')
        time.sleep(.9)
        assert state['experiment']['draft']['name'] == 'Changed study'
        assert browser.eval("document.querySelector('[data-testid=autosave-status]').textContent") == 'Saved'
        assert len(state['requests']) == 1  # Autosave did not run checks or dispatch.
        click(browser, 'Check setup')
        click(browser, 'Review plan')
        time.sleep(.25)
        assert browser.eval('location.pathname') == '/projects/demo/review/plan-one'
        assert 'source-sha256' in browser.eval('document.body.textContent')
        assert browser.eval("[...document.querySelectorAll('button')].find(b => b.textContent==='Dispatch this plan').disabled")
        browser.eval("document.querySelector('input[type=checkbox]').click()")
        click(browser, 'Dispatch this plan')
        time.sleep(.3)
        assert browser.eval('location.pathname + location.search') == '/projects/demo/runs?execution=execution-one'
        assert browser.eval('window.__workspaceErrors') == []
        assert 'Smoke test' in browser.eval('document.body.textContent')
        assert 'blocked' in browser.eval('document.body.textContent')
        browser.eval("document.querySelector('tbody details').open=true")
        click(browser, 'Logs: attempt 1')
        assert 'Smoke test' in browser.eval("document.querySelector('[aria-label=\"Logs for v-one-smoke-attempt\"]').textContent")
        browser.eval("document.querySelector('[aria-label=\"Home — Projects\"]').click()")
        time.sleep(.2)
        assert browser.eval('location.pathname + location.search') == '/jobs/project?search=demo'
        browser.goto(url + '/projects/demo/experiments/exp-one', settle=.5)
        state['conflict'] = True
        fill(browser, 'Name', 'Unsaved edits survive')
        time.sleep(.9)
        assert browser.eval("document.querySelector('[aria-label=Name]').value") == 'Unsaved edits survive'
        assert browser.eval("document.querySelector('[data-testid=autosave-status]').textContent") == 'Unsaved'
        assert 'version conflict' in browser.eval('document.body.textContent')
        assert state['experiment']['draft']['name'] == 'Changed study'
        browser.call('Emulation.setDeviceMetricsOverride', width=390, height=844, deviceScaleFactor=1, mobile=True)
        assert browser.eval('document.documentElement.scrollWidth <= innerWidth') is True


def test_archive_preserves_history_and_global_purpose_filter(workspace_browser_server):
    url, state = workspace_browser_server
    state['experiment']['executions'] = ['execution-one']
    with Browser() as browser:
        browser.goto(url + '/projects/demo/experiments', settle=.6)
        assert 'Repeat' in browser.eval('document.body.textContent')
        assert 'Delete unused draft' not in browser.eval('document.body.textContent')
        click(browser, 'Archive')
        assert state['experiment']['archived']
        assert 'Token cap comparison' not in browser.eval('document.body.textContent')
        browser.eval("""(() => {
          const select = document.querySelector('[aria-label="Archive filter"]');
          select.value = 'archived'; select.dispatchEvent(new Event('change', {bubbles:true}));
        })()""")
        time.sleep(.1)
        click(browser, 'Restore')
        assert not state['experiment']['archived']
        assert state['experiment']['executions'] == ['execution-one']
        browser.goto(url + '/jobs/monitor', settle=.5)
        assert 'Unclassified' in browser.eval('document.body.textContent')
        browser.eval("""(() => {
          const select = document.querySelector('[aria-label="Purpose"]');
          select.value = 'smoke-test'; select.dispatchEvent(new Event('change', {bubbles:true}));
        })()""")
        time.sleep(.1)
        assert 'Unclassified' not in browser.eval('document.body.textContent')
        assert browser.eval('document.querySelector("tbody").textContent.includes("Smoke test")')


def test_prerequisites_are_bound_to_each_checked_variant(workspace_browser_server):
    url, state = workspace_browser_server
    state['experiment']['draft']['prerequisites'] = 'existing'
    state['plan']['variants'] = [
        {'id': 'v-small-64', 'parameters': {'model': 'small', 'token_cap': 64}},
        {'id': 'v-small-128', 'parameters': {'model': 'small', 'token_cap': 128}},
    ]
    state['artifacts'] = [
        {'id': 'corpus-64', 'path': 'saved/64', 'purpose': 'experiment', 'complete': True},
        {'id': 'corpus-128', 'path': 'saved/128', 'purpose': 'experiment', 'complete': True},
        {'id': 'smoke', 'path': 'saved/smoke', 'purpose': 'smoke-test', 'complete': True},
    ]
    with Browser() as browser:
        browser.goto(url + '/projects/demo/experiments/exp-one', settle=.6)
        click(browser, 'Check setup')
        browser.eval("""(() => {
          const select=document.querySelector('[aria-label="v-small-64:collect existing artifact"]');
          select.value='corpus-64';select.dispatchEvent(new Event('change',{bubbles:true}));
        })()""")
        time.sleep(.85)
        browser.eval("""(() => {
          const select=document.querySelector('[aria-label="v-small-128:collect existing artifact"]');
          select.value='corpus-128';select.dispatchEvent(new Event('change',{bubbles:true}));
        })()""")
        time.sleep(.85)
        assert state['experiment']['draft']['existing_artifacts'] == {
            'v-small-64:collect': 'corpus-64', 'v-small-128:collect': 'corpus-128'}
        assert not browser.eval("document.querySelector('[aria-label=\"v-small-64:collect existing artifact\"]').textContent.includes('saved/smoke')")
        assert browser.eval("[...document.querySelectorAll('button')].find(b=>b.textContent==='Review plan').disabled")


def test_runs_scheduler_observation_integrity_and_scoped_retrieval(workspace_browser_server):
    url, state = workspace_browser_server
    execution = state['execution']
    execution['scheduler_observation'] = {
        'checked_at': '2026-10-03T12:00:00Z', 'error': 'Fixture scheduler unavailable'}
    execution['stages'][0].update(location='cluster', fetch_state='complete',
                                  resume_from='saved/checkpoint-64',
                                  jobs=[{'job_id': '41', 'status': 'FAILED'}])
    execution['stages'][1]['waiting_reason'] = 'Prerequisite requires human review'
    execution['stages'].extend([
        {'id': 'v-two:collect', 'purpose': 'experiment', 'location': 'cluster',
         'state': 'accepted', 'job_ids': ['43'], 'jobs': [{'job_id': '43', 'status': 'RUNNING'}]},
        {'id': 'v-old:collect', 'purpose': 'experiment', 'state': 'superseded',
         'continued_by': 'recovery-one', 'job_ids': []},
    ])
    state['executions'] = [execution]
    with Browser() as browser:
        capture_browser_errors(browser)
        browser.goto(url + '/projects/demo/runs?execution=execution-one', settle=.6)
        assert browser.eval('window.__workspaceErrors') == []
        content = browser.eval('document.body.textContent')
        assert 'Observed 2026-10-03T12:00:00Z' in content
        assert 'Fixture scheduler unavailable' in content
        assert 'Scheduler: stale' in content
        assert '#43: RUNNING' in content and 'accepted' in content
        assert 'Prerequisite requires human review' in content
        assert 'Resumed from: saved/checkpoint-64' in content
        assert browser.eval("document.querySelector('a[href=\"/projects/demo/runs?execution=recovery-one\"]').textContent") == 'Continuation'
        # A failed cluster stage can retrieve stranded outputs even after a completed fetch.
        browser.eval("document.querySelector('[aria-label=\"Select v-one:smoke\"]').click()")
        click(browser, 'Retrieve selected outputs')
        assert state['requests'][-1] == (
            'POST', '/api/v1/projects/demo/workspace/executions/execution-one/fetch',
            {'stage_ids': ['v-one:smoke']})
        execution['integrity_error'] = [{'field': 'source', 'message': 'Reviewed runner changed'}]
        browser.goto(url + '/projects/demo/runs?execution=execution-one', settle=.6)
        assert 'Execution paused: approved files changed' in browser.eval('document.body.textContent')
        assert 'Reviewed runner changed' in browser.eval('document.body.textContent')
        for label in ('Retrieve selected outputs', 'Review retry', 'Reconcile submission'):
            assert browser.eval(f"[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==={json.dumps(label)}).disabled")
        assert not browser.eval("[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='Logs: attempt 1').disabled")
