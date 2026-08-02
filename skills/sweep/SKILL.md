---
name: sweep
description: "Submit a batch of related Unity jobs under one campaign — respects account submit limits and queue depth."
---

# unity-hpc:sweep

Announce: "Using unity-hpc:sweep to submit a batch of jobs to Unity."

A sweep uses one manifest-driven SLURM array. The manifest contains one safe
experiment name per line. The shared campaign makes the array one unit for
status, fetch and telemetry.

Vary the jobs the way the project already varies them: a different `JOB_COMMAND`
for each variant, an argument that the entrypoint reads, or an env var.

## Steps

**1. Source the env file**

```bash
set -a && . unityHPC/.env && set +a
```

**2. Check the account limits**

Call `mcp__unity-hpc__unity_cluster_profile` and read `max_submit_jobs` for the
account. If there is no cluster configuration yet, run `/unity-hpc:recon` first.

The value is one of three answers, and each has its own branch:

| Printed | Meaning | What to do |
|---|---|---|
| a number | the account cap | compare the variant count against it |
| `no limit` | probed, no cap | continue |
| `not probed` | nobody has measured it | run `/unity-hpc:recon`, or ask the user to approve an uncapped batch |

Count the variants. If the count is more than the cap, stop and print the cap.
Offer to submit the first batch now, and the rest later.

Do not submit past the limit. SLURM rejects the overflow, and then the ledger
disagrees with the cluster.

**3. Check the queue**

Call `mcp__unity-hpc__unity_traffic` and print the queue state. If more than 50
jobs are pending, print that fact. Then offer the `-preempt` partition, or an
off-peak window, before the user commits a whole batch.

**4. Get approval for the plan**

Print the exact list of jobs and the campaign name. Then ask the user to approve.
A sweep is the one place where one mistake is multiplied.

**5. Submit the batch**

Write the experiment names to a manifest. Then submit one array for the whole
sweep:

```bash
CAMPAIGN=<sweep-name>
bash unityHPC/run.sh array variants.txt --campaign "$CAMPAIGN" --limit <N>
```

The `--limit` value controls the number of array tasks that can run at once.
Omit it when the scheduler and account limits allow all tasks to run.

Each task reads its own line from the manifest into `$EXP`. To vary anything
else, read `$EXP` in the job command, or pass values with `sbatch --export`:

```bash
bash unityHPC/run.sh array variants.txt --campaign "$CAMPAIGN" \
    --export=ALL,MODEL=llama-3-8b
```

The job template runs `set -euo pipefail`. It then runs `eval "$JOB_COMMAND"`.
If the command reads a name that nobody exported, the job stops with
`MODEL: unbound variable`.

If submission fails, stop and report the scheduler error. The ledger records
each array task as `<job-id>_<task-id>` after SLURM accepts the parent job.

The dispatcher parses the rendered array script before it submits it. If the
script does not parse, the dispatcher submits nothing and records nothing.
Report that error. Do not retry it: each task fails on its first line.

**6. Check what landed**

```bash
bash unityHPC/run.sh jobs --campaign "$CAMPAIGN"
```

Check that the row count matches the number of variants. Then print: "Submitted
N array tasks for campaign `<name>`."

**7. Print the next steps**

```
Live state:  bash unityHPC/run.sh status --campaign <name>
Output:      /unity-hpc:fetch
```

Nothing collects the results on its own. Fetch them when every job is terminal.
