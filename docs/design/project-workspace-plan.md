# Project workspace decisions and research

Updated: 2026-10-03. Status: planning only. Q1–Q23 form the accepted Experiments baseline. Other page designs remain provisional.

The consolidated [functional specification](experiments-spec.md) and [build plan](experiments-build-plan.md) are the current handoff documents.
This file preserves decisions, evidence, and later review scope. No implementation or cluster action is authorized in this session.

The attached project opens a dedicated page with its own URL. The page supports the path from a hypothesis to experiments and evidence.
The first design targets `llm-thinking-trace`. Other applications can reuse the navigation and supply their own result views.

The editable source is [project-workspace.tldr](project-workspace.tldr). Its pages contain native shapes, labels, and bound arrows.
The [tool research](../research/project-workspace-tools.md) records the delegated review of the six supplied links.

## Confirmed terminology and current evidence

### Accepted design decisions

The user confirmed these decisions on 2026-10-02:

- Clicking an attached project opens its full research Overview page.
- The project page has its own sidebar, replacing the UnityHPC navigation and horizontal project tabs.
- Home at the top of that sidebar returns to the UnityHPC Projects page.
- ML becomes an application category and leaves the target primitive selector.
- `llm-thinking-trace` uses `multi-gpu` as its intended project default for independent experiments across GPUs.
- `multi-gpu` supports both independent experiments and coordinated GPU execution, selected through an explicit execution mode.
- Overview retains the research question. The user provisionally accepts the rest of its current layout.
- Humans operate the workspace. Scripted automation supports its complete workflow without an LLM after initial project setup or attachment.

The target primitive selector contains `cpu`, `gpu`, `multi-cpu`, and `multi-gpu`.
The application category is **ML**, with **reasoning-trace evaluation** as this project's specialization.
This decision changes the design. The live registry, dispatch code, and scaffolds retain their current behavior during this planning session.

### Target multi-gpu modes

| Execution mode | Meaning | Execution identity |
| --- | --- | --- |
| Independent experiments | Separate tasks run across GPUs without rank communication between tasks | A fan-out group with a ledger row per task |
| Coordinated ranks | Ranks cooperate within one GPU allocation | One scheduler job and one ledger row |

The primitive identifies the execution family. The mode identifies how that family launches work.
Neither the application category nor the GPU count alone selects the mode.
The experiment editor shows **Execution mode** when `multi-gpu` is selected.
Each mode exposes its relevant fields, such as task concurrency or nodes and ranks.
The dispatch preview records the chosen mode and its resource request.

The planned compatibility mapping is explicit:

- Existing `multi-gpu` configurations map to `multi-gpu` with independent experiments.
- Existing `ml` configurations map to `multi-gpu` with coordinated ranks.

Historical configuration snapshots retain their original values and can show the mapped interpretation beside them.
The implementation must define storage, CLI compatibility, and scaffold migration before it changes dispatch behavior.

### Current implementation vocabulary

The repository calls the execution classification a **Primitive**. [Source: glossary](../../CONTEXT.md)

| Primitive | Resource | Orchestration |
| --- | --- | --- |
| `cpu` | CPU | Single job |
| `gpu` | GPU | Single job on one node, potentially with several GPUs |
| `multi-cpu` | CPU | Fan-out of independent tasks |
| `multi-gpu` | GPU | Fan-out of independent tasks |
| `ml` | GPU | Coordinated ranks in one allocation |

The current specification explicitly defines `ml` as a primitive. It rejects treating `ml` as a `multi-gpu` preset.
That definition differs from the user's intended application category. [Source: design decision 3.4](../design-decisions.md)

Accepted direction: introduce **ML** as an application category, separately from execution primitives.
The application category selects experiment fields and result views. Each experiment declares its actual resource and orchestration needs.
The table above describes the current implementation, not the target selector.
Existing coordinated GPU jobs move into `multi-gpu` with the coordinated-ranks mode in the target design.
Independent fan-out and coordinated ranks retain distinct launch behavior within that primitive.

