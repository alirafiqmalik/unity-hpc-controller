#!/usr/bin/env bash
# sync-telemetry.sh — pull cluster telemetry into the local archive, roll it
# up, then drop archived days from the cluster so it does not accumulate (I2,
# I7, I8). Holds locks/sync.lock across the pull, the rollup and the remote
# prune. The pull is additive: it never --delete's a local day. Siblings
# (telemetry-imported/, summaries.db, cluster-config.json, archive/, locks/)
# are never children of the destination and are never touched.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRUNE="$HERE/../scripts/hpc-remote-prune"
LOCAL_RETENTION="$HERE/../scripts/hpc-local-retention"
ROLLUP="$HERE/rollup.py"

DATA_DIR="${UNITY_HPC_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/unity-hpc}"
DEST="$DATA_DIR/telemetry/"
# The source is intentionally explicit.  Falling back to a local account/user
# could silently build /work//... or pull telemetry from the wrong cluster.
# A path with no ':' remains a supported local test fixture.
SRC="${UNITY_TELEMETRY_SRC:-}"
if [ -z "$SRC" ]; then
    echo "sync: UNITY_TELEMETRY_SRC must name the telemetry source; set it from a validated project .env or the environment." >&2
    exit 2
fi
LOCK="$DATA_DIR/locks/sync.lock"

mkdir -p "$DATA_DIR/locks" "$DEST"

exec 9>"$LOCK"
if ! flock -n 9; then
    echo "sync already running — skipping pull and rollup"
    exit 0
fi

# test-only seam: hold the lock long enough to make contention deterministic
[ -n "${UNITY_HPC_SYNC_SLEEP:-}" ] && sleep "$UNITY_HPC_SYNC_SLEEP"

echo "sync: pulling $SRC -> $DEST"

# 1. Reachability. A dry-run that fails must abort before the real pull.
PROBE="$(mktemp)"
trap 'rm -f "$PROBE"' EXIT

set +e
rsync -a --dry-run "$SRC" "$DEST" >"$PROBE" 2>&1
DRYRUN_RC=$?
set -e

if [ "$DRYRUN_RC" -ne 0 ]; then
    echo "sync: dry-run rsync failed (rc=$DRYRUN_RC) — aborting before any pull" >&2
    echo "sync: dry-run output:" >&2
    cat "$PROBE" >&2
    exit "$DRYRUN_RC"
fi

# 2. The real pull. Additive: local-only days stay on this machine.
set +e
rsync -a "$SRC" "$DEST"
PULL_RC=$?
set -e
if [ "$PULL_RC" -ne 0 ]; then
    echo "sync: real pull failed (rc=$PULL_RC)" >&2
    exit "$PULL_RC"
fi

# 3. Roll up under the SAME lock (we already hold it, so pass --no-lock).
python3 "$ROLLUP" --no-lock

# 4. Drop archived days from the cluster staging tree. A prune fault must
# not undo the pull or the rollup: the next run retries it.
set +e
python3 "$PRUNE" "$SRC"
PRUNE_RC=$?
set -e
if [ "$PRUNE_RC" -ne 0 ]; then
    echo "sync: remote prune failed (rc=$PRUNE_RC) — local archive is intact" >&2
fi

# 5. The live queue signal. snapshot.csv is a sibling of the telemetry
# directory on the cluster, it is one small file, and the live header
# reads it. The default source is that sibling; UNITY_SNAPSHOT_SRC overrides
# it, and an empty value turns this step off. A cluster that does not publish
# the file is normal, so a failure here is reported and never fatal: the
# telemetry archive and the rollup above are already done.
if [ -z "${UNITY_SNAPSHOT_SRC+x}" ]; then
    SNAP_SRC="$(printf '%s' "${SRC%/}" | sed 's#/telemetry$#/snapshot.csv#')"
    [ "$SNAP_SRC" = "${SRC%/}" ] && SNAP_SRC=""
else
    SNAP_SRC="$UNITY_SNAPSHOT_SRC"
fi
if [ -n "$SNAP_SRC" ]; then
    set +e
    rsync -a "$SNAP_SRC" "$DATA_DIR/snapshot.csv"
    SNAP_RC=$?
    set -e
    if [ "$SNAP_RC" -eq 0 ]; then
        echo "sync: snapshot.csv updated from $SNAP_SRC"
    else
        echo "sync: no snapshot.csv at $SNAP_SRC (rc=$SNAP_RC) — header stays on the last one" >&2
    fi
fi

# 6. Keep 90 days live. Older raw files and summary rows are compressed into
# local backups before they leave the live store. The sync lock is still held.
python3 "$LOCAL_RETENTION" --days "${UNITY_HPC_LOCAL_RETENTION_DAYS:-90}" \
    --apply --no-lock

echo "sync: done"
