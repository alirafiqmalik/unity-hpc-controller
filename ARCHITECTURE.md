# unity-hpc — architecture

Version 0.9.1. An abstraction layer between a project's experiments and Unity's
SLURM cluster. The plugin's job is plumbing — submit, record, observe, fetch —
and to stay generic: nothing in the core knows what a project's metrics mean.

**The central contract:** `unityHPC/run.sh` records every job it submits into
`<project>/.unity_state/<campaign>.db`. Every management tool reads that ledger.
If a job is not in the ledger, the project cannot name it.

---

## 1. Skills

User-facing entry points, invoked as `/unity-hpc:<name>`.

| Skill | Purpose | Touches cluster? |
|---|---|---|
| `setup` | Bootstrap a project: verify SSH, scaffold `unityHPC/`, sync code to `/work`, run recon if the shared profile is missing | yes |
| `run` | Submit one job, queue-aware, and record it in the ledger | yes |
| `sweep` | Submit a batch under one campaign, respecting account submit limits and queue depth | yes |
| `status` | This project's job states — local ledger read, with an explicit live SLURM check when it matters | no (opt-in) |
| `fetch` | rsync job output back, then summarise whatever metrics the jobs printed | yes |
| `log-result` | Append a row to `results.tsv`, using that file's existing columns and the project's declared metric | no |
| `recon` | Observe partitions, GPU fleet, account limits, fair-share and storage; merge into the shared `cluster-config.json` | yes (read-only) |
| `recommend-hardware` | Rank backends: what you may request ∩ what is free now ∩ what has been fastest for you | no |
| `resume` | Rebuild session context after a reset, from ledger + results + cluster profile + queue | no |

## 2. MCP tools

Served by `mcp/hpc_server.py` over stdio; namespaced `mcp__unity-hpc__*`.
Stdlib + `mcp` only.

**Project-local reads — no SSH, instant**

| Tool | Returns |
|---|---|
| `unity_status` | Job state counts for the latest (or named) campaign |
| `unity_jobs` | job_id, exp, partition, status, and the hardware each landed on |
| `unity_results` | Numeric `key: value` pairs each fetched job printed to stdout — metric-agnostic |
| `unity_results_tsv` | Local `results.tsv` as structured rows, header-driven |
| `unity_my_jobs` | This project's jobs enriched from shared telemetry |
| `unity_doctor` | Which plugin version this server process is actually running, plus scaffold drift |

**Cluster-touching**

| Tool | Notes |
|---|---|
| `unity_submit` | Delegates to `run.sh run`; `--dry-run` previews |
| `unity_logs` | Live tail over SSH, falling back to a fetched copy |
| `unity_ssh` | Read-only command on the login node; blocks dangerous writes; `timeout` arg |

**Shared-tier reads**

| Tool | Notes |
|---|---|
| `unity_cluster_profile` | Partitions, GPU types, account limits, capacity — cwd-independent |
| `unity_traffic` | Live-ish queue signal plus best/worst submit hours |
| `unity_usage` | Historical usage by window: GPU allocation by type, jobs, memory |

## 3. Internal tools

**Dispatcher** — `unityHPC/run.sh`, generated into each project.
Subcommands: `run` · `render` · `sync` · `status` · `jobs` · `logs` · `fetch`.

**Python libraries** (`lib/`)

| Module | Role |
|---|---|
| `campaign.py` | The per-project job ledger — the one record every management tool reads |
| `scaffold.py` | Typed scaffold generator; version stamping and append-only backups |
| `metrics.py` | Optional, per-project metric declaration (`unityHPC/metrics.json`) |
| `queries.py` | Read-only helpers over `summaries.db`; these never write |
| `cluster_config.py` | Deterministic, order-independent merge for the shared cluster config |
| `retention.py` | Retention gate: decide whether an `rsync --delete` is safe |
| `paths.py` | Resolution of the machine-wide data store |

**cluster-intel** — `collector.sh`, `collector_parse.py`, `rollup.py`,
`sync-telemetry.sh`, `migrate.py`, `backfill_hardware.py`, `dashboard/`.

**CLI scripts** (`scripts/`) — `hpc-scaffold`, `hpc-status`, `hpc-results`,
`hpc-logs`, `hpc-ssh`, `hpc-tmux`, `hpc-usage`, `hpc-compare`, `hpc-dashboard`,
`hpc-cleanup`, `hpc-sync-telemetry`, `hpc-retention-gate`, `hpc-config-write`.

