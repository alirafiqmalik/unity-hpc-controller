import importlib.util
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _serve(tmp_path, monkeypatch):
    monkeypatch.setenv("UNITY_HPC_DATA", str(tmp_path))
    spec = importlib.util.spec_from_file_location(
        "dashboard_serve", ROOT / "cluster-intel" / "dashboard" / "serve.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_historical_reads_live_summaries(tmp_path, monkeypatch):
    con = sqlite3.connect(tmp_path / "summaries.db")
    con.execute(
        "CREATE TABLE hourly_resource(resource_kind TEXT, resource_id TEXT, "
        "hour_utc TEXT, util_min REAL, util_mean REAL, util_max REAL, "
        "util_p95 REAL, free_ratio REAL, samples INTEGER)"
    )
    con.execute(
        "CREATE TABLE task_run(job_id TEXT, project TEXT, campaign TEXT, "
        "submit TEXT, wait_s REAL, state TEXT)"
    )
    con.execute(
        "INSERT INTO hourly_resource VALUES('gpu_type','a100',?,?,?,?,?,?,?)",
        ("2026-07-30T10:00:00Z", .2, .5, .8, .7, .5, 4),
    )
    con.execute(
        "INSERT INTO task_run VALUES('1','proj','camp',?,?,?)",
        ("2026-07-30T10:00:00Z", 12, "COMPLETED"),
    )
    con.commit()
    con.close()

    serve = _serve(tmp_path, monkeypatch)
    out = serve.historical(24 * 3650, "proj", "camp")
    assert out["available"] is True
    assert out["series"]["a100"] == [50.0]
    assert out["task_stats"]["runs"] == 1
    assert out["task_stats"]["success_rate"] == 1.0
    assert out["freshness_utc"] == "2026-07-30T10:00:00Z"


def test_historical_is_empty_without_live_database(tmp_path, monkeypatch):
    serve = _serve(tmp_path, monkeypatch)
    assert serve.historical(24)["available"] is False


def test_main_explains_an_in_use_port(tmp_path, monkeypatch, capsys):
    import errno
    import sys

    serve = _serve(tmp_path, monkeypatch)

    def occupied(*_args, **_kwargs):
        raise OSError(errno.EADDRINUSE, "address already in use")

    monkeypatch.setattr(serve, "ThreadingHTTPServer", occupied)
    monkeypatch.setattr(sys, "argv", ["serve.py", "--port", "8899"])
    assert serve.main() == 2
    err = capsys.readouterr().err
    assert "8899" in err and "already in use" in err
