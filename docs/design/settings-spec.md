# Project Settings specification

Version 1, 2026-10-03. Final design for implementation planning.

## Authority and scope

The page maintains one attached project. It does not administer the cluster.
All decisions labeled S1–S8 below are agent-selected within the user's planning authorization.
They extend the accepted [Experiments specification](experiments-spec.md) without changing Q1–Q23.
[ADR 0008](../adr/0008-project-workspace-and-approved-executions.md) fixes the workspace storage and identity boundaries.
The [capability report](../research/settings-composition-capabilities.md) separates observed source from required work.
The [shared contract](remaining-workspace-spec.md) governs state mappings, identities, navigation, and action receipts across pages.

| Decision | Selected behavior | Rationale |
| --- | --- | --- |
| S1 | Settings contains Connection, Defaults, Capabilities, and Compatibility sections | Maintenance stays separate from experiment work |
| S2 | Connection health consists of independent facts with observation times | Valid declarations do not establish cluster access |
| S3 | Defaults affect new drafts or explicit draft updates only | Saved and approved work must remain reproducible |
| S4 | Project declarations remain project-owned, with reviewed field patches | Settings cannot replace scientific files or adapters |
| S5 | Application, primitive, and execution mode remain separate | Preserve accepted ML and coordinated-rank semantics |
| S6 | Connection changes use preview, conflict checks, and explicit activation | Paths and credentials affect more than the visible page |
| S7 | Migration preserves history and supports a checked rollback | Old job identities must stay meaningful |
| S8 | Maintenance never cancels, retries, synchronizes, or dispatches work implicitly | Passive maintenance must not spend resources or lose evidence |

## Navigation and layout

Settings uses the dedicated project sidebar. Home occupies its accepted brand-header position and returns to `/jobs/project`.
The header names the project and Settings, with Application and default primitive below.
Four anchored sections occupy the main column. A right column shows maintenance status and recent changes.
On narrow screens, these columns stack. Section links, field errors, and action reviews support keyboard navigation.


Connection shows the slug, controller-host directory, cluster alias, remote directory, manifest path, and active connection revision.
The slug has no edit control. A directory on the controller host is not a directory on the browser device.

Connection facts include declaration validity, local path availability, runner compatibility, SSH access, and remote-root access.
Each fact shows its source, observed time, and error or capability limit.

Defaults shows application category, primitive, execution mode, execution location preferences, and compatible per-stage resource profiles.
Resource fields include CPU count, GPU count and class, nodes, ranks, memory, walltime, account, and partition preference where supported.
Variant concurrency is a separate field. It never becomes the coordinated rank count.
The page shows each effective value and its origin: controller policy, project declaration, or attachment compatibility value.

Capabilities lists declared operations, workflows, metrics, collectors, plots, checks, retrieval, recovery, and queue actions.
Rows expose version, support status, dependencies, and a reason when unavailable.
A declared feature is not usable until the controller supports it and its required dependencies pass.
Result schema and metric mappings are inspectable here. Scientific definition edits use project-owned files outside this page.

Compatibility shows controller version, manifest schema, store schema, scaffold version, and migration status.
It links migration previews, ownership differences, and backup evidence.
Global SSH keys and telemetry settings remain in global Settings. Project Settings links them with explicit controller-wide scope.
Project Settings does not duplicate credential entry or telemetry scheduling controls.

## Controls and effects

| Control | Availability | Effect and scope |
| --- | --- | --- |
| Check connection | Project registration exists | Run bounded local checks and an explicitly requested read-only remote probe. Return separate facts |
| Reload declarations | Controller-host directory is accessible | Read and validate current declaration bytes. Show differences before activation |
| Edit connection | No conflicting maintenance action | Stage a path or alias change. Save creates a maintenance preview |
| Save defaults | Valid changed fields and matching revision | Save one reviewed field patch. List affected future drafts |
| Apply defaults to draft | An editable draft exists | Open Experiments with a differences preview. Save a new draft version after human acceptance |
| Preview migration | A supported migration exists | Show mappings, changed generated files, preserved files, backup scope, and rollback conditions |
| Activate migration | Preview remains valid and project is quiescent | Apply only the checked migration after the human approves its exact patch |
| Relocate attachment | No active, scheduled, uncertain, or locally running work | Preserve slug, validate the target directory, and preview identity and artifact-path differences |
| Detach project | Same quiescence guard as relocation | Remove attachment after explicit scope review. Preserve source, ledgers, workspace store, and artifacts |
| Inspect declaration / adapter | File is available | Open the scoped Files preview. No automatic edits |