The local controller registry currently records `llm-thinking-trace` as `gpu`, not `ml`.
The project's migration notes also describe single-node, one-GPU jobs. This evidence supersedes the remembered ML label for this attachment.
[Source: project migration](the attached research project/docs/controller-migration.md)

### Project default and actual execution

The intended project default is `multi-gpu` with independent experiments.
Independent experiment tasks can each request one GPU and run concurrently across available devices.
A single experiment can still use `gpu`. The UI shows each experiment's effective plan separately from the project default.
Multiple separate `gpu` submissions do not automatically become one fan-out group under the current contract.
Hardware availability and the concurrency limit determine how many tasks run at once.

TLAiBench stages within one model have dependencies. Their ordering must survive the change to a fan-out default.
The design cannot treat all thirty-three model-stage jobs as independent tasks.
The current project wrappers own these dependencies. The execution migration must define the fan-out unit and preserve the stage links.

The project has an original trace corpus and a separate TLAiBench pipeline.
TLAiBench declares eleven active models, three stages per model, and thirty-three campaign jobs.
These are declared plan counts, not a claim about current cluster activity.
Its glossary distinguishes a research run, a scheduler job, a sample, a chain, a turn, and a stage.
[Source: project glossary](the attached research project/CONTEXT.md)
[Source: TLAiBench specification](the attached research project/docs/tlaibench-spec.md)

## Navigation and placement

Project cards open a dedicated project page, proposed as `/projects/:slug/overview`.
The page uses a project layout with its own sidebar. The UnityHPC sidebar and horizontal project tabs are absent from this layout.
This design treats “new page” as a separate application route. Opening a separate browser tab is not required by the wireframe.
Project navigation retains the slug, campaign scope, filters, and selected evidence in the URL where practical.

Home occupies the sidebar's brand-header slot, where the main app shows **[U icon] Unity HPC / unity · live sync**.
It aligns with the page header and uses the same 52-pixel header height. It is separate from the navigation items below.
Home returns to the UnityHPC Projects page, currently `/jobs/project`.
That destination restores the UnityHPC navigation and the project list, including its previous filters where available.
The project name appears below Home. Overview, Experiments, Runs, Results, Files, and Settings form the vertical navigation list.
The active section is highlighted. Overview remains the landing page whenever the user opens an attached project from the list.

The main content header shows the project name and current section. Application category and default primitive remain visible below it.
The primary action sits at the upper right. Section content starts below the header without a horizontal project tab row.

| Sidebar item | Main work | Placement |
| --- | --- | --- |
| Overview | Resume research and resolve blockers | Hypothesis at upper left, attention items at upper right, recent work below |
| Experiments | Define or clone a study | Catalog first, then a draft editor with a review summary |
| Runs | Observe execution and manage queued work | Filtered table, dependency view, selected-job actions |
| Results | Read and compare evidence | Plots, Compare, and Samples & traces as subviews |
| Files | Inspect code, configuration, logs, and outputs | Directory tree beside a large preview, with availability labels |
| Settings | Maintain attachment and future defaults | Paths, execution defaults, result mappings, supported actions |

Overview is the confirmed landing page. Runs remains a direct link for operational work.
Compare lives inside Results as a subview. The Results subview controls remain within the main content area.
Settings holds project defaults. An experiment draft holds overrides. A dispatched attempt retains its effective configuration snapshot.
Changes to defaults never silently change historical results.

On narrow screens, the project sidebar collapses into a menu that retains Home and all six sections.
Tables retain identity and state columns. Plot details and file trees stack above their selected content.
Links, sidebar selection, subview selection, and row actions need keyboard access and visible focus.

## First research workflow

1. State a hypothesis and choose the outcome measure.
2. Select an existing experiment or clone a prior configuration.
3. Choose the model, dataset, sample set, seed, and generation budget.
4. Review the resource request, prerequisites, output identity, and changed conditions.
5. Preview the plan, then dispatch it through the controller.
6. Observe scheduler state and research progress separately.
7. Fetch records, check completeness, and refresh derived summaries.
8. Inspect plots and samples, compare conditions, and save a conclusion with evidence links.

