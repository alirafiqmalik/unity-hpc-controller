---
name: setup
description: "Bootstrap a new Unity HPC experiment — checks SSH, syncs code to /work, starts the cluster-intel collector, and runs recon if needed."
---

# unity-hpc:setup

Announce: "Using unity-hpc:setup to bootstrap a new Unity HPC experiment."

## Steps

Do the steps in order. Every step is safe to re-run: each one detects the
existing state, and reports skip or create instead of a clobber. On any failure,
stop and print what failed.

**1. Get the project type**

Ask the user for the project type: **cpu** for CPU-only jobs, **gpu** for
single-node GPU jobs, or **ml** for multi-node training with `torchrun`.

Do not guess. The answer selects the job template. If the user is not sure, use
`cpu`. It is the safe default, and you can generate a new scaffold later.

### Non-interactive setup

For an agent or CI workflow, use the explicit path below. It asks no questions,
uses only the supplied values, and fails if any required value is missing.

```bash
UNITY_HPC_NONINTERACTIVE=1 \
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/hpc-scaffold" \
  --type <cpu|gpu|ml> \
  --account <slurm-account> \
  --remote-dir <remote-project-dir> \
  --job-command '<command>' \
  --collector skip \
  --write-guidance
```

Every `.env` key has a flag. Give the environment flags for any job that needs
more than the system python:

| Flag | Sets | Use it for |
|---|---|---|
| `--venv PATH` | `VENV_PATH` | the virtualenv the node activates |
| `--modules 'cuda/12.8'` | `MODULES` | modules the node loads |
| `--hf-home PATH` | `HF_HOME` | a shared model cache |
| `--constraint 'sm_80&vram48'` | `SLURM_CONSTRAINT` | a node feature, rendered as `#SBATCH --constraint` |
| `--host NAME` | `UNITY_HOST` | an SSH alias other than `unity` |
| `--results-dir PATH` | `REMOTE_RESULTS_DIR` | the artifacts base; fetch prefers `<base>/<campaign>` |

A GPU job with no `--venv` runs the system python, which has no framework
installed. The job then fails on the node for a reason no plugin tool can
report.

Use `--collector deploy` only when the caller explicitly authorizes a
long-lived collector. Add `--dry-run` to review the files and actions without
writing or connecting to the cluster. The project `.env` remains the source of
truth after setup; each flag fills its key in that file, in place.

**2. Generate the unityHPC/ scaffold**

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/hpc-scaffold" --type <cpu|gpu|ml> --dry-run
```

Print what will change. Then run the same command without `--dry-run` to apply
it.

This writes `unityHPC/{run.sh,job_template.sh,sync.sh,.env}`. An existing `.env`
always stays as it is. Any other file that differs from the canonical template
moves to `unityHPC/.pre-redesign/<name>`, and the command writes a new one. The
command prints every move.

If the project had a hand-written `run.sh`, tell the user where that file went.
Also tell the user that the generated dispatcher now owns that contract.

**3. Fill in .env**

`unityHPC/.env` needs three values before any job can run: `SLURM_ACCOUNT`,
`REMOTE_DIR` and `JOB_COMMAND`. Ask the user for the three values, or ask the
user to edit the file. Stop here until the user approves. Set
`SLURM_CONSTRAINT` only when the cluster requires a node feature; the dispatcher
renders it as `#SBATCH --constraint=...`.

**4. Check SSH**

```bash
set -a && . unityHPC/.env && set +a
ssh "$UNITY_HOST" 'echo unity-ok'
```

Expected output: `unity-ok`. If the command fails, check the SSH configuration,
the VPN (campus or UMass VPN), and key authentication. Do not continue until SSH
works.

**5. Create the remote directory**

```bash
ssh "$UNITY_HOST" "mkdir -p ${REMOTE_DIR}/_slurm"
```

**6. Sync the project**

```bash
bash unityHPC/sync.sh
```

Expected output: `Sync done.`

**7. Check that the dispatcher renders**

```bash
bash unityHPC/run.sh render smoke-test
```

This prints the sbatch script and submits nothing. Check that the `#SBATCH`
lines match what the user expects, in particular `--time`, `--mem` and, for gpu
or ml, `--gres`.

**8. Create an experiment branch, only in a git repo**

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

If the directory is not a repo, offer to run `git init`. Do not run `git init`
unasked, and do not treat the absent repo as a failure. Version control is not
necessary to run jobs.

**9. Create results.tsv, if it is absent**

```bash
[ -f results.tsv ] || printf 'commit\tmetric\tvalue\tstatus\tdescription\n' > results.tsv
```

The columns belong to the project. Everything downstream reads this header
instead of an assumed schema. If the user already tracks the results somewhere
else, skip this file.

**9b. Optional — declare a headline metric**

Ask the question, but default to a skip: does this project have one number that
decides whether a run was good? A loss, an accuracy, a throughput or a residual
are all examples.

- **No, or not sure** — skip it. `unity_results` then reports whatever each job
  prints, and ranks nothing. This is the correct answer for most projects, and it
  keeps the plugin honest about work that it knows nothing about.
- **Yes** — write `unityHPC/metrics.json` with the user's own metric names:

```json
{
  "primary": "val_bpb",
  "goal": "min",
  "report": ["val_bpb", "peak_vram_mb", "mfu_percent"],
  "labels": {"peak_vram_mb": "vram_mb"}
}
```

`primary` and `goal` (`min` or `max`) turn on best-job reporting. `report` puts
those columns first. `labels` renames them for the display only. Every field is
optional, and the tools still print metrics that the job prints but does not
declare. The job must print each one as a `name: value` line on stdout.

This file is the only place that ever names a domain metric. The plugin core has
none built in. An ML project and a CPU simulation therefore get the same
treatment, until each one says otherwise.

**10. Get the cluster configuration**

Every project on this machine shares one cluster configuration. If it does not
exist yet, run the `unity-hpc:recon` skill. It is read-only and safe. If the
configuration exists, skip this step: another project already produced it.

**11. Cluster-intel collector — ask the user first, this is opt-in**

> ⚠ **CAUTION: This step leaves a lasting footprint on shared infrastructure.**
> It starts one **long-lived tmux session on the Unity login node**.
> `collector.sh` samples queue, partition, GPU and job state every 15 minutes. It
> keeps running after your session ends, and other cluster users can see it.

Ask the user directly whether to deploy the collector. **Default to no.** Nothing
else in this skill depends on it, and it feeds usage analytics only. If the user
declines, say so in the summary and continue. Setup is complete without the
collector.

Run the next commands only after the user opts in:

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

`collector.sh` is the single cluster-side telemetry writer. Two guards keep it a
singleton: `tmux has-session` allows one session, and a `flock` on
`collector.lock` allows one writer even if two sessions race. A second setup run
therefore never starts a second copy, and never writes a record twice. The
collector also owns the 35-day retention prune on its own output, so there is no
separate prune step.

**12. Print the summary**

Report what the run created, what it skipped, what it moved to `.pre-redesign/`,
and whether it deployed the collector. Then print:

```
Next: bash unityHPC/run.sh run <job-name>
  or: use the unity_submit MCP tool
```

**If any behavior differs from this documentation**, call
`mcp__unity-hpc__unity_doctor` before you investigate further. It reports the
plugin version that this server process runs, and whether the code changed after
the session started. A stale server looks exactly like a bug in code that is
already fixed.
