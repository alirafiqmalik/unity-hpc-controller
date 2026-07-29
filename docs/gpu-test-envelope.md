# GPU testing envelope

Supersedes the earlier CPU-only rule for plugin testing. GPU paths are a
first-class part of this plugin and were previously unverified end-to-end: no
test job had ever been allocated a GPU, so `--gres` rendering, the gpu/ml job
templates' on-node behaviour, and GPU telemetry attribution were all assumed
rather than observed.

Unity is shared infrastructure. Being allowed to take a GPU is not a reason to
take a good one, or to hold it a second longer than the test needs.

## Permitted for plugin testing

| | Limit |
|---|---|
| GPUs per job | **1** |
| Preferred card | the **least contended** type available — `m40`, `titan_x`, `rtx_8000`, `l4`. Never `h100`/`h200`/`a100`/`l40s` unless the test is specifically about typed requests, and then for one short job only |
| Partition | `gpu-preempt` by default (yields to real work); `gpu` only when testing partition selection itself |
| Walltime | ≤ **00:05:00**, and the job should finish in seconds |
| CPUs / RAM | ≤ 2 CPUs, ≤ 8G |
| Workload | `nvidia-smi` queries and trivial shell only. **No** model downloads, no dataset reads, no training, no long-running CUDA kernels |
| Concurrency | at most **one** GPU test job in flight at a time |

## Required around every GPU test

- Wrap all SSH in `timeout`; never run compute on the login node.
- Record the job id **before** anything else, so it can always be cancelled.
- Verify from the cluster (`sacct`/`scontrol`), never from local stdout alone —
  a stale dispatcher once printed the right thing while the cluster ran 64G/gpu.
- `scancel` immediately on any anomaly, and check `squeue -u $USER` is empty at
  the end of every session.
- If a job is still PENDING after ~5 minutes, cancel it rather than let it sit
  in a queue holding a reservation for a test.

## Still out of bounds

- Multi-GPU (`--gres=gpu:2+`) and multi-node/`torchrun` **execution**. Render
  and inspect these; do not allocate them. A distributed test job that hangs
  holds several nodes.
- Any job whose command is a real project workload. Test jobs always override
  `JOB_COMMAND` with something trivial.
- Deliberately triggering preemption or OOM on a GPU node.

## Rationale

The point of a GPU test is to prove the *plumbing* — allocation, template
execution, ledger, telemetry attribution — not to exercise the GPU. A job that
runs `nvidia-smi` and exits proves everything the plugin is responsible for.
