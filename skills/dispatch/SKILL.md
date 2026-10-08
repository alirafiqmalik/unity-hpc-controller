---
name: dispatch
description: Plan or submit an experiment campaign through the headless Unity controller, then read incremental results. Use for experiment runs, dataset/model matrices, or continuation.
---

# Dispatch an experiment campaign

Announce the use of unity-hpc:dispatch to submit through the controller.

1. Use the project's runner to build campaign JSON from its experiment YAML.
   For a new adapter, read [the campaign contract](../../docs/backend-campaigns.md).
2. Call `mcp__unity-hpc__unity_campaign_plan` with the absolute `specification_path`.
   Resolve errors before submission. A plan never submits jobs.
3. If the user authorized the experiment, call `mcp__unity-hpc__unity_campaign_submit` with that same file.
   Preserve its `campaign_id`. Resending the same declaration is idempotent.
4. Read `mcp__unity-hpc__unity_campaign_status` for the accepted campaign.
   Consume `mcp__unity-hpc__unity_campaign_results` pages, saving each `next_cursor` for the next read.
5. Use the project runner's collection command to retrieve and assemble declared results.
   Keep scheduler completion, artifact retrieval, and scientific evaluation outcomes separate.

The controller owns remote submissions, reconciliation, retries, and artifact retrieval.
An uncertain submission requires reconciliation. A fresh campaign can duplicate expensive work when an existing attempt remains uncertain.
Report completion only after you retrieve every required result and the project validates its expected sample count.
Report failures and unresolved evaluations as recorded outcomes.
