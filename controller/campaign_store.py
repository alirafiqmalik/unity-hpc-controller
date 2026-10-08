"""Controller-owned campaign journal. Transactions precede remote effects."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from lib import paths
from controller.campaign_contract import Conflict, safe_id

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS campaigns(id TEXT PRIMARY KEY,spec TEXT NOT NULL,request_hash TEXT NOT NULL,state TEXT NOT NULL,created_at TEXT NOT NULL,staged INTEGER DEFAULT 0,error TEXT);
CREATE TABLE IF NOT EXISTS tasks(campaign_id TEXT,task_id TEXT,spec TEXT NOT NULL,state TEXT NOT NULL,attempt INTEGER DEFAULT 0,job_id TEXT,job_name TEXT,eligible_at REAL DEFAULT 0,error TEXT,observation TEXT,artifacts TEXT,PRIMARY KEY(campaign_id,task_id));
CREATE TABLE IF NOT EXISTS attempts(campaign_id TEXT,task_id TEXT,attempt INTEGER,job_name TEXT,job_id TEXT,state TEXT,created_at TEXT,receipt TEXT,observation TEXT,PRIMARY KEY(campaign_id,task_id,attempt));
CREATE TABLE IF NOT EXISTS hardware_locks(model_class TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,observed TEXT);
CREATE TABLE IF NOT EXISTS events(cursor INTEGER PRIMARY KEY AUTOINCREMENT,campaign_id TEXT,task_id TEXT,kind TEXT,payload TEXT,created_at TEXT);
CREATE INDEX IF NOT EXISTS events_campaign ON events(campaign_id,cursor);
"""


def now():
    return datetime.now(timezone.utc).isoformat()


def root(identity):
    return paths.controller_dir() / "campaigns" / safe_id(identity, "campaign_id")


def _attempt_state(task_state, observation):
    # The task waits for a new attempt after these terminal scheduler outcomes.
    # Keep that outcome on the finished attempt, including cancellation in backoff.
    scheduler_state = (observation or {}).get("state")
    if task_state in ("waiting", "cancelled", "blocked") and scheduler_state in ("PREEMPTED", "NODE_FAIL", "BOOT_FAIL"):
        return scheduler_state
    return task_state


@contextmanager
def database():
    directory = paths.controller_dir()
    directory.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(directory / "campaigns.db", timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(SCHEMA)
    try:
        connection.execute("BEGIN IMMEDIATE")
        version = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if version and version[0] not in ("1", "2"):
            raise Conflict("unsupported campaigns database schema")
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(attempts)")}
        if "observation" not in columns:
            connection.execute("ALTER TABLE attempts ADD COLUMN observation TEXT")
        if version and version[0] == "1":
            # Only the latest task observation is recoverable. Do not invent
            # scheduler history for earlier attempts after a retry.
            for row in connection.execute("SELECT * FROM tasks WHERE attempt>0"):
                task = decode(row)
                observation = task.get("observation")
                connection.execute("UPDATE attempts SET state=?,observation=? WHERE campaign_id=? AND task_id=? AND attempt=?",
                                   (_attempt_state(task["state"], observation), json.dumps(observation, sort_keys=True) if observation else None,
                                    task["campaign_id"], task["task_id"], task["attempt"]))
        connection.execute("INSERT OR REPLACE INTO meta VALUES('schema_version','2')")
        connection.commit()
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def event(connection, campaign_id, task_id, kind, payload=None):
    connection.execute("INSERT INTO events(campaign_id,task_id,kind,payload,created_at) VALUES(?,?,?,?,?)",
                       (campaign_id, task_id, kind, json.dumps(payload or {}, sort_keys=True), now()))


def decode(row):
    value = dict(row)
    for key in ("spec", "observation", "artifacts", "receipt"):
        if value.get(key):
            value[key] = json.loads(value[key])
    return value


def read(identity):
    safe_id(identity, "campaign_id")
    with database() as con:
        row = con.execute("SELECT * FROM campaigns WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise FileNotFoundError(f"unknown campaign: {identity}")
        value = decode(row)
        value["tasks"] = [decode(t) for t in con.execute("SELECT * FROM tasks WHERE campaign_id=? ORDER BY rowid", (identity,))]
        value["attempts"] = [decode(t) for t in con.execute("SELECT * FROM attempts WHERE campaign_id=? ORDER BY task_id,attempt", (identity,))]
        value["result_cursor"] = con.execute("SELECT COALESCE(MAX(cursor),0) FROM events WHERE campaign_id=?", (identity,)).fetchone()[0]
        return value


def listing():
    with database() as con:
        return [decode(row) for row in con.execute("SELECT * FROM campaigns ORDER BY created_at DESC")]


def results(identity, after=0, limit=100):
    read(identity)
    with database() as con:
        rows = [dict(row) for row in con.execute("SELECT * FROM events WHERE campaign_id=? AND cursor>? ORDER BY cursor LIMIT ?", (identity, after, max(1, min(limit, 1000))))]
    for row in rows:
        row["payload"] = json.loads(row["payload"])
    return {"campaign_id": identity, "events": rows, "next_cursor": rows[-1]["cursor"] if rows else after}


def change(identity, task_id, state, **updates):
    allowed = {"attempt", "job_id", "job_name", "eligible_at", "error", "observation", "artifacts"}
    if updates.keys() - allowed:
        raise ValueError("unknown task update")
    with database() as con:
        row = con.execute("SELECT * FROM tasks WHERE campaign_id=? AND task_id=?", (identity, task_id)).fetchone()
        if row is None:
            raise FileNotFoundError(f"unknown campaign task: {identity}/{task_id}")
        previous = decode(row)
        publish = previous["state"] != state or any(
            key != "observation" and previous.get(key) != value for key, value in updates.items()
        )
        if "observation" in updates:
            before, after = previous.get("observation") or {}, updates["observation"] or {}
            meaningful = ("state", "job_id", "pending_reason", "estimated_start", "node_list", "exit_code", "fetch_attempts")
            publish = publish or any(before.get(key) != after.get(key) for key in meaningful)
        data = {"state": state, **updates}
        for key in ("observation", "artifacts"):
            if key in data:
                data[key] = json.dumps(data[key], sort_keys=True)
        con.execute(f"UPDATE tasks SET {','.join(k+'=?' for k in data)} WHERE campaign_id=? AND task_id=?", (*data.values(), identity, task_id))
        # Persist every measurement and observation timestamp. The event stream
        # carries transitions and actionable queue changes, not routine polls.
        if publish:
            event(con, identity, task_id, state, updates)
        current = {**previous, "state": state, **updates}
        observation = current.get("observation")
        con.execute("UPDATE attempts SET job_id=?,state=?,observation=? WHERE campaign_id=? AND task_id=? AND attempt=?",
                    (current.get("job_id"), _attempt_state(state, observation),
                     json.dumps(observation, sort_keys=True) if observation else None,
                     identity, task_id, current["attempt"]))


def bind_observed(model_class, actual):
    encoded = json.dumps(actual, sort_keys=True)
    with database() as con:
        lock = con.execute("SELECT observed FROM hardware_locks WHERE model_class=?", (model_class,)).fetchone()
        if lock is None:
            raise Conflict("hardware class has no durable lock")
        if lock[0] and lock[0] != encoded:
            raise Conflict("observed GPU model or memory differs from this hardware class")
        con.execute("UPDATE hardware_locks SET observed=? WHERE model_class=?", (encoded, model_class))
