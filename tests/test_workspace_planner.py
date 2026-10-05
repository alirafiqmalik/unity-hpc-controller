"""Deterministic acceptance fixtures: no scheduler or real model execution."""
import copy
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from controller.workspace_connection import load_connection
from controller.workspace_planner import (PlanError, check_configuration, compile_plan,
    expand_variants, save_custom_script, verify_plan, verify_snapshot)


@pytest.fixture
def connected(tmp_path):
    root = tmp_path / "project with spaces"
    (root / "unityHPC").mkdir(parents=True)
    (root / "science").mkdir()
    (root / "science" / "runner.py").write_text('import json,sys,pathlib\np=pathlib.Path(sys.argv[1]); p.mkdir(parents=True, exist_ok=True); (p/"record.json").write_text(json.dumps(sys.argv[2:]))\n')
    (root / "unityHPC" / ".env").write_text("SECRET=do-not-copy\n")
    manifest = {
        "schema_version": 1, "application": "ml", "default_primitive": "multi-gpu", "default_mode": "independent",
        "source_paths": ["science"],
        "parameters": {"model": {"type": "string", "choices": ["small", "large"], "default": "small", "variant_eligible": True},
                       "token_cap": {"type": "integer", "default": 128, "min": 1, "variant_eligible": True},
                       "seed": {"type": "integer", "default": 0},
                       "literal": {"type": "string", "default": "literal; $(touch /bad) ' spaces"}},
        "operations": {"collect": {"argv": ["python3", "science/runner.py", {"context": "output_dir"}, {"param": "literal"}, {"param": "model"}, {"param": "token_cap"}], "cwd": ".", "location": "cluster", "version": "1"},
                       "analyze": {"argv": ["python3", "science/runner.py", {"context": "output_dir"}, {"context": "analysis_input_dirs"}], "location": "controller", "version": "1"}},
        "workflows": {"t1": {"parameters": ["model", "token_cap", "seed", "literal"], "metrics": ["score"], "stages": [
            {"id": "smoke", "operation": "collect", "purpose": "smoke-test", "optional": True, "outputs": [{"id": "corpus", "path": "record.json", "schema": "records", "version": 1}]},
            {"id": "t1", "operation": "collect", "depends_on": ["smoke"], "outputs": [{"id": "corpus", "path": "record.json", "schema": "records", "version": 1}]},
            {"id": "t2", "operation": "collect", "depends_on": ["t1"], "inputs": [{"from_stage": "t1", "output": "corpus", "schema": "records", "version": 1}], "outputs": [{"id": "corpus", "path": "record.json", "schema": "records", "version": 1}]},
            {"id": "analyze", "operation": "analyze", "depends_on": ["t2"], "inputs": [{"from_stage": "t2", "output": "corpus", "schema": "records", "version": 1}], "outputs": [{"id": "report", "path": "record.json", "schema": "report", "version": 1}]}
        ]}}, "metrics": {"score": {"source_field": "score", "unit": "ratio", "definition": "Project score"}},
        "resume": {"compatibility_parameters": ["model", "token_cap"]}}
    (root / "unityHPC" / "project.json").write_text(json.dumps(manifest))
    return root, manifest


def write_manifest(root, manifest):
    (root / "unityHPC" / "project.json").write_text(json.dumps(manifest))
    return load_connection(root)


def draft(**kwargs):
    return {"workflow": "t1", "parameters": {}, "variant_parameters": {"model": ["small", "large"], "token_cap": [128, 256]}, **kwargs}


def test_four_variants_are_distinct_from_stage_jobs_and_resources(connected):
    root, _ = connected
    plan = compile_plan(root, load_connection(root), draft(), "plan-four")
    assert len(plan["variants"]) == 4
    assert len(plan["stages"]) == 12
    assert len({s["output_dir"] for s in plan["stages"]}) == 12
    assert all(s["resources"]["gpus"] == 0 for s in plan["stages"] if s["stage_id"] == "analyze")
    assert all(len(s["depends_on"]) == (0 if s["stage_id"] == "t1" else 1) for s in plan["stages"])
    assert not (root / ".unity-workspace/plans/plan-four/source/unityHPC/.env").exists()
    assert any(f["redacted"] for f in plan["source"]["files"])
    assert verify_plan(root, plan)["valid"]


