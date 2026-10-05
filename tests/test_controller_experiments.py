"""Attached-project catalog, fixed launch plans, and sync policy."""

import json
from pathlib import Path

from controller import registry
from controller import dispatch
from controller.http import Request, handle


def _call(method, path, body=None):
    raw = b"" if body is None else json.dumps(body).encode()
    response = handle(Request(method=method, path=path, body=raw))
    return response.status, json.loads(response.body)


def _catalog(root: Path, entries: list[dict]):
    unity = root / "unityHPC"
    unity.mkdir(exist_ok=True)
    (unity / "experiments.json").write_text(json.dumps({
        "schema_version": 1, "experiments": entries,
    }))


def test_project_resources_catalog_and_sync_policy(tmp_project, tmp_data_dir):
    _catalog(tmp_project, [{
        "id": "canary", "title": "Toolchain canary", "status": "ready",
        "resources": {"gpus_per_task": 1, "gpu_type": "A100 80GB"},
    }])
    status, body = _call("POST", "/api/v1/projects", {
        "slug": "lab", "path": str(tmp_project), "primitive": "gpu",
        "resources": {"cpus_per_task": 8, "memory_gb": 64},
        "sync_policy": "disabled",
        "overrides": {"WALLTIME": "00:20:00"},
    })
    assert status == 201, body
    assert body["project"]["resources"]["memory_gb"] == 64
    assert body["project"]["sync_policy"] == "disabled"
    assert body["project"]["experiments"][0]["id"] == "canary"
    status, body = _call("POST", "/api/v1/projects/lab/sync", {})
    assert status == 400
    assert "disabled" in body["error"]
    status, body = _call("GET", "/api/v1/projects/lab/experiments")
    assert status == 200
    assert body["experiments"][0]["resources"]["gpus_per_task"] == 1
    status, body = _call("PATCH", "/api/v1/projects/lab", {
        "resources": {"gpus_per_task": 1, "notes": "pinned"},
    })
    assert status == 200
    assert body["project"]["sync_policy"] == "disabled"
    assert body["project"]["resources"]["notes"] == "pinned"
    assert body["project"]["overrides"] == {"WALLTIME": "00:20:00"}
    # A later /unity-hpc:connect call only supplies connection fields. It must
    # not silently re-enable the unsafe sync path.
    status, body = _call("POST", "/api/v1/projects", {
        "slug": "lab", "path": str(tmp_project), "primitive": "gpu",
    })
    assert status == 201
    assert body["project"]["sync_policy"] == "disabled"
    assert body["project"]["resources"]["notes"] == "pinned"
    assert body["project"]["overrides"] == {"WALLTIME": "00:20:00"}


def test_catalog_script_preview_and_live_gate(tmp_project, tmp_data_dir):
    script = tmp_project / "launch.sh"
    script.write_text('#!/usr/bin/env bash\nprintf "arg:%s\\n" "$@"\n')
    _catalog(tmp_project, [{
        "id": "model-stage", "title": "A model and stage", "status": "needs_input",
        "resources": {"gpus_per_task": 1},
        "launch": {"kind": "script", "path": "launch.sh",
                   "args": ["model", "t1"], "dry_run_arg": "--dry-run"},
    }])
    registry.attach("lab", tmp_project)
    status, body = _call("POST", "/api/v1/projects/lab/experiments/model-stage/runs",
                         {"dry_run": True})
    assert status == 200, body
    assert body["dry_run"] is True
    assert body["output"].splitlines() == ["arg:model", "arg:t1", "arg:--dry-run"]
    status, body = _call("POST", "/api/v1/projects/lab/experiments/model-stage/runs", {})
    assert status == 400
    assert "needs_input" in body["error"]
    status, body = _call("POST", "/api/v1/projects/lab/experiments/model-stage/runs",
                         {"dry_run": True, "args": ["surprise"]})
    assert status == 400
    assert "only dry_run" in body["error"]


def test_catalog_script_cannot_escape_project(tmp_project, tmp_data_dir, tmp_path):
    outside = tmp_path / "outside.sh"
    outside.write_text("#!/usr/bin/env bash\nexit 0\n")
    (tmp_project / "launch.sh").symlink_to(outside)
    _catalog(tmp_project, [{
        "id": "outside", "status": "ready", "launch": {
            "kind": "script", "path": "launch.sh", "args": [],
            "dry_run_arg": "--dry-run",
        },
    }])
    registry.attach("lab", tmp_project)
    status, body = _call("POST", "/api/v1/projects/lab/experiments/outside/runs",
                         {"dry_run": True})
    assert status == 400
    assert "inside the project" in body["error"]


def test_bad_catalog_does_not_hide_attached_project(tmp_project, tmp_data_dir):
    unity = tmp_project / "unityHPC"
    unity.mkdir()
    (unity / "experiments.json").write_text("{bad json")
    registry.attach("lab", tmp_project)
    status, body = _call("GET", "/api/v1/projects/lab")
    assert status == 200
    assert body["project"]["experiments"] == []
    assert "cannot read" in body["project"]["experiments_error"]


def test_catalog_run_accepts_older_scaffold_override_declaration(tmp_project, tmp_data_dir):
    unity = tmp_project / "unityHPC"
    unity.mkdir()
    (unity / "run.sh").write_text('''#!/usr/bin/env bash
UNITY_OVERRIDABLE="JOB_COMMAND WALLTIME
                   SLURM_CPUS SLURM_MEM"
printf 'command:%s\\n' "$JOB_COMMAND"
printf 'argv:%s\\n' "$*"
''')
    _catalog(tmp_project, [{
        "id": "old-scaffold", "status": "needs_input",
        "launch": {"kind": "run", "exp": "preview", "campaign": "checks",
                   "overrides": {"JOB_COMMAND": "python harness/run.py"}},
    }])
    registry.attach("lab", tmp_project)
    assert "JOB_COMMAND" in dispatch._overridable(unity / "run.sh")
    status, body = _call("POST", "/api/v1/projects/lab/experiments/old-scaffold/runs",
                         {"dry_run": True})
    assert status == 200, body
    assert "command:python harness/run.py" in body["output"]
    assert "argv:run preview --campaign checks --dry-run" in body["output"]
