# Project connection contract for the Experiments workspace

Planning research, 2026-10-02. Source inspection only. No workloads, tests, cluster commands, or implementation changes ran for this report.

Recommendation: define a versioned connection contract around the project's existing files. The UI composes scripts from declared entrypoints, parameters, and artifact connections. Project code owns scientific methods, metrics, and plots. Humans choose the work. Deterministic scripts run it.

## Accepted direction

- One saved experiment can contain several variants. Each execution keeps its own identity.
- Experiments opens the library. Users start from a project workflow or clone an experiment.
- Dispatch authorizes the reviewed sequence, including dependent stages, artifact fetch, and summaries. Failures pause affected work for human review.
- Source files, runners, and inputs remain in the project directory. The UI creates orchestration scripts, with their configuration records.
- ML becomes an application category. The proposed `multi-gpu` primitive supports independent experiments and coordinated ranks.

These are design decisions from this discussion. Current code still implements five primitives and fixed catalog launches. [S1] [S2]

## Existing building blocks

| Area | Current implementation | Implication |
| --- | --- | --- |
| Original corpus | `harness/run_traces.py` accepts model, benchmark, item count, context length, seed, output directory, and summary path. `--mock` uses a CPU engine. | Most form fields already map to real CLI arguments. [S3] |
| Original records | The runner writes JSONL records, a manifest, and a TSV summary. Records include provenance and generation parameters. | Preserve these formats through adapters. [S4] |
| TLAiBench runner | `tlaibench/run_traces.py` adds stages, sample count, turns, token cap, TLC timeout, parent artifacts, and optional turn details. | Stage inputs and collection choices need explicit form fields. [S5] |
| TLAiBench provenance | Its manifest records effective parameters, prompts, protocol, grader, toolchain, hardware, outcome classes, and parent run. | Existing metadata supports useful comparisons without an LLM interpreter. [S6] |
| Submission | `tlaibench_submit.sh` builds a command and calls `unityHPC/run.sh`. The sweep submits stages with `afterok` dependencies. | Reuse the ledger writer; replace fixed campaign assumptions before general composition. [S7] [S8] |
| Analysis | `harness.overview` exports Markdown/CSV. `tlaibench.report` exports summaries, per-chain tables, JSON, and Markdown. | Register these as analysis entrypoints. No reusable plotting entrypoint was found in the inspected source catalog. [S9] [S10] |
| Fetch | The controller fetches scheduler logs, then calls the project's artifact hook. The hook pulls both corpora and requests separate validation. | Automatic fetch/check/report is a proposed extension, not the current hook's behavior. [S11] [S12] |
| Existing checks | Tests cover mock execution, resume, manifests, parent linkage, reports, graders, and toolchain behavior. | Attach can register focused checks instead of inventing a second scientific harness. [S13] |

The original flow is configuration → runner → engine and grader → records/manifest → catalog and reports. TLAiBench adds a chain/turn/tool-feedback loop and dependent stage artifacts. These project modules already provide the scientific behavior.

## What attach currently misses

The repository and installed v0.14.0 `connect` skills have the same instructions. They check controller health, choose a primitive, scaffold infrastructure, attach the directory, and check the attachment. They do not define typed workflows, artifact schemas, collection stages, or project checks. [S14] [S15]

The scaffold generator creates four files: dispatcher, job template, sync script, and environment configuration. It preserves an existing environment file. The generator replaces other changed scripts and keeps backups for handwritten files. This project's custom sync adapter explicitly requires preservation after regeneration. The future contract needs explicit file ownership rather than recovery instructions after replacement. [S16] [S17]

The old setup instructions now live in operator runbooks. Their optional `metrics.json` declares display columns and a possible ranking direction. It does not define metric collectors, dimensions, units, aggregation, or artifact sources. The current project declares no primary metric, appropriately avoiding one ranking across unlike benchmarks. [S18] [S19]

There is also stale generated guidance to fix during implementation. `templates/CLAUDE.md.template` names retired skills, an old collector loop, and project-specific training-file assumptions. `hpc-scaffold --write-guidance` still uses that template when `CLAUDE.md` is absent. Updating only a version marker cannot correct its content. [S20] [S21]

## Proposed reusable contract

The filename below is illustrative: `unityHPC/project.json`. It references existing paths. It does not require a new source layout.

