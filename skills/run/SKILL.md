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

`unity_traffic` reports historical GPU use, not live queue counts or an
estimated wait. For a live answer, run `squeue` through `unity_ssh` before a
large submission.

If the traffic result has no data, print this warning:

> "No historical traffic data is available. The scheduler can still accept this
> job, but its wait time is unknown. For shared usage data, run
> `/unity-hpc:recon` and the telemetry sync."

Do not invent a partition recommendation or a wait time. Partition access comes
from `unity_cluster_profile`. Offer a preempt partition only when that profile
lists it as available, and the job is checkpoint-safe.

**3. Submit the job**

```bash
bash unityHPC/run.sh run <exp> [--campaign <name>] [extra sbatch args...]
```

- `--campaign <name>` groups related jobs. Omit it, and the campaign is today's
  UTC date (`YYYYMMDD`). This default is correct for one-off jobs.
- To preview a job without submission, add `--dry-run`. It prints the script and
  touches nothing on the cluster.
- Every other argument goes straight to `sbatch`, for example `--qos=short`.

### Change one setting for one job

Set any `.env` value for one invocation. Put it in front of the command. The
`.env` file stays as it is:

```bash
JOB_COMMAND="echo smoke-test" SLURM_MEM=1G bash unityHPC/run.sh run smoke
```

An empty value is a deliberate value, not an omission. This is how you run one
CPU job in a project whose `.env` requests a GPU:

```bash
SLURM_GPUS= SLURM_PARTITION=cpu bash unityHPC/run.sh run smoke
```

Settable this way: `JOB_COMMAND`, `WALLTIME`, `SLURM_PARTITION`, `SLURM_CPUS`,
`SLURM_MEM`, `SLURM_NODES`, `SLURM_GPUS`, `SLURM_GPU_TYPE`, `SLURM_CONSTRAINT`,
`SLURM_ACCOUNT`, `SLURM_PARTITION_FALLBACK`, `SLURM_PARTITION_WALLTIME_CAP`,
`REMOTE_DIR`, `UNITY_HOST`, `CAMPAIGN`, `MODULES`, `VENV_PATH`, `HF_HOME`,
`USER_EMAIL`.

### Try more than one partition

A full partition, or one closed to the account, makes `sbatch` refuse the job.
Give the dispatcher an ordered list and it retries down it. The first entry is
the primary:

```bash
SLURM_PARTITION_FALLBACK="cpu cpu-preempt ood-shared" bash unityHPC/run.sh run smoke
```

Partitions have different walltime ceilings, so a retry that sends the same
walltime to a shorter-ceiling queue fails again for an unrelated reason. Give
the ceilings and each attempt is clamped to fit:

```bash
SLURM_PARTITION_FALLBACK="cpu ood-shared" \
SLURM_PARTITION_WALLTIME_CAP="ood-shared=08:00:00" \
  bash unityHPC/run.sh run smoke
```

Four rules govern this:

- Unset `SLURM_PARTITION_FALLBACK` keeps the single-attempt behaviour exactly.
- Naming `SLURM_PARTITION` yourself disables the ladder. You named a partition,
  so only that one is tried. A blank `SLURM_PARTITION=` names nothing, and
  leaves the ladder running — that is the same "unset it for one run" idiom as
  `SLURM_GPUS=` above.
- `run.sh jobs` and `run.sh status` report the partition the job **landed on**,
  which is not always the one first requested.
- Only a refused `sbatch` moves to the next partition. If `sbatch` accepts the
  job but its reply carries no job id, the dispatcher stops and warns: that job
  is queued and unrecorded, so check `squeue` before resubmitting or it runs
  twice.

A cap that shortens the request says so on stderr, naming the partition and
both walltimes. A cap-table entry it cannot read — no `=`, or a value that is
not `HH:MM:SS`, `D-HH:MM:SS` or `MM:SS` — is named on stderr and skipped, so a
typo costs you the ceiling, not the submission.

`--dry-run` previews the first rung of the same plan a real submit walks,
carrying the `--partition` and clamped `--time` that submission would, and
lists the rest of the ladder under it.

### Pass values into the job command

The dispatcher records `MODEL`, `DATASET`, `SEED` and `CONFIG_HASH` as
provenance. These names do **not** reach the node. To give the job command a
value, use `sbatch --export`:

```bash
bash unityHPC/run.sh run sweep-a --export=ALL,MODEL=llama-3-8b
```

Keep `ALL` in the list. Without it, SLURM sends no other environment to the job.
The job template runs `set -euo pipefail`. It then runs `eval "$JOB_COMMAND"`.
If the command reads a name that nobody exported, the job stops with
`MODEL: unbound variable`.

### If the script does not parse

The dispatcher parses the rendered script before it submits it. If the script
does not parse, the dispatcher prints the parse error. It submits nothing and
records nothing. Correct `unityHPC/job_template.sh` or `JOB_COMMAND`.

Your local shell and the cluster shell can differ. If the cluster accepts a
script that your shell rejects, set `UNITY_SKIP_SYNTAX_CHECK=1`.

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

`run.sh logs` and `unity_logs` both print stdout and stderr. When a job fails,
the reason is almost always in the `.err` section.

Nothing runs in the background for the user. A state check and an output fetch
are both explicit actions.

## Multi-node note

If `SLURM_NODES` is more than 1 in `.env`, the `ml` job template runs the job
under `torchrun`. The entrypoint in `JOB_COMMAND` must then support `torchrun`.
