import { ApiError } from '../controller/api';
import type { SchedulerJob, SchedulerObservation } from './SchedulerStatus';

export type Parameter = {
  name: string; label: string; type: 'string' | 'integer' | 'number' | 'boolean';
  default?: string | number | boolean; choices?: (string | number | boolean)[];
  min?: number; max?: number; required?: boolean; unit?: string;
};
export type Stage = {
  id: string; operation?: string; location?: string; purpose?: string; state?: string;
  depends_on?: string[]; resources?: Record<string, unknown>; argv?: unknown[];
  script?: string; output_dir?: string; completeness?: string; retrieval?: string;
  outputs?: unknown[];
  error?: string; waiting_reason?: string; job_ids?: string[]; jobs?: SchedulerJob[];
  attempts?: { id: string; state: string; job_ids?: string[] }[];
};
export type Workflow = { id: string; title: string; parameters: Parameter[]; stages: Stage[]; purpose: string; metrics: string[] };
export type Catalog = { valid: boolean; errors: unknown[]; workflows: Workflow[]; application: string };
export type Plan = {
  id: string; valid: boolean; stages: Stage[]; variants: unknown[];
  source?: { digest: string }; inputs?: unknown[]; checks?: unknown;
  config?: { name?: string; workflow?: string; parameters?: Record<string, unknown> }; recovery?: unknown; errors?: unknown;
};
export type Prepared = { ok: boolean; valid: boolean; plan_id?: string; plan?: Plan; error?: string; checks?: unknown };
export type Artifact = { id: string; path: string; complete?: boolean; files?: { path: string }[]; purpose?: string };
export type Execution = { id: string; plan_id: string; state: string; summary: string; experiment_name?: string; updated_at?: string; stages: Stage[]; artifacts?: Artifact[]; scheduler_observation?: SchedulerObservation | null };
export type Log = { text: string | null; reason?: string; cursor?: string; next_offset?: number | null; availability: string; boundary?: string; legacy_tail?: boolean };

const projectRequest = async <T>(slug: string, namespace: 'runner' | 'workspace', path: string, method = 'GET', body?: unknown): Promise<T> => {
  const response = await fetch(`/api/v1/projects/${encodeURIComponent(slug)}/${namespace}/${path}`, {
    method, headers: { 'content-type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const payload = await response.json();
  if (!response.ok) throw new ApiError(payload.error ?? response.statusText, response.status, payload);
  return payload as T;
};

export const runnerRequest = <T>(slug: string, path: string, method = 'GET', body?: unknown) =>
  projectRequest<T>(slug, 'runner', path, method, body);

export const executionLogTail = (slug: string, executionId: string, stageId: string) =>
  projectRequest<{ stages: { id: string; job_ids: string[]; output: string }[] }>(slug, 'workspace',
    `executions/${encodeURIComponent(executionId)}/logs?${new URLSearchParams({ stage_id: stageId })}`);
