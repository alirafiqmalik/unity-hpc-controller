---
name: status
description: "Check this project's Unity job states — instant local read, with an explicit live SLURM check when it matters."
---

# unity-hpc:status

Announce: "Using unity-hpc:status to check job states."

There are two sources of job state. Know which one you read.

| Source | Cost | Freshness |
|---|---|---|
| `unity_status` / `unity_jobs` | local, instant | the ledger, refreshed from shared telemetry (collected every ~15 min) |
| `bash unityHPC/run.sh status` | one SSH round-trip | live `sacct`, and it writes what it learns back to the ledger |

## Steps

**1. Get the job state counts**

Call `mcp__unity-hpc__unity_status`. Print the counts:

```
Campaign: <name>
  COMPLETED    N
  RUNNING      N
  PENDING      N
  FAILED       N
```

If the tool reports no campaign DB, the project submitted nothing through the
dispatcher yet. Point the user at `/unity-hpc:run`. This is not an error.

**2. Get the job details**

Call `mcp__unity-hpc__unity_jobs`:

```
job_id  exp         partition      status     hardware
------  ----------  -------------  ---------  --------
12345   baseline    gpu            COMPLETED  a100
12346   sweep-lr    gpu-preempt    RUNNING    -
```

**3. Get a live answer for every non-terminal job**

If any job is PENDING or RUNNING, the ledger can be behind the collector. Run
the live check, then print the counts again:

```bash
bash unityHPC/run.sh status
```

**4. Report PREEMPTED jobs**

Print this text: "Higher-priority work preempted N job(s). Nothing requeues them
automatically. To get them back, resubmit with `/unity-hpc:run`, preferably on a
non-preempt partition."

**5. Report failures**

For each job in FAILED, TIMEOUT, OUT_OF_MEMORY or NODE_FAIL, print the job id.
Offer `/unity-hpc:fetch` to get its `.err` file. For OUT_OF_MEMORY, also offer to
raise `SLURM_MEM` in `.env`. For TIMEOUT, offer to raise `WALLTIME`.

**6. Report a complete campaign**

If every job is terminal, print: "Campaign complete. Run /unity-hpc:fetch to get
the output."

**7. Watch a running job**

For live output from the newest job in the campaign, run:

```bash
bash unityHPC/run.sh logs [-n 40]
```

## If the output disagrees with the documentation

Call `mcp__unity-hpc__unity_doctor`. It reports the plugin version that this
server process runs. It also reports whether the code changed after the session
started, and the scaffold and ledger state of the project.

A server that started before a plugin upgrade keeps the old behavior, while the
source on disk shows the fix. The cure is `/reload-plugins`, or a session
restart.

If `unity_doctor` is absent, or answers `Unknown tool`, that is the answer: this
session runs a server from before 0.8.0. Reload it.

Do not compare the observed behavior against the source until this check is
clean. A file that is already fixed proves nothing about the process that serves
you.

## Efficiency of past jobs

`mcp__unity-hpc__unity_my_jobs` adds what each job *used*: hardware, wait time,
CPU efficiency and memory efficiency, from shared telemetry. Use it for the
question "was this job sized correctly", not "is it done yet".
