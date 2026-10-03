# Remaining workspace delivery plan

Version 1, 2026-10-03. Agent-selected implementation sequence. Research and design only in this session.

The [shared specification and index](remaining-workspace-spec.md) defines the final remaining scope.
The accepted [Experiments build plan](experiments-build-plan.md) remains a separate delivery owned by the concurrent implementation effort.
This plan names its phases E0–E5 to distinguish them from the remaining phases W0–W6 below.
No phase below authorizes application changes or cluster actions during this planning session.

## Delivery objective and boundaries

A human can move from a research question to a declared experiment, observe its exact work, and inspect comparable evidence.
Failures expose their scope and preserve successful work. Recovery, additional collection, and queue changes require explicit review.
Runtime coordination uses deterministic project operations, with no orchestration LLM.
Scientific source, runners, tests, analyses, and plotting code remain project-owned.

Deliver a read-capable workspace before advanced scheduler controls. Enable each write action only after its backend scope and recovery guarantees pass.
Keep legacy job history and fixed-catalog behavior accessible during migration.
No tracker vendor, new scheduler, unrestricted graph engine, or in-browser scientific editor is required.

## Dependencies on accepted Experiments

| Accepted phase | Required output | Remaining work that consumes it |
| --- | --- | --- |
| E0: contracts and migration | Stable IDs, store, source/output ownership, primitive/mode mapping, capability schema | All remaining APIs, state projections, Settings compatibility |
| E1: connection and project adapters | Declared operations, schemas, checks, selected-output retrieval, scientific identity rules | Files, Results, composition, recovery checks |
| E2: layout and drafts | Project sidebar, Overview route, draft versioning, archive and history links | Overview refinements and all page routes |
| E3: deterministic planning and review | Frozen plan, exact variant/stage expansion, resource snapshots, script review | Recovery, pending-change provenance, analysis, composition, schedules |
| E4: durable execution | Idempotent dispatch, ledger reconciliation, purpose, stage continuation, restart behavior | Runs, cancellation fences, operational summaries, one-off schedules |
| E5: artifact and analysis baseline | Scoped artifact identities, completeness evidence, analysis revisions, cap-preserving aggregation | Full Results, Files retrieval UX, evidence pins, selected-artifact composition |

ADR 0008 already pins the route prefix, SQLite workspace store, and bundle paths in the working tree.
Reuse those choices. Confirm them against the completed implementation before splitting tickets.
If E4/E5 already implement scoped fetch, recovery, or analysis services, extend those services.
Extend the same service with remaining-page contracts and acceptance cases.

## Phase W0: contract reconciliation and fixtures

Start while E0–E3 are available. Read the concurrent branch without changing its files during this design session.
For implementation, assign one owner to shared workspace schema and one owner to each page/API slice.

Pin the shared response envelopes, capability descriptor, observation timestamps, action receipts, and expected-version rules.
Map existing storage enums to the shared display dimensions. Preserve raw scheduler states and reasons.
Define exact scheduler identity with cluster, campaign, submission time, parent, and task ID.
Define immutable artifact versions, location copies, content integrity, completeness evidence, and analysis freshness separately.

Build a fixture set from sanitized project records and synthetic scheduler observations:

- Original-corpus and TLAiBench records, including historical missing provenance and effective-versus-requested token caps.
- Four variants, a shared prerequisite, a failed smoke gate, a valid negative outcome, and a complete corpus behind a failed scheduler exit.
- Partial submission, uncertain acceptance, array siblings, scheduler restarts, and mixed pending/running group members.
- Remote-only outputs, partial retrieval, changed bytes at the same path, stale summaries, missing optional turn details, and corrupt records.
- Legacy primitive mappings, external declaration edits, unsupported schema versions, interrupted maintenance, and backup restoration.

Gate: publish the concrete schema mapping and run semantic fixture checks before any consumer writes a second incompatible model.
An unknown compatibility case blocks only the affected capability, with the fallback defined in the spike register.

## Phase W1: observation, Files reads, and Overview

Dependencies: E0, E2, E4 read projections, and W0 identity and freshness contracts.

Build Runs Executions and Queue views, stage/attempt detail, purpose filters, dependency list/diagram, and raw/effective resource history.
Add bounded log reads, rotation markers, exact attempt paths, and unavailable-stream fallback to retrieved files.
Support legacy Unclassified jobs without creating fake experiment or execution links.

