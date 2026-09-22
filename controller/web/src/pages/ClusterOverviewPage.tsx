/**
 * Cluster overview: capacity, partition load, alerts and recent activity.
 *
 * Every number says where it came from. When the live snapshot is missing the
 * card falls back to the fleet counts in the cluster profile and says so in
 * its caption, because a fleet total and a live free count are different
 * facts and must not look the same.
 */

import { useNavigate } from 'react-router-dom';
import { useRecoilValue } from 'recoil';
import {
  IconCpu,
  IconPlayerPlay,
  IconPlus,
  IconStack2,
  IconUsers,
} from '@tabler/icons-react';

import { EventFeed } from '../modules/events/EventFeed';
import { UsageChart } from '../modules/charts/UsageChart';
import {
  clusterState,
  eventsState,
  jobsState,
  latestSampleSelector,
  liveBlockSelector,
  usageState,
} from '../modules/controller/state';
import { dash, fmtAge, fmtCount, statusOf } from '../modules/controller/format';
import { Button, ButtonGroup } from '../ui/components/Button';
import { Card, CardHeader, Grid, SplitGrid, Stack } from '../ui/components/Card';
import { EmptyState } from '../ui/components/EmptyState';
import { Meter } from '../ui/components/ProgressBar';
import { StatCard } from '../ui/components/StatCard';
import { Page } from '../ui/layout/AppLayout';

