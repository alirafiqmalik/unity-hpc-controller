---
name: log-result
description: "Append a job result to the project's results.tsv — uses whatever columns that file already has, and the project's declared metric if it has one."
---

# unity-hpc:log-result

Announce: "Using unity-hpc:log-result to record this result."

`results.tsv` belongs to the project, not to the plugin: its columns are
whatever the project chose. Read them; never impose a schema.

## Steps

**1. Get the current table**
Call `mcp__unity-hpc__unity_results_tsv`. It returns `columns` (from the file's
own header) and `rows`. Display it formatted.

If the file does not exist, ask the user which columns they want before
creating it. A sensible default is `commit  metric  value  status  description`,
but do not assume it.

**2. Identify the target result**
- If the user named a job or commit, use it.
- Otherwise take it from the most recent `/unity-hpc:fetch`
  (`mcp__unity-hpc__unity_results`). If the project declares a primary metric in
  `unityHPC/metrics.json`, that output already names the best job — use it.
- With no declared metric, do **not** guess which number is "best". Show the
  candidates and ask.

**3. Confirm with the user**
Print a preview row using the file's real columns and ask for confirmation:
```
Logging (columns: commit, metric, value, status, description):
  commit:      <7-char git hash>
  metric:      <name>
  value:       <value>
  status:      keep | discard | crash
  description: <what changed / what you learned>
```
Always confirm `description` and `status` explicitly — they are the fields only
the user can supply.

**4. Append to results.tsv**
One tab-separated line, one value per existing column, in header order. No tabs
inside a field, no commas needed.
- `commit`: `git rev-parse --short HEAD` (skip if not a git repo)
- numbers: enough precision to distinguish runs; do not round away a difference
- unknown column for this run: leave the field empty rather than inventing a value

**5. Show the updated table**
Run `scripts/hpc-results`, or re-call `unity_results_tsv`.

**6. Print best-so-far — only if that is meaningful**
If the project declares a primary metric and the table has a matching column,
print the best row among `status=keep` in the declared direction:
```
Best so far: <commit>  <metric>=<value>  (<description>)
```
Otherwise print the most recent rows instead. A ranking the project never
defined is a fabrication.
