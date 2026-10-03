# Execution services implementation record

Date: 2026-10-03. Owner: execution subagent. This record supplements the manager's implementation record.
No cluster action, live project mutation, commit, or deployment occurred.

## Ownership and contracts

New services use the existing workspace SQLite records. They do not create another store or scheduler ledger.
The existing dispatcher remains the job-ledger writer. Shared contracts come from `workspace_contracts.py`.

| Owned module | Behavior |
| --- | --- |
| `controller/workspace_runs.py` | Execution projections, queue joins, exact attempt streams, bounded cursors |
| `controller/workspace_actions.py` | Frozen management reviews, optimistic concurrency, fences, receipts, reconciliation |
| `controller/workspace_schedules.py` | Frozen schedule approval, windows, due ownership, restart reconciliation |
| `controller/workspace_execution_http.py` | Additive execution routes |
| `controller/workspace_worker.py` | Fence enforcement, maintenance guard, schedule hook, artifact snapshot hook |
| `controller/workspace_local.py` | Separate stream files, process ownership receipts, exact process-group cancellation |
| `controller/web/src/modules/workspace/RunsPage.tsx` | Executions, Queue, stage details, action review, exact logs |
| `controller/web/src/modules/workspace/Schedules.tsx` | Schedule review, history, changed windows, cancellation |
| `tests/test_workspace_{runs,actions,schedules,log_transport}.py` | Isolated acceptance fixtures |
| `templates/scaffold/common/run.sh` | Exact bounded remote log reads and checked log retrieval |

Execution versions advance on worker writes and management writes. Old unversioned records use a content token.
Management reviews bind plan bytes, connection identity, capability version, target identities, and observation tokens.
The controller records a stop fence before cancellation. Worker saves preserve newer fences and management history.
A cancellation acknowledgement does not establish termination. An unresolved acknowledgement blocks overlapping mutations.

Schedule states are `scheduled`, `due`, `dispatching`, `dispatched`, `blocked`, `missed`, `cancelled`, and `uncertain`.
One project lock serializes due dispatch, direct approval, and maintenance. One plan can create only one execution.
The due worker calls the existing internal dispatch service. It never calls a scheduler directly.
Explicit UTC instants round-trip through forms. Local times require an offset that agrees with the selected timezone.

## Acceptance mapping

| Runs scenario | Implementation and check | Status or gate |
| --- | --- | --- |
| RUN-A1: variant identities and purpose | Existing execution fixtures plus Runs projection | Backend checked; complete browser path belongs to manager |
| RUN-A2: branch failure and attention | Existing smoke-gate fixture; new active-plus-attention projection | Checked |
| RUN-A3: exit success with partial outputs | `test_scheduler_success_with_incomplete_outputs_blocks_only_consumers` | Checked: COMPLETED remains visible beside partial completeness; consumer stays waiting |
| RUN-A4: complete failed corpus | Existing artifact checks; manager's `checked-outputs` recovery extension | Manager owns extension checks |
| RUN-A5: uncertain acceptance and restart | Existing receipt reconciliation tests | Checked |
| RUN-A6: exact array child | Unsupported production adapter rejects narrow action | Site capability gate remains |
| RUN-A7: cancellation fence race | Stale worker save cannot clear durable fence | Checked |
| RUN-A8: pending-to-running race | Fake adapter rejects conditional update at scheduler boundary | Checked with fixture; site adapter remains disabled |
| RUN-A9: shorter walltime | Review includes termination risk and no earlier-start promise | Fixture checked; UI integration gate |
| RUN-A10: replacement partial outcomes | `test_refused_cancellation_never_dispatches_replacement`; `test_failed_replacement_does_not_restart_cancelled_original` | Checked: refusal blocks replacement; replacement rejection leaves original cancelled |
| RUN-A11: incompatible checkpoint | Existing explicit resume checks; no automatic resume | Existing baseline |
| RUN-A12: log rotation | Exact stream cursor detects replacement/truncation; response limit 64 KiB | Checked |
| RUN-A13: controller restart | Existing execution receipts and schedule intent reconciliation | Checked |
| RUN-A14: missed schedule | Window expiry creates no execution | Checked |
| RUN-A15: changed schedule inputs | Source/declaration/input checks and exact attachment binding | Source-change fixture checked |
| RUN-A16: DST and duplicate due work | Explicit offset validation, one project lock, dispatch key | Restart and duplicate fixtures checked |
| RUN-A17: stale observation | Stored timestamps age independently; mutation requires authoritative token | Checked |
| RUN-A18: partial cancellation | Per-target refusal and acknowledgement remain distinct | Checked |

