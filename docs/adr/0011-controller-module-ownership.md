# One owner module for each controller concept

Accepted on 2026-11-12 for `feat/new-approach-refinement`.
This decision keeps ADR 0009's contract and ADRs 0003–0007's telemetry rules.
It records which module inside the controller owns each concept, and the choices that a later reader would otherwise have to rediscover.

Before this change, one concept was spread over several files.
The twelve task states were string literals written at seventeen sites.
Thirteen of seventeen journal write statements sat outside the journal module.
Eight files restated parts of the `summaries.db` schema.
SSH options were built in five places.
Each concept now has one module with a small interface, and tests cross that interface.

## Decisions

**Lifecycle.** `controller/campaign_lifecycle.py` owns the task, attempt, and campaign states, the retry rule, the backoff, and the Result event payloads.
It does no IO and reads no clock; the Worker passes the time in.
The journal refuses a task state that this module does not name.

**Campaign journal.** `controller/campaign_store.py` is the only code that opens `campaigns.db`.
Callers use operations named for what the Worker means, and each operation is one transaction.
Schema setup and the version 1 migration run once for each process and database path.
A read uses a snapshot on a `query_only` connection and never takes the write lock.
A read-only URI connection was rejected: it fails on a database that does not exist yet, and it needs the path quoted as a URI.
Only one listing runs at a time, because each listing decodes every frozen declaration.

**Worker pass.** A failure while the Worker handles one campaign stays with that campaign.
The campaign's `error` starts with the step that failed (`reconcile`, `placement`, `stage`, or `admission`) and clears when that step next succeeds.
The journal has no column for the step, so the text carries it.
The campaign lock is still held for a full pass.
Releasing it during a remote call was examined for every step and rejected: each step decides from records read under the lock, so a cancel request between the read and the write could make the Worker submit or retry a task that was just cancelled.
Accepting a campaign and cancelling one therefore wait for the pass to end; reads do not.

**Hardware class and Attestation.** `controller/hardware_class.py` owns the fingerprint, the stored lock text, the conflict rule, and the controller check of retrieved evidence.
The in-job check is an ordinary file, `controller/attestation.py`, that holds the one match rule and the evidence file names.
Each job script carries that file's text, so nothing is installed on the cluster, and the controller imports the rule from the same file.
The file must stay valid for Python 3.7 and import only the standard library.
The controller check now also compares a declared GPU UUID; the in-job check already refused a mismatch before it wrote `verified`.
Keeping two copies of the rule with a parity test was rejected, because the two copies had already drifted.

**Cluster access.** `controller/cluster_access.py` owns the SSH option set, alias and identity handling, the agent environment, remote commands, and file transfer.
It has two adapters: SSH and rsync in production, a local shell in tests.
The command lines did not change by one byte, and tests pin them.
The callers deliberately keep their different option order around `-i` and their different environments: unifying them needs a check against the live cluster, which this change did not have.
The identity status is read with local tool calls only (four when the key is loaded in the agent) and is not cached, so it cannot report a stale unlocked state.

**Telemetry archive.** `lib/telemetry_archive.py` owns the `summaries.db` schema and its `ensure` step, the dated tables, the per-day backup content and prune, the profile rebuild, and the production read queries.
`cluster-intel/rollup.py` keeps its upserts next to its computation and is the one other writer.
Moving the upserts was rejected: it would split one function for no gain, on code that rewrites a multi-gigabyte archive each run.
The Planner reads wait history by the canonical GPU name, the spelling that the archive stores.

**Catalog.** `controller/catalog.py` owns the survey parsing, the stored `backend-catalog.json`, the freshness decision, and the refresh schedule.
A plan request reads the Catalog once. A pass reads it at most once, at its first placement, and keeps that copy, also when the stored document is not a Catalog.
An `observed_at` that is absent or malformed counts as stale.

## Not done

- Slurm text parsers were not merged. After these moves each format has one parser in the controller; the collector's parsers run on the cluster and follow different rules.
- The `/api/v1/cluster*` routes, `controller/snapshot.py`, and `lib/cluster_config.py` were left as they are. A client outside this repository can use those routes, so their removal is an owner decision.
- The sync pipeline keeps its order and its lock in the shell script (ADR 0003).

## Consequences

- A change to a state, a journal statement, an SSH option, the archive schema, or the Catalog shape has one place.
- Tests use the module interfaces: a transition table for the lifecycle, journal operations on a temporary directory, a local-shell transport for the Slurm protocol, golden dumps for rollup.
- The test suite does not touch the developer's SSH agent or keyring.
- Every journal operation that writes a task state, the submission intent included, refuses a state that the lifecycle does not name.
- `GET /api/v1/campaigns/{id}` shows a step-prefixed `error` for a campaign that the Worker could not advance.
- A new hardware field or a new in-job check is an edit to `controller/attestation.py`, and it changes the text that every later job carries.
