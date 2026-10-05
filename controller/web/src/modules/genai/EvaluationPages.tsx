/**
 * Evaluation runs: dataset × model × scorers, each producing traces.
 *
 * The list reads runs the project has on disk plus the executions the
 * workspace worker is still running. `New evaluation` is the MLflow
 * `evaluate(data, predict_fn, scorers)` step: pick a workflow, a dataset and
 * parameters, and the controller prepares a frozen plan for review and approval.
 */

import styled from '@emotion/styled';
import { IconFlask, IconPlayerPlay, IconRefresh } from '@tabler/icons-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { ApiError, errorText } from '../controller/api';
import { Button, IconButton } from '../../ui/components/Button';
import { Card, CardHeader, Grid, Hint, KeyValue } from '../../ui/components/Card';
import { EmptyState } from '../../ui/components/EmptyState';
import { Checkbox, Field, FieldRow, Select, TextInput } from '../../ui/components/Field';
import { Modal } from '../../ui/components/SidePanel';
import { StatCard } from '../../ui/components/StatCard';
import { MonoCell, Table, TableEmptyRow, TableScroller, THead, TRow } from '../../ui/components/Table';
import { Tag, TagRow } from '../../ui/components/Tag';
import { useToast } from '../../ui/components/Toast';
import {
  genaiApi,
  type Evaluation,
  type EvaluationDetail,
  type EvaluationsAnswer,
  type LaunchAnswer,
  type LaunchOptions,
  type LaunchWorkflow,
} from './api';
import {
  AssessmentSummaryBlock,
  BackLink,
  formatDuration,
  formatNumber,
  formatTime,
  GenAIPage,
  Mono,
  Muted,
  percent,
  SectionHead,
  SectionTitle,
  StateTag,
  Toolbar,
  useGenAI,
} from './GenAIWorkspace';
import { TracesTable } from './TracesTable';


const Wide = styled.div`
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.spacing(3)};
  width: 100%;
`;

const metricTag = (key: string, value: number) => {
  const ratio = key === 'accuracy' || key.endsWith('_rate');
  return <Tag key={key} color={ratio ? (value > 0 ? 'green' : 'red') : 'gray'} text={`${key} ${ratio ? percent(value) : value.toLocaleString()}`} mono />;
};

/* ------------------------------------------------------------------------ */
/* New evaluation                                                            */
/* ------------------------------------------------------------------------ */

const coerce = (type: string, raw: string | boolean): unknown => {
  if (type === 'boolean') return typeof raw === 'boolean' ? raw : raw === 'true';
  if (type === 'integer') return Number(raw);
  if (type === 'number') return Number(raw);
  return raw;
};

