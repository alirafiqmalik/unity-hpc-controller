#!/usr/bin/env bash
# collector.sh — the SINGLE cluster-side telemetry writer (invariant I1).
#
# The controller does not start `loop`. A schedule sends `once` into a tmux
# session that closes on its own (ADR 0004). `loop` remains for a manual run.
#
# `once` samples and prunes, then exits. It appends to the cluster staging tree:
#   $UNITY_CID/telemetry/YYYY-MM-DD/{resource_state,events,task_runs}.jsonl
# The local machine keeps the archive after a successful pull (ADR 0005).
#
# Singleton-guarded by a `flock` on collector.lock, so a second copy of this
# script can never double-write (I1). The controller opens one session and
# sends `once`. flock is what enforces I1 if two samples overlap. Every cluster
# command runs under `timeout` and `nice`, with the wrapper PATH + PAGER fix
# (the `unity-slurm-*` wrappers are not on the non-interactive PATH).
# The 35-day prune here is a backstop for a machine that never pulls.
# After a successful local rollup, hpc-remote-prune drops archived days.
#
# All record construction/parsing is delegated to the co-located, unit-tested
# collector_parse.py — this script is a thin driver: it runs cluster
# commands, reshapes their raw output into the pipe-delimited shapes
# collector_parse.py expects, and pipes it through.
#
# Modes: once (what the controller sends) | sample | prune | loop (manual only)
set -euo pipefail

export PATH="/modules/user-resources/bin:$PATH"
export PAGER=NONE
export TZ=UTC
export LC_ALL=C

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# No personal identifiers hardcoded: account comes from $SLURM_ACCOUNT, user
# from $USER/whoami. UNITY_CID always overrides this fallback in practice.
WORK_DIR="${UNITY_CID:-/work/${SLURM_ACCOUNT:-unknown-account}/$(whoami)/cluster-intel}"
TEL="$WORK_DIR/telemetry"
LOCK="$WORK_DIR/collector.lock"
INTERVAL="${UNITY_COLLECTOR_INTERVAL:-900}"
RETENTION_DAYS="${UNITY_COLLECTOR_RETENTION_DAYS:-35}"
SACCT_SCOPE="${SACCT_SCOPE:--a}"
TMUX_SESSION="${UNITY_TMUX_SESSION:-unity-collector}"

mkdir -p "$TEL"

# --- deferred-contract enrichment (best-effort; never fatal, never fabricated) ---

# task_runs.used.cpu_eff_pct / .mem_eff_pct via `seff <jobid>`. No-ops
# cleanly if `seff` is unavailable (e.g. under test).
enrich_seff() {
    local out="$1" tmp="$2"
    local runs="$out/task_runs.jsonl"
    [ -f "$runs" ] || return 0
    command -v seff >/dev/null 2>&1 || return 0
    local jobs eff_json
    # seff is optional and can stall for each job. A seven-day sacct catch-up
    # can contain thousands of rows, so inspect only the newest 12 terminal
    # jobs and give each query at most five seconds (60 seconds total).
    jobs="$(python3 - "$runs" "$HERE" <<'PY'
import json, sys
sys.path.insert(0, sys.argv[2])
from collector_parse import is_terminal
rows = []
for line in open(sys.argv[1], encoding="utf-8"):
    rec = json.loads(line)
    jid = str(rec.get("job_id") or "")
    if jid.isdigit() and is_terminal(rec.get("state")):
        rows.append((rec.get("end") or rec.get("start") or "", jid))
seen = set()
for _, jid in sorted(rows, reverse=True):
    if jid not in seen:
        print(jid)
        seen.add(jid)
    if len(seen) == 12:
        break
PY
)"
    [ -n "$jobs" ] || return 0
    eff_json="$tmp/seff.json"
    {
        printf '{'
        local first=1 jid seff_out cpu mem
        while IFS= read -r jid; do
            [ -n "$jid" ] || continue
            seff_out="$(timeout 5 nice -n 19 seff "$jid" 2>/dev/null || true)"
            cpu="$(printf '%s\n' "$seff_out" | sed -n 's/^CPU Efficiency: \([0-9.]*\)%.*/\1/p')"
            mem="$(printf '%s\n' "$seff_out" | sed -n 's/^Memory Efficiency: \([0-9.]*\)%.*/\1/p')"
            [ -n "$cpu$mem" ] || continue
            [ "$first" -eq 1 ] || printf ','
            first=0
            printf '"%s":{"cpu_eff_pct":%s,"mem_eff_pct":%s}' \
                "$jid" "${cpu:-null}" "${mem:-null}"
        done <<<"$jobs"
        printf '}'
    } >"$eff_json"
    python3 - "$runs" "$eff_json" "$HERE" <<'PY'
