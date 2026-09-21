# unity-hpc — design decisions

Why the plugin has the shape it has. `ARCHITECTURE.md` describes *what* the plugin
does. This document records *why*, so that a future change does not re-litigate a
settled question, or repeat a fault the current design exists to prevent.

It replaces three executed implementation plans, two dated design specs and a v0.3
build plan. Git history holds those originals.

Current at plugin version 0.13.0.

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
| D8 | **The array manifest is keyed by the parent job id — `_slurm/<campaign>-<jobid>.manifest`, uploaded once `sbatch` has replied** | An array task reads its own line at runtime, not at submit time. Keyed by campaign name, a second `run.sh array` under the same campaign overwrote the file the first array's queued tasks had not read yet, and those tasks then ran the second array's units under the first job id, with no error anywhere. A job id no other array can hold removes the shared name itself | Refusing the second submission while one is live: it detects the collision instead of removing it, and one forgotten rule brings it back. Snapshotting the manifest into the sbatch script: race-free, but it embeds thousands of lines in every script |
| D9 | **The partition fallback ladder is opt-in, and only a REFUSED `sbatch` advances it** | On a shared cluster a rejected partition is routine, not exceptional, so `SLURM_PARTITION_FALLBACK` takes an ordered list and retries down it. Five constraints shape it. (a) Unset, it must be byte-for-byte the previous single-attempt submit — a project that never asked for this must not find synthetic `--partition`/`--time` on its `sbatch` line. (b) Partitions have different walltime ceilings, so a retry that resubmits the same walltime to a shorter-ceiling queue fails again for an unrelated reason; `SLURM_PARTITION_WALLTIME_CAP` clamps per rung. (c) Only a non-zero `sbatch` means "this partition refused the job". An accepted submission whose reply carries no job id stops the ladder dead: that job is already queued, and retrying would queue a second copy that no ledger row can `scancel`. (d) The two ways the ladder can be stood down must not overlap with the script's existing idioms: it is the caller's *value* of `SLURM_PARTITION` that names a partition, because `SLURM_GPUS= run.sh run x` is already how this script turns an option off for one invocation, so a blank one means the opposite of naming one. (e) One `_submit_plan` produces the rungs and their clamped walltimes, and both `_submit_ladder` and `--dry-run` read it — a preview assembled independently drifts from the submit the moment either side changes, and a preview that describes a submission that will not happen is worse than no preview | Retrying on "no job id parsed", which is what the first implementation did — it cannot tell a refusal from a successful submit with an unreadable reply, and silently queues one job per rung. Making the ladder always-on with a built-in Unity partition list, which bakes cluster policy into a plugin that is meant to stay generic. Clamping only on retries and not the first attempt, which leaves the primary rung the one case that can fail on walltime — it clamps every rung instead, and says on stderr when a cap actually shortened the request. Reading the cap table permissively: a hand-written `"a=1:0:0, b=2:0:0"` split on the comma alone yields the name `" b"`, an entry with no `=` puts a partition NAME into the arithmetic, and either way the ceiling the author wrote down silently did not apply. Malformed entries are named on stderr and skipped |

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

### 3.4 Five primitives: resource × orchestration, one public name

D1 ships a typed scaffold with `--type {cpu,gpu,ml}`. That list mixes a
**resource** (`cpu`, `gpu`) with an **orchestration** (`ml` = coordinated
multi-node training). Arrays — the other orchestration — are not a type. They
live in `common/run.sh`. A CPU job that spans nodes and talks through `srun`
has no home. Issue #11 pinned the names. `CONTEXT.md` holds the glossary.

| Primitive | Resource | Orchestration | What it is |
|---|---|---|---|
| `cpu` | cpu | single | One CPU job. One `sbatch`. One ledger row. |
| `gpu` | gpu | single | One GPU job on one node. One `sbatch`. One ledger row. Several GPUs on that node still count as `gpu`. |
| `multi-cpu` | cpu | fan-out | N independent CPU tasks. Today's `run.sh array`. N ledger rows. |
| `multi-gpu` | gpu | fan-out | N independent GPU tasks. Today's `run.sh array`. N ledger rows. |
| `ml` | gpu | coordinated | One allocation whose ranks communicate. Today's `ml` template. One ledger row. |

