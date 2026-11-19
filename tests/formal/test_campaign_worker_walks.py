"""Generated walks of the real Worker pass, checked against the rules of
tests/formal/campaign_worker/CampaignWorker.tla.

Each walk drives campaigns.tick and campaigns.cancel through a fake Slurm.
The walk picks submit outcomes (accepted, reply lost after sbatch, reply lost
while sbatch can still run, refused), job ends, controller crashes before and
after journal writes and Slurm calls, and journal write errors. After every
step it checks the model's rules on the real journal and the fake Slurm.

CAMPAIGN_WORKER_WALKS and CAMPAIGN_WORKER_STEPS make the run longer.
A failure prints the seed and the steps; rerun one walk with
CAMPAIGN_WORKER_SEED=<seed>.
"""

from __future__ import annotations

import copy
import json
import os
import random
import sqlite3

import pytest

from controller import campaign_lifecycle as lifecycle, campaign_planner as planner, campaign_store as store, campaigns, catalog

WALKS = int(os.environ.get("CAMPAIGN_WORKER_WALKS", "45"))
STEPS = int(os.environ.get("CAMPAIGN_WORKER_STEPS", "24"))
SEED = os.environ.get("CAMPAIGN_WORKER_SEED")

# The model's constants (MCCampaignWorker.tla), and the two finding configs.
PROFILES = {
    "model": {"max_active_tasks": 2, "max_active_gpus": 1, "qos_limits": {"normal": 2, "long": 1}, "account_limit": 2},
    "qos-finding": {"max_active_tasks": 3, "max_active_gpus": 1, "qos_limits": {"normal": 2, "long": 1}, "account_limit": 3},
    "account-finding": {"max_active_tasks": 3, "max_active_gpus": 2, "qos_limits": {"normal": 2, "long": 2}, "account_limit": 2},
}
LIVE = {"PENDING", "RUNNING"}
WRITES = ("record_intent", "record_submission", "record_transition", "roll_up", "record_staged", "record_diagnostics",
          "record_cancel_request", "record_campaign_error", "clear_campaign_error", "record_task_error", "bind_observed")


class Crash(BaseException):
    """The controller process dies here; no handler in the controller runs."""


def gpu_task(task_id):
    return {"task_id": task_id, "model_class": "walk-a100-v1", "argv": ["python3", "run.py"], "env": {}, "outputs": ["out.json"],
            "resources": {"gpu_type": "a100", "gpu_count": 1, "cpus": 1, "memory_mb": 1024, "walltime_seconds": 600,
                          "expected_gpu_name": "NVIDIA A100-SXM4-80GB", "expected_gpu_memory_mb": 81151}}


def cpu_task(task_id, qos=None):
    resources = {"gpu_count": 0, "cpus": 1, "memory_mb": 1024, "walltime_seconds": 600}
    if qos:
        resources["qos"] = qos
    return {"task_id": task_id, "argv": ["python3", "run.py"], "env": {}, "outputs": ["out.json"], "resources": resources}