## Verification evidence

The expanded service and dispatcher regression run passed 81 tests. TypeScript and ESLint also passed.
The run included new Runs, management, schedule, and log transport tests, plus existing execution, local-receipt, transport, and dispatcher tests.
The local-stage projection regression covers the absence of scheduler submission for controller-host work.

The artifact integrity regression now changes the frozen member. A separate regression changes the original output and checks preserved input provenance.
Neither test weakens the integrity requirement. They distinguish mutable producer files from immutable selected versions.

The manager owns the final browser checks and integrated output directory. No default frontend build changed the live controller UI.

## Capability gates and next steps

The default scheduler adapter disables scheduler cancellation and pending request changes.
A site adapter must prove exact scope, ownership, authoritative observations, and conditional update behavior before activation.
The fake adapter checks the service boundary. It does not establish Unity permissions or installed Slurm semantics.

Controller-host cancellation checks process start identity and process-group ownership before a signal.
An absent process receipt remains uncertain. A signal acknowledgement remains separate from terminal evidence.

The scaffold now provides exact `log-read` and `log-fetch` commands. They resolve the job through its campaign ledger.
Reads return at most 64 KiB. Retrieval checks the complete hash, preserves prior cache bytes, and rejects changed transfer inputs.
A full transfer accepts at most 256 MiB. Larger logs remain available through bounded reads.

The controller invokes these commands through the reviewed dispatcher. Earlier frozen dispatchers retain cached local preview with a capability explanation.
No maintenance silently changes an approved dispatcher. Local operations retain separate stdout and stderr files.
Four shell tests execute these commands with local SSH and rsync stand-ins. No real SSH process reaches a cluster.

Scheduler restart attribution remains unknown without a restart counter. The service does not invent a new approved attempt.
The manager must inspect the combined browser, route aliases, narrow layouts, and full question-to-evidence path.


## Technical spike evidence

| Spike | Evidence | Remaining gate |
| --- | --- | --- |
| T1: conditional scheduler mutation | `test_pending_running_race_rejects_and_plan_stays_frozen`; fake adapter receives an observation token at its mutation boundary | A read-only Unity version/policy survey and audited adapter implementation. Production fields stay disabled. |
| T2: exact array cancellation | `test_one_array_child_never_expands_to_sibling`; `test_partial_cancel_preserves_receipts_and_never_broadens` | Version-specific pending/split/running array proof on the site adapter. No parent fallback activates silently. |
| T4: checkpoint semantics | Existing compatible-resume fixture and manager recovery guards require stopped writers, matching source, and a declared checkpoint checker | Project-specific checkpoint validity remains a declared adapter obligation. Incompatible checkpoints fail closed. |
| T9: local restart and deadlines | Four existing `test_workspace_local.py` cases; active cancellation checks process start token and process-group ownership | Checked with isolated processes. Local stages remain serialized per project. |
| T10: stream and restart identity | Bounded, binary, rotation, remote cursor, exact full-transfer, changed-transfer, and symlink tests | Scheduler restart counter attribution remains Unknown when absent. No automatic recovery treats a reused job ID as a new approved attempt. |

## Independent review and integration repairs

