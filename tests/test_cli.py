import subprocess
import sys
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