Build Files directory and artifact views, bounded safe previews, and links to producer attempts and immutable source snapshots.
Use indexed metadata for known remote files. Browsing must not crawl remote roots or invoke fetch hooks.
Add independent loading/error states and capability explanations for unavailable writes.

Refine Overview with the question editor, readiness counts, recent work, and deterministic attention items.
Use metadata projections instead of corpus scans. Every card exposes its scope and source age.
Add read-only Settings sections so missing connection capabilities have an actionable destination.

Gate: mixed-freshness pages, no-result filters, unavailable remote files, missing logs, keyboard navigation, and direct history links work.
Observing and browsing cause no dispatch, mutation, retrieval, repair, or scientific checks.

## Phase W2: evidence retrieval and complete Results

Dependencies: E1 and E5 artifact contracts, plus W1 navigation and read surfaces.

Integrate exact artifact retrieval with progress and per-item receipts. Keep legacy broad fetch visibly separate.
Add integrity verification, copy availability, artifact completeness, and stale-analysis detection.
Preserve prior bytes when a remote path changes. Never update a saved comparison by mutating its input artifact version.

Build Results Reports, Plots, Compare, and Samples & traces.
Keep original corpus and TLAiBench separate. Preserve First numbers and declared measurement limitations.
Support baseline selection, configuration differences, matched and unmatched counts, exclusions, and declared metric definitions.
Disable numerical deltas for incompatible metric definitions. Preserve side-by-side descriptive evidence with the mismatch explained.

Use bounded indexed sample/turn reads. Link a plot selection to its source records and exact artifact version.
Analysis revision review binds complete selected inputs, source, metric/collector versions, parameters, resources, and fresh outputs.
Missing inputs lead to an explicit collection draft, never an implicit generation rerun.
Add saved comparisons, Overview evidence pins, and human conclusions once those references are stable.

Gate: both token-cap conditions survive analysis. Retries do not double-count samples. Changed bytes cannot alter old evidence.
Partial artifacts remain inspectable, while complete-input requirements for new analysis remain enforced.
Log retrieval success and corpus retrieval failure produce separate outcomes and a scoped retry option.

## Phase W3: cancellation, recovery, and pending changes

Dependencies: E4 recovery/coordination foundation, E5 completeness, W0 receipts, W1 Runs UI.
This phase can proceed alongside W2 after its artifact and completeness contracts settle.

Implement concrete target selection, stop fences for unsent work, fresh action-time checks, and durable operation receipts.
Support exact array-task cancellation only after its adapter proves that sibling jobs remain untouched.
When the adapter lacks exact-scope support, offer only explicit demonstrated group scope with the affected children shown.
Do not retrofit a narrow UI label onto campaign cancellation.

Extend reviewed recovery with retry, declared checkpoint resume, checked-output reuse, and stop-before-replacement.
Use a new plan and execution with fresh outputs and original attempt lineage.
Preserve completed evidence and source failure. Reconcile cancellation or submission uncertainty before replacement dispatch.

Add pending changes only for demonstrated fields and scheduler states.
Preserve the original plan and append effective resource-change history.
Use replacement for unsupported changes. Ordinary running walltime increases remain unavailable.
Display a shorter time limit's termination risk without promising an earlier start.

Gate: pending-to-running races fail closed, cancel races cannot release new work, and partial operations keep per-target outcomes.
No unknown scheduler outcome, reused idempotency key, or controller restart creates duplicate work.

## Phase W4: Settings maintenance and migration

Dependencies: E0 compatibility, W0 action contracts, W1 connection facts, and active/scheduled/uncertain-work inventory.

Add explicit default updates and per-draft adoption previews. Defaults retain their origin and materialize into new drafts.
Add connection reload, reviewed activation, protected-file checks, migration journal, and backup/restore evidence.
Relocation and detach require quiescence. They preserve history, artifact identity, and original remote provenance.
Unknown schemas block unsafe writes and retain compatible historical reads.

Gate: external changes produce recoverable conflicts. Interrupted activation reconciles. Rollback preserves post-migration records.
Custom adapters, source, environments, and already dispatched work retain their bytes or effective snapshots.
Missing migration support leaves a usable read-only compatibility view with a concrete exported maintenance plan.

## Phase W5: declared dynamic composition

Dependencies: complete E0–E5, W0 schema negotiation, W2 artifact selection, W4 capability inspection.

