"""Pure lifecycle decisions pin state names, fields, and effects."""

import ast
from pathlib import Path

import pytest

from controller import campaign_lifecycle as lc


def task(state, attempt=1, eligible_at=0, observation=None, depends_on=()):
    return {"task_id": "t", "state": state, "attempt": attempt, "eligible_at": eligible_at,
            "observation": observation, "spec": {"depends_on": list(depends_on)}}

def seen(state, **extra):                      # as observe() returns it
    return {"job_id": "123", "state": state, **extra}

def kept(state, fetch_attempts=0, **extra):    # as the lifecycle records it
    return {"job_id": "123", "state": state, **extra, "fetch_attempts": fetch_attempts}

def step(state, fields):                       # a Step: the next state and the fields to record
    return (state, fields)

OBS = {"cancelling": False, "max_attempts": 2, "now": 50}
SAL = {"cancelling": False, "retry_backoff_seconds": 60, "now": 1000}
UND = {"conflict": False, "max_fetch_attempts": 5, "retry_backoff_seconds": 60, "now": 1000}
ADM = {"cancelling": False, "now": 50}
M = {"files": [], "controller_files": [], "missing": [], "hardware": {}, "attempt": 1, "job_id": "123"}


def J(observation):
    return {"job_id": "123", "observation": observation}


