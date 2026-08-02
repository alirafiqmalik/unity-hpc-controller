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


def _env_of(tmp_project):
    return (tmp_project / "unityHPC" / ".env").read_text()


def _assignments(text, key):
    """Every uncommented assignment of `key`, in file order."""
    return [line for line in text.splitlines()
            if line.strip().startswith(f"{key}=")]


def test_supplied_values_replace_the_placeholders_rather_than_duplicating_them(tmp_project):
    """The generated file defined six keys twice -- once blank from the
    template, once appended with the real value. Sourcing it works, because the
    last assignment wins, but anything that PARSES the file reads the empty one,
    and hand-editing it means guessing which line matters."""
    result = run_cli(
        "--type", "gpu", "--project-dir", str(tmp_project), "--non-interactive",
        "--account", "pi_test", "--remote-dir", "/work/pi_test/user/project",
        "--job-command", "python infer.py", "--constraint", "sm_80&vram48",
    )
    assert result.returncode == 0, result.stderr
    env = _env_of(tmp_project)
    for key in ("SLURM_ACCOUNT", "REMOTE_DIR", "JOB_COMMAND", "SLURM_CONSTRAINT"):
        assert len(_assignments(env, key)) == 1, f"{key} is defined more than once:\n{env}"
    assert "# --- added by hpc-scaffold ---" not in env, \
        "every key the template ships must be filled in place, not appended"


def test_substitution_keeps_the_documenting_comment(tmp_project):
    run_cli("--type", "gpu", "--project-dir", str(tmp_project), "--non-interactive",
            "--account", "pi_test", "--remote-dir", "/work/x", "--job-command", "true")
    line = _assignments(_env_of(tmp_project), "SLURM_ACCOUNT")[0]
    assert "pi_test" in line
    assert "# e.g. pi_yourlab_umass_edu" in line, line


def test_a_value_containing_a_hash_is_not_mistaken_for_a_comment(tmp_project):
    run_cli("--type", "cpu", "--project-dir", str(tmp_project), "--non-interactive",
            "--account", "pi_test", "--remote-dir", "/work/x",
            "--job-command", "python run.py --tag build#1")
    env = _env_of(tmp_project)
    assert "build#1" in env
    assert len(_assignments(env, "JOB_COMMAND")) == 1


def test_environment_flags_reach_the_env_file(tmp_project):
    """VENV_PATH, MODULES and HF_HOME are read by the job template and shipped
    blank with no way to set them, so a GPU job ran the system python with no
    framework installed and the plugin could not say why."""
    result = run_cli(
        "--type", "gpu", "--project-dir", str(tmp_project), "--non-interactive",
        "--account", "pi_test", "--remote-dir", "/work/pi_test/p",
        "--job-command", "python infer.py", "--venv", "/work/pi_test/p/.venv",
        "--modules", "cuda/12.8", "--hf-home", "/work/pi_test/hf",
        "--results-dir", "/work/pi_test/p/out",
    )
    assert result.returncode == 0, result.stderr
    env = _env_of(tmp_project)
    assert "VENV_PATH=/work/pi_test/p/.venv" in env
    assert "MODULES=cuda/12.8" in env
    assert "HF_HOME=/work/pi_test/hf" in env
    assert "REMOTE_RESULTS_DIR=/work/pi_test/p/out" in env
    for key in ("VENV_PATH", "MODULES", "HF_HOME", "REMOTE_RESULTS_DIR"):
        assert len(_assignments(env, key)) == 1, key


def test_rerunning_with_new_values_does_not_stack_assignments(tmp_project):
    for account in ("pi_first", "pi_second"):
        run_cli("--type", "cpu", "--project-dir", str(tmp_project), "--non-interactive",
                "--account", account, "--remote-dir", "/work/x", "--job-command", "true")
    lines = _assignments(_env_of(tmp_project), "SLURM_ACCOUNT")
    assert len(lines) == 1 and "pi_second" in lines[0]


def test_an_existing_duplicate_is_made_consistent(tmp_project):
    """Repair path for a .env written by the version that appended."""
    unity = tmp_project / "unityHPC"
    unity.mkdir()
    (unity / ".env").write_text(
        'SLURM_ACCOUNT=""\nREMOTE_DIR="/work/x"\nJOB_COMMAND="true"\n'
        "\n# --- hpc-scaffold non-interactive settings ---\n"
        "SLURM_ACCOUNT=pi_old\n")
    run_cli("--type", "cpu", "--project-dir", str(tmp_project), "--non-interactive",
            "--account", "pi_new")
    lines = _assignments(_env_of(tmp_project), "SLURM_ACCOUNT")
    assert lines and all("pi_new" in line for line in lines), lines


def test_write_guidance_still_never_overwrites_existing_prose(tmp_project):
    (tmp_project / "CLAUDE.md").write_text("# My notes\nHand written.\n")
    run_cli("--type", "cpu", "--project-dir", str(tmp_project), "--write-guidance")
    assert (tmp_project / "CLAUDE.md").read_text() == "# My notes\nHand written.\n"


def test_refresh_guidance_marker_stamps_an_existing_file(tmp_project):
    """The finding fires only when CLAUDE.md exists, and --write-guidance only
    acts when it does not, so doctor's advice could never resolve it."""
    claude = tmp_project / "CLAUDE.md"
    claude.write_text("# Unity Cluster\nUse unityHPC/run.sh run job.\n")
    result = run_cli("--type", "cpu", "--project-dir", str(tmp_project),
                     "--refresh-guidance-marker")
    assert result.returncode == 0, result.stderr
    text = claude.read_text()
    assert "unity-hpc-guidance:" in text
    assert "Use unityHPC/run.sh run job." in text, "prose must survive"


def test_refresh_guidance_marker_replaces_an_older_stamp(tmp_project):
    claude = tmp_project / "CLAUDE.md"
    claude.write_text("# Unity Cluster\n<!-- unity-hpc-guidance: 0.0.1 -->\nprose\n")
    run_cli("--type", "cpu", "--project-dir", str(tmp_project),
            "--refresh-guidance-marker")
    text = claude.read_text()
    assert "0.0.1" not in text
    assert text.count("unity-hpc-guidance:") == 1, text


def test_refresh_guidance_marker_is_idempotent(tmp_project):
    claude = tmp_project / "CLAUDE.md"
    claude.write_text("# Unity Cluster\nprose\n")
    run_cli("--type", "cpu", "--project-dir", str(tmp_project),
            "--refresh-guidance-marker")
    once = claude.read_text()
    run_cli("--type", "cpu", "--project-dir", str(tmp_project),
            "--refresh-guidance-marker")
    assert claude.read_text() == once


def test_refresh_guidance_marker_reports_a_missing_file(tmp_project):
    result = run_cli("--type", "cpu", "--project-dir", str(tmp_project),
                     "--refresh-guidance-marker")
    assert result.returncode == 0, result.stderr
    assert "--write-guidance" in result.stdout
    assert not (tmp_project / "CLAUDE.md").exists()
