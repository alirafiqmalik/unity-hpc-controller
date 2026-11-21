# Workflow runner design

Status: implemented. The guided runner page uses the existing durable execution engine.
The dedicated project layout remains the home for every attached project.
The old research Overview is not the new landing page.

## Project page

An `llms-agents` project continues to open on Traces with its six current sections.
Other projects open on Workflow runner inside the same dedicated project layout.
The project header shows its name and declared application.
Home returns to the Projects list.

The global Cluster, User Jobs, and Settings pages remain available there.

Workflow runner is a supporting project page for every application.
The GenAI New evaluation form sends its workflow and dataset context through the runner interface.
Evaluation execution links and job evidence links open the same execution view.
Project controls remain accessible from the project header.
View docs opens a bounded viewer for the declared document, without the old Files page.

The page uses guided setup with a persistent stage summary.
The initial prototype compared this layout with a stage workbench and a combined setup/history layout.

## Workflow setup

The page starts with workflows from `unityHPC/project.json`.
Each workflow shows its title, purpose, execution location, and stage count.
The selected workflow supplies typed parameters, declared choices, defaults, and bounds.
The page preserves stage order, dependencies, operation identities, and declared resource requests.
Dataset selection follows the workflow parameter declaration.
The GenAI form retains its connector-specific dataset binding.
The generic runner does not require a GenAI connector.

The guided flow has four steps:

1. Workflow: select a project-declared workflow.
2. Setup: set the run name and workflow parameters.
3. Review: inspect checks, exact stages, resources, source, inputs, and outputs.
4. Run: follow execution status, attempts, job references, logs, and output checks.

Check setup does not dispatch work.
Approval starts only the checked, frozen plan shown in Review.
A setup edit invalidates the prior check and plan.
The page retains execution history when the live project declaration is invalid.
A project with no workflows shows connection guidance inside its project page.

## New runner interface

`controller/runner.py` owns the runner interface.
`controller/runner_http.py` exposes it under `/api/v1/projects/<slug>/runner`.
Pages do not create experiments or call the old workspace page endpoints directly.
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
It delegates preparation and approval to the runner module.
It preserves the existing response shape and workflow allowlist.
The generic runner derives allowed workflows from the project declaration.
The worker continues independently of browser sessions.

## Engine migration

The implementation places the existing durable engine behind the new runner interface.
It preserves approvals, submission receipts, frozen source, artifact hashes, existing schedules, and recovery history.
Historical records and approved bundles retain their existing identities and meaning.

## Project routes and cleanup

`/projects/<slug>/runner` configures and approves workflows.
`/projects/<slug>/executions` lists execution history.
`/projects/<slug>/executions/<id>` shows stages, attempts, bounded logs, and artifact downloads.
`/projects/<slug>/docs` shows the declared document through a bounded, escaped renderer.

The cleanup deleted the old research page modules and their browser suites.
The active execution contract lives at `docs/workspace-contract-v1.md`.
The backend retains workspace endpoints for existing execution contracts and compatibility.
The guided runner uses the new runner namespace.
The main checkout's separate edits remain outside this worktree change.

## Validation

The API tests cover explicit approval, repeat approval, changed-source rejection, frozen-source execution, and execution-scoped logs.
The browser tests cover guided approval, execution evidence, and bounded document rendering.
The GenAI launch tests also exercise the new runner interface.
TypeScript, ESLint for the runner and changed pages, and the production build pass.