import json, sys
runs_path, eff_path, here = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, here)
from collector_parse import is_terminal  # single shared terminal predicate
eff = json.loads(open(eff_path, encoding="utf-8").read() or "{}")
if not eff:
    raise SystemExit(0)
lines = open(runs_path, encoding="utf-8").read().splitlines()
out = []
for line in lines:
    rec = json.loads(line)
    e = eff.get(rec.get("job_id"))
    if e and is_terminal(rec.get("state")):
        for key in ("cpu_eff_pct", "mem_eff_pct"):
            if e.get(key) is not None:
                rec["used"][key] = e[key]
    out.append(json.dumps(rec, sort_keys=True))
open(runs_path, "w", encoding="utf-8").write("\n".join(out) + "\n")
PY
}

# gpu_type.pending via the %b (requested TRES-per-node) column already
# requested on the pending-jobs squeue call below. No-ops cleanly if no
# GPU-bearing pending jobs are found. This is a GAP-FILLER only: when
# `unity-slurm-gpu-usage` already reported a per-type pending count that
# reading is authoritative (it is the scheduler's own, in GPUs) and is left
# alone — this tally counts pending JOBS, a different, weaker quantity.
enrich_gpu_pending() {
    local out="$1" tmp="$2" ts="$3"
    local rs="$out/resource_state.jsonl"
    [ -f "$rs" ] || return 0
    [ -f "$tmp/pending.raw" ] || return 0
    python3 - "$rs" "$tmp/pending.raw" "$ts" <<'PY'
import json, re, sys
rs_path, pending_path, ts = sys.argv[1], sys.argv[2], sys.argv[3]
pat = re.compile(r"gpu:([a-z0-9_]+)", re.I)
counts: dict[str, int] = {}
for line in open(pending_path, encoding="utf-8").read().splitlines():
    f = line.split("|")
    if len(f) < 3:
        continue
    for m in pat.finditer(f[2]):
        t = m.group(1).lower()
        counts[t] = counts.get(t, 0) + 1
if not counts:
    raise SystemExit(0)
lines = open(rs_path, encoding="utf-8").read().splitlines()
out = []
for line in lines:
    rec = json.loads(line)
    if (rec.get("kind") == "gpu_type" and rec.get("ts") == ts
            and rec.get("resource_id") in counts and rec.get("pending") is None):
        rec["pending"] = counts[rec["resource_id"]]
    out.append(json.dumps(rec, sort_keys=True))
open(rs_path, "w", encoding="utf-8").write("\n".join(out) + "\n")
PY
}

# partition.access via `unity-slurm-partition-usage`. No-ops cleanly if the
# wrapper is unavailable or its output can't be matched to a known
# partition name (never fabricated).
enrich_partition_access() {
    local out="$1" tmp="$2" ts="$3"
    local rs="$out/resource_state.jsonl"
    [ -f "$rs" ] || return 0
    command -v unity-slurm-partition-usage >/dev/null 2>&1 || return 0
    timeout 30 nice -n 19 unity-slurm-partition-usage </dev/null \
        >"$tmp/partition_usage.raw" 2>/dev/null || return 0
    [ -s "$tmp/partition_usage.raw" ] || return 0
    python3 - "$rs" "$tmp/partition_usage.raw" "$ts" <<'PY'
import json, re, sys
rs_path, usage_path, ts = sys.argv[1], sys.argv[2], sys.argv[3]
access: dict[str, str] = {}
pat = re.compile(r"^\s*(\S+)\s+(open|restricted|pi[- _]only)\b", re.I)
for line in open(usage_path, encoding="utf-8").read().splitlines():
    m = pat.match(line)
    if m:
        access[m.group(1)] = m.group(2).lower()
if not access:
    raise SystemExit(0)
lines = open(rs_path, encoding="utf-8").read().splitlines()
out = []
for line in lines:
    rec = json.loads(line)
    if rec.get("kind") == "partition" and rec.get("ts") == ts and rec.get("resource_id") in access:
        rec["access"] = access[rec["resource_id"]]
    out.append(json.dumps(rec, sort_keys=True))
open(rs_path, "w", encoding="utf-8").write("\n".join(out) + "\n")
PY
}

