---
name: sweep
description: "Submit a batch of related Unity jobs under one campaign — respects account submit limits and queue depth."
---

# unity-hpc:sweep

Announce: "Using unity-hpc:sweep to submit a batch of jobs to Unity."

A sweep is not a separate mechanism: it is N ordinary submissions sharing one
`--campaign`, which is what makes them a single unit for status, fetch and
telemetry. Vary the jobs however the project already varies them — a different
`JOB_COMMAND` per variant, an argument the entrypoint reads, or an env var.

## Steps

**1. Source env**: `set -a && . unityHPC/.env && set +a`

**2. Check account limits**
Call `mcp__unity-hpc__unity_cluster_profile` and read `MaxSubmitJobs` for the
account. If there is no profile yet, run `/unity-hpc:recon` first.

Count the variants. If the count exceeds `MaxSubmitJobs`, stop and tell the user
the cap — offer to submit the first batch now and the rest later. Do not submit
past the limit: SLURM will reject the overflow and the ledger will disagree with
the cluster.

**3. Check queue**
Call `mcp__unity-hpc__unity_traffic`. Print the queue state. If it is deep
(>50 pending), say so and offer the `-preempt` partition or an off-peak window
before committing a whole batch.

**4. Confirm the plan before submitting**
Print the exact list of jobs to be submitted and the campaign name, and get the
user's go-ahead. A sweep is the one place where a mistake is multiplied.

**5. Submit the batch**
One campaign for the whole sweep:
```bash
CAMPAIGN=<sweep-name>
for variant in <variants>; do
    bash unityHPC/run.sh run "${variant}" --campaign "$CAMPAIGN"
done
```
Submit sequentially — each call is a short SSH round-trip, and serial submission
keeps the ledger consistent and the login node unloaded.

If any submission fails, stop and report which ones made it. Never silently
continue past a rejection: the account limit is the usual cause.

**6. Verify what landed**
```bash
bash unityHPC/run.sh jobs --campaign "$CAMPAIGN"
```
Confirm the row count matches the number of variants, then print:
"Submitted N jobs for campaign `<name>`."

**7. Print next steps**
```
Live state:  bash unityHPC/run.sh status --campaign <name>
Output:      /unity-hpc:fetch
```
Nothing collects results on its own — fetch when the jobs are terminal.
