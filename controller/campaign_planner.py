"""Rank feasible partitions using measured history, without changing hardware.

Slurm remains the scheduler. Cached observations provide conservative fit and
queue estimates; they never justify waiting for a predicted quiet hour.
"""

from __future__ import annotations

import math
import sqlite3
import time

from lib import telemetry_archive
from lib.cluster_config import canonical_gpu_type
from controller import catalog
from controller.campaign_contract import expand_nodes, inventory, validate


def _percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def tres_limits(expression):
    """Return only numeric CPU/node/GPU ceilings; unknown policy stays unknown."""
    values = {}
    for token in str(expression or "").split(","):
        name, _, value = token.partition("=")
        if name in ("cpu", "node", "gres/gpu") and value.isdigit():
            values[name] = int(value)
    return values


def _history_hardware(gpu_type):
    """The archive's hardware key for a request: the canonical GPU name, or `cpu`."""
    if isinstance(gpu_type, str) and gpu_type:
        return canonical_gpu_type(gpu_type)
    return gpu_type or "cpu"


def historical_profile(partition, gpu_type):
    hardware = _history_hardware(gpu_type)
    value = {"source": "local task_run accounting", "partition": partition, "hardware": hardware, "sample_count": 0,
             "wait_p50_seconds": None, "wait_p95_seconds": None, "runtime_p95_seconds": None, "max_rss_p95_mb": None, "confidence": "unknown"}
    try:
        rows = telemetry_archive.completed_runs(partition, hardware)
        if rows is None:
            return value
        value["sample_count"] = len(rows)
        for index, key, frac in ((0, "wait_p50_seconds", .5), (0, "wait_p95_seconds", .95), (1, "runtime_p95_seconds", .95), (2, "max_rss_p95_mb", .95)):
            value[key] = _percentile([float(row[index]) for row in rows if row[index] is not None and float(row[index]) >= 0], frac)
        value["confidence"] = "measured aggregate; workload mismatch possible" if len(rows) >= 20 else "low sample count"
    except (sqlite3.Error, ValueError, TypeError):
        pass
    return value


def _profile(partition, gpu_type, profiles):
    """historical_profile; with a plan request's `profiles`, read once per partition and history
    hardware key. A CPU task's gpu_type is not validated, so a key that is not text is read each time."""
    hardware = _history_hardware(gpu_type)
    if profiles is None or not isinstance(hardware, str):
        return historical_profile(partition, gpu_type)
    if (partition, hardware) not in profiles:
        profiles[partition, hardware] = historical_profile(partition, gpu_type)
    return dict(profiles[partition, hardware])


UNREAD = object()  # "read the stored Catalog"; a loaded document can itself be null


def qos_for(resources, settings):
    """The QOS a task runs under: its resources.qos, else the settings' (a campaign's frozen backend) qos."""
    return resources.get("qos") or settings.get("qos", "normal")


def nodes_by_partition(observed):
    """Each partition's Catalog nodes in Catalog order; a node is listed once per partition."""
    groups = {}
    for node in observed.get("nodes", []):
        for name in dict.fromkeys(node.get("partitions", [])):
            groups.setdefault(name, []).append(node)
    return groups


