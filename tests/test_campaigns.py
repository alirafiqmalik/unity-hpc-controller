"""Portable campaign seam: faults and restarts must not duplicate compute."""
import copy
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from controller import cluster_access, campaigns, campaign_lifecycle as lifecycle, campaign_store as store, events
from controller import catalog as catalog_module
from controller.campaign_contract import CampaignError, Conflict
from controller.campaign_slurm import SlurmAdapter, script
from controller.http import Request, handle


@pytest.fixture
def setup(tmp_data_dir, tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "run.py").write_text("print('scientific task')\n")
    campaigns.configure({"account": "pi_test", "remote_root": "/work/pi_test/controller", "retry_backoff_seconds": 1})
    catalog = {"observed_at": store.now(), "nodes": [{"name": "gpu013", "cpus": 112, "memory_mb": 2000000, "features": ["a100-80g", "sapphirerapids"], "partitions": ["gpu", "gpu-preempt"], "gpus": {"a100": 8}}],
               "partitions": {"gpu": {"state": "UP", "allow_accounts": ["ALL"], "max_walltime_seconds": 86400, "preempt_mode": "OFF"}, "gpu-preempt": {"state": "UP", "allow_accounts": ["ALL"], "max_walltime_seconds": 86400, "preempt_mode": "REQUEUE"}}, "account": {"qos": ["normal"]}, "qos": {"normal": {}}}
    campaigns._write_json(tmp_data_dir / "controller/backend-catalog.json", catalog)
    spec = {"schema_version": 1, "campaign_id": "study", "bundle": {"path": str(source)}, "max_concurrent": 2, "max_attempts": 2,
            "tasks": [{"task_id": "model-a", "model_class": "small-a10080-v1", "argv": ["python3", "run.py", "{output_dir}"], "env": {},
                       "resources": {"gpu_type": "a100", "gpu_count": 1, "cpus": 4, "memory_mb": 32768, "walltime_seconds": 3600, "constraint": "a100-80g&sapphirerapids", "expected_gpu_name": "NVIDIA A100-SXM4-80GB", "expected_gpu_memory_mb": 81151}, "outputs": ["results.jsonl", "summary.json"]}]}
    return spec, catalog


class FakeSlurm:
    def __init__(self):
        self.submissions, self.observations, self.staged = [], {}, 0
        self.receipt = {"outcome": "accepted", "job_id": "123"}
        self.missing, self.fetch_failure, self.gpu_name = False, False, "NVIDIA A100-SXM4-80GB"
        self.cancelled = []

    def stage(self, campaign):
        self.staged += 1
        return {}

    def submit(self, campaign, task, placement):
        self.submissions.append((task["job_name"], placement))
        return self.receipt

    def observe(self, campaign, tasks):
        return self.observations

    def cancel(self, job_ids):
        self.cancelled.append(list(job_ids))

    def collect(self, campaign, task):
        if self.fetch_failure:
            raise RuntimeError("network interrupted during fetch")
        local = store.root(campaign["id"]) / "results" / task["task_id"]
        (local / ".controller").mkdir(parents=True, exist_ok=True)
        (local / ".controller" / f"hardware-{task['attempt']}.json").write_text(json.dumps({"verified": True, "task_id": task["task_id"], "attempt": task["attempt"], "gpus": [{"name": self.gpu_name, "memory_mb": 81151}]}))
        (local / "results.jsonl").write_text('{"result":"ok"}\n')
        if not self.missing:
            (local / "summary.json").write_text('{"count":1}\n')
        return local

    def terminal(self, state="COMPLETED", job_id="123"):
        name = self.submissions[-1][0]
        self.observations[name] = {"job_id": job_id, "state": state, "exit_code": "0:0"}


class Canned:
    def __init__(self, stdout):
        self.stdout, self.commands = stdout, []

    def run(self, command, *, timeout, input=None):
        self.commands.append(command)
        return subprocess.CompletedProcess([], 0, self.stdout, "")

    def run_script(self, *args, **kwargs):
        raise AssertionError("unexpected script")

    def transfer(self, *args, **kwargs):
        raise AssertionError("unexpected transfer")


class FakeClock:
    """The Worker's clock in tests: time stays where the test sets it."""
    def __init__(self, wall=0.0, monotonic=0.0):
        self.now, self.elapsed = wall, monotonic
    def wall(self):
        return self.now
    def monotonic(self):
        return self.elapsed


def test_cancel_fences_waiting_tasks_and_ends_live_jobs(setup, monkeypatch):
    spec, _ = setup
    dependent = copy.deepcopy(spec["tasks"][0])
    dependent.update(task_id="model-b", depends_on=["model-a"])
    spec["tasks"].append(dependent)
    campaigns.create(spec)
    fake = FakeSlurm()
    campaigns.tick("study", fake)
    value = campaigns.cancel("study", adapter=fake)
    assert value["state"] == "cancelling"
    assert [task["state"] for task in value["tasks"]] == ["accepted", "cancelled"]
    assert fake.cancelled == [["123"]]
    fake.observations[fake.submissions[0][0]] = {"job_id": "123", "state": "RUNNING"}
    campaigns.tick("study", fake)
    assert store.read("study")["tasks"][0]["state"] == "cancelling"
    assert fake.cancelled == [["123"], ["123"]]
    fake.terminal("CANCELLED")
    campaigns.tick("study", fake)
    value = store.read("study")
    assert value["state"] == "cancelled"
    assert value["tasks"][0]["state"] == "cancelled"
    assert value["attempts"][0]["state"] == "cancelled"
    assert campaigns.cancel("study")["state"] == "cancelled"
    pairs = {(event["task_id"], event["kind"]) for event in store.results("study")["events"]}
    assert {(None, "cancelling"), (None, "cancelled"), ("model-b", "cancelled")} <= pairs


def test_failed_dependency_blocks_dependent_task(setup):
    spec, _ = setup
    dependent = copy.deepcopy(spec["tasks"][0])
    dependent.update(task_id="model-b", depends_on=["model-a"])
    spec["tasks"].append(dependent)
    campaigns.create(spec)
    fake = FakeSlurm()
    campaigns.tick("study", fake)
    fake.terminal("FAILED")
    campaigns.tick("study", fake)
    value = store.read("study")
    assert [task["state"] for task in value["tasks"]] == ["failed", "blocked"]
    assert value["tasks"][1]["error"] == "a required task did not complete"
    assert value["state"] == "failed"
    assert len(fake.submissions) == 1


def test_record_transition_rejects_unknown_task_state(setup):
    spec, _ = setup
    value = campaigns.create(spec)
    cursor = value["result_cursor"]
    with pytest.raises(ValueError, match="unknown task state"):
        store.record_transition("study", "model-a", "done")
    assert store.read("study")["tasks"][0]["state"] == "waiting"
    assert store.results("study", after=cursor)["events"] == []


def test_source_freeze_idempotency_and_persistent_hardware_lock(setup):
    spec, _ = setup
    first = campaigns.create(spec)
    assert first["state"] == "accepted" and not first["idempotent"]
    assert campaigns.create(spec)["idempotent"]
    changed = copy.deepcopy(spec)
    changed["campaign_id"] = "new-study"
    changed["tasks"][0]["resources"]["expected_gpu_memory_mb"] = 40960
    with pytest.raises(Conflict, match="locked"):
        campaigns.create(changed)
    (Path(spec["bundle"]["path"]) / "run.py").write_text("changed source")
    with pytest.raises(Conflict, match="different declaration or source"):
        campaigns.create(spec)


