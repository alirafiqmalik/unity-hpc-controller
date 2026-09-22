# The local machine keeps the telemetry archive

Status: accepted. Supersedes the retention sentence in ADR 0004. I1 still
owns new samples on the cluster. I2 and I8 now describe an archive, not a
shrinking mirror.

The cluster wrote raw telemetry for 35 days and the workstation mirrored it
with `rsync --delete`. When the cluster pruned a day, the local copy went
with it. The lasting record was `summaries.db` only. Shared `/work` still
held weeks of jsonl, and the login-node sample log stayed in `/tmp`.

The pull is additive. After the rollup, days that are on this machine, fully
summarised, and not today leave the cluster. Today's live day stays so the
collector can keep appending. The collector's 35-day prune remains a
backstop for a machine that never pulls. Sample logs from the cluster
session are written under `$UNITY_HPC_DATA/controller/session-logs/` and
the remote `/tmp` files are removed.

A local pruner was rejected: the archive is what the operator keeps. Deleting
local days when the cluster prunes was rejected: that is the fault this
change exists to stop. Shortening the cluster retention to one day and
keeping `--delete` was rejected: a failed pull would then wipe the only copy.

## Consequences

- `sync-telemetry.sh` no longer passes `--delete`. `hpc-remote-prune` runs
  under the same `locks/sync.lock` after the rollup.
- I2: only the sync script writes the local tree, and it never shrinks it.
- I8: the gate now decides which **remote** days may go.
- Session sample logs are local. Closing the session also wipes the remote
  `/tmp` files.
