---
name: recommend-hardware
description: >-
  Recommend the best GPU backend for the user's task. It intersects what the user
  can request, what is free now, and what was fastest in the user's own job
  history. A fast lookup-and-rank skill (Haiku-level) — it reads existing analysis
  output, and it neither trains nor submits anything.
---

# unity-hpc:recommend-hardware

Announce: "Using unity-hpc:recommend-hardware to rank backends for this task."

This skill is a data lookup and a ranking. It is cheap and fast, and it needs no
heavy reasoning. It submits no jobs and modifies no files.

## Inputs

Other components already produce all four inputs.

**1. Capable** — the GPU types that the user can request. They come from the
shared cluster configuration:

```
${UNITY_HPC_DATA:-$HOME/.local/share/unity-hpc}/cluster-config.json
```

`unity-hpc:recon` writes that file, and every project shares it. Read it with the
`mcp__unity-hpc__unity_cluster_profile` MCP tool, which prints it as markdown. If the tool
reports no configuration yet, tell the user to run `/unity-hpc:recon`.

**2. Fast-for-you (project-measured)** — the per-backend performance of *this
project*. It comes from a join of *this project's* `.unity_state` job ids against
the `task_run` table in the shared `summaries.db`.

Prefer the `mcp__unity-hpc__unity_my_jobs` tool. It already does the join, and it
reports "pending" for jobs that the collector has not seen yet. To compute the
per-hardware profile directly instead, run:

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

This returns one row for each hardware type that the project ran on, with `n`,
`runtime_p50`, `runtime_p90`, `wait_p50`, `success_rate`, `cpu_eff_p50` and
`mem_eff_p50`.

**3. Cold-start fallback (cluster-wide)** — for hardware with fewer than **3** of
this project's own runs, including hardware the project never used, read the
shared cross-project `task_profile` table instead. A sample that thin is not
worth trust:

```bash
sqlite3 -json "${UNITY_HPC_DATA:-$HOME/.local/share/unity-hpc}/summaries.db" \
  "SELECT hardware, n, runtime_p50, wait_p50, success_rate FROM task_profile"
```

**4. Available now** — the live queue from the `mcp__unity-hpc__unity_traffic`
tool, and the historical contention from `mcp__unity-hpc__unity_usage`.

## Steps

1. Get this project's own per-hardware profile (input 2). Use `unity_my_jobs`, or
   the `project_hardware_profile` snippet.
2. For each capable hardware type, pick the data source:
   - **3 or more project runs on that hardware** — use the project-measured row.
     Label it `project-measured`.
   - **Fewer than 3 project runs** — read the shared `task_profile` (input 3) for
     that hardware. Label it `cluster-wide (few own runs)`.
3. Call `mcp__unity-hpc__unity_traffic` for the current queue signal.
4. Intersect the sets. Keep only the GPU types that are capable, and that have
   performance data or availability data. Print each capable but untested backend
   as untested. Do not guess a number for it.
5. Rank the rows. Put speed first, that is `runtime_p50` from whichever source you
   used. Weight it by the `success_rate` of that same row. Then discount it by
   access cost, that is the median wait and the current contention. Print the
   weighting you used, and which rows were project-measured or cluster-wide.
6. Print a short ranked verdict, and print the trade-off you made. Never print a
   single opaque pick. Always print the runner-up, and why it lost.

## Output format

```
For this task (<one line: what the task is>):
  ▸ <gpu>  — fastest (median <N>s, <ok>% success, project-measured) but ~<W>min queue now
  ▸ <gpu>  — <X>× slower, but <W>min wait → better wall-clock today (cluster-wide, few own runs)
  ▸ <gpu>  — free immediately; suitable only for quick smoke tests
Recommendation: <gpu> now (queue-adjusted); <gpu> for overnight batch.
```

## Notes

If the user has no prior jobs on any backend, rank on availability alone, and say
so. The recommendation is then "the most available capable GPU", not "the fastest
for you".

Label every ranked row `project-measured` or `cluster-wide (few own runs)`. The
label tells the user whether the number is their own history or a cold-start
fallback.

Keep the output to a few lines. This is a decision aid, not a report.
