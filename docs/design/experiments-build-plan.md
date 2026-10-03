# Experiments workspace build plan

Version 1, 2026-10-03. Planning only. This session covers design documents and wireframes.

The [functional specification](experiments-spec.md) records accepted behavior.
The sequence and technical choices below are engineering proposals for delivering it.
They do not reopen Q1–Q23 or claim approval of exact schemas and storage paths.

## Delivery boundary

Build the project layout and the Experiments workflow through its execution handoff and declared result processing.
Keep the research question in Overview.
Add the required purpose labels to project Runs, global Job Monitor, and logs.
Provide artifact and report links before building the broader Results experience.

Initial workflows use declared operations and cloning. The connection must support later composition without replacing experiment identities or history.
Do not include automatic queue reassignment, future schedules, arbitrary metric expressions, or a visual graph editor in this delivery.
Those features need separate product review.

The first end-to-end example is TLAiBench T1 with two models and two token caps.
Dependent-stage fixtures also exercise T1 → T2 → T3 compatibility and smoke-test gating.
This example does not decide the eventual prominence of the original corpus versus TLAiBench in Results.

## Architecture and ownership

Keep the controller as the sole route to cluster dispatch.
Keep `unityHPC/run.sh` as the job-ledger writer, as [ADR 0001](../adr/0001-two-component-split.md) requires.
Add an experiment service above that boundary for drafts, planning, execution history, and approved continuation.
Project adapters retain scientific meaning. The generic dispatcher remains metric-agnostic.

| Component | Responsibility | Boundary |
| --- | --- | --- |
| Project UI | Forms, autosave, plan review, purpose labels, navigation | HTTP client with no scheduler commands |
| Connection reader | Check declarations and expose typed capabilities | No arbitrary source discovery during execution |
| Experiment store | Draft revisions, plans, executions, attempts, archive state | Preserve immutable history and atomic updates |
| Plan compiler | Expand variants and stages, resolve inputs, generate wrappers | Deterministic output from explicit inputs |
| Execution coordinator | Advance the approved graph, reconcile submissions, trigger fetch and analysis | Dispatch through the controller and existing ledger writer |
| Project adapters | Collect, check, analyze, and plot scientific artifacts | Source remains in the project directory |

No component uses an LLM to interpret routine user intent or to choose the next operation.
The browser can close without stopping the approved workflow.

## Proposed data and API contract

The following names are planning choices, not existing APIs.
Phase 0 must pin exact schemas before frontend and backend integration.

Use stable IDs for experiments, revisions, plans, variants, executions, stages, attempts, and artifacts.
Store immutable references from each execution to its plan and source snapshot.
Keep campaign and scheduler identities as links, not replacements for execution identity.
Purpose belongs to a stage and persists into attempts, jobs, logs, and artifacts.

| Resource or operation | Proposed contract |
| --- | --- |
| Connection | Read schema version, capabilities, operations, workflows, metrics, and connection errors |
| Experiments | List, create, clone, archive, restore, and delete only unused drafts |
| Draft revision | Read and update with an expected revision token; return conflicts without overwriting |
| Check | Return structured errors by field, variant, stage, or artifact; no cluster dispatch |
| Plan | Return immutable expansion, snapshot references, scripts, changes, exclusions, and check results |
| Dispatch | Accept a reviewed plan ID and an idempotency key; return durable execution identity |
| Execution | Return submission outcomes, stage progress, job links, purpose, freshness, and artifact links |
| Recovery | Prepare a scoped resume/retry plan; require compatibility checks and review |
| Analysis revision | Resolve saved inputs and record a new analysis plan and outputs |

A candidate route family is `/api/v1/projects/{slug}/experiments` with separate plan and execution resources.
Existing catalog launch and generic run endpoints keep their current contracts during migration.
Do not reuse a catalog ID as a mutable experiment definition without an explicit conversion record.

Suggested storage separates project declarations from controller-owned operational records.
A project manifest can live at `unityHPC/project.json` and reference existing files.
A controller store can hold drafts, plans, submission intentions, and execution history.
Generated scripts and snapshots need execution-scoped locations, declared ownership, and references from that store.
Phase 0 must specify backup, retention, relocation, and schema migration for these records together.
Archive and draft deletion must never trigger artifact retention or project-file deletion.

Source snapshots must cover declared entrypoints, imported project code, configurations, and the connection declaration.
A Git commit alone is insufficient when relevant files contain uncommitted changes.
Large inputs need immutable versions or checked identities instead of automatic full copies.
Mutable or unavailable inputs must block a claim of a reproducible reviewed plan until the adapter supplies a supported strategy.
Environment references record the effective runtime definition without copying secret values into review or history.

## Delivery phases

### Phase 0 — Contracts and migration design

Produce exact connection and state schemas, a route contract, and a migration note.
Resolve source snapshot boundaries, variant-to-job mapping, and stage execution placement.
Specify concurrency accounting separately from coordinated-rank resources.
Record decisions for local stages, interrupted controller work, and ambiguous submission outcomes.

