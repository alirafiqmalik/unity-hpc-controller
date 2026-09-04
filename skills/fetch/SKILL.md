---
name: fetch
description: "Fetch job output and artifacts from Unity with rsync, then summarise whatever metrics the jobs printed."
---

# unity-hpc:fetch

Announce: "Using unity-hpc:fetch to fetch job output."

## Steps

**1. Source the env file**

```bash
set -a && . unityHPC/.env && set +a
```

**2. Check the campaign state**

Call `mcp__unity-hpc__unity_status`. This is a local read, with no SSH. If any job
is still RUNNING or PENDING, get a live answer first:

```bash
bash unityHPC/run.sh status
```

If any job is still active after that check, ask:

> "Campaign not complete (N jobs still active). Fetch partial output? [y/N]"

If the user approves, or if every job is terminal, continue.

**3. Fetch the output**

```bash
bash unityHPC/run.sh fetch [--campaign <name>]
```

This pulls exactly the `.out` and `.err` files of that campaign's recorded jobs
into `_results/<campaign>/`. It also pulls the remote results directory into
`_results/<campaign>/artifacts/`.

The remote base is `$REMOTE_RESULTS_DIR`, and its default is
`$REMOTE_DIR/_results`. Fetch prefers `<base>/<campaign>` when that
subdirectory exists on the cluster, so one campaign does not pull the
artifacts of every earlier campaign that shares the base. If the
subdirectory does not exist -- a project whose job writes a flat
`_results/` -- fetch pulls the whole base instead.

If the campaign has no recorded jobs, `fetch` prints that fact, and pulls the
whole remote `_slurm/` directory instead. That is the fallback for jobs submitted
outside the dispatcher.

**4. Summarise the metrics**

Call `mcp__unity-hpc__unity_results`. It reports every numeric `key: value` pair
that the jobs printed to stdout. It assumes no particular metric, because the
plugin does not know what this project measures.

Print the table it returns, unchanged. Two cases need care:

- If the tool reports that the jobs printed nothing numeric, say so plainly. Point
  the user at `_results/<campaign>/` for the raw output. This outcome is normal
  for jobs that write their own artifact files. It is not a failure. Do not invent
  columns to cover it.
- If the tool reports "Declared but not printed", print that first. The project
  declared a metric that its job did not emit. The usual cause is a run that died
  before it reached that point.

**Optional — ranking.** A project with a headline metric can declare it once in
`unityHPC/metrics.json`. `unity_results` then orders those columns first, and
names the best job:

```json
{"primary": "val_bpb", "goal": "min", "report": ["val_bpb", "mfu_percent"]}
```

Without that file, the tool ranks nothing. That is correct for most jobs. Never
decide for the user which number is "best".

**5. Report the failures honestly**

For each job in FAILED, TIMEOUT, OUT_OF_MEMORY or NODE_FAIL, print the tail of its
`.err` file. Never present a partial result set as complete. Name the missing jobs
and the reason.

**6. Offer to log the result**

If the project keeps `results.tsv`, print: "Run /unity-hpc:log-result to record
this result."
