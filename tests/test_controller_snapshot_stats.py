"""The dashboard stats tabs read cluster, queue and usage from snapshot.py.

These checks seed the same three stores the controller already has — the
cluster config, snapshot.csv and summaries.db — and assert the public
payloads the tabs render. A missing store stays empty (I6).
"""

import json
import os
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


def test_usage_does_not_slide_back_to_old_samples(tmp_data_dir):
    _seed_config(tmp_data_dir)
    _seed_summaries(tmp_data_dir)
    usage = snapshot.usage(24)
    assert usage["available"] is False
    assert usage["window"] == "recent"
    assert usage["partial"] is False
    assert usage["slots"] == []


def test_usage_includes_heatmap_and_median(tmp_data_dir):
    _seed_config(tmp_data_dir)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    earlier = now - timedelta(hours=2)
    later = now - timedelta(hours=1)
    con = sqlite3.connect(tmp_data_dir / "summaries.db")
    con.execute(
        "CREATE TABLE hourly_resource(resource_kind TEXT, resource_id TEXT, "
        "hour_utc TEXT, util_min REAL, util_mean REAL, util_max REAL, "
        "util_p95 REAL, free_ratio REAL, samples INTEGER)"
    )
    con.executemany(
        "INSERT INTO hourly_resource VALUES(?,?,?,?,?,?,?,?,?)",
        [
            ("gpu_type", "a100", earlier.strftime("%Y-%m-%dT%H:%M:%SZ"),
             .2, .5, .8, .7, .5, 4),
            ("gpu_type", "a100", later.strftime("%Y-%m-%dT%H:%M:%SZ"),
             .2, .6, .9, .8, .4, 4),
            ("gpu_type", "a40", later.strftime("%Y-%m-%dT%H:%M:%SZ"),
             .1, .25, .4, .3, .7, 4),
        ],
    )
    con.commit()
    con.close()
    usage = snapshot.usage(24)
    assert usage["available"] is True
    assert usage["window"] == "recent"
    assert usage["partial"] is True
    assert usage["series"]["a100"] == [50.0, 60.0]
    by_type = {r["gpu_type"]: r for r in usage["by_type"]}
    assert by_type["a100"]["avg"] == 55.0
    assert by_type["a100"]["median"] == 55.0
    assert by_type["a100"]["peak"] == 60.0
    cells = {(c["dow"], c["hour"]): c["value"] for c in usage["heatmap"]}
    assert cells[(earlier.weekday(), earlier.hour)] == 50.0
    # capacity-weighted: (60*100 + 25*40) / 140
    assert cells[(later.weekday(), later.hour)] == 50.0


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
    assert body["usage"]["window"] == "recent"
    assert body["usage"]["slots"] == []
    assert body["outcomes"]["counts"] == {}
    assert body["stats"]["available"] is False
    status, body = _call("GET", "/api/v1/cluster/queue")
    assert status == 200
    gpu = next(p for p in body["partitions"] if p["name"] == "gpu")
    assert gpu["util"] == 75.0


def _live_job(job_id, user, submit, start, end, elapsed_s, *, account="pi_lab",
              partition="cpu", state="COMPLETED", cpus=8, gpus=0, gpu_type=None,
              mem_mb=16384, nodes=1):
    req = {"cpus": cpus, "mem_mb": mem_mb, "nodes": nodes}
    if gpus:
        req["gpus"] = gpus
    return {
        "job_id": job_id, "user": user, "account": account, "partition": partition,
        "state": state, "submit": submit, "start": start, "end": end,
        "gpu_type": gpu_type, "req": req, "used": {"elapsed_s": elapsed_s},
    }


def _write_live_jobs(data_dir, jobs, *, day=None, mtime=None):
    when = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    directory = data_dir / "telemetry" / when
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "task_runs.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        for job in jobs:
            handle.write(json.dumps(job) + "\n")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _seed_live_jobs(data_dir):
    _write_live_jobs(data_dir, [
        _live_job("1", "alice_umass_edu", "2026-07-01T00:00:00", "2026-07-01T00:00:00",
                  "2026-07-01T01:30:00", 5400, partition="gpu", gpus=1, gpu_type="a100"),
        _live_job("2", "alice_umass_edu", "2026-07-02T00:00:00", "2026-07-02T00:00:00",
                  "2026-07-02T00:30:00", 1800, partition="gpu", gpus=1, gpu_type="a100"),
        _live_job("3", "labmate_umass_edu", "2026-07-02T00:00:00", "2026-07-02T00:00:00",
                  "2026-07-02T02:00:00", 7200),
    ])


