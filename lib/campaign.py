"""The per-project job ledger — the one record every management tool reads.

A project's `unityHPC/run.sh` writes a row here the moment SLURM accepts a job.
Everything downstream (`unity_status`, `unity_jobs`, `unity_my_jobs`,
`recommend-hardware`) reads it. Without this file the project has submitted
jobs it cannot name, and every management tool is blind.

Two writers share the schema:
  * `run.sh` — an inlined python3 helper, so the generated dispatcher stays
    self-contained and survives plugin upgrades (it must not import from a
    version-stamped plugin path). It embeds `SCHEMA` verbatim; a contract test
    asserts the two never drift.
  * this module — used by the MCP server to read and to fold in shared
    telemetry.

Stdlib only. Every read is fail-safe: a missing, empty or corrupt ledger yields
an empty result, never an exception.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

#: Embedded verbatim in templates/scaffold/common/run.sh. Change both together;
#: tests/test_ledger_contract.py fails if they drift.
SCHEMA = """CREATE TABLE IF NOT EXISTS jobs (
    job_id        TEXT PRIMARY KEY,
    exp           TEXT NOT NULL DEFAULT '',
    partition     TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'PENDING',
    attempt       INTEGER NOT NULL DEFAULT 1,
    submitted_utc TEXT NOT NULL DEFAULT '',
    hardware      TEXT,
    elapsed_s     REAL,
    updated_utc   TEXT
)"""

#: Every column the readers expect, with the declaration used to add it to a
#: ledger written by an older plugin version. Projects have live ledgers from
#: before `hardware`/`elapsed_s`/`updated_utc` existed; they are upgraded in
#: place on first write rather than being rejected or rebuilt.
_COLUMNS: dict[str, str] = {
    "exp": "TEXT NOT NULL DEFAULT ''",
    "partition": "TEXT NOT NULL DEFAULT ''",
    "status": "TEXT NOT NULL DEFAULT 'PENDING'",
    "attempt": "INTEGER NOT NULL DEFAULT 1",
    "submitted_utc": "TEXT NOT NULL DEFAULT ''",
    "hardware": "TEXT",
    "elapsed_s": "REAL",
    "updated_utc": "TEXT",
}

#: SLURM states from which a job never leaves. Anything else may still change.
TERMINAL = frozenset({
    "COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY",
    "NODE_FAIL", "BOOT_FAIL", "DEADLINE", "REVOKED", "PREEMPTED",
})

STATE_DIRNAME = ".unity_state"


def state_dir(project_dir: Path) -> Path:
    return Path(project_dir) / STATE_DIRNAME


def db_path(project_dir: Path, campaign: str) -> Path:
    return state_dir(project_dir) / f"{campaign}.db"


def campaigns(project_dir: Path) -> list[str]:
    """Campaign names for this project, newest-written first."""
    d = state_dir(project_dir)
    if not d.is_dir():
        return []
    dbs = sorted(d.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.stem for p in dbs]


def latest_campaign(project_dir: Path) -> str | None:
    names = campaigns(project_dir)
    return names[0] if names else None


def _connect(path: Path, create: bool) -> sqlite3.Connection | None:
    if not create and not path.exists():
        return None
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    if create:
        con.execute(SCHEMA)
    return con


def _upgrade(con: sqlite3.Connection) -> None:
    """Add any column an older plugin version did not write. Idempotent."""
    try:
        have = {r[1] for r in con.execute("PRAGMA table_info(jobs)")}
    except sqlite3.Error:
        return
    if not have:
        return
    for column, decl in _COLUMNS.items():
        if column not in have:
            try:
                con.execute(f"ALTER TABLE jobs ADD COLUMN {column} {decl}")
            except sqlite3.Error:
                pass


def record(project_dir: Path, campaign: str, job_id: str, exp: str,
           partition: str = "", submitted_utc: str | None = None) -> None:
    """Register a freshly submitted job. Idempotent on job_id."""
    stamp = submitted_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    con = _connect(db_path(project_dir, campaign), create=True)
    assert con is not None
    try:
        _upgrade(con)
        with con:
            con.execute(
                "INSERT INTO jobs (job_id, exp, partition, status, attempt, "
                "submitted_utc, updated_utc) VALUES (?,?,?,'PENDING',1,?,?) "
                "ON CONFLICT(job_id) DO UPDATE SET exp=excluded.exp, "
                "partition=excluded.partition",
                (str(job_id), exp, partition, stamp, stamp),
            )
    finally:
        con.close()


def jobs(project_dir: Path, campaign: str | None = None, *, include_hidden: bool = True) -> list[dict]:
    """Rows for one campaign (default: the newest). Empty on any failure."""
    name = campaign or latest_campaign(project_dir)
    if name is None:
        return []
    con = _connect(db_path(project_dir, name), create=False)
    if con is None:
        return []
    blank: dict = {"job_id": None} | {k: None for k in _COLUMNS}
    try:
        # Normalised to the full column set: a ledger written by an older
        # version is missing columns the readers index by name, and a KeyError
        # there would blind every management tool.
        query = "SELECT * FROM jobs ORDER BY rowid"
        if not include_hidden and con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='controller_hidden_jobs'"
        ).fetchone():
            query = "SELECT * FROM jobs WHERE job_id NOT IN (SELECT job_id FROM controller_hidden_jobs) ORDER BY rowid"
        return [blank | dict(r) for r in con.execute(query)]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def forget(project_dir: Path, campaign: str, job_ids: list[str]) -> int:
    """Hide selected monitor rows while retaining their scheduler receipts.

    A missing id removes nothing. This does not cancel the scheduler job and
    does not delete remote files. Execution and management readers keep all rows.
    """
    ids = list(dict.fromkeys(str(job_id) for job_id in job_ids if str(job_id)))
    if not ids or campaign not in campaigns(project_dir):
        return 0
    con = _connect(db_path(project_dir, campaign), create=False)
    if con is None:
        return 0
    marks = ",".join("?" for _ in ids)
    try:
        with con:
            con.execute("CREATE TABLE IF NOT EXISTS controller_hidden_jobs (job_id TEXT PRIMARY KEY, hidden_utc TEXT NOT NULL)")
            cursor = con.execute(
                "INSERT OR IGNORE INTO controller_hidden_jobs(job_id, hidden_utc) "
                f"SELECT job_id, datetime('now') FROM jobs WHERE job_id IN ({marks})", ids,
            )
            return int(cursor.rowcount)
    finally:
        con.close()


def all_job_ids(project_dir: Path) -> list[str]:
    """Every job id this project has submitted, across all campaigns."""
    ids: list[str] = []
    for name in campaigns(project_dir):
        ids += [r["job_id"] for r in jobs(project_dir, name)]
    return [j for j in dict.fromkeys(ids) if j]


def apply_states(project_dir: Path, campaign: str, states: dict[str, dict]) -> int:
    """Fold observed states into the ledger. Returns the number of rows changed.

    `states` maps job_id -> {state, hardware?, elapsed_s?}. A terminal state is
    never overwritten by a later non-terminal observation: SLURM's accounting
    is the truth and the job cannot un-finish.
    """
    if not states:
        # Nothing observed means nothing to write. Returning before opening for
        # write matters: the schema upgrade below rewrites the file, and these
        # ledgers are read by tools users think of as read-only -- one project
        # keeps them in git and saw five tracked files turn modified just from
        # listing its jobs. Migrate when there is data to store, not before.
        return 0
    con = _connect(db_path(project_dir, campaign), create=False)
    if con is None:
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    changed = 0
    try:
        _upgrade(con)
        current = {r["job_id"]: r["status"] for r in
                   con.execute("SELECT job_id, status FROM jobs")}
        with con:
            for job_id, obs in states.items():
                job_id = str(job_id)
                if job_id not in current:
                    continue
                if current[job_id] in TERMINAL:
                    continue
                new_state = (obs.get("state") or "").strip()
                if not new_state or new_state == current[job_id]:
                    continue
                con.execute(
                    "UPDATE jobs SET status=?, hardware=COALESCE(?, hardware), "
                    "elapsed_s=COALESCE(?, elapsed_s), updated_utc=? WHERE job_id=?",
                    (new_state, obs.get("hardware"), obs.get("elapsed_s"),
                     stamp, job_id),
                )
                changed += 1
    except sqlite3.Error:
        return changed
    finally:
        con.close()
    return changed


def refresh_from_telemetry(project_dir: Path, campaign: str | None = None) -> int:
    """Update non-terminal rows from the shared telemetry store.

    Purely local — no SSH, no network — so management tools stay instant and
    work offline. Jobs the collector has not reached yet keep their recorded
    state; `run.sh status` is the live path.
    """
    name = campaign or latest_campaign(project_dir)
    if name is None:
        return 0
    pending = [r["job_id"] for r in jobs(project_dir, name)
               if r["status"] not in TERMINAL]
    if not pending:
        return 0
    try:
        from lib import queries
        rows = queries.task_runs_for_jobs(pending)
    except Exception:
        return 0
    observed = {
        r["job_id"]: {"state": r.get("state"), "hardware": r.get("hardware"),
                      "elapsed_s": r.get("elapsed_s")}
        for r in rows
    }
    if not observed:
        return 0
    return apply_states(project_dir, name, observed)


def parse_sbatch_output(text: str) -> str | None:
    """Pull the job id out of sbatch's reply.

    Handles the default `Submitted batch job 12345` and the `;`-suffixed form
    some sites emit. Returns None when sbatch said something else entirely —
    the caller must treat that as "not submitted", never as job id "".
    """
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("Submitted batch job"):
            tail = line.split()[3] if len(line.split()) > 3 else ""
            tail = tail.split(";")[0].strip()
            if tail.isdigit():
                return tail
    return None


def parse_sacct(text: str) -> dict[str, dict]:
    """Parse `sacct -X -P -n -o JobID,State,Partition,Elapsed` output.

    Array elements (`123_4`) fold onto their base id so a ledger row recorded
    from a single sbatch still matches. `CANCELLED by <uid>` normalises to
    `CANCELLED`, as everywhere else in this codebase.
    """
    out: dict[str, dict] = {}
    for line in (text or "").splitlines():
        parts = line.strip().split("|")
        if len(parts) < 2 or not parts[0]:
            continue
        job_id = parts[0].split(".")[0].split("_")[0]
        if not job_id.isdigit():
            continue
        state = parts[1].strip()
        if state.startswith("CANCELLED by"):
            state = "CANCELLED"
        rec: dict = {"state": state}
        if len(parts) > 2 and parts[2].strip():
            rec["hardware"] = parts[2].strip()
        if len(parts) > 3 and parts[3].strip():
            rec["elapsed_s"] = _elapsed_seconds(parts[3].strip())
        out[job_id] = rec
    return out


def _elapsed_seconds(value: str) -> float | None:
    """SLURM elapsed (`[DD-]HH:MM:SS`) to seconds."""
    days = 0
    if "-" in value:
        d, _, value = value.partition("-")
        if not d.isdigit():
            return None
        days = int(d)
    parts = value.split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    while len(nums) < 3:
        nums.insert(0, 0.0)
    return days * 86400 + nums[0] * 3600 + nums[1] * 60 + nums[2]


# ─── CLI (used by the generated run.sh only for `status`; see run.sh header) ──

def _main(argv: list[str]) -> int:  # pragma: no cover - thin CLI shim
    if len(argv) < 3:
        print("usage: campaign.py <record|jobs|ids> <project_dir> [...]",
              file=sys.stderr)
        return 2
    mode, project = argv[1], Path(argv[2])
    if mode == "ids":
        print("\n".join(all_job_ids(project)))
    elif mode == "jobs":
        for r in jobs(project, argv[3] if len(argv) > 3 else None):
            print(f"{r['job_id']}\t{r['exp']}\t{r['partition']}\t{r['status']}")
    elif mode == "record":
        record(project, argv[3], argv[4], argv[5],
               argv[6] if len(argv) > 6 else "")
    else:
        print(f"unknown mode {mode}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
