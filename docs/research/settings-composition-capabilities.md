# Settings and composition capability review

Research date: 2026-10-03. Read-only source inspection for the remaining workspace design.
The repository contains concurrent Experiments implementation work and unrelated uncommitted changes.
A source module in this report does not establish a deployed or integration-tested capability.
No application code, setup skill, project settings, or cluster state changed for this review.

## Scope and source hierarchy

The accepted [Experiments specification](../design/experiments-spec.md) and [decision record](../design/project-workspace-plan.md) govern Q1–Q23.
The [Experiments build plan](../design/experiments-build-plan.md) supplies delivery dependencies.
Existing [connection research](project-connection-harness.md) and [tool research](project-workspace-tools.md) supplied the initial evidence map.
This review then inspected repository and project source directly.

[ADR 0001](../adr/0001-two-component-split.md) preserves the controller and ledger boundary.
[ADR 0008](../adr/0008-project-workspace-and-approved-executions.md) now records implementation contracts for approved executions.
It selects workspace routes, SQLite storage, immutable bundles, and legacy primitive mappings.
That ADR exists alongside concurrent code additions. Its engineering choices are not additional user-approved Q decisions.

The older [glossary](../../CONTEXT.md) still defines `ml` as a primitive and `multi-gpu` as independent fan-out.
The accepted workspace baseline and ADR 0008 explicitly revise those workspace semantics.
The new specifications preserve historical and legacy meanings while using the accepted workspace names.
The earlier five-primitive and no-sequenced-work decisions remain relevant to legacy contracts only within the scope of ADR 0008.

## Observed capabilities and gaps

| Capability | Primary evidence | Observation | Required remaining work |
| --- | --- | --- | --- |
| Attachment maintenance | [registry](../../controller/registry.py), `attach`, `update`, `detach` | Registry stores paths, primitive, remote root, host, resource defaults, and sync policy. File locking and atomic replacement exist | Expected-version settings changes, reviewed maintenance scope, active-work guards, relocation identity checks |
| Existing project HTTP | [HTTP](../../controller/http.py), `_project_route` | Project PATCH writes attachment fields and updates a client stub. DELETE detaches | Transactional maintenance preview, idempotent apply, migration journal, conflict recovery |
| Legacy Sync | [dispatcher](../../controller/dispatch.py), `sync` | `sync_policy=disabled` rejects generic Sync | Preserve this boundary in project Settings and Files. Snapshot upload must remain a separate operation |
| Connection declarations | [connection reader](../../controller/workspace_connection.py), `validate_connection` | New schema-1 reader validates relative paths, source closure declaration, typed parameters, argv operations, workflow dependencies, and cycles | Typed input ports, cardinalities, schema compatibility, purpose restrictions, operation versions, graph composition |
| Dynamic choices | [connection reader](../../controller/workspace_connection.py), `load_connection` | Declared choice readers use literal argv, local working directories, 1–30 second deadlines, and at most 10000 returned choices | Cached facts and visible reader freshness, bounded output-byte handling, reliable invalidation of reviewed choice values |
| Workspace persistence | [workspace store](../../controller/workspace_store.py) | New SQLite record store uses transactions, expected-version conflicts, experiment revisions, archive, and stable IDs | Maintenance transaction semantics and composition graph revisions must use this boundary |
| Snapshot transport | [workspace dispatcher](../../controller/workspace_dispatch.py), `stage_bundle` | New transport copies the reviewed plan bundle, rejects symlinks, and avoids project-wide Sync | Composition must reuse the bundle, not upload mutable project roots |
| Workspace Settings UI | [workspace UI](../../controller/web/src/modules/workspace/Workspace.tsx), `ProjectConnection` | New component shows declaration details and sync policy. It explicitly describes broader Settings as planned | The four complete Settings sections and action reviews |
| Workspace frontend contracts | [workspace API](../../controller/web/src/modules/workspace/api.ts) | New typed client names experiments, drafts, plans, executions, metrics, and resources | Typed ports, versioned operation definitions, composition capability negotiation |
| Global access maintenance | [global Settings](../../controller/web/src/pages/SettingsConfigPage.tsx) | Global page already exposes telemetry source, SSH alias/identity, probe, and key unlock | Project page links these controls without presenting them as project-only settings |
| Legacy metric declarations | [metric reader](../../lib/metrics.py) | `metrics.json` declares primary ranking, report columns, and labels | It cannot supply units, collector costs, cardinality, provenance, or scientifically valid aggregation rules |
| Artifact retrieval | [dispatcher](../../controller/dispatch.py), `fetch` | Scheduler logs and project hook return separate results | Selected-artifact contracts and per-artifact provenance remain required |
| Scaffold ownership | [scaffold](../../lib/scaffold.py), `plan`, `apply` | Generator has generated-file and backup handling. Existing setup preservation work is concurrent | A Settings migration must still preview exact ownership and refuse unsupported replacement |

