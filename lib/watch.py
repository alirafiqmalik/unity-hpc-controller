"""hpc-watch — opt-in foreground requeue.

Spec: docs/scaffold-axes-spec.md §8. Decision: docs/design-decisions.md §3.7.

The watcher is a black box on top of `unityHPC/run.sh`: it reads only the
text `run.sh status` prints and drives `run.sh run` (retry) and `run.sh
fetch`. It never opens the ledger, never calls `sacct`, never calls
`sbatch` -- those stay inside run.sh (D9's partition ladder included). A
second copy of the SLURM terminal-state list lives here, not because the
ledger's copy (lib/campaign.TERMINAL) is wrong, but because importing it
would tempt a future edit to reach past run.sh's text contract into the
database it is this module's whole point not to touch.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

TERMINAL = frozenset({
    "COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY",
    "NODE_FAIL", "BOOT_FAIL", "DEADLINE", "REVOKED", "PREEMPTED",
})
FAILURE = TERMINAL - {"COMPLETED", "CANCELLED"}

#: A job that reaches a failure state this soon after the watcher first saw
#: it is almost certainly a config/code bug, not a flaky cluster -- retrying
#: it would just burn the budget on every task the same way. Not a retry.
DIED_YOUNG_SECONDS = 120

DEFAULT_POLL_SECONDS = 30

_RECORDED_RE = re.compile(r"Recorded job (\S+) in campaign")


# ─── run.sh text contract ──────────────────────────────────────────────────

def parse_jobs_table(output: str) -> list[dict]:
    """Parse the `job_id exp partition status` table `run.sh jobs`/`status`
    print. Empty when the campaign has no recorded jobs."""
    rows: list[dict] = []
    started = False
    for line in output.splitlines():
        if not started:
            if line.startswith("job_id"):
                started = True
            continue
        if not line.strip() or line.startswith("("):
            break
        parts = line.split()
        if len(parts) < 4:
            continue
        rows.append({"job_id": parts[0], "exp": parts[1],
                     "partition": parts[2], "status": parts[3]})
    return rows


def parse_recorded_job_id(output: str) -> str | None:
    m = _RECORDED_RE.search(output)
    return m.group(1) if m else None


def group_id(job_id: str) -> str:
    """A fan-out child `<parent>_<index>` collapses onto its parent; a
    single job is its own group."""
    return job_id.split("_", 1)[0]


def scope_rows(rows: list[dict], job: str | None,
                retry_jobs: frozenset | set = frozenset()) -> list[dict]:
    """In-scope rows for this tick. A retry carries a job id the scheduler
    picked, so `--job <parent>` would filter out the very job this watcher
    submitted -- and then never see it reach a terminal state. Retries of
    in-scope work stay in scope."""
    if not job:
        return rows
    return [r for r in rows
            if group_id(r["job_id"]) == job or r["job_id"] in retry_jobs]


def groups_terminal(rows: list[dict]) -> bool:
    return all(r["status"] in TERMINAL for r in rows)


# ─── run.sh invocation ─────────────────────────────────────────────────────

def call_run_sh(run_sh: Path, campaign: str, *args: str,
                 env: dict | None = None) -> subprocess.CompletedProcess:
    cmd = ["bash", str(run_sh), *args, "--campaign", campaign]
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


# ─── state file ─────────────────────────────────────────────────────────

def state_path(project_dir: Path, campaign: str) -> Path:
    return Path(project_dir) / ".unity_state" / f"{campaign}.watch.json"


def acquire_lock(path: Path):
    """Open `path` and take a non-blocking exclusive flock on it. Returns the
    open file handle on success, `None` when another watcher already holds
    it -- the caller is the second watcher on this campaign and must exit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def load_state(fh) -> dict:
    fh.seek(0)
    raw = fh.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {}
    data.setdefault("first_seen", {})
    data.setdefault("processed", [])
    data.setdefault("tokens", {})
    data.setdefault("job_token", {})
    return data


def save_state(fh, state: dict) -> None:
    fh.seek(0)
    fh.truncate()
    json.dump(state, fh, indent=2, sort_keys=True)
    fh.write("\n")
    fh.flush()
    os.fsync(fh.fileno())


# ─── retry budget ───────────────────────────────────────────────────────

def update_first_seen(state: dict, rows: list[dict], now: float) -> None:
    for r in rows:
        state["first_seen"].setdefault(r["job_id"], now)


