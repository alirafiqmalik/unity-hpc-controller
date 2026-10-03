# Remaining project workspace specification

Version 1, 2026-10-03. Final design for implementation planning. No application or cluster changes form part of this work.

## Authority and reading order

The user approved the project layout and Experiments Q1–Q23 in [the decision record](project-workspace-plan.md).
The [Experiments specification](experiments-spec.md) remains that accepted product baseline.
All choices in this document and the linked remaining-page specifications are **agent-selected decisions** under the user's autonomous planning instruction.
They are final planning choices, not claims of earlier user approval or released behavior.

Read this shared contract first, then the applicable page specification:

| Deliverable | Scope |
| --- | --- |
| [Runs](runs-spec.md) | Monitoring, logs, dependencies, queue changes, cancellation, recovery, and future scheduling |
| [Results](results-spec.md) | Reports, plots, comparisons, samples, traces, completeness, and analysis revisions |
| [Files](files-spec.md) | Browsing, previews, artifact locations, retrieval, external editing, and sync boundaries |
| [Settings](settings-spec.md) | Connection maintenance, defaults, capabilities, compatibility, and migration |
| [Overview](overview-spec.md) | Research question, continuation, attention items, and evidence-linked conclusions |
| [Composition](composition-spec.md) | Typed project operations, artifact connections, and declared metrics beyond workflow presets |
| [Delivery plan](remaining-workspace-build-plan.md) | Shared dependencies, phases, technical gates, and release scenarios |
| [Editable board](project-workspace.tldr) | Preserved earlier work plus final wireframes and function diagrams on pages 10–19 |

The older documents' references to “later review” describe their historical boundary.
These specifications resolve that later scope without expanding the other agent's accepted Experiments delivery.
No Q1–Q23 amendment is required. Future scheduling adds a separate reviewed action after the initial delivery.
Composition extends the accepted declaration model. It does not replace initial workflow selection or cloning.

## Evidence and implementation status

Existing reports supply evidence: [connection review](../research/project-connection-harness.md) and [tool review](../research/project-workspace-tools.md).
Focused source reviews cover [Runs](../research/runs-capabilities.md), [Results and Files](../research/results-files-capabilities.md), and [Settings and composition](../research/settings-composition-capabilities.md).

The checkout contains concurrent changes. [ADR 0008](../adr/0008-project-workspace-and-approved-executions.md) pins the emerging workspace architecture.
Its presence establishes an implementation contract, not release verification.
Current source inspection found a connection reader, fixed catalog launches, ledger monitoring, cancellation, and fetch hooks.
The page specifications identify which additional services and capabilities they require.

Recheck the working implementation at each delivery gate. Do not infer completed work from an untracked module or a sketch.

## Decision register

| ID | Agent-selected decision | Reason and limit |
| --- | --- | --- |
| W01 | Preserve all seven sidebar destinations, with Home in the brand-header slot | Project entry opens Overview; Dispatch opens Runs filtered to the execution |
| W02 | Interpret “schedule reassign” as three distinct intents | Future dispatch, a pending request change, and replacement/recovery have different effects and identities |
| W03 | Use separate state dimensions | Scheduler success cannot establish corpus completeness, local availability, or scientific validity |
| W04 | Require exact operation scope and durable action receipts | Campaign and array-parent controls cannot impersonate narrower actions |
| W05 | Start Results at Reports; keep Plots, Compare, and Samples & traces inside Results | A saved report provides a reproducible entry into the evidence |
| W06 | Give original corpus and TLAiBench separate collections | Their identities and evaluators do not support a pooled score |
| W07 | Keep Files read-only; edit project source in its existing editor | Source changes require new checks and review; browsing must not trigger sync |
| W08 | Keep Settings as maintenance and future-default control | An edited default must not alter an existing draft, approved plan, or active job |
| W09 | Compose typed declared operations through an ordered stage editor and dependency preview | Avoid a second execution model and arbitrary shell-expression construction |
| W10 | Save conclusions as human-authored metadata with immutable evidence references | No generated scientific interpretation or automatic best-model claim |
| W11 | Use capability-gated writes and optimistic concurrency throughout | An unavailable backend must produce an explanation, not a decorative enabled control |
| W12 | Defer recurrence, automatic recovery policies, arbitrary metric expressions, and browser source editing | The completed core supports explicit human choices and deterministic continuation |

## Navigation and common layout

