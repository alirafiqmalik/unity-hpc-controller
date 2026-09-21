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

Operator runbooks (the old skill bodies) are in `ops/`. The HTTP seam is
`http.handle` — tests call it without sockets.

## Dashboard

`ui/` holds plain ES modules and stylesheets. `http._static` serves them as
they are: no bundler, no `package.json`, no build step. Edit a file and
reload the page.

```text
ui/
├── index.html        markup only; loads /js/main.js as a module
├── css/              tokens, base, layout, components — linked in that order
└── js/
    ├── main.js       entry: nav, chip handlers, the window bridge, boot
    ├── app.js        go(), render(), renderHeader(), refresh()
    ├── bus.js        late-bound refresh(), so a page never imports app.js
    ├── state.js      the one store, plus live() and latest()
    ├── config.js     TABS, CHART_COLORS, FAIL_STATES, PRIMITIVES
    ├── api.js        the JSON client
    ├── format.js     pure formatters
    ├── chart.js      canvas line charts
    ├── toast.js      notices and the copy button
    ├── drawer.js     the job and project drawers
    └── pages/        one module per tab, each exporting render()
```

Two rules the tests hold:

- **The stylesheet order is the cascade.** The four files split the original
  rules at their boundaries. Reorder the `<link>` tags and rules change which
  one wins.
- **Every inline `onclick=` handler must be on the `window` bridge** in
  `main.js`. Module bindings are not global, so a handler left off the list
  fails only when someone clicks it.

`tests/test_controller_ui.py` checks both from the source.
`tests/test_controller_ui_smoke.py` loads the page in headless Chrome; run it
with `UNITY_HPC_UI_SMOKE=1` and it skips when Chrome is absent.
