# hpc-plugin Implementation Plan

> **Status (v0.3):** Implemented. The cluster-intel component was redesigned from
> a forward-only queue poller to authoritative sacct-based usage history with
> fixed time slots, terminal plots (`hpc-usage`), and a backend recommender
> (`analyze-backends.py` + `unity-hpc:recommend-hardware`). See the redesign notes in
> the project artifacts. Pending: deploying the new collectors to the cluster.

**Target dir:** `/home/ahm/Desktop/project/Research/tools/hpc-experiment-workflow/`  
**Install target:** `~/LocalServices/plugins/hpc-plugin/` (symlinked from project)  
**Cluster storage:** `/work/pi_taqi_umass_edu/ali/` (PI group allocation, `ali/` reserved for user)

---

## Resolved Ambiguities

Before coding, these spec decisions are locked:

| Question | Decision |
|---|---|
| `HPC_PROJECT_DIR` in MCP server | Read from `os.getcwd()` by default; overridden by env var. Projects set it in `.claude/settings.json` `env` block. |
| usage/traffic summary location | `$UNITY_HPC_DATA/analysis/usage_summary.json` (default `~/.local/share/unity-hpc/analysis/`) — the MCP server resolves it via `_data_dir()` (`$UNITY_HPC_DATA` → `$XDG_DATA_HOME/unity-hpc` → `~/.local/share/unity-hpc`), independent of cwd and of the plugin version. |
| `unity-hpc:recon` output | Writes to the **shared machine-wide data dir** `$UNITY_HPC_DATA/cluster-profile.md` (default `~/.local/share/unity-hpc`; one copy for the cluster, every project reads it, so recon runs once). Kept outside the versioned plugin install so it survives plugin updates. Served cwd-independently by the `unity_cluster_profile` MCP tool. |
| `job_template.sh` multi-node | Single template; branches on `SLURM_NODES > 1` to switch between `python` and `torchrun` launcher. |
| `hpc-tmux` | Local script that SSHes to the cluster to list/create/kill sessions. |
| SKILL.md frontmatter | `name: unity-hpc:<name>` + `description: "..."` — matches superpowers skill convention. |
| Skills calling MCP tools | Skills are pure markdown instructions to Claude. They tell Claude to call e.g. `mcp__unity-hpc__unity_status`. No subprocess invocation. |
| Fair-use limits scope | `/home/ahmalik_umass_edu/` = personal home (user-only). `/work/pi_taqi_umass_edu/` = PI group allocation. `/work/pi_taqi_umass_edu/ali/` = user's reserved dir within PI space. SLURM account = `pi_taqi_umass_edu`; unity-hpc:recon queries per-user limits within that account. |

---

## Project Structure

```
hpc-experiment-workflow/          ← git repo (this dir)
├── docs/
│   └── implementation-plan.md   ← this file
├── package.json                  ← plugin manifest
├── README.md
├── .gitignore
│
├── skills/
│   ├── setup/SKILL.md
│   ├── run/SKILL.md
│   ├── sweep/SKILL.md
│   ├── status/SKILL.md
│   ├── fetch/SKILL.md
│   ├── resume/SKILL.md
│   ├── log-result/SKILL.md
│   └── recon/SKILL.md
│
├── mcp/
│   ├── hpc_server.py             ← stdio MCP server, 8 tools
│   └── requirements.txt
│
├── scripts/
│   ├── hpc-status                ← exit 0=done 1=running 2=fail
│   ├── hpc-logs
│   ├── hpc-results
│   ├── hpc-ssh
│   ├── hpc-compare
│   ├── hpc-cleanup
│   └── hpc-tmux                  ← SSH-based tmux session manager
│
├── cluster-intel/
│   ├── cluster-poller.sh         ← runs on login node inside tmux
│   ├── analyze-traffic.py        ← runs locally, produces reports
│   └── analysis/                 ← .gitkeep (output dir, gitignored)
│
├── agents/
│   ├── experiment-dispatcher.md
│   ├── result-analyzer.md
│   └── recon.md
│
└── templates/
    ├── CLAUDE.md.template
    ├── .env.example
    └── job_template.sh           ← updated sbatch template
```

---

## Build Order & Task Breakdown

### Wave 1 — Parallel (no shared files)

#### Task A: Scaffold + Scripts + Templates + Agents
Files: `package.json`, `README.md`, `.gitignore`, `templates/`, `scripts/` (7 files), `agents/` (3 files)

