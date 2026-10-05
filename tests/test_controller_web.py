"""Structural checks on the controller dashboard.

The dashboard is a Vite build of `controller/web`, so nothing but a test links
the Python side to the TypeScript side. These checks read both trees and hold
the joints between them: the navigation map against the router, the build
output against what `http._static` serves, and the routing rules a
single-page app needs from the server.

They read source. `tests/test_controller_web_smoke.py` runs the built page in
a real browser.
"""

import json
import re
from pathlib import Path

import pytest

from controller import http
from controller.http import Request, handle

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "controller" / "web"
SRC = WEB / "src"
DIST = WEB / "dist"

#: The three sections and their pages, as the redesign fixed them.
NAVIGATION = {
    "Cluster": ["/cluster/overview", "/cluster/queue", "/cluster/users",
                "/cluster/analytics"],
    "User Jobs": ["/jobs/monitor", "/jobs/project", "/jobs/dispatch"],
    "Settings": ["/settings/config", "/settings/scheduled", "/settings/logs"],
}

ALL_ROUTES = [path for paths in NAVIGATION.values() for path in paths]

needs_build = pytest.mark.skipif(
    not (DIST / "index.html").is_file(),
    reason="run `cd controller/web && npm install && npm run build` first",
)


def _read(rel: str) -> str:
    return (WEB / rel).read_text()


# ---------------------------------------------------------------------------
# The project
# ---------------------------------------------------------------------------

def test_the_package_declares_the_twenty_front_stack():
    """The stack is the point of the migration, so it is pinned by a test."""
    pkg = json.loads(_read("package.json"))
    deps = pkg["dependencies"]
    for name in ("react", "react-dom", "react-router-dom", "recoil",
                 "@emotion/react", "@emotion/styled"):
        assert name in deps, f"{name} is not a dependency"
    assert "vite" in pkg["devDependencies"]
    assert "typescript" in pkg["devDependencies"]
    assert pkg["scripts"]["build"].startswith("tsc --noEmit"), \
        "the build must typecheck before it bundles"


def test_the_build_writes_where_the_controller_serves():
    """`vite.config.ts` and `http.UI_DIR` must name the same directory."""
    config = _read("vite.config.ts")
    match = re.search(r"outDir:\s*'([^']+)'", config)
    assert match, "vite.config.ts must set build.outDir"
    assert (WEB / match.group(1)).resolve() == http.UI_DIR.resolve()


def test_the_dev_server_proxies_the_api_to_the_controller():
    config = _read("vite.config.ts")
    assert "'/api'" in config, "npm run dev must proxy /api"
    assert str(http.DEFAULT_PORT) in config, \
        "the dev proxy must target the controller's default port"


def test_the_source_is_typescript_only():
    """A stray .js file in src/ is a file that skipped the typecheck."""
    stray = sorted(p.relative_to(SRC) for p in SRC.rglob("*.js"))
    assert stray == [], f"untyped sources in controller/web/src: {stray}"


def test_generated_directories_are_ignored():
    ignore = _read(".gitignore")
    assert "node_modules/" in ignore
    assert "dist/" in ignore, "the build output must not be committed"


# ---------------------------------------------------------------------------
# The navigation map
# ---------------------------------------------------------------------------

def test_the_navigation_map_holds_the_three_sections():
    routes = _read("src/modules/navigation/routes.ts")
    for section, paths in NAVIGATION.items():
        assert f"label: '{section}'" in routes, f"no {section!r} section"
        for path in paths:
            assert f"path: '{path}'" in routes, f"{path} is not in the drawer"


def test_the_router_serves_every_page_the_drawer_offers():
    """A path in the drawer and not in the router is a dead link."""
    app = _read("src/App.tsx")
    for path in ALL_ROUTES:
        # Settings pages are nested under a shared telemetry provider, so the
        # router holds the child segment rather than the whole path.
        needle = path if not path.startswith("/settings/") else path.split("/")[-1]
        assert f'path="{needle}"' in app, f"{path} has no route"


def test_the_router_has_no_page_the_drawer_hides():
    app = _read("src/App.tsx")
    declared = set(re.findall(r'path="(/[^"*]+)"', app))
    declared.discard("/")
    declared.discard("/settings")
    declared.discard("/projects/:slug")
    assert declared <= set(ALL_ROUTES), \
        f"routes missing from the drawer: {sorted(declared - set(ALL_ROUTES))}"


