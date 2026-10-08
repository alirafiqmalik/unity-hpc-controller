"""HTTP seam for the controller. Tests call handle(); serve.py wraps sockets."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

from controller import events, snapshot, telemetry, campaigns, campaign_store
from controller.campaign_contract import CampaignError

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8300


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
    except CampaignError as exc:
        return _error(exc.status, str(exc))
    except ValueError as exc:
        return _json(400, {"ok": False, "error": str(exc), "errors": getattr(exc, "errors", [])})
    except FileNotFoundError as exc:
        return _error(404, str(exc))
    except Exception as exc:  # never crash the server on one bad request
        return _error(500, f"controller error: {exc}")


_RETIRED_PREFIXES = ("/api/v1/projects", "/api/v1/jobs/delete")


def _route(method: str, path: str, req: Request) -> Response:
    if path == "/api/v1/backend" and method == "GET":
        return _json(200, {"settings": campaigns.settings(), "catalog": campaigns.planner.catalog()})
    if path == "/api/v1/backend" and method == "PATCH":
        return _json(200, {"settings": campaigns.configure(_read_json(req))})
    if path == "/api/v1/backend/probe" and method == "POST":
        return _json(200, {"catalog": campaigns.probe()})
    if path == "/api/v1/campaigns/plan" and method == "POST":
        return _json(200, campaigns.plan(_read_json(req)))
    if path == "/api/v1/campaigns" and method == "GET":
        return _json(200, {"campaigns": campaign_store.listing()})
    if path == "/api/v1/campaigns" and method == "POST":
        value = campaigns.create(_read_json(req))
        return _json(200 if value["idempotent"] else 202, {"campaign": value})
    if path.startswith("/api/v1/campaigns/"):
        identity, _, rest = path.removeprefix("/api/v1/campaigns/").partition("/")
        if not rest and method == "GET":
            return _json(200, {"campaign": campaign_store.read(identity)})
        if rest == "results" and method == "GET":
            return _json(200, campaign_store.results(identity, int(_q(req, "after", "0")), int(_q(req, "limit", "100"))))
        if rest == "artifacts" and method == "GET":
            artifact = campaigns.artifact(identity, _q(req, "task_id"), _q(req, "path"))
            return Response(200, artifact.read_bytes(), "application/octet-stream")
        if rest == "cancel" and method == "POST":
            return _json(202, {"campaign": campaigns.cancel(identity)})
        return _error(404, "unknown campaign route")
    if path == "/api/v1/telemetry/accounting" and method == "GET":
        from lib.queries import historical_accounting
        rows = historical_accounting(user=_q(req, "user"), account=_q(req, "account"), partition=_q(req, "partition"), gpu_type=_q(req, "gpu_type"),
                                     since=_q(req, "since"), until=_q(req, "until"), limit=int(_q(req, "limit", "100")), offset=int(_q(req, "offset", "0")))
        return _json(200, {"accounting": rows})
    if path.startswith(_RETIRED_PREFIXES):
        return _error(410, "Project registration is retired. Submit a portable campaign to /api/v1/campaigns.")
    if path == "/api/v1/health" and method == "GET":
        ssh = telemetry.ssh_status()
        return _json(200, {
            "ok": True,
            "service": "unity-hpc-controller",
            "mode": "backend",
            "campaign_schema_version": 1,
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
        # decision to start. Clients poll /api/v1/telemetry for the outcome.
        return _json(202 if result.get("started") else 200, result)

    if path == "/api/v1/telemetry/settings" and method == "PATCH":
        body = _read_json(req)
        keys = ("source", "schedule_enabled", "interval_minutes", "script_mode",
                "ssh_host", "ssh_identity", "session_name")
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
        jobs = [{**task, "campaign_id": campaign["id"]}
                for campaign in campaign_store.listing()
                for task in campaign_store.read(campaign["id"])["tasks"]
                if task.get("job_id")]
        return _json(200, {"jobs": jobs})

    if path == "/api/v1/events" and method == "GET":
        try:
            limit = int(_q(req, "limit", "50") or "50")
        except ValueError:
            limit = 50
        return _json(200, {"events": events.recent(limit)})

    if path.startswith("/api/"):
        return _error(404, f"no route {method} {path}")

    if method == "GET" and path == "/":
        return _json(200, {"service": "unity-hpc-controller", "mode": "backend",
                           "campaigns": "/api/v1/campaigns", "settings": "/api/v1/backend",
                           "telemetry": "/api/v1/telemetry", "health": "/api/v1/health"})

    return _error(404, f"no route {method} {path}")


def parse_raw(method: str, url: str, body: bytes = b"") -> Request:
    parsed = urlparse(url)
    return Request(
        method=method,
        path=parsed.path,
        query=parse_qs(parsed.query),
        body=body,
    )
