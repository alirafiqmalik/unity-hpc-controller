#!/usr/bin/env python3
"""Check one campaign JSON round trip through the controller HTTP routes.

Standard library only. It imports nothing from this repository, so one copy
can check a controller at any revision.

    declare  Write a verification declaration from a template, with an absolute
             bundle path and a fresh campaign ID that starts with a prefix.
    run      Drive the routes that a runner uses against one controller: plan,
             listing, submit, resend, status, paged results, artifact downloads,
             and a resend after completion. Record every HTTP exchange and a
             summary.json in the output directory.
    sacct    Query Slurm accounting over SSH for the recorded job name. Require
             one allocation ID that agrees with the journal. Write sacct.json.
    compare  Compare two recorded round trips. Run-specific values are replaced
             at known fields only; every other recorded field must be equal.

Recorded files never hold the backend account, SSH identity, remote root, or
mail recipient: `run` replaces them, and each --redact value, before it writes.

Exit status: 0 when the round trip passes or the two runs match; 1 when a check
fails or the runs differ (the first differing field path comes first); 2 when
the run could not finish (deadline, controller unreachable, refused request).

Example, from the repository root, with a controller on port 8411:

    python3 tests/verify_campaign_round_trip.py declare \\
        --template examples/cpu-result/campaign.json --bundle /abs/bundle \\
        --prefix rtb- --out /abs/declarations/baseline.json
    python3 tests/verify_campaign_round_trip.py run --url http://127.0.0.1:8411 \\
        --declaration /abs/declarations/baseline.json --out /abs/evidence/baseline
    python3 tests/verify_campaign_round_trip.py sacct --ssh-host unity /abs/evidence/baseline
    python3 tests/verify_campaign_round_trip.py compare /abs/evidence/baseline /abs/evidence/head
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

FORMAT = 1
DEFAULT_RESULT = '{"count": 5, "sum": 28}\n'
CAMPAIGN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$")
CAMPAIGN_TERMINAL = ("completed", "failed", "cancelled")
# Result events that every successful one-task round trip publishes, in this order.
# Task-level accepted or running events that carry a scheduler observation are
# optional: whether a poll sees the job pending or running depends on timing.
MILESTONES = ("campaign:accepted", "campaign:running", "campaign:source_staged", "task:submitting", "task:accepted",
              "task:fetching", "task:diagnostics_available", "task:completed", "campaign:completed")
REQUIRED_LABELS = ("health", "backend", "plan", "listing-after-plan", "submit", "resend", "results", "status-final",
                   "results-after-final", "artifact-declared", "artifact-diagnostic", "artifact-undeclared",
                   "resend-after-completion")
UNCOMPARED_LABELS = ("health", "backend", "probe")


class Blocked(Exception):
    """The round trip cannot go on: deadline, unreachable controller, or a refused step."""


def now():
    return datetime.now(timezone.utc).isoformat()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def request_hash(spec):
    """The request hash of controller/campaigns.py create: contract.digest over
    {"spec", "source_sha256"}. The accepted spec gains bundle_manifest and
    backend after the hash is taken, so they are left out here."""
    hashed = {key: value for key, value in spec.items() if key not in ("bundle_manifest", "backend")}
    value = {"spec": hashed, "source_sha256": spec["bundle_manifest"]["sha256"]}
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def job_name(campaign_id, task_id, attempt):
    """The unique Slurm job name of one attempt (controller/campaigns.py _intent)."""
    digest = sha256(f"{campaign_id}/{task_id}/{attempt}".encode())[:20]
    return f"{campaign_id[:64]}-{task_id[:10]}-{digest}"


def classify(event):
    """'observation' for an optional scheduler observation, else '<level>:<kind>'."""
    level = "task" if event.get("task_id") else "campaign"
    payload = event.get("payload") or {}
    if level == "task" and event.get("kind") in ("accepted", "running") and "observation" in payload:
        return "observation"
    return f"{level}:{event.get('kind')}"


def _query(route):
    return {key: values[0] for key, values in urllib.parse.parse_qs(urllib.parse.urlsplit(route).query).items()}


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


class Redactor:
    """Replace each secret value, longest first, in every string and key."""

    def __init__(self):
        self.secrets = []

    def add(self, value, name):
        if not isinstance(value, str):
            return
        for text in dict.fromkeys((value.strip(), value.strip().rstrip("/"), os.path.expanduser(value.strip()))):
            if len(text) >= 3 and text not in (known for known, _ in self.secrets):
                self.secrets.append((text, f"<redacted:{name}>"))
        self.secrets.sort(key=lambda item: -len(item[0]))

    def __call__(self, value):
        if isinstance(value, str):
            for secret, placeholder in self.secrets:
                value = value.replace(secret, placeholder)
            return value
        if isinstance(value, list):
            return [self(item) for item in value]
        if isinstance(value, dict):
            return {self(key): self(item) for key, item in value.items()}
        return value


class Recorder:
    """Send one HTTP request and write the exchange, redacted, as exchanges/NNNN-label.json."""

    def __init__(self, url, out, timeout, redact):
        self.url = url.rstrip("/")
        self.out = Path(out)
        self.timeout = timeout
        self.redact = redact
        self.index = []
        self.bodies = []  # unredacted JSON responses, for checks across responses

    def call(self, label, method, route, payload=None, learn=None):
        seq = len(self.index) + 1
        data = None if payload is None else json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"} if data is not None else {}
        request = urllib.request.Request(self.url + route, data=data, method=method, headers=headers)
        record = {"seq": seq, "label": label, "method": method, "path": route, "at": now()}
        if payload is not None:
            record["request"] = payload
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status, kind, raw = response.status, response.headers.get("Content-Type", ""), response.read()
        except urllib.error.HTTPError as exc:
            status, kind, raw = exc.code, exc.headers.get("Content-Type", ""), exc.read()
        except OSError as exc:
            record.update(status=None, error=str(exc), elapsed_seconds=round(time.monotonic() - started, 3))
            self._save(record)
            raise Blocked(f"{method} {route}: {exc}") from exc
        record.update(status=status, elapsed_seconds=round(time.monotonic() - started, 3))
        body = raw
        if kind.startswith("application/json"):
            try:
                body = json.loads(raw)
                record["response"] = body
            except ValueError:
                record["response_text"] = raw.decode("utf-8", "replace")
        else:
            described = {"size": len(raw), "sha256": sha256(raw), "content_type": kind}
            try:
                described["text"] = raw.decode("utf-8")
            except UnicodeDecodeError:
                described["base64"] = base64.b64encode(raw).decode()
            record["response_bytes"] = described
        if learn is not None and isinstance(body, dict):
            learn(body)
        if isinstance(body, (dict, list)) and label not in UNCOMPARED_LABELS:
            self.bodies.append(body)
        self._save(record)
        return status, body

    def _save(self, record):
        name = f"{record['seq']:04d}-{record['label']}.json"
        _write_json(self.out / "exchanges" / name, self.redact(record))
        self.index.append({"seq": record["seq"], "label": record["label"], "status": record.get("status"), "file": "exchanges/" + name})


class Checks:
    def __init__(self):
        self.items = []

    def check(self, name, ok, detail=None):
        self.items.append({"name": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    @property
    def failed(self):
        return [item["name"] for item in self.items if not item["ok"]]


class Pager:
    """Page through /results with limit=1, resuming from each next_cursor."""

    def __init__(self, recorder, base):
        self.recorder, self.base = recorder, base
        self.cursor = 0
        self.events, self.problems, self.seen = [], [], set()

    def drain(self):
        while True:
            after = self.cursor
            status, page = self.recorder.call("results", "GET", f"{self.base}/results?after={after}&limit=1")
            if status != 200 or not isinstance(page, dict):
                raise Blocked(f"results after {after} answered HTTP {status}")
            events = page.get("events") or []
            if len(events) > 1:
                self.problems.append(f"limit=1 returned {len(events)} events after {after}")
            if not events:
                if page.get("next_cursor") != after:
                    self.problems.append(f"an empty page after {after} returned next_cursor {page.get('next_cursor')}")
                return
            for event in events:
                cursor = event.get("cursor")
                if not isinstance(cursor, int) or cursor <= self.cursor or cursor in self.seen:
                    self.problems.append(f"event cursor {cursor} after {self.cursor} does not increase or repeats")
                    raise Blocked("result cursor did not advance")
                self.seen.add(cursor)
                self.events.append(event)
                self.cursor = cursor
            if page.get("next_cursor") != self.cursor:
                self.problems.append(f"next_cursor {page.get('next_cursor')} differs from the last event cursor {self.cursor}")
            if len(self.events) > 10000:
                raise Blocked("more than 10000 result events")


def _field_values(value, key):
    """Every value stored under `key` anywhere in a JSON value."""
    found = []
    if isinstance(value, dict):
        for name, item in value.items():
            if name == key and not isinstance(item, (dict, list)):
                found.append(item)
            else:
                found.extend(_field_values(item, key))
    elif isinstance(value, list):
        for item in value:
            found.extend(_field_values(item, key))
    return found


def _subsequence(sequence, pattern):
    items = iter(sequence)
    return all(any(item == wanted for item in items) for wanted in pattern)


def _stale(plan):
    warnings = [w for task in plan.get("tasks") or [] for w in (task.get("placement") or {}).get("warnings") or []]
    return any("stale" in warning or "absent" in warning for warning in warnings)


def _round_trip(recorder, checks, declaration, args, summary):
    identity = declaration["campaign_id"]
    base = "/api/v1/campaigns/" + urllib.parse.quote(identity, safe="")

    def learn(body):
        settings = body.get("settings") or {}
        for key in ("account", "ssh_identity", "remote_root", "mail_user"):
            recorder.redact.add(settings.get(key), key)

    status, _ = recorder.call("backend", "GET", "/api/v1/backend", learn=learn)
    if status != 200:
        raise Blocked(f"GET /api/v1/backend answered HTTP {status}")
    status, health = recorder.call("health", "GET", "/api/v1/health")
    checks.check("health", status == 200 and isinstance(health, dict) and health.get("ok") is True, status)

    # 1. Plan, then confirm that planning accepted nothing.
    status, plan = recorder.call("plan", "POST", "/api/v1/campaigns/plan", declaration)
    if status == 200 and isinstance(plan, dict) and not plan.get("ready") and args.probe and _stale(plan):
        status, _ = recorder.call("probe", "POST", "/api/v1/backend/probe", learn=learn)
        checks.check("catalog probe", status == 200, status)
        recorder.call("backend", "GET", "/api/v1/backend", learn=learn)
        status, plan = recorder.call("plan", "POST", "/api/v1/campaigns/plan", declaration)
    if status != 200 or not isinstance(plan, dict):
        raise Blocked(f"plan answered HTTP {status}: {plan if isinstance(plan, dict) else ''}")
    tasks = plan.get("tasks") or []
    summary["plan"] = {"bundle_sha256": (plan.get("bundle") or {}).get("sha256"),
                       "bundle_files": [f.get("path") for f in (plan.get("bundle") or {}).get("files") or []],
                       "tasks": [{"task_id": t.get("task_id"), "resources": t.get("resources"),
                                  "selected_partitions": (t.get("placement") or {}).get("selected_partitions")} for t in tasks]}
    checks.check("plan names the declared campaign", plan.get("campaign_id") == identity, plan.get("campaign_id"))
    cpu = bool(tasks) and all((t.get("resources") or {}).get("gpu_count") == 0 and (t.get("placement") or {}).get("selected_partitions")
                              and not (t.get("placement") or {}).get("warnings") for t in tasks)
    checks.check("plan places every task on a CPU partition", cpu, [(t.get("placement") or {}).get("warnings") for t in tasks])
    if not checks.check("plan is ready", plan.get("ready") is True, plan.get("ready")):
        raise Blocked("the plan is not ready: " + json.dumps([(t.get("placement") or {}).get("warnings") for t in tasks]))
    status, listing = recorder.call("listing-after-plan", "GET", "/api/v1/campaigns")
    checks.check("planning leaves the campaign listing empty", status == 200 and isinstance(listing, dict) and listing.get("campaigns") == [],
                 [c.get("id") for c in (listing or {}).get("campaigns") or []] if isinstance(listing, dict) else status)

    # 2. Submit, then resend the same JSON.
    status, body = recorder.call("submit", "POST", "/api/v1/campaigns", declaration)
    campaign = body.get("campaign") if isinstance(body, dict) else None
    checks.check("submit answers 202", status == 202, status)
    if not isinstance(campaign, dict):
        raise Blocked(f"submit answered HTTP {status}: {body.get('error') if isinstance(body, dict) else ''}")
    checks.check("submit is not idempotent", campaign.get("idempotent") is False, campaign.get("idempotent"))
    checks.check("submit keeps the declared campaign ID", campaign.get("id") == identity, campaign.get("id"))
    digest = campaign.get("request_hash")
    try:
        computed = request_hash(campaign["spec"])
    except (KeyError, TypeError):
        computed = None
    summary["request_hash"] = {"recorded": digest, "computed": computed, "match": computed == digest}
    checks.check("request hash follows the create formula", computed == digest, summary["request_hash"])
    status, body = recorder.call("resend", "POST", "/api/v1/campaigns", declaration)
    again = (body.get("campaign") if isinstance(body, dict) else None) or {}
    checks.check("resend answers 200", status == 200, status)
    checks.check("resend is idempotent", again.get("idempotent") is True, again.get("idempotent"))
    checks.check("resend keeps the campaign ID and request hash", again.get("id") == identity and again.get("request_hash") == digest,
                 {"id": again.get("id"), "request_hash": again.get("request_hash")})

    # 3. Poll the campaign and page through its results until it ends.
    pager = Pager(recorder, base)
    deadline = time.monotonic() + args.deadline_seconds
    while True:
        status, body = recorder.call("status", "GET", base)
        current = (body.get("campaign") if isinstance(body, dict) else None) or {}
        if status != 200 or not current:
            raise Blocked(f"campaign status answered HTTP {status}")
        pager.drain()
        if current.get("state") in CAMPAIGN_TERMINAL:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            summary["last_state"] = {"campaign": current.get("state"), "error": current.get("error"),
                                     "tasks": {t.get("task_id"): t.get("state") for t in current.get("tasks") or []}}
            raise Blocked(f"deadline of {args.deadline_seconds:g} s passed: {json.dumps(summary['last_state'])}")
        time.sleep(min(args.poll_seconds, remaining))
    status, body = recorder.call("status-final", "GET", base)
    final = (body.get("campaign") if isinstance(body, dict) else None) or {}
    pager.drain()
    status, page = recorder.call("results-after-final", "GET", f"{base}/results?after={pager.cursor}&limit=1")
    checks.check("reading after the final cursor returns no events and the same cursor",
                 status == 200 and isinstance(page, dict) and page.get("events") == [] and page.get("next_cursor") == pager.cursor,
                 page if isinstance(page, dict) else status)
    checks.check("results paging resumes from next_cursor, cursors increase, and each event arrives once", not pager.problems, pager.problems)
    events = pager.events
    summary["events"] = events
    summary["final_cursor"] = pager.cursor

    records = final.get("tasks") or []
    attempts = final.get("attempts") or []
    checks.check("campaign completed", final.get("state") == "completed", {"state": final.get("state"), "error": final.get("error")})
    checks.check("every task completed", bool(records) and all(t.get("state") == "completed" for t in records),
                 {t.get("task_id"): [t.get("state"), t.get("error")] for t in records})
    checks.check("exactly one attempt per task", len(attempts) == len(records) and all(t.get("attempt") == 1 for t in records),
                 [(a.get("task_id"), a.get("attempt")) for a in attempts])
    job_ids = sorted({str(v) for body in recorder.bodies for v in _field_values(body, "job_id") if v is not None})
    checks.check("one Slurm job ID per attempt across every response",
                 len(job_ids) == len(attempts) and all(x.isdigit() for x in job_ids)
                 and sorted(str(a.get("job_id")) for a in attempts) == job_ids, job_ids)
    names = [a.get("job_name") for a in attempts]
    checks.check("job names follow the attempt name formula",
                 all(a.get("job_name") == job_name(identity, a.get("task_id", ""), a.get("attempt")) for a in attempts), names)
    observations = [t.get("observation") or {} for t in records]
    checks.check("terminal Slurm observation with a successful exit",
                 bool(observations) and all(o.get("state") == "COMPLETED" and o.get("exit_code") == "0:0" for o in observations),
                 [(o.get("state"), o.get("exit_code")) for o in observations])
    checks.check("result_cursor is the last event cursor", final.get("result_cursor") == pager.cursor,
                 {"result_cursor": final.get("result_cursor"), "last": pager.cursor})

    # 4. Milestone order and the source cache.
    classes = [classify(e) for e in events]
    milestones = [c for c in classes if c != "observation"]
    summary["milestones"] = milestones
    summary["optional_observations"] = [f"{e.get('kind')}:{((e.get('payload') or {}).get('observation') or {}).get('state')}"
                                        for e in events if classify(e) == "observation"]
    counts_ok = all(milestones.count(m) == (1 if m.startswith("campaign:") else len(records)) for m in MILESTONES)
    checks.check("milestone events arrive once each and in order", counts_ok and _subsequence(milestones, MILESTONES), milestones)
    staged = next((e.get("payload") or {} for e in events if classify(e) == "campaign:source_staged"), {})
    checks.check("the source cache was cold", staged.get("cache_hit") is False, staged.get("cache_hit"))

    # 5. Downloads: the declared artifact, the attestation through its diagnostic receipt, and an undeclared path.
    for task in records:
        task_id = task.get("task_id")
        artifacts = task.get("artifacts") or {}
        for receipt in artifacts.get("files") or []:
            status, raw = recorder.call("artifact-declared", "GET", receipt["download_url"])
            raw = raw if isinstance(raw, bytes) else b""
            checks.check(f"declared artifact {task_id}/{receipt.get('path')} matches its receipt",
                         status == 200 and len(raw) == receipt.get("size_bytes") and sha256(raw) == receipt.get("sha256"),
                         {"status": status, "size": len(raw), "sha256": sha256(raw)})
            if receipt.get("path") == args.result_path and args.expected_result is not None:
                checks.check(f"declared artifact {task_id}/{receipt.get('path')} holds the expected bytes",
                             raw == args.expected_result.encode(), raw[:200].decode("utf-8", "replace"))
        evidence = f".controller/hardware-{task.get('attempt')}.json"
        receipt = next((r for r in artifacts.get("controller_files") or [] if r.get("path") == evidence), None)
        if checks.check(f"diagnostic receipt for {task_id}/{evidence}", receipt is not None, [r.get("path") for r in artifacts.get("controller_files") or []]):
            status, raw = recorder.call("artifact-diagnostic", "GET", receipt["download_url"])
            raw = raw if isinstance(raw, bytes) else b""
            checks.check(f"diagnostic {task_id}/{evidence} matches its receipt",
                         status == 200 and len(raw) == receipt.get("size_bytes") and sha256(raw) == receipt.get("sha256"),
                         {"status": status, "size": len(raw), "sha256": sha256(raw)})
            try:
                record = json.loads(raw)
            except ValueError:
                record = {}
            gpu_count = ((task.get("spec") or {}).get("resources") or {}).get("gpu_count")
            checks.check(f"attestation {task_id}/{evidence} names the task and attempt, is verified, and lists no GPU",
                         isinstance(record, dict) and record.get("task_id") == task_id and record.get("attempt") == task.get("attempt")
                         and record.get("verified") is True and (record.get("gpus") == [] or gpu_count),
                         {k: record.get(k) for k in ("task_id", "attempt", "verified", "gpus")} if isinstance(record, dict) else None)
        query = urllib.parse.urlencode({"task_id": task_id, "path": args.undeclared_path})
        status, _ = recorder.call("artifact-undeclared", "GET", f"{base}/artifacts?{query}")
        checks.check(f"undeclared path {task_id}/{args.undeclared_path} answers 404", status == 404, status)

    # 6. Resend after completion.
    status, body = recorder.call("resend-after-completion", "POST", "/api/v1/campaigns", declaration)
    again = (body.get("campaign") if isinstance(body, dict) else None) or {}
    checks.check("resend after completion answers 200 and is idempotent", status == 200 and again.get("idempotent") is True,
                 {"status": status, "idempotent": again.get("idempotent")})
    checks.check("resend after completion keeps the campaign ID and request hash",
                 again.get("id") == identity and again.get("request_hash") == digest)
    checks.check("resend after completion keeps the attempts", again.get("attempts") == attempts)
    checks.check("resend after completion keeps the result cursor", again.get("result_cursor") == final.get("result_cursor"),
                 again.get("result_cursor"))
    checks.check("resend after completion keeps the artifacts",
                 [t.get("artifacts") for t in again.get("tasks") or []] == [t.get("artifacts") for t in records])
    summary.update(state=final.get("state"), created_at=final.get("created_at"), job_ids=job_ids, job_names=names,
                   artifacts={t.get("task_id"): t.get("artifacts") for t in records})


def run(args):
    declaration = json.loads(Path(args.declaration).read_text())
    identity = declaration.get("campaign_id") if isinstance(declaration, dict) else None
    if not isinstance(identity, str) or not CAMPAIGN_ID.fullmatch(identity):
        print("the declaration needs a valid campaign_id", file=sys.stderr)
        return 2
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        print(f"{out} is not empty; give each round trip a new directory", file=sys.stderr)
        return 2
    redact = Redactor()
    for value in args.redact or ():
        redact.add(value, "extra")
    if args.redact_file:
        for line in Path(args.redact_file).read_text().splitlines():
            redact.add(line, "extra")
    recorder = Recorder(args.url, out, args.request_timeout, redact)
    checks = Checks()
    summary = {"format": FORMAT, "revision": args.revision, "url": args.url, "campaign_id": identity,
               "declaration": declaration, "started_at": now()}
    blocker = None
    try:
        _round_trip(recorder, checks, declaration, args, summary)
    except Blocked as exc:
        blocker = str(exc)
    except KeyboardInterrupt:
        blocker = "interrupted"
    summary.update(finished_at=now(), blocker=blocker, checks=checks.items, failed=checks.failed,
                   ok=blocker is None and not checks.failed, exchanges=recorder.index)
    _write_json(out / "summary.json", redact(summary))
    for item in checks.items:
        if not item["ok"]:
            print(f"FAILED {item['name']}: {json.dumps(redact(item['detail']), default=str)[:400]}")
    if blocker:
        print(f"BLOCKED {redact(blocker)}")
        return 2
    verdict = "passed" if summary["ok"] else "FAILED"
    print(f"round trip {verdict}: {identity}, job {','.join(summary.get('job_ids') or [])}, "
          f"{len(summary.get('events') or [])} events, {len(recorder.index)} exchanges, {len(checks.items)} checks -> {out}")
    return 0 if summary["ok"] else 1


def declare(args):
    template = json.loads(Path(args.template).read_text())
    bundle = Path(args.bundle).expanduser()
    out = Path(args.out).expanduser()
    if not bundle.is_absolute() or not bundle.is_dir():
        print("--bundle must name an existing absolute directory", file=sys.stderr)
        return 2
    if out.resolve().is_relative_to(bundle.resolve()):
        print("write the declaration outside the bundle so that the bundle digest stays fixed", file=sys.stderr)
        return 2
    if out.exists():
        print(f"{out} exists; each round trip needs a fresh declaration", file=sys.stderr)
        return 2
    identity = args.prefix + datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%Sz")
    if not CAMPAIGN_ID.fullmatch(identity):
        print(f"campaign ID {identity!r} is not valid", file=sys.stderr)
        return 2
    template["campaign_id"] = identity
    template.setdefault("bundle", {})["path"] = str(bundle)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(template, indent=2) + "\n")
    print(identity)
    return 0


def sacct(args):
    directory = Path(args.directory)
    summary = json.loads((directory / "summary.json").read_text())
    names, journal = summary.get("job_names") or [], sorted(summary.get("job_ids") or [])
    if not names or not summary.get("created_at"):
        print("summary.json has no job name or creation time; the round trip did not submit", file=sys.stderr)
        return 2
    created = datetime.fromisoformat(summary["created_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
    start = (created - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    remote = (f"export TZ=UTC LC_ALL=C; timeout {int(args.query_timeout)} sacct -n -P --name={shlex.quote(','.join(names))}"
              f" -S {start} -E now -o JobIDRaw,JobName%100,State,ExitCode")
    command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", args.ssh_host, remote]
    redact = Redactor()
    for value in args.redact or ():
        redact.add(value, "extra")
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=args.query_timeout + 40)
        returncode, stdout, stderr = result.returncode, result.stdout, result.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        returncode, stdout, stderr = None, "", str(exc)
    rows = [line.split("|") for line in stdout.splitlines() if line.strip()]
    allocations = sorted({row[0].split(".")[0] for row in rows if row and row[0]})
    allocation_rows = [row for row in rows if row and "." not in row[0]]
    record = {"at": now(), "ssh_host": args.ssh_host, "command": remote, "returncode": returncode, "rows": rows,
              "allocation_ids": allocations, "distinct_allocations": len(allocations), "journal_job_ids": journal,
              "job_names": names, "agrees_with_journal": allocations == journal,
              "allocation": [{"job_id": r[0], "job_name": r[1] if len(r) > 1 else None, "state": r[2] if len(r) > 2 else None,
                              "exit_code": r[3] if len(r) > 3 else None} for r in allocation_rows],
              "stderr": stderr[-1500:]}
    record["ok"] = (returncode == 0 and len(allocations) == len(names) == 1 and record["agrees_with_journal"]
                    and all(r.get("job_name") == names[0] for r in record["allocation"]))
    _write_json(directory / "sacct.json", redact(record))
    print(("sacct agrees" if record["ok"] else "sacct DISAGREES") + f": allocations {allocations}, journal {journal}, "
          f"states {[(r['state'], r['exit_code']) for r in record['allocation']]}")
    return 0 if record["ok"] else 1


# --- compare -----------------------------------------------------------------

TIMESTAMP_KEYS = frozenset({"created_at", "observed_at", "submit", "start", "end"})
MEASUREMENT_KEYS = frozenset({"elapsed_seconds", "freshness_seconds", "max_rss", "total_cpu", "tres_usage_in_max"})
HINT_KEYS = frozenset({"pending_reason", "estimated_start", "estimated_start_source"})
CURSOR_KEYS = frozenset({"cursor", "result_cursor", "next_cursor"})
NODE_KEYS = frozenset({"node", "node_list", "accounting_node_list"})
NO_NODE = frozenset({"", "None", "None assigned", "(null)"})
TOKEN_KEYS = {"id": "campaign_id", "campaign_id": "campaign_id", "request_hash": "request_hash",
              "job_name": "job_name", "job_id": "job_id", **{key: "node" for key in NODE_KEYS}}
TEXT_KEYS = frozenset({"local_path", "download_url", "path", "error", "cache_path", "source_path"})
DIAGNOSTIC_KEYS = frozenset({"sha256", "size_bytes"})
QUEUE_FIELDS = ("job_id", "job_name", "state", "source", "node_list", "fetch_attempts",
                "pending_reason", "estimated_start", "estimated_start_source")
TOKEN_KINDS = ("campaign_id", "request_hash", "job_name", "job_id", "node", "data_root")
MISSING = "<missing>"


class Run:
    """One recorded round trip, read back from its directory."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.summary = json.loads((self.directory / "summary.json").read_text())
        files = sorted((self.directory / "exchanges").glob("*.json"))
        self.exchanges = sorted((json.loads(path.read_text()) for path in files), key=lambda x: x["seq"])
        sacct_path = self.directory / "sacct.json"
        self.sacct = json.loads(sacct_path.read_text()) if sacct_path.exists() else None
        submit = self.labeled("submit")
        self.campaign_id = (submit[-1].get("request") or {}).get("campaign_id") if submit else self.summary.get("campaign_id")
        self.events = [e for x in self.labeled("results") for e in (x.get("response") or {}).get("events") or []]
        self.cursors = [e.get("cursor") for e in self.events]
        self.tokens = self._tokens()

    def labeled(self, label):
        return [x for x in self.exchanges if x.get("label") == label]

    def last(self, label):
        return self.labeled(label)[-1]

    def campaign(self, label):
        return ((self.last(label).get("response") or {}).get("campaign")) or {}

    def _tokens(self):
        """Run-specific values by kind, in order of first appearance across every response."""
        tokens = {kind: {} for kind in TOKEN_KINDS}

        def register(kind, raw):
            tokens[kind].setdefault(raw, f"<{kind}#{len(tokens[kind]) + 1}>")

        if self.campaign_id:
            register("campaign_id", self.campaign_id)
        root = re.compile(r"^(.*)/campaigns/" + re.escape(self.campaign_id or "") + r"/results/")

        def walk(value, key=None):
            if isinstance(value, dict):
                for name, item in value.items():
                    walk(item, name)
            elif isinstance(value, list):
                for item in value:
                    walk(item, key)
            elif isinstance(value, (str, int)) and not isinstance(value, bool):
                kind = TOKEN_KEYS.get(key)
                if kind == "node" and value in NO_NODE:
                    return
                if kind:
                    register(kind, str(value))
                elif key == "local_path" and isinstance(value, str) and (match := root.match(value)):
                    register("data_root", match.group(1))

        for exchange in self.exchanges:
            if exchange.get("label") not in UNCOMPARED_LABELS:
                walk(exchange.get("request"))
                walk(exchange.get("response"))
        return tokens


