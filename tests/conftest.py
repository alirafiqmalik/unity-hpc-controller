import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """A fresh $UNITY_HPC_DATA with a locks/ subdir. Readers resolve it at call time."""
    d = tmp_path / "data"
    (d / "locks").mkdir(parents=True)
    monkeypatch.setenv("UNITY_HPC_DATA", str(d))
    return d
