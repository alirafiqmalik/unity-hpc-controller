"""Campaign journal: the only code that opens campaigns.db. One transaction for each operation; transactions precede remote effects."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from lib import paths
from controller import campaign_lifecycle as lifecycle, hardware_class
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


_prepared = set()
_prepare_lock = threading.Lock()
# Listings decode every frozen declaration, so two at once would double peak
# memory; a second listing waits for the first. No other operation takes this lock.
_listing_lock = threading.Lock()


def _path():
    return paths.controller_dir() / "campaigns.db"


def _connect(path):
    connection = sqlite3.connect(path, timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    return connection


def _ready():
    """Create or migrate the journal once per process and database path."""
    path = _path()
    key = str(path)
    if key in _prepared and path.exists():
        return path
    with _prepare_lock:
        if key in _prepared and path.exists():
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = _connect(path)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA)  # outside the txn: executescript would COMMIT an open txn
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
                    task = _decode(row)
                    observation = task.get("observation")
                    connection.execute("UPDATE attempts SET state=?,observation=? WHERE campaign_id=? AND task_id=? AND attempt=?",
                                       (lifecycle.attempt_outcome(task["state"], observation), json.dumps(observation, sort_keys=True) if observation else None,
                                        task["campaign_id"], task["task_id"], task["attempt"]))
            if version is None or version[0] == "1":
                connection.execute("INSERT OR REPLACE INTO meta VALUES('schema_version','2')")
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
        _prepared.add(key)
    return path


def prepare():
    """Create or migrate the journal now instead of on first use."""
    _ready()


@contextmanager
def _write():
    connection = _connect(_ready())
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.execute("COMMIT")
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


@contextmanager
def _read():
    connection = _connect(_ready())
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        yield connection
    finally:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        connection.close()


def _event(connection, campaign_id, task_id, kind, payload=None):
    connection.execute("INSERT INTO events(campaign_id,task_id,kind,payload,created_at) VALUES(?,?,?,?,?)",
                       (campaign_id, task_id, kind, json.dumps(payload or {}, sort_keys=True), now()))


def _decode(row):
    value = dict(row)
    for key in ("spec", "observation", "artifacts", "receipt"):
        if value.get(key):
            value[key] = json.loads(value[key])
    return value


def _campaign(con, identity, attempts=None):
    """The campaign row, its task rows, and the named attempt columns, if any, read in one snapshot."""
    row = con.execute("SELECT * FROM campaigns WHERE id=?", (identity,)).fetchone()
    if row is None:
        raise FileNotFoundError(f"unknown campaign: {identity}")
    value = _decode(row)
    value["tasks"] = [_decode(t) for t in con.execute("SELECT * FROM tasks WHERE campaign_id=? ORDER BY rowid", (identity,))]
    if attempts:
        value["attempts"] = [_decode(t) for t in con.execute(f"SELECT {attempts} FROM attempts WHERE campaign_id=? ORDER BY task_id,attempt", (identity,))]
    return value


def read(identity):
    """The full campaign snapshot: tasks, attempts with receipts and observations, and the Result cursor."""
    safe_id(identity, "campaign_id")
    with _read() as con:
        value = _campaign(con, identity, "*")
        value["result_cursor"] = con.execute("SELECT COALESCE(MAX(cursor),0) FROM events WHERE campaign_id=?", (identity,)).fetchone()[0]
        return value


def downloadable(identity, task_id):
    """The paths a client may download from one task: its declared outputs and its
    retrieved controller diagnostics. None when the campaign has no such task."""
    safe_id(identity, "campaign_id")
    with _read() as con:
        if con.execute("SELECT 1 FROM campaigns WHERE id=?", (identity,)).fetchone() is None:
            raise FileNotFoundError(f"unknown campaign: {identity}")
        row = con.execute("SELECT spec,artifacts FROM tasks WHERE campaign_id=? AND task_id=?", (identity, task_id)).fetchone()
    if row is None:
        return None
    task = _decode(row)
    paths = set(task["spec"]["outputs"])
    paths.update(receipt["path"] for receipt in (task.get("artifacts") or {}).get("controller_files", []))
    return paths


def worker_read(identity, *, attempt_identities=False):
    """The campaign and task records that one Worker step decides from, in one snapshot, without the
    Result cursor. With attempt_identities, also each attempt's task_id, attempt, and job_name, which
    reconciliation uses to name diagnostics from earlier attempts; never receipts or observations."""
    safe_id(identity, "campaign_id")
    with _read() as con:
        return _campaign(con, identity, "task_id,attempt,job_name" if attempt_identities else None)


def listing():
    with _listing_lock:
        with _read() as con:
            return [_decode(row) for row in con.execute("SELECT * FROM campaigns ORDER BY created_at DESC")]


def identities_excluding(states):
    """Select worker identities without loading historical source manifests."""
    states = tuple(sorted(states))
    placeholders = ",".join("?" for _ in states)
    with _read() as con:
        return [row[0] for row in con.execute(
            f"SELECT id FROM campaigns WHERE state NOT IN ({placeholders}) ORDER BY created_at DESC", states
        )]


def tasks_in_states(states):
    """Read capacity evidence without traversing campaign bundles or results."""
    states = tuple(sorted(states))
    placeholders = ",".join("?" for _ in states)
    with _read() as con:
        return [_decode(row) for row in con.execute(
            f"SELECT * FROM tasks WHERE state IN ({placeholders}) ORDER BY rowid", states
        )]


def results(identity, after=0, limit=100):
    safe_id(identity, "campaign_id")
    with _read() as con:
        if con.execute("SELECT 1 FROM campaigns WHERE id=?", (identity,)).fetchone() is None:
            raise FileNotFoundError(f"unknown campaign: {identity}")
        rows = [dict(row) for row in con.execute("SELECT * FROM events WHERE campaign_id=? AND cursor>? ORDER BY cursor LIMIT ?", (identity, after, max(1, min(limit, 1000))))]
    for row in rows:
        row["payload"] = json.loads(row["payload"])
    return {"campaign_id": identity, "events": rows, "next_cursor": rows[-1]["cursor"] if rows else after}


def _check(state, updates):
    if state not in lifecycle.TASK_STATES:
        raise ValueError("unknown task state")
    allowed = {"attempt", "job_id", "job_name", "eligible_at", "error", "observation", "artifacts"}
    if updates.keys() - allowed:
        raise ValueError("unknown task update")


def _transition(con, identity, task_id, state, updates):
    # Read only what this transition compares or carries to the attempt row, never the frozen declaration.
    columns = ",".join(dict.fromkeys(("state", "attempt", "job_id", "observation", *updates)))
    row = con.execute(f"SELECT {columns} FROM tasks WHERE campaign_id=? AND task_id=?", (identity, task_id)).fetchone()
    if row is None:
        raise FileNotFoundError(f"unknown campaign task: {identity}/{task_id}")
    previous = _decode(row)
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
        _event(con, identity, task_id, state, updates)
    current = {**previous, "state": state, **updates}
    observation = current.get("observation")
    con.execute("UPDATE attempts SET job_id=?,state=?,observation=? WHERE campaign_id=? AND task_id=? AND attempt=?",
                (current.get("job_id"), lifecycle.attempt_outcome(state, observation),
                 json.dumps(observation, sort_keys=True) if observation else None,
                 identity, task_id, current["attempt"]))


def record_transition(identity, task_id, state, **updates):
    _check(state, updates)
    with _write() as con:
        _transition(con, identity, task_id, state, updates)


def bind_observed(model_class, observed):
    """Bind the devices that the Model class's first accepted result reported (hardware_class.observed text)."""
    with _write() as con:
        lock = con.execute("SELECT observed FROM hardware_locks WHERE model_class=?", (model_class,)).fetchone()
        if lock is None:
            raise Conflict("hardware class has no durable lock")
        if hardware_class.observed_differs(lock[0], observed):
            raise Conflict("observed GPU model or memory differs from this hardware class")
        con.execute("UPDATE hardware_locks SET observed=? WHERE model_class=?", (observed, model_class))


