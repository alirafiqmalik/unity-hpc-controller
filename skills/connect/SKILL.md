---
name: connect
description: Check a project's portable experiment runner against the headless Unity controller. Use when preparing a new runner or migrating old project registration.
---

# Prepare a portable runner

Announce the use of unity-hpc:connect to prepare the experiment runner.

1. Read controller health with `mcp__unity-hpc__unity_doctor`.
   If unavailable, start the installed `scripts/hpc-controller`, then repeat the health check.
2. Read the project's experiment command and runner documentation.
   Keep cluster configuration inside the existing runner directory.
3. Build the project's immutable source bundle and campaign JSON with its runner command.
   For a new adapter, read [the campaign contract](../../docs/backend-campaigns.md).
4. Call `mcp__unity-hpc__unity_campaign_plan` with the absolute `specification_path`.
   Resolve reported source, resource, access, or hardware errors.

Preparation is complete when the plan reports `ready: true` and identifies the frozen source and compatible hardware.
Submission requires the user's experiment instruction. Preparation alone authorizes no experiment.
The controller has no project registration and writes no scaffold into the project.
