"""Controller HTTP seam — handle() with no sockets."""

import json
import sqlite3

import pytest

from controller.http import Request, handle
from controller import registry
from lib import campaign as _campaign


def _call(method, path, body=None):
    raw = b"" if body is None else json.dumps(body).encode()
    req = Request(method=method, path=path, body=raw)
    resp = handle(req)
    payload = json.loads(resp.body.decode()) if resp.body else {}
    return resp.status, payload


def test_health_ok(tmp_data_dir):
    status, body = _call("GET", "/api/v1/health")
    assert status == 200
    assert body["ok"] is True
    assert body["projects"] == 0
    assert "needs_passphrase" in body["ssh"]
    assert "key_path" in body["ssh"]


def test_cluster_empty_without_shared_data(tmp_data_dir):
    status, body = _call("GET", "/api/v1/cluster")
    assert status == 200
    assert body["kpis"]["attached_projects"] == 0
    assert body["live"]["available"] is False
    assert body["partitions"] == []


def test_attach_list_detail_and_detach(tmp_project, tmp_data_dir):
    status, body = _call("POST", "/api/v1/projects", {
        "slug": "phd-gnn",
        "path": str(tmp_project),
        "primitive": "gpu",
        "remote_dir": "/work/x",
    })
    assert status == 201, body
    assert body["project"]["slug"] == "phd-gnn"
    assert body["project"]["scaffold"] is False

    status, body = _call("GET", "/api/v1/projects")
    assert status == 200
    assert [p["slug"] for p in body["projects"]] == ["phd-gnn"]

    status, body = _call("GET", "/api/v1/projects/phd-gnn")
    assert status == 200
    assert body["project"]["remote_dir"] == "/work/x"

    status, body = _call("PATCH", "/api/v1/projects/phd-gnn", {"campaign": "c1"})
    assert status == 200
    assert body["project"]["campaign"] == "c1"

    status, body = _call("DELETE", "/api/v1/projects/phd-gnn")
    assert status == 200
    status, body = _call("GET", "/api/v1/projects/phd-gnn")
    assert status == 404


def test_attach_requires_path(tmp_data_dir):
    status, body = _call("POST", "/api/v1/projects", {"slug": "x"})
    assert status == 400
    assert "path" in body["error"]


def test_overlapping_project_operations_return_conflict(tmp_project, tmp_data_dir):
    from controller import dispatch

    registry.attach("lab", tmp_project)
    rec = registry.get("lab")
    with dispatch._operation(rec, "fetch"):
        status, body = _call("POST", "/api/v1/projects/lab/fetch", {})
        assert status == 409
        assert "fetch in progress" in body["error"]
    with dispatch._operation(rec, "launch"):
        status, body = _call("POST", "/api/v1/projects/lab/runs", {
            "exp": "smoke", "dry_run": True,
        })
        assert status == 409
        assert "launch in progress" in body["error"]


def test_status_uses_selected_campaign(tmp_project, tmp_data_dir, monkeypatch):
    from controller import dispatch

    registry.attach("lab", tmp_project)
    monkeypatch.setattr(dispatch, "_run", lambda _rec, argv, **_kw: {
        "ok": True, "argv": argv,
    })
    status, body = _call("POST", "/api/v1/projects/lab/status", {
        "campaign": "older-campaign",
    })
    assert status == 200
    assert body["argv"] == ["status", "--campaign", "older-campaign"]


def test_jobs_from_attached_ledger(tmp_project, tmp_data_dir):
    registry.attach("lab", tmp_project, primitive="cpu")
    _campaign.record(tmp_project, "2026-09-21", "12345", "smoke", "cpu")
    status, body = _call("GET", "/api/v1/projects/lab/jobs")
    assert status == 200
    assert body["jobs"][0]["job_id"] == "12345"
    assert body["jobs"][0]["exp"] == "smoke"
    status, body = _call("GET", "/api/v1/jobs")
    assert any(j["job_id"] == "12345" and j["slug"] == "lab" for j in body["jobs"])