A remote probe checks authentication, directory visibility, and required command availability only.
It does not create directories, install environments, regenerate scaffolds, or submit a smoke test.
Expensive scientific checks belong to Check setup or a reviewed smoke-test stage.
A check result reports its deadline and any steps that did not run.

Save defaults uses an explicit button. It does not use experiment autosave semantics.
Default precedence is: explicit stage override, saved workflow value, compatible project default, supported controller fallback.

The compiler records the selected origin and effective value for every resource field.
Fallbacks cannot supply mandatory scientific inputs or convert unsupported execution modes.
Existing drafts retain their materialized values. The UI offers an explicit differences preview to adopt newer defaults.

A changed declaration digest invalidates undispatched reviews, even when their effective values remain the same.
This rule preserves the accepted check-and-review requirement for declaration changes.
Settings changes preserve already dispatched executions' snapshots and resource requests.
Explicitly reviewed queue changes in Runs retain separate effective-request history.

Changing a remote root or cluster alias blocks new dispatch until the new connection passes checks and the human activates it.
The first delivery requires project quiescence for these changes. It does not move live jobs or outstanding retrievals.
An active schedule also blocks relocation. The human must first cancel the schedule through Runs.

A retained historical artifact keeps its original origin locator. Relocation updates checked local mappings without rewriting provenance.

## State model and edge cases

Connection state combines independent facts. It never becomes a permanent green badge.
`unknown → checking → ready | degraded | unavailable` describes the latest check session.
Declaration state is separately `missing | invalid | compatible | unsupported`.
Freshness is separately `current | stale`, with an observation timestamp.
A valid local declaration and failed SSH probe produce Degraded, with local drafts and historical Results still accessible.

A settings edit follows `clean → editing → preview → applying → saved`.
Invalid fields remain in Editing. A stale revision produces Conflict and preserves visible edits.
A failed apply remains Failed until reconciliation establishes whether the revision changed.
The UI never invites a second apply while its outcome is uncertain.

| Condition | Required behavior |
| --- | --- |
| Empty attachment | Show missing fields and the connection contract. Keep historical or legacy job links when available |
| No manifest | Show legacy capabilities honestly. New workspace dispatch remains unavailable |
| Loading | Retain section layout. Disable mutations until current revisions arrive |
| Stale capability observation | Keep the last facts with timestamps. Refresh before a dependent mutation |
| Controller unavailable | Retain visible unsaved edits. Show cached data as stale and disable saves |
| Local path unavailable | Preserve registration and history. Offer relocation preview, never automatic reattachment |
| Partial check success | Show each successful and failed check. Do not label the entire connection Ready |
| Partial migration or uncertain write | Lock dependent mutations, expose transaction evidence, and require recovery or rollback |
| External declaration edit | Show old, external, and staged values. Never overwrite unknown fields or scientific definitions |
| Unknown schema version | Read safe legacy history when possible. Block compilation, migration, and mutation without a supported reader |
| Unsupported queue action | Show the reason and any supported alternative. Do not expose a nonfunctional action |
| Failed authentication | Link global access maintenance. Do not put credentials into drafts, logs, or snapshots |

Capabilities expire according to their advertised freshness contract.
Remote action availability also requires a fresh action-time state check in Runs.
Cached capability support alone never authorizes a scheduler mutation.

## Data contracts and ownership

All resource names below extend `/api/v1/projects/{slug}/workspace` and require implementation.
Exact route suffixes can share existing baseline resources, but these semantics are required.

| Resource | Required fields |
| --- | --- |
| Settings revision | Stable revision, expected version, effective defaults, origins, declaration digest, actor, timestamp |
| Connection facts | Fact ID, status, evidence source, observed time, expiration, error code, remediation link |
| Capability | Stable ID, declared version, supported version, availability, reason, required dependencies, action scope |
| Maintenance preview | ID, expected registry version, declaration digest, store version, exact patch, affected plans, protected files, expiry |
| Maintenance action | ID, preview ID, idempotency key, state, actor, before/after references, completed steps, remaining steps |
| Migration record | Source/target versions, mappings, source digests, backup manifest, verification results, activation and rollback history |
| Artifact relocation map | Original locator, checked local locator, digest evidence, connection revision, unchanged artifact ID |

Suggested endpoints are `settings`, `connection/checks`, `connection/preview`, and `maintenance/<id>`.
Settings PATCH requires an expected version. Preview activation requires a preview ID and idempotency key.
Errors contain a field or capability ID, stable code, scope, and human-readable correction.
Authentication errors cannot expose secret values or shell environment dumps.

