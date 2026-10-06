/**
 * Evaluation runs: dataset × model × scorers, each producing traces.
 *
 * The list reads runs the project has on disk plus the executions the
 * workspace worker is still running. `New evaluation` is the MLflow
 * `evaluate(data, predict_fn, scorers)` step: pick a workflow, a dataset and
 * parameters, then review the frozen plans before explicit approval.
 */

import styled from '@emotion/styled';
import { IconFlask, IconPlayerPlay, IconRefresh, IconTrash, IconX } from '@tabler/icons-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { errorText } from '../controller/api';
import { SchedulerStatus } from '../runner/SchedulerStatus';
import { ActionBar, ActionBarCount, ActionBarDivider } from '../../ui/components/ActionBar';
import { Button, IconButton } from '../../ui/components/Button';
import { Card, CardHeader, Grid, Hint, KeyValue } from '../../ui/components/Card';
import { EmptyState } from '../../ui/components/EmptyState';
import { Checkbox, Field, FieldRow, Select, SelectionCheckbox, TextInput } from '../../ui/components/Field';
import { Modal } from '../../ui/components/SidePanel';
import { StatCard } from '../../ui/components/StatCard';
import { MonoCell, SelectCell, SelectHead, Table, TableEmptyRow, TableScroller, THead, TRow } from '../../ui/components/Table';
import { Tag, TagRow } from '../../ui/components/Tag';
import { useToast } from '../../ui/components/Toast';
import {
  genaiApi,
  type Evaluation,
  type EvaluationDetail,
  type EvaluationsAnswer,
  type MatrixAnswer,
  type EvaluationSelection,
  type PreparedEvaluation,
  type LaunchOptions,
  type LaunchWorkflow,
  type DatasetViewer,
} from './api';
import {
  AssessmentSummaryBlock,
  BackLink,
  elapsedSeconds,
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

const datasetControl = (name: string) => ['dataset_subset', 'subset', 'config', 'dataset_split', 'split', 'dataset_revision', 'revision', 'n_items', 'limit', 'sample_limit', 'dataset_offset', 'dataset_sampling'].includes(name);

const selectionSplits = (viewer: DatasetViewer | undefined, subset: string) => {
  const rows = new Map<string, number>();
  for (const partition of viewer?.subsets ?? []) {
    if (subset && partition.name !== subset) continue;
    for (const split of partition.splits) rows.set(split.name, (rows.get(split.name) ?? 0) + split.rows);
  }
  return [...rows].map(([name, count]) => ({ name, rows: count }));
};

const defaultSplit = (splits: { name: string }[]) => splits.length === 1 ? splits[0].name : '';

export const NewEvaluationDialog = ({ onClose, onLaunched, initialDataset, initialSubset, initialSplit }: { onClose: () => void; onLaunched: (answer: MatrixAnswer) => void; initialDataset?: string; initialSubset?: string; initialSplit?: string }) => {
  const { slug } = useGenAI();
  const [options, setOptions] = useState<LaunchOptions | null>(null);
  const [workflowId, setWorkflowId] = useState('');
  const [models, setModels] = useState<string[]>([]);
  const [customModels, setCustomModels] = useState<string[]>([]);
  const [modelInput, setModelInput] = useState('');
  const [selections, setSelections] = useState<Record<string, EvaluationSelection>>({});
  const [name, setName] = useState('');
  const [values, setValues] = useState<Record<string, string | boolean>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [answer, setAnswer] = useState<MatrixAnswer | null>(null);
  const [prepared, setPrepared] = useState<PreparedEvaluation[] | null>(null);
  const workflow = options?.workflows.find((w) => w.id === workflowId);
  const eligible = useMemo(() => options?.workflows.filter((w) => w.purpose === workflow?.purpose) ?? [], [options, workflow]);
  const canonical = useCallback((model: string) => options?.model_aliases[model] || model, [options]);
  const modelChoices = useMemo(() => [...new Set([...customModels, ...eligible.flatMap((w) => {
    const parameter = w.parameters.find((p) => p.name === w.model_parameter);
    return (parameter?.choices ?? [parameter?.default]).filter(Boolean).map((x) => canonical(String(x)));
  })])], [eligible, canonical, customModels]);

  const acceptsModelInput = eligible.some((candidate) => {
    const parameter = candidate.parameters.find((p) => p.name === candidate.model_parameter);
    return parameter?.type === 'string' && !parameter.choices?.length;
  });
  const addModel = () => {
    const value = modelInput.trim();
    if (!value || modelChoices.includes(value)) return;
    setCustomModels((old) => [...old, value]);
    setModels((old) => [...old, value]);
    setModelInput('');
  };

  useEffect(() => {
    let live = true;
    genaiApi.launchOptions(slug).then((value) => {
      if (!live) return;
      setOptions(value);
      const first = value.workflows.find((w) => (!initialDataset || w.supported_datasets.includes(initialDataset)) && w.purpose === 'experiment') ?? value.workflows[0];
      if (first) setWorkflowId(first.id);
    }).catch((reason) => { if (live) setError(errorText(reason)); });
    return () => { live = false; };
  }, [slug, initialDataset]);

  const defaultSelection = useCallback((dataset: string, candidate: LaunchWorkflow): EvaluationSelection => {
    const viewer = options?.dataset_options[dataset];
    const parameters: Record<string, unknown> = {};
    for (const parameter of candidate.parameters.filter((p) => datasetControl(p.name))) {
      if (!['dataset_subset', 'subset', 'config', 'dataset_split', 'split'].includes(parameter.name)) parameters[parameter.name] = parameter.default;
    }
    const requestedSubset = dataset === initialDataset ? initialSubset : undefined;
    const requestedSplit = dataset === initialDataset ? initialSplit : undefined;
    const subset = requestedSubset ?? '';
    const splits = selectionSplits(viewer, subset);
    return { dataset, workflow: candidate.id, subset, split: requestedSplit ?? defaultSplit(splits), parameters };
  }, [options, initialDataset, initialSubset, initialSplit]);

  useEffect(() => {
    if (!workflow) return;
    const next: Record<string, string | boolean> = {};
    for (const parameter of workflow.parameters) next[parameter.name] = parameter.type === 'boolean' ? Boolean(parameter.default) : parameter.default == null ? '' : String(parameter.default);
    setValues(next);
    const model = workflow.parameters.find((p) => p.name === workflow.model_parameter);
    setModels(model?.default ? [canonical(String(model.default))] : []);
    setCustomModels([]); setModelInput('');
    const dataset = initialDataset && workflow.supported_datasets.includes(initialDataset) ? initialDataset : workflow.supported_datasets[0];
    setSelections(dataset ? { [dataset]: defaultSelection(dataset, workflow) } : {});
    setPrepared(null);
  }, [workflow, initialDataset, canonical, defaultSelection]);

  const setSelection = (dataset: string, patch: Partial<EvaluationSelection>) => {
    setSelections((old) => ({ ...old, [dataset]: { ...old[dataset], ...patch } }));
    setPrepared(null);
  };
  const updateParameter = (dataset: string, parameter: string, value: unknown) => setSelection(dataset, { parameters: { ...selections[dataset].parameters, [parameter]: value } });
  const compatibleModel = (model: string, candidate: LaunchWorkflow) => {
    const spec = candidate.parameters.find((p) => p.name === candidate.model_parameter);
    return !spec?.choices?.length || spec.choices.some((x) => canonical(String(x)) === model);
  };
  const incompatible = Object.values(selections).some((s) => models.some((m) => !compatibleModel(m, options!.workflows.find((w) => w.id === s.workflow)!)));

  const prepare = async () => {
    if (!workflow) return;
    setBusy(true); setError(''); setAnswer(null);
    try {
      const parameters: Record<string, unknown> = {};
      for (const parameter of workflow.parameters) {
        if (parameter.name === workflow.model_parameter || parameter.name === workflow.dataset_parameter || datasetControl(parameter.name)) continue;
        const raw = values[parameter.name];
        if (raw !== '' && raw !== undefined) parameters[parameter.name] = coerce(parameter.type, raw);
      }
      const result = await genaiApi.prepareMatrix(slug, { name: name.trim() || undefined, models, datasets: Object.values(selections), parameters });
      setAnswer(result);
      if (result.ok) setPrepared(result.prepared ?? []);
    } catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  };
  const launch = async () => {
    if (!prepared?.length) return;
    setBusy(true); setError('');
    try {
      const result = await genaiApi.launchMatrix(slug, prepared.map((p) => p.plan_id));
      setAnswer(result);
      if (result.ok) onLaunched(result);
    } catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  };

  return (
    <Modal open onClose={busy ? () => {} : onClose} title={prepared ? 'Review evaluation matrix' : 'New evaluation'} width={1040} footer={<Toolbar style={{ justifyContent: 'flex-end' }}>
          <Button size="small" disabled={busy} onClick={onClose}>Cancel</Button>
          {prepared ? <><Button size="small" disabled={busy || Boolean(answer?.launched?.length)} onClick={() => { setPrepared(null); setAnswer(null); }}>Edit setup</Button><Button size="small" variant="primary" Icon={IconPlayerPlay} disabled={busy} onClick={() => void launch()}>{busy ? 'Launching…' : prepared.some((p) => p.stages.some((s) => s.location === 'cluster')) ? 'Launch on Unity' : 'Launch evaluations'}</Button></> : <Button size="small" variant="primary" disabled={busy || !workflow || !options?.valid || !models.length || !Object.keys(selections).length || incompatible} onClick={() => void prepare()}>{busy ? 'Checking plans…' : 'Review evaluation matrix'}</Button>}
        </Toolbar>}>
      <Wide>
        {error ? <Card role="alert">{error}</Card> : null}
        {!options ? <Muted>Loading evaluation options…</Muted> : !options.valid ? <Card role="alert">The project connection is invalid. {JSON.stringify(options.errors).slice(0, 300)}</Card> : !workflow ? <Muted>No evaluation workflow is available.</Muted> : prepared ? (
          <>
            <Hint>{models.length} models × {prepared.length} datasets = {models.length * prepared.length} evaluations. Each dataset has one checked execution, with a separate variant for every model.</Hint>
            <TableScroller><Table><THead><tr><th>Dataset</th><th>Subset / split</th><th>Models</th><th>Items per model</th><th>Execution stages</th></tr></THead><tbody>
              {prepared.map((p) => <TRow key={p.plan_id}><td>{p.dataset}</td><td>{p.subset || 'All subsets'} / {p.split || 'All splits'}</td><td>{p.models.join(', ')}</td><td>{String(p.parameters?.n_items ?? p.parameters?.limit ?? p.rows ?? 'all')}</td><td>{p.stages.filter((s) => s.location === 'cluster').length} Unity · {p.stages.filter((s) => s.location === 'controller').length} controller</td></TRow>)}
            </tbody></Table></TableScroller>
            {prepared.map((p) => <details key={p.plan_id}><summary>{p.dataset} · resources and checked plan</summary><Mono>{p.plan_id}</Mono>{p.stages.map((s) => <div key={s.id}><Mono>{s.id}</Mono> · {s.purpose} · {s.location} · {JSON.stringify(s.resources)}</div>)}<details><summary>Exact frozen plan and checks</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontSize: 11 }}>{JSON.stringify({ plan: p.plan, checks: p.checks }, null, 2)}</pre></details></details>)}
          </>
        ) : (
          <>
            <FieldRow $columns={2}>
              <Field label="Evaluation workflow"><Select aria-label="Evaluation workflow" value={workflowId} options={options.workflows.map((w) => ({ value: w.id, label: `${w.title}${w.purpose === 'smoke-test' ? ' (smoke test)' : ''}` }))} onChange={(e) => setWorkflowId(e.target.value)} /></Field>
              <Field label="Comparison name"><TextInput value={name} placeholder="Model comparison" onChange={(e) => setName(e.target.value)} /></Field>
            </FieldRow>
            <Card><CardHeader title="Models" note="Select the same models for every dataset" /><Grid $min="250px" style={{ maxHeight: 220, overflow: 'auto' }}>
              {modelChoices.map((model) => <Checkbox key={model} label={model} checked={models.includes(model)} onChange={(e) => setModels((old) => e.target.checked ? [...old, model] : old.filter((m) => m !== model))} />)}
            </Grid>{acceptsModelInput ? <FieldRow $columns={2}><Field label="Model name"><TextInput value={modelInput} onChange={(e) => setModelInput(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addModel(); } }} /></Field><Button size="small" disabled={!modelInput.trim() || modelChoices.includes(modelInput.trim())} onClick={addModel}>Add model</Button></FieldRow> : null}</Card>
            <Card><CardHeader title="Datasets" note="Select one or more datasets, then choose their available subset and split" />
              {options.datasets.map((dataset) => {
                const candidates = eligible.filter((w) => w.supported_datasets.includes(dataset));
                const selection = selections[dataset];
                const candidate = candidates.find((w) => w.id === selection?.workflow) ?? candidates[0];
                const viewer = options.dataset_options[dataset];
                const splits = selectionSplits(viewer, selection?.subset ?? '');
                const selectedRows = splits.filter((s) => !selection?.split || s.name === selection.split).reduce((sum, s) => sum + s.rows, 0);
                const availableRows = Math.max(0, selectedRows - Number(selection?.parameters?.dataset_offset ?? 0));
                return <div key={dataset} style={{ marginBottom: 16 }}>
                  <Checkbox label={`${dataset}${candidates.length ? '' : ' (no evaluation workflow)'}`} checked={Boolean(selection)} disabled={!candidates.length} onChange={(e) => setSelections((old) => { if (e.target.checked) return { ...old, [dataset]: defaultSelection(dataset, candidate) }; const next = { ...old }; delete next[dataset]; return next; })} />
                  {selection ? <FieldRow $columns={3} style={{ marginTop: 8 }}>
                    <Field label={`${dataset} workflow`}><Select value={selection.workflow} options={candidates.map((w) => ({ value: w.id, label: w.title }))} onChange={(e) => setSelection(dataset, defaultSelection(dataset, candidates.find((w) => w.id === e.target.value)!))} /></Field>
                    <Field label={`${dataset} subset`}><Select value={selection.subset} options={[{ value: '', label: `All subsets · ${formatNumber(viewer?.total_rows ?? 0)} rows` }, ...(viewer?.subsets ?? []).map((s) => ({ value: s.name, label: `${s.name} · ${formatNumber(s.rows)} rows` }))]} onChange={(e) => setSelection(dataset, { subset: e.target.value, split: defaultSplit(selectionSplits(viewer, e.target.value)) })} /></Field>
                    <Field label={`${dataset} split`}><Select value={selection.split} options={[...(splits.length > 1 ? [{ value: '', label: `All splits · ${formatNumber(splits.reduce((sum, s) => sum + s.rows, 0))} rows` }] : []), ...splits.map((s) => ({ value: s.name, label: `${s.name} · ${formatNumber(s.rows)} rows` }))]} onChange={(e) => setSelection(dataset, { split: e.target.value })} /></Field>
                    {candidate?.parameters.filter((p) => datasetControl(p.name) && !['dataset_subset', 'subset', 'config', 'dataset_split', 'split'].includes(p.name)).map((p) => <Field key={p.name} label={`${dataset} ${p.label}`}>{p.choices?.length ? <Select value={String(selection.parameters?.[p.name] ?? '')} options={p.choices.map((v) => ({ value: String(v), label: String(v) }))} onChange={(e) => updateParameter(dataset, p.name, coerce(p.type, e.target.value))} /> : <TextInput type={p.type === 'string' ? 'text' : 'number'} min={p.min ?? undefined} max={p.name === 'n_items' ? Math.min(p.max ?? Infinity, availableRows) : p.max ?? undefined} value={String(selection.parameters?.[p.name] ?? '')} onChange={(e) => updateParameter(dataset, p.name, e.target.value === '' ? undefined : coerce(p.type, e.target.value))} />}</Field>)}
                  </FieldRow> : null}
                </div>;
              })}
            </Card>
            <FieldRow $columns={3}>{workflow.parameters.filter((p) => p.name !== workflow.model_parameter && p.name !== workflow.dataset_parameter && !datasetControl(p.name)).map((p) => <Field key={p.name} label={`${p.label}${p.unit ? ` (${p.unit})` : ''}`}>
              {p.type === 'boolean' ? <Checkbox label={p.name} checked={Boolean(values[p.name])} disabled={p.allowed_purposes?.length ? !p.allowed_purposes.includes(workflow.purpose) : false} onChange={(e) => setValues({ ...values, [p.name]: e.target.checked })} /> : p.choices?.length ? <Select value={String(values[p.name] ?? '')} options={p.choices.map((c) => ({ value: String(c), label: String(c) }))} onChange={(e) => setValues({ ...values, [p.name]: e.target.value })} /> : <TextInput type={p.type === 'string' ? 'text' : 'number'} min={p.min ?? undefined} max={p.max ?? undefined} value={String(values[p.name] ?? '')} onChange={(e) => setValues({ ...values, [p.name]: e.target.value })} />}
            </Field>)}</FieldRow>
            <Hint>{models.length} models × {Object.keys(selections).length} datasets = {models.length * Object.keys(selections).length} evaluations. Only real dataset partitions are available. Shared generation settings apply wherever declared by the dataset workflow.</Hint>
            {incompatible ? <Card role="alert">Some selected models are unavailable for a dataset workflow. Choose compatible models before reviewing.</Card> : null}
          </>
        )}
        {answer && !answer.ok ? <Card role="alert"><strong>{answer.error}{answer.dataset ? ` (${answer.dataset})` : ''}</strong>{answer.checks?.errors?.map((e) => <div key={e.field}><Mono>{e.field}</Mono> — {e.message}</div>)}{answer.checks?.checks?.filter((c) => !c.passed).map((c) => <details key={c.id}><summary>{c.id} output</summary><pre style={{ whiteSpace: 'pre-wrap', fontSize: 11 }}>{c.output}</pre></details>)}{answer.launched?.length ? <div>{answer.launched.length} dataset executions have already launched. Retry launches only the remaining plans.</div> : null}</Card> : null}

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
  const [selected, setSelected] = useState<string[]>([]);
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);

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
  const pending = useMemo(() => data?.executions ?? [], [data]);
  const complete = runs.filter((r) => r.state === 'complete').length;
  const keys = useMemo(() => [...runs.map((r) => `run:${r.id}`), ...pending.map((e) => `execution:${e.id}`)], [runs, pending]);
  const selectedKeys = selected.filter((key) => keys.includes(key));
  const allRunsSelected = runs.length > 0 && runs.every((r) => selectedKeys.includes(`run:${r.id}`));
  const allExecutionsSelected = pending.length > 0 && pending.every((e) => selectedKeys.includes(`execution:${e.id}`));
  const toggle = (key: string) => setSelected((old) => old.includes(key) ? old.filter((x) => x !== key) : [...old, key]);
  const toggleGroup = (group: string[]) => setSelected((old) => group.every((x) => old.includes(x)) ? old.filter((x) => !group.includes(x)) : [...new Set([...old, ...group])]);
  useEffect(() => { setSelected((old) => { const next = old.filter((key) => keys.includes(key)); return next.length === old.length ? old : next; }); }, [keys]);
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (confirming || deleting || !selectedKeys.length) return;
      const target = event.target;
      if (target instanceof HTMLElement && (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable)) return;
      if (event.key === 'Escape') setSelected([]);
      if (['Delete', 'Backspace'].includes(event.key)) { event.preventDefault(); setConfirming(true); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [confirming, deleting, selectedKeys.length]);
  const remove = async () => {
    setDeleting(true);
    try {
      const result = await genaiApi.deleteEvaluations(slug, selectedKeys.filter((x) => x.startsWith('run:')).map((x) => x.slice(4)), selectedKeys.filter((x) => x.startsWith('execution:')).map((x) => x.slice(10)));
      setSelected([]); setConfirming(false);
      toast(`Removed ${result.deleted} evaluations and ${result.deleted_executions} finished executions from this list.`, 'success');
      await load(); await refresh();
    } catch (reason) { toast(errorText(reason), 'error'); }
    finally { setDeleting(false); }
  };




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
          <CardHeader title="Dataset comparisons" note="One checked execution per dataset; open individual model results below" />
          <TableScroller>
            <Table>
              <THead><tr><SelectHead><SelectionCheckbox aria-label="Select all executions" checked={allExecutionsSelected} indeterminate={!allExecutionsSelected && pending.some((e) => selectedKeys.includes(`execution:${e.id}`))} onChange={() => toggleGroup(pending.map((e) => `execution:${e.id}`))} /></SelectHead><th>Comparison</th><th>State</th><th>Model results</th><th>Stages</th><th>Approved</th><th>Updated</th></tr></THead>
              <tbody>
                {pending.map((execution) => (
                  <TRow key={execution.id} $selected={selectedKeys.includes(`execution:${execution.id}`)}>
                    <SelectCell><SelectionCheckbox aria-label={`Select execution ${execution.id}`} checked={selectedKeys.includes(`execution:${execution.id}`)} onChange={() => toggle(`execution:${execution.id}`)} /></SelectCell>
                    <td><Link to={`../executions/${encodeURIComponent(execution.id)}`}>{execution.name || execution.id}</Link>{execution.kind !== 'experiment' ? <> <Tag color="gray" text={execution.kind} /></> : null}</td>
                    <td><StateTag state={execution.state} /></td>
                    <td><TagRow>{(execution.models ?? []).map((model) => {
                      const results = (data?.evaluations ?? []).filter((r) => r.execution_id === execution.id && r.model === model && r.purpose !== 'smoke-test');
                      const result = results.find((r) => r.state === 'complete') ?? results[0];
                      return result ? <Link key={model} to={encodeURIComponent(result.id)} title={`${model} · ${result.dataset} · ${result.traces ?? result.n_items ?? 0} traces`}><Tag color={result.state === 'complete' ? 'green' : result.state === 'failed' ? 'red' : 'yellow'} text={`${model.split('/').pop()} · ${result.metrics.accuracy !== undefined ? percent(result.metrics.accuracy) : result.state} · ${result.traces ?? '…'} traces`} /></Link> : <Tag key={model} color="gray" text={`${model.split('/').pop()} · pending`} />;
                    })}</TagRow></td>
                    <td>{execution.stages.map((s) => <div key={s.id}><Tag color={s.state === 'completed' ? 'green' : s.state === 'failed' ? 'red' : s.state === 'running' || s.state === 'submitted' ? 'yellow' : 'gray'} text={`${s.id.split('--').pop()} · ${s.state}`} /><SchedulerStatus jobIds={s.job_ids} jobs={s.jobs} observation={execution.scheduler_observation} /></div>)}</td>
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
                  <SelectHead><SelectionCheckbox aria-label="Select all evaluation runs" checked={allRunsSelected} indeterminate={!allRunsSelected && runs.some((r) => selectedKeys.includes(`run:${r.id}`))} onChange={() => toggleGroup(runs.map((r) => `run:${r.id}`))} /></SelectHead>
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
                {!data ? <TableEmptyRow colSpan={10}>Loading runs…</TableEmptyRow> : runs.map((run) => (
                  <TRow key={run.id} $selected={selectedKeys.includes(`run:${run.id}`)} $clickable onClick={() => navigate(encodeURIComponent(run.id))}>
                    <SelectCell onClick={(e) => e.stopPropagation()}><SelectionCheckbox aria-label={`Select evaluation ${run.name}`} checked={selectedKeys.includes(`run:${run.id}`)} onChange={() => toggle(`run:${run.id}`)} /></SelectCell>
                    <td>
                      <div style={{ fontWeight: 500, maxWidth: 360, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={run.name}><Link to={encodeURIComponent(run.id)} onClick={(event) => event.stopPropagation()}>{run.name}</Link></div>
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
      {selectedKeys.length ? <ActionBar label="Evaluation selection actions"><ActionBarCount>{selectedKeys.length} selected</ActionBarCount><ActionBarDivider /><Button size="small" Icon={IconTrash} onClick={() => setConfirming(true)}>Remove from list</Button><IconButton Icon={IconX} aria-label="Clear evaluation selection" onClick={() => setSelected([])} /></ActionBar> : null}
      {confirming ? <Modal open title="Remove selected evaluations?" width={600} onClose={deleting ? () => {} : () => setConfirming(false)}><Wide><p>Remove {selectedKeys.length} selected items from evaluation lists. Imported runs stay excluded if fetched again.</p><p>Active executions must be cancelled and stopped before removal. Source files, results, frozen plans, scheduler receipts and execution history remain available through Research tools.</p><Toolbar style={{ justifyContent: 'flex-end' }}><Button size="small" disabled={deleting} onClick={() => setConfirming(false)}>Cancel</Button><Button size="small" variant="primary" Icon={IconTrash} disabled={deleting} onClick={() => void remove()}>{deleting ? 'Removing…' : 'Remove from list'}</Button></Toolbar></Wide></Modal> : null}
      {creating ? (
        <NewEvaluationDialog
          initialDataset={params.get('dataset') || undefined}
          initialSubset={params.get('subset') ?? undefined}
          initialSplit={params.get('split') ?? undefined}
          onClose={() => { setCreating(false); const next = new URLSearchParams(params); next.delete('new'); next.delete('dataset'); next.delete('subset'); next.delete('split'); setParams(next, { replace: true }); }}
          onLaunched={(answer) => {
            setCreating(false);
            toast(`Launched ${answer.launched?.length ?? 1} dataset comparisons. Monitor their executions below.`, 'success');
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
  const elapsed = elapsedSeconds(data?.started, data?.finished);
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
            <StatCard label={elapsed === null ? 'Summed trace time' : 'Elapsed time'} value={formatDuration(elapsed ?? data.duration_total_s)} caption={elapsed === null ? 'Sum across traces; parallel durations overlap.' : `${formatTime(data.started)} → ${formatTime(data.finished)}`} />
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