The human writes the research question and selects the experiment configuration.
Project scripts define executable operations and their inputs. The UI does not translate prose into commands through an LLM.
Validation, plan expansion, dispatch, monitoring, retrieval, and result processing use declared rules and scripts.
Setup or attachment skills can establish those contracts initially. Routine operation and error reporting must work without those skills or an LLM service.
LLM models remain valid experimental workloads. They are not the application's workflow controller.

## Experiments: accepted functional baseline

The user accepted Q1–Q23 and requested specification and build-plan finalization.
The product interview for the first Experiments delivery is complete. Exact engineering contracts belong to the build plan.

### Accepted human workflow

1. Open the experiment library and select an existing experiment or choose New experiment.
2. Choose a project-declared recipe, such as original trace collection or a TLAiBench workflow.
3. Give the experiment a name and configure its inputs through typed fields.
4. Save a draft without contacting the cluster.
5. Run scripted checks for required inputs, resource compatibility, prerequisites, and output conflicts.
6. Review the expanded plan, including variants, jobs, dependencies, resources, and output identities.
7. Explicitly dispatch the reviewed configuration.
8. Follow execution in Runs and inspect evidence in Results.

The current editor wireframe represents a draft, not the entire Experiments landing page.
The accepted library entry point shows experiments and their readiness, with links to their latest execution and results.
A project recipe defines available fields, defaults, script entry points, validation rules, and output conventions.
A saved experiment supplies values for that recipe. A dispatched configuration snapshot records what the human actually approved.
The user accepted the saved-study experiment model, library entry point, and automatic completion of the approved sequence.
Exact field schemas and script bindings are engineering work for the build plan. Later dynamic composition needs a separate interface review.

Accepted illustrative study: compare two models under two token caps on TLAiBench T1.
Under the accepted model, this is one saved experiment with four variants, rather than four unrelated experiment definitions.
That example does not settle the mapping between variants and scheduler jobs.
Q9–Q21 settle the user-facing variant, dependency, identity, and review behavior. Phase 0 of the build plan pins the scheduler mapping.

### Design tree and first-round decisions

| Root decision | Accepted decision | Decisions developed in later rounds |
| --- | --- | --- |
| Q1: What is an experiment? | A reusable study configuration that can contain several variants and be dispatched more than once | Variant identity, repeat attempts, editing after dispatch, result grouping |
| Q2: How does a human create one? | Initially select a project-defined workflow or clone an experiment. Later compose dynamic setups and metric collection from project files | Connection contract, script composition, metric declarations, configuration import, validation messages |
| Q3: What opens under Experiments? | A library of saved experiments, with a separate editor page | Columns, filters, empty state, row actions, draft persistence |
| Q4: What happens after Dispatch? | Approved dependencies and retrieval proceed through scripts; failures pause for human review | Retry policy, partial success, approval scope, offline controller recovery |

No runtime LLM is an accepted constraint, not an open question.
Automatic retries and resource reassignment remain outside the first delivery. Changes to an approved plan require another check and review.

### Project ownership and dynamic composition

The project directory owns input files, source code, runner files, tests, analysis code, and plotting code.
The UI creates the scripts that invoke those files. It does not author or modify the scientific source through an LLM.
Its generated execution wrappers remain distinct from project-owned code.
The UI also saves machine-readable drafts, reviewed configuration, and execution history.
The user accepted these companion records. Exact storage paths remain a design detail.

Initial creation uses declared workflows and cloning. This is the first delivery scope, not a permanent limit to fixed launch catalogs.
The longer-term target supports dynamic experimental setups and metric collection by composing project operations and their declared inputs and outputs.
The project connection template must give setup skills a repeatable contract for finding or establishing those operations.
It must also make later source changes, tests, analysis, and plotting easy to connect without another runtime agent.

The [delegated source review](../research/project-connection-harness.md) inspected the actual project, repository and installed attachment skills, and scaffold guidance.
The user accepted its recommendation to adapt existing modules through a typed connection manifest.
The attachment skill currently wires infrastructure without defining research operations or metric contracts.
Existing runners, mock execution, validators, and reports provide reusable building blocks. The review found no reusable plotting entrypoint in the inspected source catalog.