**package.json**
```json
{
  "name": "hpc-plugin",
  "version": "0.2.0",
  "description": "Unity HPC cluster workflow plugin for Claude Code",
  "pi": { "skills": ["./skills"] }
}
```

**README.md** — brief plugin description, install command, quick-start

**.gitignore**
```
cluster-intel/analysis/*.png
cluster-intel/analysis/*.json
cluster-intel/analysis/*.md
__pycache__/
*.pyc
```

**templates/.env.example**
```bash
USER_EMAIL="ahmalik@umass.edu"
UNITY_HOST="unity"
REMOTE_DIR="/work/pi_taqi_umass_edu/ali/autoresearch"
HF_HOME="/work/pi_taqi_umass_edu/ali/hf"
AUTORESEARCH_CACHE="/work/pi_taqi_umass_edu/ali/cache"
WALLTIME="00:15:00"
SLURM_CPUS="8"
SLURM_MEM="64G"
SLURM_GPUS="1"
SLURM_GPU_TYPE=""        # h100, a100, l40s — blank = scheduler picks
SLURM_NODES="1"          # set to 2+ for multi-node (switches to torchrun)
SLURM_ACCOUNT="pi_taqi_umass_edu"
POLL="60"
```

**templates/job_template.sh** — sbatch body script
- `#SBATCH` directives read from env vars (WALLTIME, SLURM_CPUS, SLURM_MEM, SLURM_GPUS, SLURM_GPU_TYPE, SLURM_NODES, SLURM_ACCOUNT)
- `module purge && module load cuda/12.8`
- activate `.venv`
- set PYTHONUNBUFFERED, OMP_NUM_THREADS, etc.
- `if [ "${SLURM_NODES:-1}" -gt 1 ]` → torchrun launcher; else python launcher
- REMOTE_DIR base: `/work/pi_taqi_umass_edu/ali/autoresearch`

**scripts/hpc-status**
```bash
#!/usr/bin/env bash
# Reads .unity_state/*.db locally — no SSH
# Exit: 0=all done, 1=jobs running/pending, 2=failed/no campaign
HPC_DIR="${HPC_PROJECT_DIR:-$PWD}"
DB=$(ls "$HPC_DIR/.unity_state/"*.db 2>/dev/null | sort | tail -1)
[[ -z "$DB" ]] && echo "No active campaign" && exit 2
# sqlite3 query for status counts, exit code based on running count
```

**scripts/hpc-logs**
```bash
#!/usr/bin/env bash
# Tail the monitor log for the active campaign
HPC_DIR="${HPC_PROJECT_DIR:-$PWD}"
LOG=$(ls "$HPC_DIR/.unity_state/"*.monitor.log 2>/dev/null | sort | tail -1)
[[ -z "$LOG" ]] && echo "No monitor log found" && exit 1
tail -f "${LOG}"  # or tail -n "${1:-50}" if arg given
```

**scripts/hpc-results**
```bash
#!/usr/bin/env bash
# Pretty-print results.tsv with column alignment and status coloring
# Uses ANSI colors: green=keep, red=crash, yellow=discard
HPC_DIR="${HPC_PROJECT_DIR:-$PWD}"
TSV="$HPC_DIR/results.tsv"
[[ ! -f "$TSV" ]] && echo "No results.tsv found in $HPC_DIR" && exit 1
# column -t -s $'\t', then colorize status column with sed/awk
```

**scripts/hpc-ssh**
```bash
#!/usr/bin/env bash
# SSH to Unity with env loaded
[[ -f "${HPC_PROJECT_DIR:-$PWD}/unityHPC/.env" ]] && \
  set -a && source "${HPC_PROJECT_DIR:-$PWD}/unityHPC/.env" && set +a
exec ssh "${UNITY_HOST:-unity}" "$@"
```

**scripts/hpc-compare**
```bash
#!/usr/bin/env bash
# Diff two experiment commits: val_bpb delta, memory delta, train.py diff
# Usage: hpc-compare <commit-a> <commit-b>
# Reads results.tsv for metrics, runs git diff for code changes
```

**scripts/hpc-cleanup**
```bash
#!/usr/bin/env bash
# Remove .unity_state/ DB + log files older than N days (default 30)
# Asks for confirmation before deleting
DAYS="${1:-30}"
HPC_DIR="${HPC_PROJECT_DIR:-$PWD}"
```