The two axes classify the five names. They are not two CLI flags. A cartesian
`--resource` × `--orchestration` would let a caller write `cpu` + coordinated,
which this plugin does not implement, and it would treat `ml` as `gpu` + multi,
which is `multi-gpu`. The public selector stays one name.

**`ml` is a primitive, not a `multi-gpu` preset.** The difference is
independence, not the launcher. Fan-out tasks do not communicate. Coordinated
ranks share one allocation and exchange messages. `torchrun` is today's
implementation of coordinated GPU. It is not the definition. A later launcher
does not create a sixth primitive.

**`gpu` with `SLURM_GPUS>1` is not `multi-gpu`.** One process on one node that
uses several GPUs is still `gpu`. `multi-gpu` is N independent copies of that
shape.

**Multi-node CPU is out of scope for this redesign.** `run.sh` does not emit
`--ntasks` or `--ntasks-per-node`. No CPU template calls `srun`. G1 never named
that shape. No closed issue asked for it. It is not a flag on `multi-cpu`: that
would mix two submission mechanisms under one name. It is not a sixth
primitive on this map. A later consumer that needs it would add a coordinated
CPU primitive. That work is separate.

#4–#8 act on a group. Fan-out (`multi-cpu`, `multi-gpu`) is that group.
`cpu`, `gpu` and `ml` remain one job.

### 3.5 Fan-out payload is opaque JSON; headers stay as today

`cpu`, `gpu` and `ml` keep today's `render()` header: `--job-name`, `--account`,
`--partition`, `--time`, `--nodes`, `--cpus-per-task`, `--mem`, `--output`,
`--error`, optional `--gres` / `--constraint` / `--mail-user`. They never emit
`--ntasks` or `--ntasks-per-node`. `ml` raises `SLURM_NODES` and the template
launches ranks; it still has no `--ntasks` line.

`multi-cpu` and `multi-gpu` keep today's `render_array()` header: the same
keys, plus `--array`, plus logs named `%A_%a`. One `sbatch --array`. N ledger
rows as `<parent>_<index>`. `JOB_COMMAND` is shared. Per-task data is the
manifest.

A fan-out task receives `EXP` and, when the manifest line has a tab, the JSON
tail as `UNITY_TASK_PAYLOAD`. A tab-free line is today's `EXP`-only behaviour.
The harness copies the tail. It does not parse it. `EXP` stays the SLURM job
name and a filename fragment, so it cannot carry structure. Closed #7 is the
contract. `ml` has a per-job `EXP` only. No per-task payload.

### 3.6 `campaign` stays a label; the group is the parent job id