def select(resources, settings, observed=UNREAD, *, now=None, partition_nodes=None, profiles=None):
    """Rank the candidate partitions for one task. `partition_nodes` is nodes_by_partition(observed);
    a plan request groups its Catalog once and passes it for every task, with one `profiles` dict
    that keeps the history read for each partition and hardware key during that request."""
    observed = catalog.load() if observed is UNREAD else observed
    now = time.time() if now is None else now
    partitions = observed.get("partitions", {})
    default_partitions = settings.get("allowed_partitions") or ["gpu", "gpu-preempt"] if resources.get("gpu_count") else settings.get("cpu_partitions") or ["cpu"]
    candidates = resources.get("partitions") or default_partitions
    allowed = settings.get("allowed_partitions", []) if resources.get("gpu_count") else settings.get("cpu_partitions", [])
    qos_name = qos_for(resources, settings)
    qos = observed.get("qos", {}).get(qos_name, {})
    account = settings.get("account", "")
    required = set(filter(None, resources.get("constraint", "").split("&")))
    proposed = []
    age = catalog.age(observed, now)
    warnings = []
    if not catalog.is_fresh(observed, settings.get("catalog_max_age_seconds", 3600), now):
        warnings.append("hardware and policy catalog is absent or stale; refresh the backend probe before dispatch")
    association = dict(observed.get("account", {}))
    if association.get("name") not in (None, account):
        association = {}
    if observed.get("associations"):
        # Blank user fields do not erase known account-wide ceilings from the
        # parent association survey.
        association.update({key: value for key, value in observed["associations"].get(account, {}).items() if value not in (None, "", [])})
    allowed_qos = association.get("qos", [])
    requested_nodes = expand_nodes(resources.get("nodelist", ""))
    partition_nodes = nodes_by_partition(observed) if partition_nodes is None else partition_nodes
    for name in dict.fromkeys(candidates):
        reasons = []
        entry = partitions.get(name)
        if allowed and name not in allowed:
            reasons.append("partition outside controller allowlist")
        if not entry:
            reasons.append("partition policy has not been verified")
            entry = {}
        if entry.get("state", "UP").upper() != "UP":
            reasons.append("partition is down")
        for field, who in (("allow_accounts", account), ("allow_qos", qos_name)):
            members = entry.get(field, [])
            if members and "ALL" not in members and who not in members:
                reasons.append(f"{field} excludes request")
        if account in entry.get("deny_accounts", []):
            reasons.append("account is denied")
        if qos_name in entry.get("deny_qos", []):
            reasons.append("QOS is denied")
        groups = entry.get("allow_groups", [])
        if groups and "ALL" not in groups and not set(groups).intersection(observed.get("groups", [])):
            reasons.append("partition group restriction excludes current SSH user")
        if allowed_qos and qos_name not in allowed_qos:
            reasons.append("QOS is not allowed for this account")
        for expression in (association.get("grp_tres"), qos.get("max_tres_per_user")):
            limits = tres_limits(expression)
            for metric, requested in (("cpu", resources["cpus"]), ("node", 1), ("gres/gpu", resources.get("gpu_count", 0))):
                if metric in limits and requested > limits[metric]:
                    reasons.append(f"request exceeds known {metric} account/QOS limit")
        for bound in (entry.get("max_walltime_seconds"), qos.get("max_walltime_seconds"), association.get("max_walltime_seconds")):
            if bound is not None and resources["walltime_seconds"] > bound:
                reasons.append("requested walltime exceeds partition/account/QOS ceiling")
        fits = []
        for node in partition_nodes.get(name, []):
            if not required <= set(node.get("features", [])):
                continue
            if requested_nodes and node["name"] not in requested_nodes:
                continue
            if node.get("cpus", 0) < resources["cpus"] or node.get("memory_mb", 0) < resources["memory_mb"]:
                continue
            if resources.get("gpu_count") and node.get("gpus", {}).get(resources.get("gpu_type"), 0) < resources["gpu_count"]:
                continue
            fits.append(node["name"])
        if not fits:
            reasons.append("no verified node fits the exact features, GPU type/count, CPU, and memory request")
        if entry.get("preempt_mode", "OFF") != "OFF" and not settings.get("allow_preemptible", True):
            reasons.append("preemptible partitions disabled by controller policy")
        profile = _profile(name, resources.get("gpu_type"), profiles)
        proposed.append({"partition": name, "eligible": not reasons, "reasons": list(dict.fromkeys(reasons)), "matching_nodes": fits,
                         "history": profile, "preempt_mode": entry.get("preempt_mode"), "priority_tier": entry.get("priority_tier"),
                         "freshness_seconds": age, "estimated_queue_seconds": profile["wait_p50_seconds"]})
    proposed.sort(key=lambda p: (not p["eligible"], p["estimated_queue_seconds"] is None, p["estimated_queue_seconds"] or 0, -(p.get("priority_tier") or 0)))
    return {"partitions": proposed, "selected_partitions": [p["partition"] for p in proposed if p["eligible"]], "warnings": warnings,
            "account_limits": association, "qos_limits": qos, "qos": qos_name, "observed_at": observed.get("observed_at"),
            "gpu_utilization": None, "estimate_note": "Accounting wait percentiles describe prior workloads, not a guarantee. Submit now; Slurm backfill decides start time."}


def plan(raw, settings):
    specification = validate(raw)
    bundle = inventory(specification["bundle"])
    observed = catalog.load()
    partition_nodes, profiles = nodes_by_partition(observed), {}
    tasks = [{"task_id": task["task_id"], "model_class": task.get("model_class"), "resources": task["resources"],
              "placement": select(task["resources"], settings, observed, partition_nodes=partition_nodes, profiles=profiles)}
             for task in specification["tasks"]]
    return {"schema_version": 1, "campaign_id": specification["campaign_id"], "bundle": bundle, "tasks": tasks,
            "ready": all(t["placement"]["selected_partitions"] and not t["placement"]["warnings"] for t in tasks),
            "max_concurrent": specification["max_concurrent"], "max_attempts": specification["max_attempts"]}
