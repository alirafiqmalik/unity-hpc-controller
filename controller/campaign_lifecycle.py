"""Task, attempt, and campaign lifecycle.

Pure rules with no IO and no clock: callers pass the time in. A decision takes
plain records and one input (a submission receipt, a scheduler observation, a
retrieval outcome, dependency states, or a cancel request) and returns the next
task state, the task fields to record, and the Result event payload. The worker
performs remote effects; the journal records the fields.
"""

from __future__ import annotations

from typing import NamedTuple

WAITING = "waiting"
SUBMITTING = "submitting"
UNCERTAIN = "uncertain"
ACCEPTED = "accepted"
RUNNING = "running"
FETCHING = "fetching"
CANCELLING = "cancelling"
COMPLETED = "completed"
FAILED = "failed"
REJECTED = "rejected"
CANCELLED = "cancelled"
BLOCKED = "blocked"

ACTIVE = frozenset({SUBMITTING, UNCERTAIN, ACCEPTED, RUNNING, FETCHING, CANCELLING})
TERMINAL = frozenset({COMPLETED, FAILED, REJECTED, CANCELLED, BLOCKED})
TASK_STATES = ACTIVE | TERMINAL | {WAITING}
# Campaign states reuse task state names: accepted, running, cancelling, and these.
CAMPAIGN_TERMINAL = frozenset({COMPLETED, FAILED, CANCELLED})

SLURM_TERMINAL = frozenset({"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL", "PREEMPTED",
                            "BOOT_FAIL", "OUT_OF_MEMORY", "DEADLINE", "REVOKED"})
SLURM_RETRYABLE = frozenset({"NODE_FAIL", "PREEMPTED", "BOOT_FAIL"})
SLURM_RUNNING = frozenset({"RUNNING", "COMPLETING"})

# Effects the worker performs for a Decision.
CANCEL_JOB = "cancel_job"  # cancel the Slurm job, then record the step
SALVAGE = "salvage"        # record the step, collect evidence best-effort, then record salvaged()
RETRIEVE = "retrieve"      # record the step, retrieve outputs, then record delivered() or undelivered()
HOLD = "hold"              # record the step if there is one; nothing more in this pass
ADMIT = "admit"            # the task may be submitted if capacity allows

INTERRUPTED = "interrupted submission; reconcile by unique job name before any retry"
INCOMPLETE = "scheduler failed or required outputs missing"
DEPENDENCY_FAILED = "a required task did not complete"


class Step(NamedTuple):
    """A task transition. The Result event has kind == state and payload == event."""
    state: str
    fields: dict
    event: dict


class Decision(NamedTuple):
    step: Step | None
    effect: str | None


def _step(state, fields, event=None):
    return Step(state, fields, dict(fields) if event is None else event)


def _ends_in_cancellation(observation, cancelling):
    return observation["state"] == "CANCELLED" or cancelling


def _retry_delay(retry_backoff_seconds, attempt):
    return retry_backoff_seconds * 2 ** (attempt - 1)


def intent(attempt, job_name):
    """A waiting task records its submission intent before any Slurm call."""
    return _step(SUBMITTING, {"attempt": attempt, "job_name": job_name, "job_id": None, "error": None,
                              "observation": None, "eligible_at": 0},
                 {"attempt": attempt, "job_name": job_name})


def uncertain_receipt(error):
    """The receipt recorded when the submit call itself raised."""
    return {"outcome": UNCERTAIN, "error": error}


def submitted(receipt):
    """Only a numeric job id proves acceptance; only an explicit refusal proves rejection.
    Receipt outcomes use the task state names."""
    outcome = receipt.get("outcome", UNCERTAIN)
    if outcome == ACCEPTED and str(receipt.get("job_id", "")).isdigit():
        state = ACCEPTED
    elif outcome == REJECTED:
        state = REJECTED
    else:
        state = UNCERTAIN
    return _step(state, {"job_id": receipt.get("job_id"), "error": receipt.get("error")})


