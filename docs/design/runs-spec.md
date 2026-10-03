# Runs and queue specification

Version 1, 2026-10-03. Final design for implementation planning. All choices introduced here are **agent-selected**, not previously user-approved.
The accepted [Experiments specification](experiments-spec.md), Q1–Q23, and [ADR 0008](../adr/0008-project-workspace-and-approved-executions.md) remain unchanged.
The [capability report](../research/runs-capabilities.md) distinguishes existing code from required backend work.
The [shared contract](remaining-workspace-spec.md) governs state mappings, identities, navigation, and action receipts across pages.

## Purpose and decisions

Runs answers four questions: what executes, what blocks it, what happened, and what exact action can change its outcome.
The human operates the UI. The controller advances only the reviewed plan through deterministic project operations.

| Decision | Choice and reason |
| --- | --- |
| RUN-01 | Interpret “schedule reassign” as three separate needs: future scheduling, pending request changes, and replacement or recovery. The phrase names no action. |
| RUN-02 | Keep executions primary, with stage and attempt drilldown. Scheduler jobs remain linked evidence, because variants and jobs are not equivalent. |
| RUN-03 | Separate scheduler state, submission state, artifact completeness, retrieval, progress, and freshness. One green badge cannot represent all six. |
| RUN-04 | Review each mutation against an exact target list and version. Preserve the original plan and append the management record. |
| RUN-05 | Use a new reviewed recovery plan and execution for retry, resume, and replacement. Link new stages and attempts to their original identities. |
| RUN-06 | Support one-off future dispatch with a frozen plan and a bounded dispatch window. Recurrence and adaptive queue policies remain deferred. |
| RUN-07 | Use stop-then-replace. A replacement cannot dispatch until the original target is observably terminal and its output writer has stopped. |
| RUN-08 | Do not offer automatic resource changes, retry, requeue, or dependency bypass. Approved continuation and explicitly selected retrieval remain automatic. |

## Navigation and layout

The project sidebar remains Home, Overview, Experiments, Runs, Results, Files, and Settings.
Home occupies the brand-header position and returns to the global Projects list. Project selection opens Overview.
Dispatch opens Runs filtered to the new execution. The execution banner links to its experiment, frozen revision, and reviewed plan.

Runs has three internal views: **Executions**, **Queue**, and **Schedules**. These are view controls, not extra project sidebar sections.
The default Executions view shows active work first, then recent terminal executions. URL filters survive reload and shared links.

Filters cover experiment, execution, purpose, state, date, and attention reason. Clear filters preserves the project scope.
Purpose choices remain All, Experiments, and Smoke tests. All includes historical Unclassified jobs.

| Surface | Layout and controls |
| --- | --- |
| Executions | Summary counts, search/filter bar, execution table, expandable variant/stage rows. Columns: execution, experiment, purpose, state, progress, results, started/updated. |
| Queue | Pending and running attempts, grouped by execution or scheduler group. Columns: job, stage, purpose, reason, request, elapsed/time limit, estimated start, observed time. |
| Detail | Header identities and action menu. Sections: Stages, Logs, Resources, Artifacts, History. Dependency diagram includes a keyboard-accessible ordered table. |
| Stage | Operation and version, variant or shared scope, inputs, dependencies, attempt timeline, exit evidence, progress, and output links. |
| Schedules | Approved future plans, timezone, earliest dispatch, latest dispatch, readiness, state, and edit/cancel actions. |
| Review drawer | Explicit targets, before/after request, affected dependents, capability evidence, data-loss risks, new output paths, and action-specific approval. |

Queue does not claim the user's place in a total queue. Pending reasons show raw scheduler codes beside short explanations.
Estimated start is optional and labelled Estimate, with its source and observation time. Unknown is an ordinary value.
A shorter walltime never guarantees an earlier start. The editor explains the risk that a shorter limit terminates unfinished work.

The principal action is **Open experiment** on a scoped execution. List actions are Refresh and New experiment.
Runs never introduces a second scientific configuration editor. Changes to parameters, operation code, or measurements return to an experiment revision.

## Identity and state contract

