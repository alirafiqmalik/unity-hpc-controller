# Unity Cluster Monitor (dashboard POC)

A tiny, dependency-free web dashboard for the data `cluster-intel` already
collects — a quick human overview of who's using the cluster and when.

- **`serve.py`** — stdlib-only HTTP server (no Flask/pandas/pyarrow). Reads the
  existing SQLite/CSV/JSON outputs and exposes one `/api/data` endpoint.
- **`index.html` · `style.css` · `app.js`** — the page. Charts are hand-drawn
  SVG (no CDN), so it works over a bare tailnet. Colors come from the validated
  dataviz palette and live in `style.css`.

## What it shows

All sources live in the shared data dir `$UNITY_HPC_DATA`
(default `~/.local/share/unity-hpc/`) — the same store every project uses, kept
outside the versioned plugin so it survives plugin updates.

| Panel | Source | Reads as |
|---|---|---|
| KPI tiles (running / pending / free nodes / GPU types free) | `snapshot.csv` (live poller) | current state |
| GPU allocation over time, by type | archived usage snapshot | trend |
| Queue trend (running vs pending) | `snapshot.csv` | live movement |
| Per-GPU-type demand (avg + peak) | archived usage snapshot | magnitude |
| Hour × day-of-week heatmap | archived usage snapshot | when it's busy |

Every panel degrades to an empty state if its source isn't there yet, so you can
run it before the full pipeline has data.

**Note:** the historical panels still read the pre-redesign snapshot archived
under `$UNITY_HPC_DATA/archive/` — the live pipeline now writes `summaries.db`
instead. Rewiring these panels to `summaries.db` is a follow-up task; until
then they show the archived, no-longer-updated data.

## Run it

```bash
python3 serve.py            # http://0.0.0.0:8787
python3 serve.py --port 9000
```

No dependencies beyond Python 3.10+. It auto-refreshes every minute and has a
7d/30d/all window switch and a light/dark toggle.

## Serve it over Tailscale

The machine that has the synced `usage.db` / `snapshot.csv` (your laptop, or
wherever you run the cluster-intel sync) runs the server; you view it from any
device on your tailnet.

**Option A — bind to the tailnet, hit it directly:**
```bash
python3 serve.py --host 0.0.0.0 --port 8787
# then browse to  http://<this-machine's-tailscale-ip>:8787
#   ( tailscale ip -4  to find it )
```

**Option B — `tailscale serve` (HTTPS, tailnet-only, no open port):**
```bash
python3 serve.py --host 127.0.0.1 --port 8787 &
tailscale serve --bg 8787
# view at the https://<machine>.<tailnet>.ts.net URL it prints
```

Option B is preferable: TLS, and it never exposes a port beyond your tailnet.
For a public share you could add `tailscale funnel`, but this dashboard is meant
to stay private.

## Data freshness

The server reads the files on every request — no restart needed. The live
panels (`snapshot.csv`) stay current automatically; the historical panels read
the archived snapshot (see note above) and do not update until the dashboard
is rewired to `summaries.db`.

## Editing

Each chart is one function in `app.js` (`lineChart`, `barChart`, `heatmap`).
Palette is CSS custom properties in `style.css`. The server's data shaping is
in the `historical()` / `live()` functions in `serve.py`. Everything is small
on purpose.
