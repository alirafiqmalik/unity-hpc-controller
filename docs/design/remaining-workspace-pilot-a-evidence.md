# Pilot A site survey and focused project checks

Date: 2026-10-03. The user approved the read-only Pilot A survey and a few project checks.
This record supplements the [live validation plan](remaining-workspace-live-validation.md).

## Site observations

The controller registry attaches `llm-thinking-trace` to the local project at
`the attached research project`.
Its SSH alias is `unity`, its configured host is `unity.rc.umass.edu`, and its remote root is
`/work/pi_taqi_umass_edu/ali/llm_thinking_trace_logic`.

The survey used the controller's bounded, unattended `cluster_session.ssh_run` path.
The site reported the following facts at 10:05–10:07 UTC:

| Fact | Observation |
| --- | --- |
| Access | SSH succeeded as `ahmalik_umass_edu` on `login5.unity.rc.umass.edu`. The registered root exists and is readable and writable. |
| Scheduler | `scontrol version` returned Slurm 25.11.8. |
| Commands | `sbatch`, `squeue`, `sacct`, `scancel`, `scontrol`, `sinfo`, `sacctmgr`, `srun`, and `salloc` exist. The survey only located mutation commands; it did not invoke them. |
| Account | The user's default account and listed association are `pi_taqi_umass_edu`. |
| CPU candidate | `cpu` is up and is the default partition. Its reported policy allows all accounts and uses QoS `default`. |
| GPU observation | `gpu` is up and reports all accounts allowed. This survey did not check a GPU allocation. |

These reads identify a candidate account and CPU partition. They do not prove that a job request will be accepted.
They also do not prove exact array-child cancellation or safe pending resource changes.

## Remote project state

At 10:07:03 UTC, exact read-only file checks found `unityHPC/run.sh` at the registered remote root.
Its SHA-256 is `2358d4599337849f158c377385ba7ffe26dbdcccd90227374d8d9012c875e668`.
The local file's SHA-256 is `315ab77bdc056baed88c82f8e11b376b08100dc476787d80de8603937318d8db`.
The remote root did not provide readable
`unityHPC/project.json`, `unityHPC/workspace_adapter.py`, or `unityHPC/workspace_results_adapter.py`.
The survey did not upload or change these files.

The local workspace stages frozen source for approved executions. This survey did not exercise that transport.
Remote execution and the scientific adapters remain unverified on Unity.

## Focused checks after the survey

All checks used temporary controller data and copied scientific project fixtures.
They made no scheduler submission or remote file change.

| Check | Result | Evidence |
| --- | --- | --- |
| Copied-project mock, composed restart, scheduling, smoke gate, four-condition Results, and partial retrieval | 18 passed | `[temporary local artifact]` |
| Attached project's collection and result adapters | 12 passed | `[temporary local artifact]` |
| Real browser question-to-comparison-and-evidence workflow | 1 passed | `[temporary local artifact]` |

The browser test used the isolated build at `[temporary local artifact]`.
The earlier complete local run passed 1,055 checks before Pilot A.

## Evidence and remaining gates

The raw bounded observations are in `[temporary local artifact]`,
`[temporary local artifact]`, and `[temporary local artifact]`.
The SSH calls ended successfully. They ran read-only commands with 15–35 second outer deadlines.

Pilot A is complete. Pilots B and C remain separate approval scopes.
The exact scheduler adapter still needs site validation before the application enables cancellation or pending changes.
Remote staging, retrieval, and GPU collection remain unverified. No production migration ran.