Every workspace item carries project slug and stable execution, stage, and attempt IDs.
A stage also carries variant ID or explicit shared scope. Logs and artifacts carry purpose and attempt provenance.
Scheduler identity includes cluster, campaign, job ID, parent group, and optional array task ID.
A numeric job ID alone is insufficient across clusters or historical reuse.

An external scheduler requeue can reuse a job ID. The adapter records scheduler restart count or an equivalent observation segment.
It never invents a newly approved attempt for an external action. History marks external state changes and uncertain attribution explicitly.

| Axis | Values and rules |
| --- | --- |
| Submission | `waiting`, `submitting`, `accepted`, `rejected`, `uncertain`. Uncertain forbids another submit until reconciliation. |
| Stage lifecycle | `waiting`, `ready`, `active`, `blocked`, `succeeded`, `failed`, `cancelled`, `skipped`. Waiting names its dependency, eligibility, or concurrency condition. |
| Scheduler | Raw state and flags, normalized category, reason code, exit code/signal, observed time. Controller-host stages have no job ID. |
| Progress | Declared unit, done, expected, source, observed time, optional rate. Missing progress is Unknown, never zero. |
| Completeness | `unknown`, `partial`, `complete`, `invalid`, plus checker version and evidence. Results defines artifact-level details. |
| Retrieval | `not_requested`, `queued`, `running`, `partial`, `complete`, `failed`. Retrieval failure does not change the job's exit state. |
| Freshness | `fresh`, `stale`, `unavailable`, with `observed_at`, `stale_after`, and source. Each observation domain ages independently. |
| Management action | `prepared`, `approved`, `applying`, `succeeded`, `partial`, `failed`, `uncertain`. Unknown action outcome blocks an overlapping mutation. |

Execution summaries derive from stage records. Active work yields Active even when a separate branch needs attention.
An attention badge shows blocked, rejected, uncertain, or failed portions alongside active counts.
When no work is active, unmet recovery conditions yield Needs attention. Remaining ordinary waits yield Waiting.

When all required stages succeed, the execution summary shows Succeeded. Explicit skipped optional stages do not prevent success.
When no work remains, all cancelled yields Cancelled, all failed yields Failed, and mixed outcomes yield Partial success.
Cancelled and failed required work cannot yield Succeeded. Completeness and retrieval badges remain visible beside the summary.

A stage becomes ready only when its declared conditions hold. Accepted submission does not prove that it started.
A successful scheduler exit does not prove scientific completeness. A valid negative scientific result does not imply execution failure.
Controller-host stages use bounded process groups and the same history, cancellation, and uncertainty rules.

## Dependencies and approved continuation

The detail view shows edges from exact producer stages and immutable artifact inputs.
Each edge names its condition: successful operation, passing smoke test, complete checked artifact, or a declared combination.
Shared prerequisites appear once, with all consumers visible. Variant concurrency and coordinated rank counts remain separate.

The default coordinator submits a downstream stage after its prerequisites satisfy the declared conditions.
A scheduler dependency alone cannot establish artifact completeness. Pre-submitted dependencies require equivalent explicit guards in the reviewed plan.
Independent branches continue after another branch fails. A failed smoke test blocks its dependents without relabelling them as failed experiments.

A complete corpus behind a failed job remains usable evidence for manual recovery.
**Use checked outputs** prepares a recovery plan with the failed producer, checker evidence, selected outputs, and dependent scope.
It does not rewrite the producer as successful or release an old failed scheduler dependency.
New dependents receive new attempts and producer references. The original dependency graph remains immutable history.

## Action availability

The service returns allowed actions with reasons. The UI never infers mutation rights from a state badge alone.
Each action requires capability support, ownership, fresh preflight, and absence of an overlapping unresolved action.
Read-only history and available files remain accessible during connection failure.

