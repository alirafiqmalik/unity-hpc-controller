/**
 * The JSON client of the LLMs & Agents evaluation workspace.
 *
 * Every call goes to `/api/v1/projects/<slug>/genai/…`; `controller/genai_http.py`
 * is the other side. Types mirror what `controller/genai.py` writes.
 */

import { ApiError } from '../controller/api';

export type AssessmentKind = 'pass_fail' | 'category' | 'score';

export type AssessmentValue = { value: unknown; kind: AssessmentKind };

export type AssessmentFull = AssessmentValue & { rationale: string; source: string };

export type AssessmentSummary = {
  kind: AssessmentKind;
  count: number;
  pass: number;
  fail: number;
  values: Record<string, number>;
  pass_rate?: number;
  mean?: number;
};

export type TraceRow = {
  trace_id: string;
  request: string;
  response: string;
  request_time: string;
  duration_s: number | null;
  tokens: number | null;
  prompt_tokens: number | null;
  state: string;
  error: string;
  session: string;
  dataset_record: string;
  model: string;
  assessments: Record<string, AssessmentValue>;
  expectations: Record<string, string>;
  evaluation_id: string;
  evaluation: string;
  dataset: string;
  evaluation_state: string;
  collection: string;
  purpose: string;
};

export type Span = {
  index: number;
  name: string;
  type: string;
  duration_s: number | null;
  tokens: number | Record<string, number> | null;
  inputs: unknown;
  outputs: unknown;
  reasoning: unknown;
  tool_calls: unknown;
  tool_results: unknown;
  status: unknown;
  attributes: Record<string, unknown>;
};

export type TraceFull = Omit<TraceRow, 'assessments' | 'expectations' | 'evaluation_state' | 'collection' | 'purpose'> & {
  request: string | null;
  response: string | null;
  reasoning: string | null;
  inputs: Record<string, unknown> | null;
  tags: Record<string, unknown>;
  assessments: Record<string, AssessmentFull>;
  expectations: Record<string, unknown>;
  spans: Span[];
  metadata: Record<string, unknown>;
  nested: Record<string, Record<string, unknown>>;
};

export type Collection = { id: string; path: string; default: boolean; label: string };

export type TracesAnswer = {
  traces: TraceRow[];
  total: number;
  offset: number;
  limit: number;
  assessments: Record<string, AssessmentSummary>;
  expectations: string[];
  states: Record<string, number>;
  models: string[];
  sessions: number;
  datasets: string[];
  collections: Collection[];
  collection: string;
};

export type DatasetProfile = {
  records: number;
  labeled: number;
  unlabeled: number;
  inputs_schema: string[];
  expectations_schema: string[];
  sources: Record<string, number>;
  tag_keys: string[];
};

export type DatasetSummary = {
  id: string;
  path: string;
  name: string;
  description: string;
  tags: Record<string, string>;
  created_utc: string;
  updated_utc: string;
  modified_utc: string;
  source: Record<string, unknown>;
  declared: boolean;
  license: string;
  profile: DatasetProfile;
  raw_files: number;
  evaluations: number;
  last_evaluation_utc: string;
};

export type DatasetRecord = {
  record_id: string;
  inputs: Record<string, unknown>;
  expectations: Record<string, unknown>;
  source: Record<string, unknown>;
  tags: Record<string, unknown>;
  fingerprint: string;
};

export type DatasetDetail = Omit<DatasetSummary, 'raw_files' | 'evaluations' | 'last_evaluation_utc' | 'modified_utc'> & {
  records_file: string;
  records: DatasetRecord[];
  total: number;
  offset: number;
  limit: number;
  evaluations: Evaluation[];
  files: { path: string; size: number }[];
  added?: number;
  /** Existing records whose expectations or tags took the incoming values. */
  updated?: number;
  skipped?: number;
};

