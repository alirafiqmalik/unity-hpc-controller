# llms-agents

An evaluation workspace for an LLM application or agent. The layout follows
how MLflow evaluates GenAI apps: a **dataset** of inputs and expectations, a
**predict function**, a set of **scorers**, and the **traces** one evaluation
run produces. The controller dashboard opens the project on those traces.
New evaluations require setup checks, a frozen plan review, and explicit approval.

```
dataset/<name>/dataset.json       metadata, tags, provenance
dataset/<name>/records.jsonl      {record_id, inputs, expectations, source, tags}
prompts/system.md                 the prompt; its digest is the prompt version
unityHPC/agent.py                 predict(inputs, context) -> response, spans, tokens
unityHPC/scorers.py               correctness, exact_match, contains_all, judge, …
unityHPC/evaluate.py              run · validate · fetch · check
unityHPC/project.json             workflows for the controller + the `genai` connector
evaluations/<run>/manifest.json   one evaluation run
evaluations/<run>/traces.jsonl    one trace per record, with assessments
```

## The flow

1. **Dataset.** Put records under `dataset/<name>/records.jsonl`. Each record
   has `inputs` and, when labeled, `expectations`. The dashboard can create a
   dataset and add records by hand or from selected traces.
2. **Predict.** `agent.py` calls your model once per record. The default talks
   to an OpenAI-compatible endpoint (`LLM_BASE_URL`), such as `vllm serve` on
   the compute node. Replace `predict` with your agent and keep one span per
   step.
3. **Score.** `scorers.py` turns each output into assessments: pass/fail,
   a score, or a category. `judge` is an LLM-as-a-judge over a rubric.
4. **Run.** From the dashboard, *Evaluation runs → New evaluation* picks a
   dataset, a model and the scorers. Setup checks prepare a frozen plan.
   The user reviews the plan and explicitly approves the run. `evaluate-smoke` runs the mock engine on the controller; `evaluate`
   runs on a GPU node through `unityHPC/run.sh`.
5. **Review.** *Traces* lists every request with its assessments and the
   expectations it was graded against. Select traces → *Actions → Add to
   evaluation dataset* to grow a regression set from real failures.

## Commands

```bash
python3 unityHPC/evaluate.py check                                   # mock run on the first dataset
python3 unityHPC/evaluate.py run --dataset example --model mock --mock true --out evaluations/smoke
python3 unityHPC/evaluate.py run --dataset example --model Qwen/Qwen3-1.7B --out evaluations/qwen3-1.7b
bash unityHPC/run.sh run qwen3-1.7b                                  # the same, as a SLURM job
```

## The connector

The `genai` block of `unityHPC/project.json` tells the dashboard where the
datasets and runs live and how trace fields map onto its columns. The
defaults match this layout. A project with another trace format sets
`traces.fields`, `traces.assessments` and `traces.expectations` to its own
dotted field paths.
