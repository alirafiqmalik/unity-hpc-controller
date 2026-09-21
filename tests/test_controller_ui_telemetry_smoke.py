"""Drive the telemetry retrieval panel in a real browser.

Every control on the Settings tab is clicked here, against a controller that
runs the real `scripts/hpc-sync-telemetry` over a local fixture source. A path
with no ':' is a supported local source, so the pull, the retention gate and
the rollup all run — only the network is absent.

It needs Chrome and it starts a server, so it is opt-in:

    UNITY_HPC_UI_SMOKE=1 python3 -m pytest tests/test_controller_ui_telemetry_smoke.py
"""

import fcntl
import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer

import pytest

from tests.cdp import Browser, find_chrome

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("UNITY_HPC_UI_SMOKE"),
        reason="set UNITY_HPC_UI_SMOKE=1 to run the browser smoke test",
    ),
    pytest.mark.skipif(find_chrome() is None, reason="no Chrome binary on PATH"),
    pytest.mark.skipif(
        subprocess.run(["bash", "-c", "command -v rsync"],
                       capture_output=True).returncode != 0,
        reason="rsync not available"),
]

DAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _slots(day, rid="a100", n=96):
    return [
        {"ts": f"{day}T{i // 4:02d}:{(i % 4) * 15:02d}:00Z", "kind": "gpu_type",
         "resource_id": rid, "alloc": 40 + (i % 20), "total": 100}
        for i in range(n)
    ]


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    """A telemetry tree and its sibling snapshot.csv, as the cluster lays them out."""
    root = tmp_path_factory.mktemp("cluster")
    day = root / "telemetry" / DAY
    day.mkdir(parents=True)
    (day / "resource_state.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in _slots(DAY)))
    # Stamp the newest row at now. A running collector writes a row every few
    # seconds, so this is what a real pull lands. Stamping it at midnight made
    # the pulled snapshot hours old, and the pill below reads freshness.
    newest = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (root / "snapshot.csv").write_text(
        "timestamp_utc,gpu_running,gpu_pending,gpu_preempt_pending,"
        "total_nodes,free_nodes,gpu_types_free\n"
        f"{newest},12,4,1,544,31,a100 a40\n")
    return str(root / "telemetry") + "/"


@pytest.fixture(scope="module")
def dashboard(tmp_path_factory):
    """The controller on a free port, against an empty data directory."""
    data = tmp_path_factory.mktemp("teldata")
    os.environ["UNITY_HPC_DATA"] = str(data)
    # The panel resolves a source from the environment when nothing is saved, so
    # a developer who exports one must not change what this test sees.
    os.environ.pop("UNITY_TELEMETRY_SRC", None)
    from controller.serve import Handler  # imported late, after UNITY_HPC_DATA

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


TRAP = """
window.__errs=[];
window.addEventListener('error',e=>window.__errs.push('error: '+(e.message||e)));
window.addEventListener('unhandledrejection',e=>window.__errs.push('reject: '+(e.reason&&e.reason.message||e.reason)));
'ok'
"""


@pytest.fixture(scope="module")
def page(dashboard):
    with Browser() as b:
        b.goto(dashboard + "/")
        b.eval(TRAP)
        b.eval("go('settings')")
        yield b


def wait(page, expression, seconds=30):
    """Poll a JS expression until it is truthy. Returns its last value."""
    deadline = time.monotonic() + seconds
    value = None
    while time.monotonic() < deadline:
        value = page.eval(expression)
        if value:
            return value
        time.sleep(0.25)
    return value


def txt(page, element_id):
    return page.eval(f"document.getElementById({element_id!r}).textContent") or ""


def test_the_panel_says_no_source_before_one_is_set(page):
    assert wait(page, "document.getElementById('telSource').textContent"
                      ".includes('not configured')")
    assert "nothing names a source" in txt(page, "telOrigin")
    assert page.eval("document.getElementById('telSyncBtn').disabled") is True
    assert "No retrieval has run" in txt(page, "telHistory")


def test_saving_a_source_enables_the_retrieve_button(page, source):
    page.eval(
        "(()=>{document.getElementById('telSourceInput').value=%s;})()"
        % json.dumps(source)
    )
    page.eval("telSaveSource()")
    assert wait(page, "document.getElementById('telSource').textContent"
                      ".includes('telemetry')")
    assert txt(page, "telOrigin") == "settings"
    assert wait(page, "!document.getElementById('telSyncBtn').disabled")


def test_the_interval_control_saves(page):
    page.eval("(()=>{document.getElementById('telInterval').value='25';})()")
    page.eval("telSaveInterval()")
    assert wait(page, "fetch('/api/v1/telemetry').then(r=>r.json())"
                      ".then(j=>j.telemetry.schedule.interval_minutes===25)")
    # 25 minutes × 1.5 = 37.5 minutes of quiet before the session closes.
    assert wait(page, "document.getElementById('telIdle').textContent.includes('37.5')")


def test_the_interval_control_refuses_a_value_out_of_range(page):
    page.eval("(()=>{document.getElementById('telInterval').value='2';})()")
    page.eval("telSaveInterval()")
    # The controller refuses it, so the saved value does not move.
    time.sleep(1)
    assert page.eval("fetch('/api/v1/telemetry').then(r=>r.json())"
                     ".then(j=>j.telemetry.schedule.interval_minutes)") == 25


def test_the_schedule_toggle_turns_the_schedule_on_and_off(page):
    page.eval("document.getElementById('telSchedTgl').click()")
    assert wait(page, "document.getElementById('telSchedTgl').classList.contains('on')")
    assert wait(page, "document.getElementById('telNext').textContent!=='schedule is off'")
    assert "on" in txt(page, "telSchedState")

    page.eval("document.getElementById('telSchedTgl').click()")
    assert wait(page, "!document.getElementById('telSchedTgl').classList.contains('on')")
    assert txt(page, "telNext") == "schedule is off"


def test_retrieve_now_runs_a_real_retrieval_and_reports_it(page):
    page.eval("document.getElementById('telSyncBtn').click()")
    assert wait(page, "document.querySelector('#telHistory .tel-run')!==null", 60)
    assert wait(page, "document.querySelector('#telHistory .pill').textContent==='ok'", 60)
    assert "manual" in page.eval(
        "document.querySelector('#telHistory .tel-run .rs').textContent")
    assert "sync: done" in txt(page, "telOutput")


def test_the_stores_go_from_absent_to_present(page):
    assert wait(page, "!document.getElementById('telDb').textContent"
                      ".includes('absent')", 60)
    assert wait(page, "!document.getElementById('telCsv').textContent"
                      ".includes('absent')", 60)
    assert DAY in txt(page, "telRaw")
    assert "current" in txt(page, "telRollup")


def test_the_button_is_refused_while_the_sync_lock_is_held(page):
    """Two retrievals must never overlap, whoever holds the lock."""
    from lib import paths

    lock = paths.sync_lock()
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.touch()
    with lock.open("w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        assert wait(page, "fetch('/api/v1/telemetry').then(r=>r.json())"
                          ".then(j=>j.telemetry.running)", 30)
        answer = page.eval("""
          fetch('/api/v1/telemetry/sync',{method:'POST',
            headers:{'content-type':'application/json'},body:'{}'})
            .then(r=>r.json()).then(j=>j.status)
        """)
        assert answer == "already-running"
        page.eval("go('settings')")
        assert wait(page, "document.getElementById('telSyncBtn').disabled", 30)
    assert wait(page, "fetch('/api/v1/telemetry').then(r=>r.json())"
                      ".then(j=>!j.telemetry.running)", 30)


def test_the_charts_draw_the_retrieved_series(page):
    page.eval("refresh()")
    assert wait(page, "fetch('/api/v1/cluster/usage?hours=24').then(r=>r.json())"
                      ".then(j=>j.usage.available && 'a100' in j.usage.series)", 30)
    page.eval("go('settings')")
    assert wait(page, "document.getElementById('telSeries').textContent"
                      ".includes('slots')")
    assert "last 24h" in txt(page, "telSeries")


def test_the_header_pill_goes_live_on_the_pulled_snapshot(page):
    """A pull that lands a current snapshot must turn the pill live.

    The pill follows freshness, not the mere presence of rows, so this also
    guards the other direction: a pull of an old mirror must NOT read live.
    """
    assert wait(page, "document.getElementById('envLabel').textContent"
                      ".includes('live sync')", 30)
    assert page.eval(
        "document.getElementById('envPill').classList.contains('off')") is False


def test_no_control_raised_an_error(page):
    """Run last: it reads the errors every check above could have produced."""
    errs = [e for e in (page.eval("window.__errs") or []) if "Clipboard" not in e]
    assert errs == [], f"the panel raised: {errs}"
