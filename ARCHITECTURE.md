# Headless campaign architecture

Version 0.19.0. The controller owns all cluster execution.
Projects provide portable argument vectors, source bundles, and scientific output declarations.
Runner adapters translate experiment definitions into this contract.

## Ownership

A project owns dataset selection, models, prompts, generation, evaluators, and result schemas.
A runner owns deployment configuration and the translation to campaign JSON.
The controller owns its task journal, source snapshots, hardware locks, placement, attempts, and artifact retrieval.
Slurm owns allocation, priority, backfill, and preemption.

The current contract supersedes the project dispatcher ownership described in ADRs 0001 and 0008.
[ADR 0009](docs/adr/0009-headless-campaign-controller.md) records the migration; the old contracts were removed.
[ADR 0011](docs/adr/0011-controller-module-ownership.md) records which module owns each concept inside the controller.
[ADR 0012](docs/adr/0012-retire-the-cluster-dashboard-routes.md) records the removal of the cluster dashboard routes and of code that no client used.

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
Given a task record and one input (a submission receipt, a scheduler observation, a retrieval outcome, dependency states, or a cancel request), it returns the next state and the fields to record.
The worker performs the remote effects, and the journal records the fields.
The journal publishes the Result event: its payload is the recorded fields, and it is written only when the state, a field, or an actionable part of the scheduler observation changes.
A submission intent's event carries only the attempt number and the job name, and commits with the attempt row and the task state.
The journal refuses a task state that the lifecycle does not name.

Task states: `waiting`; the active states `submitting`, `uncertain`, `accepted`, `running`, `fetching`, `cancelling`; and the terminal states `completed`, `failed`, `rejected`, `cancelled`, `blocked`.
Campaign states: `accepted`, `running`, `cancelling`, and the terminal states `completed`, `failed`, `cancelled`.
An attempt records its task's state.
When `NODE_FAIL`, `PREEMPTED`, or `BOOT_FAIL` sends a task back to `waiting`, the finished attempt keeps that scheduler state, also if the task is then cancelled or blocked.

## Worker pass

