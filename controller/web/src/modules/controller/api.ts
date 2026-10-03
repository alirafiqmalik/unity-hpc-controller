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
  /** The parsed body of the failed answer, such as a failed run.sh result. */
  readonly payload: Record<string, unknown>;

  constructor(message: string, status: number, payload: Record<string, unknown> = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }
}

const request = async <T>(path: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(path, {
    headers: { 'content-type': 'application/json' },
    ...init,
  });
  const payload = (await response.json().catch(() => ({}))) as {
    error?: string;
    output?: string;
  };
  if (!response.ok) {
    // A failed run.sh answers 502 with its `output` and no `error`.
    const message =
      payload.error || payload.output?.trim().split('\n').pop() || response.statusText;
    throw new ApiError(message, response.status, payload);
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

/**
 * What a project declares it needs, read from the project record. Free-form:
 * `cpus_per_task`, `memory_gb`, `gpus_per_task`, `gpu_type`, `walltime` and
 * `notes` are common, but any key may appear. The controller does not enforce
 * any of it; it is a declaration, not a measurement or a scheduler limit.
 */
export type ProjectResources = Record<string, unknown>;

/** `run_sh` lets the controller run `run.sh sync`; `disabled` refuses it. */
export type SyncPolicy = 'run_sh' | 'disabled';

export type ExperimentStatus = 'ready' | 'needs_input' | 'historical';

/** One entry of the project-owned `unityHPC/experiments.json`. */
export type Experiment = {
  id: string;
  title?: string | null;
  description?: string | null;
  resources?: ProjectResources | null;
  launch?: {
    kind: 'script' | 'run';
    path?: string;
    args?: string[];
    dry_run_arg?: string;
    exp?: string;
    campaign?: string;
    overrides?: Record<string, string>;
  } | null;
  status?: ExperimentStatus | string | null;
  ledger_exp?: string | null;
};

/**
 * The project record with the fields `types.ts` does not carry yet. Every
 * extra field is optional: an older controller omits them.
 */
export type ProjectRecord = Project & {
  resources?: ProjectResources | null;
  sync_policy?: SyncPolicy | string | null;
  experiments?: Experiment[] | null;
  experiments_error?: string | null;
  artifact_fetch?: boolean;
};

export type AttachBody = {
  path: string;
  slug?: string;
  primitive?: string;
  remote_dir?: string;
  unity_host?: string;
  campaign?: string;
  resources?: ProjectResources;
  sync_policy?: SyncPolicy;
};

export type ProjectPatch = Partial<
  Pick<
    ProjectRecord,
    'path' | 'primitive' | 'remote_dir' | 'unity_host' | 'campaign' | 'overrides'
  >
> & {
  resources?: ProjectResources;
  sync_policy?: SyncPolicy;
};

/** The answer of `POST /runs`: a `run.sh` result plus what it was called with. */
export type RunResult = CommandResult & {
  returncode?: number;
  /** True when `run.sh` printed its `[dry-run]` marker. */
  dry_run?: boolean;
  argv?: string[];
};

/** Fetch runs scheduler log retrieval, then an optional project artifact hook. */
export type FetchResult = CommandResult & {
  logs?: CommandResult;
  artifacts?: CommandResult;
};

const withHours = (path: string, hours?: number): string =>
  hours === undefined ? path : `${path}?hours=${hours}`;

export const controllerApi = {
  health: () => request<Health>('/api/v1/health'),
  cluster: (hours?: number) =>
    request<Cluster>(withHours('/api/v1/cluster', hours)),
  queue: (hours?: number) =>
    request<QueueAnswer>(withHours('/api/v1/cluster/queue', hours)),
  usage: (hours: number) =>
    request<UsageAnswer>(`/api/v1/cluster/usage?hours=${hours}`),
  jobs: () => request<{ jobs: Job[] }>('/api/v1/jobs'),
  events: (limit = 50) =>
    request<{ events: ControllerEvent[] }>(`/api/v1/events?limit=${limit}`),

  projects: () => request<{ projects: ProjectRecord[] }>('/api/v1/projects'),
  project: (slug: string) =>
    request<{ project: ProjectRecord }>(
      `/api/v1/projects/${encodeURIComponent(slug)}`,
    ),
  experiments: (slug: string) =>
    request<{ experiments: Experiment[] }>(
      `/api/v1/projects/${encodeURIComponent(slug)}/experiments`,
    ),
  launchExperiment: (slug: string, id: string, dryRun: boolean) =>
    post<RunResult>(
      `/api/v1/projects/${encodeURIComponent(slug)}/experiments/${encodeURIComponent(id)}/runs`,
      { dry_run: dryRun },
    ),
  attachProject: (body: AttachBody) =>
    post<{ ok: boolean; project: ProjectRecord }>('/api/v1/projects', body),
  patchProject: (slug: string, body: ProjectPatch) =>
    request<{ ok: boolean; project: ProjectRecord }>(
      `/api/v1/projects/${encodeURIComponent(slug)}`,
      { method: 'PATCH', body: JSON.stringify(body) },
    ),
  detachProject: (slug: string) =>
    request<{ ok: boolean }>(`/api/v1/projects/${encodeURIComponent(slug)}`, {
      method: 'DELETE',
    }),

  dispatch: (slug: string, body: DispatchBody) =>
    post<RunResult>(`/api/v1/projects/${encodeURIComponent(slug)}/runs`, body),
  /** One of the project sub-routes: `stop`, `fetch`, `sync`, `status`. */
  projectCommand: (slug: string, command: string, body: unknown = {}) =>
    post<FetchResult>(
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
    post<{ ok: boolean; remembered?: boolean; output?: string; error?: string }>(
      '/api/v1/telemetry/ssh-unlock',
      { passphrase },
    ),
};

/** The message an operator should see for a thrown error. */
export const errorText = (error: unknown): string =>
  error instanceof Error ? error.message : String(error);
