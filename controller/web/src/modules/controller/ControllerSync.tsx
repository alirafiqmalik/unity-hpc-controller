/**
 * The refresh cycle.
 *
 * One provider reads every shared endpoint on a ten-second timer and writes
 * the answers into the store. The calls settle independently, so one dead
 * endpoint blanks its own panel and leaves the rest of the dashboard live.
 * A page that writes to the controller calls `refresh()` from `useSync()`.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { useRecoilValue, useSetRecoilState } from 'recoil';

import { controllerApi, errorText } from './api';
import {
  clusterState,
  eventsState,
  healthState,
  jobsState,
  lastSyncState,
  projectsState,
  queueState,
  syncErrorState,
  usageHoursState,
  usageState,
} from './state';

export const REFRESH_INTERVAL_MS = 10_000;

type SyncContextValue = {
  refresh: () => Promise<void>;
  /** True while a cycle is in flight. */
  syncing: boolean;
};

const SyncContext = createContext<SyncContextValue>({
  refresh: async () => {},
  syncing: false,
});

/** Re-read every shared endpoint and redraw. */
export const useSync = (): SyncContextValue => useContext(SyncContext);

/** The value of a settled promise, or the fallback when it rejected. */
const valueOr = <T,>(settled: PromiseSettledResult<T>, fallback: T): T =>
  settled.status === 'fulfilled' ? settled.value : fallback;

export const ControllerSyncProvider = ({ children }: { children: ReactNode }) => {
  const hours = useRecoilValue(usageHoursState);
  const setHealth = useSetRecoilState(healthState);
  const setCluster = useSetRecoilState(clusterState);
  const setQueue = useSetRecoilState(queueState);
  const setUsage = useSetRecoilState(usageState);
  const setJobs = useSetRecoilState(jobsState);
  const setEvents = useSetRecoilState(eventsState);
  const setProjects = useSetRecoilState(projectsState);
  const setError = useSetRecoilState(syncErrorState);
  const setLastSync = useSetRecoilState(lastSyncState);
  const [syncing, setSyncing] = useState(false);

  // The timer closes over `hours`, so the cycle must read the current value
  // rather than the one captured when the interval was created.
  const hoursRef = useRef(hours);
  hoursRef.current = hours;

  const refresh = useCallback(async () => {
    setSyncing(true);
    const settled = await Promise.allSettled([
      controllerApi.health(),
      controllerApi.cluster(),
      controllerApi.queue(),
      controllerApi.usage(hoursRef.current),
      controllerApi.jobs(),
      controllerApi.events(),
      controllerApi.projects(),
    ]);

    const rejected = settled.filter((one) => one.status === 'rejected');
    setError(
      rejected.length === settled.length
        ? errorText(
            (rejected[0] as PromiseRejectedResult | undefined)?.reason,
          ) || 'controller unreachable'
        : null,
    );

    setHealth(valueOr(settled[0], null));
    setCluster(valueOr(settled[1], null));
    setQueue(valueOr(settled[2], null));
    setUsage(valueOr(settled[3], null));
    setJobs(valueOr(settled[4], { jobs: [] }).jobs ?? []);
    setEvents(valueOr(settled[5], { events: [] }).events ?? []);
    setProjects(valueOr(settled[6], { projects: [] }).projects ?? []);
    setLastSync(Date.now());
    setSyncing(false);
  }, [
    setCluster,
    setError,
    setEvents,
    setHealth,
    setJobs,
    setLastSync,
    setProjects,
    setQueue,
    setUsage,
  ]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  // Changing the analytics window must not wait for the next tick.
  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hours]);

  const value = useMemo(() => ({ refresh, syncing }), [refresh, syncing]);

  return <SyncContext.Provider value={value}>{children}</SyncContext.Provider>;
};
