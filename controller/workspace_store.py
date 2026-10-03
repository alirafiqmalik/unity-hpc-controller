"""Transactional workspace records. The scheduler ledger remains owned by run.sh."""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from lib import paths

SCHEMA_VERSION = 1
_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")


class WorkspaceError(ValueError):
    status = 400


class Conflict(WorkspaceError):
    status = 409

    def __init__(self, message, *, current_version=None, expected_version=None):
        super().__init__(message)
        # These are entity concurrency tokens, never workspace schema versions.
        # State/capability conflicts may have no meaningful entity token.
        self.current_version = current_version
        self.expected_version = expected_version


class Missing(WorkspaceError):
    status = 404


def now():
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:20]}"


def safe_id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise WorkspaceError("invalid workspace identity")
    return value


@contextmanager
def transaction(slug):
    safe_id(slug)
    directory = paths.controller_dir() / "workspaces"
    directory.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(directory / f"{slug}.db", timeout=30)
    try:
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA synchronous=FULL")
        version = con.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, SCHEMA_VERSION):
            raise WorkspaceError(f"unsupported workspace store version {version}")
        con.execute("CREATE TABLE IF NOT EXISTS records(kind TEXT, id TEXT, body TEXT NOT NULL, PRIMARY KEY(kind,id))")
        con.execute("CREATE TABLE IF NOT EXISTS dispatch_keys(key TEXT PRIMARY KEY, plan_id TEXT NOT NULL, execution_id TEXT NOT NULL)")
        con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        con.commit()
        con.execute("BEGIN IMMEDIATE")
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def get(con, kind, identity):
    safe_id(identity)
    row = con.execute("SELECT body FROM records WHERE kind=? AND id=?", (kind, identity)).fetchone()
    if row is None:
        raise Missing(f"unknown {kind} {identity}")
    return json.loads(row[0])


def put(con, kind, obj):
    safe_id(obj["id"])
    con.execute("INSERT INTO records(kind,id,body) VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body",
                (kind, obj["id"], json.dumps(obj, sort_keys=True, allow_nan=False)))
    return obj


def list_records(con, kind):
    return [json.loads(row[0]) for row in con.execute("SELECT body FROM records WHERE kind=? ORDER BY rowid DESC", (kind,))]


def read(slug, kind, identity):
    with readonly(slug) as con:
        if con is None:
            raise Missing(f"unknown {kind} {identity}")
        return get(con, kind, identity)


def listing(slug, kind):
    with readonly(slug) as con:
        if con is None:
            return []
        return list_records(con, kind)


@contextmanager
def readonly(slug):
    """History reads never create stores or advance an unknown store schema."""
    safe_id(slug)
    database = paths.controller_dir() / "workspaces" / f"{slug}.db"
    if not database.is_file():
        yield None
        return
    con = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=30)
    try:
        columns = {row[1] for row in con.execute('PRAGMA table_info(records)')}
        if not {'kind', 'id', 'body'}.issubset(columns):
            raise WorkspaceError('Workspace history schema has no compatible record reader')
        yield con
    finally:
        con.close()


def create_experiment(slug, draft, *, cloned_from=None):
    if not isinstance(draft, dict) or not isinstance(draft.get("workflow"), str):
        raise WorkspaceError("draft requires a declared workflow")
    stamp = now()
    item = dict(id=new_id("exp"), name=draft.get("name") or "Untitled experiment",
                workflow=draft["workflow"], draft=draft, revision=1, version=1,
                archived=False, executions=[], created_at=stamp, updated_at=stamp,
                cloned_from=cloned_from, readiness="unchecked")
    with transaction(slug) as con:
        return put(con, "experiment", item)


def update_experiment(slug, identity, body):
    with transaction(slug) as con:
        item = get(con, "experiment", identity)
        if body.get("expected_version") != item["version"]:
            raise Conflict("The draft changed in another editor. Reload the saved draft or keep your edits and retry with its version.",
                           current_version=item['version'], expected_version=body.get('expected_version'))
        draft = body.get("draft")
        if not isinstance(draft, dict):
            raise WorkspaceError("draft must be an object")
        if item.get("frozen_revision") == item["revision"]:
            item["revision"] += 1
        item.update(draft=draft, name=draft.get("name") or "Untitled experiment",
                    workflow=draft.get("workflow", item["workflow"]), version=item["version"] + 1,
                    updated_at=now(), readiness="unchecked")
        return put(con, "experiment", item)


def experiment_action(slug, identity, action):
    with transaction(slug) as con:
        item = get(con, "experiment", identity)
        if action == "delete":
            if item["executions"]:
                raise Conflict("This experiment has execution history. Archive it instead.")
            con.execute("DELETE FROM records WHERE kind='experiment' AND id=?", (identity,))
            return {"ok": True}
        if action in ("archive", "restore"):
            item["archived"] = action == "archive"
        elif action == "revisions":
            put(con, "revision", dict(id=f"{identity}-r{item['revision']}", experiment_id=identity,
                                      revision=item["revision"], draft=item["draft"]))
            item["revision"] += 1
            item["readiness"] = "unchecked"
        else:
            raise WorkspaceError("unknown experiment action")
        item.update(version=item["version"] + 1, updated_at=now())
        return put(con, "experiment", item)
