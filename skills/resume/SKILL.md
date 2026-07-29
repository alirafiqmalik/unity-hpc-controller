---
name: resume
description: "Rebuild full session context after a reset — reads results, job ledger, cluster profile, and queue conditions."
---

# unity-hpc:resume

Announce: "Using unity-hpc:resume to rebuild session context."

This skill is read-only — it submits nothing and modifies no files.

## Steps

**1. Read project context**
- Read `CLAUDE.md` if present (project instructions)
- Read `unityHPC/.env` — note UNITY_HOST, REMOTE_DIR (mask USER_EMAIL in output)

**2. Read research direction**
Read `program-unity.md` (or the project's equivalent). Print the first 8 lines
as the current direction. Skip silently if there is none.

**3. Read experiment history**
Call `mcp__unity-hpc__unity_results_tsv`. It returns the file's own header plus
rows keyed by that header — the columns are whatever this project chose. Report:
- total rows, broken down by `status` if that column exists
- the most recent few rows
- the best row *only* if the project's own convention makes "best" meaningful
  (e.g. a documented metric column); otherwise do not invent a ranking

**4. Check the current campaign**
Call `mcp__unity-hpc__unity_status` for job state counts, then
`mcp__unity-hpc__unity_jobs` for the per-job list. If any job is non-terminal,
note that these come from the ledger and that
`bash unityHPC/run.sh status` gives a live answer.

**5. Read the cluster profile**
Call `mcp__unity-hpc__unity_cluster_profile` — the profile is shared by every
project on this machine. Note partition limits, GPU types, and MaxSubmitJobs.
If it reports no profile yet, suggest `/unity-hpc:recon`.

**6. Check queue conditions**
Call `mcp__unity-hpc__unity_traffic` for current queue depth and the
recommendation.

**7. Print a structured resume brief**
```
╔════════════════════════════════════════════╗
║              RESUME BRIEF                  ║
╠════════════════════════════════════════════╣
║ History:  <N> logged runs (<status split>) ║
║ Latest:   <commit> — "<description>"       ║
╠════════════════════════════════════════════╣
║ Campaign: <name>                           ║
║   <N> running  <M> completed  <K> failed   ║
╠════════════════════════════════════════════╣
║ Direction: <first line of program-unity.md>║
╠════════════════════════════════════════════╣
║ Queue:  <N> pending on <partition>         ║
║ Rec:    use <partition> (~Xmin wait)       ║
╠════════════════════════════════════════════╣
║ Next:   <fetch / submit / wait>            ║
╚════════════════════════════════════════════╝
```
Omit any line whose data does not exist rather than printing a placeholder.

Choose "Next" from:
- All jobs terminal → "Run /unity-hpc:fetch, then /unity-hpc:log-result"
- Jobs still active → "Check progress: bash unityHPC/run.sh status"
- No campaign → "Run /unity-hpc:run <exp> to submit the next job"
