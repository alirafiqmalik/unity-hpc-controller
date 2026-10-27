"""Durable portable campaigns: stage, submit, reconcile, retry, and return files.

This module is the controller's small public interface. Scientific commands
and evaluations remain opaque. Its SSH adapter can be replaced in tests.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from lib import paths
from controller import campaign_contract as contract, campaign_planner as planner, campaign_store as store
from controller.campaign_slurm import SlurmAdapter
from controller.cluster_session import clean_ssh_host, clean_ssh_identity

ACTIVE = {"submitting", "uncertain", "accepted", "running", "fetching", "cancelling"}
TERMINAL = {"completed", "failed", "rejected", "cancelled", "blocked"}
SLURM_TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL", "PREEMPTED", "BOOT_FAIL", "OUT_OF_MEMORY", "DEADLINE", "REVOKED"}
RETRYABLE = {"NODE_FAIL", "PREEMPTED", "BOOT_FAIL"}
DEFAULTS = {"ssh_host": "unity", "ssh_identity": "", "account": "", "remote_root": "", "allowed_partitions": ["gpu", "gpu-preempt"],
            "cpu_partitions": ["cpu", "cpu-preempt"], "qos": "normal", "mail_user": "", "poll_seconds": 30, "catalog_max_age_seconds": 3600,
            "max_active_tasks": 32, "max_active_gpus": 32, "max_new_tasks_per_pass": 4, "admission_budget_seconds": 10, "allow_preemptible": True, "sample_gpu_metrics": True, "retry_backoff_seconds": 60, "max_fetch_attempts": 5}
_thread = None
_stop = threading.Event()


def settings():
    out = dict(DEFAULTS)
    try:
        saved = json.loads((paths.controller_dir() / "backend.json").read_text())
        out.update({key: val for key, val in saved.items() if key in DEFAULTS})
    except (OSError, ValueError):
        pass
    # SSH configuration is controller-owned and already exists for telemetry.
    try:
        telemetry = json.loads((paths.controller_dir() / "telemetry.json").read_text())
    except (OSError, ValueError):
        telemetry = {}
    out["ssh_host"] = out["ssh_host"] or telemetry.get("ssh_host", "unity")
    out["ssh_identity"] = out["ssh_identity"] or telemetry.get("ssh_identity", "")
    out["account"] = os.environ.get("UNITY_ACCOUNT", out["account"])
    out["remote_root"] = os.environ.get("UNITY_CONTROLLER_REMOTE_ROOT", out["remote_root"])
    return out


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temp.chmod(0o600)
    os.replace(temp, path)


def configure(changes):
    if not isinstance(changes, dict) or changes.keys() - DEFAULTS.keys():
        raise contract.CampaignError("unknown backend setting")
    value = {**settings(), **changes}
    value["ssh_host"] = clean_ssh_host(value["ssh_host"])
    value["ssh_identity"] = clean_ssh_identity(value["ssh_identity"])
    recipient = value["mail_user"]
    if not isinstance(recipient, str) or (recipient and (
            len(recipient) > 254 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", recipient))):
        raise contract.CampaignError("mail_user must be one email address or an empty string to disable notifications")
    for key in ("account", "qos"):
        if value[key] and not contract.TOKEN.fullmatch(value[key]):
            raise contract.CampaignError(f"{key} must be a Slurm identifier")
    root = value["remote_root"]
    if root and (not isinstance(root, str) or not re.fullmatch(r"/[A-Za-z0-9_./-]+", root) or ".." in Path(root).parts or root == "/"):
        raise contract.CampaignError("remote_root must be an absolute directory without whitespace or parent traversal")
    for key in ("allowed_partitions", "cpu_partitions"):
        if not isinstance(value[key], list) or not value[key] or not all(isinstance(p, str) and contract.TOKEN.fullmatch(p) for p in value[key]):
            raise contract.CampaignError(f"{key} must contain partition names")
    for key, minimum, maximum in (("poll_seconds", 15, 3600), ("catalog_max_age_seconds", 60, 86400), ("max_active_tasks", 1, 128), ("max_active_gpus", 1, 128), ("max_new_tasks_per_pass", 1, 128), ("admission_budget_seconds", 1, 300), ("retry_backoff_seconds", 1, 86400), ("max_fetch_attempts", 1, 100)):
        contract._positive(value[key], key, maximum, minimum)
    for key in ("allow_preemptible", "sample_gpu_metrics"):
        if not isinstance(value[key], bool):
            raise contract.CampaignError(f"{key} must be boolean")
    _write_json(paths.controller_dir() / "backend.json", value)
    return value


def probe(adapter=None):
    value = settings()
    if not value["account"]:
        raise contract.CampaignError("configure backend.account before probing")
    observed = (adapter or SlurmAdapter(value)).probe()
    _write_json(paths.controller_dir() / "backend-catalog.json", observed)
    return observed


def plan(raw):
    return planner.plan(raw, settings())


@contextmanager
def lock():
    directory = paths.controller_dir() / "locks"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "campaigns.lock").open("a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def create(raw):
    specification = contract.validate(raw)
    bundle = contract.inventory(specification["bundle"])
    if specification["bundle"].get("sha256") and specification["bundle"]["sha256"] != bundle["sha256"]:
        raise contract.Conflict("bundle digest does not match declaration")
    request_hash = contract.digest({"spec": specification, "source_sha256": bundle["sha256"]})
    identity = specification["campaign_id"]
    backend = settings()
    if not backend["account"] or not backend["remote_root"]:
        raise contract.CampaignError("configure controller backend account and remote_root before accepting campaigns")
    with lock():
        with store.database() as con:
            existing = con.execute("SELECT request_hash FROM campaigns WHERE id=?", (identity,)).fetchone()
            if existing and existing[0] != request_hash:
                raise contract.Conflict("campaign_id already identifies a different declaration or source")
            if existing:
                already = True
            else:
                already = False
                for task in specification["tasks"]:
                    if not task["resources"]["gpu_count"]:
                        continue
                    fingerprint = json.dumps(contract.hardware_fingerprint(task["resources"]), sort_keys=True)
                    previous = con.execute("SELECT fingerprint FROM hardware_locks WHERE model_class=?", (task["model_class"],)).fetchone()
                    if previous and previous[0] != fingerprint:
                        raise contract.Conflict(f"model_class {task['model_class']} is locked to different hardware; use an explicit new scientific regime")
                    con.execute("INSERT OR IGNORE INTO hardware_locks(model_class,fingerprint) VALUES(?,?)", (task["model_class"], fingerprint))
                directory = store.root(identity)
                directory.mkdir(parents=True, exist_ok=True)
                contract.snapshot(specification["bundle"], bundle, directory / "bundle.tar.gz")
                (directory / "bundle.tar.gz").chmod(0o600)
                specification["bundle_manifest"] = bundle
                specification["backend"] = backend
                _write_json(directory / "declaration.json", specification)
                con.execute("INSERT INTO campaigns(id,spec,request_hash,state,created_at) VALUES(?,?,?,?,?)", (identity, json.dumps(specification, sort_keys=True), request_hash, "accepted", store.now()))
                for task in specification["tasks"]:
                    con.execute("INSERT INTO tasks(campaign_id,task_id,spec,state) VALUES(?,?,?,?)", (identity, task["task_id"], json.dumps(task, sort_keys=True), "waiting"))
                store.event(con, identity, None, "accepted", {"source_sha256": bundle["sha256"], "task_count": len(specification["tasks"])})
    value = store.read(identity)
    value["idempotent"] = already
    return value


def _intent(campaign, task):
    attempt = task["attempt"] + 1
    name = "uh-" + hashlib.sha256(f"{campaign['id']}/{task['task_id']}/{attempt}".encode()).hexdigest()[:28]
    with store.database() as con:
        con.execute("INSERT INTO attempts(campaign_id,task_id,attempt,job_name,state,created_at) VALUES(?,?,?,?,?,?)", (campaign["id"], task["task_id"], attempt, name, "submitting", store.now()))
        con.execute("UPDATE tasks SET attempt=?,job_name=?,job_id=NULL,state='submitting',error=NULL,observation=NULL,eligible_at=0 WHERE campaign_id=? AND task_id=?", (attempt, name, campaign["id"], task["task_id"]))
        store.event(con, campaign["id"], task["task_id"], "submitting", {"attempt": attempt, "job_name": name})
    return {**task, "attempt": attempt, "job_name": name, "state": "submitting", "job_id": None,
            "observation": None, "eligible_at": 0.0}


def _file_receipt(campaign, task, local, output, *, allow_empty=False):
    """Describe only a safe retrieved file; controller diagnostics are optional."""
    from urllib.parse import urlencode
    path = local / output
    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(local.resolve()):
        return None
    if not allow_empty and path.stat().st_size == 0:
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    query = urlencode({"task_id": task["task_id"], "path": output})
    return {"path": output, "sha256": digest.hexdigest(), "size_bytes": path.stat().st_size,
            "download_url": f"/api/v1/campaigns/{campaign['id']}/artifacts?{query}", "local_path": str(path)}


def controller_artifacts(campaign, task):
    """Expose only known attempt evidence, without making logs required outputs."""
    local = store.root(campaign["id"]) / "results" / task["task_id"]
    attempts = [a for a in campaign.get("attempts", []) if a["task_id"] == task["task_id"]]
    attempts.append(task)
    names = set()
    for attempt in attempts:
        number = attempt.get("attempt", 0)
        if isinstance(number, int) and 0 < number <= task["attempt"]:
            names.update((f".controller/hardware-{number}.json", f".controller/gpu-samples-{number}.csv"))
        if attempt.get("job_name"):
            names.update(attempt["job_name"] + "." + suffix for suffix in ("out", "err"))
    return [receipt for name in sorted(names)
            if (receipt := _file_receipt(campaign, task, local, name, allow_empty=True)) is not None]


def record_controller_artifacts(campaign, task):
    """Retain retrieved failure evidence without promoting scientific completion."""
    diagnostics = controller_artifacts(campaign, task)
    if not diagnostics:
        return
    with store.database() as con:
        row = con.execute("SELECT artifacts FROM tasks WHERE campaign_id=? AND task_id=?",
                          (campaign["id"], task["task_id"])).fetchone()
        metadata = json.loads(row[0]) if row and row[0] else {"files": [], "complete": False}
        if metadata.get("controller_files") == diagnostics:
            return
        metadata["controller_files"] = diagnostics
        con.execute("UPDATE tasks SET artifacts=? WHERE campaign_id=? AND task_id=?",
                    (json.dumps(metadata, sort_keys=True), campaign["id"], task["task_id"]))
        store.event(con, campaign["id"], task["task_id"], "diagnostics_available", {"controller_files": diagnostics})


def _collect(campaign, task, adapter, successful):
    local = adapter.collect(campaign, task)
    record_controller_artifacts(campaign, task)
    spec = task["spec"]
    hardware_path = local / ".controller" / f"hardware-{task['attempt']}.json"
    if not hardware_path.is_file():
        raise contract.Conflict("job ended without hardware attestation; outputs cannot be marked complete")
    hardware = json.loads(hardware_path.read_text())
    if not hardware.get("verified") or hardware.get("task_id") != task["task_id"] or hardware.get("attempt") != task["attempt"]:
        raise contract.Conflict("hardware attestation is missing, invalid, or belongs to another attempt")
    if spec["resources"]["gpu_count"]:
        resources = spec["resources"]
        if len(hardware.get("gpus", [])) != resources["gpu_count"]:
            raise contract.Conflict("GPU count in attestation differs from the scientific hardware lock")
        for gpu in hardware["gpus"]:
            if gpu["name"] != resources["expected_gpu_name"] or abs(gpu["memory_mb"] - resources["expected_gpu_memory_mb"]) > resources["gpu_memory_tolerance_mb"]:
                raise contract.Conflict("GPU attestation does not satisfy the scientific hardware lock")
        actual = [{"name": gpu["name"], "memory_mb": gpu["memory_mb"]} for gpu in hardware["gpus"]]
        store.bind_observed(spec["model_class"], actual)
    artifacts, missing = [], []
    for output in spec["outputs"]:
        receipt = _file_receipt(campaign, task, local, output)
        if receipt is None:
            missing.append(output)
            continue
        artifacts.append(receipt)
    metadata = {"files": artifacts, "controller_files": controller_artifacts(campaign, task),
                "missing": missing, "hardware": hardware, "attempt": task["attempt"], "job_id": task["job_id"], "complete": successful and not missing}
    store.change(campaign["id"], task["task_id"], "completed" if metadata["complete"] else "failed", artifacts=metadata, error=None if metadata["complete"] else "scheduler failed or required outputs missing")


def _finish_campaign(identity):
    value = store.read(identity)
    states = {t["state"] for t in value["tasks"]}
    if states <= TERMINAL:
        state = "completed" if states == {"completed"} else "cancelled" if states <= {"completed", "cancelled"} else "failed"
    else:
        state = "cancelling" if value["state"] == "cancelling" else "running"
    with store.database() as con:
        if state != value["state"]:
            con.execute("UPDATE campaigns SET state=? WHERE id=?", (state, identity))
            store.event(con, identity, None, state)


def _reconcile(campaign, transport, clock):
    backend = campaign["spec"]["backend"]
    active = [t for t in campaign["tasks"] if t["state"] in ACTIVE and t.get("job_name")]
    if active:
        try:
            observations = transport.observe(campaign, active)
        except Exception as exc:
            with store.database() as con:
                con.execute("UPDATE campaigns SET error=? WHERE id=?", (str(exc), campaign["id"]))
            return False
        for task in active:
            observation = observations.get(task["job_name"])
            if not observation:
                if task["state"] == "submitting":
                    store.change(campaign["id"], task["task_id"], "uncertain", error="interrupted submission; reconcile by unique job name before any retry")
                continue
            task["job_id"] = observation["job_id"]
            fetch_attempts = (task.get("observation") or {}).get("fetch_attempts", 0)
            observation["fetch_attempts"] = fetch_attempts
            state = observation["state"]
            if campaign["state"] == "cancelling" and state not in SLURM_TERMINAL:
                transport.cancel([task["job_id"]])
                store.change(campaign["id"], task["task_id"], "cancelling", job_id=task["job_id"], observation=observation)
                continue
            if state in SLURM_TERMINAL:
                store.change(campaign["id"], task["task_id"], "fetching", job_id=task["job_id"], observation=observation)
                if state == "CANCELLED" or campaign["state"] == "cancelling":
                    try:
                        transport.collect(campaign, task)
                        record_controller_artifacts(campaign, task)
                    except Exception:
                        pass
                    store.change(campaign["id"], task["task_id"], "cancelled", observation=observation)
                elif state in RETRYABLE and task["attempt"] < campaign["spec"]["max_attempts"]:
                    # Checkpoints share one task output path. A retry never changes hardware.
                    try:
                        transport.collect(campaign, task)
                        record_controller_artifacts(campaign, task)
                    except Exception:
                        pass
                    store.change(campaign["id"], task["task_id"], "waiting", eligible_at=clock() + backend["retry_backoff_seconds"] * 2 ** (task["attempt"] - 1), observation=observation, error=f"infrastructure failure: {state}; bounded retry scheduled")
                else:
                    if task["state"] == "fetching" and task["eligible_at"] > clock():
                        continue
                    try:
                        _collect(campaign, task, transport, state == "COMPLETED" and observation.get("exit_code", "0:0") == "0:0")
                    except contract.Conflict as exc:
                        store.change(campaign["id"], task["task_id"], "failed", error=str(exc))
                    except Exception as exc:
                        # Fetch failure is recoverable independently of compute. No resubmit.
                        observation["fetch_attempts"] += 1
                        store.change(campaign["id"], task["task_id"], "failed" if observation["fetch_attempts"] >= backend["max_fetch_attempts"] else "fetching", error=str(exc), observation=observation,
                                     eligible_at=clock() + backend["retry_backoff_seconds"])
            else:
                store.change(campaign["id"], task["task_id"], "running" if state in ("RUNNING", "COMPLETING") else "accepted", job_id=task["job_id"], observation=observation, error=None)
    if campaign["state"] == "cancelling":
        for task in campaign["tasks"]:
            if task["state"] == "waiting":
                store.change(campaign["id"], task["task_id"], "cancelled")
    return True


def tick(identity=None, adapter=None, clock=time.time, admission_clock=time.monotonic):
    """One restart-safe pass. Tests supply an adapter, never SSH or Slurm."""
    with lock():
        # Capacity is service policy, so changes apply to every campaign on the
        # next pass. Execution locations and per-campaign behavior stay frozen.
        controller_limits = settings()
        campaigns = [store.read(identity)] if identity else [store.read(c["id"]) for c in store.listing() if c["state"] not in TERMINAL]
        reconciled = set()
        for campaign in campaigns:
            transport = adapter or SlurmAdapter(campaign["spec"]["backend"])
            if _reconcile(campaign, transport, clock):
                reconciled.add(campaign["id"])
                _finish_campaign(campaign["id"])
        # Reconcile every accepted attempt before staging or submitting work.
        # A long staging batch must not postpone existing result transfers.
        admission_started = admission_clock()
        admission_attempts = admission_progress = 0
        deferred_eligible = False
        global_active = [t for c in store.listing() for t in store.read(c["id"])["tasks"] if t["state"] in ACTIVE]
        for original in campaigns:
            if original["id"] not in reconciled:
                continue
            campaign = store.read(original["id"])
            if campaign["state"] in TERMINAL:
                continue
            backend = campaign["spec"]["backend"]
            # Mail is current service policy, including for waiting tasks and
            # retries in campaigns accepted before notifications were enabled.
            transport = adapter or SlurmAdapter({**backend, "mail_user": controller_limits["mail_user"]})
            global_active = [t for c in store.listing() for t in store.read(c["id"])["tasks"] if t["state"] in ACTIVE]
            states = {t["task_id"]: t["state"] for t in campaign["tasks"]}
            running = sum(t["state"] in ACTIVE for t in campaign["tasks"])
            for task in campaign["tasks"]:
                if task["state"] != "waiting" or task["eligible_at"] > clock():
                    continue
                if campaign["state"] == "cancelling":
                    store.change(campaign["id"], task["task_id"], "cancelled")
                    continue
                deps = task["spec"]["depends_on"]
                if any(states[d] in TERMINAL - {"completed"} for d in deps):
                    store.change(campaign["id"], task["task_id"], "blocked", error="a required task did not complete")
                    continue
                if any(states[d] != "completed" for d in deps):
                    continue
                if running >= campaign["spec"]["max_concurrent"] or len(global_active) >= controller_limits["max_active_tasks"]:
                    break
                gpu_count = task["spec"]["resources"]["gpu_count"]
                if sum(t["spec"]["resources"]["gpu_count"] for t in global_active) + gpu_count > controller_limits["max_active_gpus"]:
                    continue
                placement = planner.select(task["spec"]["resources"], backend)
                if placement["warnings"] or not placement["selected_partitions"]:
                    with store.database() as con:
                        con.execute("UPDATE tasks SET error=? WHERE campaign_id=? AND task_id=?", ("; ".join(placement["warnings"]) or "no eligible exact hardware partition; refresh backend probe", campaign["id"], task["task_id"]))
                    continue
                same_qos = [t for t in global_active if (t["spec"]["resources"].get("qos") or backend["qos"]) == placement["qos"]]
                count_limits = [placement["qos_limits"].get(k) for k in ("max_submit_jobs", "max_jobs")]
                count_limits += [placement["account_limits"].get(k) for k in ("max_submit_jobs", "max_jobs", "grp_submit_jobs", "grp_jobs")]
                if any(limit is not None and len(same_qos) >= limit for limit in count_limits):
                    continue
                qos_tres = planner.tres_limits(placement["qos_limits"].get("max_tres_per_user"))
                account_tres = planner.tres_limits(placement["account_limits"].get("grp_tres"))
                requested = {"cpu": task["spec"]["resources"]["cpus"], "gres/gpu": gpu_count, "node": 1}
                def exceeds(limits, tasks):
                    used = {"cpu": sum(t["spec"]["resources"]["cpus"] for t in tasks), "gres/gpu": sum(t["spec"]["resources"]["gpu_count"] for t in tasks), "node": len(tasks)}
                    return any(used[key] + requested[key] > ceiling for key, ceiling in limits.items())
                if exceeds(qos_tres, same_qos) or exceeds(account_tres, global_active):
                    continue
                if (admission_attempts >= controller_limits["max_new_tasks_per_pass"]
                        or admission_clock() - admission_started >= controller_limits["admission_budget_seconds"]):
                    deferred_eligible = True
                    break
                if not campaign["staged"]:
                    try:
                        staged_at = admission_clock()
                        staged_receipt = transport.stage(campaign)
                    except Exception as exc:
                        with store.database() as con:
                            con.execute("UPDATE campaigns SET error=? WHERE id=?", (str(exc), campaign["id"]))
                        break
                    with store.database() as con:
                        con.execute("UPDATE campaigns SET staged=1,error=NULL WHERE id=?", (campaign["id"],))
                        evidence = {"elapsed_seconds": round(admission_clock() - staged_at, 3)}
                        if isinstance(staged_receipt, dict):
                            evidence.update(staged_receipt)
                        store.event(con, campaign["id"], None, "source_staged", evidence)
                    campaign["staged"] = 1
                task = _intent(campaign, task)
                admission_attempts += 1
                try:
                    receipt = transport.submit(campaign, task, placement)
                except Exception as exc:
                    receipt = {"outcome": "uncertain", "error": str(exc)}
                outcome = receipt.get("outcome", "uncertain")
                state = "accepted" if outcome == "accepted" and str(receipt.get("job_id", "")).isdigit() else "rejected" if outcome == "rejected" else "uncertain"
                store.change(campaign["id"], task["task_id"], state, job_id=receipt.get("job_id"), error=receipt.get("error"))
                with store.database() as con:
                    con.execute("UPDATE attempts SET receipt=?,state=? WHERE campaign_id=? AND task_id=? AND attempt=?", (json.dumps(receipt), state, campaign["id"], task["task_id"], task["attempt"]))
                if state in ACTIVE:
                    admission_progress += 1
                    running += 1
                    global_active.append(task)
            _finish_campaign(campaign["id"])
            if deferred_eligible:
                break
        return {"admission_attempts": admission_attempts, "admission_progress": admission_progress,
                "admission_seconds": round(admission_clock() - admission_started, 3),
                "deferred_eligible": deferred_eligible,
                "continue_immediately": bool(admission_progress and deferred_eligible)}


def cancel(identity):
    with lock():
        campaign = store.read(identity)
        if campaign["state"] in TERMINAL:
            return campaign
        with store.database() as con:
            con.execute("UPDATE campaigns SET state='cancelling' WHERE id=?", (identity,))
            store.event(con, identity, None, "cancelling")
        transport = SlurmAdapter(campaign["spec"]["backend"])
        jobs = [t["job_id"] for t in campaign["tasks"] if t["state"] in ACTIVE and t["job_id"]]
        transport.cancel(jobs)
        for task in campaign["tasks"]:
            if task["state"] == "waiting":
                store.change(identity, task["task_id"], "cancelled")
    _finish_campaign(identity)
    return store.read(identity)


def artifact(identity, task_id, output):
    contract.safe_id(task_id, "task_id")
    output = contract.relative(output)
    campaign = store.read(identity)
    task = next((t for t in campaign["tasks"] if t["task_id"] == task_id), None)
    allowed = set(task["spec"]["outputs"]) if task else set()
    if task:
        allowed.update(receipt["path"] for receipt in (task.get("artifacts") or {}).get("controller_files", []))
    if output not in allowed:
        raise FileNotFoundError("artifact is not a declared output or retrieved controller diagnostic")
    root = store.root(identity) / "results" / task_id
    path = root / output
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise FileNotFoundError("artifact has not been retrieved")
    return path


def _loop():
    last_probe = 0
    while not _stop.is_set():
        try:
            last_probe, progress = worker_pass(last_probe, with_progress=True)
            if (progress or {}).get("continue_immediately"):
                continue
        except Exception as exc:
            from controller import events
            events.record("campaign-error", str(exc), ok=False)
        _stop.wait(settings()["poll_seconds"])


def worker_pass(last_probe=0, *, with_progress=False):
    """Catalog failure must never suppress receipt reconciliation or fetch."""
    pending = any(c["state"] not in TERMINAL for c in store.listing())
    if pending and (last_probe == 0 or time.monotonic() - last_probe >= 900):
        # Bound unsuccessful refreshes too, so catalog downtime cannot cause
        # one expensive policy survey on every 30-second task poll.
        last_probe = time.monotonic()
        try:
            probe()
        except Exception as exc:
            from controller import events
            events.record("campaign-probe-error", str(exc), ok=False)
    progress = tick() if pending else None
    return (last_probe, progress) if with_progress else last_probe


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="portable-campaigns", daemon=True)
    _thread.start()


def stop():
    _stop.set()
    if _thread:
        _thread.join(timeout=3)
