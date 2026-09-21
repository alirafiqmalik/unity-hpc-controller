# unity-hpc — architecture

Version 0.12.0. Two components share one ledger contract.

**The central contract:** `unityHPC/run.sh` records every job it submits into
`<project>/.unity_state/<campaign>.db`. Every management tool reads that ledger.
A job that is not in the ledger is a job the project cannot name.

**The split:** the **controller** is an always-on process on this machine. It
owns the project registry, HTTP `/api/v1/*`, the dashboard, and every call to
`run.sh`. The **plugin** is three LLM skills (`connect`, `dispatch`, `doctor`)
that HTTP to the controller. They do not SSH. See
`docs/two-component-architecture.md` and `docs/adr/0001-two-component-split.md`.

---

## 1. Skills

These are the LLM-facing entry points. You run each one as `/unity-hpc:<name>`.

| Skill | Purpose | Touches cluster? |
|---|---|---|
| `connect` | Scaffold `unityHPC/` if needed, attach the directory to the controller | no (controller does) |
| `dispatch` | POST a run request to the controller | no (controller does) |
| `doctor` | Controller health and this project's wiring | no |

Operator runbooks for recon, fetch, watch, sweep, and setup live under
`controller/ops/`. Humans use the dashboard at `:8300`.

## 1b. Controller

`scripts/hpc-controller` serves the API and `controller/ui/index.html`.
`--tailscale` binds localhost and runs `tailscale serve`. The registry is
`$UNITY_HPC_DATA/controller/projects.json`. Dispatch is `run.sh`, never a
second writer.

HTTP (tests call `controller.http.handle`, no sockets):

| Method | Path | Role |
|---|---|---|
| GET | `/api/v1/health` | liveness |
| GET | `/api/v1/cluster` | snapshot + KPIs |
| GET | `/api/v1/projects` | attached projects |
| POST | `/api/v1/projects` | attach |
| POST | `/api/v1/projects/{slug}/runs` | dispatch |
| POST | `/api/v1/projects/{slug}/stop` | cancel |
| POST | `/api/v1/projects/{slug}/fetch` | fetch |
| POST | `/api/v1/projects/{slug}/sync` | sync |

## 2. MCP tools

`mcp/hpc_server.py` serves these over stdio, in the `mcp__unity-hpc__*`
namespace. It needs the standard library and `mcp`, nothing else.

**Project-local reads — no SSH, instant**

| Tool | Returns |
|---|---|
| `unity_status` | Job state counts for the latest campaign, or a named one |
| `unity_jobs` | job_id, exp, partition, status, and the hardware each job landed on |
| `unity_results` | The numeric `key: value` pairs each fetched job printed — metric-agnostic |
| `unity_results_tsv` | The local `results.tsv` as structured rows, driven by its own header |
| `unity_my_jobs` | This project's jobs, enriched from the shared telemetry |
| `unity_doctor` | The plugin version this server process actually runs, plus the scaffold drift |

**Cluster-touching**

| Tool | Notes |
|---|---|
| `unity_submit` | Delegates to `run.sh run`. `--dry-run` previews the job |
| `unity_array` | Delegates to `run.sh array`. One manifest, one `sbatch --array`, N ledger rows |
| `unity_cancel` | Delegates to `run.sh cancel`. Scoped by campaign, or by one parent job id |
| `unity_logs` | A live tail over SSH, with a fetched copy as the fallback |
| `unity_ssh` | One read-only command on the login node. It blocks dangerous writes, and takes a `timeout` argument |

**Shared-tier reads**

| Tool | Notes |
|---|---|
| `unity_cluster_profile` | Partitions, GPU types, account limits, capacity — independent of the working directory |
| `unity_traffic` | A near-live queue signal, plus the best and worst submit hours |
| `unity_usage` | Historical usage by window: GPU allocation by type, jobs, memory |

## 3. Internal tools

**Dispatcher** — `unityHPC/run.sh`, generated into each project. Its subcommands
are `run`, `array`, `render`, `sync`, `status`, `jobs`, `logs`, `fetch` and
`cancel`.

**Python libraries** (`lib/`)

| Module | Role |
|---|---|
| `campaign.py` | The per-project job ledger — the one record that every management tool reads |
| `scaffold.py` | The typed scaffold generator, with version stamping and append-only backups |
| `metrics.py` | The optional per-project metric declaration (`unityHPC/metrics.json`) |
| `queries.py` | Read-only helpers over `summaries.db`. These never write |
| `cluster_config.py` | The deterministic, order-independent merge for the shared cluster configuration |
| `retention.py` | The retention gate. It decides whether an `rsync --delete` is safe |
| `paths.py` | Resolution of the machine-wide data store |

