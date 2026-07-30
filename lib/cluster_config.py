"""Deterministic, order-independent merge for the shared cluster-config.json.

Merge rules (SS6.2):
  - capacity counts (nodes, cpus_total, gpus_total, total_accessible) -> max
  - sets (lists) -> union (dicts-with-name union by name)
  - point-in-time scalars -> newest observed_utc wins
  - any field NOT present in the observation -> left untouched

Pure functions only. Neither argument is mutated. The locked write protocol
lives in write_config() (added in the next task). Stdlib only.
"""

from __future__ import annotations

import copy
import fcntl
import json
import os
from datetime import datetime, timezone

from lib import paths

SCHEMA_VERSION = 1
DEFAULT_TTL_SECONDS = 43200  # 12 hours

#: fields that merge by max wherever they appear inside a resource record
_MAX_FIELDS = frozenset({"nodes", "cpus_total", "gpus_total", "total_accessible"})

#: top-level map-of-record sections merged per resource id
_MAP_SECTIONS = ("partitions", "gpu_fleet", "storage")

# Slurm's GPU name is a resource key, not display text.  Keep the spelling that
# `%G`, `--gres`, and sacct use, while accepting names that have appeared in
# handwritten configuration and telemetry.  Add aliases here, rather than at
# individual reader call sites, so every config write folds the same keys.
GPU_ALIASES = {
    "rtx_8000": "rtx8000",
    "rtx-8000": "rtx8000",
    "titan_x": "titanx",
    "titan-x": "titanx",
}


def canonical_gpu_type(value: str) -> str:
    """Return the canonical Slurm GPU resource spelling for ``value``."""
    raw = str(value).strip().lower()
    lookup = raw.replace(" ", "_").replace("-", "_")
    return GPU_ALIASES.get(raw, GPU_ALIASES.get(lookup, raw))


def canonicalize_config(data: dict) -> dict:
    """Fold legacy GPU keys before a config merge or write.

    The original spelling remains in ``source_resource_ids`` when it differs,
    so diagnostics retain what a collector or an older config actually saw.
    """
    out = json.loads(json.dumps(data))
    fleet: dict = {}
    # Older stores used all three names below.  Fold them into gpu_fleet on
    # every write so an old orphan cannot reappear after a later merge.
    for section_name in ("gpu_fleet", "gpu_types", "gpu_capacity"):
        section = out.get(section_name) or {}
        if not isinstance(section, dict):
            continue
        for raw, record in section.items():
            canonical = canonical_gpu_type(raw)
            record = (dict(record or {}) if isinstance(record, dict)
                      else {"total_accessible": record})
            if canonical != raw:
                record["source_resource_ids"] = _union_list(
                    record.get("source_resource_ids") or [], [raw])
            fleet[canonical] = merge_resource(fleet.get(canonical) or {}, record)
    if any(key in out for key in ("gpu_fleet", "gpu_types", "gpu_capacity")):
        out["gpu_fleet"] = fleet
    out.pop("gpu_types", None)
    out.pop("gpu_capacity", None)
    for record in (out.get("partitions") or {}).values():
        if isinstance(record, dict) and isinstance(record.get("gpu_types"), list):
            record["gpu_types"] = _union_list(
                [], [canonical_gpu_type(item) for item in record["gpu_types"]])
    return out


def _union_by_name(a: list, b: list) -> list:
    by_name: dict = {}
    for item in list(a) + list(b):
        by_name[item.get("name")] = copy.deepcopy({**by_name.get(item.get("name"), {}), **item})
    return [by_name[k] for k in sorted(by_name, key=lambda x: (x is None, x))]


def _union_list(a: list, b: list) -> list:
    combined = list(a) + list(b)
    if combined and all(isinstance(x, dict) and "name" in x for x in combined):
        return _union_by_name(a, b)
    # scalar set union, deduped via canonical JSON, sorted (type, value) for determinism
    seen = {json.dumps(x, sort_keys=True) for x in combined}
    return sorted((json.loads(s) for s in seen), key=lambda x: (str(type(x)), x))


def merge_resource(cur: dict, obs: dict) -> dict:
    """Merge one resource record (a partition, gpu type, storage volume, or the
    fairshare scalar block). Newness is decided by observed_utc."""
    out = dict(cur)
    obs_utc = obs.get("observed_utc")
    cur_utc = cur.get("observed_utc")
    newer = obs_utc is not None and (cur_utc is None or obs_utc >= cur_utc)
    for k, v in obs.items():
        if k in _MAX_FIELDS and isinstance(v, (int, float)) and not isinstance(v, bool):
            prev = cur.get(k)
            out[k] = max(v, prev) if isinstance(prev, (int, float)) and not isinstance(prev, bool) else v
        elif isinstance(v, list):
            out[k] = _union_list(cur.get(k) or [], v)
        elif k == "observed_utc":
            out[k] = obs_utc if newer else cur_utc
        else:
            if newer or k not in out:
                out[k] = copy.deepcopy(v)
    return out