# High-water-mark sacct window (I-loss fix). The collector persists the start
# timestamp of its last successful sample in $WORK_DIR/last_sample_utc (it is
# the single writer of that file under the existing flock, so no extra lock is
# needed). Each sample pulls sacct from (last_sample_utc − 5-minute overlap) so
# nothing that started AND ended between two samples is lost during downtime.
# First run (no state file, or an unparseable one) falls back to the safe
# now-20minutes default. If the mark is older than 7 days the window is clamped
# to now-7days and a warning is emitted — an unbounded sacct pull on a shared
# login node is unacceptable; the operator runs `catchup` for older history.
compute_start_window() {
    local state="$WORK_DIR/last_sample_utc"
    local hwm hwm_epoch now_epoch floor_epoch start_epoch
    now_epoch="$(date -u +%s)"
    floor_epoch=$((now_epoch - 7 * 86400))
    if [ -f "$state" ] \
        && hwm="$(cat "$state" 2>/dev/null)" && [ -n "$hwm" ] \
        && hwm_epoch="$(date -u -d "$hwm" +%s 2>/dev/null)"; then
        start_epoch=$((hwm_epoch - 300))
        if [ "$start_epoch" -lt "$floor_epoch" ]; then
            echo "[collector] high-water mark $hwm older than 7d; clamping -S to now-7days (run 'catchup' for older history)" >&2
            start_epoch="$floor_epoch"
        fi
        date -u -d "@$start_epoch" +%Y-%m-%dT%H:%M:%S
    else
        echo "now-20minutes"
    fi
}