Proposed first fan-out unit: one independent variant contains its ordered stage chain.
TLAiBench T1/T2/T3 are not three independent siblings.
Shared checks must declare their scope and dependencies rather than rely on implicit global success.
The compiler expands this model into exact ledger submissions and dependency links.

Exit checks:

- Fixtures describe a single GPU stage, independent GPU variants, coordinated ranks, and GPU collection followed by CPU analysis.
- The model can represent all four variants and their stage dependencies without conflating variants with jobs.
- The migration preserves historical primitives, campaigns, group IDs, and job IDs.
- A design review resolves the technical contracts before implementation depends on them.

### Phase 1 — Connection contract and project adapters

Implement the versioned connection reader and structured errors.
Map the existing project modules without moving source folders.
Expose model choices through the project's declared deterministic reader.
Register available collection, checks, analysis, and plot capabilities honestly.
A missing plotting entrypoint is a visible capability gap until project code supplies it.

Update the repository connect skill, scaffold ownership rules, and generated guidance together.
Remove retired skill references and training-specific assumptions from the guidance template.
Preserve custom sync/fetch adapters and existing environment files during repeated setup.
Keep workflow declarations versioned separately from runtime metadata.

Exit checks:

- A representative existing project connects without moving scientific files or overwriting custom adapters.
- Invalid paths, missing entrypoints, unsupported schema versions, and incompatible artifact declarations produce specific errors.
- Declared bounded checks use fixtures or mock execution and never submit a cluster test implicitly.
- Setup can repeat without losing project-owned edits.

### Phase 2 — Project layout and experiment drafts

Add the dedicated project layout, Overview landing route, and Home placement.
Build the library and editor against the connection contract.
Implement typed fields, combination selection, autosave, cloning, revisions, archive, and restore.
Keep dispatched records immutable and preserve direct links to archived history.

Exit checks:

- Selecting a project replaces global navigation and opens Overview with the research question visible.
- Home restores the Projects list. Deep links, browser history, keyboard navigation, and narrow layouts work.
- A failed save retains edits and shows Unsaved. A stale revision produces a recoverable conflict.
- An experiment with execution history cannot use the unused-draft delete operation.
- Saving, filtering, cloning, and archiving cause no dispatch or cancellation.

### Phase 3 — Deterministic planning and review

Build exact variant expansion, prerequisite selection, per-stage resources, and output isolation.
Add Measurements and the full Dispatch review page.
Generate inspectable wrappers from argument vectors and declared bindings.
Implement source snapshots, input identities, plan fingerprints, and review invalidation.
Support Save as custom script through an explicit project-owned entrypoint.

Exit checks:

- Two models × two token caps produce exactly four declared variants.
- Invalid combinations block review readiness until fixed or explicitly excluded.
- Missing, incompatible, or smoke-only parent artifacts cannot satisfy a full collection prerequisite.
- Editing source, inputs, collectors, or configuration cannot silently alter an already reviewed execution.
- Arguments containing spaces or shell punctuation retain literal values in generated commands.
- Regeneration preserves custom source and creates isolated outputs for Repeat.
- Metric presets expose sources and units; optional collection requires selection.

### Phase 4 — Dispatch, continuation, and Runs handoff

Persist an execution and submission intentions before calling the dispatcher.
Add idempotent dispatch and durable per-stage outcomes.
Reconcile uncertain submissions against the existing ledger before any repeat submission.
Continue only approved dependencies, fetch, checks, and analysis after controller restart.
Keep the current single-writer contract intact.

Open Runs filtered to the new execution after dispatch.
Add Purpose separately from State in project Runs, global Job Monitor, details, and logs.
Persist purpose in attempts and child jobs. Keep historical missing purpose as Unclassified.
Implement scoped recovery plans without automatic retries or resource reassignment.

Exit checks:

- Double-clicks and repeated requests create one execution for one dispatch intent.
- A failure after some accepted jobs preserves those jobs and reports the failed or uncertain portion.
- Closing the browser does not interrupt continuation. Restarting the controller does not duplicate accepted work.
- A failing smoke test pauses its dependents while independent branches continue.
- A negative model result stays a valid scientific outcome when the declared operation completed correctly.
- Archive leaves active jobs running and their history accessible.
- Every cluster action still passes through the controller and `run.sh`.

### Phase 5 — Artifacts, analysis revisions, and release check

Add scoped fetch, completeness checks, and artifact indexing for the selected execution.
Register project analysis operations and preserve their input selections and versions.
Keep separate output summaries or serialize shared summary writes.
Expose reports and declared plots through artifact links before the full Results page review.

Fix or adapt TLAiBench deduplication so different token-cap variants survive aggregation.
Retain stage-parent provenance and expose complete corpora behind failed scheduler exits for manual recovery.
A new analysis revision uses complete saved inputs or explains the need for new collection.

