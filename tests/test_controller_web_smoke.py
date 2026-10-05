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
DIST = Path(os.environ.get("UNITY_HPC_TEST_UI_DIR", ROOT / "controller" / "web" / "dist"))

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
    from controller import http
    prior_ui = http.UI_DIR
    http.UI_DIR = DIST

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        http.UI_DIR = prior_ui


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


def test_project_controls_remain_visible_and_catalog_confirmation_resets(dashboard, tmp_path):
    """A long catalog must scroll, and arming one project must not arm another."""
    from controller import registry

    entries = [{
        "id": f"entry-{i}", "title": f"Entry {i}", "status": "ready",
        "launch": {"kind": "run", "exp": f"entry-{i}"},
    } for i in range(49)]
    for slug in ("ui-a", "ui-b"):
        root = tmp_path / slug
        unity = root / "unityHPC"
        unity.mkdir(parents=True)
        (unity / "run.sh").write_text("#!/bin/sh\nexit 0\n")
        if slug == "ui-a":
            (unity / "fetch.sh").write_text("#!/bin/sh\nexit 0\n")
        (unity / "experiments.json").write_text(json.dumps({
            "schema_version": 1, "experiments": entries,
        }))
        registry.attach(slug, root, sync_policy="disabled")
    from lib import campaign
    campaign.record(tmp_path / "ui-a", "older-campaign", "12345", "entry-0", "cpu")

    def open_legacy_controls(browser):
        assert browser.eval('location.pathname') == '/projects/ui-a/overview'
        browser.eval("document.querySelector('nav a[href=\"/projects/ui-a/settings\"]').click()")
        time.sleep(.2)
        browser.eval("[...document.querySelectorAll('button')]"
                     ".find(x => x.textContent === 'Legacy project controls').click()")
        time.sleep(.3)

    try:
        with Browser(width=1400, height=900) as browser:
            browser.goto(dashboard + "/jobs/project", settle=1)
            browser.eval(
                "[...document.querySelectorAll('button')]"
                ".find(x => x.getAttribute('aria-label') === 'Open project ui-a').click()"
            )
            time.sleep(0.5)
            open_legacy_controls(browser)
            sizes = browser.eval("""(() => {
              const run = [...document.querySelectorAll('h3')]
                .find(x => x.textContent === 'Run').closest('section');
              return [run.clientHeight, run.scrollHeight,
                run.parentElement.clientHeight, run.parentElement.scrollHeight];
            })()""")
            assert sizes[0] == sizes[1], "the Run card was compressed and clipped"
            assert sizes[3] > sizes[2], "the project panel should scroll"
            browser.eval("[...document.querySelectorAll('button')]"
                         ".find(x => x.textContent === 'Stop campaign').click()")
            assert browser.eval("document.body.innerText.includes('older-campaign')")

            browser.eval("[...document.querySelectorAll('button')]"
                         ".find(x => x.getAttribute('aria-label') === 'Close panel').click()")
            browser.eval("document.querySelector('[aria-label=\"Home — Projects\"]').click()")
            time.sleep(.2)
            browser.eval("""(() => {
              const set = Object.getOwnPropertyDescriptor(
                HTMLInputElement.prototype, 'value').set;
              const inputs = [...document.querySelectorAll('input')];
              for (const [placeholder, value] of [
                ['/home/you/my-project', %s],
                ['optional — derived from the path', 'ui-a'],
              ]) {
                const input = inputs.find(x => x.placeholder === placeholder);
                set.call(input, value);
                input.dispatchEvent(new Event('input', {bubbles: true}));
              }
            })()""" % json.dumps(str(tmp_path / "ui-a")))
            browser.eval("[...document.querySelectorAll('button')]"
                         ".find(x => x.textContent === 'Open attached project').click()")
            time.sleep(0.3)
            assert registry.get("ui-a")["sync_policy"] == "disabled"

            browser.goto(dashboard + "/jobs/dispatch", settle=1)
            catalog_run = """[...document.querySelectorAll('h3')]
              .find(x => x.textContent === 'Experiment catalog')
              .closest('section').querySelector('button')"""
            # The first catalog button is Preview; the second is Run.
            browser.eval(catalog_run.replace("querySelector('button')", "querySelectorAll('button')[1]") + ".click()")
            assert browser.eval("document.body.innerText.includes('Click again to run')")
            browser.eval("""(() => {
              const select = [...document.querySelectorAll('select')]
                .find(x => [...x.options].some(o => o.value === 'ui-b'));
              select.value = 'ui-b';
              select.dispatchEvent(new Event('change', {bubbles: true}));
            })()""")
            time.sleep(0.3)
            assert not browser.eval("document.body.innerText.includes('Click again to run')")

            browser.goto(dashboard + "/jobs/project", settle=1)
            browser.eval("""(() => {
              const real = window.fetch;
              window.fetch = (input, init) => {
                if (String(input).endsWith('/ui-a/fetch')) {
                  return Promise.resolve(new Response(JSON.stringify({
                    ok: false, output: 'artifact pull failed',
                    logs: {ok: true, output: 'logs retrieved'},
                    artifacts: {ok: false, output: 'artifact pull failed'},
                  }), {status: 502, headers: {'content-type': 'application/json'}}));
                }
                return real(input, init);
              };
            })()""")
            browser.eval("[...document.querySelectorAll('button')]"
                         ".find(x => x.getAttribute('aria-label') === 'Open project ui-a').click()")
            time.sleep(0.3)
            open_legacy_controls(browser)
            browser.eval("[...document.querySelectorAll('button')]"
                         ".find(x => x.textContent === 'Fetch logs + artifacts').click()")
            time.sleep(0.3)
            assert browser.eval("document.body.innerText.includes('Scheduler logs · ok')")
            assert browser.eval("document.body.innerText.includes('Project artifacts · failed')")
    finally:
        registry.detach("ui-a")
        registry.detach("ui-b")


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


def test_cluster_window_buttons_refresh_each_endpoint(page):
    _go(page, "/cluster/analytics")
    labels = page.eval(
        "[...document.querySelectorAll('[aria-label=\"Time window\"] button')]"
        ".map(button => button.textContent.trim())"
    )
    assert labels == ["24h", "7d", "30d", "60d", "90d"]
    page.eval("window.__windowRequests = []; const originalFetch = window.fetch; "
              "window.fetch = (input, init) => { "
              "window.__windowRequests.push(String(input)); "
              "return originalFetch(input, init); };")

    for label, hours in (("60d", 1440), ("90d", 2160)):
        page.eval(
            "[...document.querySelectorAll('[aria-label=\"Time window\"] button')]"
            f".find(button => button.textContent.trim() === '{label}').click()"
        )
        time.sleep(0.7)
        assert page.eval(
            f"document.querySelector('[aria-label=\"Time window\"] "
            f"[aria-checked=\"true\"]').textContent.trim()"
        ) == label
        requests = page.eval("window.__windowRequests")
        for path in ("/api/v1/cluster", "/api/v1/cluster/queue",
                     "/api/v1/cluster/usage"):
            assert f"{path}?hours={hours}" in requests


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
