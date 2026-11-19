"""Durable portable campaigns: stage, submit, reconcile, retry, and return files.

This module is the controller's small public interface. Scientific commands
and evaluations remain opaque. Tests replace its Slurm adapter or the Cluster access transport under it.
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
from controller import campaign_contract as contract, campaign_lifecycle as lifecycle, campaign_planner as planner, campaign_store as store, catalog, events, hardware_class
from controller.campaign_slurm import SlurmAdapter
from controller.cluster_access import clean_ssh_host, clean_ssh_identity

DEFAULTS = {"ssh_host": "unity", "ssh_identity": "", "account": "", "remote_root": "", "allowed_partitions": ["gpu", "gpu-preempt"],
            "cpu_partitions": ["cpu", "cpu-preempt"], "qos": "normal", "mail_user": "", "poll_seconds": 30, "catalog_max_age_seconds": 3600,
            "max_active_tasks": 32, "max_active_gpus": 32, "max_new_tasks_per_pass": 4, "admission_budget_seconds": 10, "allow_preemptible": True, "sample_gpu_metrics": True, "retry_backoff_seconds": 60, "max_fetch_attempts": 5}
_thread = None
_worker = None


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


def slurm_adapter(campaign=None, live=None):
    """The Slurm adapter for one campaign now: the campaign's frozen backend (alias,
    identity, account, remote root) with the current mail policy. Without a
    campaign: the current backend settings, for the catalog refresh."""
    live = settings() if live is None else live
    if campaign is None:
        return SlurmAdapter(live)
    return SlurmAdapter({**campaign["spec"]["backend"], "mail_user": live["mail_user"]})


def probe(adapter=None):
    value = settings()
    if not value["account"]:
        raise contract.CampaignError("configure backend.account before probing")
    return catalog.refresh(adapter or slurm_adapter(live=value))


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
    # An accepted declaration is immutable. Identical HTTP retries can read it
    # without waiting for a worker's bounded remote source-staging operation.
    try:
        accepted = store.read(identity)
    except FileNotFoundError:
        pass
    else:
        if accepted["request_hash"] != request_hash:
            raise contract.Conflict("campaign_id already identifies a different declaration or source")
        accepted["idempotent"] = True
        return accepted
    with lock():
        hardware = hardware_class.class_locks(specification["tasks"])
        existing, locked = store.prior_acceptance(identity, [model_class for model_class, _ in hardware])
        if existing is not None and existing != request_hash:
            raise contract.Conflict("campaign_id already identifies a different declaration or source")
        already = existing is not None
        if not already:
            conflict = hardware_class.conflicting_class(hardware, locked)
            if conflict is not None:
                raise contract.Conflict(f"model_class {conflict} is locked to different hardware; use an explicit new scientific regime")
            directory = store.root(identity)
            directory.mkdir(parents=True, exist_ok=True)
            contract.snapshot(specification["bundle"], bundle, directory / "bundle.tar.gz")
            (directory / "bundle.tar.gz").chmod(0o600)
            specification["bundle_manifest"] = bundle
            specification["backend"] = backend
            _write_json(directory / "declaration.json", specification)
            store.accept(identity, specification, request_hash, hardware,
                         {"source_sha256": bundle["sha256"], "task_count": len(specification["tasks"])})
    value = store.read(identity)
    value["idempotent"] = already
    return value


def _intent(campaign, task):
    attempt = task["attempt"] + 1
    digest = hashlib.sha256(f"{campaign['id']}/{task['task_id']}/{attempt}".encode()).hexdigest()[:20]
    # Keep Slurm names readable while retaining a collision-resistant attempt ID.
    # The 97-character bound also fits the accounting query's JobName%100 field.
    name = f"{campaign['id'][:64]}-{task['task_id'][:10]}-{digest}"
    step = lifecycle.intent(attempt, name)
    store.record_intent(campaign["id"], task["task_id"], step)
    return {**task, "attempt": attempt, "job_name": name, "state": step.state, "job_id": None,
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
            names.update((hardware_class.hardware_evidence(number), hardware_class.gpu_samples(number)))
        if attempt.get("job_name"):
            names.update(attempt["job_name"] + "." + suffix for suffix in ("out", "err"))
    return [receipt for name in sorted(names)
            if (receipt := _file_receipt(campaign, task, local, name, allow_empty=True)) is not None]


def record_controller_artifacts(campaign, task):
    """Retain retrieved failure evidence without promoting scientific completion.
    Returns the receipts, so delivery records the same ones without hashing again."""
    diagnostics = controller_artifacts(campaign, task)
    if diagnostics:
        store.record_diagnostics(campaign["id"], task["task_id"], diagnostics)
    return diagnostics


def _collect(campaign, task, adapter, successful):
    local = adapter.collect(campaign, task)
    diagnostics = record_controller_artifacts(campaign, task)
    spec = task["spec"]
    hardware_path = local / hardware_class.hardware_evidence(task["attempt"])
    if not hardware_path.is_file():
        raise contract.Conflict("job ended without hardware attestation; outputs cannot be marked complete")
    hardware = json.loads(hardware_path.read_text())
    problem = hardware_class.attestation_problem(spec["resources"], task["task_id"], task["attempt"], hardware)
    if problem:
        raise contract.Conflict(problem)
    if spec["resources"]["gpu_count"]:
        store.bind_observed(spec["model_class"], hardware_class.observed(hardware["gpus"]))
    artifacts, missing = [], []
    for output in spec["outputs"]:
        receipt = _file_receipt(campaign, task, local, output)
        if receipt is None:
            missing.append(output)
            continue
        artifacts.append(receipt)
    metadata = {"files": artifacts, "controller_files": diagnostics,
                "missing": missing, "hardware": hardware, "attempt": task["attempt"], "job_id": task["job_id"]}
    step = lifecycle.delivered(metadata, successful=successful)
    store.record_transition(campaign["id"], task["task_id"], step.state, **step.fields)


def _campaign_failed(identity, step, exc):
    """One campaign's step raised: show it on the campaign and in events.jsonl; the pass goes on.
    When the journal cannot record it, the exception ends the pass."""
    detail = str(exc) or type(exc).__name__
    line = f"{identity}: {step}: {detail}"
    try:
        changed = store.record_campaign_error(identity, step, detail)
    except Exception:
        events.record("campaign-error", line, ok=False, campaign_id=identity)
        raise
    if changed:
        events.record("campaign-error", line, ok=False, campaign_id=identity)


def _resolved(campaign, step):
    """The step succeeded for this campaign: clear the error it recorded, and no other."""
    error = campaign.get("error")
    if store.error_step(error) == step:
        store.clear_campaign_error(campaign["id"], error)
        campaign["error"] = None


def _reconcile(campaign, adapter, clock):
    backend = campaign["spec"]["backend"]
    cancelling = campaign["state"] == lifecycle.CANCELLING
    active = [t for t in campaign["tasks"] if t["state"] in lifecycle.ACTIVE and t.get("job_name")]
    if active:
        observations = adapter.observe(campaign, active)
        for task in active:
            raw = observations.get(task["job_name"])
            if raw:
                task["job_id"] = raw["job_id"]
            decision = lifecycle.observed(task, raw, cancelling=cancelling,
                                          max_attempts=campaign["spec"]["max_attempts"], now=clock.wall())
            if decision.effect == lifecycle.CANCEL_JOB:
                adapter.cancel([task["job_id"]])
            if decision.step:
                store.record_transition(campaign["id"], task["task_id"], decision.step.state, **decision.step.fields)
            if decision.effect not in (lifecycle.SALVAGE, lifecycle.RETRIEVE):
                continue
            observation = decision.step.fields["observation"]
            if decision.effect == lifecycle.SALVAGE:
                # Checkpoints share one task output path. A retry never changes hardware.
                try:
                    adapter.collect(campaign, task)
                    record_controller_artifacts(campaign, task)
                except Exception:
                    pass
                step = lifecycle.salvaged(task, observation, cancelling=cancelling,
                                          retry_backoff_seconds=backend["retry_backoff_seconds"], now=clock.wall())
            else:
                try:
                    _collect(campaign, task, adapter, lifecycle.scheduler_succeeded(observation))
                    continue
                except Exception as exc:
                    # Fetch failure is recoverable independently of compute. No resubmit.
                    step = lifecycle.undelivered(observation, str(exc), conflict=isinstance(exc, contract.Conflict),
                                                 max_fetch_attempts=backend["max_fetch_attempts"],
                                                 retry_backoff_seconds=backend["retry_backoff_seconds"], now=clock.wall())
            store.record_transition(campaign["id"], task["task_id"], step.state, **step.fields)
    if cancelling:
        for task in campaign["tasks"]:
            step = lifecycle.cancel_request(task)
            if step:
                store.record_transition(campaign["id"], task["task_id"], step.state, **step.fields)


class Clock:
    """The Worker's time source. wall(): epoch seconds, for times that are stored or
    compared with stored times. monotonic(): seconds for durations inside this process."""

    def wall(self):
        return time.time()

    def monotonic(self):
        return time.monotonic()


def tick(identity=None, adapter=None, clock=None):
    """One restart-safe pass. Tests supply an adapter and a clock, never SSH or Slurm.
    A failure while handling one campaign is recorded on that campaign; the pass goes on."""
    clock = Clock() if clock is None else clock
    with lock():
        # Capacity is service policy, so changes apply to every campaign on the
        # next pass. Execution locations and per-campaign behavior stay frozen.
        controller_limits = settings()
        identities = [identity] if identity else store.identities_excluding(lifecycle.CAMPAIGN_TERMINAL)
        reconciled = []
        for campaign_id in identities:
            try:
                campaign = store.read(campaign_id)
                _reconcile(campaign, adapter or slurm_adapter(campaign, controller_limits), clock)
                store.roll_up(campaign_id)
                _resolved(campaign, "reconcile")
            except Exception as exc:
                _campaign_failed(campaign_id, "reconcile", exc)
            else:
                reconciled.append(campaign_id)
        # Reconcile every accepted attempt before staging or submitting work.
        # A long staging batch must not postpone existing result transfers.
        admission_started = clock.monotonic()
        admission_attempts = admission_progress = 0
        deferred_eligible = False
        # The campaign lock fences concurrent creation/cancellation. Reconcile
        # first, then count active tasks once and append each accepted intent.
        # After a campaign fails, count again from the journal: its last intent
        # may have no recorded outcome and is still active.
        # Historical bundle manifests must not consume the admission window.
        global_active = store.tasks_in_states(lifecycle.ACTIVE)
        observed = planner.UNREAD  # the Catalog for this pass: read at the first placement, then kept
        for campaign_id in reconciled:
            if deferred_eligible:
                break
            try:
                campaign = store.read(campaign_id)
                if campaign["state"] in lifecycle.CAMPAIGN_TERMINAL:
                    continue
                backend = campaign["spec"]["backend"]
                # Mail is current service policy, including for waiting tasks and
                # retries in campaigns accepted before notifications were enabled.
                slurm = adapter or slurm_adapter(campaign, controller_limits)
                states = {t["task_id"]: t["state"] for t in campaign["tasks"]}
                running = sum(t["state"] in lifecycle.ACTIVE for t in campaign["tasks"])
                cancelling = campaign["state"] == lifecycle.CANCELLING
                for task in campaign["tasks"]:
                    decision = lifecycle.admission(task, states, cancelling=cancelling, now=clock.wall())
                    if decision.step:
                        store.record_transition(campaign["id"], task["task_id"], decision.step.state, **decision.step.fields)
                        continue
                    if decision.effect != lifecycle.ADMIT:
                        continue
                    if running >= campaign["spec"]["max_concurrent"] or len(global_active) >= controller_limits["max_active_tasks"]:
                        break
                    gpu_count = task["spec"]["resources"]["gpu_count"]
                    if sum(t["spec"]["resources"]["gpu_count"] for t in global_active) + gpu_count > controller_limits["max_active_gpus"]:
                        continue
                    try:
                        if observed is planner.UNREAD:
                            observed = catalog.load()
                        placement = planner.select(task["spec"]["resources"], backend, observed, now=clock.wall())
                    except Exception as exc:
                        _campaign_failed(campaign_id, "placement", exc)
                        break
                    _resolved(campaign, "placement")
                    if placement["warnings"] or not placement["selected_partitions"]:
                        store.record_task_error(campaign["id"], task["task_id"], "; ".join(placement["warnings"]) or "no eligible exact hardware partition; refresh backend probe")
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
                            or clock.monotonic() - admission_started >= controller_limits["admission_budget_seconds"]):
                        deferred_eligible = True
                        break
                    if not campaign["staged"]:
                        try:
                            staged_at = clock.monotonic()
                            staged_receipt = slurm.stage(campaign)
                        except Exception as exc:
                            _campaign_failed(campaign_id, "stage", exc)
                            break
                        evidence = {"elapsed_seconds": round(clock.monotonic() - staged_at, 3)}
                        evidence.update(staged_receipt)
                        store.record_staged(campaign["id"], evidence)
                        campaign["staged"] = 1
                        _resolved(campaign, "stage")
                    task = _intent(campaign, task)
                    admission_attempts += 1
                    try:
                        receipt = slurm.submit(campaign, task, placement)
                    except Exception as exc:
                        receipt = lifecycle.uncertain_receipt(str(exc))
                    step = lifecycle.submitted(receipt)
                    store.record_submission(campaign["id"], task["task_id"], task["attempt"], receipt, step)
                    if step.state in lifecycle.ACTIVE:
                        admission_progress += 1
                        running += 1
                        global_active.append(task)
                store.roll_up(campaign["id"])
                _resolved(campaign, "admission")
            except Exception as exc:
                _campaign_failed(campaign_id, "admission", exc)
                global_active = store.tasks_in_states(lifecycle.ACTIVE)
        return {"admission_attempts": admission_attempts, "admission_progress": admission_progress,
                "admission_seconds": round(clock.monotonic() - admission_started, 3),
                "deferred_eligible": deferred_eligible,
                "continue_immediately": bool(admission_progress and deferred_eligible)}


def cancel(identity, adapter=None):
    with lock():
        campaign = store.read(identity)
        state = lifecycle.cancel_campaign(campaign["state"])
        if state is None:
            return campaign
        store.record_cancel_request(identity, state)
        slurm = adapter or slurm_adapter(campaign)
        jobs = [t["job_id"] for t in campaign["tasks"] if t["state"] in lifecycle.ACTIVE and t["job_id"]]
        slurm.cancel(jobs)
        for task in campaign["tasks"]:
            step = lifecycle.cancel_request(task)
            if step:
                store.record_transition(identity, task["task_id"], step.state, **step.fields)
    store.roll_up(identity)
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


class Worker:
    """The Worker thread: its clock, its catalog refresh schedule, and its stop signal."""

    def __init__(self, *, clock=None, adapter=None, refresh_catalog=None, stop=None):
        self.clock = Clock() if clock is None else clock
        self.adapter = adapter  # None: slurm_adapter() for each campaign
        self.refresh_catalog = probe if refresh_catalog is None else refresh_catalog
        self.stop = threading.Event() if stop is None else stop
        self.catalog_schedule = catalog.RefreshSchedule(self.clock.monotonic())  # the first pass with work refreshes the catalog

    def run_pass(self):
        """One pass: refresh the catalog when due, then tick. Catalog failure must never
        suppress receipt reconciliation or fetch. Returns tick's report, or None when no
        campaign needs work."""
        if not store.identities_excluding(lifecycle.CAMPAIGN_TERMINAL):
            return None
        if self.catalog_schedule.claim(self.clock.monotonic()):
            # Bound unsuccessful refreshes too, so catalog downtime cannot cause
            # one expensive policy survey on every 30-second task poll.
            try:
                self.refresh_catalog()
            except Exception as exc:
                events.record("campaign-probe-error", str(exc), ok=False)
        return tick(adapter=self.adapter, clock=self.clock)

    def run(self):
        while not self.stop.is_set():
            try:
                report = self.run_pass()
                if report is not None and report["continue_immediately"]:
                    continue
            except Exception as exc:
                events.record("campaign-error", str(exc), ok=False)
            self.stop.wait(settings()["poll_seconds"])


def start():
    global _worker, _thread
    if _thread and _thread.is_alive():
        return
    try:
        store.prepare()
    except Exception:
        # the same error recurs on the first journal use and is recorded there
        pass
    _worker = Worker()
    _thread = threading.Thread(target=_worker.run, name="portable-campaigns", daemon=True)
    _thread.start()


def stop():
    if _worker:
        _worker.stop.set()
    if _thread:
        _thread.join(timeout=3)
