# Settings, Overview, and composition implementation record

Date: 2026-10-03. Owner: maintenance subagent in the central implementation session.
This record supplements the manager's requirement matrix. It does not replace the Experiments agent's records.

## Ownership and interfaces

The subagent owns these new modules:

- `controller/workspace_settings.py` and `workspace_settings_http.py`
- `controller/workspace_overview.py`
- `controller/workspace_composition.py`
- `controller/web/src/modules/workspace/SettingsPage.tsx`, `OverviewPage.tsx`, and `CompositionEditor.tsx`
- `tests/test_workspace_settings.py`, `test_workspace_overview.py`, and `test_workspace_composition.py`

The manager assigned `workspace_connection.py` and `workspace_planner.py` to this subagent for composition integration.
The manager retains `workspace.py`, the shared store, shared HTTP routing, application routes, and `ExperimentEditor.tsx`.
The execution agent owns the worker and schedule guards. The artifacts agent owns immutable evidence reference validation.

Settings uses additive records in the existing workspace store. There is no second database schema.
`maintenance_blocked(slug)` reports actions that block dispatch and worker advancement.
`materialize_defaults(manifest, draft)` freezes future draft resource values and their origins.
The manager calls this helper when creating a draft.

The route adapter returns an HTTP response or `None`. Its routes include Settings, connection checks, maintenance, defaults adoption, and Overview metadata.
Research writes require an expected version. Pins and notes use the artifacts service's immutable reference validator.
A note can omit evidence. Pin updates retain the previous reference in history.

Composition requires `required_features.composition=1` in the project declaration.
The existing experiment uses `workflow=__composition__` and a `graph` containing ordered nodes and explicit edges.
Nodes retain exact operation versions, purpose, scope, parameters, and resources.
Edges identify a node output, an indexed artifact, or explicit permitted absence.
The strict validator lowers this graph into the existing plan compiler and durable worker.
Predefined workflows retain their prior declaration semantics.

## Implemented behavior and checked evidence

| Acceptance | Implementation and evidence | State |
| --- | --- | --- |
| Settings 1, 9 | Exact declaration bytes, registry fingerprint, and expected settings version prevent conflicting applies. External edit fixture preserves unknown fields. | Verified in service tests |
| Settings 2 | New drafts materialize defaults. Maintenance freezes older drafts before changing defaults. Approved plans retain their original snapshots. | Verified with old-draft fixture and baseline snapshot checks |
| Settings 3, 5 | Semantic migration preserves registry primitive, ledger IDs, custom adapter bytes, disabled Sync, and project science. | Verified in migration and preservation fixtures |
| Settings 4 | Connection facts have separate statuses, deadlines, sources, and times. Local pages do not run SSH. | Verified with failed authentication and timeout probes |
| Settings 6 | Quiescence includes workspace stages, schedules, management operations, transfers, and legacy ledger jobs. Relocation checks target history and artifact bytes. | Verified with active and legacy fixtures; transfer guard inspected |
| Settings 7 | Journal records backup, draft freeze, declaration, registry, and metadata steps. Reconciliation resumes the same action. | Fault injection passed after every step |
| Settings 8 | Unknown required features block planning. Unknown store versions retain Settings reads and block writes. | Verified with unsupported store and feature fixtures |
| Settings 10 | Backup digests and readback precede activation. Rollback rejects post-migration records and preserves them. | Verified with restore and newer-record fixtures |
| Overview 1, 2 | Research editor, real zero counts, purpose-preserving attention, and exact entity links. | Service fixtures passed; browser gate owned by manager |
| Overview 3 | Scheduler observations retain their own times. Local research metadata stays readable. | Implemented; mixed-freshness browser gate remains |
| Overview 4, 9 | Saved text, intentionally cleared questions, and manifest origin survive later declaration changes. Concurrent writes return conflicts. | Verified in context fixtures |
| Overview 5 | Notes and pins store immutable evidence revisions; updates retain history. | Immutable pin and cross-page currency fixture passed |
| Overview 6 | Failed stages remain blockers even when their artifacts are complete. | Verified in failed-complete fixture |
| Overview 7 | Failed artifact metadata reads do not discard research text or Runs counts. Failed counts return unavailable, never zero. | Verified in partial-read fixture |
| Overview 8 | Native links, buttons, labels, cards, and responsive grids support keyboard and narrow layouts. | Implemented; browser gate owned by manager |
| Composition 1, 2 | Typed cards lower into the existing compiler. The real project CPU mock executes four variants with both caps. | Fixture and copied-project tests passed |
| Composition 3, 4, 5 | Scope, exact version, typed port, unit, cycle, purpose, and completeness validation precedes snapshot creation. | Version, cycle, unit, scope, and purpose fixtures passed |
| Composition 6, 7 | Reduction expands exact producer variants once. Inputs and expansion have fixed upper limits. | Four-input reducer and limit tests passed |
| Composition 8 | Literal argument bindings use the baseline wrapper compiler. | Literal metacharacter fixture passed |
| Composition 9 | Collector metrics require explicit collector nodes. Saved artifact inputs use immutable copies. | Collector rejection and exact saved-input fixtures passed |
| Composition 10 | Missing operations retain saved graph nodes and block a new plan. | Implemented and version fixture passed |
| Composition 11, 12, 13 | Composition uses existing worker receipts, bounded local stages, isolated output directories, and dependency rules. | Baseline restart tests are the shared gate; composition execution fixture passed |
| Composition 14 | Ordered cards, accessible dependency links, duplication, removal review, scope, purpose, and bindings edit the same graph. | Implemented; browser gate owned by manager |

## Spikes

