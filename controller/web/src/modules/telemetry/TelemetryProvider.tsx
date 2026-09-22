/**
 * Telemetry state for the three Settings pages.
 *
 * `/api/v1/telemetry` is only useful on Settings, so it is read here rather
 * than in the shared sync cycle: leaving the section stops the request. While
 * a retrieval runs the read repeats every two seconds, so the output panel
 * fills without a manual refresh.
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
import { Outlet } from 'react-router-dom';

import { controllerApi, errorText } from '../controller/api';
import type { Telemetry } from '../controller/types';
import { useToast } from '../../ui/components/Toast';

const POLL_WHILE_RUNNING_MS = 2000;

type SettingsChange = Parameters<typeof controllerApi.telemetrySettings>[0];

type TelemetryContextValue = {
  telemetry: Telemetry | null;
  error: string | null;
  /** Read `/api/v1/telemetry` again. */
  reload: () => Promise<void>;
  /** PATCH one setting, report it, and keep the answer. */
  save: (change: SettingsChange, note: string) => Promise<void>;
  busy: boolean;
};

const TelemetryContext = createContext<TelemetryContextValue>({
  telemetry: null,
  error: null,
  reload: async () => {},
  save: async () => {},
  busy: false,
});

export const useTelemetry = (): TelemetryContextValue =>
  useContext(TelemetryContext);

export const TelemetryProvider = ({ children }: { children?: ReactNode }) => {
  const toast = useToast();
  const [telemetry, setTelemetry] = useState<Telemetry | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const reading = useRef(false);
  const timer = useRef<number | null>(null);

  const reload = useCallback(async () => {
    if (reading.current) return;
    reading.current = true;
    try {
      const answer = await controllerApi.telemetry(10);
      setTelemetry(answer.telemetry ?? null);
      setError(null);
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      reading.current = false;
    }
  }, []);

  const save = useCallback(
    async (change: SettingsChange, note: string) => {
      setBusy(true);
      try {
        const answer = await controllerApi.telemetrySettings(change);
        setTelemetry(answer.telemetry ?? null);
        setError(null);
        toast(note, 'success');
      } catch (caught) {
        toast(errorText(caught), 'error');
      } finally {
        setBusy(false);
      }
    },
    [toast],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  // A running retrieval is the only state that changes on its own.
  useEffect(() => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
    if (!telemetry?.running) return;
    timer.current = window.setTimeout(() => {
      timer.current = null;
      void reload();
    }, POLL_WHILE_RUNNING_MS);
    return () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    };
  }, [telemetry, reload]);

  const value = useMemo(
    () => ({ telemetry, error, reload, save, busy }),
    [telemetry, error, reload, save, busy],
  );

  return (
    <TelemetryContext.Provider value={value}>
      {children ?? <Outlet />}
    </TelemetryContext.Provider>
  );
};
