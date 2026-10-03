"""Exercise the existing dispatcher boundary with local SSH stand-ins only."""
import hashlib
import io
import tarfile
from pathlib import Path
from unittest.mock import patch

from controller import workspace_dispatch as transport
from lib import campaign
from test_dispatcher_ledger import dispatcher


def test_reviewed_template_override_and_scoped_job_logs(dispatcher, tmp_path):
    template = tmp_path / 'reviewed.sh'
    template.write_text('echo EXACT_REVIEWED_TEMPLATE\n')
    preview = dispatcher('render', 'reviewed', UNITY_JOB_TEMPLATE=str(template))
    assert preview.returncode == 0
    assert 'EXACT_REVIEWED_TEMPLATE' in preview.stdout
    dispatcher('run', 'first', '--campaign', 'scope', STUB_SBATCH='Submitted batch job 1001')
    dispatcher('run', 'last', '--campaign', 'scope', STUB_SBATCH='Submitted batch job 1002')
    result = dispatcher('logs', '--campaign', 'scope', '--job', '1001')
    assert 'first-1001.out' in result.stdout
    assert 'last-1002.out' not in result.stdout
    assert [r['job_id'] for r in campaign.jobs(dispatcher.project, 'scope')] == ['1001', '1002']


def test_frozen_bundle_upload_contains_only_plan_and_approved_prerequisites(tmp_path):
    folder = tmp_path / '.unity-workspace/plans/plan-a/source'
    folder.mkdir(parents=True)
    (folder / 'source.py').write_text('print(1)')
    (tmp_path / 'unrelated-secret').write_text('never-upload')
    artifact = tmp_path / '.unity-workspace/outputs/old/v/t/result.json'
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{}')
    record = {'path': str(artifact.relative_to(tmp_path)), 'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest()}
    def fake_ssh(argv, **kwargs):
        assert argv[:3] == ['ssh', '-oBatchMode=yes', 'fake-host']
        with tarfile.open(fileobj=io.BytesIO(kwargs['input']), mode='r:gz') as bundle:
            assert set(bundle.getnames()) == {'.unity-workspace/plans/plan-a/source/source.py', record['path']}
        return type('Result', (), {'returncode': 0})()
    with patch.object(transport.subprocess, 'run', side_effect=fake_ssh):
        transport.stage_bundle({'path': str(tmp_path), 'remote_dir': '/fake/with spaces', 'unity_host': 'fake-host'},
                               {'id': 'plan-a', 'artifacts': [{'files': [record]}]})


def test_effective_stage_resources_reach_existing_dispatcher(tmp_path):
    stage = {'script_path': '.unity-workspace/plans/plan-a/scripts/v--t.sh',
             'resources': {'primitive': 'cpu', 'mode': 'single', 'cpus': 3, 'gpus': 0, 'nodes': 1,
                           'memory_gb': 7, 'walltime': '00:02:00', 'partition': 'cpu'}}
    with patch.object(transport.dispatch, 'run', return_value={'ok': True}) as run:
        transport.submit({'slug': 'demo', 'path': str(tmp_path)}, {'id': 'plan-a'}, stage, {'exp': 'unique-stage'})
    args, kwargs = run.call_args
    assert args == ('demo', 'unique-stage')
    assert kwargs['campaign'] == 'plan-a'
    assert kwargs['overrides']['SLURM_MEM'] == '7G'
    assert kwargs['overrides']['SLURM_GPUS'] == '0'
    assert kwargs['overrides']['SLURM_PARTITION_FALLBACK'] == ''
    assert kwargs['overrides']['JOB_COMMAND'].startswith('bash .unity-workspace/plans/plan-a/')


def test_coordinated_rank_count_is_in_actual_allocation(dispatcher):
    rendered = dispatcher('render', 'coordinated', SLURM_NODES='2', SLURM_NTASKS='8', SLURM_CPUS='3')
    assert rendered.returncode == 0
    assert '#SBATCH --nodes=2' in rendered.stdout
    assert '#SBATCH --ntasks=8' in rendered.stdout
    assert '#SBATCH --cpus-per-task=3' in rendered.stdout


def test_frozen_dispatcher_keeps_original_ledger_when_live_runner_changes(dispatcher, tmp_path, monkeypatch):
    import os
    from controller import dispatch
    root = dispatcher.project
    source = root / '.unity-workspace/plans/frozen/source/unityHPC'
    source.mkdir(parents=True)
    frozen = source / 'run.sh'
    frozen.write_bytes((root / 'unityHPC/run.sh').read_bytes())
    template = source / 'job_template.sh'
    template.write_bytes((root / 'unityHPC/job_template.sh').read_bytes())
    (root / 'unityHPC/run.sh').write_text('#!/bin/sh\nexit 99\n')
    monkeypatch.setenv('PATH', str(tmp_path / 'bin') + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv('STUB_LOG', str(dispatcher.log))
    monkeypatch.setenv('STUB_SBATCH', 'Submitted batch job 777')
    monkeypatch.setattr(dispatch.telemetry, 'settings', lambda: {'ssh_host': 'fake', 'ssh_identity': ''})
    monkeypatch.setattr(dispatch.cluster_session, 'restore_identity', lambda *args: None)
    response = dispatch._run({'path': str(root), 'slug': 'fake'}, ['run', 'frozen-stage', '--campaign', 'frozen'],
                             env_overrides={'UNITY_JOB_TEMPLATE': str(template)}, runner_path=frozen)
    assert response['ok'], response
    assert campaign.jobs(root, 'frozen')[0]['job_id'] == '777'
    assert not (source.parent / '.unity_state').exists()
