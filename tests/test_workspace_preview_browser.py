"""Real Files renderers against isolated local data; no remote content or jobs."""
import base64
import json
import os
from pathlib import Path
import struct
import time
import zlib
from urllib.parse import quote

import pytest

from tests.cdp import Browser, find_chrome
from test_remaining_workspace_browser import workspace_server, BUILD  # noqa: F401
from test_workspace_api import project  # noqa: F401
from test_workspace_browser import click, fill

pytestmark = pytest.mark.skipif(not os.environ.get('UNITY_HPC_UI_SMOKE') or find_chrome() is None or not (BUILD / 'index.html').is_file(), reason='requires isolated UI build, Chrome, and UNITY_HPC_UI_SMOKE=1')


def png():
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\0\xff\0\0')) + chunk(b'IEND', b'')


def open_preview(browser, url, path, suffix=''):
    browser.goto(url + '/projects/demo/files?root=source&preview=' + quote(path) + suffix, settle=.4)
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        if browser.eval("document.body.innerText.includes('loaded bytes')"):
            break
        time.sleep(.05)
    assert browser.eval("document.body.innerText.includes('loaded bytes')"), browser.eval('document.body.innerText')


def source_lines(browser):
    return browser.eval("[...document.querySelectorAll('[aria-label=\"Escaped source preview\"] code')].map(n=>n.textContent).join('\\n')")


def test_files_structured_previews_escape_hostile_content_and_keep_locators(workspace_server):
    url, root = workspace_server
    (root/'nested.json').write_text(json.dumps({'nested':{'scientific':'<script>window.previewExecuted=true</script>'},'empty':None,'code':'001'}))
    (root/'invalid.json').write_text('{"invalid": nope}')
    (root/'records.jsonl').write_text('{"id":"one"}\n{"id":"two"}\n{"cut":')
    (root/'values.csv').write_text('condition,value\nmodel-a,001\nmodel-b,"text, with comma"\n')
    (root/'report.md').write_text('# Report title\n**Declared result**\n<script>window.previewExecuted=true</script>\n![remote](https://invalid.example/preview.png)\n[unsafe](javascript:alert(1))\n```html\n<img src="https://invalid.example/code.png">\n```\n')
    (root/'hostile.html').write_text('<script>window.previewExecuted=true</script>\n<img src="https://invalid.example/unsafe.png" onerror="window.previewExecuted=true">')
    (root/'plot.png').write_bytes(png())
    with Browser(width=1200, height=1000) as browser:
        browser.call('Page.addScriptToEvaluateOnNewDocument', source="window.__previewErrors=[];addEventListener('error',e=>window.__previewErrors.push(e.message));")
        open_preview(browser,url,'nested.json')
        assert browser.eval("!!document.querySelector('[aria-label=\"JSON tree\"]')")
        browser.eval("[...document.querySelectorAll('[aria-label=\"JSON tree\"] summary')].find(n=>n.textContent.startsWith('nested')).click()")
        assert '<script>' in browser.eval('document.body.innerText')
        assert browser.eval('window.previewExecuted===undefined')
        click(browser,'Raw source')
        assert '001' in source_lines(browser)
        open_preview(browser,url,'invalid.json')
        assert 'JSON parse error at offset' in browser.eval('document.body.innerText')
        assert '{"invalid": nope}' in source_lines(browser)
        open_preview(browser,url,'records.jsonl')
        summaries=browser.eval("[...document.querySelectorAll('[aria-label=\"JSONL records\"] > details > summary')].map(n=>n.textContent)")
        assert len(summaries)==3 and 'Byte 13' in summaries[1]
        assert 'Invalid JSON' in summaries[2] or 'Incomplete final record' in summaries[2]
        open_preview(browser,url,'values.csv')
        assert browser.eval("document.querySelector('[aria-label=\"Delimited table\"] th').textContent")=='condition'
        cells=browser.eval("[...document.querySelectorAll('[aria-label=\"Delimited table\"] td')].map(n=>n.textContent)")
        assert '001' in cells and 'text, with comma' in cells
        open_preview(browser,url,'report.md')
        assert browser.eval("document.querySelector('[aria-label=\"Rendered Markdown report\"] h3').textContent")=='Report title'
        assert browser.eval("document.querySelector('[aria-label=\"Rendered Markdown report\"] strong').textContent")=='Declared result'
        assert browser.eval("document.querySelectorAll('[aria-label=\"Rendered Markdown report\"] img, [aria-label=\"Rendered Markdown report\"] script, a[href^=\"javascript:\"]').length")==0
        assert browser.eval("performance.getEntriesByType('resource').some(r=>r.name.includes('invalid.example'))") is False
        Path('/tmp/unity-files-markdown.png').write_bytes(base64.b64decode(browser.call('Page.captureScreenshot',format='png')['data']))
        click(browser,'Raw source')
        assert '<script>window.previewExecuted=true</script>' in source_lines(browser)
        open_preview(browser,url,'hostile.html')
        assert '<img src=' in source_lines(browser)
        assert browser.eval('window.previewExecuted===undefined')
        assert browser.eval("document.querySelectorAll('img[src^=\"https://invalid.example\"]').length")==0
        open_preview(browser,url,'plot.png')
        deadline=time.monotonic()+3
        while time.monotonic()<deadline and not browser.eval("document.querySelector('img[alt^=\"Raster preview\"]')?.complete"):
            time.sleep(.05)
        assert browser.eval("(()=>{const i=document.querySelector('img[alt^=\"Raster preview\"]');return [i?.naturalWidth,i?.naturalHeight,i?.src.startsWith('data:image/png;base64,')];})()") == [1,1,True]
        assert browser.eval('window.__previewErrors')==[]
        browser.call('Emulation.setDeviceMetricsOverride',width=390,height=844,deviceScaleFactor=1,mobile=True)
        assert browser.eval('document.documentElement.scrollWidth <= innerWidth')