Exit checks:

- Both token-cap conditions remain present after analysis of the four-variant example.
- Smoke-test records never enter default research aggregates but remain in resource accounting.
- Reanalysis creates a new report and preserves its predecessor without rerunning generation.
- Missing analysis inputs require a new explicit collection plan.
- Fetch failure and outdated summaries remain visible independently of scheduler completion.
- Repeat, retry, archive, and analysis each retain the correct execution and artifact lineage.

Release requires all phases for the accepted end-to-end workflow.
A UI preview alone does not satisfy the release criteria.

## Repository touchpoints

These are inspected areas, not a requirement to place every new module in an existing file.

| Area | Existing locations | Planned change |
| --- | --- | --- |
| Navigation and project entry | `controller/web/src/modules/navigation/routes.ts`, `controller/web/src/pages/JobsProjectPage.tsx`, `controller/web/src/modules/panels/ProjectPanel.tsx` | Dedicated project layout and routes |
| UI data contract | `controller/web/src/modules/controller/api.ts`, `types.ts`, `state.ts` | Typed experiment, plan, execution, and purpose records |
| Catalog and HTTP | `controller/experiments.py`, `controller/http.py` | Separate mutable experiments from fixed launch entries |
| Dispatch and registry | `controller/dispatch.py`, `controller/registry.py` | Reviewed dispatch, mode compatibility, durable execution links |
| Monitoring | `controller/web/src/pages/JobsMonitorPage.tsx`, `controller/snapshot.py`, `controller/telemetry.py` | Purpose and execution identity without conflating state |
| Ledger and scaffold | `lib/campaign.py`, `lib/scaffold.py`, `templates/scaffold/` | Preserve the writer contract and support declared execution modes |
| Setup | `skills/connect/SKILL.md`, `templates/CLAUDE.md.template`, `scripts/hpc-scaffold` | Connection declarations and ownership-preserving setup |
| Scientific adapters | The attached project's `harness/`, `tlaibench/`, `slurm/`, and `unityHPC/fetch.sh` | Scoped operations, provenance, fetch, and safe aggregation |

The scientific adapters live in a separate project directory.
Changes there require their own review and compatibility checks when implementation starts.
Before implementation starts, inspect and preserve existing uncommitted controller work.

## Compatibility and migration

The accepted design conflicts with [design decisions](../design-decisions.md) sections 3.4, 3.9, and 3.10.
They define five primitives, exclude sequenced work, and preserve `ml` as a CLI primitive.
Implementation must revise these decisions and the glossary explicitly.
[ADR 0001](../adr/0001-two-component-split.md) still applies: the controller owns cluster access and the plugin remains thin.

| Existing value or behavior | Target treatment |
| --- | --- |
| `ml` primitive | Compatibility mapping to `multi-gpu` with coordinated ranks; ML application stored separately |
| `multi-gpu` primitive | Independent-experiments mode unless an explicit new mode says otherwise |
| Existing `gpu` attachment | Keep valid; change this project's default only through the planned migration |
| Historical configuration | Preserve original values and show mapped interpretation where useful |
| Fixed experiment catalog | Keep read/launch compatibility while adding saved study definitions |
| Project-owned stage dependencies | Adapt into an explicit plan; preserve ordering and parent links |
| Existing job without purpose | Unclassified; never infer Smoke test from its name |

Before changing runtime defaults, produce a migration preview with old and new values.
Define legacy CLI acceptance, template selection, and downgrade behavior in Phase 0.
Schema migration and runtime activation are distinct steps.
A rollback must preserve new execution history and avoid interpreting coordinated work as independent fan-out.
Exact rollback support depends on the selected store and schema versions.

## Validation and rollout

Use deterministic fixtures and a fake dispatcher for most plan, restart, and failure-path checks.
Use the project's existing mock runner for a small end-to-end path.
Run the relevant controller API, dispatch, catalog, scaffold, and frontend checks after implementation changes.
Add tests for invariants and failure recovery rather than mirroring UI component structure.

A later live pilot uses a reviewed, bounded cluster smoke test, followed by a small real experiment.
Neither is part of this planning session.
The pilot must include resource limits and output locations in its reviewed plan.
When the backend guarantees pass the phase checks, enable the corresponding project write actions.
Keep legacy read and launch behavior available during staged rollout.

## Later product reviews

| Area | Unsettled scope |
| --- | --- |
| Runs and queue | Pending edits, replacement, cancellation scope, scheduling, and the meaning of schedule reassignment |
| Results | Comparison layout, plot interaction, sample browsing, uncertainty, and corpus prominence |
| Files | Browsing details, remote availability, editing, save conflicts, and code push |
| Settings | Connection maintenance, defaults, compatibility migration, and capability management |
| Dynamic composition | Adding and connecting declared operations beyond predefined workflows |

These reviews do not block finalizing the Experiments baseline.
They do block treating their sketches as complete build specifications.