sample() {
    local ts day out tmp start_window
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    start_window="$(compute_start_window)"
    day="$(date -u +%F)"
    out="$TEL/$day"
    mkdir -p "$out"
    tmp="$(mktemp -d)"

    timeout 30 nice -n 19 sinfo -h -o '%R|%a|%D|%C|%G' \
        </dev/null >"$tmp/partitions.raw" 2>/dev/null || true

    # Per-node sinfo -O (long format) with explicit field widths, to reach
    # real per-node FreeMem/GresUsed (GresUsed has no short %-letter, only
    # a long field name via -O) and produce the parser's expected 8-field
    # partition|name|state|cpu|mem_total|mem_free|gres_total|gres_alloc
    # shape. Stock sinfo fields only — no `unity-slurm-*` wrapper (not on
    # the non-interactive PATH). Each field is fixed-width, left-justified,
    # so it can be sliced deterministically instead of split on whitespace.
    timeout 30 nice -n 19 sinfo -N -h \
        -O 'NodeList:24,Partition:20,StateCompact:10,CPUsState:24,Memory:12,FreeMem:12,Gres:60,GresUsed:60' \
        </dev/null >"$tmp/nodes.raw.wide" 2>/dev/null || true

    # Honesty guard (§8): mem_free/gres_alloc are MEASURED, never derived
    # from the totals. sinfo prints "N/A" for FreeMem when a node hasn't
    # reported it, and GresUsed can be blank/truncated/malformed; either
    # case is emitted here as an EMPTY field so collector_parse.py records
    # it as unknown (None) rather than a fabricated 100%-free / 0%-busy
    # reading. "(null)" (no GRES on the node) is a real, measured zero and
    # is passed through as-is.
    awk -v widths="24 20 10 24 12 12 60 60" '
        BEGIN {
            n = split(widths, w, " ")
            off[1] = 1
            for (i = 2; i <= n; i++) off[i] = off[i - 1] + w[i - 1]
        }
        {
            node      = substr($0, off[1], w[1])
            part      = substr($0, off[2], w[2])
            state     = substr($0, off[3], w[3])
            cpu       = substr($0, off[4], w[4])
            mem_total = substr($0, off[5], w[5])
            mem_free  = substr($0, off[6], w[6])
            gres_tot  = substr($0, off[7], w[7])
            gres_used = substr($0, off[8], w[8])
            gsub(/^[ \t]+|[ \t]+$/, "", node)
            gsub(/^[ \t]+|[ \t]+$/, "", part)
            gsub(/\*$/, "", part)
            gsub(/^[ \t]+|[ \t]+$/, "", state)
            gsub(/^[ \t]+|[ \t]+$/, "", cpu)
            gsub(/^[ \t]+|[ \t]+$/, "", mem_total)
            gsub(/^[ \t]+|[ \t]+$/, "", mem_free)
            gsub(/^[ \t]+|[ \t]+$/, "", gres_tot)
            gsub(/^[ \t]+|[ \t]+$/, "", gres_used)
            if (node == "") next
            if (mem_free !~ /^[0-9]+$/) mem_free = ""
            if (gres_used != "(null)" && gres_used !~ /gpu:[A-Za-z0-9_]+:[0-9]+/) gres_used = ""
            print part "|" node "|" state "|" cpu "|" mem_total "|" mem_free "|" gres_tot "|" gres_used
        }
    ' "$tmp/nodes.raw.wide" >"$tmp/nodes.raw" 2>/dev/null || : >"$tmp/nodes.raw"

    # %b (requested TRES-per-node) feeds enrich_gpu_pending's per-GPU-type
    # tally; parse_pending only reads field 1 so the extra column is inert
    # to the tested parser.
    timeout 30 nice -n 19 squeue -h -t PD -o '%P|%r|%b' \
        </dev/null >"$tmp/pending.raw" 2>/dev/null || true

    timeout 60 nice -n 19 unity-slurm-gpu-usage \
        </dev/null >"$tmp/gpu.raw" 2>/dev/null || true

    # Keep the legacy first 13 fields, followed by request, node, and step
    # measurements. The parser also accepts older allocation-only samples.
    # sacct's OWN exit code must be checked: a transient slurmdbd failure
    # (rate-limit, restart) yields empty output, and treating that as "no
    # jobs" while advancing the high-water mark would PERMANENTLY skip this
    # window's jobs. Failure -> keep the mark, warn, retry the same window
    # next cycle. (Same masking class as the sync driver's dry-run guard.)
    local sacct_rc=0
    # Include steps: -X suppresses the RSS/CPU/GPU accounting we need.
    # Tabs preserve OR constraints whose literal pipe conflicts with -P's default.
    timeout 60 nice -n 19 sacct $SACCT_SCOPE -S "$start_window" -E now -P -n --delimiter=$'\t' \
        -o JobID,User,Account,Partition,State,Submit,Start,End,Elapsed,AllocTRES,ExitCode,MaxRSS,Timelimit,NodeList,JobName,QOS,ReqTRES,ReqMem,ReqCPUS,Constraints,TotalCPU,CPUTimeRAW,TRESUsageInMax,Eligible,Restarts \
        </dev/null 2>"$tmp/sacct.err" >"$tmp/sacct.raw" || sacct_rc=$?

    if [ "$sacct_rc" -ne 0 ]; then
        echo "[collector] WARNING: sacct failed (rc=$sacct_rc) -- keeping high-water mark, window retried next cycle" >&2
        sed 's/^/[collector]   sacct: /' "$tmp/sacct.err" >&2 || true
        : >"$tmp/sacct.raw"   # parse sees no jobs this cycle; mark does not advance
    fi

    python3 "$HERE/collector_parse.py" --ts "$ts" \
        --partitions "$tmp/partitions.raw" --nodes "$tmp/nodes.raw" \
        --pending "$tmp/pending.raw" --gpu "$tmp/gpu.raw" --sacct "$tmp/sacct.raw" \
        --provenance-dir "$WORK_DIR/manifests" \
        --prev "$WORK_DIR/prev_nodes.json" --out-dir "$out"

    # Advance the high-water mark ONLY when both sacct and the parse pipeline
    # succeeded (set -e would have aborted on a parse failure). The mark is
    # THIS sample's start timestamp, captured before sacct ran, so the next
    # window's overlap can never skip a job that appeared mid-sample.
    if [ "$sacct_rc" -eq 0 ]; then
        printf '%s\n' "$ts" >"$WORK_DIR/last_sample_utc"
    fi

    enrich_seff "$out" "$tmp"
    enrich_gpu_pending "$out" "$tmp" "$ts"
    enrich_partition_access "$out" "$tmp" "$ts"

    rm -rf "$tmp"
}

