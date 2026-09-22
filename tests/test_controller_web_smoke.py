"""Load the built dashboard in a real browser and drive every page.

`test_controller_web.py` reads source. This one runs the bundle: a broken
import, a bad hook order or a component that throws on an empty payload shows
up only when a browser evaluates it.

It needs Chrome and a build, and it starts a server, so it is opt-in:

    UNITY_HPC_UI_SMOKE=1 python3 -m pytest tests/test_controller_web_smoke.py
"""

import json
import os
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from tests.cdp import Browser, find_chrome

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "controller" / "web" / "dist"

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("UNITY_HPC_UI_SMOKE"),
        reason="set UNITY_HPC_UI_SMOKE=1 to run the browser smoke test",
    ),
    pytest.mark.skipif(find_chrome() is None, reason="no Chrome binary on PATH"),
    pytest.mark.skipif(
        not (DIST / "index.html").is_file(),
        reason="run `cd controller/web && npm run build` first",
    ),
]

ROUTES = [
    ("/cluster/overview", "Cluster Overview"),
    ("/cluster/queue", "Queue & Partitions"),
    ("/cluster/users", "Users & Fairshare"),
    ("/cluster/analytics", "Usage Analytics"),
    ("/jobs/monitor", "Job Monitor"),
    ("/jobs/project", "Projects"),
    ("/jobs/dispatch", "Dispatch Run"),
    ("/settings/config", "Configuration"),
    ("/settings/scheduled", "Scheduled Retrieval"),
    ("/settings/logs", "Logs & History"),
]

TRAP = """
window.__errs = [];
window.addEventListener('error', e => window.__errs.push('error: ' + (e.message || e)));
window.addEventListener('unhandledrejection',
  e => window.__errs.push('reject: ' + ((e.reason && e.reason.message) || e.reason)));
'ok'
"""

GO = """
history.pushState({}, '', %s);
window.dispatchEvent(new PopStateEvent('popstate'));
'ok'
"""


@pytest.fixture(scope="module")
def dashboard(tmp_path_factory):
    """The controller on a free port, against an empty data directory."""
    data = tmp_path_factory.mktemp("data")
    os.environ["UNITY_HPC_DATA"] = str(data)
    from controller.serve import Handler  # imported late, after UNITY_HPC_DATA

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.fixture(scope="module")
def page(dashboard):
    with Browser() as browser:
        browser.goto(dashboard + "/")
        browser.eval(TRAP)
        yield browser


def _go(page, path: str) -> None:
    page.eval(GO % json.dumps(path))
    time.sleep(0.7)


def test_the_bundle_mounts(page):
    assert page.eval("!!document.querySelector('#root').firstChild")
    assert page.eval("location.pathname") == "/cluster/overview", \
        "the root path must redirect to the default page"


def test_the_drawer_lists_every_page(page):
    hrefs = page.eval(
        "[...document.querySelectorAll('nav a')].map(a => a.getAttribute('href'))"
    )
    assert hrefs == [path for path, _ in ROUTES]


@pytest.mark.parametrize("path, title", ROUTES)
def test_each_page_renders_against_an_empty_controller(page, path, title):
    """Every panel must draw an empty state, not throw, with no data at all."""
    _go(page, path)
    assert page.eval("document.querySelector('h1').textContent") == title
    body = page.eval("document.querySelector('main').innerText") or ""
    assert body.strip(), f"{path} rendered nothing"


def test_the_active_page_is_marked_in_the_drawer(page):
    _go(page, "/jobs/dispatch")
    active = page.eval(
        "[...document.querySelectorAll('nav a.active')]"
        ".map(a => a.getAttribute('href'))"
    )
    assert active == ["/jobs/dispatch"]


def test_the_dispatch_preview_follows_the_form(page):
    """The preview is the request body, so a typed field must appear in it."""
    _go(page, "/jobs/dispatch")
    page.eval(
        "(() => {"
        "  const input = [...document.querySelectorAll('input')]"
        "    .find(i => i.placeholder === 'smoke');"
        "  const set = Object.getOwnPropertyDescriptor("
        "    window.HTMLInputElement.prototype, 'value').set;"
        "  set.call(input, 'smoke-test');"
        "  input.dispatchEvent(new Event('input', {bubbles: true}));"
        "  return 'ok';"
        "})()"
    )
    time.sleep(0.4)
    assert "smoke-test" in (page.eval("document.querySelector('pre').innerText") or "")


def test_the_job_filter_chips_switch(page):
    _go(page, "/jobs/monitor")
    labels = page.eval(
        "[...document.querySelectorAll('header button')].map(b => b.textContent)"
    )
    assert "Failed" in labels
    page.eval(
        "[...document.querySelectorAll('header button')]"
        ".find(b => b.textContent === 'Failed').click()"
    )
    time.sleep(0.4)
    assert page.eval("document.querySelector('tbody').innerHTML.length") > 0


def test_the_theme_toggle_repaints(page):
    _go(page, "/cluster/overview")
    before = page.eval("getComputedStyle(document.body).backgroundColor")
    page.eval("document.querySelector('[data-testid=theme-toggle]').click()")
    time.sleep(0.5)
    after = page.eval("getComputedStyle(document.body).backgroundColor")
    assert before != after, "the colour scheme did not change"
    page.eval("document.querySelector('[data-testid=theme-toggle]').click()")
    time.sleep(0.5)


def test_the_header_pill_never_calls_an_old_snapshot_live(dashboard):
    """Rows in the mirror do not mean the collector still runs.

    A stale snapshot kept the old dashboard's pill green and reading "live
    sync", which is the most prominent trust signal on the page. The wording
    must follow freshness, not the presence of rows.
    """
    cases = [
        (30, True, True, "live sync"),
        (60 * 60 * 24 * 59, True, False, "snapshot"),
        (None, False, False, "waiting on snapshot"),
    ]
    for age_s, available, fresh, wording in cases:
        payload = {
            "cluster": "unity",
            "live": {
                "available": available, "fresh": fresh, "age_s": age_s,
                "latest": {}, "trend": [],
            },
            "partitions": [], "gpu_fleet": [],
            "fairshare": {"available": False},
            "users": {"available": False, "rows": []},
            "stats": {"available": False, "runs": 0, "counts": {},
                      "by_hardware": [], "by_partition": []},
            "kpis": {},
        }
        stub = """
        (() => {
          const body = %s;
          const real = window.fetch;
          window.fetch = (input, init) => {
            const url = String(typeof input === 'string' ? input : input.url);
            if (url.indexOf('/api/v1/cluster') === 0
                && url.indexOf('/api/v1/cluster/') !== 0) {
              return Promise.resolve(new Response(JSON.stringify(body),
                {status: 200, headers: {'content-type': 'application/json'}}));
            }
            return real(input, init);
          };
          return 'ok';
        })()
        """ % json.dumps(payload)
        with Browser() as browser:
            browser.goto(dashboard + "/")
            assert browser.eval(stub) == "ok"
            time.sleep(11)  # one refresh cycle
            label = browser.eval(
                "document.querySelector('[data-testid=connection-state]').textContent"
            )
            assert wording in (label or ""), f"the pill read {label!r}"
            if not fresh:
                assert "live sync" not in (label or "")


def test_no_page_raised_an_error(page):
    """Run last: it reads the errors every check above could have produced."""
    errs = [e for e in (page.eval("window.__errs") or []) if "Clipboard" not in e]
    assert errs == [], f"the dashboard raised: {errs}"
