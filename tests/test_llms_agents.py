"""llms-agents application: the evaluation scaffold and the Projects page.

The application is a dataset, a predict function and scorers. `hpc-scaffold
--application llms-agents` installs that layout. Machine Learning stays a
reserved name with no runner.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from controller.http import Request, handle
from lib import scaffold

REPO_ROOT = Path(__file__).resolve().parent.parent
APP = REPO_ROOT / "templates" / "scaffold" / "applications" / "llms-agents"
CLI = REPO_ROOT / "scripts" / "hpc-scaffold"

REQUIRED_NAMES = (
    "unityHPC/.env  (env.example)",
    "unityHPC/evaluate.py",
    "unityHPC/agent.py",
    "unityHPC/scorers.py",
    "unityHPC/project.json",
    "unityHPC/job_template.sh",
    "unityHPC/run.sh",
    "unityHPC/sync.sh",
    "dataset/example/dataset.json",
    "dataset/example/records.jsonl",
    "prompts/system.md",
)


def _call(method, path, body=None):
    raw = b"" if body is None else json.dumps(body).encode()
    resp = handle(Request(method=method, path=path, body=raw))
    payload = json.loads(resp.body.decode()) if resp.body else {}
    return resp.status, payload


def test_the_template_declares_dataset_evaluation_not_a_training_lane():
    manifest = json.loads((APP / "project.json").read_text())
    assert manifest["application"] == "llms-agents"
    assert set(manifest["workflows"]) == {"evaluate", "evaluate-smoke"}
    evaluate = manifest["workflows"]["evaluate"]
    assert [stage["id"] for stage in evaluate["stages"]] == ["evaluate"]
    assert evaluate["stages"][0]["resources"]["primitive"] == "gpu"
    assert manifest["workflows"]["evaluate-smoke"]["stages"][0]["location"] == "controller"
    assert manifest["genai"]["datasets_dir"] == "dataset"
    assert manifest["genai"]["launch"]["dataset_parameter"] == "dataset"
    assert "train" not in (APP / "README.md").read_text().lower() or "not a training" in (APP / "README.md").read_text().lower()
    readme = (APP / "README.md").read_text()
    for word in ("dataset", "scorer", "traces"):
        assert word in readme


def test_dry_run_lists_the_application_files(tmp_project):
    result = subprocess.run(
        [sys.executable, str(CLI), "--application", "llms-agents",
         "--project-dir", str(tmp_project), "--dry-run"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    for name in REQUIRED_NAMES:
        assert name in result.stdout, name
    assert "train_job.sh" not in result.stdout
    assert not (tmp_project / "unityHPC").exists()
    assert not (tmp_project / "dataset").exists()


def test_scaffold_writes_the_dataset_at_the_project_root(tmp_project):
    env = dict(os.environ, UNITY_HPC_NONINTERACTIVE="1")
    result = subprocess.run(
        [sys.executable, str(CLI), "--application", "llms-agents",
         "--project-dir", str(tmp_project), "--account", "pi_demo",
         "--remote-dir", "/work/pi_demo/u/demo",
         "--job-command", "python3 unityHPC/evaluate.py run --dataset example --model m --out evaluations/$EXP"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    records = (tmp_project / "dataset" / "example" / "records.jsonl").read_text().splitlines()
    assert len(records) == 3
    assert json.loads(records[0])["expectations"]["expected_response"] == "Paris"
    assert (tmp_project / "prompts" / "system.md").is_file()
    assert (tmp_project / "unityHPC" / "evaluate.py").is_file()
    # A second scaffold leaves the user's dataset and prompt alone.
    (tmp_project / "dataset" / "example" / "records.jsonl").write_text('{"record_id":"kept"}\n')
    (tmp_project / "prompts" / "system.md").write_text("project prompt\n")
    # The predict function and scorers are the user's code once written.
    (tmp_project / "unityHPC" / "agent.py").write_text("# my agent\n")
    (tmp_project / "unityHPC" / "scorers.py").write_text("# my scorers\n")
    again = subprocess.run(
        [sys.executable, str(CLI), "--application", "llms-agents",
         "--project-dir", str(tmp_project), "--account", "pi_demo",
         "--remote-dir", "/work/pi_demo/u/demo",
         "--job-command", "python3 unityHPC/evaluate.py run --dataset example --model m --out evaluations/$EXP"],
        capture_output=True, text=True, env=env,
    )
    assert again.returncode == 0, again.stderr
    assert (tmp_project / "dataset" / "example" / "records.jsonl").read_text() == '{"record_id":"kept"}\n'
    assert (tmp_project / "prompts" / "system.md").read_text() == "project prompt\n"
    assert (tmp_project / "unityHPC" / "agent.py").read_text() == "# my agent\n"
    assert (tmp_project / "unityHPC" / "scorers.py").read_text() == "# my scorers\n"


def test_machine_learning_is_reserved_and_has_no_runner(tmp_project):
    root = scaffold.template_root() / "applications" / "machine-learning"
    files = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
    assert files == ["README.md"]
    result = subprocess.run(
        [sys.executable, str(CLI), "--application", "machine-learning",
         "--project-dir", str(tmp_project), "--dry-run"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "reserved" in (result.stderr + result.stdout)
    assert not (tmp_project / "unityHPC").exists()


def test_attach_stores_llms_agents_without_a_cluster(tmp_project, tmp_data_dir, monkeypatch):
    """Re-attach keeps the slug, remote_dir, and ledger bytes. No SSH."""
    unity = tmp_project / "unityHPC"
    unity.mkdir()
    ledger = tmp_project / ".unity_state" / "c1.db"
    ledger.parent.mkdir()
    ledger.write_bytes(b"ledger-bytes-stay")
    remote = "/work/pi_yourlab_umass_edu/you/llm_thinking_trace"

    def boom(*_args, **_kwargs):
        raise AssertionError("attach must not open a cluster connection")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)

    from controller import registry
    registry.attach(
        "llm-thinking-trace", tmp_project, primitive="gpu", remote_dir=remote,
    )
    status, body = _call("POST", "/api/v1/projects", {
        "slug": "llm-thinking-trace",
        "path": str(tmp_project),
        "application": "llms-agents",
    })
    assert status == 201, body
    project = body["project"]
    assert project["slug"] == "llm-thinking-trace"
    assert project["application"] == "llms-agents"
    assert project["remote_dir"] == remote
    assert project["primitive"] == "gpu"
    assert ledger.read_bytes() == b"ledger-bytes-stay"

    status, body = _call("POST", "/api/v1/projects", {
        "slug": "reserved-ml",
        "path": str(tmp_project),
        "application": "machine-learning",
    })
    assert status == 400
    assert "reserved" in body["error"]


def test_projects_page_offers_both_applications_and_hides_ml_as_one():
    page = (REPO_ROOT / "controller/web/src/pages/JobsProjectPage.tsx").read_text()
    formats = (REPO_ROOT / "controller/web/src/modules/controller/format.ts").read_text()
    routes = (REPO_ROOT / "controller/web/src/modules/navigation/routes.ts").read_text()
    app = (REPO_ROOT / "controller/web/src/App.tsx").read_text()
    assert "LLMs & Agents" in formats
    assert "Machine Learning" in formats
    assert "llms-agents" in formats
    assert "runnable: false" in formats
    assert "APPLICATION_OPTIONS" in page
    assert "project.application" in page
    assert "reserved" in page
    assert "export const PRIMITIVES = ['cpu', 'gpu', 'multi-cpu', 'multi-gpu']" in formats
    assert "GENAI_APPLICATION = 'llms-agents'" in routes
    assert 'path="traces"' in app
    assert 'path="datasets"' in app
    assert 'path="evaluations"' in app


def test_the_job_reads_the_model_endpoint_from_the_synced_env(tmp_path):
    """run.sh exports a fixed list; the job itself loads LLM_* from unityHPC/.env."""
    import re
    template = (APP / "job_template.sh").read_text()
    block = re.search(r"^if \[ -f unityHPC/\.env \]; then\n.*?^fi\n", template, re.S | re.M).group(0)
    (tmp_path / "unityHPC").mkdir()
    (tmp_path / "unityHPC" / ".env").write_text(
        'LLM_BASE_URL="https://api.example/v1"   # hosted\n  export LLM_API_KEY="secret"\nLLM_TIMEOUT_S="30"\nSLURM_ACCOUNT="x"\n')
    script = "set -euo pipefail\n" + block + 'echo "$LLM_BASE_URL|$LLM_API_KEY|$LLM_TIMEOUT_S|${SLURM_ACCOUNT:-unset}"\n'
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LLM_", "SLURM_"))}
    result = subprocess.run(["bash", "-c", script], cwd=tmp_path, capture_output=True, text=True,
                            env={**env, "LLM_TIMEOUT_S": "99"})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "https://api.example/v1|secret|99|unset"


def test_unassessed_records_stay_out_of_the_run_metrics(tmp_project):
    env = dict(os.environ, UNITY_HPC_NONINTERACTIVE="1")
    result = subprocess.run(
        [sys.executable, str(CLI), "--application", "llms-agents", "--project-dir", str(tmp_project),
         "--account", "pi_demo", "--remote-dir", "/work/pi_demo/u/demo",
         "--job-command", "python3 unityHPC/evaluate.py run --dataset example --model m --out evaluations/$EXP"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    records = tmp_project / "dataset" / "example" / "records.jsonl"
    records.write_text(
        json.dumps({"record_id": "labeled", "inputs": {"question": "hi"}, "expectations": {"expected_response": "mock answer"}}) + "\n"
        + json.dumps({"record_id": "unlabeled", "inputs": {"question": "bye"}}) + "\n")
    run = subprocess.run(
        [sys.executable, "unityHPC/evaluate.py", "run", "--dataset", "example", "--model", "mock", "--mock", "true",
         "--out", "evaluations/mixed"],
        cwd=tmp_project, capture_output=True, text=True,
    )
    assert run.returncode == 0, run.stderr
    manifest = json.loads((tmp_project / "evaluations" / "mixed" / "manifest.json").read_text())
    assert manifest["metrics"]["correctness_rate"] == 1.0, "the unlabeled record is not a failure"