export const NewEvaluationDialog = ({ onClose, onPrepared, initialDataset }: { onClose: () => void; onPrepared: (answer: LaunchAnswer) => void; initialDataset?: string }) => {
  const { slug } = useGenAI();
  const navigate = useNavigate();
  const [options, setOptions] = useState<LaunchOptions | null>(null);
  const [workflowId, setWorkflowId] = useState('');
  const [dataset, setDataset] = useState(initialDataset || '');
  const [name, setName] = useState('');
  const [values, setValues] = useState<Record<string, string | boolean>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [answer, setAnswer] = useState<LaunchAnswer | null>(null);

  useEffect(() => {
    genaiApi.launchOptions(slug).then((value) => {
      setOptions(value);
      const first = value.workflows.find((w) => !initialDataset || w.dataset === initialDataset || w.dataset_parameter) ?? value.workflows[0];
      if (first) setWorkflowId(first.id);
    }).catch((reason) => setError(errorText(reason)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug]);

  const workflow: LaunchWorkflow | undefined = options?.workflows.find((w) => w.id === workflowId);
  useEffect(() => {
    if (!workflow) return;
    const next: Record<string, string | boolean> = {};
    for (const parameter of workflow.parameters) {
      next[parameter.name] = parameter.type === 'boolean' ? Boolean(parameter.default) : parameter.default === null || parameter.default === undefined ? '' : String(parameter.default);
    }
    setValues(next);
    // The dataset follows the workflow: bound by name, or chosen through its parameter.
    if (workflow.dataset) setDataset(workflow.dataset);
    else if (workflow.dataset_parameter) {
      const current = next[workflow.dataset_parameter];
      setDataset(initialDataset && options?.datasets.includes(initialDataset) ? initialDataset : typeof current === 'string' ? current : '');
    } else setDataset('');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflow]);

  const launch = async () => {
    if (!workflow) return;
    setBusy(true);
    setError('');
    try {
      const parameters: Record<string, unknown> = {};
      for (const parameter of workflow.parameters) {
        const raw = values[parameter.name];
        if (raw === '' || raw === undefined) continue;
        parameters[parameter.name] = coerce(parameter.type, raw);
      }
      const result = await genaiApi.launch(slug, {
        workflow: workflow.id,
        name: name.trim() || undefined,
        parameters,
        dataset: dataset || undefined,
        dataset_parameter: workflow.dataset_parameter ?? undefined,
      });
      setAnswer(result);
      if (result.ok && result.plan_id) {
        onPrepared(result);
        navigate(`/projects/${encodeURIComponent(slug)}/runner?plan=${encodeURIComponent(result.plan_id)}&workflow=${encodeURIComponent(workflow.id)}`);
      }
    } catch (reason) {
      setError(errorText(reason));
      if (reason instanceof ApiError) setAnswer(reason.payload as LaunchAnswer);
    } finally {
      setBusy(false);
    }
  };

  const cluster = workflow?.stages.some((s) => s.location === 'cluster');

  return (
    <Modal open onClose={onClose} title="New evaluation" width={760}>
      <Wide>
        {error ? <Card role="alert">{error}</Card> : null}
        {options && !options.valid ? (
          <Card role="alert">The project connection is invalid, so no evaluation can be planned. {JSON.stringify(options.errors).slice(0, 300)}</Card>
        ) : null}
        {!options ? <Muted>Loading workflows…</Muted> : !options.workflows.length ? (
          <Muted>This project declares no evaluation workflow. Add one to <Mono>unityHPC/project.json</Mono> and list it under <Mono>genai.launch.workflows</Mono>.</Muted>
        ) : (
          <>
            <FieldRow $columns={2}>
              <Field label="Workflow — the predict function and scorers">
                <Select aria-label="Evaluation workflow" value={workflowId} options={options.workflows.map((w) => ({ value: w.id, label: `${w.title}${w.purpose === 'smoke-test' ? ' (smoke test)' : ''}` }))} onChange={(e) => setWorkflowId(e.target.value)} />
              </Field>
              <Field label={workflow?.dataset ? 'Dataset — bound by the workflow' : workflow?.dataset_parameter ? `Dataset — sets ${workflow.dataset_parameter}` : 'Dataset'}>
                <Select
                  aria-label="Evaluation dataset"
                  value={dataset}
                  options={[{ value: '', label: workflow?.dataset_parameter ? 'Choose a dataset' : 'Declared by the workflow' }, ...options.datasets.map((d) => ({ value: d, label: d }))]}
                  onChange={(e) => { setDataset(e.target.value); if (workflow?.dataset_parameter) setValues({ ...values, [workflow.dataset_parameter]: e.target.value }); }}
                  disabled={!workflow?.dataset_parameter}
                />
              </Field>
            </FieldRow>
            <Field label="Run name">
              <TextInput value={name} placeholder={workflow ? `${workflow.title} · ${values.model ?? ''}` : 'optional'} onChange={(e) => setName(e.target.value)} />
            </Field>
            {workflow ? (
              <>
                <Hint style={{ marginTop: 6 }}>
                  Stages: {workflow.stages.map((s) => `${s.id} (${s.location}${s.purpose === 'smoke-test' ? ', smoke' : ''})`).join(' → ')}.
                  {cluster ? ' Cluster stages use the frozen source bundle on Unity through run.sh.' : ' Every stage runs on the controller.'}
                  {workflow.metrics.length ? ` Scorers: ${workflow.metrics.join(', ')}.` : ''}
                </Hint>
                <FieldRow $columns={3} style={{ marginTop: 8 }}>
                  {workflow.parameters.filter((parameter) => parameter.name !== workflow.dataset_parameter).map((parameter) => (
                    <Field key={parameter.name} label={`${parameter.label}${parameter.unit ? ` (${parameter.unit})` : ''}`}>
                      {parameter.type === 'boolean' ? (
                        <Checkbox label={parameter.name} checked={Boolean(values[parameter.name])} onChange={(e) => setValues({ ...values, [parameter.name]: e.target.checked })} />
                      ) : parameter.choices?.length ? (
                        <Select value={String(values[parameter.name] ?? '')} options={parameter.choices.map((c) => ({ value: String(c), label: String(c) }))} onChange={(e) => setValues({ ...values, [parameter.name]: e.target.value })} />
                      ) : (
                        <TextInput type={parameter.type === 'string' ? 'text' : 'number'} min={parameter.min ?? undefined} max={parameter.max ?? undefined} value={String(values[parameter.name] ?? '')} onChange={(e) => setValues({ ...values, [parameter.name]: e.target.value })} />
                      )}
                    </Field>
                  ))}
                </FieldRow>
              </>
            ) : null}
          </>
        )}
        {answer && !answer.ok ? (
          <Card role="alert" style={{ marginTop: 12 }}>
            <strong>{answer.error}</strong>
            {answer.checks?.errors?.map((e) => <div key={e.field}><Mono>{e.field}</Mono> — {e.message}</div>)}
            {answer.checks?.checks?.filter((c) => !c.passed).map((c) => <details key={c.id}><summary>{c.id} output</summary><pre style={{ whiteSpace: 'pre-wrap', fontSize: 11 }}>{c.output}</pre></details>)}
          </Card>
        ) : null}
        <Toolbar style={{ justifyContent: 'flex-end', marginTop: 12 }}>
          <Button size="small" onClick={onClose}>Cancel</Button>
          <Button size="small" variant="primary" Icon={IconPlayerPlay} disabled={busy || !workflow || !options?.valid} onClick={() => void launch()}>{busy ? 'Checking setup…' : 'Check setup and review'}</Button>
        </Toolbar>
      </Wide>
    </Modal>
  );
};

/* ------------------------------------------------------------------------ */
/* List                                                                      */
/* ------------------------------------------------------------------------ */

export const EvaluationsPage = () => {
  const { slug, refresh } = useGenAI();
  const navigate = useNavigate();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const collection = params.get('collection') || 'all';
  const [data, setData] = useState<EvaluationsAnswer | null>(null);
  const [error, setError] = useState('');
  const [hideSuperseded, setHideSuperseded] = useState(true);
  const [purpose, setPurpose] = useState('');
  const [creating, setCreating] = useState(params.get('new') === '1');

  const load = useCallback(async () => {
    try {
      setData(await genaiApi.evaluations(slug, collection));
      setError('');
    } catch (reason) {
      setError(errorText(reason));
    }
  }, [slug, collection]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const live = data?.executions.some((e) => !['completed', 'failed', 'cancelled', 'canceled', 'rejected'].includes(e.state));
    if (!live) return undefined;
    const timer = window.setInterval(() => { void load(); void refresh(); }, 5000);
    return () => window.clearInterval(timer);
  }, [data, load, refresh]);

  const runs = useMemo(() => (data?.evaluations ?? []).filter((e) => (!hideSuperseded || e.state !== 'superseded') && (!purpose || e.purpose === purpose)), [data, hideSuperseded, purpose]);
  const pending = (data?.executions ?? []).filter((e) => !['completed'].includes(e.state) || !(data?.evaluations ?? []).some((run) => run.execution_id === e.id));
  const complete = runs.filter((r) => r.state === 'complete').length;



  return (
    <GenAIPage
      title="Evaluation runs"
      subtitle="dataset × model × scorers — each run produces the traces on the Traces page"
      actions={<Button size="small" variant="primary" Icon={IconPlayerPlay} onClick={() => setCreating(true)}>New evaluation</Button>}
    >
      <Grid $min="150px">
        <StatCard label="Runs" value={formatNumber(runs.length)} Icon={IconFlask} caption={collection === 'all' ? 'all collections' : `collection ${collection}`} />
        <StatCard label="Complete" value={formatNumber(complete)} accent="green" />
        <StatCard label="In progress" value={formatNumber(pending.filter((e) => e.state !== 'completed').length)} accent={pending.some((e) => e.state !== 'completed') ? 'yellow' : undefined} caption="workspace executions" />
        <StatCard label="Models" value={formatNumber(new Set(runs.map((r) => r.model).filter(Boolean)).size)} />
      </Grid>
      <Toolbar>
        {(data?.collections.length ?? 0) > 1 ? (
          <Select aria-label="Collection" value={collection} style={{ width: 'auto' }}
            options={[{ value: 'all', label: 'Collections: all' }, ...(data?.collections ?? []).map((c) => ({ value: c.id, label: `Collection: ${c.label}` }))]}
            onChange={(e) => { const next = new URLSearchParams(params); next.set('collection', e.target.value); setParams(next); }} />
        ) : null}
        <Select aria-label="Purpose" value={purpose} style={{ width: 'auto' }} options={[{ value: '', label: 'Purpose: any' }, { value: 'experiment', label: 'Purpose: experiment' }, { value: 'smoke-test', label: 'Purpose: smoke test' }, { value: 'unclassified', label: 'Purpose: unclassified' }]} onChange={(e) => setPurpose(e.target.value)} />
        <Checkbox label="Hide superseded" checked={hideSuperseded} onChange={(e) => setHideSuperseded(e.target.checked)} />
        <IconButton Icon={IconRefresh} aria-label="Refresh evaluation runs" onClick={() => void load()} />
        <Muted>{runs.length} runs</Muted>
      </Toolbar>
      {error ? <Card role="alert">{error}</Card> : null}
      {pending.length ? (
        <Card>
          <CardHeader title="Workspace executions" note="approved plans the controller worker is running or has finished" />
          <TableScroller>
            <Table>
              <THead><tr><th>Execution</th><th>State</th><th>Stages</th><th>Approved</th><th>Updated</th></tr></THead>
              <tbody>
                {pending.map((execution) => (
                  <TRow key={execution.id}>
                    <td><Link to={`../executions/${encodeURIComponent(execution.id)}`}><Mono>{execution.id}</Mono></Link>{execution.kind !== 'experiment' ? <> <Tag color="gray" text={execution.kind} /></> : null}</td>
                    <td><StateTag state={execution.state} /></td>
                    <td><TagRow>{execution.stages.map((s) => <Tag key={s.id} color={s.state === 'completed' ? 'green' : s.state === 'failed' ? 'red' : s.state === 'running' || s.state === 'submitted' ? 'yellow' : 'gray'} text={`${s.id.split('--').pop()} · ${s.state}${s.job_ids.length ? ` · ${s.job_ids.join(',')}` : ''}`} dot={s.state === 'running' ? 'pulsing' : false} />)}</TagRow></td>
                    <MonoCell>{formatTime(execution.approved_at)}</MonoCell>
                    <MonoCell>{formatTime(execution.updated_at)}</MonoCell>
                  </TRow>
                ))}
              </tbody>
            </Table>
          </TableScroller>
        </Card>
      ) : null}
      {data && !runs.length && !pending.length ? (
        <Card>
          <EmptyState title="No evaluation runs" Icon={IconFlask} action={<Button size="small" variant="primary" Icon={IconPlayerPlay} onClick={() => setCreating(true)}>New evaluation</Button>}>
            An evaluation run is a dataset, a model (the predict function) and the project's scorers. Launch one, or widen the collection filter.
          </EmptyState>
        </Card>
      ) : (
        <Card $padded={false}>
          <TableScroller>
            <Table>
              <THead>
                <tr>
                  <th>Run</th>
                  <th>Dataset</th>
                  <th>Model</th>
                  <th>State</th>
                  <th>Traces</th>
                  <th>Metrics</th>
                  <th>Assessments</th>
                  <th>Collection</th>
                  <th>Started</th>
                </tr>
              </THead>
              <tbody>
                {!data ? <TableEmptyRow colSpan={9}>Loading runs…</TableEmptyRow> : runs.map((run) => (
                  <TRow key={run.id} $clickable onClick={() => navigate(encodeURIComponent(run.id))}>
                    <td>
                      <div style={{ fontWeight: 500, maxWidth: 360, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={run.name}>{run.name}</div>
                      <TagRow>{run.purpose === 'smoke-test' ? <Tag color="yellow" text="smoke test" /> : null}{run.source === 'workspace' ? <Tag color="gray" text="workspace" /> : null}<Muted>{run.path}</Muted></TagRow>
                    </td>
                    <td>{run.dataset ? <Link to={`../datasets/${encodeURIComponent(run.dataset)}`} onClick={(e) => e.stopPropagation()}>{run.dataset}</Link> : <Muted>—</Muted>}</td>
                    <td title={run.model}>{run.model.split('/').pop() || '—'}</td>
                    <td><StateTag state={run.state} /></td>
                    <MonoCell>{run.traces === null ? <Muted title="indexed on open">{run.n_items ? `≤${run.n_items}` : '…'}</Muted> : formatNumber(run.traces)}</MonoCell>
                    <td><TagRow>{Object.entries(run.metrics).slice(0, 3).map(([k, v]) => metricTag(k, v))}</TagRow></td>
                    <td>
                      <TagRow>
                        {Object.entries(run.assessments).filter(([, s]) => s.kind === 'pass_fail').map(([k, s]) => <Tag key={k} color={(s.pass_rate ?? 0) > 0 ? 'green' : 'red'} text={`${k} ${percent(s.pass_rate)}`} />)}
                        {!run.indexed ? <Muted>open to index</Muted> : null}
                      </TagRow>
                    </td>
                    <td><Tag color="gray" text={run.collection} /></td>
                    <MonoCell>{formatTime(run.started)}</MonoCell>
                  </TRow>
                ))}
              </tbody>
            </Table>
          </TableScroller>
        </Card>
      )}
      {creating ? (
        <NewEvaluationDialog
          initialDataset={params.get('dataset') || undefined}
          onClose={() => { setCreating(false); const next = new URLSearchParams(params); next.delete('new'); next.delete('dataset'); setParams(next, { replace: true }); }}
          onPrepared={(answer) => {
            setCreating(false);
            toast(`Setup checked for ${answer.plan_id}. Review the plan before approval.`, 'success');
            void load();
            void refresh();
          }}
        />
      ) : null}
    </GenAIPage>
  );
};

/* ------------------------------------------------------------------------ */
/* Detail                                                                    */
/* ------------------------------------------------------------------------ */

const flat = (value: Record<string, unknown>, prefix = ''): [string, string][] => {
  const out: [string, string][] = [];
  for (const [k, v] of Object.entries(value)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === 'object' && !Array.isArray(v)) out.push(...flat(v as Record<string, unknown>, key));
    else out.push([key, Array.isArray(v) ? JSON.stringify(v) : String(v)]);
  }
  return out;
};

export const EvaluationDetailPage = () => {
  const { slug } = useGenAI();
  const { evaluationId = '' } = useParams();
  const [data, setData] = useState<EvaluationDetail | null>(null);
  const [error, setError] = useState('');
  const [showManifest, setShowManifest] = useState(false);

  useEffect(() => {
    let live = true;
    setData(null);
    genaiApi.evaluation(slug, evaluationId)
      .then((value) => { if (live) { setData(value); setError(''); } })
      .catch((reason) => { if (live) setError(errorText(reason)); });
    return () => { live = false; };
  }, [slug, evaluationId]);

  const run: Evaluation | null = data;
  const assessments = Object.entries(data?.assessments ?? {});

  return (
    <GenAIPage title={`Evaluation run · ${run?.name ?? evaluationId}`} subtitle={run ? `${run.collection} · ${run.path}` : undefined}>
      <BackLink to="../evaluations">All evaluation runs</BackLink>
      {error ? <Card role="alert">{error}</Card> : null}
      {data ? (
        <>
          <TagRow>
            <StateTag state={data.state} />
            {data.purpose === 'smoke-test' ? <Tag color="yellow" text="smoke test" /> : <Tag color="green" text="experiment" />}
            {data.dataset ? <Link to={`../datasets/${encodeURIComponent(data.dataset)}`}><Tag color="blue" text={`dataset ${data.dataset}`} /></Link> : null}
            {data.model ? <Tag color="purple" text={data.model} /> : null}
            {data.execution_id ? <Link to={`../executions/${encodeURIComponent(data.execution_id)}`}><Tag color="gray" text={`execution ${data.execution_id}`} mono /></Link> : null}
          </TagRow>
          <Grid $min="150px">
            <StatCard label="Traces" value={formatNumber(data.traces)} caption={data.n_items ? `${data.n_items} requested` : undefined} />
            {Object.entries(data.metrics).slice(0, 2).map(([k, v]) => <StatCard key={k} label={k} value={k === 'accuracy' || k.endsWith('_rate') ? percent(v) : v.toLocaleString()} accent={k === 'accuracy' ? (v > 0 ? 'green' : 'red') : undefined} />)}
            <StatCard label="Tokens" value={formatNumber(data.token_total)} caption="completion tokens, all traces" />
            <StatCard label="Compute time" value={formatDuration(data.duration_total_s)} caption={data.started && data.finished ? `${formatTime(data.started)} → ${formatTime(data.finished)}` : formatTime(data.started)} />
            <StatCard label="Sessions" value={formatNumber(data.sessions.length)} caption={Object.entries(data.states).map(([s, n]) => `${n} ${s.toLowerCase()}`).join(' · ')} />
          </Grid>
          {assessments.length ? (
            <Card>
              <CardHeader title="Assessments" note="over every trace of this run" />
              <Grid $min="180px">
                {assessments.map(([name, summary]) => (
                  <div key={name}>
                    <Muted>{name}</Muted>
                    <AssessmentSummaryBlock name={name} summary={summary} />
                  </div>
                ))}
              </Grid>
            </Card>
          ) : null}
          <Grid $min="320px">
            <Card>
              <CardHeader title="Agent & prompt" />
              {Object.entries(data.agent).map(([k, v]) => <KeyValue key={k} label={k}>{String(v)}</KeyValue>)}
              {Object.entries(data.prompt).filter(([, v]) => typeof v !== 'object').map(([k, v]) => <KeyValue key={`p-${k}`} label={`prompt ${k}`}>{String(v)}</KeyValue>)}
              {!Object.keys(data.agent).length && !Object.keys(data.prompt).length ? <Muted>The run manifest names no agent or prompt fields.</Muted> : null}
            </Card>
            <Card>
              <CardHeader title="Run" action={<Button size="small" variant="tertiary" onClick={() => setShowManifest((v) => !v)}>{showManifest ? 'Hide manifest' : 'Show manifest'}</Button>} />
              <KeyValue label="Started">{formatTime(data.started)}</KeyValue>
              <KeyValue label="Finished">{formatTime(data.finished)}</KeyValue>
              <KeyValue label="Trace files">{data.trace_files.join(', ') || '—'}</KeyValue>
              {data.variant_id ? <KeyValue label="Variant">{data.variant_id}</KeyValue> : null}
              {data.stage_id ? <KeyValue label="Stage">{data.stage_id}</KeyValue> : null}
              {showManifest ? (
                <div style={{ marginTop: 8, maxHeight: 360, overflow: 'auto' }}>
                  {flat(data.manifest).map(([k, v]) => <KeyValue key={k} label={k} title={v}>{v.length > 120 ? `${v.slice(0, 119)}…` : v}</KeyValue>)}
                  {Object.keys(data.provenance).length ? flat(data.provenance).map(([k, v]) => <KeyValue key={`prov-${k}`} label={`provenance ${k}`} title={v}>{v.length > 120 ? `${v.slice(0, 119)}…` : v}</KeyValue>) : null}
                </div>
              ) : null}
            </Card>
          </Grid>
          <SectionHead><SectionTitle>Traces of this run</SectionTitle></SectionHead>
          <TracesTable fixed={{ evaluation: data.id }} collections={false} />
        </>
      ) : !error ? <Muted>Indexing run…</Muted> : null}
    </GenAIPage>
  );
};