**cluster-intel** — `collector.sh`, `collector_parse.py`, `rollup.py`,
`sync-telemetry.sh`, `migrate.py`, `backfill_hardware.py`, `dashboard/`.

**CLI scripts** (`scripts/`) — `hpc-scaffold`, `hpc-status`, `hpc-results`,
`hpc-logs`, `hpc-ssh`, `hpc-tmux`, `hpc-usage`, `hpc-compare`, `hpc-dashboard`,
`hpc-cleanup`, `hpc-sync-telemetry`, `hpc-retention-gate`, `hpc-config-write`.

**Templates** (`templates/scaffold/`) — `common/{run.sh,sync.sh}`, plus typed
`cpu|gpu|ml/{env.example,job_template.sh}`. Five primitives map onto these three
template directories:

| Primitive | Resource | Orchestration | Template dir |
|---|---|---|---|
| `cpu` | cpu | single | `cpu/` |
| `gpu` | gpu | single | `gpu/` |
| `multi-cpu` | cpu | fan-out | `cpu/` + `common/run.sh array` |
| `multi-gpu` | gpu | fan-out | `gpu/` + `common/run.sh array` |
| `ml` | gpu | coordinated | `ml/` |

There is no `templates/scaffold/multi-*` directory. Fan-out reuses the matching
resource template and submits through `run.sh array`.

**Agents** (`agents/`) — `recon`, `experiment-dispatcher`, `result-analyzer`.

`recon` does the same work as the `recon` skill, and delegates to the same locked
merge CLI. The other two are optional personas for an ML experiment loop: they
expect a `program-unity.md` file, a declared metric and a short training budget.
Each one states that scope in its own header, and names the skill to use instead.

The core stays general-purpose for CPU, GPU and ML SLURM jobs. That core is the
skills, the dispatcher, the MCP server, the scaffold and the telemetry pipeline.

---

## 4. Layer map

```
        YOU  ─── /unity-hpc:connect|dispatch|doctor ── HTTP :8300 ──┐
                                                                  │
 ┌────────────────────────────────────────────────────────────────▼──────────┐
 │ CONTROLLER   registry  snapshot  dispatch→run.sh  UI                       │
 └───────┬──────────────────────────────────────────────┬────────────────────┘
         │ writes / submits                             │ reads
 ┌───────▼──────────────────┐               ┌───────────▼───────────────────┐
 │ DISPATCHER (in project)  │               │ MCP SERVER  mcp/hpc_server.py │
 │ unityHPC/run.sh          │               │ (programmatic; skills are HTTP)│
 │   run render sync        │               │ unity_status  unity_jobs      │
 │   status jobs logs fetch │               │ unity_results unity_logs      │
 │   cancel array           │               │ unity_ssh     unity_doctor    │
 └───────┬──────────┬───────┘               └───────┬───────────────┬───────┘
         │ writes   │ ssh/rsync                     │ reads         │ reads
 ┌───────▼──────────┼───────────────────────────────▼──────┐ ┌──────▼────────┐
 │  LEDGER  <project>/.unity_state/<campaign>.db           │ │ SHARED TIER   │
 │  ── the one contract: everything submitted is recorded  │ │ $UNITY_HPC_   │
 └───────────────────────────┼─────────────────────────────┘ │  DATA         │
                             │                               │ summaries.db  │
                    ┌────────▼─────────┐                     │ usage.db      │
                    │ UNITY  (SLURM)   │────telemetry───────▶ │ cluster-      │
                    └──────────────────┘                     │  config.json  │
                                                             └───────────────┘
```

## 5. Submit path — controller dispatch → `run.sh run` / `run.sh array`

