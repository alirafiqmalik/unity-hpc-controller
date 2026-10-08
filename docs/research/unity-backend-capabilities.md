# Unity backend data capabilities

Assessment date: 2026-10-05 in America/New_York.
Live probes continued into 2026-10-06 UTC.
The initial cluster survey used existing SSH credentials and bounded read-only commands.
Later filesystem and runtime probes ran in controller-managed, GPU-free compute allocations.
Runtime preparation used controller-owned staging directories and allocation-owned temporary directories.
Read-only queries had command timeouts; compute probes had Slurm walltime limits.

The review covered the maintainer's earlier local notes (kept outside the repository in `.research_notes/temp-research/`):

| Input | Finding |
|---|---|
| `unity-cluster-point-in-time-capabilities.md` | Useful inventory. Its absolute claims about missing GPU metrics and node history need correction. |
| `unity-cluster-historical-capabilities.md` | The fixed 30–90-day retention claim lacks evidence. Step accounting and node events are queryable. |
| `unity-cluster-complete-assessment.md` | Its summary repeats those unverified limits. GPU allocation and actual utilization must remain distinct. |
| `unity-hpc-data-pipeline-analysis.md` | It correctly identifies the collector's omitted fields. `NodeList` is a Slurm field, despite one contradictory sentence. |
| `unity-hpc-data-pipeline-summary.json` | It describes an older collector. Its retention and attribution assertions require current source and live checks. |

The earlier controller coupled scheduling to project registration and a project-owned dispatcher.
The campaign interface moved that execution state into the controller, and the project-side code was removed.
The source project retains experiments, scientific evaluation, and runner adapters.

## Deployed collection evidence

The isolated backend on port 8301 collected and imported enriched telemetry at `2026-10-06T03:35:51Z`.
Its remote source is `unity:/work/pi_yourlab_umass_edu/<user>/unity-controller/cluster-intel/telemetry/`.
It uses the separate `unity-hpc-backend-v1` tmux session and completion markers.
The local data directory is `$HOME/.local/share/unity-hpc-backend-refinement`.
The existing controller on port 8300 remains separate.

The import preserved 1,706,700 historical job rows and added 6,252 enriched accounting records.
A bounded recent API page contained 613 jobs, including 417 with recorded steps.
All 16 pending formal-conjectures campaign jobs appeared with exact feature constraints.
Each requested eight CPUs, one GPU, 65,536 MiB RAM, and 7,200 seconds.
Their allocated resources remained unknown while pending.

One imported completed A100 job, `65293119`, recorded node `umd-cscdr-gpu002` and separate requested and allocated resources.
Its step reported GPU memory `26204M`, GPU utilization peak `98`, and peak host memory about 2,022 MiB.
The derived CPU efficiency was about 12.16% from 2,123 CPU seconds over 17,464 allocated CPU seconds.
These are usage measurements from that job.
They do not establish hardware equivalence with this campaign's A100 80GB class.

