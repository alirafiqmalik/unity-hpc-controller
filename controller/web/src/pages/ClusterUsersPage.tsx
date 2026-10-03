/** People on the cluster, their usage, and this account's fairshare. */

import styled from '@emotion/styled';
import { useTheme } from '@emotion/react';
import { IconArrowDown, IconArrowUp, IconDownload } from '@tabler/icons-react';
import { useMemo, useState } from 'react';
import { useRecoilValue } from 'recoil';

import { fmtCount, fmtHours, fmtWait } from '../modules/controller/format';
import { clusterState, usageHoursState } from '../modules/controller/state';
import {
  inWindow,
  PageActions,
  TimeWindowPicker,
  windowPhrase,
} from '../modules/controller/TimeWindow';
import {
  INDEX_WIDTH,
  USER_COLUMNS,
  USER_TABLE_WIDTH,
  accountsOf,
  compareUsers,
  matchingAccount,
  csvCell,
  cycleSort,
  highlightParts,
  partitionsOf,
  rowMatches,
  searchPieces,
  sortHint,
  sortSummary,
  type UserSort,
  type UserSortKey,
} from '../modules/controller/userList';
import { Button } from '../ui/components/Button';
import { Card, CardHeader, Grid } from '../ui/components/Card';
import { EmptyState } from '../ui/components/EmptyState';
import { SearchField } from '../ui/components/Field';
import { StatCard } from '../ui/components/StatCard';
import {
  HeadButton,
  MonoCell,
  SortCue,
  SortRank,
  Table,
  TableEmptyRow,
  TableScroller,
  THead,
  TRow,
} from '../ui/components/Table';
import { Tag } from '../ui/components/Tag';
import { useToast } from '../ui/components/Toast';
import type { ThemeColor } from '../ui/theme/colors';
import { Page } from '../ui/layout/AppLayout';

const CSV_HEADER = [
  '#',
  'User',
  'Account',
  'Accounts',
  'Jobs',
  'Running',
  'Pending',
  'Completed',
  'Failed',
  'Timeout',
  'Out of memory',
  'Preempted',
  'Cancelled',
  'Requeued',
  'Other',
  'Success %',
  'Avg wait s',
  'Hours',
  'GPU jobs',
  'GPU hours',
  'CPU hours',
  'Node hours',
  'Memory GB-hours',
  'Avg CPUs',
  'Avg GPUs',
  'Last seen',
  'Partition',
  'Partitions',
  'GPU type',
].join(',');

const RecordTable = styled(Table)`
  table-layout: fixed;
  width: ${USER_TABLE_WIDTH}px;

  th:last-of-type,
  td:last-of-type {
    padding-right: ${({ theme }) => theme.spacing(1.5)};
    text-align: left;
  }

  th[data-freeze] {
    position: sticky;
    z-index: 3;
  }

  td[data-freeze] {
    background: ${({ theme }) => theme.background.secondary};
    position: sticky;
    z-index: 1;
  }

  th[data-edge],
  td[data-edge] {
    box-shadow: 8px 0 10px -8px ${({ theme }) => theme.border.color.strong};
  }

  td[data-sorted]:not([data-freeze]) {
    background: ${({ theme }) => theme.background.transparent.primary};
  }
`;

const IndexLabel = styled.span`
  color: ${({ theme }) => theme.font.color.tertiary};
  display: block;
  padding: ${({ theme }) => theme.spacing(1.5, 1.5)};
  padding-left: 0;
`;

