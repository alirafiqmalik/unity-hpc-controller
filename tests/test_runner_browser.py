"""Guided runner and bounded documentation against an isolated real controller."""
import threading
import time
from http.server import ThreadingHTTPServer

import pytest

from controller import http, workspace_store as store, workspace_worker as worker
from tests.cdp import Browser, find_chrome
from test_workspace_api import project  # noqa: F401
from test_genai import native_project  # noqa: F401

pytestmark = pytest.mark.skipif(find_chrome() is None or not (http.UI_DIR / 'index.html').is_file(),
                                reason='requires Chrome and a built dashboard')


@pytest.fixture
def runner_server(project, monkeypatch):
    from controller.serve import Handler

    def forbidden(*args, **kwargs):
        raise AssertionError('Runner browser fixture attempted cluster access')

    monkeypatch.setattr(worker.transport, 'submit', forbidden)
    monkeypatch.setattr(worker.transport, 'stage_bundle', forbidden)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f'http://127.0.0.1:{server.server_address[1]}', project
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def genai_server(native_project, monkeypatch):
    from controller.serve import Handler

    def forbidden(*args, **kwargs):
        raise AssertionError('Evaluation browser fixture attempted cluster access')

    monkeypatch.setattr(worker.transport, 'submit', forbidden)
    monkeypatch.setattr(worker.transport, 'stage_bundle', forbidden)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f'http://127.0.0.1:{server.server_address[1]}'
    finally:
        server.shutdown()
        server.server_close()