export const ClusterOverviewPage = () => {
  const navigate = useNavigate();
  const cluster = useRecoilValue(clusterState);
  const live = useRecoilValue(liveBlockSelector);
  const latest = useRecoilValue(latestSampleSelector);
  const usage = useRecoilValue(usageState);
  const jobs = useRecoilValue(jobsState);
  const events = useRecoilValue(eventsState);

  const kpis = cluster?.kpis ?? {};
  const fleet = cluster?.gpu_fleet ?? [];
  const partitions = cluster?.partitions ?? [];
  const people = cluster?.users?.rows ?? [];
  const fairshare = cluster?.fairshare;

  const mineRunning = jobs.filter((job) => statusOf(job) === 'RUNNING').length;
  const minePending = jobs.filter((job) => statusOf(job) === 'PENDING').length;

  const alerts = [...events].reverse().filter((event) => event.ok === false);
  const activity = [...events].reverse();

  /** Free capacity: the live node count when there is one, else the fleet. */
  const capacity = live.available
    ? {
        value: dash(latest.free_nodes),
        unit: latest.total_nodes ? `/ ${latest.total_nodes}` : undefined,
        caption: latest.gpu_types_free || 'free nodes in the live snapshot',
      }
    : {
        value: dash(kpis.gpus_free),
        unit: kpis.gpus_total ? `/ ${kpis.gpus_total}` : undefined,
        caption: kpis.gpus_total
          ? 'GPUs free in the fleet — no live snapshot'
          : 'waiting on a snapshot',
      };

  const peopleCard = people.length
    ? { value: fmtCount(people.length), caption: 'people in the job history' }
    : kpis.gpu_types_busy
      ? {
          value: String(kpis.gpu_types_busy),
          caption: `${fleet.length} GPU types in the fleet`,
        }
      : fairshare?.available && fairshare.factor !== null && fairshare.factor !== undefined
        ? {
            value: `${Math.round(Number(fairshare.factor) * 100)}%`,
            caption: 'your fairshare factor',
          }
        : { value: '—', caption: 'no user history in the archive' };

  const loaded = partitions
    .filter((partition) => partition.util !== null && partition.util !== undefined)
    .sort((a, b) => Number(b.util) - Number(a.util));

  return (
    <Page
      actions={
        <ButtonGroup>
          <Button
            size="small"
            variant="primary"
            Icon={IconPlayerPlay}
            onClick={() => navigate('/jobs/dispatch')}
          >
            Dispatch run
          </Button>
          <Button size="small" Icon={IconPlus} onClick={() => navigate('/jobs/project')}>
            Attach project
          </Button>
        </ButtonGroup>
      }
    >
      <Grid $min="200px">
        <StatCard
          label="Capacity free"
          value={capacity.value}
          unit={capacity.unit}
          caption={capacity.caption}
          accent="green"
          Icon={IconCpu}
        />
        <StatCard
          label="GPU jobs running"
          value={
            live.available
              ? dash(latest.gpu_running)
              : dash(kpis.gpus_allocated ?? mineRunning ?? null)
          }
          caption={
            mineRunning
              ? `${mineRunning} of these are yours`
              : live.available
                ? 'cluster GPU jobs'
                : 'GPUs allocated in the fleet'
          }
          accent="blue"
          Icon={IconPlayerPlay}
        />
        <StatCard
          label="GPU jobs queued"
          value={
            live.available
              ? dash(latest.gpu_pending)
              : dash(
                  fleet.reduce((sum, one) => sum + (Number(one.pending) || 0), 0) ||
                    minePending ||
                    null,
                )
          }
          caption={
            latest.gpu_preempt_pending
              ? `${latest.gpu_preempt_pending} preempt pending`
              : live.available
                ? 'pending on the cluster'
                : 'pending in the fleet'
          }
          accent="yellow"
          Icon={IconStack2}
        />
        <StatCard
          label="People"
          value={peopleCard.value}
          caption={peopleCard.caption}
          accent="purple"
          Icon={IconUsers}
        />
      </Grid>

      <SplitGrid>
        <Card>
          <CardHeader
            title="Partition load"
            note={
              loaded.length
                ? `${loaded.length} partitions with a rollup`
                : 'no partition rollup yet'
            }
          />
          {loaded.length ? (
            <div>
              {loaded.slice(0, 10).map((partition) => {
                const percent = Number(partition.util);
                return (
                  <Meter
                    key={partition.name}
                    label={partition.name}
                    percent={percent}
                    value={`${Math.round(percent)}%`}
                    title={`${partition.name}: ${Math.round(percent)}% allocated${
                      partition.nodes ? ` · ${partition.nodes} nodes` : ''
                    }`}
                  />
                );
              })}
            </div>
          ) : (
            <EmptyState title="No partition utilisation yet" compact>
              Partition load comes from the rolled-up telemetry. Run a retrieval
              from Settings once a cluster session is configured.
            </EmptyState>
          )}
        </Card>

        <Card>
          <CardHeader
            title="Alerts"
            note={alerts.length ? `${alerts.length} active` : 'quiet'}
            warn={alerts.length > 0}
          />
          {alerts.length ? (
            <EventFeed events={alerts} limit={6} tone="warn" />
          ) : (
            <EmptyState title="No active alerts" compact>
              A failed dispatch, retrieval or cluster command appears here.
            </EmptyState>
          )}
        </Card>
      </SplitGrid>

      <Grid $columns={2} $min="380px">
        <Card>
          <CardHeader
            title="GPU utilisation"
            note={
              usage?.usage?.window === 'latest-available'
                ? `newest data ${fmtAge(usage.usage.stale_s)} old`
                : `last ${usage?.usage?.hours ?? 24}h`
            }
            warn={usage?.usage?.window === 'latest-available'}
          />
          <UsageChart
            chartId="overview-usage"
            usage={usage?.usage}
            fallbackNames={['a100', 'a40', 'preempt']}
          />
        </Card>

        <Card>
          <CardHeader title="Recent activity" note="controller log" />
          <EventFeed events={activity} limit={8} showKind />
        </Card>
      </Grid>

      <Stack>
        {cluster && !cluster.config_present ? (
          <Card>
            <EmptyState title="No cluster profile on this machine">
              The controller has no <code>cluster-config.json</code>. Capacity,
              partitions and the GPU fleet stay empty until a recon run writes
              one.
            </EmptyState>
          </Card>
        ) : null}
      </Stack>
    </Page>
  );
};
