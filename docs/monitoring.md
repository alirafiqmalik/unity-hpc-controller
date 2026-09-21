# Cluster monitoring — recommendations

The controller dashboard is a Datadog-style operator view built with
no extra runtime dependencies. This note is the stack we would add,
and why the first cut stays stdlib.

## What the first cut shows

Same sources the cluster-intel dashboard already reads:

| Panel | Source | Pattern |
|---|---|---|
| GPU / node KPIs | `snapshot.csv` | live poller, 15 min |
| Partition cards | `cluster-config.json` | recon merge |
| Queue trend | `snapshot.csv` | sparkline |
| Job table | per-project ledgers | campaign rows + telemetry join |
| Usage / heatmap | `summaries.db` | rollup |
| Activity feed | `controller/events.jsonl` | append-only |
| Project cards | `controller/projects.json` | registry |
| Retrieval panel | `controller/telemetry.json`, `controller/telemetry-runs.jsonl` | on-demand pull + schedule |

`snapshot.csv` and `summaries.db` are local copies. The Settings tab starts the
retrieval that fills them, and reports how old each one is. ADR 0003 has the
design.

Degrade to an empty state when a source is missing (I6). Poll `/api/v1/*`
every 10s from the browser. No WebSocket in v0.12 — Tailscale and a
stdlib server keep HTTP + JSON.

## Patterns taken from SaaS monitors

- **KPI strip + delta** on the overview (Datadog, Grafana)
- **Status pills** with a live dot on running jobs
- **Heatmap** for node / GPU util
- **Faceted job table** (all / running / pending / failed)
- **Drawer / modal** for one entity, not a new route
- **Activity feed** as the audit log of controller actions
- **Empty states that name the command** which populates the panel

## If we outgrow stdlib

Add these only when a panel's source is already collected. Do not
scrape the login node from a new exporter without an explicit opt-in
(G4, RC-5).

| Need | Tool | Notes |
|---|---|---|
| Time-series store | Prometheus + `slurm-exporter` | scrape from this machine, not the login node |
| Dashboards / alerts | Grafana + Alertmanager | link a panel from a job drawer |
| Experiment metrics | MLflow or the existing `metrics.json` | the core stays metric-agnostic |
| Tailnet serve | `tailscale serve` | already the dashboard pattern; never Funnel |
| Always-on | systemd `--user` | `hpc-controller install-user-service` |

Grafana is the right next UI kit if the stdlib page is no longer
enough: it already matches the dark operator aesthetic, and it can
read Prometheus without replacing the controller's dispatch API.

## What we will not add in this cut

- LLM API tokens in the UI
- A second job writer besides `run.sh`
- In-job streaming metrics (see `docs/design-decisions.md` §4)
- Public internet exposure (`tailscale funnel`)
