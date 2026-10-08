# Two-component split: controller owns the cluster, the plugin stays thin

> **Superseded by [ADR 0009](0009-headless-campaign-controller.md).** The project ledger, `unityHPC/run.sh`, and project registration were removed. The controller-owns-the-cluster split still holds.

The plugin used to load nine skills, fourteen MCP tools, and three agent
personas into every LLM session. That put SSH, recon, fetch, watch, and
cluster telemetry into the model's context even when the user only wanted
to attach a project or submit a run. We split the system into an always-on
**controller** on this machine and a **plugin** of three skills that HTTP
to it.

The ledger contract does not move: `unityHPC/run.sh` still records every
submit, and every management tool still reads that record. The controller
is the process that calls `run.sh`. The plugin does not SSH, does not call
`sbatch`, and does not poll the queue.

## Considered options

- **Keep everything in the plugin.** Rejected: every session reloads the
  full cluster workflow, which is the overhead this change exists to cut.
- **Two git repositories.** Rejected for now: `lib/`, the scaffold, and
  `cluster-intel/` are one implementation. A monorepo with two entry
  points (`scripts/hpc-controller`, `skills/`) keeps one ledger contract
  and one test suite. Split repos later if the plugin needs to ship
  without the controller.

## Consequences

- Humans and agents share one HTTP interface. The UI is a client of that
  interface, not a second dispatcher.
- The watcher stays an opt-in foreground process. The controller is the
  always-on local service; it is not a login-node daemon.
- Old skill bodies live under `controller/ops/` as operator runbooks.
  They are not loaded into LLM sessions.
