"""The Hardware class uses one match rule and preserves stored and delivered evidence."""
import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from controller import attestation, hardware_class
from controller.campaign_slurm import script


FIXTURES = Path(__file__).parent / "fixtures"
A100 = {"gpu_count": 1, "expected_gpu_name": "NVIDIA A100-SXM4-80GB",
        "expected_gpu_memory_mb": 81920, "gpu_memory_tolerance_mb": 0}
GPU = {"uuid": "GPU-a", "name": "NVIDIA A100-SXM4-80GB", "memory_mb": 81920}
VERIFIED = {"verified": True, "task_id": "model-a", "attempt": 1, "gpus": [GPU]}


@pytest.mark.parametrize("changes,gpus,expected", [
    ({}, [GPU], None),
    ({}, [], "count"),
    ({}, [GPU, GPU], "count"),
    ({}, [{**GPU, "name": "NVIDIA A100-PCIE-40GB"}], "name"),
    ({}, [{**GPU, "name": "NVIDIA A100-PCIE-40GB", "memory_mb": 40960}], "name"),
    ({"gpu_memory_tolerance_mb": 1024}, [{**GPU, "memory_mb": 80896}], None),
    ({"gpu_memory_tolerance_mb": 1024}, [{**GPU, "memory_mb": 80895}], "memory"),
    ({}, [{**GPU, "memory_mb": 81919}], "memory"),
    ({"expected_gpu_uuid": "GPU-a"}, [GPU], None),
    ({"expected_gpu_uuid": "GPU-z"}, [GPU], "uuid"),
    ({"expected_gpu_uuid": ""}, [GPU], None),
    ({}, [{k: v for k, v in GPU.items() if k != "uuid"}], None),
    ({"gpu_count": 2}, [GPU, {**GPU, "memory_mb": 40960}], "memory"),
], ids=["match", "none", "extra", "name", "name-first", "tolerance-edge", "beyond-tolerance",
        "zero-tolerance", "uuid-equal", "uuid-differs", "uuid-empty", "no-uuid-field", "second-device"])
def test_match_rule(changes, gpus, expected):
    assert hardware_class.devices_mismatch is attestation.devices_mismatch
    assert hardware_class.devices_mismatch({**A100, **changes}, gpus) == expected


IDENTITY_ERROR = "hardware attestation is missing, invalid, or belongs to another attempt"
DEVICE_ERROR = "GPU attestation does not satisfy the scientific hardware lock"


@pytest.mark.parametrize("changes,record,expected", [
    ({}, VERIFIED, None),
    ({}, {**VERIFIED, "verified": False}, IDENTITY_ERROR),
    ({}, {**VERIFIED, "attempt": 2}, IDENTITY_ERROR),
    ({}, {**VERIFIED, "task_id": "other"}, IDENTITY_ERROR),
    ({}, {**VERIFIED, "gpus": []}, "GPU count in attestation differs from the scientific hardware lock"),
    ({}, {**VERIFIED, "gpus": [{**GPU, "name": "other"}]}, DEVICE_ERROR),
    ({}, {**VERIFIED, "gpus": [{**GPU, "memory_mb": 1}]}, DEVICE_ERROR),
    ({"expected_gpu_uuid": "GPU-z"}, VERIFIED, DEVICE_ERROR),
], ids=["passes", "unverified", "other-attempt", "other-task", "count", "name", "memory", "uuid"])
def test_controller_check(changes, record, expected):
    assert hardware_class.attestation_problem({**A100, **changes}, "model-a", 1, record) == expected


@pytest.mark.parametrize("kind,attempt,expected", [
    ("plain", 1, '[{"memory_mb": 81151, "name": "NVIDIA A100-SXM4-80GB"}]'),
    ("mig", 2, '[{"memory_mb": 24064, "name": "NVIDIA RTX PRO 6000 Blackwell Server Edition MIG 1g.24gb"}]'),
], ids=["plain", "mig"])
def test_evidence_in_the_current_format_passes_the_controller_check(kind, attempt, expected):
    record = json.loads((FIXTURES / ("hardware-evidence-" + kind + ".json")).read_text())
    assert hardware_class.attestation_problem(record["requested"], "model-a", attempt, record) is None
    assert hardware_class.observed(record["gpus"]) == expected


def test_stored_lock_texts_are_unchanged():
    resources = json.loads((FIXTURES / "hardware-evidence-plain.json").read_text())["requested"]
    text = '{"constraint": "a100-80g&sapphirerapids", "expected_gpu_memory_mb": 81151, "expected_gpu_name": "NVIDIA A100-SXM4-80GB", "expected_gpu_uuid": null, "gpu_count": 1, "gpu_memory_tolerance_mb": 1024, "gpu_type": "a100", "nodelist": null}'
    assert hardware_class.lock_text(resources) == text
    tasks = [{"model_class": "cpu-prep", "resources": {"gpu_count": 0}},
             {"model_class": "a", "resources": resources},
             {"model_class": "b", "resources": {**resources, "expected_gpu_memory_mb": 81920}}]
    locks = hardware_class.class_locks(tasks)
    assert [name for name, _ in locks] == ["a", "b"]
    assert locks[0][1] == text
    assert hardware_class.conflicting_class(locks, {}) is None
    assert hardware_class.conflicting_class(locks, {"a": text}) is None
    assert hardware_class.conflicting_class(locks, {"a": text, "b": text}) == "b"
    assert not hardware_class.observed_differs(None, "[]")
    assert not hardware_class.observed_differs("", "[]")
    assert not hardware_class.observed_differs("[]", "[]")
    assert hardware_class.observed_differs("[1]", "[]")


