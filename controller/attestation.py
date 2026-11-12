"""Attestation: the in-job record of the assigned GPUs, taken before the scientific command runs.

The controller sends the text of this file inside every job script, on the
standard input of python3, with the declared resources as the only argument.
On the compute node it runs alone: standard library only, no import from this
repository, syntax that Python 3.7 accepts. It writes .controller/hardware-<attempt>.json
under HPC_OUTPUT_DIR and exits with status 86 when the devices do not match,
so the job script stops before the scientific command.

The controller imports the match rule and the evidence names from this file
through controller/hardware_class.py, so the in-job check and the controller
check are the same code.
"""
import csv
import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path

EVIDENCE_DIR = '.controller'
NOT_VERIFIED = 86


def hardware_evidence(attempt):
    """The Attestation file of one attempt, relative to the task output directory."""
    return EVIDENCE_DIR + '/hardware-' + str(attempt) + '.json'


def gpu_samples(attempt):
    """The GPU sample file of one attempt, relative to the task output directory."""
    return EVIDENCE_DIR + '/gpu-samples-' + str(attempt) + '.csv'


def count_matches(request, devices):
    """True when the number of devices is the declared GPU count."""
    return len(devices) == request['gpu_count']


def device_mismatch(request, gpu):
    """The first field in which one attested device differs from the declared
    Hardware class: 'name', 'memory', or 'uuid'. None when it matches.
    The UUID is compared only when the declaration names one."""
    if gpu['name'] != request['expected_gpu_name']:
        return 'name'
    if abs(gpu['memory_mb'] - request['expected_gpu_memory_mb']) > request['gpu_memory_tolerance_mb']:
        return 'memory'
    if request.get('expected_gpu_uuid') and gpu['uuid'] != request['expected_gpu_uuid']:
        return 'uuid'
    return None


def devices_mismatch(request, gpus):
    """None when the attested devices match the declared Hardware class;
    otherwise 'count', or the first device's mismatch."""
    if not count_matches(request, gpus):
        return 'count'
    for gpu in gpus:
        reason = device_mismatch(request, gpu)
        if reason:
            return reason
    return None


def query_devices(environ, run=None, load=None):
    """Rows [index, uuid, name, memory MiB, driver] for the devices that this job sees.
    run replaces subprocess.run and load replaces ctypes.CDLL in tests."""
    run = run or subprocess.run
    load = load or ctypes.CDLL
    p = run(['nvidia-smi', '--query-gpu=index,uuid,name,memory.total,driver_version', '--format=csv,noheader,nounits'], capture_output=True, text=True, check=True, timeout=15)
    rows = list(csv.reader(p.stdout.splitlines(), skipinitialspace=True))
    visible_cuda = environ.get('CUDA_VISIBLE_DEVICES', '').split(',')
    if any(value.startswith('MIG-') for value in visible_cuda):
        # nvidia-smi --query-gpu reports the parent board's full memory.
        # Query the allocated MIG UUIDs through NVML instead; never attest
        # the parent's memory as the capacity of a partitioned device.
        if not all(value.startswith('MIG-') for value in visible_cuda):
            raise ValueError('mixed MIG and full GPU visibility is unsupported')
        nvml = load('libnvidia-ml.so.1')

        def nvcall(name, *args):
            code = getattr(nvml, name)(*args)
            if code:
                raise ValueError('NVML ' + name + ' failed: ' + str(code))

        class Memory(ctypes.Structure):
            _fields_ = [('total', ctypes.c_ulonglong), ('free', ctypes.c_ulonglong), ('used', ctypes.c_ulonglong)]

        nvcall('nvmlInit_v2')
        try:
            rows = []
            driver = ctypes.create_string_buffer(128)
            nvcall('nvmlSystemGetDriverVersion', driver, 128)
            for index, uuid in enumerate(visible_cuda):
                handle = ctypes.c_void_p()
                nvcall('nvmlDeviceGetHandleByUUID', uuid.encode(), ctypes.byref(handle))
                name = ctypes.create_string_buffer(256)
                memory = Memory()
                nvcall('nvmlDeviceGetName', handle, name, 256)
                nvcall('nvmlDeviceGetMemoryInfo', handle, ctypes.byref(memory))
                rows.append([str(index), uuid, name.value.decode(), str(memory.total // (1024 * 1024)), driver.value.decode()])
        finally:
            nvml.nvmlShutdown()
    return rows


def assigned(rows, environ):
    """Keep the rows of the GPUs that Slurm assigned to this job.
    Device cgroups may expose an already restricted list. Slurm GPU ids
    are global; CUDA ordinals can be remapped inside that list."""
    visible = environ.get('SLURM_STEP_GPUS') or environ.get('SLURM_JOB_GPUS') or environ.get('CUDA_VISIBLE_DEVICES', '')
    ids = []
    for item in visible.split(','):
        if '-' in item and all(x.isdigit() for x in item.split('-')):
            a, b = map(int, item.split('-'))
            ids.extend(str(x) for x in range(a, b + 1))
        else:
            ids.append(item)
    return [x for x in rows if x[0].strip() in ids or x[1].strip() in ids]


def verify(request, environ, gpus, query=None):
    """Append each matching device to gpus; raise ValueError at the first mismatch."""
    rows = (query or query_devices)(environ)
    if not count_matches(request, rows):
        rows = assigned(rows, environ)
    if not count_matches(request, rows):
        raise ValueError('visible GPU count differs from declared GPU count')
    for x in rows:
        gpu = {'uuid': x[1].strip(), 'name': x[2].strip(), 'memory_mb': int(float(x[3])), 'driver_version': x[4].strip()}
        reason = device_mismatch(request, gpu)
        if reason == 'name':
            raise ValueError('GPU model mismatch: ' + gpu['name'])
        if reason == 'memory':
            raise ValueError('GPU memory mismatch')
        if reason == 'uuid':
            raise ValueError('physical GPU UUID mismatch')
        gpus.append(gpu)


def main(argv, environ, query=None):
    """The in-job program: argv[1] is the declared resources as JSON.
    Writes the Attestation file and returns 0 when verified, else 86."""
    request = json.loads(argv[1])
    out = Path(environ['HPC_OUTPUT_DIR'])
    out.mkdir(parents=True, exist_ok=True)
    metadata = {'task_id': environ['HPC_TASK_ID'], 'attempt': int(environ['HPC_ATTEMPT']), 'job_id': environ.get('SLURM_JOB_ID'),
                'node': environ.get('SLURMD_NODENAME'), 'requested': request, 'gpus': [], 'verified': False}
    try:
        if request['gpu_count']:
            verify(request, environ, metadata['gpus'], query)
        metadata['verified'] = True
    except Exception as exc:
        metadata['error'] = str(exc)
    finally:
        (out / EVIDENCE_DIR).mkdir(exist_ok=True)
        (out / hardware_evidence(environ['HPC_ATTEMPT'])).write_text(json.dumps(metadata, sort_keys=True))
    return 0 if metadata['verified'] else NOT_VERIFIED


if __name__ == '__main__':
    sys.exit(main(sys.argv, os.environ))
