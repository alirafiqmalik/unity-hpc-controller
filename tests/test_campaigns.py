"""Portable campaign seam: faults and restarts must not duplicate compute."""
import copy
import json
import subprocess
from pathlib import Path

import pytest

from controller import campaigns, campaign_store as store
from controller.campaign_contract import CampaignError, Conflict
from controller.campaign_slurm import script, parse_probe
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

    def stage(self, campaign):
        self.staged += 1

    def submit(self, campaign, task, placement):
        self.submissions.append((task["job_name"], placement))
        return self.receipt

    def observe(self, campaign, tasks):
        return self.observations

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
    campaigns.tick("study", slurm, clock=lambda: 0)
    slurm.terminal()
    slurm.fetch_failure = True
    campaigns.tick("study", slurm, clock=lambda: 0)
    assert store.read("study")["tasks"][0]["state"] == "fetching"
    slurm.fetch_failure, slurm.missing = False, True
    campaigns.tick("study", slurm, clock=lambda: 2)
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
    campaigns.tick("study", slurm, clock=lambda: 0)
    slurm.terminal(failure)
    first_name = slurm.submissions[0][0]
    slurm.observations[first_name]["node_list"] = "gpu013"
    campaigns.tick("study", slurm, clock=lambda: 0)
    campaign = store.read("study")
    assert campaign["tasks"][0]["state"] == "waiting"
    first = campaign["attempts"][0]
    assert first["state"] == failure
    assert first["observation"]["node_list"] == "gpu013"
    slurm.receipt = {"outcome": "accepted", "job_id": "124"}
    campaigns.tick("study", slurm, clock=lambda: 2)
    assert store.read("study")["attempts"][1]["observation"] is None
    slurm.terminal("COMPLETED", job_id="124")
    campaigns.tick("study", slurm, clock=lambda: 4)
    attempts = store.read("study")["attempts"]
    assert attempts[0] == first
    assert attempts[1]["state"] == "completed"
    assert attempts[1]["observation"]["state"] == "COMPLETED"
    assert attempts[1]["job_id"] == "124"


def test_schema_one_migration_repairs_recoverable_current_attempt_only(setup):
    spec, _ = setup
    campaigns.create(spec)
    slurm = FakeSlurm()
    campaigns.tick("study", slurm)
    slurm.terminal()
    campaigns.tick("study", slurm)
    with store.database() as con:
        con.execute("UPDATE attempts SET state='fetching'")
        con.execute("ALTER TABLE attempts DROP COLUMN observation")
        con.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
    migrated = store.read("study")
    assert migrated["attempts"][0]["state"] == "completed"
    assert migrated["attempts"][0]["observation"] == migrated["tasks"][0]["observation"]
    assert migrated["attempts"][0]["receipt"] == {"outcome": "accepted", "job_id": "123"}
    assert migrated["tasks"][0]["artifacts"]["complete"]
    with store.database() as con:
        assert con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "2"


def test_only_bounded_infrastructure_retry_with_same_hardware(setup):
    spec, _ = setup
    campaigns.create(spec)
    slurm = FakeSlurm()
    campaigns.tick("study", slurm, clock=lambda: 0)
    slurm.terminal("NODE_FAIL")
    campaigns.tick("study", slurm, clock=lambda: 0)
    assert len(slurm.submissions) == 1
    campaigns.tick("study", slurm, clock=lambda: 2)
    assert len(slurm.submissions) == 2
    assert slurm.submissions[0][0] != slurm.submissions[1][0]
    slurm.terminal("NODE_FAIL")
    campaigns.tick("study", slurm, clock=lambda: 4)
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


def test_parse_probe_preserves_policy_not_fabricated_free_memory():
    result = parse_probe("NODES\nNodeName=gpu013 CPUTot=112 RealMemory=2000000 ActiveFeatures=a100-80g,sapphirerapids Partitions=gpu Gres=gpu:a100:8(S:0-1) State=MIXED FreeMem=N/A\nPARTITIONS\nPartitionName=gpu State=UP MaxTime=14-00:00:00 AllowAccounts=pi_test AllowGroups=ALL AllowQos=ALL DenyQos=short PreemptMode=OFF PriorityTier=4\nQOS\nnormal||1000|2000|\nASSOCIATIONS\npi_test|normal,long||||\nGROUPS\nusers pi_test\n", "pi_test")
    assert result["nodes"][0]["free_memory_mb"] is None
    assert result["nodes"][0]["gpus"] == {"a100": 8}
    assert result["partitions"]["gpu"]["deny_qos"] == ["short"]
    assert result["qos"]["normal"]["max_submit_jobs"] == 2000