**scripts/hpc-tmux**
```bash
#!/usr/bin/env bash
# Manage named tmux sessions on Unity via SSH
# Usage: hpc-tmux ls | start <name> [cmd] | attach <name> | kill <name>
# Loads env for UNITY_HOST
CMD="${1:-ls}"
[[ -f "${HPC_PROJECT_DIR:-$PWD}/unityHPC/.env" ]] && \
  set -a && source "${HPC_PROJECT_DIR:-$PWD}/unityHPC/.env" && set +a
case "$CMD" in
  ls)     ssh "${UNITY_HOST:-unity}" "tmux ls 2>/dev/null || echo 'No sessions'" ;;
  start)  ssh "${UNITY_HOST:-unity}" "tmux new -d -s '${2:?name required}' '${3:-bash}'" ;;
  attach) ssh -t "${UNITY_HOST:-unity}" "tmux attach -t '${2:?name required}'" ;;
  kill)   ssh "${UNITY_HOST:-unity}" "tmux kill-session -t '${2:?name required}'" ;;
  *)      echo "Usage: hpc-tmux ls|start <name> [cmd]|attach <name>|kill <name>" ;;
esac
```

**agents/experiment-dispatcher.md** — agent persona:
- Input: program-unity.md, results.tsv, docs/cluster-profile.md
- Checks unity_traffic MCP before submitting
- Generates variants with explicit hypotheses
- Caps at min(4, MaxSubmitJobs from cluster-profile.md)
- Never modifies prepare.py

**agents/result-analyzer.md** — agent persona:
- Triggered after campaign completes
- Calls unity_results MCP tool
- Parses multi-node merged output
- Updates results.tsv, writes to docs/experiment-log.md
- keep/discard/crash decision with rationale

**agents/recon.md** — agent persona:
- Reads cluster facts (read-only SLURM commands on login node)
- Key commands: sinfo, sacctmgr, scontrol, cat /etc/motd, module avail
- Output: docs/cluster-profile.md with structured partition table + limits
- Includes: PI account (`pi_taqi_umass_edu`) per-user limits, GPU types, MaxJobs/MaxSubmitJobs/MaxWall

---

#### Task B: All 8 Skills (SKILL.md files)

SKILL.md frontmatter format (from superpowers convention):
```yaml
---
name: unity-hpc:<name>
description: "<one line — used in skill discovery>"
---
```

Skills are **pure markdown instructions to Claude**. They do NOT run code. They tell Claude what commands to run (via Bash tool) and what MCP tools to call (via the `mcp__unity-hpc__*` tool namespace).

**skills/setup/SKILL.md** — unity-hpc:setup
```
Announce: "Using unity-hpc:setup to bootstrap a new Unity HPC experiment."

Steps (execute in order, stop and report if any fail):
1. Verify .env exists at unityHPC/.env — if not, copy templates/.env.example → unityHPC/.env and ask user to fill in USER_EMAIL
2. Source env: set -a && . unityHPC/.env && set +a
3. SSH check: ssh "$UNITY_HOST" 'echo ok' — must succeed
4. Create /work dirs on cluster:
   ssh "$UNITY_HOST" "mkdir -p /work/pi_taqi_umass_edu/ali/{autoresearch,hf,cache,cluster-intel/analysis}"
5. Sync code: bash unityHPC/sync.sh
6. Start cluster-intel poller if not running:
   ssh "$UNITY_HOST" "tmux has-session -t cluster-intel 2>/dev/null || tmux new-session -d -s cluster-intel 'while true; do bash /work/pi_taqi_umass_edu/ali/cluster-intel/cluster-poller.sh; sleep 900; done'"
   (copies cluster-poller.sh to cluster first if not present)
7. Check if docs/cluster-profile.md exists — if not, invoke unity-hpc:recon skill
8. Create git branch: git checkout -b autoresearch/<tag> (propose tag = today's date)
9. Initialize results.tsv with header if not present:
   echo "commit\tval_bpb\tmemory_gb\tstatus\tdescription" > results.tsv
10. Print summary: SSH ✓, sync ✓, cluster-intel ✓, branch created, results.tsv ready
```

