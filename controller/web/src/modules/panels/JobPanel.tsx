/** One job, read from the snapshot the dashboard already holds. */

import { IconDownload, IconFolder, IconSquareX } from '@tabler/icons-react';
import { Link } from 'react-router-dom';
import { useRecoilValue } from 'recoil';

import { Button, ButtonGroup } from '../../ui/components/Button';
import { Card, CardHeader, KeyValue } from '../../ui/components/Card';
import { EmptyState } from '../../ui/components/EmptyState';
import { SidePanel } from '../../ui/components/SidePanel';
import { Tag, TagRow } from '../../ui/components/Tag';
import { useProjectCommands } from '../projects/useProjectCommands';
import { purposeLabel, exitOf, fmtElapsed, isLiveState, stateTag, statusOf } from '../controller/format';
import { jobsState } from '../controller/state';
import { usePanels } from './PanelProvider';

export const JobPanel = ({
  jobId,
  slug: projectSlug,
  onClose,
}: {
  jobId: string;
  slug?: string;
  onClose: () => void;
}) => {
  const jobs = useRecoilValue(jobsState);
  const { openProject } = usePanels();
  const { runCommand, busy } = useProjectCommands();
  const job = jobs.find((one) =>
    String(one.job_id) === String(jobId) && (!projectSlug || one.slug === projectSlug));

  if (!job) {
    return (
      <SidePanel open onClose={onClose} title={jobId} subtitle="job">
        <EmptyState title="This job left the snapshot">
          The ledger row is no longer in the current refresh. It may belong to a
          campaign that is not attached any more.
        </EmptyState>
      </SidePanel>
    );
  }

  const state = statusOf(job);
  const tag = stateTag(job.status);
  const slug = job.slug ?? '';

  return (
    <SidePanel
      open
      onClose={onClose}
      title={job.exp || job.job_id}
      subtitle={`#${job.job_id} · ${slug}${job.campaign ? ` / ${job.campaign}` : ''}`}
    >
      <TagRow>
        <Tag color={tag.color} text={tag.label} dot={tag.live ? 'pulsing' : true} />
        <Tag text={job.partition || 'no partition'} />
        <Tag text={job.hardware || 'hardware unknown'} mono />
      </TagRow>

      <Card>
        <CardHeader title="Detail" />
        <KeyValue label="Purpose">{purposeLabel(job.purpose)}</KeyValue>
        <KeyValue label="Execution">{job.execution_id || '—'}</KeyValue>
        <KeyValue label="Runtime">{fmtElapsed(job.elapsed_s)}</KeyValue>
        <KeyValue label="Exit">{exitOf(job)}</KeyValue>
        <KeyValue label="Attempt">{job.attempt ?? '—'}</KeyValue>
        <KeyValue label="Submitted">{job.submitted_utc || '—'}</KeyValue>
        <KeyValue label="Updated">{job.updated_utc || '—'}</KeyValue>
      </Card>

      <Card>
        <CardHeader title="Metrics" />
        <EmptyState title="No training metrics in the job ledger" compact>
          The harness records submission and state only. A project's own metrics
          stay in its results tree.
        </EmptyState>
      </Card>

      {job.execution_id ? <Card><CardHeader title="Experiment evidence" /><p>Purpose: {purposeLabel(job.purpose)}</p><Link onClick={onClose} to={`/projects/${encodeURIComponent(slug)}/executions/${encodeURIComponent(job.execution_id)}`}>Open execution logs and artifacts</Link></Card> : null}
      <ButtonGroup>
        <Button
          Icon={IconSquareX}
          size="small"
          disabled={!slug || busy || !isLiveState(state)}
          onClick={() =>
            void runCommand(slug, 'stop', { job: job.job_id, campaign: job.campaign }, 'Cancel sent')
          }
        >
          Cancel
        </Button>
        <Button
          Icon={IconDownload}
          size="small"
          disabled={!slug || busy}
          onClick={() => void runCommand(slug, 'fetch', { campaign: job.campaign }, 'Fetch finished')}
        >
          Fetch campaign results
        </Button>
        <Button
          Icon={IconFolder}
          size="small"
          variant="tertiary"
          disabled={!slug}
          onClick={() => openProject(slug)}
        >
          Open project
        </Button>
      </ButtonGroup>
    </SidePanel>
  );
};
