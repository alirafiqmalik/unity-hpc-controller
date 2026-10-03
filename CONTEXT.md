# Unity HPC

A blind harness between a project and Unity SLURM. It submits, records, observes
and fetches. It does not know what a project's metrics mean.

## Language

**Primitive**:
A named legal pairing of a resource and an orchestration. The workspace primitives are `cpu`, `gpu`, `multi-cpu`, and `multi-gpu`.
Legacy CLI configurations also accept `ml`. See ADR 0008.
_Avoid_: type, job type, backend, scaffold type

**Resource**:
The hardware class a job asks for: `cpu` or `gpu`.
_Avoid_: partition, queue

**Orchestration**:
How the work is launched: single, fan-out or coordinated.
_Avoid_: sweep, array

**Fan-out**:
N independent tasks that do not communicate. One group. N ledger rows.
_Avoid_: sweep, parallel, multi

**Coordinated**:
One allocation whose ranks communicate. One job. One ledger row.
_Avoid_: distributed, multi-node

**cpu**:
One CPU job. Single orchestration. One ledger row.
_Avoid_: CPU-only, serial

**gpu**:
One GPU job on one node. Single orchestration. One ledger row. The job may use
more than one GPU on that node.
_Avoid_: single-gpu (that name excludes a one-node multi-GPU job)

**multi-cpu**:
Fan-out of independent CPU tasks. Today's `run.sh array` on a CPU resource.
_Avoid_: MPI, multi-node CPU, ntasks

**multi-gpu**:
GPU work with an explicit execution mode: independent experiments or coordinated ranks.
Legacy configurations without a mode retain independent fan-out behavior.
Variant concurrency and rank counts are separate controls.

**ml**:
An application category in the workspace. Legacy `ml` primitive configurations
map to `multi-gpu` with coordinated mode. Historical values remain unchanged.
The legacy CLI template continues to accept `ml`.

**Hardware**:
A device class on a finished task (`cpu`, `a100`, `gpu:unspecified`). It is not
a primitive and not a partition.
_Avoid_: queue, backend

**Campaign**:
An optional grouping label on ledger rows. Default is today's UTC date. It is
not the fan-out group's identity. One campaign may hold many groups and may mix
primitives. It is the public scope for cancel, fetch and watch.
_Avoid_: run, sweep, group

**Group**:
The tasks from one fan-out submit. Its identity is the parent SLURM job id.
Membership is the ledger rows `<parent>_<index>`.
_Avoid_: campaign, array, sweep

**Task payload**:
An opaque JSON string on a fan-out manifest line, exported as
`UNITY_TASK_PAYLOAD`. The harness never parses it. The leading token remains
`EXP`.
_Avoid_: plan, sidecar, unit config

**Watcher**:
An opt-in foreground process on the user's machine. The user starts it and
stops it. It drives `run.sh` subcommands only. It owns a retry budget. One
watcher per campaign. It is not a login-node daemon.
_Avoid_: monitor, collector, daemon

**Results tree**:
Remote artifacts for one campaign, default `$REMOTE_DIR/_results/<campaign>/`.
Fetch prefers that directory when it exists.
_Avoid_: output, artifacts dir

**Bootstrap hook**:
An optional `unityHPC/bootstrap.sh`. If the file exists, the job template
sources it under one `flock` so concurrent tasks do not race. The harness
does not own a pip convention.
_Avoid_: VENV_BOOTSTRAP, requirements.txt

**Controller**:
The always-on process on this machine. It owns the project registry, the
HTTP interface, the dashboard, and every call to `run.sh`. It is not a
login-node process and not the watcher.
_Avoid_: daemon, monitor, MCP server, plugin

**Cluster session**:
A tmux session on the login node that the controller opens to run one
scheduled sample. It closes after a quiet period. Sample logs are copied
to this machine and the remote `/tmp` files are removed. It is not a
resident collector and not the watcher.
_Avoid_: collector, daemon, unity-collector

**Attached project**:
A local directory registered with the controller. Identity is its slug.
The controller reaches its `unityHPC/run.sh` and its ledger through that
registration.
_Avoid_: repo, workspace, integration

**Dispatch**:
A run request sent to the controller. The controller calls `run.sh`. A
dispatch that does not go through the controller is outside the contract.
_Avoid_: submit (that is `run.sh`'s act), sbatch

**Plugin**:
The three LLM-facing skills (`connect`, `dispatch`, `doctor`). They write
wiring and HTTP to the controller. They do not SSH.
_Avoid_: agent, MCP, marketplace plugin (the install unit is still this
repo; this term is the thin skill catalog)

**Experiment**:
A reusable project-declared study with editable revisions and immutable executions.

**Reviewed plan**:
The checked expansion of one revision: variants, stages, resources, scripts, source, and input identities.
One plan approves at most one execution. Repeat creates another plan with fresh outputs.

**Execution**:
One approved plan and its durable attempts, ledger links, artifacts, and continuation history.
It does not replace a campaign or scheduler job identity.

**Purpose**:
Explicit stage metadata: Experiment or Smoke test. Historical jobs remain Unclassified.
Purpose is separate from scheduler State and never inferred from names.

**Analysis revision**:
A reviewed analysis of selected saved artifacts, with fresh report outputs and preserved input provenance.
