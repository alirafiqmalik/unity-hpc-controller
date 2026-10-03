# Experiments workspace specification

Version 1, 2026-10-03. Status: accepted functional baseline for build planning.

The user accepted Q1–Q23 in the [decision record](project-workspace-plan.md).
This specification consolidates those decisions. It does not claim that the application implements them.
The [build plan](experiments-build-plan.md) separates engineering proposals from accepted product behavior.

## Scope and authority

The first delivery covers the dedicated project layout and the complete Experiments workflow for `llm-thinking-trace`.
Overview keeps the research question and its provisionally accepted layout.
Runs provides the execution destination and smoke-test identification required by Experiments.
Results provides links to the artifacts and reports produced by the approved sequence.

Detailed Results, Files, Settings, and queue-management designs still need their own review.
Automatic retries, resource reassignment, future schedules, and an unrestricted workflow graph editor are outside this baseline.
Initial creation uses project-declared workflows or cloning. Dynamic composition remains a planned extension of the same connection contract.

The [editable scratchpad](project-workspace.tldr) shows placement. This document defines behavior when illustrative labels omit detail.
Example models, resource requests, metrics, counts, and states in the wireframes are not live project facts.
Wireframe pages 02a–02d cover the accepted Experiments workflow. Page 08 explains the project connection.

## Project layout

Selecting an attached project opens its dedicated Overview route.
The project sidebar replaces the global UnityHPC sidebar. A separate browser tab is not required.
Home occupies the exact brand-header position used by **[U icon] Unity HPC / unity · live sync**.
Home returns to the UnityHPC Projects list, currently `/jobs/project`.

The project name sits below Home. The sidebar contains Overview, Experiments, Runs, Results, Files, and Settings.
The header shows the current section. Application and default primitive appear below it.
The principal action occupies the upper right. Project sections do not also appear as horizontal tabs.

The target primitive choices are `cpu`, `gpu`, `multi-cpu`, and `multi-gpu`.
ML is an application category. `multi-gpu` supports independent experiments and coordinated ranks as explicit execution modes.
The intended default for `llm-thinking-trace` is independent experiments under `multi-gpu`.
A stage can use a different compatible resource plan, including CPU analysis after GPU collection.

