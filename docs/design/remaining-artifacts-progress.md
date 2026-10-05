# Files and Results implementation record

Date: 2026-10-03. Owner: artifacts subagent. Integration owner: session manager.

This record adds to the earlier Experiments records. It does not replace them.
All checks use temporary stores, local fixtures, or mock project operations. No cluster workload changed.

## Files and interfaces

| File | Responsibility |
| --- | --- |
| `controller/workspace_artifacts.py` | Immutable copies, safe roots, bounded previews, downloads, exact transfers, cancellation, reconciliation |
| `controller/workspace_results.py` | Frozen sample mappings, sample locators, comparisons, typed plot coordinates, saved views, evidence references |
| `controller/workspace_artifact_http.py` | Files, Results, and transfer routes under the existing workspace API |
| `controller/web/src/modules/workspace/ArtifactPages.tsx` | FilesPage and ResultsPage, including reports, comparisons, samples, plots, and notes |
| `tests/test_workspace_artifacts.py` | Path attacks, version changes, transfer interruption, partial retry, and immutable evidence |
| `tests/test_workspace_results.py` | Four conditions, compatibility, unknown values, pagination, parent scope, and frozen exports |
| `tests/test_workspace_artifact_races_browser.py` | Real browser preview races and Results scope changes after pagination |
| Attached project `unityHPC/workspace_adapter.py` | Saved-corpus completeness independent of resume invocation counters; conflicting duplicate rejection |
| Attached project `unityHPC/workspace_results_adapter.py` | Declared completion-token plot with isolated outputs and condition identities |
| Attached project `tests/test_workspace_results_adapter.py` | Four-condition plot fixture with colliding record IDs |
| Attached project `unityHPC/project.json` | Additive sample mappings, exact retrieval declaration, and plot analysis operation |

The attached project backup is `[temporary local artifact]`.
The collection adapter retains its operations and gains stronger completeness evidence.
Scientific source, datasets, and previous reports remain intact.

The manager owns the workspace router and application service.
The execution agent connects artifact collection to `preserve_artifact(slug, artifact)`.
The manager connects analysis to `freeze_inputs(slug, ids)` and downloads to `download(slug, id, path)`.
The maintenance agent owns evidence notes and pins. It uses `validate_references(slug, references)`.

## Contract decisions

Artifact records retain their original paths and add immutable `frozen_path` values.
A changed content digest creates another artifact identity linked through `logical_id` and `supersedes`.
Repeated checks over unchanged bytes append completeness observations. They do not replace the content version.
Frozen artifacts capture result mappings and metric definitions from their producing declaration.
Saved views retain their exact sample cohort and metric definitions.

The transfer service requires exact member paths and digests.
It supports declared local-copy fixtures and an rsync-files adapter through the controller.
Each receipt has an isolated destination. Partial bytes stay outside final member paths.

Retries select only failed members from the earlier receipt. Successful members remain available.
Reconciliation inspects installed bytes before it permits another transfer.
The broad legacy hook cannot run through a selected-file action.

The T6 fallback uses bounded file scans and immutable byte locators.
Each scan stops at 8 MiB or 5,000 records. Each sample response stops at 100 records.
Full-corpus search remains disabled with an explicit reason.
A cursor starts at its selected member, then continues through later members.
The snapshot metadata check prevents changed files from reusing old locators.

Comparisons require an explicit baseline and two to four conditions.
Metric definitions, units, dataset identity, and evaluator identity must match before paired deltas appear.
Unknown keys, malformed samples, ambiguous joins, and incomplete scans disable paired deltas.
Model and effective cap remain condition dimensions. They do not enter the sample join key.

## Verification evidence

The artifact, result, and actual-project mock suites passed together: 43 tests in 19.30 seconds.
These include actual concurrency tokens on Files and Results conflicts.
The isolated Files and Results browser suites passed: seven tests in 17.92 seconds.
They cover rich previews, safe markup, keyboard access, narrow layouts, path copy, and restored byte pages.
They also delay file, sample, and comparison responses and change Results scope after pagination.
Artifact changes clear sample cursors and detail state. Evidence observation time remains separate from metadata read time.
The final artifact, result, response-contract, and restart checks passed: 55 tests in 6.03 seconds.
JSON NaN, Infinity, and floating-point overflow remain raw parse errors or excluded sample records.
The browser test confirms these values cannot invalidate the JSON response envelope.
The T6 corpus fixture exceeds 8 MiB and stops at 8,387,136 bytes and 3,969 records.
Its observed scan time was 0.054 seconds. A separate fixture reaches the 5,000-record ceiling.
Malformed and oversized rows retain locators and cannot enter derived sample values.
The attached project adapter and Results adapter suites passed: 12 tests.
TypeScript compilation and ESLint for ArtifactPages passed.
The manager owns the combined browser checks and final release acceptance.

