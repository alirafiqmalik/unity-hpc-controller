# Unity HPC controller

Version 0.16.0. A headless controller runs experiment campaigns on Unity Slurm.
A project sends an immutable source bundle and declared tasks.
The controller handles placement, SSH, Slurm, retries, state recovery, and result retrieval.

Experiment code stays independent of the cluster.
A project keeps its hardware adapter in one runner directory.
Projects do not register local directories and receive no generated dispatcher.

## Start the service

```bash
scripts/hpc-controller
scripts/hpc-controller --status
```

The default interface is `http://127.0.0.1:8300/api/v1`, on the loopback interface only.
Startup needs Python, SSH, and rsync. There is no browser page and no Node build.
Backend configuration defines the SSH host, Slurm account, remote root, and permitted partitions.
Read [backend operations](docs/backend-campaigns.md) for configuration commands and the campaign JSON contract.

## Submit and collect

Use a project's runner to compile experiment YAML into a campaign declaration.
The declaration names an immutable bundle, argument vectors, exact resource requests, dependencies, and required output files.

```bash
scripts/hpc-campaign plan /absolute/path/campaign.json
scripts/hpc-campaign submit /absolute/path/campaign.json
scripts/hpc-campaign status campaign-id
scripts/hpc-campaign results campaign-id
```

Planning checks policy and hardware fit without submitting jobs.
Resending an identical declaration uses the existing campaign identity.
The service continues work after the submitting agent exits.
Results have durable cursors, so clients resume collection without duplicating events.

The MCP tools expose the same HTTP interface:
`unity_campaign_plan`, `unity_campaign_submit`, `unity_campaign_status`,
`unity_campaign_results`, `unity_campaign_cancel`, `unity_backend`,
`unity_accounting`, and `unity_doctor`.
The `connect`, `dispatch`, and `doctor` skills use those tools.

## Hardware consistency

GPU tasks declare a model class, typed GPU resource, exact device name, memory size, and node features.
The controller preserves each class's hardware lock across campaigns.
An in-job check records the assigned device and rejects mismatches before experiment code runs.
Compatible partitions can change without changing the hardware class.
Historical results retain their original hardware provenance.

## Telemetry and scheduling

Live probes read nodes, partitions, access rules, account/QOS limits, queue state, and fair share.
Accounting reads retain requested resources separately from actual allocations.
Job-step records provide CPU, memory, and configured GPU accounting high-water marks.
Those marks are not time-weighted utilization, and the archive never presents them as such.
Node-event records describe recorded transitions, rather than a complete history of idle capacity.

The planner checks hardware fit and resource ceilings, then ranks compatible partitions using measured wait history.
It submits eligible work promptly and lets Slurm backfill determine start times.
Queue estimates carry sample counts and measurement limits.
The controller does not substitute another GPU model to shorten a wait.

Read [the verified capability assessment](docs/research/unity-backend-capabilities.md) for available fields, visibility, history, and collection gaps.

## Source layout

- `controller/campaign*`: declarations, journal, placement, Slurm transport, worker, and HTTP routes.
- `controller/telemetry.py`, `controller/cluster_session.py`, `controller/snapshot.py`: scheduled telemetry sessions and read-only cluster views.
- `cluster-intel/`: bounded collection, parsers, retention, and durable local summaries.
- `lib/queries.py`: read-only accounting and usage queries.
- `scripts/hpc-controller` and `scripts/hpc-campaign`: service and command clients.
- `mcp/hpc_server.py` and `skills/`: agent clients of the controller.

Read [architecture](ARCHITECTURE.md) and [ADR 0009](docs/adr/0009-headless-campaign-controller.md) for ownership and migration decisions.

## Removed surfaces

Version 0.16.0 removed the project registry, generated scaffolds, workspace APIs, dashboards, agent personas, and operator runbooks.
Existing data directories keep their old files. The controller reads only the campaign journal and the telemetry archive.
Git history before 2026-10-08 holds the removed code.

## Verification

```bash
python -m pytest -q
scripts/release-check
```

The suite covers journal recovery, uncertain submissions, bounded retries, hardware locks, artifact retrieval, policy checks, telemetry collection, and the shipping guards.
