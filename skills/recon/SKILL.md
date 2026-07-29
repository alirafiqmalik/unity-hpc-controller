---
name: recon
description: "Cluster reconnaissance — observes partition capacity, GPU fleet, account limits, fair-share and storage, and merges them into the shared cluster-config.json in $UNITY_HPC_DATA. Read-only on the cluster; never clobbers another project's observations."
---

# unity-hpc:recon

Announce: "Using unity-hpc:recon to gather cluster configuration."

Read-only on the cluster. Produces a single **cluster-neutral** observation and
merges it into the shared `cluster-config.json` through a locked, deterministic
read-merge-write. **Never** write project-specific commentary (e.g. "not used by
this project") into the config — that is what caused the `a100=157 → a100=40`
regression. Absence is not evidence of absence: if you did not probe GPUs, do not
emit a `gpu_fleet` key at all, and the merge will leave the existing fleet intact.

## Where the config lives

```
${UNITY_HPC_DATA:-$HOME/.local/share/unity-hpc}/cluster-config.json
```

Shared by every project, outside the versioned plugin. Read it back at any time
with the `unity_cluster_profile` MCP tool, which renders it as markdown.

## Staleness guard

Recon is skipped if the config is younger than `UNITY_HPC_RECON_TTL` (default
`43200` seconds = 12h). To force a re-probe, pass `--force` to `hpc-config-write`
(step 6) and proceed with the SSH probes below regardless. Check first:

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, "${CLAUDE_PLUGIN_ROOT}")
from lib import cluster_config as cc
print("probe" if cc.should_probe(int(__import__("os").environ.get("UNITY_HPC_RECON_TTL", cc.DEFAULT_TTL_SECONDS))) else "fresh")
PY
```

If it prints `fresh` and the user did not ask to force, stop and report that the
config is current. Otherwise continue.

## Steps

**1. SSH connectivity check**
```bash
ssh unity "echo ok"
```
If this fails, stop and tell the user to check their `~/.ssh/config` entry for `unity`.

**2. Observe partitions, GPU fleet, limits, fair-share, storage**

All probes run in one remote shell with the wrapper PATH and pager fix. The
`unity-slurm-*` wrappers live in `/modules/user-resources/bin`, which is not on
the non-interactive PATH, and block on a pager unless `PAGER=NONE`.

```bash
ssh unity 'export PATH=/modules/user-resources/bin:$PATH; export PAGER=NONE
  echo "### slurm_version"; sinfo --version
  echo "### partitions_raw";   sinfo -h -o "%R|%a|%D|%C|%G|%l"
  echo "### gpu_usage";        timeout 60 unity-slurm-gpu-usage
  echo "### assoc";            sacctmgr -n show assoc user=$(whoami) format=Account,QOS,MaxSubmitJobs,MaxJobs,GrpTRES,MaxWallDurationPerJob -P
  echo "### qos";               sacctmgr -n show qos format=Name,Priority,MaxWall -P
  echo "### fairshare";        sshare -U -n -P -o FairShare,EffectvUsage
  echo "### storage";          df -P "/work/${SLURM_ACCOUNT:-$(whoami)}" 2>/dev/null | tail -1'
```

**3. Build a cluster-neutral observation**

Transcribe the output into a JSON object. Emit **only** the sections you actually
observed; stamp every point-in-time record with `observed_utc` (current UTC in
`YYYY-MM-DDTHH:MM:SSZ`). Capacity counts (`nodes`, `cpus_total`, `gpus_total`,
`total_accessible`) are merged by max, so a partial reading never shrinks a
fuller one. Describe the **cluster only** — never a project's usage of it, and
never how much of the fleet a given project needs or avoids. Use
`${SLURM_ACCOUNT:-your_account}` (from env/.env), never a literal account name.
Example shape (omit any key you did not observe):

```json
{
  "slurm_version": "25.11.6",
  "partitions": {
    "gpu": {"nodes": 145, "cpus_total": 3288, "gpus_total": 769,
            "gpu_types": ["a100", "l40s"], "max_walltime": "24:00:00",
            "access": "open", "observed_utc": "<UTC>"}
  },
  "gpu_fleet": {
    "a100": {"total_accessible": 157, "vram_gb": [80, 40],
             "compute_capability": 8.0, "observed_utc": "<UTC>"}
  },
  "account_limits": {"account": "${SLURM_ACCOUNT}", "max_submit_jobs": null,
                     "qos": [{"name": "short", "max_wall": "04:00:00", "priority": 10}]},
  "fairshare": {"factor": 0.449, "effective_usage": 0.9998, "observed_utc": "<UTC>"},
  "storage": {"/work/${SLURM_ACCOUNT}": {"used_gb": 590, "total_gb": 1024,
                                          "observed_utc": "<UTC>"}},
  "sacct_scope": "-a"
}
```

**4. Probe sacct scope** (feeds the telemetry collector)
```bash
ssh unity "sacct -a -S now-1hours -X -P --noheader 2>&1 | head -1"
```
If rows return, set `"sacct_scope": "-a"`; if denied, `"sacct_scope": "-A ${SLURM_ACCOUNT}"`.

**5. Write the observation to a temp file**
```bash
cat > /tmp/unity-recon-obs.json <<'JSON'
<the JSON object you built in steps 3–4>
JSON
```

**6. Merge into the shared config through the locked CLI**
```bash
PROJECT_NAME="$(basename "$(pwd)")"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/hpc-config-write" \
    --obs-file /tmp/unity-recon-obs.json --writer "$PROJECT_NAME"
# add --force only if the user asked to re-probe within the TTL
```
This acquires `locks/config.lock`, merges with union/max/newest-wins rules, and
atomically rewrites `cluster-config.json`. No project's write ever blindly
replaces another's observations — the merge is the only path to the file. It
prints `written` or `skipped`.

**7. Confirm**

Read the merged result back with the `unity_cluster_profile` MCP tool and show the
user the partition and GPU-fleet tables.

**8. Print summary**

Report the account limits, accessible GPU types, and whether the write was
applied or skipped by the TTL guard. Suggest: "Run /unity-hpc:setup to configure
your project for this cluster."

## Migrating an old prose profile

If a legacy prose profile document (the pre-JSON format) exists in the data
dir, it is handled once by the migration script (`cluster-intel/migrate.py`),
which seeds `cluster-config.json` from it taking maximum capacity values and
archives the original. Do not parse it here.
