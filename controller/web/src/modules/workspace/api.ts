import { ApiError } from '../controller/api';
import type { Job } from '../controller/types';

export type Value = string | number | boolean;
export type Parameter = {
  type: 'string' | 'integer' | 'number' | 'boolean';
  default?: Value;
  required?: boolean;
  min?: number;
  max?: number;
  choices?: Value[];
  unit?: string;
  variant_eligible?: boolean;
};
export type Resource = {
  primitive?: string;
  mode?: string;
  cpus?: number;
  gpus?: number;
  nodes?: number;
  ranks?: number;
  memory_gb?: number;
  walltime?: string;
  [key: string]: unknown;
};
export type Stage = {
  location?: string;
  id: string;
  operation: string;
  depends_on?: string[];
  purpose?: string;
  resources?: Resource;
  optional?: boolean;
  scope?: string;
  outputs?: unknown[];
};
export type Metric = {
  id?: string;
  source_field?: string;
  collector?: string;
  unit?: string;
  dimensions?: string[];
  definition?: string;
  denominator?: string;
  exclusions?: unknown;
  optional?: boolean;
  aggregations?: string[];
  aggregation?: string;
  collection_stages?: string[];
};
export type Workflow = {
  smoke_test_required?: boolean;
  title?: string;
  parameters?: string[];
  defaults?: Record<string, Value>;
  stages: Stage[];
  metrics?: string[];
};
export type Manifest = {
  schema_version: number;
  application: string;
  default_primitive: string;
  default_mode: string;
  research_question?: string;
  analyses?: Record<
    string,
    { title?: string; operation: string; parameters?: string[] }
  >;
  parameters: Record<string, Parameter>;
  workflows: Record<string, Workflow>;
  metrics?: Record<string, Metric>;
  operations?: Record<string, { location?: string; [key: string]: unknown }>;
  [key: string]: unknown;
};
export type Connection = {
  valid: boolean;
  errors: unknown[];
  manifest?: Manifest;
};
export type Draft = {
  graph?: {
    nodes: {
      id: string;
      operation: string;
      operation_version: string | number;
      scope: 'per_variant' | 'shared' | 'reduce_selected';
      purpose: string;
      parameters?: Record<string, Value>;
      resources?: Resource;
      [key: string]: unknown;
    }[];
    edges: { from_node?: string; output?: string; to_node: string; input: string; artifact_id?: string; absent?: boolean }[];
  };
  name?: string;
  workflow: string;
  question?: string;
  notes?: string;
  outcome_measure?: string;
  parameters?: Record<string, Value>;
  variant_parameters?: Record<string, Value[]>;
  combinations?: Record<string, Value>[];
  excluded_variants?: string[];
  stages?: string[];
  prerequisites?: 'add' | 'existing';
  existing_artifacts?: Record<string, string>;
  resources?: Record<string, Resource>;
  metrics?: string[];
  aggregations?: Record<string, string>;
  collection_stages?: string[];
  include_smoke_test?: boolean;
  variant_concurrency?: number;
};
export type Experiment = {
  id: string;
  name: string;
  workflow: string;
  archived: boolean;
  draft: Draft;
  version: number;
  revision: number;
  executions: string[];
  updated_at: string;
  readiness?: string;
};
export type Issue = {
  field?: string;
  message: string;
  variant_id?: string;
  stage_id?: string;
};
export type Variant = {
  id: string;
  parameters: Record<string, Value>;
  excluded?: boolean;
};
export type Check = {
  valid: boolean;
  errors: Issue[];
  variants?: Variant[];
  checks?: unknown[];
};
export type PlannedStage = {
  scheduler_script?: string;
  id: string;
  stage_id: string;
  variant_id: string;
  depends_on: string[];
  argv: string[];
  script: string;
  script_path: string;
  resources: Resource;
  location: string;
  purpose: string;
  outputs: { id: string; path: string; schema?: string; version?: string }[];
  output_dir: string;
};
export type Plan = {
  id: string;
  experiment_id?: string;
  revision?: number;
  config: Draft;
  source: { digest: string; files: unknown };
  variants: Variant[];
  stages: PlannedStage[];
  metrics: Metric[];
  excluded_variants: string[];
  checks: unknown;
  valid: boolean;
  changes?: unknown;
  recovery?: unknown;
  [key: string]: unknown;
};
export type Attempt = {
  location?: 'controller' | 'cluster';
  jobs?: Job[];
  waiting_reason?: string;
  continued_by?: string;
  resume_from?: string;
  attempts?: Attempt[];
  artifacts?: string[];
  fetch_state?: string;
  completeness?: string;
  result?: { output?: string };
  id?: string;
  stage_id?: string;
  purpose?: string;
  state?: string;
  status?: string;
  job_id?: string;
  job_ids?: string[];
  error?: string;
  output?: string;
  [key: string]: unknown;
};
export type Execution = {
  integrity_error?: (Issue | string)[];
  scheduler_observation?: { checked_at?: string; error?: string | null } | null;
  id: string;
  experiment_id: string;
  revision: number;
  plan_id: string;
  state?: string;
  status?: string;
  stages?: Attempt[] | Record<string, Attempt>;
  attempts?: Attempt[];
  updated_at?: string;
  artifacts?: unknown[];
  [key: string]: unknown;
};
export type Artifact = {
  id: string;
  execution_id?: string;
  stage_id?: string;
  purpose?: string;
  path: string;
  complete?: boolean;
  available?: boolean;
  report_url?: string;
  reports?: string[];
  files?: { path: string }[];
  [key: string]: unknown;
};

