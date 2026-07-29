---
name: run
description: "Submit a single job to Unity SLURM — queue-aware, works for any job type (CPU, GPU, multi-node), and records the job so status and fetch can find it."
---

# unity-hpc:run

Announce: "Using unity-hpc:run to submit a job to Unity."

## Steps

**1. Verify and source env**
Check `unityHPC/.env` exists, then: `set -a && . unityHPC/.env && set +a`
If it is missing, run `/unity-hpc:setup` first.

**2. Check queue conditions**
Call MCP tool `mcp__unity-hpc__unity_traffic`. Print:
```
Queue: <N> running, <M> pending
Estimated wait: ~Xmin (<partition>)
Recommendation: <partition>
```
If `current_pending > 30`, warn:
> "Queue is deep (~Xmin estimated wait on `<partition>`). Options:
> (a) Use the matching `-preempt` partition [usually faster when the queue is deep]
> (b) Wait for off-peak (best hours: <best_submit_hours_utc>)
> (c) Proceed anyway"

Ask the user to choose; default to the recommendation from traffic data.
A preempt partition trades wait time for the risk of being killed mid-run — only
suggest one for work that is short or checkpointed.

**3. Submit the job**
```bash
bash unityHPC/run.sh run <exp> [--campaign <name>] [extra sbatch args...]
```
- `--campaign <name>` groups related jobs. Omit it and the campaign is today's
  UTC date (`YYYYMMDD`) — the right default for one-off jobs.
- To preview without submitting, add `--dry-run`: it prints what would be
  submitted and touches nothing on the cluster.
- Any other argument is passed straight through to `sbatch` (e.g. `--qos=short`).

**4. Confirm submission**
`run.sh` prints the scheduler reply followed by the ledger line:
```
Submitted batch job 12345
Recorded job 12345 in campaign 20260727 (.unity_state/20260727.db)
```
Both lines matter. If you instead see `WARNING ... could not be recorded`, the
job **is queued** but no management tool can see it — report the job id
explicitly to the user so it is not lost.

**5. Print next steps**
```
Job <id> submitted to <partition> (campaign <name>).
  Live state:  bash unityHPC/run.sh status
  Output:      bash unityHPC/run.sh logs
  Retrieve:    /unity-hpc:fetch
```

Nothing runs in the background on the user's behalf. Checking state and
retrieving output are explicit actions.

## Multi-node note
If `SLURM_NODES > 1` in `.env`, the `ml` job template launches under `torchrun`.
Make sure the entrypoint in `JOB_COMMAND` is distributed-launch compatible.
