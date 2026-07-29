import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI = REPO_ROOT / "scripts" / "hpc-scaffold"


def test_fresh_non_git_project_reaches_a_rendered_sbatch(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(REPO_ROOT))
    project = tmp_path / "hermes"
    project.mkdir()
    assert not (project / ".git").exists(), "this scenario is a non-git project"

    # 1. generate the scaffold
    result = subprocess.run(
        [sys.executable, str(CLI), "--type", "cpu", "--project-dir", str(project)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr

    # 2. fill in the three required values
    (project / "unityHPC" / ".env").write_text(
        'SLURM_ACCOUNT="pi_test_umass_edu"\n'
        'REMOTE_DIR="/work/pi_test_umass_edu/tester/hermes"\n'
        'JOB_COMMAND="python synthesise.py"\n'
        'WALLTIME="08:00:00"\n'
    )

    # 3. render an sbatch script without touching the cluster
    render = subprocess.run(
        ["bash", str(project / "unityHPC" / "run.sh"), "render", "synth"],
        capture_output=True, text=True,
    )
    assert render.returncode == 0, render.stderr
    assert "#SBATCH --job-name=synth" in render.stdout
    assert "#SBATCH --time=08:00:00" in render.stdout
    # read the value back through bash rather than matching the literal text:
    # the export line is shell-quoted so arbitrary commands survive intact
    job_line = next(l for l in render.stdout.splitlines()
                    if l.startswith("export JOB_COMMAND="))
    got = subprocess.run(["bash", "-c", f'{job_line}; printf %s "$JOB_COMMAND"'],
                         capture_output=True, text=True).stdout
    assert got == "python synthesise.py"
    assert "--gres=gpu" not in render.stdout, "a cpu project must request no GPU"
    assert "torchrun" not in render.stdout