Promoting `campaign` to the fan-out identity fights its default (today's UTC
date) and fights D8 (the manifest is already keyed by parent job id after #9).
A campaign remains an optional label. It may mix primitives. Two `multi-*`
submits may share one campaign name. The group object the verbs need is the
parent SLURM job id: identity, membership (`<parent>_<index>`), and the id
one `scancel` covers.

**Public scope is the label.** `cancel`, `fetch` and `watch` take `--campaign
N` and act on every live group with that label. `--job <parent>` pins one
group. `status` and `jobs` already take the same flag. A campaign, as a
label, has no end state. A group is finished when every child row is
terminal.

**Remote layout is campaign-keyed, prefer-if-present.** New scaffolds default
jobs to `$REMOTE_DIR/_results/<campaign>/`. `REMOTE_RESULTS_DIR` joins
`UNITY_OVERRIDABLE`. Fetch prefers `<base>/<campaign>` when that directory
exists, and falls back to today's whole-tree rsync when it does not, so a
flat `_results/` project keeps working. Two `multi-*` submits that share a
campaign share one results tree. Closed #4 and #5 are in.

### 3.7 Watcher is opt-in, foreground, on the user's machine

Closed #6 asked for poll → requeue → fetch. Auto-requeue inside `run.sh
status` stays rejected: a read tool must not submit. The collector's tmux
session on the login node is not the pattern to copy. The login node is
shared, and §10 forbids compute there. A watcher that resubmits is not
telemetry.

The watcher is a process the user starts on their machine and stops with
Ctrl-C. No other subcommand starts it. It takes `--campaign N` (optional
`--job`). It calls `run.sh status`, `run` (retry), `fetch`, and `cancel` only.
It never opens the ledger, never calls `sacct`, never calls `sbatch`. The
partition ladder stays inside `run.sh` (D9).

The harness owns the retry budget: no retry if that token's previous retry
failed; no retry if the job died within 120s of submit; attempt counts
persist so a restart does not reset the budget. A project may disable the
watcher or pass tighter limits. Infinite retry is not the default.

**Guards.** Attempt counts live in `.unity_state/<campaign>.watch.json`. One
`flock` on that file: a second watcher on the same campaign exits. The
process dies with the terminal. Nothing respawns. It runs until every
in-scope group is terminal, then `fetch`, then exits.

The watcher binary lives in the plugin (`scripts/hpc-watch`), not in the
frozen `run.sh` copy. It calls the project's `unityHPC/run.sh`. A watcher
inside the scaffold would freeze retry policy at setup time (§8).

### 3.8 Remote bootstrap is a locked hook, not a pip convention

Nothing in the plugin creates a remote environment. That is survivable for one
job and not for fan-out: N tasks start together and race on NFS. The race is a
property of the primitive. The lock is the part every project gets wrong.

If `unityHPC/bootstrap.sh` exists, the job template sources it under one
`flock` on `REMOTE_DIR`, re-checks after acquire, and uses `if/then … exit 0`
(not `[ … ] && exit 0` under `set -e`). If the file is absent, the template
only activates `VENV_PATH` as today. No `VENV_BOOTSTRAP` flag. No
`requirements.txt` convention. A project that needs conda, modules, `HF_HOME`,
or scratch setup writes that in the hook and still gets the lock.

### 3.9 Sequenced work is out of scope

`--dependency=afterok:` is a different object from same-shape fan-out. The
evidence base has no DAG workaround. A later map can name it. This one does
not.

### 3.10 `--type` grows two names; the three old ones stay

`--type cpu|gpu|ml` keep working: `ml` is still a primitive. `--type
multi-cpu` and `--type multi-gpu` are added. No `.env` key is renamed.
`templates/scaffold/{cpu,gpu,ml}` stay. Fan-out reuses the matching resource
template plus `common/run.sh array`. There is no `templates/scaffold/multi-*`
directory.

Re-scaffold keeps today's replace and `.pre-redesign/` backup. There is no
migration command and no major version bump for the type set. `unity_doctor`
does not treat a three-type scaffold as broken. A generated `run.sh` that
lacks cancel, payload or hook is ordinary scaffold drift: re-scaffold picks
it up.

### 3.11 MCP matches the dispatcher; it does not take a primitive

Primitive is a scaffold fact (`--type` at setup). MCP tools do not grow a
`type` or `primitive` parameter. `unity_submit` stays `run.sh run`. Add
`unity_array` (manifest) and `unity_cancel`. Do not add a long-running
`unity_watch` tool. An agent uses the same verbs as `run.sh`. Policy stays
in the skill (D5).

### 3.12 Telemetry does not record the primitive

`task_run.hardware` is a device class (§3.3). The primitive is a project
fact. The collector cannot see it. Do not add a `primitive` column. If a
ranking needs the primitive, join the project ledger at read time (R1).

### 3.13 Skills and README follow the five names

The setup type table lists `cpu|gpu|ml|multi-cpu|multi-gpu`.
`/unity-hpc:sweep` is the fan-out path. `/unity-hpc:run` stays single-job.
README drops the sentence that nothing runs in the background. Document
payload, `bootstrap.sh`, `cancel`, and `watch`.

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
- `../CONTEXT.md` — glossary for the five primitives and the two axes
- `scaffold-axes-spec.md` — implementable spec for the scaffold-axes redesign
- `../README.md` — installation and daily use
- `docs/open-follow-ups.md` at the marketplace root — what is still open
- `docs/marketplace.md` at the marketplace root — naming, versioning, releases