def prior_acceptance(identity, model_classes):
    with _read() as con:
        row = con.execute("SELECT request_hash FROM campaigns WHERE id=?", (identity,)).fetchone()
        locked = {}
        for model_class in dict.fromkeys(model_classes):
            previous = con.execute("SELECT fingerprint FROM hardware_locks WHERE model_class=?", (model_class,)).fetchone()
            if previous:
                locked[model_class] = previous[0]
        return (row[0] if row else None), locked


def accept(identity, specification, request_hash, hardware_locks, event):
    with _write() as con:
        for model_class, fingerprint in hardware_locks:
            con.execute("INSERT OR IGNORE INTO hardware_locks(model_class,fingerprint) VALUES(?,?)", (model_class, fingerprint))
        con.execute("INSERT INTO campaigns(id,spec,request_hash,state,created_at) VALUES(?,?,?,?,?)", (identity, json.dumps(specification, sort_keys=True), request_hash, lifecycle.ACCEPTED, now()))
        for task in specification["tasks"]:
            con.execute("INSERT INTO tasks(campaign_id,task_id,spec,state) VALUES(?,?,?,?)", (identity, task["task_id"], json.dumps(task, sort_keys=True), lifecycle.WAITING))
        _event(con, identity, None, lifecycle.ACCEPTED, event)


