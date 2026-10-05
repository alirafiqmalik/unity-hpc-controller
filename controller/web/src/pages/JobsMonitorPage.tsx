/**
 * Every ledger row across the attached projects, with a state filter, a
 * project filter, a search, and multi-select delete.
 */

import { IconAlertTriangle, IconSearch, IconTrash, IconX } from '@tabler/icons-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRecoilState, useRecoilValue, useSetRecoilState } from 'recoil';

import { controllerApi, errorText } from '../modules/controller/api';
import { useSync } from '../modules/controller/ControllerSync';
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
import type { Job } from '../modules/controller/types';
import { usePanels } from '../modules/panels/PanelProvider';
import { useProjectCommands } from '../modules/projects/useProjectCommands';
import { ActionBar, ActionBarCount, ActionBarDivider } from '../ui/components/ActionBar';
import { Button, ButtonGroup, IconButton } from '../ui/components/Button';
import { Card, CardHeader, Grid } from '../ui/components/Card';
import { Select, SelectionCheckbox, TextInput } from '../ui/components/Field';
import { Modal } from '../ui/components/SidePanel';
import { StatCard } from '../ui/components/StatCard';
import {
  MonoCell,
  MutedCell,
  SelectCell,
  SelectHead,
  Table,
  TableEmptyRow,
  TableScroller,
  THead,
  TRow,
} from '../ui/components/Table';
import { Chip, ChipRow, Tag } from '../ui/components/Tag';
import { useToast } from '../ui/components/Toast';
import { Page } from '../ui/layout/AppLayout';

const jobKey = (job: Pick<Job, 'slug' | 'campaign' | 'job_id'>): string =>
  `${job.slug ?? ''}\u0000${job.campaign ?? ''}\u0000${job.job_id}`;

const FILTERS: { id: JobFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'running', label: 'Running' },
  { id: 'pending', label: 'Pending' },
  { id: 'completed', label: 'Completed' },
  { id: 'failed', label: 'Failed' },
];

