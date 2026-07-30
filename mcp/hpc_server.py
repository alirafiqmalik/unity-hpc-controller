#!/usr/bin/env python3
"""
Unity HPC MCP server — stdio transport.
Exposes 12 tools for reading campaign state, job status, results,
logs, cluster queue, historical usage, the shared cluster profile, this
project's own job telemetry, this server's own health, and running SSH
commands on Unity.

Reports metrics a job printed; it never names one itself. A project declares
its own in unityHPC/metrics.json (see lib/metrics.py).

Registered automatically by the plugin's .mcp.json; no manual config needed.
Only third-party dependency is `mcp` — the analysis libraries (pandas, plotext)
belong to cluster-intel/, not to this server.

Campaign state resolves from PROJECT_DIR if set, else the working directory.
Shared cluster-intel data (usage history, cluster profile) resolves to
$UNITY_HPC_DATA (default ~/.local/share/unity-hpc) — a machine-wide, version-
independent store shared by every project, NOT the versioned plugin dir.

Tools are invoked as mcp__unity-hpc__<tool_name> in skills.
"""

import asyncio
import json
import os
import subprocess
import sqlite3
import sys
import time
import glob
from pathlib import Path
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

# The repo root holds lib/; make it importable however this file is launched
# (plugin cache, checkout, or a spec-loaded test import).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import queries as _queries  # noqa: E402
from lib import campaign as _campaign  # noqa: E402
from lib import metrics as _metrics  # noqa: E402

server = Server("unity-hpc")

#: This process runs the code that existed when it started. A plugin upgrade
#: rewrites those files but cannot restart the server, so a session can keep
#: talking to code that was replaced minutes ago — reading the fixed source and
#: seeing the old behaviour, with nothing to indicate why. Recorded at import so
#: unity_doctor can detect exactly that.
_SOURCE = Path(__file__).resolve()
_LOADED_AT = time.time()


def _project_dir() -> Path:
    """Return the project root from PROJECT_DIR env or cwd."""
    d = os.environ.get("PROJECT_DIR", "")
    return Path(d) if d else Path.cwd()


def _state_dir() -> Path:
    return _project_dir() / ".unity_state"


