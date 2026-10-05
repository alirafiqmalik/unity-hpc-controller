# Remaining workspace implementation progress

Date: 2026-10-03. Manager: current implementation session. The user authorized local fixtures only.

## Intake and preservation

The current checkout contains the completed Experiments delivery and unrelated pending work.
The prior implementation chat is idle. Its E0–E5 record claims fixture verification; this session rechecks those claims.
The intake snapshot contains 155 modified or untracked files, hashes, and the tracked patch.
Snapshot: `[temporary local artifact]`.

The earlier Experiments and attached-project progress records remain intact.
The intake found one checkout. Separate file ownership permits integration in this checkout without losing prerequisite changes.
The controller on port 8300 is live and remains untouched. Tests use temporary registries, data, outputs, and separate ports.

## Contracts and ownership

The existing SQLite store remains schema version 1. New entities use its generic records table.
The existing dispatcher remains the only job-ledger writer. Existing plan and execution identities retain their meaning.

Shared helpers live in `controller/workspace_contracts.py`.
Explicit integer versions remain optimistic tokens. Legacy records use a digest of their exact content.
Observations carry source, observation time, stale threshold, availability, and freshness. Polling does not change source time.

Previews freeze concrete target IDs, versions, and capabilities. Confirmations revalidate scope and use durable idempotency keys.
Receipts retain target outcomes: accepted, rejected, skipped, or uncertain. Uncertainty never permits automatic resubmission.
Artifact snapshots have immutable content identities and retain their logical producer identity.

| Owner | Exclusive implementation files | Shared integration dependencies |
| --- | --- | --- |
| Manager | workspace.py, workspace_store.py, workspace_http.py, workspace_contracts.py, App routing, Workspace.tsx, api.ts, ExperimentEditor.tsx, ExecutionPages.tsx, integration tests | All slices |
| execution | workspace_runs.py, workspace_actions.py, workspace_schedules.py, workspace_execution_http.py, workspace_worker.py, workspace_local.py, RunsPage.tsx, Schedules.tsx, matching tests | Shared helpers; artifact preservation hook; maintenance guard |
| artifacts | workspace_artifacts.py, workspace_results.py, workspace_artifact_http.py, ArtifactPages.tsx, matching tests; attached project result adapters | Worker indexes immutable snapshots; analysis/download use frozen inputs |
| maintenance | workspace_settings.py, workspace_overview.py, workspace_composition.py, workspace_settings_http.py, workspace_connection.py, workspace_planner.py, SettingsPage.tsx, OverviewPage.tsx, CompositionEditor.tsx, matching tests | Manager materializes defaults; execution observes maintenance guard; immutable evidence references |

Agents must request shared-file ownership changes through the manager. Their reports are handoffs, not acceptance.

## Additive API and state mapping

Every workspace JSON response adds `response_metadata`. Existing resource shapes and optimistic tokens retain their meaning.
Metadata includes a stable content token, source revision, local read time, domain observations, and entity metadata keyed by JSON pointer.
Unknown source revisions remain `unknown`. Artifact schema versions never substitute for artifact content versions.

Read-time projection clocks do not change content tokens. Stored scheduler, artifact, and probe observation times retain their original age.

HTTP 409 includes `current_version`. A known optimistic conflict also includes `expected_version`.
State conflicts without an entity token use null. The service never invents a concurrency token from the store schema version.

| Contract | Stored or raw value | Display or response meaning |
| --- | --- | --- |
| Submission | waiting/submitting/accepted/rejected/uncertain | Separate from scheduler and controller activity |
| Scheduler | Original ledger state and exact cluster/campaign/task/submission reference | Normalized category plus retained raw state and source age |
| Controller operation | Durable process receipt and stage outcome | No scheduler job identity or invented scheduler state |
| Purpose | experiment/smoke-test/absent | Experiment/Smoke test/Unclassified; research queries exclude smoke by default |
| Completeness | Project checker evidence and complete/partial/invalid/unknown | Does not follow exit status or transfer success |
| Integrity | unchecked/checked/changed/mismatch | Separate from scientific completeness |
| Retrieval | queued/running/succeeded/partial/failed/cancelled | Per-member operation outcome; retained old local bytes |
| Analysis | Fresh plan/execution/output with exact selected artifact versions | Independent from preserved report currency |
| Report currency | current/earlier-inputs/input-changed/unknown | Failed new analysis does not hide earlier reports |
| Management | Frozen preview, target IDs, capability token, idempotency key and receipt | Reconciliation precedes another conflicting operation |
| Settings | Declaration digest, registry digest, entity version and journal step | Existing drafts require explicit adoption; active work blocks maintenance |

## Phase ledger

| Phase | Intake state | Current state | Verification / remaining gate |
| --- | --- | --- | --- |
| E0–E5 | Prior implementation and evidence present | Reconciled and checked in combined implementation | Full suite, copied-project mock and attached adapter checks pass |
| W0 | Domain identities present; page/action envelopes absent | Integrated; direct API checks pass | Additive metadata, preserved source ages, entity conflict versions and passive reads |
| W1 | Minimal Runs/Overview; Files/Settings placeholders | Integrated; local checks pass | Six-page navigation, exact logs, safe previews, keyboard, narrow layout, passive reads |
| W2 | Basic artifact index and analysis present | Integrated; local checks pass | Immutable inputs, four-cap analysis, comparisons, samples, strict previews and response-race browser regressions |
| W3 | Reviewed retry/resume present | Integrated; local checks pass | Exact receipts, uncertain-acceptance reconciliation, stop fences, replacement refusal and lineage |
| W4 | Migration preview only | Integrated; local checks pass | Five activation and three rollback fault steps, defaults conflicts, blockers, missing-root relocation |
| W5 | Preset compiler present | Integrated; local checks pass | Copied-project preset equivalence, four variants, composed receipt restart, typed ports and keyboard editor |
| W6 | Absent | Integrated; local checks pass | Frozen windows, DST, duplicate workers, both cancel-race orders, changed selected input and restart |

## Verification policy

Implemented and verified are separate states. Tests use fake schedulers and copied project fixtures.
Each major slice receives a review by another agent before manager acceptance.

The final pass includes API integration, browser navigation, narrow layouts, keyboard access, and the four-variant project mock.
Site-dependent mutation capabilities stay disabled until their precise capability gates pass.
Q1–Q23 remain unchanged. Deferred product features retain the specification boundary.

## Integration status

The complete local implementation is integrated and checked. No independent local implementation item remains open.
Site-dependent validation remains limited by the explicit live gates below.
The final evidence distinguishes the full combined run from subsequent focused contract checks.

## Accepted Experiments reconciliation

The earlier record remains historical. This session rechecked its prerequisites against the combined implementation.

| Baseline | Implementation consumed or extended | Current evidence |
| --- | --- | --- |
| E0 | Existing SQLite identities, records, migration and primitive mapping | Store compatibility, passive history and Settings fault fixtures |
| E1 | Connection declarations, exact adapters and project-owned scientific operations | Planner/connection tests; attached adapter tests; copied-project mock |
| E2 | Library, drafts, revisions, archive, dedicated navigation | Existing browser autosave/conflict/archive tests and real six-page navigation |
| E3 | Frozen source, scripts, resources, four variants and explicit review | Planner/API suites; composed-equivalence test; source-change and frozen-transport regressions |
| E4 | Durable intent, ledger receipts, stop fences and deterministic continuation | Execution/local worker suites; composed receipt restart and cancellation-race checks |
| E5 | Immutable artifacts, completeness and saved-input analysis | Project mock, Results/Files fixtures and complete real-browser evidence flow |