Use `/projects/:slug/overview`, `/experiments`, `/runs`, `/results`, `/files`, and `/settings` under the same project prefix.
Home returns to `/jobs/project`, restoring the prior list filters when available.
The project sidebar contains Home, Overview, Experiments, Runs, Results, Files, and Settings, in that order.
Home occupies the 52-pixel brand-header position. It is not a second navigation row below the brand.

The header names the project and current section. Application category and default primitive appear as context, not inferred execution facts.

Use stable entity IDs in URL filters and selection state. Display names can change without breaking links.
Shared query keys are `experiment`, `execution`, `variant`, `stage`, `attempt`, `purpose`, `campaign`, `collection`, and `artifact`.
Results also uses `view=reports|plots|compare|samples`, `analysis`, and `comparison`.
Page-specific contracts can add filters. Unknown filters produce a visible reset option. They must not silently select another execution.

Cross-page links preserve relevant identities. They drop incompatible filters and name any scope change.
Browser Back restores selection and filters. A missing entity shows its ID and an explicit recovery link.

Pages can contain content-level subviews. Horizontal project-section tabs remain absent.
On narrow screens, collapse the sidebar and stack details after the selected row. Keep identity, purpose, and state visible.

All controls need keyboard access, visible focus, accessible names, and text equivalents for color or graph state.
Tables support pagination. A graph always has an equivalent dependency list.

## Identity, terminology, and ownership

The accepted terms Experiment, draft revision, reviewed plan, variant, execution, stage, attempt, research run, and analysis revision retain their definitions.
Campaign remains a grouping label. Group remains one fan-out submission. Neither replaces experiment or execution identity.

ML is an application category. `multi-gpu` supports independent experiments and coordinated ranks as explicit modes.
Variant concurrency limits active variant chains. Rank count describes cooperation within one stage allocation.
Controller-host operations have process activity identities and no invented scheduler job ID.

| Entity | Required reference and lifetime |
| --- | --- |
| Project | Stable attachment slug; root and connection revisions can change through maintenance |
| Plan | Immutable ID, revision, source/declaration/input digests, scripts, graph, resources, outputs, and approval scope |
| Execution | One approved plan; one dispatch intent; links to experiment revision and every stage attempt |
| Stage | Stable node within a plan; variant or shared scope, operation, purpose, dependencies, and resource snapshot |
| Attempt | One performance of a stage; links to ledger jobs or controller activity and previous recovery lineage |
| Scheduler reference | Cluster identity, job ID including array task suffix, campaign, submission time, and ledger reference |
| Artifact | Immutable logical ID and content/version identity, producer attempt where known, schema, purpose, and physical locations |
| Analysis revision | Exact input artifact versions, operation/metric definitions, source, parameters, and fresh output identities |
| Comparison | Saved selected analysis/artifact revisions, alignment policy, metric definitions, exclusions, and baseline |
| Research note | Human-authored versioned text with stable experiment, comparison, sample, or artifact references |

Job IDs can recur across cluster history. A job number alone is never a global identity.
Artifact paths can move or contain new bytes. A path alone is never an immutable evidence reference.

Legacy and imported artifacts retain explicit Unknown provenance slots. Import identity never fabricates a producer attempt or source snapshot.
Project result adapters own scientific identity and interpretation. Generic services own storage, jobs, retrieval, and display contracts.

Follow ADR 0008: workspace routes use `/api/v1/projects/{slug}/workspace` and storage uses `controller/workspaces/<slug>.db`.
Plans and outputs use the declared `.unity-workspace` bundle structure. Do not invent a second metadata store for another page.

The store and bundles remain one backup unit. Protect historical and selected evidence from automatic deletion.
Page route names in these documents specify target contracts. They do not assert that HTTP handlers already exist.

## Shared state and action contract

Every response carries entity version, source revision, and freshness for the facts it presents.
Use `observed_at`, `stale_after`, `source`, and `availability` per domain: scheduler, progress, artifacts, connection, and capabilities.
The service supplies the age threshold according to its collection cadence. Browser polling never resets the observation time.
`fresh`, `stale`, and `unavailable` describe observations, not workload outcomes.

| Dimension | Required distinction |
| --- | --- |
| Submission | Awaiting submission, submitting, accepted, rejected, uncertain |
| Scheduler | Raw scheduler state and normalized category, with reason and observed time |
| Coordinator | Waiting for prerequisite, eligible, active, paused, canceled, completed |
| Data completeness | Unknown, checking, partial, complete, invalid, with expected/observed coverage evidence |
| Artifact location | Local, remote, both, missing, or unknown; each copy has its own version |
| Retrieval | Not requested, queued, transferring, verifying, complete, partial, failed, canceled |
| Analysis activity | None, draft, checked, reviewed, queued, running, succeeded, failed, canceled; submission uncertainty remains separate |
| Report currency | Current, earlier inputs available, input changed, or unknown; every completed revision remains immutable |
| Purpose | Experiment or Smoke test; legacy absent values display Unclassified |

