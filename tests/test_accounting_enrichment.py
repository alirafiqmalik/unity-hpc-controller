"""Job accounting keeps requests, allocations, steps and provenance separate."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cluster-intel"))
import collector_parse as parser
import rollup
from lib import paths, queries


def row(job="123", state="COMPLETED", cpu="00:04:00.500", rss="", usage=""):
    return "\t".join([
        job, "alice", "lab", "gpu", state, "2026-10-05T10:00:00",
        "2026-10-05T10:05:00", "2026-10-05T10:10:00", "00:05:00",
        "cpu=4,mem=8G,gres/gpu:a100=1", "0:0", rss, "01:00:00",
        "gpu013", "campaign-task", "normal", "cpu=2,mem=4G,gres/gpu:a100=1",
        "2Gc", "2", "a100-80g&sapphirerapids", cpu, "1200", usage,
        "2026-10-05T10:01:00", "0",
    ])


def test_accounting_uses_actual_steps_without_double_counting_allocation():
    records = parser.parse_task_runs("\n".join([
        row(cpu="00:04:00.500"),
        row("123.batch", cpu="00:03:00.250", rss="512M", usage="gres/gpumem=2048,gres/gpuutil=80"),
        row("123.0", cpu="00:01:00.250", rss="768M", usage="gres/gpumem=4096,gres/gpuutil=90"),
    ]))
    assert len(records) == 1
    record = records[0]
    assert record["node_list"] == "gpu013"
    assert record["req"]["cpus"] == 2
    assert record["req"]["mem_mb"] == 4096
    assert record["allocated"]["cpus"] == 4
    assert record["allocated"]["mem_mb"] == 8192
    assert record["used"]["total_cpu_s"] == 240.5
    assert record["used"]["cpu_eff_pct"] == 240.5 / 1200 * 100
    assert record["used"]["max_rss_mb"] == 768
    assert len(record["steps"]) == 2
    assert record["steps"][0]["tres_usage_in_max"]["gres/gpuutil"] == 80
    assert record["used"]["gpu_util_pct"] is None, "step high-water marks are not time-weighted GPU utilization"


def test_pending_requests_do_not_become_allocations_or_measured_efficiency():
    fields = row(state="PENDING", cpu="").split("\t")
    fields[6:9] = ["Unknown", "Unknown", "00:00:00"]
    fields[9] = ""
    fields[13] = "None assigned"
    fields[21] = "0"
    record = parser.parse_task_runs("\t".join(fields))[0]
    assert record["req"]["gpus"] == 1
    assert record["gpu_type"] is None
    assert record["allocated"] is None
    assert record["used"]["cpu_eff_pct"] is None


def test_constraint_or_expression_survives_tab_separated_collection():
    fields = row().split("\t")
    fields[19] = "a100-80g|l40s"
    record = parser.parse_task_runs("\t".join(fields))[0]
    assert record["constraints"] == "a100-80g|l40s"


def test_richer_accounting_survives_rollup_and_legacy_reobservations(tmp_data_dir):
    day = paths.telemetry_dir() / "2026-10-05"
    day.mkdir(parents=True)
    record = parser.parse_task_runs(row(rss="512M"))[0]
    raw = day / "task_runs.jsonl"
    raw.write_text(json.dumps(record) + "\n")
    rollup.run()
    found = queries.job_accounting_for_jobs(["123"])[0]
    assert found["user"] == "alice"
    assert found["node_list"] == "gpu013"
    assert found["req"]["cpus"] == 2
    assert found["allocated"]["cpus"] == 4
    legacy = parser.parse_task_runs(
        "123|alice|lab|gpu|COMPLETED|2026-10-05T10:00:00|2026-10-05T10:05:00|"
        "2026-10-05T10:10:00|00:05:00|cpu=4,mem=8G,gres/gpu:a100=1|0:0||01:00:00"
    )[0]
    raw.write_text(json.dumps(legacy) + "\n")
    rollup.run()
    assert queries.job_accounting_for_jobs(["123"])[0]["node_list"] == "gpu013"
    with sqlite3.connect(paths.summaries_db()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM task_accounting").fetchone()[0] == 1
