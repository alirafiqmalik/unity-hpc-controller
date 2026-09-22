/**
 * Every visual the rollups can support, over one chosen window.
 *
 * The window chips drive the `hours` query the sync cycle sends, so every
 * panel on this page describes the same span. When the API had to slide the
 * window back to the newest rows it says so in the card note, because a chart
 * headed "last 24h" that holds month-old rows is a wrong reading.
 */

import { useRecoilState, useRecoilValue } from 'recoil';

import { BarList } from '../modules/charts/BarList';
import { HourHeatmap } from '../modules/charts/HourHeatmap';
import { OutcomeDonut } from '../modules/charts/OutcomeDonut';
import { UsageChart } from '../modules/charts/UsageChart';
import {
  fmtAge,
  fmtCount,
  fmtHours,
  fmtWait,
  jobHours,
} from '../modules/controller/format';
import {
  clusterState,
  jobsState,
  projectsState,
  usageHoursState,
  usageState,
} from '../modules/controller/state';
import { Card, CardHeader, Grid, SplitGrid } from '../ui/components/Card';
import { Chip, ChipRow } from '../ui/components/Tag';
import { StatCard } from '../ui/components/StatCard';
import { Page } from '../ui/layout/AppLayout';

const WINDOWS: { hours: number; label: string }[] = [
  { hours: 24, label: '24h' },
  { hours: 168, label: '7d' },
  { hours: 720, label: '30d' },
];

export const ClusterAnalyticsPage = () => {
  const [hours, setHours] = useRecoilState(usageHoursState);
  const usage = useRecoilValue(usageState);
  const cluster = useRecoilValue(clusterState);
  const projects = useRecoilValue(projectsState);
  const jobs = useRecoilValue(jobsState);

  const block = usage?.usage;
  const stats = usage?.stats ?? cluster?.stats;
  const slid = block?.window === 'latest-available';
  const windowNote = slid
    ? `newest data ${fmtAge(block?.stale_s)} old`
    : `last ${block?.hours ?? hours}h`;

  const byType = block?.by_type ?? [];
  const byHardware = stats?.by_hardware ?? [];
  const byPartition = stats?.by_partition ?? [];

  /** Per-project GPU-hours when projects are attached; hardware otherwise. */
  const projectRows = projects.length
    ? projects.map((project) => {
        const mine = jobs.filter((job) => job.slug === project.slug);
        return {
          label: project.slug,
          value: jobHours(mine),
          text: fmtHours(jobHours(mine)),
        };
      })
    : [];

  return (
    <Page
      actions={
        <ChipRow>
          {WINDOWS.map((option) => (
            <Chip
              key={option.hours}
              type="button"
              $active={hours === option.hours}
              onClick={() => setHours(option.hours)}
            >
              {option.label}
            </Chip>
          ))}
        </ChipRow>
      }
    >
      <Grid $min="200px">
        <StatCard
          label="Finished runs"
          value={stats?.available ? fmtCount(stats.runs) : '—'}
          caption={stats?.available ? 'terminal rows in this window' : 'no rollup yet'}
          accent="blue"
        />
        <StatCard
          label="GPU hours"
          value={stats?.available ? fmtHours(stats.gpu_hours) : '—'}
          caption={stats?.available ? 'elapsed across those runs' : 'no rollup yet'}
          accent="green"
        />
        <StatCard
          label="Average wait"
          value={stats?.available ? fmtWait(stats.wait_s_avg) : '—'}
          caption={
            stats?.wait_s_gpu_avg !== null && stats?.wait_s_gpu_avg !== undefined
              ? `GPU jobs waited ${fmtWait(stats.wait_s_gpu_avg)}`
              : 'submit to start'
          }
          accent="yellow"
        />
        <StatCard
          label="GPU types seen"
          value={byType.length || '—'}
          caption={
            byType.length
              ? `peak ${Math.round(Math.max(...byType.map((one) => one.peak)))}%`
              : 'no per-type series in this window'
          }
          accent="purple"
        />
      </Grid>

      <Card>
        <CardHeader
          title="Cluster utilisation by GPU type"
          note={windowNote}
          warn={slid}
        />
        <UsageChart
          chartId="analytics-usage"
          usage={block}
          height={260}
          fallbackNames={['a100', 'a40', 'cpu-only']}
        />
      </Card>

      <SplitGrid>
        <Card>
          <CardHeader title="Job outcomes" note={windowNote} warn={slid} />
          <OutcomeDonut counts={usage?.outcomes?.counts} />
        </Card>
        <Card>
          <CardHeader
            title="Average utilisation per type"
            note={byType.length ? `${byType.length} types` : undefined}
          />
          <BarList
            rows={byType.map((one) => ({
              label: one.gpu_type,
              value: one.avg,
              text: `${one.avg}%`,
            }))}
            emptyTitle="No per-type averages in this window"
            emptyBody="The rollup reports an average once it holds hourly samples."
          />
        </Card>
      </SplitGrid>

      <Grid $columns={2} $min="360px">
        <Card>
          <CardHeader
            title={
              projectRows.length
                ? 'GPU hours by attached project'
                : 'GPU hours by hardware'
            }
            note={projectRows.length ? 'from the attached ledgers' : 'from the rollup'}
          />
          <BarList
            rows={
              projectRows.length
                ? projectRows
                : byHardware.map((one) => ({
                    label: one.hardware ?? 'unspecified',
                    value: Number(one.gpu_hours) || 0,
                    text: fmtHours(one.gpu_hours),
                  }))
            }
            emptyTitle="No attached projects and no rollup yet"
            emptyBody="Attach a project, or run a telemetry retrieval, to fill this."
          />
        </Card>
        <Card>
          <CardHeader title="GPU hours by partition" note="from the rollup" />
          <BarList
            rows={byPartition.map((one) => ({
              label: one.partition ?? 'unspecified',
              value: Number(one.gpu_hours) || 0,
              text: fmtHours(one.gpu_hours),
            }))}
            emptyTitle="No per-partition rollup in this window"
            emptyBody="Partition totals come from the archived job table."
          />
        </Card>
      </Grid>

      <Card>
        <CardHeader
          title="When is the cluster busy?"
          note="hour × day of week · UTC"
        />
        <HourHeatmap cells={block?.heatmap ?? []} />
      </Card>

      <Card>
        <CardHeader
          title="Wait time by partition"
          note="average from submit to start"
        />
        <BarList
          rows={byPartition
            .filter(
              (one) => one.wait_s_avg !== null && one.wait_s_avg !== undefined,
            )
            .map((one) => ({
              label: one.partition ?? 'unspecified',
              value: Number(one.wait_s_avg) || 0,
              text: fmtWait(one.wait_s_avg),
            }))}
          emptyTitle="No wait times in this window"
          emptyBody="A wait is measured only on rows that carry both a submit and a start time."
        />
      </Card>
    </Page>
  );
};