class World:
    """Fake Slurm and the fault plan of one walk."""

    def __init__(self, rng):
        self.rng, self.jobs, self.inflight, self.names, self.next_id = rng, {}, set(), {}, 1000
        self.faults = False
        self.log = []

    def fault(self, rate=0.06):
        if self.faults and self.rng.random() < rate:
            raise Crash()

    def _job(self, name):
        self.next_id += 1
        self.jobs[name] = {"job_id": str(self.next_id), "state": self.rng.choice(["PENDING", "RUNNING"])}

    # The SlurmAdapter interface used by campaigns.tick and campaigns.cancel.
    def stage(self, campaign):
        self.fault()
        return {}

    def submit(self, campaign, task, placement):
        name = task["job_name"]
        self.names[name] = (campaign["id"], task["task_id"], task["attempt"])
        self.fault()
        outcome = self.rng.choice(["accepted", "accepted", "lost-after-sbatch", "lost-in-flight", "lost-before-sbatch", "refused"])
        self.log.append(f"    submit {task['task_id']}#{task['attempt']}: {outcome}")
        if outcome in ("accepted", "lost-after-sbatch"):
            self._job(name)
        elif outcome == "lost-in-flight":
            self.inflight.add(name)
        self.fault()
        if outcome == "accepted":
            return {"outcome": "accepted", "job_id": self.jobs[name]["job_id"]}
        if outcome == "refused":
            return {"outcome": "rejected", "error": "HPC_SUBMISSION_REJECTED"}
        if self.rng.random() < 0.5:
            raise RuntimeError("ssh connection lost")
        return {"outcome": "uncertain", "error": "submission receipt missing"}

    def observe(self, campaign, tasks):
        self.fault()
        if self.faults and self.rng.random() < 0.05:
            raise RuntimeError("scheduler observation failed")
        found = {}
        for task in tasks:
            job = self.jobs.get(task["job_name"])
            if job:
                exit_code = "1:0" if job["state"] == "FAILED" else "0:0"
                found[task["job_name"]] = {"job_id": job["job_id"], "job_name": task["job_name"], "state": job["state"],
                                           "exit_code": exit_code, "node_list": "n1"}
        return found

    def cancel(self, job_ids):
        self.fault()
        for job in self.jobs.values():
            if job["job_id"] in job_ids and job["state"] in LIVE:
                job["state"] = "CANCELLED"
        self.fault()

    def collect(self, campaign, task):
        self.fault()
        if self.faults and self.rng.random() < 0.15:
            raise RuntimeError("artifact transfer failed")
        local = store.root(campaign["id"]) / "results" / task["task_id"]
        (local / ".controller").mkdir(parents=True, exist_ok=True)
        gpus = [{"name": "NVIDIA A100-SXM4-80GB", "memory_mb": 81151}] * task["spec"]["resources"]["gpu_count"]
        record = {"verified": True, "task_id": task["task_id"], "attempt": task["attempt"], "gpus": gpus}
        (local / ".controller" / f"hardware-{task['attempt']}.json").write_text(json.dumps(record))
        (local / "out.json").write_text("{}\n")
        return local

    # Slurm moving on by itself between controller steps.
    def advance(self):
        for name, job in self.jobs.items():
            if job["state"] in LIVE and self.rng.random() < 0.5:
                job["state"] = self.rng.choice(["COMPLETED", "FAILED", "NODE_FAIL", "PREEMPTED", "RUNNING"])
        for name in sorted(self.inflight):
            if self.rng.random() < 0.5:
                self.inflight.discard(name)
                if self.rng.random() < 0.7:
                    self._job(name)


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def wall(self):
        return self.now

    def monotonic(self):
        return 0.0


def journal():
    tasks, campaign_states, backends = {}, {}, {}
    for identity in ("c1", "c2"):
        value = store.read(identity)
        campaign_states[identity] = value["state"]
        backends[identity] = value["spec"]["backend"]
        for task in value["tasks"]:
            tasks[(identity, task["task_id"])] = task
    return tasks, campaign_states, backends


def violations(world, profile, before, after):
    """The rules of CampaignWorker.tla, on the real journal after one step."""
    tasks, states, backends = after
    problems = []
    active = [key for key, task in tasks.items() if task["state"] in lifecycle.ACTIVE]
    for name, (identity, task_id, attempt) in world.names.items():
        task = tasks[(identity, task_id)]
        job = world.jobs.get(name)
        if (job or name in world.inflight) and attempt > task["attempt"]:
            problems.append(f"IntentBeforeSlurm: {name} has no recorded intent")
        if (job and job["state"] in LIVE) or name in world.inflight:
            if task["state"] not in lifecycle.ACTIVE or task["attempt"] != attempt:
                problems.append(f"SlurmWorkCounted: {task_id} attempt {attempt} can run in Slurm while the journal says "
                                f"{task['state']} attempt {task['attempt']}")
    gpus = sum(tasks[key]["spec"]["resources"]["gpu_count"] for key in active)
    if len(active) > profile["max_active_tasks"] or gpus > profile["max_active_gpus"]:
        problems.append(f"CapacityHeld: {len(active)} active tasks and {gpus} GPUs")
    for identity in ("c1", "c2"):
        mine = [key for key in active if key[0] == identity]
        limit = {"c1": 2, "c2": 1}[identity]
        if len(mine) > limit:
            problems.append(f"CapacityHeld: {identity} has {len(mine)} active tasks, max_concurrent {limit}")
    for qos, limit in profile["qos_limits"].items():
        under = [key[1] for key in active if (tasks[key]["spec"]["resources"].get("qos") or backends[key[0]]["qos"]) == qos]
        if len(under) > limit:
            problems.append(f"QosLimitHeld: {sorted(under)} active under QOS {qos}, limit {limit}")
    if len(active) > profile["account_limit"]:
        problems.append(f"AccountLimitHeld: {len(active)} active tasks, account job limit {profile['account_limit']}")
    old_tasks, old_states, _ = before
    for key, task in tasks.items():
        if task["attempt"] > old_tasks[key]["attempt"] and old_states[key[0]] != "accepted" and old_states[key[0]] != "running":
            problems.append(f"CancelFence: {key[1]} recorded a new intent after its campaign was {old_states[key[0]]}")
    return problems