The project now declares its scientific plotting operation and typed composition ports.
The environment lock for real GPU collection remains an external dependency.
Online benchmark collection still requires immutable dataset declarations when the project does not supply them.
No accepted product decision changed.

## Shared acceptance and release scenarios

| Shared requirement | Implementation | Evidence / remaining gate |
| --- | --- | --- |
| W01 navigation and exact links | Workspace routes, Home return state, navigation query contracts | Real browser pages, Projects filter restoration and narrow keyboard checks |
| W02 separate scheduling, pending changes and recovery | Schedules, management previews and reviewed recovery plans | Schedule/action/integration suites; site mutation adapter remains disabled |
| W03 separate state dimensions | Runs projections, immutable artifacts, Results currency, Settings facts | Incomplete scheduler success; failed complete evidence; local analysis has no scheduler state |
| W04 exact scope and receipts | Actions, transfers, schedules, maintenance journals | Array sibling, scope race, partial receipt, uncertainty and duplicate-worker fixtures |
| W05–W06 evidence views and separate collections | Results Reports/Plots/Compare/Samples, frozen field mappings | Four-cap comparison, original/TLAiBench mappings, incompatible metric rejection |
| W07 read-only Files | Bounded local/metadata browsing and escaped previews | Passive API/browser reads, source-version conflicts, traversal and secret exclusions |
| W08 future defaults | Materialized snapshots and explicit draft adoption | Default conflict/adoption test; prior plan unchanged |
| W09 one composition model | Typed graph lowering into existing compiler/worker | Preset/composed equality, four conditions, restart after durable receipt |
| W10 human conclusions | Versioned notes/pins and exact immutable references | Browser note conflict, reanalysis, preserved original pin |
| W11 versions and capabilities | Common response metadata, conflict fields, server guards | Direct API metadata/conflict checks pass; unsupported site actions fail closed |
| W12 deferred boundaries | No recurring scientific scheduler, inferred science, arbitrary expressions or source editor | Design boundary retained |
| Lost acceptance reply | One intent and ledger reconciliation | Execution crash/uncertainty fixtures preserve accepted work without resubmission |
| Partial retrieval and changed bytes | Quarantine, exact member retries and frozen content | Artifact transfer fixtures and old-pin/reanalysis checks |
| Interrupted maintenance | Durable journal, complete backup and guarded rollback | Fault injection, protected-file digests, target history and post-migration record tests |
| Offline/stale/partial pages | Independent read sections and retained form edits | Overview failure browser case, cached-log age, malformed preview and optimistic conflict fixtures |

## Requirement and acceptance register

Rows retain specification order. Ownership includes service, UI, and verification; a source section remains pending until its acceptance evidence exists.

