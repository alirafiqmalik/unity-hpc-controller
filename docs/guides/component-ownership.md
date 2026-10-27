# Plugin and controller responsibilities

The controller uses the headless campaign contract in [ADR 0009](../adr/0009-headless-campaign-controller.md).
The plugin provides HTTP clients and skills.
The controller owns cluster execution and continues after the agent exits.

| Component | Owns | Interface |
|---|---|---|
| Evaluation project | Experiment YAML, datasets, models, scientific checks, result schemas | Portable task commands and result files |
| Project runner | Hardware environment and campaign translation | Immutable bundle and campaign JSON |
| Plugin | Preparation, submission, health, and incremental result tools | Controller HTTP API |
| Controller | Source snapshots, placement, attempts, hardware locks, retries, and retrieval | SSH, rsync, and Slurm |
| Slurm | Allocation, priority, backfill, and preemption | Job identities and observations |

The project requires no registered directory, generated dispatcher, or local Unity ledger.
Only its runner directory contains cluster details.
The controller treats the scientific command and its result schema as opaque.
Its completion check verifies declared files and hardware evidence.
The project checks response counts and scientific outcomes.

Campaign state resides under `$UNITY_HPC_DATA/controller/`.
The SQLite journal, source bundles, and retrieved files form a single execution record.
Telemetry remains a separate shared archive under `$UNITY_HPC_DATA`.
The collector records measured resource and accounting evidence.
The planner uses that evidence without replacing Slurm scheduling.

Read [backend operations](../backend-campaigns.md) for the API, settings, and recovery procedure.
Read [architecture](../../ARCHITECTURE.md) for the execution flow and data stores.
