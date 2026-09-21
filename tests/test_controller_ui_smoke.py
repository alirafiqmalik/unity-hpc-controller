"""Load the dashboard in a real browser and click through every tab.

The structural checks in test_controller_ui.py read the source. This one runs
it: with no build step, a bad import path or a missing `window` binding shows
up only when a browser evaluates the module graph.

It needs Chrome and it starts a server, so it is opt-in:

    UNITY_HPC_UI_SMOKE=1 python3 -m pytest tests/test_controller_ui_smoke.py
"""

import json
import os
import threading
from http.server import ThreadingHTTPServer

import pytest

from tests.cdp import Browser, find_chrome

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("UNITY_HPC_UI_SMOKE"),
        reason="set UNITY_HPC_UI_SMOKE=1 to run the browser smoke test",
    ),
    pytest.mark.skipif(find_chrome() is None, reason="no Chrome binary on PATH"),
]

TABS = [
    "overview", "queue", "jobs", "users",
    "analytics", "dispatch", "projects", "settings",
]

# Every function an inline handler names. main.js must put each on `window`.
BRIDGE = [
    "go", "refresh", "copyPre",
    "openJob", "openProject", "closeDrawer",
    "patchProject", "runProject", "projectPost", "detachProject",
    "attachProject",
    "dispatchRun", "onDispProject", "renderPreview",
    "exportUsers",
    "telSync", "telSchedule", "telSaveInterval", "telSaveSource",
]

