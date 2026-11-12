"""A MIG allocation must attest its slice, never the parent board's VRAM."""
import ctypes
import json
from types import SimpleNamespace

import pytest

from controller.campaign_slurm import PREFLIGHT


@pytest.mark.parametrize('expected,accepted', [(48000, True), (96000, False)])
def test_mig_uses_allocated_uuid_and_slice_memory(tmp_path, monkeypatch, expected, accepted):
    calls = []

    class Nvml:
        def nvmlInit_v2(self): return 0
        def nvmlShutdown(self): return 0
        def nvmlSystemGetDriverVersion(self, buf, size):
            buf.value = b'595.91.07'
            return 0
        def nvmlDeviceGetHandleByUUID(self, uuid, handle):
            calls.append(uuid)
            handle._obj.value = 123
            return 0
        def nvmlDeviceGetName(self, handle, buf, size):
            buf.value = b'Blackwell'
            return 0
        def nvmlDeviceGetMemoryInfo(self, handle, memory):
            memory._obj.total = 48000 * 1024**2
            return 0

    monkeypatch.setattr(ctypes, 'CDLL', lambda name: Nvml())
    monkeypatch.setattr('subprocess.run', lambda *a, **kw: SimpleNamespace(
        stdout='0, GPU-parent, Blackwell, 96000, 595.91.07\n'))
    for k,v in {'HPC_OUTPUT_DIR':str(tmp_path), 'HPC_TASK_ID':'evaluation',
                'HPC_ATTEMPT':'1', 'CUDA_VISIBLE_DEVICES':'MIG-assigned',
                'SLURM_JOB_GPUS':'7'}.items(): monkeypatch.setenv(k,v)
    request = {'gpu_count':1, 'expected_gpu_name':'Blackwell',
               'expected_gpu_memory_mb':expected, 'gpu_memory_tolerance_mb':0}
    monkeypatch.setattr('sys.argv', ['preflight', json.dumps(request)])
    if accepted:
        exec(PREFLIGHT, {})
    else:
        with pytest.raises(SystemExit): exec(PREFLIGHT, {})
    result = json.loads((tmp_path/'.controller/hardware-1.json').read_text())
    assert calls == [b'MIG-assigned']
    assert result['verified'] is accepted
    if accepted:
        assert result['gpus'][0]['uuid'] == 'MIG-assigned'
        assert result['gpus'][0]['memory_mb'] == 48000