| Requirement | Specification requirement | Owner | Implementation | Verification | Dependency |
| --- | --- | --- | --- | --- | --- |
| RUN-S1 | [Purpose and decisions](runs-spec.md) | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-S2 | [Navigation and layout](runs-spec.md) | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-S3 | [Identity and state contract](runs-spec.md) | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-S4 | [Dependencies and approved continuation](runs-spec.md) | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-S5 | [Action availability](runs-spec.md) | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-S6 | [Pending request changes and walltime](runs-spec.md) | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-S7 | [Cancellation scope](runs-spec.md) | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-S8 | [Retry, resume, and replacement](runs-spec.md) | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-S9 | [Future scheduling](runs-spec.md) | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-S10 | [Logs and observation](runs-spec.md) | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-S11 | [Empty, stale, partial, and failure behavior](runs-spec.md) | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-S12 | [Required data and API extensions](runs-spec.md) | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-S13 | [Verification and acceptance](runs-spec.md) | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-A1 | Dispatch four variants with a shared smoke test. Runs preserves stage counts, purpose labels, exact dependencies, and the execution filter. | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Existing execution fixtures plus Runs projection ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-A2 | Fail one branch. Independent branches advance, dependent stages pause, and the summary shows active work plus attention. | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Existing smoke-gate fixture; new active-plus-attention projection ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-A3 | Return exit zero with incomplete outputs. Runs shows scheduler success beside partial completeness and blocks incompatible consumers. | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | `test_scheduler_success_with_incomplete_outputs_blocks_only_consumers` ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-A4 | Return a complete corpus with a failed job. Only a reviewed recovery plan can use it, with original failure retained. | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Existing artifact checks; manager's `checked-outputs` recovery extension ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-A5 | Timeout after scheduler acceptance. Restart and repeated clicks create no duplicate submission. Missing ledger evidence stays uncertain. | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Existing receipt reconciliation tests ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-A6 | Select one array child. The preview never expands silently. Unsupported exact scope disables the action and explains group scope. | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Unsupported production adapter rejects narrow action ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Fixtures verified; site adapter disabled until live gate |
| RUN-A7 | Cancel during dependency completion. The stop fence prevents any newly eligible dependent submission outside the approved scope. | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Stale worker save cannot clear durable fence ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-A8 | Change a pending job while it starts. The adapter rejects the unsafe mutation or exposes reconciliation, without silently changing running resources. | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Fake adapter rejects conditional update at scheduler boundary ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Fixtures verified; site adapter disabled until live gate |
| RUN-A9 | Reduce walltime. Review shows the exact limit and termination risk, with no promise of an earlier start. | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Review includes termination risk and no earlier-start promise ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-A10 | Fail cancellation during replacement. No replacement dispatch occurs. Fail replacement after cancellation and show that the old job remains stopped. | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | `test_refused_cancellation_never_dispatches_replacement`; `test_failed_replacement_does_not_restart_cancelled_original` ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-A11 | Resume from an incompatible checkpoint. Dispatch stays blocked, while compatible Retry remains separately reviewable. | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Existing explicit resume checks; no automatic resume ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-A12 | Rotate logs between reads. The viewer preserves stream boundaries and never mixes attempts or purpose labels. | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Exact stream cursor detects replacement/truncation; response limit 64 KiB ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-A13 | Close the browser and restart the controller. Approved continuation and one-off schedules retain their durable scope. | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Existing execution receipts and schedule intent reconciliation ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-A14 | Miss a schedule window. State becomes Missed and no late job appears. A new review can dispatch later. | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Window expiry creates no execution ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-A15 | Change an input or attachment before a due schedule. The worker blocks it instead of substituting a new identity. | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Source/declaration/input checks and exact attachment binding ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-A16 | Resolve a DST overlap, two due workers, and a duplicate request. Exactly one approved dispatch intent survives. | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Explicit offset validation, one project lock, dispatch key ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-A17 | Return stale status with a successful command exit. Stale remains visible and mutation preflight requires authoritative observations. | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Stored timestamps age independently; mutation requires authoritative token ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-A18 | Cancel several targets with one refusal. The UI reports per-target outcomes and preserves successful cancellation evidence. | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Per-target refusal and acknowledgement remain distinct ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RUN-S14 | [Delivery phases and technical spikes](runs-spec.md) | execution | Implemented: workspace_runs.py, workspace_actions.py, workspace_schedules.py; RunsPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-execution-progress.md)); `tests/test_workspace_runs.py, test_workspace_actions.py, test_workspace_schedules.py, test_workspace_log_transport.py` | Verified locally; external gates below |
| RESULT-S1 | [Decisions and purpose](results-spec.md) | artifacts | Implemented: workspace_results.py, workspace.py; ArtifactPages.tsx | Focused area suite and integrated browser checks ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_results.py, test_workspace_project_mock.py` | Verified locally; external gates below |
| RESULT-S2 | [Navigation and layout](results-spec.md) | artifacts | Implemented: workspace_results.py, workspace.py; ArtifactPages.tsx | Focused area suite and integrated browser checks ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_results.py, test_workspace_project_mock.py` | Verified locally; external gates below |
| RESULT-S3 | [Reports and analysis revisions](results-spec.md) | artifacts | Implemented: workspace_results.py, workspace.py; ArtifactPages.tsx | Focused area suite and integrated browser checks ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_results.py, test_workspace_project_mock.py` | Verified locally; external gates below |
| RESULT-S4 | [Completeness, provenance, and outcome rules](results-spec.md) | artifacts | Implemented: workspace_results.py, workspace.py; ArtifactPages.tsx | Focused area suite and integrated browser checks ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_results.py, test_workspace_project_mock.py` | Verified locally; external gates below |
| RESULT-S5 | [Plots and metric semantics](results-spec.md) | artifacts | Implemented: workspace_results.py, workspace.py; ArtifactPages.tsx | Focused area suite and integrated browser checks ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_results.py, test_workspace_project_mock.py` | Verified locally; external gates below |
| RESULT-S6 | [Comparisons](results-spec.md) | artifacts | Implemented: workspace_results.py, workspace.py; ArtifactPages.tsx | Focused area suite and integrated browser checks ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_results.py, test_workspace_project_mock.py` | Verified locally; external gates below |
| RESULT-S7 | [Samples and traces](results-spec.md) | artifacts | Implemented: workspace_results.py, workspace.py; ArtifactPages.tsx | Focused area suite and integrated browser checks ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_results.py, test_workspace_project_mock.py` | Verified locally; external gates below |
| RESULT-S8 | [Data and service contracts](results-spec.md) | artifacts | Implemented: workspace_results.py, workspace.py; ArtifactPages.tsx | Focused area suite and integrated browser checks ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_results.py, test_workspace_project_mock.py` | Verified locally; external gates below |
| RESULT-S9 | [Loading and failure behavior](results-spec.md) | artifacts | Implemented: workspace_results.py, workspace.py; ArtifactPages.tsx | Focused area suite and integrated browser checks ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_results.py, test_workspace_project_mock.py` | Verified locally; external gates below |
| RESULT-S10 | [Acceptance and verification scenarios](results-spec.md) | artifacts | Implemented: workspace_results.py, workspace.py; ArtifactPages.tsx | Focused area suite and integrated browser checks ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_results.py, test_workspace_project_mock.py` | Verified locally; external gates below |
| RESULT-A1 | Two models and two effective caps produce four visible conditions after analysis, even when TLAiBench record IDs collide across caps. | artifacts | Implemented: workspace_results.py, workspace.py; ArtifactPages.tsx | Four-condition comparison test and attached project plot fixture ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_results.py, test_workspace_project_mock.py` | Verified locally; external gates below |
| RESULT-A2 | A resumed corpus with zero invocation `done` count can become complete only through its declared expected-item check. | artifacts | Implemented: workspace_results.py, workspace.py; ArtifactPages.tsx | Existing project completeness check uses requested, done, skipped, and unique records ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_results.py, test_workspace_project_mock.py` | Verified locally; external gates below |
| RESULT-A3 | A failed scheduler exit plus a complete corpus shows both facts and links to manual Runs recovery without releasing children. | artifacts | Implemented: workspace_results.py, workspace.py; ArtifactPages.tsx | Existing worker keeps scheduler and completeness facts separate ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_results.py, test_workspace_project_mock.py` | Verified locally; external gates below |
| RESULT-A4 | A metric change over complete saved artifacts creates a new analysis revision and leaves generation untouched. | artifacts | Implemented: workspace_results.py, workspace.py; ArtifactPages.tsx | Existing actual-project mock performs two saved-input analyses ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_results.py, test_workspace_project_mock.py` | Verified locally; external gates below |
| RESULT-A5 | A missing collector field blocks that analysis and identifies the collection requirement before any dispatch. | artifacts | Implemented: workspace_results.py, workspace.py; ArtifactPages.tsx | Existing planner checks declared metrics and collection requirements ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_results.py, test_workspace_project_mock.py` | Verified locally; external gates below |
| RESULT-A6 | A failed analysis preserves its partial outputs and the prior successful report with exact source links. | artifacts | Implemented: workspace_results.py, workspace.py; ArtifactPages.tsx | Isolated output IDs and immutable report copies preserve old evidence ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_results.py, test_workspace_project_mock.py` | Verified locally; external gates below |
| RESULT-A7 | A comparison with different evaluator versions shows values and differences but no unsupported paired delta. | artifacts | Implemented: workspace_results.py, workspace.py; ArtifactPages.tsx | Evaluator and metric-definition mismatch tests ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_results.py, test_workspace_project_mock.py` | Verified locally; external gates below |
| RESULT-A8 | Missing, unmatched, and excluded samples remain counted. Zero is never the default for missing measurement data. | artifacts | Implemented: workspace_results.py, workspace.py; ArtifactPages.tsx | Missing-value and unmatched/ambiguous-join tests ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_results.py, test_workspace_project_mock.py` | Verified locally; external gates below |
| RESULT-A9 | A TLAiBench sample opens its actual parent, turn, phase applicability, effective cap, and recovered-trace marker. | artifacts | Implemented: workspace_results.py, workspace.py; ArtifactPages.tsx | Frozen field mappings expose turns, phases, effective cap, and exact parent scope ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_results.py, test_workspace_project_mock.py` | Verified locally; external gates below |
| RESULT-A10 | A historical `nogit` source and unversioned dataset display unknown provenance and cannot claim reproducibility. | artifacts | Implemented: workspace_results.py, workspace.py; ArtifactPages.tsx | Unknown provenance blocks compatible comparison ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_results.py, test_workspace_project_mock.py` | Verified locally; external gates below |
| RESULT-A11 | A smoke-test artifact appears under Smoke tests and in resource accounting, but never in default research aggregates. | artifacts | Implemented: workspace_results.py, workspace.py; ArtifactPages.tsx | Smoke filtering and analysis guards ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_results.py, test_workspace_project_mock.py` | Verified locally; external gates below |
| RESULT-A12 | Exports reproduce the displayed cohort, metric definitions, and analysis revision from their companion manifest. | artifacts | Implemented: workspace_results.py, workspace.py; ArtifactPages.tsx | Saved plot data and comparison export retain exact cohorts and definitions ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_results.py, test_workspace_project_mock.py` | Verified locally; external gates below |
| RESULT-A13 | Browser closure and controller restart preserve an approved analysis execution without duplicate generation or report overwrite. | artifacts | Implemented: workspace_results.py, workspace.py; ArtifactPages.tsx | Existing durable worker and actual-project reanalysis tests ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_results.py, test_workspace_project_mock.py` | Verified locally; external gates below |
| RESULT-A14 | Concurrent evidence-note edits return a conflict and retain both the saved version and the user's unsaved text. | artifacts | Implemented: workspace_results.py, workspace.py; ArtifactPages.tsx | Notes use maintenance expected-version API; UI retains text on failure ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_results.py, test_workspace_project_mock.py` | Verified locally; external gates below |
| RESULT-S11 | [Delivery phases and technical gates](results-spec.md) | artifacts | Implemented: workspace_results.py, workspace.py; ArtifactPages.tsx | Focused area suite and integrated browser checks ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_results.py, test_workspace_project_mock.py` | Verified locally; external gates below |
| FILE-S1 | [Decisions and purpose](files-spec.md) | artifacts | Implemented: workspace_artifacts.py; ArtifactPages.tsx | Focused area suite and integrated browser checks ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_artifacts.py` | Verified locally; external gates below |
| FILE-S2 | [Navigation and layout](files-spec.md) | artifacts | Implemented: workspace_artifacts.py; ArtifactPages.tsx | Focused area suite and integrated browser checks ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_artifacts.py` | Verified locally; external gates below |
| FILE-S3 | [Preview contract](files-spec.md) | artifacts | Implemented: workspace_artifacts.py; ArtifactPages.tsx | Focused area suite and integrated browser checks ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_artifacts.py` | Verified locally; external gates below |
| FILE-S4 | [Artifact availability and completeness](files-spec.md) | artifacts | Implemented: workspace_artifacts.py; ArtifactPages.tsx | Focused area suite and integrated browser checks ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_artifacts.py` | Verified locally; external gates below |
| FILE-S5 | [Retrieval and action availability](files-spec.md) | artifacts | Implemented: workspace_artifacts.py; ArtifactPages.tsx | Focused area suite and integrated browser checks ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_artifacts.py` | Verified locally; external gates below |
| FILE-S6 | [Editing and synchronization boundaries](files-spec.md) | artifacts | Implemented: workspace_artifacts.py; ArtifactPages.tsx | Focused area suite and integrated browser checks ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_artifacts.py` | Verified locally; external gates below |
| FILE-S7 | [Data contracts and resource scope](files-spec.md) | artifacts | Implemented: workspace_artifacts.py; ArtifactPages.tsx | Focused area suite and integrated browser checks ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_artifacts.py` | Verified locally; external gates below |
| FILE-S8 | [Loading and failure behavior](files-spec.md) | artifacts | Implemented: workspace_artifacts.py; ArtifactPages.tsx | Focused area suite and integrated browser checks ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_artifacts.py` | Verified locally; external gates below |
| FILE-S9 | [Acceptance and verification scenarios](files-spec.md) | artifacts | Implemented: workspace_artifacts.py; ArtifactPages.tsx | Focused area suite and integrated browser checks ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_artifacts.py` | Verified locally; external gates below |
| FILE-A1 | A Results artifact link opens the exact file version and preserves execution, variant, stage, attempt, and Purpose. | artifacts | Implemented: workspace_artifacts.py; ArtifactPages.tsx | Immutable download test; Files links retain artifact and producer IDs ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_artifacts.py` | Verified locally; external gates below |
| FILE-A2 | A browser on another machine distinguishes controller-local availability from a completed browser download. | artifacts | Implemented: workspace_artifacts.py; ArtifactPages.tsx | Controller host labels and separate browser download links ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_artifacts.py` | Verified locally; external gates below |
| FILE-A3 | Selecting one remote artifact cannot invoke the broad legacy corpus hook without a review of that full scope. | artifacts | Implemented: workspace_artifacts.py; ArtifactPages.tsx | `test_unknown_adapter_cannot_call_legacy_hook` ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_artifacts.py` | Verified locally; external gates below |
| FILE-A4 | A partial transfer preserves checked files, quarantines incomplete bytes, and retries only reviewed remaining members through a capable adapter. | artifacts | Implemented: workspace_artifacts.py; ArtifactPages.tsx | Partial quarantine and partial-retry tests ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_artifacts.py` | Verified locally; external gates below |
| FILE-A5 | A changed local destination never loses its prior bytes during retrieval. | artifacts | Implemented: workspace_artifacts.py; ArtifactPages.tsx | `test_partial_transfer_quarantines_bytes_and_preserves_destination` ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_artifacts.py` | Verified locally; external gates below |
| FILE-A6 | Transfer cancellation leaves scheduler jobs and unrelated transfers unchanged. | artifacts | Implemented: workspace_artifacts.py; ArtifactPages.tsx | Transfer cancellation writes only transfer records; bounded transfer process termination ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_artifacts.py` | Verified locally; external gates below |
| FILE-A7 | An interrupted transfer reconciles existing bytes before any retry and never reports complete from an exit code alone. | artifacts | Implemented: workspace_artifacts.py; ArtifactPages.tsx | `test_transfer_restart_reconciles_before_retry` ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_artifacts.py` | Verified locally; external gates below |
| FILE-A8 | A successful retrieval of incomplete JSONL remains Partial in Results and Files until its declared completeness check passes. | artifacts | Implemented: workspace_artifacts.py; ArtifactPages.tsx | `test_successful_retrieval_does_not_promote_incomplete_science` ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_artifacts.py` | Verified locally; external gates below |
| FILE-A9 | Source edits after review invalidate the next dispatch review while queued executions keep their frozen source. | artifacts | Implemented: workspace_artifacts.py; ArtifactPages.tsx | Existing execution source-change tests; immutable input copy test ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_artifacts.py` | Verified locally; external gates below |
| FILE-A10 | A symlink escape, traversal path, secret file, and oversized preview cannot bypass server-side root and budget controls. | artifacts | Implemented: workspace_artifacts.py; ArtifactPages.tsx | Secret, traversal, symlink, preview-budget tests ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_artifacts.py` | Verified locally; external gates below |
| FILE-A11 | JSON parse failure leaves the raw bounded preview available without attempting a repair. | artifacts | Implemented: workspace_artifacts.py; ArtifactPages.tsx | Parse-error test retains raw JSON text ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_artifacts.py` | Verified locally; external gates below |
| FILE-A12 | Model output that contains HTML or tool directives displays as evidence and executes nothing. | artifacts | Implemented: workspace_artifacts.py; ArtifactPages.tsx | Literal markup preview; React text output; sandboxed download ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_artifacts.py` | Verified locally; external gates below |
| FILE-A13 | An unavailable remote location does not disable the checked local copy or erase its provenance. | artifacts | Implemented: workspace_artifacts.py; ArtifactPages.tsx | Immutable local copies remain independent of remote state ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_artifacts.py` | Verified locally; external gates below |
| FILE-A14 | Large text and JSONL remain navigable through bounded pages and accurately labeled search scope. | artifacts | Implemented: workspace_artifacts.py; ArtifactPages.tsx | Bounded preview and multi-file sample cursor tests ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_artifacts.py` | Verified locally; external gates below |
| FILE-A15 | Archive and report supersession preserve file paths, downloads, and evidence links. | artifacts | Implemented: workspace_artifacts.py; ArtifactPages.tsx | Immutable versions and prior-analysis mock tests ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_artifacts.py` | Verified locally; external gates below |
| FILE-S10 | [Delivery phases and technical gates](files-spec.md) | artifacts | Implemented: workspace_artifacts.py; ArtifactPages.tsx | Focused area suite and integrated browser checks ([evidence](remaining-artifacts-progress.md)); `tests/test_workspace_artifacts.py` | Verified locally; external gates below |
| SETTING-S1 | [Authority and scope](settings-spec.md) | maintenance | Implemented: workspace_settings.py; SettingsPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_settings.py` | Verified locally; external gates below |
| SETTING-S2 | [Navigation and layout](settings-spec.md) | maintenance | Implemented: workspace_settings.py; SettingsPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_settings.py` | Verified locally; external gates below |
| SETTING-S3 | [Controls and effects](settings-spec.md) | maintenance | Implemented: workspace_settings.py; SettingsPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_settings.py` | Verified locally; external gates below |
| SETTING-S4 | [State model and edge cases](settings-spec.md) | maintenance | Implemented: workspace_settings.py; SettingsPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_settings.py` | Verified locally; external gates below |
| SETTING-S5 | [Data contracts and ownership](settings-spec.md) | maintenance | Implemented: workspace_settings.py; SettingsPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_settings.py` | Verified locally; external gates below |
| SETTING-S6 | [Compatibility and migration](settings-spec.md) | maintenance | Implemented: workspace_settings.py; SettingsPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_settings.py` | Verified locally; external gates below |
| SETTING-S7 | [Acceptance and verification](settings-spec.md) | maintenance | Implemented: workspace_settings.py; SettingsPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_settings.py` | Verified locally; external gates below |
| SETTING-A1 | Given concurrent declaration edits, Save defaults returns a conflict and preserves both versions without a partial field overwrite. | maintenance | Implemented: workspace_settings.py; SettingsPage.tsx | Exact declaration bytes, registry fingerprint, and expected settings version prevent conflicting applies. External edit fixture preserves unknown fields. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_settings.py` | Verified locally; external gates below |
| SETTING-A2 | Given a queued execution, new defaults change a new draft but preserve the queued source, resources, and outputs. | maintenance | Implemented: workspace_settings.py; SettingsPage.tsx | New drafts materialize defaults. Maintenance freezes older drafts before changing defaults. Approved plans retain their original snapshots. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_settings.py` | Verified locally; external gates below |
| SETTING-A3 | Given an `ml` attachment, migration shows coordinated mode and preserves every historical primitive and job ID. | maintenance | Implemented: workspace_settings.py; SettingsPage.tsx | Semantic migration preserves registry primitive, ledger IDs, custom adapter bytes, disabled Sync, and project science. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_settings.py` | Verified locally; external gates below |
| SETTING-A4 | Given an unavailable SSH key, local history opens and Connection shows the failed remote fact with its timestamp. | maintenance | Implemented: workspace_settings.py; SettingsPage.tsx | Connection facts have separate statuses, deadlines, sources, and times. Local pages do not run SSH. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_settings.py` | Verified locally; external gates below |
| SETTING-A5 | Given a custom sync/fetch adapter, migration preserves its bytes and never enables disabled Sync. | maintenance | Implemented: workspace_settings.py; SettingsPage.tsx | Semantic migration preserves registry primitive, ledger IDs, custom adapter bytes, disabled Sync, and project science. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_settings.py` | Verified locally; external gates below |
| SETTING-A6 | Given active or uncertain work, relocation and detach remain blocked with exact blocking identities and links. | maintenance | Implemented: workspace_settings.py; SettingsPage.tsx | Quiescence includes workspace stages, schedules, management operations, transfers, and legacy ledger jobs. Relocation checks target history and artifact bytes. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_settings.py` | Verified locally; external gates below |
| SETTING-A7 | Given a restart during activation, the controller reports one maintenance action and reconciles it before another write. | maintenance | Implemented: workspace_settings.py; SettingsPage.tsx | Journal records backup, draft freeze, declaration, registry, and metadata steps. Reconciliation resumes the same action. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_settings.py` | Verified locally; external gates below |
| SETTING-A8 | Given an unknown schema, Settings reports the unsupported version and cannot dispatch through a guessed compatibility mapping. | maintenance | Implemented: workspace_settings.py; SettingsPage.tsx | Unknown required features block planning. Unknown store versions retain Settings reads and block writes. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_settings.py` | Verified locally; external gates below |
| SETTING-A9 | Given the same controller in two browsers, an expected-version conflict prevents one settings form from replacing the other. | maintenance | Implemented: workspace_settings.py; SettingsPage.tsx | Exact declaration bytes, registry fingerprint, and expected settings version prevent conflicting applies. External edit fixture preserves unknown fields. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_settings.py` | Verified locally; external gates below |
| SETTING-A10 | Given a backup restore fixture, historical links resolve and newer records never disappear under an older controller. | maintenance | Implemented: workspace_settings.py; SettingsPage.tsx | Backup digests and readback precede activation. Rollback rejects post-migration records and preserves them. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_settings.py` | Verified locally; external gates below |
| SETTING-S8 | [Delivery and technical gates](settings-spec.md) | maintenance | Implemented: workspace_settings.py; SettingsPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_settings.py` | Verified locally; external gates below |
| OVERVIEW-S1 | [User goal and layout](overview-spec.md) | maintenance | Implemented: workspace_overview.py; OverviewPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_overview.py` | Verified locally; external gates below |
| OVERVIEW-S2 | [Controls, priorities, and transitions](overview-spec.md) | maintenance | Implemented: workspace_overview.py; OverviewPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_overview.py` | Verified locally; external gates below |
| OVERVIEW-S3 | [Edge states](overview-spec.md) | maintenance | Implemented: workspace_overview.py; OverviewPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_overview.py` | Verified locally; external gates below |
| OVERVIEW-S4 | [Proposed data contract](overview-spec.md) | maintenance | Implemented: workspace_overview.py; OverviewPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_overview.py` | Verified locally; external gates below |
| OVERVIEW-S5 | [Automation limits and verification](overview-spec.md) | maintenance | Implemented: workspace_overview.py; OverviewPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_overview.py` | Verified locally; external gates below |
| OVERVIEW-A1 | A new attachment opens Overview with an editable empty question and truthful zero counts. Home returns to the prior Projects filter. | maintenance | Implemented: workspace_overview.py; OverviewPage.tsx | Research editor, real zero counts, purpose-preserving attention, and exact entity links. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_overview.py` | Verified locally; external gates below |
| OVERVIEW-A2 | A failed smoke test appears under attention with Purpose intact. Its link opens only the affected execution and dependents. | maintenance | Implemented: workspace_overview.py; OverviewPage.tsx | Research editor, real zero counts, purpose-preserving attention, and exact entity links. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_overview.py` | Verified locally; external gates below |
| OVERVIEW-A3 | Scheduler observations become stale while local notes remain available. Their independent timestamps remain visible. | maintenance | Implemented: workspace_overview.py; OverviewPage.tsx | Scheduler observations retain their own times. Local research metadata stays readable. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_overview.py` | Verified locally; external gates below |
| OVERVIEW-A4 | Two editors save the same question revision. The second receives a conflict, keeps its text, and cannot overwrite silently. | maintenance | Implemented: workspace_overview.py; OverviewPage.tsx | Saved text, intentionally cleared questions, and manifest origin survive later declaration changes. Concurrent writes return conflicts. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_overview.py` | Verified locally; external gates below |
| OVERVIEW-A5 | Reanalysis creates a new report. An existing pin and conclusion still open the original revision until the human updates the pin. | maintenance | Implemented: workspace_overview.py; OverviewPage.tsx | Notes and pins store immutable evidence revisions; updates retain history. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_overview.py` | Verified locally; external gates below |
| OVERVIEW-A6 | A complete corpus behind a failed scheduler exit appears as a blocker and as available evidence, without automatic continuation. | maintenance | Implemented: workspace_overview.py; OverviewPage.tsx | Failed stages remain blockers even when their artifacts are complete. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_overview.py` | Verified locally; external gates below |
| OVERVIEW-A7 | Results indexing fails. The question, Runs cards, and successful section reads remain usable. | maintenance | Implemented: workspace_overview.py; OverviewPage.tsx | Failed artifact metadata reads do not discard research text or Runs counts. Failed counts return unavailable, never zero. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_overview.py` | Verified locally; external gates below |
| OVERVIEW-A8 | Keyboard and narrow-screen users can reach Home, all six sections, attention items, pins, and metadata save controls. | maintenance | Implemented: workspace_overview.py; OverviewPage.tsx | Native links, buttons, labels, cards, and responsive grids support keyboard and narrow layouts. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_overview.py` | Verified locally; external gates below |
| OVERVIEW-A9 | An existing manifest question survives upgrade. Declaration reload cannot overwrite a saved human revision or restore intentionally cleared text. | maintenance | Implemented: workspace_overview.py; OverviewPage.tsx | Saved text, intentionally cleared questions, and manifest origin survive later declaration changes. Concurrent writes return conflicts. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_overview.py` | Verified locally; external gates below |
| OVERVIEW-S6 | [Delivery and deferred features](overview-spec.md) | maintenance | Implemented: workspace_overview.py; OverviewPage.tsx | Focused area suite and integrated browser checks ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_overview.py` | Verified locally; external gates below |
| COMPOSE-S1 | [Authority and product decision](composition-spec.md) | maintenance | Implemented: workspace_composition.py, workspace_planner.py; CompositionEditor.tsx | Focused area suite and integrated browser checks ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_composition.py` | Verified locally; external gates below |
| COMPOSE-S2 | [Navigation, layout, and actions](composition-spec.md) | maintenance | Implemented: workspace_composition.py, workspace_planner.py; CompositionEditor.tsx | Focused area suite and integrated browser checks ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_composition.py` | Verified locally; external gates below |
| COMPOSE-S3 | [Operation and artifact contracts](composition-spec.md) | maintenance | Implemented: workspace_composition.py, workspace_planner.py; CompositionEditor.tsx | Focused area suite and integrated browser checks ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_composition.py` | Verified locally; external gates below |
| COMPOSE-S4 | [Stage scope and deterministic expansion](composition-spec.md) | maintenance | Implemented: workspace_composition.py, workspace_planner.py; CompositionEditor.tsx | Focused area suite and integrated browser checks ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_composition.py` | Verified locally; external gates below |
| COMPOSE-S5 | [Measurement composition](composition-spec.md) | maintenance | Implemented: workspace_composition.py, workspace_planner.py; CompositionEditor.tsx | Focused area suite and integrated browser checks ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_composition.py` | Verified locally; external gates below |
| COMPOSE-S6 | [States and action availability](composition-spec.md) | maintenance | Implemented: workspace_composition.py, workspace_planner.py; CompositionEditor.tsx | Focused area suite and integrated browser checks ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_composition.py` | Verified locally; external gates below |
| COMPOSE-S7 | [Automatic-action limits](composition-spec.md) | maintenance | Implemented: workspace_composition.py, workspace_planner.py; CompositionEditor.tsx | Focused area suite and integrated browser checks ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_composition.py` | Verified locally; external gates below |
| COMPOSE-S8 | [Acceptance and verification scenarios](composition-spec.md) | maintenance | Implemented: workspace_composition.py, workspace_planner.py; CompositionEditor.tsx | Focused area suite and integrated browser checks ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_composition.py` | Verified locally; external gates below |
| COMPOSE-A1 | A researcher composes GPU collection, CPU validation, and CPU analysis through typed ports without a predefined workflow. | maintenance | Implemented: workspace_composition.py, workspace_planner.py; CompositionEditor.tsx | Typed cards lower into the existing compiler. The real project CPU mock executes four variants with both caps. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_composition.py` | Verified locally; external gates below |
| COMPOSE-A2 | Two models and two token caps produce four variants and preserve both cap conditions through result analysis. | maintenance | Implemented: workspace_composition.py, workspace_planner.py; CompositionEditor.tsx | Typed cards lower into the existing compiler. The real project CPU mock executes four variants with both caps. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_composition.py` | Verified locally; external gates below |
| COMPOSE-A3 | A shared fixture check appears once, while a variant-dependent input prevents accidental shared execution. | maintenance | Implemented: workspace_composition.py, workspace_planner.py; CompositionEditor.tsx | Scope, exact version, typed port, unit, cycle, purpose, and completeness validation precedes snapshot creation. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_composition.py` | Verified locally; external gates below |
| COMPOSE-A4 | A cyclic graph, missing port, unsupported version, and incompatible unit each produce a specific blocking error before dispatch. | maintenance | Implemented: workspace_composition.py, workspace_planner.py; CompositionEditor.tsx | Scope, exact version, typed port, unit, cycle, purpose, and completeness validation precedes snapshot creation. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_composition.py` | Verified locally; external gates below |
| COMPOSE-A5 | A smoke-test artifact cannot replace the full parent corpus of a TLAiBench stage. | maintenance | Implemented: workspace_composition.py, workspace_planner.py; CompositionEditor.tsx | Scope, exact version, typed port, unit, cycle, purpose, and completeness validation precedes snapshot creation. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_composition.py` | Verified locally; external gates below |
| COMPOSE-A6 | A many-input analysis consumes exactly the reviewed artifact set and exposes unmatched or incomplete inputs. | maintenance | Implemented: workspace_composition.py, workspace_planner.py; CompositionEditor.tsx | Reduction expands exact producer variants once. Inputs and expansion have fixed upper limits. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_composition.py` | Verified locally; external gates below |
| COMPOSE-A7 | A graph over the configured expansion limit fails without partial submission or silent truncation. | maintenance | Implemented: workspace_composition.py, workspace_planner.py; CompositionEditor.tsx | Reduction expands exact producer variants once. Inputs and expansion have fixed upper limits. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_composition.py` | Verified locally; external gates below |
| COMPOSE-A8 | Arguments containing spaces and shell metacharacters retain literal values in inspectable generated wrappers. | maintenance | Implemented: workspace_composition.py, workspace_planner.py; CompositionEditor.tsx | Literal argument bindings use the baseline wrapper compiler. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_composition.py` | Verified locally; external gates below |
| COMPOSE-A9 | Selecting a derived metric over saved fields creates an analysis revision without collection. A new collector requires explicit added stages. | maintenance | Implemented: workspace_composition.py, workspace_planner.py; CompositionEditor.tsx | Collector metrics require explicit collector nodes. Saved artifact inputs use immutable copies. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_composition.py` | Verified locally; external gates below |
| COMPOSE-A10 | A removed operation preserves a saved draft and historical execution, with its original operation reference visible. | maintenance | Implemented: workspace_composition.py, workspace_planner.py; CompositionEditor.tsx | Missing operations retain saved graph nodes and block a new plan. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_composition.py` | Verified locally; external gates below |
| COMPOSE-A11 | A controller restart resumes an approved graph without duplicate stages, overwritten outputs, or new scientific choices. | maintenance | Implemented: workspace_composition.py, workspace_planner.py; CompositionEditor.tsx | Composition uses existing worker receipts, bounded local stages, isolated output directories, and dependency rules. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_composition.py` | Verified locally; external gates below |
| COMPOSE-A12 | Parallel analysis attempts cannot corrupt a shared summary file because isolated outputs or declared exclusive scope control writes. | maintenance | Implemented: workspace_composition.py, workspace_planner.py; CompositionEditor.tsx | Composition uses existing worker receipts, bounded local stages, isolated output directories, and dependency rules. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_composition.py` | Verified locally; external gates below |
| COMPOSE-A13 | A failed prerequisite pauses only its dependents, while a valid negative measurement continues through approved analysis. | maintenance | Implemented: workspace_composition.py, workspace_planner.py; CompositionEditor.tsx | Composition uses existing worker receipts, bounded local stages, isolated output directories, and dependency rules. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_composition.py` | Verified locally; external gates below |
| COMPOSE-A14 | Every graph action works through keyboard-accessible cards and preserves the same dependency representation as the diagram. | maintenance | Implemented: workspace_composition.py, workspace_planner.py; CompositionEditor.tsx | Ordered cards, accessible dependency links, duplication, removal review, scope, purpose, and bindings edit the same graph. ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_composition.py` | Verified locally; external gates below |
| COMPOSE-S9 | [Delivery and technical gates](composition-spec.md) | maintenance | Implemented: workspace_composition.py, workspace_planner.py; CompositionEditor.tsx | Focused area suite and integrated browser checks ([evidence](remaining-maintenance-progress.md)); `tests/test_workspace_composition.py` | Verified locally; external gates below |