def wait_for(browser, expression, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if browser.eval(expression):
            return
        time.sleep(.05)
    raise AssertionError(browser.eval('document.body.innerText'))


def click(browser, label):
    import json
    browser.eval(f"[...document.querySelectorAll('button')].find(b => b.textContent.trim() === {json.dumps(label)}).click()")


def test_workflow_setup_review_approval_and_execution_evidence(runner_server):
    url, root = runner_server
    with Browser(width=1400, height=1000) as browser:
        browser.call('Page.addScriptToEvaluateOnNewDocument', source="window.__runnerErrors=[];addEventListener('error',e=>window.__runnerErrors.push(e.message));addEventListener('unhandledrejection',e=>window.__runnerErrors.push(String(e.reason)))")
        browser.goto(url + '/projects/demo', settle=.5)
        wait_for(browser, "location.pathname === '/projects/demo/runner' && !!document.querySelector('[aria-label=\"Workflow\"]')")
        assert store.listing('demo', 'experiment') == []
        assert 'Check setup and review' in browser.eval('document.body.innerText')
        assert not browser.eval("[...document.querySelectorAll('button')].some(b => b.textContent === 'Continue')")
        click(browser, 'Check setup and review')
        wait_for(browser, "[...document.querySelectorAll('button')].some(b=>b.textContent==='Approve run' && !b.disabled)")
        assert store.listing('demo', 'execution') == []
        assert 'Source digest' in browser.eval('document.body.innerText')
        click(browser, 'Approve run')
        wait_for(browser, "location.pathname.includes('/executions/') && document.body.innerText.includes('Inspect frozen plan')")
        execution = store.listing('demo', 'execution')[0]
        (root / 'science.py').write_text('raise Exception("must use approved source")')
        worker.tick('demo')
        wait_for(browser, "document.body.innerText.includes('Artifacts') && document.body.innerText.includes('Complete')")
        assert store.read('demo', 'execution', execution['id'])['state'] == 'completed'
        browser.eval("[...document.querySelectorAll('button')].find(b=>b.textContent.startsWith('Logs:')).click()")
        wait_for(browser, "!!document.querySelector('[aria-label=\"Log stream\"]')")
        assert browser.eval('window.__runnerErrors') == []
        browser.goto(url + '/projects/demo', settle=.3)
        wait_for(browser, "location.pathname === '/projects/demo/executions'")
        wait_for(browser, "document.body.innerText.includes('succeeded')")
        browser.call('Emulation.setDeviceMetricsOverride', width=390, height=844, deviceScaleFactor=1, mobile=True)
        assert browser.eval('document.documentElement.scrollWidth <= innerWidth')


def test_document_view_is_bounded_escaped_and_passive(runner_server):
    url, root = runner_server
    (root / 'README.md').write_text('# Declared documentation\n<script>window.documentExecuted=true</script>\n[unsafe](javascript:alert(1))\n')
    before = {kind: store.listing('demo', kind) for kind in ('experiment', 'plan', 'execution')}
    with Browser() as browser:
        browser.goto(url + '/projects/demo/docs', settle=.4)
        wait_for(browser, "document.body.innerText.includes('Declared documentation')")
        assert browser.eval('window.documentExecuted === undefined')
        assert browser.eval("!document.querySelector('a[href^=\"javascript:\"]')")
        assert 'loaded bytes' in browser.eval('document.body.innerText')
    assert before == {kind: store.listing('demo', kind) for kind in before}


def test_genai_setup_preserves_dataset_binding_and_requires_visible_approval(genai_server):
    with Browser(width=1400, height=1000) as browser:
        browser.goto(genai_server + '/projects/native/evaluations?new=1', settle=.5)
        wait_for(browser, "!!document.querySelector('[aria-label=\"Evaluation workflow\"]')")
        browser.eval("const select = document.querySelector('[aria-label=\"Evaluation workflow\"]'); select.value='evaluate-smoke'; select.dispatchEvent(new Event('change',{bubbles:true}));")
        wait_for(browser, "[...document.querySelectorAll('dialog label')].some(label => label.textContent === 'example' && label.querySelector('input').checked)")
        click(browser, 'Review evaluation matrix')
        wait_for(browser, "document.querySelector('dialog').textContent.includes('Exact frozen plan and checks')")
        assert store.listing('native', 'execution') == []
        plan = store.listing('native', 'plan')[0]
        assert plan['config']['parameters']['dataset'] == 'example'
        click(browser, 'Edit setup')
        wait_for(browser, "document.querySelector('[aria-label=\"Evaluation workflow\"]').value === 'evaluate-smoke'")
        click(browser, 'Review evaluation matrix')
        wait_for(browser, "document.querySelector('dialog').textContent.includes('Exact frozen plan and checks')")
        assert store.listing('native', 'execution') == []
        click(browser, 'Launch evaluations')
        wait_for(browser, "!document.querySelector('dialog')")
        assert len(store.listing('native', 'execution')) == 1


def test_legacy_log_tail_fallback_is_explicit_scoped_and_not_paginated(runner_server, monkeypatch):
    from controller import dispatch, workspace, workspace_runs as runs
    url, root = runner_server
    stage = {'id': 'legacy', 'operation': 'evaluate', 'location': 'cluster', 'state': 'accepted',
             'purpose': 'research', 'job_ids': ['123'],
             'attempts': [{'id': 'attempt-legacy', 'exp': 'legacy', 'state': 'accepted', 'job_ids': ['123']}]}
    execution = {'id': 'plan-legacy', 'plan_id': 'plan-legacy', 'campaign': 'plan-legacy',
                 'state': 'active', 'stages': [stage]}
    with store.transaction('demo') as db:
        store.put(db, 'plan', {'id': execution['id'], 'stages': [stage]})
        store.put(db, 'execution', execution)
    monkeypatch.setattr(runs.campaign, 'jobs', lambda *args: [{'job_id': '123', 'status': 'RUNNING'}])
    error = ['Reviewed dispatcher lacks exact bounded log transport.']
    def unsupported(*args, **kwargs):
        raise store.Conflict(error[0])
    monkeypatch.setattr(runs, '_remote_transport', unsupported)
    calls = []
    tail_output = ['stdout progress\nstderr warning']
    def transport(rec, argv, **kwargs):
        calls.append(argv)
        return {'ok': True, 'output': tail_output[0]}
    monkeypatch.setattr(dispatch, '_run', transport)
    with Browser(width=1300, height=850) as browser:
        browser.goto(url + '/projects/demo/executions/plan-legacy', settle=.3)
        wait_for(browser, "[...document.querySelectorAll('button')].some(b=>b.textContent.startsWith('Logs:'))")
        browser.eval("[...document.querySelectorAll('button')].find(b=>b.textContent.startsWith('Logs:')).click()")
        wait_for(browser, "document.body.innerText.includes('stdout progress') && document.body.innerText.includes('stderr warning')")
        assert browser.eval("document.body.innerText.includes('Latest tail · stdout + stderr · last 100 lines per stream')")
        assert browser.eval("[...document.querySelectorAll('button')].find(b=>b.textContent==='Next bounded page').disabled")
        assert calls == [['logs', '--campaign', 'plan-legacy', '--job', '123', '-n', '100']]
        tail_output[0] = 'x' * 100000
        click(browser, 'Refresh logs')
        wait_for(browser, "document.body.innerText.includes('display truncated to the latest 64 KiB')")
        assert browser.eval("document.querySelector('pre').textContent.length") == 65536
        before_failure = len(calls)
        error[0] = 'Remote network timeout'
        click(browser, 'Refresh logs')
        wait_for(browser, "document.body.innerText.includes('Remote network timeout')")
        assert not browser.eval("document.body.innerText.includes('stdout progress')")
        assert len(calls) == before_failure
        # A multi-attempt stage cannot safely use a stage-wide legacy tail.
        stage['attempts'].append({'id': 'attempt-other', 'exp': 'other', 'state': 'accepted', 'job_ids': ['123']})
        with store.transaction('demo') as db:
            store.put(db, 'execution', execution)
        error[0] = 'Reviewed dispatcher lacks exact bounded log transport.'
        browser.goto(url + '/projects/demo/executions/plan-legacy', settle=.3)
        wait_for(browser, "[...document.querySelectorAll('button')].some(b=>b.textContent.startsWith('Logs: attempt-legacy'))")
        browser.eval("[...document.querySelectorAll('button')].find(b=>b.textContent.startsWith('Logs: attempt-legacy')).click()")
        wait_for(browser, "document.body.innerText.includes('Reviewed dispatcher lacks exact bounded log transport')")
        assert len(calls) == before_failure

        # Reject an unexpected identity in the legacy response itself.
        stage['attempts'] = stage['attempts'][:1]
        with store.transaction('demo') as db:
            store.put(db, 'execution', execution)
        monkeypatch.setattr(workspace, 'execution_logs', lambda *args: {
            'stages': [{'id': 'other-stage', 'job_ids': ['999'], 'output': 'sibling must not leak'}]})
        browser.goto(url + '/projects/demo/executions/plan-legacy', settle=.3)
        wait_for(browser, "[...document.querySelectorAll('button')].some(b=>b.textContent.startsWith('Logs: attempt-legacy'))")
        browser.eval("[...document.querySelectorAll('button')].find(b=>b.textContent.startsWith('Logs: attempt-legacy')).click()")
        wait_for(browser, "document.body.innerText.includes('Legacy log identity changed')")
        assert not browser.eval("document.body.innerText.includes('sibling must not leak')")
