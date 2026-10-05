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
