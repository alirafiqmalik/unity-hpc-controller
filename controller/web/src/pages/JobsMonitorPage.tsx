/** Every ledger row across the attached projects, with a filter and a search. */

import { IconAlertTriangle, IconSearch } from '@tabler/icons-react';
import { useMemo } from 'react';
import { useRecoilState, useRecoilValue } from 'recoil';

import {
  exitOf,
  FAIL_STATES,
  fmtElapsed,
  isFailState,
  isLiveState,
  stateTag,
  statusOf,
} from '../modules/controller/format';
import {
  jobFilterState,
  jobSearchState,
  jobsState,
  projectsState,
  type JobFilter,
} from '../modules/controller/state';
import { usePanels } from '../modules/panels/PanelProvider';
import { useProjectCommands } from '../modules/projects/useProjectCommands';
import { Button } from '../ui/components/Button';
import { Card, CardHeader, Grid } from '../ui/components/Card';
import { TextInput } from '../ui/components/Field';
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
import { Chip, ChipRow, Tag } from '../ui/components/Tag';
import { Page } from '../ui/layout/AppLayout';

const FILTERS: { id: JobFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'running', label: 'Running' },
  { id: 'pending', label: 'Pending' },
  { id: 'completed', label: 'Completed' },
  { id: 'failed', label: 'Failed' },
];

export const JobsMonitorPage = () => {
  const jobs = useRecoilValue(jobsState);
  const projects = useRecoilValue(projectsState);
  const [filter, setFilter] = useRecoilState(jobFilterState);
  const [search, setSearch] = useRecoilState(jobSearchState);
  const { openJob } = usePanels();
  const { runCommand, busy } = useProjectCommands();

  const counts = useMemo(() => {
    const byState = { running: 0, pending: 0, completed: 0, failed: 0 };
    for (const job of jobs) {
      const state = statusOf(job);
      if (state === 'RUNNING') byState.running += 1;
      else if (state === 'PENDING') byState.pending += 1;
      else if (state === 'COMPLETED') byState.completed += 1;
      else if (isFailState(state)) byState.failed += 1;
    }
    return byState;
  }, [jobs]);

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return jobs
      .filter((job) => {
        const state = statusOf(job);
        if (filter === 'running') return state === 'RUNNING';
        if (filter === 'pending') return state === 'PENDING';
        if (filter === 'completed') return state === 'COMPLETED';
        if (filter === 'failed') return (FAIL_STATES as readonly string[]).includes(state);
        return true;
      })
      .filter((job) => {
        if (!needle) return true;
        return [job.job_id, job.exp, job.slug, job.campaign, job.partition, job.hardware]
          .map((one) => String(one ?? '').toLowerCase())
          .some((one) => one.includes(needle));
      })
      .reverse();
  }, [jobs, filter, search]);

  return (
    <Page
      actions={
        <ChipRow>
          {FILTERS.map((one) => (
            <Chip
              key={one.id}
              type="button"
              $active={filter === one.id}
              onClick={() => setFilter(one.id)}
            >
              {one.label}
            </Chip>
          ))}
        </ChipRow>
      }
    >
      <Grid $min="190px">
        <StatCard
          label="Running"
          value={counts.running}
          caption="across the attached ledgers"
          accent="green"
        />
        <StatCard
          label="Pending"
          value={counts.pending}
          caption="waiting on the scheduler"
          accent="yellow"
        />
        <StatCard
          label="Completed"
          value={counts.completed}
          caption="finished with exit 0"
          accent="blue"
        />
        <StatCard
          label="Failed"
          value={counts.failed}
          caption="every non-zero terminal state"
          accent="red"
          Icon={counts.failed ? IconAlertTriangle : undefined}
        />
      </Grid>

      <Card>
        <CardHeader
          title={`Jobs${rows.length ? ` · ${rows.length}` : ''}`}
          action={
            <div style={{ alignItems: 'center', display: 'flex', gap: 8 }}>
              <IconSearch size={14} style={{ opacity: 0.5 }} />
              <TextInput
                value={search}
                placeholder="Job id, exp, project, partition"
                onChange={(event) => setSearch(event.target.value)}
                style={{ width: 260 }}
              />
            </div>
          }
        />
        <TableScroller>
          <Table>
            <THead>
              <tr>
                <th>Job</th>
                <th>Project / campaign</th>
                <th>State</th>
                <th>Partition</th>
                <th>Hardware</th>
                <th>Runtime</th>
                <th>Exit</th>
                <th />
              </tr>
            </THead>
            <tbody>
              {rows.length ? (
                rows.map((job) => {
                  const state = statusOf(job);
                  const tag = stateTag(job.status);
                  const exit = exitOf(job);
                  return (
                    <TRow
                      key={`${job.slug}-${job.job_id}`}
                      $clickable
                      onClick={() => openJob(String(job.job_id))}
                    >
                      <td>
                        <b style={{ fontFamily: 'inherit' }}>{job.exp || job.job_id}</b>
                        <div style={{ fontSize: 11, opacity: 0.55 }}>
                          #{job.job_id}
                        </div>
                      </td>
                      <MutedCell>
                        {job.slug || '—'}
                        {job.campaign ? ` / ${job.campaign}` : ''}
                      </MutedCell>
                      <td>
                        <Tag
                          color={tag.color}
                          text={tag.label}
                          dot={tag.live ? 'pulsing' : true}
                        />
                      </td>
                      <td>{job.partition || '—'}</td>
                      <MonoCell>{job.hardware || '—'}</MonoCell>
                      <MonoCell>{fmtElapsed(job.elapsed_s)}</MonoCell>
                      <MonoCell>{exit}</MonoCell>
                      <td>
                        {isLiveState(state) && job.slug ? (
                          <Button
                            size="small"
                            variant="tertiary"
                            disabled={busy}
                            onClick={(event) => {
                              event.stopPropagation();
                              void runCommand(
                                job.slug as string,
                                'stop',
                                { job: job.job_id },
                                'Cancel sent',
                              );
                            }}
                          >
                            Cancel
                          </Button>
                        ) : null}
                      </td>
                    </TRow>
                  );
                })
              ) : (
                <TableEmptyRow colSpan={8}>
                  {jobs.length
                    ? 'No job matches this filter'
                    : projects.length
                      ? 'The attached projects have no ledger rows yet'
                      : 'No attached projects. Register one on the Project page.'}
                </TableEmptyRow>
              )}
            </tbody>
          </Table>
        </TableScroller>
      </Card>
    </Page>
  );
};