## Spike register

| Spike | Owner | Evidence | Completion gate |
| --- | --- | --- | --- |
| T1 | execution | Conditional fake adapter race, exact resource history | Local contract checked; all site fields disabled pending audited adapter |
| T2 | execution | Exact child and sibling fixtures, partial refusals and reconciliation | Local contract checked; real array-state matrix remains a site gate |
| T3 | artifacts | Partial/restart/cancel/digest/secret/symlink regressions | Local contract checked; owned remote fixture pilot remains |
| T4 | execution + artifacts | Project mock resume and active/stopped checkpoint writer checks | Checked locally; each scientific checkpoint needs its declared validator |
| T5 | artifacts | Actual copied-project selected analysis and four-condition comparison | Both caps, parent identity and duplicate handling checked |
| T6 | artifacts | 8 MiB/5,000-record scan budgets, malformed/oversized and partial records | Documented bounded-scan fallback checked; full-corpus search disabled |
| T7 | maintenance | All five activation and three rollback fault boundaries | Checked; backup includes bundles, artifacts, receipts and ledger |
| T8 | maintenance | Required-feature/port validators and exact preset/composed equality | Checked; unknown features block planning, historical reads remain |
| T9 | execution + maintenance | Real process receipts/deadlines/locks; composed receipt restart | Checked locally; project serialization is the declared fallback |
| T10 | execution | 64 KiB stream cursor, binary/rotation/exact transfer/cache regressions | Local checks pass; live transport pilot remains; absent restart attribution stays Unknown |

