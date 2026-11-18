# Controller

The controller accepts portable experiment campaigns and owns their execution on Unity.
It records source snapshots, submission intents, hardware locks, attempts, scheduler observations, and artifact receipts.
Projects keep scientific methods and evaluations in their own portable packages.
Only their runner directory contains Unity-specific translation.

```bash
scripts/hpc-controller --fg --no-tailscale --port 8301
scripts/hpc-campaign --url http://127.0.0.1:8301 configure backend.json
scripts/hpc-campaign --url http://127.0.0.1:8301 probe
scripts/hpc-campaign --url http://127.0.0.1:8301 plan request.json
scripts/hpc-campaign --url http://127.0.0.1:8301 submit request.json
scripts/hpc-campaign --url http://127.0.0.1:8301 watch campaign-id
```

The service needs no Node installation and serves no browser page.
The controller binds to loopback by default.
Its existing background process, user service, and Tailscale options remain available.
SSH authentication uses the controller's configured alias and identity.

The [campaign guide](../docs/backend-campaigns.md) defines the declaration, HTTP routes, state, and operator procedure.
The [capability assessment](../docs/research/unity-backend-capabilities.md) records available live and historical cluster data.
[ADR 0009](../docs/adr/0009-headless-campaign-controller.md) records the migration decision.

| Module | Responsibility |
|---|---|
| `campaign_contract.py` | Portable declaration checks and immutable bundle snapshots |
| `campaign_store.py` | Campaign journal: the only code that opens `campaigns.db`; one transaction for each named operation; snapshot reads; schema setup once per process |
| `campaign_planner.py` | Exact hardware fit, access, ceilings, and historical placement signals, checked against the Catalog that the caller passes |
| `catalog.py` | Catalog: turns the survey output into a Catalog, stores it atomically and reads it, freshness at a given time, and the refresh schedule |
| `cluster_access.py` | Cluster access: SSH alias and identity, the one SSH option set, agent and keyring restore, remote commands and rsync transfer; a local-shell transport for tests |
| `campaign_slurm.py` | Slurm protocol over Cluster access: atomic staging, job scripts that carry the Attestation, Slurm receipts, artifact retrieval, and the Catalog survey command |
| `hardware_class.py` | Hardware class: fingerprint, hardware lock and bind rule, evidence file names, and the controller check of an Attestation; no IO after import |
| `attestation.py` | In-job Attestation and the match rule that the controller also uses; standard library only; job scripts carry its text |
| `campaign_lifecycle.py` | Task, attempt, and campaign states; transitions, retry budget, backoff, and Result event payloads; no IO |
| `campaigns.py` | Worker passes: reconciliation, admission, retrieval, and cancellation; a campaign's failure is recorded on it and the pass goes on; one clock for the pass; slurm_adapter() gives a campaign its Slurm adapter |
| `campaign_cli.py` | HTTP-only operator client |
| `telemetry.py` | Existing optional telemetry archive schedule |
| `http.py` | HTTP request seam |
| `serve.py` | Socket adapter and process lifecycle |
| `cluster_session.py` | Cluster session: the login-node tmux protocol for scheduled telemetry samples |
| `events.py` | Controller event log |

The task worker remains independent of a browser or agent session.
Its catalog refresh runs at the first pass with work and then every 15 minutes while campaigns need work.
Its default scheduler poll runs every 30 seconds.
No controller process remains on a login node.
Scientific commands run only inside Slurm allocations.

