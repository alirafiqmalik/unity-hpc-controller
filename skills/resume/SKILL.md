---
name: resume
description: "Rebuild full session context after a reset — reads the results, the job ledger, the cluster configuration, and the queue conditions."
---

# unity-hpc:resume

Announce: "Using unity-hpc:resume to rebuild session context."

This skill is read-only. It submits nothing and modifies no files.

## Steps

**1. Read the project context**

- If `CLAUDE.md` exists, read it. It holds the project instructions.
- Read `unityHPC/.env`. Note `UNITY_HOST` and `REMOTE_DIR`. Mask `USER_EMAIL` in
  the output.

**2. Read the research direction**

Read `program-unity.md`, or the equivalent file of this project. Print the first
8 lines as the current direction. If there is no such file, skip this step
silently.

**3. Read the experiment history**

Call `mcp__unity-hpc__unity_results_tsv`. It returns the file's own header, and
the rows keyed by that header. The columns are whatever this project chose.
Report:

- the total number of rows, split by `status` if that column exists
- the most recent few rows
- the best row, but only if a convention of this project makes "best" meaningful,
  for example a documented metric column

If no such convention exists, invent no ranking.

**4. Read the current campaign**

Call `mcp__unity-hpc__unity_status` for the job state counts. Then call
`mcp__unity-hpc__unity_jobs` for the per-job list.

If any job is non-terminal, print that these counts come from the ledger. Also
print that `bash unityHPC/run.sh status` gives a live answer.

**5. Read the cluster configuration**

Call `mcp__unity-hpc__unity_cluster_profile`. Every project on this machine shares
this configuration. Note the partition limits, the GPU types and `MaxSubmitJobs`.
If the tool reports no configuration yet, offer `/unity-hpc:recon`.

**6. Read the queue conditions**

Call `mcp__unity-hpc__unity_traffic` for the current queue depth and the
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

If the data for a line does not exist, omit the line. Do not print a placeholder.

Pick the "Next" line from these three:

- If every job is terminal, print "Run /unity-hpc:fetch, then
  /unity-hpc:log-result".
- If any job is still active, print "Check progress: bash unityHPC/run.sh status".
- If there is no campaign, print "Run /unity-hpc:run <exp> to submit the next
  job".
