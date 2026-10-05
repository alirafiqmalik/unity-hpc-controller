"""Exercise the real heatmap through the controller and built browser bundle."""

import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from controller.serve import Handler
from tests.cdp import Browser, find_chrome

DIST = Path(__file__).resolve().parent.parent / "controller" / "web" / "dist" / "index.html"
pytestmark = pytest.mark.skipif(
    find_chrome() is None or not DIST.exists(),
    reason="build the dashboard and provide Chrome for the visual test",
)


def _stamp(value):
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed(data):
    """Thirty days of varied allocations, one real gap, and long stat lists."""
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=30)
    missing = end - timedelta(hours=10)
    con = sqlite3.connect(data / "historical_usage.db")
    try:
        con.executescript("""
            CREATE TABLE hour_gpu(hour_utc TEXT, gpu_type TEXT, allocated_avg REAL,
                                  PRIMARY KEY(hour_utc,gpu_type));
            CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
        """)
        for n in range(720):
            hour = start + timedelta(hours=n)
            if hour == missing:
                continue
            value = 500 + hour.hour * 10
            con.executemany("INSERT INTO hour_gpu VALUES(?,?,?)", [
                (_stamp(hour), "__all__", value), (_stamp(hour), "a100", value),
            ])
        con.executemany("INSERT INTO meta VALUES(?,?)", [
            ("start_utc", _stamp(start)), ("end_utc", _stamp(end)),
        ])
        con.commit()
    finally:
        con.close()

    con = sqlite3.connect(data / "summaries.db")
    try:
        con.execute("""CREATE TABLE task_run(
            job_id TEXT, project TEXT, campaign TEXT, skill TEXT, hardware TEXT,
            submit TEXT, start TEXT, "end" TEXT, elapsed_s REAL, wait_s REAL,
            cpu_eff REAL, mem_eff REAL, max_rss_mb REAL, state TEXT,
            exit_code INTEGER, day_utc TEXT, partition TEXT)""")
        for n in range(48):
            con.execute("INSERT INTO task_run VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (str(n), "", "", "", f"gpu_{n}", _stamp(end), _stamp(end),
                         _stamp(end), 3600, n * 60, None, None, None, "COMPLETED", 0,
                         end.strftime("%Y-%m-%d"), f"partition_{n}"))
        con.commit()
    finally:
        con.close()


def _matrix(browser):
    return browser.eval("""(() => {
      const title=[...document.querySelectorAll('h3')]
        .find(node=>node.textContent.includes('When is the cluster busy?'));
      const cells=[...document.querySelectorAll('[data-testid=heatmap-cell]')];
      const filled=cells.filter(node=>['value','partial'].includes(node.dataset.state));
      return {top:Math.round(title.getBoundingClientRect().top),
        filled:filled.length,
        partial:cells.filter(node=>node.dataset.state==='partial').length,
        missing:cells.filter(node=>node.dataset.state==='missing').length,
        outside:cells.filter(node=>node.dataset.state==='outside').length,
        colors:new Set(filled.map(node=>getComputedStyle(node).backgroundColor)).size,
        buttons:cells.filter(node=>node.tagName==='BUTTON').length};
    })()""")


