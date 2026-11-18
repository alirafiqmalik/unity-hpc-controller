# Retire the cluster dashboard routes and the code no client uses

Accepted on 2026-11-18 for `feat/new-approach-refinement`.
This decision completes the "Not done" list of ADR 0011.

ADR 0011 kept `/api/v1/cluster`, `/api/v1/cluster/queue`, `/api/v1/cluster/usage`, and `controller/snapshot.py`, because a client outside this repository could use them.
The owner decided to remove them.
No client in this repository calls these routes: the CLI, the MCP server, and the Worker use the campaign and telemetry routes.
The routes served the retired dashboard (ADRs 0002 and 0006).

## Decisions

**Cluster routes.** The three routes and every path below `/api/v1/cluster/` answer HTTP 410 with the names of the current routes, as the retired project registration routes do.
A 410 tells an old client that the route was removed, where a 404 could look like a wrong address.
`controller/snapshot.py` is deleted.
The Planner and the Catalog give the placement facts (`POST /api/v1/campaigns/plan`), and `GET /api/v1/telemetry` gives the archive state.

**Code that only the routes used.** `cluster-intel/backfill_usage.py` and `scripts/hpc-backfill-usage` filled `historical_usage.db`, which only `snapshot.py` read. They are deleted.
Data files are not deleted: `historical_usage.db` and `cluster-config.json` stay in the data directory until the owner removes them.

**Scripts that nothing starts.** `scripts/hpc-retention-gate` and `scripts/hpc-config-write` are deleted, with the functions that only they used (`retention.parse_deletions`, `retention.retention_decision`, `cluster_config.should_probe`).
The remote prune keeps its own fully-summarised check (ADR 0007).
`lib/cluster_config.py` stays, because rollup, the Planner, and `cluster-intel/migrate.py` use it.

**Project runtime helper.** `controller/node_runtime.py` and `controller/runtime_integrity.py` moved to `examples/allocation-local-runtime/`.
They stage one project's Lean runtime on a compute node, and the controller never imported them.
ADR 0010 puts executable examples in `examples/`, outside the runtime implementation.

## Consequences

- The HTTP contract loses three read routes. A client that used them gets a 410 with the current routes.
- `controller/` holds only controller code.
- A project that bundled the runtime helper copies it from `examples/allocation-local-runtime/` and pins its own copy.
- Plugin version 0.19.0.
