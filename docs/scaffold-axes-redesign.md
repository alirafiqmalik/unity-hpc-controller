# Scaffold axes redesign — evidence base

The live artifact for this effort is the wayfinder map on the issue tracker.
This file is its **evidence base**: what the redesign is answering, and the
real-world workarounds that prove each problem is real. It does not record
decisions — those live on the map's tickets.

Written 2026-08-08, against plugin version 0.11.1.

---

## Why this exists

Six enhancement issues (#3–#8) were opened against 0.11.1. Each was
well-specified, each proposed an interface, and each traced to one downstream
consumer that had already built the missing piece by hand.

Read one at a time they look like six unrelated features. Five of the six share
a shape: **they are operations on a group of jobs, not on one job.** The
single-job path is mature — the 0.10.1 end-to-end audit (#2) scored job
submission 8/10 and ledger accuracy 8/10. The group is where the gap is.

| Issue | Asked for | Acts on |
|---|---|---|
| #4 | `run.sh cancel --campaign N` | the group — tear it down |
| #5 | Campaign-scoped fetch | the group — collect its results |
| #6 | Opt-in watcher: poll → requeue → fetch | the group — is it finished? |
| #7 | Per-array-task payload beyond `EXP` | the group — what it hands each task |
| #8 | Remote venv bootstrap, NFS-safe | the group — what it sets up before tasks run |
| #3 | Ordered `SLURM_PARTITION` fallback | **one `sbatch` call** — not the group |

### Why a group is not an object today

`campaign` is a label on ledger rows. Nothing owns it, nothing defines which
jobs belong to it, and nothing defines when it ends. It is a filter on queries,
not a thing the harness submits.

So the first five are verbs without a noun. That is measurable in the
workarounds: cancelling a campaign takes four parts (`TERMINAL_STATUSES`,
`JOB_ID_RE`, `parse_job_ids`, `cancel_campaign`) to *rebuild* the group from
the text output of `run.sh jobs` before it can act on it. Fetch guesses a
remote layout the plugin never defines. The watcher cannot ask whether the
group is finished, so it infers the answer from every task.

Building those verbs against the label means building them twice. Closed #9 —
an array-manifest collision when two arrays shared one campaign name — is what
the label's missing semantics already cost.

Naming `multi-cpu`, `multi-gpu` and `ml` as orchestration primitives makes that
group an object with an identity, a membership and an end state. The five verbs
then have something to act on. **The rename alone fixes nothing:** if the
redesign stops at new template names and does not define the object, the verbs
gain nothing.

**#3 is the exception and is not on the map.** It is one `sbatch` call rejected
at submit time, which happens to a single job as readily as to a group. Tracked
separately as #17.

## The model being replaced

Today `hpc-scaffold --type` takes `cpu`, `gpu` or `ml`. That reads as one axis
but is two:

- `cpu` and `gpu` name a **resource** — what hardware the job asks for.
- `ml` names an **orchestration** — multi-node training via `torchrun`, with
  `SLURM_NODES` raised. It also implies GPU.

Meanwhile arrays — the other orchestration shape — are not a type at all. They
live in `common/run.sh` as the `array` subcommand, orthogonal to type, so
`cpu + array` and `gpu + array` are reachable but unnamed.

Mixing the two axes is why "where does a multi-CPU job go" has no answer.

## The gap that has no issue

`run.sh` emits `--nodes` and `--cpus-per-task`. It never emits `--ntasks` or
`--ntasks-per-node`, and no CPU template calls `srun`. A CPU job submitted with
`SLURM_NODES=4` therefore gets four nodes and runs its command once, on one of
them. `ml` is the only multi-node template and it is `torchrun`-shaped.

None of #3–#8 covers this. It was found while charting the map.

## The rule that is already false

`README.md:80` states: *"Nothing runs in the background. There is no monitor
process, nothing auto-fetches, and nothing auto-requeues."* Issue #6 cites
`ARCHITECTURE.md` §10 for it; §10 does not contain it.

The plugin already ships an opt-in background process. `/unity-hpc:setup`
step 11 starts `collector.sh loop` in a detached `tmux` session on the login
node, kept a singleton by `tmux has-session` plus a `flock` on
`collector.lock`, owning its own 35-day retention prune. `scripts/hpc-tmux`
exists to manage exactly such sessions.

So a job watcher is not a new kind of thing. It is a second instance of a
pattern already in the tree — which turns "may anything run unattended?" into
"what is the contract for an opt-in background process, now that there are
two?"

The §10 rule that genuinely applies is **"Reads never write."** A watcher does
not break it. Auto-requeue inside `run.sh status` — the alternative #6 itself
rejected — would.

## Workarounds in the wild

The consumer project's hand-built layer, preserved here because the issues that
cited it are closed. Each is evidence that the gap is real and that the fix is
non-obvious enough to get wrong.

| Gap | Built by hand as |
|---|---|
| Per-task payload beyond `EXP` | `plan.py` writes `plans/<campaign>.json` mapping token → 7 fields; `exec_unit.sh` re-reads it per task and `eval`s the fields into the environment, with an explicit error on a lookup miss |
| Remote env bootstrap | `exec_unit.sh` creates the venv under `flock -w 1800`, re-checking after acquiring the lock; a second lock covers venv-exists-but-package-missing. Uses `if/then … exit 0`, not `[ … ] && exit 0`, because under `set -euo pipefail` a false `&&` guard aborts the very path meant to handle it |
| Campaign teardown | `plan.py`: `parse_job_ids` reads `run.sh jobs` stdout, drops rows in `TERMINAL_STATUSES`, collapses `62614212_0` → `62614212` so one `scancel` covers a whole array; `cancel_campaign` unions ids across buckets and issues one call |
| Campaign-scoped fetch | `plan.py: fetch_campaign` pins `REMOTE_RESULTS_DIR` to `$REMOTE_DIR/_results/<campaign>`. Unpinned, fetch pulls every campaign ever run into each bucket, so campaign 50 re-fetches 1–49 |
| Partition fallback | `plan.py`: `PARTITION_FALLBACK = [cpu, cpu-preempt, ood-shared]`, `PARTITION_MAX_WALLTIME = {ood-shared: 08:00:00}`, `walltime_seconds`/`capped_walltime` to clamp the request before each retry, and a retry loop in `submit_plan`. An explicit caller `SLURM_PARTITION` disables the ladder |
| Unattended requeue | `watch.py` polls `run.sh status` per bucket, classifies `FAILED`/`TIMEOUT`/`NODE_FAIL`/`PREEMPTED`/`OUT_OF_MEMORY`/`BOOT_FAIL`/`REVOKED` as retriable, and guards against deterministic failure — no retry if the token's own previous retry failed, or if a job failed within 120s of submission. Attempt counts persist to `<campaign>.watch.json` so a restarted watcher does not hand out a fresh budget. It never opens the ledger, never calls `sacct`, never calls `sbatch` |

The last row is the constraint any upstream version must keep: the watcher
drives `run.sh` subcommands and reaches past them for nothing.

## Partial work already in the tree

`REMOTE_RESULTS_DIR` (#5) is half-landed. It reaches `env.example` for all three
types, `hpc-scaffold --results-dir`, and the setup and fetch skills. It is still
absent from `UNITY_OVERRIDABLE`, so it cannot be set per invocation, and
`cmd_fetch` (`run.sh:695`) still rsyncs the whole `_results` tree.

## Not carried forward

Issue #2, the 0.10.1 end-to-end audit, is closed as done rather than as noise —
all ten numbered findings were fixed by 0.11.1. Its **coverage gaps** were never
tested and remain untested: sweep proper (`--limit`, array telemetry, campaign
roll-up), `unity_usage` / `hpc-sync-telemetry`, `metrics.json` ranking, and
config schema migration. Re-testing is a separate effort, not part of this map.