def test_evidence_from_a_job_submitted_before_the_change_completes_the_task(setup, tmp_data_dir):
    import sqlite3

    spec, _ = setup
    spec["tasks"][0]["resources"]["expected_gpu_uuid"] = "GPU-5f0c3a52-8d1e-4b7a-9c2f-000000000001"
    campaigns.create(spec)

    class OldJobSlurm(FakeSlurm):
        def collect(self, campaign, task):
            local = super().collect(campaign, task)
            fixture = Path(__file__).parent / "fixtures/hardware-evidence-plain.json"
            (local / ".controller/hardware-1.json").write_text(fixture.read_text())
            return local

    fake = OldJobSlurm()
    campaigns.tick("study", fake)
    fake.terminal()
    campaigns.tick("study", fake)
    assert store.read("study")["tasks"][0]["state"] == "completed"
    with sqlite3.connect(tmp_data_dir / "controller/campaigns.db") as con:
        assert con.execute("SELECT observed FROM hardware_locks").fetchone()[0] == (
            '[{"memory_mb": 81151, "name": "NVIDIA A100-SXM4-80GB"}]')


def test_uncertain_submit_and_restart_never_submit_twice(setup):
    spec, _ = setup
    campaigns.create(spec)
    slurm = FakeSlurm()
    slurm.receipt = {"outcome": "uncertain", "error": "ssh disconnected after acceptance"}
    campaigns.tick("study", slurm)
    assert store.read("study")["tasks"][0]["state"] == "uncertain"
    campaigns.tick("study", slurm)
    assert len(slurm.submissions) == 1
    slurm.terminal()
    campaigns.tick("study", slurm)
    assert store.read("study")["state"] == "completed"
    assert len(slurm.submissions) == 1
    assert store.results("study")["events"][-1]["kind"] == "completed"


def test_interrupted_persisted_intent_reconciles_without_resubmit(setup):
    spec, _ = setup
    campaign = campaigns.create(spec)
    task = campaigns._intent(campaign, campaign["tasks"][0])
    slurm = FakeSlurm()
    campaigns.tick("study", slurm)
    assert store.read("study")["tasks"][0]["state"] == "uncertain"
    assert not slurm.submissions
    slurm.observations[task["job_name"]] = {"job_id": "123", "state": "RUNNING"}
    campaigns.tick("study", slurm)
    assert store.read("study")["tasks"][0]["job_id"] == "123"
    assert not slurm.submissions


def test_fetch_failure_retries_fetch_without_compute_and_missing_output_fails(setup):
    spec, _ = setup
    campaigns.create(spec)
    slurm = FakeSlurm()
    campaigns.tick("study", slurm, clock=FakeClock(0))
    slurm.terminal()
    slurm.fetch_failure = True
    campaigns.tick("study", slurm, clock=FakeClock(0))
    assert store.read("study")["tasks"][0]["state"] == "fetching"
    slurm.fetch_failure, slurm.missing = False, True
    campaigns.tick("study", slurm, clock=FakeClock(2))
    assert store.read("study")["state"] == "failed"
    assert store.read("study")["tasks"][0]["artifacts"]["missing"] == ["summary.json"]
    assert len(slurm.submissions) == 1


@pytest.mark.parametrize("scheduler_state,missing,expected", [
    ("COMPLETED", False, "completed"), ("COMPLETED", True, "failed"), ("CANCELLED", False, "cancelled"),
])
def test_terminal_delivery_updates_attempt_without_repeating_job_id(setup, scheduler_state, missing, expected):
    spec, _ = setup
    campaigns.create(spec)
    slurm = FakeSlurm()
    campaigns.tick("study", slurm)
    slurm.missing = missing
    slurm.terminal(scheduler_state)
    campaigns.tick("study", slurm)
    campaign = store.read("study")
    assert campaign["tasks"][0]["state"] == expected
    attempt = campaign["attempts"][0]
    assert attempt["state"] == expected
    assert attempt["job_id"] == "123"
    assert attempt["observation"]["state"] == scheduler_state
    assert attempt["receipt"] == {"outcome": "accepted", "job_id": "123"}


@pytest.mark.parametrize("failure", ["PREEMPTED", "NODE_FAIL", "BOOT_FAIL"])
def test_retry_retains_previous_attempt_scheduler_outcome_and_observation(setup, failure):
    spec, _ = setup
    campaigns.create(spec)
    slurm = FakeSlurm()
    campaigns.tick("study", slurm, clock=FakeClock(0))
    slurm.terminal(failure)
    first_name = slurm.submissions[0][0]
    slurm.observations[first_name]["node_list"] = "gpu013"
    campaigns.tick("study", slurm, clock=FakeClock(0))
    campaign = store.read("study")
    assert campaign["tasks"][0]["state"] == "waiting"
    first = campaign["attempts"][0]
    assert first["state"] == failure
    assert first["observation"]["node_list"] == "gpu013"
    slurm.receipt = {"outcome": "accepted", "job_id": "124"}
    campaigns.tick("study", slurm, clock=FakeClock(2))
    assert store.read("study")["attempts"][1]["observation"] is None
    slurm.terminal("COMPLETED", job_id="124")
    campaigns.tick("study", slurm, clock=FakeClock(4))
    attempts = store.read("study")["attempts"]
    assert attempts[0] == first
    assert attempts[1]["state"] == "completed"
    assert attempts[1]["observation"]["state"] == "COMPLETED"
    assert attempts[1]["job_id"] == "124"


def test_only_bounded_infrastructure_retry_with_same_hardware(setup):
    spec, _ = setup
    campaigns.create(spec)
    slurm = FakeSlurm()
    campaigns.tick("study", slurm, clock=FakeClock(0))
    slurm.terminal("NODE_FAIL")
    campaigns.tick("study", slurm, clock=FakeClock(0))
    assert len(slurm.submissions) == 1
    campaigns.tick("study", slurm, clock=FakeClock(2))
    assert len(slurm.submissions) == 2
    assert slurm.submissions[0][0] != slurm.submissions[1][0]
    slurm.terminal("NODE_FAIL")
    campaigns.tick("study", slurm, clock=FakeClock(4))
    assert store.read("study")["state"] == "failed"
    assert store.read("study")["tasks"][0]["attempt"] == 2


def test_wrong_gpu_rejects_scientific_outputs(setup):
    spec, _ = setup
    campaigns.create(spec)
    slurm = FakeSlurm()
    campaigns.tick("study", slurm)
    slurm.terminal()
    slurm.gpu_name = "NVIDIA A100-PCIE-40GB"
    campaigns.tick("study", slurm)
    assert store.read("study")["state"] == "failed"
    assert "hardware lock" in store.read("study")["tasks"][0]["error"]


def test_placement_enforces_access_walltime_constraint_nodelist_and_staleness(setup, tmp_data_dir):
    spec, catalog = setup
    resources = spec["tasks"][0]["resources"]
    assert campaigns.plan(spec)["ready"]
    catalog["partitions"]["gpu"]["allow_accounts"] = ["another-pi"]
    catalog["partitions"]["gpu-preempt"]["max_walltime_seconds"] = 600
    selected = campaigns.planner.select(resources, campaigns.settings(), catalog)
    assert not selected["selected_partitions"]
    catalog["partitions"]["gpu"]["allow_accounts"] = ["ALL"]
    resources["nodelist"] = "gpu099"
    assert not campaigns.planner.select(resources, campaigns.settings(), catalog)["selected_partitions"]
    resources.pop("nodelist")
    catalog["observed_at"] = "2000-01-01T00:00:00+00:00"
    campaigns._write_json(tmp_data_dir / "controller/backend-catalog.json", catalog)
    campaigns.create(spec)
    fake = FakeSlurm()
    campaigns.tick("study", fake)
    assert not fake.submissions