**skills/run/SKILL.md** — unity-hpc:run
```
Announce: "Using unity-hpc:run to submit an experiment to Unity."

Steps:
1. Source env: set -a && . unityHPC/.env && set +a
2. Call MCP tool mcp__unity-hpc__unity_traffic — print queue depth and recommendation
3. If queue is deep (>30 jobs pending): warn user, suggest gpu-preempt or waiting; ask to proceed
4. Run: bash unityHPC/run.sh run <exp> [--dry-run if --dry-run flag passed]
5. Print: campaign name, monitor PID, tail command
6. Tail first 10 lines of monitor log to confirm submission
```

**skills/sweep/SKILL.md** — unity-hpc:sweep
```
Announce: "Using unity-hpc:sweep to submit a parameter sweep to Unity."

Steps:
1. Source env
2. Read docs/cluster-profile.md for MaxSubmitJobs limit
3. Warn if sweep size > MaxSubmitJobs
4. Call mcp__unity-hpc__unity_traffic — print queue state
5. Run: bash unityHPC/run.sh sweep <exp> <sweep_config> [--parallel-seeds]
6. Print: number of jobs submitted, campaign name
```

**skills/status/SKILL.md** — unity-hpc:status
```
Announce: "Using unity-hpc:status to check campaign job states."

Steps:
1. Call MCP tool mcp__unity-hpc__unity_status — print job state counts
2. Call MCP tool mcp__unity-hpc__unity_jobs — list individual jobs with status
3. If any jobs RUNNING: print estimated completion from monitor log
4. If all COMPLETED: suggest running /unity-hpc:fetch
5. If any FAILED/PREEMPTED: show retry status from DB
```

**skills/fetch/SKILL.md** — unity-hpc:fetch
```
Announce: "Using unity-hpc:fetch to retrieve experiment results."

Steps:
1. Source env
2. Run: bash unityHPC/run.sh fetch [campaign]
3. Call MCP tool mcp__unity-hpc__unity_results — parse and print metrics per job
4. For multi-node jobs: grep merged output for val_bpb, peak_vram_mb, mfu_percent
5. Print summary table: job, val_bpb, memory_gb, status
6. Prompt: "Run /unity-hpc:log-result to record the best result to results.tsv"
```

**skills/resume/SKILL.md** — unity-hpc:resume
```
Announce: "Using unity-hpc:resume to rebuild session context."

Steps (read-only — no cluster operations):
1. Read CLAUDE.md (project context)
2. Read unityHPC/.env (cluster config — mask USER_EMAIL in output)  
3. Read program-unity.md (current research direction)
4. Call mcp__unity-hpc__unity_results_tsv — read all experiment history, find best val_bpb
5. Call mcp__unity-hpc__unity_status — get current job states
6. Read docs/cluster-profile.md if exists (partition limits, GPU types)
7. Call mcp__unity-hpc__unity_traffic — current queue state
8. Print compact brief:
   - Best result so far: commit, val_bpb, description
   - Current campaign: N running, M completed, K failed
   - Active research direction (from program-unity.md summary)
   - Queue: current depth + recommended partition
   - Suggested next step (fetch results / run next experiment / wait)
```

**skills/log-result/SKILL.md** — unity-hpc:log-result
```
Announce: "Using unity-hpc:log-result to record experiment to results.tsv."

Steps:
1. Call mcp__unity-hpc__unity_results — get latest campaign metrics
2. Get current git commit: git rev-parse --short HEAD
3. Extract: val_bpb, peak_vram_mb (convert to GB: /1024, round to 1dp)
4. Ask user: status (keep/discard/crash) and short description (no commas)
5. Append TSV row: <commit>\t<val_bpb>\t<memory_gb>\t<status>\t<description>
6. Confirm: "Logged to results.tsv. Best so far: <best_val_bpb> (<commit>)"
```

**skills/recon/SKILL.md** — unity-hpc:recon
```
Announce: "Using unity-hpc:recon to profile the Unity cluster."

Steps (all read-only — safe on login node):
1. Source env
2. Run via ssh "$UNITY_HOST":
   a. sinfo -o "%P %a %l %D %c %m %G" — partition table
   b. sacctmgr show assoc user=ahmalik_umass_edu format=Account,MaxJobs,MaxSubmitJobs,MaxWall -n
   c. squeue -u ahmalik_umass_edu -o "%i %P %j %T %R %l" — current jobs
   d. cat /etc/motd — cluster announcements
   e. module avail cuda 2>&1 | grep -i "cuda/" | head -5 — available CUDA
3. Parse results into structured data
4. Write docs/cluster-profile.md with:
   - Partition table (name, active, max walltime, nodes, CPUs/node, memory, GPUs)
   - Account limits for ahmalik_umass_edu under pi_taqi_umass_edu
   - Available GPU types (from sinfo -o "%G")
   - Current active jobs count
   - CUDA versions available
   - Recommended resource combinations based on findings
5. Print: "Cluster profile written to docs/cluster-profile.md"
```