class Normalizer:
    """Replace run-specific values at known fields; leave every other value as recorded."""

    def __init__(self, run, strict_catalog=False):
        self.tokens, self.cursors, self.strict = run.tokens, run.cursors, strict_catalog
        texts = [item for kind in ("job_name", "campaign_id", "data_root") for item in self.tokens[kind].items()]
        self.texts = sorted(texts, key=lambda item: -len(item[0]))

    def text(self, value):
        for raw, placeholder in self.texts:
            value = value.replace(raw, placeholder)
        return value

    def cursor(self, value):
        if self.cursors and value == self.cursors[-1]:
            return "<cursor:last>"
        if value in self.cursors:
            return f"<cursor:#{self.cursors.index(value)}>"
        return "<cursor:0>" if value == 0 else "<cursor:unknown>"

    def __call__(self, value, key=None, inside=()):
        if key == "matching_nodes" and not self.strict and isinstance(value, list):
            return "<catalog:nodes>" if value else []
        if isinstance(value, dict):
            return {name: self(item, name, inside + (name,)) for name, item in value.items()}
        if isinstance(value, list):
            return [self(item, key, inside) for item in value]
        # Scheduler hints and measurements can be absent (null) on one run and known on another.
        if key in HINT_KEYS:
            return "<scheduler-hint>"
        if key in MEASUREMENT_KEYS:
            return "<measurement>"
        if value is None or isinstance(value, bool):
            return value
        if key in TIMESTAMP_KEYS:
            return "<timestamp>"
        if key in CURSOR_KEYS and isinstance(value, int):
            return self.cursor(value)
        if key in DIAGNOSTIC_KEYS and "controller_files" in inside:
            return "<diagnostic>"
        if key in TOKEN_KEYS and str(value) in self.tokens[TOKEN_KEYS[key]]:
            return self.tokens[TOKEN_KEYS[key]][str(value)]
        if key == "alloc_tres" and isinstance(value, str):
            return re.sub(r"(?:^|,)billing=[^,]*", "", value).lstrip(",")
        if key in TEXT_KEYS and isinstance(value, str):
            return self.text(value)
        return value