def _latest_db() -> Path | None:
    """Return the most recently modified campaign DB, or None."""
    dbs = sorted(_state_dir().glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return dbs[0] if dbs else None


def _db_query(db_path: Path, sql: str, params: tuple = ()) -> list[dict]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        cur = con.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        con.close()


def _parse_env_value(raw: str) -> str:
    """Take the value out of one `.env` right-hand side, the way bash would.

    The generated .env documents itself with trailing comments
    (`UNITY_HOST="unity"   # ssh alias`). Stripping only the quotes left the
    comment glued to the value, so `_ssh` was handed `unity"   # ssh alias`
    as a hostname — every SSH-backed tool failed with "hostname contains
    invalid characters" in any project scaffolded from a template that
    comments that line."""
    raw = raw.strip()
    if not raw:
        return ""
    if raw[0] in "\"'":
        quote = raw[0]
        end = raw.find(quote, 1)
        return raw[1:end] if end != -1 else raw[1:]
    for marker in (" #", "\t#"):
        cut = raw.find(marker)
        if cut != -1:
            raw = raw[:cut]
    return raw.strip()


def _env_value(key: str, default: str = "") -> str:
    """Read one value from the project's unityHPC/.env.

    Last assignment wins, because that is what `set -a; . .env` does: the
    generated .env ships blank placeholders and users append their real values
    below them. Taking the first match read those placeholders and silently
    disabled every feature that depended on them."""
    env_path = _project_dir() / "unityHPC" / ".env"
    if not env_path.exists():
        return default
    value = default
    for line in env_path.read_text(errors="replace").splitlines():
        line = line.strip()
        if line.startswith("#") or not line.startswith(f"{key}="):
            continue
        candidate = _parse_env_value(line.split("=", 1)[1])
        if candidate:
            value = candidate
    return value


def _ssh(cmd: str, timeout: int = 30) -> tuple[str, str, int]:
    """Run a command on Unity via SSH. Returns (stdout, stderr, returncode)."""
    unity_host = _env_value("UNITY_HOST", "unity")
    proc = subprocess.run(
        ["ssh", unity_host, cmd],
        capture_output=True, text=True, timeout=timeout
    )
    return proc.stdout, proc.stderr, proc.returncode


# ─── Tool handlers ────────────────────────────────────────────────────────────

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="unity_status",
            description="Job state counts for this project's latest (or named) campaign. Instant local read of the job ledger, refreshed from shared telemetry; no SSH.",
            inputSchema={
                "type": "object",
                "properties": {
                    "campaign": {"type": "string", "description": "Campaign name. Omit for latest."}
                }
            }
        ),
        types.Tool(
            name="unity_jobs",
            description="This project's jobs for a campaign: job_id, exp, partition, status and the hardware each landed on. Local read; no SSH.",
            inputSchema={
                "type": "object",
                "properties": {
                    "campaign": {"type": "string", "description": "Campaign name. Omit for latest."}
                }
            }
        ),
        types.Tool(
            name="unity_results",
            description="Numeric `key: value` pairs each fetched job printed to stdout. Metric-agnostic — reports whatever the job chose to print.",
            inputSchema={
                "type": "object",
                "properties": {
                    "campaign": {"type": "string", "description": "Campaign name. Omit for latest."}
                }
            }
        ),
        types.Tool(
            name="unity_results_tsv",
            description=("Read one bounded page of local results.tsv as structured data. "
                         "Rows use the file's own header."),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500,
                              "description": "Maximum rows to return (default 100)."},
                    "offset": {"type": "integer", "minimum": 0,
                               "description": "Zero-based row offset (default 0)."},
                },
            },
        ),
        types.Tool(
            name="unity_submit",
            description=(
                "Submit a job to SLURM via the project's unityHPC/run.sh dispatcher. "
                "Works for any job type (CPU-only, GPU, or multi-node). Returns the "
                "scheduler's response, or guidance if the project has no scaffold yet."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "exp": {"type": "string", "description": "Job name — used for the SLURM job name and log filenames"},
                    "extra_args": {"type": "string", "description": "Extra flags passed to sbatch, e.g. '--qos=short'. Use '--dry-run' to preview without submitting."},
                    "campaign": {"type": "string", "description": "Group this job with others under one campaign. Omit for today's UTC date."}
                },
                "required": ["exp"]
            }
        ),
        types.Tool(
            name="unity_logs",
            description="Tail the newest recorded job's SLURM output — live over SSH, falling back to a fetched copy.",
            inputSchema={
                "type": "object",
                "properties": {
                    "campaign": {"type": "string", "description": "Campaign name. Omit for the latest."},
                    "lines": {"type": "integer", "description": "Lines to tail (default 20)"}
                }
            }
        ),
        types.Tool(
            name="unity_ssh",
            description="Run a read-only command on Unity login node via SSH. Blocks dangerous writes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "Shell command to run on Unity"},
                    "timeout": {"type": "integer", "description": "Seconds to wait (default 60, or $UNITY_SSH_TIMEOUT). Raise it for wide sacct queries."}
                },
                "required": ["cmd"]
            }
        ),
        types.Tool(
            name="unity_traffic",
            description="Live-ish queue signal + best/worst submit hours from cluster-intel usage summary.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="unity_cluster_profile",
            description="Return the shared cluster profile (partitions, GPU types, account limits, capacity) written by unity-hpc:recon. Shared by all projects; cwd-independent.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="unity_my_jobs",
            description=("This project's own submitted jobs, enriched with the "
                         "real hardware and efficiency each got (from shared "
                         "telemetry). Jobs not yet collected show as pending."),
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="unity_doctor",
            description=("Report which plugin version this server process is actually "
                         "running and whether it is stale (code upgraded since the "
                         "session started), plus project scaffold, ledger, metric "
                         "declaration and shared-data health. Call this first when "
                         "behaviour disagrees with the source."),
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="unity_usage",
            description="Query historical cluster usage (fixed time slots) for a window: GPU allocation by type, jobs, memory. Reads usage.db built from sacct history.",
            inputSchema={
                "type": "object",
                "properties": {
                    "hours": {"type": "integer", "description": "Look-back window in hours (default 168 = 7d)"},
                    "gpu_type": {"type": "string", "description": "Filter to one GPU type (e.g. h100)"}
                }
            }
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    result = await _dispatch(name, arguments)
    return [types.TextContent(type="text", text=result)]


async def _dispatch(name: str, args: dict) -> str:
    if name == "unity_status":
        return _unity_status(args.get("campaign"))
    elif name == "unity_jobs":
        return _unity_jobs(args.get("campaign"))
    elif name == "unity_results":
        return _unity_results(args.get("campaign"))
    elif name == "unity_results_tsv":
        return _unity_results_tsv(args.get("limit"), args.get("offset"))
    elif name == "unity_submit":
        return _unity_submit(args["exp"], args.get("extra_args", ""),
                             args.get("campaign"))
    elif name == "unity_logs":
        return _unity_logs(args.get("campaign"), args.get("lines", 20))
    elif name == "unity_ssh":
        return _unity_ssh(args["cmd"], args.get("timeout"))
    elif name == "unity_cluster_profile":
        return _unity_cluster_profile()
    elif name == "unity_usage":
        return _unity_usage(args.get("hours", 168), args.get("gpu_type"))
    elif name == "unity_traffic":
        return _unity_traffic()
    elif name == "unity_my_jobs":
        return _unity_my_jobs()
    elif name == "unity_doctor":
        return _unity_doctor()
    return f"Unknown tool: {name}"


def _resolve_db(campaign: str | None) -> tuple[str, Path] | tuple[None, None]:
    if campaign:
        db = _state_dir() / f"{campaign}.db"
        return (campaign, db) if db.exists() else (None, None)
    db = _latest_db()
    if db is None:
        return None, None
    return db.stem, db


_NO_LEDGER = (
    "No jobs recorded for this project yet.\n"
    "Jobs are recorded when you submit through the dispatcher:\n"
    "  bash unityHPC/run.sh run <exp>      (or the unity_submit tool)\n"
    "If you submitted with sbatch directly, this project has no record of it — "
    "unity_ssh with an sacct query is the way to find it."
)


def _refresh(campaign: str | None) -> None:
    """Fold shared telemetry into the ledger. Local-only, never raises."""
    try:
        _campaign.refresh_from_telemetry(_project_dir(), campaign)
    except Exception:
        pass  # a stale read is fine; an exception here would blind the tool


def _stale_hint(rows: list[dict]) -> str | None:
    if any(r.get("status") not in _campaign.TERMINAL for r in rows):
        return ("\nSome jobs are not in a terminal state. These come from the "
                "ledger (refreshed from telemetry collected every ~15 min). "
                "For a live answer: bash unityHPC/run.sh status")
    return None


def _unity_status(campaign: str | None) -> str:
    _refresh(campaign)
    name = campaign or _campaign.latest_campaign(_project_dir())
    if name is None:
        return _NO_LEDGER
    rows = _campaign.jobs(_project_dir(), name)
    if not rows:
        return f"Campaign {name} has no recorded jobs."
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    lines = [f"Campaign: {name}"]
    for status in sorted(counts):
        lines.append(f"  {status:<14} {counts[status]}")
    hint = _stale_hint(rows)
    if hint:
        lines.append(hint)
    return "\n".join(lines)


def _unity_jobs(campaign: str | None) -> str:
    _refresh(campaign)
    name = campaign or _campaign.latest_campaign(_project_dir())
    if name is None:
        return _NO_LEDGER
    rows = _campaign.jobs(_project_dir(), name)
    if not rows:
        return f"Campaign {name} has no recorded jobs."
    header = f"{'job_id':<10} {'exp':<20} {'partition':<14} {'status':<14} {'hardware'}"
    lines = [f"Campaign: {name}", header, "-" * len(header)]
    for r in rows:
        lines.append(
            f"{str(r['job_id'] or ''):<10} {str(r['exp'] or ''):<20} "
            f"{str(r['partition'] or ''):<14} {str(r['status'] or ''):<14} "
            f"{r['hardware'] or '-'}"
        )
    hint = _stale_hint(rows)
    if hint:
        lines.append(hint)
    return "\n".join(lines)


#: keys a job might print that are not really metrics
_METRIC_SKIP = {"real", "user", "sys", "warning", "error", "note", "usage"}


def _parse_out_file(out_path: Path) -> dict:
    """Parse `key: value` numeric pairs a job printed to stdout.

    Deliberately metric-agnostic: this plugin serves every kind of SLURM job,
    so it reports whatever the job chose to print rather than looking for one
    domain's metrics. A job that prints nothing parseable yields {} — which the
    caller must report as "no metrics", not as an empty result set.
    """
    metrics: dict = {}
    try:
        text = out_path.read_text(errors="replace")
    except OSError:
        return metrics
    for line in text.splitlines():
        line = line.strip()
        if not line or ":" not in line or line.count(":") > 3:
            continue
        key, _, value = line.partition(":")
        key = key.strip().rstrip(":")
        if not key or len(key) > 40 or " " in key.strip() and len(key.split()) > 3:
            continue
        if key.lower() in _METRIC_SKIP:
            continue
        try:
            metrics[key] = float(value.strip().split()[0]) if value.strip() else None
        except (ValueError, IndexError):
            continue
        if metrics.get(key) is None:
            metrics.pop(key, None)
    return metrics


def _unity_results(campaign: str | None) -> str:
    """Parse metrics from _results/<campaign>/*.out files (source of truth)."""
    name = campaign or _campaign.latest_campaign(_project_dir())
    if name is None:
        return _NO_LEDGER

    results_dir = _project_dir() / "_results" / name
    if not results_dir.exists():
        return (f"Nothing fetched yet for campaign {name}. "
                f"Run /unity-hpc:fetch (bash unityHPC/run.sh fetch).")

    out_files = sorted(results_dir.glob("*.out"))
    if not out_files:
        return (f"No .out files in {results_dir}. The jobs may still be running, "
                f"or they wrote their output elsewhere.")

    parsed = {f.stem: _parse_out_file(f) for f in out_files}
    discovered: list[str] = []
    for metrics in parsed.values():
        for k in metrics:
            if k not in discovered:
                discovered.append(k)

    spec, spec_error = _metrics.load_with_error(_project_dir())
    footer: list[str] = []
    if spec_error:
        footer.append(spec_error)

    if not discovered:
        msg = [f"Campaign {name}: {len(out_files)} output file(s) fetched, but "
               f"none printed any `key: value` numeric lines.",
               f"Raw output is in {results_dir}."]
        declared = _metrics.missing_keys(spec, discovered)
        if declared:
            msg.append(f"This project declares {', '.join(declared)} in "
                       f"unityHPC/{_metrics.FILENAME}; no job printed them.")
        return "\n".join(msg + footer)

    keys = _metrics.order_keys(spec, discovered)
    width = max(len(s) for s in parsed) + 2
    labels = [spec.label(k) if spec else k for k in keys]
    header = f"{'job':<{width}}" + "".join(f"{lab:>16}" for lab in labels)
    lines = [f"Campaign: {name}", header, "-" * len(header)]
    for stem in sorted(parsed):
        row = f"{stem:<{width}}"
        for k in keys:
            v = parsed[stem].get(k)
            row += f"{v:>16.6g}" if isinstance(v, (int, float)) else f"{'-':>16}"
        lines.append(row)

    winner = _metrics.best(spec, parsed)
    if winner and spec is not None:
        lines.append(f"\nBest by {spec.label(spec.primary)} ({spec.goal}): "
                     f"{winner[0]} = {winner[1]:.6g}")
    missing = _metrics.missing_keys(spec, discovered)
    if missing:
        footer.append(f"Declared but not printed by any job: {', '.join(missing)}")
    if spec is None and not spec_error:
        footer.append("Metrics are whatever each job printed. To rank results, "
                      f"declare a primary metric in unityHPC/{_metrics.FILENAME}.")
    lines.append("")
    lines.append(f"{len(out_files)} job(s). " + " ".join(footer))
    return "\n".join(lines).rstrip()


def _unity_results_tsv(limit: int | None = None, offset: int | None = None) -> str:
    """Return results.tsv keyed by its own header row.

    Header-driven on purpose: every project chooses its own columns, and a
    hardcoded schema silently dropped rows that did not match it.  The page is
    bounded so a long-running project cannot exhaust an MCP response."""
    try:
        page_limit = 100 if limit is None else int(limit)
    except (TypeError, ValueError):
        page_limit = 100
    try:
        page_offset = 0 if offset is None else int(offset)
    except (TypeError, ValueError):
        page_offset = 0
    page_limit = max(1, min(page_limit, 500))
    page_offset = max(0, page_offset)

    tsv = _project_dir() / "results.tsv"
    if not tsv.exists():
        return "results.tsv not found. Run /unity-hpc:setup to initialise it."
    lines = [l for l in tsv.read_text().splitlines() if l.strip()]
    if not lines:
        return "results.tsv is empty."
    columns = lines[0].split("\t")
    if len(lines) == 1:
        return json.dumps({"columns": columns, "rows": [], "total_rows": 0,
                           "offset": page_offset, "limit": page_limit,
                           "next_offset": None})
    all_rows = []
    for line in lines[1:]:
        parts = line.split("\t")
        row = {columns[i]: (parts[i] if i < len(parts) else "")
               for i in range(len(columns))}
        if len(parts) > len(columns):
            row["_extra"] = parts[len(columns):]
        all_rows.append(row)
    rows = all_rows[page_offset:page_offset + page_limit]
    next_offset = page_offset + len(rows)
    if next_offset >= len(all_rows):
        next_offset = None
    return json.dumps({"columns": columns, "rows": rows,
                       "total_rows": len(all_rows), "offset": page_offset,
                       "limit": page_limit, "next_offset": next_offset})


def _unity_submit(exp: str, extra_args: str, campaign: str | None = None) -> str:
    runner = _project_dir() / "unityHPC" / "run.sh"
    if not runner.exists():
        return (
            f"No job scaffold in this project: {runner} does not exist.\n"
            "Run /unity-hpc:setup to generate unityHPC/{run.sh,job_template.sh,"
            "sync.sh,.env} for this project (it will ask whether the project is "
            "cpu, gpu or ml).\n"
            "If you keep your dispatcher elsewhere, point PROJECT_DIR at the "
            "directory that contains unityHPC/."
        )

    cmd = ["bash", str(runner), "run", exp]
    if campaign:
        cmd += ["--campaign", campaign]
    if extra_args:
        cmd += extra_args.split()
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_project_dir()))
    output = (proc.stdout + proc.stderr).strip()
    if not output:
        return f"run.sh exited {proc.returncode} with no output."
    dry_run = "[dry-run]" in output
    if not dry_run and "Recorded job" not in output and proc.returncode == 0:
        output += ("\n\n[unity-hpc] The job was not recorded in the ledger — "
                   "unity_status/unity_jobs will not see it. Note the job id above.")
    return output


