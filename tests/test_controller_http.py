"""Controller HTTP seam — handle() with no sockets."""

import json

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


def test_jobs_from_attached_ledger(tmp_project, tmp_data_dir):
    registry.attach("lab", tmp_project, primitive="cpu")
    _campaign.record(tmp_project, "2026-09-21", "12345", "smoke", "cpu")
    status, body = _call("GET", "/api/v1/projects/lab/jobs")
    assert status == 200
    assert body["jobs"][0]["job_id"] == "12345"
    assert body["jobs"][0]["exp"] == "smoke"
    status, body = _call("GET", "/api/v1/jobs")
    assert any(j["job_id"] == "12345" and j["slug"] == "lab" for j in body["jobs"])


def test_root_serves_the_dashboard(tmp_data_dir):
    req = Request(method="GET", path="/")
    resp = handle(req)
    assert resp.status == 200
    assert b"Unity HPC Controller" in resp.body
    assert b"/api/v1/projects" in resp.body


def test_unknown_route(tmp_data_dir):
    status, body = _call("GET", "/api/v1/nope")
    assert status == 404