```
 skill ──▶ run.sh run <exp> [--campaign C]
              │
              ├─▶ load .env  ──┐
              │                ├─▶ merge: caller override wins  (${!v+x}: SET, not non-empty)
              ├─▶ env overrides┘        UNITY_OVERRIDABLE = JOB_COMMAND WALLTIME SLURM_*
              │                                              SLURM_PARTITION_FALLBACK
              │                                              SLURM_PARTITION_WALLTIME_CAP
              │                                              REMOTE_DIR UNITY_HOST CAMPAIGN
              │                                              MODULES VENV_PATH HF_HOME USER_EMAIL
              ├─▶ _require_safe_name(exp, campaign)   ── exp → remote shell │ campaign → file path
              │        └─ reject metacharacters, exit 2
              │
              ├─▶ render()  =  #SBATCH header  +  typed job_template.sh
              │        └─ printf %q  for EXP / JOB_COMMAND   (quotes survive)
              │        └─ --gres only if SLURM_GPUS set and != "0"
              │
              ├─▶ _submit_plan()  ── the rungs to try, in order, as PARTITION⇥WALLTIME
              │        ├─ ladder inactive → one rung, SLURM_PARTITION, walltime EMPTY
              │        │                    (empty = add no --partition/--time at all)
              │        └─ ladder active   → SLURM_PARTITION_FALLBACK, first entry primary,
              │                             each W = WALLTIME clamped by
              │                             SLURM_PARTITION_WALLTIME_CAP[P]
              │
              ├─▶ _submit_ladder()  ── one attempt per rung, in order
              │        │
              │        ├─▶ ssh unity 'cd $REMOTE_DIR && sbatch --partition=P --time=W'
              │        │        └─ (command line beats the #SBATCH header render() baked in)
              │        │           a clamp that SHORTENS the request says so on stderr
              │        │
              │        ├─ job id parsed  ─────────▶ SUBMIT_JOB_ID / SUBMIT_PARTITION, stop
              │        ├─ sbatch refused (rc != 0) ─▶ next rung
              │        └─ rc == 0, no job id       ─▶ STOP. Accepted but unnameable: the job
              │                                       is queued, so a retry would run it twice
              │
              └─▶ campaign.record(project, C, 12345, exp, SUBMIT_PARTITION)  ◀── THE CONTRACT
                       │                                   └─ the partition it LANDED on,
                       │                                      not the one first requested
                       └─ .unity_state/C.db   (PENDING, submitted_utc)

 --dry-run  ─▶ renders + prints, touches nothing, records nothing
               (previews _submit_plan's FIRST rung, carrying the same
                --partition/--time a real submit would, then lists the ladder)
```

The ladder is opt-in and off by default: with `SLURM_PARTITION_FALLBACK` unset,
`_submit_ladder` makes exactly one attempt and adds no `--partition`/`--time`
of its own, which is byte-for-byte the submit that preceded the ladder. An explicit caller
`SLURM_PARTITION` also disables it — the caller named a partition, so the
ladder does not second-guess it. A *blank* one does not: `SLURM_PARTITION=` is
this script's documented way to unset an option for one invocation, so it reads
as "I am not naming a partition". See `docs/design-decisions.md` §3.1 D9.

`--dry-run` reads the same `_submit_plan`, which is what stops the preview from
describing a submission that cannot happen. A preview built independently drifts
the moment either side changes.

Every variable that `render()` bakes into the job must appear in
`UNITY_OVERRIDABLE`. A variable that `render()` exports without that listing
ignores the caller in silence. `MODULES`, `VENV_PATH`, `HF_HOME` and `USER_EMAIL`
all did, until 0.9.1.

Two tests now hold the line. One enforces that rule. The second enforces that
somebody actually reads every key `env.example` advertises.

### Fan-out — `run.sh array`

`run.sh array <manifest> [--campaign N] [--limit N]` reuses the resource
template's `#SBATCH` header through `render_array()`, adds
`--array=0-N%LIMIT`, and names logs `%A_%a`. One `sbatch --array` call submits
the whole batch; `campaign.record` writes N ledger rows, keyed
`<parent>_<index>`.

A manifest line is `EXP` alone, or `EXP<TAB>JSON`. The JSON tail becomes
`UNITY_TASK_PAYLOAD` in the task's environment. The harness copies that tail
and never parses it — `EXP` stays the SLURM job name and a filename fragment,
so it cannot carry structure. A tab-free line keeps today's `EXP`-only
behaviour.

### Remote bootstrap hook

If `unityHPC/bootstrap.sh` exists, `job_template.sh` sources it under one
`flock` on `REMOTE_DIR`, re-checks after acquiring the lock, and falls back to
plain `VENV_PATH` activation when the file is absent. The lock exists because
fan-out starts N tasks together, and they would otherwise race each other
setting up the same NFS-mounted environment. A project that needs conda,
modules, `HF_HOME` or scratch setup writes that once, in the hook, and every
task shares the lock.

### Cancel — `run.sh cancel`