def observed(task, observation, *, cancelling, max_attempts, now):
    """One scheduler observation, or None, for an active task that has a job name.
    task is the record from before this pass."""
    if not observation:
        if task["state"] == SUBMITTING:
            return Decision(_step(UNCERTAIN, {"error": INTERRUPTED}), None)
        return Decision(None, None)
    carried = (task.get("observation") or {}).get("fetch_attempts", 0)
    observation = {**observation, "fetch_attempts": carried}
    state = observation["state"]
    job = {"job_id": observation["job_id"], "observation": observation}
    if cancelling and state not in SLURM_TERMINAL:
        return Decision(_step(CANCELLING, job), CANCEL_JOB)
    if state not in SLURM_TERMINAL:
        return Decision(_step(RUNNING if state in SLURM_RUNNING else ACCEPTED, {**job, "error": None}), None)
    fetching = _step(FETCHING, job)
    if _ends_in_cancellation(observation, cancelling) or (state in SLURM_RETRYABLE and task["attempt"] < max_attempts):
        return Decision(fetching, SALVAGE)
    if task["state"] == FETCHING and task["eligible_at"] > now:
        return Decision(fetching, HOLD)
    return Decision(fetching, RETRIEVE)


def salvaged(task, observation, *, cancelling, retry_backoff_seconds, now):
    """After best-effort evidence collection: cancellation, or a bounded infrastructure retry."""
    if _ends_in_cancellation(observation, cancelling):
        return _step(CANCELLED, {"observation": observation})
    return _step(WAITING, {"eligible_at": now + _retry_delay(retry_backoff_seconds, task["attempt"]),
                           "observation": observation,
                           "error": f"infrastructure failure: {observation['state']}; bounded retry scheduled"})


def scheduler_succeeded(observation):
    return observation["state"] == "COMPLETED" and observation.get("exit_code", "0:0") == "0:0"


def delivered(metadata, *, successful):
    """Retrieved outputs. Completion needs scheduler success and every declared output."""
    complete = successful and not metadata["missing"]
    return _step(COMPLETED if complete else FAILED,
                 {"artifacts": {**metadata, "complete": complete}, "error": None if complete else INCOMPLETE})


def undelivered(observation, error, *, conflict, max_fetch_attempts, retry_backoff_seconds, now):
    """Retrieval raised. Invalid evidence fails the task; a transfer failure retries the transfer, never compute."""
    if conflict:
        return _step(FAILED, {"error": error})
    observation = {**observation, "fetch_attempts": observation["fetch_attempts"] + 1}
    return _step(FAILED if observation["fetch_attempts"] >= max_fetch_attempts else FETCHING,
                 {"error": error, "observation": observation, "eligible_at": now + retry_backoff_seconds})


def admission(task, dependency_states, *, cancelling, now):
    """A task considered for submission. dependency_states maps task_id to state."""
    if task["state"] != WAITING or task["eligible_at"] > now:
        return Decision(None, HOLD)
    if cancelling:
        return Decision(_step(CANCELLED, {}), None)
    dependencies = task["spec"]["depends_on"]
    if any(dependency_states[d] in TERMINAL - {COMPLETED} for d in dependencies):
        return Decision(_step(BLOCKED, {"error": DEPENDENCY_FAILED}), None)
    if any(dependency_states[d] != COMPLETED for d in dependencies):
        return Decision(None, HOLD)
    return Decision(None, ADMIT)


def cancel_request(task):
    """Cancellation fences a task that is not submitted."""
    return _step(CANCELLED, {}) if task["state"] == WAITING else None


def campaign_state(current, task_states):
    """The campaign state its task states imply, or None when it does not change."""
    states = set(task_states)
    if states <= TERMINAL:
        state = COMPLETED if states == {COMPLETED} else CANCELLED if states <= {COMPLETED, CANCELLED} else FAILED
    else:
        state = CANCELLING if current == CANCELLING else RUNNING
    return None if state == current else state


def cancel_campaign(current):
    """A cancel request sets cancelling on an unfinished campaign, again if it is already cancelling."""
    return None if current in CAMPAIGN_TERMINAL else CANCELLING


def attempt_outcome(task_state, observation):
    """An attempt records its task's state. The infrastructure failure that sent the task back
    to waiting stays on the finished attempt, also when the task is then cancelled or blocked."""
    scheduler_state = (observation or {}).get("state")
    if task_state in (WAITING, CANCELLED, BLOCKED) and scheduler_state in SLURM_RETRYABLE:
        return scheduler_state
    return task_state