## Integration log

- Intake baseline: 53 focused Experiments tests passed.
- Shared read-only store and explicit recovery integration: 23 tests passed.
- First combined artifact snapshot run found an inconsistent frozen member-path check. The planner correction passed its regression.
- Browser checks use `[temporary local artifact]`; the live controller build remains unchanged.
- New scientific fixture identities discard inherited snapshot metadata before indexing. This preserves the distinction from their original Smoke test evidence.

- Combined integration: 36 passed, including actual copied-project analysis and resume.
- Dashboard typecheck, ESLint and isolated production build passed.
- First browser pass: 23 passed, 2 legacy fixture contract failures. Updated fixture to reflect additive Overview and Runs responses; the experiment edit/review/dispatch browser case now passes.
- Real API browser navigation passed all six workspace pages, narrow layout, keyboard focus, Home links, and passive state preservation. Screenshot: `[temporary local artifact]`.
- Full non-browser regression: 935 passed, one old mutable-artifact test requires separate snapshot-tamper and original-overwrite assertions. The acceptance criterion remains intact.
- New real API browser flow reaches four local variants, reviewed dispatch, Results and saved four-condition comparison. Evidence-note accessibility fix and analysis leg remain under verification.
- Independent reviews identified cancellation reconciliation after uncertain acceptance, comparison metric compatibility, multi-file sample cursors, and report currency. Owners added repairs and regressions.