def _unity_logs(campaign: str | None, lines: int) -> str:
    """Tail the newest recorded job's stdout on the cluster.

    There is no background monitor and no monitor log — that machinery was
    removed. The useful answer to "what is my job printing" is the job's own
    SLURM output file, read live over SSH, falling back to a fetched copy."""
    name = campaign or _campaign.latest_campaign(_project_dir())
    if name is None:
        return _NO_LEDGER
    rows = _campaign.jobs(_project_dir(), name)
    if not rows:
        return f"Campaign {name} has no recorded jobs."
    job = rows[-1]
    stem = f"{job['exp']}-{job['job_id']}"

    local = _project_dir() / "_results" / name / f"{stem}.out"
    remote_dir = _env_value("REMOTE_DIR")
    if remote_dir:
        try:
            stdout, stderr, rc = _ssh(
                f"tail -n {int(lines)} {remote_dir}/_slurm/{stem}.out", timeout=30)
            if rc == 0 and stdout.strip():
                return f"--- {stem}.out (last {lines} lines, live) ---\n{stdout.strip()}"
            if not local.exists():
                return (f"No output yet for job {job['job_id']} ({job['status']}).\n"
                        f"{stderr.strip()}" if stderr.strip() else
                        f"No output yet for job {job['job_id']} ({job['status']}).")
        except subprocess.TimeoutExpired:
            pass  # fall through to the fetched copy
        except Exception:
            pass

    if local.exists():
        tail = local.read_text(errors="replace").splitlines()[-int(lines):]
        return f"--- {stem}.out (last {lines} lines, fetched copy) ---\n" + "\n".join(tail)
    return (f"Could not read output for job {job['job_id']}. "
            f"Check SSH, or fetch it: bash unityHPC/run.sh fetch --campaign {name}")