TRAP = """
window.__errs=[];
window.addEventListener('error',e=>window.__errs.push('error: '+(e.message||e)));
window.addEventListener('unhandledrejection',e=>window.__errs.push('reject: '+(e.reason&&e.reason.message||e.reason)));
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
    with Browser() as b:
        b.goto(dashboard + "/")
        b.eval(TRAP)
        yield b


def test_the_module_graph_loads(page):
    assert page.eval("document.querySelectorAll('.tab').length") == len(TABS)
    assert page.eval("document.querySelectorAll('.page').length") == len(TABS)


def test_every_bridged_function_is_callable(page):
    missing = page.eval(
        "%s.filter(n=>typeof window[n]!=='function')" % repr(BRIDGE).replace("'", '"')
    )
    assert missing == [], f"not on window: {missing}"


@pytest.mark.parametrize("tab", TABS)
def test_each_tab_renders(page, tab):
    page.eval(f"go({tab!r})")
    assert page.eval(f"document.getElementById('pg-{tab}').classList.contains('active')")
    text = page.eval(f"document.getElementById('pg-{tab}').innerText") or ""
    assert text.strip(), f"tab {tab!r} rendered nothing"


def test_the_jobs_filter_chips_redraw(page):
    page.eval("go('jobs')")
    page.eval("document.querySelectorAll('#jobChips .chip')[4].click()")
    assert page.eval(
        "document.querySelectorAll('#jobChips .chip')[4].classList.contains('on')"
    )
    assert page.eval("document.getElementById('jobRows').innerHTML.length") > 0


def test_the_dispatch_preview_follows_the_form(page):
    page.eval("go('dispatch')")
    page.eval(
        "(()=>{const e=document.getElementById('dispExp');e.value='smoke-test';"
        "e.dispatchEvent(new Event('input'));})()"
    )
    assert "smoke-test" in (page.eval("document.getElementById('dispatchPrev').innerText") or "")


CHARTS = [("overview", "chartUtil", 150), ("queue", "chartQ", 170), ("analytics", "chartAn", 180)]


@pytest.mark.parametrize("dpr", [1, 2, 3])
def test_chart_canvases_hold_their_authored_height_across_rerenders(page, dpr):
    """Regression for the dashboard growing taller on every reopen.

    `lineChart()` in chart.js used to read the canvas `height` ATTRIBUTE on
    every call, but writing the `height` PROPERTY reflects back into that
    same attribute. At dpr > 1 each re-render re-read its own dpr-scaled
    output and scaled it again, so the element grew on screen without
    bound. This drives many re-renders at a HiDPI scale factor and checks
    the laid-out height never moves off the authored value.
    """
    try:
        page.call(
            "Emulation.setDeviceMetricsOverride",
            width=1400, height=1000, deviceScaleFactor=dpr, mobile=False,
        )
        for tab, canvas_id, authored_h in CHARTS:
            heights = []
            for _ in range(8):
                page.eval(f"go({tab!r})")
                heights.append(page.eval(
                    f"document.getElementById('{canvas_id}').clientHeight"
                ))
            assert heights == [authored_h] * len(heights), (
                f"dpr={dpr} {canvas_id} clientHeight drifted across re-renders: {heights}"
            )
    finally:
        page.call("Emulation.clearDeviceMetricsOverride")


# --------------------------------------------------------------------------
# The usage-chart series selector.
#
# The local controller has no rollup data, so /api/v1/cluster/usage reports
# `available: false` and the chart draws the empty fallback. These checks put
# a payload with three GPU types into the store and drive the real render
# path, thus they see the same markup and the same canvas as an operator.
# --------------------------------------------------------------------------

MULTI_USAGE = {
    "usage": {
        "available": True,
        "slots": ["00", "04", "08", "12", "16", "20"],
        "series": {
            "a100": [12, 44, 71, 33, 58, 24],
            "a40": [81, 62, 47, 92, 36, 73],
            "l40s": [5, 27, 16, 61, 52, 41],
        },
        "by_type": [
            {"gpu_type": "a100", "avg": 40.3},
            {"gpu_type": "a40", "avg": 65.2},
            {"gpu_type": "l40s", "avg": 33.7},
        ],
    }
}

# CHART_COLORS, in the order usageSeries() hands them out.
SERIES_COLOR = {"a100": "#34d399", "a40": "#60a5fa", "l40s": "#a78bfa"}

_INJECT = """
(async () => {
  const s = await import('/js/state.js');
  s.state.usage = %s;
  const a = await import('/js/app.js');
  a.go(%s);
  return 'ok';
})()
"""

_RESET = """
(async () => {
  const c = await import('/js/chart.js');
  c.setHiddenSeries('chartUtil', []);
  c.setHiddenSeries('chartAn', []);
  return 'ok';
})()
"""

_ENTRIES = """
Array.from(document.getElementById(%s).children).map(c => [
  c.dataset.series || null,
  parseFloat(c.style.opacity || '1') > 0.9,
  c.querySelector('i') ? c.querySelector('i').style.background : '',
])
"""

_PIXELS = """
(() => {
  const cv = document.getElementById(%s);
  const d = cv.getContext('2d').getImageData(0, 0, cv.width, cv.height).data;
  const want = [%d, %d, %d];
  let n = 0;
  for (let i = 0; i < d.length; i += 4) {
    if (d[i + 3] > 200
        && Math.abs(d[i] - want[0]) < 12
        && Math.abs(d[i + 1] - want[1]) < 12
        && Math.abs(d[i + 2] - want[2]) < 12) n++;
  }
  return n;
})()
"""

_CLICK = """
(() => {
  const el = Array.from(document.getElementById(%s).children)
    .find(c => c.dataset.series === %s);
  if (!el) return 'no entry';
  el.click();
  return 'ok';
})()
"""


def _inject(page, tab="overview", payload=MULTI_USAGE):
    """Put a multi-series payload in the store and run the real render path."""
    assert page.eval(_INJECT % (json.dumps(payload), json.dumps(tab))) == "ok"


def _reset(page):
    """Show every series again, in storage and in the module cache."""
    assert page.eval(_RESET) == "ok"


def _entries(page, legend_id):
    """[name, shows, swatch colour] for every entry of one legend."""
    return [tuple(row) for row in page.eval(_ENTRIES % json.dumps(legend_id))]


def _pixels(page, canvas_id, name):
    """How many opaque pixels on the canvas hold the colour of one series."""
    hexcol = SERIES_COLOR[name]
    r, g, b = (int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
    return page.eval(_PIXELS % (json.dumps(canvas_id), r, g, b))


def _click(page, legend_id, name):
    assert page.eval(_CLICK % (json.dumps(legend_id), json.dumps(name))) == "ok"


@pytest.fixture()
def selector(page):
    """A drawn three-series Overview chart, with every series showing."""
    _reset(page)
    _inject(page)
    yield page
    _reset(page)
    _inject(page)


def test_the_legend_says_a_click_filters(selector):
    """A first look must show that a name is a filter. A hover tip is not enough.

    The sentence sits under the chart. The staleness note keeps the heading.
    """
    report = selector.eval(
        """(() => {
          const hint = document.getElementById('chartUtilLegendHint');
          const legend = document.getElementById('chartUtilLegend');
          const note = document.getElementById('utilWindow');
          const pick = legend.querySelector('[data-series]');
          const box = pick ? getComputedStyle(pick) : null;
          return {
            text: hint ? hint.textContent : '',
            childOfLegend: hint ? hint.parentElement === legend : null,
            justBefore: hint ? hint.nextElementSibling === legend : false,
            names: Array.from(legend.children).map(c => c.dataset.series || ''),
            noteParent: note ? note.parentElement.tagName : '',
            border: box ? box.borderTopWidth : '',
            radius: box ? box.borderRadius : '',
          };
        })()"""
    )
    assert report["text"] == "Click a name to show or hide it."
    assert report["childOfLegend"] is False
    assert report["justBefore"] is True
    assert report["names"] == ["a100", "a40", "l40s"]
    assert report["noteParent"] == "H3"
    assert report["border"] not in ("", "0px")
    assert report["radius"] not in ("", "0px")

    # The same chart on Analytics is the same control.
    selector.eval("go('analytics')")
    an = selector.eval(
        "document.getElementById('chartAnLegendHint') "
        "&& document.getElementById('chartAnLegendHint').textContent"
    )
    assert an == "Click a name to show or hide it."
    assert selector.eval(
        "document.getElementById('anWindow').parentElement.tagName"
    ) == "H3"

    # A legend that does not filter must not grow the sentence.
    selector.eval("go('queue')")
    assert selector.eval("document.getElementById('chartQLegendHint')") is None


def test_the_legend_lists_every_series_the_api_returned(selector):
    names = [row[0] for row in _entries(selector, "chartUtilLegend")]
    assert names == ["a100", "a40", "l40s"]
    assert all(row[1] for row in _entries(selector, "chartUtilLegend"))
    for name in names:
        assert _pixels(selector, "chartUtil", name) > 0, f"{name} was not drawn"


def test_a_legend_click_hides_only_that_series(selector):
    before = {row[0]: row[2] for row in _entries(selector, "chartUtilLegend")}
    _click(selector, "chartUtilLegend", "a40")
    after = _entries(selector, "chartUtilLegend")
    assert [row[0] for row in after] == ["a100", "a40", "l40s"], "an entry left the legend"
    assert dict((row[0], row[1]) for row in after) == {
        "a100": True, "a40": False, "l40s": True
    }
    # The colour of a series must not move when a different series goes off.
    assert {row[0]: row[2] for row in after} == before
    assert _pixels(selector, "chartUtil", "a40") == 0, "the hidden line is still drawn"
    assert _pixels(selector, "chartUtil", "a100") > 0
    assert _pixels(selector, "chartUtil", "l40s") > 0
    # A second click brings it back.
    _click(selector, "chartUtilLegend", "a40")
    assert _pixels(selector, "chartUtil", "a40") > 0


def test_the_choice_survives_a_redraw_and_a_tab_change(selector):
    _click(selector, "chartUtilLegend", "a40")
    # What the 10-second refresh does at the end of every cycle.
    for _ in range(3):
        _inject(selector)
        assert _pixels(selector, "chartUtil", "a40") == 0
    # Leave the tab and come back.
    selector.eval("go('analytics')")
    _inject(selector)
    assert dict((r[0], r[1]) for r in _entries(selector, "chartUtilLegend"))["a40"] is False
    assert _pixels(selector, "chartUtil", "a40") == 0


def test_each_chart_keeps_its_own_choice(selector):
    _click(selector, "chartUtilLegend", "a40")
    _inject(selector, tab="analytics")
    assert all(row[1] for row in _entries(selector, "chartAnLegend")), \
        "the Analytics chart followed the Overview choice"
    assert _pixels(selector, "chartAn", "a40") > 0
    _click(selector, "chartAnLegend", "a100")
    assert _pixels(selector, "chartAn", "a100") == 0
    _inject(selector)
    assert _pixels(selector, "chartUtil", "a100") > 0, "the Overview chart followed Analytics"
    keys = selector.eval("Object.keys(localStorage).filter(k=>k.indexOf('uhpc.chart')===0).sort()")
    assert keys == ["uhpc.chart.hidden.chartAn", "uhpc.chart.hidden.chartUtil"]
    selector.eval("(async()=>{const c=await import('/js/chart.js');"
                  "c.setHiddenSeries('chartAn',[]);return 'ok';})()")


def test_all_series_off_leaves_the_empty_frame(selector):
    for name in ("a100", "a40", "l40s"):
        _click(selector, "chartUtilLegend", name)
    rows = _entries(selector, "chartUtilLegend")
    assert [row[0] for row in rows] == ["a100", "a40", "l40s"], "the legend lost its entries"
    assert not any(row[1] for row in rows)
    for name in SERIES_COLOR:
        assert _pixels(selector, "chartUtil", name) == 0
    # The grid lines stay, and the canvas keeps its authored height.
    assert selector.eval(_PIXELS % (json.dumps("chartUtil"), 0x23, 0x2B, 0x38)) > 0
    assert selector.eval("document.getElementById('chartUtil').clientHeight") == 150
    _click(selector, "chartUtilLegend", "l40s")
    assert _pixels(selector, "chartUtil", "l40s") > 0


def test_the_chart_works_when_storage_throws(selector):
    """Private windows and blocked site data make every access throw."""
    broke = selector.eval("""
    (() => {
      const get = Storage.prototype.getItem, set = Storage.prototype.setItem;
      Storage.prototype.getItem = function () { throw new Error('denied'); };
      Storage.prototype.setItem = function () { throw new Error('denied'); };
      window.__restore = () => {
        Storage.prototype.getItem = get; Storage.prototype.setItem = set;
      };
      return 'broken';
    })()
    """)
    assert broke == "broken"
    try:
        # The read path of a chart that has nothing cached yet.
        assert selector.eval(
            "(async()=>{const c=await import('/js/chart.js');"
            "return c.hiddenSeries('chartNothingYet');})()"
        ) == []
        # The write path: the click still lands, and nothing throws.
        _inject(selector)
        _click(selector, "chartUtilLegend", "a100")
        assert _pixels(selector, "chartUtil", "a100") == 0
        assert _pixels(selector, "chartUtil", "a40") > 0
        _click(selector, "chartUtilLegend", "a100")
        assert _pixels(selector, "chartUtil", "a100") > 0
    finally:
        selector.eval("window.__restore()")


def test_the_choice_survives_a_reload(dashboard):
    """A new page load must read the choice back from storage."""
    with Browser() as b:
        b.goto(dashboard + "/")
        b.eval(TRAP)
        _inject(b)
        _click(b, "chartUtilLegend", "a40")
        assert _pixels(b, "chartUtil", "a40") == 0
        b.goto(dashboard + "/")
        b.eval(TRAP)
        _inject(b)
        rows = dict((r[0], r[1]) for r in _entries(b, "chartUtilLegend"))
        assert rows == {"a100": True, "a40": False, "l40s": True}
        assert _pixels(b, "chartUtil", "a40") == 0
        assert _pixels(b, "chartUtil", "a100") > 0
        assert (b.eval("window.__errs") or []) == []


PILL_CASES = [
    # (age in seconds, rows present, expected wording fragment, pill is "off")
    (30, True, "live sync", False),
    (60 * 60 * 24 * 59, True, "snapshot", True),
    (None, False, "waiting on snapshot", True),
]


@pytest.mark.parametrize("age_s, available, wording, is_off", PILL_CASES)
def test_the_header_pill_never_calls_an_old_snapshot_live(page, age_s, available, wording, is_off):
    """`snapshot.csv` having rows does not mean the collector still runs.

    A stale mirror kept the pill green and reading "live sync", which is the
    most prominent trust signal on the page. It must follow freshness.
    """
    page.eval(
        "(async()=>{const s=await import('/js/state.js');"
        "const a=await import('/js/app.js');"
        "s.state.error=null; s.state.health={ok:true};"
        "s.state.cluster={cluster:'unity',live:{available:%s,fresh:%s,age_s:%s,"
        "latest:{},trend:[]}};"
        "a.renderHeader();})()"
        % (
            "true" if available else "false",
            "true" if (available and age_s is not None and age_s < 900) else "false",
            "null" if age_s is None else str(age_s),
        )
    )
    label = page.eval("document.getElementById('envLabel').textContent") or ""
    assert wording in label, f"pill read {label!r}"
    assert page.eval("document.getElementById('envPill').classList.contains('off')") is is_off
    if is_off and available:
        assert "live sync" not in label


def test_a_slid_usage_window_says_how_old_the_data_is(page):
    """A chart headed "last 24h" may hold much older rows. It must say so."""
    page.eval("go('overview')")
    page.eval(
        "(async()=>{const s=await import('/js/state.js');"
        "const c=await import('/js/chart.js');"
        "s.state.usage={usage:{available:true,window:'latest-available',"
        "stale_s:4242576,slots:['a'],series:{a100:[10]},by_type:[]}};"
        "c.windowNote('utilWindow', s.state.usage);})()"
    )
    note = page.eval("document.getElementById('utilWindow').textContent") or ""
    assert "49d" in note, f"note read {note!r}"

    # A current window must stay silent, or the warning stops meaning anything.
    page.eval(
        "(async()=>{const s=await import('/js/state.js');"
        "const c=await import('/js/chart.js');"
        "s.state.usage={usage:{available:true,window:'recent',stale_s:20,"
        "slots:['a'],series:{a100:[10]},by_type:[]}};"
        "c.windowNote('utilWindow', s.state.usage);})()"
    )
    assert (page.eval("document.getElementById('utilWindow').textContent") or "") == ""


def test_no_page_raised_an_error(page):
    """Run last: it reads the errors every check above could have produced."""
    errs = [e for e in (page.eval("window.__errs") or []) if "Clipboard" not in e]
    assert errs == [], f"the dashboard raised: {errs}"