def test_attestation_program_runs_alone():
    source = Path(attestation.__file__).read_text(encoding="utf-8")
    assert hardware_class.ATTESTATION_PROGRAM == source.strip()
    assert source.isascii()
    assert "HPC_PREFLIGHT" not in source.splitlines()
    tree = ast.parse(source, feature_version=(3, 7))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".")[0] in sys.stdlib_module_names for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0
            assert node.module.split(".")[0] in sys.stdlib_module_names


SETTINGS = {"account": "pi_test", "remote_root": "/work/pi_test/controller", "mail_user": "", "sample_gpu_metrics": True}
GPU_RESOURCES = {"gpu_type": "a100", "gpu_count": 1, "cpus": 4, "memory_mb": 32768,
                 "walltime_seconds": 3600, "constraint": "a100-80g&sapphirerapids",
                 "expected_gpu_name": "NVIDIA A100-SXM4-80GB", "expected_gpu_memory_mb": 81920,
                 "gpu_memory_tolerance_mb": 0, "partitions": [], "nodelist": None}
GPU_TASK = {"task_id": "model-a", "job_name": "study-model-a-0123456789abcdef0123", "attempt": 1,
            "spec": {"model_class": "small-a10080-v2", "env": {"PYTHONPATH": "src"},
                     "argv": ["python3", "run.py", "{output_dir}"], "resources": GPU_RESOURCES,
                     "outputs": ["results.jsonl"]}}
CPU_TASK = {"task_id": "prep", "job_name": "study-prep-x", "attempt": 2,
            "spec": {"env": {}, "argv": ["bash", "prep.sh"],
                     "resources": {"gpu_count": 0, "cpus": 2, "memory_mb": 1024,
                                   "walltime_seconds": 90061, "constraint": "", "partitions": []},
                     "outputs": ["a"]}}


GPU_EXPECTED = r"""#!/usr/bin/env bash
#SBATCH --job-name=study-model-a-0123456789abcdef0123
#SBATCH --account=pi_test
#SBATCH --partition=gpu,gpu-preempt
#SBATCH --time=0-01:00:00
#SBATCH --nodes=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32768M
#SBATCH --output=/work/pi_test/controller/campaigns/study/logs/study-model-a-0123456789abcdef0123.out
#SBATCH --error=/work/pi_test/controller/campaigns/study/logs/study-model-a-0123456789abcdef0123.err
#SBATCH --qos=normal
#SBATCH --no-requeue
#SBATCH --gres=gpu:a100:1
#SBATCH --constraint=a100-80g&sapphirerapids
set -euo pipefail
umask 077
export PYTHONPATH=src
export HPC_TASK_ID=model-a
export HPC_OUTPUT_DIR=/work/pi_test/controller/campaigns/study/outputs/model-a
export HPC_ATTEMPT=1
export HPC_CAMPAIGN_ID=study
export HPC_HARDWARE_PROFILE_ID=small-a10080-v2
export HPC_EXPECT_GPU_NAME='NVIDIA A100-SXM4-80GB'
export HPC_EXPECT_GPU_MEMORY_MB=81920
cd /work/pi_test/controller/campaigns/study/source
mkdir -p /work/pi_test/controller/campaigns/study/outputs/model-a
python3 - '{"gpu_type": "a100", "gpu_count": 1, "cpus": 4, "memory_mb": 32768, "walltime_seconds": 3600, "constraint": "a100-80g&sapphirerapids", "expected_gpu_name": "NVIDIA A100-SXM4-80GB", "expected_gpu_memory_mb": 81920, "gpu_memory_tolerance_mb": 0, "partitions": [], "nodelist": null}' <<'HPC_PREFLIGHT'
<<BODY>>
HPC_PREFLIGHT
HPC_GPU_IDS=$(python3 -c 'import json,sys;print('"'"','"'"'.join(g['"'"'uuid'"'"'] for g in json.load(open(sys.argv[1]))['"'"'gpus'"'"']))' /work/pi_test/controller/campaigns/study/outputs/model-a/.controller/hardware-1.json)
nvidia-smi --id="${HPC_GPU_IDS}" --query-gpu=timestamp,index,uuid,utilization.gpu,memory.used,power.draw --format=csv --loop=30 >/work/pi_test/controller/campaigns/study/outputs/model-a/.controller/gpu-samples-1.csv 2>/dev/null &
HPC_SAMPLE_PID=$!
trap 'kill "${HPC_SAMPLE_PID}" 2>/dev/null || true' EXIT
python3 run.py /work/pi_test/controller/campaigns/study/outputs/model-a
"""