export const workspaceRequest = async <T>(
  slug: string,
  path: string,
  method = 'GET',
  body?: unknown,
): Promise<T> => {
  const response = await fetch(
    `/api/v1/projects/${encodeURIComponent(slug)}/workspace/${path}`,
    {
      method,
      headers: { 'content-type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    },
  );
  const payload = await response.json();
  if (!response.ok)
    throw new ApiError(
      payload.error ?? response.statusText,
      response.status,
      payload,
    );
  return payload as T;
};
export const workspaceApi = {
  connection: (slug: string) =>
    workspaceRequest<Connection>(slug, 'connection'),
  experiments: (slug: string) =>
    workspaceRequest<{ experiments: Experiment[] }>(
      slug,
      'experiments?archived=all',
    ),
  experiment: (slug: string, id: string) =>
    workspaceRequest<Experiment>(slug, `experiments/${id}`),
  create: (slug: string, workflow: string, name: string) =>
    workspaceRequest<Experiment>(slug, 'experiments', 'POST', {
      workflow,
      name,
    }),
  save: (slug: string, id: string, expected_version: number, draft: Draft) =>
    workspaceRequest<Experiment>(slug, `experiments/${id}`, 'PATCH', {
      expected_version,
      draft,
    }),
  action: (slug: string, id: string, action: string, body = {}) =>
    workspaceRequest<Experiment>(
      slug,
      `experiments/${id}/${action}`,
      'POST',
      body,
    ),
  remove: (slug: string, id: string) =>
    workspaceRequest(slug, `experiments/${id}`, 'DELETE'),
  check: (slug: string, id: string) =>
    workspaceRequest<Check>(slug, `experiments/${id}/check`, 'POST', {}),
  plan: (slug: string, id: string) =>
    workspaceRequest<Plan>(slug, `experiments/${id}/plans`, 'POST', {}),
  getPlan: (slug: string, id: string) =>
    workspaceRequest<Plan>(slug, `plans/${id}`),
  dispatch: (slug: string, id: string, key: string) =>
    workspaceRequest<Execution>(slug, `plans/${id}/dispatch`, 'POST', {
      idempotency_key: key,
    }),
  executions: (slug: string) =>
    workspaceRequest<{ executions: Execution[] }>(slug, 'executions'),
  recovery: (slug: string, id: string, stage_ids: string[], mode: string) =>
    workspaceRequest<Plan>(slug, `executions/${id}/recovery`, 'POST', {
      stage_ids,
      mode,
    }),
  artifacts: (slug: string) =>
    workspaceRequest<{ artifacts: Artifact[] }>(slug, 'artifacts'),
};
