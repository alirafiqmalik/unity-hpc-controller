# Project workspace and approved executions

> **Superseded by [ADR 0009](0009-headless-campaign-controller.md).** The workspace modules, project registry, and scaffold templates were removed on 2026-10-08. Campaigns replace reviewed plans and executions.

Accepted implementation decision, 2026-10-03. Implements the accepted Experiments specification Q1–Q23.
This decision supersedes design decisions 3.4, 3.9, and 3.10 for the workspace API.
ADR 0001 still governs dispatch and ledger ownership.

## Ownership and storage

`unityHPC/project.json` is the project-owned connection declaration, with `schema_version: 1`.
It declares parameter types, operations, workflows, inputs, artifacts, metrics, checks, resource modes, and source paths.
Declared operations use argument vectors. The controller never discovers scientific operations from arbitrary source during execution.
Source paths include imported project code and small fixture or dataset files. Inputs outside that closure require checked immutable identities.

The controller stores each workspace in `$UNITY_HPC_DATA/controller/workspaces/<slug>.db`.
SQLite transactions serialize draft updates, plan records, approvals, attempts, and artifact indexing.
Draft writes require `expected_version`. A stale write returns HTTP 409 and preserves both the saved draft and the caller's visible edits.
Dispatch freezes a revision. Later editing creates another revision without changing dispatched history.

Each plan has a fresh ID and project directory `.unity-workspace/plans/<id>/` containing its source snapshot and wrappers.
Outputs use `.unity-workspace/outputs/<id>/<variant>/<stage>/`. One plan creates at most one execution.
Repeat compiles a new plan and therefore allocates fresh outputs. Recovery is a separate reviewed plan with explicit lineage.

The store and project `.unity-workspace` directory form one backup unit. Archive and unused-draft deletion do not remove project files.
No automatic retention applies to workspace history. Unknown store or manifest versions fail closed.
Relocation preserves the slug and relative paths. Re-review is required for plans whose runtime connection changed.
Rollback keeps the store and bundles intact. Older controllers can read legacy jobs but cannot advance workspace executions.

## Planning and source references

The compiler expands a workflow into concrete variants and a flat dependency graph.
A stage has one purpose, operation, execution location, effective resource request, output directory, and attempt identity.
Shared prerequisites have one graph node. Independent variants can each contain a stage chain.
Variant concurrency limits active variant chains. Coordinated rank counts belong to a stage allocation and remain separate.

The source snapshot captures declared file bytes, including relevant uncommitted changes, and a digest of every captured file.
The declaration belongs to that snapshot. Environment references retain fingerprints and versions, without copying secret values into public history.
A reviewed plan records its configuration, input identities, source digest, scripts, resource requests, exclusions, and metric definitions.

Dispatch rejects changed drafts, declarations, inputs, or source. Already approved work executes its frozen source.
The controller uploads the immutable bundle and exact indexed prerequisite files for cluster execution. It never invokes project-wide sync for this step.

## API boundary

Routes live under `/api/v1/projects/<slug>/workspace`.
`connection` reads capabilities. `experiments` provides draft CRUD, cloning, revisions, archive, restore, checks, and plan creation.
`plans/<id>` reads review data. `plans/<id>/dispatch` accepts an idempotency key and approves that exact plan.
`executions` exposes accepted, waiting, failed, and uncertain stages. `executions/<id>/recovery` prepares a scoped recovery plan.
`artifacts` lists selected execution outputs. `analysis` creates a reviewed analysis revision over complete saved artifacts.

Existing catalog and generic run routes keep their previous meaning.

## Durable continuation

The controller commits an execution and a submission intention before calling the dispatcher.
A process lock prevents concurrent workers from advancing the same project. The worker survives browser closure through controller ownership.
After restart, an interrupted submission is uncertain until its campaign and unique stage token reconcile with the ledger.
An absent ledger row alone does not prove rejection. Uncertain work cannot be automatically submitted again.

Accepted work keeps its job IDs. A rejected stage pauses its dependents while unrelated branches can advance.
Retries, resume, resource changes, and uncertain-outcome resolution require explicit reviewed scope.
Controller-host stages use bounded process groups and durable completion receipts.
A process lock survives supervisor failure while scientific work remains active.
Restart consumes a receipt or fences interrupted work before an explicit recovery.
These stages have no scheduler identities.

Artifact retrieval uses only declared output paths. Scheduler completion, retrieval success, and scientific completeness remain separate facts.
A complete corpus behind a failed job remains evidence for manual recovery, never automatic dependency release.

Analysis selects artifact identities and creates new outputs. It cannot silently rerun collection.
Purpose is explicit stage metadata and joins job records by campaign and job ID. Historical jobs remain Unclassified.

## Compatibility migration

Workspace primitive choices are `cpu`, `gpu`, `multi-cpu`, and `multi-gpu`.
Legacy `ml` maps to `multi-gpu` with `coordinated` mode. Application category remains a separate declaration.
Legacy `multi-gpu` maps to independent mode. Existing `gpu` attachments remain valid.
The connection declaration can select a workspace default without rewriting historical attachment, campaign, group, or job values.

A migration preview records old values and the new interpretation before activation.
Legacy CLI `--type ml` and its template remain supported. Downgrade must never reinterpret coordinated work as independent fan-out.
Custom sync and fetch adapters and existing environment files remain project-owned during setup updates.