These are display dimensions, not a requirement to replace baseline storage enums.
Service adapters map their raw states to them without discarding the original state or reason.

Files' `succeeded` transfer maps to Complete retrieval. `running` maps to Transferring. `idle` maps to Not requested.
Files' `unavailable` location means no currently usable known copy. Unknown means that observation cannot establish location.

Integrity remains separate: Unchecked, Checked, Mismatch, or Changed. Completeness comes from the project's scientific check.
Files and Settings use Current for a fresh observation. They map that label to the shared `fresh` value.
A failed new analysis can coexist with a readable earlier report. Neither fact replaces the other.

Executions summarize child counts and blockers. An aggregate status never conceals failed, uncertain, or omitted children.
Results use explicit scientific outcome fields. A valid negative model outcome does not become an execution failure.

New write actions follow this sequence:

1. Prepare a preview against `expected_version`, exact IDs, current capability revision, and observed resource state.
2. Show affected children, unchanged evidence, differences, dependencies, output paths, and costs that the service can establish.
3. Confirm the action with the preview ID and an idempotency key.
4. Revalidate scope and prerequisites at commit. A conflict returns HTTP 409 with the current version and no expanded action.
5. Return a durable operation receipt with per-target accepted, rejected, skipped, or uncertain outcomes.
6. Reconcile uncertain outcomes before allowing another conflicting action.

Autosave and human note edits need version checks but do not need a full execution review.
Bulk selection stores concrete IDs, including the selected pages of a paginated table. “All matching” requires an explicit frozen selection preview.
An unsupported exact scope must remain disabled. The service cannot substitute a campaign or array parent.

Use the controller and existing ledger writer for all cluster actions. New scheduler mutations require audited management support through that boundary.

## Common failure and automation rules

Initial loads show skeletons and a named loading operation. A refresh keeps existing content with its observation time.
Empty means a successful query found no matching records. Unavailable means the query cannot establish the answer.
A partial response preserves successful rows and gives a retry action for the failed scope.
An expired cursor restarts the listing with notice. It must not silently mix different snapshots.

Source, connection, or capability changes invalidate dependent action previews. They do not rewrite history.
Offline writes retain form edits locally in the open view and show Unsaved. They do not queue an invisible future dispatch.

Opening pages, filtering, browsing, and refreshing never dispatch, cancel, migrate, edit source, or change resources.
Only a reviewed execution authorizes its declared continuation, retrieval, checks, analysis, and plots.
Failed stages pause affected dependents. Independent branches can continue within the existing approval.

There is no automatic retry, replacement, partition reassignment, new collection, or evidence-based scientific conclusion.
One-off schedules require their own explicit approval and expiry policy. Recurring scientific dispatch remains outside this delivery.
Shorter walltime never guarantees an earlier start. Eligible-after times are lower bounds, not reservations.

## Cross-document acceptance

- The same execution, stage, attempt, purpose, and artifact identities resolve across all six pages and global job details.
- A smoke test retains Purpose after retry and stays out of research aggregates while contributing to resource accounting.
- A complete corpus behind a failed scheduler exit is visible evidence. It never releases a failed `afterok` dependency automatically.
- A new analysis revision preserves old reports and cannot trigger missing generation without another explicit collection plan.
- A changed default or source file cannot mutate an approved execution, pending job, or saved comparison.
- An unsupported action shows the missing capability and safe next step. The server independently enforces the same restriction.
- The four-variant accepted example retains both token-cap conditions through retrieval, indexing, report generation, and comparison.
- No record from one project, campaign, array sibling, or later output version leaks into a narrower confirmed action.

## Baseline amendment audit

This package proposes no amendment to Q1–Q23.
Settings migration follows the accepted mapping and ADR 0008. Composition follows Q2, Q5–Q8, and Q19–Q21.
Scheduling and queue changes are separate later capabilities. Initial Dispatch keeps the accepted meaning.
Pending request changes add an immutable resource-change event. They preserve the originally reviewed plan and record the human's later approval.
Legacy design decisions that ADR 0008 supersedes remain historical evidence, not a second target behavior.
