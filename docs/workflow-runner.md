# Workflow runner design

Status: implemented. The runner page uses the existing durable execution engine.
The dedicated project layout remains the home for every attached project.
Research tools retain the existing experiment editor and execution management pages.

## Project page

An `llms-agents` project continues to open on Traces with its six current sections.
Other projects open on Workflow runner before their first execution and execution history afterward.
The project header shows its name and declared application.
Home returns to the Projects list.

The global Cluster, User Jobs, and Settings pages remain available there.

Workflow runner is a supporting project page for every application.
The GenAI New evaluation form sends its workflow and dataset context through the runner interface.
Evaluation execution links and job evidence links open the same execution view.
Project controls remain accessible from the project header.
View docs opens a bounded viewer for the declared document.
Research tools also provide file management.

The page uses one prefilled setup form with a persistent stage summary.
The main checkout’s interface research informs this layout.

## Workflow setup

The page starts with workflows from `unityHPC/project.json`.
Each workflow shows its title, purpose, execution location, and stage count.
The selected workflow supplies typed parameters, declared choices, defaults, and bounds.
The page preserves stage order, dependencies, operation identities, and declared resource requests.
Dataset selection follows the workflow parameter declaration.
The GenAI form retains its connector-specific dataset binding.
The generic runner does not require a GenAI connector.

The setup form combines workflow selection, a run name, and typed parameters.
Check setup prepares the exact stages, resources, source, inputs, and outputs for review.
Explicit approval starts the frozen plan.
The execution view records status, attempts, job references, logs, and output checks.

Check setup does not dispatch work.
Approval starts only the checked, frozen plan shown in Review.
A setup edit invalidates the prior check and plan.
The page retains execution history when the live project declaration is invalid.
A project with no workflows shows connection guidance inside its project page.

## New runner interface

`controller/runner.py` owns the runner interface.
`controller/runner_http.py` exposes it under `/api/v1/projects/<slug>/runner`.
Runner pages use this interface. Research tools continue to use the workspace API.
The runner translates workflow setup into the execution engine's reviewed plan contract.
The [execution contract](workspace-contract-v1.md) retains the persistence and dispatch requirements.

| Method | Route | Role |
| --- | --- | --- |
| GET | `/workflows` | Validated workflows, parameter definitions, stage dependencies, and capabilities |
| POST | `/plans` | Check typed setup, run bounded project checks, and freeze a reviewable plan |
| GET | `/plans/<id>` | Retrieve that exact review, including blockers and check results |
| POST | `/plans/<id>/approve` | Approve the frozen plan with an idempotency key |
| GET | `/executions` | List workflow executions, with filters and pagination |
| GET | `/executions/<id>` | Stage states, attempts, job references, and output completeness |
| GET | `/executions/<id>/logs` | Bounded logs for an attempt of this execution |
| GET | `/document` | Bounded preview of the declared documentation path |
| GET | `/artifacts/<id>` | Checked artifact download with a sandboxed response |

Plan responses include `valid`, field errors, check results, source/input identities, and exact effective stages.
Approval rejects invalid plans and changed identities.
Repeated approval returns the existing execution instead of another submission.
Read requests never dispatch or implicitly run setup checks.

GenAI launch remains a compatibility adapter for its current form and dataset binding.
It delegates preparation to the runner module. The form then opens the frozen plan for explicit approval.
It preserves the workflow allowlist and dataset bindings.
Evaluation setup returns a prepared plan. Runner approval returns an execution.
The matrix form selects models and datasets, with available corpus subsets and splits.
Preparation freezes one plan per dataset, with separate model variants.
Each plan and its checks remain visible in the matrix review before explicit batch approval.
Unrestricted string model parameters accept manually entered model names.
Batch retries return existing approvals and approve only remaining plans.
The single-evaluation API still prepares a plan without approving it.

Evaluation removal hides selected rows from GenAI lists.
It retains source, results, artifacts, frozen plans, approval bindings, execution history, and scheduler receipts.
Research tools can still inspect the evidence.

The generic runner derives allowed workflows from the project declaration.
The worker continues independently of browser sessions.

## Engine migration

The implementation places the existing durable engine behind the new runner interface.
It preserves approvals, submission receipts, frozen source, artifact hashes, existing schedules, and recovery history.
Historical records and approved bundles retain their existing identities and meaning.

## Project routes

`/projects/<slug>/runner` configures and approves workflows.
`/projects/<slug>/executions` lists execution history.
`/projects/<slug>/executions/<id>` shows stages, attempts, bounded logs, and artifact downloads.
`/projects/<slug>/docs` shows the declared document through a bounded, escaped renderer.

Research tools preserve the main checkout’s revised experiment editor, recovery, schedules, results, files, and settings.
The existing browser suites continue to cover those pages.
`/projects/<slug>/research` opens experiment setup first and Runs after an execution exists.
The active execution contract lives at `docs/workspace-contract-v1.md`.
The backend retains workspace endpoints for existing execution contracts and compatibility.
The runner uses the new runner namespace.
The design specifications and delivery evidence remain in `docs/design/`.

## Validation

The API tests cover explicit approval, repeat approval, changed-source rejection, frozen-source execution, and execution-scoped logs.
The browser tests cover guided approval, execution evidence, and bounded document rendering.
The GenAI launch tests also exercise the new runner interface.
TypeScript, ESLint for the runner and changed pages, and the production build pass.