def _merge_account_limits(cur: dict, obs: dict) -> dict:
    """Newest-observed_utc-wins for the scalar fields (max_submit_jobs, max_jobs,
    max_wall, grp_tres, ...), the same mechanism merge_resource uses for resources.
    The qos list always unions by name, regardless of which side is newer."""
    out = dict(cur)
    obs_utc = obs.get("observed_utc")
    cur_utc = cur.get("observed_utc")
    newer = obs_utc is not None and (cur_utc is None or obs_utc >= cur_utc)
    for k, v in obs.items():
        if k == "qos":
            out["qos"] = _union_by_name(cur.get("qos") or [], v)
        elif k == "observed_utc":
            out[k] = obs_utc if newer else cur_utc
        elif v is not None and (newer or k not in out):
            out[k] = copy.deepcopy(v)
    return out


def _merge_provenance(cur: dict, obs: dict) -> dict:
    """Provenance is INTENTIONALLY last-write: last_write_utc/last_writer must
    record the actual most-recent write (not the newest observed_utc), so this
    section is not order-independent by design. writers_seen is a union."""
    out = dict(cur)
    seen = set(cur.get("writers_seen") or []) | set(obs.get("writers_seen") or [])
    for k, v in obs.items():
        if k != "writers_seen" and v is not None:
            out[k] = copy.deepcopy(v)
    out["writers_seen"] = sorted(seen)
    return out


def merge_config(current: dict, observation: dict) -> dict:
    """Merge one observation into the current config. Pure: neither argument is
    mutated, and no value from `observation` is aliased into the result.

    Order-independence holds for capacity (max), sets (union), and
    observed_utc-timestamped sections (resources, account_limits); provenance
    is deliberately last-write; cluster-invariant scalars (slurm_version,
    sacct_scope, cluster) are the same for every observer.
    """
    out = canonicalize_config(current)
    observation = canonicalize_config(observation)
    for k, v in observation.items():
        if k in _MAP_SECTIONS:
            section = dict(out.get(k) or {})
            for rid, rec in v.items():
                if k == "gpu_fleet":
                    rid = canonical_gpu_type(rid)
                section[rid] = merge_resource(section.get(rid) or {}, rec)
            out[k] = section
        elif k == "account_limits":
            out[k] = _merge_account_limits(out.get(k) or {}, v)
        elif k == "fairshare":
            out[k] = merge_resource(out.get(k) or {}, v)
        elif k == "provenance":
            out[k] = _merge_provenance(out.get(k) or {}, v)
        elif isinstance(v, list):
            out[k] = _union_list(out.get(k) or [], v)
        elif v is not None:
            out[k] = copy.deepcopy(v)
    return out


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


#: sections that make a config substantive; a config carrying none of them
#: (e.g. freshly seeded with only schema_version/cluster/provenance, or an
#: empty/corrupt file) has no recon-worthy content regardless of its mtime.
_SUBSTANTIVE_SECTIONS = ("partitions", "gpu_fleet", "account_limits")


def should_probe(ttl_seconds: int, *, force: bool = False) -> bool:
    """Return False iff the config exists, parses, carries at least one
    substantive section, and is younger than ttl_seconds, and not forced.

    A missing file, unparseable JSON, or a config with none of
    partitions/gpu_fleet/account_limits (an empty `{}` or a stub) must not
    suppress recon until the TTL expires on mtime alone — there is nothing
    fresh to protect, so a probe is always needed regardless of age.
    """
    if force:
        return True
    p = paths.config_path()
    if not p.exists():
        return True
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return True
    if not isinstance(data, dict) or not any(data.get(k) for k in _SUBSTANTIVE_SECTIONS):
        return True
    age = datetime.now(timezone.utc).timestamp() - p.stat().st_mtime
    return age >= ttl_seconds


def _atomic_write(path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def write_config(observation: dict, *, writer: str, force: bool = False,
                 ttl_seconds: int = DEFAULT_TTL_SECONDS) -> tuple[str, dict]:
    """flock + read-merge-write + atomic rename. Returns (status, config)."""
    lock_path = paths.config_lock()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path = paths.config_path()

    with open(lock_path, "w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            # TTL is evaluated inside the lock so concurrent writers agree.
            if not force and cfg_path.exists():
                age = datetime.now(timezone.utc).timestamp() - cfg_path.stat().st_mtime
                if age < ttl_seconds:
                    return "skipped", json.loads(cfg_path.read_text())

            current = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
            current.setdefault("schema_version", SCHEMA_VERSION)
            current.setdefault("cluster", "unity")

            merged = merge_config(current, observation)
            prov = _merge_provenance(
                merged.get("provenance") or {},
                {"last_write_utc": _now_iso(), "last_writer": writer,
                 "writers_seen": [writer]})
            merged["provenance"] = prov

            _atomic_write(cfg_path, json.dumps(merged, indent=2, sort_keys=True) + "\n")
            return "written", merged
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
