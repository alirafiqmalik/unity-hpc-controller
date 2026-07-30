import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _run(name, *args, project, **env):
    call_env = dict(os.environ, HPC_PROJECT_DIR=str(project), **env)
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / name), *args],
        text=True, capture_output=True, env=call_env,
    )


def test_results_script_uses_the_header_and_declared_metric(tmp_path):
    (tmp_path / "unityHPC").mkdir()
    (tmp_path / "unityHPC" / "metrics.json").write_text(
        json.dumps({"primary": "accuracy", "goal": "max"}))
    (tmp_path / "results.tsv").write_text(
        "revision\taccuracy\tnote\n"
        "a\t0.82\tbaseline\n"
        "b\t0.91\tbetter\n")
    result = _run("hpc-results", project=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "accuracy" in result.stdout
    assert "Best accuracy (max): b = 0.91" in result.stdout
    assert "val_bpb" not in result.stdout


def test_compare_script_uses_the_declared_metric(tmp_path):
    (tmp_path / "unityHPC").mkdir()
    (tmp_path / "unityHPC" / "metrics.json").write_text(
        json.dumps({"primary": "loss", "goal": "min"}))
    (tmp_path / "results.tsv").write_text(
        "commit\tloss\tnote\n"
        "a\t3.0\tbaseline\n"
        "b\t2.0\tbetter\n")
    result = _run("hpc-compare", "a", "b", project=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "loss delta: -1 (improvement; goal=min)" in result.stdout
    assert "val_bpb" not in result.stdout


def test_cleanup_help_and_validation_are_actionable(tmp_path):
    help_result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "hpc-cleanup"), "--help"],
        text=True, capture_output=True,
    )
    assert help_result.returncode == 0
    assert "HPC_PROJECT_DIR" in help_result.stdout
    invalid = subprocess.run(
        ["bash", str(ROOT / "scripts" / "hpc-cleanup"), "old"],
        text=True, capture_output=True,
    )
    assert invalid.returncode == 2


def test_retention_gate_help_documents_its_override():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "hpc-retention-gate"), "--help"],
        text=True, capture_output=True,
    )
    assert result.returncode == 0
    assert "UNITY_HPC_FORCE_PRUNE" in result.stdout