export const JobsMonitorPage = () => {
  const jobs = useRecoilValue(jobsState);
  const setJobs = useSetRecoilState(jobsState);
  const projects = useRecoilValue(projectsState);
  const [filter, setFilter] = useRecoilState(jobFilterState);
  const [search, setSearch] = useRecoilState(jobSearchState);
  const { openJob } = usePanels();
  const { runCommand, busy } = useProjectCommands();
  const { refresh } = useSync();
  const toast = useToast();
  const [selected, setSelected] = useState<string[]>([]);
  const [pending, setPending] = useState<Job[]>([]);
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
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

  const visibleKeys = useMemo(() => rows.map(jobKey), [rows]);
  const selectedKeys = useMemo(
    () => selected.filter((key) => visibleKeys.includes(key)),
    [selected, visibleKeys],
  );
  const allSelected = visibleKeys.length > 0 && selectedKeys.length === visibleKeys.length;
  const someSelected = selectedKeys.length > 0 && !allSelected;
  const selectedRows = useMemo(
    () => rows.filter((job) => selectedKeys.includes(jobKey(job))),
    [rows, selectedKeys],
  );
  const pendingLive = pending.filter((job) => isLiveState(statusOf(job))).length;
  const pendingLinked = pending.filter((job) => job.execution_id).length;

  useEffect(() => {
    setSelected((current) => {
      const next = current.filter((key) => visibleKeys.includes(key));
      return next.length === current.length ? current : next;
    });
  }, [visibleKeys]);

  const askDelete = useCallback(() => {
    const next = selectedRows.filter((job) => job.slug && job.campaign);
    if (!next.length) return;
    setPending(next);
    setConfirming(true);
  }, [selectedRows]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (confirming || deleting) return;
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.tagName === 'SELECT' ||
          target.isContentEditable)
      ) {
        return;
      }
      if (!selectedKeys.length) return;
      if (event.key === 'Escape') {
        setSelected([]);
        return;
      }
      if (event.key === 'Delete' || event.key === 'Backspace') {
        event.preventDefault();
        askDelete();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [askDelete, confirming, deleting, selectedKeys.length]);

  const toggleAll = () => setSelected(allSelected ? [] : visibleKeys);
  const toggleOne = (key: string) =>
    setSelected((current) =>
      current.includes(key) ? current.filter((one) => one !== key) : [...current, key],
    );

  const closeConfirm = () => {
    if (deleting) return;
    setConfirming(false);
    setPending([]);
  };

  const removeSelected = async () => {
    const payload = pending.flatMap((job) =>
      job.slug && job.campaign
        ? [{ slug: job.slug, campaign: job.campaign, job_id: String(job.job_id) }]
        : [],
    );
    if (!payload.length) return;
    const keys = new Set(payload.map((job) => jobKey(job)));
    setDeleting(true);
    try {
      const result = await controllerApi.deleteJobs(payload);
      setJobs((current) => current.filter((job) => !keys.has(jobKey(job))));
      setSelected([]);
      setPending([]);
      setConfirming(false);
      const noun = result.deleted === 1 ? 'row' : 'rows';
      toast(
        result.missing
          ? `Removed ${result.deleted} ${noun} from Job Monitor. ${result.missing} were already gone.`
          : `Removed ${result.deleted} ${noun} from Job Monitor`,
        'success',
      );
      void refresh();
    } catch (caught) {
      toast(errorText(caught), 'error');
    } finally {
      setDeleting(false);
    }
  };

  const scope = activeProject ? `in ${activeProject}` : 'across the attached ledgers';
  const selectedCount = selectedKeys.length;

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
                <SelectHead>
                  <SelectionCheckbox
                    aria-label="Select all shown jobs"
                    checked={allSelected}
                    indeterminate={someSelected}
                    disabled={!rows.length}
                    onChange={toggleAll}
                  />
                </SelectHead>
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
                  const key = jobKey(job);
                  const open = () => openJob(String(job.job_id), job.slug || undefined);
                  return (
                    <TRow
                      key={`${job.slug}-${job.job_id}`}
                      $clickable
                      $selected={selectedKeys.includes(key)}
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
                      <SelectCell
                        onClick={(event) => event.stopPropagation()}
                        onKeyDown={(event) => event.stopPropagation()}
                      >
                        <SelectionCheckbox
                          aria-label={`Select job ${job.job_id}`}
                          checked={selectedKeys.includes(key)}
                          onChange={() => toggleOne(key)}
                        />
                      </SelectCell>
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
                <TableEmptyRow colSpan={10}>
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

      {selectedCount ? (
        <ActionBar>
          <SelectionCheckbox
            aria-label={allSelected ? 'Clear selection' : 'Select every shown job'}
            checked={allSelected}
            indeterminate={someSelected}
            onChange={toggleAll}
          />
          <ActionBarCount>
            {selectedCount} selected
          </ActionBarCount>
          <ActionBarDivider />
          <Button
            size="small"
            variant="danger"
            Icon={IconTrash}
            disabled={deleting}
            aria-label="Delete selected jobs"
            onClick={askDelete}
          >
            Delete
          </Button>
          <IconButton
            Icon={IconX}
            aria-label="Clear selection"
            onClick={() => setSelected([])}
          />
        </ActionBar>
      ) : null}

      <Modal
        open={confirming}
        onClose={closeConfirm}
        title={`Delete ${pending.length} monitor ${pending.length === 1 ? 'row' : 'rows'}`}
      >
        <p style={{ margin: 0 }}>
          This removes the selected {pending.length === 1 ? 'row' : 'rows'} from the
          Job Monitor. The project ledger retains the scheduler receipts.
          {pendingLive
            ? ` ${pendingLive} ${pendingLive === 1 ? 'job is' : 'jobs are'} still live on the scheduler and ${pendingLive === 1 ? 'is' : 'are'} not cancelled.`
            : ''}{' '}
          Remote files stay.
          {pendingLinked
            ? ` ${pendingLinked} ${pendingLinked === 1 ? 'experiment execution that points' : 'experiment executions that point'} at ${pendingLinked === 1 ? 'this row stays' : 'these rows stay'}.`
            : ''}
        </p>
        <ButtonGroup align="right">
          <Button size="small" disabled={deleting} onClick={closeConfirm}>
            Cancel
          </Button>
          <Button
            size="small"
            variant="danger"
            Icon={IconTrash}
            disabled={deleting || !pending.length}
            onClick={() => void removeSelected()}
          >
            Delete
          </Button>
        </ButtonGroup>
      </Modal>
    </Page>
  );
};
