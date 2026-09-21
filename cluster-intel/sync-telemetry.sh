#!/usr/bin/env bash
# sync-telemetry.sh — one-way, retention-aware pull of the cluster telemetry into
# the local mirror, followed by a rollup. Holds locks/sync.lock across BOTH so a
# rollup never reads a half-synced tree and two pulls never --delete concurrently
# (I2, I7). --delete is gated by hpc-retention-gate and scoped to telemetry/ only;
# siblings (telemetry-imported/, summaries.db, cluster-config.json, archive/,
# locks/) are never children of the destination and are never touched.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATE="$HERE/../scripts/hpc-retention-gate"
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

# 1. Learn which local day-dirs a real --delete would remove.
ITEMIZE="$(mktemp)"
trap 'rm -f "$ITEMIZE"' EXIT

set +e
rsync -a --delete --dry-run --itemize-changes "$SRC" "$DEST" >"$ITEMIZE" 2>&1
DRYRUN_RC=$?
set -e

if [ "$DRYRUN_RC" -ne 0 ]; then
    echo "sync: dry-run rsync failed (rc=$DRYRUN_RC) — aborting before any delete or pull" >&2
    echo "sync: dry-run output:" >&2
    cat "$ITEMIZE" >&2
    exit "$DRYRUN_RC"
fi

set +e
python3 "$GATE" <"$ITEMIZE"
GATE_RC=$?  # gate's own exit status (0=allow, 10=withhold, other=gate failure) — NOT rsync's
set -e

DELETE_ARGS=()
if [ "$GATE_RC" -eq 0 ]; then
    DELETE_ARGS=(--delete)
elif [ "$GATE_RC" -eq 10 ]; then
    echo "sync: retention withholding --delete this run"
else
    echo "sync: retention gate failed (rc=$GATE_RC)" >&2
    exit "$GATE_RC"
fi

# 2. The real pull. --delete (if allowed) is scoped to telemetry/ only.
set +e
rsync -a "${DELETE_ARGS[@]}" "$SRC" "$DEST"
PULL_RC=$?
set -e
if [ "$PULL_RC" -ne 0 ]; then
    echo "sync: real pull failed (rc=$PULL_RC)" >&2
    exit "$PULL_RC"
fi

# 3. Roll up under the SAME lock (we already hold it, so pass --no-lock).
python3 "$ROLLUP" --no-lock

# 4. The live queue signal. snapshot.csv is a sibling of the telemetry
# directory on the cluster, it is one small file, and the dashboard header
# reads it. The default source is that sibling; UNITY_SNAPSHOT_SRC overrides
# it, and an empty value turns this step off. A cluster that does not publish
# the file is normal, so a failure here is reported and never fatal: the
# telemetry mirror and the rollup above are already done.
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

echo "sync: done"