Add versioned typed input/output ports, cardinalities, purpose rules, scope, and explicit compatibility declarations.
Reuse the accepted experiment draft, plan compiler, Measurements page, review, and execution coordinator.
Add ordered stage cards with an operation picker and read-only dependency diagram.
Support per-variant, shared, and selected-input reduction stages with bounded expansion.
New collectors expose additional stages and costs before review. Scientific formulas remain project code.

Gate: a composed equivalent of the accepted four-variant workflow has the same scientific identities, inputs, and effective resources.
Reject cycles, unbound ports, invalid scope, incompatible schema, unapproved collectors, and undeclared shared writes before dispatch.
Restart and output-isolation fixtures must pass through the same coordinator as preset workflows.

## Phase W6: one-off future scheduling

Dependencies: E3/E4 immutable approval and durable dispatch, W3 action reconciliation, W4 maintenance guards.
W5 composition is not a prerequisite. Schedules can first apply to accepted predefined workflows.

Add Schedule this plan as a separate full-review action. Initial Dispatch retains its accepted immediate behavior.
Store UTC instants, the selected timezone, an earliest dispatch, and an explicit latest dispatch.
Use a one-hour default window. The review allows a different window and states that cluster start remains unreserved.

Use durable due-worker ownership and the plan's dispatch idempotency key.
Changed identities/capabilities block dispatch. Missed windows require review. No automatic catch-up occurs.
Due checks also compare current draft, declaration, source, and input digests under the accepted dispatch-invalidation rules.
Changed values require a fresh reviewed plan, even when the earlier source bundle still exists.

Gate: controller downtime, DST ambiguity, duplicate workers, changed inputs, cancellation races, and uncertain submission never create duplicate or unapproved work.
Schedules remain distinct from global telemetry retrieval schedules and scheduler Eligible after controls.

## Technical spike register

These engineering questions have bounded scope, not unresolved product preferences.
Use documented fallback behavior until each completion gate passes.

| ID | Question | Recommended approach | Fallback | Completion gate |
| --- | --- | --- | --- | --- |
| T1 | Which Unity mutations have safe state/scope semantics? | Versioned scheduler adapter, read-only site capability survey, and isolated race fixtures | Disable the field; offer reviewed replacement | Publish field/state/scope matrix and prove pending-to-running races cannot broaden effects |
| T2 | Can cancellation target exact array children? | Resolve task identity through a tested management adapter and observe actual termination | Explicit parent-group scope only | No sibling cancellation across pending, split, running, and terminal arrays |
| T3 | Can project retrieval select exact artifact versions? | Extend project-owned adapter with explicit manifest, temporary transfer, digest verification, and atomic installation | Explicit broad-hook review, then index only checked selected evidence | Partial transfer, changed remote bytes, symlink escape, and restart fixtures pass |
| T4 | Which resume inputs preserve scientific meaning? | Project-owned compatibility validator and copy-to-new-output checkpoints | Retry from immutable original inputs | Incompatible source/parameters, active writer, and truncated checkpoint fail closed |
| T5 | Can reports analyze selected conditions without global deduplication? | Immutable artifact-selection manifest passed to a project adapter | Isolated checked temporary input tree | Different effective caps, repeated records, parent links, and exclusions survive correctly |
| T6 | How can large corpora serve bounded sample reads? | Derived rebuildable index keyed by immutable artifact version, record locator, and schema | Paginated bounded file scans with explicit limits | Large, malformed, changed, and partially available artifacts do not freeze UI or mix versions |
| T7 | How does maintenance span files and SQLite safely? | Durable step journal, project lock, checked backup, atomic replacement, and reconciliation | Read-only Settings plus exported operator maintenance plan | Fault injection after each step preserves all historical records and protected files |
| T8 | How does schema v1 gain typed composition ports? | Required feature negotiation plus strict versioned validator | Preset workflows remain available; composition reports Unsupported | Existing declarations retain meaning; unknown required features cannot execute |
| T9 | How are local stages bounded across restart? | Durable lease, process-group deadline, isolated outputs, and declared exclusive resources | Serialize local stages per project | Crashes and concurrent writers cannot duplicate work or corrupt shared summaries |
| T10 | How are log cursors and external requeues identified? | Attempt paths, scheduler restart segments, byte cursors, and rotation boundaries | Retrieve then preview locally; mark attribution Unknown | Large/rotated/binary logs and reused job IDs cannot merge histories |