def test_bounded_source_search_wrap_keyboard_copy_and_url_page_restore(workspace_server):
    url,root=workspace_server
    (root/'large.log').write_text(''.join(f'fixture-line-{i:04d} alpha beta\n' for i in range(3000)))
    with Browser(width=1200,height=1000) as browser:
        open_preview(browser,url,'large.log')
        assert len(source_lines(browser).splitlines())==2000
        assert 'fixture-line-2000' not in source_lines(browser)
        fill(browser,'Search loaded preview page','fixture-line-0042')
        assert browser.eval("document.querySelectorAll('[aria-label=\"Escaped source preview\"] mark').length")==1
        assert '1 matching lines' in browser.eval('document.body.innerText')
        browser.eval("[...document.querySelectorAll('label')].find(n=>n.textContent==='Wrap source lines').querySelector('input').focus()")
        for kind in ('keyDown','keyUp'):
            browser.call('Input.dispatchKeyEvent',type=kind,key=' ',code='Space',windowsVirtualKeyCode=32)
        assert browser.eval("[...document.querySelectorAll('label')].find(n=>n.textContent==='Wrap source lines').querySelector('input').checked") is False
        # A stub captures the intended clipboard payload; it avoids an OS clipboard dependency.
        browser.eval("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async value=>{window.__copiedControllerPath=value;}}})")
        click(browser,'Copy controller path')
        assert browser.eval('window.__copiedControllerPath')=='controller:'+str(root/'large.log')
        click(browser,'Next bounded page')
        time.sleep(.25)
        assert browser.eval("new URLSearchParams(location.search).get('preview_offset')") not in (None,'0')
        assert browser.eval("!!new URLSearchParams(location.search).get('preview_version')")
        assert 'fixture-line-2000' in source_lines(browser)
        restored=browser.eval('location.href')
        browser.goto(restored,settle=.5)
        assert 'fixture-line-2000' in source_lines(browser)
        assert 'absolute line range unknown' in browser.eval('document.body.innerText')
        browser.call('Emulation.setDeviceMetricsOverride',width=390,height=844,deviceScaleFactor=1,mobile=True)
        assert browser.eval('document.documentElement.scrollWidth <= innerWidth')
        browser.eval("document.querySelector('[aria-label=\"Escaped source preview\"]').scrollIntoView({block:'center'})")
        Path('/tmp/unity-files-source-narrow.png').write_bytes(base64.b64decode(browser.call('Page.captureScreenshot',format='png')['data']))
        browser.eval("document.querySelector('[aria-label=\"Escaped source preview\"]').focus()")
        assert browser.eval("document.activeElement.getAttribute('aria-label')")=='Escaped source preview'
        browser.call('Input.dispatchKeyEvent',type='keyDown',key='Tab',code='Tab',windowsVirtualKeyCode=9)
        browser.call('Input.dispatchKeyEvent',type='keyUp',key='Tab',code='Tab',windowsVirtualKeyCode=9)
        assert browser.eval('document.activeElement!==document.body')
