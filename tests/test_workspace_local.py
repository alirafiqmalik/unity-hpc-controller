"""Controller restarts cannot duplicate a local scientific operation."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from controller import workspace_local as local, workspace_store as store, workspace_worker as worker
from test_workspace_execution import harness
from test_workspace_planner import connected, draft, write_manifest


def _running(h):
    definition = next(stage for stage in h.manifest['workflows']['t1']['stages'] if stage['id'] == 't1')
    definition['operation'] = 'analyze'
    definition['resources'] = {'primitive': 'cpu', 'mode': 'single', 'gpus': 0}
    write_manifest(h.root, h.manifest)
    _, plan, execution = h.start(draft(variant_parameters={}, stages=['t1']))
    stage = execution['stages'][0]
    stage['state'] = 'running'
    stage['attempts'][0]['state'] = 'running'
    execution['state'] = 'active'
    with store.transaction('study') as con:
        store.put(con, 'execution', execution)
    return plan, execution, stage['attempts'][0]['id']


def _supervisor(h, attempt, command):
    return [sys.executable, str(Path(local.__file__)), str(h.root), attempt, json.dumps(command)]


def test_restart_consumes_durable_local_success_without_reexecution(harness, monkeypatch):
    h = harness
    plan, execution, attempt = _running(h)
    command = ['bash', str(h.root / plan['stages'][0]['script_path'])]
    result = subprocess.run(_supervisor(h, attempt, command), capture_output=True, text=True,
                            env={**os.environ, 'UNITY_PROJECT_ROOT': str(h.root)})
    assert result.returncode == 0, result.stderr
    receipt, _ = local.receipt_paths(h.root, attempt)
    assert json.loads(receipt.read_text())['ok']
    monkeypatch.setattr(worker, 'run_local', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('must consume receipt, not rerun')))
    h.tick()
    assert h.execution(execution['id'])['state'] == 'completed'
    assert h.execution(execution['id'])['stages'][0]['job_ids'] == []
    assert h.calls == []


def test_restart_fences_late_supervisor_and_allows_reviewed_recovery(harness):
    h = harness
    _, execution, attempt = _running(h)
    h.tick()
    stage = h.execution(execution['id'])['stages'][0]
    assert stage['state'] == 'failed'
    receipt, _ = local.receipt_paths(h.root, attempt)
    assert json.loads(receipt.read_text())['interrupted']
    marker = h.root / 'must-not-execute'
    late = subprocess.run(_supervisor(h, attempt, [sys.executable, '-c', f'from pathlib import Path; Path({str(marker)!r}).touch()']), capture_output=True, text=True)
    assert late.returncode != 0
    assert not marker.exists()
    assert h.calls == []


def test_live_scientific_child_keeps_lock_after_supervisor_death(harness):
    h = harness
    _, execution, attempt = _running(h)
    marker = h.root / 'child-running'
    command = [sys.executable, '-c', f'from pathlib import Path; import time; Path({str(marker)!r}).touch(); time.sleep(30)']
    supervisor = subprocess.Popen(_supervisor(h, attempt, command), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists()
        h.tick()
        assert h.execution(execution['id'])['stages'][0]['state'] == 'running'
        supervisor.kill()
        supervisor.wait(timeout=3)
        # Its child inherited the same open lock description, so no retry is safe.
        h.tick()
        assert h.execution(execution['id'])['stages'][0]['state'] == 'running'
    finally:
        try:
            os.killpg(supervisor.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        supervisor.wait(timeout=3)
    deadline = time.monotonic() + 3
    while local.interrupted_receipt(h.root, attempt) is None and time.monotonic() < deadline:
        time.sleep(0.01)
    h.tick()
    assert h.execution(execution['id'])['stages'][0]['state'] == 'failed'
    assert h.calls == []


def test_local_timeout_kills_scientific_group_and_releases_attempt_lock(harness):
    h = harness
    _, _, attempt = _running(h)
    marker = h.root / 'timeout-child'
    command = [sys.executable, '-c', f'from pathlib import Path; import time; Path({str(marker)!r}).touch(); time.sleep(30)']
    result = worker.run_local(_supervisor(h, attempt, command), h.root, timeout=0.2)
    assert marker.exists()
    assert result['returncode'] == 124
    assert local.interrupted_receipt(h.root, attempt)['interrupted']