| State or condition | Available actions | Unavailable actions |
| --- | --- | --- |
| Waiting, no submitted job | Inspect, cancel selected planned work, prepare recovery/replacement plan where meaningful | Scheduler request update, scheduler cancel |
| Submitting or uncertain | Inspect, reconcile, stop further downstream dispatch | Retry, replacement dispatch, request mutation until outcome resolves |
| Accepted pending job | Logs if present, inspect request, review supported pending changes, cancel, prepare replacement | Arbitrary scientific edits, live hardware migration |
| Running | Logs, declared progress, cancel, prepare checkpoint resume/replacement, permitted walltime reduction | Ordinary running walltime increase, pending resource updates |
| Completing | Logs, retrieval of declared stable files, cancellation status | Retry until termination and writer completion resolve |
| Terminal failure/cancellation | Inspect, retrieve, review retry, compatible resume, use checked outputs | Change old scheduler request, overwrite historical outputs |
| Terminal success | Inspect, retrieve, Results, repeat through a new plan | Retry as a substitute for repeat |
| Stale observation | Read cached evidence, refresh, prepare a review | Apply until the controller obtains fresh authoritative preflight |
| Unsupported capability | Read evidence and capability explanation | Hidden fallback to broader scope or another primitive |

## Pending request changes and walltime

**Change pending request** opens a typed form backed by the attachment's capability descriptor.
The first implementation supports only explicitly demonstrated fields. Candidate fields are walltime, partition preference, and earliest eligibility.
CPU, memory, GPU, node, rank, and constraint changes use replacement until an adapter proves safe in-place semantics.
Scientific parameters, source snapshots, input identities, and output paths never change in place.

The review shows the original approved request, current effective request, proposed values, and affected task list.
It also shows changed limits, capability evidence, and stale estimates. Mutations cannot extend beyond the human's reviewed target set.
For arrays, the adapter must distinguish whole-group updates from selected task updates. Mixed running/pending membership blocks an unsafe whole-group update.

The backend re-reads state immediately before applying a mutation. If the job started, the pending edit fails closed and returns the new state.
An adapter must reject unsafe state races at the scheduler boundary. A local preflight alone is insufficient.

If the adapter cannot provide this guarantee, the field stays unavailable and the UI offers a replacement plan.
A timed-out update becomes uncertain. Reconciliation compares observed values before any second mutation.

Walltime uses an absolute duration, shown in hours and minutes. The service checks site limits and the exact allocation scope.
Running increases remain unavailable to ordinary users. The UI offers checkpoint-compatible recovery or site-support instructions when supplied by the project.

A supported running reduction shows the new termination horizon and requires explicit approval.
The product rejects a new limit at or below observed elapsed runtime. Cancellation remains the explicit way to stop now.
The review warns that the job can advance between preview and application. No walltime control promises a checkpoint.

A successful update appends old and new values, action ID, actor, timestamps, and scheduler acknowledgement.
The original frozen plan remains unchanged. Resources shows both approved-at-dispatch and effective-current requests.
No scientific result loses the request history used to produce it.

## Cancellation scope

Cancel always opens a scope preview. Selecting rows selects only those identities, not future rows that match the same filter.
Scope choices include selected attempts, selected variants with dependents, an execution, or an explicitly selected scheduler group.
Campaign cancellation is an advanced legacy action. It names every affected execution and group before approval.

The preview separates submitted jobs, controller-host processes, work awaiting submission, and unaffected siblings.
It shows all downstream work that will become blocked or cancelled. Shared prerequisite cancellation lists every affected consumer.

The default stage action cancels that target and blocks dependent dispatch. Cancelling the execution cancels its remaining planned work too.
A human can explicitly include dependent jobs already pending or running. Their identities and data-loss implications remain visible.

The controller first records a stop fence for affected unsent work. Then it cancels exact active targets.
This ordering prevents a dependency completion from racing a cancellation into a new submission.

The status becomes Cancel requested until observation establishes termination. A successful command exit alone cannot establish Cancelled.
A target that completed before cancellation remains completed. Its action outcome is Already terminal.

Partial cancellation reports each target separately. It never repeats cancellation against newly discovered group members without a new review.

The existing parent-group cancellation adapter cannot satisfy exact array-child scope.
Until a replacement adapter passes scope tests, the UI offers only the demonstrated group scope with all siblings shown.
No action stops another project's jobs or uses all-user scheduler filters.
Cancellation preserves existing files, reports, and provenance. Deletion is not a cancellation side effect.

## Retry, resume, and replacement

**Retry** starts the selected failed work from its declared initial inputs, under a new plan and fresh output paths.
**Resume** starts from a declared checkpoint or reusable partial corpus after compatibility checks.
**Replace** changes execution resources or replaces accepted work, with explicit termination and recovery scope.
**Repeat** creates another full execution through Experiments. These labels remain distinct.


