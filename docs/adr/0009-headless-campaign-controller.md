# Headless campaigns replace registered project workspaces

Accepted on 2026-10-05 for `feat/new-approach-refinement`.
This decision supersedes ADR 0001's project ledger ownership and ADR 0008's workspace workflow for new backend use.
ADRs 0003–0007 still govern the existing telemetry archive.

The controller accepts portable task bundles through `/api/v1/campaigns`.
Each task declares an argument vector, resources, required output files, and optional dependencies.
The source project owns scientific methods and evaluations.
Only its runner directory translates portable experiments into a controller request.
The controller never interprets evaluation scores or imports the project package.

The controller owns source snapshots, remote staging, SQLite state, submission receipts, retries, and result retrieval.
Its data directory replaces per-project `unityHPC/run.sh`, `.unity_state`, and `.unity-workspace` as the source of execution state.
Campaign identity now names a durable execution object.
Historical campaign labels retain their previous meaning in the compatibility interface.

The controller records a submission intent before SSH.
A unique job name identifies each attempt.
A remote `flock` protects the submission receipt.
After a restart, the controller reconciles the intent with Slurm before any further submission.
A missing receipt does not prove rejection.
Uncertain attempts remain fenced until Slurm supplies evidence.

Automatic retries apply only to declared infrastructure states: `NODE_FAIL`, `PREEMPTED`, and `BOOT_FAIL`.
Retries preserve the task output directory and hardware request.
The retry budget persists in SQLite.
Application failures require a new campaign.
Artifact transfer retries do not repeat compute.

A model class has one durable hardware fingerprint across campaigns.
The fingerprint includes typed GPU GRES, count, exact device name, expected memory, features, and optional node or UUID restrictions.
The job checks the device before scientific work starts.
The controller checks the returned device evidence before it marks outputs complete.
The first accepted result also binds the reported device name and memory.
A new hardware regime requires a new explicit class identity.

The planner checks live catalog age, partition access, features, capacity, walltime, and known account or QOS limits.
Historical wait percentiles rank compatible partitions.
They do not guarantee start times or justify delayed submission.
Slurm retains scheduling authority.
Unknown telemetry remains unknown.

Global task and GPU ceilings are current service policy.
They apply across campaigns on each scheduling pass.
Execution paths, account settings, and campaign concurrency remain frozen with the accepted declaration.
CPU tasks can use additional task slots without raising the GPU ceiling.
Lower ceilings fence new admissions and preserve accepted jobs.

The controller starts without Node or a dashboard build.
Project registration routes answer HTTP 410.
On 2026-10-08 the repository dropped the compatibility mode: the project registry, workspace modules, scaffold templates, agent personas, dashboards, and their tests were removed.
Existing data directories keep their old files; the controller reads only the campaign journal and the telemetry archive.

The interface and operator procedure are in [backend-campaigns.md](../backend-campaigns.md).
The live evidence is in [unity-backend-capabilities.md](../research/unity-backend-capabilities.md).
