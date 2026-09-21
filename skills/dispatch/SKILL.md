---
name: dispatch
description: "Dispatch a run through the Unity HPC controller (POST /api/v1/projects/{slug}/runs). Use when submitting, sweeping, or dry-running a job. Do not SSH or call sbatch."
---

# unity-hpc:dispatch

Announce: "Using unity-hpc:dispatch to submit a run through the controller."

Do not call sbatch. Do not SSH. The controller calls run.sh. A job not recorded is a job the project cannot name.

**1. Read `unityHPC/controller.json`** for the controller URL and slug. If it is missing, run `/unity-hpc:connect`.

**2. POST `/api/v1/projects/{slug}/runs`** with JSON `{exp, campaign?, dry_run?, overrides?}`. For fan-out, `{manifest: path}`.

```bash
curl -sS -X POST "${controller}/api/v1/projects/${slug}/runs" \
  -H 'Content-Type: application/json' \
  -d '{"exp":"<exp>"}'
```

**3. Print the controller output.** If health fails (`GET /api/v1/health`), tell the user to start `hpc-controller` or `hpc-controller --tailscale`.
