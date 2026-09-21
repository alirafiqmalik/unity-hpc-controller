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

If this fails, tell the user to run `hpc-controller` or `hpc-controller --tailscale`. Stop.

**2. Get the primitive**

Ask for `cpu`, `gpu`, `ml`, `multi-cpu`, or `multi-gpu`. Do not guess; default `cpu`.

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

Interactive: dry-run first, then apply. Differing files move to `unityHPC/.pre-redesign/`. Full `.env` flags: `controller/ops/setup.md`.

Collector deploy is **opt-in**: ask the user before starting a long-lived `tmux has-session` collector on the login node (`collector.sh` / `collector_parse.py`). Default skip. Details: `controller/ops/setup.md`. Use `--collector deploy` only when authorized.

**4. POST attach**

```bash
curl -sS -X POST "${UNITY_CONTROLLER:-http://127.0.0.1:8300}/api/v1/projects" \
  -H 'Content-Type: application/json' \
  -d "{\"slug\":\"<slug>\",\"path\":\"$(pwd)\",\"primitive\":\"<cpu|gpu|ml|multi-cpu|multi-gpu>\"}"
```

**5. Confirm `unityHPC/controller.json` was written.**

**6. Done** when health is ok, the scaffold exists, and `GET /api/v1/projects/{slug}` returns the project.

If this directory is a git repo, create or reuse an experiment branch only after probing:

```bash
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git checkout -b "unity/$(date +%Y-%m-%d)" 2>/dev/null \
        || git checkout "unity/$(date +%Y-%m-%d)"
fi
```
