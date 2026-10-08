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
| `campaign_store.py` | SQLite journal, attempts, hardware locks, and result cursors |
| `campaign_planner.py` | Exact hardware fit, access, ceilings, and historical placement signals |
| `campaign_slurm.py` | Bounded SSH, atomic staging, Slurm receipts, device checks, and artifact transfer |
| `campaigns.py` | Durable progression, reconciliation, bounded retries, and cancellation |
| `campaign_cli.py` | HTTP-only operator client |
| `telemetry.py` | Existing optional telemetry archive schedule |
| `http.py` | HTTP request seam |
| `serve.py` | Socket adapter and process lifecycle |
| `cluster_session.py` | Login-node tmux session for scheduled telemetry samples |
| `snapshot.py` | Read-only cluster, queue, and usage views over the local archive |
| `node_runtime.py`, `runtime_integrity.py` | Compute-node runtime staging and digest checks |
| `events.py` | Controller event log |

The task worker remains independent of a browser or agent session.
Its catalog probe runs every 15 minutes while campaigns need work.
Its default scheduler poll runs every 30 seconds.
No controller process remains on a login node.
Scientific commands run only inside Slurm allocations.