def test_project_routes_keep_research_tools_alongside_application_landings():
    app = _read("src/App.tsx")
    navigation = _read("src/modules/navigation/routes.ts")
    drawer = _read("src/ui/layout/NavigationDrawer.tsx")
    assert 'path="/projects/:slug"' in app
    assert '<Navigate to="traces" replace' in app
    assert "result.total > 0 ? 'executions' : 'runner'" in app
    assert 'path="research"' in app
    sections = re.search(r'PROJECT_SECTIONS = \[([^\]]+)\]', navigation).group(1)
    for label in re.findall(r"'([^']+)'", sections):
        assert f'path="{label.lower()}"' in app
    assert 'PROJECT_SECTIONS.map' in drawer
    assert 'to={projectsReturn}' in drawer
    assert "let projectsReturn = '/jobs/project'" in drawer
    assert "sessionStorage.getItem('unity-hpc.projects-return')" in drawer
    for section in ('traces', 'sessions', 'datasets', 'evaluations', 'prompts', 'agent-versions', 'runner', 'executions'):
        assert f'path="{section}"' in app


def test_the_default_route_is_the_overview():
    routes = _read("src/modules/navigation/routes.ts")
    assert "DEFAULT_ROUTE = '/cluster/overview'" in routes


def test_every_page_module_the_router_imports_exists():
    app = _read("src/App.tsx")
    for rel in re.findall(r"from '(\./pages/[^']+)'", app):
        assert (SRC / (rel[2:] + ".tsx")).is_file(), f"missing module {rel}"


# ---------------------------------------------------------------------------
# What the controller serves
# ---------------------------------------------------------------------------

def _get(path: str):
    return handle(Request(method="GET", path=path))


@needs_build
@pytest.mark.parametrize("path", ["/", *ALL_ROUTES, "/projects/demo/overview",
                                  "/projects/demo/experiments/exp-example",
                                  "/projects/demo/review/plan-example",
                                  "/projects/demo/runs?execution=plan-example"])
def test_every_route_answers_with_the_page(path):
    """A deep link must work on a cold load, not only after client routing."""
    resp = _get(path)
    assert resp.status == 200, f"{path} answered {resp.status}"
    assert resp.content_type.startswith("text/html")
    assert b'<div id="root">' in resp.body


@needs_build
def test_a_missing_asset_is_a_404_and_never_the_page():
    """An HTML body served as JavaScript is a syntax error with no cause."""
    resp = _get("/assets/does-not-exist.js")
    assert resp.status == 404
    assert b"<html" not in resp.body.lower()


@needs_build
def test_hashed_assets_are_cached_and_the_page_is_not():
    asset = next(iter(sorted((DIST / "assets").glob("*.js"))))
    resp = _get(f"/assets/{asset.name}")
    assert resp.status == 200
    assert resp.content_type == "application/javascript"
    assert "immutable" in resp.headers.get("Cache-Control", "")
    assert "Cache-Control" not in _get("/").headers


@needs_build
def test_one_cache_control_header_reaches_the_wire(tmp_path, monkeypatch):
    """`handle()` is not the whole answer: `serve.py` writes the headers.

    The handler adds a default `Cache-Control: no-store`, which is right for
    the API and for index.html. When a route sets its own, sending both puts
    two headers on the wire, a client combines them into one list, `no-store`
    wins, and the hashed asset is never cached. This drives a real socket,
    because that merge is invisible to a `handle()` call.
    """
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    monkeypatch.setenv("UNITY_HPC_DATA", str(tmp_path))
    from controller.serve import Handler

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    asset = next(iter(sorted((DIST / "assets").glob("*.js"))))
    try:
        with urllib.request.urlopen(f"{base}/assets/{asset.name}") as answer:
            on_asset = answer.headers.get_all("Cache-Control") or []
        with urllib.request.urlopen(f"{base}/") as answer:
            on_page = answer.headers.get_all("Cache-Control") or []
        with urllib.request.urlopen(f"{base}/api/v1/health") as answer:
            on_api = answer.headers.get_all("Cache-Control") or []
    finally:
        srv.shutdown()
        srv.server_close()

    assert on_asset == ["public, max-age=31536000, immutable"], \
        f"the asset carried {on_asset}"
    assert on_page == ["no-store"], f"index.html carried {on_page}"
    assert on_api == ["no-store"], f"the API carried {on_api}"


def test_an_unknown_api_route_is_never_rewritten_to_the_page():
    """`/api/...` is data. A 404 there must stay a 404."""
    resp = _get("/api/v1/nope")
    assert resp.status == 404
    assert resp.content_type == "application/json"


def test_a_traversal_stays_inside_the_build():
    for path in ("/../../etc/passwd", "/../../../controller/telemetry.py"):
        resp = _get(path)
        assert resp.status == 404, f"{path} was served"


def test_an_unbuilt_dashboard_says_how_to_build_it(monkeypatch, tmp_path):
    """The API must come up even when the dashboard never built."""
    monkeypatch.setattr(http, "UI_DIR", tmp_path / "dist")
    resp = _get("/")
    assert resp.status == 503
    assert b"npm run build" in resp.body
    assert _get("/api/v1/health").status == 200
