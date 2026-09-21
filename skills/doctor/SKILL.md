---
name: doctor
description: "Check the Unity HPC controller and this project's wiring. Use when the controller is down, attach failed, or a dispatch is rejected."
---

# unity-hpc:doctor

Announce: "Using unity-hpc:doctor to check the controller and this project's wiring."

**1. Curl health**

```bash
curl -sS "${UNITY_CONTROLLER:-http://127.0.0.1:8300}/api/v1/health"
```

If this fails, tell the user to run `hpc-controller`. That starts the controller in the background and publishes it over Tailscale. Stop.

**2. Read `unityHPC/controller.json`** for the controller URL and slug.

**3. `GET /api/v1/projects/{slug}`** and report whether the project is registered.

**4. Confirm `unityHPC/run.sh` is present.**

If the plugin MCP server looks stale, also call `mcp__unity-hpc__unity_doctor`.
