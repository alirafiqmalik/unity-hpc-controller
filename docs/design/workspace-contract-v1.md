# Workspace contract v1

The implementation uses Python standard-library validation and SQLite schema version 1.
The accepted behavior is in `experiments-spec.md`. ADR 0008 records ownership and migration decisions.

## Project connection

`unityHPC/project.json` requires `schema_version: 1`.
The connection reader returns `{valid, errors, manifest, digest, capabilities}`.
Each error has a field and message. Planning errors can also identify a variant, stage, or artifact.

| Field | Contract |
| --- | --- |
| `application` | Project application category, separate from primitive |
| `default_primitive`, `default_mode` | Workspace default resource family and execution mode |
| `source_paths` | Relative source/configuration closure, including imported local modules |
| `environment` | Runtime definition path/version and protected `secret_paths` |
| `parameters` | Map of typed fields: `string`, `integer`, `number`, or `boolean` |
| `operations` | Map of literal `argv`, `cwd`, `location`, `version`, and bounded timeout |
| `workflows` | Map of parameter sets, defaults, stages, checks, and available metrics |
| `inputs` | Relative paths with checked hashes or declared immutable versions |
| `metrics` | Source fields/collectors, units, definitions, grouping, aggregation, and collection requirements |
| `analyses` | Named analysis operations and compatible input/output schemas |
| `resume` | Explicit operation mappings, checkpoint checks, and compatibility parameters |
| `ownership` | Project source, generated directories, and protected outputs |

An argument is a literal string, `{param: name}`, or `{context: name}`.
Contexts include project/source roots, output directory, execution/variant/stage identities, purpose, selected inputs, and checkpoint directory.
Shell punctuation remains literal argument data. Generated scripts call project code and contain no scientific calculations.

A stage declares its operation, dependencies, purpose, input/output connections, scope, and resources.
Resources include primitive, mode, CPUs, GPUs, nodes, ranks, memory in GiB, walltime, and optional scheduler placement fields.
Coordinated stages require an explicit `srun` launcher declaration. Independent stages do not receive implicit rank launchers.
Controller stages use one CPU node and bounded process groups. They receive no scheduler job IDs.

## Stored records

Each project uses `controller/workspaces/<slug>.db` inside the controller data directory.
`PRAGMA user_version=1` identifies the schema. Unknown versions stop writes.
The `records` table keys JSON documents by `(kind,id)`. `dispatch_keys` uniquely maps approval keys to plans and executions.
SQLite transactions use full synchronization and serialize read-modify-write operations.

| Record | Required identity and content |
| --- | --- |
| Experiment | ID, draft, version, revision, archive flag, execution links, timestamps |
| Revision | Experiment ID, revision number, frozen draft |
| Plan | ID, configuration, source/input identities, scripts, resources, checks, variants, metrics, artifact references |
| Execution | Plan ID, approval time, campaign, stages, attempts, outcomes, lineage |
| Artifact | Execution/stage/attempt IDs, purpose, schema/version, completeness, file hashes, provenance, report paths |

Draft updates require `expected_version`. Conflicts return HTTP 409 without replacing the saved draft.
Dispatch freezes the current revision. A later edit advances its revision number.
Plans have fresh IDs and outputs. Repeated approval of one plan returns its existing execution, even with another approval key.

Attempt states include `waiting`, `submitting`, `accepted`, `running`, `fetching`, `completed`, `failed`, `rejected`, and `uncertain`.
Recovery can supersede covered waiting stages and link them to the approved continuation.
An uncertain submission requires a ledger receipt before recovery can name and reuse accepted work.
A missing receipt does not authorize resubmission.

## HTTP

All routes below use `/api/v1/projects/<slug>/workspace`.
Single-resource responses contain the resource directly. List responses use the named plural array.
Errors contain `error` and, when available, structured `errors`.

| Method | Route | Body or result |
| --- | --- | --- |
| GET | `/connection` | Validated declaration, capability errors, migration preview |
| GET, POST | `/experiments` | List or create with workflow/name/draft |
| GET, PATCH, DELETE | `/experiments/<id>` | Read, autosave with expected version, or delete unused draft |
| POST | `/experiments/<id>/clone` | Optional visible draft for conflict recovery |
| GET, POST | `/experiments/<id>/revisions` | Frozen revisions or new draft revision |
| POST | `/experiments/<id>/archive`, `/restore` | Preserve history and files |
| POST | `/experiments/<id>/check` | Bounded controller-host setup checks |
| POST | `/experiments/<id>/plans` | Compile a fresh reviewed plan |
| GET | `/plans/<id>` | Exact plan and inspectable scripts |
| POST | `/plans/<id>/dispatch` | `{idempotency_key}`; persist approval and return execution |
| POST | `/plans/<id>/custom-script` | `{stage_id,path}`; create and register protected project source |
| GET | `/executions`, `/executions/<id>` | Durable execution state and stage outcomes |
| POST | `/executions/<id>/recovery` | `{stage_ids,mode}`; review retry/resume and affected waiting descendants |
| POST | `/executions/<id>/reconcile` | Read ledger receipts without dispatch |
| POST | `/executions/<id>/fetch` | `{stage_ids}`; retrieve declared completed/failed outputs |
| GET | `/executions/<id>/logs` | Optional stage filter, explicit purpose/state/job linkage |
| GET | `/artifacts`, `/artifacts/<id>` | Indexed evidence and reports |
| GET | `/artifacts/<id>/file` | Indexed `path`, checked hash, bounded download |
| POST | `/analysis` | Selected artifact IDs, declared operation, parameters, and metrics |

`/analyses` is an alias for analysis revision creation/listing.
Experiment listing accepts `archived=true|false|all`. Execution and artifact lists accept their corresponding identity filters.

## Source and transport

Plan source inventories include current dirty file bytes, the declaration, local imports, and dispatcher/bootstrap definitions.
Secret environment files contribute hashes but their contents do not enter review data or bundles.
Source and artifact changes invalidate a new approval. Approved continuation verifies frozen bytes independently of live scientific edits.
Public effective runtime settings and full allocation scripts appear in cluster review.

Cluster transport uploads only the frozen plan bundle and exact indexed prerequisite/checkpoint files.
It does not call project-wide sync or overwrite custom adapters.
The frozen dispatcher receives the original project directory for its ledger and protected environment reference.
Scheduler options and the allocation template come from review. The existing dispatcher remains the ledger writer.

## Migration and recovery

The connection API reports the legacy attachment beside its workspace interpretation before any dispatch.
`ml` maps to `multi-gpu/coordinated`; legacy `multi-gpu` retains independent behavior.
The research connection selects `multi-gpu/independent` and application `ml`, while its historical `gpu` attachment remains valid.
No historical campaign, group, job, catalog identity, or purpose is rewritten.

Backup the workspace SQLite files, project declarations, and `.unity-workspace` directories together.
Archive does not cancel jobs or delete artifacts. Draft deletion does not run retention.
Older controllers must not advance workspace executions. Preserve the store and bundles during rollback.

Resume requires an audited project checkpoint operation and matching source, parameters, inputs, and runtime references.
It copies selected checkpoint records into fresh attempt outputs and preserves the original evidence.
At most one active resume attempt can use a selected checkpoint. Retry starts fresh without checkpoint reuse.
