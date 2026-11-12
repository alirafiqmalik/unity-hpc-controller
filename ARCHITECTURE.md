# Headless campaign architecture

Version 0.16.3. The controller owns all cluster execution.
Projects provide portable argument vectors, source bundles, and scientific output declarations.
Runner adapters translate experiment definitions into this contract.

## Ownership

A project owns dataset selection, models, prompts, generation, evaluators, and result schemas.
A runner owns deployment configuration and the translation to campaign JSON.
The controller owns its task journal, source snapshots, hardware locks, placement, attempts, and artifact retrieval.
Slurm owns allocation, priority, backfill, and preemption.

The current contract supersedes the project dispatcher ownership described in ADRs 0001 and 0008.
[ADR 0009](docs/adr/0009-headless-campaign-controller.md) records the migration; the old contracts were removed.

## Execution flow

1. A runner produces a source bundle and campaign JSON from experiment YAML.
2. Read-only planning checks source identity, dependencies, compatible nodes, access rules, and resource ceilings.
3. Acceptance snapshots the source and commits campaign tasks and hardware locks to controller-owned SQLite.
4. The worker uploads the snapshot and persists a submission intention before calling Slurm.
5. A unique attempt name supports reconciliation after an interrupted or uncertain SSH response.
6. Compute-node attestation checks exact GPU identity before the scientific command runs.
7. The worker observes scheduler state and retrieves declared outputs and controller diagnostics.
8. Result events and artifact identities become available to clients through durable cursors.

Scheduler completion and scientific completion remain separate facts.
Missing required outputs prevent successful task completion.
An uncertain submit never causes a blind duplicate submission.
Retries preserve output identity and remain within the declared budget.

## Task lifecycle

`controller/campaign_lifecycle.py` owns the task, attempt, and campaign states and every transition between them.
It performs no IO and reads no clock; the worker passes the time in.
Given a task record and one input (a submission receipt, a scheduler observation, a retrieval outcome, dependency states, or a cancel request), it returns the next state, the fields to record, and the Result event payload.
The worker performs the remote effects, and the journal records the fields.
The journal refuses a task state that the lifecycle does not name.

Task states: `waiting`; the active states `submitting`, `uncertain`, `accepted`, `running`, `fetching`, `cancelling`; and the terminal states `completed`, `failed`, `rejected`, `cancelled`, `blocked`.
Campaign states: `accepted`, `running`, `cancelling`, and the terminal states `completed`, `failed`, `cancelled`.
An attempt records its task's state.
When `NODE_FAIL`, `PREEMPTED`, or `BOOT_FAIL` sends a task back to `waiting`, the finished attempt keeps that scheduler state, also if the task is then cancelled or blocked.

## Data

`$UNITY_HPC_DATA/controller/campaigns.db` is the campaign journal: campaigns, tasks, attempts, hardware locks, and result events.
`controller/campaign_store.py` is the only code that opens it. Callers use its named operations, and each operation is one SQLite transaction, so a reader sees a transition whole or not at all.
Writes take `BEGIN IMMEDIATE`. Reads use a snapshot on a `query_only` connection and never take the write lock, so a long listing does not delay the worker, a campaign read, or a result read.
Only one listing runs at a time, to bound memory; a second listing waits for the first.
Schema setup and the version 1 migration run once for each process and database path.
Campaign directories hold immutable bundles, scripts, receipts, and retrieved artifacts.
`backend-catalog.json` records live hardware and policy observations with timestamps.
`summaries.db` retains collected job and resource history.

The `task_run` table keeps its established shape for existing archives.
The richer `task_accounting` table retains user/account, nodes, job metadata, requests, allocations, job steps, and provenance.
Readers use read-only SQLite connections. Unknown measurements remain absent or null.
Slurm GPU high-water marks do not become time-weighted utilization percentages.

## Interfaces

The HTTP contract lives in [backend operations](docs/backend-campaigns.md).
CLI and MCP clients cross that same interface; neither submits directly to Slurm.
The service starts without UI dependencies.
Project registration routes answer HTTP 410.

## Scheduling limits

The planner permits only nodes that satisfy the fixed hardware class and resource request.
It observes partition access, account/QOS policy, walltime ceilings, and configured concurrency.
It ranks compatible queues using measured historical waits with stated uncertainty.
Source and result storage remain independent of UI state and agent lifetimes.

Accounting retention and data visibility depend on the live cluster configuration.
The controller archives its collected evidence locally and never assumes an unverified history window.
See [the capability assessment](docs/research/unity-backend-capabilities.md) for verified observations.