_BLOCKED_PATTERNS = ["rm ", "rmdir", "mv ", "cp ", "> ", ">>", "kill ", "pkill", "shutdown"]

#: sacct over a wide window on a busy slurmdbd routinely needs more than 30s.
#: Raise with $UNITY_SSH_TIMEOUT, or per call with the `timeout` argument.
def _default_ssh_timeout() -> int:
    try:
        return max(5, int(os.environ.get("UNITY_SSH_TIMEOUT", "60")))
    except ValueError:
        return 60


def _unity_ssh(cmd: str, timeout: int | None = None) -> str:
    for pattern in _BLOCKED_PATTERNS:
        if pattern in cmd:
            return f"Blocked: '{pattern}' is not allowed via unity_ssh (use hpc-ssh script for write ops)."
    limit = timeout if timeout and timeout > 0 else _default_ssh_timeout()
    try:
        stdout, stderr, rc = _ssh(cmd, timeout=limit)
        parts = []
        if stdout.strip():
            parts.append(stdout.strip())
        if stderr.strip():
            parts.append(f"[stderr] {stderr.strip()}")
        if rc != 0:
            parts.append(f"[exit {rc}]")
        return "\n".join(parts) if parts else "(no output)"
    except subprocess.TimeoutExpired:
        return (f"SSH command timed out after {limit}s. Heavy sacct/squeue reads "
                f"can exceed it — retry with a larger `timeout`, narrow the query "
                f"(add -S/-E or fewer fields), or raise $UNITY_SSH_TIMEOUT.")
    except Exception as e:
        return f"SSH error: {e}"


