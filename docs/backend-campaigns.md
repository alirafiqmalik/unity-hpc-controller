# Portable backend campaigns

The controller accepts frozen source bundles and task declarations.
It owns SSH, Slurm submission, durable attempts, and result retrieval.
Projects do not register a directory or maintain a Unity ledger.
Their runner directory contains the hardware adapter.

## Start and configure

Start the controller from this checkout:

```bash
scripts/hpc-controller --fg --no-tailscale --port 8301
```

The default mode requires Python, SSH, rsync, and access to the configured cluster.
It has no dashboard and no project registration.

`UNITY_CONTROLLER` sets the HTTP client address when `--url` is absent.
The CLI also accepts the older `UNITY_CONTROLLER_URL` value as a fallback.
The controller resolves its data directory from `UNITY_HPC_DATA`.

Create a controller settings file:

```json
{
  "account": "pi_yourlab_umass_edu",
  "ssh_host": "unity",
  "ssh_identity": "~/.ssh/unity_cluster_ed25519",
  "remote_root": "/work/pi_yourlab_umass_edu/<user>/unity-controller",
  "allowed_partitions": ["gpu", "gpu-preempt"],
  "cpu_partitions": ["cpu", "cpu-preempt"],
  "qos": "normal",
  "mail_user": "you@umass.edu",
  "max_active_tasks": 32,
  "max_active_gpus": 16
}
```

Configure the backend, then collect its live catalog:

```bash
scripts/hpc-campaign --url http://127.0.0.1:8301 configure backend.json
scripts/hpc-campaign --url http://127.0.0.1:8301 probe
```

### Job email notifications

