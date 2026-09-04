"""Issue #24: scripts/hpc-watch opt-in foreground requeue.

Spec: docs/scaffold-axes-spec.md §8 / docs/design-decisions.md §3.7. hpc-watch
treats `unityHPC/run.sh` as a black box -- it only reads the text `run.sh
status` prints and drives `run.sh run`/`fetch`. Tests below stand a fake
run.sh in for the real one (its own correctness is covered by
test_cancel.py, test_partition_fallback.py, etc.) and drive `lib.watch`'s
pure step/lock functions directly, without a real poll-and-sleep loop.
"""

import fcntl
import json
import subprocess

import pytest

from lib import watch

FAKE_RUN_SH = r"""#!/usr/bin/env bash
echo "$@" >>"$STUB_CALLS"
case "$1" in
    status)
        echo "Campaign: ${CAMPAIGN_NAME}"
        printf '%-10s %-20s %-14s %s\n' job_id exp partition status
        printf '%s\n' "$STUB_JOBS_TABLE"
        ;;
    run)
        echo "Recorded job ${STUB_NEW_JOB_ID} in campaign ${CAMPAIGN_NAME} (.unity_state/${CAMPAIGN_NAME}.db)"
        ;;
    fetch)
        echo "Fetched to _results/${CAMPAIGN_NAME}/"
        ;;
esac
"""


@pytest.fixture
def fake_run_sh(tmp_path):
    path = tmp_path / "run.sh"
    path.write_text(FAKE_RUN_SH)
    path.chmod(0o755)
    return path


def _env(tmp_path, jobs_table="", campaign="c1", new_job_id="999"):
    return {
        "PATH": "/usr/bin:/bin",
        "STUB_CALLS": str(tmp_path / "calls.log"),
        "STUB_JOBS_TABLE": jobs_table,
        "STUB_NEW_JOB_ID": new_job_id,
        "CAMPAIGN_NAME": campaign,
    }


def _calls(tmp_path):
    log = tmp_path / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


# ─── lock: one watcher per campaign ─────────────────────────────────────

def test_second_watcher_on_same_campaign_exits(tmp_path):
    path = tmp_path / "c1.watch.json"

    first = watch.acquire_lock(path)
    assert first is not None

    second = watch.acquire_lock(path)
    assert second is None, "a second watcher on the same campaign must not get the lock"

    fcntl.flock(first.fileno(), fcntl.LOCK_UN)
    first.close()

    third = watch.acquire_lock(path)
    assert third is not None, "the lock is free again once the first watcher exits"
    third.close()


# ─── restart reuses the persisted budget ────────────────────────────────

def test_restarted_watcher_reuses_persisted_attempt_counts(tmp_path, fake_run_sh):
    path = tmp_path / "c1.watch.json"
    env = _env(tmp_path, jobs_table="12345 trial-a cpu FAILED")

    fh = watch.acquire_lock(path)
    state = watch.load_state(fh)
    state["tokens"]["trial-a"] = {"retried": True, "retry_result": "failed",
                                   "retry_job_id": "555"}
    watch.save_state(fh, state)
    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    fh.close()

    # "Restart": a fresh open of the same state file, as a new process would do.
    fh2 = watch.acquire_lock(path)
    assert fh2 is not None
    reloaded = watch.load_state(fh2)
    assert reloaded["tokens"]["trial-a"]["retried"] is True

    watch.step(fake_run_sh, "c1", None, reloaded, now=1_000_000.0, env=env)

    calls = _calls(tmp_path)
    assert not any(c.startswith("run ") for c in calls), \
        "a token that already used its retry must not hand out a fresh one after restart"
    fh2.close()


# ─── retry budget: died young ───────────────────────────────────────────

def test_job_that_fails_within_120s_is_not_retried(tmp_path, fake_run_sh):
    env = _env(tmp_path, jobs_table="12345 trial-a cpu FAILED")
    state = {"first_seen": {}, "processed": [], "tokens": {}, "job_token": {}}

    # First poll ever sees the job already FAILED: first_seen == now, so the
    # observed lifetime is 0s -- well under the 120s floor.
    watch.step(fake_run_sh, "c1", None, state, now=1_000_000.0, env=env)

    calls = _calls(tmp_path)
    assert not any(c.startswith("run ") for c in calls), \
        "a job dead within 120s of being first observed must not be retried"
    assert state["tokens"].get("trial-a", {}).get("retried") is not True