def _data_dir() -> Path:
    """Machine-wide cluster-intel data root — shared by every project and
    INDEPENDENT of the plugin version (so a plugin update never orphans it).
    Override with $UNITY_HPC_DATA; defaults to $XDG_DATA_HOME/unity-hpc or
    ~/.local/share/unity-hpc. (Code lives in the versioned plugin install; data
    lives here.)"""
    d = os.environ.get("UNITY_HPC_DATA")
    if d:
        return Path(d).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "unity-hpc"


def _config_path() -> Path:
    return _data_dir() / "cluster-config.json"


def _summaries_db() -> Path:
    return _data_dir() / "summaries.db"


def _unity_cluster_profile() -> str:
    """Render the shared cluster-config.json as human-readable markdown.

    Cwd-independent; written by unity-hpc:recon through a locked merge."""
    p = _config_path()
    if not p.exists():
        return (f"No shared cluster config yet at {p}. "
                "Run /unity-hpc:recon to generate it (shared across all projects).")
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return f"cluster-config.json unreadable: {e}"
    return _render_cluster_config(data)


def _render_cluster_config(data: dict) -> str:
    lines = [f"# Unity Cluster Profile",
             f"_cluster: {data.get('cluster', '?')}  ·  "
             f"slurm: {data.get('slurm_version', '?')}  ·  "
             f"schema: {data.get('schema_version', '?')}_", ""]

    parts = data.get("partitions") or {}
    if parts:
        lines += ["## Partitions",
                  "| Partition | Nodes | GPU types | Max walltime | Access |",
                  "|---|---|---|---|---|"]
        for name in sorted(parts):
            p = parts[name]
            gt = ", ".join(p.get("gpu_types") or []) or "—"
            lines.append(f"| {name} | {p.get('nodes', '?')} | {gt} | "
                         f"{p.get('max_walltime', '?')} | {p.get('access', '?')} |")
        lines.append("")

    fleet = data.get("gpu_fleet") or {}
    if fleet:
        lines += ["## GPU fleet (accessible)",
                  "| Type | Accessible | VRAM (GB) | Compute cap. |",
                  "|---|---|---|---|"]
        for name in sorted(fleet):
            g = fleet[name]
            vram = ", ".join(str(v) for v in (g.get("vram_gb") or [])) or "?"
            lines.append(f"| {name} | {g.get('total_accessible', '?')} | {vram} | "
                         f"{g.get('compute_capability', '?')} |")
        lines.append("")

    al = data.get("account_limits") or {}
    if al:
        lines += ["## Account limits",
                  f"- account: {al.get('account', '?')}",
                  f"- max_submit_jobs: {al.get('max_submit_jobs')}",
                  f"- max_jobs: {al.get('max_jobs')}",
                  f"- max_wall: {al.get('max_wall')}"]
        for q in al.get("qos") or []:
            lines.append(f"- qos {q.get('name')}: max_wall={q.get('max_wall')} "
                         f"priority={q.get('priority')}")
        lines.append("")

    fs = data.get("fairshare") or {}
    if fs:
        lines += [f"## Fair-share",
                  f"- factor: {fs.get('factor')}  (observed {fs.get('observed_utc', '?')})", ""]

    storage = data.get("storage") or {}
    if storage:
        lines.append("## Storage")
        for vol in sorted(storage):
            s = storage[vol]
            lines.append(f"- {vol}: {s.get('used_gb', '?')} / {s.get('total_gb', '?')} GB")
        lines.append("")

    prov = data.get("provenance") or {}
    if prov:
        lines += ["## Provenance",
                  f"- last write: {prov.get('last_write_utc', '?')} "
                  f"by {prov.get('last_writer', '?')}",
                  f"- writers seen: {', '.join(prov.get('writers_seen') or []) or '—'}"]
    return "\n".join(lines)


