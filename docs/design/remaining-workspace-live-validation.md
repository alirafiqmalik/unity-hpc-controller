# Remaining workspace live validation gates

This document defines separate live pilots. The user approved and completed the read-only Pilot A survey on 2026-10-03.
The [Pilot A evidence](remaining-workspace-pilot-a-evidence.md) records the site observations and focused local checks.
The user later approved Pilots B and C. Their [evidence](remaining-workspace-pilot-bc-evidence.md) records one running two-task cancellation and one fixture transfer.
Those runs do not enable production cancellation or pending changes. Local fixtures still do not establish the remaining site cases.

## Capability status

| Capability | Local evidence | Live gate |
| --- | --- | --- |
| Exact scheduler cancellation | Array-child selection, refusal, uncertainty, fences, and terminal reconciliation fixtures | Audited site adapter and pending, split, running, and terminal array observations |
| Pending request changes | Conditional fake adapter rejects the pending-to-running race | A site mechanism that enforces the reviewed state at mutation time. Otherwise keep disabled |
| Exact remote logs | Bounded read, rotation, binary, changed-transfer, and preserved-cache fixtures | A reviewed dispatcher with the new commands and an owned fixture log |
| Exact artifact retrieval | Manifest selection, quarantine, partial retry, cancellation, and restart fixtures | Owned remote fixture files, checked hashes, and the declared controller transport |
| Scientific GPU collection | Four-condition CPU mock and selected-input analysis | The attached project's approved GPU environment lock and a separate scientific resource review |
| Production migration | Backup, activation, rollback, relocation, and restart fault fixtures | An explicit production attachment, maintenance window, and reviewed backup. Excluded from this pilot |

## Pilot A: read-only site survey

Approval scope: use the attached project's configured SSH alias `unity` through the controller to read site capabilities.
Record the configured host alias, project root, Slurm version, available commands, and relevant account and partition permissions.
Do not change scheduler configuration, project declarations, files, or workloads.
Use bounded command timeouts and preserve each observation time.
The approved survey ran on 2026-10-03. Its observed CPU candidate is account `pi_taqi_umass_edu` on partition `cpu`.
Job acceptance and exact mutation scope remain unverified.

Before Pilot B, select one permitted CPU partition and account from these observations.
Record the exact host, account, partition, adapter revision, and fixture directory in its reviewed plan.
A missing value blocks Pilot B. Do not substitute a default or enable unsupported fields.

## Pilot B: isolated scheduler scope

Approval scope: create one new fixture array with exactly two children, under a fresh campaign and output root.
Each child requests one CPU, no GPU, 128 MiB, and at most one minute.

The total resource ceiling is two CPU-minutes. The operation only writes its own identity and waits for a bounded interval.
Use the existing dispatcher to create the ledger. Preserve both exact child identities before management review.

1. Observe the owned array and freeze an exact-child cancellation preview.
2. Check the preview targets one child and explicitly lists the other as unaffected.
3. Apply cancellation only through the audited adapter. Observe terminal state separately from acknowledgement.
4. Check the sibling's ledger and scheduler identity retain their previous values after the action.
5. Preserve stdout, stderr, receipt, observations, and adapter version as pilot evidence.

Repeat runs require another explicit approval. This plan authorizes only one two-child array.
One run cannot establish every pending, split, running, and terminal case.
Keep the relevant production capability disabled until all required cases have evidence.
Do not test pending resource updates unless the site exposes a safe state-conditional operation.
Shorter walltime never guarantees an earlier start.

## Pilot C: exact remote file transport

Approval scope: create a new remote fixture directory with three files, each at most 1 MiB.
Use only the configured project output root and a unique pilot suffix.
Record paths and SHA-256 hashes before retrieval review. This pilot needs no scheduler job.

Retrieve one selected file into an isolated controller destination. Check the other two files were not transferred.
Repeat with an intentionally changed selected member and check digest rejection preserves the prior local version.

Interrupt a fixture transfer, restart the development controller, and reconcile installed bytes before retry.
Cancel only the fixture transfer process. Check no scheduler action or unrelated transfer occurs.
Read an owned fixture log with a 64 KiB limit and check exact stream identity and cursor boundaries.

The pilot must leave an evidence manifest and its receipts. Cleanup requires a separate explicit scope.
Do not overwrite scientific datasets, reports, existing logs, or a production attachment.

## Approval boundary

Record each pilot’s exact configured targets before requesting its separate approval.
Pilot A supplies missing site facts. The user separately approved one Pilot B array and one Pilot C fixture on 2026-10-03.
That approval does not authorize a repeat run, cleanup, GPU collection, or production migration.