def record_intent(identity, task_id, step):
    """Record the attempt row, the task state, and the Result event in one transaction.
    The event carries only the attempt number and the job name."""
    _check(step.state, step.fields)
    fields = step.fields
    attempt, name = fields["attempt"], fields["job_name"]
    with _write() as con:
        con.execute("INSERT INTO attempts(campaign_id,task_id,attempt,job_name,state,created_at) VALUES(?,?,?,?,?,?)", (identity, task_id, attempt, name, lifecycle.attempt_outcome(step.state, None), now()))
        con.execute("UPDATE tasks SET attempt=?,job_name=?,job_id=?,state=?,error=?,observation=?,eligible_at=? WHERE campaign_id=? AND task_id=?", (attempt, name, fields["job_id"], step.state, fields["error"], fields["observation"], fields["eligible_at"], identity, task_id))
        _event(con, identity, task_id, step.state, {"attempt": attempt, "job_name": name})


def record_submission(identity, task_id, attempt, receipt, step):
    _check(step.state, step.fields)
    with _write() as con:
        _transition(con, identity, task_id, step.state, step.fields)
        con.execute("UPDATE attempts SET receipt=? WHERE campaign_id=? AND task_id=? AND attempt=?",
                    (json.dumps(receipt), identity, task_id, attempt))


def record_diagnostics(identity, task_id, diagnostics):
    with _write() as con:
        row = con.execute("SELECT artifacts FROM tasks WHERE campaign_id=? AND task_id=?", (identity, task_id)).fetchone()
        metadata = json.loads(row[0]) if row and row[0] else {"files": [], "complete": False}
        if metadata.get("controller_files") == diagnostics:
            return False
        metadata["controller_files"] = diagnostics
        con.execute("UPDATE tasks SET artifacts=? WHERE campaign_id=? AND task_id=?",
                    (json.dumps(metadata, sort_keys=True), identity, task_id))
        _event(con, identity, task_id, "diagnostics_available", {"controller_files": diagnostics})
        return True


def roll_up(identity):
    safe_id(identity, "campaign_id")
    with _write() as con:
        row = con.execute("SELECT state FROM campaigns WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise FileNotFoundError(f"unknown campaign: {identity}")
        states = [task[0] for task in con.execute("SELECT state FROM tasks WHERE campaign_id=? ORDER BY rowid", (identity,))]
        state = lifecycle.campaign_state(row[0], states)
        if state is not None:
            con.execute("UPDATE campaigns SET state=? WHERE id=?", (state, identity))
            _event(con, identity, None, state)
        return state


def record_cancel_request(identity, state):
    with _write() as con:
        con.execute("UPDATE campaigns SET state=? WHERE id=?", (state, identity))
        _event(con, identity, None, state)


ERROR_STEPS = ("reconcile", "placement", "stage", "admission")


def error_step(error):
    """The Worker step a campaign error belongs to, or None. Text without a known
    step prefix predates the prefixes and belongs to reconcile."""
    if not error:
        return None
    step, separator, _ = error.partition(": ")
    return step if separator and step in ERROR_STEPS else "reconcile"


def record_campaign_error(identity, step, message):
    """Show a failed Worker step on the campaign as "<step>: <message>".
    Returns True when the stored error changed."""
    if step not in ERROR_STEPS:
        raise ValueError("unknown worker step")
    text = f"{step}: {message}"
    with _write() as con:
        if con.execute("UPDATE campaigns SET error=? WHERE id=? AND error IS NOT ?", (text, identity, text)).rowcount:
            return True
        if con.execute("SELECT 1 FROM campaigns WHERE id=?", (identity,)).fetchone() is None:
            raise FileNotFoundError(f"unknown campaign: {identity}")
        return False


def clear_campaign_error(identity, error):
    """Clear the campaign error only if it is still exactly this text."""
    with _write() as con:
        con.execute("UPDATE campaigns SET error=NULL WHERE id=? AND error=?", (identity, error))


def record_staged(identity, evidence):
    with _write() as con:
        # This commit also resolves a stage error, so a crash right after it
        # cannot leave an error that no later pass would clear.
        con.execute("UPDATE campaigns SET staged=1,error=CASE WHEN substr(error,1,7)='stage: ' THEN NULL ELSE error END WHERE id=?", (identity,))
        _event(con, identity, None, "source_staged", evidence)


def record_task_error(identity, task_id, message):
    with _write() as con:
        con.execute("UPDATE tasks SET error=? WHERE campaign_id=? AND task_id=?", (message, identity, task_id))