The artifact owner found an unresolved cancellation after lost acceptance. Reconciliation now requires a new exact review after ledger identity appears.
The original stop fence remains. The service never expands the earlier cancellation to the newly discovered job.
The local cancellation intent now commits before the process signal. This order prevents a terminal receipt from racing the intent.
Unchanged worker polls preserve the execution version, so a human can approve an unchanged review.

Runs applies experiment, execution, variant, stage, attempt, purpose, state, and attention URL scopes.
Queue applies the same identity scopes. Log links open the exact Files preview and its containing directory.
Controller-host stages show no scheduler submission. Their lifecycle still reports waiting, active, or succeeded independently.

The execution owner reviewed Settings, Overview, the shared store, recovery, analysis, transport, and editor defaults adoption.
The review found missing backup members, rollback journaling, null scheduler observation handling, and draft journal replay issues.
The maintenance owner repaired those findings. Manager-owned analysis schema selection and concurrent revision numbering findings went to the manager.


Final review additions prevent reuse of an invalidated schedule plan after source restoration, cancellation, or expiry.
The schedule test requires a new plan identity. Receipt links now retain an `operation` query key and reload the exact saved receipt.
The UI supplies explicit accessible names for schedule windows, log search, and replacement walltime.
The targeted Runs, actions, and manager integration run passed 27 tests. The schedule regression run passed nine tests.

The final integration review checked all three manager repairs. Unique analysis declarations enforce input schemas for operation-only requests.
Analysis revision numbers now allocate within one transaction. Cancelled checkpoint writers release their active-use fence only after observed stop.
The expanded execution and manager integration run passed 97 tests. Later log fallback additions passed all nine Runs tests.

Server filters now apply campaign, collection, search, date, and exact execution identities.
Collection uses frozen plan parameters and the Results `family_path` mapping. No workflow name implies a scientific collection.
Date filters use UTC approval dates for executions and UTC submission dates for scheduler jobs. Both interval endpoints are included.
Queue uses scheduler states. Execution state filters retain their separate meaning.

A pending change now records effective requests by exact job identity. Its sibling retains the original request in later reviews.
Log observation checks the frozen dispatcher hash before remote access. Missing remote streams and timeouts retain cached bytes and their age.
Unsupported full-file retrieval stays disabled with a capability reason. A wrapper without a separate event stream reports that absence explicitly.

New controller-host artifacts have no scheduler state. Their operation outcome remains separate from output completeness.
The saved-input reanalysis test checks the Results projection and preserves the original cluster artifact's scheduler evidence.
The final execution, Runs, and manager integration check passed 31 tests.

The final read-only review found no issue in the analysis provenance addition.
Revision allocation, predecessor selection, differences, and sealing share one transaction. Source execution identities come from the frozen artifact inputs.
Execution-owned code is released to the manager for final integration checks. The site capability gates above remain open.

## Shared response contract follow-up

Workspace JSON responses now add `response_metadata` without changing existing fields or optimistic versions.
Metadata separates the current local read from stored scheduler, artifact, and connection observations.
Unknown source revisions and observation times remain explicit. Entity references use JSON pointers to avoid collisions between repeated identifiers.
Response versions exclude projection clocks. Existing content-based approval tokens exclude the added metadata.
The projection only reads returned JSON. It does not create stores, scan files, or run checks.

Actual Results, Files, Settings, and Overview API tests repeat reads and check stable versions and old evidence timestamps.
The contract, conflict, action, schedule, API, and integration run passed 47 tests.
Artifact, Results, Settings, and Overview regression suites passed 65 tests.
Known management and schedule version conflicts now report current and expected entity tokens.
Scientific record fields remain opaque to metadata projection. Invalid freshness thresholds return Unknown without breaking the read.
The API fixture checks strict serialized JSON and preserves scientific fields named `source` or `observed_at`.
Raw artifact downloads retain their exact bytes, including JSON files. They do not receive metadata inside scientific content.
The final response and conflict contract checks passed 12 tests.
