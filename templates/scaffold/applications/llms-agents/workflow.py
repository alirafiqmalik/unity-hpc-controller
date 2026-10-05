#!/usr/bin/env python3
"""Stage runner for the llms-agents application.

Each cluster stage is one ``run.sh run`` and one ledger row. ``run.sh`` is
the only submitter. This module renders those invocations and the sbatch
bodies. It does not call ``sbatch``.

A stage with ``location: controller`` runs on this machine. The mock smoke
uses that path. It does not open SSH and it does not request a GPU.

The stranded-stage check reads a failed parent whose declared outputs are
complete. It does not submit, resubmit, or edit the ledger.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent

FAILED_STATES = frozenset({
    "FAILED",
    "TIMEOUT",
    "OUT_OF_MEMORY",
    "NODE_FAIL",
    "BOOT_FAIL",
    "DEADLINE",
    "PREEMPTED",
})

_SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


def _strip_comment(line: str) -> str:
    quote = ""
    out = []
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = ""
            out.append(ch)
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
            continue
        if ch == "#" and (i == 0 or line[i - 1].isspace()):
            break
        out.append(ch)
    return "".join(out).rstrip()


def _scalar(text: str):
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if text in ("true", "True"):
        return True
    if text in ("false", "False"):
        return False
    if text in ("null", "~"):
        return None
    if text == "[]":
        return []
    if text == "{}":
        return {}
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def load_workflow_text(text: str) -> dict:
    """Load the workflow subset this template writes. Stdlib only."""
    lines = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        code = _strip_comment(raw)
        if not code.strip():
            continue
        if code.startswith("\t"):
            raise ValueError(f"line {lineno}: workflow YAML uses spaces, not tabs")
        indent = len(code) - len(code.lstrip(" "))
        lines.append((indent, code.strip(), lineno))
    value, idx = _parse_block(lines, 0)
    if idx != len(lines):
        raise ValueError(f"line {lines[idx][2]}: leftover workflow content")
    if not isinstance(value, dict):
        raise ValueError("workflow file must be a mapping")
    return value


def load_workflow(path: Path | str) -> dict:
    return load_workflow_text(Path(path).read_text(encoding="utf-8"))


def _parse_block(lines, idx):
    if idx >= len(lines):
        return {}, idx
    if lines[idx][1].startswith("-"):
        return _parse_list(lines, idx, lines[idx][0])
    return _parse_map(lines, idx, lines[idx][0])


def _parse_map(lines, idx, indent):
    out = {}
    while idx < len(lines):
        ind, text, lineno = lines[idx]
        if ind < indent:
            break
        if ind > indent:
            raise ValueError(f"line {lineno}: unexpected indent")
        if text.startswith("-"):
            break
        key, sep, rest = text.partition(":")
        if not sep:
            raise ValueError(f"line {lineno}: expected key: value")
        key = key.strip()
        rest = rest.strip()
        idx += 1
        if rest == "":
            if idx < len(lines) and lines[idx][0] > indent:
                child, idx = _parse_block(lines, idx)
                out[key] = child
            else:
                out[key] = None
        else:
            out[key] = _scalar(rest)
    return out, idx


def _parse_list(lines, idx, indent):
    out = []
    while idx < len(lines):
        ind, text, lineno = lines[idx]
        if ind < indent:
            break
        if ind != indent or not text.startswith("-"):
            break
        item = text[1:].strip()
        if item == "":
            idx += 1
            if idx < len(lines) and lines[idx][0] > indent:
                child, idx = _parse_block(lines, idx)
                out.append(child)
            else:
                out.append(None)
            continue
        if ":" in item and not (item[0] in "\"'" ):
            key, _sep, rest = item.partition(":")
            mapping = {}
            rest = rest.strip()
            if rest == "":
                mapping[key.strip()] = None
            else:
                mapping[key.strip()] = _scalar(rest)
            idx += 1
            while idx < len(lines) and lines[idx][0] > indent and not lines[idx][1].startswith("-"):
                kind, ktext, _kline = lines[idx]
                kkey, ksep, krest = ktext.partition(":")
                if not ksep:
                    break
                krest = krest.strip()
                idx += 1
                if krest == "":
                    if idx < len(lines) and lines[idx][0] > kind:
                        child, idx = _parse_block(lines, idx)
                        mapping[kkey.strip()] = child
                    else:
                        mapping[kkey.strip()] = None
                else:
                    mapping[kkey.strip()] = _scalar(krest)
            out.append(mapping)
            continue
        out.append(_scalar(item))
        idx += 1
    return out, idx


def _safe(name: str) -> str:
    if not name or any(ch not in _SAFE for ch in name):
        raise ValueError(f"unsafe name {name!r}")
    return name


def render_train_sbatch(
    env: dict | None = None,
    *,
    parallel: str | None = None,
    launcher: str | None = None,
    exp: str = "train",
) -> str:
    """Full train sbatch. ``LLMS_PARALLEL`` selects FSDP or DeepSpeed ZeRO-3."""
    values = dict(env or {})
    if parallel:
        values["LLMS_PARALLEL"] = parallel
    if launcher:
        values["LLMS_LAUNCHER"] = launcher
    values.setdefault("LLMS_PARALLEL", "fsdp")
    values.setdefault("LLMS_LAUNCHER", "axolotl")
    values.setdefault("LLMS_JOB", "train")
    header = _sbatch_header(exp, values)
    chosen = (
        "configs/deepspeed_zero3.json"
        if values["LLMS_PARALLEL"] == "deepspeed"
        else "configs/fsdp.yaml"
    )
    preamble = "\n".join([
        f"export LLMS_PARALLEL={shlex.quote(str(values['LLMS_PARALLEL']))}",
        f"export LLMS_LAUNCHER={shlex.quote(str(values['LLMS_LAUNCHER']))}",
        f"export LLMS_PARALLEL_CONFIG=\"${{LLMS_APP_DIR:-$REMOTE_DIR/unityHPC}}/{chosen}\"",
        "",
    ])
    body = (APP_DIR / "train_job.sh").read_text(encoding="utf-8")
    return header + preamble + body


def render_eval_sbatch(
    env: dict | None = None,
    *,
    parent_job_id: str,
    eval_kind: str | None = None,
    exp: str = "eval",
) -> str:
    """Full eval sbatch. The dependency is ``afterok``, never ``afterany``."""
    if not parent_job_id or any(ch not in set("0123456789") for ch in str(parent_job_id)):
        raise ValueError("eval dependency needs a numeric parent job id")
    values = dict(env or {})
    if eval_kind:
        values["LLMS_EVAL_KIND"] = eval_kind
    values.setdefault("LLMS_EVAL_KIND", "lm-eval")
    values.setdefault("LLMS_ENGINE", "openai")
    values["LLMS_JOB"] = "eval"
    header = _sbatch_header(exp, values, dependency=f"afterok:{parent_job_id}")
    preamble = "\n".join([
        f"export LLMS_EVAL_KIND={shlex.quote(str(values['LLMS_EVAL_KIND']))}",
        f"export LLMS_ENGINE={shlex.quote(str(values['LLMS_ENGINE']))}",
        "",
    ])
    body = (APP_DIR / "eval_job.sh").read_text(encoding="utf-8")
    script = header + preamble + body
    if "afterany" in script:
        raise ValueError("eval sbatch must use afterok, not afterany")
    return script


def _sbatch_header(exp: str, env: dict, dependency: str | None = None) -> str:
    exp = _safe(exp)
    account = env.get("SLURM_ACCOUNT") or "account"
    partition = env.get("SLURM_PARTITION") or "gpu"
    wall = env.get("WALLTIME") or "08:00:00"
    nodes = env.get("SLURM_NODES") or "1"
    cpus = env.get("SLURM_CPUS") or "8"
    mem = env.get("SLURM_MEM") or "64G"
    remote = env.get("REMOTE_DIR") or "/work/project"
    lines = [
        "#!/bin/bash",
        f"#SBATCH --job-name={exp}",
        f"#SBATCH --account={account}",
        f"#SBATCH --partition={partition}",
        f"#SBATCH --time={wall}",
        f"#SBATCH --nodes={nodes}",
        f"#SBATCH --cpus-per-task={cpus}",
        f"#SBATCH --mem={mem}",
        f"#SBATCH --output={remote}/_slurm/{exp}-%j.out",
        f"#SBATCH --error={remote}/_slurm/{exp}-%j.err",
    ]
    gpus = str(env.get("SLURM_GPUS") or "")
    if gpus and gpus != "0":
        gpu_type = env.get("SLURM_GPU_TYPE") or ""
        if gpu_type:
            lines.append(f"#SBATCH --gres=gpu:{gpu_type}:{gpus}")
        else:
            lines.append(f"#SBATCH --gres=gpu:{gpus}")
    if env.get("SLURM_CONSTRAINT"):
        lines.append(f"#SBATCH --constraint={env['SLURM_CONSTRAINT']}")
    if dependency:
        if not dependency.startswith("afterok:"):
            raise ValueError("only afterok dependencies are emitted")
        lines.append(f"#SBATCH --dependency={dependency}")
    lines.append("")
    return "\n".join(lines) + "\n"


def plan_invocations(
    workflow: dict,
    *,
    campaign: str = "campaign",
    job_ids: dict[str, str] | None = None,
    run_sh: str = "unityHPC/run.sh",
) -> list[str]:
    """One ``run.sh run`` line per cluster stage. Controller stages are omitted.

    The second stage of a chain carries ``--dependency=afterok:<parent job id>``.
    """
    known = {str(k): str(v) for k, v in (job_ids or {}).items()}
    lines = []
    for stage in workflow.get("stages") or []:
        if stage.get("location") == "controller":
            continue
        stage_id = _safe(str(stage["id"]))
        env = _stage_env(stage)
        env["JOB_COMMAND"] = _stage_command(stage)
        env["LLMS_STAGE_ID"] = stage_id
        parent_ids = []
        for dep in stage.get("depends_on") or []:
            dep_id = str(dep)
            if dep_id not in known:
                raise ValueError(f"stage {stage_id} depends on {dep_id}, which has no job id")
            parent_ids.append(known[dep_id])
        assign = " ".join(
            f"{key}={shlex.quote(str(value))}"
            for key, value in env.items()
            if value is not None and str(value) != ""
        )
        line = f"{assign} bash {run_sh} run {shlex.quote(stage_id)} --campaign {shlex.quote(campaign)}"
        if parent_ids:
            line += " --dependency=afterok:" + ":".join(parent_ids)
        if "afterany" in line:
            raise ValueError("stage dependency must be afterok")
        lines.append(line)
    return lines


def _memory(resources: dict) -> str:
    if resources.get("memory"):
        return str(resources["memory"])
    if resources.get("memory_gb") is not None:
        return f"{resources['memory_gb']}G"
    return ""


def _stage_env(stage: dict) -> dict:
    resources = stage.get("resources") or {}
    primitive = str(resources.get("primitive") or "cpu")
    env = {
        "LLMS_JOB": _job_kind(stage),
        "LLMS_METRIC_KEYS": ",".join(str(k) for k in (stage.get("metrics") or [])) or "",
    }
    if resources.get("walltime"):
        env["WALLTIME"] = str(resources["walltime"])
    if resources.get("cpus") is not None:
        env["SLURM_CPUS"] = str(resources["cpus"])
    mem = _memory(resources)
    if mem:
        env["SLURM_MEM"] = mem
    if resources.get("nodes") is not None:
        env["SLURM_NODES"] = str(resources["nodes"])
    if primitive in ("cpu", "multi-cpu"):
        env["SLURM_GPUS"] = "0"
    elif resources.get("gpus") is not None:
        env["SLURM_GPUS"] = str(resources["gpus"])
    if resources.get("constraint"):
        env["SLURM_CONSTRAINT"] = str(resources["constraint"])
    if resources.get("partition"):
        env["SLURM_PARTITION"] = str(resources["partition"])
    if stage.get("format"):
        env["LLMS_FORMAT"] = str(stage["format"])
    if stage.get("parallel"):
        env["LLMS_PARALLEL"] = str(stage["parallel"])
    if stage.get("launcher"):
        env["LLMS_LAUNCHER"] = str(stage["launcher"])
    if stage.get("engine"):
        env["LLMS_ENGINE"] = str(stage["engine"])
    eval_block = stage.get("eval") or {}
    if isinstance(eval_block, dict) and eval_block.get("kind"):
        env["LLMS_EVAL_KIND"] = str(eval_block["kind"])
    if isinstance(eval_block, dict) and eval_block.get("tasks"):
        tasks = eval_block["tasks"]
        env["LLMS_EVAL_TASKS"] = ",".join(tasks) if isinstance(tasks, list) else str(tasks)
    if isinstance(eval_block, dict) and eval_block.get("argv"):
        env["LLMS_PROJECT_EVAL_ARGV"] = _join_argv(eval_block["argv"])
    mode = stage.get("mode") or stage.get("id")
    if mode == "consolidate":
        env["LLMS_STAGE"] = "consolidate"
        env["LLMS_JOB"] = "train"
    elif _job_kind(stage) == "train":
        env["LLMS_STAGE"] = "train-only"
    parents = [str(d) for d in (stage.get("depends_on") or [])]
    if parents:
        env["LLMS_PARENT_STAGE"] = parents[-1]
    if stage.get("purpose"):
        env["LLMS_PURPOSE"] = str(stage["purpose"])
    return env


def _job_kind(stage: dict) -> str:
    if stage.get("job") in ("train", "eval", "command"):
        return str(stage["job"])
    if stage.get("id") == "consolidate" or stage.get("mode") == "consolidate":
        return "train"
    if stage.get("id") in ("train",) or stage.get("lane") == "train" and stage.get("id") == "train":
        return "train"
    eval_block = stage.get("eval") or {}
    if stage.get("id") == "eval" or (isinstance(eval_block, dict) and eval_block.get("kind") == "lm-eval"):
        return "eval"
    return "command"


def _join_argv(argv) -> str:
    if isinstance(argv, str):
        return argv
    return " ".join(shlex.quote(str(part)) for part in argv)


def _stage_command(stage: dict) -> str:
    if stage.get("command"):
        return _join_argv(stage["command"])
    if stage.get("resume"):
        return _join_argv(stage["resume"])
    kind = _job_kind(stage)
    if kind == "eval":
        return "unityHPC/eval_job.sh"
    if kind == "train":
        return "unityHPC/train_job.sh"
    raise ValueError(f"stage {stage.get('id')} has no command")


def resume_argv(stage: dict, checkpoint_dir: str) -> list[str]:
    """The project resume command, with ``{checkpoint_dir}`` filled in.

    The template does not implement a resume policy. It only has this slot.
    """
    argv = stage.get("resume")
    if not argv:
        raise ValueError(f"stage {stage.get('id')} has no resume command")
    return [str(part).replace("{checkpoint_dir}", checkpoint_dir) for part in argv]


def _output_paths(stage: dict) -> list[str]:
    paths = []
    for item in stage.get("outputs") or []:
        if isinstance(item, str):
            paths.append(item)
        elif isinstance(item, dict) and item.get("path"):
            paths.append(str(item["path"]))
    return paths


def _outputs_complete(stage: dict, root: Path) -> bool:
    paths = _output_paths(stage)
    if not paths or not root.is_dir():
        return False
    for rel in paths:
        path = root / rel
        if not path.is_file() or path.stat().st_size <= 0:
            return False
        if path.suffix == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return False
    return True


def stranded_stages(
    workflow: dict,
    ledger_rows: list[dict],
    output_dirs: dict[str, Path | str],
) -> list[dict]:
    """Report a parent SLURM marked failed whose declared outputs are complete.

    Read-only. This function does not submit, resubmit, or edit the ledger.
    """
    stages = {str(stage["id"]): stage for stage in workflow.get("stages") or []}
    parents = set()
    for stage in stages.values():
        for dep in stage.get("depends_on") or []:
            parents.add(str(dep))
    findings = []
    for row in ledger_rows:
        stage_id = str(row.get("stage") or row.get("exp") or "")
        status = str(row.get("status") or "").upper()
        if stage_id not in parents or status not in FAILED_STATES:
            continue
        root = Path(output_dirs.get(stage_id, ""))
        stage = stages.get(stage_id)
        if stage is None or not _outputs_complete(stage, root):
            continue
        findings.append({
            "stage": stage_id,
            "job_id": str(row.get("job_id") or ""),
            "status": status,
            "verdict": "STRANDED",
            "detail": "parent is marked failed and its declared outputs are complete",
        })
    return findings


def run_project_command(
    argv: list[str],
    *,
    cwd: Path | str,
    substitutions: dict | None = None,
) -> int:
    """Run a project argv on this machine. No SSH. No GPU request."""
    filled = []
    subs = substitutions or {}
    for part in argv:
        text = str(part)
        for key, value in subs.items():
            text = text.replace("{" + key + "}", str(value))
        filled.append(text)
    if any(part == "ssh" or part.startswith("ssh ") for part in filled):
        raise ValueError("project command hook does not open ssh")
    proc = subprocess.run(filled, cwd=str(cwd))
    return proc.returncode


def _numeric_leaves(value, prefix: str = "") -> dict[str, float]:
    found = {}
    if isinstance(value, bool):
        return found
    if isinstance(value, (int, float)):
        if prefix:
            found[prefix] = float(value)
        return found
    if isinstance(value, dict):
        for key, item in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            found.update(_numeric_leaves(item, name))
    return found


def collect_metrics(results_dir: Path, keys: list[str]) -> dict[str, float]:
    """Flat numeric keys from metrics, the harness JSON, or workspace-artifact."""
    results_dir = Path(results_dir)
    numbers: dict[str, float] = {}
    for name in ("metrics.json", "harness.json", "workspace-artifact.json"):
        path = results_dir / name
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        leaves = _numeric_leaves(payload)
        measurements = payload.get("measurements")
        if isinstance(measurements, dict):
            for key, item in measurements.items():
                if isinstance(item, (int, float)) and not isinstance(item, bool):
                    leaves[str(key)] = float(item)
        for key, item in leaves.items():
            short = key.split(".")[-1]
            short = short.split(",")[0]
            numbers.setdefault(short, item)
            numbers.setdefault(key, item)
    if "accuracy" not in numbers and "acc" in numbers:
        numbers["accuracy"] = numbers["acc"]
    if not keys:
        return {k: v for k, v in numbers.items() if "." not in k}
    return {key: numbers[key] for key in keys if key in numbers}


def write_metrics(results_dir: Path, keys: list[str], *, labels: dict | None = None) -> dict:
    """Write ``metrics.json`` and print ``key: value`` lines for the scalar reader."""
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    numbers = collect_metrics(results_dir, keys)
    report = [key for key in keys if key in numbers] or sorted(numbers)
    payload = {"report": report, "labels": dict(labels or {})}
    payload.update({key: numbers[key] for key in report})
    (results_dir / "metrics.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    for key in report:
        print(f"{key}: {numbers[key]}")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="workflow.py")
    sub = parser.add_subparsers(dest="cmd", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--workflow", required=True, type=Path)
    plan.add_argument("--campaign", default="campaign")
    plan.add_argument("--job-id", action="append", default=[], help="stage=jobid")

    train = sub.add_parser("render-train")
    train.add_argument("--parallel", choices=("fsdp", "deepspeed"), default="fsdp")
    train.add_argument("--launcher", choices=("axolotl", "trl"), default="axolotl")

    ev = sub.add_parser("render-eval")
    ev.add_argument("--parent", required=True)
    ev.add_argument("--eval-kind", default="lm-eval")

    stranded = sub.add_parser("stranded")
    stranded.add_argument("--workflow", required=True, type=Path)
    stranded.add_argument("--ledger", required=True, type=Path, help="JSON list of ledger rows")
    stranded.add_argument("--output", action="append", default=[], help="stage=directory")

    metrics = sub.add_parser("write-metrics")
    metrics.add_argument("--results", required=True, type=Path)
    metrics.add_argument("--keys", default="accuracy")

    project = sub.add_parser("project-command")
    project.add_argument("--cwd", required=True, type=Path)
    project.add_argument("argv", nargs=argparse.REMAINDER)

    args = parser.parse_args(argv)
    if args.cmd == "plan":
        job_ids = {}
        for item in args.job_id:
            stage, _, job = item.partition("=")
            job_ids[stage] = job
        for line in plan_invocations(load_workflow(args.workflow), campaign=args.campaign, job_ids=job_ids):
            print(line)
        return 0
    if args.cmd == "render-train":
        sys.stdout.write(render_train_sbatch(parallel=args.parallel, launcher=args.launcher))
        return 0
    if args.cmd == "render-eval":
        sys.stdout.write(render_eval_sbatch(parent_job_id=args.parent, eval_kind=args.eval_kind))
        return 0
    if args.cmd == "stranded":
        rows = json.loads(args.ledger.read_text(encoding="utf-8"))
        roots = {}
        for item in args.output:
            stage, _, directory = item.partition("=")
            roots[stage] = directory
        for finding in stranded_stages(load_workflow(args.workflow), rows, roots):
            print(json.dumps(finding, sort_keys=True))
        return 0
    if args.cmd == "write-metrics":
        keys = [key for key in args.keys.split(",") if key]
        write_metrics(args.results, keys)
        return 0
    argv = list(args.argv)
    if argv and argv[0] == "--":
        argv = argv[1:]
    return run_project_command(argv, cwd=args.cwd)


if __name__ == "__main__":
    raise SystemExit(main())
