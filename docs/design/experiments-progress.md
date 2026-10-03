# Experiments implementation progress

Updated 2026-10-03. Phases 0–5 are implemented and verified with deterministic fixtures and project mock runners.
Real model collection requires the project runtime lock described below.

## Workspace preservation

Implementation used the existing checkout because the feature depends on its uncommitted controller and catalog changes.
No attached worktrees existed at intake. The checkout contained 95 modified or untracked files.
Their contents, hashes, and tracked patch remain in `[temporary local artifact]`.
The task-specific patch is `implementation.patch` in that directory. Its file list is `implementation-files.json`.
It excludes pre-existing edits and the concurrently updated workspace design drawing.

The attached project's baseline remains in `[temporary local artifact]`.
Existing scientific folders, environment files, data, and custom sync/fetch scripts remain in place.
All implementation changes remain uncommitted for review alongside the existing work.

## Completed phases

| Phase | Delivered behavior |
| --- | --- |
| 0: Contracts | Versioned connection and store, HTTP contract, source/input identities, dependency model, migration preview, ownership and rollback decisions |
| 1: Connection | Typed declarations, deterministic model choices, structured errors, bounded checks, project adapters, ownership-preserving setup |
| 2: Workspace | Dedicated project routes/sidebar, Home, Overview question, library, typed editor, autosave/conflicts, clone/revisions, archive/restore |
| 3: Review | Exact combinations/exclusions, prerequisites, per-stage resources, measurements, source snapshots, allocation scripts, custom scripts, prior-execution differences |
| 4: Execution | Durable approval and intent, idempotency, partial outcomes, ledger reconciliation, restart continuation, reviewed retry/resume, filtered Runs, Purpose labels |
| 5: Evidence | Scoped retrieval, completeness checks, indexed artifacts, compatible saved-input analysis, preserved report revisions, token-cap separation |

Contracts are recorded in [ADR 0008](../adr/0008-project-workspace-and-approved-executions.md) and [contract v1](workspace-contract-v1.md).
The [adapter record](experiments-project-adapter-progress.md) describes the scientific project changes and migration preview.

## Execution guarantees checked

The fake dispatcher preserves accepted jobs when later submissions fail or become uncertain.
Restart reconciliation does not resubmit accepted work. Missing receipts do not prove rejection.
A failed Smoke test pauses its own dependents while another independent branch continues.
Reviewed recovery includes affected waiting descendants and preserves prior attempt identities.

Controller-host work uses durable receipts and process locks, with no scheduler job IDs.
Restart consumes completed receipts, retains running work, or fences an interrupted attempt before recovery.
Timeouts terminate the process group. Retries remain explicit.

Review retains dirty source bytes, input file hashes, effective resources, and generated scripts.
Changed source invalidates new approval. Already approved stages use frozen scientific source and a frozen dispatcher.
That dispatcher writes the original project ledger through the existing writer.
Coordinated rank counts appear in the actual scheduler allocation.

Artifact checks reject changed files and unindexed additions to selected directories.
A failed scheduler job can retain complete scientific evidence without releasing its dependents automatically.
Retrieval failure remains separate from scheduler completion and corpus completeness.

The actual project mock runner exercised two models and two token caps through frozen wrappers.
Separate analysis conditions preserve both token caps before deduplication.
Interrupted mock resume preserves checkpoint bytes, uses fresh outputs, and continues the reviewed analysis.
Reanalysis creates another report without repeating collection or replacing its predecessor.

## Validation

| Check | Result |
| --- | --- |
| Complete plugin Python suite | 875 passed, 20 skipped |
| Final API, project mock, and transport checks after input-path refinement | 13 passed |
| Final execution and local-receipt checks | 17 passed |
| Final API checks, including source-change differences and dependent custom scripts | 6 passed |
| UI build and ESLint | Passed |
| UI structural and real-browser checks | 36 passed |
| Legacy project-controls browser check | Passed |
| Scientific project adapter, harness, and report checks | 107 passed |
| Python compilation and Git whitespace check | Passed |

These commands overlap, so their counts are not additive.
The normal Python suite skips opt-in browser cases. The separate browser checks ran against isolated deterministic HTTP fixtures.
The project integration tests copy its source into temporary directories and reject any cluster transport attempt.
No real cluster workload, live artifact transfer, or model-weight download ran for verification.

## Compatibility and migrations

The `/workspace` API remains separate from the fixed experiment catalog and generic run API.
The connection exposes a migration preview before workspace dispatch.
The research project declares `multi-gpu/independent` and application `ml`. Existing `gpu` attachment values remain valid.
Legacy `ml` maps explicitly to coordinated execution. Its CLI spelling remains supported.
Campaigns, groups, job IDs, and historical primitive values are unchanged.
Historical jobs without explicit purpose remain Unclassified.

The scaffold supports reviewed template selection, original-project ledger routing, explicit rank allocation, and public environment inspection.
Custom sync/fetch adapters and existing environment files survive setup updates.
The controller store and project `.unity-workspace` directories form one backup unit.
Archive and unused-draft deletion do not remove artifacts or alter active jobs.

## Activation prerequisite and capability gaps

Real collection is blocked until the approved GPU environment supplies its exact package lock.
The current local environment lacks vLLM and cannot supply that evidence.
The two example models have immutable model revisions. Additional model selections require corresponding lock records.
The connection reports these conditions through readiness errors.

The project has no reusable plotting entrypoint. The connection exposes this gap and provides available report links.
Online original-corpus benchmarks require immutable dataset declarations before workspace collection.
These project capabilities do not affect the verified mock workflow or saved-artifact report revisions.

Detailed queue reassignment, scheduling, broader Results/Files/Settings interfaces, and unrestricted workflow composition remain outside this delivery.
The provisional designs from the other session remain separate future work.