`controller/campaigns.py` runs the Worker: one thread that runs one pass at a time.
A pass runs every `poll_seconds`, or at once when the previous pass admitted work and deferred more.
While campaigns need work, a pass first refreshes the Catalog when the Catalog module says a refresh is due (the first pass with work, then 15 minutes after the last attempt); this runs before the campaign lock is taken.
Under the campaign lock it then reconciles every unfinished campaign (observe Slurm, cancel the live jobs of a cancelling campaign, retrieve outputs), and then admits new work (placement, staging, submission intent, submit).
Each step reads the campaign and its tasks in one journal snapshot, without the Result cursor. Reconciliation also reads each attempt's task, number, and job name, to name the diagnostics of earlier attempts; admission reads no attempt rows and skips a campaign that reconciliation finished.
Admission counts the active tasks, CPUs, GPUs, and nodes once per pass, by the QOS each task runs under (its `resources.qos`, else its own campaign's frozen default), and adds each submit outcome that stays active (accepted or uncertain). QOS job and TRES limits count the tasks under the placement's QOS; account job and TRES limits count every active task. After an admission failure the totals are counted again from the journal, because a submission intent can commit before its outcome is recorded. `tests/formal/campaign_worker` model-checks these rules; see `.claude/skills/verify-campaign-worker`.

One clock gives the pass its time.
Wall time is for times that are stored or compared with stored times: `eligible_at` and the catalog age.
Monotonic time is for durations inside the process: the admission budget, staging time, and the catalog refresh schedule.

An exception while the Worker handles one campaign stops the work on that campaign for this pass, not the pass.
The Worker records it as the campaign's `error`, which starts with the step that failed (`reconcile`, `placement`, `stage`, or `admission`), and writes a `campaign-error` line to `events.jsonl` when that error changes.
The error clears when the same step next succeeds for that campaign; a success of another step leaves it.
When the journal cannot record the failure, the pass ends, and the next pass starts again from the journal.
A submission intent whose outcome was not recorded leaves the task `submitting`; the next pass reconciles it by job name and never submits it again.

The campaign lock is held for a full pass because each step decides from journal records read under the lock and records its result under the same lock.
If the lock were released during a remote call, a cancel request could fence a task between the Worker's read and its write, and the Worker would then submit or retry a task that had just been cancelled.
So accepting a new campaign and cancelling one wait for the current pass to end.
Journal reads, listings, results, plans, and an identical resend of an accepted campaign do not wait.

## Hardware class

`controller/hardware_class.py` owns the Hardware class: the fingerprint that a Model class is locked to, the text that the journal stores for the lock and for the bound devices, the rule that a locked class conflicts with a different fingerprint, and the controller check of a retrieved Attestation.
The match rule and the evidence file names live in `controller/attestation.py`, the in-job check.
That file uses only the standard library and imports nothing from this repository.
Each job script carries its text as a here-document on the standard input of `python3`, so nothing is installed on the cluster.
The controller imports the same match rule from that file, so the job and the controller compare devices with one function.
The journal keeps the SQL for hardware locks and asks `hardware_class` for the rule.

## Cluster access

`controller/cluster_access.py` owns how the controller reaches the cluster: the SSH alias and identity checks, the one set of SSH options, the agent that holds the unlocked key (with the desktop keyring and the askpass helper), a bounded remote command, and file transfer with rsync.
A transport offers three operations: run a command line, run a script on the standard input of `bash`, and transfer files to or from the cluster.
The production transport runs `ssh` and `rsync` through the saved alias.
The local-shell transport runs the same command text in local `bash`, treats a remote path as a local path, and transfers with local `rsync`, so tests run the real staging, receipt, cancel, and retrieval protocols without a cluster.

`controller/campaign_slurm.py` keeps the Slurm protocol (stage, submit, observe, collect, cancel, probe) and takes its transport from Cluster access.
`campaigns.slurm_adapter()` gives the Worker, cancellation, and the catalog refresh the adapter for a campaign now: the campaign's frozen backend with the current mail policy.
`controller/cluster_session.py` keeps the tmux protocol of the Cluster session and sends it through the same transport.
`cluster-intel/sync-telemetry.sh` runs the pull; the controller gives it `RSYNC_RSH`, built by Cluster access, and `lib/retention.py` uses that variable for the remote prune.

The callers deliberately keep their own option order and environment (ADR 0011), and tests pin every command line.
The Slurm commands put the options before `-i` and use the agent socket that the alias's `IdentityAgent` names; the Cluster session and the pull put `-i` first and inherit the controller's environment; the settings panel's SSH test sets no keep-alive.
`GET /api/v1/health` reads the identity state with local tool calls only, opens no cluster connection, and caches nothing.
With the key loaded in the agent these are four calls (`ssh -G`, `ssh-add -l`, `ssh-keygen -l`, `busctl`); with no key loaded `ssh-keygen -l` is not needed, and a restore from the desktop keyring adds its own calls.

## Catalog

`controller/catalog.py` owns the Catalog.
It turns the survey output into a Catalog, writes `backend-catalog.json` atomically, reads it, and decides freshness and when a refresh is due.
The survey is the bounded set of Slurm queries that `SlurmAdapter.probe` runs over Cluster access; a test pins its command text.
A Catalog is fresh when its `observed_at` is at most `catalog_max_age_seconds` old at the wall time that the caller passes; an absent, unreadable, or undated Catalog is stale.
The refresh schedule takes monotonic time: the first Worker pass with work refreshes, and then at most one refresh runs each 15 minutes, also after a failure.
A pass reads the Catalog at most once, at its first placement, and checks every task of that pass against that copy; a pass that places nothing does not read it. A plan request reads it once.
The Planner and the Worker ask this module; neither reads the file nor judges age itself.

## Data

`$UNITY_HPC_DATA/controller/campaigns.db` is the campaign journal: campaigns, tasks, attempts, hardware locks, and result events.
`controller/campaign_store.py` is the only code that opens it. Callers use its named operations, and each operation is one SQLite transaction, so a reader sees a transition whole or not at all.
Writes take `BEGIN IMMEDIATE`. Reads use a snapshot on a `query_only` connection and never take the write lock, so a long listing does not delay the worker, a campaign read, or a result read.
Only one listing runs at a time, to bound memory; a second listing waits for the first.
Schema setup and the version 1 migration run once for each process and database path.
Campaign directories hold immutable bundles, scripts, receipts, and retrieved artifacts.
`backend-catalog.json` is the stored Catalog: live hardware and policy observations and their observation time. `controller/catalog.py` is the only code that reads or writes it.
`summaries.db` is the Telemetry archive: collected job and resource history.
`lib/telemetry_archive.py` owns it: the schema and the `ensure` step, which creates missing tables, adds missing `task_run` columns, and writes nothing on a current archive; the five dated tables and how a day's rows are selected, with `task_accounting` rows following their day's `task_run` rows; the content of a per-day summary backup and the prune that local retention uses; the `task_profile` rebuild; and the reads that production uses (the accounting route, the fully-summarised gate of the remote prune, the Planner's wait and runtime history, and the rollup stamp in telemetry status).
`cluster-intel/rollup.py` computes rows from raw days and is the one other writer; its upserts stay next to the computation.
`lib/local_retention.py` owns the backup files, their names, and the copy-and-replace of the live file.
The test-only readers in `lib/queries.py` and the one-time tools `cluster-intel/migrate.py` and `cluster-intel/backfill_hardware.py` keep their own SQL.

The `task_run` table keeps its established shape for existing archives.
The richer `task_accounting` table retains user/account, nodes, job metadata, requests, allocations, job steps, and provenance.
Readers use read-only SQLite connections. Unknown measurements remain absent or null.
Slurm GPU high-water marks do not become time-weighted utilization percentages.

## Interfaces

The HTTP contract lives in [backend operations](docs/backend-campaigns.md).
CLI and MCP clients cross that same interface; neither submits directly to Slurm.
The service starts without UI dependencies.
Project registration routes and the retired cluster dashboard routes (`/api/v1/cluster`, `/api/v1/cluster/queue`, `/api/v1/cluster/usage`) answer HTTP 410 ([ADR 0012](docs/adr/0012-retire-the-cluster-dashboard-routes.md)).

## Scheduling limits

The planner permits only nodes that satisfy the fixed hardware class and resource request.
It observes partition access, account/QOS policy, walltime ceilings, and configured concurrency.
It ranks compatible queues using measured historical waits with stated uncertainty.
It reads that history by partition and the canonical GPU name, the spelling that the archive's `hardware` column holds.
Source and result storage remain independent of UI state and agent lifetimes.

Accounting retention and data visibility depend on the live cluster configuration.
The controller archives its collected evidence locally and never assumes an unverified history window.
See [the capability assessment](docs/research/unity-backend-capabilities.md) for verified observations.
