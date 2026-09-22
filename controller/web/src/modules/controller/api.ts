/**
 * The one JSON client for the controller API.
 *
 * It throws on a non-2xx answer, carrying the `error` field the controller
 * sends, so a caller reports what the controller said rather than a status
 * code. `controller/http.py` is the other side.
 */

import type {
  Cluster,
  CommandResult,
  ControllerEvent,
  Health,
  Job,
  Project,
  QueueAnswer,
  Telemetry,
  UsageAnswer,
} from './types';

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

const request = async <T>(path: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(path, {
    headers: { 'content-type': 'application/json' },
    ...init,
  });
  const payload = (await response.json().catch(() => ({}))) as {
    error?: string;
  };
  if (!response.ok) {
    throw new ApiError(payload.error || response.statusText, response.status);
  }
  return payload as T;
};

const post = <T>(path: string, body: unknown): Promise<T> =>
  request<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) });

export type DispatchBody = {
  exp?: string;
  campaign?: string;
  manifest?: string;
  dry_run?: boolean;
  overrides?: Record<string, string>;
  extra_args?: string;
};

export const controllerApi = {
  health: () => request<Health>('/api/v1/health'),
  cluster: () => request<Cluster>('/api/v1/cluster'),
  queue: () => request<QueueAnswer>('/api/v1/cluster/queue'),
  usage: (hours: number) =>
    request<UsageAnswer>(`/api/v1/cluster/usage?hours=${hours}`),
  jobs: () => request<{ jobs: Job[] }>('/api/v1/jobs'),
  events: (limit = 50) =>
    request<{ events: ControllerEvent[] }>(`/api/v1/events?limit=${limit}`),

  projects: () => request<{ projects: Project[] }>('/api/v1/projects'),
  project: (slug: string) =>
    request<{ project: Project }>(`/api/v1/projects/${encodeURIComponent(slug)}`),
  attachProject: (body: {
    path: string;
    slug?: string;
    primitive?: string;
  }) => post<{ ok: boolean; project: Project }>('/api/v1/projects', body),
  patchProject: (slug: string, body: Partial<Project>) =>
    request<{ ok: boolean; project: Project }>(
      `/api/v1/projects/${encodeURIComponent(slug)}`,
      { method: 'PATCH', body: JSON.stringify(body) },
    ),
  detachProject: (slug: string) =>
    request<{ ok: boolean }>(`/api/v1/projects/${encodeURIComponent(slug)}`, {
      method: 'DELETE',
    }),

  dispatch: (slug: string, body: DispatchBody) =>
    post<CommandResult>(`/api/v1/projects/${encodeURIComponent(slug)}/runs`, body),
  /** One of the project sub-routes: `stop`, `fetch`, `sync`, `status`. */
  projectCommand: (slug: string, command: string, body: unknown = {}) =>
    post<CommandResult>(
      `/api/v1/projects/${encodeURIComponent(slug)}/${command}`,
      body,
    ),

  telemetry: (limit = 10) =>
    request<{ telemetry: Telemetry }>(`/api/v1/telemetry?limit=${limit}`),
  telemetrySync: (reason = 'manual') =>
    post<{ started?: boolean; status?: string; message?: string }>(
      '/api/v1/telemetry/sync',
      { reason },
    ),
  telemetryScript: (mode: string, reason = 'manual') =>
    post<{ started?: boolean; status?: string; message?: string; error?: string }>(
      '/api/v1/telemetry/script',
      { mode, reason },
    ),
  telemetryCloseSession: () =>
    post<{ ok: boolean; skipped?: boolean; message?: string; error?: string }>(
      '/api/v1/telemetry/session',
      { action: 'close' },
    ),
  telemetrySettings: (change: {
    source?: string;
    schedule_enabled?: boolean;
    interval_minutes?: number;
    script_mode?: string;
    ssh_host?: string;
    ssh_identity?: string;
  }) =>
    request<{ ok: boolean; telemetry: Telemetry }>('/api/v1/telemetry/settings', {
      method: 'PATCH',
      body: JSON.stringify(change),
    }),
  sshTest: () =>
    post<{ ok: boolean; command?: string; output?: string; error?: string }>(
      '/api/v1/telemetry/ssh-test',
      {},
    ),
  sshUnlock: (passphrase: string) =>
    post<{ ok: boolean; output?: string; error?: string }>(
      '/api/v1/telemetry/ssh-unlock',
      { passphrase },
    ),
};

/** The message an operator should see for a thrown error. */
export const errorText = (error: unknown): string =>
  error instanceof Error ? error.message : String(error);