The controller now schedules a bounded `once` sample every 15 minutes.
It then pulls and rolls up records under the local sync lock.
The remote shell closes after 22.5 idle minutes.
No resident collector runs on the login node.
See [the backend guide](../backend-campaigns.md#collect-historical-telemetry) for configuration and history limits.

## Live observations

The cluster reported Slurm `25.11.8`, `sched/backfill`, and `select/cons_tres`.
Accounting enforcement included associations, limits, and QOS.
`PrivateData=none` permitted accounting queries for other users in tested windows.
That observation describes this account's current access.
It does not promise future access policy.

`AccountingStorageTRES` included CPU, memory, energy, disk, pages, typed GPUs, `gres/gpumem`, and `gres/gpuutil`.
`JobAcctGatherType=jobacct_gather/cgroup` and `JobAcctGatherFrequency=task=30` were visible.
`AccountingStoreFlags=job_comment,job_script` was also visible.
Script and comment retention capability does not guarantee unrestricted access to every user's content.

## What one bounded survey can read

| Source | Readable data | Limits and use |
|---|---|---|
| `scontrol show node -o` | Node CPU capacity, memory, features, state, GRES, allocated TRES, partitions | Features expose CPU families and model flags. They do not prove runtime firmware or software versions. |
| `scontrol show partition -o` | Account/group/QOS access, walltime, node sets, priority tier, preemption mode | Access decisions need account and group identity. A visible partition is not automatically usable. |
| `sinfo` | Node and partition state, CPU allocation, configured and allocated GRES | Allocation measures reserved capacity. Missing `FreeMem` stays unknown. |
| `squeue` | Pending and running jobs, requested resources, reasons, current nodes | Reasons explain present blockers. They do not guarantee a future start time. |
| `sacctmgr show assoc/qos` | Account associations, allowed QOS, job and resource ceilings | Blank fields can indicate inherited or absent limits. Slurm remains the policy authority. |
| `sshare` | Fairshare factor and effective usage | The probe recorded factor `0.386814`. This value changes with usage. |
| `sprio --user` | Weighted age, fairshare, job size, partition, QOS, and TRES priority components | Current pending-job priorities explain competition. They do not predict a guaranteed start time. |
| `sdiag` | Scheduler/backfill cycles, queue depth, controller load, and RPC statistics | These are controller counters with explicit reset boundaries, rather than permanent per-job history. |
| `scontrol show reservation -o` | Reserved nodes, resource counts, time windows, flags, and permitted accounts/users | A visible reservation does not grant access. Maintenance can restrict apparently configured capacity. |
| Unity helper scripts | GPU fleet memory/classes, accessible idle allocation, account resource usage | Noninteractive SSH needs `/modules/user-resources/bin` on PATH and `PAGER=NONE`. |
| `df`, quota tools | Mounted filesystem capacity and available quota, where permitted | Scheduler memory is RAM. It is not disk capacity or GPU memory. |
| `sstat` | Running job-step CPU and memory statistics | Access and available fields depend on job ownership and accounting settings. No historical time series is implied. |

Unity documents typed GPU requests and feature constraints in its [GPU guide](https://docs.unity.rc.umass.edu/documentation/tools/gpus/).
Its [helper guide](https://docs.unity.rc.umass.edu/documentation/jobs/helper_scripts/) explains fleet and account allocation commands.
The [sstat manual](https://slurm.schedmd.com/sstat.html) defines live step statistics.

The live catalog contained 551 visible nodes and 37 partitions in the controller's full probe.
These counts describe the probe's timestamp.
Node membership overlaps partitions, so summed partition capacity double-counts some hardware.

The additional probe record (local research notes, not shipped) preserves successful priority, diagnostic, reservation, and filesystem queries.
At `04:39 UTC`, `sdiag` reported counters since `00:00 UTC`, including 11,541 pending jobs and 4,007 running jobs.
The [diagnostic manual](https://slurm.schedmd.com/sdiag.html) defines the counters and their reset behavior.
These counts cover the cluster, rather than this account or the selected GPU class.

The priority probe returned separate rows for each candidate partition of the same pending job.
Deduplicate job identities when counting jobs across those rows.
The [priority manual](https://slurm.schedmd.com/sprio.html) describes component weights and user/job filters.
Collect these diagnostics sparingly when explaining a queue blocker.
The current scheduled collector does not archive their full output.

The reservation query exposed an active quarterly maintenance window involving 79 nodes.
Its end time was `06:38:04 UTC` on October 6.
This is timestamped policy evidence, rather than a promise that every affected node will become usable then.
The [control manual](https://slurm.schedmd.com/scontrol.html) documents reservation queries.

The login node's `/work`, `/home`, and `/scratch` mounts reported NFS-backed VAST storage.
Their `df` figures describe the mounted filesystems and do not establish this user's remaining quota.
Directory-specific `df` queries then exposed the home and PI work quotas at `04:48 UTC`.
They reported about 9.8 GiB available in the 100 GiB home quota and 266.2 GiB in the shared 1,000 GiB work quota.
These values share the probe record and can change as other group members write files.
Unity's [quota guide](https://docs.unity.rc.umass.edu/documentation/managing-files/quotas/) recommends querying the specific directory and describes small-file storage costs.
Check the controller's staging directory before large transfers.
Do not use the capacity of the mount root as an account's storage budget.

Compute-node local storage requires a probe inside an owned allocation.
Runtime extraction and verification timings must distinguish transfer throughput from shared-filesystem metadata costs.

### Complete installed field inventory

The installed clients expose 120 `sacct` fields, 52 `sstat` fields, and 117 named `squeue` fields.
The [field inventory](slurm-readable-fields-2026-10-06.json) preserves their complete lists and successful command return codes.
The queue client also exposes 51 short format codes.
A listed field does not guarantee a populated value or unrestricted visibility for every job.

Queryable fields extend beyond the scheduled collector's 25-column accounting export.
They include average CPU frequency, page and virtual-memory statistics, disk reads/writes, and available energy measurements.
Accounting also offers resource usage averages, totals, and maxima, with node/task attribution where supplied.
Other fields describe deadlines, reservations, arrays, heterogeneous jobs, dependencies, comments, and working directories.

Use those fields for targeted investigations after checking their actual values and access.
The scheduled archive currently preserves requests, allocations, exact nodes, timing, CPU/RSS, and selected GPU step maxima.
It does not silently claim to retain every queryable field.

### Additional measurements inside an allocation

NVIDIA's monitoring interface can expose device clocks, temperature, power limits, performance state, ECC counters, and active compute processes.
Actual availability depends on the GPU, driver, and access policy.
Unsupported values remain `N/A`.
Its [official reference](https://docs.nvidia.com/deploy/nvidia-smi/index.html) describes the queries and recommends stable device UUIDs.
These are potential extensions to assigned-device monitoring, rather than fields verified on every Unity node.
The current sampler archives utilization, memory, and power draw every 30 seconds.
Read device measurements only inside an owned allocation, restricted to its assigned UUIDs.
Historical device curves require prior collection.
The monitoring command does not recreate them.

## Historical data and retention

`sacct` returned job identities, users, accounts, partitions, requested TRES, allocated TRES, timestamps, exit codes, and exact node lists.
Step rows returned `MaxRSS`, `TotalCPU`, disk statistics, GPU memory, and GPU utilization where collected.
The [sacct manual](https://slurm.schedmd.com/sacct.html) defines those fields and separates allocation records from job steps.

The earlier collector used `-X`, which excludes steps.
That omitted much of the real usage evidence.
The new collector retains enriched accounting records and step measurements alongside compatibility summaries.
Requested resources remain separate from allocated resources.
`NodeList` now supplies the exact job-to-node link.

The live accounting configuration reported:

```text
PurgeJobAfter     = NONE
PurgeStepAfter    = NONE
PurgeEventAfter   = NONE
PurgeUsageAfter   = NONE
ArchiveJobs      = no
ArchiveSteps     = no
ArchiveEvents    = no
ArchiveUsage     = no
```

The [SlurmDBD manual](https://slurm.schedmd.com/slurmdbd.conf.html) defines purge and archive policy.
These values show no configured age purge for those records at probe time.
They do not establish when the current database began or whether older data survived migrations.

Bounded all-user windows returned these row counts:

| Explicit window | Job allocation rows |
|---|---:|
| 2026-07-08, 12:00–12:01 | 3,802 |
| 2026-07-15, 12:00–12:01 | 3,962 |
| 2026-08-01, 12:00–12:01 | 3,976 |
| 2026-08-15, 12:00–12:01 | 5,186 |
| 2026-09-01, 12:00–12:01 | 2,091 |
| 2026-09-06, 12:00–12:01 | 5,590 |
| 2026-09-15, 12:00–12:01 | 5,221 |
| 2026-10-01, 12:00–12:01 | 6,106 |
| 2026-07-01, 12:00–12:01 | 0 |
| 2026-04-01, 12:00–12:01 | 0 |
| 2026-01-01, 12:00–12:01 | 0 |
| 2025-10-01, 12:00–12:01 | 0 |
| 2024-10-01, 12:00–12:01 | 0 |

Slurm selects jobs that overlap the interval.
These counts are not submissions within one minute.
Empty windows do not prove a retention cutoff.
They can also reflect absent jobs, database migration, or historical visibility differences.
The tested accessible history reaches July 8, 2026.
The full earliest retained timestamp remains unestablished.
The four additional probes each completed successfully within their 20-second command budget.
Their exact arguments, return codes, counts, and durations appear in [the probe record](accounting-window-probe-2026-10-06.json).

The preserved controller archive separately contains rows from July 8 through October 6, 2026.
At `2026-10-06T04:05:40Z`, it contained 1,707,429 job rows and 6,981 enriched accounting records.
Archive availability and current Slurm query visibility are different evidence.
An archive does not prove that Slurm still exposes every corresponding record.

`sreport cluster utilization` returned daily aggregate CPU usage for October 4–5.
The [sreport manual](https://slurm.schedmd.com/sreport.html) describes aggregate reports and TRES selection.
These reports supplement job accounting rather than replace per-job evidence.

`sacctmgr show event` returned node DRAIN and BOOT events, reasons, start times, and end times.
Examples included an operating-system reboot, an InfiniBand failure, and a bad GPU state.
The [sacctmgr manual](https://slurm.schedmd.com/sacctmgr.html) defines node events and accounting access.
Thus Slurm exposes some historical node events.
Those events do not reconstruct every free/allocated transition or historical available memory.

## GPU allocation versus actual use

`AllocTRES` identifies allocated GPU type and count.
It does not describe computational utilization.
`TRESUsageInMax` on sampled job steps contained actual recorded GPU metrics:

| Job step | Allocated hardware | Recorded high-water evidence |
|---|---|---|
| `65009754.batch` | One A100 | `gres/gpumem=6130M`, `gres/gpuutil=42` |
| `65069626.batch` | One A100 | `gres/gpumem=74844M`, `gres/gpuutil=100` |
| `65070742_1.batch` | Four 2080 Ti GPUs | `gres/gpumem=25278M`, `gres/gpuutil=375` |
| `65167883.batch` | One A100, seven-second failed job | `gres/gpumem=0`, `gres/gpuutil=0` |

Slurm can sum GPU utilization across devices in step accounting.
The value `375` does not mean one device exceeded 100 percent.
The [GRES manual](https://slurm.schedmd.com/gres.html) documents GPU memory/utilization accounting and its device limitations.
These accounting summaries do not supply per-second curves.
Missing records remain unknown.

New controller jobs record their assigned GPU UUIDs, exact name, reported memory, node, and driver before execution.
They can sample utilization, memory, and power every 30 seconds inside the allocation.
The sampler restricts itself to attested assigned UUIDs.
The controller does not run GPU probes on arbitrary compute nodes without an allocation.

## Exact hardware and accessible placement

The scientific A100 profile requires `a100-80g&sapphirerapids` and `NVIDIA A100-SXM4-80GB` with 81,920 reported MiB.
The 81,151 MiB value in the first campaign was a historical assumption.
No allocated-device probe established that value for this campaign.
Live job attestations on `gpu014`, `gpu017`, and `gpu018` measured 81,920 MiB.
The corrected class is `small-reasoning-a10080-v2` with zero memory tolerance.
The previous class and declaration remain immutable audit records.

Typed `gpu:a100:1` alone also matches different A100 memory variants.
The controller therefore combines typed GRES, features, and device evidence.
An optional node list or expected UUID can impose a stricter physical-device policy.

### Live execution and recovery evidence

The controller restarted while campaign `formal-conjectures-bench-v1-10pct-small4-1067e3fd` held accepted jobs.
Its durable journal retained those identities and reconciled queue and accounting state after the restart.
The controlled restart loaded telemetry session isolation without resubmitting accepted attempts.

The first jobs passed the controller's device-name check and its original 1,024 MiB memory tolerance.
Their attestations recorded this evidence:

| Slurm job | Task model | Node | Reported GPU memory | Driver |
|---|---|---|---:|---|
| `65296126` | Qwen3-0.6B | `gpu014` | 81,920 MiB | `580.178.04` |
| `65296127` | R1-Distill-Qwen-1.5B | `gpu014` | 81,920 MiB | `580.178.04` |
| `65296128` | Qwen3-1.7B | `gpu017` | 81,920 MiB | `595.91.07` |
| `65296129` | Qwen3-4B | `gpu018` | 81,920 MiB | `595.91.07` |

Every listed device reported `NVIDIA A100-SXM4-80GB`.
Attestations also preserve the assigned GPU UUID, task identity, and attempt number.
Driver versions differ across these nodes and remain part of runtime provenance.
The hardware class does not currently pin the driver version.

The project runner then rejected the measured memory because its duplicate check required exactly 81,151 MiB.
Retrieved stderr records identify `tracebench.workflow.hardware_info` and the GPU memory mismatch.
The application stopped before generation, so these attempts produced no evaluation results.

The controller retained logs and attestation evidence and marked missing required outputs as failed.
It did not retry application failures automatically.
The journal contains 21 distinct submitted jobs, each with attempt number one.

Cancellation fenced the remaining work in this campaign.
Its terminal state contains five failed tasks and 31 cancelled tasks.
The corrected release uses a new campaign and hardware class while preserving the original evidence.

Nodes `gpu013`–`gpu024` exposed the required features.
They belong to `gpu-preempt` and `superpod-a100`.
The current `gpu` partition also contains `gpu022`–`gpu024`.
`superpod-a100` explicitly excludes this account through its account allowlist.
The controller must not recommend that partition merely because its devices are visible.

The live `gpu` and `gpu-preempt` maximum walltime was 14 days.
Their preemption modes were `OFF` and `REQUEUE` respectively.
The user association allowed `normal`, `long`, and `short` QOS.
`normal` and `long` exposed 1,000 jobs and 2,000 submissions per user.
`short` exposed a four-hour ceiling, a two-node limit, and one submission per user.

The controller records these ceilings and checks the request against them.
Other users can consume shared capacity after the observation.

## How the backend uses these data

The planner first filters by access, exact hardware, CPU, memory, node restrictions, and walltime.
It ranks only eligible partitions by measured wait history.
The report includes catalog age, sample counts, and uncertainty.
A100 aggregate history can include other memory variants or workloads.
It is a coarse scheduling signal, not experimental comparability evidence.
The current estimate uses up to 500 completed allocations from the last 30 days per partition and GPU type.
Pending, cancelled, and never-started jobs do not contribute to those completed-job percentiles.
This selection can understate difficult waits.
The planner reports sample counts and leaves missing estimates unknown.

The controller submits eligible work immediately within persistent campaign and controller limits.
Slurm's backfill scheduler selects actual start times.
Short checkpointed shards reduce recovery loss and create more scheduling opportunities.
Project measurements can later tune shard size, CPU, memory, and walltime.
The controller does not silently edit scientific hardware or generation parameters.

The worker records submission intent, accepted job identity, terminal observation, transfer state, and artifact checks separately.
Infrastructure failures consume a bounded retry budget.
Uncertain submissions never trigger blind retries.
Result events allow each project to ingest completed files as they arrive.

The durable attempt journal links Slurm `job_id` values to campaigns and tasks.
Join enriched accounting through that identity for experiment attribution.
Dataset, model, and generation parameters come from the frozen project manifest.
Raw cluster accounting cannot infer them from arbitrary job names.

Availability curves require the local forward archive of `sinfo` snapshots.
Fairshare and queue trends also require snapshots.
Historical jobs and node events cannot recover every missing point.
Per-user resource hours must integrate elapsed time and allocated resource counts.
They must not confuse job counts, GPU seconds, CPU seconds, or busy fractions.

### Decisions from the first completed response shard

The corrected Qwen3-0.6B shard returned 32 responses from job `65296727` on `gpu014`.
It used 486 Slurm allocation seconds and 165.47 seconds attributed to generation batches.
The 320.53-second difference includes environment loading, model setup, compilation, I/O, and teardown.
The measurements do not isolate any one phase.
The controller retrieved 17 GPU samples and verified their assigned UUID.

These measurements justify preparation and cache work before increasing GPU concurrency.
Pinned environments and model caches remain reusable external runtime dependencies.
CPU preparation and proof checking use GPU-free campaign tasks.
Proof checks therefore do not retain a GPU allocation after responses finish.
Larger inference batches require a separate measured experiment with a frozen configuration.
They must not change midway through this comparison.

The sampled GPU memory reached about 73,000 MiB for both completed small-model shards.
The configured vLLM engine reserves memory for its KV cache.
That sample does not measure model weights alone or establish the minimum memory requirement.
Future resource tuning must separate model weights, cache reservation, active token budget, and measured peaks.
Sample means also need phase boundaries and sampling intervals.
They do not directly establish a time-weighted utilization value for the entire allocation.

### Decisions from CPU runtime measurements

Compute allocations exposed writable ext4 scratch under `/tmp` and `/var/tmp`.
The project runtime on `/work` used NFS storage.
The shared attempt spent 1,737 seconds resuming source extraction.
Its full verification remained unfinished when the controller cancelled the superseded job.
A separate allocation staged SHA-pinned archives on local scratch and verified all 126,548 runtime entries.
It also passed the five unchanged Lean checker tests and finished in 129 Slurm seconds.
Runtime staging took 110.4 seconds, including 34.7 seconds for full file verification.
The runtime evidence record (local research notes, not shipped) retains both attempts and their phases.
The filesystem probe record (local research notes, not shipped) distinguishes local disk from shared storage and memory-backed scratch.

The attempts used different nodes and cache states.
Their timings support allocation-local staging for this campaign without establishing a controlled storage speed comparison.
Per-allocation setup remains measurable overhead.
Future runners can group several CPU grading shards in one allocation to reuse a verified runtime.
Such grouping must retain each shard's checkpoint, result identity, and evaluation provenance.
CPU and memory requests also need separate tuning from the fixed scientific generation and proof-checking budgets.

### Decisions from controller scheduling measurements

Sixteen grading campaigns shared the same frozen bundle: 896 files and 29.98 MB of source.
The previous scheduling pass staged new campaigns before observing accepted jobs.

Submission receipts took 2.2–2.6 seconds.
Their first observations followed 94–498 seconds after those receipts.
Eight tasks received controller completion events 73–287 seconds after Slurm completion.
The controller latency record (local research notes, not shipped) retains exact journal and scheduler timestamps.
It includes scoped process categories and timings, without command arguments.

The deployed controller now observes and retrieves accepted work before admitting new tasks.
Admission work uses a count limit and a time budget checked between operations.
An operation already in progress can exceed that budget.
After progress with eligible deferred tasks, the worker starts another observation pass immediately.
Idle or full-capacity passes use the normal polling interval.

Identical frozen source manifests now share a controller-owned, read-only remote snapshot.
Publication uses an atomic directory activation and a lock for each manifest digest.
Warm reuse checks the matching marker and real cache directories before linking the new campaign source.
Existing accepted campaign directories remain in place.
The [backend guide](../backend-campaigns.md#source-reuse-and-delivery-latency) documents cache retention and its account-level trust boundary.

A sequential CPU smoke checked two files totalling 686 bytes through the live controller.
Cold staging took 3.640 seconds; warm staging took 1.230 seconds.
Both one-second jobs returned the same resolved cache path and exact checker and payload digests.
Their required files and controller evidence passed HTTP size and SHA-256 checks.
The deployment and smoke report (local research notes, not shipped) also verifies preserved journal identities and source directory inodes.

This tiny smoke checks protocol behavior rather than representative 896-file staging performance.
It does not establish large-batch delivery latency after deployment.
Serial job observation and artifact retrieval remain potential delays when many tasks finish together.
Measure those phases before changing transport concurrency or grouping CPU shards into fewer allocations.

## Bounded operator queries

Use `whoami` for the remote username.
The inherited `$USER` value produced empty user history in an initial probe.
Use explicit date intervals and restricted accounts before wider historical queries.

```bash
timeout 25 sacct -u "$(whoami)" -S 2026-10-01 -E 2026-10-02 -P -n \
  -o JobID,User,Account,Partition,NodeList,ReqTRES,AllocTRES,Submit,Start,End,ElapsedRaw,TotalCPU,MaxRSS,TRESUsageInMax

timeout 25 sacctmgr -n -P show event \
  Start=2026-10-05T20:00 End=2026-10-05T21:00 \
  format=Cluster,NodeName,Start,End,State,Reason

timeout 15 sacctmgr show configuration
timeout 25 sreport -n -P cluster utilization Start=2026-10-04 End=2026-10-05 -t Hours
```

An optional historical import must use bounded daily chunks and durable progress.
The existing collector's seven-day automatic window protects the login node from unbounded recovery queries.
Older queries remain possible through explicit operator backfills.
Cluster staging retention and local archive retention are separate from SlurmDBD retention.
