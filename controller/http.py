"""HTTP seam for the controller. Tests call handle(); serve.py wraps sockets."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from controller import dispatch, events, experiments, registry, snapshot, telemetry
from lib import campaign as _campaign
from controller.dispatch import DispatchError, OperationBusy
from controller.registry import RegistryError
from controller.workspace_store import WorkspaceError

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8300

#: The Vite build output. `controller/web` holds the source; `npm run build`
#: writes this directory, and `serve.py` builds it on first start when it is
#: missing. ADR 0006.
WEB_DIR = Path(__file__).resolve().parent / "web"
UI_DIR = WEB_DIR / "dist"

_SLUG = re.compile(r"^/api/v1/projects/([^/]+)(?:/(.*))?$")


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, list[str]] = field(default_factory=dict)
    body: bytes = b""


@dataclass
class Response:
    status: int
    body: bytes
    content_type: str = "application/json"
    headers: dict[str, str] = field(default_factory=dict)


def _json(status: int, payload: Any) -> Response:
    raw = json.dumps(payload, default=str).encode()
    return Response(status=status, body=raw, content_type="application/json")


def _error(status: int, message: str) -> Response:
    return _json(status, {"ok": False, "error": message})


def _slug_from_path(path: str) -> str:
    name = Path(path).name.lower()
    name = re.sub(r"[^a-z0-9_-]+", "-", name).strip("-")
    return name or "project"


def _read_json(req: Request) -> dict:
    if not req.body:
        return {}
    try:
        data = json.loads(req.body.decode())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("JSON body must be an object")
    return data


def _q(req: Request, key: str, default: str | None = None) -> str | None:
    vals = req.query.get(key) or []
    return vals[0] if vals else default


def _optional_hours(req: Request) -> int | str | None:
    """The `hours` query: an hour count, `all`, or None when the parameter is absent."""
    raw = _q(req, "hours")
    if raw is None or raw == "":
        return None
    if raw.lower() == "all":
        return "all"
    try:
        return int(raw)
    except ValueError:
        return None


def handle(req: Request) -> Response:
    """Route one request. Never talks to a socket."""
    method = req.method.upper()
    path = req.path.rstrip("/") or "/"
    try:
        return _route(method, path, req)
    except WorkspaceError as exc:
        payload = {"ok": False, "error": str(exc), "errors": getattr(exc, "errors", [])}
        if exc.status == 409:
            payload['current_version'] = getattr(exc, 'current_version', None)
            if getattr(exc, 'expected_version', None) is not None:
                payload['expected_version'] = exc.expected_version
        if '/workspace/' in req.path:
            from controller.workspace_contracts import response_metadata
            from controller.workspace_store import now
            rest = req.path.partition('/workspace/')[2]
            payload['response_metadata'] = response_metadata(payload, rest, now())
        return _json(exc.status, payload)
    except RegistryError as exc:
        return _error(400, str(exc))
    except OperationBusy as exc:
        return _error(409, str(exc))
    except DispatchError as exc:
        return _error(400, str(exc))
    except ValueError as exc:
        return _json(400, {"ok": False, "error": str(exc), "errors": getattr(exc, "errors", [])})
    except FileNotFoundError as exc:
        return _error(404, str(exc))
    except Exception as exc:  # I6: never crash the server on a bad panel
        return _error(500, f"controller error: {exc}")


def _route(method: str, path: str, req: Request) -> Response:
    if path == "/api/v1/health" and method == "GET":
        ssh = telemetry.ssh_status()
        return _json(200, {
            "ok": True,
            "service": "unity-hpc-controller",
            "projects": len(registry.list_projects()),
            "ssh": {
                "needs_passphrase": ssh.get("needs_passphrase"),
                "key_path": ssh.get("key_path") or "",
                "command": ssh.get("command") or "",
                "unlocked": ssh.get("unlocked"),
            },
        })

    if path == "/api/v1/cluster" and method == "GET":
        return _json(200, snapshot.cluster(_optional_hours(req)))

    if path == "/api/v1/cluster/queue" and method == "GET":
        hours = _optional_hours(req)
        live = snapshot.live_snapshot()
        return _json(200, {
            "partitions": snapshot.partitions(hours),
            "live": live,
        })

    if path == "/api/v1/cluster/usage" and method == "GET":
        raw_hours = _q(req, "hours", "24") or "24"
        if raw_hours.lower() == "all":
            hours = "all"
        else:
            try:
                hours = int(raw_hours)
            except ValueError:
                hours = 24
        return _json(200, {
            "usage": snapshot.usage(hours),
            "outcomes": snapshot.outcomes(hours),
            "stats": snapshot.task_stats(hours),
        })

    if path == "/api/v1/telemetry" and method == "GET":
        try:
            limit = int(_q(req, "limit", "10") or "10")
        except ValueError:
            limit = 10
        return _json(200, {"telemetry": telemetry.status(limit)})

    if path == "/api/v1/telemetry/script" and method == "POST":
        body = _read_json(req)
        result = telemetry.start_script(
            mode=body.get("mode"),
            reason=body.get("reason") or "manual",
        )
        return _json(202 if result.get("started") else 200, result)

    if path == "/api/v1/telemetry/session" and method == "POST":
        body = _read_json(req)
        if body.get("action") != "close":
            raise ValueError("action must be close")
        return _json(200, telemetry.close_session())

    if path == "/api/v1/telemetry/sync" and method == "POST":
        body = _read_json(req)
        result = telemetry.start_sync(reason=body.get("reason") or "manual")
        # 202: the retrieval runs in its own thread, so this answer is only the
        # decision to start. The panel polls /api/v1/telemetry for the outcome.
        return _json(202 if result.get("started") else 200, result)

    if path == "/api/v1/telemetry/settings" and method == "PATCH":
        body = _read_json(req)
        keys = ("source", "schedule_enabled", "interval_minutes", "script_mode",
                "ssh_host", "ssh_identity")
        saved = telemetry.save_settings(**{k: body[k] for k in keys if k in body})
        events.record("configure", "updated telemetry retrieval settings")
        return _json(200, {"ok": True, "settings": saved,
                           "telemetry": telemetry.status()})

    if path == "/api/v1/telemetry/ssh-test" and method == "POST":
        return _json(200, telemetry.probe_ssh())

    if path == "/api/v1/telemetry/ssh-unlock" and method == "POST":
        body = _read_json(req)
        return _json(200, telemetry.unlock_ssh(body.get("passphrase") or ""))

    if path == "/api/v1/jobs" and method == "GET":
        return _json(200, {"jobs": snapshot.all_jobs()})

    if path == "/api/v1/jobs/delete" and method == "POST":
        result = _forget_jobs(_read_json(req))
        events.record(
            "forget",
            f"removed {result['deleted']} rows from Job Monitor",
            deleted=result["deleted"],
        )
        return _json(200, result)

    if path == "/api/v1/events" and method == "GET":
        try:
            limit = int(_q(req, "limit", "50") or "50")
        except ValueError:
            limit = 50
        return _json(200, {"events": events.recent(limit)})

    if path == "/api/v1/projects" and method == "GET":
        details = []
        for rec in registry.list_projects():
            details.append(snapshot.project_detail(rec["slug"]) or rec)
        return _json(200, {"projects": details})

    if path == "/api/v1/projects" and method == "POST":
        body = _read_json(req)
        if not body.get("path"):
            return _error(400, "path is required")
        slug = body.get("slug") or _slug_from_path(body["path"])
        existing = registry.get(slug)
        if "application" in body:
            application = body.get("application") or ""
        else:
            application = (existing or {}).get("application") or ""
        rec = registry.attach(
            slug=slug,
            path=body["path"],
            primitive=body.get("primitive") or (existing or {}).get("primitive") or "cpu",
            remote_dir=body.get("remote_dir") or (existing or {}).get("remote_dir") or "",
            unity_host=body.get("unity_host") or "unity",
            campaign=body.get("campaign") or "",
            overrides=body.get("overrides"),
            resources=body.get("resources"),
            sync_policy=body.get("sync_policy"),
            application=application,
        )
        events.record("attach", f"attached {rec['slug']}", slug=rec["slug"])
        _write_client_stub(rec)
        return _json(201, {"ok": True, "project": snapshot.project_detail(rec["slug"])})

    match = _SLUG.match(path)
    if match:
        slug, rest = match.group(1), match.group(2) or ""
        return _project_route(method, slug, rest, req)

    if path.startswith("/api/"):
        return _error(404, f"no route {method} {path}")

    if method == "GET":
        return _static(path)

    return _error(404, f"no route {method} {path}")


def _project_route(method: str, slug: str, rest: str, req: Request) -> Response:
    if rest == "runner" or rest.startswith("runner/"):
        from controller.runner_http import route as runner_route
        return runner_route(method, slug, rest[len("runner/"):] if rest != "runner" else "", req)

    if rest.startswith("workspace/"):
        from controller.workspace_http import route
        return route(method, slug, rest[len("workspace/"):], req)

    if rest == "genai" or rest.startswith("genai/"):
        from controller.genai_http import route as genai_route
        if registry.get(slug) is None:
            return _error(404, f"unknown project {slug!r}")
        return genai_route(method, slug, rest[len("genai/"):] if rest != "genai" else "", req)

    if rest == "" and method == "GET":
        detail = snapshot.project_detail(slug)
        if detail is None:
            return _error(404, f"unknown project {slug!r}")
        return _json(200, {"project": detail})

    if rest == "" and method == "PATCH":
        body = _read_json(req)
        rec = registry.update(slug, **{
            k: body[k] for k in (
                "path", "primitive", "remote_dir", "unity_host",
                "campaign", "overrides", "application",
                "resources", "sync_policy",
            ) if k in body
        })
        events.record("configure", f"updated {slug}", slug=slug)
        _write_client_stub(rec)
        return _json(200, {"ok": True, "project": snapshot.project_detail(slug)})

    if rest == "" and method == "DELETE":
        if not registry.detach(slug):
            return _error(404, f"unknown project {slug!r}")
        events.record("detach", f"detached {slug}", slug=slug)
        return _json(200, {"ok": True})

    if rest == "jobs" and method == "GET":
        if registry.get(slug) is None:
            return _error(404, f"unknown project {slug!r}")
        return _json(200, {
            "jobs": snapshot.project_jobs(slug, _q(req, "campaign")),
        })

    if rest == "experiments" and method == "GET":
        if registry.get(slug) is None:
            return _error(404, f"unknown project {slug!r}")
        return _json(200, experiments.read(slug))

    experiment_run = re.fullmatch(r"experiments/([^/]+)/runs", rest)
    if experiment_run and method == "POST":
        body = _read_json(req)
        if any(key != "dry_run" for key in body):
            raise ValueError("catalog launch accepts only dry_run")
        if "dry_run" in body and not isinstance(body["dry_run"], bool):
            raise ValueError("dry_run must be a boolean")
        result = experiments.launch(slug, experiment_run.group(1),
                                    dry_run=body.get("dry_run", False))
        return _json(200 if result["ok"] else 502, result)

    if rest == "runs" and method == "POST":
        body = _read_json(req)
        manifest = body.get("manifest")
        if manifest:
            result = dispatch.array(
                slug,
                manifest=manifest if isinstance(manifest, str) else "",
                campaign=body.get("campaign"),
                extra_args=body.get("extra_args") or "",
            )
        else:
            exp = body.get("exp") or body.get("name")
            if not exp:
                return _error(400, "runs require 'exp' (or a 'manifest' path)")
            result = dispatch.run(
                slug,
                exp=exp,
                campaign=body.get("campaign"),
                dry_run=bool(body.get("dry_run")),
                overrides=body.get("overrides") or {},
                extra_args=body.get("extra_args") or "",
            )
        return _json(200 if result["ok"] else 502, result)

    if rest in ("runs/cancel", "stop", "cancel") and method == "POST":
        body = _read_json(req)
        result = dispatch.cancel(
            slug,
            campaign=body.get("campaign"),
            job=body.get("job"),
        )
        return _json(200 if result["ok"] else 502, result)

    if rest == "fetch" and method == "POST":
        body = _read_json(req)
        result = dispatch.fetch(slug, campaign=body.get("campaign"))
        return _json(200 if result["ok"] else 502, result)

    if rest == "sync" and method == "POST":
        result = dispatch.sync(slug)
        return _json(200 if result["ok"] else 502, result)

    if rest == "status" and method == "POST":
        body = _read_json(req)
        result = dispatch.status(slug, campaign=body.get("campaign"))
        return _json(200 if result["ok"] else 502, result)

    return _error(404, f"no route {method} /api/v1/projects/{slug}/{rest}")


def _forget_jobs(body: dict) -> dict:
    """Hide selected monitor rows while retaining the project ledger receipts.

    The body is ``{"jobs": [{"slug", "campaign", "job_id"}, ...]}``. Each
    identity must already exist on an attached project. Duplicate identities
    count once. This does not call ``run.sh``.
    """
    if not isinstance(body, dict):
        raise ValueError("Request body must be an object")
    items = body.get("jobs")
    if not isinstance(items, list) or not items:
        raise ValueError("jobs must list the rows to remove")
    grouped: dict[tuple[str, str], list[str]] = {}
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each job needs slug, campaign, and job_id")
        slug = item.get("slug")
        campaign_name = item.get("campaign")
        job_id = item.get("job_id")
        if (
            not isinstance(slug, str)
            or not isinstance(campaign_name, str)
            or not isinstance(job_id, str)
            or not slug
            or not campaign_name
            or not job_id
        ):
            raise ValueError("each job needs slug, campaign, and job_id")
        rec = registry.get(slug)
        if rec is None:
            raise ValueError(f"unknown project {slug!r}")
        root = Path(rec["path"])
        if campaign_name not in _campaign.campaigns(root):
            raise ValueError(f"unknown campaign {campaign_name!r} on {slug}")
        identity = (slug, campaign_name, job_id)
        if identity in seen:
            continue
        seen.add(identity)
        grouped.setdefault((slug, campaign_name), []).append(job_id)
    deleted = 0
    for (slug, campaign_name), ids in grouped.items():
        rec = registry.get(slug)
        if rec is None:
            raise ValueError(f"unknown project {slug!r}")
        deleted += _campaign.forget(Path(rec["path"]), campaign_name, ids)
    return {"ok": True, "deleted": deleted, "missing": len(seen) - deleted}


def _write_client_stub(rec: dict) -> None:
    """Write unityHPC/controller.json so the plugin knows where to POST."""
    unity = Path(rec["path"]) / "unityHPC"
    if not unity.is_dir():
        return
    stub = {
        "controller": f"http://127.0.0.1:{DEFAULT_PORT}",
        "slug": rec["slug"],
        "primitive": rec["primitive"],
    }
    if rec.get("application"):
        stub["application"] = rec["application"]
    try:
        (unity / "controller.json").write_text(json.dumps(stub, indent=2) + "\n")
    except OSError:
        return


_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".map": "application/json",
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}

#: Hashed build assets never change under their own name, so they are safe to
#: cache hard. `index.html` names them, and it is never cached.
_IMMUTABLE_DIR = "assets/"

_NOT_BUILT = (
    "The dashboard is not built.\n\n"
    "Run it once:\n"
    "    cd controller/web && npm install && npm run build\n\n"
    "`hpc-controller` does this on start when Node is on PATH.\n"
)


def _index_missing() -> Response:
    return Response(
        status=503,
        body=_NOT_BUILT.encode(),
        content_type="text/plain; charset=utf-8",
    )


def _static(path: str) -> Response:
    """
    Serve one built file, or `index.html` for any other path.

    The dashboard is a single-page app, so a deep link such as
    `/cluster/queue` is not a file. Every GET that is not an API route and not
    a real file answers with `index.html`, and the router reads the path. A
    request under the hashed asset directory is never rewritten: a missing
    asset must be a 404, not an HTML page that a script tag cannot parse.
    """
    index = UI_DIR / "index.html"
    rel = "index.html" if path == "/" else path.lstrip("/")
    root = UI_DIR.resolve()
    target = (UI_DIR / rel).resolve()
    inside = True
    try:
        target.relative_to(root)
    except ValueError:
        inside = False

    if inside and target.is_file():
        ctype = _STATIC_TYPES.get(target.suffix, "application/octet-stream")
        headers = {}
        if rel.startswith(_IMMUTABLE_DIR):
            headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return Response(
            status=200,
            body=target.read_bytes(),
            content_type=ctype,
            headers=headers,
        )

    if not inside or rel.startswith(_IMMUTABLE_DIR) or "." in Path(rel).name:
        if not index.is_file():
            return _index_missing()
        return Response(status=404, body=b"not found", content_type="text/plain")

    if not index.is_file():
        return _index_missing()
    return Response(
        status=200,
        body=index.read_bytes(),
        content_type=_STATIC_TYPES[".html"],
    )


def parse_raw(method: str, url: str, body: bytes = b"") -> Request:
    parsed = urlparse(url)
    return Request(
        method=method,
        path=parsed.path,
        query=parse_qs(parsed.query),
        body=body,
    )