const UserRow = styled(TRow)`
  &:hover {
    background: ${({ theme }) => theme.background.transparent.primary};
  }

  &:hover td[data-freeze] {
    background: ${({ theme }) => theme.background.tertiary};
  }

  &:hover td[data-sorted]:not([data-freeze]) {
    background: ${({ theme }) => theme.background.transparent.secondary};
  }

  &[data-partial='true'] td,
  &[data-partial='true'] td[data-freeze],
  &[data-partial='true'] td[data-sorted] {
    background: ${({ theme }) =>
      `color-mix(in srgb, ${theme.color.yellow[40]} 18%, ${theme.background.secondary})`};
    box-shadow: inset 0 -2px 0 ${({ theme }) => theme.color.yellow[40]};
  }

  &[data-partial='true'] td[data-edge] {
    box-shadow:
      inset 0 -2px 0 ${({ theme }) => theme.color.yellow[40]},
      8px 0 10px -8px ${({ theme }) => theme.border.color.strong};
  }

  &[data-partial='true']:hover td,
  &[data-partial='true']:hover td[data-freeze],
  &[data-partial='true']:hover td[data-sorted] {
    background: ${({ theme }) =>
      `color-mix(in srgb, ${theme.color.yellow[40]} 32%, ${theme.background.secondary})`};
  }
`;

const Clip = styled.td`
  max-width: 0;
  overflow: hidden;
`;

const Identity = styled.div`
  align-items: center;
  display: flex;
  gap: ${({ theme }) => theme.spacing(1.5)};
  min-width: 0;
`;

const IdentityText = styled.span`
  display: block;
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

const Num = styled(MonoCell)`
  font-variant-numeric: tabular-nums;
  overflow: hidden;
  text-align: right;
  text-overflow: ellipsis;
`;

const Hit = styled.mark`
  background: ${({ theme }) => theme.accent.tertiary};
  border-radius: 2px;
  color: inherit;
  padding: 0 1px;
`;

const MatchCount = styled.span`
  color: ${({ theme }) => theme.font.color.tertiary};
  flex-shrink: 0;
  font-size: ${({ theme }) => theme.font.size.xs};
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
`;

const PartialNote = styled.div`
  align-items: center;
  color: ${({ theme }) => theme.font.color.tertiary};
  display: flex;
  flex-wrap: wrap;
  font-size: ${({ theme }) => theme.font.size.xs};
  gap: ${({ theme }) => theme.spacing(1)};
  margin-top: ${({ theme }) => theme.spacing(2)};
`;

const PartialSwatch = styled.i`
  background: ${({ theme }) =>
    `color-mix(in srgb, ${theme.color.yellow[40]} 18%, ${theme.background.secondary})`};
  border-bottom: 2px solid ${({ theme }) => theme.color.yellow[40]};
  border-radius: 2px;
  display: inline-block;
  height: 10px;
  width: 16px;
`;

const SortNote = styled.div`
  align-items: center;
  color: ${({ theme }) => theme.font.color.tertiary};
  display: flex;
  font-size: ${({ theme }) => theme.font.size.xs};
  gap: ${({ theme }) => theme.spacing(2)};
  margin-top: ${({ theme }) => theme.spacing(2)};
  min-height: 16px;
`;

const TextButton = styled.button`
  background: transparent;
  border: 0;
  color: ${({ theme }) => theme.accent.primary};
  cursor: pointer;
  font-size: inherit;
  padding: 0;

  &:hover {
    text-decoration: underline;
  }
`;

const Toolbar = styled.div`
  margin-bottom: ${({ theme }) => theme.spacing(3)};
`;

const successTone = (pct: number): ThemeColor => {
  if (pct >= 90) return 'green';
  if (pct >= 50) return 'yellow';
  return 'red';
};

const fmtPct = (value?: number | null): string =>
  value === null || value === undefined || !Number.isFinite(Number(value))
    ? '—'
    : `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;

const fmtAvg = (value?: number | null): string => {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return '—';
  return number.toLocaleString(undefined, {
    maximumFractionDigits: number >= 100 ? 0 : 1,
    minimumFractionDigits: number < 10 ? 1 : 0,
  });
};

const fmtDay = (iso?: string | null): string => {
  if (!iso) return '—';
  const parsed = Date.parse(iso.endsWith('Z') ? iso : `${iso}Z`);
  if (Number.isNaN(parsed)) return '—';
  return new Date(parsed).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  });
};