ROWS = [
    ("L01", "intent", (2, 'job-2'), {}, ("submitting", {"attempt": 2, "job_name": "job-2", "job_id": None, "error": None, "observation": None, "eligible_at": 0})),
    ("L02", "uncertain_receipt", ('ssh reset',), {}, {"outcome": "uncertain", "error": "ssh reset"}),
    ("L03", "submitted", ({'outcome': 'accepted', 'job_id': '123'},), {}, step("accepted", {"job_id": "123", "error": None})),
    ("L04", "submitted", ({'outcome': 'accepted', 'job_id': '12a'},), {}, step("uncertain", {"job_id": "12a", "error": None})),
    ("L05", "submitted", ({'outcome': 'accepted'},), {}, step("uncertain", {"job_id": None, "error": None})),
    ("L06", "submitted", ({'outcome': 'rejected', 'error': 'job script staging failed: disk full'},), {}, step("rejected", {"job_id": None, "error": "job script staging failed: disk full"})),
    ("L07", "submitted", ({'outcome': 'uncertain', 'error': 'submission receipt missing'},), {}, step("uncertain", {"job_id": None, "error": "submission receipt missing"})),
    ("L08", "submitted", ({},), {}, step("uncertain", {"job_id": None, "error": None})),
    ("L09", "observed", (task('submitting'), None), {**OBS}, (step("uncertain", {"error": "interrupted submission; reconcile by unique job name before any retry"}), None)),
    ("L10", "observed", (task('submitting'), {}), {**OBS}, (step("uncertain", {"error": "interrupted submission; reconcile by unique job name before any retry"}), None)),
    ("L11", "observed", (task('uncertain'), None), {**OBS}, (None, None)),
    ("L12", "observed", (task('fetching'), None), {**OBS}, (None, None)),
    ("L13", "observed", (task('submitting'), seen('PENDING')), {**OBS}, (step("accepted", {**J(kept("PENDING")), "error": None}), None)),
    ("L14", "observed", (task('uncertain'), seen('RUNNING')), {**OBS}, (step("running", {**J(kept("RUNNING")), "error": None}), None)),
    ("L15", "observed", (task('accepted'), seen('COMPLETING')), {**OBS}, (step("running", {**J(kept("COMPLETING")), "error": None}), None)),
    ("L16", "observed", (task('running'), seen('SUSPENDED')), {**OBS}, (step("accepted", {**J(kept("SUSPENDED")), "error": None}), None)),
    ("L17", "observed", (task('running', observation={'fetch_attempts': 2}), seen('RUNNING')), {**OBS}, (step("running", {**J(kept("RUNNING", 2)), "error": None}), None)),
    ("L18", "observed", (task('running'), seen('RUNNING')), {**OBS, 'cancelling': True}, (step("cancelling", J(kept("RUNNING"))), "cancel_job")),
    ("L19", "observed", (task('cancelling'), seen('PENDING')), {**OBS, 'cancelling': True}, (step("cancelling", J(kept("PENDING"))), "cancel_job")),
    ("L20", "observed", (task('running'), seen('CANCELLED')), {**OBS}, (step("fetching", J(kept("CANCELLED"))), "salvage")),
    ("L21", "observed", (task('running'), seen('COMPLETED', exit_code='0:0')), {**OBS, 'cancelling': True}, (step("fetching", J(kept("COMPLETED", exit_code="0:0"))), "salvage")),
    ("L22", "observed", (task('running', attempt=1), seen('PREEMPTED')), {**OBS}, (step("fetching", J(kept("PREEMPTED"))), "salvage")),
    ("L23", "observed", (task('running', attempt=2), seen('NODE_FAIL')), {**OBS}, (step("fetching", J(kept("NODE_FAIL"))), "retrieve")),
    ("L24", "observed", (task('running'), seen('FAILED')), {**OBS}, (step("fetching", J(kept("FAILED"))), "retrieve")),
    ("L25", "observed", (task('running'), seen('COMPLETED', exit_code='0:0')), {**OBS}, (step("fetching", J(kept("COMPLETED", exit_code="0:0"))), "retrieve")),
    ("L26", "observed", (task('fetching', eligible_at=100, observation={'fetch_attempts': 1}), seen('COMPLETED')), {**OBS}, (step("fetching", J(kept("COMPLETED", 1))), "hold")),
    ("L27", "observed", (task('fetching', eligible_at=50), seen('COMPLETED')), {**OBS}, (step("fetching", J(kept("COMPLETED"))), "retrieve")),
    ("L28", "observed", (task('accepted', eligible_at=100), seen('COMPLETED')), {**OBS}, (step("fetching", J(kept("COMPLETED"))), "retrieve")),
    ("L29", "observed", (task('submitting'), seen('DEADLINE')), {**OBS}, (step("fetching", J(kept("DEADLINE"))), "retrieve")),
    ("L30", "salvaged", (task('running'), kept('CANCELLED')), {**SAL}, step("cancelled", {"observation": kept("CANCELLED")})),
    ("L31", "salvaged", (task('running'), kept('PREEMPTED')), {**SAL, 'cancelling': True}, step("cancelled", {"observation": kept("PREEMPTED")})),
    ("L32", "salvaged", (task('running', attempt=1), kept('PREEMPTED')), {**SAL}, step("waiting", {"eligible_at": 1060, "observation": kept("PREEMPTED"), "error": "infrastructure failure: PREEMPTED; bounded retry scheduled"})),
    ("L33", "salvaged", (task('running', attempt=2), kept('NODE_FAIL')), {**SAL}, step("waiting", {"eligible_at": 1120, "observation": kept("NODE_FAIL"), "error": "infrastructure failure: NODE_FAIL; bounded retry scheduled"})),
    ("L34", "salvaged", (task('running', attempt=3), kept('BOOT_FAIL')), {**SAL}, step("waiting", {"eligible_at": 1240, "observation": kept("BOOT_FAIL"), "error": "infrastructure failure: BOOT_FAIL; bounded retry scheduled"})),
    ("L35", "scheduler_succeeded", (seen('COMPLETED', exit_code='0:0'),), {}, True),
    ("L36", "scheduler_succeeded", (seen('COMPLETED'),), {}, True),
    ("L37", "scheduler_succeeded", (seen('COMPLETED', exit_code='1:0'),), {}, False),
    ("L38", "scheduler_succeeded", (seen('FAILED', exit_code='0:0'),), {}, False),
    ("L39", "scheduler_succeeded", (seen('NODE_FAIL'),), {}, False),
    ("L40", "delivered", (M,), {'successful': True}, step("completed", {"artifacts": {**M, "complete": True}, "error": None})),
    ("L41", "delivered", ({**M, 'missing': ['summary.json']},), {'successful': True}, step("failed", {"artifacts": {**M, "missing": ["summary.json"], "complete": False}, "error": "scheduler failed or required outputs missing"})),
    ("L42", "delivered", (M,), {'successful': False}, step("failed", {"artifacts": {**M, "complete": False}, "error": "scheduler failed or required outputs missing"})),
    ("L43", "undelivered", (kept('COMPLETED'), 'GPU attestation does not satisfy the scientific hardware lock'), {**UND, 'conflict': True}, step("failed", {"error": "GPU attestation does not satisfy the scientific hardware lock"})),
    ("L44", "undelivered", (kept('COMPLETED', 0), 'network interrupted during fetch'), {**UND}, step("fetching", {"error": "network interrupted during fetch", "observation": kept("COMPLETED", 1), "eligible_at": 1060})),
    ("L45", "undelivered", (kept('COMPLETED', 4), 'network interrupted during fetch'), {**UND}, step("failed", {"error": "network interrupted during fetch", "observation": kept("COMPLETED", 5), "eligible_at": 1060})),
    ("L46", "undelivered", (kept('COMPLETED', 0), 'network interrupted during fetch'), {**UND, 'max_fetch_attempts': 1}, step("failed", {"error": "network interrupted during fetch", "observation": kept("COMPLETED", 1), "eligible_at": 1060})),
    ("L47", "admission", (task('waiting', eligible_at=100), {}), {**ADM}, (None, "hold")),
    ("L48", "admission", (task('accepted'), {}), {**ADM}, (None, "hold")),
    ("L49", "admission", (task('waiting', eligible_at=100), {}), {**ADM, 'cancelling': True}, (None, "hold")),
    ("L50", "admission", (task('waiting'), {}), {**ADM, 'cancelling': True}, (step("cancelled", {}), None)),
    ("L51", "admission", (task('waiting', depends_on=['a']), {'a': 'failed'}), {**ADM, 'cancelling': True}, (step("cancelled", {}), None)),
    ("L52", "admission", (task('waiting', depends_on=['a']), {'a': 'failed'}), {**ADM}, (step("blocked", {"error": "a required task did not complete"}), None)),
    ("L53", "admission", (task('waiting', depends_on=['a']), {'a': 'rejected'}), {**ADM}, (step("blocked", {"error": "a required task did not complete"}), None)),
    ("L54", "admission", (task('waiting', depends_on=['a']), {'a': 'cancelled'}), {**ADM}, (step("blocked", {"error": "a required task did not complete"}), None)),
    ("L55", "admission", (task('waiting', depends_on=['a']), {'a': 'blocked'}), {**ADM}, (step("blocked", {"error": "a required task did not complete"}), None)),
    ("L56", "admission", (task('waiting', depends_on=['a', 'b']), {'a': 'waiting', 'b': 'failed'}), {**ADM}, (step("blocked", {"error": "a required task did not complete"}), None)),
    ("L57", "admission", (task('waiting', depends_on=['a']), {'a': 'running'}), {**ADM}, (None, "hold")),
    ("L58", "admission", (task('waiting', depends_on=['a']), {'a': 'waiting'}), {**ADM}, (None, "hold")),
    ("L59", "admission", (task('waiting'), {}), {**ADM}, (None, "admit")),
    ("L60", "admission", (task('waiting', depends_on=['a']), {'a': 'completed'}), {**ADM}, (None, "admit")),
    ("L61", "admission", (task('waiting', eligible_at=50), {}), {**ADM}, (None, "admit")),
    ("L62", "cancel_request", (task('waiting'),), {}, step("cancelled", {})),
    ("L63", "cancel_request", (task('accepted'),), {}, None),
    ("L64", "cancel_request", (task('fetching'),), {}, None),
    ("L65", "cancel_request", (task('blocked'),), {}, None),
    ("L66", "campaign_state", ('accepted', ['waiting']), {}, "running"),
    ("L67", "campaign_state", ('running', ['running', 'waiting']), {}, None),
    ("L68", "campaign_state", ('running', ['completed', 'completed']), {}, "completed"),
    ("L69", "campaign_state", ('running', ['completed', 'cancelled']), {}, "cancelled"),
    ("L70", "campaign_state", ('running', ['completed', 'failed']), {}, "failed"),
    ("L71", "campaign_state", ('running', ['completed', 'blocked']), {}, "failed"),
    ("L72", "campaign_state", ('running', ['rejected']), {}, "failed"),
    ("L73", "campaign_state", ('running', ['cancelled', 'blocked']), {}, "failed"),
    ("L74", "campaign_state", ('cancelling', ['cancelling', 'cancelled']), {}, None),
    ("L75", "campaign_state", ('cancelling', ['cancelled']), {}, "cancelled"),
    ("L76", "campaign_state", ('cancelling', ['completed']), {}, "completed"),
    ("L77", "campaign_state", ('completed', ['completed']), {}, None),
    ("L78", "campaign_state", ('accepted', []), {}, "cancelled"),
    ("L79", "cancel_campaign", ('accepted',), {}, "cancelling"),
    ("L80", "cancel_campaign", ('running',), {}, "cancelling"),
    ("L81", "cancel_campaign", ('cancelling',), {}, "cancelling"),
    ("L82", "cancel_campaign", ('completed',), {}, None),
    ("L83", "cancel_campaign", ('failed',), {}, None),
    ("L84", "cancel_campaign", ('cancelled',), {}, None),
    ("L85", "attempt_outcome", ('waiting', {'state': 'PREEMPTED'}), {}, "PREEMPTED"),
    ("L86", "attempt_outcome", ('cancelled', {'state': 'NODE_FAIL'}), {}, "NODE_FAIL"),
    ("L87", "attempt_outcome", ('blocked', {'state': 'BOOT_FAIL'}), {}, "BOOT_FAIL"),
    ("L88", "attempt_outcome", ('waiting', None), {}, "waiting"),
    ("L89", "attempt_outcome", ('cancelled', {'state': 'CANCELLED'}), {}, "cancelled"),
    ("L90", "attempt_outcome", ('failed', {'state': 'NODE_FAIL'}), {}, "failed"),
    ("L91", "attempt_outcome", ('fetching', {'state': 'PREEMPTED'}), {}, "fetching"),
    ("L92", "attempt_outcome", ('submitting', None), {}, "submitting"),
]