The generated guidance template also contains retired skill names and training-specific assumptions.
The implementation plan must update attachment prompts and that template together, while preserving project-owned sync and fetch adapters.
The proposed checks cover declared entrypoints, argument bindings, artifacts, fixtures, and isolated outputs.

The source review found that TLAiBench reporting deduplicates records across a scanned root, while record identity excludes the effective token cap.
The analysis adapter must preserve variant and execution identity before deduplication. Distinct output directories alone do not protect the comparison.
It must also distinguish a valid negative scientific outcome from a script or infrastructure failure that pauses automation.

### Connection-contract decisions: accepted

The scratchpad page **08 Project connection (proposal)** records the accepted ownership boundaries and the proposed execution details.
The user accepted recommendations Q5–Q8:

| Decision | Accepted direction | Consequence |
| --- | --- | --- |
| Q5: Must existing projects adopt fixed folders? | Use a standard connection manifest that maps existing paths, with a suggested layout for new projects | Current source imports and corpus paths stay intact while the controller gets a consistent interface |
| Q6: What is editable: the form or generated script? | Save a structured draft and generate inspectable wrappers. Manual script edits create a project-owned custom entrypoint that later experiments can select | The UI never silently overwrites a handwritten script or claims it can reconstruct its form fields |
| Q7: How can humans define metrics dynamically? | Select declared outputs and collectors, then choose fields and supported aggregations. Register new scientific metric logic as project code | Metric composition remains deterministic and auditable without generating analysis source |
| Q8: Can the UI save companion metadata? | Save structured drafts, variant definitions, reviewed configurations, and execution history alongside generated scripts | Editing and repeatability work without generating scientific source code |

Project layout conventions do not replace an interface contract.
The contract must describe parameter types, inputs, outputs, prerequisites, execution location, metrics, and checks for each callable operation.
Those declarations let setup skills connect existing code and let scripts reject incompatible combinations later.
Generated wrappers are inspectable and regenerated from the saved draft.
An explicit Save as custom script action creates a project-owned entrypoint for manual editing and later selection.
Regeneration does not overwrite that custom source or reconstruct form fields from arbitrary shell code.
Exact schemas, paths, registration checks, and aggregation syntax belong to the engineering contract phase of the build plan.

### Experiment execution: accepted decisions

The user accepted Q9–Q12 on 2026-10-03. These are design decisions, not changes to current execution behavior.

| Decision | Accepted direction | Later details unlocked |
| --- | --- | --- |
| Q9: What happens after a draft or source change? | Edits after dispatch create a new draft revision. Check and review again before dispatch. Dispatched executions retain their reviewed configuration and declared source snapshot | Snapshot boundaries, external data versions, changed-source indicators |
| Q10: How do selected parameter values create variants? | Offer All combinations and Explicit combinations. Start with all combinations and show the exact expanded list before dispatch | Invalid combinations, per-variant overrides, sample and seed expansion |
| Q11: How do repeat and resume differ? | Repeat creates a fresh execution and outputs. Resume or retry is a separate action with explicit scope and compatibility checks | Completed-item reuse, checkpoints, attempt identity, failures |
| Q12: Where do resource choices apply? | Each stage inherits compatible project defaults and can override them. CPU analysis can follow GPU collection. Variant concurrency is separate from coordinated ranks | Local versus cluster placement, concurrency limits, resource validation |

The experiment editor exposes combination mode and a preview of its expanded variants.
Resources belong to individual stages. The project default does not force CPU analysis or plotting to request GPUs.
Repeat and Resume/retry remain separate actions. Repeating does not silently reuse previous outputs.
An edit after dispatch starts another draft revision and cannot modify the source snapshot of a queued execution.

### Drafts and pre-dispatch checks: accepted decisions

The user accepted Q13–Q16 on 2026-10-03 and added explicit identification for cluster smoke tests in monitors and logs.

