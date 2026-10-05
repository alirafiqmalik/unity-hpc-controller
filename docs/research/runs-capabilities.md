# Runs and queue capability research

Research date: 2026-10-03. Scope: repository inspection and official Slurm documentation. No cluster commands ran.

This report supports the [Runs specification](../design/runs-spec.md). New product choices are agent-selected.
The source tree contains concurrent implementation changes. Presence in this tree does not establish released or tested behavior.

## Existing evidence

The prior [workspace research](project-workspace-tools.md) separates future eligibility, pending updates, running limits, and replacement.
The [connection research](project-connection-harness.md) identifies ambiguous submission, dependent stages, and complete corpora behind failed jobs.
Those distinctions remain binding inputs to the design.

| Area | Observed implementation | Required extension |
| --- | --- | --- |
| Ownership | `controller/dispatch.py` calls the attached `unityHPC/run.sh`. ADR 0001 preserves ledger ownership. | Keep management commands behind this boundary. |
| HTTP | `controller/http.py` provides generic runs, cancel, status, and fetch routes. | Workspace management reviews, schedules, attempt logs, and per-target operation outcomes. |
| Monitoring | `JobsMonitorPage.tsx` lists ledger jobs with filters, runtime, purpose, and state. `JobPanel.tsx` links execution identity. | Execution aggregation, dependencies, application progress, and observed freshness per source. |
| Status | `run.sh status` calls `sacct`, then updates the ledger. On lookup failure it prints cached rows and returns success. | Structured observation failure distinct from command success. |
| Cancellation | The ledger finds live rows by campaign and optional parent job ID. `cmd_cancel` sends parent IDs and immediately marks rows cancelled. | Exact target resolution, scope review, and cancellation acknowledgement distinct from observed termination. |
| Array child | A child ID passed as `--job` does not match the parent filter. Parent scope cancels the group. | An exact-task adapter with demonstrated scheduler semantics. Never map a selected child silently to its parent. |
| Logs | `cmd_logs` tails stdout and stderr for the newest campaign job only. No dedicated attempt-log HTTP route appears in the inspected handler. | Stable stream identity, attempt selection, bounded offsets, rotation detection, and historical retrieval. |
| Fetch | Controller fetch returns scheduler logs and optional project-owned hook outcomes separately. The hook uses a bounded process group. | Declared artifact scope and per-artifact progress. Existing campaign fetch is not exact-artifact retrieval. |
| Request edits | No `scontrol update` adapter appears in the inspected dispatcher or scaffold. | Capability-specific update commands, preflight, reconciliation, and append-only audit. |
| Submission fallback | The scaffold partition ladder advances only after refused submission. An accepted response without a job ID stops it. | Preserve that ambiguity guard. This feature does not move accepted pending jobs. |
| Schedule | Telemetry settings schedule data retrieval. They do not schedule scientific executions. | Durable one-off execution schedules with frozen plans and missed-window behavior. |
| Recovery | The foreground watcher owns explicit retry budgets under the existing design. | Reviewed workspace recovery without starting or adopting the watcher. |
| Workspace | ADR 0008 and new workspace files define durable plans, attempts, and outputs. | Treat their concurrent implementation as a dependency, not a finished Runs feature. |

Evidence: [dispatcher](../../controller/dispatch.py), [HTTP handler](../../controller/http.py), [scaffold](../../templates/scaffold/common/run.sh),
[monitor](../../controller/web/src/pages/JobsMonitorPage.tsx), [job panel](../../controller/web/src/modules/panels/JobPanel.tsx),
[workspace store](../../controller/workspace_store.py), and [ADR 0008](../adr/0008-project-workspace-and-approved-executions.md).

## Scheduler facts and product implications

Slurm exposes request updates subject to permissions. Increasing a running or suspended job's time limit requires privilege.

Requeue returns a batch job to pending. It does not establish application checkpoint compatibility.
A hold on a running job does not stop it. These facts rule out a generic Pause or Reassign button.
[Official scontrol reference](https://slurm.schedmd.com/scontrol.html)

A begin time establishes earliest eligibility, not a reserved start. A failed dependency remains failed even after its parent later succeeds through requeue.
Requeue starts the batch script again. Recovery therefore needs explicit application semantics and dependent-attempt lineage.
[Official sbatch reference](https://slurm.schedmd.com/sbatch.html)

Backfill considers resource requests and time limits. Accurate shorter walltime can create opportunities, but it never guarantees an earlier start.
The UI must retain the estimate's source and observation time.
[Official scheduling guide](https://slurm.schedmd.com/sched_config.html), [official squeue reference](https://slurm.schedmd.com/squeue.html)

Slurm distinguishes job, array, and task cancellation scopes. Array task behavior needs special care when Slurm has not split a task record.
Exact task cancellation cannot rely on replacing a parent ID with a child-shaped string alone.
[Official scancel reference](https://slurm.schedmd.com/scancel.html)

These sources describe current upstream semantics. Unity permissions, version, and site rules still require a later read-only capability survey.
That survey must not use production job mutation as a capability probe.

## Existing decisions and authority

[ADR 0008](../adr/0008-project-workspace-and-approved-executions.md) explicitly supersedes legacy primitive and sequence restrictions for the workspace API.
The original [design decisions](../design-decisions.md) still prohibit hidden retry during status reads and preserve ledger identities.
Runs adds no change to accepted Q1–Q23. The narrower initial Experiments scope excludes these later management extensions without prohibiting their later delivery.

A mutation that changes the execution request must retain the original approved plan and append its management review.
Historical campaign and job values remain evidence. They do not become execution IDs.
