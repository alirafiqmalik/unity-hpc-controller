# The dashboard is a React build on the twenty-front stack

Supersedes ADR 0002, which made the dashboard plain ES modules with no build
step.

`controller/web/` is a Vite project: React 18, TypeScript, Emotion, Recoil and
react-router, which is the stack `twentyhq/twenty` uses in `twenty-front`.
`npm run build` writes `controller/web/dist/`, and `controller/http.py::_static`
serves that directory. `scripts/hpc-controller` builds it on the first start of
a machine, so a fresh clone still reaches a working dashboard in one command.

```text
controller/web/
├── package.json, vite.config.ts, tsconfig.json
├── index.html            the mount point and the entry module
└── src/
    ├── main.tsx          providers: theme → toast → Recoil → sync → router
    ├── App.tsx           the router
    ├── ui/               the design system
    │   ├── theme/        THEME_DARK, THEME_LIGHT, the Emotion provider
    │   ├── components/   Button, Tag, Card, Table, Field, SidePanel, Toast …
    │   └── layout/       the navigation drawer and the page chrome
    ├── modules/
    │   ├── controller/   types, the JSON client, the store, the refresh cycle
    │   ├── navigation/   the navigation map, read by the drawer and the router
    │   ├── charts/       Recharts wrappers and the series filter
    │   ├── panels/       the job and project side panels
    │   ├── projects/     the write path to a project
    │   ├── telemetry/    the Settings reader
    │   └── events/       the controller event feed
    └── pages/            one module per route
```

## Why this changed

ADR 0002 rejected a framework stack because it "makes Node 22 and pnpm hard
prerequisites for anyone running the controller, and it puts a build between a
clone and a working dashboard". Both objections were right about the cost. Two
things moved.

**The dashboard outgrew the pattern.** ADR 0002 sized it at about 950 lines
served to one operator. It reached roughly 1,700 across eleven modules, and the
joints that a build normally checks were being held by tests instead: one test
matched every inline `onclick=` against a hand-written `window` bridge in both
directions, another pinned the order of four stylesheets because the cascade
was the contract. Both tests exist because the code had no types and no module
boundary the tooling could see. A wrong element id still failed only at click
time.

**The navigation was regrouped.** Eight flat tabs became three sections and
eleven pages. Flat tabs were a `TABS` array and a `display: none` toggle;
sections with deep links need a router, and a router in hand-written ES modules
is a router to maintain.

The chosen stack is not arbitrary. It is the one `twenty-front` uses, so the
component patterns, the theme shape and the state layering come from a large
project that has already answered those questions.

## Considered options

- **Keep ADR 0002 and hand-write the router and the sections.** Rejected: it
  keeps every cost the change was meant to remove — no types, no component
  boundary, a growing `window` bridge — and adds a hand-rolled router.
- **Commit `dist/` instead of building on start.** Rejected: it puts a
  generated artefact in git and creates a new way to be wrong, a `dist/` that
  does not match its source. ADR 0002 rejected it for the same reason, and that
  reasoning did not change.
- **A GraphQL backend as well, modelled on `twenty-server`.** Rejected: the
  controller is stdlib-only Python that owns the SSH and tmux session to the
  login node (ADR 0001, ADR 0004). A NestJS server in front of it adds
  PostgreSQL and Redis as prerequisites and moves nothing the dashboard needs.
  The REST API under `/api/v1/` is unchanged by this ADR.

## Consequences

- **Node is needed to change the dashboard, not to run the controller.**
  `hpc-controller` builds `dist/` on the first start when `npm` is on PATH. If
  it is not, the API comes up as usual and the page answers `503` with the two
  commands to run. `--no-build-ui` skips the step and `--build-ui` forces it.
- **`/` is not the only page the server answers with.** A single-page app puts
  state in the path, so `/cluster/queue` must work on a cold load. Every GET
  that is not an API route and not a real file answers with `index.html`. A
  request under `/assets/` is never rewritten: a missing asset must be a 404,
  not an HTML page that a script tag cannot parse.
- **Hashed assets are cached for a year, `index.html` never.** The build names
  every asset by content hash and `index.html` names them.
- **The navigation map is one file.** `src/modules/navigation/routes.ts` is read
  by the drawer, the router and the page header, and
  `tests/test_controller_web.py` checks the three against each other, so a page
  cannot appear in the drawer and be missing from the router.
- **The two tests ADR 0002 needed are gone.** TypeScript replaces the inline
  handler bridge, and Emotion replaces the stylesheet cascade order, so neither
  joint needs a test to hold it. `tests/test_controller_web.py` checks what a
  compiler cannot: the Python and TypeScript sides agreeing on the build
  directory, the API port and the route list.
- **A real browser is still worth testing in.**
  `tests/test_controller_web_smoke.py` drives the built bundle over CDP with
  the same stdlib-only client (`tests/cdp.py`). It is opt-in
  (`UNITY_HPC_UI_SMOKE=1`) and skips when Chrome or the build is absent.
- **CI installs Node.** The workflow builds the dashboard before the suite, so
  the routing checks and the browser smoke test both run.
- **The theme covers light as well as dark.** The old stylesheet was dark only.
  Every colour is now a token defined twice, and the choice is per browser.