def test_jobs_fold_local_telemetry_without_ssh(tmp_project, tmp_data_dir, monkeypatch):
    from controller import dispatch
    from lib import paths

    registry.attach("lab", tmp_project, primitive="gpu")
    _campaign.record(tmp_project, "c1", "12345", "smoke", "gpu")
    con = sqlite3.connect(paths.summaries_db())
    con.execute("CREATE TABLE task_run(job_id TEXT, hardware TEXT, elapsed_s REAL, "
                "wait_s REAL, cpu_eff REAL, mem_eff REAL, max_rss_mb REAL, "
                "state TEXT, exit_code INTEGER, day_utc TEXT)")
    con.execute("INSERT INTO task_run VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("12345", "a100", 42.0, None, None, None, None,
                 "COMPLETED", 0, "2026-09-28"))
    con.commit()
    con.close()
    monkeypatch.setattr(dispatch, "_run", lambda *_args, **_kw: (_ for _ in ()).throw(
        AssertionError("GET jobs must not call run.sh or SSH")))

    status, body = _call("GET", "/api/v1/jobs")
    assert status == 200
    assert body["jobs"][0]["status"] == "COMPLETED"
    assert body["jobs"][0]["hardware"] == "a100"
    status, body = _call("GET", "/api/v1/projects/lab/jobs")
    assert status == 200
    assert body["jobs"][0]["status"] == "COMPLETED"


def test_delete_jobs_removes_only_the_selected_ledger_rows(tmp_project, tmp_data_dir, monkeypatch):
    from controller import dispatch, events

    registry.attach("lab", tmp_project, primitive="cpu")
    _campaign.record(tmp_project, "c1", "111", "keep", "cpu")
    _campaign.record(tmp_project, "c1", "222", "drop", "cpu")
    _campaign.record(tmp_project, "c2", "333", "other", "cpu")
    monkeypatch.setattr(dispatch, "_run", lambda *_args, **_kw: (_ for _ in ()).throw(
        AssertionError("deleting a ledger row must not call run.sh")))

    status, body = _call("POST", "/api/v1/jobs/delete", {
        "jobs": [
            {"slug": "lab", "campaign": "c1", "job_id": "222"},
            {"slug": "lab", "campaign": "c1", "job_id": "222"},
        ],
    })
    assert status == 200, body
    assert body["deleted"] == 1
    assert body["missing"] == 0
    assert any(row.get("kind") == "forget" for row in events.recent())
    assert {row["job_id"] for row in _campaign.jobs(tmp_project, "c1")} == {"111", "222"}
    assert "222" in _campaign.all_job_ids(tmp_project), "management and recovery retain scheduler receipts"

    status, body = _call("GET", "/api/v1/jobs")
    assert {(job["campaign"], job["job_id"]) for job in body["jobs"]} == {
        ("c1", "111"),
        ("c2", "333"),
    }


def test_delete_jobs_rejects_an_unknown_project(tmp_data_dir):
    status, body = _call("POST", "/api/v1/jobs/delete", {
        "jobs": [{"slug": "nope", "campaign": "c1", "job_id": "1"}],
    })
    assert status == 400
    assert "unknown project" in body["error"]


def test_delete_jobs_requires_a_list(tmp_data_dir):
    status, body = _call("POST", "/api/v1/jobs/delete", {})
    assert status == 400
    assert "jobs" in body["error"]


def test_job_poll_without_telemetry_does_not_rewrite_ledger(tmp_project, tmp_data_dir):
    registry.attach("lab", tmp_project)
    _campaign.record(tmp_project, "c1", "12345", "smoke", "cpu")
    db = tmp_project / ".unity_state" / "c1.db"
    before = db.stat().st_mtime_ns
    status, body = _call("GET", "/api/v1/jobs")
    assert status == 200
    assert body["jobs"][0]["status"] == "PENDING"
    assert db.stat().st_mtime_ns == before


def test_root_serves_the_dashboard(tmp_data_dir):
    """The page itself, when it is built.

    The dashboard is a Vite bundle, so the markup is one mount point and a
    script tag; the panels are in the bundle. `tests/test_controller_web.py`
    covers the routing rules, and it skips the same way when nothing is built.
    """
    resp = handle(Request(method="GET", path="/"))
    if resp.status == 503:
        pytest.skip("run `cd controller/web && npm run build` first")
    assert resp.status == 200
    assert resp.content_type.startswith("text/html")
    assert b'<div id="root">' in resp.body
    assert b"Unity HPC" in resp.body


def test_unknown_route(tmp_data_dir):
    status, body = _call("GET", "/api/v1/nope")
    assert status == 404
