"""The round-trip check: compare accepts run-specific differences and rejects contract changes.

Each recorded round trip drives the real controller HTTP routes in this process.
A fake Slurm adapter stands in for the cluster, so the test is offline.
"""
import importlib.util
import json
import shutil
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from controller import campaigns, campaign_store as store, telemetry
from controller.serve import Handler

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("verify_campaign_round_trip", REPO / "tests" / "verify_campaign_round_trip.py")
verify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify)

ACCOUNT = "pi_example_umass_edu"


class FakeCluster:
    """One CPU job: Slurm accepts it, optionally shows it pending once, then reports it completed."""

    def __init__(self, job_id, node, pending):
        self.job_id, self.node, self.pending, self.polls = job_id, node, pending, 0

    def stage(self, campaign):
        manifest = campaign["spec"]["bundle_manifest"]["sha256"]
        cache = campaign["spec"]["backend"]["remote_root"] + "/source-cache/" + manifest
        return {"source_manifest_sha256": manifest, "cache_hit": False, "legacy_source": False,
                "cache_path": cache, "source_path": cache + "/source"}

    def submit(self, campaign, task, placement):
        return {"outcome": "accepted", "job_id": self.job_id}

    def observe(self, campaign, tasks):
        self.polls += 1
        task = tasks[0]
        base = {"job_id": self.job_id, "job_name": task["job_name"], "observed_at": store.now()}
        if self.pending and self.polls == 1:
            return {task["job_name"]: {**base, "state": "PENDING", "node_list": "", "source": "QUEUE", "pending_reason": "Priority",
                                       "estimated_start": None, "estimated_start_source": None, "accounting_state": "PENDING",
                                       "accounting_node_list": "None assigned", "sources": ["QUEUE", "ACCOUNTING"]}}
        return {task["job_name"]: {**base, "state": "COMPLETED", "node_list": self.node, "source": "ACCOUNTING", "exit_code": "0:0",
                                   "elapsed_seconds": 2 + self.polls, "submit": "2026-11-19T10:00:00", "start": "2026-11-19T10:00:05",
                                   "end": "2026-11-19T10:00:08", "alloc_tres": f"billing={self.polls},cpu=1,mem=1G,node=1",
                                   "max_rss": None, "total_cpu": "00:00.512", "tres_usage_in_max": None, "sources": ["ACCOUNTING"]}}

    def collect(self, campaign, task):
        local = store.root(campaign["id"]) / "results" / task["task_id"]
        (local / ".controller").mkdir(parents=True, exist_ok=True)
        (local / "result.json").write_text(verify.DEFAULT_RESULT)
        attestation = {"task_id": task["task_id"], "attempt": task["attempt"], "job_id": self.job_id, "node": self.node,
                       "requested": task["spec"]["resources"], "gpus": [], "verified": True}
        (local / ".controller" / f"hardware-{task['attempt']}.json").write_text(json.dumps(attestation, sort_keys=True))
        for suffix in ("out", "err"):
            (local / f"{task['job_name']}.{suffix}").write_text("")
        return local

    def cancel(self, job_ids):
        raise AssertionError("the round trip never cancels")


def _record(root, monkeypatch, name, bundle, *, job_id, node, pending):
    data = root / f"{name}-data"
    (data / "locks").mkdir(parents=True)
    monkeypatch.setenv("UNITY_HPC_DATA", str(data))
    campaigns.configure({"account": ACCOUNT, "remote_root": f"/work/{ACCOUNT}/verify/{name}", "cpu_partitions": ["cpu", "cpu-preempt"],
                         "ssh_identity": "~/.ssh/example_cluster_key", "mail_user": ""})
    catalog = {"observed_at": store.now(), "account": {"name": ACCOUNT, "qos": ["normal"]}, "qos": {"normal": {}},
               "nodes": [{"name": "cpu001", "cpus": 64, "memory_mb": 256000, "features": [], "partitions": ["cpu", "cpu-preempt"], "gpus": {}}],
               "partitions": {"cpu": {"state": "UP", "allow_accounts": ["ALL"], "max_walltime_seconds": 86400, "preempt_mode": "OFF", "priority_tier": 1},
                              "cpu-preempt": {"state": "UP", "allow_accounts": ["ALL"], "max_walltime_seconds": 86400, "preempt_mode": "REQUEUE"}}}
    campaigns._write_json(data / "controller" / "backend-catalog.json", catalog)
    declaration = root / "declarations" / f"{name}.json"
    assert verify.main(["declare", "--template", str(REPO / "examples" / "cpu-result" / "campaign.json"), "--bundle", str(bundle),
                        "--prefix", f"rt{name[0]}-", "--out", str(declaration)]) == 0
    cluster, stop, failures = FakeCluster(job_id, node, pending), threading.Event(), []

    def worker():
        while not stop.is_set():
            try:
                campaigns.tick(adapter=cluster)
            except Exception as exc:  # surfaced by the assertion below
                failures.append(exc)
            stop.wait(0.02)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threads = [threading.Thread(target=server.serve_forever, daemon=True), threading.Thread(target=worker, daemon=True)]
    for thread in threads:
        thread.start()
    out = root / name
    try:
        code = verify.main(["run", "--url", f"http://127.0.0.1:{server.server_address[1]}", "--declaration", str(declaration),
                            "--out", str(out), "--deadline-seconds", "30", "--poll-seconds", "0.05", "--revision", name])
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        for thread in threads:
            thread.join(timeout=5)
    assert not failures
    assert code == 0, json.loads((out / "summary.json").read_text())["failed"]
    return out


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    root = tmp_path_factory.mktemp("round-trip")
    bundle = root / "bundle"
    shutil.copytree(REPO / "examples" / "cpu-result", bundle)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.delenv("UNITY_ACCOUNT", raising=False)
        monkeypatch.delenv("UNITY_CONTROLLER_REMOTE_ROOT", raising=False)
        monkeypatch.setattr(telemetry, "ssh_status", lambda: {"needs_passphrase": False, "key_path": "", "command": "", "unlocked": True})
        baseline = _record(root, monkeypatch, "baseline", bundle, job_id="4101", node="cpu001", pending=True)
        head = _record(root, monkeypatch, "head", bundle, job_id="5202", node="cpu002", pending=False)
    return baseline, head


