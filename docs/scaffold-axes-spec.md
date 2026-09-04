# Scaffold axes — implementable spec

Decisions live in GitHub issue #10 and in `docs/design-decisions.md` §3.4–§3.13.
`CONTEXT.md` is the glossary. `docs/scaffold-axes-redesign.md` is evidence only.
This file is what to build. Do not reopen the names here.

Plugin version at spec time: 0.11.1.

Implementation tickets (children of #10):

| # | Work |
|---|---|
| #19 | Fan-out `UNITY_TASK_PAYLOAD` |
| #20 | `bootstrap.sh` under flock |
| #21 | `run.sh cancel` |
| #22 | Campaign-keyed fetch |
| #23 | `--type multi-cpu` / `multi-gpu` |
| #24 | `scripts/hpc-watch` (blocked by #21) |
| #25 | MCP `unity_array` / `unity_cancel` (blocked by #19, #21) |
| #26 | Skills and README |

---

## 1. Primitives

One public selector: `--type`. Five names.

| `--type` | Resource | Orchestration | Submit | Ledger |
|---|---|---|---|---|
| `cpu` | cpu | single | one `sbatch` | one row |
| `gpu` | gpu | single | one `sbatch` | one row |
| `ml` | gpu | coordinated | one `sbatch` | one row |
| `multi-cpu` | cpu | fan-out | one `sbatch --array` | N rows `<parent>_<index>` |
| `multi-gpu` | gpu | fan-out | one `sbatch --array` | N rows `<parent>_<index>` |

`gpu` with `SLURM_GPUS>1` on one node is still `gpu`. `ml` is not a `multi-gpu`
preset. Multi-node CPU (`--ntasks` / `srun`) is out of scope. Sequenced
`--dependency=afterok:` is out of scope.

`--type cpu|gpu|ml` keep working. Add `multi-cpu` and `multi-gpu`. No `.env`
key is renamed. No major version bump for the type set.

## 2. `#SBATCH` headers

Keep today's `render()` for `cpu`, `gpu`, `ml`:

`--job-name`, `--account`, `--partition`, `--time`, `--nodes`,
`--cpus-per-task`, `--mem`, `--output`, `--error`, optional `--gres` /
`--constraint` / `--mail-user`.

Never emit `--ntasks` or `--ntasks-per-node`. `ml` may raise `SLURM_NODES`.
The template launches ranks.

Keep today's `render_array()` for `multi-cpu` and `multi-gpu`: the same keys,
plus `--array`, plus logs `%A_%a`. `JOB_COMMAND` is shared.

## 3. Fan-out payload

Manifest line:

- `token` → export `EXP` (today).
- `token<TAB>json` → export `EXP` from the token; export the JSON tail as
  `UNITY_TASK_PAYLOAD`. Do not parse the JSON.

`EXP` stays `_require_safe_name`-checked. It is still the SLURM job name and a
filename fragment. `cpu` / `gpu` / `ml` have no per-task payload.

## 4. Campaign and group

- **Campaign** — optional grouping label. Default: today's UTC date. May mix
  primitives. May hold several fan-out submits.
- **Group** — one fan-out submit. Identity: parent SLURM job id. Membership:
  ledger rows `<parent>_<index>`. Finished when every child row is terminal.
  A campaign has no end state.

Public scope for `cancel`, `fetch`, `watch`: `--campaign N`. Optional
`--job <parent>` pins one group.

## 5. Cancel

`run.sh cancel [--campaign N] [--job <parent>]`

- Read the ledger the same way `cmd_jobs` does.
- Skip rows already in a terminal ledger state.
- Collapse `<parent>_<index>` to `<parent>` before `scancel`.
- One `scancel` over SSH. Print what was cancelled. Write `CANCELLED` to the
  ledger.
- Exit nonzero if the scope has no jobs.

This lives in `run.sh` because the ledger and the array-id convention are
internal to it.

## 6. Results tree and fetch

- New scaffolds default job output to `$REMOTE_DIR/_results/<campaign>/`.
- Add `REMOTE_RESULTS_DIR` to `UNITY_OVERRIDABLE`.
- `cmd_fetch` prefers `<REMOTE_RESULTS_DIR or $REMOTE_DIR/_results>/<campaign>`
  when that directory exists remotely. If it does not, keep today's whole-tree
  rsync.

## 7. Bootstrap hook

If `unityHPC/bootstrap.sh` exists, each job template sources it under one
`flock` on `REMOTE_DIR`. Re-check after acquire. Use `if/then … exit 0`, not
`[ … ] && exit 0`. If the file is absent, activate `VENV_PATH` when present,
otherwise run. No `VENV_BOOTSTRAP`. No pip convention.

## 8. Watcher

Plugin script `scripts/hpc-watch`, not a `run.sh` subcommand (scaffold copies
freeze policy). The user starts it. Ctrl-C stops it. No other command starts
it.

```
hpc-watch [--campaign N] [--job <parent>] [--poll SECONDS]
```

- Calls the project's `unityHPC/run.sh` only: `status`, `run` (retry),
  `fetch`, `cancel`. Never opens the ledger. Never `sacct`. Never `sbatch`.
- State file: `.unity_state/<campaign>.watch.json`. One `flock`. A second
  watcher on that campaign exits.
- Retry budget: no retry if that token's previous retry failed; no retry if
  the job died within 120s of submit. Persist attempt counts. Flags may
  tighten the budget. Infinite retry is not the default.
- Runs until every in-scope group is terminal, then `fetch`, then exits.
- Dies with the terminal. Nothing respawns. Nothing runs on the login node.

Do not add `unity_watch` to the MCP server.

## 9. Scaffold

`hpc-scaffold --type` accepts the five names.

| `--type` | Template dir |
|---|---|
| `cpu`, `multi-cpu` | `templates/scaffold/cpu/` |
| `gpu`, `multi-gpu` | `templates/scaffold/gpu/` |
| `ml` | `templates/scaffold/ml/` |

`common/run.sh` and `common/sync.sh` stay common. No
`templates/scaffold/multi-*` directory. Re-scaffold: replace generated files,
backup hand-written files to `.pre-redesign/`. `unity_doctor` does not treat a
three-type scaffold as broken.

## 10. MCP

No `primitive` / `type` parameter on MCP tools.

- `unity_submit` — still `run.sh run`.
- `unity_array` — `run.sh array` with a manifest path.
- `unity_cancel` — `run.sh cancel`.

Telemetry does not record the primitive. Join the project ledger at read time
if a ranking needs it.

## 11. Docs

- `skills/setup/SKILL.md` type table: the five names.
- `/unity-hpc:sweep` is the fan-out path. `/unity-hpc:run` stays single-job.
- README: drop "Nothing runs in the background…". Document payload,
  `bootstrap.sh`, `cancel`, and `hpc-watch`.
- `ARCHITECTURE.md` gains cancel, payload, hook, watch, and the five names.

## 12. Out of scope

- Multi-node CPU with `srun` / MPI.
- Stage-then-aggregate (`--dependency=afterok:`).
- A `primitive` column on `task_run`.
- A long-running MCP watch tool.
- Re-testing 0.11.1 coverage gaps (#2).
- Items in `docs/open-follow-ups.md`.
