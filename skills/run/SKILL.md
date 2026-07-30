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
Historical GPU use: <best_hours_utc> is usually quiet; <worst_hours_utc> is busy
Recommendation: submit in a quiet UTC hour when the work is not urgent
```

`unity_traffic` reports historical GPU utilization, not live queue counts or an
estimated wait. For a live answer, run `squeue` through `unity_ssh` before a
large submission.

If the traffic result shows no data, print this warning:

> "No historical traffic data is available. The scheduler can still accept this
> job, but its wait time is unknown. Run `/unity-hpc:recon` and telemetry sync
> when shared usage data is needed."

Do not invent a partition recommendation or a wait time. Partition access comes
from `unity_cluster_profile`; only offer a preempt partition when that profile
shows it is available and the job is checkpoint-safe.

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