def test_job_failing_after_120s_is_retried(tmp_path, fake_run_sh):
    state = {"first_seen": {}, "processed": [], "tokens": {}, "job_token": {}}

    pending_env = _env(tmp_path, jobs_table="12345 trial-a cpu PENDING")
    watch.step(fake_run_sh, "c1", None, state, now=0.0, env=pending_env)

    failed_env = _env(tmp_path, jobs_table="12345 trial-a cpu FAILED", new_job_id="999")
    watch.step(fake_run_sh, "c1", None, state, now=200.0, env=failed_env)

    calls = _calls(tmp_path)
    assert any(c.startswith("run trial-a") for c in calls), \
        "a job that ran for over 120s before failing is within budget for one retry"
    assert state["tokens"]["trial-a"]["retried"] is True
    assert state["tokens"]["trial-a"]["retry_job_id"] == "999"
    assert state["job_token"]["999"] == "trial-a"


# ─── retry budget: one retry per token ──────────────────────────────────

def test_token_whose_retry_already_failed_is_not_retried_again(tmp_path, fake_run_sh):
    state = {"first_seen": {}, "processed": [], "tokens": {}, "job_token": {}}

    pending_env = _env(tmp_path, jobs_table="12345 trial-a cpu PENDING")
    watch.step(fake_run_sh, "c1", None, state, now=0.0, env=pending_env)

    failed_env = _env(tmp_path, jobs_table="12345 trial-a cpu FAILED", new_job_id="999")
    watch.step(fake_run_sh, "c1", None, state, now=200.0, env=failed_env)
    assert state["tokens"]["trial-a"]["retried"] is True

    # The retry job (999) itself now shows up terminal-failed on a later poll.
    retry_failed_env = _env(tmp_path, jobs_table="999 trial-a cpu FAILED")
    watch.step(fake_run_sh, "c1", None, state, now=210.0, env=retry_failed_env)

    calls = [c for c in _calls(tmp_path) if c.startswith("run trial-a")]
    assert len(calls) == 1, "a token gets exactly one retry, ever"
    assert state["tokens"]["trial-a"]["retry_result"] == "failed"


# ─── the watcher's own subprocess list ──────────────────────────────────

def test_watcher_subprocess_list_contains_only_run_sh(tmp_path, fake_run_sh, monkeypatch):
    calls = []
    real_run = subprocess.run

    def spy(cmd, *args, **kwargs):
        calls.append(list(cmd))
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(watch.subprocess, "run", spy)

    env = _env(tmp_path, jobs_table="12345 trial-a cpu COMPLETED")
    fh = watch.acquire_lock(tmp_path / "c1.watch.json")
    try:
        watch.watch(fake_run_sh, "c1", None, poll_seconds=0, fh=fh, env=env)
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()

    assert calls, "the watcher should have made at least one call"
    for cmd in calls:
        assert cmd[0] == "bash" and cmd[1] == str(fake_run_sh), (
            "the watcher must only ever invoke run.sh, never sbatch/sacct/sqlite directly")
        joined = " ".join(cmd)
        for forbidden in ("sbatch", "sacct", "sqlite3", "ssh"):
            assert forbidden not in joined


# ─── run.sh text contract ────────────────────────────────────────────────

def test_parse_jobs_table_handles_no_jobs_recorded():
    assert watch.parse_jobs_table("No jobs recorded for campaign c1.\n") == []


def test_parse_jobs_table_stops_before_the_updated_marker():
    output = (
        "Campaign: c1\n"
        "job_id     exp                  partition      status\n"
        "1          a                    cpu            COMPLETED\n"
        "(1 state(s) updated from sacct)\n"
    )
    rows = watch.parse_jobs_table(output)
    assert rows == [{"job_id": "1", "exp": "a", "partition": "cpu", "status": "COMPLETED"}]


