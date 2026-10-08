"""Controller mail policy reaches every submission, including old campaigns."""

import copy
import json
import subprocess

import pytest

from controller import campaign_slurm, campaigns, campaign_store as store
from controller.campaign_contract import CampaignError
from controller.http import Request, handle


@pytest.fixture
def campaign(tmp_data_dir, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "run.py").write_text("print('task')\n")
    campaigns.configure({"account": "pi_test", "remote_root": "/work/pi_test/controller"})
    campaigns._write_json(tmp_data_dir / "controller/backend-catalog.json", {
        "observed_at": store.now(),
        "nodes": [{"name": "cpu001", "cpus": 8, "memory_mb": 32768,
                   "features": [], "partitions": ["cpu"], "gpus": {}}],
        "partitions": {"cpu": {"state": "UP", "allow_accounts": ["ALL"],
                                "max_walltime_seconds": 86400, "preempt_mode": "OFF"}},
        "account": {"qos": ["normal"]}, "qos": {"normal": {}},
    })
    return campaigns.create({
        "schema_version": 1, "campaign_id": "notifications",
        "bundle": {"path": str(source)}, "max_attempts": 2,
        "tasks": [{"task_id": "task", "argv": ["python3", "run.py"],
                   "resources": {"gpu_count": 0, "cpus": 1, "memory_mb": 1024,
                                 "walltime_seconds": 60, "partitions": ["cpu"]},
                   "outputs": ["result.json"]}],
    })


@pytest.mark.parametrize("gpu_count", [0, 1])
def test_scheduler_receives_mail_headers_for_cpu_and_gpu(campaign, monkeypatch, gpu_count):
    task = campaigns._intent(campaign, campaign["tasks"][0])
    task = copy.deepcopy(task)
    task["spec"]["resources"].update(gpu_count=gpu_count, gpu_type="a100")
    settings = {**campaign["spec"]["backend"], "mail_user": "operator@example.edu"}
    monkeypatch.setattr(campaign_slurm, "_agent_env", lambda host: {})
    adapter = campaign_slurm.SlurmAdapter(settings)
    calls = []

    def command(code, **kwargs):
        calls.append((code, kwargs.get("input")))
        return subprocess.CompletedProcess([], 0, stdout="123\n", stderr="")

    monkeypatch.setattr(adapter, "command", command)
    receipt = adapter.submit(campaign, task, {"selected_partitions": ["cpu"], "qos": "normal"})
    assert receipt["job_id"] == "123"
    uploaded = calls[0][1]
    assert "#SBATCH --mail-user=operator@example.edu\n" in uploaded
    assert "#SBATCH --mail-type=END,FAIL,TIME_LIMIT,REQUEUE\n" in uploaded
    assert "sbatch --parsable" in calls[1][0]


def test_mail_is_opt_in_for_other_controller_deployments(campaign):
    task = campaigns._intent(campaign, campaign["tasks"][0])
    settings = {**campaign["spec"]["backend"], "mail_user": ""}
    text = campaign_slurm.script(settings, campaign, task, {"selected_partitions": ["cpu"], "qos": "normal"})
    assert "--mail-" not in text


@pytest.mark.parametrize("next_recipient", ["updated@umass.edu", ""])
def test_existing_campaign_and_retry_use_current_mail_policy(campaign, monkeypatch, next_recipient):
    # Simulate a campaign accepted before mail settings existed.
    with store.database() as con:
        spec = copy.deepcopy(campaign["spec"])
        spec["backend"].pop("mail_user", None)
        con.execute("UPDATE campaigns SET spec=? WHERE id=?", (json.dumps(spec), campaign["id"]))
    captured = []

    class Adapter:
        def __init__(self, settings):
            self.settings = settings

        def stage(self, campaign):
            pass

        def observe(self, campaign, tasks):
            return {t["job_name"]: {"job_id": t["job_id"], "state": "PREEMPTED"} for t in tasks}

        def collect(self, campaign, task):
            raise RuntimeError("no files yet")

        def submit(self, campaign, task, placement):
            captured.append((dict(self.settings), task["attempt"]))
            return {"outcome": "accepted", "job_id": str(100 + task["attempt"])}

    monkeypatch.setattr(campaigns, "SlurmAdapter", Adapter)
    campaigns.configure({"mail_user": "operator@example.edu"})
    campaigns.tick(campaign["id"], clock=lambda: 0)
    campaigns.configure({"mail_user": next_recipient, "remote_root": "/work/elsewhere"})
    campaigns.tick(campaign["id"], clock=lambda: 0)
    campaigns.tick(campaign["id"], clock=lambda: 100)
    assert [(s["mail_user"], attempt) for s, attempt in captured] == [
        ("operator@example.edu", 1), (next_recipient, 2),
    ]
    assert all(s["remote_root"] == "/work/pi_test/controller" for s, _ in captured)
    assert "mail_user" not in store.read(campaign["id"])["spec"]["backend"]


def test_backend_api_persists_mail_policy(tmp_data_dir):
    response = handle(Request("PATCH", "/api/v1/backend", body=json.dumps({"mail_user": "operator@example.edu"}).encode()))
    assert response.status == 200
    assert campaigns.settings()["mail_user"] == "operator@example.edu"
    assert json.loads((tmp_data_dir / "controller/backend.json").read_text())["mail_user"] == "operator@example.edu"
    campaigns.configure({"mail_user": ""})
    assert campaigns.settings()["mail_user"] == ""


@pytest.mark.parametrize("recipient", [None, 42, [], "operator", " a@umass.edu", "a@umass.edu\n#SBATCH --exclusive", "a@umass.edu,b@umass.edu"])
def test_invalid_recipient_is_rejected_without_changing_settings(tmp_data_dir, recipient):
    campaigns.configure({"account": "pi_test"})
    before = (tmp_data_dir / "controller/backend.json").read_bytes()
    with pytest.raises(CampaignError, match="mail_user"):
        campaigns.configure({"mail_user": recipient})
    assert (tmp_data_dir / "controller/backend.json").read_bytes() == before