def test_heatmap_windows_colors_keyboard_touch_and_mobile(tmp_data_dir):
    _seed(tmp_data_dir)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/cluster/analytics"
        with Browser(width=1400, height=900) as browser:
            browser.goto(url, settle=3)
            week = _matrix(browser)
            assert week["top"] < 900, week
            assert (week["filled"], week["missing"], week["outside"]) == (167, 1, 0)
            assert browser.eval("""(() => {
              const card=[...document.querySelectorAll('h3')]
                .find(node=>node.textContent==='Job outcomes')?.closest('section');
              const sections=[...card.querySelectorAll('section')];
              return sections.length===2 &&
                sections[0].querySelector('h4')?.textContent==='All jobs' &&
                sections[0].textContent.includes('48') &&
                !!sections[0].querySelector('.recharts-pie') &&
                sections[1].querySelector('h4')?.textContent==='My jobs' &&
                sections[1].textContent.includes('not available yet') &&
                !!sections[1].querySelector('[data-testid=empty-outcome-ring]') &&
                !sections[1].textContent.includes('0%');
            })()""") is True
            assert browser.eval("""(() => {
              const left=[...document.querySelectorAll('h3')]
                .find(node=>node.textContent==='Job outcomes').closest('section');
              const right=left.nextElementSibling;
              const row=[...right.querySelectorAll('[title]')]
                .find(node=>node.title.startsWith('a100:'));
              const value=row?.lastElementChild;
              return right.getBoundingClientRect().width > left.getBoundingClientRect().width &&
                value?.textContent.endsWith(' GPUs') &&
                value.scrollHeight <= value.clientHeight;
            })()""") is True
            browser.eval("[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='24h').click()")
            time.sleep(1)
            day = _matrix(browser)
            assert day["top"] < 900, day
            assert day["filled"] == 23, day
            assert day["missing"] >= 1 and day["outside"] >= 143, day
            assert day["filled"] + day["missing"] + day["outside"] == 168
            assert day["colors"] >= 6, day
            assert day["buttons"] == 168
            assert browser.eval("""(async () => {
              const cell=document.querySelector('[data-testid=heatmap-cell][data-state=value]');
              cell.focus(); cell.click();
              await new Promise(resolve=>setTimeout(resolve,40));
              return document.activeElement===cell &&
                document.querySelector('[data-testid=heatmap-detail]')?.textContent
                  .includes('allocated GPUs');
            })()""") is True
            assert browser.eval("""(async () => {
              const active=document.activeElement;
              const [day,hour]=active.dataset.cellKey.split('-').map(Number);
              active.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
              await new Promise(resolve=>setTimeout(resolve,40));
              const next=`${(day+(hour===23?1:0))%7}-${(hour+1)%24}`;
              return document.activeElement.dataset.cellKey===next;
            })()""") is True
            assert browser.eval("""(() => {
              const cell=document.querySelector('[data-testid=heatmap-cell][data-state=missing]');
              return cell.title.includes('no sample');
            })()""") is True

            for label in ("7d", "30d"):
                browser.eval(f"[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='{label}').click()")
                time.sleep(1)
                view = _matrix(browser)
                assert view["outside"] == 0, view
                assert view["missing"] == (1 if label == "7d" else 0), view
                assert view["partial"] == (0 if label == "7d" else 1), view
                assert view["colors"] >= 6, view

            browser.eval("[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='24h').click()")
            time.sleep(1)
            browser.eval("document.querySelector('[data-testid=theme-toggle]').click()")
            assert browser.eval("""(() => {
              const cell=document.querySelector('[data-testid=heatmap-cell][data-state=missing]');
              return getComputedStyle(cell).backgroundImage!=='none';
            })()""") is True
            browser.call("Emulation.setDeviceMetricsOverride", width=390, height=844,
                         deviceScaleFactor=1, mobile=True)
            assert browser.eval("document.documentElement.scrollWidth <= innerWidth") is True
            assert browser.eval("""(() => {
              const title=[...document.querySelectorAll('h3')]
                .find(node=>node.textContent.includes('When is the cluster busy?'));
              const header=title.closest('header');
              const note=header.lastElementChild;
              return title.getBoundingClientRect().height < 30 &&
                note.getBoundingClientRect().right <= header.getBoundingClientRect().right;
            })()""") is True

            # A quiet cluster with one busy hour keeps zero in the lowest band.
            con = sqlite3.connect(tmp_data_dir / "historical_usage.db")
            try:
                con.execute("UPDATE hour_gpu SET allocated_avg=0")
                con.execute("UPDATE hour_gpu SET allocated_avg=100 "
                            "WHERE hour_utc=(SELECT MAX(hour_utc) FROM hour_gpu)")
                con.commit()
            finally:
                con.close()
            browser.goto(url, settle=2)
            assert browser.eval("""(() => {
              const cells=[...document.querySelectorAll('[data-testid=heatmap-cell]')];
              const zero=cells.find(cell=>cell.title.includes('average 0 allocated GPUs'));
              const peak=cells.find(cell=>cell.title.includes('average 100 allocated GPUs'));
              const chips=document.querySelectorAll('[aria-label="Relative allocation scale for the selected window"] i');
              return zero && peak && chips.length >= 7 &&
                getComputedStyle(zero).backgroundColor===getComputedStyle(chips[chips.length-7]).backgroundColor &&
                getComputedStyle(zero).backgroundColor!==getComputedStyle(peak).backgroundColor;
            })()""") is True
    finally:
        server.shutdown()
        server.server_close()