def _unity_traffic() -> str:
    """Best/worst submit hours by GPU utilization, from summaries.db."""
    db = _summaries_db()
    if not db.exists():
        return json.dumps({
            "status": "no_data",
            "message": "No summaries yet. Run hpc-sync-telemetry to pull cluster "
                       "telemetry and build summaries.db.",
            "recommendation": "proceed_with_caution"})
    try:
        rows = _db_query(db,
            "SELECT substr(hour_utc,12,2) AS hour, ROUND(AVG(util_mean),3) AS util, "
            "SUM(samples) AS samples FROM hourly_resource "
            "WHERE resource_kind='gpu_type' GROUP BY hour ORDER BY util ASC")
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            return json.dumps({
                "status": "no_data",
                "message": "summaries.db is missing the hourly_resource table. "
                           "Run hpc-sync-telemetry to pull cluster telemetry and "
                           "build summaries.db.",
                "recommendation": "proceed_with_caution"})
        return json.dumps({"status": "error", "message": str(e)})
    if not rows:
        return json.dumps({"status": "no_data",
                           "message": "summaries.db has no gpu_type rows yet. "
                                      "Run hpc-sync-telemetry.",
                           "recommendation": "proceed_with_caution"})
    return json.dumps({
        "status": "ok",
        "best_hours_utc": [r["hour"] for r in rows[:3]],
        "worst_hours_utc": [r["hour"] for r in rows[-3:]],
        "by_hour_utc": rows}, indent=2)


