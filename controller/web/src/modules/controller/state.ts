/**
 * The one store: a Recoil atom per endpoint, plus the selectors that read it.
 *
 * One atom per endpoint, not one object for the whole snapshot, so a panel
 * re-renders when its own endpoint changes and stays still when a sibling's
 * does.
 */

import { atom, selector } from 'recoil';

import type {
  Cluster,
  ControllerEvent,
  Health,
  Job,
  LiveBlock,
  LiveSample,
  Project,
  QueueAnswer,
  UsageAnswer,
} from './types';

export const healthState = atom<Health | null>({
  key: 'controller/health',
  default: null,
});

export const clusterState = atom<Cluster | null>({
  key: 'controller/cluster',
  default: null,
});

export const queueState = atom<QueueAnswer | null>({
  key: 'controller/queue',
  default: null,
});

export const usageState = atom<UsageAnswer | null>({
  key: 'controller/usage',
  default: null,
});

export const jobsState = atom<Job[]>({
  key: 'controller/jobs',
  default: [],
});

export const eventsState = atom<ControllerEvent[]>({
  key: 'controller/events',
  default: [],
});

export const projectsState = atom<Project[]>({
  key: 'controller/projects',
  default: [],
});

/** Set only when every endpoint of one cycle failed. */
export const syncErrorState = atom<string | null>({
  key: 'controller/syncError',
  default: null,
});

/** When the last cycle finished, so the header can age it. */
export const lastSyncState = atom<number | null>({
  key: 'controller/lastSync',
  default: null,
});

/** The analytics window, in hours. It drives the usage request. */
export const usageHoursState = atom<number>({
  key: 'controller/usageHours',
  default: 24,
});

export type JobFilter = 'all' | 'running' | 'pending' | 'completed' | 'failed';

export const jobFilterState = atom<JobFilter>({
  key: 'controller/jobFilter',
  default: 'all',
});

/** The text typed into the Monitor search box. */
export const jobSearchState = atom<string>({
  key: 'controller/jobSearch',
  default: '',
});

const EMPTY_LIVE: LiveBlock = {
  available: false,
  latest: {},
  trend: [],
  age_s: null,
  fresh: false,
};

/** The live cluster block, or an empty stand-in when no snapshot arrived. */
export const liveBlockSelector = selector<LiveBlock>({
  key: 'controller/liveBlock',
  get: ({ get }) => get(clusterState)?.live ?? EMPTY_LIVE,
});

/** The newest sample in the live block. */
export const latestSampleSelector = selector<LiveSample>({
  key: 'controller/latestSample',
  get: ({ get }) => get(liveBlockSelector).latest ?? {},
});

export type ConnectionState = {
  /** `live` only when a sample arrived inside the live window. */
  kind: 'live' | 'stale' | 'waiting' | 'down';
  label: string;
  clusterName: string;
};

/**
 * What the header pill says.
 *
 * Rows in the mirror do not mean the collector still runs. A snapshot older
 * than the live window is history, and the pill must never call it live.
 */
export const connectionSelector = selector<ConnectionState>({
  key: 'controller/connection',
  get: ({ get }) => {
    const cluster = get(clusterState);
    const error = get(syncErrorState);
    const health = get(healthState);
    const live = get(liveBlockSelector);
    const clusterName = cluster?.cluster || 'unity';

    if (error && !health) {
      return { kind: 'down', label: 'controller unreachable', clusterName };
    }
    if (live.fresh) {
      return { kind: 'live', label: 'live sync', clusterName };
    }
    if (live.available) {
      const age = live.age_s ?? null;
      const text = age === null ? 'old' : `${ageWord(age)} old`;
      return { kind: 'stale', label: `snapshot ${text}`, clusterName };
    }
    return { kind: 'waiting', label: 'waiting on snapshot', clusterName };
  },
});

/** The same coarse age the formatters use, without importing the DOM layer. */
const ageWord = (seconds: number): string => {
  if (seconds < 90) return `${Math.round(seconds)}s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86400)}d`;
};
