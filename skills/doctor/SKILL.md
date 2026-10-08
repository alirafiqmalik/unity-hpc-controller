---
name: doctor
description: Check headless controller health, backend configuration, catalog freshness, or campaign failure. Use for unavailable controllers or rejected experiment placement.
---

# Check the controller

1. Call `mcp__unity-hpc__unity_doctor` for controller health.
   If unavailable, start the installed `scripts/hpc-controller`, then repeat the health check.
2. Call `mcp__unity-hpc__unity_backend` with `action: status`.
   Check the SSH host, account, remote storage, permitted partitions, and hardware catalog age.
3. For stale catalog errors, call `mcp__unity-hpc__unity_backend` with `action: probe`, then repeat campaign planning.
4. For an accepted campaign, read `mcp__unity-hpc__unity_campaign_status` with its `campaign_id`.
   Report recorded errors and uncertain attempts before making another submission.

The controller needs no project registration and no project-owned dispatcher.
Read [backend operations](../../docs/backend-campaigns.md) for configuration and recovery commands.
