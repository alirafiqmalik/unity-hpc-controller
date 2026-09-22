/**
 * Which series of one chart are hidden.
 *
 * React state is the master copy. `localStorage` is only a second copy: it can
 * throw in a private window and when site data is blocked, so every access is
 * guarded and the chart stays correct with no storage at all. Each chart keeps
 * its own choice, so hiding a type on Overview does not hide it on Analytics.
 */

import { useCallback, useState } from 'react';

const STORAGE_PREFIX = 'unity-hpc.chart.hidden.';

const read = (chartId: string): string[] => {
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + chartId);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    if (Array.isArray(parsed)) return parsed.map(String);
  } catch {
    // No storage, or bad data in it. Every series shows.
  }
  return [];
};

const write = (chartId: string, names: string[]): void => {
  try {
    window.localStorage.setItem(STORAGE_PREFIX + chartId, JSON.stringify(names));
  } catch {
    // No storage. The choice holds until the page reloads.
  }
};

export type HiddenSeries = {
  hidden: string[];
  isHidden: (name: string) => boolean;
  toggle: (name: string) => void;
};

export const useHiddenSeries = (chartId: string): HiddenSeries => {
  const [hidden, setHidden] = useState<string[]>(() => read(chartId));

  const toggle = useCallback(
    (name: string) => {
      setHidden((current) => {
        const next = current.includes(name)
          ? current.filter((one) => one !== name)
          : [...current, name];
        write(chartId, next);
        return next;
      });
    },
    [chartId],
  );

  const isHidden = useCallback(
    (name: string) => hidden.includes(name),
    [hidden],
  );

  return { hidden, isHidden, toggle };
};