## Contract ownership and likely implementation seams

| Boundary | Responsibility | Existing touchpoints, not mandatory module destinations |
| --- | --- | --- |
| Workspace domain service | IDs, immutable plans, versions, action records, analysis and maintenance lineage | ADR 0008 workspace store and emerging workspace modules |
| Read projections | Page summaries, scoped pagination, freshness, dependency projections | `controller/snapshot.py`, workspace API, frontend controller data modules |
| Scheduler management | Exact cancellation, safe mutations, reconciliation, logs | `controller/dispatch.py`, project dispatcher, `lib/campaign.py` |
| Artifact service | Safe paths, copies, transfers, content versions, derived indexes | Existing fetch boundary and project-owned adapters |
| Result adapters | Sample identity, effective parameters, outcomes, completeness, reports | Attached project's `harness/`, `tlaibench/`, tests, and analysis code |
| Frontend workspace | Shared navigation, page-local views, action reviews, evidence links | `controller/web/src/modules/workspace/` and shared UI components |
| Connection maintenance | Capabilities, protected ownership, schema compatibility, migration journal | `controller/workspace_connection.py`, registry, workspace store |

Implementation tickets must name the contract they extend, the dependency phase, fixture evidence, and action scope.
Backend and frontend can progress separately against the same fixtures. A mocked UI is not evidence that scheduler or artifact semantics work.
The attached scientific project is a separate ownership boundary. Its adapter changes require their own review and tests during implementation.

## Release verification matrix

| Scenario | Pages crossed | Required evidence |
| --- | --- | --- |
| Accepted four variants | Overview → Experiments → Runs → Results → Files | Four variant identities, both caps preserved, exact source/report links |
| Smoke gate fails | Runs → Overview → Results | Purpose retained, only dependents paused, test evidence excluded from research aggregates |
| Acceptance reply lost | Review → Runs → recovery | One durable intent, uncertain state, no duplicate submission |
| Scheduler success with incomplete data | Runs → Results → Files | Separate success/completeness states and no invalid downstream input |
| Failed parent with complete corpus | Runs → Results → recovery | Original failure preserved; explicit checked-output recovery creates new lineage |
| Partial fetch and changed bytes | Files → Results → Overview | Per-item receipt, retained old artifact version, old pin remains stable |
| Reanalysis without generation | Results → Runs → Reports | Exact complete input set, new analysis/output identities, no collection job |
| Pending edit races start | Queue → review → History | Capability check, conflict or uncertainty, no unsupported running mutation |
| Cancel one fan-out child | Runs → queue → logs | No sibling changes, exact stop fence and observed termination |
| Defaults and source change | Settings/Files → Experiments → Runs | New review required; queued execution retains its prior snapshot |
| Interrupted migration | Settings → all history pages | Reconciled journal, preserved protected files, resolvable prior evidence |
| Composed graph | Experiments → Runs → Results | Same baseline identities, typed edges, finite expansion, isolated outputs |
| Missed or duplicate schedule | Schedules → Runs | No late dispatch, no duplicate intent, explicit re-review |
| Offline or stale data | All six pages | Independent source ages, preserved edits, no false zeroes or enabled unsafe actions |

Use deterministic fixtures, temporary stores, and fake dispatchers for these checks.
Add browser tests for navigation, keyboard access, URL restoration, and narrow layouts.
Use bounded representative corpora to measure index and preview performance. Avoid whole-file browser downloads.
A later live pilot requires a separately reviewed small cluster plan and verified site capability checks.
No live job or configuration change is necessary to finish this planning package.

## Deferred scope

Defer recurring scientific schedules, automatic recovery budgets, queue reassignment policies, and cross-cluster migration.
Defer browser source editing, arbitrary code push, generic synchronization, destructive file management, and credential storage in project metadata.
Defer arbitrary metric expressions, inferred statistical significance, runtime graph invention, and cross-project joins.
Defer automatic scientific conclusions and unrestricted graph-canvas authoring.
These limits do not leave the specified page workflows incomplete.

## Design verification and handoff

The [verification record](remaining-workspace-verification.md) records document, board, export, and preservation checks for this session.
It distinguishes checks of the planning artifacts from tests still required during implementation.
The six page specifications and the shared contract resolve routine product choices. Only the bounded backend and adapter gates remain.
