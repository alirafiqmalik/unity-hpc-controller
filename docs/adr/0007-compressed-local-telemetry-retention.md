# Keep 90 days live and back up older telemetry locally

Status: accepted. Supersedes the unlimited local archive in ADR 0005 and the
unlimited live summary in ADR 0004.

Scheduled pulls make the local telemetry tree and `summaries.db` grow. The
operator chose a 90 day live window and local compressed backups for older
data. The same rule applies to a manual sync. The cutoff uses UTC calendar
days. A day leaves the live store only when its date is before the cutoff.

`sync-telemetry.sh` pulls and rolls up first. It then prunes the cluster staging
tree. While it still holds `locks/sync.lock`, it runs `hpc-local-retention`.
That command writes two kinds of backup under
`$UNITY_HPC_DATA/archive/telemetry-retention/YYYY-MM-DD/`:

- `raw-mirror-*.tar.gz` and `raw-imported-*.tar.gz` hold the two local raw
  trees when that day exists in them.
- `summary-*.sqlite.gz` holds that day's rows from the five dated summary
  tables. It also has `meta` and a profile built from that day's task rows.

Each filename includes a content hash. A later copy of an old day adds a new
file, so it cannot overwrite an earlier backup. The command reads each backup
after it writes it. It checks the SQLite database before compression. Only
then does it copy `summaries.db`, remove old rows from the copy, rebuild the
live profile, vacuum the copy, and replace the live database. It removes old
raw directories last. A backup fault leaves the live data in place. A fault
after the database replacement leaves the compressed copies available; the
next sync can retry any raw directory that remains.

The cluster prune still requires a local copy and a complete rollup. It runs
before local retention, so a day can leave the cluster before its local raw
copy moves into the compressed backup. `UNITY_HPC_LOCAL_RETENTION_DAYS` changes
the 90 day limit for the sync script. Run `python3 scripts/hpc-local-retention
--days 90` to see eligible days without changing data.

The live dashboard and per-project hardware profile read only the 90 day live
database. They do not query compressed backups. The backup files are standard
tar and SQLite files compressed with gzip. To inspect one summary backup,
decompress it to a separate directory and open the resulting SQLite database.
To inspect raw files, list a tar file with `tar -tzf` before extracting it.
Keep all versions of a day's backup when late data arrives.
