"""HTTP seam for the controller. Tests call handle(); serve.py wraps sockets."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from controller import dispatch, events, registry, snapshot
from controller.dispatch import DispatchError
from controller.registry import RegistryError

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8300

UI_DIR = Path(__file__).resolve().parent / "ui"

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


def handle(req: Request) -> Response:
    """Route one request. Never talks to a socket."""
    method = req.method.upper()
    path = req.path.rstrip("/") or "/"
    try:
        return _route(method, path, req)
    except RegistryError as exc:
        return _error(400, str(exc))
    except DispatchError as exc:
        return _error(400, str(exc))
    except ValueError as exc:
        return _error(400, str(exc))
    except FileNotFoundError as exc:
        return _error(404, str(exc))
    except Exception as exc:  # I6: never crash the server on a bad panel
        return _error(500, f"controller error: {exc}")


def _route(method: str, path: str, req: Request) -> Response:
    if path == "/api/v1/health" and method == "GET":
        return _json(200, {
            "ok": True,
            "service": "unity-hpc-controller",
            "projects": len(registry.list_projects()),
        })

    if path == "/api/v1/cluster" and method == "GET":
        return _json(200, snapshot.cluster())

    if path == "/api/v1/cluster/queue" and method == "GET":
        live = snapshot.live_snapshot()
        return _json(200, {
            "partitions": snapshot.partitions(),
            "live": live,
        })

    if path == "/api/v1/cluster/usage" and method == "GET":
        try:
            hours = int(_q(req, "hours", "24") or "24")
        except ValueError:
            hours = 24
        return _json(200, {
            "usage": snapshot.usage(hours),
            "outcomes": snapshot.outcomes(),
        })

    if path == "/api/v1/jobs" and method == "GET":
        return _json(200, {"jobs": snapshot.all_jobs()})

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
        rec = registry.attach(
            slug=slug,
            path=body["path"],
            primitive=body.get("primitive") or "cpu",
            remote_dir=body.get("remote_dir") or "",
            unity_host=body.get("unity_host") or "unity",
            campaign=body.get("campaign") or "",
            overrides=body.get("overrides") or {},
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
                "campaign", "overrides",
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
        result = dispatch.status(slug)
        return _json(200 if result["ok"] else 502, result)

    return _error(404, f"no route {method} /api/v1/projects/{slug}/{rest}")


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
    try:
        (unity / "controller.json").write_text(json.dumps(stub, indent=2) + "\n")
    except OSError:
        return


_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".json": "application/json",
}


def _static(path: str) -> Response:
    rel = "index.html" if path == "/" else path.lstrip("/")
    target = (UI_DIR / rel).resolve()
    try:
        target.relative_to(UI_DIR.resolve())
    except ValueError:
        return _error(404, "not found")
    if not target.is_file():
        return Response(status=404, body=b"not found", content_type="text/plain")
    ctype = _STATIC_TYPES.get(target.suffix, "application/octet-stream")
    return Response(status=200, body=target.read_bytes(), content_type=ctype)


def parse_raw(method: str, url: str, body: bytes = b"") -> Request:
    parsed = urlparse(url)
    return Request(
        method=method,
        path=parsed.path,
        query=parse_qs(parsed.query),
        body=body,
    )
