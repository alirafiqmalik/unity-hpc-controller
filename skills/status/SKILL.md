---
name: status
description: "Check this project's Unity job states — instant local read, with an explicit live SLURM check when it matters."
---

# unity-hpc:status

Announce: "Using unity-hpc:status to check job states."

There are two sources, and it is worth knowing which you are reading:

| Source | Cost | Freshness |
|---|---|---|
| `unity_status` / `unity_jobs` | local, instant | the ledger, refreshed from shared telemetry (collected every ~15 min) |
| `bash unityHPC/run.sh status` | one SSH round-trip | live `sacct`, and it writes what it learns back to the ledger |

## Steps

**1. Get job state counts**
Call `mcp__unity-hpc__unity_status`. Print the breakdown:
```
Campaign: <name>
  COMPLETED    N
  RUNNING      N
  PENDING      N
  FAILED       N
```

If it reports no campaign DB, the project has not submitted anything through
the dispatcher yet — point at `/unity-hpc:run`, do not treat it as an error.

**2. Get job details**
Call `mcp__unity-hpc__unity_jobs`:
```
job_id  exp         partition      status     hardware
------  ----------  -------------  ---------  --------
12345   baseline    gpu            COMPLETED  a100
12346   sweep-lr    gpu-preempt    RUNNING    -
```

**3. Get a live answer when any job is non-terminal**
If any job is PENDING or RUNNING, the ledger may simply be behind the collector.
Run the live check and re-report:
```bash
bash unityHPC/run.sh status
```

**4. Handle PREEMPTED**
Report them plainly: "N job(s) were preempted by higher-priority work. Nothing
requeues them automatically — resubmit with `/unity-hpc:run` if you want them
back, ideally on a non-preempt partition."

**5. Handle failures**
For FAILED / TIMEOUT / OUT_OF_MEMORY / NODE_FAIL, name each job and suggest
`/unity-hpc:fetch` to pull its `.err` file. For OUT_OF_MEMORY, also suggest
raising `SLURM_MEM` in `.env`; for TIMEOUT, `WALLTIME`.

**6. Handle all complete**
If every job is terminal: "Campaign complete. Run /unity-hpc:fetch to retrieve
output."

**7. Watch a running job**
For live output from the newest job in the campaign:
```bash
bash unityHPC/run.sh logs [-n 40]
```

## When the output disagrees with the documentation
Call `mcp__unity-hpc__unity_doctor`. It reports the plugin version this server
process is running, whether the code changed after the session started, and the
project's scaffold/ledger state. A server started before a plugin upgrade keeps
serving the old behaviour while the source on disk shows the fix — `/reload-plugins`
or a session restart is the cure.

If `unity_doctor` itself is unavailable or answers `Unknown tool`, that is the
answer: the session is running a server from before 0.8.0. Reload it.

Do not spend time reconciling observed behaviour against the source until this
check is clean — reading a file that has already been fixed proves nothing about
the process serving you.

## Efficiency of past jobs
`mcp__unity-hpc__unity_my_jobs` adds what each job actually *used* — hardware,
wait time, CPU and memory efficiency — from shared telemetry. Use it when the
question is "was this job sized correctly", not "is it done yet".
