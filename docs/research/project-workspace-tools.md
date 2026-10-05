# Project workspace: experiment tool research

Research date: 2026-10-02. Status: planning evidence, not an implementation specification.

This report reviews the six supplied sources and follows useful claims to first-party documentation. Recommendations target the LLM thinking-trace project. Its glossary and TLAiBench specification provide the project-specific constraints. Representative result files still need review before the UI can promise exact field mappings.

## Recommendation

Build a full-page attached-project workspace around experiment setup, cluster runs, and interpretable results. Give configuration snapshots, run history, plots, sample inspection, comparison, and files a common project context. Keep project-specific interpretation outside the metric-agnostic dispatch harness.

The best patterns come from several tools. MLflow supplies run provenance, W&B supplies sample tables, and LangSmith supplies aligned output comparisons. Slurm supplies the actual limits on scheduling controls. These patterns do not require adopting those products.

## Review of the supplied sources

| Supplied source | Useful evidence | Treatment |
| --- | --- | --- |
| [Neptune experiment-tool comparison](https://medium.com/neptune-ai/15-best-tools-for-tracking-machine-learning-experiments-64c6eff16808) | Broad checklist: parameters, metrics, files, reproduction, and comparison. | Historical vendor-authored discovery material. Confirm capabilities in current primary docs. |
| [Experiment-management list](https://github.com/awesome-mlops/awesome-ml-experiment-management) | Names candidate trackers and visualization tools. | Discovery index, not evidence of maintenance or integration fit. |
| [LocalLLaMA discussion](https://www.reddit.com/r/LocalLLaMA/comments/1q1ntkh/i_built_a_simple_web_ui_for_training_and_running/) | Researcher friction from scattered scripts, datasets, configurations, and outputs. | Followed its project link to the author's repository. |
| [Datadog agent-evaluation landing page](https://www.datadoghq.com/dg/ai/agent-evaluations/) | Could not retrieve this page. | Used Datadog's accessible first-party experiment article. Several documentation URLs also failed to open. |
| [LangChain observability comparison](https://www.langchain.com/resources/llm-observability-tools) | Distinguishes operational tracing from evaluation workflows. | Vendor comparison, not a neutral ranking. Followed relevant claims to LangSmith documentation. |
| [AI agents for ML list](https://github.com/OpenJobsAI/awesome-ai-agents-for-ml) | Separates research agents, training agents, evaluation, and platforms. | Discovery index. Autonomous experimentation is a later product decision. Benchmark and popularity claims were not independently validated. |

Neptune's official transition page schedules hosted service shutdown for March 5, 2026 and closes new sign-ups. Its old comparison cannot support a current Neptune integration recommendation. Other historical product entries require separate diligence before selection. [Neptune transition notice](https://docs.neptune.ai/transition_hub)

The Reddit-linked project, `llm-madness`, documents versioned dataset snapshots, run manifests, configuration, Git SHA, loss curves, samples, and token inspection. It demonstrates useful local research UI patterns. Its custom training pipeline does not establish compatibility with this controller or the thinking-trace project. [Author's repository](https://github.com/MaxHastings/llm-madness)

## Adopt, adapt, defer, reject

| Decision | Proposed feature | Why and evidence |
| --- | --- | --- |
| Adopt | Snapshot each experiment's configuration and code revision. Link dataset identity, model revision, seed, and result files. | MLflow records parameters, code versions, metrics, and artifacts per run. [MLflow Tracking](https://mlflow.org/docs/latest/ml/tracking/) |
| Adopt | Filterable run table with campaign, experiment label, job identity, status, elapsed time, and result availability. | The existing ledger already owns jobs and campaign scope. [Repository architecture](../../ARCHITECTURE.md) |
| Adopt | Saved plots with metric selection, explicit units, axis choice, and linked source runs. | TensorBoard demonstrates scalar histories recorded against steps. Available plots depend on emitted records. [TensorBoard](https://www.tensorflow.org/tensorboard/get_started) |
| Adopt | A sample table that connects aggregate results to individual model outputs. | W&B Tables supports prediction inspection and comparisons on the same test set. [W&B Tables](https://docs.coreweave.com/products/wandb/tables) |
| Adapt | Baseline selection, configuration differences, score changes, and aligned output comparison. | LangSmith offers experiment comparison, filters, full text, and two-experiment text differences. [LangSmith comparison](https://docs.langchain.com/langsmith/compare-experiment-results) |
| Adapt | Save an interesting failure as a named evaluation case, then rerun a controlled variant. | Datadog connects inspected outputs, versioned datasets, experiments, and evaluations. [Datadog experiments](https://www.datadoghq.com/blog/llm-experiments/) |
| Adapt | File browser showing producing run, path, size, format, and local or remote availability. | MLflow separates run metadata from large artifacts. This controller already has a fetch path. [MLflow Tracking](https://mlflow.org/docs/latest/ml/tracking/), [repository architecture](../../ARCHITECTURE.md) |
| Defer | Production application tracing, online traffic dashboards, model serving, registries, and autonomous research loops. | These add workflows beyond the requested batch research workspace. This is a scope recommendation, not a claim that the tools lack value. |
| Reject | A mandatory tracking vendor, a second scheduler, and a generic “avoid queue” action. | These obscure existing ownership or promise behavior the controller cannot guarantee. [Controller split](../adr/0001-two-component-split.md), [Slurm scheduling](https://slurm.schedmd.com/sched_config.html) |

## Thinking traces need a sample inspector

LangSmith defines application traces as trees of operations. Its trajectories show ordered messages. These structures capture instrumented application activity. They do not automatically expose a model's internal reasoning. [LangSmith concepts](https://docs.langchain.com/langsmith/observability-concepts)

For this project, the proposed inspector shows recorded data: prompt, emitted thinking text, answer, reference, evaluator outcome, and source file. Token counts, truncation, generation parameters, and per-sample timing belong beside them when available. Hidden states, attention, and token probabilities require separate instrumentation. The UI must identify missing data instead of inventing it.

Comparison needs a stable sample identity, dataset revision, and evaluator revision. It can then align the same example across runs. Aggregate plots need visible sample counts and coverage. A partial run must not look equivalent to a complete run. These are proposed validity rules, inferred from the project goal and dataset-oriented comparison patterns.

The first plots should answer the actual hypothesis. Candidate views include score distributions, output length, score versus length, and throughput. Training-loss charts belong only to projects that produce training metrics. Statistical summaries need a stated aggregation rule and repeated-run policy before confidence intervals appear.

## Fit to the current thinking-trace project

The project studies observable reasoning traces and task outcomes. Its glossary explicitly separates generated rationales from internal reasoning mechanisms. The UI must preserve this wording. [Thinking-trace glossary](the attached research project/CONTEXT.md)

TLAiBench currently specifies 11 active models and T1, T2, and T3 stages, for 33 jobs. Its fixed profile requests one GPU. It collects sixteen independently seeded samples. A sample count is not concurrency. T1 has 160 items, while T2 and T3 each have 96. [Project glossary](the attached research project/CONTEXT.md), [TLAiBench specification](the attached research project/docs/tlaibench-spec.md)

These facts change the proposed UI:

| Surface | Project-specific requirement |
| --- | --- |
| Overview | Separate the original corpus from TLAiBench. Carry TLAiBench's “first numbers” designation and measurement limits. |
| Experiments | Show model revision, seed policy, effective per-turn cap, context budget, toolchain, and output directory. Different caps need distinct directories. |
| Runs | Distinguish the project run's output directory from the scheduler job. Show stage dependencies and corpus completion separately from scheduler success. |
| Results / Plots | Prioritize per-item pass rate, stage outcomes, applicable checker phases, trace length, truncation, and context exhaustion. |
| Results / Samples | Open an item or chain, then its turns. Show model text, tool directives, checker feedback, and applicable phase verdicts. |
| Results / Compare | Align puzzle, sample, stage, and conditions. Preserve parent linkage. Surface token-cap, evaluator, hardware, and dataset differences. |
| Files | Separate scheduler logs from corpus records, manifests, generated specifications, checker artifacts, and reports. |

Model failures, harness errors, and dataset limitations need separate filters and counts. A skipped checker phase must retain its reason. Superseded runs stay inspectable but do not enter current campaign aggregates. Recovered traces need a truncation label. These requirements come directly from the [project specification](the attached research project/docs/tlaibench-spec.md).

A stranded stage has a complete corpus but a nonzero scheduler exit. Its dependent stages remain pending under `afterok`. The existing campaign checker reports this condition and submits nothing. A proposed “re-drive dependent stage” action therefore needs explicit evidence and separate controller support. [TLAiBench specification](the attached research project/docs/tlaibench-spec.md)

The controller's Fetch action first retrieves scheduler logs through `run.sh fetch`. It then runs the optional project-owned `unityHPC/fetch.sh` hook. The current thinking-trace project already supplies this hook. It pulls both `data/traces/` and `data/tlaibench/` with backups and without deletion. The controller returns separate log and artifact results. [Controller contract](../../controller/README.md), [project migration](the attached research project/docs/controller-migration.md), [artifact hook](the attached research project/unityHPC/fetch.sh)

The hook does not transfer or rebuild `results.tsv` or `results_tlaibench.tsv`. The remaining design work concerns results indexing, plot and sample HTTP/UI support, and summary regeneration. File availability and summary freshness need separate states. A successful corpus pull does not establish that aggregate tables reflect those files. The migration document updates the older specification's fetch limitation. [Project migration](the attached research project/docs/controller-migration.md)

## Scheduling and run monitoring

Slurm backfill uses resource requests and time limits. An accurate shorter walltime can create more scheduling opportunities. It cannot guarantee an immediate start. Slurm's expected start time remains an estimate dependent on the queue and scheduler configuration. [Slurm scheduling](https://slurm.schedmd.com/sched_config.html)

The proposed UI separates these actions:

| State or intent | Suitable UI action | Boundary |
| --- | --- | --- |
| Experiment draft | Edit walltime, resource request, partition preference, and eligible start time. Preview dispatch. | “Eligible after” describes a lower bound, not a reserved start. |
| Pending job | Show pending reason and supported request changes. Preview differences. | Exact editable fields depend on permissions, job state, and site policy. |
| Running job | Show logs, progress, resource observations, time remaining, and checkpoint status. | Slurm reserves increases to a running job's time limit for privileged users. |
| Restart elsewhere | Present a separate cancel-and-dispatch or checkpoint-resume workflow. | Show which job ends, what work survives, and the replacement's identity. |
| Automatic reassignment | Save an explicit policy with eligibility rules and retry budget. | Requires new controller behavior and an audit trail. Keep it outside passive status reads. |

Slurm distinguishes earliest initiation time, updates, and requeue. Requeue returns a batch job to pending state. It does not establish application checkpoint recovery. [Slurm `scontrol`](https://slurm.schedmd.com/scontrol.html)

The existing partition ladder retries only after a refused submission. It does not move an accepted pending job between queues. Automatic submission during status reads conflicts with the repository's documented decisions. Scheduling controls need a separate design decision and controller contract. [Design decisions, sections 3.1 and 3.7](../design-decisions.md)

Monitoring must separate scheduler state, application progress, and data freshness. A running allocation does not prove that samples advance. A finished job does not prove that files reached the local results tree. GPU allocation also does not establish GPU utilization. Those distinctions follow the repository's telemetry limits. [Design decisions, telemetry](../design-decisions.md)

## Integration and data contract

Start with the controller's ledger, project files, and fetched results. Reuse the existing artifact hook for corpus retrieval. A results adapter can describe result tables, sample records, and metric meaning. That adapter remains distinct from the existing fetch hook. The harness continues to dispatch and fetch opaque workloads. This preserves the current metric-agnostic boundary. [Domain glossary](../../CONTEXT.md), [controller contract](../../controller/README.md)

An implementation proposal needs explicit records for:

- An experiment draft, its hypothesis, baseline, and configuration snapshot.
- The execution attempt, its ledger job identity, campaign, and parent attempt.
- Metrics with names, units, step or time coordinates, and source records.
- Samples with stable identifiers and dataset revision.
- Evaluations with evaluator revision and completion status.
- Files with producing attempt, location, fetch state, and provenance.

These are proposed concepts. The repository does not currently define all of them. A campaign remains an optional grouping label and can contain several fan-out groups. It must not silently become synonymous with an experiment. [Domain glossary](../../CONTEXT.md)

MLflow is an optional adapter candidate if run tracking needs exceed the local format. TensorBoard is a useful external viewer when compatible event files already exist. Neither needs to replace controller dispatch. Vendor UI patterns alone do not justify a new service dependency. [MLflow Tracking](https://mlflow.org/docs/latest/ml/tracking/), [TensorBoard](https://www.tensorflow.org/tensorboard/get_started)

## Design questions left open

The next review needs representative thinking-trace result files and one complete experiment. It must map the documented sample identity and outcomes to actual fields. It also needs to establish the first hypothesis and comparison baseline. Scheduling design must distinguish shorter walltime, a later eligible start, and migration to another partition.

The report recommends features and boundaries. It does not select a tracker, change primitive terminology, authorize cluster actions, or implement the proposed scheduling policies.
