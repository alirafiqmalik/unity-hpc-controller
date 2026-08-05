r"""The array sbatch script must be valid bash and select the right manifest line.

`run.sh array` had no test, and the script it emitted had never parsed: printf
passed the format's backslashes through verbatim (printf defines no \" or \$
escape), so the EXP line contained a bare `((` and every array task died with
`syntax error near unexpected token '('` before the job template ran.

There is no `render array` subcommand, so these tests run `cmd_array` for real
against a fake `ssh` on PATH that captures what would have reached the cluster.
"""
import os
import stat
import subprocess
from pathlib import Path

import pytest

FAKE_SSH = """#!/usr/bin/env bash
# Fake `ssh <host> <command>` for cmd_array. Records the sbatch script and
# answers sbatch; everything else succeeds silently.
shift  # drop the host
case "$*" in
    *"cat > "*.array.sbatch)
        cat > "$CAPTURE_DIR/array.sbatch" ;;
    *sbatch*)
        echo "Submitted batch job 4242" ;;
    *"cat > "*)
        cat > /dev/null ;;
esac
exit 0
"""


@pytest.fixture
def captured_array_script(tmp_project, materialise, tmp_path):
    """Run `run.sh array` against the fake ssh; return the captured sbatch script."""
    unity_dir = materialise(tmp_project, "cpu")

    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "ssh"
    fake.write_text(FAKE_SSH)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)

    capture_dir = tmp_path / "capture"
    capture_dir.mkdir()

    manifest = tmp_path / "variants.txt"
    manifest.write_text("alpha\nbeta\ngamma\n")

    env = dict(os.environ)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["CAPTURE_DIR"] = str(capture_dir)

    result = subprocess.run(
        ["bash", str(unity_dir / "run.sh"), "array", str(manifest),
         "--campaign", "camp"],
        capture_output=True, text=True, env=env, cwd=tmp_project,
    )
    assert result.returncode == 0, result.stderr
    script = capture_dir / "array.sbatch"
    assert script.is_file(), "cmd_array never wrote the sbatch script"
    return script.read_text()


def test_array_script_is_valid_bash(captured_array_script, tmp_path):
    path = tmp_path / "check.sbatch"
    path.write_text(captured_array_script)
    result = subprocess.run(["bash", "-n", str(path)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_array_task_reads_its_own_manifest_line(captured_array_script, tmp_path):
    exp_line = next(
        line for line in captured_array_script.splitlines()
        if line.startswith("export EXP=")
    )
    # Reproduce what task N does at runtime, against a local manifest copy.
    manifest = tmp_path / "m.manifest"
    manifest.write_text("alpha\nbeta\ngamma\n")
    remote_path = next(
        tok for tok in exp_line.replace(")", " ").split()
        if tok.endswith(".manifest")
    )
    line = exp_line.replace(remote_path, str(manifest))
    for task_id, expected in [(0, "alpha"), (1, "beta"), (2, "gamma")]:
        out = subprocess.run(
            ["bash", "-c", f'{line}; printf %s "$EXP"'],
            capture_output=True, text=True,
            env={**os.environ, "SLURM_ARRAY_TASK_ID": str(task_id)},
        )
        assert out.returncode == 0, out.stderr
        assert out.stdout == expected


def test_array_header_covers_every_manifest_line(captured_array_script):
    assert "#SBATCH --array=0-2\n" in captured_array_script