def test_scope_rows_collapses_array_children_to_their_parent():
    rows = [{"job_id": "10_0", "exp": "a", "partition": "cpu", "status": "PENDING"},
            {"job_id": "10_1", "exp": "b", "partition": "cpu", "status": "PENDING"},
            {"job_id": "20", "exp": "c", "partition": "cpu", "status": "PENDING"}]
    scoped = watch.scope_rows(rows, "10")
    assert {r["job_id"] for r in scoped} == {"10_0", "10_1"}


def test_groups_terminal_is_true_only_when_every_row_is_terminal():
    assert watch.groups_terminal([]) is True
    assert watch.groups_terminal([{"status": "COMPLETED"}, {"status": "CANCELLED"}]) is True
    assert watch.groups_terminal([{"status": "COMPLETED"}, {"status": "RUNNING"}]) is False


# ─── the loop waits for the retry it submitted ──────────────────────────

def test_watcher_does_not_fetch_and_exit_on_the_tick_it_submits_a_retry(
        tmp_path, fake_run_sh):
    """Spec §8: "runs until every in-scope group is terminal, then fetch".

    The job a retry replaces is terminal by definition, so an exit test that
    only reads this tick's rows would fetch and quit before the retry it just
    submitted had produced anything.
    """
    state = {"first_seen": {}, "processed": [], "tokens": {}, "job_token": {}}

    watch.step(fake_run_sh, "c1", None, state, now=0.0,
               env=_env(tmp_path, jobs_table="12345 trial-a cpu PENDING"))
    rows = watch.step(fake_run_sh, "c1", None, state, now=200.0,
                      env=_env(tmp_path, jobs_table="12345 trial-a cpu FAILED",
                               new_job_id="999"))

    assert watch.groups_terminal(rows), "the replaced job is terminal on this tick"
    assert watch.retries_in_flight(state), "but its retry has not been seen yet"

    # The retry lands COMPLETED on a later poll -- only now may the loop exit.
    watch.step(fake_run_sh, "c1", None, state, now=400.0,
               env=_env(tmp_path, jobs_table="999 trial-a cpu COMPLETED"))
    assert not watch.retries_in_flight(state)


def test_watch_loop_keeps_polling_until_the_retry_is_terminal(tmp_path, fake_run_sh):
    """End to end over the real loop: FAILED -> retry -> the retry runs ->
    the retry completes. `fetch` must come after the retry is terminal."""
    table = tmp_path / "table.txt"
    tables = [
        "12345 trial-a cpu PENDING",
        "12345 trial-a cpu FAILED",
        "999 trial-a cpu RUNNING",
        "999 trial-a cpu COMPLETED",
    ]
    table.write_text(tables[0])

    # A stub that re-reads the table each call, so successive polls see the
    # campaign move.
    fake_run_sh.write_text(FAKE_RUN_SH.replace(
        'printf \'%s\\n\' "$STUB_JOBS_TABLE"', 'cat "$STUB_TABLE_FILE"; echo'))

    tick = {"n": 0}

    def clock():
        return tick["n"] * 200.0

    def sleep(_):
        tick["n"] += 1
        table.write_text(tables[min(tick["n"], len(tables) - 1)])

    env = _env(tmp_path, new_job_id="999")
    env["STUB_TABLE_FILE"] = str(table)

    fh = watch.acquire_lock(tmp_path / "c1.watch.json")
    try:
        watch.watch(fake_run_sh, "c1", None, poll_seconds=0, fh=fh,
                    sleep=sleep, clock=clock, env=env)
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()

    calls = _calls(tmp_path)
    assert any(c.startswith("run trial-a") for c in calls), "the retry was submitted"
    fetch_at = next(i for i, c in enumerate(calls) if c.startswith("fetch"))
    retry_at = next(i for i, c in enumerate(calls) if c.startswith("run trial-a"))
    assert fetch_at > retry_at, "fetch must not run on the tick that submitted the retry"
    # Two status polls after the retry: the retry RUNNING, then COMPLETED.
    assert len([c for c in calls[retry_at:] if c.startswith("status")]) >= 2

    state = json.loads((tmp_path / "c1.watch.json").read_text())
    assert state["tokens"]["trial-a"]["retry_result"] == "success"
