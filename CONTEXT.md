# Unity HPC

A blind harness between a project and Unity SLURM. It submits, records, observes
and fetches. It does not know what a project's metrics mean.

## Language

**Primitive**:
A named legal pairing of a resource and an orchestration. The five primitives
are `cpu`, `gpu`, `multi-cpu`, `multi-gpu` and `ml`.
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
Fan-out of independent GPU tasks. Today's `run.sh array` on a GPU resource.
_Avoid_: torchrun, data-parallel (those name a coordinated job)

**ml**:
One coordinated GPU job. Today's `ml` template. Ranks share one allocation and
exchange messages.
_Avoid_: training, workload, multi-gpu (that name is the fan-out case)

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
