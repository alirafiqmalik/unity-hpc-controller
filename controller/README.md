# Controller

Always-on HTTP service for Unity HPC: project registry, cluster snapshot,
dispatch through `unityHPC/run.sh`, and the dashboard.

```bash
scripts/hpc-controller                      # http://0.0.0.0:8300
scripts/hpc-controller --tailscale          # 127.0.0.1 + tailscale serve
scripts/hpc-controller --install-user-service
systemctl --user enable --now unity-hpc-controller
```

Do not use `tailscale funnel`.

Operator runbooks (the old skill bodies) are in `ops/`. The dashboard is
`ui/index.html`. The HTTP seam is `http.handle` — tests call it without
sockets.