def _seed_frozen_archive(data_dir):
    """The July sacct dump. Users must not read it."""
    archive = data_dir / "archive" / "2026-07-22"
    archive.mkdir(parents=True)
    con = sqlite3.connect(archive / "raw_jobs.db")
    con.execute(
        "CREATE TABLE raw_jobs(job_id TEXT PRIMARY KEY, user TEXT, account TEXT, "
        "partition TEXT, state TEXT, submit TEXT, start TEXT, end TEXT, "
        "elapsed TEXT, nnodes INTEGER, ncpus INTEGER, req_mem TEXT, "
        "alloc_tres TEXT, exit_code TEXT)"
    )
    con.execute(
        "INSERT INTO raw_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("1", "archived_user", "pi_lab", "cpu", "COMPLETED",
         "2026-07-19T00:00:00", "2026-07-19T00:00:00", "2026-07-19T01:00:00",
         "01:00:00", 1, 8, "16G", "cpu=8", "0:0"),
    )
    con.commit()
    con.close()


def test_users_are_empty_without_a_job_history(tmp_data_dir):
    body = snapshot.users()
    assert body["available"] is False
    assert body["rows"] == []


def test_users_group_cluster_accounts_and_their_hours(tmp_data_dir):
    _seed_live_jobs(tmp_data_dir)
    body = snapshot.users()
    assert body["available"] is True
    by_name = {r["user"]: r for r in body["rows"]}
    alice = by_name["alice_umass_edu"]
    assert alice["jobs"] == 2
    assert alice["hours"] == 2.0
    assert alice["completed"] == 2
    assert alice["success_pct"] == 100.0
    assert alice["gpu_hours"] == 2.0
    assert alice["cpu_hours"] == 16.0
    assert alice["avg_cpus"] == 8.0
    assert alice["avg_gpus"] == 1.0
    assert alice["accounts"] == ["pi_lab"]
    assert by_name["labmate_umass_edu"]["jobs"] == 1
    assert by_name["labmate_umass_edu"]["hours"] == 2.0
    assert by_name["labmate_umass_edu"]["avg_gpus"] is None
    assert body["rows"][0]["user"] == "alice_umass_edu"


def test_users_split_states_and_derive_allocation_rates(tmp_data_dir):
    """Each Slurm state is its own bucket, and rates come from the allocations."""
    gpu = dict(partition="gpu", gpus=1, gpu_type="a100", account="pi_a")
    cpu = dict(partition="cpu", account="pi_b")
    jobs = [
        _live_job("c", "ada_umass_edu", "2026-07-01T00:00:00", "2026-07-01T00:02:00",
                  "2026-07-01T02:02:00", 7200, state="COMPLETED", cpus=4, mem_mb=8192, **gpu),
        _live_job("f", "ada_umass_edu", "2026-07-02T00:00:00", "2026-07-02T00:00:00",
                  "2026-07-02T01:00:00", 3600, state="FAILED", cpus=4, mem_mb=8192, **cpu),
        _live_job("t", "ada_umass_edu", "2026-07-03T00:00:00", "2026-07-03T00:00:00",
                  "2026-07-03T01:00:00", 3600, state="TIMEOUT", cpus=4, mem_mb=8192, **cpu),
        _live_job("r", "ada_umass_edu", "2026-07-08T00:00:00", "2026-07-08T00:00:00",
                  "2026-07-08T01:00:00", 3600, state="RUNNING", cpus=4, mem_mb=8192, **gpu),
        _live_job("p", "ada_umass_edu", "2026-07-04T00:00:00", None, None,
                  0, state="PENDING", cpus=4, mem_mb=8192, **cpu),
        _live_job("x", "ada_umass_edu", "2026-07-05T00:00:00", None, "2026-07-05T00:10:00",
                  0, state="CANCELLED by 9", cpus=4, mem_mb=8192, **cpu),
        _live_job("o", "ada_umass_edu", "2026-07-06T00:00:00", "2026-07-06T00:00:00",
                  "2026-07-06T01:00:00", 3600, state="OUT_OF_MEMORY", cpus=4, mem_mb=8192, **cpu),
        _live_job("e", "ada_umass_edu", "2026-07-07T00:00:00", "2026-07-07T00:00:00",
                  "2026-07-07T01:00:00", 3600, state="PREEMPTED", cpus=4, mem_mb=8192,
                  partition="cpu-preempt", account="pi_b"),
        _live_job("q", "ada_umass_edu", "2026-07-04T12:00:00", None, None,
                  0, state="REQUEUED", cpus=4, mem_mb=8192, **cpu),
    ]
    _write_live_jobs(tmp_data_dir, jobs)

    row = snapshot.users()["rows"][0]
    assert row["user"] == "ada_umass_edu"
    assert row["jobs"] == 9
    assert row["completed"] == 1
    assert row["failed"] == 1
    assert row["timeout"] == 1
    assert row["oom"] == 1
    assert row["preempted"] == 1
    assert row["cancelled"] == 1
    assert row["running"] == 1
    assert row["pending"] == 1
    assert row["requeued"] == 1
    assert row["other"] == 0
    settled = ("completed", "failed", "timeout", "oom", "preempted", "cancelled")
    assert sum(row[name] for name in settled) + row["running"] + row["pending"] + row["requeued"] == 9
    assert row["success_pct"] == 16.7
    assert row["hours"] == 7.0
    assert row["gpu_jobs"] == 2
    assert row["gpu_hours"] == 3.0
    assert row["cpu_hours"] == 28.0
    assert row["node_hours"] == 7.0
    assert row["mem_gb_hours"] == 56.0
    assert row["avg_cpus"] == 4.0
    assert row["avg_gpus"] == 1.0
    assert row["avg_wait_s"] == 20
    assert row["account"] == "pi_b"
    assert row["accounts"] == ["pi_b", "pi_a"]
    assert row["partition"] == "cpu"
    assert row["partitions"] == ["cpu", "gpu", "cpu-preempt"]
    assert row["gpu_type"] == "a100"
    assert row["last_seen"] == "2026-07-08T01:00:00Z"


