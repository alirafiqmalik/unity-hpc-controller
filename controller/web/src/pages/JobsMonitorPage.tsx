/**
 * Every ledger row across the attached projects, with a state filter, a
 * project filter and a search.
 */

import { IconAlertTriangle, IconSearch } from '@tabler/icons-react';
import { useMemo, useState } from 'react';
import { useRecoilState, useRecoilValue } from 'recoil';

import {
  purposeLabel,
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
import { Select, TextInput } from '../ui/components/Field';
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
  // Local on purpose: a project filter should not follow the operator to
  // other pages the way the shared state filter does.
  const [purpose, setPurpose] = useState('');
  const [projectFilter, setProjectFilter] = useState('');
  const activeProject = projects.some((one) => one.slug === projectFilter)
    ? projectFilter
    : '';

  const scoped = useMemo(
    () => (activeProject ? jobs.filter((job) => job.slug === activeProject) : jobs),
    [jobs, activeProject],
  );

  const counts = useMemo(() => {
    const byState = { running: 0, pending: 0, completed: 0, failed: 0 };
    for (const job of scoped) {
      const state = statusOf(job);
      if (state === 'RUNNING') byState.running += 1;
      else if (state === 'PENDING') byState.pending += 1;
      else if (state === 'COMPLETED') byState.completed += 1;
      else if (isFailState(state)) byState.failed += 1;
    }
    return byState;
  }, [scoped]);

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return scoped
      .filter((job) => !purpose || job.purpose === purpose)
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
  }, [scoped, filter, search, purpose]);

  const scope = activeProject ? `in ${activeProject}` : 'across the attached ledgers';

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
          caption={scope}
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
            <div
              style={{ alignItems: 'center', display: 'flex', flexWrap: 'wrap', gap: 8 }}
            >
              <Select
                aria-label="Project"
                value={activeProject}
                options={[
                  { value: '', label: 'All projects' },
                  ...projects.map((one) => ({ value: one.slug, label: one.slug })),
                ]}
                onChange={(event) => setProjectFilter(event.target.value)}
                style={{ width: 180 }}
              />
              <Select aria-label="Purpose" value={purpose} options={[{ value: '', label: 'All purposes' }, { value: 'experiment', label: 'Experiments' }, { value: 'smoke-test', label: 'Smoke tests' }]} onChange={(event) => setPurpose(event.target.value)} style={{ width: 150 }} />
              <IconSearch size={14} style={{ opacity: 0.5 }} aria-hidden />
              <TextInput
                value={search}
                aria-label="Search jobs"
                placeholder="Job id, exp, project, partition"
                onChange={(event) => setSearch(event.target.value)}
                style={{ width: 240 }}
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
                <th>Purpose</th>
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
                  const open = () => openJob(String(job.job_id), job.slug || undefined);
                  return (
                    <TRow
                      key={`${job.slug}-${job.job_id}`}
                      $clickable
                      tabIndex={0}
                      aria-label={`Open job ${job.job_id}`}
                      onClick={open}
                      onKeyDown={(event) => {
                        if (event.target !== event.currentTarget) return;
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault();
                          open();
                        }
                      }}
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
                      <td>{purposeLabel(job.purpose)}</td>
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
                            aria-label={`Cancel job ${job.job_id}`}
                            onKeyDown={(event) => event.stopPropagation()}
                            onClick={(event) => {
                              event.stopPropagation();
                              void runCommand(
                                job.slug as string,
                                'stop',
                                { job: job.job_id, campaign: job.campaign },
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
                <TableEmptyRow colSpan={9}>
                  {scoped.length
                    ? 'No job matches this filter'
                    : activeProject
                      ? `${activeProject} has no ledger rows yet`
                      : projects.length
                        ? 'The attached projects have no ledger rows yet'
                        : 'No attached projects. Attach one on the Project page.'}
                </TableEmptyRow>
              )}
            </tbody>
          </Table>
        </TableScroller>
      </Card>
    </Page>
  );
};