`mail_user` sets the email recipient for every CPU and GPU job that this backend submits.
Slurm sends notifications for completion, cancellation, failure, time limits, and requeue events.
The controller adds `--mail-user` and `--mail-type=END,FAIL,TIME_LIMIT,REQUEUE` to each job script.
Slurm sends these emails even if the controller is offline.
See the [Slurm mail settings](https://slurm.schedmd.com/sbatch.html#OPT_mail-type).

Set the recipient through `PATCH /api/v1/backend` with `{"mail_user":"you@umass.edu"}`.
The controller saves this setting in its data directory under `controller/backend.json`.
The setting applies to new submissions and retries, including waiting tasks in existing campaigns.
Accepted campaigns retain their execution paths, resource requests, and scientific commands.

An empty `mail_user` disables notifications for future submissions.
New deployments default to an empty recipient.
This setting applies only to this controller deployment.
Other controllers retain their own mail settings.

Already submitted jobs retain the mail settings that Slurm accepted.
For those jobs, update only the notification fields with `scontrol update JobId=<id> MailUser=you@umass.edu MailType=END,FAIL,TIME_LIMIT,REQUEUE`.
Check each job ID against this controller's campaign journal before the update.
The update preserves the allocation and does not resubmit the job.

### Keep the service running

Install a named user service to keep this deployment separate from other controllers:

```bash
UNITY_HPC_DATA=/absolute/controller-data scripts/hpc-controller \
  --install-user-service --service-name unity-hpc-backend-refinement \
  --port 8301 --no-tailscale
systemctl --user daemon-reload
systemctl --user enable --now unity-hpc-backend-refinement
```

Stop an existing foreground or background instance on that port before starting the unit.
The installer preserves the selected data directory, host, port, and Tailscale setting.
The default service uses the headless API and restarts after a process failure.
Choose a distinct service name to preserve an existing controller unit.

For the refinement deployment, `/absolute/controller-data` is:

```text
$HOME/.local/share/unity-hpc-backend-refinement
```

Read status and logs, or load changed controller code:

```bash
systemctl --user status unity-hpc-backend-refinement
journalctl --user -u unity-hpc-backend-refinement -f
systemctl --user restart unity-hpc-backend-refinement
```

The enabled user unit starts with the user's systemd session.
Starting it before login requires user lingering, configured by the machine administrator.
The refinement service is active and enabled on port 8301, with user lingering enabled.
Its migration preserved all 17 then-submitted job identities and attempt numbers.
The journal, immutable bundles, and artifact receipts remain under the selected data directory.
When you update the controller source, keep that directory.

The catalog records node features, GPU GRES, partition access, QOS, account limits, fairshare, and observation time.
The controller refreshes it every 15 minutes while campaigns need work.
An absent or stale catalog blocks new submissions.
A failed catalog query does not stop accepted-job reconciliation or result retrieval.

## Collect historical telemetry

The backend catalog and accounting archive use separate collection paths.
The catalog answers placement questions.
The archive retains sampled resources, job accounting, and accounting steps for later analysis.

Deploy only `cluster-intel/collector.sh` and `cluster-intel/collector_parse.py` to a controller-owned remote directory.
Use the configured SSH alias and identity.
For the refinement deployment, that directory is:

```text
/work/pi_yourlab_umass_edu/<user>/unity-controller/cluster-intel
```

Set the collector script executable and create its `telemetry/` subdirectory.
Keep its writer lock and high-water mark in the same remote directory.
Each deployment needs a separate directory and `session_name`.
This prevents collisions with other controllers' writer locks, tmux sessions, and completion markers.

Configure the controller through `PATCH /api/v1/telemetry/settings`:

```json
{
  "source": "unity:/work/pi_yourlab_umass_edu/<user>/unity-controller/cluster-intel/telemetry/",
  "ssh_host": "unity",
  "ssh_identity": "~/.ssh/unity_cluster_ed25519",
  "session_name": "unity-hpc-backend-v1",
  "script_mode": "once",
  "interval_minutes": 15,
  "schedule_enabled": false
}
```

Preserve the source's trailing slash for rsync.
Call `POST /api/v1/telemetry/script` with `{"mode":"once"}` for the first collection.
This runs one bounded sample, pulls the files, and updates local summaries under one local sync lock.
Read `GET /api/v1/telemetry` until `last_run.status` reports `ok`.

Then enable `schedule_enabled` through the settings route.
The controller schedules one collection every 15 minutes while its service runs.
The remote shell closes after 22.5 idle minutes.
No resident collector runs on the login node.

The first sample queries accounting from the preceding 20 minutes.
Later samples resume from their successful high-water mark with a five-minute overlap.
Catch-up queries stop at seven days.
The run log reports older gaps.
The local archive keeps retrieved records after the controller prunes remote staging files.

Older accounting requires a separate bounded import from Slurm, subject to available history.
The schedule cannot reconstruct resource snapshots from before it started.

Query `GET /api/v1/telemetry/accounting` with `user`, `account`, `partition`, `gpu_type`, `since`, `until`, and bounded `limit` filters.
Accounting preserves requested resources, allocated resources, node lists, CPU measurements, and GPU step measurements when Slurm supplies them.
Missing measurements remain unknown.
GPU accounting peaks and multi-GPU sums do not represent continuous device usage.

Join accounting records to campaign attempts by `job_id` for experiment attribution.
The controller journal records that mapping before result transfer.
Opaque Slurm job names do not encode dataset or model metadata.
The frozen experiment manifest provides those scientific details.

## Declare a campaign

The controller accepts JSON.
A project's runner can translate its portable YAML experiment into this declaration:

```json
{
  "schema_version": 1,
  "campaign_id": "formal-conjectures-small-a10080-v2",
  "bundle": {
    "path": "/absolute/path/to/prepared-bundle",
    "exclude": ["results", "artifacts", "data/cache"]
  },
  "max_concurrent": 4,
  "max_attempts": 2,
  "tasks": [
    {
      "task_id": "model-a-shard-00",
      "model_class": "small-reasoning-a10080-v2",
      "argv": ["bash", "runners/unity/task.sh", "--manifest", "manifest.json", "--task", "model-a-shard-00"],
      "env": {"TRACEBENCH_PYTHON": "/absolute/remote/environment/bin/python", "PYTHONPATH": "src"},
      "resources": {
        "gpu_type": "a100",
        "gpu_count": 1,
        "constraint": "a100-80g&sapphirerapids",
        "expected_gpu_name": "NVIDIA A100-SXM4-80GB",
        "expected_gpu_memory_mb": 81920,
        "gpu_memory_tolerance_mb": 0,
        "cpus": 8,
        "memory_mb": 65536,
        "walltime_seconds": 7200,
        "partitions": ["gpu", "gpu-preempt"]
      },
      "outputs": ["results.jsonl", "summary.json", "provenance.json"],
      "depends_on": []
    }
  ]
}
```

The bundle must contain all source and input files that the task reads.
`bundle.path` names an absolute directory readable on the controller host.
The controller reads and freezes that directory when it accepts the request.
This supports multiple repositories on the same host without project registration.
Clients on another machine must first stage their bundle on the controller host or a shared mount.
The current API has no bundle upload endpoint.

Remote clients can monitor campaigns and download results through HTTP.
Submission still requires the prepared bundle to be readable by the controller.

Large model caches and Python environments remain external runtime dependencies.
The request records their paths through the runner's environment.
The controller excludes `.git`, virtual environments, `.env`, key files, caches, and compiled Python files by default.
It rejects symlinks and bundles larger than 256 MiB.
The project can add exclusion patterns.

The current A100 profile uses 81,920 MiB, measured inside allocated jobs on `gpu014`, `gpu017`, and `gpu018`.
The previous 81,151 MiB value came from a historical assumption.
It did not come from an allocated-device probe for this campaign.
The corrected profile has a new class identity and zero memory tolerance.
Older declarations and hardware locks remain intact for audit.
The project runner and controller must use the same exact memory policy.

`outputs` declares required nonempty files relative to `HPC_OUTPUT_DIR`.
Directory names do not count as required files.
The controller retrieves those files, controller metadata, and attempt logs.
It does not retrieve unrelated task output trees.
Each artifact receipt contains its digest, size, local path, and download URL.

The `files` list contains required experiment outputs.
The separate `controller_files` list contains retrieved GPU samples, hardware attestations, and attempt logs.
Download either list through its receipt's HTTP URL and check the digest.
Controller diagnostics remain optional and can include empty stderr logs.
They never satisfy a required experiment output.

Retrieved diagnostics remain available after a hardware failure, cancellation, or infrastructure retry.
The route rejects unrelated files, unobserved attempts, symlinks, and paths outside the task's result directory.

The task runs from the immutable source directory.
The controller supplies these environment values:

| Value | Meaning |
|---|---|
| `HPC_CAMPAIGN_ID` | Durable campaign identity |
| `HPC_TASK_ID` | Stable task identity |
| `HPC_ATTEMPT` | Durable attempt number |
| `HPC_OUTPUT_DIR` | Stable remote checkpoint and output directory |
| `HPC_HARDWARE_PROFILE_ID` | Scientific hardware class |
| `HPC_EXPECT_GPU_NAME` | Exact required GPU name |
| `HPC_EXPECT_GPU_MEMORY_MB` | Expected reported memory in MiB |

Callers cannot override `HPC_` environment values.
Argument values can contain `{output_dir}` and `{task_id}` placeholders.
CPU tasks use `gpu_count: 0` and omit GPU identity fields.
Dependencies release only after required files and hardware evidence pass the controller checks.

## Submit and retrieve

Review placement, then submit the same request:

```bash
scripts/hpc-campaign --url http://127.0.0.1:8301 plan request.json
scripts/hpc-campaign --url http://127.0.0.1:8301 submit request.json
scripts/hpc-campaign --url http://127.0.0.1:8301 watch formal-conjectures-small-a10080-v2
scripts/hpc-campaign --url http://127.0.0.1:8301 queue formal-conjectures-small-a10080-v2
```

Plan creation does not SSH or submit work.
The plan shows catalog age, matching nodes, rejected partitions, limits, and historical wait estimates.
The estimates describe previous workloads and can differ from this campaign.
The controller sends eligible work to Slurm immediately within its concurrency limits.

A repeated identical request returns the existing campaign.
A changed declaration or source under the same identity returns HTTP 409.
Campaign acceptance returns HTTP 202 before remote execution starts.

| HTTP route | Operation |
|---|---|
| `GET/PATCH /api/v1/backend` | Read or edit controller settings |
| `POST /api/v1/backend/probe` | Refresh the live catalog |
| `POST /api/v1/campaigns/plan` | Check a declaration without submission |
| `GET/POST /api/v1/campaigns` | List or accept campaigns |
| `GET /api/v1/campaigns/{id}` | Read tasks, attempts, evidence, and artifacts |
| `GET /api/v1/campaigns/{id}/results?after=0` | Read incremental events and result receipts |
| `GET /api/v1/campaigns/{id}/artifacts?task_id=...&path=...` | Download a declared output or retrieved controller diagnostic |
| `POST /api/v1/campaigns/{id}/cancel` | Cancel known jobs and fence waiting tasks |
| `GET /api/v1/telemetry/accounting` | Query local historical accounting |

The result cursor increases monotonically.
Clients persist `next_cursor` and resume with `after`.
The watcher prints new events and stays quiet while state remains unchanged.
Routine polls update stored measurements without adding duplicate events.
Changes to pending reasons, start hints, nodes, retry delays, and artifact transfers still produce events.

The `queue` command reads cached controller observations without SSH.
It reports live job state, pending reason, current nodes, observation time, and available Slurm start hints.
The live queue remains authoritative while Slurm lists the job.
Accounting supplies detailed measurements and terminal state after the job leaves the queue.
Slurm start hints can change.
Missing estimates remain unknown.

## Failure and recovery

The controller commits a submission intent before SSH.
Each attempt has a unique Slurm job name and remote receipt.
Each attempt retains its latest scheduler observation and final controller state.
Infrastructure retries preserve the previous attempt's terminal Slurm outcome.
The next attempt starts with a new observation history.

An SSH interruption creates an uncertain state until Slurm proves the outcome.
The controller never retries an uncertain submission blindly.

`NODE_FAIL`, `PREEMPTED`, and `BOOT_FAIL` permit bounded automatic retries.
The default budget is two attempts.
Retries use the same hardware request and checkpoint directory.
Applications must resume checkpoints safely themselves.
`FAILED`, `OUT_OF_MEMORY`, and `TIMEOUT` finish the task without automatic compute retries.

Artifact transfer has a separate retry budget.
The default budget is five transfers with a delay between attempts.
A transfer failure never repeats compute.
Missing required files or hardware evidence prevent completion.
Controller completion means that the declared files exist and hardware evidence passes.
The project remains responsible for record counts, dataset identity, and scientific evaluation checks.

## State and backups

The local store lives under `$UNITY_HPC_DATA/controller/`:

```text
backend.json
backend-catalog.json
campaigns.db
campaigns/<campaign>/declaration.json
campaigns/<campaign>/bundle.tar.gz
campaigns/<campaign>/results/<task>/
```

The SQLite database, bundles, and result files form one backup unit.
The internal journal uses SQLite schema version 2.
The public campaign schema remains version 1.

Startup migrates version 1 journals and restores recoverable observations for each current attempt.
No automatic deletion applies to campaign results.
Remote source snapshots and checkpoint directories also remain available.
The worker runs only while the controller process runs.

New requests freeze the backend settings they use.
Later settings changes do not relocate an accepted campaign.
The global task and GPU ceilings use current controller settings on every scheduling pass.
Raising the task ceiling can admit CPU grading while the GPU ceiling stays fixed.
Lowering a ceiling blocks new admissions without cancelling accepted jobs.
Each campaign's own concurrency limit remains fixed.

The catalog provides conservative admission checks for known limits.
Slurm enforces shared account usage and policy that other cluster clients can change concurrently.

## Source reuse and delivery latency

Each scheduling pass observes accepted jobs and retrieves finished outputs before admitting new work.
New admissions use the current `max_new_tasks_per_pass` and `admission_budget_seconds` settings.
Their defaults are four tasks and ten seconds.
The worker checks the time budget between operations.
An individual SSH operation can exceed that budget.

When a pass admits work and defers more eligible tasks, it starts another pass immediately.
The next pass observes existing jobs first.
Idle passes and full capacity use the normal polling interval.
An unsuccessful admission does not cause an immediate retry loop.

The remote controller reuses source snapshots by their frozen bundle manifest digest:

```text
<remote_root>/source-cache/<manifest-sha256>/source/
<remote_root>/source-cache/<manifest-sha256>/.controller-source-manifest-sha256
<remote_root>/source-cache/locks/<manifest-sha256>.lock
<remote_root>/campaigns/<campaign>/source -> <cached-source>
```

A separate lock protects publication for each digest.
Cold staging checks the archive digest, extracts into a private partial directory, and removes write permissions.
It then publishes the cache directory and campaign link atomically.
Metadata remains outside the source payload.
Warm staging requires the matching manifest marker and real cache directories.
Unexpected symlinks or mismatched markers stop staging and preserve existing files.

Existing campaign source directories continue to serve their accepted jobs.
The controller preserves those directories during upgrades.
It can reuse an interrupted legacy staging directory only when its archive marker matches exactly.
Cache reuse trusts the controller-owned, read-only snapshot after successful cold publication.
It does not reread every cached file on each admission.
This is an integrity boundary within the controller's Unix account, not isolation from that account's administrator.

The `source_staged` event records the manifest digest, source path, cache result, and elapsed staging time.
No automatic cache deletion applies.
Keep cache directories while accepted jobs or retained campaign links reference them.
Partial staging directories do not establish readiness.
Retain them for diagnosis or remove them manually after confirming no staging process uses them.

A measured batch on 2026-10-06 contained sixteen campaigns sharing 896 source files.
The previous worker staged the batch before its first job observation.
Submission receipts took 2.2–2.6 seconds, while first observations followed receipts by 94–498 seconds.
Eight completed tasks received controller completion events 73–287 seconds after Slurm completion.

The new pass order and source cache address these observed delays.
Serial observation and file retrieval can still delay delivery in large active batches.
The raw controller latency record stays in the maintainer's local research notes; the capability assessment summarizes it.

The live CPU smoke staged a two-file, 686-byte bundle in 3.640 seconds cold and 1.230 seconds warm.
Both allocations returned the same cache path and exact file digests.
This small sample checks cache publication and reuse rather than representative large-bundle performance.
The raw deployment and smoke report stays in the maintainer's local research notes.

## External runtimes

Large pinned environments and caches can exceed the campaign bundle limit.
Keep those dependencies in a separate controller-owned remote directory.
Record their versions, source revisions, file digests, and relative symlink targets before transfer.
Archive large collections of small files to reduce transfer overhead.
Verify the archive digest before extraction.

Run extraction, full file verification, and compiler verification in a GPU-free campaign allocation.
Extract into a fresh directory and activate it after extraction succeeds.
Keep existing dependency files until the new runtime passes verification.
The `runtime_integrity.py` module verifies the frozen manifest and every listed file or symlink.
The manifest itself must match its frozen digest.

File verification uses one worker by default.
`verify_tree(..., workers=1..8)` permits bounded parallel reads.
It checks every digest, preserves manifest order, and reports all mismatch counts.
Benchmark the worker count inside an allocation before enabling parallel reads on shared storage.
No measured speedup applies to untested worker counts.

An interrupted extraction can resume in its owned partial directory from the same pinned archive.
Check every listed file after resumption.
Repair interrupted files only from their matching archive members, then verify the complete tree again.
Bound repairs and retain mismatch evidence.
Reuse an existing runtime only after full verification passes.

Keep runtime verification evidence and canary outputs as required campaign artifacts.
Regenerate `launcher` paths after relocation.
Dependent evaluation tasks must wait for a successful canary.
Changing an accepted canary requires a new campaign identity and frozen bundle.

For allocation-local runtimes, use the separately pinned `controller/node_runtime.py` helper.
Its standalone bundle contains `node-runtime.py`, `runtime_integrity.py`, `lean-launcher.py`, `files.jsonl`, `runtime-lock.json`, and `archive-lock.json`.
The archive lock records exact source and Lean archive sizes and digests.

```bash
python execution/node-runtime.py --runtime-root /shared/controller/grading-runtime \
  --lock execution/runtime-lock.json --files execution/files.jsonl --output "$HPC_OUTPUT_DIR"
```

The helper checks the filesystem type and free capacity on the allocated node.
It requires a local disk filesystem and creates a private temporary directory.
It verifies both archives, extracts them, and checks the complete runtime before preparing relocated Lean paths.
The output includes the unchanged runtime lock, full verification, launcher environment, and staging measurements.
Use the same frozen helper for canary and grading allocations.

After saving results and provenance, remove only the owned temporary runtime:

```bash
python execution/node-runtime.py --cleanup-root /tmp/tracebench-runtime-OWNED
```

Cleanup requires the directory's owner and allocation marker to match the current process.
An allocation interrupted before cleanup can leave temporary files.
The retained staging artifact identifies that directory.
Never infer runtime readiness from successful transfer or extraction alone.

The formal-conjectures runtime measured this boundary on 2026-10-06.
Shared-storage extraction exhausted the first 30-minute allocation.
Resuming the owned partial directory took another 1,737 seconds before full verification began.

An independent local-disk allocation finished staging and all five unchanged canaries in 129 seconds.
It checked 126,548 entries covering 9.74 GB, with exact source and dependency revisions.
Local staging took 110.4 seconds.
Serial full verification took 34.7 seconds.
The real Mathlib canary passed in 7.4 seconds within its unchanged 60-second budget.

These observations used different nodes and cache states.
They identify shared-file access as a practical bottleneck without establishing a universal speedup.
File-digest wall time includes file opening, reading, and SHA processing.
Python CPU measurements exclude extraction subprocess CPU time.

To size future allocations, use step accounting and staging phases together.
The measured CPU canary reported a batch memory high-water mark of 13.93 GiB.
That observation does not establish memory needs for multiple concurrent proof checks.
The raw runtime and filesystem probe records stay in the maintainer's local research notes.
