import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


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