@pytest.mark.parametrize("path", ["/api/v1/cluster", "/api/v1/cluster/queue", "/api/v1/cluster/usage"])
def test_retired_cluster_routes_answer_gone(path):
    response = handle(Request("GET", path, query={"hours": ["24"]}))
    assert response.status == 410
    assert "/api/v1/campaigns/plan" in json.loads(response.body)["error"]


def test_headless_api_no_registration_and_incremental_cursor(setup):
    spec, _ = setup
    response = handle(Request("POST", "/api/v1/campaigns", body=json.dumps(spec).encode()))
    assert response.status == 202
    assert handle(Request("POST", "/api/v1/projects", body=b'{}')).status == 410
    assert json.loads(handle(Request("GET", "/")).body)["mode"] == "backend"
    results = store.results("study")
    assert results["next_cursor"] > 0
    assert not store.results("study", results["next_cursor"])["events"]
    response = handle(Request("GET", "/api/v1/campaigns/study/artifacts", query={"task_id": ["model-a"], "path": ["../../escape"]}))
    assert response.status == 400


def test_script_quotes_argv_and_uses_exact_gres_with_preflight(setup, tmp_path):
    spec, _ = setup
    campaign = campaigns.create(spec)
    task = campaigns._intent(campaign, campaign["tasks"][0])
    text = script(campaign["spec"]["backend"], campaign, task, campaigns.planner.select(task["spec"]["resources"], campaigns.settings()))
    assert "#SBATCH --gres=gpu:a100:1" in text
    assert "#SBATCH --constraint=a100-80g&sapphirerapids" in text
    assert "#SBATCH --no-requeue" in text
    assert text.index("HPC_PREFLIGHT") < text.index("python3 run.py")
    path = tmp_path / "job.sh"
    path.write_text(text)
    assert subprocess.run(["bash", "-n", str(path)]).returncode == 0


def test_constraint_gpu_submission_retains_exact_hardware_attestation(setup):
    spec, _ = setup
    resources = spec["tasks"][0]["resources"]
    resources.update(gpu_request_by_constraint=True, constraint="a100&a100-80g")
    campaign = campaigns.create(spec)
    task = campaigns._intent(campaign, campaign["tasks"][0])
    text = script(campaign["spec"]["backend"], campaign, task,
                  {"selected_partitions": ["gpu"], "qos": "normal"})
    assert "#SBATCH --gres=gpu:1\n" in text
    assert "#SBATCH --constraint=a100&a100-80g\n" in text
    assert "NVIDIA A100-SXM4-80GB" in text
    assert "81151" in text
    assert "HPC_PREFLIGHT" in text


@pytest.mark.parametrize("flag,constraint,message", [
    (True, "a100-80g", "exact gpu_type feature"),
    ("true", "a100", "must be a boolean"),
])
def test_constraint_gpu_submission_rejects_ambiguous_hardware(setup, flag, constraint, message):
    spec, _ = setup
    spec["tasks"][0]["resources"].update(gpu_request_by_constraint=flag, constraint=constraint)
    with pytest.raises(CampaignError, match=message):
        campaigns.create(spec)


def test_diagnostic_downloads_are_bounded_and_do_not_become_required_outputs(setup):
    spec, _ = setup
    campaign = campaigns.create(spec)
    task = campaigns._intent(campaign, campaign["tasks"][0])
    fake = FakeSlurm()
    local = fake.collect(campaign, task)
    metrics = local / ".controller/gpu-samples-1.csv"
    metrics.write_text("timestamp,uuid,utilization\nnow,GPU-test,90\n")
    (local / (task["job_name"] + ".err")).write_text("")
    (local / ".controller/unrelated-secret.txt").write_text("not a diagnostic")
    (local / ".controller/gpu-samples-2.csv").write_text("future attempt")
    campaigns._collect(campaign, task, fake, True)
    saved = store.read("study")["tasks"][0]
    assert saved["state"] == "completed"
    assert {r["path"] for r in saved["artifacts"]["files"]} == {"results.jsonl", "summary.json"}
    diagnostics = {r["path"]: r for r in saved["artifacts"]["controller_files"]}
    assert set(diagnostics) == {".controller/hardware-1.json", ".controller/gpu-samples-1.csv", task["job_name"] + ".err"}
    assert diagnostics[task["job_name"] + ".err"]["size_bytes"] == 0
    response = handle(Request("GET", "/api/v1/campaigns/study/artifacts", query={"task_id": [task["task_id"]], "path": [".controller/gpu-samples-1.csv"]}))
    assert response.status == 200
    assert campaigns.artifact("study", task["task_id"], ".controller/gpu-samples-1.csv").read_bytes() == metrics.read_bytes()
    for forbidden in (".controller/unrelated-secret.txt", ".controller/gpu-samples-2.csv"):
        with pytest.raises(FileNotFoundError):
            campaigns.artifact("study", task["task_id"], forbidden)
    metrics.unlink()
    metrics.symlink_to(local / "results.jsonl")
    with pytest.raises(FileNotFoundError):
        campaigns.artifact("study", task["task_id"], ".controller/gpu-samples-1.csv")


def test_failed_gpu_attestation_still_delivers_diagnostics(setup):
    spec, _ = setup
    campaign = campaigns.create(spec)
    task = campaigns._intent(campaign, campaign["tasks"][0])
    fake = FakeSlurm()
    fake.gpu_name = "different GPU"
    with pytest.raises(Conflict, match="hardware lock"):
        campaigns._collect(campaign, task, fake, True)
    saved = store.read("study")["tasks"][0]
    assert saved["artifacts"]["complete"] is False
    assert saved["artifacts"]["files"] == []
    path = campaigns.artifact("study", task["task_id"], ".controller/hardware-1.json")
    assert json.loads(path.read_text())["gpus"][0]["name"] == "different GPU"


def test_bundle_rejects_symlink_and_dependency_cycle(setup):
    spec, _ = setup
    spec["tasks"][0]["depends_on"] = ["model-a"]
    with pytest.raises(CampaignError, match="cycle"):
        campaigns.create(spec)
    spec["tasks"][0]["depends_on"] = []
    source = Path(spec["bundle"]["path"])
    (source / "escape").symlink_to("/etc/passwd")
    with pytest.raises(CampaignError, match="symlink"):
        campaigns.create(spec)


def test_catalog_probe_failure_still_reconciles_tasks(setup):
    spec, _ = setup
    probes = []
    # A newly booted host can have less than 15 minutes of monotonic uptime.
    clock = FakeClock(monotonic=100.0)
    fake = FakeSlurm()

    def broken_probe():
        probes.append(True)
        raise RuntimeError("sacctmgr policy service unavailable")

    worker = campaigns.Worker(clock=clock, adapter=fake, refresh_catalog=broken_probe)
    assert worker.run_pass() is None
    assert probes == []
    campaigns.create(spec)
    report = worker.run_pass()
    assert probes == [True]
    assert report["admission_progress"] == 1
    assert len(fake.submissions) == 1
    clock.elapsed = 999.0
    worker.run_pass()
    assert probes == [True]
    clock.elapsed = 1000.0
    worker.run_pass()
    assert probes == [True, True]
    assert any(entry["kind"] == "campaign-probe-error" for entry in events.recent(50))