def _copy(source, destination):
    shutil.copytree(source, destination)
    return destination


def _edit_last(directory, label, change):
    path = sorted((directory / "exchanges").glob(f"*-{label}.json"))[-1]
    record = json.loads(path.read_text())
    change(record)
    path.write_text(json.dumps(record))


def test_run_records_every_exchange_and_redacts_backend_values(recorded):
    baseline, head = recorded
    summary = json.loads((baseline / "summary.json").read_text())
    assert summary["ok"] and summary["milestones"] == list(verify.MILESTONES)
    assert summary["optional_observations"] == ["accepted:PENDING"]
    assert json.loads((head / "summary.json").read_text())["optional_observations"] == []
    labels = [entry["label"] for entry in summary["exchanges"]]
    assert labels[:6] == ["backend", "health", "plan", "listing-after-plan", "submit", "resend"]
    assert labels[-4:] == ["artifact-declared", "artifact-diagnostic", "artifact-undeclared", "resend-after-completion"]
    assert len(list((baseline / "exchanges").glob("*.json"))) == len(labels)
    for path in baseline.rglob("*.json"):
        text = path.read_text()
        assert ACCOUNT not in text and "example_cluster_key" not in text, path


def test_runs_that_differ_only_in_run_specific_values_match(recorded, capsys):
    baseline, head = recorded
    assert verify.main(["compare", str(baseline), str(baseline)]) == 0
    assert verify.main(["compare", str(baseline), str(head)]) == 0
    output = capsys.readouterr().out
    assert "MATCH" in output and "baseline only: ['accepted:PENDING']" in output


def test_an_altered_artifact_digest_is_rejected_at_its_field(recorded, tmp_path, capsys):
    baseline, head = recorded
    altered = _copy(head, tmp_path / "altered")

    def change(record):
        receipt = record["response"]["campaign"]["tasks"][0]["artifacts"]["files"][0]
        receipt["sha256"] = "0" * 64

    _edit_last(altered, "status-final", change)
    report = tmp_path / "report.json"
    assert verify.main(["compare", str(baseline), str(altered), "--out", str(report)]) == 1
    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith("MISMATCH head:status-final.body.campaign.tasks[0].artifacts.files[0].sha256")
    paths = [item["path"] for item in json.loads(report.read_text())["differences"]]
    assert "status-final.body.campaign.tasks[0].artifacts.files[0].sha256" in paths


def test_an_extra_attempt_is_rejected(recorded, tmp_path, capsys):
    baseline, head = recorded
    extra = _copy(head, tmp_path / "extra")

    def change(record):
        campaign = record["response"]["campaign"]
        first = campaign["attempts"][0]
        second = {**first, "attempt": 2, "job_id": "5203",
                  "job_name": verify.job_name(campaign["id"], first["task_id"], 2), "receipt": {"outcome": "accepted", "job_id": "5203"}}
        campaign["attempts"].append(second)

    _edit_last(extra, "status-final", change)
    assert verify.main(["compare", str(baseline), str(extra)]) == 1
    assert capsys.readouterr().out.splitlines()[0].startswith("MISMATCH status-final.body.campaign.attempts[1]")


def test_a_changed_milestone_payload_is_rejected(recorded, tmp_path, capsys):
    baseline, head = recorded
    changed = _copy(head, tmp_path / "changed")
    for path in sorted((changed / "exchanges").glob("*-results.json")):
        record = json.loads(path.read_text())
        for event in record["response"]["events"]:
            if event["kind"] == "submitting":
                event["payload"]["eligible_at"] = 0
                path.write_text(json.dumps(record))
    assert verify.main(["compare", str(baseline), str(changed)]) == 1
    assert "MISMATCH events[3].payload.eligible_at" in capsys.readouterr().out


def test_request_hash_follows_the_create_formula(recorded):
    baseline, _ = recorded
    run = verify.Run(baseline)
    campaign = run.campaign("submit")
    assert verify.request_hash(campaign["spec"]) == campaign["request_hash"]
    spec = json.loads(json.dumps(campaign["spec"]))
    spec["max_attempts"] += 1
    assert verify.request_hash(spec) != campaign["request_hash"]