| Contract section | Required declaration |
| --- | --- |
| Identity | Schema version, application category, supported primitives and execution modes, project root. |
| Files and ownership | Source/input paths, generated-script directory, environment references, sync/fetch ownership, protected output paths. |
| Entrypoints | Stable ID, relative path or module, interpreter, working directory, argument vector, environment profile, allowed execution location. |
| Parameters | Type, default, bounds, units, choices, required fields, argument binding, variant eligibility. Dynamic choices come from a declared deterministic reader. |
| Inputs | File/dataset/model references, versions or checksums, availability, required cache/staging steps, artifact schema. |
| Outputs | Named artifacts, format/schema version, path binding, required/optional status, completeness check, retrieval policy. |
| Stages | Entrypoint reference, parameters, input/output connections, dependencies, resource request, timeout, expected completion conditions. |
| Metrics | Artifact field or project collector entrypoint, value type, unit, dimensions, denominator, aggregation, missing-value policy, optional ranking direction. |
| Analysis and plots | Existing script/entrypoint, input selection, parameters, output format, collector/analysis version, supporting source artifacts. |
| Checks | Fast schema/argument checks, fixture tests, mock smoke workflow, optional compute-node canary, bounded execution location. |
| Resume | Checkpoint identity, compatibility fields, concurrency restrictions, stage completion evidence, retry policy. |

The contract describes behavior. It does not duplicate model registries or scientific formulas. For this project, model choices must use `tlaibench.models.load_campaign()` so excluded models stay excluded. [S7]

Local execution means the controller host, which can differ from the browser device. Each stage declares local or cluster execution and its resource needs. Tests, reports, or plots can use local CPU execution. Inference remains a cluster workload. Cluster dispatch continues through the controller and `run.sh`, as ADR 0001 requires. [S22]

Generated scripts receive concrete argument values through a deterministic serializer. They call existing entrypoints and contain no invented analysis logic. The review shows commands, dependencies, resources, output paths, and the source/configuration fingerprint. Source or contract changes invalidate that review. A dispatch uses the reviewed source snapshot, so later edits cannot silently change pending jobs.

## Correctness gaps to resolve before dynamic composition

1. **Variant identity and deduplication.** TLAiBench record IDs exclude the effective token cap. Different caps need different directories. Its report also deduplicates across the entire scanned root. Comparisons must retain execution/variant identity and deduplicate within that scope. Distinct directories alone do not protect both comparison arms. [S23] [S24]
2. **Fixed paths and parent links.** The submit wrapper fixes its campaign and derives names from model/stage. New plans need explicit execution, variant, stage, and attempt identities. Parent inputs must name the selected predecessor's artifact, including its completeness evidence. [S7]
3. **Partial submission.** The sweep parses job IDs from text and stops on the first submission failure. Earlier jobs can remain queued. The controller needs durable per-stage submission records and reconciliation with the job ledger. An ambiguous timeout requires reconciliation before any retry. Restarting the whole sweep is insufficient. [S8]
4. **Failure versus scientific outcome.** A model failure can be a valid completed measurement. A harness error cannot masquerade as that measurement. The existing project also recognizes complete corpora behind failed scheduler exits. Keep failed-parent recovery manual and preserve `afterok`. Expose the mismatch for review. [S25]
5. **Automatic continuation.** A durable controller worker must resume the approved sequence after a controller restart. It must not depend on the browser staying open. Retries or resource changes beyond the approved plan require a new review. This proposal adds that worker.
6. **Scope of fetch and analysis.** The current hook pulls whole corpora, not a selected execution. Each new stage needs declared outputs and scoped fetch. Analysis must record selected artifacts and their versions. Shared TSV append targets need serialization or per-stage summaries followed by an explicit merge. [S12] [S26]
7. **Measurement definitions.** Existing display labels are insufficient for dynamic collection. A selected metric must resolve to a field or registered collector. New scientific calculations require a project code change, tests, and a contract update. Generic tables/plots can consume declared fields without custom scientific code. [S19]

A study can contain GPU collection and CPU analysis stages. Therefore, its project default cannot fix every stage's resource request. Independent variants can each contain coordinated GPU ranks. A future workflow model must distinguish concurrency between variants from execution within each variant.

## Setup responsibilities and layout

The attach skill first inventories entrypoints, parameters, outputs, dependencies, and checks. It reports missing capabilities instead of claiming that arbitrary source files are executable workflows. It then proposes the connection declaration and thin adapters where necessary. Human review covers ambiguous scientific assumptions.