A recovery review includes the source execution, stages, attempts, dependency edges, artifacts, resource differences, and expected retained or repeated work.
Compatibility checks cover operation version, source digest, parameters, input versions, schema, checkpoint format, purpose, and execution mode.
Changed scientific behavior becomes a new experiment revision. It cannot hide inside a resource recovery action.
Smoke-test artifacts cannot satisfy full measurement inputs.


Outputs use fresh plan/variant/stage paths bound to new attempt identities, consistent with ADR 0008.
No additional attempt directory level is required. Resume reads preserved inputs or declared copied checkpoints.
An operation that requires in-place continuation needs an adapter with exclusive writer ownership and a retained prior snapshot.
Without that adapter, Resume stays unavailable and Retry remains the fallback.


Replacement order is prepare → check → review → approve → stop original → observe terminal → dispatch replacement.
If stopping fails or becomes uncertain, replacement dispatch pauses. If replacement submission fails, the old job does not restart automatically.
The UI reports this partial outcome and offers a new scoped recovery review.
A checkpoint can become invalid while the source is active. The controller rechecks it after the writer stops and before dispatch.

No controller policy automatically requeues jobs. Scheduler-initiated restart remains external evidence and never proves application resume.
Failed dependent jobs require new reviewed dependent attempts. A parent retry does not silently repair their scheduler dependencies.

## Future scheduling

**Schedule this plan** appears beside Dispatch only after the same full check and review.
It creates a schedule approval, not an execution or scheduler job. Runs opens its Schedules view filtered to that schedule.
At successful dispatch, the schedule links its new execution and opens the ordinary execution destination.

The human selects an earliest dispatch instant, timezone, and latest dispatch instant.

The default latest dispatch is one hour after the earliest instant. The review permits an explicit longer or shorter window.

UTC stores the instants. The UI also preserves the chosen timezone and shows both local offset and UTC.
Ambiguous daylight-saving times require an explicit offset. Nonexistent local times fail validation.

The controller holds the plan until the window opens. The schedule does not reserve cluster resources or promise start time.
A separate pending-job Eligible after control describes scheduler eligibility. The two controls never share a label.
A schedule fires once, with a durable idempotency key. Restart reconciliation applies before another dispatch attempt.

| Schedule state | Transition and actions |
| --- | --- |
| Scheduled | Frozen review, active approval, window not open. Inspect, edit time through new review, or cancel. |
| Due | Window open. Recheck capability, approval binding, immutable inputs, source bundle, and attachment identity. |
| Dispatching | Commit durable dispatch intent. Cancel requests stop unsent work, but cannot erase an accepted job. |
| Dispatched | Link exactly one execution. Cancellation now uses execution scope. |
| Blocked | Capability or identity changed, or required input became unavailable. Recheck and review before reactivation. |
| Missed | Controller was unavailable or work remained blocked after the latest instant. No automatic late dispatch. |
| Cancelled | Approval withdrawn before dispatch. Preserve history and frozen plan. |
| Uncertain | Submission outcome unknown. Reconcile without duplicate dispatch. |


The due check uses the approval-time plan binding. It never swaps in the latest draft, source, or default resources.
It also applies the baseline dispatch checks against current draft, declaration, source, and input digests.
Any change that invalidates an undispatched review moves the schedule to Blocked. Frozen bytes alone do not bypass those checks.

A required identity change blocks dispatch. The human must check and review a new plan before dispatch.
Reusing earlier source requires a new plan explicitly bound to that source. It cannot reactivate a stale approval.
Schedule edits create a new version and revoke the prior approval. A due-worker race requires compare-and-swap ownership.
Future releases can add recurring schedules, catch-up batches, cross-project quotas, and automatic partition reassignment.

## Logs and observation

Logs select an exact execution, stage, attempt, and stream. Stdout, stderr, wrapper events, and controller events retain separate identities.
The view offers tail, pause follow, search in loaded text, retrieve full file, and open in Files.
The server bounds each default response to 64 KiB per stream. The server returns offsets and a continuation cursor.
Rotation or truncation creates a visible boundary. The client cannot concatenate different attempts into one apparent continuous log.