---

### Wave 2 — Sequential (after Wave 1 commits)

#### Task C: MCP Server (hpc_server.py)

Python stdio MCP server. Use the `mcp` Python SDK.

**mcp/requirements.txt**
```
mcp>=1.0.0
aiosqlite>=0.19.0
```

**mcp/hpc_server.py** — 8 tools:

```python
import os, json, asyncio, subprocess, sqlite3
from pathlib import Path
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

PLUGIN_ROOT = Path(__file__).resolve().parents[1]

def get_project_dir() -> Path:
    return Path(os.environ.get("HPC_PROJECT_DIR", os.getcwd()))

# Tool: unity_status(campaign?) 
#   → query .unity_state/*.db for job state counts
#   → no SSH required

# Tool: unity_jobs(campaign?)
#   → full job list from DB: job_id, exp, partition, status, attempt, submitted_at

# Tool: unity_results(campaign?, metric?)
#   → parse _results/<campaign>/*.out for val_bpb, peak_vram_mb, mfu_percent, etc.
#   → for multi-node: merge per-node files (same base name, different _<node>.out)

# Tool: unity_results_tsv()
#   → read results.tsv → return list of dicts

# Tool: unity_submit(exp, partition="gpu", nodes=1, dry_run=False)
#   → build and run: ssh $UNITY_HOST sbatch ...job_template.sh
#   → return job_id or None (dry_run)
#   → env from project's unityHPC/.env

# Tool: unity_logs(campaign?, lines=50)
#   → read last N lines of .unity_state/<campaign>.monitor.log

# Tool: unity_ssh(command: str)
#   → subprocess.run(["ssh", UNITY_HOST, command])
#   → returns {"stdout": ..., "stderr": ..., "returncode": ...}
#   → UNITY_HOST from project's unityHPC/.env

# Tool: unity_traffic()
#   → read PLUGIN_ROOT/cluster-intel/analysis/traffic_summary.json
#   → returns {"queue_depth": N, "est_wait_min": N, "recommendation": "gpu|gpu-preempt", "last_updated": "..."}
#   → if file missing: return {"error": "traffic data not yet available — run unity-hpc:setup to start poller"}
```

Key implementation notes:
- All DB access uses sqlite3 (sync) or aiosqlite (async). DB path: `{project_dir}/.unity_state/{campaign}.db`
- `unity_results`: grep pattern `r"^(val_bpb|peak_vram_mb|mfu_percent|training_seconds|total_tokens_M|num_params_M):\s+([\d.]+)"` in .out files
- `unity_submit`: reads env from `{project_dir}/unityHPC/.env` before building sbatch command
- `unity_traffic`: reads from `PLUGIN_ROOT/cluster-intel/analysis/traffic_summary.json`

#### Task D: Cluster Intelligence

**cluster-intel/cluster-poller.sh** — runs on Unity login node in tmux
```bash
#!/usr/bin/env bash
# Polls squeue/sinfo every POLL_INTERVAL seconds, appends CSV row
# Login-node safe: only read-only SLURM commands, <1s per poll
POLL_INTERVAL="${POLL_INTERVAL:-900}"   # 15 min default
OUT="/work/pi_taqi_umass_edu/ali/cluster-intel/traffic.csv"
mkdir -p "$(dirname "$OUT")"
# Write header if new file
header="timestamp,gpu_total,gpu_running,gpu_pending,gpu_preempt_running,gpu_preempt_pending,nodes_idle,nodes_alloc,nodes_down,my_jobs_running,my_jobs_pending"
[ ! -f "$OUT" ] && echo "$header" >> "$OUT"
while true; do
  TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  GPU_R=$(squeue -p gpu -h -t R --noheader 2>/dev/null | wc -l)
  GPU_PD=$(squeue -p gpu -h -t PD --noheader 2>/dev/null | wc -l)
  GPP_R=$(squeue -p gpu-preempt -h -t R --noheader 2>/dev/null | wc -l)
  GPP_PD=$(squeue -p gpu-preempt -h -t PD --noheader 2>/dev/null | wc -l)
  TOTAL=$((GPU_R + GPU_PD))
  NODES_OUT=$(sinfo --noheader -o "%T %D" 2>/dev/null)
  IDLE=$(echo "$NODES_OUT" | awk '/idle/{s+=$2}END{print s+0}')
  ALLOC=$(echo "$NODES_OUT" | awk '/alloc/{s+=$2}END{print s+0}')
  DOWN=$(echo "$NODES_OUT" | awk '/down/{s+=$2}END{print s+0}')
  MY_R=$(squeue -u ahmalik_umass_edu -h -t R --noheader 2>/dev/null | wc -l)
  MY_PD=$(squeue -u ahmalik_umass_edu -h -t PD --noheader 2>/dev/null | wc -l)
  echo "$TS,$TOTAL,$GPU_R,$GPU_PD,$GPP_R,$GPP_PD,$IDLE,$ALLOC,$DOWN,$MY_R,$MY_PD" >> "$OUT"
  sleep "$POLL_INTERVAL"
done
```