`run.sh cancel [--campaign N] [--job P]` resolves the campaign's cancelable
rows to their distinct parent job ids — an array's children collapse onto the
id `scancel` understands — issues one `scancel` over SSH, and writes
`CANCELLED` back to the ledger. `unity_cancel` delegates to the same
subcommand.

## 6. Read path — no SSH unless asked

```
 unity_status / unity_jobs / hpc-status
        │
        ├─▶ read  .unity_state/<C>.db          (job_id, exp, status, partition)
        │
        └─▶ refresh_from_telemetry()           (shared summaries.db → hardware, elapsed)
                 │
                 └─▶ apply_states()
                        └─ states empty? RETURN 0 — never migrate schema on a read
                           (a git-tracked .db must not go "modified" from a look)
                        └─ TERMINAL states never regress

 unity_logs ──▶ ssh tail live  ──(fail)──▶ _results/<C>/<exp>-<id>.out
 fetch      ──▶ rsync --include=<exp>-<id>.{out,err} --exclude=*  ──▶ _results/<C>/
```

## 7. Shared tier — telemetry to recommendations

```
  Unity  ──sacct/seff──▶ collector.sh ──▶ telemetry/<day>/task_runs.jsonl   (raw, append-only)
                                              │
                              sync-telemetry.sh (retention gate: is --delete safe?)
                                              │
                                          rollup.py
                                              │
             derive_hardware(gpu_type, req.gpus) ──┬─ gpu_type   → "a100"
                                                   ├─ gpus>0     → "gpu:unspecified"
                                                   └─ else       → "cpu"
                                              │
                                              ▼
                          summaries.db   task_run(hardware, partition, …)
                                          task_profile · project_hardware_profile
                                              │
        ┌─────────────────────────────────────┼──────────────────────┐
        ▼                                     ▼                      ▼
  unity_usage                          unity_traffic        recommend-hardware
                                                             (may ∩ free ∩ fast)
```

`hardware` is a device class, never a queue name. The queue lives in its own
`task_run.partition` column.

Mixing the two made `task_profile`, `recommend-hardware` and
`project_hardware_profile` rank buckets that were not comparable. 22,070 a100 jobs
sat in a bucket labelled `gpu`.

`backfill_hardware.py` repairs the historical rows. It re-derives each one from the
raw telemetry, and guesses nothing.

## 8. Scaffold drift

```
  plugin templates/                       project unityHPC/
  ├── common/run.sh  ──── hpc-scaffold ──▶ run.sh   ← a COPY, frozen at scaffold time
  └── */job_template.sh                    job_template.sh
                                           .env     ← never touched, md5-checked

  server-side fix ──▶ /reload-plugins ──▶ live immediately
  scaffold-side fix ─▶ NEVER propagates until re-scaffold
                        │
                        └─▶ unity_doctor:  UNITY_SCAFFOLD_VERSION stamp
                                         + content diff (stamp line excluded)
                                         → "dispatcher differs from templates"
```

This is the plugin's one structural hazard: two update channels with different
latencies.

A project can run a months-old dispatcher against a current MCP server. The local
output then looks correct while the cluster does something else. `unity_doctor`
exists to make that visible. It compares content rather than version numbers,
which keeps it from crying wolf on a server-only release.

**The stamp must stay inside the first 40 lines of `run.sh`.**
`_scaffold_version()` (`mcp/hpc_server.py`) reads `splitlines()[:40]` and gives
up after that, returning `None` — which the caller cannot distinguish from a
pre-0.8.2 dispatcher that was never stamped. Drift detection then fails silently
and permanently. The stamp currently sits at line 39, so the header comment above
it has **one line of headroom**; adding two lines of prose there disables
`unity_doctor` for every project scaffolded afterwards. `tests/test_doctor.py::`
`test_a_freshly_generated_scaffold_is_not_stale` is the guard, and it is the only
thing standing between a header edit and a silent regression.

`run.sh` also ends with a `[ "${BASH_SOURCE[0]}" = "${0}" ]` guard around its
`case` dispatch, so the file can be `source`d to unit-test its helpers without
running a subcommand. It is the one test affordance inside the frozen copy;
`tests/test_partition_fallback.py` depends on it.

## 9. Concurrency invariants (I1–I9)

Code comments and tests cite these identifiers in more than 20 places. Search the
tree for `I7` or `RC-3` and you land on the mechanism that holds the invariant.

