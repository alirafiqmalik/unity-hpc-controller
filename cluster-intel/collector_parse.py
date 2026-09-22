#!/usr/bin/env python3
"""Pure record construction for the Unity telemetry collector.

Runs ON THE CLUSTER, invoked by collector.sh with recorded command output on
files. Self-contained: stdlib only, NO import of the plugin's lib package (it is
not shipped to the cluster). Every function is a pure transform so the logic is
tested against fixtures without cluster access (§12).

DEFERRED / BEST-EFFORT §6.3 FIELDS — the parser itself never fabricates
values; some fields below are now best-effort enriched by collector.sh
(present when the underlying command yields them, ``None``/absent
otherwise) rather than unconditionally deferred:

- ``partition.access`` (open vs PI-restricted tier): best-effort enriched by
  collector.sh, honest-or-``None`` — present only when the source command
  yields it, never fabricated.
- ``gpu_type.pending`` (pending work broken down by GPU type): read from
  ``unity-slurm-gpu-usage`` when that wrapper reports it (the scheduler's
  own per-type count), otherwise gap-filled by collector.sh from a squeue
  tally of pending JOBS. Honest-or-absent — present only when one of those
  sources yields it, never fabricated, and the weaker tally never
  overwrites the wrapper's reading.

``gpu_type`` records themselves come from ``unity-slurm-gpu-usage``
(``parse_gpu_types``) when it produces output, and otherwise from the
MEASURED per-node GRES the same sample already collects
(``gpu_types_from_nodes``). Neither path invents a reading: with no usable
source, no ``gpu_type`` record is emitted at all.
- ``task_runs.used.cpu_eff_pct`` / ``.mem_eff_pct``: best-effort enriched by
  collector.sh (``seff`` output), honest-or-``None`` — present only when the
  source command yields it, never fabricated.
- ``task_runs.project`` / ``.skill`` / ``.campaign``: sacct has no notion of
  these; they are our own job-naming convention. Still deferred — needs
  either the tags encoded into the sacct ``JobName`` (``%j``) with a
  parseable delimiter, or a side-channel manifest keyed by job_id that
  collector.sh writes alongside the sacct dump.
- ``events.jsonl`` ``job_end`` / ``preemption`` events: only
  ``node_state_change`` is emitted by ``diff_node_events`` today. Still
  deferred — needs a sacct-delta parser (job present in today's sacct but
  not in the previous sample, or a state transition into PREEMPTED) — not
  implemented in this pass; not fabricated.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

_GPU_IN_GRES = re.compile(r"gpu:([a-z0-9_]+):(\d+)", re.I)
_GPU_LINE = re.compile(r"^\s*([a-z0-9_]+)\s+(\d+)\s*/\s*(\d+)", re.I)
# The deployed `unity-slurm-gpu-usage` prints ONE entry per line:
#   " h100         [##################] 8/8          1         80        9.0     "
# The `[####...]` progress bar is OPTIONAL — the `unknown` pseudo-row has no
# bar and no alloc/total either (a bare pending count), which is exactly why
# it (and the `any` aggregate row) never match this pattern and are skipped.
_GPU_ENTRY = re.compile(
    r"^\s*([a-z0-9][a-z0-9_]*)\s+(?:\[[#\s]*\]\s+)?(\d+)\s*/\s*(\d+)\s+"
    r"(\d+)\s+(\d+(?:,\d+)*)\s+(\d+(?:\.\d+)?)\s*$", re.I | re.M)
_VRAM = re.compile(r"(\d+)\s*GB", re.I)
_CC = re.compile(r"cc\s*([0-9.]+)", re.I)
_PSEUDO_TYPES = frozenset({"any", "unknown"})
# Kept in step with lib/cluster_config.canonical_gpu_type by
# tests/test_collector_parse.py. This copy exists because the collector runs on
# the cluster with no access to the plugin's lib/.
_GPU_SEPARATOR = re.compile(r"[ _-]+")
_GPU_SUFFIXES = frozenset({"ti", "x"})
_GPU_ALIASES: dict[str, str] = {}
_TRES_GPU = re.compile(r"gres/gpu:([a-z0-9_]+)=(\d+)", re.I)
_TRES_GPU_PLAIN = re.compile(r"gres/gpu=(\d+)", re.I)
_TRES_CPU = re.compile(r"(?:^|,)cpu=(\d+)")
_TRES_MEM = re.compile(r"(?:^|,)mem=(\d+(?:\.\d+)?)([KMGT]?)")
_MEM_MB = {"K": 1 / 1024, "M": 1.0, "G": 1024.0, "T": 1024.0 * 1024, "": 1.0}


def canonical_gpu_type(value: str) -> str:
    """Canonical Slurm GPU resource spelling, kept self-contained for Unity.

    Folds a separator only before digits or a short model suffix, so `1080_ti`
    and `rtx_8000` reach their gres spelling while `h200_nvl`, which is a real
    gres name, keeps its own. Partition names never reach this function."""
    parts = _GPU_SEPARATOR.split(str(value).strip().lower())
    folded = parts[0]
    for part in parts[1:]:
        joiner = "" if (part.isdigit() or part in _GPU_SUFFIXES) else "_"
        folded += joiner + part
    return _GPU_ALIASES.get(folded, folded)


def _cpu_fields(c: str) -> tuple[int, int]:
    """From alloc/idle/other/total -> (alloc, total)."""
    parts = c.split("/")
    if len(parts) == 4:
        try:
            return int(parts[0]), int(parts[3])
        except ValueError:
            return 0, 0
    return 0, 0


def _gpu_types_from_gres(gres: str) -> list[str]:
    return sorted({canonical_gpu_type(m.group(1)) for m in _GPU_IN_GRES.finditer(gres or "")})


def _gpu_count_from_gres(gres: str) -> int:
    """Sum all gpu:<type>:<n> counts in a gres string, e.g. 'gpu:a100:4' -> 4."""
    return sum(int(m.group(2)) for m in _GPU_IN_GRES.finditer(gres or ""))


def parse_partitions(text: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        f = line.split("|")
        if len(f) < 5:
            continue
        name, _avail, nodes, cpu, gres = f[0], f[1], f[2], f[3], f[4]
        alloc, total = _cpu_fields(cpu)
        try:
            nodes_total = int(nodes)
        except ValueError:
            nodes_total = 0
        out[name] = {"cpus_total": total, "cpus_alloc": alloc,
                     "nodes_total": nodes_total,
                     "gpu_types": _gpu_types_from_gres(gres)}
    return out


def parse_pending(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        part = line.split("|", 1)[0]
        out[part] = out.get(part, 0) + 1
    return out


def _gpu_counts_by_type(gres: str) -> dict[str, int]:
    """Per-type GPU counts in a gres string: 'gpu:a100:4,gpu:l40s:2' ->
    {'a100': 4, 'l40s': 2}."""
    out: dict[str, int] = {}
    for m in _GPU_IN_GRES.finditer(gres or ""):
        t = canonical_gpu_type(m.group(1))
        out[t] = out.get(t, 0) + int(m.group(2))
    return out


def parse_gpu_types(text: str) -> list[dict]:
    """Parse `unity-slurm-gpu-usage` output into gpu_type records.

    Handles the real wrapper layout, captured live: one `type [bar]?
    alloc/total pending vram cc` entry per line, the `[####...]` progress bar
    OPTIONAL and the vram column sometimes a comma list (e.g. a100's
    "80,40" — the type is offered in more than one VRAM size). Degrades to a
    lenient one-entry-per-line `type alloc/total ... NNGB ... cc N.N` read
    when a line does not carry the full column set.

    The `any`/`unknown` pseudo-rows are fleet-wide aggregates, not GPU
    types, and are always skipped — `unknown` has no alloc/total column at
    all so it never matches in the first place, and `any` is dropped by
    name. A data row's vram/cc are bare numerics; a `0` there means the
    wrapper had no real reading, never a fabricated 0 GB / 0.0 CC (§8), so it
    is recorded as no value rather than folded into the merge set.

    A type listed on more than one row (or with more than one comma-joined
    vram value on the SAME row) is merged: counts SUM, while
    vram/compute-capability are kept only when every value agrees — a
    disagreement (or an honest no-value) yields no field at all rather than
    an invented representative value (§8 honesty).
    """
    acc: dict[str, dict] = {}

    def add(raw_rid, alloc, total, pending=None, vram_values=(), cc=None):
        rid = canonical_gpu_type(raw_rid)
        a = acc.setdefault(rid, {"alloc": 0, "total": 0, "pending": None,
                                 "vram": set(), "cc": set(), "raw": set()})
        a["raw"].add(raw_rid.lower())
        a["alloc"] += alloc
        a["total"] += total
        if pending is not None:
            a["pending"] = (a["pending"] or 0) + pending
        for v in vram_values:
            if v:
                a["vram"].add(v)
            else:
                a["vram"].add(None)
        if cc:
            a["cc"].add(cc)
        elif cc is not None:
            a["cc"].add(None)

    for line in text.splitlines():
        m = _GPU_ENTRY.match(line)
        if m:
            rid = m.group(1).lower()
            if rid in _PSEUDO_TYPES:
                continue
            vram_values = [int(v) for v in m.group(5).split(",")]
            add(rid, int(m.group(2)), int(m.group(3)),
                pending=int(m.group(4)), vram_values=vram_values,
                cc=float(m.group(6)))
            continue
        m = _GPU_LINE.match(line)
        if not m or m.group(1).lower() in _PSEUDO_TYPES:
            continue
        vram = _VRAM.search(line)
        cc = _CC.search(line)
        add(m.group(1).lower(), int(m.group(2)), int(m.group(3)),
            vram_values=[int(vram.group(1))] if vram else [],
            cc=float(cc.group(1)) if cc else None)

    out = []
    for rid in sorted(acc):
        a = acc[rid]
        rec = {"kind": "gpu_type", "resource_id": rid,
               "alloc": a["alloc"], "total": a["total"], "source": "gpu_usage"}
        if a["raw"] != {rid}:
            rec["source_resource_ids"] = sorted(a["raw"])
        if a["pending"] is not None:
            rec["pending"] = a["pending"]
        if len(a["vram"]) == 1:
            v = next(iter(a["vram"]))
            if v is not None:
                rec["vram_gb"] = v
        if len(a["cc"]) == 1:
            c = next(iter(a["cc"]))
            if c is not None:
                rec["compute_capability"] = c
        out.append(rec)
    return out


def gpu_types_from_nodes(nodes_text: str) -> list[dict]:
    """Derive gpu_type records by aggregating MEASURED per-node GRES.

    Fallback source for when `unity-slurm-gpu-usage` yields nothing (the
    wrapper is not on the non-interactive PATH, times out, or prints an
    unparseable banner). Same 8-field rows ``parse_nodes`` consumes, so the
    alloc/total are the very GresUsed/Gres readings already recorded per node
    — measured, never derived from a total.

    Honesty guard (§8), mirroring ``parse_nodes``: a node whose ``gres_alloc``
    is EMPTY (no real GresUsed reading) contributes to NEITHER alloc nor
    total, so the ratio stays a true measurement over the measured subset
    instead of counting unknown nodes as 0-allocated. Types no node measured
    are simply absent — never emitted at a fabricated 0%.
    """
    total: dict[str, int] = {}
    alloc: dict[str, int] = {}
    for line in nodes_text.splitlines():
        f = line.strip().split("|")
        if len(f) < 8:
            continue
        gres_total, gres_alloc = f[6], f[7].strip()
        if not gres_alloc:
            continue
        for t, n in _gpu_counts_by_type(gres_total).items():
            total[t] = total.get(t, 0) + n
        for t, n in _gpu_counts_by_type(gres_alloc).items():
            alloc[t] = alloc.get(t, 0) + n
    return [{"kind": "gpu_type", "resource_id": t, "alloc": alloc.get(t, 0),
             "total": total[t], "source": "node_gres"}
            for t in sorted(total) if total[t]]


def parse_nodes(text: str) -> list[dict]:
    """Parse per-node sinfo output: partition|name|state|cpu|mem_total|
    mem_free|gres_total|gres_alloc (8 pipe fields), sourced by collector.sh
    from real ``sinfo -O`` ``FreeMem``/``GresUsed`` columns. ``gres_total``/
    ``gres_alloc`` are gres-format strings (e.g. 'gpu:a100:4' / 'gpu:a100:3')
    giving configured vs. currently-allocated GRES per node, analogous to how
    ``cpu`` already reports alloc/idle/other/total.

    Honesty contract (§8): ``mem_free``/``gres_alloc`` are MEASURED values,
    never derived from the totals. When collector.sh could not source a real
    reading (sinfo's FreeMem prints "N/A", or GresUsed is blank/unparseable),
    it emits that field EMPTY rather than falling back to the total. An empty
    ``mem_free`` yields ``mem_mb_free: None``; an empty ``gres_alloc`` yields
    ``gpus_idle: None`` (we cannot say how many are idle without knowing how
    many are allocated) — never a fabricated 100%-free / 0%-busy reading.
    """
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        f = line.split("|")
        if len(f) < 8:
            continue
        (partition, name, state, cpu, mem_total, mem_free,
         gres_total, gres_alloc) = f[:8]
        alloc, total = _cpu_fields(cpu)
        try:
            mem_mb = int(mem_total)
        except ValueError:
            mem_mb = 0
        mem_free = mem_free.strip()
        mem_free_mb = int(mem_free) if mem_free.isdigit() else None
        gpus_total = _gpu_count_from_gres(gres_total)
        gres_alloc = gres_alloc.strip()
        if gres_alloc:
            gpus_alloc = _gpu_count_from_gres(gres_alloc)
            gpus_idle = max(gpus_total - gpus_alloc, 0)
        else:
            gpus_idle = None
        out.append({"kind": "node", "resource_id": name, "partition": partition,
                    "state": state, "cpus_total": total, "cpus_idle": total - alloc,
                    "mem_mb_total": mem_mb, "mem_mb_free": mem_free_mb,
                    "gpu_types": _gpu_types_from_gres(gres_total),
                    "gpus_total": gpus_total,
                    "gpus_idle": gpus_idle})
    return sorted(out, key=lambda r: r["resource_id"])


def diff_node_events(prev: dict[str, str], cur: dict[str, str], ts: str) -> list[dict]:
    out = []
    for node in sorted(cur):
        if node in prev and prev[node] != cur[node]:
            out.append({"ts": ts, "event": "node_state_change",
                        "resource_id": node, "from": prev[node], "to": cur[node]})
    return out


def _parse_elapsed(s: str) -> int:
    s = (s or "").strip()
    if not s:
        return 0
    days = 0
    if "-" in s:
        d, _, s = s.partition("-")
        days = int(d)
    parts = [int(p) for p in s.split(":")] if s else [0]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, sec = parts[-3], parts[-2], parts[-1]
    return days * 86400 + h * 3600 + m * 60 + sec


def _parse_mem_mb(s: str) -> float | None:
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([KMGT]?)", s or "")
    if not m:
        return None
    return round(float(m.group(1)) * _MEM_MB[m.group(2)], 3)


def _parse_tres(tres: str) -> tuple[str | None, dict]:
    tres = tres or ""
    gt = _TRES_GPU.search(tres)
    if gt:
        gpu_type, gpus = canonical_gpu_type(gt.group(1)), int(gt.group(2))
    else:
        p = _TRES_GPU_PLAIN.search(tres)
        gpu_type, gpus = (None, int(p.group(1))) if p else (None, 0)
    cpu = _TRES_CPU.search(tres)
    mem = _TRES_MEM.search(tres)
    req = {"cpus": int(cpu.group(1)) if cpu else 0}
    if mem:
        req["mem_mb"] = int(round(float(mem.group(1)) * _MEM_MB[mem.group(2)]))
    if gpus:
        req["gpus"] = gpus
    return gpu_type, req


# Canonical terminal-state set (the single source of truth reused by
# collector.sh's seff enrichment and rollup.py's terminal-wins upsert — do
# NOT fork a second, subtly-different list). A state whose FIRST token is in
# this set is terminal, so uid-suffixed rows (`CANCELLED by <uid>`) that
# predate state normalization are still classified correctly.
TERMINAL_STATES = frozenset({
    "COMPLETED", "FAILED", "CANCELLED", "TIMEOUT",
    "OUT_OF_MEMORY", "NODE_FAIL", "PREEMPTED",
})


def is_terminal(state: str) -> bool:
    """True when a sacct job state is terminal (settled, never to change)."""
    tok = (state or "").split()
    return bool(tok) and tok[0] in TERMINAL_STATES


_CANCELLED_BY = re.compile(r"^CANCELLED by \d+$")


def _normalize_state(state: str) -> str:
    """Collapse sacct's uid-suffixed cancel state to a bare token.

    sacct reports a job cancelled by another user as ``CANCELLED by <uid>``,
    so a single logical state fragments into hundreds of distinct per-uid
    strings and state aggregation becomes useless. Fold every such row to
    ``CANCELLED``; the uid is the cancelling user's and is dropped (also the
    privacy-correct move). Every other state passes through verbatim.
    """
    if _CANCELLED_BY.match(state or ""):
        return "CANCELLED"
    return state


#: Used when a job held a GPU but sacct did not record which kind. Explicit, so
#: it can never be mistaken for a real model name or silently ranked against one.
GPU_UNSPECIFIED = "gpu:unspecified"


def derive_hardware(gpu_type, req) -> str:
    """The hardware class a job actually ran on.

    Deliberately NOT the partition. `hardware` used to fall back to the
    partition string when the GPU type was unknown, which mixed two
    taxonomies in one column: `a100` (a device) sat beside `gpu-preempt`
    and `gpu,gpu-preempt` (queues, which may themselves be a100s). Anything
    ranking by hardware -- recommend-hardware, task_profile -- was then
    comparing buckets that are not comparable. The partition is still worth
    keeping, in its own column.
    """
    if gpu_type:
        return canonical_gpu_type(gpu_type)
    gpus = (req or {}).get("gpus") or 0
    return GPU_UNSPECIFIED if gpus else "cpu"


def _provenance(provenance_dir: str | None, job_id: str) -> dict:
    if not provenance_dir:
        return {}
    path = Path(provenance_dir) / f"{job_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict) or data.get("job_id") != job_id:
        return {}
    allowed = {"project", "skill", "campaign", "experiment", "model",
               "dataset", "seed", "git_revision", "config_hash"}
    return {k: data[k] for k in allowed if k in data and data[k] != ""}


def parse_task_runs(text: str, provenance_dir: str | None = None) -> list[dict]:
    """Parse sacct rows.

    Current: JobID|User|Account|Partition|State|Submit|Start|End|Elapsed|
    AllocTRES|ExitCode|MaxRSS|Timelimit (13 fields). A 12-field line without
    User (the previous format) is still accepted. A trailing empty field from
    collector.sh's pad is ignored.
    """
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        f = line.split("|")
        if len(f) < 12 or not f[0] or "." in f[0] or not f[0][0].isdigit():
            continue
        # 12 fields, or 13 with a trailing empty pad, is the pre-User format.
        # 13 nonempty fields, or 14 with a pad, includes User after JobID.
        if len(f) >= 14 or (len(f) == 13 and f[-1] != ""):
            (job_id, user, _acct, part, state, submit, start, end,
             elapsed, tres, exit_code, max_rss, timelimit) = f[:13]
        else:
            (job_id, _acct, part, state, submit, start, end,
             elapsed, tres, exit_code, max_rss, timelimit) = f[:12]
            user = None
        gpu_type, req = _parse_tres(tres)
        if timelimit and timelimit.strip():
            req["walltime_s"] = _parse_elapsed(timelimit)
        try:
            rc = int(exit_code.split(":", 1)[0])
        except (ValueError, AttributeError):
            rc = None
        provenance = _provenance(provenance_dir, job_id)
        out.append({
            "job_id": job_id, "user": user or None,
            "project": provenance.get("project"),
            "skill": provenance.get("skill"), "campaign": provenance.get("campaign"),
            "experiment": provenance.get("experiment"),
            "model": provenance.get("model"), "dataset": provenance.get("dataset"),
            "seed": provenance.get("seed"),
            "git_revision": provenance.get("git_revision"),
            "config_hash": provenance.get("config_hash"),
            "submit": submit or None, "start": start or None, "end": end or None,
            "partition": part, "gpu_type": gpu_type, "req": req,
            "used": {"elapsed_s": _parse_elapsed(elapsed),
                     "max_rss_mb": _parse_mem_mb(max_rss),
                     "cpu_eff_pct": None, "mem_eff_pct": None},
            "state": _normalize_state(state), "exit_code": rc,
        })
    return out


def build_resource_state(ts, partitions_text, pending_text, gpu_text, nodes_text) -> list[dict]:
    pending = parse_pending(pending_text)
    partitions = parse_partitions(partitions_text)
    nodes = parse_nodes(nodes_text)

    # Per-partition node-state tally and GPU totals, derived from the
    # per-node records (this is the aggregation the rollup's util_mean /
    # free_ratio needs — computed here, not in cluster-side bash). A node
    # with unknown gpus_idle (honesty guard: no real GresUsed reading)
    # simply doesn't contribute to gpus_alloc_by_part rather than being
    # counted as 0 alloc — best-effort, never fabricated.
    node_states: dict[str, dict[str, int]] = {}
    gpus_total_by_part: dict[str, int] = {}
    gpus_alloc_by_part: dict[str, int] = {}
    for n in nodes:
        part = n.get("partition")
        if not part:
            continue
        tally = node_states.setdefault(part, {})
        tally[n["state"]] = tally.get(n["state"], 0) + 1
        gpus_total_by_part[part] = gpus_total_by_part.get(part, 0) + n["gpus_total"]
        if n["gpus_idle"] is not None:
            node_alloc = n["gpus_total"] - n["gpus_idle"]
            gpus_alloc_by_part[part] = gpus_alloc_by_part.get(part, 0) + node_alloc

    recs: list[dict] = []
    for name in sorted(partitions):
        base = partitions[name]
        recs.append({"ts": ts, "kind": "partition", "resource_id": name,
                     "pending": pending.get(name, 0),
                     "node_states": node_states.get(name, {}),
                     "gpus_total": gpus_total_by_part.get(name, 0),
                     "gpus_alloc": gpus_alloc_by_part.get(name, 0),
                     **base})
    # gpu_type records: prefer the authoritative wrapper (it also carries
    # pending/vram/compute-capability), but fall back to the measured
    # per-node GRES already in `nodes` when the wrapper yields nothing —
    # otherwise a silent wrapper leaves the whole gpu_type series empty and
    # the unity_usage/unity_traffic readers answer no_data forever, which is
    # exactly what the deployed collector produced. Neither branch invents a
    # reading: with no source at all, no gpu_type record is emitted.
    gpu_recs = parse_gpu_types(gpu_text) or gpu_types_from_nodes(nodes_text)
    for g in gpu_recs:
        recs.append({"ts": ts, **g})
    for n in nodes:
        recs.append({"ts": ts, **n})
    return recs


def _read(path: str) -> str:
    try:
        return Path(path).read_text() if path else ""
    except OSError:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ts", required=True)
    ap.add_argument("--partitions", default="")
    ap.add_argument("--nodes", default="")
    ap.add_argument("--gres", default="")  # reserved; gres also read from partitions
    ap.add_argument("--pending", default="")
    ap.add_argument("--gpu", default="")
    ap.add_argument("--sacct", default="")
    ap.add_argument("--provenance-dir", default="")
    ap.add_argument("--prev", required=True, help="prev node-state json (read+rewrite)")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    resource = build_resource_state(args.ts, _read(args.partitions),
                                    _read(args.pending), _read(args.gpu),
                                    _read(args.nodes))
    cur_states = {r["resource_id"]: r["state"]
                  for r in resource if r["kind"] == "node"}
    prev_path = Path(args.prev)
    prev = json.loads(prev_path.read_text()) if prev_path.exists() else {}
    events = diff_node_events(prev, cur_states, args.ts)
    task_runs = parse_task_runs(_read(args.sacct), args.provenance_dir)

    def append(name, rows):
        with open(out_dir / name, "a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, sort_keys=True) + "\n")

    append("resource_state.jsonl", resource)
    if events:
        append("events.jsonl", events)
    if task_runs:
        append("task_runs.jsonl", task_runs)
    prev_path.write_text(json.dumps(cur_states, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
