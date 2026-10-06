"""The LLMs & Agents evaluation reader, dataset writer and HTTP routes.

Two projects stand in for the two layouts the reader supports: one scaffolded
from the `llms-agents` template (native trace format, defaults only), and one
with a foreign trace format mapped through the `genai` connector, the way
llm-thinking-trace maps its TLAiBench corpus.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from controller import genai, registry
from controller.http import Request, handle

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI = REPO_ROOT / "scripts" / "hpc-scaffold"


def _call(method, url, body=None):
    parts = urlparse(url)
    raw = b"" if body is None else json.dumps(body).encode()
    response = handle(Request(method=method, path=parts.path, query=parse_qs(parts.query), body=raw))
    return response.status, json.loads(response.body.decode()) if response.body else {}


@pytest.fixture
def native_project(tmp_project, tmp_data_dir):
    """A project scaffolded from the template, with one mock run on disk."""
    result = subprocess.run(
        [sys.executable, str(CLI), "--application", "llms-agents", "--project-dir", str(tmp_project),
         "--account", "pi_demo", "--remote-dir", "/work/pi_demo/u/demo",
         "--job-command", "python3 unityHPC/evaluate.py run --dataset example --model m --out evaluations/$EXP"],
        capture_output=True, text=True, env={**__import__("os").environ, "UNITY_HPC_NONINTERACTIVE": "1"},
    )
    assert result.returncode == 0, result.stderr
    run = subprocess.run(
        [sys.executable, "unityHPC/evaluate.py", "run", "--dataset", "example", "--model", "mock-model", "--mock", "true",
         "--out", "evaluations/smoke-1", "--name", "smoke-1"],
        cwd=tmp_project, capture_output=True, text=True,
    )
    assert run.returncode == 0, run.stderr
    registry.attach(slug="native", path=tmp_project, primitive="gpu", application="llms-agents")
    return tmp_project


@pytest.fixture
def mapped_project(tmp_path, tmp_data_dir):
    """A foreign trace format: corpus records under data/<collection>/<run>/ with a connector."""
    root = tmp_path / "mapped"
    (root / "unityHPC").mkdir(parents=True)
    run = root / "data" / "bench" / "run-a"
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(json.dumps({
        "run_tag": "run-a", "model_id": "org/model-7b", "benchmark": "bench_t1", "accuracy": 0.5, "n_items": 2,
        "start_time_utc": "2026-09-20T08:10:00Z", "end_time_utc": "2026-09-20T08:14:00Z",
        "dataset_source": {"path": "/remote/datasets/bench"}, "counts": {"done": 2},
        "engine": "vllm", "engine_version": "0.9.0", "tlaibench": {"prompt": {"prompt_version": "p-v1", "prompt_sha256": "abc"}},
    }))
    rows = [
        {"record_id": "r1", "prompt_raw": "Solve puzzle one", "final_answer_text": "---- MODULE One ----", "is_correct": True,
         "token_counts": {"total_completion": 120, "prompt": 40}, "timing": {"generation_time_s": 3.5}, "timestamp_utc": "2026-09-20T08:11:00Z",
         "error": None, "model_id": "org/model-7b", "item_id": "bench_t1_One_k00",
         "benchmark_meta": {"puzzle": "One", "outcome": "pass", "verdict": {"detail": "phase 2 exit 12"}, "gold_path": "/g/OneGold.tla",
                            "turns": [{"turn_idx": 0, "thinking_trace": "think", "raw_completion": "spec", "wall_s": 1.5}]}},
        {"record_id": "r2", "prompt_raw": "Solve puzzle two", "final_answer_text": "", "is_correct": False,
         "token_counts": {"total_completion": 10, "prompt": 40}, "timing": {"generation_time_s": 0.5}, "timestamp_utc": "2026-09-20T08:12:00Z",
         "error": "harness failed", "model_id": "org/model-7b", "item_id": "bench_t1_Two_k00",
         "benchmark_meta": {"puzzle": "Two", "outcome": "harness_error", "verdict": {"detail": "crash"}, "gold_path": None, "turns": []}},
    ]
    (run / "org_model-7b__bench_t1.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    stale = root / "data" / "bench" / "run-old"
    stale.mkdir()
    (stale / "manifest.json").write_text(json.dumps({"run_tag": "run-old", "model_id": "org/model-7b", "n_items": 1,
                                                     "start_time_utc": "2026-09-01T00:00:00Z", "end_time_utc": "2026-09-01T00:01:00Z"}))
    (stale / "SUPERSEDED").write_text("")
    (stale / "x.jsonl").write_text(json.dumps(rows[1]) + "\n")
    dataset = root / "dataset" / "bench"
    dataset.mkdir(parents=True)
    (dataset / "dataset.json").write_text(json.dumps({"schema_version": 1, "name": "bench", "description": "two puzzles",
                                                      "tags": {"family": "bench"}, "records_file": "records.jsonl"}))
    (dataset / "records.jsonl").write_text(json.dumps({"record_id": "One", "inputs": {"puzzle": "One"}, "expectations": {"gold": "x"}}) + "\n")
    (root / "unityHPC" / "project.json").write_text(json.dumps({
        "schema_version": 1,
        "genai": {
            "datasets_dir": "dataset",
            "evaluation_roots": [{"path": "data/bench", "manifest": "manifest.json", "traces": "*.jsonl", "depth": 1,
                                  "collection": "bench", "default": True}],
            "evaluation_fields": {"name": "run_tag", "model": "model_id", "dataset": ["dataset_source.path", "benchmark"],
                                  "started": "start_time_utc", "finished": "end_time_utc", "n_items": "n_items",
                                  "trace_count": "counts.done", "prompt": "tlaibench.prompt",
                                  "metrics": {"accuracy": "accuracy"},
                                  "agent": {"model": "model_id", "engine": "engine", "engine_version": "engine_version"}},
            "traces": {
                "fields": {"trace_id": "record_id", "request": "prompt_raw", "response": "final_answer_text",
                           "request_time": "timestamp_utc", "duration_s": "timing.generation_time_s",
                           "tokens": "token_counts.total_completion", "prompt_tokens": "token_counts.prompt", "error": "error",
                           "session": "benchmark_meta.puzzle", "dataset_record": "item_id", "model": "model_id",
                           "spans": "benchmark_meta.turns"},
                "assessments": {"correctness": {"field": "is_correct", "kind": "pass_fail", "source": "grader",
                                                "rationale": "benchmark_meta.verdict.detail"},
                                "outcome": {"field": "benchmark_meta.outcome", "kind": "category"}},
                "expectations": {"gold_spec_path": "benchmark_meta.gold_path"},
            },
        },
    }))
    registry.attach(slug="mapped", path=root, primitive="gpu", application="llms-agents")
    return root


# --------------------------------------------------------------------------- #
# Native layout (the template)
# --------------------------------------------------------------------------- #

def test_native_project_reads_dataset_run_and_traces_with_defaults(native_project):
    conn = genai.connector(registry.get("native"))
    assert conn["declared"] is True and conn["datasets_dir"] == "dataset"
    data = genai.datasets("native")["datasets"]
    assert [d["name"] for d in data] == ["example"]
    assert data[0]["profile"] == {"records": 3, "labeled": 3, "unlabeled": 0, "inputs_schema": ["question"],
                                  "expectations_schema": ["expected_facts", "expected_response", "guidelines"],
                                  "sources": {"HUMAN": 3}, "tag_keys": ["topic"]}
    assert data[0]["evaluations"] == 1
    runs = genai.evaluations("native")["evaluations"]
    assert len(runs) == 1 and runs[0]["name"] == "smoke-1" and runs[0]["dataset"] == "example"
    assert runs[0]["state"] == "complete" and runs[0]["collection"] == "evaluations"
    assert runs[0]["metrics"]["accuracy"] == 0.0 and runs[0]["agent"]["model"] == "mock-model"
    table = genai.traces("native")
    assert table["total"] == 3 and set(table["assessments"]) == {"correctness", "response_length"}
    assert table["assessments"]["correctness"]["fail"] == 3 and table["assessments"]["response_length"]["kind"] == "score"
    assert table["expectations"] == ["expected_facts", "expected_response", "guidelines"]
    row = table["traces"][0]
    assert row["state"] == "OK" and row["tokens"] > 0 and row["dataset_record"].startswith("example-")
    full = genai.trace("native", row["evaluation_id"], row["trace_id"])
    assert full["spans"][0]["type"] == "LLM" and full["assessments"]["correctness"]["rationale"]
    assert full["inputs"] == {"question": full["request"]}


def test_native_sessions_prompts_and_agent_versions(native_project):
    sessions = genai.sessions("native")["sessions"]
    assert len(sessions) == 3 and all(s["traces"] == 1 for s in sessions)
    prompts = genai.prompts("native")
    assert [f["path"] for f in prompts["files"]] == ["prompts/system.md"]
    assert prompts["observed"][0]["version"] == "system.md" and len(prompts["observed"][0]["sha256"]) == 64
    agents = genai.agent_versions("native")["versions"]
    assert agents[0]["model"] == "mock-model" and agents[0]["traces"] == 3 and agents[0]["pass_rate"] == 0.0


def test_launch_options_bind_the_dataset_parameter(native_project):
    status, answer = _call("GET", "/api/v1/projects/native/genai/launch")
    assert status == 200, answer
    assert answer["valid"] is True, answer["errors"]
    workflows = {w["id"]: w for w in answer["workflows"]}
    assert set(workflows) == {"evaluate", "evaluate-smoke"}
    assert workflows["evaluate"]["dataset_parameter"] == "dataset" and workflows["evaluate"]["dataset"] is None
    assert workflows["evaluate-smoke"]["purpose"] == "smoke-test"
    assert answer["datasets"] == ["example"]
    model = next(p for p in workflows["evaluate"]["parameters"] if p["name"] == "model")
    assert model["default"] == "Qwen/Qwen3-1.7B"


def test_evaluation_setup_requires_separate_review_and_approval(native_project):
    from controller import workspace_store as store
    status, answer = _call("POST", "/api/v1/projects/native/genai/evaluations",
                           {"workflow": "evaluate-smoke", "name": "ui smoke", "dataset": "example",
                            "dataset_parameter": "dataset", "parameters": {"n_items": 2}})
    assert status == 201, answer
    assert answer["ok"] is True, answer
    assert store.listing("native", "execution") == []
    plan = answer["plan"]
    assert plan["config"]["parameters"]["dataset"] == "example"
    assert plan["stages"][0]["outputs"]
    status, execution = _call("POST", f"/api/v1/projects/native/runner/plans/{answer['plan_id']}/approve",
                              {"idempotency_key": "reviewed-evaluation"})
    assert status == 202, execution
    assert execution["state"] == "approved" and execution["stages"][0]["location"] == "controller"
    status, listing = _call("GET", "/api/v1/projects/native/genai/evaluations")
    assert status == 200
    assert listing["executions"][0]["id"] == execution["id"]


def test_evaluation_approval_waits_for_the_worker_project_lock(native_project):
    import threading
    from controller import workspace_worker

    status, prepared = _call("POST", "/api/v1/projects/native/genai/evaluations",
                            {"workflow": "evaluate-smoke", "dataset": "example",
                             "dataset_parameter": "dataset", "parameters": {"n_items": 1}})
    assert status == 201, prepared

    held, release = threading.Event(), threading.Event()

    def tick():
        with workspace_worker.project_lock("native") as acquired:
            assert acquired
            held.set()
            release.wait(5)

    worker = threading.Thread(target=tick)
    worker.start()
    held.wait(5)
    threading.Timer(0.6, release.set).start()
    try:
        status, answer = _call("POST", f"/api/v1/projects/native/runner/plans/{prepared['plan_id']}/approve",
                               {"idempotency_key": "reviewed-evaluation"})
    finally:
        release.set()
        worker.join()
    assert status == 202, answer
    assert answer["state"] == "approved"
    status, listing = _call("GET", "/api/v1/projects/native/genai/evaluations")
    assert len(listing["executions"]) == 1, "one approval is one execution"


def test_launch_refuses_an_undeclared_workflow(native_project):
    status, answer = _call("POST", "/api/v1/projects/native/genai/evaluations", {"workflow": "nope"})
    assert status == 400 and "not an evaluation workflow" in answer["error"]


# --------------------------------------------------------------------------- #
# Mapped layout (a foreign corpus through the connector)
# --------------------------------------------------------------------------- #

def test_connector_maps_a_foreign_corpus_onto_the_trace_table(mapped_project):
    runs = genai.evaluations("mapped")["evaluations"]
    by_name = {r["name"]: r for r in runs}
    assert by_name["run-a"]["dataset"] == "bench" and by_name["run-a"]["model"] == "org/model-7b"
    assert by_name["run-a"]["indexed"] is False and by_name["run-a"]["traces"] == 2
    assert by_name["run-old"]["state"] == "superseded"
    table = genai.traces("mapped")
    assert table["total"] == 2, "superseded runs stay out of the default scope"
    assert table["states"] == {"OK": 1, "ERROR": 1}
    summary = table["assessments"]
    assert summary["correctness"] == {"kind": "pass_fail", "count": 2, "pass": 1, "fail": 1, "values": {}, "pass_rate": 0.5}
    assert summary["outcome"]["values"] == {"pass": 1, "harness_error": 1}
    assert table["expectations"] == ["gold_spec_path"]
    first = next(r for r in table["traces"] if r["trace_id"] == "r1")
    assert first["session"] == "One" and first["tokens"] == 120 and first["duration_s"] == 3.5
    full = genai.trace("mapped", first["evaluation_id"], "r1")
    assert full["assessments"]["correctness"] == {"value": True, "kind": "pass_fail", "rationale": "phase 2 exit 12", "source": "grader"}
    assert full["spans"][0]["reasoning"] == "think" and full["spans"][0]["type"] == "LLM"
    assert full["expectations"] == {"gold_spec_path": "/g/OneGold.tla"}
    with_superseded = genai.traces("mapped", include_superseded=True)
    assert with_superseded["total"] == 3


def test_trace_filters_and_sorting(mapped_project):
    assert genai.traces("mapped", state="error")["total"] == 1
    assert genai.traces("mapped", session="Two")["traces"][0]["trace_id"] == "r2"
    assert genai.traces("mapped", assessment="correctness", assessment_value="pass")["total"] == 1
    assert genai.traces("mapped", assessment="outcome", assessment_value="harness_error")["total"] == 1
    assert genai.traces("mapped", search="puzzle two")["total"] == 1
    ordered = genai.traces("mapped", sort="tokens", descending=False)["traces"]
    assert [r["trace_id"] for r in ordered] == ["r2", "r1"]
    page = genai.traces("mapped", limit=1, offset=1)
    assert page["total"] == 2 and len(page["traces"]) == 1


def test_sessions_group_traces_by_puzzle(mapped_project):
    sessions = {s["session"]: s for s in genai.sessions("mapped")["sessions"]}
    assert set(sessions) == {"One", "Two"}
    assert sessions["One"]["assessments"]["correctness"]["pass_rate"] == 1.0
    assert sessions["Two"]["states"] == {"ERROR": 1}


def test_prompts_and_agent_versions_come_from_run_manifests(mapped_project):
    prompts = genai.prompts("mapped")["observed"]
    assert prompts[0]["version"] == "p-v1" and prompts[0]["sha256"] == "abc"
    agents = genai.agent_versions("mapped")["versions"]
    assert agents[0]["details"] == {"engine": "vllm", "engine_version": "0.9.0"}
    assert agents[0]["pass_rate"] == 0.5


def test_index_cache_rebuilds_when_a_trace_file_changes(mapped_project):
    first = genai.traces("mapped")["total"]
    path = next((mapped_project / "data" / "bench" / "run-a").glob("*.jsonl"))
    with path.open("a") as handle:
        handle.write(json.dumps({"record_id": "r3", "prompt_raw": "three", "final_answer_text": "x", "is_correct": True,
                                 "token_counts": {"total_completion": 1}, "timestamp_utc": "2026-09-20T09:00:00Z",
                                 "model_id": "org/model-7b", "benchmark_meta": {"puzzle": "Three", "outcome": "pass"}}) + "\n")
    import os
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
    assert genai.traces("mapped")["total"] == first + 1


# --------------------------------------------------------------------------- #
# Datasets: the one thing the dashboard writes
# --------------------------------------------------------------------------- #

def test_create_dataset_add_records_and_export_traces(mapped_project):
    status, created = _call("POST", "/api/v1/projects/mapped/genai/datasets",
                            {"name": "Regression Set", "description": "failures to keep", "tags": {"type": "regression"}})
    assert status == 201, created
    assert created["name"] == "regression-set" and created["profile"]["records"] == 0
    folder = mapped_project / "dataset" / "regression-set"
    assert (folder / "dataset.json").is_file() and (folder / "records.jsonl").is_file()

    status, after = _call("POST", "/api/v1/projects/mapped/genai/datasets/regression-set/records",
                          {"records": [{"inputs": {"question": "2+2"}, "expectations": {"expected_response": "4"}}]})
    assert status == 200 and after["added"] == 1 and after["profile"]["labeled"] == 1
    status, again = _call("POST", "/api/v1/projects/mapped/genai/datasets/regression-set/records",
                          {"records": [{"inputs": {"question": "2+2"}, "expectations": {"expected_response": "4"}}]})
    assert again["added"] == 0 and again["skipped"] == 1, "identical inputs are not duplicated"

    table = genai.traces("mapped")
    refs = [{"trace_id": r["trace_id"], "evaluation_id": r["evaluation_id"]} for r in table["traces"]]
    status, exported = _call("POST", "/api/v1/projects/mapped/genai/datasets/regression-set/records",
                             {"traces": refs, "response_as_expectation": True})
    assert status == 200 and exported["added"] == 2
    records = {r["record_id"]: r for r in exported["records"]}
    assert records["bench_t1_One_k00"]["source"]["type"] == "TRACE"
    assert records["bench_t1_One_k00"]["expectations"]["gold_spec_path"] == "/g/OneGold.tla"
    assert records["bench_t1_One_k00"]["expectations"]["expected_response"] == "---- MODULE One ----"
    assert records["bench_t1_One_k00"]["inputs"] == {"request": "Solve puzzle one"}

    status, patched = _call("PATCH", "/api/v1/projects/mapped/genai/datasets/regression-set",
                            {"description": "renamed", "tags": {"type": "regression", "owner": "me"}})
    assert status == 200 and patched["description"] == "renamed" and patched["tags"]["owner"] == "me"
    status, listing = _call("GET", "/api/v1/projects/mapped/genai/datasets")
    assert [d["name"] for d in listing["datasets"]] == ["bench", "regression-set"]


def test_dataset_writes_are_validated(mapped_project):
    status, answer = _call("POST", "/api/v1/projects/mapped/genai/datasets", {"name": "../escape"})
    assert status == 400 and "dataset name" in answer["error"]
    status, answer = _call("POST", "/api/v1/projects/mapped/genai/datasets", {"name": "bench"})
    assert status == 409
    status, answer = _call("POST", "/api/v1/projects/mapped/genai/datasets/bench/records", {"records": [{"inputs": {}}]})
    assert status == 400 and "inputs" in answer["error"]
    status, answer = _call("POST", "/api/v1/projects/mapped/genai/datasets/bench/records", {})
    assert status == 400 and "nothing to add" in answer["error"]
    status, answer = _call("GET", "/api/v1/projects/mapped/genai/datasets/missing")
    assert status == 404


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #

def test_summary_and_unknown_routes(mapped_project):
    status, summary = _call("GET", "/api/v1/projects/mapped/genai/summary")
    assert status == 200 and summary["application"] == "llms-agents"
    assert summary["counts"] == {"datasets": 1, "evaluations": 2, "evaluations_complete": 1, "traces": 2, "sessions": 2, "models": 1}
    assert summary["collections"][0]["id"] == "bench"
    status, answer = _call("GET", "/api/v1/projects/mapped/genai/nothing")
    assert status == 404
    status, answer = _call("GET", "/api/v1/projects/unknown/genai/summary")
    assert status == 404
    status, answer = _call("GET", "/api/v1/projects/mapped/genai/traces?evaluation=ev-nope&limit=5")
    assert status == 200 and answer["total"] == 0


def test_connector_paths_stay_inside_the_project(tmp_path, tmp_data_dir):
    root = tmp_path / "escape"
    (root / "unityHPC").mkdir(parents=True)
    (root / "unityHPC" / "project.json").write_text(json.dumps({"schema_version": 1, "genai": {"datasets_dir": "../..", "evaluation_roots": ["../.."]}}))
    registry.attach(slug="escape", path=root, primitive="cpu", application="llms-agents")
    with pytest.raises(genai.GenAIError):
        genai.datasets("escape")
    assert genai.evaluations("escape")["evaluations"] == []


# --------------------------------------------------------------------------- #
# Dataset write containment and merge semantics
# --------------------------------------------------------------------------- #

def test_records_file_outside_the_dataset_folder_is_refused(mapped_project):
    meta = mapped_project / "dataset" / "bench" / "dataset.json"
    meta.write_text(json.dumps({"name": "bench", "records_file": "../../notes.jsonl"}))
    status, answer = _call("POST", "/api/v1/projects/mapped/genai/datasets/bench/records",
                           {"records": [{"inputs": {"puzzle": "Three"}}]})
    assert status == 400 and "inside the dataset folder" in answer["error"]
    assert not (mapped_project / "notes.jsonl").exists()
    assert [d["id"] for d in genai.datasets("mapped")["datasets"]] == [], "an unusable dataset is left out of the list"


def test_a_dataset_symlinked_out_of_the_datasets_dir_is_not_a_dataset(mapped_project, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (mapped_project / "dataset" / "escape").symlink_to(outside, target_is_directory=True)
    status, _ = _call("POST", "/api/v1/projects/mapped/genai/datasets/escape/records",
                      {"records": [{"inputs": {"q": "x"}}]})
    assert status == 404
    assert list(outside.iterdir()) == []


def test_a_hand_written_record_with_only_inputs_reads_as_objects(mapped_project):
    records = mapped_project / "dataset" / "bench" / "records.jsonl"
    records.write_text(records.read_text() + json.dumps({"inputs": {"puzzle": "Bare"}}) + "\n")
    detail = genai.dataset("mapped", "bench")
    bare = next(r for r in detail["records"] if r["inputs"] == {"puzzle": "Bare"})
    assert bare["expectations"] == {} and bare["source"] == {} and bare["tags"] == {}


def test_merging_known_inputs_updates_their_expectations_instead_of_skipping(mapped_project):
    records = mapped_project / "dataset" / "bench" / "records.jsonl"
    answer = genai.merge_records("mapped", "bench", {"records": [
        {"inputs": {"puzzle": "One"}, "expectations": {"gold": "y", "steps": 3}},
        {"inputs": {"puzzle": "One"}, "expectations": {"gold": "y", "steps": 3}},
        {"inputs": {"puzzle": "New"}},
    ]})
    assert (answer["added"], answer["updated"], answer["skipped"]) == (1, 1, 1)
    lines = [json.loads(line) for line in records.read_text().splitlines()]
    assert len(lines) == 2
    assert lines[0]["record_id"] == "One" and lines[0]["expectations"] == {"gold": "y", "steps": 3}


# --------------------------------------------------------------------------- #
# Connector mappings and aggregation
# --------------------------------------------------------------------------- #

def _rewrite_connector(root, change):
    path = root / "unityHPC" / "project.json"
    manifest = json.loads(path.read_text())
    change(manifest["genai"])
    path.write_text(json.dumps(manifest))


def test_a_list_valued_field_mapping_opens_the_trace(mapped_project):
    _rewrite_connector(mapped_project, lambda g: g["traces"]["fields"].update(request=["prompt_raw", "request"]))
    row = next(r for r in genai.traces("mapped")["traces"] if r["trace_id"] == "r1")
    full = genai.trace("mapped", row["evaluation_id"], "r1")
    assert full["request"] == "Solve puzzle one" and "prompt_raw" not in full["metadata"]


def test_two_expectations_with_equal_values_are_both_kept(mapped_project):
    _rewrite_connector(mapped_project, lambda g: g["traces"]["expectations"].update(gold_copy="benchmark_meta.gold_path"))
    row = next(r for r in genai.traces("mapped")["traces"] if r["trace_id"] == "r1")
    full = genai.trace("mapped", row["evaluation_id"], "r1")
    assert full["expectations"] == {"gold_spec_path": "/g/OneGold.tla", "gold_copy": "/g/OneGold.tla"}


def test_an_unassessed_value_is_neither_pass_nor_fail():
    rows = [{"assessments": {"c": {"kind": "pass_fail", "value": True}, "s": {"kind": "score", "value": 0.5}}},
            {"assessments": {"c": {"kind": "pass_fail", "value": None}, "s": {"kind": "score", "value": None}}}]
    summary = genai._assessment_summary(rows)
    assert summary["c"]["count"] == 1 and summary["c"]["pass_rate"] == 1.0 and summary["c"]["unassessed"] == 1
    assert summary["s"]["mean"] == 0.5 and summary["s"]["unassessed"] == 1


def test_an_encoded_trace_id_in_the_route_is_decoded(mapped_project):
    row = next(r for r in genai.traces("mapped")["traces"] if r["trace_id"] == "r1")
    status, answer = _call("GET", f"/api/v1/projects/mapped/genai/traces/%72%31?evaluation={row['evaluation_id']}")
    assert status == 200 and answer["trace_id"] == "r1"


def test_a_record_id_match_with_other_inputs_does_not_relabel_the_record(mapped_project):
    records = mapped_project / "dataset" / "bench" / "records.jsonl"
    answer = genai.merge_records("mapped", "bench", {"records": [
        {"record_id": "One", "inputs": {"puzzle": "Other"}, "expectations": {"gold": "wrong"}}]})
    assert (answer["added"], answer["updated"], answer["skipped"]) == (0, 0, 1)
    assert json.loads(records.read_text().splitlines()[0])["expectations"] == {"gold": "x"}


def test_an_existing_dataset_folder_with_capitals_opens(mapped_project):
    (mapped_project / "dataset" / "bench").rename(mapped_project / "dataset" / "Bench")
    status, answer = _call("GET", "/api/v1/projects/mapped/genai/datasets/Bench")
    assert status == 200 and answer["total"] == 1


@pytest.mark.parametrize("kind", ["directory", "manifest", "traces", "prompts"])
def test_evaluation_and_prompt_reads_reject_external_symlinks(native_project, tmp_path, kind):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "manifest.json").write_text(json.dumps({"name": "external", "purpose": "experiment"}))
    (outside / "traces.jsonl").write_text(json.dumps({"trace_id": "external-secret", "request": "outside"}) + "\n")
    (outside / "prompt.md").write_text("outside-secret")
    if kind == "directory":
        (native_project / "evaluations" / "external").symlink_to(outside, target_is_directory=True)
    elif kind == "manifest":
        folder = native_project / "evaluations" / "external"
        folder.mkdir()
        (folder / "manifest.json").symlink_to(outside / "manifest.json")
    elif kind == "traces":
        folder = native_project / "evaluations" / "external"
        folder.mkdir()
        (folder / "manifest.json").write_text('{"name":"safe"}')
        (folder / "traces.jsonl").symlink_to(outside / "traces.jsonl")
    else:
        (native_project / "prompts" / "external.md").symlink_to(outside / "prompt.md")
    evaluations = genai.evaluations("native", index=True)
    assert all(item["name"] != "external" for item in evaluations["evaluations"])
    assert all(item["trace_id"] != "external-secret" for item in genai.traces("native")["traces"])
    assert all(item["preview"] != "outside-secret" for item in genai.prompts("native")["files"])


def test_evaluation_purpose_comes_from_metadata_not_the_folder_name(native_project):
    folder = native_project / "evaluations" / "smoke-looking-historical-run"
    folder.mkdir()
    manifest = folder / "manifest.json"
    manifest.write_text('{"name":"historical"}')
    items = genai.evaluations("native")["evaluations"]
    assert next(item for item in items if item["name"] == "historical")["purpose"] == "unclassified"
    manifest.write_text('{"name":"historical","purpose":"experiment"}')
    items = genai.evaluations("native")["evaluations"]
    assert next(item for item in items if item["name"] == "historical")["purpose"] == "experiment"


def test_matrix_checks_two_models_on_two_datasets_before_approval(native_project):
    from controller import workspace_store as store
    genai.create_dataset('native', {'name': 'second'})
    options = _call('GET', '/api/v1/projects/native/genai/launch')[1]
    assert options['dataset_options']['example']['subsets'][0]['splits']
    selections = [{'dataset': name, 'workflow': 'evaluate-smoke', 'subset': 'default', 'split': 'local', 'parameters': {'n_items': 1}} for name in ('example', 'second')]
    # Add a real labeled record to the second dataset.
    genai.merge_records('native', 'second', {'records': [{'record_id': 'second-1', 'inputs': {'question': 'hello'}, 'expectations': {}}]})
    status, prepared = _call('POST', '/api/v1/projects/native/genai/evaluations/prepare-matrix', {'models': ['model-a', 'model-b'], 'datasets': selections, 'parameters': {}})
    assert status == 200 and prepared['ok'], prepared
    assert prepared['evaluations'] == 4
    assert len(prepared['prepared']) == 2
    assert store.listing('native', 'execution') == []
    for summary in prepared['prepared']:
        plan = store.read('native', 'plan', summary['plan_id'])
        assert {v['parameters']['model'] for v in plan['variants']} == {'model-a', 'model-b'}
        assert all(v['parameters']['dataset'] == summary['dataset'] for v in plan['variants'])
    status, launched = _call('POST', '/api/v1/projects/native/genai/evaluations/launch-matrix', {'plan_ids': [x['plan_id'] for x in prepared['prepared']]})
    assert status == 202 and launched['ok'], launched
    assert len(launched['launched']) == 2
    # Approval retries return the existing execution rather than dispatch twice.
    status, repeated = _call('POST', '/api/v1/projects/native/genai/evaluations/launch-matrix', {'plan_ids': [x['plan_id'] for x in prepared['prepared']]})
    assert status == 202 and repeated['ok'], repeated
    assert len(store.listing('native', 'execution')) == 2


def test_matrix_refuses_invalid_dataset_partition_without_creating_plans(native_project):
    from controller import workspace_store as store
    status, answer = _call('POST', '/api/v1/projects/native/genai/evaluations/prepare-matrix', {'models': ['m'], 'datasets': [{'dataset': 'example', 'workflow': 'evaluate-smoke', 'subset': 'default', 'split': 'invented-test'}]})
    assert status == 400 and 'Unknown subset or split' in answer['error']
    assert store.listing('native', 'plan') == []
    assert store.listing('native', 'execution') == []


def test_evaluation_removal_retains_files_indexes_and_excludes_reimport(mapped_project):
    import shutil
    from controller import genai_evaluations
    runs = genai.evaluations('mapped', index=True)['evaluations']
    chosen = next(x for x in runs if x['name'] == 'run-a')
    original = mapped_project / chosen['path']
    restore = mapped_project / 'copy-of-run-a'
    shutil.copytree(original, restore)
    trace = original / 'org_model-7b__bench_t1.jsonl'
    index = genai._cache_file(str(trace))
    assert index.exists()
    status, result = _call('DELETE', '/api/v1/projects/mapped/genai/evaluations', {'ids': [chosen['id']]})
    assert status == 200 and result['deleted'] == 1, result
    assert original.exists() and index.exists()
    assert str(trace) in genai._CACHE
    assert (mapped_project / 'dataset/bench/records.jsonl').exists()
    shutil.copytree(restore, original, dirs_exist_ok=True)
    assert chosen['id'] not in {x['id'] for x in genai.evaluations('mapped')['evaluations']}
    assert genai.traces('mapped')['total'] == 0
    status, result = _call('GET', f'/api/v1/projects/mapped/genai/evaluations/{chosen["id"]}')
    assert status == 404


def test_evaluation_removal_refuses_live_execution_and_retains_terminal_history(native_project):
    from controller import workspace_store as store
    execution = {'id': 'plan-delete', 'plan_id': 'plan-delete', 'experiment_id': 'exp-delete', 'campaign': 'plan-delete', 'state': 'active', 'stages': [{'id': 'eval', 'state': 'running'}]}
    with store.transaction('native') as db:
        store.put(db, 'execution', execution)
        store.put(db, 'plan', {'id': 'plan-delete'})
        store.put(db, 'experiment', {'id': 'exp-delete', 'executions': ['plan-delete']})
        store.put(db, 'artifact', {'id': 'art-delete', 'execution_id': 'plan-delete'})
        store.put(db, 'revision', {'id': 'exp-delete-r1', 'experiment_id': 'exp-delete'})
        db.execute('INSERT INTO dispatch_keys VALUES(?,?,?)', ('delete-key', 'plan-delete', 'plan-delete'))
    folder = native_project / '.unity-workspace/outputs/plan-delete'
    folder.mkdir(parents=True)
    (folder / 'evidence.json').write_text('{}')
    status, answer = _call('DELETE', '/api/v1/projects/native/genai/evaluations', {'execution_ids': ['plan-delete']})
    assert status == 409 and 'active' in answer['error']
    assert folder.exists() and store.read('native', 'execution', 'plan-delete')
    execution.update(state='completed', stages=[{'id': 'eval', 'state': 'completed'}])
    with store.transaction('native') as db:
        store.put(db, 'execution', execution)
    status, answer = _call('DELETE', '/api/v1/projects/native/genai/evaluations', {'execution_ids': ['plan-delete']})
    assert status == 200 and answer['deleted_executions'] == 1, answer
    assert folder.exists()
    for kind in ('execution', 'plan', 'artifact', 'experiment', 'revision'):
        assert store.listing('native', kind)
    assert _call('GET', '/api/v1/projects/native/genai/evaluations')[1]['executions'] == []
    assert (native_project / 'dataset/example/records.jsonl').exists()


def test_real_http_delete_reads_json_selection_body(mapped_project):
    from http.server import ThreadingHTTPServer
    import threading
    from urllib.request import Request as URLRequest, urlopen
    from controller.serve import Handler
    selected = genai.evaluations('mapped')['evaluations'][0]
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        request = URLRequest(f'http://127.0.0.1:{server.server_port}/api/v1/projects/mapped/genai/evaluations',
                             data=json.dumps({'ids': [selected['id']]}).encode(),
                             headers={'Content-Type': 'application/json'}, method='DELETE')
        with urlopen(request, timeout=5) as response:
            answer = json.load(response)
            assert response.status == 200 and answer['deleted'] == 1, answer
        assert (mapped_project / selected['path']).exists()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_matrix_sample_limit_reflects_actual_partition_size(native_project):
    from controller import workspace_store as store
    status, answer = _call('POST', '/api/v1/projects/native/genai/evaluations/prepare-matrix', {'models': ['m'], 'datasets': [{'dataset': 'example', 'workflow': 'evaluate-smoke', 'subset': 'default', 'split': 'local', 'parameters': {'n_items': 100}}]})
    assert status == 200 and answer['ok'], answer
    plan = store.read('native', 'plan', answer['prepared'][0]['plan_id'])
    assert answer['prepared'][0]['parameters']['n_items'] == 3
    assert all(variant['parameters']['n_items'] == 3 for variant in plan['variants'])


@pytest.fixture
def partitioned_launch_project(native_project):
    """A ten-row sample must span a corpus with small named partitions."""
    declaration = native_project / 'unityHPC/project.json'
    connection = json.loads(declaration.read_text())
    extra = {
        'dataset_subset': {'type': 'string', 'default': ''},
        'dataset_split': {'type': 'string', 'default': ''},
        'dataset_sampling': {'type': 'string', 'default': 'first', 'choices': ['first', 'random']},
        'dataset_offset': {'type': 'integer', 'default': 0, 'min': 0},
    }
    connection['parameters'].update(extra)
    connection['workflows']['evaluate-smoke']['parameters'].extend([*extra, 'seed'])
    declaration.write_text(json.dumps(connection))
    records = [{'record_id': f'row-{index}', 'inputs': {'question': f'Question {index}'},
                'expectations': {}, 'source': {'type': 'DOCUMENT'},
                'tags': {'subset': 'small' if index < 3 else 'other', 'split': 'test'}}
               for index in range(20)]
    (native_project / 'dataset/example/records.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in records))
    return native_project


@pytest.mark.parametrize('subset,expected_rows,expected_items', [('', 20, 10), ('small', 3, 3)])
def test_matrix_preserves_aggregate_or_named_subset_in_frozen_variants(partitioned_launch_project, subset, expected_rows, expected_items):
    from controller import workspace_store as store
    status, answer = _call('POST', '/api/v1/projects/native/genai/evaluations/prepare-matrix', {
        'models': ['model-a', 'model-b'],
        'datasets': [{'dataset': 'example', 'workflow': 'evaluate-smoke', 'subset': subset, 'split': 'test',
                      'parameters': {'n_items': 10, 'dataset_sampling': 'random', 'dataset_offset': 0}}],
        'parameters': {'seed': 42},
    })
    assert status == 200 and answer['ok'], answer
    summary = answer['prepared'][0]
    assert summary['subset'] == subset and summary['split'] == 'test'
    assert summary['rows'] == expected_rows
    plan = store.read('native', 'plan', summary['plan_id'])
    assert len(plan['variants']) == 2
    for variant in plan['variants']:
        parameters = variant['parameters']
        assert parameters['dataset_subset'] == subset
        assert parameters['dataset_split'] == 'test'
        assert parameters['n_items'] == expected_items
        assert parameters['dataset_sampling'] == 'random' and parameters['seed'] == 42
    assert store.listing('native', 'execution') == []


def test_matrix_aggregate_subset_still_rejects_invented_split(partitioned_launch_project):
    from controller import workspace_store as store
    status, answer = _call('POST', '/api/v1/projects/native/genai/evaluations/prepare-matrix', {
        'models': ['model-a'],
        'datasets': [{'dataset': 'example', 'workflow': 'evaluate-smoke', 'subset': '', 'split': 'invented'}],
    })
    assert status == 400 and 'Unknown subset or split' in answer['error']
    assert store.listing('native', 'plan') == []
    assert store.listing('native', 'execution') == []


def test_execution_listing_exposes_saved_scheduler_observations_without_refresh(native_project, monkeypatch):
    from controller import workspace_store as store
    from lib import campaign
    observation = {'checked_at': '2026-10-05T21:15:00Z', 'error': None}
    execution = {'id': 'plan-queued', 'plan_id': 'plan-queued', 'state': 'active',
                 'scheduler_observation': observation,
                 'stages': [{'id': 'evaluate', 'state': 'accepted', 'location': 'cluster',
                             'job_ids': ['123'], 'jobs': [{'job_id': '123', 'status': 'PENDING'},
                                                        {'job_id': '999', 'status': 'RUNNING'}]}]}
    with store.transaction('native') as db:
        store.put(db, 'execution', execution)
    def forbidden(*args, **kwargs):
        raise AssertionError('Listing must use saved observations without a scheduler refresh')
    monkeypatch.setattr(campaign, 'jobs', forbidden)
    status, answer = _call('GET', '/api/v1/projects/native/genai/evaluations')
    assert status == 200, answer
    row = answer['executions'][0]
    assert row['scheduler_observation'] == observation
    assert row['stages'][0]['state'] == 'accepted'
    assert row['stages'][0]['jobs'] == [{'job_id': '123', 'status': 'PENDING'}]
    assert store.read('native', 'execution', execution['id']) == execution


@pytest.fixture
def canonical_dataset_result(native_project):
    """Reuse the isolated native run as a workspace result with source-path metadata."""
    import shutil
    root = native_project
    dataset_manifest = root / 'dataset/example/dataset.json'
    meta = json.loads(dataset_manifest.read_text())
    meta['name'] = 'Example display name'
    dataset_manifest.write_text(json.dumps(meta))
    legacy = root / 'evaluations/smoke-1/manifest.json'
    original = json.loads(legacy.read_text())
    original['dataset'] = meta['name']
    legacy.write_text(json.dumps(original))
    folder = root / '.unity-workspace/outputs/plan-canonical/model/evaluate'
    folder.mkdir(parents=True)
    shutil.copy(root / 'evaluations/smoke-1/traces.jsonl', folder / 'traces.jsonl')
    manifest = {**original, 'dataset': '/remote/dataset/example/meta-test.jsonl',
                'execution_id': 'plan-canonical', 'purpose': 'experiment',
                'dataset_selection': {'dataset': 'example', 'split': 'meta-test',
                                      'source_files': {'dataset/example/meta-test.jsonl': 'source-digest'}}}
    (folder / 'manifest.json').write_text(json.dumps(manifest))
    return root, folder, manifest


def test_saved_dataset_identity_links_results_and_traces_to_viewer(canonical_dataset_result):
    root, folder, manifest = canonical_dataset_result
    before = (folder / 'manifest.json').read_bytes()
    status, listing = _call('GET', '/api/v1/projects/native/genai/evaluations?index=true')
    assert status == 200
    workspace_run = next(e for e in listing['evaluations'] if e['source'] == 'workspace')
    legacy_run = next(e for e in listing['evaluations'] if e['source'] == 'project')
    assert workspace_run['dataset'] == 'example'
    assert legacy_run['dataset'] == 'Example display name'
    status, detail = _call('GET', '/api/v1/projects/native/genai/evaluations/' + workspace_run['id'])
    assert status == 200 and detail['dataset'] == 'example'
    assert detail['manifest']['dataset'] == manifest['dataset']
    assert detail['provenance']['dataset_selection'] == manifest['dataset_selection']
    status, datasets = _call('GET', '/api/v1/projects/native/genai/datasets')
    assert status == 200 and datasets['datasets'][0]['id'] == 'example'
    assert datasets['datasets'][0]['evaluations'] == 2
    status, viewer = _call('GET', '/api/v1/projects/native/genai/datasets/' + detail['dataset'])
    assert status == 200 and {e['id'] for e in viewer['evaluations']} == {workspace_run['id'], legacy_run['id']}
    traces = genai.traces('native', dataset_name='example')
    assert traces['total'] == 3 and all(row['dataset'] == 'example' for row in traces['traces'])
    row = traces['traces'][0]
    assert genai.trace('native', row['evaluation_id'], row['trace_id'])['dataset'] == 'example'
    assert (folder / 'manifest.json').read_bytes() == before


def test_dataset_identity_updates_with_existing_unchanged_trace_index(canonical_dataset_result, monkeypatch):
    root, folder, _ = canonical_dataset_result
    files = [folder / 'manifest.json', folder / 'traces.jsonl']
    before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in files]
    original_get = genai._get
    # Simulate the older reader while populating the real trace index.
    with monkeypatch.context() as old_reader:
        old_reader.setattr(genai, '_get', lambda value, path: None if path == 'dataset_selection.dataset' else original_get(value, path))
        indexed = genai.traces('native', dataset_name='meta-test.jsonl')
        assert indexed['total'] == 3
    def no_reindex(*args, **kwargs):
        raise AssertionError('Unchanged trace files must reuse their existing index')
    monkeypatch.setattr(genai, '_light_row', no_reindex)
    normalized = genai.traces('native', dataset_name='example')
    assert normalized['total'] == 3
    assert all(row['dataset'] == 'example' for row in normalized['traces'])
    assert genai.traces('native', dataset_name='meta-test.jsonl')['total'] == 0
    assert next(e for e in genai.evaluations('native', index=True)['evaluations'] if e['source'] == 'workspace')['dataset'] == 'example'
    assert [(path.read_bytes(), path.stat().st_mtime_ns) for path in files] == before
