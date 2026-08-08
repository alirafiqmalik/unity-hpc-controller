r"""Two arrays under one campaign name must not read each other's manifest.

`cmd_array` uploads the manifest to a path keyed only by the campaign name, and
each array task reads its own line out of that file AT RUNTIME. A second
`run.sh array` under the same campaign overwrote the file while the first
array's tasks were still queued, so those tasks silently ran the second array's
units under the first array's job id.

The fake `ssh` here executes the remote command locally, with $REMOTE_DIR
pointed at a real directory, so the upload and the overwrite really happen on
disk. The rendered script is copied aside after each submission because SLURM
snapshots the batch script at submit time -- the manifest is the only file the
tasks read live.
"""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

FAKE_SSH = """#!/usr/bin/env bash
# Fake `ssh <host> <command>`: run the command here, against the local
# $REMOTE_DIR. stdin passes through so `cat > ...` uploads for real.
shift
exec bash -c "$*"
"""

FAKE_SBATCH = """#!/usr/bin/env bash
# Fake sbatch: hand out a fresh parent job id per submission.
n=$(cat "$JOBID_FILE")
printf 'Submitted batch job %s\\n' "$n"
printf '%s\\n' "$((n + 1))" > "$JOBID_FILE"
exit 0
"""


def _exe(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def submit_array(tmp_project, materialise, tmp_path):
    """Submit one array for real; return (parent_job_id, snapshot of its sbatch script)."""
    remote = tmp_path / "remote"
    remote.mkdir()
    unity_dir = materialise(tmp_project, "cpu", REMOTE_DIR=str(remote))

    bindir = tmp_path / "bin"
    bindir.mkdir()
    _exe(bindir / "ssh", FAKE_SSH)
    _exe(bindir / "sbatch", FAKE_SBATCH)

    jobid_file = tmp_path / "next_jobid"
    jobid_file.write_text("4242\n")

    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()

    env = dict(os.environ)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["JOBID_FILE"] = str(jobid_file)

    def _submit(campaign: str, experiments: list[str]) -> tuple[str, Path]:
        manifest = tmp_path / f"{campaign}-{len(list(snapshots.iterdir()))}.txt"
        manifest.write_text("".join(f"{e}\n" for e in experiments))
        result = subprocess.run(
            ["bash", str(unity_dir / "run.sh"), "array", str(manifest),
             "--campaign", campaign],
            capture_output=True, text=True, env=env, cwd=tmp_project,
        )
        assert result.returncode == 0, result.stderr
        parent = next(
            line.split()[-1] for line in result.stdout.splitlines()
            if line.startswith("Submitted batch job ")
        )
        # SLURM reads the batch script once, at submit time.
        snapshot = snapshots / f"{parent}.sbatch"
        shutil.copy(remote / "_slurm" / f"{campaign}.array.sbatch", snapshot)
        return parent, snapshot

    return _submit


def task_preamble(script: Path) -> str:
    """Everything the script does before the job body, up to resolving $EXP."""
    lines = script.read_text().splitlines()
    end = next(i for i, line in enumerate(lines) if line.startswith("export EXP="))
    return "\n".join(lines[: end + 1])


def run_task(script: Path, parent: str, task_id: int,
             path_prefix: str = "") -> subprocess.CompletedProcess:
    """Replay what array task `task_id` of job `parent` does at runtime."""
    return subprocess.run(
        ["bash", "-c", f'{task_preamble(script)}\nprintf %s "$EXP"'],
        capture_output=True, text=True, timeout=30,
        env={**os.environ,
             "PATH": path_prefix + os.environ["PATH"],
             "SLURM_ARRAY_TASK_ID": str(task_id),
             "SLURM_ARRAY_JOB_ID": parent},
    )


def exp_of(script: Path, parent: str, task_id: int) -> str:
    out = run_task(script, parent, task_id)
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_second_array_does_not_hijack_the_first_arrays_units(submit_array):
    first, script_a = submit_array("camp", ["alpha", "beta", "gamma"])
    second, script_b = submit_array("camp", ["delta", "epsilon", "zeta"])
    assert first != second

    # The first array's tasks are still queued when the second is submitted.
    assert [exp_of(script_a, first, i) for i in range(3)] == \
        ["alpha", "beta", "gamma"]
    assert [exp_of(script_b, second, i) for i in range(3)] == \
        ["delta", "epsilon", "zeta"]


def test_a_task_whose_manifest_never_arrives_fails_loudly(submit_array, tmp_path):
    """Keying the manifest by job id means it lands just after sbatch replies.

    If that upload never happens, a task must say so and stop -- the whole point
    of the change is that no task ever silently runs somebody else's unit."""
    parent, script = submit_array("camp", ["alpha"])
    (tmp_path / "remote" / "_slurm" / f"camp-{parent}.manifest").unlink()

    # A no-op `sleep` so the script's wait loop retries at full speed.
    nosleep = tmp_path / "nosleep"
    nosleep.mkdir()
    _exe(nosleep / "sleep", "#!/usr/bin/env bash\nexit 0\n")

    out = run_task(script, parent, 0, path_prefix=f"{nosleep}:")
    assert out.returncode == 1, out.stdout
    assert "never appeared" in out.stderr, out.stderr
    assert out.stdout == ""


def test_a_task_outside_an_array_refuses_to_guess(submit_array):
    parent, script = submit_array("camp", ["alpha"])
    out = subprocess.run(
        ["bash", "-c", f'{task_preamble(script)}\nprintf %s "$EXP"'],
        capture_output=True, text=True, timeout=30,
        env={k: v for k, v in os.environ.items()
             if not k.startswith("SLURM_ARRAY_")},
    )
    assert out.returncode == 1, out.stdout
    assert "SLURM_ARRAY_JOB_ID is unset" in out.stderr, out.stderr