def test_invalid_variants_require_explicit_exclusion(connected):
    root, _ = connected
    config = draft(variant_parameters={"token_cap": [128, -1]})
    checked = check_configuration(root, load_connection(root), config)
    assert not checked["valid"]
    invalid_id = checked["errors"][0]["variant_id"]
    config["excluded_variants"] = [invalid_id]
    plan = compile_plan(root, load_connection(root), config, "excluded")
    assert plan["excluded_variants"] == [invalid_id]
    assert len(plan["variants"]) == 2
    assert len(plan["stages"]) == 3


def test_literal_arguments_and_frozen_dirty_source(connected):
    root, _ = connected
    config = draft(variant_parameters={})
    plan = compile_plan(root, load_connection(root), config, "literal")
    first = plan["stages"][0]
    (root / "science/runner.py").write_text("raise RuntimeError('new dirty source must not run')\n")
    assert not verify_plan(root, plan)["valid"]
    assert verify_snapshot(root, plan)["valid"]
    result = subprocess.run(["bash", str(root / first["script_path"])], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    values = json.loads((root / first["outputs"][0]["path"]).read_text())
    assert values[0] == "literal; $(touch /bad) ' spaces"


def test_smoke_gates_each_variant_but_is_not_inferred(connected):
    root, _ = connected
    plan = compile_plan(root, load_connection(root), draft(include_smoke_test=True), "smoke")
    smoke = [s for s in plan["stages"] if s["purpose"] == "smoke-test"]
    assert len(smoke) == 4
    for stage in plan["stages"]:
        if stage["stage_id"] == "t1":
            assert stage["depends_on"] == [stage["variant_id"] + "--smoke"]


def test_saved_prerequisites_require_completeness_schema_and_provenance(connected):
    root, _ = connected
    config = draft(variant_parameters={}, stages=["t2"], prerequisites="existing", existing_artifacts={"t1": "saved"})
    artifact = {"id": "saved", "complete": True, "schema": "records", "version": 1, "purpose": "experiment", "execution_id": "old", "source_digest": "sha", "parameters": {"model": "small", "token_cap": 128}}
    path = root / "saved.json"
    path.write_text("saved immutable data")
    artifact["files"] = [{"path": "saved.json", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]
    assert check_configuration(root, load_connection(root), config, [artifact])["valid"]
    for field, value in [("complete", False), ("purpose", "smoke-test"), ("version", 2), ("source_digest", None), ("parameters", {"model": "small", "token_cap": 256})]:
        invalid = {**artifact, field: value}
        assert not check_configuration(root, load_connection(root), config, [invalid])["valid"]


def test_repeat_has_new_outputs_and_custom_source_is_not_overwritten(connected):
    root, _ = connected
    one = compile_plan(root, load_connection(root), draft(), "one")
    two = compile_plan(root, load_connection(root), draft(), "two")
    assert {s["output_dir"] for s in one["stages"]}.isdisjoint(s["output_dir"] for s in two["stages"])
    custom = save_custom_script(root, one, one["stages"][0]["id"], "unityHPC/custom/mine.sh")
    (root / custom["path"]).write_text("my handwritten script")
    with pytest.raises(PlanError, match="already exists"):
        save_custom_script(root, one, one["stages"][0]["id"], custom["path"])
    assert (root / custom["path"]).read_text() == "my handwritten script"


def test_coordinated_ranks_require_declared_launcher(connected):
    root, manifest = connected
    config = draft(resources={"t1": {"mode": "coordinated", "nodes": 2, "ranks": 4}})
    assert not check_configuration(root, load_connection(root), config)["valid"]
    manifest["operations"]["collect"]["launcher"] = "srun"
    plan = compile_plan(root, write_manifest(root, manifest), config, "ranks")
    stage = next(s for s in plan["stages"] if s["stage_id"] == "t1")
    assert stage["argv"][:5] == ["srun", "--nodes", "2", "--ntasks", "4"]
    assert plan["variant_concurrency"] == 1


def test_optional_collection_is_never_implicitly_enabled(connected):
    root, manifest = connected
    manifest["metrics"]["expensive"] = {"collector": "collect", "collection_stages": ["t2"]}
    connection = write_manifest(root, manifest)
    assert not check_configuration(root, connection, draft(metrics=["expensive"]))["valid"]
    assert check_configuration(root, connection, draft(metrics=["expensive"], collection_stages=["t2"]))["valid"]


def test_connection_rejects_missing_entrypoint_escape_version_and_cycles(connected):
    root, manifest = connected
    for modify in [lambda m: m.update(schema_version=99),
                   lambda m: m.update(source_paths=["../outside"]),
                   lambda m: m["operations"]["collect"].update(argv=["python3", "missing.py"]),
                   lambda m: m["workflows"]["t1"]["stages"][0].update(depends_on=["t2"])]:
        bad = copy.deepcopy(manifest)
        modify(bad)
        assert not write_manifest(root, bad)["valid"]


def test_bounded_declared_checks_and_dynamic_choices(connected):
    root, manifest = connected
    (root / "science/choices.py").write_text('print(\'["small", "large"]\')')
    manifest["choice_readers"] = {"models": {"argv": ["python3", "science/choices.py"], "timeout_seconds": 1}}
    manifest["parameters"]["model"]["choices_reader"] = "models"
    manifest["operations"]["check"] = {"argv": ["python3", "science/choices.py"], "location": "controller"}
    manifest["checks"] = [{"id": "mock", "operation": "check", "timeout_seconds": 1}]
    connection = write_manifest(root, manifest)
    assert connection["manifest"]["parameters"]["model"]["choices"] == ["small", "large"]
    checked = check_configuration(root, connection, draft(), run_checks=True)
    assert checked["valid"] and checked["checks"][0]["passed"]
    assert checked["checks"][0]["location"] == "controller"


def test_snapshot_modification_and_secret_changes_invalidate(connected):
    root, _ = connected
    plan = compile_plan(root, load_connection(root), draft(), "immutable")
    (root / "unityHPC/.env").write_text("SECRET=updated\n")
    assert not verify_plan(root, plan)["valid"]
    assert verify_snapshot(root, plan)["valid"]
    frozen = root / ".unity-workspace/plans/immutable/source/science/runner.py"
    frozen.chmod(0o644)
    frozen.write_text("tampered")
    assert not verify_snapshot(root, plan)["valid"]


def test_parameter_bounds_and_seeds_do_not_implicitly_expand(connected):
    root, _ = connected
    checked = check_configuration(root, load_connection(root), draft(variant_parameters={"seed": [1, 2]}))
    assert not checked["valid"]
    checked = check_configuration(root, load_connection(root), draft(variant_parameters={}, parameters={"seed": 2}))
    assert checked["valid"] and len(checked["variants"]) == 1


def test_mutable_inputs_block_reproducibility(connected):
    root, manifest = connected
    (root / "dataset.txt").write_text("input")
    manifest["inputs"] = {"data": {"path": "dataset.txt"}}
    connection = write_manifest(root, manifest)
    with pytest.raises(PlanError, match="immutable"):
        compile_plan(root, connection, draft(), "mutable")
    manifest["inputs"]["data"]["immutable"] = True
    plan = compile_plan(root, write_manifest(root, manifest), draft(), "fixed")
    (root / "dataset.txt").write_text("changed")
    assert not verify_plan(root, plan)["valid"]


def test_custom_script_uses_new_execution_outputs(connected):
    root, manifest = connected
    original = compile_plan(root, load_connection(root), draft(variant_parameters={}, stages=["t1"]), "original")
    first = original["stages"][0]
    custom = save_custom_script(root, original, first["id"], "unityHPC/custom/fresh.sh")
    manifest["source_paths"].append(custom["path"])
    manifest["operations"]["custom"] = custom["operation"]
    manifest["workflows"]["custom"] = {"parameters": [], "stages": [{"id": "custom", "operation": "custom", "resources": custom["resources"], "outputs": custom["outputs"]}]}
    plan = compile_plan(root, write_manifest(root, manifest), {"workflow": "custom"}, "new-custom")
    stage = plan["stages"][0]
    result = subprocess.run(["bash", str(root / stage["script_path"])], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (root / stage["outputs"][0]["path"]).exists()
    assert not (root / first["output_dir"]).exists()


def test_metric_parameters_smoke_and_effective_location(connected):
    root, manifest = connected
    manifest["parameters"]["detail"] = {"type": "boolean", "default": False}
    manifest["workflows"]["t1"]["parameters"].append("detail")
    manifest["metrics"]["details"] = {"optional": True, "parameter": "detail", "requires_collection": True}
    manifest["workflows"]["t1"]["metrics"].append("details")
    manifest["workflows"]["t1"]["stages"][0].update(location="controller", resources={"primitive": "cpu", "mode": "single", "gpus": 0})
    plan = compile_plan(root, write_manifest(root, manifest), draft(include_smoke_test=True, metrics=["score", "details"]), "detail")
    assert all(stage["parameters"]["detail"] for stage in plan["stages"])
    assert all(stage["location"] == "controller" for stage in plan["stages"] if stage["stage_id"] == "smoke")
    for stage in plan["stages"]:
        if stage["stage_id"] == "analyze":
            assert "smoke" not in stage["argv"][-1]


def test_resource_injection_and_invalid_time_rejected(connected):
    root, _ = connected
    for resources in [{"partition": "gpu\n#SBATCH --exclusive"}, {"memory": "20G"}, {"walltime": "00:99:00"}]:
        assert not check_configuration(root, load_connection(root), draft(resources={"t1": resources}))["valid"]


def test_source_closure_captures_dirty_import_outside_declared_directory(connected):
    root, _ = connected
    (root / "project_helpers.py").write_text("VALUE = 'dirty helper'\n")
    with (root / "science/runner.py").open("a") as stream:
        stream.write("\nimport project_helpers\n")
    plan = compile_plan(root, load_connection(root), draft(), "closure")
    assert "project_helpers.py" in {item["path"] for item in plan["source"]["files"]}
    assert (root / ".unity-workspace/plans/closure/source/project_helpers.py").read_text() == "VALUE = 'dirty helper'\n"


def test_completed_smoke_evidence_can_gate_but_never_supply_measurements(connected):
    root, _ = connected
    evidence = root / "smoke-evidence.json"
    evidence.write_text("passed")
    artifact = {"id": "smoke-result", "complete": True, "purpose": "smoke-test", "schema": "records", "version": 1,
                "stage_state": "completed", "execution_id": "previous", "source_digest": "source",
                "parameters": {"model": "small", "token_cap": 128},
                "files": [{"path": "smoke-evidence.json", "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}]}
    config = draft(variant_parameters={}, stages=["t1"], prerequisites="existing", existing_artifacts={"smoke": artifact["id"]})
    assert check_configuration(root, load_connection(root), config, [artifact])["valid"]
    assert not check_configuration(root, load_connection(root), config, [{**artifact, "stage_state": "failed"}])["valid"]
    measurement = draft(variant_parameters={}, stages=["t2"], prerequisites="existing", existing_artifacts={"t1": artifact["id"]})
    assert not check_configuration(root, load_connection(root), measurement, [artifact])["valid"]


def test_explicit_resume_uses_declared_operation_and_preserves_checkpoint(connected):
    root, manifest = connected
    manifest["operations"]["resume-collect"] = {**manifest["operations"]["collect"], "argv": [*manifest["operations"]["collect"]["argv"], "--checkpoint", {"context": "checkpoint_dir"}]}
    manifest["resume"]["operations"] = {"collect": "resume-collect"}
    connection = write_manifest(root, manifest)
    config = draft(variant_parameters={}, stages=["t1"])
    variant = check_configuration(root, connection, config)["variants"][0]
    evidence = root / "checkpoint.json"
    evidence.write_text("partial")
    artifact = {"id": "checkpoint", "complete": False, "purpose": "experiment", "path": "checkpoint.json", "output_dir": ".",
                "execution_id": "prior", "source_digest": "prior-source", "parameters": variant["parameters"],
                "files": [{"path": "checkpoint.json", "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}]}
    config["resume_artifacts"] = {variant["id"] + ":t1": "checkpoint"}
    plan = compile_plan(root, connection, config, "resume", artifacts=[artifact])
    assert plan["stages"][0]["operation"] == "resume-collect"
    assert plan["stages"][0]["resume_from"] == "checkpoint"
    assert plan["stages"][0]["argv"][-2:] == ["--checkpoint", "__UNITY_PROJECT_ROOT__/."]
    assert plan["artifacts"][0]["id"] == "checkpoint"
    assert evidence.read_text() == "partial"


def test_shared_prerequisite_must_not_choose_one_variant_silently(connected):
    root, manifest = connected
    smoke = manifest["workflows"]["t1"]["stages"][0]
    smoke["scope"] = "shared"
    connection = write_manifest(root, manifest)
    assert not check_configuration(root, connection, draft(include_smoke_test=True))["valid"]
    smoke["parameters"] = {"model": "small", "token_cap": 128}
    plan = compile_plan(root, write_manifest(root, manifest), draft(include_smoke_test=True), "shared")
    assert len([stage for stage in plan["stages"] if stage["variant_id"] == "shared"]) == 1
    assert all(stage["depends_on"] == ["shared--smoke"] for stage in plan["stages"] if stage["stage_id"] == "t1")


def test_measurement_aggregation_is_declared_and_frozen(connected):
    root, manifest = connected
    manifest["metrics"]["score"]["aggregations"] = ["mean", "median"]
    connection = write_manifest(root, manifest)
    plan = compile_plan(root, connection, draft(aggregations={"score": "median"}), "measurements")
    assert plan["metrics"][0]["aggregation"] == "median"
    assert not check_configuration(root, connection, draft(aggregations={"score": "eval(arbitrary)"}))["valid"]


def test_unindexed_added_corpus_file_invalidates_immutable_artifact(connected):
    root, _ = connected
    corpus = root / 'saved-corpus'
    corpus.mkdir()
    record = corpus / 'first.jsonl'
    record.write_text('{"result": 1}\n')
    artifact = {'id': 'saved', 'path': 'saved-corpus', 'complete': True, 'schema': 'records', 'version': 1,
                'purpose': 'experiment', 'execution_id': 'old', 'source_digest': 'source',
                'parameters': {'model': 'small', 'token_cap': 128},
                'files': [{'path': 'saved-corpus/first.jsonl', 'sha256': hashlib.sha256(record.read_bytes()).hexdigest()}]}
    config = draft(variant_parameters={}, stages=['t2'], prerequisites='existing', existing_artifacts={'t1': 'saved'})
    assert check_configuration(root, load_connection(root), config, [artifact])['valid']
    (corpus / 'unreviewed.jsonl').write_text('{"result": 999}\n')
    checked = check_configuration(root, load_connection(root), config, [artifact])
    assert not checked['valid']
    assert any('file set changed' in error['message'] for error in checked['errors'])


def test_scheduler_stdout_labels_purpose_and_frozen_execution_identity(connected):
    root, _ = connected
    plan = compile_plan(root, load_connection(root), draft(variant_parameters={}, stages=['t1'], include_smoke_test=True), 'purpose-logs')
    for stage in plan['stages']:
        result = subprocess.run(['bash', str(root / stage['script_path'])], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        label = 'Smoke test' if stage['purpose'] == 'smoke-test' else 'Experiment'
        assert result.stdout.splitlines()[0] == f"Purpose: {label} | Execution: {plan['id']} | Variant: {stage['variant_id']} | Stage: {stage['stage_id']}"