def resolve_retry_outcomes(state: dict, rows: list[dict]) -> None:
    """Fold a terminal retry job's outcome back onto the token it retried."""
    job_token = state["job_token"]
    for r in rows:
        token = job_token.get(r["job_id"])
        if token and r["status"] in TERMINAL:
            entry = state["tokens"].setdefault(token, {})
            if entry.get("retry_result") is None:
                entry["retry_result"] = ("success" if r["status"] == "COMPLETED"
                                          else "failed")


def plan_retries(state: dict, rows: list[dict], now: float) -> list[tuple[str, str]]:
    """(job_id, token) pairs newly eligible for a retry submission.

    No retry if that token's previous retry failed (or is even in flight --
    one retry per token, ever); no retry if the job reached a failure state
    within DIED_YOUNG_SECONDS of when this watcher first observed it.
    """
    eligible = []
    for r in rows:
        job_id, token, status = r["job_id"], r["exp"], r["status"]
        if status not in FAILURE or job_id in state["processed"]:
            continue
        state["processed"].append(job_id)
        died_young = (now - state["first_seen"].get(job_id, now)) < DIED_YOUNG_SECONDS
        already_retried = state["tokens"].get(token, {}).get("retried", False)
        if died_young or already_retried:
            if not already_retried:
                state["tokens"].setdefault(token, {})["died_young"] = True
            continue
        eligible.append((job_id, token))
    return eligible


def retries_in_flight(state: dict) -> bool:
    """True while a retry this watcher submitted has not yet been seen
    terminal. The job it retried is terminal by definition, so without this
    the loop would call `fetch` and exit on the same tick that submitted the
    retry -- collecting results the retry had not produced yet."""
    return any(e.get("retried") and e.get("retry_job_id")
               and e.get("retry_result") is None
               for e in state["tokens"].values())


def step(run_sh: Path, campaign: str, job: str | None, state: dict, now: float,
          env: dict | None = None) -> list[dict]:
    """One poll: read status, resolve any retry outcomes, submit newly
    eligible retries. Returns the in-scope rows for this tick."""
    proc = call_run_sh(run_sh, campaign, "status", env=env)
    rows = scope_rows(parse_jobs_table(proc.stdout), job, set(state["job_token"]))

    update_first_seen(state, rows, now)
    resolve_retry_outcomes(state, rows)

    for job_id, token in plan_retries(state, rows, now):
        rproc = call_run_sh(run_sh, campaign, "run", token, env=env)
        entry = state["tokens"].setdefault(token, {})
        entry["retried"] = True
        entry["retry_result"] = None
        entry["source_job_id"] = job_id
        new_id = parse_recorded_job_id(rproc.stdout)
        if new_id:
            entry["retry_job_id"] = new_id
            state["job_token"][new_id] = token

    return rows


# ─── main loop / CLI ────────────────────────────────────────────────────

def default_campaign() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def watch(run_sh: Path, campaign: str, job: str | None, poll_seconds: int, fh,
          sleep=time.sleep, clock=time.time, env: dict | None = None) -> None:
    state = load_state(fh)
    while True:
        rows = step(run_sh, campaign, job, state, clock(), env=env)
        save_state(fh, state)
        if groups_terminal(rows) and not retries_in_flight(state):
            break
        sleep(poll_seconds)
    call_run_sh(run_sh, campaign, "fetch", env=env)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hpc-watch",
        description="Opt-in foreground watcher: poll run.sh status, retry "
                     "within budget, fetch, exit. Ctrl-C stops it.",
        epilog="Reads HPC_PROJECT_DIR (default: cwd) to find unityHPC/run.sh.",
    )
    parser.add_argument("--campaign")
    parser.add_argument("--job", help="pin to one fan-out group by its parent job id")
    parser.add_argument("--poll", type=int, default=DEFAULT_POLL_SECONDS,
                         help=f"seconds between polls (default: {DEFAULT_POLL_SECONDS})")
    args = parser.parse_args(argv)

    project_dir = Path(os.environ.get("HPC_PROJECT_DIR", os.getcwd()))
    run_sh = project_dir / "unityHPC" / "run.sh"
    if not run_sh.is_file():
        print(f"hpc-watch: no unityHPC/run.sh found in {project_dir}", file=sys.stderr)
        return 2

    campaign = args.campaign or default_campaign()
    path = state_path(project_dir, campaign)
    fh = acquire_lock(path)
    if fh is None:
        print(f"hpc-watch: another watcher already holds {path} "
              f"-- one watcher per campaign", file=sys.stderr)
        return 1

    try:
        watch(run_sh, campaign, args.job, args.poll, fh)
    except KeyboardInterrupt:
        print("hpc-watch: stopped", file=sys.stderr)
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