**cluster-intel/analyze-traffic.py** — local analysis script
```python
#!/usr/bin/env python3
"""Analyze Unity cluster traffic CSV and produce reports + traffic_summary.json."""
import json, sys
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

INTEL_DIR = Path(__file__).parent
ANALYSIS_DIR = INTEL_DIR / "analysis"
ANALYSIS_DIR.mkdir(exist_ok=True)

def load_data(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, parse_dates=["timestamp"])
    df["hour"] = df["timestamp"].dt.hour
    df["dow"] = df["timestamp"].dt.day_name()   # Monday, Tuesday...
    df["weekday"] = df["timestamp"].dt.weekday  # 0=Mon
    return df

def heatmap_queue_depth(df: pd.DataFrame):
    """Hourly average GPU queue depth heatmap (7 days × 24 hours)."""
    pivot = df.pivot_table(values="gpu_running", index="dow", columns="hour", aggfunc="mean")
    day_order = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
    pivot = pivot.reindex([d for d in day_order if d in pivot.index])
    fig, ax = plt.subplots(figsize=(14, 4))
    im = ax.imshow(pivot.values, aspect="auto", cmap="YlOrRd")
    ax.set_xticks(range(24)); ax.set_xticklabels(range(24), fontsize=8)
    ax.set_yticks(range(len(pivot))); ax.set_yticklabels(pivot.index, fontsize=9)
    ax.set_xlabel("Hour (UTC)"); ax.set_title("Average GPU Running Jobs — Hourly Heatmap")
    plt.colorbar(im, ax=ax, label="avg running jobs")
    fig.tight_layout()
    fig.savefig(ANALYSIS_DIR / "heatmap_queue_depth.png", dpi=150)
    plt.close()

def gpu_availability_plot(df: pd.DataFrame):
    """Line chart: GPU idle nodes over time."""
    fig, ax = plt.subplots(figsize=(14, 3))
    ax.fill_between(df["timestamp"], df["nodes_idle"], alpha=0.4, color="#3FB950")
    ax.plot(df["timestamp"], df["nodes_idle"], color="#3FB950", linewidth=0.8)
    ax.set_ylabel("Idle nodes"); ax.set_title("GPU Node Availability Over Time")
    ax.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%m/%d %Hh"))
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(ANALYSIS_DIR / "gpu_availability_windows.png", dpi=150)
    plt.close()

def compute_summary(df: pd.DataFrame) -> dict:
    """Compute best/worst submit windows and current queue state."""
    p75 = df["gpu_running"].quantile(0.75)
    p25 = df["gpu_pending"].quantile(0.25)
    
    # Best hours: pending < p25 threshold
    hourly_pending = df.groupby("hour")["gpu_pending"].mean()
    best_hours = hourly_pending[hourly_pending < p25].index.tolist()
    
    # Peak hours: running > p75 threshold
    hourly_running = df.groupby("hour")["gpu_running"].mean()
    peak_hours = hourly_running[hourly_running > p75].index.tolist()
    
    # Last 3 rows for current state
    recent = df.tail(3)
    current_running = int(recent["gpu_running"].mean().round())
    current_pending = int(recent["gpu_pending"].mean().round())
    
    # Rough wait estimate: pending / max(running, 1) * avg_job_duration_min
    # Assume avg job ~30 min on gpu partition; ~10 min on gpu-preempt
    est_wait_gpu = int((current_pending / max(current_running, 1)) * 30)
    est_wait_preempt = max(est_wait_gpu // 3, 5)
    
    rec = "gpu" if current_pending < 10 else "gpu-preempt"
    
    return {
        "queue_depth": current_running + current_pending,
        "current_running": current_running,
        "current_pending": current_pending,
        "est_wait_min": {"gpu": est_wait_gpu, "gpu-preempt": est_wait_preempt},
        "recommendation": rec,
        "best_submit_hours_utc": sorted(best_hours),
        "peak_hours_utc": sorted(peak_hours),
        "last_updated": df["timestamp"].max().isoformat() if len(df) else None,
        "data_points": len(df),
    }

def write_peak_report(df: pd.DataFrame, summary: dict):
    lines = [
        "# Unity Cluster Traffic Analysis",
        f"\nData points: {summary['data_points']}",
        f"Last updated: {summary['last_updated']}",
        "\n## Current State",
        f"- GPU running: {summary['current_running']}",
        f"- GPU pending: {summary['current_pending']}",
        f"- Estimated wait: {summary['est_wait_min']['gpu']} min (gpu) / {summary['est_wait_min']['gpu-preempt']} min (gpu-preempt)",
        f"- Recommendation: use `{summary['recommendation']}` partition",
        "\n## Best Submit Times (UTC hours)",
        f"Hours with lowest queue depth: {summary['best_submit_hours_utc']}",
        "\n## Peak Contention Hours (UTC)",
        f"Hours with highest queue depth: {summary['peak_hours_utc']}",
    ]
    (ANALYSIS_DIR / "peak_hours_report.md").write_text("\n".join(lines))

def main():
    csv_path = INTEL_DIR / "traffic.csv"
    if not csv_path.exists():
        print(f"No traffic.csv found at {csv_path}", file=sys.stderr)
        print("Start the poller with: hpc-tmux start cluster-intel 'bash /work/pi_taqi_umass_edu/ali/cluster-intel/cluster-poller.sh'")
        sys.exit(1)
    df = load_data(csv_path)
    if len(df) < 5:
        print(f"Only {len(df)} data points — need more data. Come back after a few hours.")
        sys.exit(0)
    heatmap_queue_depth(df)
    gpu_availability_plot(df)
    summary = compute_summary(df)
    write_peak_report(df, summary)
    (ANALYSIS_DIR / "traffic_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"Analysis complete → {ANALYSIS_DIR}/")
    print(f"Recommendation: use '{summary['recommendation']}' partition")
    print(f"Estimated wait: {summary['est_wait_min'][summary['recommendation']]} min")

if __name__ == "__main__":
    main()
```