def _receipt(final, task_id, path):
    """(field path, receipt) of a retrieved file in the final campaign record."""
    for t_index, task in enumerate(final.get("tasks") or []):
        if task.get("task_id") != task_id:
            continue
        artifacts = task.get("artifacts") or {}
        for group in ("files", "controller_files"):
            for r_index, receipt in enumerate(artifacts.get(group) or []):
                if receipt.get("path") == path:
                    return f"status-final.body.campaign.tasks[{t_index}].artifacts.{group}[{r_index}]", receipt
    return None, None


def _paging(run):
    issues, last, seen = [], 0, set()
    for exchange in [x for x in run.exchanges if x.get("label") in ("results", "results-after-final")]:
        where = f"{exchange['label']}[seq {exchange['seq']}]"
        query = _query(exchange.get("path", ""))
        body = exchange.get("response") or {}
        events = body.get("events") or []
        if exchange.get("status") != 200:
            issues.append((where, f"answered HTTP {exchange.get('status')}"))
            continue
        if query.get("limit") != "1" or len(events) > 1:
            issues.append((where, "a page holds more than one event"))
        if query.get("after") != str(last):
            issues.append((where, f"resumed after {query.get('after')}, not after the previous next_cursor {last}"))
        for event in events:
            cursor = event.get("cursor")
            if not isinstance(cursor, int) or cursor <= last or cursor in seen:
                issues.append((where + ".events", f"cursor {cursor} does not increase or repeats"))
            else:
                seen.add(cursor)
                last = cursor
        if body.get("next_cursor") != last:
            issues.append((where + ".next_cursor", f"{body.get('next_cursor')} is not {last}"))
    return issues