def faulty(world, name, function):
    def wrapped(*args, **kwargs):
        world.fault(0.04)
        if world.faults and world.rng.random() < (0.35 if name == "record_submission" else 0.02):
            raise sqlite3.OperationalError("database is locked")
        value = function(*args, **kwargs)
        world.fault(0.04)
        return value
    return wrapped


def walk(seed, profile_name, tmp_path, monkeypatch):
    profile = PROFILES[profile_name]
    rng = random.Random(seed)
    world = World(rng)
    monkeypatch.setenv("UNITY_HPC_DATA", str(tmp_path / f"walk-{seed}"))
    source = tmp_path / f"walk-{seed}-source"
    source.mkdir()
    (source / "run.py").write_text("print('task')\n")

    def placement(resources, backend, observed=None, *, now=None):
        qos = resources.get("qos") or backend["qos"]
        return {"warnings": [], "selected_partitions": ["cpu"], "partitions": [], "qos": qos,
                "qos_limits": {"max_jobs": profile["qos_limits"][qos]}, "account_limits": {"max_submit_jobs": profile["account_limit"]}}

    monkeypatch.setattr(planner, "select", placement)
    monkeypatch.setattr(catalog, "load", lambda: {})
    campaigns.configure({"account": "pi_test", "remote_root": "/work/pi_test/controller", "retry_backoff_seconds": 1, "qos": "normal",
                         "max_active_tasks": profile["max_active_tasks"], "max_active_gpus": profile["max_active_gpus"]})
    base = {"schema_version": 1, "bundle": {"path": str(source)}, "max_attempts": 2}
    campaigns.create({**copy.deepcopy(base), "campaign_id": "c1", "max_concurrent": 2, "tasks": [gpu_task("a"), cpu_task("b", "long")]})
    campaigns.configure({"qos": "long"})
    campaigns.create({**copy.deepcopy(base), "campaign_id": "c2", "max_concurrent": 1, "tasks": [gpu_task("c")]})
    for name in WRITES:
        monkeypatch.setattr(store, name, faulty(world, name, getattr(store, name)))
    clock = Clock()
    for step in range(STEPS):
        before = journal()
        action = rng.choices(["tick", "slurm", "cancel"], weights=[6, 4, 1])[0]
        target = rng.choice(["c1", "c2"])
        world.log.append(f"{step}: {action}" + (f" {target}" if action == "cancel" else ""))
        world.faults = action != "slurm"
        try:
            if action == "tick":
                campaigns.tick(adapter=world, clock=clock)
            elif action == "cancel":
                campaigns.cancel(target, adapter=world)
            else:
                world.advance()
        except Crash:
            world.log.append("    the controller crashed")
        except Exception as exc:  # the Worker thread logs a failed pass and runs the next one
            world.log.append(f"    the step raised {type(exc).__name__}: {exc}")
        finally:
            world.faults = False
        clock.now += 1000
        problems = violations(world, profile, before, journal())
        if problems:
            return problems, world.log
    return [], world.log


def seeds():
    if SEED is not None:
        return [int(SEED)]
    return list(range(WALKS))


@pytest.mark.parametrize("seed", seeds())
def test_worker_walk_keeps_the_model_rules(seed, tmp_path, monkeypatch):
    profile = list(PROFILES)[seed % len(PROFILES)]
    problems, log = walk(seed, profile, tmp_path, monkeypatch)
    assert not problems, f"seed {seed} ({profile}): {problems[0]}\n" + "\n".join(log)
