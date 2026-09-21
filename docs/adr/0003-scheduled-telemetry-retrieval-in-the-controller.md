# Scheduled telemetry retrieval is a thread in the controller

The dashboard draws GPU utilization from `summaries.db` and the header pill from
`snapshot.csv`. Both files are local copies. `cluster-intel/sync-telemetry.sh`
fills them: it pulls the raw telemetry with `rsync`, then rolls it up, and holds
`locks/sync.lock` across both. Until now nothing called that script on a
cadence, and nothing showed an operator whether it had ever run. A dashboard
with empty charts gave no way to tell an absent source from a stale pull.

`controller/telemetry.py` adds the state, the on-demand run and the schedule.
The dashboard Settings tab drives all three.

## The schedule runs inside the controller process

The controller is already the always-on process on this machine (`CONTEXT.md`).
A periodic pull is 20 lines of `threading` inside it: one daemon thread that
wakes every five seconds, reads the saved settings, and starts a retrieval when
one is due. It starts in `controller/serve.py` and stops with the server.

- **A login-node daemon** is refused by design. §3.7 of `docs/design-decisions.md`
  and the **Watcher** entry in `CONTEXT.md` both say the login node is shared and
  that nothing the plugin ships may live there. The cluster-side collector is
  the one exception, and it is a deliberate, opt-in deployment.
- **A systemd timer or a cron job** would work, but it needs a second install
  step on every machine, it writes its state somewhere the dashboard cannot
  read, and it cannot report "running now" to a panel. The controller already
  has a service unit (`--install-user-service`); a timer beside it is a second
  thing to keep in step.
- **A thread per due time** was rejected for a single ticking thread. One thread
  that reads the settings on every tick means a changed interval, or a schedule
  switched off, takes effect at once, with no timer to cancel.

The cost is honest and recorded: **the schedule only runs while the controller
runs.** It is not a cron replacement. An operator who wants a pull on a machine
with no controller still calls `scripts/hpc-sync-telemetry`.

## The shell script keeps the lock

`sync-telemetry.sh` already takes `flock` on `locks/sync.lock` for the pull and
the rollup together. This module does not add a second lock. It *reads* that
one: a separate `open()` plus a non-blocking `flock` tells an operator whether a
retrieval is in progress, whoever started it. A process-local flag stops this
controller from starting two, so the HTTP answer is immediate instead of waiting
for a subprocess to report the skip.

A retrieval runs in its own thread. `POST /api/v1/telemetry/sync` answers `202`
with the decision to start, and the panel polls `GET /api/v1/telemetry` for the
outcome. `serve.py` uses `ThreadingHTTPServer`, and a pull of a live telemetry
tree takes minutes, so the handler must not wait for it.

## Settings live in the data directory

`$UNITY_HPC_DATA/controller/telemetry.json`, beside `projects.json` and
`events.jsonl`. Browser storage was rejected: the schedule is a property of the
controller, not of whoever last opened the dashboard, and the thread that reads
it has no browser.

The source is resolved in three layers — the saved setting, then
`UNITY_TELEMETRY_SRC` in the controller's environment, then the first attached
project whose `unityHPC/.env` declares one. The panel names which layer answered,
because "no charts" and "no source" look the same from the browser.

## `snapshot.csv` comes with the pull

The header pill reads `snapshot.csv`, and nothing in the repo ever copied that
file to this machine. `sync-telemetry.sh` now pulls it as a fourth step, from
the sibling of the telemetry directory, which is where the cluster-side poller
writes it. `UNITY_SNAPSHOT_SRC` overrides that guess and an empty value turns
the step off. The step is best-effort: it runs after the rollup, and a cluster
that publishes no such file logs a line and still exits 0.

## The usage window slides back to the newest data

`snapshot.usage(hours)` asked for the last `hours` up to *now*. A mirror that is
a week old therefore answered `available: false`, and every chart drew empty —
the same answer a machine with no data at all gives. The window now slides back
to the last `hours` of data that exists when the clock window is empty, and the
payload says which of the two happened:

```json
{"window": "recent" | "latest-available", "freshness_utc": ..., "stale_s": ...}
```

The rows are real rows either way. Nothing is interpolated, extended or
synthesised. The Settings panel prints the window and the age of the newest
slot, so a stale mirror reads as stale instead of as empty.

## The mock integration toggles are gone

The Settings tab carried eight switches — Prometheus, Grafana, MLflow,
Alertmanager and four notification rows — wired to a `tg()` function that
toggled a class and showed a toast. The controller read none of them. They are
replaced by the retrieval controls. `tg()` is removed from `js/pages/settings.js`
and from the `window` bridge in `js/main.js`.

## Consequences

- A new API surface: `GET /api/v1/telemetry`, `POST /api/v1/telemetry/sync`,
  `PATCH /api/v1/telemetry/settings`.
- `controller/serve.py` starts and stops one thread. A controller that is never
  started has no schedule, which is the same as today.
- `pages/settings.js` reads its own endpoint instead of the shared store in
  `app.js`. `app.js` renders only the showing page, so the request stops when
  the operator leaves the tab.
- Two retrievals still cannot overlap, and the guarantee is still `flock` in the
  shell script, not agreement between callers.
