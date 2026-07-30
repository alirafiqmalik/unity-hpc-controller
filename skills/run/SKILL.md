---
name: run
description: "Submit a single job to Unity SLURM — queue-aware, works for any job type (CPU, GPU, multi-node), and records the job so status and fetch can find it."
---

# unity-hpc:run

Announce: "Using unity-hpc:run to submit a job to Unity."

## Steps

**1. Check the env file, then source it**

Check that `unityHPC/.env` exists. Then run:

```bash
set -a && . unityHPC/.env && set +a
```

If the file is absent, run `/unity-hpc:setup` first.

**2. Check the queue**

Call the MCP tool `mcp__unity-hpc__unity_traffic`. Print this block:

```
Queue: <N> running, <M> pending
Estimated wait: ~Xmin (<partition>)
Recommendation: <partition>
```

If `current_pending` is more than 30, print this warning:

> "Queue is deep (~Xmin estimated wait on `<partition>`). Options:
> (a) Use the matching `-preempt` partition [faster when the queue is deep]
> (b) Wait for off-peak (best hours: <best_submit_hours_utc>)
> (c) Proceed anyway"

Ask the user to choose. The default is the recommendation from the traffic data.

A preempt partition trades wait time for the risk of a kill mid-run. Offer one
only for work that is short, or that writes checkpoints.

**3. Submit the job**

```bash
bash unityHPC/run.sh run <exp> [--campaign <name>] [extra sbatch args...]
```

- `--campaign <name>` groups related jobs. Omit it, and the campaign is today's
  UTC date (`YYYYMMDD`). This default is correct for one-off jobs.
- To preview a job without submission, add `--dry-run`. It prints the script and
  touches nothing on the cluster.
- Every other argument goes straight to `sbatch`, for example `--qos=short`.

**4. Check the submission**

`run.sh` prints the scheduler reply, and then the ledger line:

```
Submitted batch job 12345
Recorded job 12345 in campaign 20260727 (.unity_state/20260727.db)
```

Both lines matter. If you see `WARNING ... could not be recorded` instead, the
job is in the queue, but no management tool can see it. Print the job id to the
user, so that the job is not lost.

**5. Print the next steps**

```
Job <id> submitted to <partition> (campaign <name>).
  Live state:  bash unityHPC/run.sh status
  Output:      bash unityHPC/run.sh logs
  Retrieve:    /unity-hpc:fetch
```

Nothing runs in the background for the user. A state check and an output fetch
are both explicit actions.

## Multi-node note

If `SLURM_NODES` is more than 1 in `.env`, the `ml` job template runs the job
under `torchrun`. The entrypoint in `JOB_COMMAND` must then support `torchrun`.