@pytest.mark.parametrize("name,args,kwargs,expected", [r[1:] for r in ROWS], ids=[r[0] for r in ROWS])
def test_transition_table(name, args, kwargs, expected):
    assert getattr(lc, name)(*args, **kwargs) == expected


def test_state_names_and_sets():
    assert lc.TASK_STATES == {"waiting", "submitting", "uncertain", "accepted", "running", "fetching", "cancelling",
                              "completed", "failed", "rejected", "cancelled", "blocked"}
    assert lc.ACTIVE == {"submitting", "uncertain", "accepted", "running", "fetching", "cancelling"}
    assert lc.TERMINAL == {"completed", "failed", "rejected", "cancelled", "blocked"}
    assert lc.CAMPAIGN_TERMINAL == {"completed", "failed", "cancelled"}
    assert lc.SLURM_TERMINAL == {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL", "PREEMPTED",
                                 "BOOT_FAIL", "OUT_OF_MEMORY", "DEADLINE", "REVOKED"}
    assert lc.SLURM_RETRYABLE == {"NODE_FAIL", "PREEMPTED", "BOOT_FAIL"}
    assert lc.ACTIVE.isdisjoint(lc.TERMINAL)
    assert lc.SLURM_RETRYABLE <= lc.SLURM_TERMINAL


def test_lifecycle_imports_nothing_that_does_io():
    tree = ast.parse(Path(lc.__file__).read_text())
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module.split(".")[0])
    assert imports == {"__future__", "typing"}
