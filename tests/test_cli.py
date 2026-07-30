import subprocess
import sys
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI = REPO_ROOT / "scripts" / "hpc-scaffold"


def run_cli(*args, cwd=None):
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True, text=True, cwd=cwd,
    )


def test_dry_run_reports_without_writing(tmp_project):
    result = run_cli("--type", "cpu", "--project-dir", str(tmp_project), "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "run.sh" in result.stdout
    assert not (tmp_project / "unityHPC").exists(), "--dry-run must not write"


def test_generates_the_scaffold(tmp_project):
    result = run_cli("--type", "cpu", "--project-dir", str(tmp_project))
    assert result.returncode == 0, result.stderr
    unity = tmp_project / "unityHPC"
    for name in ("run.sh", "job_template.sh", "sync.sh", ".env"):
        assert (unity / name).exists(), f"{name} not generated"
    assert (unity / "run.sh").stat().st_mode & 0o111, "run.sh must be executable"


def test_unknown_type_exits_two_with_a_useful_message(tmp_project):
    result = run_cli("--type", "quantum", "--project-dir", str(tmp_project))
    assert result.returncode == 2
    assert "quantum" in (result.stderr + result.stdout)


def test_defaults_to_cwd(tmp_project):
    result = run_cli("--type", "cpu", cwd=str(tmp_project))
    assert result.returncode == 0, result.stderr
    assert (tmp_project / "unityHPC" / "run.sh").exists()


def test_nonexistent_project_dir_exits_two(tmp_path):
    missing = tmp_path / "does-not-exist"
    result = run_cli("--type", "cpu", "--project-dir", str(missing))
    assert result.returncode == 2
    assert "not a directory" in (result.stderr + result.stdout).lower()


def test_project_dir_that_is_a_file_exits_two(tmp_path):
    a_file = tmp_path / "afile"
    a_file.write_text("x")
    result = run_cli("--type", "cpu", "--project-dir", str(a_file))
    assert result.returncode == 2


def test_noninteractive_setup_requires_complete_config(tmp_project):
    env = dict(os.environ, UNITY_HPC_NONINTERACTIVE="1")
    result = subprocess.run(
        [sys.executable, str(CLI), "--type", "cpu", "--project-dir", str(tmp_project)],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 2
    assert "SLURM_ACCOUNT" in result.stderr and "JOB_COMMAND" in result.stderr


def test_noninteractive_setup_writes_quoted_explicit_values(tmp_project):
    result = run_cli(
        "--type", "cpu", "--project-dir", str(tmp_project), "--non-interactive",
        "--account", "pi_test", "--remote-dir", "/work/pi_test/user/project",
        "--job-command", 'python run.py --name "a b"', "--constraint", "avx512",
        "--write-guidance",
    )
    assert result.returncode == 0, result.stderr
    env = (tmp_project / "unityHPC" / ".env").read_text()
    assert "SLURM_ACCOUNT=pi_test" in env
    assert "REMOTE_DIR=/work/pi_test/user/project" in env
    assert "SLURM_CONSTRAINT=avx512" in env
    assert 'unity-hpc-guidance:' in (tmp_project / "CLAUDE.md").read_text()


def test_noninteractive_setup_accepts_existing_quoted_config(tmp_project):
    unity = tmp_project / "unityHPC"
    unity.mkdir()
    (unity / ".env").write_text(
        'SLURM_ACCOUNT="pi_test"\nREMOTE_DIR="/work/pi_test/project"\n'
        'JOB_COMMAND="python run.py --flag value"\n')
    result = run_cli("--type", "cpu", "--project-dir", str(tmp_project), "--non-interactive")
    assert result.returncode == 0, result.stderr
