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

## Telemetry retrieval

`telemetry.py` owns the local archive of the cluster telemetry: what state it is
in, an on-demand pull, and an optional schedule. The pull itself stays
`scripts/hpc-sync-telemetry`, which pulls the raw tree, rolls it up, drops
archived days from the cluster, and takes `locks/sync.lock` across all three.
This module starts that script and reads the same lock. It never adds a second
one.

| Route | Does |
|---|---|
| `GET /api/v1/telemetry` | source, whether a retrieval runs, store freshness, rollup age, schedule, history |
| `POST /api/v1/telemetry/sync` | start one retrieval; `202` when it starts, `200` with a reason when it does not |
| `POST /api/v1/telemetry/script` | run `once`, `sample`, or `prune` in the cluster session, then pull |
| `POST /api/v1/telemetry/session` | `{"action":"close"}` ends the cluster session |
| `PATCH /api/v1/telemetry/settings` | `source`, `schedule_enabled`, `interval_minutes`, `script_mode` |

A retrieval runs in its own thread, so the HTTP handler never waits for a pull.
The schedule is one thread in this process. It sleeps until the next run is
due. A due run sends the saved script (`once`, `sample`, or `prune`) into the
`unity-hpc` tmux session, waits for it, then pulls. Run script now on the
Settings → Scheduled page uses that same path. The session closes after a quiet period of
one and a half intervals. Settings live in
`$UNITY_HPC_DATA/controller/telemetry.json`, not in the browser.

The source is read from the saved setting, then `UNITY_TELEMETRY_SRC` in the
controller's environment, then the first attached project whose `unityHPC/.env`
declares one. Settings → Config shows which layer answered.

ADR 0003 records why the schedule lives here. ADR 0004 records the session
and the idle timeout.

## Dashboard

`web/` is a Vite project on the `twenty-front` stack: React 18, TypeScript,
Emotion, Recoil and react-router. `npm run build` writes `web/dist/`, and
`http._static` serves it. ADR 0006 records why this replaced the no-build ES
modules.

```bash
cd controller/web
npm install
npm run build          # typechecks, then bundles into dist/
npm run dev            # port 8301, proxies /api to the controller on 8300
```

`scripts/hpc-controller` runs the two commands above on the first start of a
machine, so a fresh clone needs no separate step. `--no-build-ui` skips it and
`--build-ui` forces a rebuild. With no `npm` on PATH the API still comes up and
the page answers `503` with the commands to run.

```text
web/src/
├── main.tsx          providers: theme → toast → Recoil → sync → router
├── App.tsx           the router
├── ui/
│   ├── theme/        THEME_DARK, THEME_LIGHT, the Emotion provider
│   ├── components/   Button, Tag, Card, Table, Field, SidePanel, Toast …
│   └── layout/       the navigation drawer and the page chrome
├── modules/
│   ├── controller/   types, the JSON client, the store, the refresh cycle
│   ├── navigation/   the navigation map
│   ├── charts/       Recharts wrappers and the series filter
│   ├── panels/       the job and project side panels
│   ├── projects/     the write path to a project
│   ├── telemetry/    the Settings reader
│   └── events/       the controller event feed
└── pages/            one module per route
```

### Navigation

| Section | Pages |
|---|---|
| Cluster | Overview, Queue, Users, Analytics |
| User Jobs | Monitor, Project, Dispatch |
| Settings | Config, Scheduled, Logs |

`src/modules/navigation/routes.ts` is the one list. The drawer, the router and
the page header all read it, and `tests/test_controller_web.py` checks the
three against each other.

### Two rules the tests hold

- **A deep link must work on a cold load.** Every GET that is not an API route
  and not a real file answers with `index.html`. A request under `/assets/` is
  never rewritten, so a missing asset stays a 404.
- **The navigation map and the router may not drift.** A path in the drawer
  with no route is a dead link, and a route the drawer hides is unreachable.

`tests/test_controller_web.py` reads both trees and needs no browser.
`tests/test_controller_web_smoke.py` drives the built bundle in headless
Chrome; run it with `UNITY_HPC_UI_SMOKE=1`, and it skips when Chrome or the
build is absent.
