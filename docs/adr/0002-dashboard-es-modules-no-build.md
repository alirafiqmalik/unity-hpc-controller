# The dashboard is plain ES modules with no build step

The dashboard was one 1225-line `controller/ui/index.html`: the markup, 169
lines of CSS and 776 lines of JavaScript in one file. Nothing could be read,
changed or tested in isolation. It is now a tree of stylesheets and ES modules
that `controller/http.py::_static` serves directly:

```text
controller/ui/
├── index.html        markup only
├── css/              tokens, base, layout, components
└── js/               main, app, bus, config, state, api, toast,
                      format, chart, drawer, pages/<tab>.js
```

The browser loads `/js/main.js` as a module and resolves the graph itself.
There is no bundler, no `package.json`, no lock file and no `node_modules`.
`scripts/hpc-controller` keeps working from a fresh clone, and CI still
installs nothing but `pytest`.

## Considered options

- **A bundler with the output committed** (Vite or esbuild into
  `controller/ui/dist/`). Rejected: it buys TypeScript and minification at the
  price of a build artefact in git and a new way to be wrong — a `dist/` that
  does not match its source. The dashboard is about 950 lines of code served
  over a tailnet to one operator. Neither bundle size nor cold start is a
  problem worth a toolchain.
- **A framework stack** (Next.js or Vite plus React and TypeScript).
  Rejected: it makes Node 22 and pnpm hard prerequisites for anyone running
  the controller, and it puts a build between a clone and a working dashboard.
  The controller is stdlib-only Python by design, and the plugin ships as a
  repo that users clone. That stack suits a product deployed once onto one
  known host, where an operator runs a bootstrap script before first use. This
  plugin has neither of those.
- **Leaving the single file alone.** Rejected: it was already past the size
  where a reader can hold it, and every change risked an unrelated panel.

## Consequences

- **Cascade order is a contract.** The four stylesheets are split at the
  original rule boundaries and are linked in their original order, so every
  rule still wins exactly what it won before. `tests/test_controller_ui.py`
  pins that order.
- **Inline handlers need an explicit bridge.** The markup uses `onclick=`
  attributes, which resolve against global scope, and a module's top-level
  binding is not global. `js/main.js` assigns the sixteen handler functions to
  `window` in one documented block. A handler left off that list fails silently
  at click time, so `tests/test_controller_ui.py` checks the two sides against
  each other in both directions.
- **`state` is no longer reachable from the browser console.** It was a
  top-level `const` in a classic script, so `state` used to evaluate in DevTools.
  It is now module-scoped. Nothing in the dashboard depended on it; debugging
  from the console did.
- **`app.js` imports every page module, so no page module may import it back.**
  A page reaches `refresh()` through `js/bus.js`, which app.js registers at
  start-up. A test enforces the direction.
- **A real browser is now worth testing in.** With no build step, a wrong
  import path or a missing `window` binding appears only when a browser
  evaluates the graph. `tests/test_controller_ui_smoke.py` drives headless
  Chrome over CDP with a stdlib-only client (`tests/cdp.py`). It is opt-in
  (`UNITY_HPC_UI_SMOKE=1`) and skips when Chrome is absent, so it adds no
  prerequisite to the default suite.
