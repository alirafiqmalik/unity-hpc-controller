/**
 * Queue and partitions: per-partition load, pending work, and the depth trend.
 *
 * The pending table reads the attached ledgers, not `squeue`. When the cluster
 * has pending GPU jobs and none of them are yours, the empty row says exactly
 * that, so an empty table is never read as an empty queue.
 */

import { useTheme } from '@emotion/react';
import { useRecoilValue } from 'recoil';

import { TrendChart } from '../modules/charts/TrendChart';
import {
  clusterState,
  jobsState,
  liveBlockSelector,
  queueState,
} from '../modules/controller/state';
import {
  dash,
  fmtWait,
  queuedFor,
  stateTag,
  statusOf,
} from '../modules/controller/format';
import { usePanels } from '../modules/panels/PanelProvider';
import { Card, CardHeader, Grid, SplitGrid } from '../ui/components/Card';
import { EmptyState } from '../ui/components/EmptyState';
import { Meter, ProgressBar } from '../ui/components/ProgressBar';
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
import { Tag } from '../ui/components/Tag';
import { Page } from '../ui/layout/AppLayout';

export const ClusterQueuePage = () => {
  const theme = useTheme();
  const queue = useRecoilValue(queueState);
  const cluster = useRecoilValue(clusterState);
  const live = useRecoilValue(liveBlockSelector);
  const jobs = useRecoilValue(jobsState);
  const { openJob } = usePanels();

  const partitions = queue?.partitions ?? cluster?.partitions ?? [];
  const fleet = cluster?.gpu_fleet ?? [];
  const pending = jobs.filter((job) => statusOf(job) === 'PENDING');
  const queueLive = queue?.live ?? live;
  const trend = queueLive.available ? queueLive.trend : live.trend;

  /** Pending per partition from the ledgers; the fleet when none is attached. */
  const mix = (() => {
    const buckets = new Map<string, number>();
    for (const job of pending) {
      const key = job.partition || 'unspecified';
      buckets.set(key, (buckets.get(key) ?? 0) + 1);
    }
    if (buckets.size === 0) {
      for (const entry of fleet) {
        if (entry.pending) buckets.set(entry.gpu_type, entry.pending);
      }
    }
    const total = [...buckets.values()].reduce((sum, one) => sum + one, 0);
    return {
      total,
      rows: [...buckets.entries()]
        .sort((a, b) => b[1] - a[1])
        .map(([name, count]) => ({
          name,
          count,
          percent: total ? (count / total) * 100 : 0,
        })),
      source: pending.length ? 'attached ledgers' : 'GPU fleet',
    };
  })();

  return (
    <Page>
      <Grid $min="200px">
        <StatCard
          label="Partitions"
          value={partitions.length || '—'}
          caption={partitions.length ? 'in the cluster profile' : 'no cluster profile'}
        />
        <StatCard
          label="Pending — cluster"
          value={dash(queueLive.latest?.gpu_pending)}
          caption={
            queueLive.available ? 'GPU jobs pending on the cluster' : 'no live snapshot'
          }
          accent="yellow"
        />
        <StatCard
          label="Running — cluster"
          value={dash(queueLive.latest?.gpu_running)}
          caption={
            queueLive.available ? 'GPU jobs running on the cluster' : 'no live snapshot'
          }
          accent="green"
        />
        <StatCard
          label="Pending — yours"
          value={pending.length}
          caption="rows in the attached ledgers"
          accent="blue"
        />
      </Grid>

      <Card>
        <CardHeader
          title="Partition load"
          note={partitions.length ? 'allocated against capacity' : undefined}
        />
        {partitions.length ? (
          <Grid $min="260px">
            {partitions.map((partition) => {
              const total = Number(partition.gpus_total) || Number(partition.nodes) || 0;
              const runningHere = jobs.filter(
                (job) => job.partition === partition.name && statusOf(job) === 'RUNNING',
              ).length;
              const pendingHere = jobs.filter(
                (job) => job.partition === partition.name && statusOf(job) === 'PENDING',
              ).length;
              const typePending = (partition.gpu_types ?? []).reduce((sum, type) => {
                const entry = fleet.find((one) => one.gpu_type === type);
                return sum + (entry ? Number(entry.pending) || 0 : 0);
              }, 0);
              const util =
                partition.util !== null && partition.util !== undefined
                  ? Number(partition.util)
                  : null;
              const used =
                util !== null && total
                  ? Math.round((total * util) / 100)
                  : total
                    ? Math.min(total, runningHere)
                    : runningHere;
              const percent =
                util !== null
                  ? util
                  : total
                    ? (used / total) * 100
                    : runningHere
                      ? 40
                      : 0;
              return (
                <PartitionCard
                  key={partition.name}
                  name={partition.name}
                  used={used}
                  total={total}
                  percent={percent}
                  queued={pendingHere || typePending}
                  wait={
                    partition.wait_s_avg !== null && partition.wait_s_avg !== undefined
                      ? fmtWait(partition.wait_s_avg)
                      : '—'
                  }
                  measured={util !== null}
                />
              );
            })}
          </Grid>
        ) : (
          <EmptyState title="No partitions in the cluster profile">
            Partition capacity comes from <code>cluster-config.json</code>. A recon
            run writes it.
          </EmptyState>
        )}
      </Card>

      <SplitGrid>
        <Card>
          <CardHeader title="Pending jobs" note="top of the attached ledgers" />
          <TableScroller>
            <Table>
              <THead>
                <tr>
                  <th>Job ID</th>
                  <th>Project</th>
                  <th>Partition</th>
                  <th>Hardware</th>
                  <th>Queued for</th>
                  <th>State</th>
                </tr>
              </THead>
              <tbody>
                {pending.length ? (
                  pending.slice(0, 12).map((job) => {
                    const tag = stateTag(job.status);
                    return (
                      <TRow
                        key={job.job_id}
                        $clickable
                        onClick={() => openJob(String(job.job_id))}
                      >
                        <MonoCell>{job.job_id}</MonoCell>
                        <MutedCell>{job.slug || '—'}</MutedCell>
                        <td>{job.partition || '—'}</td>
                        <MonoCell>{job.hardware || '—'}</MonoCell>
                        <MonoCell>{queuedFor(job)}</MonoCell>
                        <td>
                          <Tag color={tag.color} text={tag.label} dot="pulsing" />
                        </td>
                      </TRow>
                    );
                  })
                ) : (
                  <TableEmptyRow colSpan={6}>
                    {queueLive.available && queueLive.latest?.gpu_pending
                      ? `${queueLive.latest.gpu_pending} GPU jobs pending on the cluster · none in the attached ledgers`
                      : 'No pending jobs in the attached ledgers'}
                  </TableEmptyRow>
                )}
              </tbody>
            </Table>
          </TableScroller>
        </Card>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Card>
            <CardHeader
              title="Queue depth"
              note={trend.length ? `${trend.length} samples` : undefined}
            />
            <TrendChart trend={trend} height={168} />
          </Card>
          <Card>
            <CardHeader
              title="Pending mix"
              note={mix.total ? `${mix.total} from the ${mix.source}` : undefined}
            />
            {mix.rows.length ? (
              <div>
                {mix.rows.map((row) => (
                  <Meter
                    key={row.name}
                    label={row.name}
                    percent={row.percent}
                    value={`${row.count}`}
                    // A share of the queue, not a load: the bar must not pick
                    // its colour from the value.
                    color={theme.color.blue[40]}
                    title={`${row.name}: ${row.count} pending · ${Math.round(row.percent)}% of the queue`}
                  />
                ))}
              </div>
            ) : (
              <EmptyState title="Nothing is pending" compact>
                Neither the attached ledgers nor the GPU fleet report queued work.
              </EmptyState>
            )}
          </Card>
        </div>
      </SplitGrid>
    </Page>
  );
};

const PartitionCard = ({
  name,
  used,
  total,
  percent,
  queued,
  wait,
  measured,
}: {
  name: string;
  used: number;
  total: number;
  percent: number;
  queued: number;
  wait: string;
  measured: boolean;
}) => (
  <Card>
    <CardHeader title={name} note={measured ? undefined : 'estimated'} />
    <div
      style={{
        alignItems: 'baseline',
        display: 'flex',
        gap: 6,
        marginBottom: 10,
      }}
    >
      <span style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.02em' }}>
        {used}
      </span>
      <span style={{ fontSize: 12, opacity: 0.6 }}>/ {total || '—'} busy</span>
    </div>
    <ProgressBar percent={percent} />
    <div
      style={{
        display: 'flex',
        fontSize: 11,
        justifyContent: 'space-between',
        marginTop: 10,
        opacity: 0.75,
      }}
    >
      <span>queued: {queued}</span>
      <span>avg wait: {wait}</span>
    </div>
  </Card>
);
