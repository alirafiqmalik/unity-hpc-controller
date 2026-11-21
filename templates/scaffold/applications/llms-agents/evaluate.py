#!/usr/bin/env python3
"""Evaluate an LLM or agent against an evaluation dataset.

This is the project's `evaluate(data, predict_fn, scorers)` step. It reads one
dataset, calls the predict function once per record, scores every output,
and writes an evaluation run the controller dashboard reads:

    evaluations/<run>/manifest.json   the run: dataset, model, scorers, metrics
    evaluations/<run>/traces.jsonl    one trace per record: request, response,
                                      spans, assessments, expectations

Three parts the project owns:

    unityHPC/agent.py      predict_fn(inputs, context) -> Prediction
    unityHPC/scorers.py    scorers by name; each returns an Assessment
    dataset/<name>/        dataset.json + records.jsonl

Subcommands:

    evaluate.py run        --dataset NAME --model ID --out DIR [--scorers a,b] [--mock true]
    evaluate.py validate   --out DIR            completeness evidence for the workspace
    evaluate.py fetch      --project-root DIR --relative REL [--dry-run]
    evaluate.py check                           bounded mock run (connection check)

`run` is what the SLURM job executes. `validate`, `fetch` and `check` run on
the controller through the operations declared in unityHPC/project.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shlex
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "unityHPC"))
sys.path.insert(0, str(ROOT))

SCHEMA = "llms-agents.evaluation"
VERSION = 1


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")
    tmp.replace(path)


def boolean(value: str) -> bool:
    if value.lower() not in ("true", "false"):
        raise argparse.ArgumentTypeError("expected true or false")
    return value.lower() == "true"


# --------------------------------------------------------------------------- #
# Dataset
# --------------------------------------------------------------------------- #

def load_dataset(name: str) -> tuple[dict, list[dict]]:
    folder = ROOT / "dataset" / name
    meta_path = folder / "dataset.json"
    if not folder.is_dir():
        raise SystemExit(f"no dataset directory: {folder}")
    meta = json.loads(meta_path.read_text()) if meta_path.is_file() else {"name": name}
    records_file = folder / (meta.get("records_file") or "records.jsonl")
    records: list[dict] = []
    if records_file.is_file():
        for index, line in enumerate(records_file.read_text().splitlines()):
            if not line.strip():
                continue
            record = json.loads(line)
            record.setdefault("record_id", f"line-{index + 1}")
            record.setdefault("inputs", {})
            record.setdefault("expectations", {})
            records.append(record)
    if not records:
        raise SystemExit(f"dataset {name!r} has no records in {records_file.name}")
    return meta, records


# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #

def run(args: argparse.Namespace) -> int:
    import agent
    import scorers as scorer_module

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    meta, records = load_dataset(args.dataset)
    if args.n_items:
        records = records[: args.n_items]
    names = [n.strip() for n in (args.scorers or "").split(",") if n.strip()] or scorer_module.DEFAULT_SCORERS
    chosen = {name: scorer_module.get(name) for name in names}

    context = {
        "model": args.model, "mock": args.mock, "max_tokens": args.max_tokens, "temperature": args.temperature,
        "seed": args.seed, "run_id": out.name, "execution_id": args.execution_id, "purpose": args.purpose,
        "dataset": meta.get("name") or args.dataset, "prompt_path": str(ROOT / "prompts" / "system.md"),
    }
    predict = agent.mock_predict if args.mock else agent.predict
    started = now()
    traces_path = out / "traces.jsonl"
    counts = {"requested": len(records), "done": 0, "errors": 0}
    totals: dict[str, dict] = {name: {"count": 0, "pass": 0, "sum": 0.0} for name in chosen}
    with traces_path.open("w") as handle:
        for record in records:
            trace = evaluate_record(record, predict, chosen, context)
            counts["done"] += 1
            if trace.get("error"):
                counts["errors"] += 1
            for name, assessment in trace["assessments"].items():
                total = totals[name]
                value = assessment["value"]
                if value is None or (assessment["kind"] == "score" and not isinstance(value, (int, float))):
                    # Not assessed (no expectation, scorer error): out of the metric's denominator.
                    total["unassessed"] = total.get("unassessed", 0) + 1
                    continue
                total["count"] += 1
                if assessment["kind"] == "pass_fail":
                    total["pass"] += 1 if value is True else 0
                elif assessment["kind"] == "score" and isinstance(value, (int, float)):
                    total["sum"] += float(value)
            handle.write(json.dumps(trace, sort_keys=True, default=str) + "\n")
            handle.flush()
    metrics: dict[str, float] = {}
    for name, total in totals.items():
        if not total["count"]:
            continue
        kind = chosen[name].kind
        if kind == "pass_fail":
            metrics[f"{name}_rate"] = round(total["pass"] / total["count"], 4)
        elif kind == "score":
            metrics[f"{name}_mean"] = round(total["sum"] / total["count"], 4)
    if "correctness_rate" in metrics:
        metrics["accuracy"] = metrics["correctness_rate"]
    manifest = {
        "schema": SCHEMA, "version": VERSION,
        "name": args.name or out.name,
        "dataset": meta.get("name") or args.dataset,
        "dataset_source": {"path": str((ROOT / "dataset" / args.dataset).relative_to(ROOT)),
                           "records": len(records), "records_sha256": sha256(ROOT / "dataset" / args.dataset / (meta.get("records_file") or "records.jsonl"))},
        "model": args.model,
        "engine": agent.ENGINE, "engine_version": agent.engine_version(),
        "runner_version": f"llms-agents-evaluate-v{VERSION}",
        "prompt": agent.prompt_identity(context),
        "scorers": [{"name": name, "kind": scorer.kind, "source": scorer.source} for name, scorer in chosen.items()],
        "parameters": {"dataset": args.dataset, "model": args.model, "n_items": args.n_items, "scorers": names,
                       "max_tokens": args.max_tokens, "temperature": args.temperature, "seed": args.seed, "mock": args.mock},
        "n_items": len(records), "counts": counts, "metrics": metrics,
        "measurements": metrics,
        "started_utc": started, "finished_utc": now(),
        "host": platform.node(), "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        "execution_id": args.execution_id, "variant_id": args.variant_id, "stage_id": args.stage_id,
        "purpose": args.purpose, "runner_exit": 0,
        "traces_sha256": sha256(traces_path),
    }
    write_json(out / "manifest.json", manifest)
    print(json.dumps({"run": manifest["name"], "traces": counts["done"], "metrics": metrics, "out": str(out)}))
    return 0


def evaluate_record(record: dict, predict, chosen: dict, context: dict) -> dict:
    started = time.perf_counter()
    request_time = now()
    error = None
    try:
        prediction = predict(record["inputs"], context)
    except Exception as exc:  # The trace records the failure; the run goes on.
        prediction = {"response": None, "spans": [], "tokens": {}}
        error = f"{type(exc).__name__}: {exc}"
    duration = time.perf_counter() - started
    response = prediction.get("response")
    assessments = {}
    for name, scorer in chosen.items():
        if error is not None and scorer.needs_response:
            continue
        try:
            assessment = scorer(inputs=record["inputs"], outputs=response, expectations=record["expectations"], context=context)
        except Exception as exc:  # A scorer failure is an assessment the reviewer can see.
            assessment = {"value": None, "kind": scorer.kind, "rationale": f"scorer failed: {exc}", "source": scorer.source}
        assessments[name] = assessment
    request = record["inputs"].get("question") or record["inputs"].get("request") or record["inputs"].get("prompt") or json.dumps(record["inputs"], sort_keys=True)
    return {
        "trace_id": hashlib.sha256(f"{context['run_id']}|{record['record_id']}|{context['model']}".encode()).hexdigest()[:16],
        "request": request,
        "inputs": record["inputs"],
        "response": response,
        "reasoning": prediction.get("reasoning"),
        "request_time": request_time,
        "duration_s": round(duration, 6),
        "tokens": prediction.get("tokens") or {},
        "state": "ERROR" if error else "OK",
        "error": error,
        "session": record.get("tags", {}).get("session") or record["inputs"].get("session") or record["record_id"],
        "dataset": context["dataset"],
        "dataset_record": record["record_id"],
        "model": context["model"],
        "spans": prediction.get("spans") or [],
        "assessments": assessments,
        "expectations": record["expectations"],
        "tags": record.get("tags", {}),
    }


# --------------------------------------------------------------------------- #
# Controller-side operations
# --------------------------------------------------------------------------- #

def validate(out: Path) -> dict:
    """Completeness evidence: every requested record has a trace, and the runner exited 0."""
    errors: list[str] = []
    files: list[dict] = []
    manifest: dict = {}
    try:
        manifest = json.loads((out / "manifest.json").read_text())
        if manifest.get("schema") != SCHEMA:
            errors.append("unsupported evaluation schema")
        traces = [json.loads(line) for line in (out / "traces.jsonl").read_text().splitlines() if line.strip()]
        ids = {trace["trace_id"] for trace in traces}
        if len(ids) != manifest.get("counts", {}).get("requested"):
            errors.append("trace count does not match the requested record count")
        if manifest.get("runner_exit") != 0:
            errors.append("runner did not exit successfully")
        for path in sorted(out.iterdir()):
            if path.is_file() and path.name != "completeness.json":
                files.append({"path": path.name, "sha256": sha256(path), "size": path.stat().st_size})
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f"invalid or missing evaluation evidence: {exc}")
    return {"schema": SCHEMA, "version": VERSION, "complete": not errors, "errors": errors, "files": files,
            "provenance": {k: manifest.get(k) for k in ("execution_id", "variant_id", "stage_id", "purpose", "parameters", "model", "dataset")},
            "checked_at": now()}


def fetch(project_root: Path, relative: str, dry_run: bool) -> list[str]:
    """Pull one output directory from the cluster with rsync. Never deletes."""
    env = {}
    env_path = project_root / "unityHPC" / ".env"
    for line in env_path.read_text().splitlines() if env_path.is_file() else []:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = shlex.split(value)[0] if value.strip() else ""
    host = env.get("UNITY_HOST") or "unity"
    remote = env.get("REMOTE_DIR") or ""
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or not remote.startswith("/"):
        raise ValueError("fetch needs a relative output path and an absolute REMOTE_DIR")
    target = project_root / rel
    argv = ["rsync", "-az", "--protect-args", "--timeout=60", "-e", "ssh -o BatchMode=yes -o ConnectTimeout=15",
            f"{host}:{remote.rstrip('/')}/{rel.as_posix()}/", str(target) + "/"]
    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)
        subprocess.run(argv, check=True, timeout=600)
    return argv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    runner = commands.add_parser("run")
    runner.add_argument("--dataset", required=True)
    runner.add_argument("--model", required=True)
    runner.add_argument("--out", required=True)
    runner.add_argument("--name", default="")
    runner.add_argument("--scorers", default="")
    runner.add_argument("--n-items", type=int, default=0)
    runner.add_argument("--max-tokens", type=int, default=1024)
    runner.add_argument("--temperature", type=float, default=0.0)
    runner.add_argument("--seed", type=int, default=42)
    runner.add_argument("--mock", type=boolean, default=False)
    runner.add_argument("--execution-id", default="")
    runner.add_argument("--variant-id", default="")
    runner.add_argument("--stage-id", default="")
    runner.add_argument("--purpose", choices=("experiment", "smoke-test"), default="experiment")
    check = commands.add_parser("validate")
    check.add_argument("--out", required=True)
    pull = commands.add_parser("fetch")
    pull.add_argument("--project-root", required=True)
    pull.add_argument("--relative", required=True)
    pull.add_argument("--dry-run", action="store_true")
    commands.add_parser("check")
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return run(args)
        if args.command == "validate":
            result = validate(Path(args.out))
            print(json.dumps(result))
            return 0 if result["complete"] else 1
        if args.command == "fetch":
            cmd = fetch(Path(args.project_root), args.relative, args.dry_run)
            print(json.dumps({"scope": args.relative, "dry_run": args.dry_run, "argv": cmd if args.dry_run else None}))
            return 0
        if args.command == "check":
            first = sorted(p.name for p in (ROOT / "dataset").iterdir() if p.is_dir()) if (ROOT / "dataset").is_dir() else []
            if not first:
                raise ValueError("no dataset under dataset/; add one before checking the connection")
            with tempfile.TemporaryDirectory(prefix="llms-agents-check-") as scratch:
                code = main(["run", "--dataset", first[0], "--model", "mock", "--out", str(Path(scratch) / "smoke"),
                             "--mock", "true", "--n-items", "1", "--purpose", "smoke-test", "--execution-id", "connection-check"])
                if code:
                    return code
                print(json.dumps(validate(Path(scratch) / "smoke")))
            return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
