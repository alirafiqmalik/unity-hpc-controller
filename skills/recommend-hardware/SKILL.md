---
name: recommend-hardware
description: >-
  Recommend the best GPU backend for the user's task by intersecting what they
  can request, what is available now, and what is fastest based on their own job
  history. A fast lookup-and-rank skill (Haiku-level) — reads existing analysis
  outputs, does not train or submit anything.
---

# unity-hpc:recommend-hardware

Announce: "Using unity-hpc:recommend-hardware to rank backends for this task."

This skill is a data lookup + ranking. It is cheap and fast — no heavy reasoning.
It does not submit jobs or modify files.

## Inputs (all already produced by other components)

1. **Capable** — GPU types you may request, from the shared cluster profile
   (`${UNITY_HPC_DATA:-$HOME/.local/share/unity-hpc}/cluster-config.json`, written
   by `unity-hpc:recon` and shared by all projects). Read it via the
   `mcp__unity-hpc__unity_cluster_profile` MCP tool, which renders it. If it
   reports no profile yet, tell the user to run `/unity-hpc:recon`.
2. **Fast-for-you (project-measured)** — *this project's own* per-backend
   performance, correlated from *this project's* `.unity_state` job-ids against
   the shared `summaries.db` `task_run` table. Prefer the `mcp__unity-hpc__unity_my_jobs`
   tool (it already does this join and reports "pending" for uncollected jobs);
   or compute the per-hardware profile directly:
   ```bash
   python3 - <<'PY'
   import sys, os, sqlite3, glob, json
   sys.path.insert(0, "${CLAUDE_PLUGIN_ROOT}")
   from lib import queries

   project_dir = os.environ.get("PROJECT_DIR", os.getcwd())
   ids = []
   for db in sorted(glob.glob(os.path.join(project_dir, ".unity_state", "*.db"))):
       con = sqlite3.connect(db); con.row_factory = sqlite3.Row
       try:
           ids += [r["job_id"] for r in con.execute("SELECT job_id FROM jobs")]
       except sqlite3.OperationalError:
           pass
       con.close()
   ids = list(dict.fromkeys(ids))
   print(json.dumps(queries.project_hardware_profile(ids), indent=2))
   PY
   ```
   This returns one row per hardware this project has actually run on: `n`,
   `runtime_p50`/`p90`, `wait_p50`, `success_rate`, `cpu_eff_p50`, `mem_eff_p50`.
3. **Cold-start fallback (cluster-wide)** — for any hardware with **fewer than 3**
   of the project's own runs (including hardware the project has never used at
   all), fall back to the shared, cross-project `task_profile` table instead of
   trusting a thin project sample:
   ```bash
   sqlite3 -json "${UNITY_HPC_DATA:-$HOME/.local/share/unity-hpc}/summaries.db" \
     "SELECT hardware, n, runtime_p50, wait_p50, success_rate FROM task_profile"
   ```
4. **Available now** — live queue from the `mcp__unity-hpc__unity_traffic` tool,
   and historical contention from `mcp__unity-hpc__unity_usage`.

## Steps

1. Get this project's own per-hardware profile (input 2, above) via
   `unity_my_jobs` or the `project_hardware_profile` snippet.
2. For each capable hardware type, decide the data source:
   - **≥3 project runs on that hardware** → use the project-measured row.
     Label it `project-measured`.
   - **<3 project runs (or none)** → query the shared `task_profile` (input 3)
     for that hardware instead. Label it `cluster-wide (few own runs)`.
3. Call `mcp__unity-hpc__unity_traffic` for the current queue signal.
4. Intersect: keep only GPU types that are **capable** (in cluster-profile) AND
   have performance or availability data (project-measured or cluster-wide).
   Flag any capable-but-untested backend explicitly rather than guessing.
5. Rank by a simple blend — speed first (`runtime_p50` from whichever source was
   used), weighted by that row's `success_rate`, then discounted by access cost
   (median wait / current contention). State the weighting you used, and which
   rows were project-measured vs. cluster-wide.
6. Present a short ranked verdict with the tradeoff made explicit. Never emit a
   single opaque pick — always show the runner-up and why.

## Output format

```
For this task (<one line: what the task is>):
  ▸ <gpu>  — fastest (median <N>s, <ok>% success, project-measured) but ~<W>min queue now
  ▸ <gpu>  — <X>× slower, but <W>min wait → better wall-clock today (cluster-wide, few own runs)
  ▸ <gpu>  — free immediately; suitable only for quick smoke tests
Recommendation: <gpu> now (queue-adjusted); <gpu> for overnight batch.
```

## Notes
- If the user has no prior jobs on any backend, fall back to availability-only
  and say so — the recommendation is then "most available capable GPU", not
  "fastest for you".
- Always label each ranked row `project-measured` or `cluster-wide (few own
  runs)` so the user knows whether the number is their own history or a
  cold-start fallback.
- Keep it to a few lines. This is a decision aid, not a report.