def test_catalog_probe_failure_still_reconciles_tasks(setup, monkeypatch):
    spec, _ = setup
    campaigns.create(spec)
    reconciled, probes = [], []
    # A newly booted host can have less than 15 minutes of monotonic uptime.
    monkeypatch.setattr(campaigns.time, "monotonic", lambda: 100.0)
    def broken_probe():
        probes.append(True)
        raise RuntimeError("sacctmgr policy service unavailable")
    monkeypatch.setattr(campaigns, "probe", broken_probe)
    monkeypatch.setattr(campaigns, "tick", lambda: reconciled.append(True))
    next_probe = campaigns.worker_pass(0)
    assert reconciled == [True]
    assert next_probe == 100.0
    assert probes == [True]
    assert campaigns.worker_pass(next_probe) == next_probe
    assert reconciled == [True, True]
    assert probes == [True]


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
    store.change("study", "model-b", "waiting", eligible_at=100)
    fake = FakeSlurm()
    campaigns.tick("study", fake, clock=lambda: 0)
    campaigns.configure({ceiling: 1, "remote_root": "/work/pi_test/new-location"})
    campaigns.tick("study", fake, clock=lambda: 200)
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
    commands = []
    class MidnightAdapter(SlurmAdapter):
        def command(self, command, **kwargs):
            commands.append(command)
            output = f"QUEUE\nACCOUNTING\n123|{task['job_name']}|COMPLETED|0:0|gpu013|300|2026-10-06T00:05:01|2026-10-06T00:05:05|2026-10-06T00:10:05|gres/gpu:a100=1|||\n"
            return subprocess.CompletedProcess([], 0, output, "")
    adapter = MidnightAdapter(campaign["spec"]["backend"])
    observed = adapter.observe(campaign, [task])
    assert observed[task["job_name"]]["state"] == "COMPLETED"
    assert "-S 2026-10-05T00:05:00 -E now" in commands[0]


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
    class MixedAdapter(SlurmAdapter):
        def command(self, command, **kwargs):
            output = f"QUEUE\n123|{task['job_name']}|{live_state}|{reason}|{live_node}|{estimate}\nACCOUNTING\n123|{task['job_name']}|{accounting_state}|0:0|None assigned|300|2026-10-06T00:05:01|Unknown|Unknown|gres/gpu:a100=1|128M|00:04:00|gres/gpuutil=42\n"
            return subprocess.CompletedProcess([], 0, output, "")
    record = MixedAdapter(campaign["spec"]["backend"]).observe(campaign, [task])[task["job_name"]]
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
    class FinishedAdapter(SlurmAdapter):
        def command(self, command, **kwargs):
            output = f"QUEUE\nACCOUNTING\n123|{task['job_name']}|COMPLETED|0:0|gpu019|300|2026-10-06T00:05:01|2026-10-06T00:05:05|2026-10-06T00:10:05|gres/gpu:a100=1|||\n"
            return subprocess.CompletedProcess([], 0, output, "")
    record = FinishedAdapter(campaign["spec"]["backend"]).observe(campaign, [task])[task["job_name"]]
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
            super().stage(campaign)
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
    budget_clock = [0]
    calls = []
    class SlowStage(FakeSlurm):
        def stage(self, campaign):
            calls.append("stage")
            budget_clock[0] += 11
            super().stage(campaign)
        def observe(self, campaign, tasks):
            calls.append("observe")
            return super().observe(campaign, tasks)
    fake = SlowStage()
    report = campaigns.tick(adapter=fake, admission_clock=lambda: budget_clock[0])
    assert len(fake.submissions) == 1 and report["continue_immediately"]
    assert report["admission_seconds"] == 11
    calls.clear()
    campaigns.tick(adapter=fake, admission_clock=lambda: budget_clock[0])
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


def test_worker_skips_sleep_only_for_progress_with_deferred_eligible_admission(setup, monkeypatch):
    _, _ = setup
    class Stop:
        stopped = False
        waits = []
        def is_set(self):
            return self.stopped
        def wait(self, duration):
            self.waits.append(duration)
            self.stopped = True
    stop = Stop()
    passes = []
    def worker(last_probe, *, with_progress=False):
        assert with_progress
        passes.append(last_probe)
        return last_probe + 1, {"continue_immediately": len(passes) == 1}
    monkeypatch.setattr(campaigns, "_stop", stop)
    monkeypatch.setattr(campaigns, "worker_pass", worker)
    campaigns._loop()
    assert passes == [0, 1] and stop.waits == [30]


@pytest.mark.parametrize("field,value", [
    ("pending_reason", "Resources"), ("estimated_start", "2026-10-06T06:00:00"),
    ("node_list", "gpu014"), ("fetch_attempts", 1),
])
def test_actionable_observation_changes_remain_in_incremental_stream(setup, field, value):
    spec, _ = setup
    campaigns.create(spec)
    observation = {"state": "PENDING", "job_id": "123", "pending_reason": "Priority", "estimated_start": None, "node_list": "", "fetch_attempts": 0}
    store.change("study", "model-a", "accepted", job_id="123", observation=observation)
    cursor = store.results("study")["next_cursor"]
    observation[field] = value
    store.change("study", "model-a", "accepted", observation=observation)
    assert len(store.results("study", cursor)["events"]) == 1


def test_retry_backoff_changes_remain_visible_even_with_same_waiting_state(setup):
    spec, _ = setup
    campaigns.create(spec)
    store.change("study", "model-a", "waiting", eligible_at=60, error="preempted")
    cursor = store.results("study")["next_cursor"]
    store.change("study", "model-a", "waiting", eligible_at=120, error="preempted")
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
    class LocalAdapter(SlurmAdapter):
        def __init__(self):
            self.settings = {**campaign["spec"]["backend"], "remote_root": str(remote)}
        def command(self, command, timeout=90, input=None):
            import os
            return subprocess.run(["bash", "-c", command], input=input, capture_output=True, text=True, timeout=timeout,
                                  env={**os.environ, "PATH": str(bin_dir) + ":" + os.environ["PATH"]})
    adapter = LocalAdapter()
    placement = campaigns.planner.select(task["spec"]["resources"], campaigns.settings())
    assert adapter.submit(campaign, task, placement) == {"outcome": "accepted", "job_id": "123"}
    assert adapter.submit(campaign, task, placement) == {"outcome": "accepted", "job_id": "123"}
    assert counter.read_text().splitlines() == ["accepted"]
