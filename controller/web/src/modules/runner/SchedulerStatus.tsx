import { Hint } from '../../ui/components/Card';
import { Tag, TagRow } from '../../ui/components/Tag';

export type SchedulerJob = { job_id: string; status?: string };
export type SchedulerObservation = { checked_at?: string | null; error?: string | null };

const label = (state?: string) => {
  if (state === 'PENDING') return 'Queued (PENDING)';
  if (state === 'RUNNING') return 'Running (RUNNING)';
  return state || 'Not yet observed';
};

export const SchedulerStatus = ({ jobIds, jobs = [], observation }: {
  jobIds: string[]; jobs?: SchedulerJob[]; observation?: SchedulerObservation | null;
}) => {
  if (!jobIds.length) return null;
  const checked = observation?.checked_at;
  return <div>
    <TagRow>{jobIds.map((id) => {
      const state = jobs.find((one) => one.job_id === id)?.status;
      return <Tag key={id} color={state === 'RUNNING' ? 'yellow' : state === 'COMPLETED' ? 'green' : ['FAILED', 'CANCELLED', 'TIMEOUT', 'OUT_OF_MEMORY'].includes(state || '') ? 'red' : 'gray'} text={`Job ${id} · ${label(state)}`} dot={state === 'RUNNING' && !observation?.error ? 'pulsing' : false} />;
    })}</TagRow>
    <Hint>{checked ? <>Scheduler last checked <time dateTime={checked}>{new Date(checked).toLocaleString()}</time></> : 'Scheduler has not been checked yet.'}{observation?.error ? ` · Check failed: ${observation.error}. Showing last known states.` : ''}</Hint>
  </div>;
};
