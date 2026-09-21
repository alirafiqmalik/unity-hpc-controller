---
name: log-result
description: "Append a job result to the project's results.tsv — it uses the columns that the file already has, and the project's declared metric if the project has one."
---

# unity-hpc:log-result

Announce: "Using unity-hpc:log-result to record this result."

`results.tsv` belongs to the project, not to the plugin. The project chose its
columns. Read them, and impose no schema.

## Steps

**1. Get the current table**

Call `mcp__unity-hpc__unity_results_tsv` with a small `limit`. It returns
`columns`, taken from the file's own header, `rows`, `total_rows`, `offset`,
`limit`, and `next_offset`. Request the next page only when it is needed.
Print the returned rows as a table.

If the file does not exist, ask the user which columns they want, before you
create it. One reasonable default is `commit  metric  value  status  description`,
but do not assume it.

**2. Identify the target result**

- If the user named a job or a commit, use it.
- If the user named neither, take it from the most recent `/unity-hpc:fetch`, that
  is `mcp__unity-hpc__unity_results`. If the project declares a primary metric in
  `unityHPC/metrics.json`, that output already names the best job. Use that job.
- If the project declares no metric, do **not** guess which number is "best".
  Print the candidates and ask the user.

**3. Get the user's approval**

Print a preview row that uses the file's real columns, then ask the user to
approve it:

```
Logging (columns: commit, metric, value, status, description):
  commit:      <7-char git hash>
  metric:      <name>
  value:       <value>
  status:      keep | discard | crash
  description: <what changed / what you learned>
```

Always ask the user about `description` and `status` directly. Only the user can
supply those two fields.

**4. Append to results.tsv**

Write one tab-separated line, with one value per existing column, in header order.
Put no tab inside a field. Commas are not necessary.

- `commit`: use `git rev-parse --short HEAD`. Skip it outside a git repo.
- numbers: keep enough precision to separate two runs. Never round a difference
  away.
- a column with no value for this run: leave the field empty. Do not invent a
  value.

**5. Print the updated table**

Run `scripts/hpc-results`, or call `unity_results_tsv` again.

**6. Print the best result so far, but only when that is meaningful**

If the project declares a primary metric, and the table has a matching column,
print the best row among the `status=keep` rows, in the declared direction:

```
Best so far: <commit>  <metric>=<value>  (<description>)
```

In every other case, print the most recent rows instead. A ranking that the
project never defined is a fabrication.
