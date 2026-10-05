---
name: connect
description: "Attach this project to the Unity HPC controller: scaffold unityHPC/ if missing, register the directory, write the client stub. Use when bootstrapping a project or connecting it so runs go through the controller."
---

# unity-hpc:connect

Announce: "Using unity-hpc:connect to attach this project to the controller."

Do the steps in order. Every step is safe to re-run.

**1. Check controller health**

```bash
curl -sS "${UNITY_CONTROLLER:-http://127.0.0.1:8300}/api/v1/health"
```

If this fails, tell the user to run `hpc-controller`. That starts the controller in the background and publishes it over Tailscale. Stop.

**2. Inventory the project and connection**

Read existing project guidance, source entrypoints, inputs, output schemas, and
bounded checks. Preserve the working tree. `git rev-parse --is-inside-work-tree`
can identify a Git project; attachment does not require changing its branch.

Use existing configuration or the task's accepted resource choice. New primitives
are `cpu`, `gpu`, `multi-cpu`, and `multi-gpu`. ML is an application category;
legacy `ml` remains accepted and maps to coordinated ranks. Existing `multi-gpu`
means independent experiments unless an explicit mode selects coordinated ranks.
Preview compatibility migration before changing an existing runtime default.

Declare implemented operations and typed workflows in `unityHPC/project.json`
(schema version 1), mapping current project paths. Use deterministic choice
readers for existing registries; preserve their exclusions. Register project
checks and analyses, and show missing capabilities instead of inventing them.
Source paths must cover imported project modules and configuration. Declare
immutable input identities and an environment reference without copying secrets.
Ask only when a scientific assumption or product scope remains unresolved.

**3. Generate the scaffold via hpc-scaffold**

Keep the existing noninteractive flags. For an agent or CI:

```bash
UNITY_HPC_NONINTERACTIVE=1 \
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/hpc-scaffold" \
  --type <cpu|gpu|ml|multi-cpu|multi-gpu> \
  --account <slurm-account> \
  --remote-dir <remote-project-dir> \
  --job-command '<command>' \
  --collector skip \
  --write-guidance
```

Dry-run first, then apply. Existing `.env`, `sync.sh`, and `fetch.sh` remain
project-owned; replacement of other handwritten scaffold files preserves an
append-only copy in `unityHPC/.pre-redesign/`. Full `.env` flags:
`controller/ops/setup.md`. Keep source, inputs, artifacts, connection declarations,
and custom adapters in place.

Copying the sample scripts is **opt-in**: ask the user before putting `collector.sh` and `collector_parse.py` on the login node. Default skip. Do not start `collector.sh loop`. The controller opens a tmux session when a schedule runs, and that session closes after a quiet period. Details: `controller/ops/setup.md`. Use `--collector deploy` only when authorized.

**4. POST attach**

```bash
curl -sS -X POST "${UNITY_CONTROLLER:-http://127.0.0.1:8300}/api/v1/projects" \
  -H 'Content-Type: application/json' \
  -d "{\"slug\":\"<slug>\",\"path\":\"$(pwd)\",\"primitive\":\"<cpu|gpu|ml|multi-cpu|multi-gpu>\"}"
```

**5. Confirm `unityHPC/controller.json` was written.**

**6. Validate the declared connection**

Read `GET /api/v1/projects/{slug}/connection`. Resolve structured declaration
errors, then run registered bounded fixture/mock checks. Check argument quoting,
isolated output paths, and generated scripts without submitting cluster work.
Repeat setup and verify custom adapters and environment remain unchanged.

Done when health is OK, `controller.json` exists, the project endpoint returns
this directory, and the connection exposes implemented workflows with no errors.
For a legacy project without a workflow declaration, report attachment as legacy
compatibility and list the missing connection capabilities.
