/**
 * The write path to a project: attach, dispatch, stop, fetch, sync, status,
 * patch, detach.
 *
 * Every call reports what the controller answered, then refreshes the shared
 * snapshot, so a panel never shows a state the controller has already left.
 */

import { useCallback, useState } from 'react';

import { useSync } from '../controller/ControllerSync';
import {
  ApiError,
  controllerApi,
  errorText,
  type AttachBody,
  type DispatchBody,
  type FetchResult,
  type ProjectPatch,
  type RunResult,
} from '../controller/api';
import { useToast } from '../../ui/components/Toast';

/** The first line of a command's output, short enough for a notice. */
const headline = (text: string): string => {
  const trimmed = text.trim();
  if (!trimmed) return 'ok';
  const first = trimmed.split('\n')[0];
  return first.length > 180 ? `${first.slice(0, 180)}…` : first;
};

export const useProjectCommands = () => {
  const toast = useToast();
  const { refresh } = useSync();
  const [busy, setBusy] = useState(false);

  /** POST one of the project sub-routes: `stop`, `fetch`, `sync`, `status`. */
  const runCommand = useCallback(
    async (slug: string, command: string, body: unknown, okNote: string) => {
      setBusy(true);
      try {
        const answer = await controllerApi.projectCommand(slug, command, body);
        const text = headline(String(answer.output || answer.error || okNote));
        toast(
          answer.ok === false ? `Failed: ${text}` : `${okNote}: ${text}`,
          answer.ok === false ? 'error' : 'success',
        );
        await refresh();
        return answer;
      } catch (error) {
        toast(errorText(error), 'error');
        if (error instanceof ApiError && 'ok' in error.payload) {
          return error.payload as FetchResult;
        }
        return null;
      } finally {
        setBusy(false);
      }
    },
    [refresh, toast],
  );

  /**
   * Post a run. Returns the controller's answer, including a failed run.sh
   * result, so a caller can show its output. Null means no answer at all.
   */
  const dispatch = useCallback(
    async (slug: string, body: DispatchBody): Promise<RunResult | null> => {
      setBusy(true);
      try {
        const answer = await controllerApi.dispatch(slug, body);
        const text = headline(String(answer.output || answer.error || 'ok'));
        // A manifest goes to `run.sh array`, which has no dry-run.
        const verb = body.manifest
          ? 'Fan-out submitted'
          : body.dry_run
            ? 'Validated'
            : 'Dispatched';
        toast(
          answer.ok === false ? `Failed: ${text}` : `${verb}: ${text}`,
          answer.ok === false ? 'error' : 'success',
        );
        await refresh();
        return answer;
      } catch (error) {
        toast(errorText(error), 'error');
        if (error instanceof ApiError && 'ok' in error.payload) {
          return error.payload as RunResult;
        }
        return null;
      } finally {
        setBusy(false);
      }
    },
    [refresh, toast],
  );

  const launchExperiment = useCallback(
    async (slug: string, id: string, dryRun: boolean): Promise<RunResult | null> => {
      setBusy(true);
      try {
        const answer = await controllerApi.launchExperiment(slug, id, dryRun);
        toast(`${dryRun ? 'Previewed' : 'Launched'} ${id}: ${headline(answer.output || 'ok')}`, 'success');
        await refresh();
        return answer;
      } catch (error) {
        toast(errorText(error), 'error');
        if (error instanceof ApiError && 'ok' in error.payload) {
          return error.payload as RunResult;
        }
        return null;
      } finally {
        setBusy(false);
      }
    },
    [refresh, toast],
  );

  const patchProject = useCallback(
    async (slug: string, body: ProjectPatch) => {
      setBusy(true);
      try {
        await controllerApi.patchProject(slug, body);
        toast(`Updated ${slug}`, 'success');
        await refresh();
        return true;
      } catch (error) {
        toast(errorText(error), 'error');
        return false;
      } finally {
        setBusy(false);
      }
    },
    [refresh, toast],
  );

  const detachProject = useCallback(
    async (slug: string) => {
      setBusy(true);
      try {
        await controllerApi.detachProject(slug);
        toast(`Detached ${slug}`, 'success');
        await refresh();
        return true;
      } catch (error) {
        toast(errorText(error), 'error');
        return false;
      } finally {
        setBusy(false);
      }
    },
    [refresh, toast],
  );

  const attachProject = useCallback(
    async (body: AttachBody) => {
      setBusy(true);
      try {
        const answer = await controllerApi.attachProject(body);
        toast(`Attached ${answer.project?.slug ?? body.slug ?? body.path}`, 'success');
        await refresh();
        // The new slug, or '' when the answer did not name it. Null is failure.
        return answer.project?.slug ?? body.slug ?? '';
      } catch (error) {
        toast(errorText(error), 'error');
        return null;
      } finally {
        setBusy(false);
      }
    },
    [refresh, toast],
  );

  return { runCommand, dispatch, launchExperiment, patchProject, detachProject, attachProject, busy };
};