A missing log before start says Not created yet. An unavailable remote stream says Remote unavailable, with cached bytes and their age.
A binary stream offers retrieval and metadata instead of text. ANSI escape sequences cannot execute browser actions.

Logs do not constitute sample traces. Scientific traces link to Results with sample identity.
Generated metadata excludes secrets. Project stdout remains potentially sensitive local content, with explicit download controls.

The controller batches observation requests and exposes source freshness. Browser refresh cannot trigger submissions, retries, or expensive project checks.
Allocated GPUs do not establish GPU busy fraction. That measurement requires declared project instrumentation inside an allocation.
An unchanged progress counter says Last progress at, not Hung. No inferred stall causes automatic cancellation.

## Empty, stale, partial, and failure behavior

| Situation | Required behavior |
| --- | --- |
| No executions | Explain the workflow and link New experiment. Historical jobs remain discoverable in Queue. |
| No filter matches | Show active filters and Clear filters. Do not offer setup repair. |
| First load | Skeleton table and loading label. No false zero counts or enabled mutations. |
| Refresh in progress | Retain existing rows, selection, and observed times. Show refreshing without replacing evidence. |
| Connection unavailable | Retain cached history and local files. Explain which observations and actions require reconnection. |
| Partial submission | Show accepted, rejected, waiting, and uncertain stages individually. Recovery excludes already accepted work. |
| Partial fetch | Separate successful logs/artifacts from failed items. Retry retrieval only for selected failed items. |
| Stale scheduler data | Mark age and source. A successful HTTP response cannot erase the stale badge. |
| Unknown terminal outcome | Keep Unknown with last known state. Missing from queue does not imply success. |
| Permission or policy rejection | Show the rejected field and scheduler message. Preserve the original request and offer permitted alternatives. |
| Concurrent edit | Return conflict with current values. Preserve the user's proposed diff for another review. |
| Action timeout | Show Uncertain and reconcile. A second click returns the existing operation identity. |
| Historical metadata absent | Show Unclassified or Unknown. Never infer purpose, experiment, or completeness from names. |

## Required data and API extensions

Routes extend `/api/v1/projects/{slug}/workspace` from ADR 0008. These endpoint names are design proposals.
Existing generic routes keep their legacy scope until their callers migrate.

| Contract | Minimum payload and behavior |
| --- | --- |
| `executions` and detail | Stable IDs, frozen plan, stage graph, attempts, raw observations, summary counters, allowed actions, and source freshness. |
| `attempts/{id}/logs` | Stream ID, attempt ID, purpose, byte range, cursor, encoding, truncation/rotation, freshness, and availability. |
| `management-plans` | Action kind, explicit target IDs, expected versions, scheduler observation tokens, proposed diff, scope expansion, and capability evidence. |
| `management-plans/{id}/apply` | Frozen review digest, expected version, idempotency key, approval actor/time, and durable operation ID. |
| `operations/{id}` | Per-target requested, acknowledged, observed, failed, or uncertain outcome, with immutable audit entries. |
| `executions/{id}/recovery` | Recovery kind, source identities, compatibility results, checkpoint references, dependency remapping, and a new reviewable plan. |
| `schedules` | Frozen plan binding, window, timezone, version, approval, state, lease/dispatch intent, and eventual execution reference. |
| Capability descriptor | Per-action scopes and fields, permitted states, permission evidence, adapter version, observation age, and unsupported reason. |

All mutation reviews bind the project, connection revision, plan digest, target set, effective request versions, and capability version.
Apply rejects changed values with conflict. Idempotency keys bind request content, so key reuse with a different payload fails.
The controller owns operation records. `run.sh` remains the scheduler-ledger writer.
New scheduler update, exact cancel, and log adapters must obey that ownership. HTTP handlers never become direct scheduler clients.

## Verification and acceptance

Implementation acceptance uses controller and scheduler fakes plus dedicated adapter integration tests. Production jobs are not test fixtures.

