"""Transport frozen bundles, then submit through the existing dispatcher."""
from __future__ import annotations

import io
import os
import shlex
import subprocess
import tarfile
from pathlib import Path

from controller import dispatch
from controller.workspace_store import WorkspaceError


def _remote_path(value):
    if not isinstance(value, str) or not value or '\n' in value or '\x00' in value:
        raise WorkspaceError("A remote project directory is required")
    if value.startswith('~/'):
        return '"$HOME"/' + shlex.quote(value[2:])
    return shlex.quote(value)


def stage_bundle(project, plan):
    """Copy the approved bundle only. No project-wide sync or deletion."""
    root = Path(project['path']).resolve()
    relative = f".unity-workspace/plans/{plan['id']}"
    folder = (root / relative).resolve()
    if not folder.is_relative_to(root) or not folder.is_dir():
        raise WorkspaceError("Reviewed bundle is unavailable")
    host = project.get('unity_host') or 'unity'
    if host.startswith('-') or any(c.isspace() for c in host):
        raise WorkspaceError("Invalid SSH host")
    target = _remote_path(project.get('remote_dir', ''))
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz') as archive:
        for path in sorted(folder.rglob('*')):
            if path.is_symlink():
                raise WorkspaceError("Reviewed bundles cannot contain symlinks")
            if path.is_file():
                archive.add(path, arcname=relative + '/' + str(path.relative_to(folder)), recursive=False)
        for artifact in plan.get('artifacts', []):
            for record in artifact.get('files', []):
                artifact_file = (root / record.get('frozen_path', record['path'])).resolve()
                allowed = (root / '.unity-workspace/outputs', root / '.unity-workspace/artifacts')
                if not any(artifact_file.is_relative_to(directory) for directory in allowed) or not artifact_file.is_file():
                    raise WorkspaceError('Approved prerequisite artifact is unavailable')
                import hashlib
                if hashlib.sha256(artifact_file.read_bytes()).hexdigest() != record['sha256']:
                    raise WorkspaceError('Approved prerequisite artifact changed')
                archive.add(artifact_file, arcname=str(artifact_file.relative_to(root)), recursive=False)
    env = dict(os.environ, SSH_ASKPASS_REQUIRE='never')
    result = subprocess.run(['ssh', '-oBatchMode=yes', host,
                             f'mkdir -p {target} && tar -xzf - -C {target}'],
                            input=data.getvalue(), capture_output=True, timeout=300, env=env)
    if result.returncode:
        raise WorkspaceError("Snapshot upload failed: " + result.stderr.decode(errors='replace')[-2000:])


def overrides(project, plan, stage):
    resources = stage['resources']
    mapping = {'partition': 'SLURM_PARTITION', 'cpus': 'SLURM_CPUS', 'memory': 'SLURM_MEM',
               'mem': 'SLURM_MEM', 'nodes': 'SLURM_NODES', 'gpus': 'SLURM_GPUS',
               'gpu_type': 'SLURM_GPU_TYPE', 'constraint': 'SLURM_CONSTRAINT',
               'account': 'SLURM_ACCOUNT', 'walltime': 'WALLTIME', 'ranks': 'SLURM_NTASKS'}
    overrides = dict(plan.get('runtime_overrides', {}))
    # Empty values deliberately clear inherited partition ladders and GPU requests.
    overrides.update(SLURM_PARTITION_FALLBACK='', SLURM_PARTITION_WALLTIME_CAP='',
                     SLURM_GPUS='0', SLURM_GPU_TYPE='', SLURM_CONSTRAINT='')
    overrides.update({target: str(resources[key]) for key, target in mapping.items() if key in resources})
    overrides['SLURM_MEM'] = str(resources['memory_gb']) + 'G'
    script = stage['script_path']
    overrides['JOB_COMMAND'] = 'bash ' + shlex.quote(script)
    overrides['UNITY_JOB_TEMPLATE'] = str(Path(project['path']) / '.unity-workspace' / 'plans' / plan['id'] / 'job_template.sh')
    return overrides


def submit(project, plan, stage, attempt):
    runner = Path(project['path']) / '.unity-workspace/plans' / plan['id'] / 'source/unityHPC/run.sh'
    result = dispatch.run(project['slug'], attempt['exp'], campaign=plan['id'],
                          overrides=overrides(project, plan, stage), runner_path=runner)
    if 'sbatch: error: Batch job submission failed' in result.get('output', ''):
        result['submission_outcome'] = 'rejected'
    return result