# catchup <START> — one-shot historical backfill. Runs a SINGLE sacct pull
# from an operator-supplied -S value (e.g. after >7d downtime, when the normal
# window clamps to now-7days) through the SAME parse path as `sample`, and
# appends the re-observed jobs to the raw store. It takes the flock (never runs
# concurrently with a sample), does NOT advance last_sample_utc, and does NOT
# prune. Each job is filed under its OWN submit-derived day-dir, because rollup
# derives day_utc from the day-directory a task_runs.jsonl lives in (not from
# record timestamps) — appending everything to today would stamp historical
# jobs with today's date. The terminal-wins upsert then heals any stale
# non-terminal rows those days already hold.
catchup() {
    local start="${1:-}"
    if [ -z "$start" ]; then
        echo "usage: collector.sh catchup <START>  (START = sacct -S value, e.g. 2026-07-20T03:00:00 or now-3days)" >&2
        return 2
    fi
    local ts tmp pout
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    tmp="$(mktemp -d)"
    pout="$tmp/out"
    mkdir -p "$pout"

    # A catchup exists to recover history; a swallowed sacct failure here
    # reports "success" with zero records and the operator believes the heal
    # happened. Fail LOUDLY instead (rc=3) so callers can retry the chunk.
    local sacct_rc=0
    timeout 300 nice -n 19 sacct $SACCT_SCOPE -S "$start" -E now -P -n --delimiter=$'\t' \
        -o JobID,User,Account,Partition,State,Submit,Start,End,Elapsed,AllocTRES,ExitCode,MaxRSS,Timelimit,NodeList,JobName,QOS,ReqTRES,ReqMem,ReqCPUS,Constraints,TotalCPU,CPUTimeRAW,TRESUsageInMax,Eligible,Restarts \
        </dev/null 2>"$tmp/sacct.err" >"$tmp/sacct.raw" || sacct_rc=$?
    if [ "$sacct_rc" -ne 0 ]; then
        echo "[collector] catchup: sacct failed (rc=$sacct_rc) -- nothing written, retry this window" >&2
        sed 's/^/[collector]   sacct: /' "$tmp/sacct.err" >&2 || true
        rm -rf "$tmp"
        return 3
    fi

    # Same parser as `sample`, sacct-only (catchup is a task_runs backfill).
    # The parser insists on --prev/--out-dir; give it throwaway ones in tmp.
    python3 "$HERE/collector_parse.py" --ts "$ts" \
        --sacct "$tmp/sacct.raw" --provenance-dir "$WORK_DIR/manifests" \
        --prev "$tmp/prev.json" --out-dir "$pout"

    enrich_seff "$pout" "$tmp"

    [ -f "$pout/task_runs.jsonl" ] || { rm -rf "$tmp"; return 0; }
    python3 - "$pout/task_runs.jsonl" "$TEL" <<'PY'
import json, os, sys
runs_path, tel = sys.argv[1], sys.argv[2]
buckets: dict[str, list[str]] = {}
for line in open(runs_path, encoding="utf-8").read().splitlines():
    line = line.strip()
    if not line:
        continue
    rec = json.loads(line)
    # Submit-derived day, falling back to start then end. day_utc must track
    # the job's own day, not the day catchup happened to run.
    stamp = rec.get("submit") or rec.get("start") or rec.get("end")
    if not stamp or len(stamp) < 10:
        continue  # cannot place it honestly -> skip rather than misfile
    buckets.setdefault(stamp[:10], []).append(line)
for day, lines in buckets.items():
    d = os.path.join(tel, day)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "task_runs.jsonl"), "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
PY
    rm -rf "$tmp"
}

prune() {
    [ -d "$TEL" ] || return 0
    local cutoff name d
    cutoff="$(date -u -d "${RETENTION_DAYS} days ago" +%F)"
    for d in "$TEL"/*/; do
        [ -d "$d" ] || continue
        name="$(basename "${d%/}")"
        case "$name" in 20*) ;; *) continue ;; esac
        if [[ "$name" < "$cutoff" ]]; then
            rm -rf "${d%/}"
        fi
    done
}

acquire_lock_or_exit() {
    exec 9>"$LOCK"
    if ! flock -n 9; then
        echo "collector already running (lock held) — exiting cleanly"
        exit 0
    fi
}

case "${1:-loop}" in
    sample) sample ;;
    window) compute_start_window ;;
    catchup) acquire_lock_or_exit; catchup "${2:-}" ;;
    prune)  prune ;;
    once)   acquire_lock_or_exit; sample; prune ;;
    loop|*)
        acquire_lock_or_exit
        echo "[collector] loop every ${INTERVAL}s, ${RETENTION_DAYS}d retention -> $TEL (session: $TMUX_SESSION)"
        while true; do
            sample
            prune
            sleep "$INTERVAL"
        done
        ;;
esac