| Requirement | Implementation and evidence | Status or remaining gate |
| --- | --- | --- |
| FILE-A1 | Immutable download test; Files links retain artifact and producer IDs | Service verified; browser integration owned by manager |
| FILE-A2 | Controller host labels and separate browser download links | Implemented; browser inspection owned by manager |
| FILE-A3 | `test_unknown_adapter_cannot_call_legacy_hook` | Verified |
| FILE-A4 | Partial quarantine and partial-retry tests | Verified |
| FILE-A5 | `test_partial_transfer_quarantines_bytes_and_preserves_destination` | Verified |
| FILE-A6 | Transfer cancellation writes only transfer records; bounded transfer process termination | Verified by a real isolated local process cancellation fixture |
| FILE-A7 | `test_transfer_restart_reconciles_before_retry` | Verified |
| FILE-A8 | `test_successful_retrieval_does_not_promote_incomplete_science` | Verified |
| FILE-A9 | Existing execution source-change tests; immutable input copy test | Verified in baseline suite; manager reruns combined checks |
| FILE-A10 | Resolved project-relative secrets, traversal, symlink, preview-budget tests | Verified |
| FILE-A11 | Parse-error test retains raw JSON text | Verified |
| FILE-A12 | Literal markup preview; React text output; sandboxed download | Verified in real browser with escaped HTML, safe Markdown, structured data, and bounded PNG |
| FILE-A13 | Immutable local copies remain independent of remote state | Verified by old-version download and transfer-failure tests |
| FILE-A14 | Bounded preview and multi-file sample cursor tests | Verified |
| FILE-A15 | Immutable versions and prior-analysis mock tests | Verified |
| RESULT-A1 | Four-condition comparison test and attached project plot fixture | Verified; actual project mock also retains both caps |
| RESULT-A2 | Project completeness check uses unique saved records and expected identities independently of invocation counters | Verified by the attached zero-invocation resume and duplicate-conflict fixture |
| RESULT-A3 | Existing worker keeps scheduler and completeness facts separate | Baseline implementation retained; manager owns stranded-stage integration |
| RESULT-A4 | Existing actual-project mock performs two saved-input analyses | Verified without collection dispatch |
| RESULT-A5 | Existing planner checks declared metrics and collection requirements | Verified through the analysis API with no new execution; actual-project accuracy and token fields pass |
| RESULT-A6 | Isolated output IDs and immutable report copies preserve old evidence | Verified by failed analysis with retained partial outputs and unchanged prior report |
| RESULT-A7 | Evaluator and metric-definition mismatch tests | Verified |
| RESULT-A8 | Missing-value and unmatched/ambiguous-join tests | Verified |
| RESULT-A9 | Frozen field mappings expose turns, phases, effective cap, and exact parent scope | Verified with actual project field mappings, T3 phases, recovered turn, and exact parent |
| RESULT-A10 | Unknown provenance blocks compatible comparison | Verified |
| RESULT-A11 | Smoke filtering and analysis guards | Verified |
| RESULT-A12 | Saved plot data and comparison export retain exact cohorts and definitions | Verified |
| RESULT-A13 | Existing durable worker and actual-project reanalysis tests | Baseline verified; manager owns restart integration |
| RESULT-A14 | Notes use maintenance expected-version API; UI retains text on failure | Maintenance owns the conflict check; UI edit preserves text and expected version |
| T3 | Exact manifest transfer, digest rejection, partial retry, isolated promotion, reconciliation | Local fixture gate verified; real remote transport remains unverified |
| T5 | Existing adapter scans each explicit condition separately; plot fixture preserves four conditions | Verified |
| T6 | Bounded scan fallback, checked snapshots, multi-file cursors | Verified; full indexing/search stays capability-disabled |

## Independent review

The maintenance agent found metric-definition, cursor, unknown-join, and report-currency defects.
The implementation now rejects incompatible deltas and preserves multi-file pagination.
Regression tests cover the first three defects. Currency uses linked analysis inputs and independent execution activity.

The artifact agent reviewed execution actions and schedules.
It reported unresolved cancellation after uncertain submission and a local cancellation intent race.
The execution agent owns those fixes and their regression checks.

Late execution review found non-source secret aliases, partial CSV rows, stale pagination, and delayed preview responses.
Regression checks now cover all four defects. Partial CSV pages show raw source with an explicit boundary limitation.
Whole bounded CSV files use strict parsing.
Files and Results conflicts expose the actual current and expected concurrency tokens when these are known.

## Remaining validation boundaries

Real rsync transport needs a separately approved fixture under a declared remote output root.
That check must prove exact file selection, changed-remote rejection, cancellation, and restart recovery.
It must not submit, cancel, or change a cluster workload.

The real project still needs its approved GPU environment lock before genuine collection.
This is an existing readiness gate. Local mock workflows and all independent Results work remain available.
