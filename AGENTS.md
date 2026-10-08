# AGENTS.md

Guidance for coding agents working in this repository.

## Read first

- `CONTEXT.md`: the glossary. Use its terms; the "Retired terms" list names words to avoid.
- `ARCHITECTURE.md`: ownership, execution flow, data stores, and limits.
- `docs/adr/0009-headless-campaign-controller.md`: the current contract. ADRs 0001, 0002, 0006, and 0008 are superseded; read them only for history.
- `docs/backend-campaigns.md`: the HTTP routes, the campaign JSON, and operator procedure.
- `docs/research/unity-backend-capabilities.md`: what the cluster exposes, with its measurement limits. Do not claim data this file marks unknown.

## Shape of the repository

- `controller/campaign_*.py`, `controller/campaigns.py`: the headless campaign service.
- `controller/telemetry.py`, `controller/cluster_session.py`, `controller/snapshot.py`, `cluster-intel/`: bounded telemetry collection and the local archive.
- `mcp/hpc_server.py`, `skills/`: agent clients. Every MCP tool is an HTTP call to the controller.
- `scripts/hpc-controller`, `scripts/hpc-campaign`: service and command clients.

There is no dashboard, no project registration, no scaffold template, and no agent persona.
Do not add project-side dispatchers; projects talk to the controller through their runner and campaign JSON.

## Rules

- GPU allocation counts and step high-water marks are not time-weighted utilization. Name them as allocation or peaks.
- Never put the maintainer's account, remote path, email, or home directory into shipped files. `tests/test_shipping_safety.py` enforces placeholders.
- Bump the version in both plugin manifests when shipped code changes. `scripts/release-check` enforces this.
- Never delete a branch whose name matches `bkup/*`. Create a `bkup/*` branch only when the user explicitly asks.

## Agent skills

Issues live in this repo's GitHub Issues, driven via the `gh` CLI. See `docs/agents/issue-tracker.md`.
Triage label strings are in `docs/agents/triage-labels.md`.
Domain docs conventions are in `docs/agents/domain.md`.