def _unity_usage(hours: int, gpu_type: str | None) -> str:
    """GPU-type utilization over a window, from summaries.db hourly_resource."""
    db = _summaries_db()
    if not db.exists():
        return json.dumps({
            "status": "no_data",
            "message": "No summaries yet. Run hpc-sync-telemetry to pull cluster "
                       "telemetry and build summaries.db."})
    from datetime import datetime, timedelta, timezone
    hours = max(1, min(int(hours), 24 * 3650))
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:00:00Z")
    sql = ("SELECT resource_id AS gpu_type, ROUND(AVG(util_mean),3) AS avg_util, "
           "ROUND(MAX(util_max),3) AS peak_util, ROUND(AVG(free_ratio),3) AS avg_free, "
           "SUM(samples) AS samples FROM hourly_resource "
           "WHERE resource_kind='gpu_type' AND hour_utc >= ? ")
    params: tuple = (cutoff,)
    if gpu_type:
        sql += "AND resource_id = ? "
        params += (gpu_type,)
    sql += "GROUP BY resource_id ORDER BY avg_util DESC"
    try:
        rows = _db_query(db, sql, params)
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            return json.dumps({
                "status": "no_data",
                "message": "summaries.db is missing the hourly_resource table. "
                           "Run hpc-sync-telemetry to pull cluster telemetry and "
                           "build summaries.db."})
        return json.dumps({"status": "error", "message": str(e)})
    if not rows:
        return json.dumps({
            "status": "no_data",
            "message": "summaries.db has no gpu_type rows for this window. "
                       "Run hpc-sync-telemetry."})
    return json.dumps({"window_hours": hours, "since_utc": cutoff,
                       "gpu_type_filter": gpu_type, "by_gpu_type": rows}, indent=2)


def _project_job_ids() -> list[str]:
    """Every job_id this project has submitted, across its .unity_state campaigns."""
    ids: list[str] = []
    for db in sorted(_state_dir().glob("*.db")):
        try:
            ids += [r["job_id"] for r in _db_query(db, "SELECT job_id FROM jobs")]
        except sqlite3.Error:
            # A campaign DB without a jobs table (or an unreadable one) simply
            # contributes no ids — never a crash for the whole project.
            continue
    return [j for j in dict.fromkeys(ids) if j]


def _unity_my_jobs() -> str:
    """This project's own jobs joined against the shared task_run telemetry.

    Read-only over both stores. Jobs not yet collected are reported as
    "pending" rather than dropped, and an absent summaries.db yields guidance
    instead of an error (I6)."""
    job_ids = _project_job_ids()
    if not job_ids:
        return json.dumps({"jobs": [],
                           "note": "No jobs submitted from this project yet."})
    telem = {r["job_id"]: r for r in _queries.task_runs_for_jobs(job_ids)}
    jobs = []
    for jid in job_ids:
        t = telem.get(jid)
        if t is None:
            jobs.append({"job_id": jid, "telemetry": "pending"})
        else:
            jobs.append({"job_id": jid, "hardware": t["hardware"],
                         "elapsed_s": t["elapsed_s"], "wait_s": t["wait_s"],
                         "cpu_eff": t["cpu_eff"], "mem_eff": t["mem_eff"],
                         "state": t["state"]})
    result: dict = {"jobs": jobs}
    if not telem:
        result["note"] = ("No telemetry for these jobs yet. Run hpc-sync-telemetry "
                          "to pull cluster telemetry and build summaries.")
    return json.dumps(result, indent=2)


def _plugin_version(root: Path) -> str | None:
    try:
        return json.loads((root / ".claude-plugin" / "plugin.json").read_text()).get("version")
    except (OSError, ValueError, AttributeError):
        return None


def _installed_registry() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    root = Path(base).expanduser() if base else Path.home() / ".claude"
    return root / "plugins" / "installed_plugins.json"


def _installed_version() -> tuple[str | None, str | None]:
    """(version, installPath) this machine has registered for unity-hpc.

    Prefers the entry whose projectPath contains the current project, so a
    machine with several projects reports the one that matters here."""
    try:
        data = json.loads(_installed_registry().read_text())
        entries = data.get("plugins", {}).get("unity-hpc@phd-agentic-tools", [])
    except (OSError, ValueError, AttributeError):
        return None, None
    if not entries:
        return None, None
    project = str(_project_dir())
    for entry in entries:
        if project.startswith(str(entry.get("projectPath", "\0"))):
            return entry.get("version"), entry.get("installPath")
    return entries[0].get("version"), entries[0].get("installPath")


