/**
 * Which series of one chart are hidden.
 *
 * React state is the master copy. `localStorage` is only a second copy: it can
 * throw in a private window and when site data is blocked, so every access is
 * guarded and the chart stays correct with no storage at all. Each chart keeps
 * its own choice, so hiding a type on Overview does not hide it on Analytics.
 *
 * `null` means the operator has not chosen yet, which is not the same as
 * having chosen to hide nothing. Until they do, the chart's own default
 * applies — a cluster with sixteen GPU types must not draw sixteen lines on
 * a first look.
 */

import { useCallback, useState } from 'react';

const STORAGE_PREFIX = 'unity-hpc.chart.hidden.';

/** The stored choice, or null when the operator has not made one. */
const read = (chartId: string): string[] | null => {
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + chartId);
    if (raw === null) return null;
    const parsed: unknown = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed.map(String);
  } catch {
    // No storage, or bad data in it. The chart's default applies.
  }
  return null;
};

const write = (chartId: string, names: string[]): void => {
  try {
    window.localStorage.setItem(STORAGE_PREFIX + chartId, JSON.stringify(names));
  } catch {
    // No storage. The choice holds until the page reloads.
  }
};

export type HiddenSeries = {
  isHidden: (name: string) => boolean;
  toggle: (name: string) => void;
  /** True while the chart's own default is in force. */
  usingDefault: boolean;
};

/**
 * @param chartId the storage key, one per chart
 * @param fallback the names to hide until the operator chooses otherwise
 */
export const useHiddenSeries = (
  chartId: string,
  fallback: string[] = [],
): HiddenSeries => {
  const [chosen, setChosen] = useState<string[] | null>(() => read(chartId));

  const effective = chosen ?? fallback;

  const isHidden = useCallback(
    (name: string) => effective.includes(name),
    [effective],
  );

  const toggle = useCallback(
    (name: string) => {
      setChosen((current) => {
        // The first click turns the default into a choice, so the series the
        // default hid stay hidden until they are clicked too.
        const base = current ?? fallback;
        const next = base.includes(name)
          ? base.filter((one) => one !== name)
          : [...base, name];
        write(chartId, next);
        return next;
      });
    },
    [chartId, fallback],
  );

  return { isHidden, toggle, usingDefault: chosen === null };
};
