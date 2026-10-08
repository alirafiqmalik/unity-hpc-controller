"""HTTP-only command line client for the portable campaign interface."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def request(base, route, method="GET", payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base.rstrip("/") + route, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.loads(response.read())


def main(argv=None):
    parser = argparse.ArgumentParser(description="Portable HPC campaigns through the controller HTTP interface")
    parser.add_argument("--url", default=os.environ.get("UNITY_CONTROLLER", os.environ.get("UNITY_CONTROLLER_URL", "http://127.0.0.1:8300")))
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("configure", "plan", "submit"):
        sub.add_parser(name).add_argument("file", type=Path, help="JSON declaration file")
    sub.add_parser("probe")
    sub.add_parser("list")
    for name in ("status", "queue", "cancel", "watch", "results"):
        command = sub.add_parser(name)
        command.add_argument("campaign_id")
        if name in ("watch", "results"):
            command.add_argument("--after", type=int, default=0)
        if name == "watch":
            command.add_argument("--interval", type=int, default=30)
    args = parser.parse_args(argv)
    routes = {"configure": ("/api/v1/backend", "PATCH"), "probe": ("/api/v1/backend/probe", "POST"), "plan": ("/api/v1/campaigns/plan", "POST"), "submit": ("/api/v1/campaigns", "POST"), "list": ("/api/v1/campaigns", "GET")}
    try:
        if args.command in routes:
            route, method = routes[args.command]
            payload = json.loads(args.file.read_text()) if hasattr(args, "file") else None
            result = request(args.url, route, method, payload)
        else:
            base = "/api/v1/campaigns/" + urllib.parse.quote(args.campaign_id, safe="")
            if args.command == "watch":
                cursor = args.after
                while True:
                    events = request(args.url, base + "/results?after=" + str(cursor))
                    for event in events["events"]:
                        print(json.dumps(event, sort_keys=True), flush=True)
                    cursor = events["next_cursor"]
                    campaign = request(args.url, base)["campaign"]
                    if campaign["state"] in ("completed", "failed", "cancelled"):
                        return 0 if campaign["state"] == "completed" else 1
                    time.sleep(max(15, args.interval))
            route = base + ("/cancel" if args.command == "cancel" else "/results?after=" + str(args.after) if args.command == "results" else "")
            result = request(args.url, route, "POST" if args.command == "cancel" else "GET")
            if args.command == "queue":
                from collections import Counter
                campaign = result["campaign"]
                result = {"campaign_id": campaign["id"], "state": campaign["state"], "error": campaign.get("error"),
                          "task_counts": dict(Counter(t["state"] for t in campaign["tasks"])),
                          "jobs": [{"task_id": t["task_id"], "job_id": t["job_id"], "state": (t.get("observation") or {}).get("state", t["state"]),
                                    "pending_reason": (t.get("observation") or {}).get("pending_reason"), "node_list": (t.get("observation") or {}).get("node_list"),
                                    "estimated_start": (t.get("observation") or {}).get("estimated_start"), "observed_at": (t.get("observation") or {}).get("observed_at")}
                                   for t in campaign["tasks"] if t.get("job_id") and t["state"] not in ("completed", "failed", "rejected", "cancelled", "blocked")],
                          "estimate_note": "Slurm start hints can change. Missing estimates remain unknown. This command reads cached controller observations."}
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except urllib.error.HTTPError as exc:
        print(exc.read().decode(), file=sys.stderr)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        print(str(exc), file=sys.stderr)
    except KeyboardInterrupt:
        return 130
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
