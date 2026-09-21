"""Structural checks on the controller dashboard.

The dashboard is plain ES modules with no build step, so nothing but a test
links the markup to the code. These checks read the tree and hold the joints
that a browser only reports at click time.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "controller" / "ui"
INDEX = UI / "index.html"

# The four stylesheets, in the cascade order the single-file dashboard used.
# Reordering them changes which rule wins, so the order is part of the contract.
CSS_ORDER = ["tokens.css", "base.css", "layout.css", "components.css"]

PRIMITIVES = ("cpu", "gpu", "ml", "multi-cpu", "multi-gpu")

# Identifiers an inline attribute may name that are not dashboard functions.
BUILTINS = {"event"}


def _js_files() -> list[Path]:
    return sorted((UI / "js").rglob("*.js"))


def _ui_text() -> str:
    """Every source file in the UI tree, concatenated."""
    parts = [INDEX.read_text()]
    parts += [p.read_text() for p in _js_files()]
    parts += [p.read_text() for p in sorted((UI / "css").glob("*.css"))]
    return "\n".join(parts)


def _inline_handlers(text: str) -> set[str]:
    """
    Every function an on<event>= attribute calls, across markup and JS.

    A `${...}` substitution inside a template literal runs while the module
    builds the markup, in module scope, so it is dropped: only what survives
    into the attribute has to resolve globally when the user clicks.
    """
    names: set[str] = set()
    for attr in re.finditer(r"""on[a-z]+\s*=\s*(["'])(.*?)\1""", text, re.S):
        body = re.sub(r"\$\{.*?\}", "", attr.group(2))
        for call in re.finditer(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(", body):
            name = call.group(1)
            if name not in BUILTINS:
                names.add(name)
    return names


def _bridged_names() -> set[str]:
    """The identifiers main.js puts on `window`."""
    main = (UI / "js" / "main.js").read_text()
    block = re.search(r"Object\.assign\(window,\s*\{(.*?)\}\);", main, re.S)
    assert block, "main.js must expose the inline-handler surface on window"
    return {n.strip() for n in block.group(1).replace("\n", "").split(",") if n.strip()}


def test_index_is_markup_only():
    html = INDEX.read_text()
    assert "<style>" not in html, "CSS belongs in controller/ui/css/"
    assert not re.search(r"<script(?![^>]*\bsrc=)", html), \
        "JavaScript belongs in controller/ui/js/"
    assert '<script type="module" src="/js/main.js"></script>' in html


def test_every_referenced_asset_exists():
    html = INDEX.read_text()
    refs = re.findall(r'(?:href|src)="/([^"]+)"', html)
    assert refs, "index.html must reference its stylesheets and entry module"
    for ref in refs:
        assert (UI / ref).is_file(), f"index.html references a missing file: {ref}"


def test_stylesheets_keep_their_cascade_order():
    html = INDEX.read_text()
    found = re.findall(r'<link rel="stylesheet" href="/css/([^"]+)">', html)
    assert found == CSS_ORDER, f"stylesheet order changed: {found}"


def test_every_tab_has_a_page_module_that_app_imports():
    config = (UI / "js" / "config.js").read_text()
    tabs = re.findall(r"\['([a-z-]+)',\s*'[^']+'\]", config)
    assert len(tabs) == 8, f"expected eight tabs, found {tabs}"

    app = (UI / "js" / "app.js").read_text()
    html = INDEX.read_text()
    for tab in tabs:
        module = UI / "js" / "pages" / f"{tab}.js"
        assert module.is_file(), f"tab {tab!r} has no page module"
        assert "export function render()" in module.read_text(), \
            f"pages/{tab}.js must export render()"
        assert f"./pages/{tab}.js" in app, f"app.js does not import pages/{tab}.js"
        assert f'id="pg-{tab}"' in html, f"index.html has no section for tab {tab!r}"


def test_no_page_module_imports_app():
    """app.js imports every page. A page importing it back closes the loop."""
    for module in sorted((UI / "js" / "pages").glob("*.js")):
        text = module.read_text()
        assert "from '../app.js'" not in text, (
            f"{module.name} imports app.js; reach refresh() through bus.js instead"
        )


def test_every_inline_handler_is_on_the_window_bridge():
    """An onclick= that the bridge forgot fails only when a user clicks it."""
    used = _inline_handlers(_ui_text())
    bridged = _bridged_names()
    missing = sorted(used - bridged)
    assert not missing, f"inline handlers missing from the window bridge: {missing}"


def test_the_window_bridge_carries_nothing_extra():
    """Every bridged name must be reachable from the markup, or it is dead."""
    used = _inline_handlers(_ui_text())
    extra = sorted(_bridged_names() - used)
    assert not extra, f"window bridge exports unused names: {extra}"


def test_controller_ui_is_a_live_dashboard():
    text = _ui_text()
    assert "/api/v1/projects" in text
    assert "fetch('/api/v1/projects" in text
    assert "uhpc_sk_agent" not in text
    assert "X-Token" not in text
    assert "v2.0-mock" not in text
    assert "Design mock" not in text
    for primitive in PRIMITIVES:
        assert primitive in text
    assert "openProject" in text
