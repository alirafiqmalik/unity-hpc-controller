"""The dashboard stats tabs read cluster, queue and usage from snapshot.py.

These checks seed the same three stores the controller already has — the
cluster config, snapshot.csv and summaries.db — and assert the public
payloads the tabs render. A missing store stays empty (I6).
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from controller import snapshot
from controller.http import handle, parse_raw


def _call(method, path):
    resp = handle(parse_raw(method, path))
    return resp.status, json.loads(resp.body.decode())


def _seed_config(data_dir):
    (data_dir / "cluster-config.json").write_text(json.dumps({
        "cluster": "unity",
        "slurm_version": "25.11.6",
        "fairshare": {
            "factor": 0.45,
            "effective_usage": 0.99,
            "observed_utc": "2026-09-03T16:50:16Z",
        },
        "account_limits": {"account": "pi_lab"},
        "gpu_fleet": {
            "a100": {"total_accessible": 100, "allocated": 80, "pending": 12,
                     "vram_gb": [80]},
            "a40": {"total_accessible": 40, "allocated": 0, "pending": 0,
                    "vram_gb": [48]},
        },
        "partitions": {
            "gpu": {
                "nodes": 20, "gpus_total": 80, "gpu_types": ["a100"],
                "max_walltime": "14-00:00:00", "access": "open",
            },
            "cpu": {"nodes": 100, "cpus_total": 3200, "access": "open"},
        },
    }))


def _seed_summaries(data_dir):
    con = sqlite3.connect(data_dir / "summaries.db")
    con.execute(
        "CREATE TABLE hourly_resource(resource_kind TEXT, resource_id TEXT, "
        "hour_utc TEXT, util_min REAL, util_mean REAL, util_max REAL, "
        "util_p95 REAL, free_ratio REAL, samples INTEGER)"
    )
    con.execute(
        "CREATE TABLE task_run(job_id TEXT, project TEXT, campaign TEXT, "
        "skill TEXT, hardware TEXT, submit TEXT, start TEXT, \"end\" TEXT, "
        "elapsed_s REAL, wait_s REAL, cpu_eff REAL, mem_eff REAL, "
        "max_rss_mb REAL, state TEXT, exit_code INTEGER, day_utc TEXT, "
        "partition TEXT)"
    )
    con.executemany(
        "INSERT INTO hourly_resource VALUES(?,?,?,?,?,?,?,?,?)",
        [
            ("gpu_type", "a100", "2026-08-03T10:00:00Z", .2, .5, .8, .7, .5, 4),
            ("gpu_type", "a100", "2026-08-03T11:00:00Z", .2, .6, .9, .8, .4, 4),
            ("gpu_type", "a40", "2026-08-03T11:00:00Z", .1, .25, .4, .3, .7, 4),
            ("partition", "gpu", "2026-08-03T11:00:00Z", .1, .75, .9, .8, .2, 4),
            ("partition", "cpu", "2026-08-03T11:00:00Z", .1, .33, .5, .4, .6, 4),
        ],
    )
    con.executemany(
        "INSERT INTO task_run VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("1", "p", "c", "s", "a100", "2026-08-03T10:00:00Z", None, None,
             3600, 120, None, None, None, "COMPLETED", 0, "2026-08-03", "gpu"),
            ("2", "p", "c", "s", "a100", "2026-08-03T10:00:00Z", None, None,
             1800, 60, None, None, None, "FAILED", 1, "2026-08-03", "gpu"),
            ("3", "p", "c", "s", "cpu", "2026-08-03T10:00:00Z", None, None,
             7200, 30, None, None, None, "CANCELLED by 12", 0, "2026-08-03",
             "cpu"),
        ],
    )
    con.commit()
    con.close()


def test_cluster_is_empty_without_shared_data(tmp_data_dir):
    body = snapshot.cluster()
    assert body["partitions"] == []
    assert body["gpu_fleet"] == []
    assert body["fairshare"]["available"] is False
    assert body["stats"]["available"] is False
    assert body["kpis"]["gpus_total"] == 0


def test_cluster_exposes_fleet_fairshare_and_partition_util(tmp_data_dir):
    _seed_config(tmp_data_dir)
    _seed_summaries(tmp_data_dir)
    body = snapshot.cluster()
    assert body["fairshare"]["available"] is True
    assert body["fairshare"]["factor"] == 0.45
    assert body["fairshare"]["account"] == "pi_lab"
    fleet = {g["gpu_type"]: g for g in body["gpu_fleet"]}
    assert fleet["a100"]["total"] == 100
    assert fleet["a100"]["allocated"] == 80
    assert fleet["a100"]["free"] == 20
    assert fleet["a100"]["pending"] == 12
    assert body["kpis"]["gpus_total"] == 140
    assert body["kpis"]["gpus_allocated"] == 80
    assert body["kpis"]["gpus_free"] == 60
    parts = {p["name"]: p for p in body["partitions"]}
    assert parts["gpu"]["util"] == 75.0
    assert parts["cpu"]["util"] == 33.0
    assert parts["gpu"]["wait_s_avg"] == 90.0
    assert parts["gpu"]["jobs"] == 2


def test_outcomes_collapse_cancelled_by_uid(tmp_data_dir):
    _seed_summaries(tmp_data_dir)
    out = snapshot.outcomes()
    assert out["available"] is True
    assert out["counts"] == {"COMPLETED": 1, "FAILED": 1, "CANCELLED": 1}


def test_task_stats_sum_hours_and_group_hardware(tmp_data_dir):
    _seed_summaries(tmp_data_dir)
    stats = snapshot.task_stats()
    assert stats["available"] is True
    assert stats["runs"] == 3
    assert stats["gpu_hours"] == 3.5
    assert stats["wait_s_avg"] == 70.0
    assert stats["wait_s_gpu_avg"] == 90.0
    by_hw = {r["hardware"]: r for r in stats["by_hardware"]}
    assert by_hw["a100"]["runs"] == 2
    assert by_hw["a100"]["gpu_hours"] == 1.5
    assert by_hw["cpu"]["gpu_hours"] == 2.0


def test_usage_includes_heatmap_and_median(tmp_data_dir):
    _seed_summaries(tmp_data_dir)
    # The seeded hours are in August 2026; a 24h window from now is empty,
    # so the reader must slide back to the data that exists.
    usage = snapshot.usage(24)
    assert usage["available"] is True
    assert usage["window"] == "latest-available"
    assert usage["series"]["a100"] == [50.0, 60.0]
    by_type = {r["gpu_type"]: r for r in usage["by_type"]}
    assert by_type["a100"]["avg"] == 55.0
    assert by_type["a100"]["median"] == 55.0
    assert by_type["a100"]["peak"] == 60.0
    cells = {(c["dow"], c["hour"]): c["value"] for c in usage["heatmap"]}
    # 2026-08-03 is a Monday (dow 0).
    assert cells[(0, 10)] == 50.0
    assert cells[(0, 11)] == 85.0  # a100 60 + a40 25


def test_http_cluster_and_usage_carry_the_stats(tmp_data_dir):
    _seed_config(tmp_data_dir)
    _seed_summaries(tmp_data_dir)
    status, body = _call("GET", "/api/v1/cluster")
    assert status == 200
    assert body["fairshare"]["factor"] == 0.45
    assert body["stats"]["runs"] == 3
    assert any(g["gpu_type"] == "a100" for g in body["gpu_fleet"])
    status, body = _call("GET", "/api/v1/cluster/usage?hours=24")
    assert status == 200
    assert body["usage"]["heatmap"]
    assert body["outcomes"]["counts"]["CANCELLED"] == 1
    assert body["stats"]["gpu_hours"] == 3.5
    status, body = _call("GET", "/api/v1/cluster/queue")
    assert status == 200
    gpu = next(p for p in body["partitions"] if p["name"] == "gpu")
    assert gpu["util"] == 75.0


def _seed_raw_jobs(data_dir):
    archive = data_dir / "archive" / "2026-07-22"
    archive.mkdir(parents=True)
    con = sqlite3.connect(archive / "raw_jobs.db")
    con.execute(
        "CREATE TABLE raw_jobs(job_id TEXT PRIMARY KEY, user TEXT, account TEXT, "
        "partition TEXT, state TEXT, submit TEXT, start TEXT, end TEXT, "
        "elapsed TEXT, nnodes INTEGER, ncpus INTEGER, req_mem TEXT, "
        "alloc_tres TEXT, exit_code TEXT)"
    )
    con.executemany(
        "INSERT INTO raw_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("1", "alice_umass_edu", "pi_lab", "gpu", "COMPLETED",
             "2026-07-01", "2026-07-01", "2026-07-01", "01:30:00",
             1, 8, "16G", "gres/gpu:a100=1", "0:0"),
            ("2", "alice_umass_edu", "pi_lab", "gpu", "COMPLETED",
             "2026-07-02", "2026-07-02", "2026-07-02", "00:30:00",
             1, 8, "16G", "gres/gpu:a100=1", "0:0"),
            ("3", "labmate_umass_edu", "pi_lab", "cpu", "COMPLETED",
             "2026-07-02", "2026-07-02", "2026-07-02", "02:00:00",
             1, 8, "16G", "cpu=8", "0:0"),
        ],
    )
    con.commit()
    con.close()


def test_users_are_empty_without_a_job_history(tmp_data_dir):
    body = snapshot.users()
    assert body["available"] is False
    assert body["rows"] == []


def test_users_group_cluster_accounts_and_their_hours(tmp_data_dir):
    _seed_raw_jobs(tmp_data_dir)
    body = snapshot.users()
    assert body["available"] is True
    by_name = {r["user"]: r for r in body["rows"]}
    assert by_name["alice_umass_edu"]["jobs"] == 2
    assert by_name["alice_umass_edu"]["hours"] == 2.0
    assert by_name["labmate_umass_edu"]["jobs"] == 1
    assert by_name["labmate_umass_edu"]["hours"] == 2.0
    assert body["rows"][0]["user"] == "alice_umass_edu"


def test_http_cluster_carries_users(tmp_data_dir):
    _seed_raw_jobs(tmp_data_dir)
    status, body = _call("GET", "/api/v1/cluster")
    assert status == 200
    assert any(r["user"] == "alice_umass_edu" for r in body["users"]["rows"])


def test_a_corrupt_summaries_db_degrades(tmp_data_dir):
    (tmp_data_dir / "summaries.db").write_bytes(b"not a database")
    assert snapshot.usage(24)["available"] is False
    assert snapshot.outcomes()["available"] is False
    assert snapshot.task_stats()["available"] is False
    assert snapshot.cluster()["stats"]["available"] is False