def integrity(run):
    """Problems inside one recorded round trip, as (field path, detail), and notes."""
    issues, notes = [], []
    summary = run.summary
    if summary.get("format") != FORMAT:
        issues.append(("summary.format", f"{summary.get('format')} is not {FORMAT}"))
    if not summary.get("ok"):
        issues.append(("summary.ok", summary.get("blocker") or "failed checks: " + "; ".join(summary.get("failed") or [])))
    missing = [label for label in REQUIRED_LABELS if not run.labeled(label)]
    issues.extend((label, "exchange was not recorded") for label in missing)
    if missing:
        return issues, notes
    issues.extend(_paging(run))
    final = run.campaign("status-final")
    if final.get("result_cursor") != (run.cursors[-1] if run.cursors else 0):
        issues.append(("status-final.body.campaign.result_cursor", "is not the last event cursor"))

    submit = run.campaign("submit")
    spec = submit.get("spec") or {}
    try:
        computed = request_hash(spec)
    except (KeyError, TypeError, AttributeError):
        computed = None
    if computed != submit.get("request_hash"):
        hashed = {key: value for key, value in spec.items() if key not in ("bundle_manifest", "backend")}
        if "<redacted:" in json.dumps(hashed) and (summary.get("request_hash") or {}).get("match"):
            notes.append("request hash: the declaration holds a redacted value; the run verified the formula before redaction")
        else:
            issues.append(("submit.body.campaign.request_hash", "does not follow the create formula over the declaration and source digest"))
    hashes = {run.campaign(label).get("request_hash") for label in ("submit", "resend", "status-final", "resend-after-completion")}
    if len(hashes) != 1:
        issues.append(("resend.body.campaign.request_hash", "the request hash changed within the round trip"))

    attempts = final.get("attempts") or []
    for index, attempt in enumerate(attempts):
        if attempt.get("job_name") != job_name(run.campaign_id or "", attempt.get("task_id") or "", attempt.get("attempt")):
            issues.append((f"status-final.body.campaign.attempts[{index}].job_name", "does not follow the attempt name formula"))
    expected = {"campaign_id": 1, "request_hash": 1, "data_root": 1, "job_name": len(attempts),
                "job_id": len([a for a in attempts if a.get("job_id")])}
    for kind, count in expected.items():
        if len(run.tokens[kind]) != count:
            issues.append((f"substitutions.{kind}", f"{len(run.tokens[kind])} distinct values across responses, expected {count}"))
    if len(run.tokens["node"]) > max(1, len(attempts)):
        issues.append(("substitutions.node", f"{len(run.tokens['node'])} assigned nodes for {len(attempts)} attempts"))

    for exchange in run.labeled("artifact-declared") + run.labeled("artifact-diagnostic"):
        query = _query(exchange.get("path", ""))
        where, receipt = _receipt(final, query.get("task_id"), query.get("path"))
        recorded = exchange.get("response_bytes") or {}
        if exchange.get("status") != 200 or receipt is None:
            issues.append((f"{exchange['label']}[seq {exchange['seq']}]", f"HTTP {exchange.get('status')}; receipt found: {receipt is not None}"))
            continue
        for field, actual in (("sha256", recorded.get("sha256")), ("size_bytes", recorded.get("size"))):
            if receipt.get(field) != actual:
                issues.append((f"{where}.{field}", f"receipt {receipt.get(field)} differs from the downloaded bytes ({actual})"))
        text = recorded.get("text")
        if text is not None and "<redacted:" not in text and sha256(text.encode()) != recorded.get("sha256"):
            issues.append((f"{exchange['label']}[seq {exchange['seq']}].response_bytes", "recorded bytes do not match their recorded sha256"))
        if exchange["label"] == "artifact-diagnostic" and text is not None:
            task = next((t for t in final.get("tasks") or [] if t.get("task_id") == query.get("task_id")), {})
            try:
                record = json.loads(text)
            except ValueError:
                record = None
            if record != (task.get("artifacts") or {}).get("hardware"):
                issues.append((f"{exchange['label']}[seq {exchange['seq']}]", "the downloaded attestation differs from the task's recorded hardware evidence"))
    return issues, notes


