# unity-hpc — design decisions

Why the plugin has the shape it has. `ARCHITECTURE.md` describes *what* the plugin
does. This document records *why*, so that a future change does not re-litigate a
settled question, or repeat a fault the current design exists to prevent.

It replaces three executed implementation plans, two dated design specs and a v0.3
build plan. Git history holds those originals.

Current at plugin version 0.10.1.

---

## 1. The faults that drove the 2026-07-22 redesign

Tests still cite these identifiers, so this list keeps them verbatim.

**RC-1 · No scaffold shipped.** `_unity_submit` shelled `bash unityHPC/run.sh run
<exp>` with no existence check and no fallback. The plugin shipped no `run.sh`, no
`sync.sh` and no `submit.py`. A fresh project got a raw shell error with no hint.

**RC-2 · ML coupling.** The single shipped template served exactly one ML project:
`python -u train.py`, `torchrun`, `module load cuda/12.8`, `.venv` activation and
`nvidia-smi`. There was no CPU path, and no way to run an arbitrary command.

**RC-3 · Destructive shared write.** The recon skill did a blind
create-or-overwrite of the one shared prose profile. No lock, no atomicity, no
merge, no staleness check. `tests/test_recon_skill.py` cites this ID.

**RC-4 · Project bias in cluster truth.** Recon wrote project-flavored prose into a
document that describes the **cluster**. A CPU project wrote a reduced GPU capacity
(`a100=40`), which destroyed a GPU project's correct reading (`a100=157`). RC-3 made
the overwrite possible. RC-4 made it harmful.

**RC-5 · Setup fragility.** Skill text named a plugin-directory placeholder that
never resolved at runtime. `git checkout -b` hard-failed in a non-git project. The
`.env` defaults suited short ML iterations, not long CPU pipelines. Setup also
planted two persistent login-node tmux sessions on shared infrastructure, as a
routine step.

**RC-6 · No live reconciliation.** The campaign DB recorded a submission only, so
`unity_status` reported `SUBMITTED` forever.

## 2. Goals that still bind

- **G1** A user can submit any Unity job with no extra setup: CPU-only,
  single-GPU, multi-node ML, or an arbitrary command.
- **G2** Concurrent projects can run every skill at the same time, with no data
  loss and no corruption.
- **G3** Shared data stays structured and deterministic, so a program can base a
  scheduling decision on it.
- **G4** Setup succeeds in a plain, non-git directory, and it never touches shared
  infrastructure without explicit consent.
- **G5** The plugin is honest about what Unity does and does not expose.

Non-goals, still deliberate: in-job time-series (see §4), replacing SLURM
scheduling, cross-cluster portability, and a GUI.

## 3. Decisions

### 3.1 Submission and data core

| # | Decision | Why | Rejected |
|---|---|---|---|
| D1 | **A typed scaffold generator.** Setup asks for `cpu`, `gpu` or `ml`, then generates `unityHPC/` from plugin templates | It keeps the existing `run.sh` contract, so the MCP surface does not churn, and the plugin finally ships the scaffold and a real CPU path | A declarative `jobs.toml` renderer, which is cleaner but has a larger blast radius. Raw command passthrough, which gives no reproducibility |
| D2 | **A greenfield structured store, then a migration** | The old files were ad-hoc and markdown-shaped. A deterministic scheduling decision needs typed, queryable data | Evolving the old databases in place. Cheaper, but it perpetuates the prose-profile design |
| D3 | **Single-writer telemetry.** Only the cluster-side collector writes. Projects read | It removes the write contention behind RC-3 structurally, not by convention | Lockfiles around multi-writer access, which still permit a lost update after a logic error |
| D4 | **A deterministic merge for `cluster-config.json`** | Recon runs from different projects observe different subsets. A merge preserves the union | Last-writer-wins with provenance. Visible, but still lossy |
| D5 | **Query tools plus a skill that decides.** The scheduling policy lives in the skill, not in the tool | It keeps the data layer deterministic and testable, and it keeps the policy inspectable and adjustable per project | A turnkey advisor MCP tool, which bakes policy into code and is harder to check |
| D6 | **Partition raw telemetry by `date/kind`, not by `date/resource_id`** | 544 nodes with one file per resource is about 544 files per day. `resource_id` is a field, and a rollup scans by day | The literal `date/resource_id` layout. It matches the original sketch, and it is operationally unwieldy |
| D7 | **A one-time break of hand-written scaffolds was accepted** | Two projects worked only because they hand-wrote the scaffold the plugin never shipped. To support those bespoke layouts forever would freeze the coupling this redesign removes. The owner of all three projects accepted the disruption | Treating a hand-written scaffold as a supported configuration, which freezes the contract. An opt-in converter, which is more to build for a two-project blast radius |

