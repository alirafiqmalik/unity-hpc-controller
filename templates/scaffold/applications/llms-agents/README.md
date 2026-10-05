# llms-agents

This application runs two lanes on one stage runner.

The train lane prepares data, trains, consolidates weights, and evaluates.
The agent lane runs the commands a project declares.
`run.sh` is the only submitter. One stage is one `run.sh run` and one ledger row.

A second project adopts this application with three inputs:

- a workflow file
- a dataset adapter name
- a project eval argv

No plugin change is required.

## Hooks

Each name is a field on a stage. The runner calls the project command. It does not absorb the project.

1. `engine`. `project` runs the project argv and starts in-process vLLM inside that command. `openai` starts `python -m vllm.entrypoints.openai.api_server`. The train-lane default is `openai`.
2. `eval.kind`. `lm-eval` runs `lm_eval --model local-completions` against `http://127.0.0.1:8000/v1`. `project` runs the project grader argv. Project records are not lm-eval rows.
3. `command`. The runner calls this argv. Use it for `collect`, `analyze`, `validate`, `fetch`, and the mock smoke. Multi-turn work is this command. Pass the parent corpus with `{parent_dir}`.
4. `resources`. Set `primitive`, `gpus`, `cpus`, `memory`, `walltime`, and `constraint` on the stage. Those values override `.env` for that one `run.sh` invocation. The primitive is `cpu`, `gpu`, `multi-cpu`, or `multi-gpu`.
5. `depends_on`. The child `run.sh run` receives `--dependency=afterok:<parent job id>`. A failed parent does not start the child. The runner does not emit `afterany`.
6. `outputs`. List the files the stage writes. A corpus is JSONL under the campaign tree. The completeness file is `corpus/manifest.json` when the stage declares that path. `run.sh fetch` pulls `$RESULTS_DIR`.
7. `metrics`. The runner writes `metrics.json` with a `report` list, `labels`, and flat numeric keys. It also prints `key: value` lines so the scalar reader is not empty. The harness JSON stays beside `metrics.json`.
8. `location: controller`. The mock smoke runs on this machine with the mock engine, one item, no GPU, and no SSH. Wire the workflow only after that command exits 0.
9. `resume`. A project argv plus `{checkpoint_dir}`. The template has the slot. It does not apply the project resume policy.
10. `format` and `adapter`. `native` writes each source line unchanged. `sharegpt` and `preference` convert only when the stage sets that format. The workflow file declares the source schema and the adapter name.
11. `inputs`. `from_stage` names the parent. The child command receives `{parent_dir}`.
12. Stranded-stage report. The report names a parent SLURM marked failed whose declared outputs are complete. The report does not submit, resubmit, or edit the ledger.

Secrets stay in `unityHPC/.env`. The cache write and the weight-directory write refuse that file.

Shared storage is the project `REMOTE_DIR` on `/work`. `HF_HOME` is the shared Hugging Face cache. There is no `/vols/hpc_shared` path.