def _observation_view(event, norm):
    payload = event.get("payload") or {}
    observation = payload.get("observation") or {}
    return {"kind": event.get("kind"), "payload_fields": sorted(payload), "job_id": norm(payload.get("job_id"), "job_id"),
            "error": payload.get("error"),
            "observation": {key: norm(observation.get(key, MISSING), key) for key in QUEUE_FIELDS}}


def view(run, norm):
    """The normalized fields that two round trips must share, in the order of the round trip."""
    result = {}
    health = run.last("health")
    result["health"] = {"status": health.get("status"),
                        **{key: (health.get("response") or {}).get(key) for key in ("ok", "service", "mode", "campaign_schema_version", "capabilities")}}
    backend = run.last("backend")
    result["settings"] = {"status": backend.get("status"), "settings": norm((backend.get("response") or {}).get("settings"))}
    result["declaration"] = norm(run.last("submit").get("request"))
    for label in ("plan", "listing-after-plan", "submit"):
        exchange = run.last(label)
        result[label] = {"status": exchange.get("status"), "body": norm(exchange.get("response"))}
    resend = run.last("resend")
    campaign = (resend.get("response") or {}).get("campaign") or {}
    result["resend"] = {"status": resend.get("status"), "idempotent": campaign.get("idempotent"),
                        "id": norm(campaign.get("id"), "id"), "request_hash": norm(campaign.get("request_hash"), "request_hash")}
    result["events"] = [{"campaign_id": norm(e.get("campaign_id"), "campaign_id"), "task_id": e.get("task_id"), "kind": e.get("kind"),
                         "created_at": norm(e.get("created_at"), "created_at"), "payload": norm(e.get("payload"))}
                        for e in run.events if classify(e) != "observation"]
    for label in ("results-after-final", "status-final"):
        exchange = run.last(label)
        result[label] = {"status": exchange.get("status"), "body": norm(exchange.get("response"))}
    for label in ("artifact-declared", "artifact-diagnostic"):
        items = []
        for exchange in run.labeled(label):
            query, recorded = _query(exchange.get("path", "")), exchange.get("response_bytes") or {}
            item = {"status": exchange.get("status"), "task_id": query.get("task_id"), "path": norm(query.get("path"), "path")}
            if label == "artifact-declared":
                item.update(size=recorded.get("size"), sha256=recorded.get("sha256"), text=recorded.get("text"))
            else:
                try:
                    item["attestation"] = norm(json.loads(recorded.get("text") or "null"))
                except ValueError:
                    item["attestation"] = "<unreadable>"
            items.append(item)
        result[label] = items
    for label in ("artifact-undeclared", "resend-after-completion"):
        exchange = run.last(label)
        result[label] = {"status": exchange.get("status"), "body": norm(exchange.get("response"))}
    result["substitutions"] = {kind: len(values) for kind, values in run.tokens.items()}
    return result


