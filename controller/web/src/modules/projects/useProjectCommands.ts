/**
 * The write path to a project: dispatch, stop, fetch, sync, patch, detach.
 *
 * Every call reports what the controller answered, then refreshes the shared
 * snapshot, so a panel never shows a state the controller has already left.
 */

import { useCallback, useState } from 'react';

import { useSync } from '../controller/ControllerSync';
import { controllerApi, errorText, type DispatchBody } from '../controller/api';
import type { Project } from '../controller/types';
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
        return null;
      } finally {
        setBusy(false);
      }
    },
    [refresh, toast],
  );

  const dispatch = useCallback(
    async (slug: string, body: DispatchBody) => {
      setBusy(true);
      try {
        const answer = await controllerApi.dispatch(slug, body);
        const text = headline(String(answer.output || answer.error || 'ok'));
        const verb = body.dry_run ? 'Validated' : 'Dispatched';
        toast(
          answer.ok === false ? `Failed: ${text}` : `${verb}: ${text}`,
          answer.ok === false ? 'error' : 'success',
        );
        await refresh();
        return answer;
      } catch (error) {
        toast(errorText(error), 'error');
        return null;
      } finally {
        setBusy(false);
      }
    },
    [refresh, toast],
  );

  const patchProject = useCallback(
    async (slug: string, body: Partial<Project>) => {
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
    async (body: {
      path: string;
      slug?: string;
      primitive?: string;
      application?: string;
    }) => {
      setBusy(true);
      try {
        const answer = await controllerApi.attachProject(body);
        toast(`Attached ${answer.project?.slug ?? body.slug ?? body.path}`, 'success');
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

  return { runCommand, dispatch, patchProject, detachProject, attachProject, busy };
};
