"""Late navigation responses and scope pagination use isolated controller data."""
import json
import os
import time

import pytest
from controller import workspace_store as store
from tests.cdp import Browser, find_chrome
from test_remaining_workspace_browser import workspace_server, BUILD  # noqa: F401
from test_workspace_api import project  # noqa: F401
from test_workspace_browser import click

pytestmark = pytest.mark.skipif(not os.environ.get('UNITY_HPC_UI_SMOKE') or find_chrome() is None or not (BUILD / 'index.html').is_file(), reason='requires isolated UI build, Chrome, and UNITY_HPC_UI_SMOKE=1')


def test_preview_late_response_cannot_replace_new_selection(workspace_server):
    url, root = workspace_server
    (root/'first.txt').write_text('FIRST PREVIEW EVIDENCE')
    (root/'second.txt').write_text('SECOND PREVIEW EVIDENCE')
    with Browser(width=1300,height=900) as browser:
        browser.goto(url+'/projects/demo/files',settle=.5)
        browser.eval("""window.__previewRequests=[]; window.__fetch=window.fetch;
        window.fetch=async (...args)=>{ const address=String(args[0]);const response=await window.__fetch(...args);
          if(address.includes('files/preview')) {window.__previewRequests.push(address);if(address.includes('first.txt'))await new Promise(resolve=>setTimeout(resolve,800));}return response; };""")
        click(browser,'first.txt')
        click(browser,'second.txt')
        time.sleep(1)
        text=browser.eval("document.querySelector('[aria-label=\"Escaped source preview\"]').innerText")
        assert 'SECOND PREVIEW EVIDENCE' in text and 'FIRST PREVIEW EVIDENCE' not in text
        assert browser.eval("new URLSearchParams(location.search).get('preview')")=='second.txt'
        assert len(browser.eval('window.__previewRequests'))==2


def test_results_scope_change_discards_previous_page_fingerprint(workspace_server):
    url,_=workspace_server
    with store.transaction('demo') as con:
        for index in range(53):
            identity=f'page-{index:03d}'
            store.put(con,'artifact',dict(id=identity,version=1,digest=identity,files=[],path='',purpose='experiment',complete=True,variant_id=f'variant-{index:03d}'))
    with Browser(width=1300,height=900) as browser:
        browser.goto(url+'/projects/demo/results',settle=.5)
        click(browser,'Next evidence page')
        time.sleep(.3)
        assert browser.eval("new URLSearchParams(location.search).get('offset')")=='50'
        assert browser.eval("!!new URLSearchParams(location.search).get('selection_fingerprint')")
        identity=browser.eval("[...document.querySelectorAll('button')].find(b=>b.textContent.startsWith('Inspect page-')).textContent.slice(8)")
        click(browser,'Inspect '+identity)
        time.sleep(.3)
        query=browser.eval("Object.fromEntries(new URLSearchParams(location.search))")
        assert query['artifact']==identity and 'offset' not in query and 'selection_fingerprint' not in query
        assert 'Result selection changed' not in browser.eval('document.body.innerText')
        assert 'Evidence '+identity in browser.eval('document.body.innerText')
        click(browser,'Show all matching evidence')
        click(browser,'Next evidence page')
        browser.eval("""(()=>{const element=document.querySelector('[aria-label="Evidence purpose"]');
            Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(element,'smoke-test');element.dispatchEvent(new Event('change',{bubbles:true}));})()""")
        time.sleep(.3)
        query=browser.eval("Object.fromEntries(new URLSearchParams(location.search))")
        assert query['purpose']=='smoke-test' and 'offset' not in query and 'selection_fingerprint' not in query
        assert 'No indexed artifacts match this scope' in browser.eval('document.body.innerText')


def test_results_artifact_switch_clears_cursor_and_rejects_late_sample(workspace_server):
    from controller import workspace_artifacts as files
    from test_workspace_artifacts import artifact
    url,root=workspace_server
    for identity in ('first','second'):
        evidence=files.preserve_artifact('demo',artifact(root,identity,rows=[{'record_id':f'{identity}-{i}','item':f'{identity}-{i}','tokens':128} for i in range(120)]))
        evidence['result_schema']={'fields':{'record_id':'record_id','item':'item','tokens':'tokens'}}
        evidence['observed_at']='2000-01-01T00:00:00+00:00'
        with store.transaction('demo') as con:store.put(con,'artifact',evidence)
    with Browser(width=1400,height=1000) as browser:
        browser.goto(url+'/projects/demo/results?view=samples&artifact=first',settle=.5)
        assert 'Evidence observed: 2000-01-01' in browser.eval('document.body.innerText')
        assert 'Metadata read ' in browser.eval('document.body.innerText')
        click(browser,'Load selected artifact samples')
        assert browser.eval("document.body.innerText.includes('Next sample page')")
        browser.eval("""window.__fetch=window.fetch;window.fetch=async(...args)=>{const address=String(args[0]);const response=await window.__fetch(...args);if(address.includes('/results/samples/')&&!address.includes('/parent'))await new Promise(resolve=>setTimeout(resolve,800));return response;};""")
        click(browser,'first-0')
        click(browser,'Show all matching evidence')
        click(browser,'Inspect second')
        assert not browser.eval("document.body.innerText.includes('Next sample page')")
        assert not browser.eval("document.body.innerText.includes('first-99')")
        click(browser,'Load selected artifact samples')
        time.sleep(1)
        text=browser.eval('document.body.innerText')
        assert 'second-0' in text and 'first-0' not in text and 'Sample first-0' not in text
        assert browser.eval("new URLSearchParams(location.search).get('sample')") is None


def test_nonfinite_json_shows_raw_parse_failure_in_browser(workspace_server):
    url,root=workspace_server
    (root/'nonfinite.json').write_text('{"result":NaN}')
    with Browser(width=1200,height=900) as browser:
        browser.goto(url+'/projects/demo/files?preview=nonfinite.json',settle=.6)
        text=browser.eval('document.body.innerText')
        assert 'Non-finite JSON constant' in text
        assert '{"result":NaN}' in text
        assert 'Unexpected token' not in text


def test_results_late_comparison_response_keeps_new_identity(workspace_server):
    url,_=workspace_server
    with store.transaction('demo') as con:
        for identity in ('first-comparison','second-comparison'):
            store.put(con,'comparison',{'id':identity,'marker':identity,'version':1})
    with Browser(width=1200,height=900) as browser:
        browser.goto(url+'/projects/demo/results?view=compare',settle=.5)
        browser.eval("""window.__fetch=window.fetch;window.fetch=async(...args)=>{const address=String(args[0]);const response=await window.__fetch(...args);if(address.includes('/comparisons/first-comparison'))await new Promise(resolve=>setTimeout(resolve,800));return response;};""")
        for identity in ('first-comparison','second-comparison'):
            browser.eval("history.pushState({},'',"+json.dumps('?view=compare&comparison='+identity)+");dispatchEvent(new PopStateEvent('popstate'))")
            time.sleep(.15)
        time.sleep(1)
        payload=browser.eval("[...document.querySelectorAll('pre')].map(n=>n.textContent).join('\\n')")
        assert 'second-comparison' in payload and 'first-comparison' not in payload
        assert browser.eval("new URLSearchParams(location.search).get('comparison')")=='second-comparison'