**cluster-intel/analysis/.gitkeep** — empty file to track dir

---

## Testing Strategy

| Component | How to verify |
|---|---|
| scripts/ | Run with `--help` or no args; check exit codes manually. `hpc-status` with no .unity_state/ → exit 2. |
| skills/ | Read SKILL.md files; check for completeness and correct MCP tool names (`mcp__unity-hpc__*`). |
| MCP server | `echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \| python mcp/hpc_server.py` — should list 8 tools. |
| analyze-traffic.py | `python cluster-intel/analyze-traffic.py` with a sample traffic.csv (5 rows of test data). |
| cluster-poller.sh | Shellcheck for syntax. Run locally with fake squeue/sinfo aliases to verify CSV format. |
| job_template.sh | Shellcheck. Test multi-node branch: `SLURM_NODES=2 bash -n templates/job_template.sh`. |

---

## Implementation Notes

- All scripts: start with `#!/usr/bin/env bash`, `set -euo pipefail`
- All scripts: resolve env file relative to `HPC_PROJECT_DIR` or `$PWD`
- MCP tool names: must match exactly what Claude sees — `mcp__unity-hpc__<tool_name>` (server name from claude_desktop_config.json key `"unity-hpc"`)
- Skills: use imperative tone, numbered steps. Include expected output for each step so Claude knows if something failed.
- Don't write comments in skills explaining the skill format — just write the instructions.

---

## Commit Strategy

Each wave produces one commit per agent. Wave 1 agents commit independently (no conflicts — different file trees). Wave 2 commits after Wave 1 is merged.

```
feat: add plugin scaffold, scripts, templates, and agents  ← Agent A
feat: add all 8 skill SKILL.md files                       ← Agent B
feat: add MCP server with 8 tools                          ← Task C
feat: add cluster-intel poller and traffic analysis        ← Task D
```