These choices revise the current five-primitive contract. Existing `ml` configurations represent coordinated execution, not an application declaration.
Migration must preserve that meaning. Historical records retain their original values.
The [build plan](experiments-build-plan.md#compatibility-and-migration) defines the migration work.

## Terms and identity

These terms describe the target workspace. Existing ledger terminology retains its current meaning.

| Term | Meaning |
| --- | --- |
| Workflow | A project-declared set of operations, parameters, artifact connections, checks, and defaults |
| Experiment | A named reusable study that can contain several variants and executions |
| Draft revision | An editable experiment configuration with autosaved values |
| Reviewed plan | The checked expansion of one revision, including source, inputs, scripts, resources, and outputs |
| Variant | One concrete combination of experiment parameters |
| Execution | One approved dispatch of a reviewed plan, with its own history and output identities |
| Stage | A declared operation within a variant or a declared shared prerequisite |
| Attempt | One attempt to perform a stage, including an explicit retry or resume |
| Research run | The project's output directory and manifest, distinct from a scheduler job |
| Campaign / group | Existing ledger concepts: a grouping label / one fan-out submission |
| Analysis revision | A new analysis of selected saved artifacts, with its own parameters, versions, and reports |

Two models and two token caps produce four variants. They do not necessarily produce four scheduler jobs.
Each variant can contain smoke tests, dependent collection stages, analysis, and plots.
Variant concurrency and coordinated ranks describe different limits and remain separate controls.

## Library: page 02a

Experiments opens the library. New experiment starts from a declared workflow.
Clone creates a separate experiment draft and retains its source reference.
The library shows name, workflow, configuration readiness, latest execution, and relevant actions.
Configuration readiness remains separate from execution state.
Search and filters cover workflow, readiness, and active or archived experiments.

| Action | Result |
| --- | --- |
| Continue editing | Open the saved draft |
| New revision | Start an editable revision without changing dispatched history |
| Clone | Create a separate draft from the selected experiment configuration |
| Repeat | Create a fresh execution through check and review, with fresh outputs |
| Resume / retry | Open a separate, compatibility-checked recovery plan with explicit scope |
| Archive | Hide the experiment from the active library while preserving history and files |
| Restore | Return an archived experiment to the active library |
| Delete unused draft | Delete an experiment draft that has no execution history |

An experiment with execution history uses Archive rather than Delete.
Archiving does not cancel active work, delete project files, or remove results.
Links from executions and artifacts continue to resolve after archival.
The Archived filter exposes Restore.

An empty library offers New experiment when declared workflows exist.
A missing or invalid connection explains the unavailable capability and provides a path to connection details.
The UI does not invent runnable operations from arbitrary files.

## Editor: page 02b

The editor groups fields by research context, data and models, variants, and stages and resources.
Measurements opens page 02c. Check setup and Review plan are separate actions.
Dispatch appears only on page 02d.

| Area | Required behavior |
| --- | --- |
| Research context | Name, workflow, human-written question or notes, selected outcome measure |
| Data and models | Project-declared choices, input references, versions, and required availability |
| Parameters | Typed fields with units, bounds, choices, defaults, and clear errors |
| Variants | All combinations by default, or explicit combinations, with the exact expanded list |
| Stages | Declared dependencies, input/output connections, and optional or mandatory smoke tests |
| Resources | Compatible defaults and overrides per stage, execution location, mode, and variant concurrency |
| Preview | Variant and stage counts, missing inputs, expected outputs, and inspectable generated scripts |

Invalid variants block dispatch until the human fixes or explicitly excludes them.
The plan retains the exclusions. The application never silently drops a variant.
Sample count and seed remain workflow parameters. They create variants only when the human selects an eligible field for expansion.

For a later stage, the human chooses Add prerequisite stages or Use existing completed outputs.
The latter checks artifact compatibility, completeness, and provenance.
A smoke-test artifact cannot satisfy a full measurement-stage input.

Autosave shows Saving, Saved, or Unsaved. It does not run checks or submit jobs.
A failed save retains the visible edits and explains that they are not saved.
A conflicting update must not silently replace another saved revision.
These recovery requirements support the accepted autosave behavior; the build plan defines their technical mechanism.

Edits after dispatch create a new draft revision. Queued work retains the approved source and configuration snapshot.
Changes to source, inputs, workflow declarations, or draft values require another check and review before a new dispatch.

## Checks and smoke tests

Check setup runs field checks and declared bounded checks on the controller host.
“Local” means that host, which can differ from the browser device.
Ordinary checks do not submit cluster jobs.
Each result names the affected field, variant, stage, or artifact and gives an actionable explanation.

Include cluster smoke test is an explicit control. A workflow can require it.
The review includes its stage, resources, outputs, and dependencies.
A passing smoke test releases dependent measurement stages. Failure pauses those dependents while independent branches can continue.

Every cluster test carries **Purpose: Smoke test**, separate from **State**.
Project Runs, global Job Monitor, job details, and logs preserve this label.
Purpose filters include All, Experiments, and Smoke tests. All also retains historical Unclassified jobs.
Retries and fan-out children inherit the declared purpose.

The application never infers purpose from a job name or filename.
Test artifacts stay outside research aggregates but remain available as evidence and count toward resource usage.
Controller-host checks appear as local activity without invented scheduler job IDs.
A valid negative scientific outcome remains a measurement. Script and infrastructure failures remain execution failures.

## Measurements: page 02c

The workflow supplies an initial metric preset.
Each selected metric shows its source field or collector, unit, grouping, and definition.
Rates also expose their denominator and exclusions.
Humans can add declared metrics and supported aggregations.
New scientific metric logic remains project code and requires an updated declaration.

Additional collection with runtime or storage costs needs explicit selection.
The UI distinguishes metrics derived from existing records from metrics that need additional collection.
The review records collector versions and selected collection stages.

Analysis of saved artifacts creates an analysis revision when all required inputs exist.
That revision retains artifact references, analysis and collector versions, parameters, and new output paths.
Earlier reports remain available.
If inputs are missing, the UI explains the gap and requires an explicit collection plan.
Changing a metric must not silently rerun model generation.

## Review and dispatch: page 02d

The full review shows the exact variants, expanded stages and jobs, dependencies, and smoke tests.
It also shows effective resources, execution mode, source and input versions, output locations, and measurement definitions.
Generated scripts and frozen configuration are inspectable.
For a repeat or revision, the review shows differences from the relevant prior execution.

Dispatch this plan starts only the shown, checked plan.
An edit invalidates the review. The application cannot substitute a newer draft during submission.
A second click or repeated request must not create a second execution of the same dispatch intent.
Repeat remains the explicit route to another fresh execution.

After dispatch, Runs opens with a filter for the new execution and a link to its experiment revision.
The destination distinguishes accepted jobs, work awaiting submission, rejected submissions, and uncertain outcomes.
An uncertain outcome requires reconciliation with the ledger before recovery can submit duplicate work.
Partial submission must preserve accepted jobs and the failed portion of the plan.

The approved sequence continues through declared dependencies, retrieval, artifact checks, analysis, and plots.
The browser does not need to stay open. A controller restart must preserve progress and approval scope.
Failures pause affected work for human review. Automatic retries or resource changes are not implied by Dispatch.
Recovery shows its exact scope and compatibility checks before approval.

## Project connection and ownership

The connection is a versioned manifest that maps existing project paths.
Existing projects keep their layout. New projects can use suggested folders.
The UI creates execution wrappers and companion metadata. Project files own scientific behavior.

| Contract area | Required information |
| --- | --- |
| Identity | Schema version, application, supported primitives and execution modes |
| Operations | Stable entrypoint, interpreter, working directory, argument bindings, environment reference, execution location |
| Parameters | Types, units, defaults, bounds, choices, required fields, variant eligibility |
| Inputs and outputs | Schemas, versions, paths, availability, completeness rules, retrieval policy |
| Stages | Dependencies, resource requests, purpose, completion conditions |
| Metrics and plots | Field or collector, unit, dimensions, aggregation, missing-value policy, output formats |
| Checks and recovery | Declared bounded checks, fixtures, smoke-test rules, resume compatibility |
| Ownership | Protected project files, generated wrappers, snapshots, custom adapters, metadata locations |

Generated wrappers call declared operations with concrete arguments.
They contain no invented scientific calculations.
Save as custom script creates project-owned source for manual editing and later selection.
Regeneration cannot overwrite it or reconstruct forms from arbitrary handwritten shell code.

Setup skills inventory existing code, declare the connection, and report missing capabilities.
They preserve existing source, data, environment files, and custom sync/fetch adapters.
Runtime operation requires no LLM or repeated skill invocation.
The evaluated models can still be LLM workloads.

For TLAiBench, analysis must preserve execution and variant identity before deduplication.
Its current record identity omits the effective token cap, so separate directories alone are insufficient.
The adapter must preserve stage-parent links and distinguish complete corpora from successful scheduler exits.
These findings come from the [project source review](../research/project-connection-harness.md).

## Completion criteria

The first release is complete when a human can configure, check, review, dispatch, observe, and analyze a declared experiment without a workflow LLM.
The end-to-end example uses two models and two token caps with isolated outputs and attributable results.
A smoke-test failure, partial submission, source edit, repeat, and archived experiment must retain correct identity and history.
The build plan assigns these checks to delivery phases.