The skill creates connection metadata, generated wrapper locations, and contract checks. It preserves source, inputs, existing artifacts, environment files, and custom sync/fetch adapters. It checks declared paths, argument construction, output isolation, fixtures, mock execution, and rendered job scripts. Cluster canaries remain a separate bounded action.

For `llm-thinking-trace`, keep `harness/`, `tlaibench/`, `config/`, `tests/`, and `slurm/`. A suggested layout for new projects can separate runners, analyses, plots, and fixtures. Existing projects only need mappings. Forced restructuring creates import/path churn without improving the interface itself.

One ownership proposal is `unityHPC/generated/<execution>/` for immutable generated wrappers and reviewed plans. Experiment drafts live in a separate declared directory. Source-controlled workflow definitions remain project-owned. Exact paths remain open for design review.

“UI creates only scripts” needs one narrow clarification. Forms still need machine-readable drafts and execution records to support editing, review, and repeatability. These records contain configuration and provenance, not scientific source. The generated wrapper remains the executable output. This metadata boundary needs user agreement.

Recommendation: generated wrappers are inspectable and regenerated from the saved experiment. Direct edits require an explicit conversion to a project-owned custom entrypoint. The next experiment references that entrypoint, so regeneration cannot silently overwrite its changes.

## Incremental path

1. Declare the two existing workflows, their source paths, metrics, and checks. Preserve fixed catalog compatibility.
2. Add typed forms, cloning, variant expansion, unique outputs, and structured review. Keep script generation deterministic.
3. Add durable orchestration, scoped fetch, validation, reports, and explicit recovery states.
4. Add stage composition from registered entrypoints and declared artifact connections.
5. Add metric/plot selection and new registered collectors. Runtime LLM interpretation remains unnecessary.

Two documented decisions need explicit revision during implementation: the five-primitive map and the exclusion of sequenced work. The requested design changes both. The single-writer dispatch contract and metric-agnostic core can remain intact. [S1] [S22] [S27]

## Decisions for the next discussion

- **Composition:** recommend selecting and connecting registered project entrypoints. Register new source outside the experiment form, then reload its declaration.
- **Measurements:** recommend field selection and approved aggregations in the UI, plus project scripts for new scientific metrics. Defer arbitrary expressions.
- **Script ownership:** recommend inspectable generated wrappers, with an explicit transition to project-owned code for manual edits.
- **Source changes:** recommend a new reviewed revision after code/configuration changes, with immutable snapshots for dispatched executions.
- **Mixed execution:** recommend resource settings per stage, with independent variants able to contain coordinated GPU work.

[S1]: ../../CONTEXT.md:7
[S2]: ../../controller/experiments.py:71
[S3]: the attached research project/harness/run_traces.py:129
[S4]: the attached research project/harness/run_traces.py:292
[S5]: the attached research project/tlaibench/run_traces.py:248
[S6]: the attached research project/tlaibench/run_traces.py:962
[S7]: the attached research project/slurm/tlaibench_submit.sh:57
[S8]: the attached research project/slurm/tlaibench_sweep.sh:108
[S9]: the attached research project/harness/overview.py:251
[S10]: the attached research project/tlaibench/report.py:939
[S11]: ../../controller/dispatch.py:213
[S12]: the attached research project/unityHPC/fetch.sh:16
[S13]: the attached research project/tests/test_tlaibench_runner.py:448
[S14]: ../../skills/connect/SKILL.md:11
[S15]: ../../skills/connect/SKILL.md:11
[S16]: ../../lib/scaffold.py:87
[S17]: the attached research project/docs/agents/unity-operations.md:48
[S18]: ../../controller/ops/README.md:1
[S19]: ../../lib/metrics.py:34
[S20]: ../../templates/CLAUDE.md.template:49
[S21]: ../../scripts/hpc-scaffold:113
[S22]: ../../docs/adr/0001-two-component-split.md:1
[S23]: the attached research project/slurm/tlaibench_submit.sh:210
[S24]: the attached research project/tlaibench/report.py:269
[S25]: the attached research project/docs/adr/0004-keep-afterok-with-an-external-checker.md:1
[S26]: the attached research project/harness/run_traces.py:381
[S27]: ../../docs/design-decisions.md:220
