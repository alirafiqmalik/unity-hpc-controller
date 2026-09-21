# Controller

Always-on HTTP service for Unity HPC: project registry, cluster snapshot,
dispatch through `unityHPC/run.sh`, and the dashboard.

```bash
scripts/hpc-controller                      # background + Tailscale HTTPS
scripts/hpc-controller --status
scripts/hpc-controller --stop
scripts/hpc-controller --fg                 # stay in the terminal
scripts/hpc-controller --no-tailscale       # localhost only
scripts/hpc-controller --install-user-service
systemctl --user enable --now unity-hpc-controller
```

Do not use `tailscale funnel`.

Operator runbooks (the old skill bodies) are in `ops/`. The dashboard is
`ui/index.html`. The HTTP seam is `http.handle` — tests call it without
sockets.
