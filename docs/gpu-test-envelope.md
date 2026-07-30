# GPU testing envelope

This document replaces the earlier CPU-only rule for plugin testing.

GPU paths matter as much as CPU paths in this plugin, and no test verified them
end-to-end. No test job had ever held a GPU.

Three things were therefore assumed rather than observed: `--gres` rendering, the
on-node behavior of the gpu and ml job templates, and GPU telemetry attribution.

Unity is shared infrastructure. Permission to take a GPU is not a reason to take a
good one. It is also not a reason to hold one a second longer than the test needs.

## Permitted for plugin testing

| | Limit |
|---|---|
| GPUs per job | **1** |
| Preferred card | the **least contended** type available: `m40`, `titan_x`, `rtx_8000`, `l4`. Never `h100`, `h200`, `a100` or `l40s`, unless the test is about typed requests, and then for one short job only |
| Partition | `gpu-preempt` by default, because it yields to real work. Use `gpu` only to test partition selection itself |
| Walltime | **00:05:00** or less, and the job must finish in seconds |
| CPUs / RAM | 2 CPUs or fewer, 8G or less |
| Workload | `nvidia-smi` queries and trivial shell only. **No** model downloads, no dataset reads, no training, no long-running CUDA kernels |
| Concurrency | at most **one** GPU test job in flight |

## Required around every GPU test

1. Wrap every SSH call in `timeout`. Never run compute on the login node.
2. Record the job id **first**, so that you can always cancel the job.
3. Check the result from the cluster with `sacct` or `scontrol`, never from local
   stdout alone. A stale dispatcher once printed the right thing while the cluster
   ran 64G per GPU.
4. On any anomaly, run `scancel` at once.
5. At the end of every session, check that `squeue -u $USER` is empty.
6. If a job is still PENDING after about 5 minutes, cancel it. Do not let a test
   job hold a reservation in a queue.

## Still out of bounds

- Do not **run** a multi-GPU (`--gres=gpu:2+`), multi-node, or `torchrun` job.
  Render these and read them. Do not allocate them. A distributed test job that
  hangs holds several nodes.
- Any job whose command is a real project workload. A test job always overrides
  `JOB_COMMAND` with something trivial.
- Deliberate preemption or a deliberate out-of-memory error on a GPU node.

## Rationale

A GPU test proves the *plumbing*: allocation, template execution, the ledger, and
telemetry attribution. It does not exercise the GPU.

A job that runs `nvidia-smi` and exits proves everything that the plugin is
responsible for.