| Decision | Accepted direction | Later details unlocked |
| --- | --- | --- |
| Q13: How are unfinished edits saved? | Autosave drafts with visible Saving, Saved, or Unsaved states. Saving never validates or dispatches work | Save conflicts, offline behavior, draft recovery |
| Q14: What happens when some selected variants are invalid? | Highlight each invalid combination and block dispatch until the human fixes or explicitly excludes it | Validation severity, exclusion records, variant overrides |
| Q15: How does a later stage obtain its prerequisites? | Offer Add prerequisite stages or Use existing completed outputs. Require an explicit choice and check artifact compatibility | Artifact selector, dataset scope, provenance and completeness checks |
| Q16: Which checks can run without submitting jobs? | Run quick field checks and declared bounded checks on the controller host. Cluster smoke tests must be explicit stages in the reviewed plan | Check budgets, fixture declarations, canary resources and errors |

Draft autosave shows Saving, Saved, or Unsaved. The editor offers Check setup and Review plan. Dispatch appears only on the full review page.
Expected scientific failures remain valid measurements. Pre-dispatch validation concerns executable plans and input compatibility, not whether a model will pass.

### Smoke-test identity in monitors and logs

Cluster smoke tests carry an explicit **Smoke test** purpose label, separate from scheduler **State**.
A smoke test can be Pending, Running, Completed, or Failed without losing that label.
The same label appears in the project Runs view, global Job Monitor, job details, and associated log views.
Purpose filtering offers All, Experiments, and Smoke tests. Historical jobs without recorded purpose remain Unclassified.

The reviewed stage declares its purpose before dispatch. Submitted jobs, fan-out children, and retry attempts retain that purpose.
Names and filename patterns do not determine whether a job is a test.
Each log and artifact retains its execution, stage, attempt, and job linkage so filters can separate test evidence from experiment evidence.
An experiment can contain both smoke-test stages and measurement stages. Its tests do not relabel the whole experiment as a test.

Smoke-test outputs remain separate from measurement outputs and normal research aggregates.
They remain inspectable as test evidence and count toward cluster resource usage.
CPU checks on the controller do not receive invented scheduler job IDs. They appear as local check activity.
An arbitrary user-tag editor is not part of this decision. The required custom identification is the explicit Smoke test label.

### Smoke-test behavior: accepted decisions

The user accepted Q17 and Q18 on 2026-10-03.

| Decision | Accepted direction |
| --- | --- |
| Q17: When are cluster smoke tests included? | Offer an explicit Include cluster smoke test control. Recommend it after relevant code, model, or environment changes. A workflow can declare it mandatory |
| Q18: Does a smoke test gate measurement stages? | When included, a passing smoke test is a prerequisite for its dependent measurement stages. A failure pauses those stages while independent work can continue |

The editor exposes Include cluster smoke test and explains when the workflow requires it.
A required smoke test cannot be silently omitted. Its stage and resource request appear in the reviewed plan.
Only the stages that depend on its passing result wait. Independent branches can continue after a smoke-test failure.
The Smoke test purpose label remains visible through submission, execution, failure, and log inspection.

### Measurements and final review: accepted direction

The user accepted Q19–Q21 on 2026-10-03:

| Decision | Accepted direction |
| --- | --- |
| Q19: How are initial measurements selected? | Load the workflow's declared metric preset. Show source fields or collectors, units, and grouping. Let the human add declared metrics and explicitly enable costly extra collection |
| Q20: Can measurements change after collection? | Create a new analysis revision over selected saved artifacts when they contain the required inputs. Otherwise explain what is missing and require a new collection plan |
| Q21: Where is final dispatch approval? | Use a dedicated full-page review with exact variants, stages, smoke tests, resources, source versions, output paths, and differences. One explicit Dispatch starts that reviewed plan |

A new analysis revision retains links to original artifacts and its own collector versions and parameters.
It does not replace the earlier report or silently rerun model generation.
The UI must distinguish metrics derived from existing records from metrics that require additional data collection during execution.
The scratchpad now includes Measurements and Dispatch review pages under Experiments.
The metric rows illustrate the layout; the project connection must declare the actual preset and field definitions.
The editor leads to review. Only the dedicated review page offers Dispatch for that exact plan.
Editing the draft invalidates the reviewed plan and requires another check and review.

### Experiment lifecycle: accepted decisions