def differences(a, b, path, out):
    if isinstance(a, dict) and isinstance(b, dict):
        for key in list(a) + [key for key in b if key not in a]:
            where = f"{path}.{key}" if path else str(key)
            if key not in b:
                out.append((where, a[key], MISSING))
            elif key not in a:
                out.append((where, MISSING, b[key]))
            else:
                differences(a[key], b[key], where, out)
    elif isinstance(a, list) and isinstance(b, list):
        for index, (x, y) in enumerate(zip(a, b)):
            differences(x, y, f"{path}[{index}]", out)
        out.extend((f"{path}[{i}]", a[i], MISSING) for i in range(len(b), len(a)))
        out.extend((f"{path}[{i}]", MISSING, b[i]) for i in range(len(a), len(b)))
    elif isinstance(a, bool) != isinstance(b, bool) or a != b:
        out.append((path, a, b))


def _leaves(value):
    if isinstance(value, dict):
        return sum(_leaves(item) for item in value.values())
    if isinstance(value, list):
        return sum(_leaves(item) for item in value) or 1
    return 1


def _short(value):
    text = json.dumps(value, sort_keys=True, default=str)
    return text if len(text) <= 240 else text[:237] + "..."


def compare(args):
    try:
        runs = {"baseline": Run(args.baseline), "head": Run(args.head)}
    except (OSError, ValueError, KeyError) as exc:
        print(f"MISMATCH evidence: cannot read a recorded round trip: {exc}")
        return 1
    problems, notes = [], []
    for side, recorded in runs.items():
        issues, side_notes = integrity(recorded)
        problems.extend((f"{side}:{path}", detail) for path, detail in issues)
        notes.extend(f"{side}: {note}" for note in side_notes)
    views = {}
    if not any(path.split(":", 1)[1] in REQUIRED_LABELS for path, _ in problems):
        norms = {side: Normalizer(recorded, args.strict_catalog) for side, recorded in runs.items()}
        views = {side: view(recorded, norms[side]) for side, recorded in runs.items()}
        found = []
        differences(views["baseline"], views["head"], "", found)
        observed = {}
        for side, recorded in runs.items():
            observed[side] = {}
            for event in recorded.events:
                if classify(event) == "observation":
                    state = ((event.get("payload") or {}).get("observation") or {}).get("state")
                    observed[side].setdefault(f"{event.get('kind')}:{state}", _observation_view(event, norms[side]))
        shared = [key for key in observed["baseline"] if key in observed["head"]]
        for key in shared:
            differences(observed["baseline"][key], observed["head"][key], f"observations[{key}]", found)
        views["observations"] = {"compared": shared, "baseline_only": [k for k in observed["baseline"] if k not in shared],
                                 "head_only": [k for k in observed["head"] if k not in shared]}
        notes.append(f"optional queue observations compared: {shared or 'none'}; baseline only: {views['observations']['baseline_only'] or 'none'};"
                     f" head only: {views['observations']['head_only'] or 'none'}")
        sacct_records = {side: recorded.sacct for side, recorded in runs.items()}
        if all(sacct_records.values()):
            for side, record in sacct_records.items():
                if not record.get("ok"):
                    problems.append((f"{side}:sacct.ok", f"allocations {record.get('allocation_ids')}, journal {record.get('journal_job_ids')}"))
            reduced = {side: {"distinct_allocations": r.get("distinct_allocations"), "agrees_with_journal": r.get("agrees_with_journal"),
                              "allocation": [{"state": a.get("state"), "exit_code": a.get("exit_code")} for a in r.get("allocation") or []]}
                       for side, r in sacct_records.items()}
            differences(reduced["baseline"], reduced["head"], "sacct", found)
        else:
            notes.append("Slurm accounting: " + ", ".join(f"{side} {'recorded' if r else 'not recorded'}" for side, r in sacct_records.items()))
        if not args.strict_catalog:
            nodes = {side: [(t.get("placement") or {}).get("matching_nodes") for t in (r.last("plan").get("response") or {}).get("tasks") or []]
                     for side, r in runs.items()}
            if nodes["baseline"] != nodes["head"]:
                notes.append("plan matching_nodes differ between the two catalogs; --strict-catalog compares them")
        problems.extend((path, f"baseline={_short(a)} head={_short(b)}") for path, a, b in found)
    report = {"result": "mismatch" if problems else "match", "differences": [{"path": p, "detail": d} for p, d in problems],
              "notes": notes, "baseline": {k: runs["baseline"].summary.get(k) for k in ("revision", "campaign_id", "job_ids", "url")},
              "head": {k: runs["head"].summary.get(k) for k in ("revision", "campaign_id", "job_ids", "url")}, "normalized": views}
    if args.out:
        _write_json(Path(args.out), report)
    if problems:
        shown = problems if args.all else problems[:1]
        for path, detail in shown:
            print(f"MISMATCH {path}: {detail}")
        if len(problems) > len(shown):
            print(f"({len(problems) - len(shown)} more; --all lists every difference)")
        for note in notes:
            print(f"note: {note}")
        return 1
    print(f"MATCH baseline {report['baseline']['revision'] or ''} {report['baseline']['campaign_id']} and head "
          f"{report['head']['revision'] or ''} {report['head']['campaign_id']}: {_leaves(views['baseline'])} normalized fields equal")
    for note in notes:
        print(f"note: {note}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    command = commands.add_parser("declare", help="write a verification declaration with a fresh campaign ID")
    command.add_argument("--template", required=True, help="campaign JSON to copy, such as examples/cpu-result/campaign.json")
    command.add_argument("--bundle", required=True, help="absolute bundle directory that every compared controller reads")
    command.add_argument("--prefix", required=True, help="campaign ID prefix, distinct for each side (rtb-, rth-)")
    command.add_argument("--out", required=True, help="new declaration file, outside the bundle")

    command = commands.add_parser("run", help="drive and record one round trip")
    command.add_argument("--url", required=True, help="controller base URL, such as http://127.0.0.1:8411")
    command.add_argument("--declaration", required=True, help="campaign JSON to post for plan, submit, and every resend")
    command.add_argument("--out", required=True, help="new or empty evidence directory")
    command.add_argument("--deadline-seconds", type=float, default=2700, help="give up waiting for completion after this (default 2700)")
    command.add_argument("--poll-seconds", type=float, default=15, help="pause between status polls (default 15)")
    command.add_argument("--request-timeout", type=float, default=300, help="timeout of one HTTP request (default 300)")
    command.add_argument("--revision", default=None, help="controller revision to record, such as a commit SHA")
    command.add_argument("--no-probe", dest="probe", action="store_false", help="do not refresh a stale catalog before planning")
    command.add_argument("--redact", action="append", default=[], help="another value to replace in recorded files")
    command.add_argument("--redact-file", default=None, help="file with one more value to replace on each line")
    command.add_argument("--result-path", default="result.json", help="declared output whose bytes are checked")
    command.add_argument("--expected-result", default=DEFAULT_RESULT, help="exact bytes of --result-path (UTF-8)")
    command.add_argument("--undeclared-path", default="task.py", help="bundle file that the artifact route must refuse")

    command = commands.add_parser("sacct", help="check the recorded attempt against Slurm accounting over SSH")
    command.add_argument("directory", help="evidence directory written by run")
    command.add_argument("--ssh-host", required=True, help="SSH alias of the cluster login node")
    command.add_argument("--query-timeout", type=float, default=30, help="remote timeout for sacct (default 30)")
    command.add_argument("--redact", action="append", default=[], help="value to replace in sacct.json")

    command = commands.add_parser("compare", help="compare two recorded round trips")
    command.add_argument("baseline", help="evidence directory of the baseline revision")
    command.add_argument("head", help="evidence directory of the revision under test")
    command.add_argument("--out", default=None, help="write the raw and normalized comparison as JSON")
    command.add_argument("--all", action="store_true", help="print every difference, not only the first")
    command.add_argument("--strict-catalog", action="store_true", help="also compare the plan's matching catalog nodes")

    args = parser.parse_args(argv)
    return {"declare": declare, "run": run, "sacct": sacct, "compare": compare}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
