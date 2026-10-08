"""Rank feasible partitions using measured history, without changing hardware.

Slurm remains the scheduler. Cached observations provide conservative fit and
queue estimates; they never justify waiting for a predicted quiet hour.
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timezone

from lib import paths
from controller.campaign_contract import CampaignError, validate, inventory


def seconds(value):
    if value is None or str(value).upper() in ("UNLIMITED", "INFINITE", "NONE", "N/A", ""):
        return None
    text = str(value)
    days, _, text = text.rpartition("-") if "-" in text else ("0", "", text)
    fields = [int(x) for x in text.split(":")]
    if len(fields) == 1:
        return int(days) * 86400 + fields[0] * 60
    if len(fields) == 2:
        fields.insert(0, 0)
    return int(days) * 86400 + fields[0] * 3600 + fields[1] * 60 + fields[2]


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


def catalog():
    location = paths.controller_dir() / "backend-catalog.json"
    try:
        return json.loads(location.read_text())
    except (OSError, ValueError):
        return {}


def historical_profile(partition, gpu_type):
    value = {"source": "local task_run accounting", "partition": partition, "hardware": gpu_type or "cpu", "sample_count": 0,
             "wait_p50_seconds": None, "wait_p95_seconds": None, "runtime_p95_seconds": None, "max_rss_p95_mb": None, "confidence": "unknown"}
    database = paths.summaries_db()
    if not database.is_file():
        return value
    try:
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as con:
            fields = {row[1] for row in con.execute("PRAGMA table_info(task_run)")}
            if not {"partition", "hardware", "wait_s", "elapsed_s", "state"} <= fields:
                return value
            rss = "max_rss_mb" if "max_rss_mb" in fields else "NULL"
            date_filter = " AND day_utc>=date('now','-30 days')" if "day_utc" in fields else ""
            rows = con.execute(f"SELECT wait_s,elapsed_s,{rss} FROM task_run WHERE partition=? AND hardware=? AND state='COMPLETED'{date_filter} ORDER BY rowid DESC LIMIT 500", (partition, gpu_type or "cpu")).fetchall()
        value["sample_count"] = len(rows)
        for index, key, frac in ((0, "wait_p50_seconds", .5), (0, "wait_p95_seconds", .95), (1, "runtime_p95_seconds", .95), (2, "max_rss_p95_mb", .95)):
            value[key] = _percentile([float(row[index]) for row in rows if row[index] is not None and float(row[index]) >= 0], frac)
        value["confidence"] = "measured aggregate; workload mismatch possible" if len(rows) >= 20 else "low sample count"
    except (sqlite3.Error, ValueError, TypeError):
        pass
    return value


def select(resources, settings, observed=None):
    observed = catalog() if observed is None else observed
    partitions = observed.get("partitions", {})
    default_partitions = settings.get("allowed_partitions") or ["gpu", "gpu-preempt"] if resources.get("gpu_count") else settings.get("cpu_partitions") or ["cpu"]
    candidates = resources.get("partitions") or default_partitions
    allowed = settings.get("allowed_partitions", []) if resources.get("gpu_count") else settings.get("cpu_partitions", [])
    qos_name = resources.get("qos") or settings.get("qos", "normal")
    qos = observed.get("qos", {}).get(qos_name, {})
    account = settings.get("account", "")
    required = set(filter(None, resources.get("constraint", "").split("&")))
    proposed = []
    age = None
    try:
        stamp = datetime.fromisoformat(observed.get("observed_at", "").replace("Z", "+00:00"))
        age = max(0, (datetime.now(timezone.utc) - stamp).total_seconds())
    except ValueError:
        pass
    warnings = []
    if age is None or age > settings.get("catalog_max_age_seconds", 3600):
        warnings.append("hardware and policy catalog is absent or stale; refresh the backend probe before dispatch")
    association = dict(observed.get("account", {}))
    if association.get("name") not in (None, account):
        association = {}
    if observed.get("associations"):
        # Blank user fields do not erase known account-wide ceilings from the
        # parent association survey.
        association.update({key: value for key, value in observed["associations"].get(account, {}).items() if value not in (None, "", [])})
    allowed_qos = association.get("qos", [])
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
        for expression in (association.get("grp_tres"), qos.get("max_tres_per_user"), qos.get("max_tres_per_job"), qos.get("max_tres_per_account")):
            limits = tres_limits(expression)
            for metric, requested in (("cpu", resources["cpus"]), ("node", 1), ("gres/gpu", resources.get("gpu_count", 0))):
                if metric in limits and requested > limits[metric]:
                    reasons.append(f"request exceeds known {metric} account/QOS limit")
        for bound in (entry.get("max_walltime_seconds"), qos.get("max_walltime_seconds"), association.get("max_walltime_seconds")):
            if bound is not None and resources["walltime_seconds"] > bound:
                reasons.append("requested walltime exceeds partition/account/QOS ceiling")
        fits = []
        requested_nodes = expand_nodes(resources.get("nodelist", ""))
        for node in observed.get("nodes", []):
            if name not in node.get("partitions", []) or not required <= set(node.get("features", [])):
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
        profile = historical_profile(name, resources.get("gpu_type"))
        proposed.append({"partition": name, "eligible": not reasons, "reasons": list(dict.fromkeys(reasons)), "matching_nodes": fits,
                         "history": profile, "preempt_mode": entry.get("preempt_mode"), "priority_tier": entry.get("priority_tier"),
                         "freshness_seconds": age, "estimated_queue_seconds": profile["wait_p50_seconds"]})
    proposed.sort(key=lambda p: (not p["eligible"], p["estimated_queue_seconds"] is None, p["estimated_queue_seconds"] or 0, -(p.get("priority_tier") or 0)))
    return {"partitions": proposed, "selected_partitions": [p["partition"] for p in proposed if p["eligible"]], "warnings": warnings,
            "account_limits": association, "qos_limits": qos, "qos": qos_name, "observed_at": observed.get("observed_at"),
            "gpu_utilization": None, "estimate_note": "Accounting wait percentiles describe prior workloads, not a guarantee. Submit now; Slurm backfill decides start time."}


def expand_nodes(expression):
    """Expand bounded Slurm nodelists without a controller-side shell call."""
    import re
    if not expression:
        return set()
    result = set()
    for token in re.findall(r"[^,\[\]]+(?:\[[^\]]+\])?", expression):
        match = re.fullmatch(r"([^\[]+)\[([^\]]+)\]", token)
        if not match:
            result.add(token)
            continue
        prefix, ranges = match.groups()
        for item in ranges.split(","):
            bounds = item.split("-")
            if len(bounds) == 1:
                result.add(prefix + bounds[0])
            elif len(bounds) == 2 and all(b.isdigit() for b in bounds):
                start, end = map(int, bounds)
                if end < start or end - start > 10000:
                    raise CampaignError("nodelist range exceeds 10000 nodes")
                result.update(prefix + str(i).zfill(len(bounds[0])) for i in range(start, end + 1))
            else:
                raise CampaignError("invalid nodelist expression")
    return result


def plan(raw, settings):
    specification = validate(raw)
    bundle = inventory(specification["bundle"])
    tasks = [{"task_id": task["task_id"], "model_class": task.get("model_class"), "resources": task["resources"],
              "placement": select(task["resources"], settings)} for task in specification["tasks"]]
    return {"schema_version": 1, "campaign_id": specification["campaign_id"], "bundle": bundle, "tasks": tasks,
            "ready": all(t["placement"]["selected_partitions"] and not t["placement"]["warnings"] for t in tasks),
            "max_concurrent": specification["max_concurrent"], "max_attempts": specification["max_attempts"]}
