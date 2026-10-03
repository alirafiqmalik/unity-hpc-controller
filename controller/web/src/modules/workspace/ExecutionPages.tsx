import { useEffect, useState } from 'react';
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router-dom';
import { errorText } from '../controller/api';
import { ago, purposeLabel } from '../controller/format';
import { usePanels } from '../panels/PanelProvider';
import { Button, ButtonGroup } from '../../ui/components/Button';
import {
  Card,
  CardHeader,
  Grid,
  Hint,
  KeyValue,
} from '../../ui/components/Card';
import { Checkbox, Field, Select, TextInput } from '../../ui/components/Field';
import { Table, TableScroller, THead } from '../../ui/components/Table';
import {
  workspaceApi,
  workspaceRequest,
  type Artifact,
  type Attempt,
  type Execution,
  type Plan,
  type Value,
} from './api';
import { TypedInput } from './ExperimentEditor';
import { SchedulePlan } from './Schedules';
import {
  ErrorNotice,
  JsonDetails,
  useWorkspace,
  WorkspacePage,
} from './Workspace';

export const PlanReview = () => {
  const { slug, refreshConnection } = useWorkspace();
  const { planId = '' } = useParams();
  const navigate = useNavigate();
  const [plan, setPlan] = useState<Plan | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [approved, setApproved] = useState(false);
  const [customPaths, setCustomPaths] = useState<Record<string, string>>({});
  const [customResult, setCustomResult] = useState<unknown>(null);
  useEffect(() => {
    setPlan(null);
    setApproved(false);
    workspaceApi
      .getPlan(slug, planId)
      .then(setPlan)
      .catch((e) => setError(errorText(e)));
  }, [slug, planId]);
  const dispatch = async () => {
    setBusy(true);
    setError('');
    try {
      // One immutable plan has one dispatch intent, including after a lost response.
      const execution = await workspaceApi.dispatch(
        slug,
        planId,
        `review:${planId}`,
      );
      navigate(`../runs?execution=${encodeURIComponent(execution.id)}`);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <WorkspacePage
      title="Review execution plan"
      actions={
        <Button
          variant="primary"
          disabled={!plan?.valid || !approved || busy}
          onClick={() => void dispatch()}
        >
          {busy ? 'Dispatching…' : 'Dispatch this plan'}
        </Button>
      }
    >
      <ErrorNotice error={error} />
      {customResult ? (
        <Card>
          <CardHeader title="Saved project-owned custom script" />
          <JsonDetails
            title="Script and registered workflow"
            value={customResult}
          />
          <Hint>
            Manual edits remain project-owned. Select the registered workflow in
            a new experiment, then check and review again.
          </Hint>
        </Card>
      ) : null}
      {plan ? (
        <>
          <Card>
            <CardHeader
              title={`Plan ${plan.id}`}
              note={`${plan.variants.length} variants · ${plan.stages.length} stages`}
            />
            <p>
              This approval covers only the exact source, configuration, stages,
              resources, and outputs shown here. An edit requires a new check
              and review.
            </p>
            {plan.experiment_id ? (
              <Link to={`../experiments/${plan.experiment_id}`}>
                Return to experiment editor
              </Link>
            ) : null}
            <Checkbox
              label="I reviewed this exact plan, including its scripts, resources, and outputs"
              checked={approved}
              onChange={(e) => setApproved(e.target.checked)}
            />
          </Card>
          {plan.recovery ? (
            <Card>
              <CardHeader title="Recovery scope and compatibility" />
              <JsonDetails title="Recovery plan" value={plan.recovery} />
            </Card>
          ) : null}
          <SchedulePlan planId={plan.id} reviewed={approved} />
          <Card>
            <CardHeader title="Immutable source and configuration" />
            <KeyValue label="Source digest">{plan.source?.digest}</KeyValue>
            <JsonDetails
              title="Source files and versions"
              value={plan.source}
            />
            <JsonDetails title="Frozen configuration" value={plan.config} />
            <JsonDetails
              title="Effective runtime paths and allocation settings"
              value={plan.runtime_overrides ?? {}}
            />
            <JsonDetails
              title="Input versions and references"
              value={plan.inputs ?? plan.config.existing_artifacts ?? {}}
            />
            <JsonDetails
              title="Differences from prior execution"
              value={
                plan.differences ??
                plan.changes ??
                'First reviewed configuration'
              }
            />
            <JsonDetails title="Setup check results" value={plan.checks} />
          </Card>
          <Card>
            <CardHeader title="Exact variants" />
            <TableScroller>
              <Table>
                <THead>
                  <tr>
                    <th>Variant</th>
                    <th>Parameters</th>
                    <th>Included</th>
                  </tr>
                </THead>
                <tbody>
                  {plan.variants.map((v) => (
                    <tr key={v.id}>
                      <td>{v.id}</td>
                      <td>{JSON.stringify(v.parameters)}</td>
                      <td>
                        {v.excluded || plan.excluded_variants?.includes(v.id)
                          ? 'Explicitly excluded'
                          : 'Yes'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </TableScroller>
          </Card>
          {plan.stages.map((stage) => (
            <Card key={stage.id}>
              <CardHeader
                title={stage.id}
                note={`Purpose: ${purposeLabel(stage.purpose)}`}
              />
              <Grid>
                <div>
                  <KeyValue label="Variant">
                    {stage.variant_id || 'Shared prerequisite'}
                  </KeyValue>
                  <KeyValue label="Location">{stage.location}</KeyValue>
                  <KeyValue label="Execution mode">
                    {stage.resources.mode}
                  </KeyValue>
                  <KeyValue label="Resources">
                    {stage.resources.primitive} · {stage.resources.cpus} CPUs ·{' '}
                    {stage.resources.gpus} GPUs · {stage.resources.memory_gb} GB
                  </KeyValue>
                  <KeyValue label="Nodes / ranks">
                    {stage.resources.nodes} / {stage.resources.ranks}
                  </KeyValue>
                  <KeyValue label="Walltime">
                    {stage.resources.walltime}
                  </KeyValue>
                  <KeyValue label="Dependencies">
                    {stage.depends_on?.join(', ') || 'None'}
                  </KeyValue>
                  <KeyValue label="Output directory">
                    {stage.output_dir}
                  </KeyValue>
                </div>
                <JsonDetails
                  title="Effective stage resources"
                  value={stage.resources}
                />
              </Grid>
              <JsonDetails
                title="Generated execution wrapper"
                value={stage.script}
              />
              {stage.scheduler_script ? (
                <JsonDetails
                  title="Exact scheduler allocation script"
                  value={stage.scheduler_script}
                />
              ) : null}
              <JsonDetails title="Concrete arguments" value={stage.argv} />
              <JsonDetails
                title="Expected outputs and artifact schemas"
                value={stage.outputs}
              />
              <Button
                onClick={() => {
                  const source = new Blob([stage.script], {
                    type: 'text/x-shellscript',
                  });
                  const link = document.createElement('a');
                  link.href = URL.createObjectURL(source);
                  link.download = `${stage.id}.sh`;
                  link.click();
                  URL.revokeObjectURL(link.href);
                }}
              >
                Download wrapper
              </Button>
              <Field label="Custom project script path">
                <TextInput
                  aria-label={`Custom path ${stage.id}`}
                  value={
                    customPaths[stage.id] ?? `unityHPC/custom/${stage.id}.sh`
                  }
                  onChange={(e) =>
                    setCustomPaths({
                      ...customPaths,
                      [stage.id]: e.target.value,
                    })
                  }
                />
              </Field>
              <Button
                disabled={busy}
                onClick={() => {
                  setBusy(true);
                  setError('');
                  void workspaceRequest(
                    slug,
                    `plans/${plan.id}/custom-script`,
                    'POST',
                    {
                      stage_id: stage.id,
                      path:
                        customPaths[stage.id] ??
                        `unityHPC/custom/${stage.id}.sh`,
                    },
                  )
                    .then(async (result) => {
                      setCustomResult(result);
                      setApproved(false);
                      await refreshConnection();
                    })
                    .catch((e) => setError(errorText(e)))
                    .finally(() => setBusy(false));
                }}
              >
                Save as custom script
              </Button>
            </Card>
          ))}
          <Card>
            <CardHeader title="Measurements and collection versions" />
            <JsonDetails
              title="Selected metric definitions"
              value={plan.metrics}
            />
            <Hint>
              Approved stages continue on the controller. Failures pause
              affected work for review; retries need separate approval.
            </Hint>
          </Card>
        </>
      ) : (
        <p>Loading reviewed plan…</p>
      )}
    </WorkspacePage>
  );
};

const executionAttempts = (execution: Execution): Attempt[] =>
  execution.attempts ??
  (Array.isArray(execution.stages)
    ? execution.stages
    : Object.entries(execution.stages ?? {}).map(([id, value]) => ({
        ...value,
        stage_id: value.stage_id ?? id,
      })));
export const ProjectRuns = () => {
  const { slug } = useWorkspace();
  const [search, setSearch] = useSearchParams();
  const navigate = useNavigate();
  const { openJob } = usePanels();
  const [executions, setExecutions] = useState<Execution[]>([]);
  const [purpose, setPurpose] = useState('');
  const [selected, setSelected] = useState<Record<string, string[]>>({});
  const [mode, setMode] = useState('retry');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<{ purpose: string; value: unknown } | null>(
    null,
  );
  useEffect(() => {
    let active = true;
    const refresh = () =>
      workspaceApi
        .executions(slug)
        .then((r) => {
          if (active) setExecutions(r.executions);
        })
        .catch((e) => {
          if (active) setError(errorText(e));
        });
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [slug]);
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError('');
    try {
      await fn();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const rows = executions.filter(
    (e) => !search.get('execution') || e.id === search.get('execution'),
  );
  return (
    <WorkspacePage
      title="Runs"
      actions={
        search.get('execution') ? (
          <Button onClick={() => setSearch({})}>Show all executions</Button>
        ) : undefined
      }
    >
      <ErrorNotice error={error} />
      <Card>
        <CardHeader
          title={
            search.get('execution')
              ? `Execution ${search.get('execution')}`
              : 'Project executions'
          }
        />
        <Select
          aria-label="Purpose"
          value={purpose}
          options={[
            { value: '', label: 'All purposes' },
            { value: 'experiment', label: 'Experiments' },
            { value: 'smoke-test', label: 'Smoke tests' },
          ]}
          onChange={(e) => setPurpose(e.target.value)}
        />
        <Hint>
          Accepted jobs, work awaiting submission, rejected submissions, and
          uncertain outcomes remain separate. Uncertain outcomes require ledger
          reconciliation before recovery.
        </Hint>
      </Card>
      {!rows.length ? (
        <Card>No executions in this view.</Card>
      ) : (
        rows.map((execution) => (
          <Card key={execution.id}>
            <CardHeader
              title={execution.id}
              note={`State: ${execution.state ?? execution.status ?? 'unknown'}`}
            />
            <ButtonGroup>
              {execution.experiment_id ? (
                <Link
                  to={`../experiments/${execution.experiment_id}/revisions/${execution.revision}`}
                >
                  Experiment revision {execution.revision}
                </Link>
              ) : (
                <span>Analysis execution</span>
              )}
              <Link to={`../review/${execution.plan_id}`}>Approved plan</Link>
              <Link to={`../results?execution=${execution.id}`}>
                Artifacts and reports
              </Link>
            </ButtonGroup>
            <Hint>Observed: {execution.updated_at ?? 'Not recorded'}</Hint>
            <Hint>
              Last scheduler check:{' '}
              {execution.scheduler_observation?.checked_at
                ? `${execution.scheduler_observation.checked_at} (${ago(execution.scheduler_observation.checked_at)})`
                : 'Not recorded'}
            </Hint>
            {execution.scheduler_observation?.error ? (
              <p role="alert">
                Scheduler observation failed:{' '}
                {execution.scheduler_observation.error}. Scheduler states may be
                stale.
              </p>
            ) : null}
            {execution.integrity_error?.length ? (
              <Card role="alert">
                <CardHeader title="Execution paused: approved files changed" />
                <p>
                  Retrieval and recovery are unavailable while the approved
                  files fail integrity checks. Inspect the approved plan and
                  resolve these errors before continuing.
                </p>
                <ul>
                  {execution.integrity_error.map((issue, i) => (
                    <li key={i}>
                      {typeof issue === 'string'
                        ? issue
                        : `${issue.field ? `${issue.field}: ` : ''}${issue.message}`}
                    </li>
                  ))}
                </ul>
              </Card>
            ) : null}
            <TableScroller>
              <Table>
                <THead>
                  <tr>
                    <th>Recovery scope</th>
                    <th>Stage / attempt</th>
                    <th>Purpose</th>
                    <th>Stage state</th>
                    <th>Scheduler state</th>
                    <th>Jobs</th>
                    <th>Artifacts</th>
                    <th>Evidence</th>
                  </tr>
                </THead>
                <tbody>
                  {executionAttempts(execution)
                    .filter((a) => !purpose || a.purpose === purpose)
                    .map((a, i) => {
                      const id = a.id ?? a.stage_id ?? String(i);
                      const state =
                        a.state ?? a.status ?? 'awaiting submission';
                      return (
                        <tr key={a.id ?? `${id}-${i}`}>
                          <td>
                            <Checkbox
                              aria-label={`Recover ${id}`}
                              label=""
                              checked={
                                selected[execution.id]?.includes(id) ?? false
                              }
                              disabled={
                                Boolean(execution.integrity_error?.length) ||
                                Boolean(a.continued_by)
                              }
                              onChange={(event) =>
                                setSelected({
                                  ...selected,
                                  [execution.id]: event.target.checked
                                    ? [...(selected[execution.id] ?? []), id]
                                    : (selected[execution.id] ?? []).filter(
                                        (one) => one !== id,
                                      ),
                                })
                              }
                            />
                          </td>
                          <td>
                            {id}
                            {a.id ? <Hint>{a.id}</Hint> : null}
                            {a.continued_by ? (
                              <Link
                                to={`../runs?execution=${encodeURIComponent(a.continued_by)}`}
                              >
                                Continued in {a.continued_by}
                              </Link>
                            ) : null}
                            {a.resume_from ? (
                              <Hint>Resumed from: {a.resume_from}</Hint>
                            ) : null}
                          </td>
                          <td>{purposeLabel(a.purpose)}</td>
                          <td>
                            {state}
                            {a.error ? <Hint>{a.error}</Hint> : null}
                            {a.waiting_reason ? (
                              <Hint>{a.waiting_reason}</Hint>
                            ) : null}
                          </td>
                          <td>
                            {a.jobs?.length
                              ? a.jobs.map((job) => (
                                  <div key={job.job_id}>
                                    #{job.job_id}: {job.status || 'Unknown'}
                                  </div>
                                ))
                              : a.location === 'controller'
                                ? 'Controller host'
                                : 'Not observed'}
                          </td>
                          <td>
                            {(a.job_ids ?? (a.job_id ? [a.job_id] : [])).map(
                              (job) => (
                                <Button
                                  key={job}
                                  onClick={() => openJob(job, slug)}
                                >
                                  #{job}
                                </Button>
                              ),
                            )}
                            {!a.job_id && !a.job_ids?.length
                              ? 'No scheduler job'
                              : null}
                          </td>
                          <td>
                            {a.completeness ?? 'Unknown completeness'}
                            <Hint>
                              Fetch: {a.fetch_state ?? 'not requested'}
                            </Hint>
                            {a.fetch_state === 'failed' ||
                            (a.location === 'cluster' &&
                              ['failed', 'completed'].includes(state)) ? (
                              <Button
                                disabled={
                                  busy ||
                                  Boolean(execution.integrity_error?.length)
                                }
                                onClick={() =>
                                  void run(async () => {
                                    await workspaceRequest(
                                      slug,
                                      `executions/${execution.id}/fetch`,
                                      'POST',
                                      { stage_ids: [id] },
                                    );
                                    const refreshed =
                                      await workspaceApi.executions(slug);
                                    setExecutions(refreshed.executions);
                                  })
                                }
                              >
                                Retrieve stage artifacts
                              </Button>
                            ) : null}
                          </td>
                          <td>
                            <Button
                              disabled={busy}
                              onClick={() =>
                                void run(async () => {
                                  const value = await workspaceRequest(
                                    slug,
                                    `executions/${execution.id}/logs?stage_id=${encodeURIComponent(id)}`,
                                  );
                                  setLogs({
                                    purpose: purposeLabel(a.purpose),
                                    value,
                                  });
                                })
                              }
                            >
                              Logs and evidence
                            </Button>
                            <JsonDetails
                              title="Attempt history"
                              value={a.attempts ?? a}
                            />
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </Table>
            </TableScroller>
            <ButtonGroup>
              <Select
                aria-label={`Recovery mode ${execution.id}`}
                value={mode}
                disabled={Boolean(execution.integrity_error?.length)}
                options={[
                  { value: 'retry', label: 'Retry selected stages' },
                  { value: 'resume', label: 'Resume compatible saved work' },
                ]}
                onChange={(e) => setMode(e.target.value)}
              />
              <Button
                disabled={
                  busy ||
                  Boolean(execution.integrity_error?.length) ||
                  !selected[execution.id]?.length
                }
                onClick={() =>
                  void run(async () => {
                    const plan = await workspaceApi.recovery(
                      slug,
                      execution.id,
                      selected[execution.id],
                      mode,
                    );
                    navigate(`../review/${plan.id}`);
                  })
                }
              >
                Check and review recovery
              </Button>
              <Button
                disabled={busy || Boolean(execution.integrity_error?.length)}
                onClick={() =>
                  void run(async () => {
                    await workspaceRequest(
                      slug,
                      `executions/${execution.id}/reconcile`,
                      'POST',
                      {},
                    );
                    const r = await workspaceApi.executions(slug);
                    setExecutions(r.executions);
                  })
                }
              >
                Reconcile with ledger
              </Button>
            </ButtonGroup>
          </Card>
        ))
      )}
      {logs ? (
        <Card>
          <CardHeader
            title="Logs and evidence"
            note={`Purpose: ${logs.purpose}`}
          />
          <JsonDetails
            title="Attempt linkage and available output"
            value={logs.value}
          />
          <Button onClick={() => setLogs(null)}>Close evidence</Button>
        </Card>
      ) : null}
    </WorkspacePage>
  );
};

export const ProjectResults = () => {
  const { slug, connection } = useWorkspace();
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [operation, setOperation] = useState('');
  const [parameters, setParameters] = useState<Record<string, Value>>({});
  const [metrics, setMetrics] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    workspaceApi
      .artifacts(slug)
      .then((r) => setArtifacts(r.artifacts))
      .catch((e) => setError(errorText(e)));
  }, [slug]);
  const operations = Object.entries(connection?.manifest?.analyses ?? {});
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError('');
    try {
      await fn();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const rows = artifacts.filter(
    (a) =>
      !search.get('execution') || a.execution_id === search.get('execution'),
  );
  return (
    <WorkspacePage title="Results">
      <ErrorNotice error={error} />
      <Card>
        <CardHeader title="Artifacts and reports" />
        <Hint>
          Artifact completeness and availability are separate from scheduler
          success. Smoke-test evidence stays outside research aggregates.
        </Hint>
        {!rows.length ? (
          <p>No artifacts have been registered for this view.</p>
        ) : (
          rows.map((a) => (
            <Card key={a.id}>
              <Checkbox
                label={a.id}
                checked={selected.includes(a.id)}
                disabled={a.purpose === 'smoke-test' || !a.complete}
                onChange={(e) =>
                  setSelected(
                    e.target.checked
                      ? [...selected, a.id]
                      : selected.filter((id) => id !== a.id),
                  )
                }
              />
              <p>{a.path}</p>
              <p>
                Purpose: {purposeLabel(a.purpose)} · Complete:{' '}
                {a.complete ? 'Yes' : 'No'} · Available:{' '}
                {a.files?.length ? 'Yes' : 'No'}
              </p>
              <ButtonGroup>
                {a.reports?.map((path) => (
                  <a
                    key={path}
                    href={`/api/v1/projects/${encodeURIComponent(slug)}/workspace/artifacts/${a.id}/file?path=${encodeURIComponent(path)}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open {path.split('/').pop()}
                  </a>
                ))}
                {!a.complete && a.execution_id ? (
                  <Link to={`../runs?execution=${a.execution_id}`}>
                    Inspect retrieval and completeness
                  </Link>
                ) : null}
              </ButtonGroup>
              <JsonDetails title="Provenance and completeness" value={a} />
              <details>
                <summary>Indexed artifact files</summary>
                <ul>
                  {a.files?.map((file) => (
                    <li key={file.path}>
                      <a
                        href={`/api/v1/projects/${encodeURIComponent(slug)}/workspace/artifacts/${a.id}/file?path=${encodeURIComponent(file.path)}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {file.path}
                      </a>
                    </li>
                  ))}
                </ul>
              </details>
            </Card>
          ))
        )}
      </Card>
      <Card>
        <CardHeader title="Analyze saved artifacts" />
        <p>
          A new analysis revision preserves earlier reports. Missing inputs
          require an explicit collection plan.
        </p>
        <Field label="Declared analysis operation">
          <Select
            aria-label="Analysis operation"
            value={operation || operations[0]?.[0] || ''}
            options={
              operations.length
                ? operations.map(([id, definition]) => ({
                    value: id,
                    label: definition.title || id,
                  }))
                : [{ value: '', label: 'No analysis operation declared' }]
            }
            onChange={(e) => setOperation(e.target.value)}
          />
        </Field>
        {Object.entries(connection?.manifest?.parameters ?? {})
          .filter(([id]) =>
            connection?.manifest?.analyses?.[
              operation || operations[0]?.[0]
            ]?.parameters?.includes(id),
          )
          .map(([id, field]) => (
            <Field key={id} label={id}>
              <TypedInput
                label={`Analysis ${id}`}
                field={field}
                value={parameters[id] ?? field.default}
                onChange={(value) =>
                  setParameters({ ...parameters, [id]: value })
                }
              />
            </Field>
          ))}
        {Object.keys(connection?.manifest?.metrics ?? {}).map((id) => (
          <Checkbox
            key={id}
            label={id}
            checked={metrics.includes(id)}
            onChange={(e) =>
              setMetrics(
                e.target.checked
                  ? [...metrics, id]
                  : metrics.filter((v) => v !== id),
              )
            }
          />
        ))}
        <Button
          disabled={busy || !selected.length || !operations.length}
          onClick={() =>
            void run(async () => {
              const plan = await workspaceRequest<Plan>(
                slug,
                'analysis',
                'POST',
                {
                  artifact_ids: selected,
                  analysis: operation || operations[0][0],
                  operation: operations.find(
                    ([id]) => id === (operation || operations[0][0]),
                  )?.[1].operation,
                  parameters,
                  metrics,
                },
              );
              navigate(`../review/${plan.id}`);
            })
          }
        >
          Create analysis revision and review
        </Button>
      </Card>
    </WorkspacePage>
  );
};
