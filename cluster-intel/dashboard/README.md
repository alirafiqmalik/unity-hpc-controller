# Unity Cluster Monitor (dashboard proof of concept)

A small web dashboard, with no dependencies, for the data that `cluster-intel`
already collects. It gives a quick human overview of who uses the cluster, and
when.

- **`serve.py`** — an HTTP server that uses the standard library only, with no
  Flask, pandas or pyarrow. It reads the existing SQLite, CSV and JSON output, and
  exposes one `/api/data` endpoint.
- **`index.html` · `style.css` · `app.js`** — the page. Each chart is hand-drawn
  SVG, with no CDN, so the page works over a bare tailnet. The colors come from the
  validated dataviz palette, and live in `style.css`.

## What it shows

Every source lives in the shared data directory `$UNITY_HPC_DATA`, whose default is
`~/.local/share/unity-hpc/`. Every project uses that same store, and it sits outside
the versioned plugin, so it survives a plugin update.

| Panel | Source | Reads as |
|---|---|---|
| KPI tiles (running / pending / free nodes / GPU types free) | `snapshot.csv` (live poller) | current state |
| GPU usage over time, by type | `summaries.db` | trend |
| Queue trend (running against pending) | `snapshot.csv` | live movement |
| Usage per GPU type (average and peak) | `summaries.db` | magnitude |
| Hour by day-of-week heatmap | `summaries.db` | when it is busy |

Each panel degrades to an empty state when its source is absent, so you can run the
page before the full pipeline has data.

Historical panels read `$UNITY_HPC_DATA/summaries.db`. Run `hpc-sync-telemetry` to
pull new telemetry and update the rollup.

## Run it

```bash
python3 serve.py            # http://0.0.0.0:8787
python3 serve.py --port 9000
```

It needs nothing beyond Python 3.10 or later. It refreshes every minute, and it has
a 24h/7d/30d/60d/90d window switch and a light/dark toggle.

## Serve it over Tailscale

Run the server on the machine that holds the synced `summaries.db` and `snapshot.csv`.
That is your laptop, or wherever you run the cluster-intel sync. You can then view
the page from any device on your tailnet.

**Option A — bind to the tailnet, and connect directly:**

```bash
python3 serve.py --host 0.0.0.0 --port 8787
# then browse to  http://<this-machine's-tailscale-ip>:8787
#   ( tailscale ip -4  to find it )
```

**Option B — `tailscale serve`, for HTTPS inside the tailnet with no open port:**

```bash
python3 serve.py --host 127.0.0.1 --port 8787 &
tailscale serve --bg 8787
# view at the https://<machine>.<tailnet>.ts.net URL it prints
```

Option B is better: it gives you TLS, and it never exposes a port beyond your
tailnet.

CAUTION: Do not use `tailscale funnel` for this page. Funnel publishes it to the
public internet, and this dashboard is meant to stay private.

## Data freshness

The server reads the files on every request, so it needs no restart.

The live panels read `snapshot.csv`. Historical panels read `summaries.db` and show
the last rollup time. Use `?project=<name>&campaign=<name>` to filter task metrics.

## Editing

Each chart is one function in `app.js`: `lineChart`, `barChart` and `heatmap`. The
palette is a set of CSS custom properties in `style.css`. The server's data shaping
is in the `historical()` and `live()` functions in `serve.py`.

Everything here is small on purpose.
