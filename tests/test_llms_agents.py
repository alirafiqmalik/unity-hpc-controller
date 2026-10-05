"""llms-agents application: scaffold, stage runner, and the Projects page."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

import pytest

from controller.http import Request, handle
from lib import scaffold

REPO_ROOT = Path(__file__).resolve().parent.parent
APP = REPO_ROOT / "templates" / "scaffold" / "applications" / "llms-agents"
LIVE = Path("/home/ahm/Desktop/project/research/ai-ml/experiments/llm-thinking-trace")
CLI = REPO_ROOT / "scripts" / "hpc-scaffold"
FICTIONAL = LIVE / "datasets" / "fictionalgeoqa" / "fictionalgeoqa.jsonl"

REQUIRED_NAMES = (
    "env.example",
    "train_job.sh",
    "eval_job.sh",
    "prep.py",
    "workflow.example.yaml",
    "configs/sft.yaml",
    "configs/dpo.yaml",
    "configs/fsdp.yaml",
    "configs/deepspeed_zero3.json",
    "run.sh",
    "sync.sh",
)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"llms_agents_{name}", APP / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def prep():
    return _load("prep")


@pytest.fixture(scope="module")
def workflow():
    return _load("workflow")


def _call(method, path, body=None):
    raw = b"" if body is None else json.dumps(body).encode()
    resp = handle(Request(method=method, path=path, body=raw))
    payload = json.loads(resp.body.decode()) if resp.body else {}
    return resp.status, payload


def test_example_workflow_declares_the_train_lane(workflow):
    doc = workflow.load_workflow(APP / "workflow.example.yaml")
    assert [stage["id"] for stage in doc["stages"]] == ["prep", "train", "consolidate", "eval"]
    assert doc["dataset"]["adapter"] == "qa-object"
    assert doc["stages"][1]["resources"]["primitive"] == "gpu"
    assert doc["stages"][3]["eval"]["kind"] == "lm-eval"
    assert doc["agent_stages"][0]["location"] == "controller"


def test_dry_run_lists_the_application_files(tmp_project):
    result = subprocess.run(
        [sys.executable, str(CLI), "--application", "llms-agents",
         "--project-dir", str(tmp_project), "--dry-run"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    for name in REQUIRED_NAMES:
        assert name in result.stdout, name
    assert not (tmp_project / "unityHPC").exists()


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


def test_train_sbatch_selects_fsdp_or_deepspeed(workflow):
    fsdp = workflow.render_train_sbatch(parallel="fsdp")
    deepspeed = workflow.render_train_sbatch(parallel="deepspeed")
    for script in (fsdp, deepspeed):
        for token in ("MASTER_ADDR", "MASTER_PORT", "WORLD_SIZE", "RANK"):
            assert token in script
        assert "--rdzv_backend=c10d" in script
        assert "--rdzv_endpoint=" in script
        subprocess.run(["bash", "-n"], input=script, text=True, check=True)
    assert "export LLMS_PARALLEL=fsdp" in fsdp
    assert "configs/fsdp.yaml" in fsdp
    assert 'LLMS_PARALLEL_CONFIG="${LLMS_APP_DIR:-$REMOTE_DIR/unityHPC}/configs/fsdp.yaml"' in fsdp
    assert "export LLMS_PARALLEL=deepspeed" in deepspeed
    assert "configs/deepspeed_zero3.json" in deepspeed
    assert "configs/deepspeed_zero3.json" in (
        deepspeed.split("export LLMS_PARALLEL_CONFIG=", 1)[1].split("\n", 1)[0]
    )


def test_eval_sbatch_is_afterok_and_lm_eval(workflow):
    script = workflow.render_eval_sbatch(parent_job_id="4242", eval_kind="lm-eval")
    assert "#SBATCH --dependency=afterok:4242" in script
    assert "vllm.entrypoints.openai.api_server" in script
    assert "lm_eval" in script
    assert "--model local-completions" in script
    assert "http://127.0.0.1:" in script
    assert "afterany" not in script
    assert "export LLMS_EVAL_KIND=lm-eval" in script
    subprocess.run(["bash", "-n"], input=script, text=True, check=True)


def _fictional_line() -> str:
    assert FICTIONAL.is_file(), FICTIONAL
    return FICTIONAL.read_text(encoding="utf-8").splitlines()[0]


def test_prep_sharegpt_and_native_on_fictionalgeoqa(prep, tmp_path):
    source = _fictional_line()
    native = prep.convert_line(source, "native")
    assert native == source.rstrip("\n")
    share = prep.convert_line(source, "sharegpt", adapter="qa-object")
    row = json.loads(share)
    assert row["conversations"][0]["from"] == "human"
    assert "longest river" in row["conversations"][0]["value"]
    assert row["conversations"][1]["from"] == "gpt"
    assert row["conversations"][1]["value"] == "Kolufori River"
    preference = json.loads(prep.convert_line(source, "preference", adapter="qa-object"))
    assert set(preference) == {"prompt", "chosen", "rejected"}
    assert preference["chosen"] == "Kolufori River"

    remote = tmp_path / "remote"
    dest = prep.prepare(FICTIONAL, remote, fmt="sharegpt", adapter="qa-object")
    assert "_cache/llms-agents" in dest.as_posix()
    assert (dest / "shard.jsonl").is_file()
    assert (dest / "shard.arrow").is_file()
    try:
        import pyarrow.ipc as ipc
    except ImportError:
        assert (dest / "shard.arrow").stat().st_size > 32
    else:
        table = ipc.open_stream(dest / "shard.arrow").read_all()
        assert "longest river" in table.column("text")[0].as_py()


def test_two_stages_render_afterok_and_stranded_check_does_not_submit(workflow, tmp_path, monkeypatch):
    spec = {
        "stages": [
            {
                "id": "prep",
                "depends_on": [],
                "command": ["python3", "unityHPC/prep.py", "convert"],
                "resources": {
                    "primitive": "cpu", "cpus": 2, "memory": "4G", "walltime": "00:10:00",
                },
                "outputs": [{"path": "corpus/manifest.json"}],
            },
            {
                "id": "train",
                "depends_on": ["prep"],
                "resources": {
                    "primitive": "gpu", "gpus": 4, "cpus": 8, "memory": "64G",
                    "walltime": "01:00:00",
                },
            },
        ]
    }
    lines = workflow.plan_invocations(spec, campaign="c1", job_ids={"prep": "1001"})
    assert len(lines) == 2
    assert "unityHPC/run.sh run prep" in lines[0]
    assert "--campaign c1" in lines[0]
    assert "WALLTIME=00:10:00" in lines[0]
    assert "SLURM_GPUS=0" in lines[0]
    assert "afterok" not in lines[0]
    assert "unityHPC/run.sh run train" in lines[1]
    assert "--dependency=afterok:1001" in lines[1]
    assert "SLURM_GPUS=4" in lines[1]
    assert "afterany" not in lines[1]

    root = tmp_path / "prep-out"
    (root / "corpus").mkdir(parents=True)
    (root / "corpus" / "manifest.json").write_text('{"done": 1}\n', encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise AssertionError("stranded check must not call sbatch")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    findings = workflow.stranded_stages(
        spec,
        [{"job_id": "64309858", "stage": "prep", "status": "FAILED"}],
        {"prep": root},
    )
    assert findings == [{
        "stage": "prep",
        "job_id": "64309858",
        "status": "FAILED",
        "verdict": "STRANDED",
        "detail": "parent is marked failed and its declared outputs are complete",
    }]
    missing = tmp_path / "empty"
    missing.mkdir()
    assert workflow.stranded_stages(
        spec,
        [{"job_id": "1", "stage": "prep", "status": "FAILED"}],
        {"prep": missing},
    ) == []


def test_resume_slot_fills_the_checkpoint_dir(workflow):
    stage = {
        "id": "t1",
        "resume": ["python3", "unityHPC/workspace_adapter.py", "resume",
                   "--resume-from", "{checkpoint_dir}"],
    }
    argv = workflow.resume_argv(stage, "/tmp/ckpt")
    assert argv[-1] == "/tmp/ckpt"
    assert "resume" in argv


def test_live_mock_smoke_exits_zero(workflow, tmp_path):
    if not (LIVE / "unityHPC" / "workspace_adapter.py").is_file():
        pytest.skip("live llm-thinking-trace tree is not on this machine")
    out = tmp_path / "smoke"
    code = workflow.run_project_command(
        [
            sys.executable, "unityHPC/workspace_adapter.py", "collect",
            "--model", "r1-distill-qwen-1.5b",
            "--out", "{output_dir}",
            "--execution-id", "template-smoke",
            "--variant-id", "mock",
            "--purpose", "smoke-test",
            "--mock", "true",
            "--n-items", "1",
            "--k", "1",
            "--max-turns", "1",
            "--max-tokens-per-turn", "128",
        ],
        cwd=LIVE,
        substitutions={"output_dir": str(out)},
    )
    assert code == 0
    assert (out / "corpus" / "manifest.json").is_file()


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
    panel = (REPO_ROOT / "controller/web/src/modules/panels/ProjectPanel.tsx").read_text()
    formats = (REPO_ROOT / "controller/web/src/modules/controller/format.ts").read_text()
    assert "LLMs & Agents" in formats
    assert "Machine Learning" in formats
    assert "llms-agents" in formats
    assert "runnable: false" in formats
    assert "APPLICATION_OPTIONS" in page
    assert "project.application || project.primitive" in page
    assert "reserved" in page
    assert "export const PRIMITIVES = ['cpu', 'gpu', 'multi-cpu', 'multi-gpu']" in formats
    assert "project?.application || project?.primitive" in panel
    assert "!runnable" in panel
