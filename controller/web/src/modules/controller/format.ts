/**
 * Pure formatters. No DOM, no state, no network.
 *
 * These are the rules that decide what an operator reads on a number, so they
 * live in one file and every panel calls them. Ported from the previous
 * dashboard's `js/format.js` with the same wording.
 */

import type { Job } from './types';
import type { ThemeColor } from '../../ui/theme/colors';

/** Every SLURM state that counts as a failure. */
export const FAIL_STATES = [
  'FAILED',
  'TIMEOUT',
  'OUT_OF_MEMORY',
  'NODE_FAIL',
  'BOOT_FAIL',
  'DEADLINE',
  'PREEMPTED',
  'REVOKED',
] as const;

/** The five primitives. See CONTEXT.md. */
export const PRIMITIVES = ['cpu', 'gpu', 'ml', 'multi-cpu', 'multi-gpu'] as const;

/** An em dash for a missing value, the value itself otherwise. */
export const dash = (value: unknown): string =>
  value === 0 || (value !== null && value !== undefined && value !== '')
    ? String(value)
    : '—';

/** "3m ago" for a recent ISO timestamp, the timestamp itself when old. */
export const ago = (iso?: string | null): string => {
  if (!iso) return '—';
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return String(iso);
  const seconds = Math.max(0, (Date.now() - parsed) / 1000);
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h ago`;
  return iso.replace('T', ' ').replace('Z', ' UTC');
};

/** A coarse age: "59d", "3h", "12m", "45s". */
export const fmtAge = (seconds?: number | null): string => {
  if (seconds === null || seconds === undefined) return '';
  const value = Number(seconds);
  if (!Number.isFinite(value) || value < 0) return '';
  if (value < 90) return `${Math.round(value)}s`;
  if (value < 5400) return `${Math.round(value / 60)}m`;
  if (value < 172800) return `${Math.round(value / 3600)}h`;
  return `${Math.round(value / 86400)}d`;
};

/** A wait an operator can read: `45s`, `12m`, `5.3h`, `3d`. */
export const fmtWait = (seconds?: number | null): string => {
  if (seconds === null || seconds === undefined || seconds === ('' as unknown))
    return '—';
  const value = Number(seconds);
  if (!Number.isFinite(value) || value < 0) return '—';
  if (value < 90) return `${Math.round(value)}s`;
  if (value < 5400) return `${Math.round(value / 60)}m`;
  if (value < 172800) return `${(value / 3600).toFixed(1)}h`;
  return `${Math.round(value / 86400)}d`;
};

/** Seconds as h:mm:ss, or m:ss below one hour. */
export const fmtElapsed = (seconds?: number | null): string => {
  if (seconds === null || seconds === undefined) return '—';
  const value = Number(seconds);
  if (!Number.isFinite(value)) return '—';
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const rest = Math.floor(value % 60);
  const head = hours > 0 ? `${hours}:` : '';
  return `${head}${String(minutes).padStart(hours > 0 ? 2 : 1, '0')}:${String(rest).padStart(2, '0')}`;
};

/** A compact hour count: `12.4`, `3.2k`, `1.1M`. */
export const fmtHours = (hours?: number | null): string => {
  const value = Number(hours);
  if (!Number.isFinite(value) || value <= 0) return '—';
  if (value >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return value.toFixed(1);
};

/** "2.4 MB", "780 kB", "512 B". */
export const fmtBytes = (bytes?: number | null): string => {
  if (bytes === null || bytes === undefined) return '—';
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(1)} kB`;
  return `${bytes} B`;
};

/** A count with thousands separators, or an em dash. */
export const fmtCount = (value?: number | null): string =>
  value === null || value === undefined || !Number.isFinite(Number(value))
    ? '—'
    : Number(value).toLocaleString();

/** A job's status in upper case, or '' when it has none. */
export const statusOf = (job?: Job | null): string =>
  String(job?.status ?? '').toUpperCase();

export const isFailState = (state: string): boolean =>
  (FAIL_STATES as readonly string[]).includes(state);

/** True while a job may still change state. */
export const isLiveState = (state: string): boolean =>
  state !== 'COMPLETED' && state !== 'CANCELLED' && !isFailState(state);

/** The tag colour and label for a SLURM state. */
export const stateTag = (
  state?: string | null,
): { color: ThemeColor; label: string; live: boolean } => {
  const upper = String(state ?? '').toUpperCase();
  if (upper === 'RUNNING') return { color: 'green', label: 'Running', live: true };
  if (upper === 'PENDING') return { color: 'yellow', label: 'Pending', live: true };
  if (upper === 'COMPLETED')
    return { color: 'blue', label: 'Completed', live: false };
  if (upper === 'CANCELLED')
    return { color: 'gray', label: 'Cancelled', live: false };
  if (isFailState(upper))
    return { color: 'red', label: upper.replaceAll('_', ' '), live: false };
  return { color: 'gray', label: upper || 'unknown', live: false };
};

/** Sum the counts whose state name is in `names`. */
export const countStates = (
  counts: Record<string, number> | undefined,
  names: readonly string[],
): number => {
  if (!counts) return 0;
  let total = 0;
  for (const [key, value] of Object.entries(counts)) {
    if (names.includes(key.toUpperCase())) total += Number(value) || 0;
  }
  return total;
};

/** How long a pending job has waited. */
export const queuedFor = (job: Job): string => {
  if (!job.submitted_utc) return '—';
  const parsed = Date.parse(job.submitted_utc);
  if (Number.isNaN(parsed)) return '—';
  return fmtElapsed((Date.now() - parsed) / 1000);
};

/** A job's exit column: '0', an em dash while live, or the failure state. */
export const exitOf = (job: Job): string => {
  const state = statusOf(job);
  if (state === 'COMPLETED') return '0';
  if (state === 'RUNNING' || state === 'PENDING' || !state) return '—';
  return state;
};

/** Elapsed seconds over a job list, as hours. */
export const jobHours = (jobs: Job[]): number =>
  jobs.reduce((total, job) => total + (Number(job.elapsed_s) || 0), 0) / 3600;

/** The clock in the header: `14:07:32`. */
export const clockText = (date = new Date()): string =>
  date.toTimeString().slice(0, 8);