The user accepted Q22–Q23 on 2026-10-03 and requested final specification and build planning.

| Decision | Accepted direction |
| --- | --- |
| Q22: How do we remove experiments from the library? | Allow deletion of drafts with no executions. Archive experiments with execution history, with a restore action and an Archived filter. Archiving does not cancel jobs or delete files |
| Q23: Where do we go after dispatch? | Open project Runs filtered to the new execution, with a link back to its experiment revision. Show accepted, pending, and failed submissions separately if dispatch is partial |

### Facts established for the interview

The current catalog contains fixed launch entries rather than editable experiment definitions.
Its launch endpoint accepts only `dry_run`. Readiness is a declared catalog status, not a calculated list of missing inputs.
The controller has no draft CRUD, recipe field schema, or experiment revision model.
[Source: catalog implementation](../../controller/experiments.py)
[Source: HTTP contract](../../controller/http.py)

The project scripts already accept model and stage selections, sample counts, and token caps.
The campaign plan prints jobs but does not perform every individual job check.
The existing in-flight admission cap rejects excessive submissions. It does not continuously enforce a running-job concurrency limit.
Dependencies belong to project scripts. Partial submission can leave accepted jobs running after another submission fails.
[Source: campaign wrapper](the attached research project/slurm/tlaibench_sweep.sh)

Output identity requires particular care when the user changes a token cap and repeats an experiment.
Full TLAiBench output names currently depend on model and stage. Resume can reuse existing records unless the revised experiment has a distinct output directory.
A later stage needs a valid full parent corpus. Smoke outputs are separate and cannot serve as that parent.
These facts support the accepted revision, resume, and dependency rules and the build-plan acceptance checks.
[Source: stage wrapper](the attached research project/slurm/tlaibench_submit.sh)

## Results for this project: provisional design

The initial views emphasize task outcomes and emitted traces. Training loss is not the default measure for this evaluation project.
Suggested plots include outcome rate by model, outcome classes by stage, trace length versus outcome, and token-cap truncation rates.
Plots show units, denominators, filters, sample selection, and metric definitions.
Uncertainty estimates must state their method and respect the dependence between repeated samples from the same puzzle.

Comparisons align dataset items, sample indices, stages, and generation conditions.
They expose differences in model revision, dataset version, seed, effective token cap, context window, grader version, and hardware.
Missing provenance is an explicit unknown. An unmatched sample remains visible as unmatched.
Different effective token caps require distinct output directories under the current project contract.

The sample view opens the prompt, full model output, extracted trace, and final artifact.
TLAiBench adds chain navigation, individual turns, tool feedback, checker phases, and parent links.
A trace is emitted model text. It does not establish the model's internal reasoning mechanism.

Model failures, harness errors, and dataset limitations have separate classifications.
Superseded runs remain inspectable but stay outside current aggregates by default.
Capped and recovered traces retain their labels. Skipped checker phases retain their reasons.
TLAiBench reports carry the project's **First numbers** designation.
[Source: project specification](the attached research project/docs/tlaibench-spec.md)

## Runs and queue controls: partial review

The Runs table distinguishes scheduler state, corpus completeness, stage readiness, fetch state, and observation time.
A job can save a complete corpus before a teardown failure blocks dependent stages.
The UI calls this condition a **stranded stage**, following the project glossary.
The existing campaign checker reports it without dispatching replacement work.

| Situation | Proposed control | Required review |
| --- | --- | --- |
| Draft | Edit walltime, partition, hardware, and resources | Effective plan, feasibility, output identity |
| Pending | Review supported request changes | Old and new values, permissions, dependency impact |
| Pending replacement | Cancel and dispatch a revised attempt | Lost queue position, affected children, preserved evidence |
| Running | Inspect progress and remaining allocation time | State freshness and checkpoint support |
| Interrupted | Retry or resume a declared plan | Completed items, checkpoint compatibility, attempt identity |
| Future scheduling | Set earliest eligibility or a saved schedule | Meaning of “schedule reassign” still needs user clarification |

