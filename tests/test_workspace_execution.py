"""Durable workflow acceptance tests with a fake run.sh receipt writer only."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from controller import registry, workspace, workspace_store as store, workspace_worker as worker
from lib import campaign
from test_workspace_planner import connected, draft, write_manifest


@pytest.fixture
def harness(connected, tmp_data_dir, monkeypatch):
    root, manifest = connected
    registry.attach("study", root, "multi-gpu", remote_dir="/fake/study")
    calls = []
    behavior = {}
    monkeypatch.setattr(worker.transport, "stage_bundle", lambda *args: None)
    monkeypatch.setattr(worker, "_ledger", lambda root, plan: campaign.jobs(root, plan["id"]))

    def submit(project, plan, stage, attempt):
        calls.append((plan["id"], stage["id"]))
        action = behavior.get(stage["id"], "accept")
        if action == "reject":
            return {"ok": False, "submission_outcome": "rejected", "output": "fake scheduler rejected the request"}
        if action == "uncertain":
            return {"ok": True, "output": "fake accepted but missing receipt"}
        # The fake alone writes a ledger receipt, standing in for run.sh.
        job_id = str(1000 + len(calls))
        campaign.record(root, plan["id"], job_id, attempt["exp"], "fake")
        if action == "crash":
            raise RuntimeError("controller stopped after scheduler receipt")
        result = subprocess.run(["bash", str(root / stage["script_path"])], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return {"ok": True, "output": job_id}

    monkeypatch.setattr(worker.transport, "submit", submit)

    class Harness:
        def start(self, config=None):
            item = workspace.create("study", {"workflow": "t1", "draft": config or draft(variant_parameters={}, stages=["t1"], variant_concurrency=4)})
            plan = workspace.plan("study", item["id"])
            execution = workspace.dispatch_plan("study", plan["id"], "intent-" + plan["id"])
            return item, plan, execution

        def tick(self):
            worker.tick("study")

        def execution(self, identity):
            return store.read("study", "execution", identity)

        def finish_jobs(self, plan, states=None):
            campaign.apply_states(root, plan["id"], {row["job_id"]: {"state": (states or {}).get(row["job_id"], "COMPLETED")} for row in campaign.jobs(root, plan["id"])})

    h = Harness()
    h.root, h.manifest, h.calls, h.behavior = root, manifest, calls, behavior
    return h


def test_dispatch_double_click_and_restart_use_one_execution(harness):
    h = harness
    _, plan, execution = h.start()
    again = workspace.dispatch_plan("study", plan["id"], "different-key-same-reviewed-plan")
    assert execution["id"] == again["id"]
    assert len(store.listing("study", "execution")) == 1
    h.tick()
    h.tick()
    assert len(h.calls) == 1
    h.finish_jobs(plan)
    h.tick()
    assert h.execution(execution["id"])["state"] == "completed"
    h.tick()
    assert len(h.calls) == 1


def test_partial_submission_preserves_accepted_and_uncertain_is_not_retried(harness):
    h = harness
    _, plan, execution = h.start(draft(variant_parameters={"model": ["small", "large"]}, stages=["t1"], variant_concurrency=4))
    first, second = plan["stages"]
    h.behavior[second["id"]] = "uncertain"
    h.tick()
    stages = h.execution(execution["id"])["stages"]
    assert [s["state"] for s in stages] == ["accepted", "uncertain"]
    assert stages[0]["job_ids"]
    h.tick()
    assert len(h.calls) == 2
    with pytest.raises(store.Conflict, match="uncertain"):
        workspace.recovery("study", execution["id"], {"stage_ids": [second["id"]]})


def test_receipt_reconciles_after_controller_crash_without_duplicate(harness):
    h = harness
    _, plan, execution = h.start()
    h.behavior[plan["stages"][0]["id"]] = "crash"
    h.tick()
    assert h.execution(execution["id"])["stages"][0]["state"] == "uncertain"
    h.tick()
    assert h.execution(execution["id"])["stages"][0]["state"] == "accepted"
    assert len(h.calls) == 1


def test_failed_smoke_pauses_own_branch_and_other_variant_continues(harness):
    h = harness
    _, plan, execution = h.start(draft(variant_parameters={"model": ["small", "large"]}, stages=["t1"], include_smoke_test=True, variant_concurrency=4))
    h.tick()
    rows = campaign.jobs(h.root, plan["id"])
    assert len(rows) == 2
    h.finish_jobs(plan, {rows[0]["job_id"]: "FAILED"})
    h.tick()
    current = h.execution(execution["id"])
    failed = next(s for s in current["stages"] if s["state"] == "failed")
    own_measurement = next(s for s in current["stages"] if s["variant_id"] == failed["variant_id"] and s["purpose"] == "experiment")
    other_measurement = next(s for s in current["stages"] if s["variant_id"] != failed["variant_id"] and s["purpose"] == "experiment")
    assert own_measurement["state"] == "waiting"
    assert other_measurement["state"] == "accepted"
    assert failed["purpose"] == "smoke-test"
    evidence = store.read("study", "artifact", failed["artifacts"][0])
    assert evidence["complete"] and evidence["purpose"] == "smoke-test"


def test_live_source_edit_after_approval_does_not_change_queued_work(harness):
    h = harness
    _, plan, execution = h.start(draft(variant_parameters={}, stages=["t1", "t2", "analyze"]))
    (h.root / "science/runner.py").write_text("raise RuntimeError('mutable source is forbidden')")
    h.tick()
    h.finish_jobs(plan)
    h.tick()
    h.finish_jobs(plan)
    h.tick()
    current = h.execution(execution["id"])
    assert current["state"] == "completed"
    assert len(h.calls) == 2
    assert next(s for s in current["stages"] if s["location"] == "controller")["job_ids"] == []
    assert len(store.listing("study", "artifact")) == 3


def test_archive_and_draft_conflict_preserve_active_execution(harness):
    h = harness
    item, plan, execution = h.start()
    h.tick()
    archived = store.experiment_action("study", item["id"], "archive")
    assert archived["archived"]
    with pytest.raises(store.Conflict):
        store.update_experiment("study", item["id"], {"expected_version": item["version"], "draft": draft()})
    with pytest.raises(store.Conflict, match="history"):
        store.experiment_action("study", item["id"], "delete")
    h.finish_jobs(plan)
    h.tick()
    assert h.execution(execution["id"])["state"] == "completed"
    assert store.experiment_action("study", item["id"], "restore")["archived"] is False


def test_retry_requires_review_and_has_new_output_identity(harness):
    h = harness
    _, plan, execution = h.start()
    h.behavior[plan["stages"][0]["id"]] = "reject"
    h.tick()
    assert h.execution(execution["id"])["stages"][0]["state"] == "rejected"
    recovery = workspace.recovery("study", execution["id"], {"stage_ids": [plan["stages"][0]["id"]], "mode": "retry"})
    assert recovery["stages"][0]["output_dir"] != plan["stages"][0]["output_dir"]
    assert len(h.calls) == 1
    h.behavior.clear()
    approved = workspace.dispatch_plan("study", recovery["id"], "approved-retry")
    h.tick()
    assert len(h.calls) == 2
    assert h.execution(approved["id"])["stages"][0]["state"] == "accepted"
    assert h.execution(execution["id"])["stages"][0]["state"] == "rejected"


def test_reanalysis_uses_saved_inputs_without_new_collection(harness):
    h = harness
    h.manifest["analysis_operations"] = ["analyze"]
    outputs = [{"id": "report", "path": "record.json", "schema": "report", "version": 1}]
    h.manifest["operations"]["analyze"]["outputs"] = outputs
    h.manifest["analyses"] = {"report": {"operation": "analyze", "input_schema": "records", "input_version": 1, "outputs": outputs}}
    write_manifest(h.root, h.manifest)
    _, plan, execution = h.start()
    h.tick()
    h.finish_jobs(plan)
    h.tick()
    artifact = store.listing("study", "artifact")[0]
    analysis = workspace.analysis("study", {"operation": "analyze", "artifact_ids": [artifact["id"]]})
    approved = workspace.dispatch_plan("study", analysis["id"], "analysis-one")
    h.tick()
    assert h.execution(approved["id"])["state"] == "completed"
    assert len(h.calls) == 1
    from controller import workspace_results
    reports = workspace_results.query("study", {"analysis": analysis["id"]})["artifacts"]
    assert reports
    assert all(report["scheduler_state"] is None for report in reports)
    assert all(report["execution_location"] == "controller" and report["operation_outcome"] == "succeeded" for report in reports)
    # Indexing a local analysis must not rewrite earlier scheduler evidence.
    assert store.read("study", "artifact", artifact["id"])["scheduler_state"] == "COMPLETED"
    repeated = workspace.analysis("study", {"operation": "analyze", "artifact_ids": [artifact["id"]]})
    assert repeated["analysis_revision"] == 2
    assert repeated["stages"][0]["output_dir"] != analysis["stages"][0]["output_dir"]
    assert (h.root / analysis["stages"][0]["outputs"][0]["path"]).exists()


def test_changed_frozen_bytes_pause_without_submission(harness):
    h = harness
    _, plan, execution = h.start()
    frozen = h.root / ".unity-workspace/plans" / plan["id"] / "source/science/runner.py"
    frozen.chmod(0o644)
    frozen.write_text("print('tampered')")
    h.tick()
    assert h.calls == []
    assert h.execution(execution["id"]).get("integrity_error")


def test_failed_fetch_is_separate_from_successful_scheduler_and_retry_fetch_scoped(harness, monkeypatch):
    h = harness
    h.manifest["operations"]["fetch"] = {"argv": ["python3", "-c", "print('fetch')"], "location": "controller"}
    h.manifest["fetch_operation"] = "fetch"
    write_manifest(h.root, h.manifest)
    _, plan, execution = h.start()
    h.tick()
    h.finish_jobs(plan)
    fetched = []

    def failed_fetch(root, reviewed, operation_id, spec):
        fetched.append(spec["output_dir"])
        return {"ok": False, "output": "fixture network unavailable"}

    monkeypatch.setattr(worker, "operation", failed_fetch)
    h.tick()
    stage = h.execution(execution["id"])["stages"][0]
    assert stage["state"] == "failed" and stage["fetch_state"] == "failed"
    assert stage["scheduler_ok"] is True
    assert fetched == [plan["stages"][0]["output_dir"]]
    monkeypatch.setattr(worker, "operation", lambda *args: {"ok": True, "output": "retrieved"})
    recovered = workspace.fetch_execution("study", execution["id"], {"stage_ids": [stage["id"]]})
    assert recovered["stages"][0]["state"] == "completed"
    assert len(h.calls) == 1


def test_input_artifact_mutation_blocks_analysis_review(harness):
    h = harness
    h.manifest["analysis_operations"] = ["analyze"]
    outputs = [{"id": "report", "path": "record.json", "schema": "report", "version": 1}]
    h.manifest["operations"]["analyze"]["outputs"] = outputs
    h.manifest["analyses"] = {"report": {"operation": "analyze", "input_schema": "records", "input_version": 1, "outputs": outputs}}
    write_manifest(h.root, h.manifest)
    _, plan, _ = h.start()
    h.tick()
    h.finish_jobs(plan)
    h.tick()
    artifact = store.listing("study", "artifact")[0]
    (h.root / artifact["files"][0].get("frozen_path", artifact["files"][0]["path"])).write_text("changed saved evidence")
    from controller.workspace_planner import PlanError
    with pytest.raises((PlanError, store.Conflict)):
        workspace.analysis("study", {"operation": "analyze", "artifact_ids": [artifact["id"]]})


def test_reviewed_failed_smoke_recovery_continues_descendants_once(harness):
    h = harness
    _, plan, execution = h.start(draft(variant_parameters={}, stages=["t1"], include_smoke_test=True))
    h.tick()
    rows = campaign.jobs(h.root, plan["id"])
    h.finish_jobs(plan, {rows[0]["job_id"]: "FAILED"})
    h.tick()
    failed = next(s for s in h.execution(execution["id"])["stages"] if s["state"] == "failed")
    recovery = workspace.recovery("study", execution["id"], {"stage_ids": [failed["id"]]})
    assert {s["stage_id"] for s in recovery["stages"]} == {"smoke", "t1"}
    assert len(recovery["recovery"]["stage_ids"]) == 2
    assert len(h.calls) == 1
    continued = workspace.dispatch_plan("study", recovery["id"], "recover-smoke")
    h.tick()
    h.finish_jobs(recovery)
    h.tick()
    h.finish_jobs(recovery)
    h.tick()
    assert h.execution(continued["id"])["state"] == "completed"
    assert len(h.calls) == 3
    old = h.execution(execution["id"])
    assert next(s for s in old["stages"] if s["purpose"] == "experiment")["state"] == "superseded"
    h.tick()
    assert len(h.calls) == 3


def test_compatible_resume_is_reviewed_keeps_checkpoint_and_continues_once(harness):
    h = harness
    h.manifest["operations"]["resume-collect"] = {**h.manifest["operations"]["collect"],
        "argv": [*h.manifest["operations"]["collect"]["argv"], "--checkpoint", {"context": "checkpoint_dir"}]}
    h.manifest["operations"]["checkpoint-check"] = {"argv": ["python3", "-c", 'print(\'{"resumable": true}\')'], "location": "controller"}
    h.manifest["resume"].update(supported=True, operations={"collect": "resume-collect"}, check_operation="checkpoint-check")
    write_manifest(h.root, h.manifest)
    _, plan, execution = h.start(draft(variant_parameters={}, stages=["t1", "t2", "analyze"]))
    h.tick()
    rows = campaign.jobs(h.root, plan["id"])
    h.finish_jobs(plan, {rows[0]["job_id"]: "FAILED"})
    h.tick()
    failed = next(s for s in h.execution(execution["id"])["stages"] if s["state"] == "failed")
    checkpoint = store.read("study", "artifact", failed["artifacts"][0])
    prior_bytes = (h.root / checkpoint["path"]).read_bytes()
    recovery = workspace.recovery("study", execution["id"], {"stage_ids": [failed["id"]], "mode": "resume"})
    duplicate = workspace.recovery("study", execution["id"], {"stage_ids": [failed["id"]], "mode": "resume"})
    resumed_stage = next(s for s in recovery["stages"] if s["stage_id"] == "t1")
    assert resumed_stage["operation"] == "resume-collect"
    assert resumed_stage["resume_from"] == checkpoint["id"]
    assert len(h.calls) == 1
    continued = workspace.dispatch_plan("study", recovery["id"], "resume-approved")
    with pytest.raises(store.Conflict):
        workspace.dispatch_plan("study", duplicate["id"], "second-resume-not-allowed")
    h.tick()
    h.finish_jobs(recovery)
    h.tick()
    h.finish_jobs(recovery)
    h.tick()
    assert h.execution(continued["id"])["state"] == "completed"
    assert len(h.calls) == 3
    assert (h.root / checkpoint["path"]).read_bytes() == prior_bytes
    assert next(s for s in continued["stages"] if s["id"] == resumed_stage["id"])["attempts"][0]["number"] == 2


def test_analysis_preserves_selected_snapshot_when_original_output_changes(harness):
    h = harness
    outputs = [{"id": "report", "path": "record.json", "schema": "report", "version": 1}]
    h.manifest["analysis_operations"] = ["analyze"]
    h.manifest["operations"]["analyze"]["outputs"] = outputs
    h.manifest["analyses"] = {"report": {"operation": "analyze", "input_schema": "records", "input_version": 1, "outputs": outputs}}
    write_manifest(h.root, h.manifest)
    _, plan, _ = h.start(); h.tick(); h.finish_jobs(plan); h.tick()
    artifact = store.listing("study", "artifact")[0]
    member = artifact["files"][0]
    before = (h.root / member["frozen_path"]).read_bytes()
    (h.root / member["path"]).write_text("later producer bytes")
    analysis = workspace.analysis("study", {"operation": "analyze", "artifact_ids": [artifact["id"]]})
    assert analysis["artifacts"][0]["id"] == artifact["id"]
    assert (h.root / member["frozen_path"]).read_bytes() == before