| Invariant | Mechanism |
|---|---|
| I1 · Telemetry has exactly one writer | `collector.sh` runs **on the cluster**, and is the only writer of the authoritative `/work/.../cluster-intel/telemetry/`. Two guards keep it single: `tmux has-session` and `collector.lock` |
| I2 · Only the sync script mutates telemetry | The local tree is a **mirror**. `sync-telemetry.sh` changes it through `rsync` alone. No other module opens anything under `telemetry/` to write or to delete, and there is deliberately no local pruner |
| I3 · A reader never sees a partial DB | A rollup builds a `.tmp` file, then calls `os.replace()`. That is atomic on POSIX, on the same filesystem |
| I4 · A config write never loses data | `flock`, then read-merge-write, then an atomic rename. The merge takes the union and the max, and it leaves an unobserved field untouched |
| I5 · Redundant work is skipped | A TTL staleness guard on recon, with `--force` to override it |
| I6 · Missing data degrades, and never crashes | Every reader returns a clear empty state that names the command which populates it |
| I7 · The pull and the rollup are serialised | One `flock` on `locks/sync.lock` spans the rsync **and** the rollup. A concurrent invocation exits cleanly, and skips both |
| I8 · Raw data is summarised before it disappears | `sync-telemetry.sh` withholds `--delete` for the whole run if any day it would remove has `day_index.fully_summarised` false, or if `summaries.db` is absent. `UNITY_HPC_FORCE_PRUNE=1` overrides this |
| I9 · A summary outlives its raw data | A rollup upserts, and never deletes a row. A full rebuild is a migration-only operation |

**RC-3**, cited in `tests/test_recon_skill.py`, is the historical fault these
invariants answer: recon used to do a blind create-or-overwrite of the single
shared prose profile, with no lock, no merge and no staleness check.
`docs/design-decisions.md` records that history in full.

## 10. Design rules

- **The core is metric-agnostic.** Nothing in the plugin knows what a metric
  means. A project can declare one in `unityHPC/metrics.json` (`primary`, `goal`,
  `report`, `labels`).

  Without that file, the tools report whatever the job printed.
- **Reads never write.** A management tool does not migrate a schema, does not
  create a file, and does not use SSH unless the operation needs it.
- **Consumer project data is never destroyed.** `.env`, hand-written scripts and
  git state stay as they are. A scaffold replacement keeps the original in an
  append-only backup.
- **Other users share the login node.** No compute runs on the login node, and a
  non-interactive SSH call runs under `timeout`. The MCP server (`$UNITY_SSH_TIMEOUT`,
  default 60s), `collector.sh` and `hpc-tmux` all obey this. **The dispatcher does
  not yet:** `run.sh` makes six untimed SSH calls, so a wedged login node hangs it.
  That is a known gap, not a decision.
- **Two safe-name gates, kept in step.** `run.sh` and `hpc-tmux` each hold their
  own copy of `_require_safe_name`, because `hpc-scaffold` copies the dispatcher into consumer
  projects, and that copy cannot source plugin code. `tests/test_safe_name_parity.py` fails
  if the two copies diverge.
- **GPU testing runs inside a written envelope** — see `docs/gpu-test-envelope.md`.

## 11. Watcher — `scripts/hpc-watch`

```
 you ──▶ scripts/hpc-watch --campaign N [--job P] [--poll SECONDS]
              │
              ├─▶ flock .unity_state/<campaign>.watch.json  ── one watcher per campaign
              │        └─ held already → print, exit 1
              │
              └─▶ loop until every in-scope group is terminal
                       ├─▶ run.sh status         (text contract only, no ledger, no sacct)
                       ├─▶ run.sh run  (retry)   within the harness-owned budget
                       ├─▶ run.sh fetch          once every in-scope job is terminal
                       └─▶ Ctrl-C or the terminal closing stops it; nothing respawns it
```

The watcher is opt-in, foreground, and runs on the user's machine — not a
`run.sh` subcommand, and not a login-node daemon. It drives only `run.sh
status`, `run` and `fetch`; it never opens the ledger, never calls `sacct`,
and never calls `sbatch`. The partition ladder (D9) stays inside `run.sh`.

The harness owns the retry budget: no retry after that token's previous retry
failed, no retry for a job that died within 120s of submit, and attempt
counts persist in `.unity_state/<campaign>.watch.json` so a restart does not
reset the budget. Infinite retry is not the default.

`scripts/hpc-watch` lives in the plugin, not in the frozen `templates/scaffold/
common/run.sh` copy: a watcher baked into the scaffold would freeze retry
policy at scaffold time.