export type Evaluation = {
  id: string;
  path: string;
  collection: string;
  indexed: boolean;
  name: string;
  model: string;
  dataset: string;
  started: string;
  finished: string;
  n_items: number | null;
  traces: number | null;
  metrics: Record<string, number>;
  agent: Record<string, unknown>;
  prompt: Record<string, unknown>;
  scorers: string[];
  state: 'complete' | 'running' | 'failed' | 'empty' | 'superseded' | 'unknown' | string;
  purpose: string;
  source: 'workspace' | 'project' | string;
  execution_id: string | null;
  experiment_id: string | null;
  variant_id: string | null;
  stage_id: string | null;
  assessments: Record<string, AssessmentSummary>;
  trace_files: string[];
};

export type EvaluationDetail = Evaluation & {
  manifest: Record<string, unknown>;
  provenance: Record<string, unknown>;
  sessions: string[];
  models: string[];
  token_total: number;
  duration_total_s: number;
  states: Record<string, number>;
};

export type Execution = {
  id: string;
  state: string;
  experiment_id: string | null;
  approved_at: string;
  updated_at: string;
  kind: string;
  stages: { id: string; state: string; location: string; job_ids: string[]; completeness: string }[];
};

export type EvaluationsAnswer = { evaluations: Evaluation[]; collections: Collection[]; executions: Execution[] };

export type Session = {
  session: string;
  traces: number;
  models: string[];
  evaluations: string[];
  datasets: string[];
  first: string;
  last: string;
  tokens: number;
  duration_s: number;
  states: Record<string, number>;
  assessments: Record<string, AssessmentSummary>;
};

export type PromptFile = { path: string; name: string; size: number; sha256: string; preview: string };

export type PromptVersion = {
  id: string;
  version: string;
  sha256: string;
  details: Record<string, unknown>;
  evaluations: { id: string; name: string; started: string }[];
  models: string[];
  first: string;
  last: string;
};

export type AgentVersion = {
  id: string;
  model: string;
  details: Record<string, unknown>;
  pinned_revision: string;
  evaluations: { id: string; name: string; started: string; state: string; metrics: Record<string, number>; dataset: string }[];
  traces: number;
  first: string;
  last: string;
  pass_rate: number | null;
};

export type LaunchParameter = {
  name: string;
  label: string;
  type: 'string' | 'integer' | 'number' | 'boolean';
  default: unknown;
  choices: unknown[] | null;
  min: number | null;
  max: number | null;
  unit: string | null;
  allowed_purposes: string[] | null;
};

export type LaunchWorkflow = {
  id: string;
  title: string;
  parameters: LaunchParameter[];
  stages: { id: string; operation: string; purpose: string; location: string; resources: Record<string, unknown> }[];
  metrics: string[];
  smoke_test_required: boolean;
  purpose: 'smoke-test' | 'experiment';
  /** The dataset this workflow is bound to, when its name or a declared binding says. */
  dataset: string | null;
  /** The parameter that picks the dataset, when one of them does. */
  dataset_parameter: string | null;
};

export type LaunchOptions = {
  valid: boolean;
  errors: unknown[];
  workflows: LaunchWorkflow[];
  datasets: string[];
  dataset_parameter: string | null;
  scorers: Record<string, { label?: string; definition?: string; unit?: string }>;
};

export type LaunchAnswer = {
  ok: boolean;
  stage?: string;
  error?: string;
  experiment_id?: string;
  plan_id?: string;
  checks?: { errors?: { field: string; message: string }[]; checks?: { id: string; passed: boolean; output: string }[] };
  execution?: Execution;
  note?: string;
};

export type Summary = {
  slug: string;
  application: string;
  path: string;
  connector: Record<string, unknown>;
  counts: { datasets: number; evaluations: number; evaluations_complete: number; traces: number; sessions: number; models: number };
  assessments: Record<string, AssessmentSummary>;
  latest_evaluation: Evaluation | null;
  docs_path: string | null;
  collections: Collection[];
};

