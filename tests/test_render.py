import subprocess

import pytest


def _exported(script: str, name: str) -> str:
    """The value the job body will actually see, read back by bash itself.

    Asserting the literal `export X="v"` text is what let a quoting bug live:
    the text looked right while bash parsed it as something else."""
    import subprocess
    line = next(l for l in script.splitlines() if l.startswith(f"export {name}="))
    return subprocess.run(["bash", "-c", f'{line}; printf %s "${name}"'],
                          capture_output=True, text=True).stdout




def render(unity_dir, exp="baseline"):
    result = subprocess.run(
        ["bash", str(unity_dir / "run.sh"), "render", exp],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize("ptype", ["cpu", "gpu", "ml"])
def test_render_emits_a_valid_sbatch_script(tmp_project, materialise, ptype):
    unity_dir = materialise(tmp_project, ptype)
    script = render(unity_dir)

    assert script.startswith("#!/bin/bash\n")
    for directive in ("--job-name=baseline", "--account=pi_test_umass_edu",
                     "--time=", "--cpus-per-task=", "--mem=", "--output="):
        assert directive in script, f"missing {directive}"
    # every directive must precede the first non-comment body line
    body_start = next(
        i for i, line in enumerate(script.splitlines())
        if line and not line.startswith("#")
    )
    assert not any(
        line.startswith("#SBATCH")
        for line in script.splitlines()[body_start:]
    ), "#SBATCH directives must not appear after the script body starts"


def test_cpu_render_requests_no_gpu(tmp_project, materialise):
    script = render(materialise(tmp_project, "cpu"))
    assert "--gres=gpu" not in script


def test_gpu_render_requests_a_gpu(tmp_project, materialise):
    script = render(materialise(tmp_project, "gpu"))
    assert "--gres=gpu:1" in script


def test_gpu_type_is_honoured(tmp_project, materialise):
    unity_dir = materialise(tmp_project, "gpu", SLURM_GPU_TYPE="a100")
    assert "--gres=gpu:a100:1" in render(unity_dir)


def test_constraint_is_emitted_when_configured(tmp_project, materialise):
    unity_dir = materialise(tmp_project, "gpu", SLURM_CONSTRAINT="nvlink&hbm")
    assert "#SBATCH --constraint=nvlink&hbm" in render(unity_dir)


def test_unsafe_constraint_is_rejected(tmp_project, materialise):
    unity_dir = materialise(tmp_project, "gpu", SLURM_CONSTRAINT="a100; touch bad")
    result = subprocess.run(["bash", str(unity_dir / "run.sh"), "render", "x"],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert "invalid SLURM_CONSTRAINT" in result.stderr


def test_render_fails_clearly_when_required_env_missing(tmp_project, materialise):
    unity_dir = materialise(tmp_project, "cpu")
    (unity_dir / ".env").write_text('SLURM_ACCOUNT=""\n')
    result = subprocess.run(
        ["bash", str(unity_dir / "run.sh"), "render", "x"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "must be set" in result.stderr


def test_run_sh_rejects_unknown_subcommand(tmp_project, materialise):
    unity_dir = materialise(tmp_project, "cpu")
    result = subprocess.run(
        ["bash", str(unity_dir / "run.sh"), "frobnicate"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "usage:" in result.stderr


@pytest.mark.parametrize("ptype", ["cpu", "gpu", "ml"])
def test_render_exports_env_vars_the_job_body_needs(tmp_project, materialise, ptype):
    unity_dir = materialise(tmp_project, ptype, VENV_PATH="/work/x/.venv", MODULES="cuda/12.8")
    script = render(unity_dir)
    # the sbatch body reads these; render must bake them in because the remote
    # submitting shell never sources .env
    assert _exported(script, "VENV_PATH") == "/work/x/.venv"


def test_gpu_render_propagates_modules(tmp_project, materialise):
    script = render(materialise(tmp_project, "gpu", MODULES="cuda/12.8"))
    assert _exported(script, "MODULES") == "cuda/12.8"


def test_sync_excludes_the_remote_slurm_dir(tmp_project, materialise):
    unity_dir = materialise(tmp_project, "cpu")
    sync = (unity_dir / "sync.sh").read_text()
    assert "_slurm/" in sync and "--exclude '_slurm/'" in sync, \
        "sync.sh must exclude the remote-only _slurm/ dir from --delete"


# ─── one-off overrides ───────────────────────────────────────────────────────

def _render_with(unity_dir, env, exp="baseline"):
    import os
    full = dict(os.environ)
    full.update(env)
    result = subprocess.run(
        ["bash", str(unity_dir / "run.sh"), "render", exp],
        capture_output=True, text=True, env=full,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_caller_can_override_the_job_command_for_one_run(tmp_project, materialise):
    """A project whose real JOB_COMMAND is a four-hour GPU run must still be
    smoke-testable without editing the .env every other run depends on."""
    unity_dir = materialise(tmp_project, "gpu", JOB_COMMAND="python train.py --big")
    script = _render_with(unity_dir, {"JOB_COMMAND": "echo smoke-test"})
    assert _exported(script, "JOB_COMMAND") == "echo smoke-test"
    assert "--big" not in script


def test_caller_can_resize_a_single_run(tmp_project, materialise):
    unity_dir = materialise(tmp_project, "gpu", SLURM_MEM="64G", SLURM_CPUS="16")
    script = _render_with(unity_dir, {"SLURM_MEM": "1G", "SLURM_CPUS": "1",
                                      "SLURM_PARTITION": "cpu"})
    assert "--mem=1G" in script and "--cpus-per-task=1" in script
    assert "--partition=cpu" in script


def test_env_file_still_wins_when_the_caller_says_nothing(tmp_project, materialise):
    unity_dir = materialise(tmp_project, "gpu", SLURM_MEM="64G")
    assert "--mem=64G" in _render_with(unity_dir, {})


def test_an_explicitly_empty_override_turns_a_setting_off(tmp_project, materialise):
    """`SLURM_GPUS=` is the only way to run a GPU project's job on cpu for one
    invocation. Treating empty as "not supplied" made that impossible: a worker
    testing a GPU project could not stop the render from requesting a GPU."""
    unity_dir = materialise(tmp_project, "gpu", SLURM_GPUS="1")
    assert "--gres=gpu" in _render_with(unity_dir, {})
    assert "--gres=gpu" not in _render_with(unity_dir, {"SLURM_GPUS": ""})


def test_blanking_an_optional_setting_falls_back_to_the_default(tmp_project,
                                                                materialise):
    """Emptying a value must not produce a malformed sbatch directive."""
    unity_dir = materialise(tmp_project, "gpu", SLURM_MEM="64G")
    script = _render_with(unity_dir, {"SLURM_MEM": ""})
    assert "--mem=16G" in script and "--mem=\n" not in script


def test_blanking_a_required_setting_fails_loudly(tmp_project, materialise):
    import os
    import subprocess
    unity_dir = materialise(tmp_project, "cpu")
    env = dict(os.environ)
    env["JOB_COMMAND"] = ""
    result = subprocess.run(["bash", str(unity_dir / "run.sh"), "render", "x"],
                            capture_output=True, text=True, env=env)
    assert result.returncode == 2 and "must be set" in result.stderr


def test_overrides_do_not_leak_between_invocations(tmp_project, materialise):
    unity_dir = materialise(tmp_project, "gpu", SLURM_MEM="64G")
    _render_with(unity_dir, {"SLURM_MEM": "1G"})
    assert "--mem=64G" in _render_with(unity_dir, {})


def test_zero_gpus_means_no_gpu_not_a_malformed_request(tmp_project, materialise):
    """A real project pins SLURM_GPUS="0" in .env; that rendered
    `--gres=gpu:0`, which is not a valid request for "none"."""
    unity_dir = materialise(tmp_project, "gpu", SLURM_GPUS="0")
    script = _render_with(unity_dir, {})
    assert "--gres" not in script


def test_a_real_gpu_count_is_still_requested(tmp_project, materialise):
    unity_dir = materialise(tmp_project, "gpu", SLURM_GPUS="2")
    assert "--gres=gpu:2" in _render_with(unity_dir, {})


# ─── the generated script must survive ordinary commands and names ───────────

def _render_raw(unity_dir, env, exp="baseline"):
    import os
    full = dict(os.environ); full.update(env)
    return subprocess.run(["bash", str(unity_dir / "run.sh"), "render", exp],
                          capture_output=True, text=True, env=full)


def test_a_job_command_containing_quotes_survives(tmp_project, materialise):
    """`python train.py --name "my run"` is an ordinary command. Interpolating
    it into export JOB_COMMAND="..." closed the assignment early, so the tail
    ran as separate shell commands at export time while the job still reported
    success."""
    unity_dir = materialise(tmp_project, "cpu")
    script = _render_with(unity_dir, {"JOB_COMMAND": 'python t.py --name "my run"'})
    line = next(l for l in script.splitlines() if l.startswith("export JOB_COMMAND="))
    # bash must read back exactly the original string
    got = subprocess.run(["bash", "-c", f'{line}; printf %s "$JOB_COMMAND"'],
                         capture_output=True, text=True)
    assert got.stdout == 'python t.py --name "my run"'


def test_a_job_command_cannot_smuggle_a_second_command(tmp_project, materialise):
    """The quote break let `; rm -rf ...` execute outside the controlled eval."""
    unity_dir = materialise(tmp_project, "cpu")
    marker = tmp_project / "SHOULD_NOT_EXIST"
    script = _render_with(unity_dir, {
        "JOB_COMMAND": f'echo "hi"; touch {marker}'})
    line = next(l for l in script.splitlines() if l.startswith("export JOB_COMMAND="))
    subprocess.run(["bash", "-c", line], capture_output=True, text=True)
    assert not marker.exists(), "export line executed the smuggled command"


@pytest.mark.parametrize("value", [
    'a "quoted" phrase', "it's fine", "back`tick`", "dollar $HOME", "semi; colon",
    "new\nline", "pipe | pipe", "glob *", "paren $(id)",
])
def test_arbitrary_job_commands_round_trip(tmp_project, materialise, value):
    unity_dir = materialise(tmp_project, "cpu")
    script = _render_with(unity_dir, {"JOB_COMMAND": value})
    line = next(l for l in script.splitlines() if l.startswith("export JOB_COMMAND="))
    got = subprocess.run(["bash", "-c", f'{line}; printf %s "$JOB_COMMAND"'],
                         capture_output=True, text=True)
    assert got.stdout == value


def test_deferred_expansion_still_works(tmp_project, materialise):
    """Quoting must not break the common `--out data/$EXP` idiom: those expand
    at eval time on the node, where EXP is exported just above."""
    unity_dir = materialise(tmp_project, "cpu")
    script = _render_with(unity_dir, {"JOB_COMMAND": "echo out/$EXP"}, exp="run7")
    body = "\n".join(l for l in script.splitlines() if l.startswith("export "))
    got = subprocess.run(["bash", "-c", f'{body}; eval "echo $JOB_COMMAND"'],
                         capture_output=True, text=True)
    assert "out/run7" in got.stdout


@pytest.mark.parametrize("bad", [
    "evil; echo INJECTED", "has space", "back`tick`", "$(id)", "../escape",
    "-leading", ".leading", "pipe|pipe",
])
def test_unsafe_experiment_names_are_refused(tmp_project, materialise, bad):
    """exp becomes a SLURM job name, a filename, and part of a remote shell
    command run on the shared login node."""
    unity_dir = materialise(tmp_project, "cpu")
    result = _render_raw(unity_dir, {"JOB_COMMAND": "true"}, exp=bad)
    assert result.returncode == 2, f"accepted unsafe name {bad!r}"
    assert "invalid" in result.stderr or "must not" in result.stderr


@pytest.mark.parametrize("good", ["baseline", "lr-1e-4", "run_7", "v1.2", "a"])
def test_ordinary_experiment_names_are_accepted(tmp_project, materialise, good):
    unity_dir = materialise(tmp_project, "cpu")
    assert _render_raw(unity_dir, {"JOB_COMMAND": "true"}, exp=good).returncode == 0


def test_an_overlong_experiment_name_is_refused(tmp_project, materialise):
    unity_dir = materialise(tmp_project, "cpu")
    result = _render_raw(unity_dir, {"JOB_COMMAND": "true"}, exp="x" * 65)
    assert result.returncode == 2 and "too long" in result.stderr
