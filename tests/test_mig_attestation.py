"""The in-job Attestation, called as code with a stub device query. A MIG allocation attests its slice."""
import json
from types import SimpleNamespace

import pytest

from controller import attestation


A100 = {"gpu_count": 1, "expected_gpu_name": "NVIDIA A100-SXM4-80GB",
        "expected_gpu_memory_mb": 81920, "gpu_memory_tolerance_mb": 0}


def smi(*rows):
    return lambda *a, **kw: SimpleNamespace(stdout="".join(r + "\n" for r in rows))


class Nvml:
    def __init__(self):
        self.calls = []

    def nvmlInit_v2(self):
        return 0

    def nvmlShutdown(self):
        self.calls.append("shutdown")
        return 0

    def nvmlSystemGetDriverVersion(self, buf, size):
        buf.value = b'595.91.07'
        return 0

    def nvmlDeviceGetHandleByUUID(self, uuid, handle):
        self.calls.append(uuid)
        handle._obj.value = 123
        return 0

    def nvmlDeviceGetName(self, handle, buf, size):
        buf.value = b'Blackwell'
        return 0

    def nvmlDeviceGetMemoryInfo(self, handle, memory):
        memory._obj.total = 48000 * 1024**2
        return 0


def environment(tmp_path, **values):
    return {"HPC_OUTPUT_DIR": str(tmp_path), "HPC_TASK_ID": "evaluation", "HPC_ATTEMPT": "1", **values}


def evidence(tmp_path):
    return json.loads((tmp_path / attestation.hardware_evidence(1)).read_text())


@pytest.mark.parametrize('expected,accepted', [(48000, True), (96000, False)])
def test_mig_uses_allocated_uuid_and_slice_memory(tmp_path, expected, accepted):
    nvml = Nvml()
    environ = environment(tmp_path, CUDA_VISIBLE_DEVICES="MIG-assigned", SLURM_JOB_GPUS="7")
    request = {"gpu_count": 1, "expected_gpu_name": "Blackwell",
               "expected_gpu_memory_mb": expected, "gpu_memory_tolerance_mb": 0}
    query = lambda e: attestation.query_devices(
        e, run=smi("0, GPU-parent, Blackwell, 96000, 595.91.07"), load=lambda name: nvml)
    assert attestation.main(["-", json.dumps(request)], environ, query=query) == (0 if accepted else 86)
    result = evidence(tmp_path)
    assert nvml.calls == [b"MIG-assigned", "shutdown"]
    assert result["verified"] is accepted
    if accepted:
        assert result["gpus"] == [{"uuid": "MIG-assigned", "name": "Blackwell",
                                  "memory_mb": 48000, "driver_version": "595.91.07"}]
    else:
        assert result["error"] == "GPU memory mismatch"


def test_mixed_mig_and_full_gpu_visibility_is_refused(tmp_path):
    def load(name):
        raise AssertionError("mixed visibility must be rejected before loading NVML")

    query = lambda e: attestation.query_devices(
        e, run=smi("0, GPU-parent, Blackwell, 96000, 595.91.07"), load=load)
    assert attestation.main(["-", json.dumps(A100)], environment(
        tmp_path, CUDA_VISIBLE_DEVICES="MIG-assigned,0"), query=query) == 86
    assert evidence(tmp_path)["error"] == "mixed MIG and full GPU visibility is unsupported"


def test_plain_gpu_attestation_keeps_only_the_assigned_device(tmp_path):
    query = lambda e: attestation.query_devices(e, run=smi(
        "0, GPU-a, NVIDIA A100-SXM4-80GB, 81920, 550.54.15",
        "1, GPU-b, NVIDIA A100-SXM4-80GB, 81920, 550.54.15"))
    assert attestation.main(["-", json.dumps(A100)], environment(
        tmp_path, SLURM_JOB_GPUS="1", SLURM_JOB_ID="123", SLURMD_NODENAME="gpu014"), query=query) == 0
    assert (tmp_path / attestation.hardware_evidence(1)).read_text() == json.dumps({
        "attempt": 1, "gpus": [{"driver_version": "550.54.15", "memory_mb": 81920,
                                "name": "NVIDIA A100-SXM4-80GB", "uuid": "GPU-b"}],
        "job_id": "123", "node": "gpu014", "requested": A100, "task_id": "evaluation", "verified": True,
    }, sort_keys=True)


@pytest.mark.parametrize("kind,changes,error,kept", [
    ("count", {}, "visible GPU count differs from declared GPU count", 0),
    ("name", {"gpu_count": 2}, "GPU model mismatch: NVIDIA A100-PCIE-40GB", 1),
    ("memory", {"expected_gpu_memory_mb": 81000}, "GPU memory mismatch", 0),
    ("uuid", {"expected_gpu_uuid": "GPU-z"}, "physical GPU UUID mismatch", 0),
], ids=["count", "name", "memory", "uuid"])
def test_plain_gpu_mismatch_stops_the_job(tmp_path, kind, changes, error, kept):
    rows = [["0", "GPU-a", "NVIDIA A100-SXM4-80GB", "81920", "550.54.15"]]
    if kind in ("count", "name"):
        rows.append(["1", "GPU-b", "NVIDIA A100-PCIE-40GB", "40960", "550.54.15"])
    assert attestation.main(["-", json.dumps({**A100, **changes})], environment(tmp_path),
                            query=lambda e: rows) == 86
    result = evidence(tmp_path)
    assert result["verified"] is False
    assert result["error"] == error
    assert len(result["gpus"]) == kept


def test_cpu_task_attests_without_a_device_query(tmp_path):
    def query(environ):
        raise AssertionError("CPU tasks must not query GPUs")

    assert attestation.main(["-", json.dumps({"gpu_count": 0})], environment(tmp_path), query=query) == 0
    assert evidence(tmp_path)["verified"] is True
    assert evidence(tmp_path)["gpus"] == []