def _scaffold_version(project: Path) -> str | None:
    """The plugin version that generated this project's dispatcher.

    None means either no dispatcher, or one generated before stamping existed
    (<= 0.8.1) — which is itself the answer: it predates the stamp."""
    runner = project / "unityHPC" / "run.sh"
    if not runner.exists():
        return None
    try:
        for line in runner.read_text(errors="replace").splitlines()[:40]:
            if line.startswith("UNITY_SCAFFOLD_VERSION="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        return None
    return None


def _strip_stamp(text: str) -> str:
    return "\n".join(l for l in text.splitlines()
                     if not l.startswith("UNITY_SCAFFOLD_VERSION="))


def _dispatcher_differs(project: Path) -> bool | None:
    """True if the project's run.sh no longer matches the canonical template.

    Compared by content, not by version number: releases that touch only the
    server leave the template alone, and flagging every project stale on those
    would train people to ignore the signal that matters. The version stamp
    itself is excluded from the comparison — it is the one line guaranteed to
    differ. None means the question does not apply (no dispatcher, or the
    template could not be read)."""
    runner = project / "unityHPC" / "run.sh"
    if not runner.exists():
        return None
    try:
        from lib import scaffold
        canonical = scaffold.render(
            (scaffold.template_root() / "common" / "run.sh").read_text())
        return _strip_stamp(runner.read_text(errors="replace")) != _strip_stamp(canonical)
    except Exception:
        return None


def _unity_doctor() -> str:
    """Report what this server is actually running, and whether it is stale.

    Exists because a field report traced a bug to source that was already
    fixed: the session was talking to a server process started before the
    upgrade. Reading the code on disk cannot reveal that — only the running
    process can."""
    root = _SOURCE.parent.parent
    running = _plugin_version(root)
    installed, install_path = _installed_version()

    problems: list[dict] = []
    try:
        if _SOURCE.stat().st_mtime > _LOADED_AT:
            problems.append({
                "issue": "server_code_changed_after_start",
                "detail": "The server source was modified after this process "
                          "started, so it is running the previous version.",
                "fix": "Run /reload-plugins, or restart the session.",
            })
    except OSError:
        pass

    if installed and running and installed != running:
        problems.append({
            "issue": "version_mismatch",
            "detail": f"This server runs {running} from {root}, but this machine "
                      f"has {installed} registered at {install_path}.",
            "fix": "Run /reload-plugins, or restart the session.",
        })

    project = _project_dir()
    scaffold_version = _scaffold_version(project)
    has_scaffold = (project / "unityHPC" / "run.sh").exists()
    if has_scaffold and _dispatcher_differs(project):
        problems.append({
            "issue": "scaffold_stale",
            "detail": (
                f"unityHPC/run.sh differs from the canonical template "
                f"(stamped {scaffold_version or 'unstamped, i.e. pre-0.8.2'}; "
                f"plugin is {running}). The dispatcher is a copy in the project: "
                f"upgrading the plugin does not upgrade it, so fixes and features "
                f"added since are absent here. If you edited it deliberately, that "
                f"edit is what is being reported."
            ),
            "fix": "Re-run /unity-hpc:setup (or hpc-scaffold --type <type>). "
                   "Your .env is preserved; the old run.sh is kept in "
                   "unityHPC/.pre-redesign/.",
        })

    campaigns = _campaign.campaigns(project)
    spec, spec_error = _metrics.load_with_error(project)
    data_dir = _data_dir()
    summaries = _summaries_db()

    report = {
        "status": "stale" if problems else "ok",
        "running": {"version": running, "source": str(_SOURCE), "root": str(root)},
        "installed": {"version": installed, "path": install_path},
        "project": {
            "dir": str(project),
            "scaffold": has_scaffold,
            "scaffold_version": scaffold_version,
            "unity_host": _env_value("UNITY_HOST", "unity"),
            "remote_dir": _env_value("REMOTE_DIR") or None,
            "campaigns": campaigns[:5],
            "recorded_jobs": len(_campaign.all_job_ids(project)),
        },
        "metrics_declaration": (
            {"declared": True, "primary": spec.primary, "goal": spec.goal,
             "report": list(spec.report)} if spec else
            {"declared": False, "note": spec_error or
             "No unityHPC/metrics.json; results report whatever jobs print."}
        ),
        "shared_data": {
            "dir": str(data_dir),
            "summaries_db": summaries.exists(),
            "cluster_config": _config_path().exists(),
        },
        "problems": problems,
    }
    if not problems:
        report["note"] = "Server is running the installed version."
    return json.dumps(report, indent=2)


# ─── Entry point ──────────────────────────────────────────────────────────────

async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
