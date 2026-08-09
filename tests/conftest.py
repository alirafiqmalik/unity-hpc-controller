import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# run.sh wraps every ssh call in `timeout`, so a dispatcher test that stubs ssh
# alone still reaches the real one. Logging the call is what lets a test assert
# the wrapper is there at all.
STUB_TIMEOUT = r"""#!/usr/bin/env bash
printf 'timeout %s\n' "$*" >>"$STUB_LOG"
shift 2
exec "$@"
"""


@pytest.fixture
def tmp_project(tmp_path, monkeypatch):
    """An empty, non-git project directory with CLAUDE_PLUGIN_ROOT pointed at the repo."""
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(REPO_ROOT))
    project = tmp_path / "proj"
    project.mkdir()
    return project


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """A fresh $UNITY_HPC_DATA with a locks/ subdir. Readers resolve it at call time."""
    d = tmp_path / "data"
    (d / "locks").mkdir(parents=True)
    monkeypatch.setenv("UNITY_HPC_DATA", str(d))
    return d


@pytest.fixture
def make_dispatcher(tmp_project, materialise, tmp_path):
    """Build a callable that drives the generated run.sh against stub commands.

    Every dispatcher test needs the same five things — a materialised project, a
    bin/ of stubs first on PATH, a shared log the stubs append to, a per-call
    copy of the environment, and a subprocess run rooted in the project. What
    differs between them is only WHICH stubs and which canned replies, so those
    are the arguments:

      STUBS         command name -> script body. `timeout` is always stubbed.
      ENV_DEFAULTS  seed values the stubs read (STUB_SBATCH, STUB_SACCT, ...).

    The returned callable takes run.sh's argv plus per-call environment
    overrides, and carries `.project`, `.log` and `.sbatch_calls()`.
    """
    def _make(stubs, **env_defaults):
        unity_dir = materialise(tmp_project, "cpu")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        for name, body in {"timeout": STUB_TIMEOUT, **stubs}.items():
            p = bin_dir / name
            p.write_text(body)
            p.chmod(0o755)

        log = tmp_path / "stub.log"
        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["STUB_LOG"] = str(log)
        env.update({k: str(v) for k, v in env_defaults.items()})

        def run(*args, **overrides):
            # A fresh copy per call: sharing one dict makes concurrent
            # invocations race on the stub's canned output rather than on the
            # code under test.
            call_env = dict(env)
            call_env.update({k: str(v) for k, v in overrides.items()})
            return subprocess.run(
                ["bash", str(unity_dir / "run.sh"), *args],
                capture_output=True, text=True, env=call_env, cwd=str(tmp_project),
            )

        def sbatch_calls():
            """The remote submit commands the stub ssh saw, in order. Empty
            when the log is absent: a dry-run never touches the cluster."""
            if not log.exists():
                return []
            return [line for line in log.read_text().splitlines()
                    if line.startswith("cd ") and "&& sbatch" in line]

        run.project = tmp_project
        run.log = log
        run.sbatch_calls = sbatch_calls
        return run

    return _make


@pytest.fixture
def materialise():
    """Write a scaffold to disk with a usable .env. Returns the unityHPC/ dir."""
    from lib import scaffold

    def _materialise(project_dir: Path, ptype: str, **env) -> Path:
        dest = project_dir / "unityHPC"
        dest.mkdir(parents=True, exist_ok=True)
        for action in scaffold.plan(project_dir, ptype):
            action.path.write_text(action.content)
        # APPEND the required values (and any overrides) so the type-specific
        # defaults in the generated .env survive. run.sh sources top-to-bottom,
        # so a later assignment wins — this is how a gpu project keeps SLURM_GPUS=1.
        settings = {
            "SLURM_ACCOUNT": "pi_test_umass_edu",
            "REMOTE_DIR": "/work/pi_test_umass_edu/tester/proj",
            "JOB_COMMAND": "python pipeline.py",
        }
        settings.update(env)
        extra = "".join(f'{k}="{v}"\n' for k, v in settings.items())
        with (dest / ".env").open("a") as fh:
            fh.write("\n# --- test overrides ---\n" + extra)
        return dest

    return _materialise
