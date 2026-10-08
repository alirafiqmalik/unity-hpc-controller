# Unity HPC

A headless controller between a project and Unity Slurm. It snapshots a source
bundle, places tasks on exact hardware, submits, reconciles, retries within a
budget, and retrieves declared outputs. It does not know what a project's
metrics mean.

## Language

**Campaign**:
A declared collection of tasks whose source bundle, configuration, attempts, and results share one durable identity.
The controller preserves this identity across restart and collection.
Resending an identical declaration returns the existing campaign.
_Avoid_: run, sweep, group, job

**Task**:
One declared scientific command, its resource request, dependencies, and required output files.
Retries preserve the task's identity and output directory.
_Avoid_: experiment, unit, step

**Attempt**:
One submission intention and its scheduler outcome for a task.
An uncertain attempt cannot establish that no job exists.
_Avoid_: retry, try, submission

**Experiment bundle**:
An immutable snapshot of portable scientific code, configuration, and selected input data.
The controller records its digest before execution.
_Avoid_: repo, checkout, source tree

**Runner**:
The one project directory that translates experiment YAML into a campaign declaration and collects declared results.
It is project-owned code. It never talks to Slurm.
_Avoid_: dispatcher, scaffold, adapter script

**Declaration**:
The campaign JSON a runner produces: bundle identity, tasks, resources, dependencies, and required outputs.
_Avoid_: spec, manifest, config

**Model class**:
A scientific comparison group locked to one GPU model, memory size, device count, and required node features.
The lock persists across campaigns. A new hardware regime needs a new class identity.
_Avoid_: hardware profile, GPU type (that is only one field of the class)

**Hardware class / fingerprint**:
The typed GRES, count, exact device name, expected memory, features, and optional node or UUID restrictions bound to a model class.
_Avoid_: partition, queue

**Attestation**:
The in-job record of the assigned GPU UUIDs, device name, reported memory, node, and driver, taken before the scientific command runs.
_Avoid_: probe, check

**Catalog**:
The controller's timestamped record of live nodes, partitions, access rules, QOS limits, and fairshare.
A stale catalog blocks new submissions.
_Avoid_: profile, recon, cluster config

**Planner**:
The read-only check of a declaration against the catalog: hardware fit, access, ceilings, and ranked compatible partitions.
A plan never submits.
_Avoid_: scheduler (that is Slurm), dry run

**Worker**:
The controller thread that stages bundles, records submission intent, calls Slurm, observes state, retries infrastructure failures, and retrieves outputs.
_Avoid_: daemon, agent, watcher

**Result event**:
One durable, cursor-addressed record of a task state change or retrieved artifact.
Clients resume from `next_cursor` without duplicates.
_Avoid_: notification, message

**Controller**:
The always-on local process that owns the campaign journal, hardware locks, scheduling requests, attempts, and result retrieval.
_Avoid_: daemon, monitor, MCP server, plugin

**Cluster session**:
A tmux session on the login node that the controller opens to run one scheduled telemetry sample.
It closes after a quiet period. It is not a resident collector.
_Avoid_: collector, daemon

**Telemetry archive**:
The local `summaries.db`, enriched accounting records, and raw sampled days under `$UNITY_HPC_DATA`.
Allocation counts in it are not time-weighted utilization.
_Avoid_: dashboard data, usage database

**Hardware**:
A device class recorded on a finished task (`cpu`, `a100`, `gpu:unspecified`).
It is not a partition.
_Avoid_: queue, backend

**Plugin**:
The LLM-facing skills and MCP tools. Every tool is an HTTP client of the controller.
_Avoid_: agent, marketplace plugin, dispatcher

## Retired terms

These terms named the project-side design that ADR 0009 replaced. Do not reintroduce them:
primitive, `ml` type, attached project, scaffold, `unityHPC/run.sh`, ledger, watcher, bootstrap hook,
reviewed plan, execution, purpose, analysis revision, workspace, dashboard.
