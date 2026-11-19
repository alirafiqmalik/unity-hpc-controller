"""The Catalog: the controller's timestamped record of live nodes, partitions, access
rules, QOS limits, and fairshare.

This module turns the survey output into a Catalog, stores it in backend-catalog.json,
reads it, decides freshness at a wall time the caller passes, and decides when a refresh
is due at a monotonic time the caller passes. The survey itself is SlurmAdapter.probe:
bounded Slurm queries over Cluster access.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone

from lib import paths

REFRESH_SECONDS = 900


def path():
    return paths.controller_dir() / "backend-catalog.json"


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


def _count(text):
    return int(text) if text.isdigit() else None


def parse(text, account):
    """Turn the survey output into a Catalog."""
    value = {"observed_at": datetime.now(timezone.utc).isoformat(), "nodes": [], "partitions": {}, "qos": {}, "associations": {}, "groups": [], "account": {"name": account}, "source": "bounded SSH Slurm commands"}
    section = ""
    for line in text.splitlines():
        if line in ("NODES", "PARTITIONS", "QOS", "ASSOCIATIONS", "ACCOUNT_LIMITS", "GROUPS", "FAIRSHARE"):
            section = line
            continue
        # NODES and PARTITIONS lines are key=value words; the other sections are '|' rows.
        fields = dict(re.findall(r"(?:^|\s)([A-Za-z][A-Za-z0-9_]*)=([^\s]*)", line)) if section in ("NODES", "PARTITIONS") else {}
        row = line.split("|")
        if section == "NODES" and "NodeName" in fields:
            gpus = {name: int(count) for name, count in re.findall(r"gpu:([^:,()]+):(\d+)", fields.get("Gres", ""))}
            value["nodes"].append({"name": fields["NodeName"], "cpus": int(fields.get("CPUTot", 0)), "memory_mb": int(fields.get("RealMemory", 0)), "features": fields.get("ActiveFeatures", "").split(","), "partitions": fields.get("Partitions", "").split(","), "gpus": gpus, "state": fields.get("State"), "alloc_tres": fields.get("AllocTRES"), "free_memory_mb": _count(fields.get("FreeMem", ""))})
        elif section == "PARTITIONS" and "PartitionName" in fields:
            value["partitions"][fields["PartitionName"]] = {"state": fields.get("State"), "max_walltime_seconds": seconds(fields.get("MaxTime")), "priority_tier": int(fields.get("PriorityTier", 0)), "preempt_mode": fields.get("PreemptMode", "OFF"), **{key: fields.get(source, "").split(",") if fields.get(source) not in (None, "(null)", "") else [] for key, source in (("allow_accounts", "AllowAccounts"), ("deny_accounts", "DenyAccounts"), ("allow_groups", "AllowGroups"), ("allow_qos", "AllowQos"), ("deny_qos", "DenyQos"))}}
        elif section == "QOS" and len(row) >= 5:
            value["qos"][row[0]] = {"max_walltime_seconds": seconds(row[1]), "max_jobs": _count(row[2]), "max_submit_jobs": _count(row[3]), "max_tres_per_user": row[4] or None}
        elif section == "ASSOCIATIONS" and len(row) >= 6:
            value["associations"][row[0]] = {"qos": row[1].split(","), "max_jobs": _count(row[2]), "max_submit_jobs": _count(row[3]), "grp_tres": row[4] or None, "max_walltime_seconds": seconds(row[5])}
            if row[0] == account:
                value["account"].update(value["associations"][row[0]])
        elif section == "ACCOUNT_LIMITS" and len(row) >= 5 and row[0] == account and not row[1]:
            value["account"].update(grp_tres=row[2] or None, grp_jobs=_count(row[3]), grp_submit_jobs=_count(row[4]))
        elif section == "GROUPS":
            value["groups"] = line.split()
        elif section == "FAIRSHARE" and len(row) >= 4 and row[0] == account:
            value["fairshare"] = {"factor": float(row[2]) if row[2] else None, "effective_usage": float(row[3]) if row[3] else None}
    return value


def refresh(adapter):
    """Survey the cluster through the adapter, store the Catalog, and return it.
    A failed survey raises and leaves the stored Catalog as it was."""
    value = adapter.probe()
    _save(value)
    return value


def load():
    """The stored Catalog, or {} when the file is absent or unreadable."""
    try:
        return json.loads(path().read_text())
    except (OSError, ValueError):
        return {}


def age(value, now):
    """Seconds since the Catalog was observed, at wall time `now` (epoch seconds); never
    negative. None when it has no timezone-aware ISO `observed_at`."""
    stamp = value.get("observed_at") if isinstance(value, dict) else None
    if not isinstance(stamp, str):
        return None
    try:
        observed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if observed.tzinfo is None:
        return None
    return max(0, (datetime.fromtimestamp(now, timezone.utc) - observed).total_seconds())


def is_fresh(value, max_age_seconds, now):
    """True when the Catalog is at most max_age_seconds old at wall time `now`."""
    current = age(value, now)
    return current is not None and current <= max_age_seconds


class RefreshSchedule:
    """When the Worker refreshes the Catalog, in monotonic seconds. The first claim at or
    after `start` is due; each due claim sets the next one REFRESH_SECONDS later, also
    when that refresh then fails, so a broken survey cannot run on every pass."""

    def __init__(self, start):
        self.due = start

    def claim(self, now):
        if now < self.due:
            return False
        self.due = now + REFRESH_SECONDS
        return True


def _save(value):
    """Atomic write: same bytes, mode, and temp-name pattern as campaigns._write_json."""
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        temp.chmod(0o600)
        os.replace(temp, target)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