def test_http_cluster_carries_users(tmp_data_dir):
    _seed_live_jobs(tmp_data_dir)
    status, body = _call("GET", "/api/v1/cluster")
    assert status == 200
    assert any(r["user"] == "alice_umass_edu" for r in body["users"]["rows"])


def _seed_windowed_history(data_dir):
    """Jobs and partition samples spread across the last month."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    recent = now - timedelta(hours=2)
    week = now - timedelta(days=5)
    month = now - timedelta(days=20)

    stamp = lambda when: when.strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_live_jobs(data_dir, [
        _live_job("r", "recent_user", stamp(recent), stamp(recent), stamp(recent),
                  3600, partition="gpu", gpus=1, gpu_type="a100"),
        _live_job("w", "week_user", stamp(week), stamp(week), stamp(week), 7200),
        _live_job("m", "month_user", stamp(month), stamp(month), stamp(month), 14400),
    ])

    _seed_config(data_dir)
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
            ("partition", "gpu", recent.strftime("%Y-%m-%dT%H:%M:%SZ"),
             .7, .8, .9, .85, .2, 4),
            ("partition", "gpu", week.strftime("%Y-%m-%dT%H:%M:%SZ"),
             .1, .2, .3, .25, .8, 4),
        ],
    )
    con.executemany(
        "INSERT INTO task_run VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("1", "p", "c", "s", "a100", None, None, None,
             3600, 10, None, None, None, "COMPLETED", 0,
             recent.strftime("%Y-%m-%d"), "gpu"),
            ("2", "p", "c", "s", "a100", None, None, None,
             3600, 1000, None, None, None, "COMPLETED", 0,
             week.strftime("%Y-%m-%d"), "gpu"),
        ],
    )
    con.commit()
    con.close()
    return recent, week


def test_users_hours_keeps_only_jobs_inside_the_window(tmp_data_dir):
    _seed_windowed_history(tmp_data_dir)
    day = snapshot.users(24)
    assert day["window"] == "recent"
    assert [row["user"] for row in day["rows"]] == ["recent_user"]
    week = snapshot.users(24 * 7)
    assert {row["user"] for row in week["rows"]} == {"recent_user", "week_user"}
    month = snapshot.users(24 * 30)
    assert {row["user"] for row in month["rows"]} == {
        "recent_user", "week_user", "month_user",
    }
    assert snapshot.users()["window"] == "all"
    assert len(snapshot.users()["rows"]) == 3


def test_users_do_not_slide_back_to_the_frozen_archive(tmp_data_dir):
    _seed_frozen_archive(tmp_data_dir)
    body = snapshot.users(24)
    assert body["available"] is False
    assert body["rows"] == []
    assert body["window"] == "recent"
    assert body["partial"] is False


def test_users_mark_partial_coverage_of_the_selected_window(tmp_data_dir):
    """A sample newer than the window start still leaves the earlier days blank."""
    now = datetime.now(timezone.utc)
    recent = now - timedelta(hours=2)
    stamp = recent.strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_live_jobs(tmp_data_dir, [
        _live_job("r", "recent_user", stamp, stamp, stamp, 3600,
                  partition="gpu", gpus=1, gpu_type="a100"),
    ])
    week = snapshot.users(24 * 7)
    assert week["partial"] is False
    assert week["rows"][0]["partial"] is False
    assert week["window"] == "recent"
    month = snapshot.users(24 * 30)
    assert month["partial"] is True
    assert month["rows"][0]["user"] == "recent_user"
    assert month["rows"][0]["partial"] is True
    assert "archived_user" not in {row["user"] for row in month["rows"]}


def test_users_without_samples_in_the_window_stay_blank(tmp_data_dir):
    old = datetime.now(timezone.utc) - timedelta(days=12)
    stamp = old.strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_live_jobs(
        tmp_data_dir,
        [_live_job("old", "stale_user", stamp, stamp, stamp, 3600)],
        day=old.strftime("%Y-%m-%d"),
        mtime=old.timestamp(),
    )
    day = snapshot.users(24)
    assert day["rows"] == []
    assert day["window"] == "recent"
    assert day["partial"] is True
    month = snapshot.users(24 * 30)
    assert {row["user"] for row in month["rows"]} == {"stale_user"}
    assert month["partial"] is True


def test_a_later_sample_replaces_a_running_job_and_keeps_a_settled_one(tmp_data_dir):
    stamp = "2026-10-03T00:00:00"
    _write_live_jobs(tmp_data_dir, [
        _live_job("run", "ada_umass_edu", stamp, stamp, None, 600, state="RUNNING"),
        _live_job("done", "ada_umass_edu", stamp, stamp, stamp, 3600, state="COMPLETED"),
    ])
    _write_live_jobs(tmp_data_dir, [
        _live_job("run", "ada_umass_edu", stamp, stamp, "2026-10-03T02:00:00",
                  7200, state="COMPLETED"),
        _live_job("done", "ada_umass_edu", stamp, stamp, stamp, 60, state="RUNNING"),
    ])
    row = snapshot.users()["rows"][0]
    assert row["jobs"] == 2
    assert row["completed"] == 2
    assert row["running"] == 0
    assert row["hours"] == 3.0


def test_partition_stats_follow_the_requested_window(tmp_data_dir):
    _seed_windowed_history(tmp_data_dir)
    day = {p["name"]: p for p in snapshot.partitions(24)}
    assert day["gpu"]["util"] == 80.0
    assert day["gpu"]["wait_s_avg"] == 10.0
    week = {p["name"]: p for p in snapshot.partitions(24 * 7)}
    assert week["gpu"]["util"] == 50.0
    assert week["gpu"]["wait_s_avg"] == 505.0
    latest = {p["name"]: p for p in snapshot.partitions()}
    assert latest["gpu"]["util"] == 80.0


def test_all_window_keeps_history_older_than_30_days(tmp_data_dir):
    _seed_windowed_history(tmp_data_dir)
    old = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(days=45)
    stamp = old.strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_live_jobs(tmp_data_dir, [
        _live_job("old", "old_user", stamp, stamp, stamp, 8 * 3600, partition="gpu"),
    ])
    con = sqlite3.connect(tmp_data_dir / "summaries.db")
    con.execute(
        "INSERT INTO hourly_resource VALUES(?,?,?,?,?,?,?,?,?)",
        ("partition", "gpu", stamp, 1, 1, 1, 1, 0, 4),
    )
    con.execute(
        "INSERT INTO hourly_resource VALUES(?,?,?,?,?,?,?,?,?)",
        ("gpu_type", "a100", stamp, 1, 1, 1, 1, 0, 4),
    )
    con.execute(
        "INSERT INTO task_run VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("old", "p", "c", "s", "a100", None, None, None, 3600, 50,
         None, None, None, "COMPLETED", 0, old.strftime("%Y-%m-%d"), "gpu"),
    )
    con.commit()
    con.close()

    month_users = {row["user"] for row in snapshot.users(24 * 30)["rows"]}
    assert "old_user" not in month_users
    assert "old_user" in {row["user"] for row in snapshot.users("all")["rows"]}
    month_util = next(p["util"] for p in snapshot.partitions(24 * 30) if p["name"] == "gpu")
    all_util = next(p["util"] for p in snapshot.partitions("all") if p["name"] == "gpu")
    assert month_util == 50.0
    assert all_util == 66.7
    usage = snapshot.usage("all")
    assert usage["window"] == "all"
    assert usage["hours"] is None
    assert stamp in usage["slots"]
    assert snapshot.task_stats("all")["runs"] == 3
    assert snapshot.task_stats(24 * 30)["runs"] == 2
    status, body = _call("GET", "/api/v1/cluster?hours=all")
    assert status == 200
    assert any(row["user"] == "old_user" for row in body["users"]["rows"])
    status, body = _call("GET", "/api/v1/cluster/usage?hours=all")
    assert status == 200
    assert body["usage"]["window"] == "all"
    assert body["stats"]["runs"] == 3


def test_60_and_90_day_windows_bound_cluster_endpoints(tmp_data_dir):
    _seed_windowed_history(tmp_data_dir)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    summaries = sqlite3.connect(tmp_data_dir / "summaries.db")
    for days, util in ((45, .4), (75, .6), (105, 1.0)):
        old = now - timedelta(days=days)
        stamp = old.strftime("%Y-%m-%dT%H:%M:%SZ")
        _write_live_jobs(tmp_data_dir, [
            _live_job(str(days), f"user_{days}", stamp, stamp, stamp, 3600,
                      partition="gpu", gpus=1, gpu_type="a100"),
        ])
        for kind, resource in (("partition", "gpu"), ("gpu_type", "a100")):
            summaries.execute(
                "INSERT INTO hourly_resource VALUES(?,?,?,?,?,?,?,?,?)",
                (kind, resource, stamp, util, util, util, util, 1 - util, 4),
            )
        summaries.execute(
            "INSERT INTO task_run VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(days), "p", "c", "s", "a100", None, None, None,
             3600, 50, None, None, None, "COMPLETED", 0,
             old.strftime("%Y-%m-%d"), "gpu"),
        )
    summaries.commit()
    summaries.close()

    for hours, included, excluded, runs in (
        (1440, "user_45", "user_75", 3),
        (2160, "user_75", "user_105", 4),
    ):
        status, cluster = _call("GET", f"/api/v1/cluster?hours={hours}")
        assert status == 200
        users = {row["user"] for row in cluster["users"]["rows"]}
        assert included in users
        assert excluded not in users
        assert cluster["stats"]["runs"] == runs

        status, queue = _call("GET", f"/api/v1/cluster/queue?hours={hours}")
        assert status == 200
        gpu = next(p for p in queue["partitions"] if p["name"] == "gpu")
        assert gpu["util"] == (46.7 if hours == 1440 else 50.0)

        status, usage = _call("GET", f"/api/v1/cluster/usage?hours={hours}")
        assert status == 200
        assert usage["usage"]["hours"] == hours
        assert usage["stats"]["runs"] == runs
        slots = usage["usage"]["slots"]
        assert (now - timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%SZ") in slots
        assert ((now - timedelta(days=75)).strftime("%Y-%m-%dT%H:%M:%SZ") in slots) == (hours == 2160)
        assert (now - timedelta(days=105)).strftime("%Y-%m-%dT%H:%M:%SZ") not in slots


def test_http_cluster_and_queue_honor_hours(tmp_data_dir):
    _seed_windowed_history(tmp_data_dir)
    status, body = _call("GET", "/api/v1/cluster?hours=24")
    assert status == 200
    assert [row["user"] for row in body["users"]["rows"]] == ["recent_user"]
    gpu = next(p for p in body["partitions"] if p["name"] == "gpu")
    assert gpu["util"] == 80.0
    status, queued = _call("GET", "/api/v1/cluster/queue?hours=168")
    assert status == 200
    gpu = next(p for p in queued["partitions"] if p["name"] == "gpu")
    assert gpu["util"] == 50.0
    assert gpu["jobs"] == 2


def test_a_corrupt_summaries_db_degrades(tmp_data_dir):
    (tmp_data_dir / "summaries.db").write_bytes(b"not a database")
    assert snapshot.usage(24)["available"] is False
    assert snapshot.outcomes()["available"] is False
    assert snapshot.task_stats()["available"] is False
    assert snapshot.cluster()["stats"]["available"] is False
