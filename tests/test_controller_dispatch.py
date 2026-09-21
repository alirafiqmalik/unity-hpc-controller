"""Controller dispatch — calls the attached project's run.sh, never sbatch."""

from pathlib import Path

from controller import dispatch, registry
from controller.http import Request, handle
import json


def _install_stub_runner(project: Path, body: str) -> None:
    unity = project / "unityHPC"
    unity.mkdir()
    runner = unity / "run.sh"
    runner.write_text(body)
    runner.chmod(0o755)


def _call(method, path, body=None):
    raw = b"" if body is None else json.dumps(body).encode()
    resp = handle(Request(method=method, path=path, body=raw))
    return resp.status, json.loads(resp.body.decode())


STUB = """#!/usr/bin/env bash
UNITY_OVERRIDABLE=(JOB_COMMAND WALLTIME SLURM_PARTITION CAMPAIGN)
echo "argv:$*"
echo "JOB_COMMAND=${JOB_COMMAND-unset}"
if [[ " $* " == *" --dry-run "* ]]; then
  echo "[dry-run] would submit"
  exit 0
fi
echo "Recorded job 999"
exit 0
"""


def test_run_records_through_run_sh(tmp_project, tmp_data_dir):
    _install_stub_runner(tmp_project, STUB)
    registry.attach("lab", tmp_project, primitive="cpu")
    result = dispatch.run("lab", "smoke", dry_run=True)
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert "smoke" in result["output"]

    result = dispatch.run("lab", "smoke", overrides={"JOB_COMMAND": "echo hi"})
    assert result["ok"] is True
    assert "Recorded job" in result["output"]
    assert "JOB_COMMAND=echo hi" in result["output"]


def test_http_dispatch_and_cancel(tmp_project, tmp_data_dir):
    _install_stub_runner(tmp_project, STUB)
    registry.attach("lab", tmp_project, primitive="cpu")
    status, body = _call("POST", "/api/v1/projects/lab/runs", {
        "exp": "smoke", "dry_run": True,
    })
    assert status == 200, body
    assert body["dry_run"] is True

    status, body = _call("POST", "/api/v1/projects/lab/stop", {})
    assert status == 200, body
    assert "cancel" in body["argv"]


def test_dispatch_rejects_unsafe_exp(tmp_project, tmp_data_dir):
    _install_stub_runner(tmp_project, STUB)
    registry.attach("lab", tmp_project, primitive="cpu")
    status, body = _call("POST", "/api/v1/projects/lab/runs", {"exp": "a;rm"})
    assert status == 400
    assert "unsafe" in body["error"]


def test_dispatch_unknown_project(tmp_data_dir):
    status, body = _call("POST", "/api/v1/projects/nope/runs", {"exp": "x"})
    assert status == 400
    assert "unknown project" in body["error"]


def test_missing_runner(tmp_project, tmp_data_dir):
    registry.attach("lab", tmp_project, primitive="cpu")
    status, body = _call("POST", "/api/v1/projects/lab/runs", {"exp": "x"})
    assert status == 400
    assert "run.sh" in body["error"]