`unityHPC/project.json` owns portable defaults and operation declarations.
The attachment registry owns controller-local directory and connection references.
The workspace store owns maintenance history, previews, approvals, and draft links.
Generated bundles and workspace store form the backup unit specified by ADR 0008.
No automatic retention deletes workspace history or research artifacts.

Settings edits only the supported fields in the project declaration.
An atomic compare-and-replace uses the exact prior digest and preserves all unrelated keys.
Custom source, runners, tests, analyses, plots, `.env`, bootstrap hooks, and custom fetch/sync adapters remain protected.
A scaffold update preview must list every generated file and identify local divergence.
Diverged project-owned files block replacement until a specific migration handles them.
Settings does not silently re-scaffold to repair a version mismatch.

## Compatibility and migration

The accepted migration is semantic, not a historical relabeling:

| Stored value | Workspace interpretation |
| --- | --- |
| `ml` | Primitive `multi-gpu`, execution mode `coordinated`. Application comes from its own declaration |
| `multi-gpu` | Primitive `multi-gpu`, independent experiments mode |
| `gpu` | Remains valid. Preserve one-allocation semantics |
| `multi-cpu` | Independent CPU tasks |
| `cpu` | One CPU allocation |

For `llm-thinking-trace`, the new workspace default is `multi-gpu` with independent experiments, as previously accepted.
An `ml` attachment does not prove that the application's category is ML.
Historical ledger values, job IDs, campaigns, fan-out groups, and execution IDs remain unchanged.
Legacy CLI and catalog routes retain their old interpretation during transition.

Migration follows `available → previewed → blocked | ready → applying → checking → active`.
Failure enters `recovery_required`, with the last completed step and backup identity.
Activation requires a quiet project, a complete backup, checked restore evidence, and unchanged preview inputs.
During a store migration lock, the controller cannot advance scheduled or approved work.

Rollback restores the matching declaration, registry references, store, and bundle mappings as one documented operation.
An older controller cannot advance newer executions. It retains legacy observation where compatible.
If post-migration records exist, rollback must preserve them separately and fail closed instead of deleting them.
Detach does not serve as rollback and never deletes the backup unit.

## Acceptance and verification

1. Given concurrent declaration edits, Save defaults returns a conflict and preserves both versions without a partial field overwrite.
2. Given a queued execution, new defaults change a new draft but preserve the queued source, resources, and outputs.
3. Given an `ml` attachment, migration shows coordinated mode and preserves every historical primitive and job ID.
4. Given an unavailable SSH key, local history opens and Connection shows the failed remote fact with its timestamp.
5. Given a custom sync/fetch adapter, migration preserves its bytes and never enables disabled Sync.
6. Given active or uncertain work, relocation and detach remain blocked with exact blocking identities and links.
7. Given a restart during activation, the controller reports one maintenance action and reconciles it before another write.
8. Given an unknown schema, Settings reports the unsupported version and cannot dispatch through a guessed compatibility mapping.
9. Given the same controller in two browsers, an expected-version conflict prevents one settings form from replacing the other.
10. Given a backup restore fixture, historical links resolve and newer records never disappear under an older controller.

These scenarios require fixture directories, stubbed connection probes, and temporary stores.
They require no live cluster jobs for contract verification.
A later deployment check can exercise authorized read-only connection probes separately.

## Delivery and technical gates

| Phase | Dependency | Deliverable and gate |
| --- | --- | --- |
| S-A | Accepted Experiments connection reader and workspace store | Read-only sections, independent health facts, capability errors, protected ownership display |
| S-B | S-A and revision contract | Defaults patch, explicit draft adoption, conflict recovery, unchanged-execution tests |
| S-C | Runs active/scheduled/uncertain-work inventory | Maintenance previews, relocation, safe detach, migration journal and rollback |
| S-D | Composition and Results contracts | Typed operation and metric capability inspection, schema compatibility details |

Spike S-T1 asks how one maintenance operation spans registry, manifest, SQLite, and bundle references.
The recommended approach is a durable journal with a project lock, backups, atomic file replacement, and resumable steps.
The fallback exposes read-only compatibility and an exported maintenance plan until an operator-driven migration completes.
Completion requires fault injection after every step and recovery without lost history or duplicate activation.

Spike S-T2 asks which connection facts the controller can probe without project-specific side effects.
The recommended approach uses fixed read-only probes with per-step deadlines and structured results.
The fallback reports only local facts and marks remote capabilities Unknown.
Completion requires unsupported-command, timeout, and authentication fixtures without any remote writes.

Deferred features are browser editing of scientific definitions, credential storage inside projects, automatic scaffold repair, and live connection relocation.
Automatic retry policies and cluster-wide administration remain outside project Settings.
