/**
 * Every visual the rollups can support, over one chosen window.
 *
 * The window chips drive the `hours` query the sync cycle sends, so every
 * panel on this page describes the same span. A window that the samples do
 * not cover completely says so, and the hour map underlines those cells.
 */

import styled from '@emotion/styled';
import { useRecoilValue } from 'recoil';

import { BarList } from '../modules/charts/BarList';
import { HourHeatmap } from '../modules/charts/HourHeatmap';
import { OutcomeDonut } from '../modules/charts/OutcomeDonut';
import { UsageChart } from '../modules/charts/UsageChart';
import {
  fmtCount,
  fmtHours,
  fmtWait,
  jobHours,
} from '../modules/controller/format';
import { TimeWindowPicker, windowPhrase } from '../modules/controller/TimeWindow';
import {
  clusterState,
  jobsState,
  projectsState,
  usageHoursState,
  usageState,
} from '../modules/controller/state';
import { Card, CardHeader, Grid } from '../ui/components/Card';
import { StatCard } from '../ui/components/StatCard';
import { Page } from '../ui/layout/AppLayout';

const OutcomeSections = styled.div`
  display: grid;
  gap: ${({ theme }) => theme.spacing(4)};
`;

const OutcomeSection = styled.section`
  min-width: 0;

  & + & {
    border-top: 1px solid ${({ theme }) => theme.border.color.light};
    padding-top: ${({ theme }) => theme.spacing(4)};
  }
`;

const OutcomeHeading = styled.h4`
  color: ${({ theme }) => theme.font.color.primary};
  font-size: ${({ theme }) => theme.font.size.sm};
  font-weight: ${({ theme }) => theme.font.weight.semiBold};
  margin-bottom: ${({ theme }) => theme.spacing(2)};
`;

const OutcomeNote = styled.p`
  color: ${({ theme }) => theme.font.color.tertiary};
  font-size: ${({ theme }) => theme.font.size.xs};
  margin-bottom: ${({ theme }) => theme.spacing(3)};
`;

const OutcomeTypeGrid = styled.div`
  display: grid;
  gap: ${({ theme }) => theme.spacing(3)};
  grid-template-columns: minmax(0, 4fr) minmax(0, 5fr);

  @media (max-width: 1200px) {
    grid-template-columns: minmax(0, 1fr);
  }
`;

const TypeExplanation = styled.p`
  color: ${({ theme }) => theme.font.color.tertiary};
  font-size: ${({ theme }) => theme.font.size.xs};
  margin-bottom: ${({ theme }) => theme.spacing(2)};
`;

export const ClusterAnalyticsPage = () => {
  const hours = useRecoilValue(usageHoursState);
  const usage = useRecoilValue(usageState);
  const cluster = useRecoilValue(clusterState);
  const projects = useRecoilValue(projectsState);
  const jobs = useRecoilValue(jobsState);

  const block = usage?.usage;
  const stats = usage?.stats ?? cluster?.stats;
  const partial = Boolean(block?.partial);
  const historical = block?.source === 'sacct';
  const windowNote =
    historical
      ? `sacct job allocations · ${Math.round(block.covered_hours ?? 0)} hours covered${partial ? ' · partial' : ''}`
      : partial
        ? `partial · ${windowPhrase(hours)}`
        : windowPhrase(hours);

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
      actions={<TimeWindowPicker />}
    >
      <Grid $min="200px">
        <StatCard
          label="Finished runs"
          value={stats?.available ? fmtCount(stats.runs) : '—'}
          caption={stats?.available ? 'terminal rows in this window' : 'no rollup yet'}
          accent="blue"
        />
        <StatCard
          label={historical ? 'GPU hours allocated' : 'GPU hours'}
          value={historical ? fmtHours(block?.gpu_hours) : stats?.available ? fmtHours(stats.gpu_hours) : '—'}
          caption={historical ? 'from sacct in this window' : stats?.available ? 'elapsed across those runs' : 'no rollup yet'}
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
          label={historical ? 'Average GPUs allocated' : 'GPU types seen'}
          value={historical ? fmtCount(block?.avg_allocated) : byType.length || '—'}
          caption={
            historical
              ? `peak ${fmtCount(block?.peak_allocated)} · ${byType.length} types`
              : byType.length
              ? `peak ${Math.round(Math.max(...byType.map((one) => one.peak)))}%`
              : 'no per-type series in this window'
          }
          accent="purple"
        />
      </Grid>

      <Card>
        <CardHeader
          title={historical ? 'GPUs allocated to jobs by type' : 'Cluster utilisation by GPU type'}
          note={windowNote}
          warn={partial}
        />
        <UsageChart
          chartId="analytics-usage"
          usage={block}
          height={260}
          fallbackNames={['a100', 'a40', 'cpu-only']}
        />
      </Card>

      <Card>
        <CardHeader
          title="When is the cluster busy?"
          note={`hour × day of week · UTC · average ${historical ? 'GPUs allocated to jobs' : 'GPU capacity allocated'}`}
        />
        <HourHeatmap
          cells={block?.heatmap ?? []}
          unit={block?.unit}
          windowStartUtc={block?.window_start_utc}
          windowEndUtc={block?.window_end_utc}
          emptyMessage={block?.available && !historical
            ? 'GPU fleet capacities are required to combine hourly samples into a cluster allocation percentage.'
            : undefined}
        />
      </Card>

      <OutcomeTypeGrid>
        <Card>
          <CardHeader title="Job outcomes" note={windowNote} warn={partial} />
          <OutcomeSections>
            <OutcomeSection aria-labelledby="all-job-outcomes">
              <OutcomeHeading id="all-job-outcomes">All jobs</OutcomeHeading>
              <OutcomeDonut counts={usage?.outcomes?.counts} />
            </OutcomeSection>
            <OutcomeSection aria-labelledby="my-job-outcomes">
              <OutcomeHeading id="my-job-outcomes">My jobs</OutcomeHeading>
              <OutcomeNote>Personal job outcomes are not available yet.</OutcomeNote>
              <OutcomeDonut counts={undefined} placeholder />
            </OutcomeSection>
          </OutcomeSections>
        </Card>
        <Card>
          <CardHeader
            title={historical ? 'Average allocated GPUs per type' : 'Average utilisation per type'}
            note={byType.length ? `${byType.length} types` : undefined}
          />
          {historical ? (
            <TypeExplanation>
              Average GPUs reserved by jobs over the selected window. Decimals come from averaging over time.
            </TypeExplanation>
          ) : null}
          <BarList
            rows={byType.map((one) => ({
              label: one.gpu_type,
              value: one.avg,
              text: `${one.avg}${historical ? ' GPUs' : '%'}`,
            }))}
            emptyTitle="No per-type averages in this window"
            emptyBody="The rollup reports an average once it holds hourly samples."
          />
        </Card>
      </OutcomeTypeGrid>

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
            emptyBody="Partition totals come from the live job rollup for this window."
          />
        </Card>
      </Grid>

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