## Live capability gates

[The bounded pilot plan](remaining-workspace-live-validation.md) records the separate approval boundaries.
[Pilot A evidence](remaining-workspace-pilot-a-evidence.md) records the approved read-only Unity survey and 31 focused checks.
Scheduler mutations stay disabled until a site adapter proves its semantics.
Remote transport and genuine GPU collection retain their explicit live gates.
Full-corpus search remains disabled under the documented bounded-scan fallback.
All independent local checks are complete. No live gate is reported as verified.

- Explicit experiment operations cache the observed manifest question as provenance. Read-only pages still use passive store access.
- Real API browser flow now checks saved comparison pins, retained note edits after a conflict, analysis-only dispatch, and prior evidence links.
- Keyboard composition checks cover adding, duplicating, reordering, removing, binding multiple inputs, and reviewing the resulting graph.
- Final full-spec review added typed file previews, complete scoped file metadata, and bounded sample filters to the implementation queue.

- The full combined run passed 1,017 checks and found three failures. The Home assertion required the new filter-restoring link contract.
- Two blank Runs pages came from a legacy fixture without the production `collections` field. All four legacy browser checks now pass.
- Independent review found protected-root aliases, partial CSV records, stale Results pagination and out-of-order preview responses. Repairs include targeted regressions.
- Four new integration checks pass: composed receipt restart, both schedule cancellation race orders, and changed selected-input invalidation.
- The final audit found API observation and conflict-envelope gaps. These remain in the final integration queue until their direct API checks pass.