CPU_EXPECTED = r"""#!/usr/bin/env bash
#SBATCH --job-name=study-prep-x
#SBATCH --account=pi_test
#SBATCH --partition=cpu
#SBATCH --time=1-01:01:01
#SBATCH --nodes=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=1024M
#SBATCH --output=/work/pi_test/controller/campaigns/study/logs/study-prep-x.out
#SBATCH --error=/work/pi_test/controller/campaigns/study/logs/study-prep-x.err
#SBATCH --qos=normal
#SBATCH --no-requeue
#SBATCH --mail-user=ops@example.org
#SBATCH --mail-type=END,FAIL,TIME_LIMIT,REQUEUE
set -euo pipefail
umask 077
export HPC_TASK_ID=prep
export HPC_OUTPUT_DIR=/work/pi_test/controller/campaigns/study/outputs/prep
export HPC_ATTEMPT=2
export HPC_CAMPAIGN_ID=study
export HPC_HARDWARE_PROFILE_ID=cpu
export HPC_EXPECT_GPU_NAME=''
export HPC_EXPECT_GPU_MEMORY_MB=''
cd /work/pi_test/controller/campaigns/study/source
mkdir -p /work/pi_test/controller/campaigns/study/outputs/prep
python3 - '{"gpu_count": 0, "cpus": 2, "memory_mb": 1024, "walltime_seconds": 90061, "constraint": "", "partitions": []}' <<'HPC_PREFLIGHT'
<<BODY>>
HPC_PREFLIGHT
bash prep.sh
"""


@pytest.mark.parametrize("settings,task,placement,expected", [
    (SETTINGS, GPU_TASK, {"selected_partitions": ["gpu", "gpu-preempt"], "qos": "normal"}, GPU_EXPECTED),
    ({**SETTINGS, "mail_user": "ops@example.org"}, CPU_TASK,
     {"selected_partitions": ["cpu"], "qos": "normal"}, CPU_EXPECTED),
], ids=["gpu", "cpu"])
def test_job_script_is_unchanged_outside_the_embedded_program(settings, task, placement, expected):
    text = script(settings, {"id": "study"}, task, placement)
    assert text.count(hardware_class.ATTESTATION_PROGRAM) == 1
    assert text.replace(hardware_class.ATTESTATION_PROGRAM, "<<BODY>>") == expected


def run_job(tmp_path, device_row):
    remote = tmp_path / "remote"
    (remote / "campaigns/study/source").mkdir(parents=True)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    smi = binaries / "nvidia-smi"
    smi.write_text('#!/bin/sh\ncase "$1" in --query-gpu=index,*) echo "' + device_row + '" ;; *) echo sample ;; esac\n')
    smi.chmod(0o755)
    python = binaries / "python3"
    python.write_text('#!/bin/sh\nexec "' + sys.executable + '" -I "$@"\n')
    python.chmod(0o755)
    task = {**GPU_TASK, "spec": {**GPU_TASK["spec"], "env": {}, "argv": [
        "python3", "-c", "import os,pathlib;pathlib.Path(os.environ['HPC_OUTPUT_DIR'],'ran').write_text('yes')"]}}
    job = tmp_path / "job.sh"
    job.write_text(script({**SETTINGS, "remote_root": str(remote)}, {"id": "study"}, task,
                          {"selected_partitions": ["gpu", "gpu-preempt"], "qos": "normal"}))
    result = subprocess.run(["bash", str(job)], cwd=tmp_path, env={
        "PATH": str(binaries) + ":/usr/bin:/bin", "SLURM_JOB_ID": "123", "SLURMD_NODENAME": "gpu014",
    }, capture_output=True, text=True, timeout=60)
    return result, remote / "campaigns/study/outputs/model-a"


def test_generated_job_script_attests_outside_the_repository(tmp_path):
    result, output = run_job(tmp_path, "0, GPU-a, NVIDIA A100-SXM4-80GB, 81920, 550.54.15")
    assert result.returncode == 0, result.stderr
    assert (output / hardware_class.hardware_evidence(1)).read_text() == json.dumps({
        "attempt": 1, "gpus": [{"driver_version": "550.54.15", "memory_mb": 81920,
                                "name": "NVIDIA A100-SXM4-80GB", "uuid": "GPU-a"}],
        "job_id": "123", "node": "gpu014", "requested": GPU_RESOURCES, "task_id": "model-a", "verified": True,
    }, sort_keys=True)
    assert (output / "ran").read_text() == "yes"
    assert (output / hardware_class.gpu_samples(1)).is_file()


def test_generated_job_script_stops_before_the_scientific_command_on_a_mismatch(tmp_path):
    result, output = run_job(tmp_path, "0, GPU-a, NVIDIA A100-PCIE-40GB, 40960, 550.54.15")
    assert result.returncode == 86, result.stderr
    record = json.loads((output / hardware_class.hardware_evidence(1)).read_text())
    assert record["verified"] is False
    assert record["error"] == "GPU model mismatch: NVIDIA A100-PCIE-40GB"
    assert not (output / "ran").exists()
