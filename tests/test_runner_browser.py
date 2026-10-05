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
        wait_for(browser, "document.querySelector('[aria-label=\"Evaluation dataset\"]').value === 'example'")
        click(browser, 'Check setup and review')
        wait_for(browser, "location.pathname === '/projects/native/runner' && [...document.querySelectorAll('button')].some(b => b.textContent === 'Approve run' && !b.disabled)")
        assert store.listing('native', 'execution') == []
        assert 'Source digest' in browser.eval('document.body.innerText')
        plan = store.listing('native', 'plan')[0]
        assert plan['config']['parameters']['dataset'] == 'example'
        click(browser, 'Back to setup')
        wait_for(browser, "document.querySelector('[aria-label=\"Workflow\"]').value === 'evaluate-smoke'")
        assert browser.eval("document.querySelector('[aria-label=\"Dataset\"]').value") == 'example'
        click(browser, 'Check setup and review')
        wait_for(browser, "[...document.querySelectorAll('button')].some(b => b.textContent === 'Approve run' && !b.disabled)")
        assert store.listing('native', 'execution') == []
        click(browser, 'Approve run')
        wait_for(browser, "location.pathname.includes('/executions/')")
        assert len(store.listing('native', 'execution')) == 1