### 3.2 Per-project scheduling reader

| # | Decision | Why | Rejected |
|---|---|---|---|
| R1 | **Read-time correlation, with no change to the shared store** | Attribution belongs where the identity is known, that is the project. It keeps `summaries.db` project-agnostic and the collector unchanged | Cluster-side job-name tagging. It needs a `run.sh` convention plus a collector parse, and it is brittle |
| R2 | **On demand by default. A persisted snapshot is optional** | `task_run` is retained long-term and never pruned (I9), so the history already survives in the shared store. A per-project copy is derivable, and would only add staleness | Always persisting a per-project profile file: duplicate state, plus cache invalidation |
| R3 | **The project's own profile, with a cold-start fallback to the shared `task_profile`** | A new project with few jobs of its own still gets a useful ranking, until it has enough history | Project-only, which is useless on a fresh project. Shared-only, which ignores the project's measured reality |
| R4 | **Reuse the existing fail-safe query pattern** | `lib/queries.py` already opens `summaries.db` read-only, and returns a conservative value when the database, table or row is absent (I6) | A new bespoke database-access path |

The insight behind R1: a project already knows its own job ids, because `run.sh`
registers every job it submits in `.unity_state/<campaign>.db`. The shared
`task_run` table uses `job_id` as its key. The join therefore happens locally, at
read time, per project.

### 3.3 `hardware` is a device class, never a queue

`ARCHITECTURE.md` §7 and the README record this decision and the repair. It is the
one decision with a measured cost: 84 distinct values collapsed to 17, and 22,070
jobs filed under `gpu` turned out to be a100s.

## 4. What Unity exposes, and what it does not

From a login-node survey on 2026-07-22, on login6, with Slurm 25.11.6. Treat the
numbers as a dated observation, not as live state.

**Available.** Cluster scale, which was 544 nodes, 42,720 cores, 1,400 GPUs, 16
accelerator types and 36 partitions. Allocation against capacity, per partition.
Idle cores, memory and GPUs, per node. The GPU fleet by type, with VRAM and compute
capability.

Also: queue depth **with pending reasons**, that is Priority, Dependency,
MaxGRESPerAccount and MaxCpuPerAccount. Open against restricted partition access.
The fair-share factor. QOS and association limits. Job accounting through `sacct`.
CPU and memory efficiency per job through `seff`. Live stats for a running job
through `sstat`. Load rollups through `sreport`. Storage headroom.

**Not available from the login node.** In-job time-series: the real-time GPU busy
fraction, VRAM draw, power, and per-second CPU or memory curves. These need
`nvidia-smi` or `dcgmi dmon` **inside** a running job, or a metrics endpoint that
Unity does not publish.

**18 GPU nodes sit outside the account's visibility.** Every capacity figure is
therefore *accessible* capacity, and the schema names the field `total_accessible`.
The schema carries **no** per-node busy-fraction field. An invented one produces a
mostly-null column that reads as real data.

**Operational trap.** The `unity-slurm-*` wrappers live in
`/modules/user-resources/bin`, which is **not on the non-interactive PATH**. A
scripted or SSH invocation must prepend that directory, and must set `PAGER=NONE`.

## 5. Risks the design accepts

| Risk | Mitigation |
|---|---|
| `unity-slurm-*` output is pretty-printed, and is not a stable API | Prefer raw `sinfo` and `squeue` wherever they are equivalent. Use a wrapper only for data with no raw equivalent, that is VRAM and compute capability. Parse defensively, and record a parse failure as an event |
| Login-node etiquette | A 15-minute cadence, `timeout` on every command, `nice`, one session, and explicit opt-in |
| The first sacct backfill is expensive | It runs inside tmux, it can resume, and it works in per-day chunks. It is opt-in, and clearly flagged |
| Capacity figures exclude 18 invisible GPU nodes | The field is named `total_accessible`, and §4 documents the limit |
| Schema churn | `schema_version` in both `cluster-config.json` and `summaries.db`. Readers assert on it |

## See also

- `../ARCHITECTURE.md` — the layer map, the submit path, and the I1–I9 invariants
- `../README.md` — installation and daily use
- `docs/open-follow-ups.md` at the marketplace root — what is still open
- `docs/marketplace.md` at the marketplace root — naming, versioning, releases
