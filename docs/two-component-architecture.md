# Two-component architecture

How the plugin, the controller, and Unity fit together. The ledger
contract in `ARCHITECTURE.md` still holds: `unityHPC/run.sh` records
every job, and every management tool reads that record.

## The three parties

```
  Cursor / Claude                 this machine                    Unity
 ┌──────────────────┐          ┌──────────────────────────┐     ┌──────────┐
 │ Plugin (3 skills)│   HTTP   │ Controller               │ SSH │ SLURM    │
 │  connect         │─────────▶│  registry  snapshot      │────▶│ sbatch   │
 │  dispatch        │          │  dispatch → run.sh       │     │ sacct    │
 │  doctor          │          │  UI  :8300               │     │ squeue   │
 └──────────────────┘          └────────────┬─────────────┘     └────┬─────┘
                                            │ Tailscale              │
                                            ▼                        │
                                      any tailnet browser            │
                                            ▲                        │
                                            │ telemetry              │
                                            └────────────────────────┘
```

The LLM session holds three short skills. Heavy work — recon, queue
reads, fetch, watch, rollup, the dashboard — lives in the controller,
which stays up independently of any chat.

## Seams

| Seam | Interface | Callers |
|---|---|---|
| Plugin → controller | HTTP `/api/v1/*` | `connect`, `dispatch`, `doctor`, the UI |
| Controller → project | `unityHPC/run.sh` subcommands | dispatch, cancel, fetch, sync, status |
| Dispatcher → Unity | SSH / rsync / sbatch | `run.sh` only |
| Unity → shared tier | collector → `sync-telemetry.sh` → `summaries.db` | snapshot, analytics |

The plugin never crosses the Unity seam. The UI never calls `run.sh`
directly; it POSTs to the same HTTP interface the plugin uses.

## What each side owns

**Controller** (always-on, this machine)

- Project registry at `$UNITY_HPC_DATA/controller/projects.json`
- Cluster snapshot from `cluster-config.json`, `snapshot.csv`, `summaries.db`
- Dispatch, cancel, fetch, sync — by invoking the attached project's `run.sh`
- The dashboard at `:8300`, published over Tailscale by default
- Operator runbooks under `controller/ops/` (the old skill bodies)

**Plugin** (loaded into an LLM session)

- `connect` — scaffold `unityHPC/` if needed, register the directory, write `unityHPC/controller.json`
- `dispatch` — POST a run request
- `doctor` — controller health and this project's wiring

MCP tools remain as a programmatic read/submit path for sessions that
already have them. New agent work goes through the three skills.

**Unity**

- Unchanged. The collector still writes telemetry on the cluster (I1).
  The dispatcher still records the landed partition, not the first
  request.

## Data

```
$UNITY_HPC_DATA
├── cluster-config.json
├── summaries.db
├── snapshot.csv
├── telemetry/
└── controller/
    ├── projects.json      attached projects
    ├── projects.json.lock
    └── events.jsonl       dispatch / attach / cancel (append-only)
```

An attached project still keeps its ledger at
`<project>/.unity_state/<campaign>.db`. The controller reads those files
in place. It does not copy the ledger.

## Why this shape

See `docs/adr/0001-two-component-split.md`. The short form: one HTTP
interface, one ledger writer, no cluster logic in the LLM context.
