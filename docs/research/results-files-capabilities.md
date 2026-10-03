# Results and Files capability review

Research date: 2026-10-03. Local source and representative artifacts only. No cluster operation ran.
This report supports [Results](../design/results-spec.md) and [Files](../design/files-spec.md).
It extends the [connection review](project-connection-harness.md) and [tool review](project-workspace-tools.md).

## Evidence boundary

The worktree contains concurrent Experiments implementation and unrelated changes.
The observations below describe inspected source, not a deployed or tested release.
New workspace files appeared during this review. Their presence does not prove complete runtime support.
[ADR 0008](../adr/0008-project-workspace-and-approved-executions.md) supplies the current connection, storage, and API direction.
The accepted [Experiments specification](../design/experiments-spec.md) remains the product authority for Q1–Q23.

## Capability inventory

| Capability | Evidence observed | Required work |
| --- | --- | --- |
| Scheduler logs and corpus pull | `dispatch.fetch` calls `run.sh fetch`, then the optional project hook. It returns separate log and artifact outcomes. [C1] | Persistent transfer identity, exact selection, progress, reconciliation, and per-artifact outcomes |
| Fetch scope | The controller passes campaign to `run.sh`. It invokes the artifact hook without campaign or execution arguments. [C1] | A versioned adapter for explicit artifact paths. The legacy hook must retain its broad scope label. |
| Original corpus | `harness.catalog` scans JSONL plus manifests and deduplicates by `record_id` across its root. [P1] | Selected-input adapters, execution/variant ownership, query index, and provenance coverage |
| TLAiBench reports | `tlaibench.report` writes Markdown, summary TSV, chain TSV, and JSON. Its flattening exposes outcomes, phases, tokens, timings, and toolchain versions. [P2] | Scope-preserving adapters, revision isolation, immutable report inputs, and UI routes |
| TLAiBench deduplication | `scan` keeps the first `record_id` across the entire scanned root. It excludes `SUPERSEDED` directories. [P2] | Partition by execution and variant before deduplication. No combined-root adapter that loses token-cap conditions. |
| Validation | `harness.validate` checks record shape and basic field consistency. [P3] | Expected-item set, duplicate conflict handling, parent resolution, and completeness evidence |
| File browsing | The inspected workspace Files view explains ownership and exposes connection details. It does not implement a file browser. [C2] | Scoped tree, bounded preview, safe download, artifact states, and transfer UI |
| Workspace state | `workspace_store.py` supplies versioned SQLite records and draft conflict checks. [C3] | Results contracts must extend the store without assuming a complete result-query service. |
| Scientific plotting | Existing research found no reusable plotting entrypoint. This review found report exports, not a project plot operation. [P2] | Declare and implement project plotting operations. Generic presentation of declared numeric fields can use fixed UI chart forms. |

The existing project hook uses backups and no deletion for both corpus trees.
It does not regenerate summaries, validate complete corpora, or retrieve one selected execution. [P4]
Successful transport therefore proves neither scientific completeness nor report freshness.

## Representative records inspected

The following observations come from local artifact files. These files are evidence fixtures, not current cluster status.
The review read each selected manifest and the first JSONL record without running scientific code.

| Source | Observed fields and limits |
| --- | --- |
| Original corpus, FOLIO | `record_id`, `item_id`, prompts, full output, trace, answers, `is_correct`, token counts, timing, engine, and `benchmark_meta`. Manifest dataset identity lacks an immutable dataset revision. `git_sha` is `nogit`. [A1] |
| TLAiBench T1 | The manifest reports `counts.done: 0`, `counts.skipped: 160`, and `n_items: 160`, while the shard contains records. Resume counters cannot establish corpus completeness alone. [A2] |
| TLAiBench T2 | Records include `benchmark_meta.parent_record_id` and `parent` with record, item, shard, and outcome. Manifests include `tlaibench.parent_run`. [A3] [A3R] |
| TLAiBench T3 | Records expose turn arrays, tool calls/results, phase verdicts, applicability, skipped reasons, artifact text, and truncation lists. [A4] [A4R] |
| Effective generation settings | T2/T3 manifests contain `gen_params_record_id.max_tokens: 32256` and effective per-sample `max_tokens: 8192`. Record `benchmark_meta.gen_params_effective` carries the actual request settings. [A3] [A4] [A3R] [A4R] |
| Incomplete provenance | TLAiBench manifests contain null Git identity and code-dirty values. No UI can reconstruct an exact historical source snapshot from those values. [A2] [A3] [A4] |

The sample schema supports emitted-text inspection. It does not imply hidden states, attention weights, or token probabilities.
A turn can retain a prompt digest without retaining its complete prompt text.
The inspector distinguishes missing fields from recorded empty values.

The project glossary defines observable traces, First numbers, model failures, harness errors, dataset limitations, and stranded stages. [P5]

## Engineering consequences

1. Artifact identity includes its producing execution, variant, stage, and attempt. Historical research-run identity remains separate.
2. A checked artifact snapshot records content digests and expected-item coverage. A mutable pathname is not a frozen analysis input.
3. A comparison aligns dataset item and sample identity across distinct conditions. `record_id` alone is neither a cross-condition join nor a global deduplication key.
4. Effective generation settings take precedence for condition labels. Original identity settings remain inspectable as separate provenance.
5. The original corpus and TLAiBench remain separate datasets and report families. No default combined score crosses their measurement definitions.
6. Existing incomplete provenance stays unknown. Import records can describe evidence without claiming that the original execution had workspace identity.
7. File transport, artifact integrity, corpus completeness, and report currency need separate state fields.
8. The Files page cannot advertise safe execution-scoped retrieval through the current broad corpus hook.

These are agent-selected design consequences. They do not change Q1–Q23.

## Sources

[C1]: ../../controller/dispatch.py
[C2]: ../../controller/web/src/modules/workspace/Workspace.tsx
[C3]: ../../controller/workspace_store.py
[P1]: the attached research project/harness/catalog.py
[P2]: the attached research project/tlaibench/report.py
[P3]: the attached research project/harness/validate.py
[P4]: the attached research project/unityHPC/fetch.sh
[P5]: the attached research project/CONTEXT.md
[A1]: the attached research project/data/traces/20260713_032909_DeepSeek-R1-Distill-Qwen-7B_folio/manifest.json
[A2]: the attached research project/data/tlaibench/tlai_t1_r1_distill_qwen_14b/manifest.json
[A3]: the attached research project/data/tlaibench/tlai_t2_r1_distill_qwen_14b/manifest.json
[A4]: the attached research project/data/tlaibench/tlai_t3_r1_distill_qwen_14b/manifest.json

[A3R]: the attached research project/data/tlaibench/tlai_t2_r1_distill_qwen_14b/deepseek-ai_DeepSeek-R1-Distill-Qwen-14B__tlaibench_t2.jsonl
[A4R]: the attached research project/data/tlaibench/tlai_t3_r1_distill_qwen_14b/deepseek-ai_DeepSeek-R1-Distill-Qwen-14B__tlaibench_t3.jsonl