- Direct API checks now verify additive response metadata, preserved source age, stable tokens and current-version conflicts.
- Metadata traversal treats scientific records as opaque data. Invalid freshness values cannot break a page response.

## Final review outcomes

Independent reviewers checked execution, artifacts, maintenance, composition, shared contracts, and manager integration changes.
The manager inspected the combined services, scientific adapter, and actual browser captures.
All actionable findings received repairs and regression checks.

The last round added strict JSON parsing for invalid numeric constants.
Malformed scientific data keeps its raw source and cannot break the browser response parser.
Results also clears artifact-specific sample state and ignores late detail responses.

The accepted specification, build plan, decision record, native board, and previous Experiments progress records retain their intake hashes.
All implementation changes remain local and uncommitted. No push, merge, publication, deployment, or live workload operation occurred.

## Session change inventory

The inventory compares current bytes with the intake snapshot, or with HEAD for files that were clean at intake.
It excludes earlier unrelated changes. The attached project has four changed files.

### Controller services

- `controller/http.py`
- `controller/workspace.py`
- `controller/workspace_actions.py`
- `controller/workspace_artifact_http.py`
- `controller/workspace_artifacts.py`
- `controller/workspace_composition.py`
- `controller/workspace_connection.py`
- `controller/workspace_contracts.py`
- `controller/workspace_dispatch.py`
- `controller/workspace_execution_http.py`
- `controller/workspace_http.py`
- `controller/workspace_local.py`
- `controller/workspace_overview.py`
- `controller/workspace_planner.py`
- `controller/workspace_results.py`
- `controller/workspace_runs.py`
- `controller/workspace_schedules.py`
- `controller/workspace_settings.py`
- `controller/workspace_settings_http.py`
- `controller/workspace_store.py`
- `controller/workspace_worker.py`