The new workspace connection reader advertises workflows, analyses, and plots from declaration keys.
That list alone does not prove that every listed capability supports validation, execution, and UI presentation.
Settings therefore combines declaration support, controller support, and checked dependencies into effective action availability.

During the first source read, HTTP did not yet contain workspace route wiring.
Other workspace modules appeared during the session.
The final implementation plan must reconcile against the completed baseline rather than treat this snapshot as a release inventory.

## Project-specific evidence

The thinking-trace project has real scientific entrypoints and report generators.
The [original runner](the attached research project/harness/run_traces.py) exposes parameters and writes records with manifests.
The [TLAiBench runner](the attached research project/tlaibench/run_traces.py) adds stages, parent artifacts, samples, token caps, and turn details.
These entrypoints support declared operation bindings. They do not establish a generic typed graph contract.

The [report reader](the attached research project/tlaibench/report.py) scans records and tracks seen record IDs across directories.
The prior connection review identifies the token-cap omission in record identity.
Therefore, composition cannot assume that isolated output directories alone preserve separate comparison conditions.
A selected-artifact adapter must preserve execution and variant identity before deduplication.

The [artifact hook](the attached research project/unityHPC/fetch.sh) pulls both corpora and keeps backups of changed local files.
It reports partial failure across its transfers and tells the operator to validate separately.
It does not scope transfer to one reviewed execution or regenerate scientific summaries.
The Settings capability table must distinguish broad legacy Fetch from scoped workspace retrieval.

The existing report entrypoints support analysis adapters.
The [connection review](project-connection-harness.md#existing-building-blocks) found no reusable plotting entrypoint in its source catalog.
A chart feature can consume declared numeric fields, but a project-specific scientific plot remains a project capability until code supplies it.
The design must never advertise an undeclared plotting operation as ready.

## Design conclusions

Settings can maintain attachment facts without claiming to own project science.
A versioned field patch can change portable defaults while preserving unrelated declaration keys and external edits.
Controller-local path and alias changes need a separate maintenance preview because they affect historical access and active work.
The recommended first delivery requires project quiescence for connection relocation and detach.

Composition extends the existing plan compiler and history model.
It needs versioned typed ports, explicit per-variant/shared/reducer scope, finite expansion, and isolated outputs.
An ordered-card editor supplies a practical interface without requiring a free-form graph drawing tool.
Its graph preview must match the exact dependencies in the reviewed plan.

New metrics divide into existing-field analysis and additional collection.
The UI can select declared fields and allowed aggregations.
Scientific calculations, collector code, and plotting source remain project-owned.
New collection needs visible stages, costs, and explicit review.

No new runtime LLM, tracking vendor, second dispatcher, or scientific source generator is required.
These are design conclusions from the accepted ownership contract and inspected source, not claims about implemented features.
The detailed choices appear in [Settings](../design/settings-spec.md) and [composition](../design/composition-spec.md).

## Verification and concurrency record

Source inspection used targeted file reads and symbol searches.
No application test, migration, connection probe, or cluster command ran for this report.
Documentation verification covers cross-document contracts and the bundled Simple English descriptive linter.
The source fingerprints below identify the sampled files, not immutable repository commits:

```text
controller/registry.py
  ddfa2a2683dcf904bcd2c8c00c1d9393e6e3c01716556aec225112023b6537c3
controller/workspace_connection.py
  74214211d7be740bcf17da4ea4b0caa72d9890ed84f2673033113ffe00238477
controller/workspace_store.py
  483a848e3ed0557ed2d8c897f3612bb4918270f466c7bf5f52e385edac70a2c4
controller/workspace_dispatch.py
  62a80b2c62a6b0d8576cc5c2294cba0d0559aa9eb71fff1a476f9330a7306438
controller/web/src/modules/workspace/Workspace.tsx
  e50fa597ab708f15bbd5855823e52bb1ee5164056d19b4a04a471a651421a0de
lib/metrics.py
  c7857f7a9334f191d2ec1eb87b12aaed284f46ad3005bce97dc134c1c630d066
```

A later mismatch is expected during concurrent implementation.
Engineering must preserve the functional contract while adapting proposed extensions to the completed baseline schema.
