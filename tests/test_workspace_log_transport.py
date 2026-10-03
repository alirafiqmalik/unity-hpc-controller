"""Execute exact log transport with local SSH/rsync fakes only."""
import base64
import json
import pytest
from lib import campaign

SSH = '''#!/usr/bin/env bash
cmd="${!#}"
printf '%s\\n' "$cmd" >>"$STUB_LOG"
exec bash -c "$cmd"
'''
RSYNC = '''#!/usr/bin/env python3
import os,sys,shutil
source,destination=sys.argv[-2:]
source=source.split(':',1)[1]
if os.environ.get('CHANGE_DURING_FETCH'):
    open(source,'a').write('changed')
shutil.copyfile(source,destination)
'''


@pytest.fixture
def logs(make_dispatcher, tmp_path):
    call = make_dispatcher({'ssh': SSH, 'rsync': RSYNC})
    remote = tmp_path / 'remote with spaces'
    (remote / '_slurm').mkdir(parents=True)
    campaign.record(call.project, 'scope', '1001', 'first')
    campaign.record(call.project, 'scope', '1002', 'second')
    (remote / '_slurm/first-1001.out').write_bytes(b'a' * 100000)
    (remote / '_slurm/second-1002.out').write_text('sibling must not leak')
    return call, remote


def test_exact_remote_read_is_bounded_and_selects_one_stream(logs):
    call, remote = logs
    result = call('log-read','--campaign','scope','--job','1001','--stream','out','--offset','0',REMOTE_DIR=str(remote))
    assert result.returncode == 0, result.stderr
    value=json.loads(result.stdout)
    assert len(base64.b64decode(value['data'])) == 65536
    assert value['size'] == 100000 and value['offset'] == 0
    assert 'second' not in result.stdout
    invalid=call('log-read','--campaign','scope','--job','1009',REMOTE_DIR=str(remote))
    assert invalid.returncode != 0


def test_exact_full_retrieval_keeps_prior_bytes(logs):
    call, remote = logs
    result=call('log-fetch','--campaign','scope','--job','1001','--stream','out',REMOTE_DIR=str(remote))
    assert result.returncode == 0, result.stderr
    target=call.project/'_results/scope/first-1001.out'
    assert target.read_bytes() == b'a' * 100000
    assert not (target.parent/'second-1002.out').exists()
    (remote/'_slurm/first-1001.out').write_text('new bytes')
    result=call('log-fetch','--campaign','scope','--job','1001',REMOTE_DIR=str(remote))
    assert result.returncode == 0, result.stderr
    assert target.read_text() == 'new bytes'
    assert next((target.parent/'.log-history').iterdir()).read_bytes() == b'a' * 100000


def test_changed_transfer_and_symlink_fail_closed(logs):
    call, remote = logs
    result=call('log-fetch','--campaign','scope','--job','1001',REMOTE_DIR=str(remote),CHANGE_DURING_FETCH='1')
    assert result.returncode != 0 and 'changed during transfer' in result.stderr
    assert not (call.project/'_results/scope/first-1001.out').exists()
    (remote/'_slurm/first-1001.out').unlink()
    (remote/'_slurm/first-1001.out').symlink_to('/etc/passwd')
    result=call('log-read','--campaign','scope','--job','1001',REMOTE_DIR=str(remote))
    assert result.returncode != 0 and 'Unsafe log path' in result.stderr


def test_missing_stream_and_bad_limit(logs):
    call, remote = logs
    result=call('log-read','--campaign','scope','--job','1001','--stream','err',REMOTE_DIR=str(remote))
    assert json.loads(result.stdout)['availability']=='not-created'
    result=call('log-read','--campaign','scope','--job','1001','--limit','65537',REMOTE_DIR=str(remote))
    assert result.returncode != 0


def test_modified_reviewed_dispatcher_cannot_run_during_log_observation(connected, tmp_data_dir, monkeypatch):
    from controller import registry, workspace, workspace_runs, workspace_store, dispatch
    from test_workspace_planner import draft
    root, _=connected
    registry.attach('study',root,'multi-gpu',remote_dir='/fake/study')
    (root/"unityHPC/run.sh").write_text("""#!/bin/bash\n# cmd_log_read() fixture capability\nif [ "$1" = workspace-env ]; then echo '{}'; else echo '# fixture allocation'; fi\n""")
    item=workspace.create('study',{'workflow':'t1','draft':draft(variant_parameters={},stages=['t1'])})
    plan=workspace.plan('study',item['id']); execution=workspace.dispatch_plan('study',plan['id'],'reviewed')
    runner=root/'.unity-workspace/plans'/plan['id']/'source/unityHPC/run.sh'
    runner.chmod(0o644); runner.write_text('# cmd_log_read() tampered\n')
    monkeypatch.setattr(dispatch,'_run',lambda *a,**k:(_ for _ in ()).throw(AssertionError('changed runner must not execute')))
    with pytest.raises(workspace_store.Conflict,match='integrity'):
        workspace_runs._remote_transport('study',execution,'1001','stdout')


from test_workspace_planner import connected  # noqa: E402,F401