### Dashboard

- `controller/web/src/App.tsx`
- `controller/web/src/modules/workspace/ArtifactPages.tsx`
- `controller/web/src/modules/workspace/CompositionEditor.tsx`
- `controller/web/src/modules/workspace/ExecutionPages.tsx`
- `controller/web/src/modules/workspace/ExperimentEditor.tsx`
- `controller/web/src/modules/workspace/FilePreview.tsx`
- `controller/web/src/modules/workspace/OverviewPage.tsx`
- `controller/web/src/modules/workspace/RunsPage.tsx`
- `controller/web/src/modules/workspace/Schedules.tsx`
- `controller/web/src/modules/workspace/SettingsPage.tsx`
- `controller/web/src/modules/workspace/Workspace.tsx`
- `controller/web/src/modules/workspace/api.ts`
- `controller/web/src/modules/workspace/navigation.ts`
- `controller/web/src/ui/layout/NavigationDrawer.tsx`

### Verification

- `tests/test_controller_web.py`
- `tests/test_controller_web_smoke.py`
- `tests/test_remaining_workspace_browser.py`
- `tests/test_remaining_workspace_integration.py`
- `tests/test_remaining_workspace_restart.py`
- `tests/test_workspace_actions.py`
- `tests/test_workspace_artifact_races_browser.py`
- `tests/test_workspace_artifacts.py`
- `tests/test_workspace_browser.py`
- `tests/test_workspace_composition.py`
- `tests/test_workspace_conflict_versions.py`
- `tests/test_workspace_execution.py`
- `tests/test_workspace_log_transport.py`
- `tests/test_workspace_overview.py`
- `tests/test_workspace_preview_browser.py`
- `tests/test_workspace_project_mock.py`
- `tests/test_workspace_response_contracts.py`
- `tests/test_workspace_results.py`
- `tests/test_workspace_runs.py`
- `tests/test_workspace_schedules.py`
- `tests/test_workspace_settings.py`

### Dispatcher support

- `templates/scaffold/common/run.sh`

### Progress and live gates

- `docs/design/remaining-artifacts-progress.md`
- `docs/design/remaining-execution-progress.md`
- `docs/design/remaining-maintenance-progress.md`
- `docs/design/remaining-workspace-live-validation.md`
- `docs/design/remaining-workspace-pilot-a-evidence.md`
- `docs/design/remaining-workspace-progress.md`

### Attached scientific project

Root: `the attached research project`.

- `unityHPC/project.json`
- `unityHPC/workspace_adapter.py`
- `unityHPC/workspace_results_adapter.py`
- `tests/test_workspace_results_adapter.py`

The manager rechecked the existing `tests/test_workspace_adapter.py` without modification.
The adapter preimages remain in `[temporary local artifact]`.
The composition declaration preimage also remains in `[temporary local artifact]`.

### Review artifacts

- Main session patch: `[temporary local artifact]`
- Main inventory and hashes: `[temporary local artifact]`
- Scientific project patch: `[temporary local artifact]`
- Scientific project inventory: `[temporary local artifact]`

These patches contain only this session's changes. A reverse dry-run against the current files checks each patch without changing files.

## Final verification evidence

| Check | Result | Evidence |
| --- | --- | --- |
| Full repository suite with real browser tests enabled | 1,055 passed in 197.37 seconds | `[temporary local artifact]` |
| Final response metadata, conflict, API and manager integration checks | 27 passed | `[temporary local artifact]` |
| Attached project adapter and plot checks | 12 passed | `[temporary local artifact]` |
| Dashboard TypeScript and ESLint | Passed | Manager command completed with exit zero |
| Isolated dashboard production build | Passed | `[temporary local artifact]` |
| Main and attached-project patch reverse dry-runs | Passed | `git apply --reverse --check` against each session patch |
| Accepted documents, native board and earlier records | Intake hashes unchanged | Preservation check recorded in this session |
| Local progress-document links | 197 resolved, zero missing | Final local link scan |
| Git whitespace check | Passed | `git diff --check` |

The full run includes real HTTP/browser navigation, deep links, narrow layouts, keyboard controls, loading, empty and unavailable states.
It covers four variants, comparison, saved evidence, analysis, composition, scheduling, cancellation receipts, strict previews, and delayed-response races.
The copied scientific project separately proves that both token-cap conditions survive selected-input analysis.

After the full run, one metadata correction exposes the already-known connection declaration digest.
The final focused run checks that correction and its API dependencies. An independent reviewer found no issue.
The check counts overlap and must not be added together.

Reproduction commands from the repository root:

```bash
UNITY_HPC_UI_SMOKE=1 UNITY_HPC_TEST_UI_DIR=[temporary local artifact] pytest -q
python -m pytest -q tests/test_workspace_response_contracts.py tests/test_workspace_conflict_versions.py tests/test_workspace_api.py tests/test_remaining_workspace_integration.py
```

Dashboard checks use `controller/web` as the working directory:

```bash
npm run typecheck
npm run lint
npx vite build --outDir [temporary local artifact]
```

The attached project checks use its root as the working directory:

```bash
python -m pytest -q tests/test_workspace_adapter.py tests/test_workspace_results_adapter.py
```

Actual browser captures remain under `[temporary local artifact]*.png` and `[temporary local artifact]*.png`.
The manager inspected the workspace and rich preview captures. These are rendered application states, not design mockups.

The user approved Pilot A's bounded read-only survey through the controller's configured `unity` SSH alias.
The [survey record](remaining-workspace-pilot-a-evidence.md) reports its site observations and 31 focused checks.
The remote root lacks the new declaration and adapters, and its dispatcher differs from the local file.
The user then approved Pilots B and C. The [pilot record](remaining-workspace-pilot-bc-evidence.md) reports one exact running-task cancellation and one fixture transfer.
Production cancellation and pending changes stay disabled. Real GPU collection still requires the approved environment lock and any missing immutable dataset declarations.
Production migration remains outside the authorized local verification scope.
