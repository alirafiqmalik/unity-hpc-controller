# Migration plan — plugin to controller + thin skills

Roadmap for the 0.11.1 plugin into the two-component shape. Each step
is a shippable commit. The ledger contract does not change between
steps.

## 1. Record the split

- ADR `docs/adr/0001-two-component-split.md`
- Glossary terms: Controller, Attached project, Dispatch, Plugin
- Architecture and this plan

Done when those files exist and the old invariants in
`ARCHITECTURE.md` still describe `run.sh`.

## 2. Controller HTTP + registry

- `controller/` package, stdlib only
- Registry of attached projects (flock + atomic write, I4)
- Snapshot reads of the shared tier (empty on missing data, I6)
- Dispatch / cancel / fetch / sync by calling `run.sh`
- Event log at `$UNITY_HPC_DATA/controller/events.jsonl`

Done when `tests/test_controller_*.py` pass without a live cluster.

## 3. CLI + Tailscale

- `scripts/hpc-controller` serves the API and UI
- `--tailscale` binds localhost and runs `tailscale serve`
- Optional systemd user unit for always-on

Done when `hpc-controller --help` documents host, port, and Tailscale,
and a local GET `/api/v1/health` succeeds.

## 4. Dashboard UI

- Retrofit `unity-hpc-controller-ui.html` into `controller/ui/index.html`
- Drop LLM API-token spokes
- Attach page lists a card per attached project
- A card opens a modal: configure, run, stop, fetch, monitor

Done when the UI is served from the controller and talks only to
`/api/v1/*`.

## 5. Thin plugin catalog

- Skills become `connect`, `dispatch`, `doctor`
- Old skill bodies move to `controller/ops/`
- Skill tests retarget those paths
- MCP keeps the existing tools; skills stop being the path that SSH

Done when a fresh plugin load shows three skills and the old tests
still pass.

## 6. Docs cutover

- `README.md` and `ARCHITECTURE.md` lead with the controller
- Version `0.12.0`
- `cluster-intel/dashboard` stays as the historical telemetry page
  (`hpc-dashboard`, :8787). The controller is the operator UI (:8300).

## What does not move

- `unityHPC/run.sh` ledger writes
- I1–I9
- Typed scaffolds (`cpu` `gpu` `ml` `multi-cpu` `multi-gpu`)
- `cluster-intel/` collector, sync, rollup
- Metric-agnostic core

## Rollback

Revert to 0.11.1. Attached-project state is only
`$UNITY_HPC_DATA/controller/`. Project ledgers and `unityHPC/` scaffolds
are untouched.