const COUNT_TONE: Partial<Record<UserSortKey, ThemeColor>> = {
  running: 'green',
  pending: 'yellow',
  failed: 'red',
  timeout: 'orange',
  oom: 'red',
  preempted: 'yellow',
};

const Highlight = ({ text, query }: { text: string; query: string }) => (
  <>
    {highlightParts(text, query).map((part, index) =>
      part.hit ? <Hit key={`${part.text}-${index}`}>{part.text}</Hit> : part.text,
    )}
  </>
);

const freezeLeft = (key: string): number | undefined => {
  if (key === 'user') return INDEX_WIDTH;
  if (key === 'account') return INDEX_WIDTH + (USER_COLUMNS[0]?.width ?? 0);
  return undefined;
};

export const ClusterUsersPage = () => {
  const theme = useTheme();
  const hours = useRecoilValue(usageHoursState);
  const cluster = useRecoilValue(clusterState);
  const toast = useToast();
  const [search, setSearch] = useState('');
  const [sorts, setSorts] = useState<UserSort[]>([]);

  const users = cluster?.users;
  const partial = Boolean(users?.partial);
  const historyNote = partial
    ? `partial coverage of the ${windowPhrase(hours)}`
    : windowPhrase(hours);
  const rows = useMemo(() => (users?.available ? (users.rows ?? []) : []), [users]);
  const fairshare = cluster?.fairshare;

  const visible = useMemo(() => {
    const matched = rows.filter((row) => rowMatches(row, search));
    if (!sorts.length) return matched;
    return [...matched].sort((a, b) => compareUsers(a, b, sorts));
  }, [rows, search, sorts]);

  const totalHours = rows.reduce((sum, row) => sum + (Number(row.hours) || 0), 0);
  const totalGpuHours = rows.reduce((sum, row) => sum + (Number(row.gpu_hours) || 0), 0);
  const totalCpuHours = rows.reduce((sum, row) => sum + (Number(row.cpu_hours) || 0), 0);
  const completed = rows.reduce((sum, row) => sum + (Number(row.completed) || 0), 0);
  const terminal = rows.reduce(
    (sum, row) =>
      sum +
      (Number(row.completed) || 0) +
      (Number(row.failed) || 0) +
      (Number(row.timeout) || 0) +
      (Number(row.oom) || 0) +
      (Number(row.preempted) || 0) +
      (Number(row.cancelled) || 0),
    0,
  );

  const exportCsv = () => {
    const lines = visible.map((row, index) =>
      [
        index + 1,
        row.user,
        row.account ?? '',
        accountsOf(row).join('|'),
        row.jobs,
        row.running ?? '',
        row.pending ?? '',
        row.completed ?? '',
        row.failed ?? '',
        row.timeout ?? '',
        row.oom ?? '',
        row.preempted ?? '',
        row.cancelled ?? '',
        row.requeued ?? '',
        row.other ?? '',
        row.success_pct ?? '',
        row.avg_wait_s ?? '',
        row.hours,
        row.gpu_jobs,
        row.gpu_hours,
        row.cpu_hours ?? '',
        row.node_hours ?? '',
        row.mem_gb_hours ?? '',
        row.avg_cpus ?? '',
        row.avg_gpus ?? '',
        row.last_seen ?? '',
        row.partition ?? '',
        partitionsOf(row).join('|'),
        row.gpu_type ?? '',
      ]
        .map(csvCell)
        .join(','),
    );
    const blob = new Blob([[CSV_HEADER, ...lines].join('\n')], { type: 'text/csv' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'unity-hpc-users.csv';
    link.click();
    URL.revokeObjectURL(link.href);
    toast(`Exported ${visible.length} rows to unity-hpc-users.csv`, 'success');
  };

  const account =
    fairshare?.account && !String(fairshare.account).includes('${')
      ? fairshare.account
      : '';
  const searching = searchPieces(search).length > 0;

  return (
    <Page
      actions={
        <PageActions>
          <TimeWindowPicker />
          <Button size="small" Icon={IconDownload} onClick={exportCsv} disabled={!visible.length}>
            Export CSV
          </Button>
        </PageActions>
      }
    >
      <Grid $min="180px">
        <StatCard
          label="People"
          value={rows.length ? fmtCount(rows.length) : '—'}
          caption={
            rows.length
              ? partial
                ? `partial · ${windowPhrase(hours)}`
                : `people ${inWindow(hours)}`
              : partial
                ? `no samples · ${windowPhrase(hours)}`
                : `no live jobs ${inWindow(hours)}`
          }
          accent="purple"
        />
        <StatCard
          label="Hours used"
          value={totalHours ? fmtHours(totalHours) : '—'}
          caption={
            totalHours
              ? partial
                ? 'wall-clock elapsed · partial'
                : 'wall-clock elapsed'
              : 'no elapsed time recorded'
          }
          accent="blue"
        />
        <StatCard
          label="GPU hours"
          value={totalGpuHours ? fmtHours(totalGpuHours) : '—'}
          caption={totalGpuHours ? 'GPUs allocated × elapsed' : 'no GPU time recorded'}
          accent="green"
        />
        <StatCard
          label="CPU hours"
          value={totalCpuHours ? fmtHours(totalCpuHours) : '—'}
          caption={totalCpuHours ? 'CPUs allocated × elapsed' : 'no CPU time recorded'}
        />
        <StatCard
          label="Success"
          value={terminal ? `${Math.round((100 * completed) / terminal)}%` : '—'}
          caption={
            terminal
              ? 'share of settled jobs'
              : 'no completed, failed, or cancelled jobs'
          }
          accent="yellow"
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
        />
      </Grid>

      <Card>
        <CardHeader
          title="Users on the cluster"
          note={rows.length ? historyNote : undefined}
          warn={partial}
        />
        {partial ? (
          <PartialNote data-testid="users-partial">
            <PartialSwatch />
            partial data — live samples cover{' '}
            {users?.covered_start_utc ? fmtDay(users.covered_start_utc) : '—'}
            {' – '}
            {users?.covered_end_utc ? fmtDay(users.covered_end_utc) : '—'}
            {' of the '}
            {windowPhrase(hours)}. A value with no sample is —.
          </PartialNote>
        ) : null}
        {rows.length ? (
          <Toolbar>
            <SearchField
              data-testid="user-search"
              value={search}
              placeholder="Search any part of a user or account"
              aria-label="Search users and accounts"
              onChange={(event) => setSearch(event.target.value)}
              onClear={() => setSearch('')}
              trailing={
                <MatchCount>
                  {searching ? `${fmtCount(visible.length)} of ${fmtCount(rows.length)}` : fmtCount(rows.length)}
                </MatchCount>
              }
            />
            {sorts.length ? (
              <SortNote>
                <span>Sorted by {sortSummary(sorts)}</span>
                <TextButton type="button" onClick={() => setSorts([])}>
                  Clear sort
                </TextButton>
              </SortNote>
            ) : (
              <SortNote>Click a heading to sort. Click it again to reverse, then again to drop it.</SortNote>
            )}
          </Toolbar>
        ) : null}
        <TableScroller>
          <RecordTable data-testid="users-table">
            <colgroup>
              <col style={{ width: INDEX_WIDTH }} />
              {USER_COLUMNS.map((column) => (
                <col key={column.key} style={{ width: column.width }} />
              ))}
            </colgroup>
            <THead $fill>
              <tr>
                <th
                  scope="col"
                  aria-sort="none"
                  data-freeze=""
                  style={{ left: 0 }}
                >
                  <IndexLabel>#</IndexLabel>
                </th>
                {USER_COLUMNS.map((column) => {
                  const sortIndex = sorts.findIndex((item) => item.key === column.key);
                  const sort = sortIndex < 0 ? undefined : sorts[sortIndex];
                  const left = freezeLeft(column.key);
                  return (
                    <th
                      key={column.key}
                      scope="col"
                      aria-sort={
                        sort ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'
                      }
                      data-freeze={left === undefined ? undefined : ''}
                      data-edge={column.key === 'account' ? '' : undefined}
                      style={left === undefined ? undefined : { left }}
                    >
                      <HeadButton
                        type="button"
                        $align={column.align}
                        $on={Boolean(sort)}
                        title={`${column.title}. ${sortHint(column, sorts)}`}
                        data-testid={`user-sort-${column.key}`}
                        data-sort-dir={sort?.dir ?? ''}
                        data-sort-rank={sort ? String(sortIndex + 1) : ''}
                        onClick={() => setSorts((current) => cycleSort(current, column.key))}
                      >
                        <span>{column.label}</span>
                        <SortCue $live={Boolean(sort)} aria-hidden="true">
                          {sort?.dir === 'desc' ? (
                            <IconArrowDown size={12} stroke={2} />
                          ) : (
                            <IconArrowUp size={12} stroke={2} />
                          )}
                          {sort && sorts.length > 1 ? <SortRank>{sortIndex + 1}</SortRank> : null}
                        </SortCue>
                      </HeadButton>
                    </th>
                  );
                })}
              </tr>
            </THead>
            <tbody>
              {visible.length ? (
                visible.map((row, index) => {
                  const accounts = accountsOf(row);
                  const partitions = partitionsOf(row);
                  const primary = matchingAccount(row, search);
                  const partition = partitions[0] ?? '';
                  const sorted = new Set(sorts.map((item) => item.key));
                  const marked = (key: UserSortKey) => (sorted.has(key) ? '' : undefined);
                  const count = (key: UserSortKey, value?: number | null) => {
                    // A missing field is unknown. Coercing it to 0 says the
                    // person had no such jobs, which the archive did not say.
                    if (value === null || value === undefined || !Number.isFinite(Number(value))) {
                      return (
                        <Num key={key} data-sorted={marked(key)}>
                          —
                        </Num>
                      );
                    }
                    const number = Number(value);
                    const tone = number > 0 ? COUNT_TONE[key] : undefined;
                    return (
                      <Num key={key} data-sorted={marked(key)} style={tone ? { color: theme.tag.text[tone] } : undefined}>
                        {fmtCount(number)}
                      </Num>
                    );
                  };
                  const hoursOf = (key: UserSortKey, value?: number | null) => (
                    <Num key={key} data-sorted={marked(key)}>
                      {value === null || value === undefined || !Number.isFinite(Number(value))
                        ? '—'
                        : Number(value) === 0
                          ? '0'
                          : fmtHours(value)}
                    </Num>
                  );
                  const cell = (key: UserSortKey) => {
                    if (key === 'user') {
                      return (
                        <Clip key={key} title={row.user} data-freeze="" data-sorted={marked(key)} style={{ left: freezeLeft('user') }}>
                          <IdentityText>
                            <b>
                              <Highlight text={row.user} query={search} />
                            </b>
                          </IdentityText>
                        </Clip>
                      );
                    }
                    if (key === 'account') {
                      return (
                        <Clip
                          key={key}
                          title={accounts.join(', ') || undefined}
                          data-freeze=""
                          data-edge=""
                          data-sorted={marked(key)}
                          style={{ left: freezeLeft('account') }}
                        >
                          {primary ? (
                            <Identity>
                              <IdentityText>
                                <Highlight text={primary} query={search} />
                              </IdentityText>
                              {accounts.length > 1 ? (
                                <Tag
                                  color="gray"
                                  text={`+${accounts.length - 1}`}
                                  title={accounts.filter((item) => item !== primary).join(', ')}
                                />
                              ) : null}
                            </Identity>
                          ) : (
                            '—'
                          )}
                        </Clip>
                      );
                    }
                    if (key === 'jobs') return count(key, row.jobs);
                    if (key === 'running') return count(key, row.running);
                    if (key === 'pending') return count(key, row.pending);
                    if (key === 'completed') return count(key, row.completed);
                    if (key === 'failed') return count(key, row.failed);
                    if (key === 'timeout') return count(key, row.timeout);
                    if (key === 'oom') return count(key, row.oom);
                    if (key === 'preempted') return count(key, row.preempted);
                    if (key === 'cancelled') return count(key, row.cancelled);
                    if (key === 'gpu_jobs') return count(key, row.gpu_jobs);
                    if (key === 'hours') return hoursOf(key, row.hours);
                    if (key === 'gpu_hours') return hoursOf(key, row.gpu_hours);
                    if (key === 'cpu_hours') return hoursOf(key, row.cpu_hours);
                    if (key === 'node_hours') return hoursOf(key, row.node_hours);
                    if (key === 'mem_gb_hours') return hoursOf(key, row.mem_gb_hours);
                    if (key === 'success_pct') {
                      return (
                        <Num key={key} data-sorted={marked(key)}>
                          {row.success_pct === null || row.success_pct === undefined ? (
                            '—'
                          ) : (
                            <span style={{ color: theme.tag.text[successTone(row.success_pct)] }}>
                              {fmtPct(row.success_pct)}
                            </span>
                          )}
                        </Num>
                      );
                    }
                    if (key === 'avg_wait_s') {
                      return (
                        <Num key={key} data-sorted={marked(key)}>
                          {fmtWait(row.avg_wait_s)}
                        </Num>
                      );
                    }
                    if (key === 'avg_cpus' || key === 'avg_gpus') {
                      return (
                        <Num key={key} data-sorted={marked(key)}>
                          {fmtAvg(key === 'avg_cpus' ? row.avg_cpus : row.avg_gpus)}
                        </Num>
                      );
                    }
                    if (key === 'last_seen') {
                      return (
                        <Num key={key} title={row.last_seen ?? undefined} data-sorted={marked(key)}>
                          {fmtDay(row.last_seen)}
                        </Num>
                      );
                    }
                    return (
                      <Clip
                        key={key}
                        title={[partitions.join(', '), row.gpu_type].filter(Boolean).join(' · ') || undefined}
                        data-sorted={marked(key)}
                      >
                        {partition || row.gpu_type ? (
                          <Identity>
                            <IdentityText>{partition || '—'}</IdentityText>
                            {partitions.length > 1 ? (
                              <Tag
                                color="gray"
                                text={`+${partitions.length - 1}`}
                                title={partitions.slice(1).join(', ')}
                              />
                            ) : null}
                            {row.gpu_type ? <Tag color="blue" text={row.gpu_type} /> : null}
                          </Identity>
                        ) : (
                          '—'
                        )}
                      </Clip>
                    );
                  };
                  return (
                    <UserRow
                      key={row.user}
                      data-testid="user-row"
                      data-user={row.user}
                      data-partial={row.partial ? 'true' : 'false'}
                      title={
                        row.partial
                          ? `Partial coverage of the ${windowPhrase(hours)}. Numbers count only the sampled part.`
                          : undefined
                      }
                    >
                      <MonoCell data-freeze="" style={{ left: 0 }}>
                        {index + 1}
                      </MonoCell>
                      {USER_COLUMNS.map((column) => cell(column.key))}
                    </UserRow>
                  );
                })
              ) : (
                <TableEmptyRow colSpan={USER_COLUMNS.length + 1}>
                  {rows.length
                    ? 'No user or account contains this search'
                    : partial
                      ? `No live samples ${inWindow(hours)}`
                      : `No cluster users ${inWindow(hours)}`}
                </TableEmptyRow>
              )}
            </tbody>
          </RecordTable>
        </TableScroller>
        {!rows.length ? (
          <EmptyState
            title={
              partial
                ? `No live samples ${inWindow(hours)}`
                : users?.available
                  ? `No jobs ${inWindow(hours)}`
                  : 'No live user samples yet'
            }
            compact
          >
            {partial
              ? 'This window is outside the samples the collector has stored. Missing values stay as —.'
              : users?.available
                ? 'Nobody in the live samples has a job in this window.'
                : 'User rows come from live sacct samples. Run a telemetry retrieval to fill them.'}
          </EmptyState>
        ) : null}
      </Card>
    </Page>
  );
};
