/** People on the cluster, their usage, and this account's fairshare. */

import { IconDownload, IconSearch } from '@tabler/icons-react';
import { useMemo, useState } from 'react';
import { useRecoilValue } from 'recoil';

import { fmtCount, fmtHours } from '../modules/controller/format';
import { clusterState } from '../modules/controller/state';
import { Button } from '../ui/components/Button';
import { Card, CardHeader, Grid } from '../ui/components/Card';
import { EmptyState } from '../ui/components/EmptyState';
import { TextInput } from '../ui/components/Field';
import { ProgressBar } from '../ui/components/ProgressBar';
import { StatCard } from '../ui/components/StatCard';
import {
  MonoCell,
  MutedCell,
  Table,
  TableEmptyRow,
  TableScroller,
  THead,
  TRow,
} from '../ui/components/Table';
import { useToast } from '../ui/components/Toast';
import { Page } from '../ui/layout/AppLayout';

const CSV_HEADER = '#,User,Account,Jobs,Hours,GPU jobs,GPU hours';

export const ClusterUsersPage = () => {
  const cluster = useRecoilValue(clusterState);
  const toast = useToast();
  const [search, setSearch] = useState('');

  const users = cluster?.users;
  const rows = users?.available ? (users.rows ?? []) : [];
  const fairshare = cluster?.fairshare;

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter(
      (row) =>
        row.user.toLowerCase().includes(needle) ||
        (row.account ?? '').toLowerCase().includes(needle),
    );
  }, [rows, search]);

  const totalHours = rows.reduce((sum, row) => sum + (Number(row.hours) || 0), 0);
  const totalGpuHours = rows.reduce(
    (sum, row) => sum + (Number(row.gpu_hours) || 0),
    0,
  );
  const peak = Math.max(1, ...filtered.map((row) => Number(row.hours) || 0));

  const exportCsv = () => {
    const lines = filtered.map((row, index) =>
      [
        index + 1,
        row.user,
        row.account ?? '',
        row.jobs,
        row.hours,
        row.gpu_jobs,
        row.gpu_hours,
      ].join(','),
    );
    const blob = new Blob([[CSV_HEADER, ...lines].join('\n')], {
      type: 'text/csv',
    });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'unity-hpc-users.csv';
    link.click();
    URL.revokeObjectURL(link.href);
    toast(`Exported ${filtered.length} rows to unity-hpc-users.csv`, 'success');
  };

  const account =
    fairshare?.account && !String(fairshare.account).includes('${')
      ? fairshare.account
      : '';

  return (
    <Page
      actions={
        <Button
          size="small"
          Icon={IconDownload}
          onClick={exportCsv}
          disabled={!filtered.length}
        >
          Export CSV
        </Button>
      }
    >
      <Grid $min="220px">
        <StatCard
          label="People"
          value={rows.length ? fmtCount(rows.length) : '—'}
          caption={
            rows.length ? 'accounts in the job history' : 'no user history in the archive'
          }
          accent="purple"
        />
        <StatCard
          label="Hours used"
          value={totalHours ? fmtHours(totalHours) : '—'}
          caption={
            totalHours ? 'elapsed across those accounts' : 'no elapsed time recorded'
          }
          accent="blue"
        />
        <StatCard
          label="GPU hours"
          value={totalGpuHours ? fmtHours(totalGpuHours) : '—'}
          caption={
            totalGpuHours ? 'elapsed on GPU allocations' : 'no GPU time recorded'
          }
          accent="green"
        />
        <StatCard
          label="Fairshare factor"
          value={
            fairshare?.available && fairshare.factor !== null && fairshare.factor !== undefined
              ? `${Math.round(Number(fairshare.factor) * 100)}%`
              : '—'
          }
          caption={
            fairshare?.available
              ? fairshare.effective_usage !== null && fairshare.effective_usage !== undefined
                ? `${account || 'this account'} · usage ${Math.round(Number(fairshare.effective_usage) * 100)}%`
                : account || 'from the cluster profile'
              : 'not in the cluster profile'
          }
          accent="yellow"
        />
      </Grid>

      <Card>
        <CardHeader
          title="Users on the cluster"
          action={
            rows.length ? (
              <div style={{ alignItems: 'center', display: 'flex', gap: 8 }}>
                <IconSearch size={14} style={{ opacity: 0.5 }} />
                <TextInput
                  value={search}
                  placeholder="Filter by user or account"
                  onChange={(event) => setSearch(event.target.value)}
                  style={{ width: 220 }}
                />
              </div>
            ) : undefined
          }
        />
        <TableScroller>
          <Table>
            <THead>
              <tr>
                <th>#</th>
                <th>User</th>
                <th>Account</th>
                <th>Jobs</th>
                <th>GPU jobs</th>
                <th>Hours</th>
                <th>GPU hours</th>
              </tr>
            </THead>
            <tbody>
              {filtered.length ? (
                filtered.map((row, index) => {
                  const percent = ((Number(row.hours) || 0) / peak) * 100;
                  return (
                    <TRow key={row.user}>
                      <MonoCell>{index + 1}</MonoCell>
                      <td>
                        <b>{row.user}</b>
                      </td>
                      <MutedCell>{row.account || '—'}</MutedCell>
                      <MonoCell>{fmtCount(row.jobs)}</MonoCell>
                      <MonoCell>{fmtCount(row.gpu_jobs)}</MonoCell>
                      <MonoCell>{fmtHours(row.hours)}</MonoCell>
                      <td>
                        <div
                          style={{ alignItems: 'center', display: 'flex', gap: 8 }}
                        >
                          <ProgressBar percent={percent} />
                          <span
                            style={{
                              fontFamily: 'inherit',
                              fontSize: 11,
                              minWidth: 46,
                              textAlign: 'right',
                            }}
                          >
                            {fmtHours(row.gpu_hours)}
                          </span>
                        </div>
                      </td>
                    </TRow>
                  );
                })
              ) : (
                <TableEmptyRow colSpan={7}>
                  {rows.length
                    ? 'No user matches this filter'
                    : 'No cluster users in the job history'}
                </TableEmptyRow>
              )}
            </tbody>
          </Table>
        </TableScroller>
        {!rows.length ? (
          <EmptyState title="The archive holds no per-user job rows" compact>
            User rows come from the archived <code>raw_jobs</code> table. Run a
            telemetry retrieval, then a rollup, to fill it.
          </EmptyState>
        ) : null}
      </Card>
    </Page>
  );
};
