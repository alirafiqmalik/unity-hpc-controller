#!/usr/bin/env python3
"""
Unity HPC MCP server. Stdio transport.

Every tool is an HTTP client of the headless controller. The controller owns
SSH, the campaign journal, source bundles, scheduling, retries, and result
retrieval. This server never opens a cluster connection and never reads a
project directory.

`UNITY_CONTROLLER` names the controller base URL (default http://127.0.0.1:8300).
The plugin's .mcp.json registers this server; no manual configuration is needed.
The only third-party dependency is `mcp`.

Tools are invoked as mcp__unity-hpc__<tool_name> in skills.
"""

import asyncio
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

server = Server("unity-hpc")

#: Recorded at import. A plugin upgrade rewrites this file but cannot restart
#: the server, so unity_doctor compares the file's mtime with this stamp.
_SOURCE = Path(__file__).resolve()
_LOADED_AT = time.time()


def _plugin_version() -> str | None:
    manifest = _SOURCE.parent.parent / ".claude-plugin" / "plugin.json"
    try:
        return json.loads(manifest.read_text()).get("version")
    except (OSError, ValueError):
        return None


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    identity = {"campaign_id": {"type": "string", "description": "Campaign identity from the accepted declaration."}}
    return [
        types.Tool(name="unity_campaign_plan",
                   description="Check an immutable experiment bundle and compatible hardware placement through the controller. Read-only; submits nothing.",
                   inputSchema={"type": "object", "properties": {"specification_path": {"type": "string", "description": "Absolute path to runner-produced campaign JSON."}}, "required": ["specification_path"]}),
        types.Tool(name="unity_campaign_submit",
                   description="Accept a campaign JSON bundle into the controller journal. The service stages, schedules, reconciles, retries within budget, and retrieves declared results.",
                   inputSchema={"type": "object", "properties": {"specification_path": {"type": "string", "description": "Absolute path to runner-produced campaign JSON; campaign_id is the idempotency identity."}}, "required": ["specification_path"]}),
        types.Tool(name="unity_campaign_status",
                   description="Read one campaign's tasks, attempts, errors and completion status, or list campaigns when campaign_id is omitted.",
                   inputSchema={"type": "object", "properties": identity}),
        types.Tool(name="unity_campaign_results",
                   description="Read a bounded page of durable result and state events. Save next_cursor and pass it as after on the next read.",
                   inputSchema={"type": "object", "properties": {**identity, "after": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 1000}}, "required": ["campaign_id"]}),
        types.Tool(name="unity_campaign_cancel",
                   description="Request cancellation of only the named controller campaign and its recorded jobs.",
                   inputSchema={"type": "object", "properties": identity, "required": ["campaign_id"]}),
        types.Tool(name="unity_backend",
                   description="Read controller backend settings and the catalog age (status), or refresh the bounded live Slurm hardware and policy catalog (probe).",
                   inputSchema={"type": "object", "properties": {"action": {"type": "string", "enum": ["status", "probe"]}}}),
        types.Tool(name="unity_accounting",
                   description="Read archived Slurm accounting rows: requested and allocated resources, nodes, timing, and step high-water marks. Allocation counts are not time-weighted utilization.",
                   inputSchema={"type": "object", "properties": {
                       "user": {"type": "string"}, "account": {"type": "string"}, "partition": {"type": "string"}, "gpu_type": {"type": "string"},
                       "since": {"type": "string", "description": "ISO-8601 UTC lower bound."}, "until": {"type": "string", "description": "ISO-8601 UTC upper bound."},
                       "limit": {"type": "integer", "minimum": 1, "maximum": 1000}, "offset": {"type": "integer", "minimum": 0}}}),
        types.Tool(name="unity_doctor",
                   description="Read controller health, backend mode, SSH key state, and whether this server process runs the plugin code on disk. Call this first when behaviour disagrees with the source.",
                   inputSchema={"type": "object", "properties": {}}),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    result = await _dispatch(name, arguments or {})
    return [types.TextContent(type="text", text=result)]