def test_known_qos_submit_limit_caps_admission(setup, tmp_data_dir):
    spec, catalog = setup
    second = copy.deepcopy(spec["tasks"][0])
    second["task_id"] = "model-b"
    spec["tasks"].append(second)
    catalog["qos"]["normal"]["max_submit_jobs"] = 1
    campaigns._write_json(tmp_data_dir / "controller/backend-catalog.json", catalog)
    campaigns.create(spec)
    fake = FakeSlurm()
    campaigns.tick("study", fake)
    assert len(fake.submissions) == 1
    assert [t["state"] for t in store.read("study")["tasks"]] == ["accepted", "waiting"]


def test_current_controller_capacity_releases_cpu_without_raising_gpu_cap(setup, tmp_data_dir):
    spec, catalog = setup
    second = copy.deepcopy(spec["tasks"][0])
    second["task_id"] = "model-b"
    spec["tasks"].append(second)
    campaigns.configure({"max_active_tasks": 1, "max_active_gpus": 1})
    campaigns.create(spec)
    gpu = FakeSlurm()
    campaigns.tick("study", gpu)
    assert len(gpu.submissions) == 1

    catalog["partitions"]["cpu"] = {"state": "UP", "allow_accounts": ["ALL"], "max_walltime_seconds": 86400}
    catalog["nodes"].append({"name": "cpu001", "cpus": 32, "memory_mb": 131072, "partitions": ["cpu"], "features": [], "gpus": {}})
    campaigns._write_json(tmp_data_dir / "controller/backend-catalog.json", catalog)
    cpu_spec = copy.deepcopy(spec)
    cpu_spec["campaign_id"] = "grade"
    cpu_spec["tasks"] = [{"task_id": "checker", "argv": ["python3", "run.py"], "env": {},
                          "resources": {"gpu_count": 0, "cpus": 4, "memory_mb": 32768, "walltime_seconds": 3600, "partitions": ["cpu"]},
                          "outputs": ["summary.json"]}]
    campaigns.create(cpu_spec)
    cpu = FakeSlurm()
    cpu.receipt = {"outcome": "accepted", "job_id": "124"}
    campaigns.tick("grade", cpu)
    assert not cpu.submissions

    campaigns.configure({"max_active_tasks": 2, "max_active_gpus": 1})
    campaigns.tick("grade", cpu)
    assert len(cpu.submissions) == 1
    assert store.read("grade")["spec"]["backend"]["max_active_tasks"] == 1
    campaigns.tick("study", gpu)
    assert len(gpu.submissions) == 1  # The GPU ceiling still applies.
    assert store.read("study")["tasks"][1]["state"] == "waiting"


@pytest.mark.parametrize("ceiling", ["max_active_tasks", "max_active_gpus"])
def test_reduced_current_ceiling_applies_to_already_accepted_campaign(setup, ceiling):
    spec, _ = setup
    second = copy.deepcopy(spec["tasks"][0])
    second["task_id"] = "model-b"
    spec["tasks"].append(second)
    campaigns.configure({"max_active_tasks": 2, "max_active_gpus": 2})
    campaigns.create(spec)
    store.record_transition("study", "model-b", "waiting", eligible_at=100)
    fake = FakeSlurm()
    campaigns.tick("study", fake, clock=FakeClock(0))
    campaigns.configure({ceiling: 1, "remote_root": "/work/pi_test/new-location"})
    campaigns.tick("study", fake, clock=FakeClock(200))
    assert len(fake.submissions) == 1
    assert store.read("study")["spec"]["backend"]["remote_root"] == "/work/pi_test/controller"


def test_blank_user_limits_preserve_known_account_ceiling(setup):
    spec, catalog = setup
    catalog["account"].update(name="pi_test", grp_tres="cpu=2,gres/gpu=1")
    catalog["associations"] = {"pi_test": {"qos": ["normal"], "grp_tres": None, "max_jobs": None}}
    result = campaigns.planner.select(spec["tasks"][0]["resources"], campaigns.settings(), catalog)
    assert not result["selected_partitions"]
    assert result["account_limits"]["grp_tres"] == "cpu=2,gres/gpu=1"


def test_accounting_reconciliation_crosses_midnight_utc_safely(setup):
    from controller.campaign_slurm import SlurmAdapter
    spec, _ = setup
    campaign = campaigns.create(spec)
    campaign["created_at"] = "2026-10-06T00:05:00+00:00"
    task = campaigns._intent(campaign, campaign["tasks"][0])
    output = f"QUEUE\nACCOUNTING\n123|{task['job_name']}|COMPLETED|0:0|gpu013|300|2026-10-06T00:05:01|2026-10-06T00:05:05|2026-10-06T00:10:05|gres/gpu:a100=1|||\n"
    transport = Canned(output)
    adapter = SlurmAdapter(campaign["spec"]["backend"], transport=transport)
    observed = adapter.observe(campaign, [task])
    assert observed[task["job_name"]]["state"] == "COMPLETED"
    assert "-S 2026-10-05T00:05:00 -E now" in transport.commands[0]


@pytest.mark.parametrize("live_state,accounting_state,reason,estimate", [
    ("PENDING", "PENDING", "Priority", "2026-10-06T04:30:00"),
    ("RUNNING", "PENDING", "gpu019", "N/A"),
    ("COMPLETING", "COMPLETED", "gpu019", "N/A"),
])
def test_live_queue_owns_state_and_keeps_accounting_details(setup, live_state, accounting_state, reason, estimate):
    from controller.campaign_slurm import SlurmAdapter
    spec, _ = setup
    campaign = campaigns.create(spec)
    task = campaigns._intent(campaign, campaign["tasks"][0])
    live_node = "(null)" if live_state == "PENDING" else "gpu019"
    output = f"QUEUE\n123|{task['job_name']}|{live_state}|{reason}|{live_node}|{estimate}\nACCOUNTING\n123|{task['job_name']}|{accounting_state}|0:0|None assigned|300|2026-10-06T00:05:01|Unknown|Unknown|gres/gpu:a100=1|128M|00:04:00|gres/gpuutil=42\n"
    transport = Canned(output)
    record = SlurmAdapter(campaign["spec"]["backend"], transport=transport).observe(campaign, [task])[task["job_name"]]
    assert record["state"] == live_state
    assert record["node_list"] == live_node
    assert record["accounting_state"] == accounting_state
    assert record["alloc_tres"] == "gres/gpu:a100=1" and record["total_cpu"] == "00:04:00"
    assert record["pending_reason"] == (reason if live_state == "PENDING" else None)
    assert record["estimated_start"] == (estimate if live_state == "PENDING" else None)
    assert record["sources"] == ["QUEUE", "ACCOUNTING"]


def test_accounting_terminal_state_releases_only_after_queue_disappears(setup):
    from controller.campaign_slurm import SlurmAdapter
    spec, _ = setup
    campaign = campaigns.create(spec)
    task = campaigns._intent(campaign, campaign["tasks"][0])
    output = f"QUEUE\nACCOUNTING\n123|{task['job_name']}|COMPLETED|0:0|gpu019|300|2026-10-06T00:05:01|2026-10-06T00:05:05|2026-10-06T00:10:05|gres/gpu:a100=1|||\n"
    transport = Canned(output)
    record = SlurmAdapter(campaign["spec"]["backend"], transport=transport).observe(campaign, [task])[task["job_name"]]
    assert record["state"] == "COMPLETED" and record["source"] == "ACCOUNTING"
    assert record["sources"] == ["ACCOUNTING"]