export const genaiRequest = async <T>(slug: string, path: string, method = 'GET', body?: unknown): Promise<T> => {
  const response = await fetch(`/api/v1/projects/${encodeURIComponent(slug)}/genai/${path}`, {
    method,
    headers: { 'content-type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const payload = (await response.json().catch(() => ({}))) as { error?: string };
  if (!response.ok) {
    throw new ApiError(payload.error || response.statusText, response.status, payload as Record<string, unknown>);
  }
  return payload as T;
};

const query = (params: Record<string, string | number | boolean | undefined>) => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '' && value !== false) search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
};

export type TraceFilters = {
  evaluation?: string;
  collection?: string;
  dataset?: string;
  session?: string;
  state?: string;
  model?: string;
  search?: string;
  assessment?: string;
  assessment_value?: string;
  since?: string;
  purpose?: string;
  superseded?: boolean;
  sort?: string;
  order?: 'asc' | 'desc';
  offset?: number;
  limit?: number;
};

export const genaiApi = {
  summary: (slug: string) => genaiRequest<Summary>(slug, 'summary'),
  datasets: (slug: string) => genaiRequest<{ datasets: DatasetSummary[]; datasets_dir: string }>(slug, 'datasets'),
  dataset: (slug: string, id: string, params: { offset?: number; limit?: number; search?: string } = {}) =>
    genaiRequest<DatasetDetail>(slug, `datasets/${encodeURIComponent(id)}${query(params)}`),
  createDataset: (slug: string, body: { name: string; description?: string; tags?: Record<string, string> }) =>
    genaiRequest<DatasetDetail>(slug, 'datasets', 'POST', body),
  updateDataset: (slug: string, id: string, body: { description?: string; tags?: Record<string, string> }) =>
    genaiRequest<DatasetDetail>(slug, `datasets/${encodeURIComponent(id)}`, 'PATCH', body),
  addRecords: (
    slug: string,
    id: string,
    body: { records?: unknown[]; traces?: { trace_id: string; evaluation_id: string }[]; response_as_expectation?: boolean },
  ) => genaiRequest<DatasetDetail>(slug, `datasets/${encodeURIComponent(id)}/records`, 'POST', body),
  evaluations: (slug: string, collection = 'all') =>
    genaiRequest<EvaluationsAnswer>(slug, `evaluations${query({ collection })}`),
  evaluation: (slug: string, id: string) => genaiRequest<EvaluationDetail>(slug, `evaluations/${encodeURIComponent(id)}`),
  launchOptions: (slug: string) => genaiRequest<LaunchOptions>(slug, 'launch'),
  launch: (slug: string, body: { workflow: string; name?: string; parameters?: Record<string, unknown>; dataset?: string; dataset_parameter?: string }) =>
    genaiRequest<LaunchAnswer>(slug, 'evaluations', 'POST', body),
  traces: (slug: string, filters: TraceFilters = {}) => genaiRequest<TracesAnswer>(slug, `traces${query(filters)}`),
  trace: (slug: string, evaluationId: string, traceId: string) =>
    genaiRequest<TraceFull>(slug, `traces/${encodeURIComponent(traceId)}${query({ evaluation: evaluationId })}`),
  sessions: (slug: string, params: { evaluation?: string; collection?: string } = {}) =>
    genaiRequest<{ sessions: Session[]; total: number; collections: Collection[]; collection: string }>(slug, `sessions${query(params)}`),
  prompts: (slug: string) => genaiRequest<{ files: PromptFile[]; observed: PromptVersion[]; prompts_dir: string }>(slug, 'prompts'),
  agentVersions: (slug: string) =>
    genaiRequest<{ versions: AgentVersion[]; pinned: Record<string, { revision: string; source: string }> }>(slug, 'agent-versions'),
};

/** True when an assessment value counts as a pass. */
export const passes = (item: AssessmentValue | AssessmentFull): boolean =>
  item.value === true || (typeof item.value === 'string' && ['pass', 'true', 'yes'].includes(item.value.toLowerCase()));