async def _dispatch(name: str, args: dict) -> str:
    if name == "unity_campaign_plan":
        return await asyncio.to_thread(_campaign_from_file, args["specification_path"], "/api/v1/campaigns/plan")
    if name == "unity_campaign_submit":
        return await asyncio.to_thread(_campaign_from_file, args["specification_path"], "/api/v1/campaigns")
    if name == "unity_campaign_status":
        route = "/api/v1/campaigns"
        if args.get("campaign_id"):
            route += "/" + urllib.parse.quote(str(args["campaign_id"]), safe="")
        return await asyncio.to_thread(_controller_request, "GET", route)
    if name == "unity_campaign_results":
        identity = urllib.parse.quote(str(args["campaign_id"]), safe="")
        after, limit = int(args.get("after", 0)), int(args.get("limit", 100))
        if after < 0 or not 1 <= limit <= 1000:
            return json.dumps({"ok": False, "error": "after must be nonnegative; limit must be 1 to 1000"})
        route = f"/api/v1/campaigns/{identity}/results?" + urllib.parse.urlencode({"after": after, "limit": limit})
        return await asyncio.to_thread(_controller_request, "GET", route)
    if name == "unity_campaign_cancel":
        identity = urllib.parse.quote(str(args["campaign_id"]), safe="")
        return await asyncio.to_thread(_controller_request, "POST", f"/api/v1/campaigns/{identity}/cancel", {})
    if name == "unity_backend":
        action = args.get("action", "status")
        if action not in ("status", "probe"):
            return json.dumps({"ok": False, "error": "action must be status or probe"})
        if action == "probe":
            return await asyncio.to_thread(_controller_request, "POST", "/api/v1/backend/probe", {})
        return await asyncio.to_thread(_controller_request, "GET", "/api/v1/backend")
    if name == "unity_accounting":
        keys = ("user", "account", "partition", "gpu_type", "since", "until", "limit", "offset")
        query = {key: str(args[key]) for key in keys if args.get(key) not in (None, "")}
        route = "/api/v1/telemetry/accounting" + ("?" + urllib.parse.urlencode(query) if query else "")
        return await asyncio.to_thread(_controller_request, "GET", route)
    if name == "unity_doctor":
        return await asyncio.to_thread(_doctor)
    return json.dumps({"ok": False, "error": f"Unknown tool: {name}"})


def _controller_base() -> str | None:
    base = os.environ.get("UNITY_CONTROLLER", "http://127.0.0.1:8300").rstrip("/")
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return None
    return base


def _controller_request(method: str, route: str, payload=None) -> str:
    """Campaign operations cross HTTP; this plugin never becomes a submitter."""
    base = _controller_base()
    if base is None:
        return json.dumps({"ok": False, "error": "UNITY_CONTROLLER must be an HTTP(S) controller URL"})
    request = urllib.request.Request(base + route, method=method,
                                    data=json.dumps(payload).encode() if payload is not None else None,
                                    headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read(16 * 1024 * 1024).decode()
    except urllib.error.HTTPError as exc:
        return exc.read(65536).decode(errors="replace")
    except (OSError, ValueError) as exc:
        return json.dumps({"ok": False, "error": f"controller request failed: {exc}"})


def _campaign_from_file(value: str, route: str) -> str:
    try:
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError("specification_path must be absolute")
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("campaign JSON exceeds 16 MiB")
        specification = json.loads(path.read_text())
        if not isinstance(specification, dict):
            raise ValueError("campaign JSON must be an object")
    except (OSError, ValueError, TypeError) as exc:
        return json.dumps({"ok": False, "error": f"cannot read campaign JSON: {exc}"})
    return _controller_request("POST", route, specification)


def _doctor() -> str:
    """Controller health plus the one local fact only this process knows:
    whether its loaded code is older than the plugin source on disk."""
    raw = _controller_request("GET", "/api/v1/health")
    try:
        health = json.loads(raw)
    except ValueError:
        health = {"ok": False, "error": raw[:500]}
    try:
        code_stale = _SOURCE.stat().st_mtime > _LOADED_AT
    except OSError:
        code_stale = False
    report = {
        "ok": bool(health.get("ok")),
        "controller": health,
        "controller_url": _controller_base(),
        "plugin": {"version": _plugin_version(), "source": str(_SOURCE), "code_stale": code_stale},
    }
    if code_stale:
        report["fix"] = "The server source changed after this process started. Run /reload-plugins, or restart the session."
    elif not health.get("ok"):
        report["fix"] = "Start the controller with scripts/hpc-controller --no-tailscale, then call unity_doctor again."
    return json.dumps(report, indent=2)


async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
