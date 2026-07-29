---
name: setup
description: "Bootstrap a new Unity HPC experiment — verifies SSH, syncs code to /work, starts cluster-intel poller, runs recon if needed."
---

# unity-hpc:setup

Announce: "Using unity-hpc:setup to bootstrap a new Unity HPC experiment."

## Steps

Execute in order. Every step is safe to re-run: each detects existing state and
reports skip-vs-create rather than clobbering. Stop and report clearly on failure.

**1. Determine the project type**

Ask the user: is this project **cpu** (CPU-only jobs), **gpu** (single-node GPU),
or **ml** (multi-node training via torchrun)? Do not guess — the answer selects
the job template. If they are unsure, `cpu` is the safe default and can be
regenerated later.

**2. Generate the unityHPC/ scaffold**

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/hpc-scaffold" --type <cpu|gpu|ml> --dry-run
```

Show the user what will change, then run it without `--dry-run` to apply.

This writes `unityHPC/{run.sh,job_template.sh,sync.sh,.env}`. An existing `.env`
is always preserved. Any other file that differs from the canonical template is
moved to `unityHPC/.pre-redesign/<name>` and replaced — the command reports every
move. If the project previously carried a hand-written `run.sh`, tell the user
where it went and that the generated dispatcher now owns that contract.

**3. Fill in .env**

`unityHPC/.env` needs three values before anything can run:
`SLURM_ACCOUNT`, `REMOTE_DIR`, and `JOB_COMMAND`. Ask the user for them, or ask
them to edit the file. Stop here until they confirm.

**4. SSH check**

```bash
set -a && . unityHPC/.env && set +a
ssh "$UNITY_HOST" 'echo unity-ok'
```

Expected: `unity-ok`. If it fails, diagnose SSH config, VPN (campus or UMass VPN),
and key auth. Do not proceed until SSH works.

**5. Create the remote directory**

```bash
ssh "$UNITY_HOST" "mkdir -p ${REMOTE_DIR}/_slurm"
```

**6. Sync the project**

```bash
bash unityHPC/sync.sh
```

Expected: `Sync done.`

**7. Verify the dispatcher renders**

```bash
bash unityHPC/run.sh render smoke-test
```

This prints the sbatch script and submits nothing. Confirm the `#SBATCH` lines
match what the user expects — particularly `--time`, `--mem`, and (for gpu/ml)
`--gres`.

**8. Experiment branch (only if this is a git repo)**

```bash
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    BRANCH="unity/$(date +%Y-%m-%d)"
    if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
        git checkout "$BRANCH"
        echo "Branch $BRANCH already exists — reusing it."
    else
        git checkout -b "$BRANCH"
    fi
else
    echo "Not a git repository — skipping branch creation."
fi
```

If it is not a repo, offer to run `git init` but **do not** do so unasked, and do
not treat this as a failure. Version control is not required to run jobs.

**9. Initialise results.tsv (if absent)**

```bash
[ -f results.tsv ] || printf 'commit\tmetric\tvalue\tstatus\tdescription\n' > results.tsv
```

The columns are the project's to choose — everything downstream reads this
header rather than assuming a schema. If the user already tracks results
elsewhere, skip this file entirely.

**9b. Optional — declare a headline metric**

Ask, but **default to skipping**: does this project have one number that decides
whether a run was good (a loss, an accuracy, a throughput, a residual)?

- **No / not sure** → skip. `unity_results` will report whatever each job prints
  and rank nothing. This is the right answer for most projects, and it is what
  keeps the plugin honest about work it knows nothing about.
- **Yes** → write `unityHPC/metrics.json` with the user's own metric names:

```json
{
  "primary": "val_bpb",
  "goal": "min",
  "report": ["val_bpb", "peak_vram_mb", "mfu_percent"],
  "labels": {"peak_vram_mb": "vram_mb"}
}
```

`primary` + `goal` (`min`/`max`) enable "best job" reporting; `report` puts those
columns first; `labels` renames them for display only. Every field is optional,
and metrics the job prints but does not declare are still shown. The job must
print them as `name: value` lines on stdout.

This file is the *only* place a domain metric is ever named — the plugin core
has none built in, so an ML project and a CPU simulation get the same treatment
until each says otherwise.

**10. Cluster profile**

The cluster profile is shared by every project on this machine. If it does not
exist yet, invoke the `unity-hpc:recon` skill (read-only, safe). If it exists,
skip it — another project already produced it.

**11. Cluster-intel collector — ASK FIRST, this is opt-in**

> ⚠ **This step leaves a lasting footprint on shared infrastructure.** It starts
> one **long-lived tmux session on the Unity login node** — `collector.sh`
> sampling queue/partition/GPU/job state every 15 minutes — which keeps running
> after your session ends and is visible to other cluster users.

Ask the user explicitly whether to deploy it. **Default to no.** Nothing else in
this skill depends on it; it feeds usage analytics only. If the user declines,
say so plainly in the summary and continue — setup is complete without it.

If and only if the user opts in:

```bash
CID=/work/${SLURM_ACCOUNT}/${USER}/cluster-intel
ssh "$UNITY_HOST" "mkdir -p $CID/telemetry"
scp "${CLAUDE_PLUGIN_ROOT}/cluster-intel/collector.sh" \
    "${CLAUDE_PLUGIN_ROOT}/cluster-intel/collector_parse.py" \
    "$UNITY_HOST:$CID/"
ssh "$UNITY_HOST" "tmux has-session -t unity-collector 2>/dev/null \
    || tmux new-session -d -s unity-collector \
       'UNITY_CID=$CID bash $CID/collector.sh loop'"
```

`collector.sh` is the single cluster-side telemetry writer: it is
singleton-guarded by both `tmux has-session` (one session) and a `flock` on
`collector.lock` (one writer even if two sessions somehow raced), so
re-running setup never starts a second copy or double-writes. It also owns
the 35-day retention prune on its own output — there is no separate pruning
step.

**12. Print the summary**

Report what was created, what was skipped, what was moved to `.pre-redesign/`,
and whether collectors were deployed. Then:

```
Next: bash unityHPC/run.sh run <job-name>
  or: use the unity_submit MCP tool
```

**If anything behaves unlike the documentation**, call
`mcp__unity-hpc__unity_doctor` before investigating further. It reports which
plugin version this server process is *actually running* and whether the code
was upgraded after the session started — a stale server looks exactly like a
bug in code that has already been fixed.
