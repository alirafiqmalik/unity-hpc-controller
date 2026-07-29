---
name: fetch
description: "Retrieve job output and artifacts from Unity via rsync, then summarise whatever metrics the jobs printed."
---

# unity-hpc:fetch

Announce: "Using unity-hpc:fetch to retrieve job output."

## Steps

**1. Source env**: `set -a && . unityHPC/.env && set +a`

**2. Check campaign state**
Call `mcp__unity-hpc__unity_status` (local read — no SSH). If any job is still
RUNNING or PENDING, get a live answer first:
```bash
bash unityHPC/run.sh status
```
If jobs are still active after that, ask:
> "Campaign not complete (N jobs still active). Fetch partial output? [y/N]"
Proceed only if the user confirms or every job is terminal.

**3. Rsync output**
```bash
bash unityHPC/run.sh fetch [--campaign <name>]
```
This pulls exactly the `.out`/`.err` files belonging to that campaign's recorded
jobs into `_results/<campaign>/`, plus anything under the remote results
directory (`$REMOTE_RESULTS_DIR`, default `$REMOTE_DIR/_results`) into
`_results/<campaign>/artifacts/`.

If the campaign has no recorded jobs, `fetch` says so and pulls the whole remote
`_slurm/` directory instead — the fallback for jobs submitted outside the
dispatcher.

**4. Summarise metrics**
Call `mcp__unity-hpc__unity_results`. It reports every `key: value` numeric pair
the jobs printed to stdout. It assumes no particular metric — the plugin does
not know what this project measures.

Print the table it returns as-is. In particular:
- If it says the jobs printed nothing numeric, say so plainly and point at
  `_results/<campaign>/` for the raw output. That is a normal outcome for jobs
  that write their own artifact files — not a failure, and not something to
  paper over by inventing columns.
- If it reports "Declared but not printed", surface that prominently: the
  project declared a metric its job did not emit, which usually means the run
  died before reaching it.

**Optional — ranking.** A project with a headline metric can declare it once in
`unityHPC/metrics.json`, and `unity_results` will then order those columns first
and name the best job:
```json
{"primary": "val_bpb", "goal": "min", "report": ["val_bpb", "mfu_percent"]}
```
Without that file nothing is ranked, which is correct for most jobs. Never
decide on the user's behalf which number is "best".

**5. Report failures honestly**
For any job in FAILED, TIMEOUT, OUT_OF_MEMORY or NODE_FAIL, show the tail of its
`.err` file. Never present a partial result set as complete — name which jobs
are missing and why.

**6. Prompt to log**
If the project keeps `results.tsv`: "Run /unity-hpc:log-result to record this
result."
