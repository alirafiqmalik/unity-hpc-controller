---
name: recon
description: "Cluster reconnaissance — observes partition capacity, GPU fleet, account limits, fair-share and storage, then merges them into the shared cluster-config.json in $UNITY_HPC_DATA. Read-only on the cluster, and it never clobbers another project's observations."
---

# unity-hpc:recon

Announce: "Using unity-hpc:recon to gather the cluster configuration."

This skill only reads from the cluster. It produces one **cluster-neutral**
observation, and merges it into the shared `cluster-config.json` through a
locked, deterministic read-merge-write.

**Never** write project-specific commentary into the configuration. A note that
one project ignores part of the fleet caused the `a100=157 → a100=40` regression.

Absence is not evidence of absence. If you did not probe the GPUs, emit no
`gpu_fleet` key at all. The merge then keeps the existing fleet as it is.

## Where the configuration lives

```
${UNITY_HPC_DATA:-$HOME/.local/share/unity-hpc}/cluster-config.json
```

Every project shares this file, and it sits outside the versioned plugin. To read
it back at any time, use the `unity_cluster_profile` MCP tool. That tool renders
the file as markdown.

## Staleness guard

Recon skips the probe while the configuration is younger than
`UNITY_HPC_RECON_TTL`. The default is `43200` seconds, that is 12 hours.

To force a new probe, pass `--force` to `hpc-config-write` in step 6. Then do the
SSH probes below in every case. Check the age first:

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, "${CLAUDE_PLUGIN_ROOT}")
from lib import cluster_config as cc
print("probe" if cc.should_probe(int(__import__("os").environ.get("UNITY_HPC_RECON_TTL", cc.DEFAULT_TTL_SECONDS))) else "fresh")
PY
```

If it prints `fresh`, and the user did not ask to force a probe, stop. Then print
that the configuration is current. In every other case, continue.

## Steps

**1. Check SSH connectivity**

```bash
ssh unity "echo ok"
```

If this fails, stop. Tell the user to check the `unity` entry in `~/.ssh/config`.

**2. Observe the partitions, GPU fleet, limits, fair-share and storage**

All probes run in one remote shell, with the wrapper PATH and the pager fix. The
`unity-slurm-*` wrappers live in `/modules/user-resources/bin`, which is not on
the non-interactive PATH. They also block on a pager until you set `PAGER=NONE`.

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

Transcribe the output into a JSON object. Emit **only** the sections that you
observed. Stamp every point-in-time record with `observed_utc`, that is the
current UTC time in `YYYY-MM-DDTHH:MM:SSZ` form.

The merge takes the maximum of each capacity count (`nodes`, `cpus_total`,
`gpus_total`, `total_accessible`), so a partial reading never shrinks a fuller
one.

Describe the **cluster only**. Never describe how one project uses the cluster.
Never describe how much of the fleet a project needs or avoids.

Use `${SLURM_ACCOUNT:-your_account}` from the env or `.env`, never a literal
account name.

This is the shape. Omit every key that you did not observe:

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

**4. Probe the sacct scope**

This value feeds the telemetry collector.

```bash
ssh unity "sacct -a -S now-1hours -X -P --noheader 2>&1 | head -1"
```

If rows come back, set `"sacct_scope": "-a"`. If the cluster denies the request,
set `"sacct_scope": "-A ${SLURM_ACCOUNT}"`.

**5. Write the observation to a temp file**

```bash
cat > /tmp/unity-recon-obs.json <<'JSON'
<the JSON object you built in steps 3–4>
JSON
```

**6. Merge into the shared configuration through the locked CLI**

```bash
PROJECT_NAME="$(basename "$(pwd)")"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/hpc-config-write" \
    --obs-file /tmp/unity-recon-obs.json --writer "$PROJECT_NAME"
# add --force only if the user asked for a new probe inside the TTL
```

This command takes `locks/config.lock`, merges with union, max and newest-wins
rules, and rewrites `cluster-config.json` atomically. The merge is the only path
to the file, so no project's write ever replaces another project's observations.
The command prints `written` or `skipped`.

**7. Check the merged result**

Read the merged file back with the `unity_cluster_profile` MCP tool. Print the
partition table and the GPU-fleet table to the user.

**8. Print the summary**

Report the account limits, the accessible GPU types, and whether the TTL guard
skipped the write. Then print: "Run /unity-hpc:setup to configure your project
for this cluster."

## Migrating an old prose profile

An old prose profile document, in the format that came before the JSON, can still
sit in the data directory. The migration script `cluster-intel/migrate.py`
handles that file once: it seeds `cluster-config.json` from the maximum capacity
values, and archives the original. Do not parse that file here.