1. Dispatch four variants with a shared smoke test. Runs preserves stage counts, purpose labels, exact dependencies, and the execution filter.
2. Fail one branch. Independent branches advance, dependent stages pause, and the summary shows active work plus attention.
3. Return exit zero with incomplete outputs. Runs shows scheduler success beside partial completeness and blocks incompatible consumers.
4. Return a complete corpus with a failed job. Only a reviewed recovery plan can use it, with original failure retained.
5. Timeout after scheduler acceptance. Restart and repeated clicks create no duplicate submission. Missing ledger evidence stays uncertain.
6. Select one array child. The preview never expands silently. Unsupported exact scope disables the action and explains group scope.
7. Cancel during dependency completion. The stop fence prevents any newly eligible dependent submission outside the approved scope.
8. Change a pending job while it starts. The adapter rejects the unsafe mutation or exposes reconciliation, without silently changing running resources.
9. Reduce walltime. Review shows the exact limit and termination risk, with no promise of an earlier start.
10. Fail cancellation during replacement. No replacement dispatch occurs. Fail replacement after cancellation and show that the old job remains stopped.
11. Resume from an incompatible checkpoint. Dispatch stays blocked, while compatible Retry remains separately reviewable.
12. Rotate logs between reads. The viewer preserves stream boundaries and never mixes attempts or purpose labels.
13. Close the browser and restart the controller. Approved continuation and one-off schedules retain their durable scope.
14. Miss a schedule window. State becomes Missed and no late job appears. A new review can dispatch later.
15. Change an input or attachment before a due schedule. The worker blocks it instead of substituting a new identity.
16. Resolve a DST overlap, two due workers, and a duplicate request. Exactly one approved dispatch intent survives.
17. Return stale status with a successful command exit. Stale remains visible and mutation preflight requires authoritative observations.
18. Cancel several targets with one refusal. The UI reports per-target outcomes and preserves successful cancellation evidence.

## Delivery phases and technical spikes

| Phase | Deliverable and dependencies | Completion gate |
| --- | --- | --- |
| R1 | Execution/attempt read model, stage graph, purpose, freshness, history, and Runs handoff. Depends on accepted Experiments identities and durable coordinator. | Scenarios 1–5 and 17 pass with frozen plan evidence. |
| R2 | Bounded logs, artifact links, scoped cancellation, and stop fences. Depends on Files retrieval contracts and exact scope adapter. | Scenarios 6–7, 12, and 18 pass without broadening scope. |
| R3 | Recovery plans, checkpoint checks, replacement, and supported pending changes. Depends on project declarations and Results completeness. | Scenarios 8–11 pass, including uncertain outcomes. |
| R4 | One-off schedules, missed-window handling, versioned approvals, and worker leases. Depends on durable dispatch idempotency. | Scenarios 13–16 pass across controller restart. |

| Spike | Question | Recommended approach | Fallback | Completion gate |
| --- | --- | --- | --- | --- |
| Scheduler mutation | Which Unity fields and scopes support safe state-dependent updates? | Read-only policy/version survey, typed adapter, then isolated scheduler fixture tests. | Disable in-place edits and offer replacement. | Capability table plus race tests show exact permitted scopes. |
| Array cancellation | Can exact task cancellation avoid affecting unsplit siblings? | Adapter resolves scheduler records and proves scope with version-specific fixtures. | Explicit whole-group cancellation only. | No sibling cancellation in all supported array states. |
| Restart identity | Which restart counter uniquely separates externally requeued job activity? | Preserve scheduler restart metadata and attempt observation segments. | Mark history uncertain and prohibit automatic recovery. | Requeue fixture never merges incompatible log/output histories. |
| Checkpoint safety | Can each project operation resume without overwriting evidence? | Project adapter declares compatibility and copy-to-new-output behavior. | Retry from immutable inputs. | Interrupted writer and incompatible checkpoint tests fail closed. |
| Log transport | Which bounded access method serves remote logs through the controller? | Extend the project management adapter with exact attempt paths and byte cursors. | Explicit retrieval then local preview. | Truncation, large files, missing streams, and path escapes pass. |

Deferred features include recurring schedules, automatic reassignment, automatic retries, interactive shells, arbitrary scheduler commands, cross-cluster migration, and predictive start guarantees.
The specified read, review, cancellation, recovery, and one-off schedule workflows remain deliverable without these features.
