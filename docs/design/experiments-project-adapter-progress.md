# Project adapter implementation record

Recorded 2026-10-03. This record covers the project adapter and scaffold work.
The main implementation record covers the controller and UI.

## Ownership and preservation

The attached project remains at `../../research/ai-ml/experiments/llm-thinking-trace`
relative to the plugin's parent workflow directory.
Scientific modules and datasets retain their existing paths.

The initial project backup is `[temporary local artifact]`.
It contains the tracked diff, status, untracked files, and copies of both changed harness modules.
The adapter work leaves all initially modified project files intact.
The controller's separate dispatcher update changes `unityHPC/run.sh`.

Scaffold generation now preserves existing `.env`, `sync.sh`, and `fetch.sh` files.
Explicit environment flags remain available for requested configuration changes.
The connect skill and generated guidance describe current controller operations.
They remove retired skills, training assumptions, and resident collector instructions.

## Compatibility preview

| Record | Before | Workspace interpretation | Activation |
| --- | --- | --- | --- |
| Attached registry primitive | `gpu` | `multi-gpu`, independent variants | Project declaration only |
| Application | Undeclared | `ml` | Project declaration only |
| Campaign, group, job identities | Existing values | Existing values | No rewrite |
| Fixed catalog | `unityHPC/experiments.json` | Existing catalog remains available | No conversion |
| Project transfers | Custom sync and fetch scripts | Existing scripts plus separate scoped adapter | No replacement |
| Legacy `ml` | Coordinated allocation | Compatibility mapping remains explicit | No implicit fan-out |

The manifest records the migration preview and rollback boundary.
Rollback retains workspace records and source snapshots.
It does not reinterpret coordinated work as independent experiments.

## Project contract

`unityHPC/project.json` declares schema version 1 and maps these capabilities:

- TLAiBench T1 and T1 → T2 → T3 collection.
- Original corpus collection for the two vendored benchmark inputs.
- Optional cluster Smoke test gates and a bounded controller mock workflow.
- Automatic CPU analysis after collection, with separate reports for each condition.
- Scoped artifact retrieval, corpus completeness checks, and report completeness checks.
- Model choices from `tlaibench.models.load_campaign()`, including its exclusions.
- Metrics with source fields, units, dimensions, denominator, and exclusions.
- Explicit optional turn prompts and outputs.

The source closure includes `harness`, `tlaibench`, configuration, vendored datasets,
the adapter, requirements, and model/environment locks.
The controller records the environment file digest without copying secret values.
The connection reports the absent plotting entrypoint as a capability gap.
Online original benchmarks need immutable input declarations before workspace collection.

## Execution and artifacts

`unityHPC/workspace_adapter.py` contains deterministic project operations.
Collection writes isolated corpus files, a per-stage summary, and companion provenance.
The adapter rejects nonempty outputs and incompatible parent artifacts.
T2 requires complete T1 evidence. T3 requires complete T2 evidence.

Parent checks cover model, context, token cap, sample count, seed, mock status, and available items.
Smoke test artifacts cannot satisfy a research prerequisite.

Completeness requires the expected record count, successful runner completion, and no harness errors.
A negative scientific outcome can still form a complete artifact.
Scoped fetch selects one execution, variant, and stage.
It preserves changed local files through backups and never uses `--delete`.

Analysis scans each selected condition separately.
This preserves token-cap conditions despite the legacy record ID omitting the effective cap.
Each analysis revision writes fresh reports and an input-file digest record.
Default analysis excludes Smoke test artifacts.

Resume requires a separately reviewed checkpoint operation.
Collection writes its source and input intent before generation, so interrupted runs retain auditable evidence.
The checkpoint check requires compatible source, model, environment, stage, parameters, purpose, and parent artifacts.
Resume copies completed records into a fresh output directory and preserves the original checkpoint.
It repairs only an incomplete final JSONL record in the copy.

The native runner skips completed record IDs and generates the remaining records.
Companion metadata records the prior execution and preserved-record count.
The existing project catalog computes cumulative accuracy across the resumed corpus.
Retry also uses a separate reviewed plan and fresh output directories.

## Immutable external references

`unityHPC/model-lock.json` contains actual public model commit references:

| Model | Commit |
| --- | --- |
| DeepSeek-R1-Distill-Qwen-1.5B | `ad9f0ae0864d7fbcd1cd905e3c6c5b069cc8b562` |
| Qwen3-1.7B | `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e` |

The bounded lock operation reads model metadata without downloading weights.
The engine receives the exact revision for both weights and tokenizer.
Other models need their own lock record before real collection.

Real collection currently fails its readiness check because the approved GPU environment lock is absent.
The local project environment lacks vLLM, so it cannot supply an honest collection environment lock.
`unityHPC/environment.lock.json` records this missing evidence explicitly.
The mock workflow uses a fixed project-owned mock identity and passes readiness checks.

To capture the approved environment, run this command within that environment:

```bash
python3 unityHPC/workspace_adapter.py lock-environment --out unityHPC/environment.lock.json
```

The collector checks installed package versions against the frozen lock before model loading.
A changed lock requires a new plan review.
No live cluster workload ran during this implementation.

## Checks

| Check | Result |
| --- | --- |
| Plugin scaffold, setup, displacement, CLI, and legacy end-to-end checks | 66 passed |
| Project adapter, harness core, and TLAiBench report checks | 107 passed |
| Actual project through HTTP, plan review, approval, worker, and artifacts | Passed |
| Separate analysis fixture through review and approval, twice | Passed |
| Four frozen mock wrappers with two models and two token caps | Passed |
| Scoped fetch command construction | Passed without network transfer |
| Interrupted mock resume and inherited analysis | Passed with fresh outputs and preserved checkpoint |
| Real readiness with missing collection environment lock | Correctly blocked |

`tests/test_workspace_project_mock.py` copies the project into a temporary directory.
It uses isolated controller state and fails immediately on cluster transport.
The test retains Smoke test purpose and checks that research analysis rejects those artifacts.
Separate synthetic research fixtures exercise report revisions without changing the Smoke test artifacts.
The test supports `UNITY_PROJECT_MOCK_SOURCE` and skips when the external checkout is unavailable.

The standalone frozen-wrapper check produced its files at `[temporary local artifact]`.
It preserved all four conditions and both token caps in four reports.

## Remaining project activation work

The approved GPU environment must supply its exact package lock.
Additional selected models need immutable model revisions.
New online benchmark inputs need immutable dataset declarations.
A future plotting entrypoint remains project-owned work.
These limitations appear as readiness errors or capability gaps.