Walltime is an allocation limit, not a completion prediction or a start reservation.
An accurate shorter limit can help Slurm backfill. It cannot guarantee an earlier start.
The current fallback ladder handles refused submissions. It does not relocate an accepted queued job.
[Source: Slurm scheduling](https://slurm.schedmd.com/sched_config.html)
[Source: current dispatch decisions](../design-decisions.md)

The interface exposes only actions the controller and project support.
Array cancellation must show the affected group. A selected child does not imply that the current backend cancels only that child.
Replacement attempts must preserve lineage and account for downstream dependencies.
Automatic reassignment, checkpoint migration, and future experiment schedules require separate contracts.

## Existing support and design gaps

This assessment reads the current working tree, which contains pre-existing uncommitted controller changes.
It does not establish that every capability is present in the deployed controller.

| Capability | Evidence now | Proposed addition |
| --- | --- | --- |
| Project attachment | Registry, paths, primitive, resources, sync policy | Dedicated route and project sidebar |
| Experiment catalog | Fixed entries with ready, needs_input, historical states | Draft editor and reviewed configuration versions |
| Launch | Controller dispatch and fixed catalog previews | Hypothesis links and immutable attempt records |
| Monitoring | Ledgers, telemetry joins, logs, controller events | Combined job and corpus view, dependency inspection |
| Fetch | Scheduler logs plus optional project artifact hook | Separate progress, result indexing, completeness checks |
| Results | Project manifests, JSONL records, metric declarations, TSV summaries | Read APIs, schema mapping, plots, samples, comparisons |
| Files | Local project paths and fetched artifacts | Scoped browsing, structured previews, availability labels |
| Queue management | Cancel, dispatch overrides, submission fallback | Supported pending edits, replacement review, scheduling policies |

The artifact hook already exists for this project. It pulls both corpora after scheduler-log retrieval.
It does not transfer or rebuild `results.tsv` or `results_tlaibench.tsv`.
The UI must distinguish fetched raw records from current derived summaries.
[Source: controller README](../../controller/README.md)
[Source: project migration](the attached research project/docs/controller-migration.md)

Generic Sync is disabled for this attachment. The first Files design supports browsing and previews.
A future file editor needs explicit save, configuration validation, code-push, and conflict behavior.
Large JSONL corpora need indexed or paginated reads rather than full browser downloads.
Result contracts must define record identity, units, missing values, provenance, and schema version.

## Accepted changes that require implementation contracts

- The full project route replaces the older drawer recommendation in [monitoring notes](../monitoring.md).
- The project layout replaces the global sidebar with project navigation and a Home link to the UnityHPC Projects page.
- The accepted ML application category revises the existing primitive map in [decision 3.4](../design-decisions.md).
- The target selector removes `ml`. Its coordinated execution maps to the coordinated-ranks mode within `multi-gpu`.
- The project default becomes `multi-gpu`. The migration must preserve TLAiBench stage dependencies and existing job identities.
- Editable experiments extend the fixed catalog contract in [controller documentation](../../controller/README.md).
- Project adapters interpret research results while the dispatch harness remains metric-agnostic.
- The project already owns TLAiBench dependencies. A generic dependency editor is a separate extension to the harness scope.
- Rich progress requires explicit data collection. Allocated GPUs do not prove utilization, and browser polling does not make old snapshots current.

The user approved these design directions. The build plan specifies migration work without changing runtime behavior in this session.

## Review status and next scope

The project layout and Q1–Q23 Experiments decisions form the accepted functional baseline.
Overview keeps the research question. Its remaining layout is provisionally accepted.
The engineering work and acceptance checks are in the [build plan](experiments-build-plan.md).

Later page reviews cover:

- Runs: queue actions, cancellation scope, scheduling, and the meaning of schedule reassignment.
- Results: comparison placement, sample inspection, plots, and prominence of the original corpus versus TLAiBench.
- Files and Settings: detailed interactions, project maintenance, and default changes.
- Dynamic composition: connecting declared project operations beyond the first predefined workflows.

Variant-to-job mapping and exact storage/API schemas are engineering contracts, not unanswered product interview questions.
All figures use illustrative states. No cluster job, project setting, or production UI changed during this design work.