T7 uses a durable journal, project lock, checked backup, atomic replacement, and resumable steps.
Activation faults cover all five steps. Rollback faults cover all three restore steps. Each resumed action completes once.
Rollback preserves post-migration records by rejecting an unsafe restore.

Its durable journal fences work before any restore write.
Alias and remote-root changes require fresh successful probes of the proposed connection before preview and activation.
No fixture contacts a live host.

T8 uses explicit required-feature negotiation. Unsupported features block predefined and composed planning without changing older declarations.
The composition fixtures retain the original four-variant preset meaning.

T9 uses the baseline durable local supervisor and project serialization.
`tests/test_workspace_local.py` covers restart receipts, delayed supervisor fencing, retained child locks, and timeout cleanup.
Composition accepts isolated output writes. Undeclared shared summary writes fail validation.

## Attached project preservation

The subagent read the attached project's instructions and domain records before editing its declaration.
The only subagent write there is additive typed operation metadata in `unityHPC/project.json`.
The artifact agent released that file before this edit.
Scientific entrypoints, datasets, existing outputs, and custom adapters remain untouched by this subagent.
The pre-edit declaration backup is `[temporary local artifact]`.

The copied-project gate uses the existing bounded CPU mock operation and a temporary controller registry.
It verifies four distinct variant IDs, both token caps, exact purpose, complete artifacts, and controller-only stages.
It compares preset and composed source digests, effective parameters, resources, and stage identities.
It never submits a cluster job.

## Check commands and latest results

- `python -m pytest -q tests/test_workspace_settings.py tests/test_workspace_overview.py`: 24 passed.
- `python -m pytest -q tests/test_workspace_composition.py`: 16 passed.
- Combined Settings, Overview, composition, planner, local worker, and real project mock checks: 66 passed before the final guard fixtures.
- Latest Settings, Overview, composition, and planner check: 63 passed.
- `python -m pytest -q tests/test_workspace_project_mock.py`: 2 passed.
- `npm run typecheck` and `npm run lint`: passed after resource, parameter, saved-input, connection-edit, and pin-update controls.

No production controller data, cluster workload, deployment, push, or commit changed.
The manager runs the integrated browser checks and resolves the remaining acceptance evidence.

## Independent review of artifacts

The review found four issues and sent them to the artifacts owner:

1. Paired deltas need matching metric definitions and units, in addition to scientific provenance.
2. Sample pagination must advance beyond the resumed JSONL member.
3. Missing join fields and malformed records must prevent unsupported paired claims.
4. Report currency needs its own projection and filters for Overview links.

The artifacts owner fixed all four findings. A second source review found the requested guards and shared currency projection.
The artifacts owner reports 26 passing service tests. Overview also tests the same currency change without rewriting an existing pin.


## Final integration notes

The composition editor supports per-node typed parameters, resources, location, and many-input selection.
The compiler preserves every selected saved artifact in the input port binding.
Drafts retain a defaults snapshot so later added graph nodes do not inherit a changed project default silently.

Backup evidence covers the full local `.unity-workspace` and `.unity_state` trees, plus declaration, registry, and workspace records.
Backup copies use temporary trees and compare every copied file before activation.
A restarted copy cannot turn an incomplete directory into a verified backup.

The remaining checks are the manager's integrated browser gates and any separately approved live connection pilot.
The first manifest fallback becomes durable on a research Save or explicit connection check.
The manager retains the decision about attachment-time caching before the first Save.
Remote scheduler permissions remain outside this subagent's implementation and verification scope.
No live probe or workload action ran during these checks.


The missing-directory relocation fixture checks a copied target against retained declaration and plan digests.
It also checks artifact bytes and known execution ledger identities before changing the registration.
The former source directory can remain unavailable. A rollback to that missing directory requires its explicit recovery first.

Independent composition review found two blocking gaps. Both now have regression fixtures.
Purpose restrictions apply after node parameter overrides. Reducer port limits sum all producer variants and selected saved artifacts.
The editor's resource defaults follow the effective node location.
Choice readers also enforce a 2 MiB output limit and clean up their process groups.

## Files preview integration

`FilePreview.tsx` provides bounded JSON trees, JSONL byte locators, CSV tables, safe Markdown, PNG previews, and escaped source lines.
Source controls support line wrapping and search within the loaded page.
Markdown never parses embedded HTML or loads remote images.
The artifacts owner integrated this component and supplies the checked PNG bytes and dimensions.

`tests/test_workspace_preview_browser.py` checks actual Files routes against an isolated local controller.
Both browser tests passed against `[temporary local artifact]` with Chrome.
The fixtures cover JSON, invalid JSON, JSONL, CSV text preservation, Markdown, PNG, and hostile HTML.
They also cover bounded paging, exact-version URL restoration, absolute controller paths, keyboard controls, and narrow layouts.
DOM and resource checks confirm that hostile source creates no executable script or remote image request.
The subagent inspected `[temporary local artifact]` and `[temporary local artifact]` after the checks.
No live cluster access was used.

## Conflict response contract

HTTP 409 responses include `current_version`; version conflicts also return the supplied `expected_version` when known.
Draft, context, note, pin, defaults, and maintenance guards report their actual entity version.
State conflicts without a meaningful version return null instead of inventing a token.
Schema versions are never used as entity versions.
The execution and artifacts owners added the same metadata at their version checks.
All seven new API fixtures plus Settings, Overview, and existing API checks passed: 37 tests.
The new fixtures preserve saved values and pending request text, and reject stale reviewed dispatch without creating an execution.
Schedule and management conflicts report the frozen plan, schedule, or execution token that failed its comparison.
Workspace errors also receive passive response metadata. Its local read time does not claim fresh scheduler or source observations.
