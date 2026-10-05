# Pilot B and Pilot C evidence

Date: 2026-10-03. The user approved both pilots and asked for them to run.
This record supplements the [live validation plan](remaining-workspace-live-validation.md).
Raw receipts are in `/tmp/unity-hpc-pilot-bc-20261003`. Cleanup of the remote fixture was not approved and did not run.

## Reviewed targets

| Target | Value |
| --- | --- |
| Host alias | `unity` (`unity.rc.umass.edu`) |
| Account | `pi_taqi_umass_edu` |
| Partition | `cpu` |
| Dispatcher | Local `unityHPC/run.sh`, SHA-256 `315ab77bdc056baed88c82f8e11b376b08100dc476787d80de8603937318d8db` |
| Cancellation adapter | Pilot-only exact-array adapter, SHA-256 `efe415ed34a9c844df13b975183a9035641e1a996861f4531eb7ce3c192765c0` |
| Pilot B campaign | `pilotb-20261003-2116` |
| Pilot B output root | `/work/pi_taqi_umass_edu/ali/llm_thinking_trace_logic/_results/pilotb-20261003-2116` |
| Pilot C fixture | `/work/pi_taqi_umass_edu/ali/llm_thinking_trace_logic/.unity-workspace/outputs/pilot-c-20261003-2118` |

The production scheduler adapter remains `unavailable-v1`. This run did not install the pilot adapter into it.
Pending resource changes were not attempted.

## Pilot B

The existing dispatcher submitted one array, job `65200112`, with tasks `65200112_0` (`pilot-b-child-0`) and `65200112_1` (`pilot-b-child-1`).
Each task requested `billing=1,cpu=1,mem=128M,node=1` on partition `cpu` and account `pi_taqi_umass_edu`.
Slurm accepted 128 MB and noted that the request is small. No GPU request was present.
The saved project defaults still name a GPU partition; this submission overrode them for this call only. The stored project overrides are still empty.

Both tasks were `RUNNING` before cancellation. The frozen preview named only `65200112_0` and listed `65200112_1` as unaffected.
`scancel 65200112_0` returned success with no terminal claim. A later `sacct` read showed `65200112_0` as `CANCELLED by 3021` and `65200112_1` still `RUNNING`.
The sibling then finished `COMPLETED` with exit 0. Its ledger identity stayed `65200112_1`.
The cancellation path did not rewrite the campaign ledger. Both rows still say `PENDING` from submission time `2026-10-03T21:17:22Z`.

Task 0 wrote its identity and was terminated during the wait. Its stderr names signal termination of Slurm job `65200121` on `uri-cpu078`.
Task 1 wrote its identity and printed `rc=0`. Both banners report `gpu=unknown`.

This is one running-array observation. It does not cover a pending cancellation, a split array, or a refusal. Production cancellation stays disabled.

## Pilot C

Three fixture files and one 72,000-byte log were created under the Pilot C directory. No scheduler job was submitted for this pilot.

| File | Size | SHA-256 before retrieval |
| --- | --- | --- |
| `selected.bin` | 20 | `939ac84a6b4bcd967cf22f3d1eec8262b3542dd1dc44784f2b6bd41b7232d3d0` |
| `untouched-a.bin` | 20 | `96fb263b3c95d8bb705b11f3b0944db82f8b0c0eb7a73706ce84f46dd0a60cb4` |
| `untouched-b.bin` | 20 | `2faded3e7bfe10cefa5d2de1fe18e1a8286ff4ed132c510c19bab4c751f15b34` |
| `fixture.log` | 72000 | `ec56591a6a3969f6d63486f3858cad60f96ccb3d5ba65187b8de1421f83f2dde` |

An exact `rsync` of `selected.bin` into an isolated directory matched that digest. The other two files were absent from that directory.
The remote selected file was then replaced. Its new digest is `86cd042be4dc7b2392ec265c41dd009df7a3a3a9a28f91774746f0ea4a5d66b0`.
The isolated copy kept the original digest, and the mismatched download was discarded.

Two reads of `fixture.log` used a 65,536-byte limit. The first returned offset 0 and next offset 65536. The second started at 65536 and ended at 72000.
Both reads named file identity `52:15078182808409643296`, and their bytes join to the original log.
The attached `run.sh` has no `log-read` command, so this read used that byte limit directly. The production dispatcher was not modified.

A slow read of the fixture log was stopped after 1,024 bytes, SHA-256 `6873221430783ccd41370b631a0594ae408288f57cef56497e9c8fcfaf5ebb0c`.
The controller was restarted after those bytes were on disk. They were unchanged after the restart.
A later retry copied the full log to a separate path and matched `ec56591a6a3969f6d63486f3858cad60f96ccb3d5ba65187b8de1421f83f2dde`. The 1,024-byte partial remained in place.
An earlier restart happened while a throttled `rsync` had not yet left a destination file. That attempt is not the reconciled partial.
After both restarts, `sacct` still showed `65200112_0` cancelled and `65200112_1` completed. The controller health check returned ok.

The remote fixture, including the replaced `selected.bin`, remains in place.
