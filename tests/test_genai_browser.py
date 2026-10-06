"""Keyboard access to evaluation setup and results through a real controller."""
import threading
import time
from http.server import ThreadingHTTPServer

import pytest

from controller import http
from tests.cdp import Browser, find_chrome
from test_genai import canonical_dataset_result, native_project  # noqa: F401

pytestmark = pytest.mark.skipif(find_chrome() is None or not (http.UI_DIR / 'index.html').is_file(), reason='requires Chrome and a built dashboard')


def wait_for(browser, expression, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if browser.eval(expression):
            return
        time.sleep(.05)
    raise AssertionError(browser.eval('document.body.innerText'))


def press(browser, key, code, modifiers=0):
    browser.call('Input.dispatchKeyEvent', type='keyDown', key=key, windowsVirtualKeyCode=code, modifiers=modifiers)
    browser.call('Input.dispatchKeyEvent', type='keyUp', key=key, windowsVirtualKeyCode=code, modifiers=modifiers)


def test_evaluation_modal_contains_focus_names_controls_and_restores_trigger(native_project):
    from controller.serve import Handler
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with Browser(width=1100, height=760) as browser:
            browser.goto(f'http://127.0.0.1:{server.server_port}/projects/native/evaluations', settle=.3)
            wait_for(browser, "[...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'New evaluation')")
            # Keep the trigger focused so closing must restore the same control.
            browser.eval("window.__trigger=[...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'New evaluation'); window.__trigger.focus()")
            browser.eval('window.__trigger.click()')
            wait_for(browser, "!!document.querySelector('dialog[open] select')")
            assert browser.eval("document.querySelector('dialog[open]').contains(document.activeElement)")
            assert browser.eval("[...document.querySelectorAll('dialog[open] input, dialog[open] select, dialog[open] textarea')].every(control => !!control.getAttribute('aria-label') || control.labels.length > 0)")
            assert browser.eval("[...document.querySelectorAll('dialog[open] label[for]')].every(label => document.getElementById(label.htmlFor))")
            assert browser.eval("[...document.querySelectorAll('a')].some(link => link.href.includes('/evaluations/ev-'))")
            # Native modal focus cycles internally in either direction.
            for modifiers in (0, 8):
                for _ in range(30):
                    press(browser, 'Tab', 9, modifiers)
                    assert browser.eval("document.querySelector('dialog[open]').contains(document.activeElement)")
            # A background control cannot take focus while the dialog is modal.
            browser.eval('window.__trigger.focus()')
            assert browser.eval("document.querySelector('dialog[open]').contains(document.activeElement)")
            assert browser.eval("(() => { const footer=[...document.querySelectorAll('dialog[open] button')].find(b=>b.textContent.trim()==='Review evaluation matrix').getBoundingClientRect(); return footer.top >= 0 && footer.bottom <= innerHeight; })()")
            press(browser, 'Escape', 27)
            wait_for(browser, "!document.querySelector('dialog[open]')")
            assert browser.eval('document.activeElement === window.__trigger')
    finally:
        server.shutdown()
        server.server_close()


def test_saved_scheduler_states_render_in_comparison_and_execution(native_project, monkeypatch):
    from controller import workspace_store as store
    from controller.serve import Handler
    from lib import campaign
    jobs = [{'job_id': '123', 'status': 'PENDING'}, {'job_id': '124', 'status': 'RUNNING'}]
    stage = {'id': 'evaluate', 'operation': 'evaluate', 'state': 'accepted', 'location': 'cluster',
             'job_ids': ['123', '124'], 'jobs': jobs}
    execution = {'id': 'plan-queue-ui', 'plan_id': 'plan-queue-ui', 'campaign': 'plan-queue-ui',
                 'state': 'active', 'kind': 'experiment', 'stages': [stage],
                 'scheduler_observation': {'checked_at': '2026-10-05T21:15:00Z', 'error': None}}
    with store.transaction('native') as db:
        store.put(db, 'plan', {'id': execution['id'], 'stages': [stage]})
        store.put(db, 'execution', execution)
    monkeypatch.setattr(campaign, 'jobs', lambda *args: jobs)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with Browser(width=1300, height=800) as browser:
            for path in ('evaluations', 'executions/plan-queue-ui'):
                browser.goto(f'http://127.0.0.1:{server.server_port}/projects/native/{path}', settle=.3)
                wait_for(browser, "document.body.innerText.includes('Job 123 · Queued (PENDING)') && document.body.innerText.includes('Job 124 · Running (RUNNING)')")
                assert browser.eval("document.body.innerText.includes('accepted')")
                assert browser.eval("document.body.innerText.includes('Scheduler last checked')")
                assert browser.eval("!!document.querySelector('time[datetime=\"2026-10-05T21:15:00Z\"]')")
            execution['scheduler_observation']['error'] = 'Status refresh unavailable'
            with store.transaction('native') as db:
                store.put(db, 'execution', execution)
            browser.goto(f'http://127.0.0.1:{server.server_port}/projects/native/evaluations', settle=.3)
            wait_for(browser, "document.body.innerText.includes('Showing last known states.')")
            assert browser.eval("document.body.innerText.includes('Status refresh unavailable')")
    finally:
        server.shutdown()
        server.server_close()


def test_evaluation_duration_uses_elapsed_time_and_labels_trace_sum_fallback(native_project, monkeypatch):
    from controller import genai
    from controller.serve import Handler
    evaluation = genai.evaluations('native')['evaluations'][0]
    detail = genai.evaluation('native', evaluation['id'])
    detail.update(started='2026-10-05T21:43:28.426610+00:00',
                  finished='2026-10-05T21:45:44.655018+00:00', duration_total_s=1349.201)
    monkeypatch.setattr(genai, 'evaluation', lambda *args: dict(detail))
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with Browser(width=1300, height=800) as browser:
            url = f'http://127.0.0.1:{server.server_port}/projects/native/evaluations/{evaluation["id"]}'
            browser.goto(url, settle=.3)
            wait_for(browser, "document.body.textContent.includes('Elapsed time') && document.body.textContent.includes('2m 16s')")
            assert not browser.eval("document.body.textContent.includes('Compute time') || document.body.textContent.includes('22m 29s')")
            for started, finished in [('2026-10-05T21:43:28Z', ''),
                                      ('invalid-date', '2026-10-05T21:45:44Z'),
                                      ('2026-10-05T21:45:44Z', '2026-10-05T21:43:28Z')]:
                detail.update(started=started, finished=finished)
                browser.goto(url, settle=.3)
                wait_for(browser, "document.body.textContent.includes('Summed trace time') && document.body.textContent.includes('22m 29s')")
                assert browser.eval("document.body.textContent.includes('Sum across traces; parallel durations overlap.')")
                assert not browser.eval("document.body.textContent.includes('Elapsed time')")
            # A valid zero interval is elapsed time, rather than a missing value.
            detail.update(started='2026-10-05T21:43:28Z', finished='2026-10-05T21:43:28Z')
            browser.goto(url, settle=.3)
            wait_for(browser, "document.body.textContent.includes('Elapsed time') && document.body.textContent.includes('0.00ms')")
    finally:
        server.shutdown()
        server.server_close()


def test_evaluation_dataset_link_opens_viewer_with_linked_runs(canonical_dataset_result):
    from controller import genai
    from controller.serve import Handler
    run = next(e for e in genai.evaluations('native')['evaluations'] if e['source'] == 'workspace')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with Browser(width=1300, height=800) as browser:
            browser.goto(f'http://127.0.0.1:{server.server_port}/projects/native/evaluations/{run["id"]}', settle=.3)
            wait_for(browser, "!!document.querySelector('a[href$=\"/datasets/example\"]')")
            assert not browser.eval("!!document.querySelector('a[href$=\"/datasets/meta-test.jsonl\"]')")
            browser.eval("document.querySelector('a[href$=\"/datasets/example\"]').click()")
            wait_for(browser, "location.pathname.endsWith('/datasets/example') && document.body.textContent.includes('Example display name')")
            wait_for(browser, f"!!document.querySelector('a[href$=\"/evaluations/{run['id']}\"]')")
            assert browser.eval("[...document.querySelectorAll('a[href]')].filter(a => /\\/evaluations\\/ev-/.test(a.getAttribute('href'))).length") == 2
    finally:
        server.shutdown()
        server.server_close()