**Templates** (`templates/scaffold/`) — `common/{run.sh,sync.sh}` plus typed
`cpu|gpu|ml/{env.example,job_template.sh}`.

**Agents** (`agents/`) — `recon`, `experiment-dispatcher`, `result-analyzer`.

---

## 4. Layer map

```
        YOU  ─── /unity-hpc:<skill> ──────────────────────────────┐
                                                                  │
 ┌────────────────────────────────────────────────────────────────▼──────────┐
 │ SKILL LAYER   setup  run  sweep  status  fetch  log-result                 │
 │               recon  recommend-hardware  resume                            │
 └───────┬──────────────────────────────────────────────┬────────────────────┘
         │ writes / submits                             │ reads
 ┌───────▼──────────────────┐               ┌───────────▼───────────────────┐
 │ DISPATCHER (in project)  │               │ MCP SERVER  mcp/hpc_server.py │
 │ unityHPC/run.sh          │               │ unity_status  unity_jobs      │
 │   run render sync        │               │ unity_results unity_logs      │
 │   status jobs logs fetch │               │ unity_ssh     unity_doctor    │
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

## 5. Submit path — `/unity-hpc:run`

```
 skill ──▶ run.sh run <exp> [--campaign C]
              │
              ├─▶ load .env  ──┐
              │                ├─▶ merge: caller override wins  (${!v+x}: SET, not non-empty)
              ├─▶ env overrides┘        UNITY_OVERRIDABLE = JOB_COMMAND WALLTIME SLURM_*
              │                                              REMOTE_DIR UNITY_HOST CAMPAIGN
              │                                              MODULES VENV_PATH HF_HOME USER_EMAIL
              ├─▶ _require_safe_name(exp, campaign)   ── exp → remote shell │ campaign → file path
              │        └─ reject metacharacters, exit 2
              │
              ├─▶ render()  =  #SBATCH header  +  typed job_template.sh
              │        └─ printf %q  for EXP / JOB_COMMAND   (quotes survive)
              │        └─ --gres only if SLURM_GPUS set and != "0"
              │
              ├─▶ ssh unity 'cd $REMOTE_DIR && sbatch' <<< script
              │        └─ "Submitted batch job 12345"
              │
              └─▶ campaign.record(project, C, 12345, exp, partition)   ◀── THE CONTRACT
                       │
                       └─ .unity_state/C.db   (PENDING, submitted_utc)

 --dry-run  ─▶ renders + prints, touches nothing, records nothing
```

Every variable `render()` bakes into the job must appear in `UNITY_OVERRIDABLE`.
A variable that is exported but not overridable silently ignores the caller —
`MODULES`, `VENV_PATH`, `HF_HOME` and `USER_EMAIL` all did, until 0.9.1. A
contract test now enforces the rule, and a second test enforces that every key
`env.example` advertises is actually read by someone.

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

`hardware` is a device class and never a queue name; the queue lives in its own
`task_run.partition` column. Mixing the two made `task_profile`,
`recommend-hardware` and `project_hardware_profile` rank buckets that were not
comparable — 22,070 a100 jobs sat in a bucket labelled `gpu`.
`backfill_hardware.py` repairs historical rows by re-deriving them from raw
telemetry, guessing nothing.

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
latencies. A project can run a months-old dispatcher against a current MCP
server and see correct-looking local output while the cluster does something
else. `unity_doctor` exists to make that visible; content comparison rather than
version equality keeps it from crying wolf on server-only releases.

## 9. Design rules

- **Metric-agnostic core.** Nothing in the plugin knows what a metric means.
  Projects may declare one in `unityHPC/metrics.json` (`primary`, `goal`,
  `report`, `labels`); without it, tools report whatever the job printed.
- **Reads never write.** Management tools do not migrate schemas, do not create
  files, and do not SSH unless the operation inherently requires it.
- **Consumer project data is never destroyed.** `.env`, hand-written scripts and
  git state are untouched; scaffold replacement preserves originals in
  append-only backups.
- **The login node is shared.** Every SSH call is wrapped in `timeout`; no
  compute runs on the login node.
- **GPU testing runs inside a written envelope** — see `docs/gpu-test-envelope.md`.
