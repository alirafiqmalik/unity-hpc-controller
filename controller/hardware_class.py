"""Hardware class: the fingerprint a Model class is locked to, the match rule, and the Attestation evidence.

The match rule and the evidence file names live in controller/attestation.py,
the in-job half of this module: the job script carries that file's text and
runs it alone on the compute node. Controller code imports them from here.
This module performs no IO except reading that file's text once at import.
"""

from __future__ import annotations

import json
from pathlib import Path

from controller import attestation
from controller.attestation import EVIDENCE_DIR, devices_mismatch, gpu_samples, hardware_evidence

# The text the job script carries, read once so that the program sent to jobs
# and the match rule imported above come from the same file version.
ATTESTATION_PROGRAM = Path(attestation.__file__).read_text(encoding="utf-8").strip()

FINGERPRINT_KEYS = ("gpu_type", "gpu_count", "constraint", "expected_gpu_name", "expected_gpu_memory_mb",
                    "gpu_memory_tolerance_mb", "nodelist", "expected_gpu_uuid")


def fingerprint(resources):
    """The Hardware class of one task's validated resources."""
    return {key: resources.get(key) for key in FINGERPRINT_KEYS}


def lock_text(resources):
    """The fingerprint as the journal stores it in hardware_locks.fingerprint."""
    return json.dumps(fingerprint(resources), sort_keys=True)


def class_locks(tasks):
    """(model_class, lock text) for each GPU task, in declaration order."""
    return [(task["model_class"], lock_text(task["resources"])) for task in tasks if task["resources"]["gpu_count"]]


def conflicting_class(locks, locked):
    """The first Model class whose lock text differs from its durable lock, or None.
    locked maps a Model class to its stored lock text; a class without one does not conflict."""
    for model_class, text in locks:
        if locked.get(model_class, text) != text:
            return model_class
    return None


def observed(gpus):
    """What a Model class's first accepted result binds: each device's name and memory, as the journal stores them."""
    return json.dumps([{"name": gpu["name"], "memory_mb": gpu["memory_mb"]} for gpu in gpus], sort_keys=True)


def observed_differs(bound, observed_text):
    """True when the class already bound other devices. An unbound class accepts any."""
    return bool(bound) and bound != observed_text


def attestation_problem(resources, task_id, attempt, record):
    """The controller check of a retrieved Attestation record: None when it passes,
    otherwise why the outputs cannot be marked complete."""
    if not record.get("verified") or record.get("task_id") != task_id or record.get("attempt") != attempt:
        return "hardware attestation is missing, invalid, or belongs to another attempt"
    if resources["gpu_count"]:
        reason = devices_mismatch(resources, record.get("gpus", []))
        if reason == "count":
            return "GPU count in attestation differs from the scientific hardware lock"
        if reason:
            return "GPU attestation does not satisfy the scientific hardware lock"
    return None