def test_compact_queue_cli_uses_controller_observation_without_ssh(setup, monkeypatch, capsys):
    from controller import campaign_cli
    spec, _ = setup
    campaign = campaigns.create(spec)
    campaign["tasks"][0].update(state="accepted", job_id="123", observation={"state": "PENDING", "pending_reason": "Priority", "estimated_start": None, "observed_at": "2026-10-06T04:00:00+00:00"})
    reads = []
    def read_controller(base, route, method="GET", payload=None):
        reads.append((route, method))
        return {"campaign": campaign}
    monkeypatch.setattr(campaign_cli, "request", read_controller)
    assert campaign_cli.main(["queue", "study"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert reads == [("/api/v1/campaigns/study", "GET")]
    assert result["jobs"][0]["pending_reason"] == "Priority"
    assert result["jobs"][0]["estimated_start"] is None
    assert result["task_counts"] == {"accepted": 1}


def test_routine_polls_refresh_measurements_without_repeated_running_events(setup):
    spec, _ = setup
    campaigns.create(spec)
    fake = FakeSlurm()
    campaigns.tick("study", fake)
    name = fake.submissions[0][0]
    fake.observations[name] = {"job_id": "123", "state": "RUNNING", "node_list": "gpu013", "observed_at": "first", "elapsed_seconds": 10, "total_cpu": "00:00:01"}
    campaigns.tick("study", fake)
    cursor = store.results("study")["next_cursor"]
    fake.observations[name].update(observed_at="second", elapsed_seconds=40, total_cpu="00:00:30")
    campaigns.tick("study", fake)
    assert not store.results("study", cursor)["events"]
    latest = store.read("study")["tasks"][0]["observation"]
    assert latest["observed_at"] == "second" and latest["elapsed_seconds"] == 40
    assert latest["total_cpu"] == "00:00:30"


def test_retrieves_older_completed_campaign_before_staging_newer_campaign(setup):
    spec, _ = setup
    calls = []
    class OrderedSlurm(FakeSlurm):
        def stage(self, campaign):
            calls.append(("stage", campaign["id"]))
            return super().stage(campaign)
        def collect(self, campaign, task):
            calls.append(("collect", campaign["id"]))
            return super().collect(campaign, task)
    fake = OrderedSlurm()
    campaigns.create(spec)
    campaigns.tick("study", fake)
    fake.terminal()
    newer = copy.deepcopy(spec)
    newer["campaign_id"] = "new-study"
    campaigns.create(newer)
    calls.clear()
    campaigns.tick(adapter=fake)
    assert calls == [("collect", "study"), ("stage", "new-study")]
    assert store.read("study")["state"] == "completed"


def test_admission_count_bound_requests_immediate_reconciliation_until_no_eligible_work(setup):
    spec, _ = setup
    spec["max_concurrent"] = 3
    for identity in ("model-b", "model-c"):
        task = copy.deepcopy(spec["tasks"][0])
        task["task_id"] = identity
        spec["tasks"].append(task)
    campaigns.configure({"max_new_tasks_per_pass": 1})
    campaigns.create(spec)
    fake = FakeSlurm()
    first = campaigns.tick("study", fake)
    assert len(fake.submissions) == 1 and first["continue_immediately"]
    second = campaigns.tick("study", fake)
    assert len(fake.submissions) == 2 and second["continue_immediately"]
    final = campaigns.tick("study", fake)
    assert len(fake.submissions) == 3 and not final["continue_immediately"]


def test_admission_time_budget_finishes_inflight_submission_then_reconciles_before_more_work(setup):
    spec, _ = setup
    campaigns.create(spec)
    another = copy.deepcopy(spec)
    another["campaign_id"] = "another-study"
    campaigns.create(another)
    clock = FakeClock()
    calls = []
    class SlowStage(FakeSlurm):
        def stage(self, campaign):
            calls.append("stage")
            clock.elapsed += 11
            return super().stage(campaign)
        def observe(self, campaign, tasks):
            calls.append("observe")
            return super().observe(campaign, tasks)
    fake = SlowStage()
    report = campaigns.tick(adapter=fake, clock=clock)
    assert len(fake.submissions) == 1 and report["continue_immediately"]
    assert report["admission_seconds"] == 11
    calls.clear()
    campaigns.tick(adapter=fake, clock=clock)
    assert calls == ["observe", "stage"] and len(fake.submissions) == 2


def test_full_capacity_and_no_progress_use_normal_polling(setup):
    spec, _ = setup
    spec["tasks"].append({**copy.deepcopy(spec["tasks"][0]), "task_id": "model-b"})
    campaigns.configure({"max_active_tasks": 1, "max_new_tasks_per_pass": 1})
    campaigns.create(spec)
    fake = FakeSlurm()
    assert not campaigns.tick("study", fake)["continue_immediately"]
    assert len(fake.submissions) == 1
    assert not campaigns.tick("study", fake)["continue_immediately"]
    assert len(fake.submissions) == 1


def test_admission_ignores_completed_bundles_and_preserves_global_capacity(setup, monkeypatch):
    spec, _ = setup
    fake = FakeSlurm()
    campaigns.create(spec)
    campaigns.tick("study", fake)
    fake.terminal()
    campaigns.tick("study", fake)
    assert store.read("study")["state"] == "completed"
    for identity in ("waiting-a", "waiting-b"):
        pending = copy.deepcopy(spec)
        pending["campaign_id"] = identity
        campaigns.create(pending)
    campaigns.configure({"max_active_gpus": 1})
    original_read = store.read

    def read_active_only(identity):
        if identity == "study":
            pytest.fail("completed bundle read during admission")
        return original_read(identity)

    def no_full_listing():
        pytest.fail("worker loaded every historical source manifest")

    monkeypatch.setattr(store, "read", read_active_only)
    monkeypatch.setattr(store, "listing", no_full_listing)
    fake.submissions.clear()
    first = campaigns.tick(adapter=fake)
    assert first["admission_progress"] == 1 and len(fake.submissions) == 1
    assert len(store.tasks_in_states(lifecycle.ACTIVE)) == 1
    assert set(store.identities_excluding(lifecycle.CAMPAIGN_TERMINAL)) == {"waiting-a", "waiting-b"}
    # An accepted task in another campaign still consumes the GPU ceiling.
    campaigns.Worker(adapter=fake, refresh_catalog=lambda: None).run_pass()
    assert len(fake.submissions) == 1
    campaigns.tick(adapter=fake)
    assert len(fake.submissions) == 1


def test_failed_staging_has_no_immediate_retry_loop(setup):
    spec, _ = setup
    campaigns.create(spec)
    class FailedStage(FakeSlurm):
        def stage(self, campaign):
            raise RuntimeError("shared storage unavailable")
    fake = FailedStage()
    report = campaigns.tick("study", fake)
    assert report["admission_progress"] == 0 and not report["continue_immediately"]
    assert not fake.submissions


def test_worker_skips_sleep_only_for_progress_with_deferred_eligible_admission(setup):
    spec, _ = setup
    spec["tasks"].append({**copy.deepcopy(spec["tasks"][0]), "task_id": "model-b"})
    campaigns.configure({"max_new_tasks_per_pass": 1})
    campaigns.create(spec)
    fake = FakeSlurm()

    class Stop:
        stopped = False
        waits = []
        def is_set(self):
            return self.stopped
        def wait(self, duration):
            self.waits.append(duration)
            self.stopped = True

    stop = Stop()
    campaigns.Worker(clock=FakeClock(), adapter=fake, refresh_catalog=lambda: None, stop=stop).run()
    assert len(fake.submissions) == 2
    assert stop.waits == [30]


@pytest.mark.parametrize("field,value", [
    ("pending_reason", "Resources"), ("estimated_start", "2026-10-06T06:00:00"),
    ("node_list", "gpu014"), ("fetch_attempts", 1),
])
def test_actionable_observation_changes_remain_in_incremental_stream(setup, field, value):
    spec, _ = setup
    campaigns.create(spec)
    observation = {"state": "PENDING", "job_id": "123", "pending_reason": "Priority", "estimated_start": None, "node_list": "", "fetch_attempts": 0}
    store.record_transition("study", "model-a", "accepted", job_id="123", observation=observation)
    cursor = store.results("study")["next_cursor"]
    observation[field] = value
    store.record_transition("study", "model-a", "accepted", observation=observation)
    assert len(store.results("study", cursor)["events"]) == 1


def test_retry_backoff_changes_remain_visible_even_with_same_waiting_state(setup):
    spec, _ = setup
    campaigns.create(spec)
    store.record_transition("study", "model-a", "waiting", eligible_at=60, error="preempted")
    cursor = store.results("study")["next_cursor"]
    store.record_transition("study", "model-a", "waiting", eligible_at=120, error="preempted")
    assert len(store.results("study", cursor)["events"]) == 1


def test_replaying_remote_submit_intent_consumes_one_sbatch(setup, tmp_path):
    from controller.campaign_slurm import SlurmAdapter
    spec, _ = setup
    campaign = campaigns.create(spec)
    task = campaigns._intent(campaign, campaign["tasks"][0])
    remote = tmp_path / "remote"
    (remote / "campaigns/study/jobs").mkdir(parents=True)
    (remote / "campaigns/study/receipts").mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    counter = tmp_path / "submissions"
    (bin_dir / "sbatch").write_text('#!/bin/sh\necho accepted >>"' + str(counter) + '"\necho 123\n')
    (bin_dir / "sbatch").chmod(0o755)
    adapter = SlurmAdapter({**campaign["spec"]["backend"], "remote_root": str(remote)}, transport=cluster_access.LocalShell(path=[bin_dir]))
    placement = campaigns.planner.select(task["spec"]["resources"], campaigns.settings())
    assert adapter.submit(campaign, task, placement) == {"outcome": "accepted", "job_id": "123"}
    assert adapter.submit(campaign, task, placement) == {"outcome": "accepted", "job_id": "123"}
    assert counter.read_text().splitlines() == ["accepted"]


def test_scheduler_name_keeps_configuration_and_unique_attempt(setup):
    spec, _ = setup
    spec['campaign_id'] = 'sg-q9-l40s-bf16-c32k-p4-1g-' + 'x' * 65
    campaign = campaigns.create(spec)
    first = campaigns._intent(campaign, campaign['tasks'][0])
    second = campaigns._intent(campaign, first)
    assert first['job_name'].startswith('sg-q9-l40s-bf16-c32k-p4-1g-')
    assert len(first['job_name']) <= 97
    assert first['job_name'] != second['job_name']


def test_identical_retry_does_not_wait_for_worker_lock(setup, monkeypatch):
    spec, _ = setup
    campaigns.create(spec)
    def locked():
        raise AssertionError('retry must not acquire worker lock')
    monkeypatch.setattr(campaigns, 'lock', locked)
    assert campaigns.create(spec)['idempotent']
    changed = copy.deepcopy(spec)
    changed['tasks'][0]['argv'] = ['python3', 'different.py']
    with pytest.raises(Conflict): campaigns.create(changed)




@pytest.mark.parametrize("nodelist", ["gpu[5-1]", "gpu[1-a]"])
def test_unexpandable_nodelist_is_rejected_before_acceptance(setup, nodelist):
    spec, _ = setup
    spec["tasks"][0]["resources"]["nodelist"] = nodelist
    for route in ("/api/v1/campaigns/plan", "/api/v1/campaigns"):
        response = handle(Request("POST", route, body=json.dumps(spec).encode()))
        assert response.status == 400
        assert "nodelist" in str(response.body)
    with pytest.raises(FileNotFoundError):
        store.read("study")
    spec["tasks"][0]["resources"]["nodelist"] = "gpu[013-013]"
    assert handle(Request("POST", "/api/v1/campaigns/plan", body=json.dumps(spec).encode())).status == 200
    assert handle(Request("POST", "/api/v1/campaigns", body=json.dumps(spec).encode())).status == 202


def test_pass_judges_catalog_age_by_its_clock(setup):
    spec, _ = setup
    campaigns.create(spec)
    fake = FakeSlurm()
    campaigns.tick("study", fake, clock=FakeClock(time.time() + 7200))
    assert fake.submissions == []
    assert "stale" in store.read("study")["tasks"][0]["error"]
    campaigns.tick("study", fake, clock=FakeClock(time.time()))
    assert len(fake.submissions) == 1


def test_planner_failure_in_one_campaign_does_not_stop_the_pass(setup, monkeypatch):
    spec, _ = setup
    campaigns.create(spec)
    pinned = copy.deepcopy(spec)
    pinned["campaign_id"] = "pinned"
    pinned["tasks"][0]["model_class"] = "pinned-a10080-v1"
    pinned["tasks"][0]["resources"]["nodelist"] = "gpu013"
    campaigns.create(pinned)
    assert store.identities_excluding(lifecycle.CAMPAIGN_TERMINAL) == ["pinned", "study"]
    fake = FakeSlurm()

    def expand_nodes(expression):
        if expression:
            raise CampaignError("nodelist cannot be expanded: " + expression)
        return set()

    with monkeypatch.context() as patch:
        patch.setattr(campaigns.planner, "expand_nodes", expand_nodes)
        campaigns.tick(adapter=fake)
        assert len(fake.submissions) == 1
        assert fake.submissions[0][0].startswith("study-")
        assert fake.staged == 1
        campaigns.tick(adapter=fake)
        error = "placement: nodelist cannot be expanded: gpu013"
        campaign = store.read("pinned")
        assert campaign["error"] == error
        assert campaign["tasks"][0]["state"] == "waiting"
        assert json.loads(handle(Request("GET", "/api/v1/campaigns/pinned")).body)["campaign"]["error"] == error
        assert store.read("study")["error"] is None
        entries = [entry for entry in events.recent(50)
                   if entry["kind"] == "campaign-error" and entry.get("campaign_id") == "pinned"]
        assert len(entries) == 1
        assert entries[0]["message"] == "pinned: placement: nodelist cannot be expanded: gpu013"
    campaigns.tick(adapter=fake)
    assert store.read("pinned")["error"] is None
    assert len(fake.submissions) == 2


def test_cancel_transport_failure_is_contained_to_its_campaign(setup, monkeypatch):
    spec, _ = setup

    class FlakyCancel(FakeSlurm):
        cancel_failure = False

        def cancel(self, job_ids):
            if self.cancel_failure:
                raise RuntimeError("scancel: Unable to contact slurm controller")
            super().cancel(job_ids)

    fake = FlakyCancel()
    campaigns.create(spec)
    campaigns.tick("study", fake)
    fake.receipt = {"outcome": "accepted", "job_id": "124"}
    newer = copy.deepcopy(spec)
    newer["campaign_id"] = "newer"
    campaigns.create(newer)
    assert store.identities_excluding(lifecycle.CAMPAIGN_TERMINAL) == ["newer", "study"]
    campaigns.tick("newer", fake)
    campaigns.cancel("newer", adapter=fake)
    fake.observations[fake.submissions[1][0]] = {"job_id": "124", "state": "RUNNING"}
    fake.observations[fake.submissions[0][0]] = {"job_id": "123", "state": "COMPLETED", "exit_code": "0:0"}
    fake.cancel_failure = True
    campaigns.tick(adapter=fake)
    assert store.read("study")["state"] == "completed"
    campaign = store.read("newer")
    assert campaign["tasks"][0]["state"] == "accepted"
    assert campaign["state"] == "cancelling"
    assert campaign["error"] == "reconcile: scancel: Unable to contact slurm controller"
    fake.cancel_failure = False
    campaigns.tick(adapter=fake)
    campaign = store.read("newer")
    assert campaign["tasks"][0]["state"] == "cancelling"
    assert campaign["error"] is None
    assert fake.cancelled == [["124"], ["124"]]


def test_failure_between_intent_and_outcome_stays_fenced_while_other_campaigns_advance(setup, monkeypatch):
    spec, _ = setup
    campaigns.create(spec)
    newer = copy.deepcopy(spec)
    newer["campaign_id"] = "newer"
    campaigns.create(newer)
    assert store.identities_excluding(lifecycle.CAMPAIGN_TERMINAL) == ["newer", "study"]
    fake = FakeSlurm()
    original = store.record_submission

    def record_submission(identity, *args):
        if identity == "newer":
            raise RuntimeError("journal unavailable")
        return original(identity, *args)

    with monkeypatch.context() as patch:
        patch.setattr(store, "record_submission", record_submission)
        campaigns.tick(adapter=fake)
    assert len(fake.submissions) == 2
    campaign = store.read("newer")
    assert campaign["tasks"][0]["state"] == "submitting"
    assert campaign["attempts"][0]["state"] == "submitting"
    assert campaign["error"] == "admission: journal unavailable"
    assert store.read("study")["tasks"][0]["state"] == "accepted"
    campaigns.tick(adapter=fake)
    campaign = store.read("newer")
    assert campaign["tasks"][0]["state"] == "uncertain"
    assert len(fake.submissions) == 2
    assert campaign["error"] is None
    fake.observations[fake.submissions[0][0]] = {"job_id": "123", "state": "RUNNING"}
    campaigns.tick(adapter=fake)
    task = store.read("newer")["tasks"][0]
    assert task["state"] == "running"
    assert task["job_id"] == "123"
    assert len(fake.submissions) == 2


def test_failed_admission_keeps_its_submitting_task_in_the_capacity_count(setup, monkeypatch):
    spec, _ = setup
    campaigns.configure({"max_active_tasks": 1})
    campaigns.create(spec)
    newer = copy.deepcopy(spec)
    newer["campaign_id"] = "newer"
    campaigns.create(newer)
    assert store.identities_excluding(lifecycle.CAMPAIGN_TERMINAL) == ["newer", "study"]
    fake = FakeSlurm()
    original = store.record_submission

    def record_submission(identity, *args):
        if identity == "newer":
            raise RuntimeError("journal unavailable")
        return original(identity, *args)

    with monkeypatch.context() as patch:
        patch.setattr(store, "record_submission", record_submission)
        campaigns.tick(adapter=fake)
    assert len(fake.submissions) == 1
    assert fake.submissions[0][0].startswith("newer-")
    assert store.read("study")["tasks"][0]["state"] == "waiting"
    assert [task["campaign_id"] for task in store.tasks_in_states(lifecycle.ACTIVE)] == ["newer"]


def test_observe_failure_is_shown_until_the_next_completed_reconcile(setup):
    spec, _ = setup

    class FlakyObserve(FakeSlurm):
        observe_failure = False

        def observe(self, campaign, tasks):
            if self.observe_failure:
                raise RuntimeError("scheduler observation failed: ssh timeout")
            return super().observe(campaign, tasks)

    campaigns.create(spec)
    fake = FlakyObserve()
    campaigns.tick("study", fake)
    fake.observe_failure = True
    campaigns.tick("study", fake)
    assert store.read("study")["error"] == "reconcile: scheduler observation failed: ssh timeout"
    fake.observe_failure = False
    campaigns.tick("study", fake)
    assert store.read("study")["error"] is None


def test_staging_error_stays_until_staging_succeeds(setup):
    spec, _ = setup

    class FlakyStage(FakeSlurm):
        stage_failure = False

        def stage(self, campaign):
            if self.stage_failure:
                raise RuntimeError("shared storage unavailable")
            return super().stage(campaign)

    other = copy.deepcopy(spec)
    other["campaign_id"] = "other"
    campaigns.create(other)
    fake = FlakyStage()
    campaigns.tick("other", fake)
    campaigns.create(spec)
    fake.stage_failure = True
    campaigns.tick("study", fake)
    assert store.read("study")["error"] == "stage: shared storage unavailable"
    campaigns.configure({"max_active_tasks": 1})
    campaigns.tick("study", fake)
    assert store.read("study")["error"] == "stage: shared storage unavailable"
    assert fake.staged == 1
    campaigns.configure({"max_active_tasks": 32})
    fake.stage_failure = False
    campaigns.tick("study", fake)
    campaign = store.read("study")
    assert campaign["error"] is None
    assert campaign["tasks"][0]["state"] == "accepted"


def test_failure_that_the_journal_cannot_record_ends_the_pass(setup, monkeypatch):
    spec, _ = setup
    campaigns.create(spec)
    newer = copy.deepcopy(spec)
    newer["campaign_id"] = "newer"
    campaigns.create(newer)
    assert store.identities_excluding(lifecycle.CAMPAIGN_TERMINAL) == ["newer", "study"]

    class FailedStage(FakeSlurm):
        def stage(self, campaign):
            if campaign["id"] == "newer":
                raise RuntimeError("shared storage unavailable")
            return super().stage(campaign)

    def record_campaign_error(*args):
        raise RuntimeError("journal is read-only")

    fake = FailedStage()
    monkeypatch.setattr(store, "record_campaign_error", record_campaign_error)
    with pytest.raises(RuntimeError, match="journal is read-only"):
        campaigns.tick(adapter=fake)
    assert fake.submissions == []
    messages = [entry["message"] for entry in events.recent(50) if entry["kind"] == "campaign-error"]
    assert "newer: stage: shared storage unavailable" in messages


def test_slurm_cancel_runs_scancel_through_the_local_shell(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "cancelled"
    scancel = bin_dir / "scancel"
    scancel.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >>"' + str(log) + '"\n')
    scancel.chmod(0o755)
    adapter = SlurmAdapter({}, transport=cluster_access.LocalShell(path=[bin_dir]))
    adapter.cancel(["123", "456"])
    adapter.cancel([])
    assert log.read_text().splitlines() == ["123 456"]
    with pytest.raises(CampaignError, match="invalid scheduler identity"):
        adapter.cancel(["12a"])
    assert log.read_text().splitlines() == ["123 456"]
    scancel.write_text('#!/bin/sh\necho "scancel: Unable to contact slurm controller" >&2\nexit 1\n')
    with pytest.raises(RuntimeError, match="scancel: Unable to contact slurm controller"):
        adapter.cancel(["123"])


@pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync is not installed")
def test_slurm_collect_retrieves_declared_outputs_and_evidence_through_the_local_shell(tmp_data_dir, tmp_path):
    remote = tmp_path / "remote"
    base = remote / "campaigns/study"
    output = base / "outputs/model-a"
    (output / "sub").mkdir(parents=True)
    (output / ".controller").mkdir()
    files = ["results.jsonl", "sub/summary.json", "a[1].txt", "a1.txt", "secret.txt", ".controller/hardware-1.json"]
    for name in files:
        (output / name).write_text(name + "\n")
    (base / "logs").mkdir()
    (base / "logs/job-a.out").write_text("job log\n")
    task = {"task_id": "model-a", "job_name": "job-a", "attempt": 1,
            "spec": {"outputs": ["results.jsonl", "sub/summary.json", "a[1].txt"]}}
    adapter = SlurmAdapter({"remote_root": str(remote)}, transport=cluster_access.LocalShell())
    local = adapter.collect({"id": "study"}, task)
    assert sorted(str(p.relative_to(local)) for p in local.rglob("*") if p.is_file()) == [
        ".controller/hardware-1.json", "a[1].txt", "job-a.out", "results.jsonl", "sub/summary.json",
    ]
    for name in ["results.jsonl", "sub/summary.json", "a[1].txt", ".controller/hardware-1.json"]:
        assert (local / name).read_bytes() == (output / name).read_bytes()
    assert (local / "job-a.out").read_text() == "job log\n"


def test_slurm_adapter_provider_freezes_backend_and_takes_current_mail(setup, ssh_tools):
    spec, _ = setup
    campaigns.create(spec)
    campaigns.configure({"mail_user": "operator@example.edu", "remote_root": "/work/elsewhere"})
    adapter = campaigns.slurm_adapter(store.read("study"))
    assert adapter.settings["remote_root"] == "/work/pi_test/controller"
    assert adapter.settings["mail_user"] == "operator@example.edu"
    assert campaigns.slurm_adapter().settings["remote_root"] == "/work/elsewhere"
    assert isinstance(adapter.transport, cluster_access.Ssh)
    assert adapter.transport.host == "unity"
    assert ssh_tools.calls() == []


def test_planner_history_reads_the_canonical_gpu_name(tmp_data_dir):
    import sqlite3
    from datetime import datetime, timezone

    from controller import campaign_planner
    from lib import paths, telemetry_archive

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    con = sqlite3.connect(paths.summaries_db())
    telemetry_archive.ensure(con)
    con.executemany(
        "INSERT INTO task_run(job_id, hardware, partition, state, wait_s, elapsed_s, max_rss_mb, day_utc) VALUES(?,?,?,?,?,?,?,?)",
        [(str(i), "rtx8000", "gpu", "COMPLETED", 10.0 * i, 100.0, 512.0, today) for i in range(1, 5)])
    con.commit()
    con.close()
    history = campaign_planner.historical_profile("gpu", "RTX_8000")
    assert history["hardware"] == "rtx8000"
    assert history["sample_count"] == 4
    assert history["wait_p50_seconds"] == 20.0
    cpu = campaign_planner.historical_profile("gpu", None)
    assert (cpu["hardware"], cpu["sample_count"]) == ("cpu", 0)


def test_pass_reads_the_catalog_once_and_keeps_it(setup, tmp_data_dir, monkeypatch):
    spec, catalog = setup
    for task_id in ("model-b", "model-c"):
        task = copy.deepcopy(spec["tasks"][0])
        task["task_id"] = task_id
        spec["tasks"].append(task)
    spec["max_concurrent"] = 3
    campaigns.configure({"max_new_tasks_per_pass": 2})
    campaigns.create(spec)
    loads = []
    original = catalog_module.load

    def counting():
        loads.append(True)
        return original()

    monkeypatch.setattr(catalog_module, "load", counting)

    class ReplacingSlurm(FakeSlurm):
        def submit(self, campaign, task, placement):
            receipt = super().submit(campaign, task, placement)
            if len(self.submissions) == 1:
                campaigns._write_json(tmp_data_dir / "controller/backend-catalog.json",
                                      {**catalog, "observed_at": "2000-01-01T00:00:00+00:00"})
            return receipt

    fake = ReplacingSlurm()
    campaigns.tick("study", fake)
    assert len(fake.submissions) == 2
    assert len(loads) == 1
    campaigns.tick("study", fake)
    assert len(fake.submissions) == 2
    task = next(task for task in store.read("study")["tasks"] if task["task_id"] == "model-c")
    assert task["state"] == "waiting"
    assert "stale" in task["error"]
    assert len(loads) == 2


def test_plan_reads_the_catalog_once(setup, monkeypatch):
    spec, _ = setup
    for task_id in ("model-b", "model-c"):
        task = copy.deepcopy(spec["tasks"][0])
        task["task_id"] = task_id
        spec["tasks"].append(task)
    loads = []
    original = catalog_module.load

    def counting():
        loads.append(True)
        return original()

    monkeypatch.setattr(catalog_module, "load", counting)
    value = campaigns.plan(spec)
    assert len(loads) == 1
    assert len(value["tasks"]) == 3
    assert len({task["placement"]["observed_at"] for task in value["tasks"]}) == 1


def test_stale_catalog_blocks_submission_not_retrieval(setup, tmp_data_dir):
    spec, catalog = setup
    task = copy.deepcopy(spec["tasks"][0])
    task["task_id"] = "model-b"
    spec["tasks"].append(task)
    spec["max_concurrent"] = 1
    campaigns.create(spec)
    fake = FakeSlurm()
    campaigns.tick("study", fake)
    assert len(fake.submissions) == 1
    catalog["observed_at"] = "2000-01-01T00:00:00+00:00"
    campaigns._write_json(tmp_data_dir / "controller/backend-catalog.json", catalog)
    fake.terminal()
    campaigns.tick("study", fake)
    tasks = store.read("study")["tasks"]
    assert tasks[0]["state"] == "completed"
    assert {row["path"] for row in tasks[0]["artifacts"]["files"]} == {"results.jsonl", "summary.json"}
    assert tasks[1]["state"] == "waiting"
    assert "stale" in tasks[1]["error"]
    assert len(fake.submissions) == 1


def test_null_catalog_document_is_read_once_and_blocks_the_pass(setup, tmp_data_dir, monkeypatch):
    spec, catalog = setup
    for task_id in ("model-b", "model-c"):
        task = copy.deepcopy(spec["tasks"][0])
        task["task_id"] = task_id
        spec["tasks"].append(task)
    spec["max_concurrent"] = 3
    campaigns.create(spec)
    stored = tmp_data_dir / "controller/backend-catalog.json"
    stored.write_text("null\n")
    loads = []
    original = catalog_module.load

    def replacing_after_the_read():
        value = original()
        loads.append(value)
        # Another writer stores a complete, fresh Catalog right after this read.
        campaigns._write_json(stored, catalog)
        return value

    monkeypatch.setattr(catalog_module, "load", replacing_after_the_read)
    fake = FakeSlurm()
    campaigns.tick("study", fake)
    assert loads == [None]
    assert fake.submissions == []
    campaign = store.read("study")
    assert [task["state"] for task in campaign["tasks"]] == ["waiting"] * 3
    assert campaign["attempts"] == []
    assert campaign["error"].startswith("placement: ")


def test_null_catalog_document_fails_a_plan_after_one_read(setup, tmp_data_dir, monkeypatch):
    spec, catalog = setup
    stored = tmp_data_dir / "controller/backend-catalog.json"
    stored.write_text("null\n")
    loads = []
    original = catalog_module.load

    def replacing_after_the_read():
        value = original()
        loads.append(value)
        campaigns._write_json(stored, catalog)
        return value

    monkeypatch.setattr(catalog_module, "load", replacing_after_the_read)
    response = handle(Request("POST", "/api/v1/campaigns/plan", body=json.dumps(spec).encode()))
    assert response.status == 500
    assert loads == [None]
