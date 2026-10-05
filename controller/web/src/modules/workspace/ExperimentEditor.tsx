import { useEffect, useRef, useState } from 'react';
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router-dom';
import { errorText } from '../controller/api';
import { Button, ButtonGroup } from '../../ui/components/Button';
import { Card, CardHeader, Grid, Hint, KeyValue, Stack } from '../../ui/components/Card';
import {
  Checkbox,
  Field,
  Select,
  TextArea,
  TextInput,
} from '../../ui/components/Field';
import {
  workspaceApi,
  workspaceRequest,
  type Artifact,
  type Check,
  type Draft,
  type Experiment,
  type Parameter,
  type Plan,
  type Resource,
  type Value,
  type Variant,
  type Workflow,
} from './api';
import { CompositionEditor } from './CompositionEditor';
import {
  ErrorNotice,
  JsonDetails,
  useWorkspace,
  WorkspacePage,
} from './Workspace';

const cast = (raw: string, field: Parameter): Value =>
  field.type === 'integer' || field.type === 'number'
    ? Number(raw)
    : field.type === 'boolean'
      ? raw === 'true'
      : raw;
export const TypedInput = ({
  label,
  field,
  value,
  onChange,
}: {
  label: string;
  field: Parameter;
  value: Value | undefined;
  onChange: (value: Value) => void;
}) => {
  if (field.type === 'boolean')
    return (
      <Checkbox
        label={label}
        checked={Boolean(value)}
        onChange={(e) => onChange(e.target.checked)}
      />
    );
  if (field.choices?.length)
    return (
      <Select
        aria-label={label}
        value={String(value ?? '')}
        options={[
          { value: '', label: 'Select…' },
          ...field.choices.map((v) => ({ value: String(v), label: String(v) })),
        ]}
        onChange={(e) => onChange(cast(e.target.value, field))}
      />
    );
  return (
    <TextInput
      aria-label={label}
      value={String(value ?? '')}
      type={field.type === 'string' ? 'text' : 'number'}
      min={field.min}
      max={field.max}
      step={field.type === 'integer' ? 1 : 'any'}
      required={field.required}
      onChange={(e) =>
        onChange(
          e.target.value === '' && field.type !== 'string'
            ? ''
            : cast(e.target.value, field),
        )
      }
    />
  );
};

export const ExperimentEditor = () => {
  const { slug, connection } = useWorkspace();
  const { experimentId = '' } = useParams();
  const navigate = useNavigate();
  const [search] = useSearchParams();
  const [experiment, setExperiment] = useState<Experiment | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saveState, setSaveState] = useState('Saved');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [savedDraft, setSavedDraft] = useState<Draft | null>(null);
  const [revisions, setRevisions] = useState<unknown[] | null>(null);
  const [check, setCheck] = useState<Check | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [approved, setApproved] = useState(false);
  const [phase, setPhase] = useState<'idle' | 'checking' | 'dispatching'>('idle');
  const [expandedVariants, setExpandedVariants] = useState<Variant[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [defaultsPreview, setDefaultsPreview] = useState<{expected_version:number;declaration_digest:string;differences:unknown;draft:Draft}|null>(null);
  const editCounter = useRef(0);
  const savedCounter = useRef(0);
  const saving = useRef(false);
  const key = `unity-hpc.draft.${slug}.${experimentId}`;
  useEffect(() => {
    let active = true;
    setDraft(null);
    setExperiment(null);
    setError('');
    workspaceApi
      .experiment(slug, experimentId)
      .then((e) => {
        if (!active) return;
        let recovered: { draft: Draft; version: number } | null = null;
        try {
          recovered = JSON.parse(sessionStorage.getItem(key) || 'null');
        } catch {
          /* Storage can be unavailable. */
        }
        setExperiment(recovered ? { ...e, version: recovered.version } : e);
        setDraft(recovered?.draft ?? e.draft);
        editCounter.current = recovered ? 1 : 0;
        savedCounter.current = 0;
        setSaveState(recovered ? 'Unsaved' : 'Saved');
        if (recovered)
          setError(
            'Recovered unsaved edits from this browser. Retry save to check for conflicts.',
          );
      })
      .catch((e) => {
        if (active) setError(errorText(e));
      });
    workspaceApi
      .artifacts(slug)
      .then((r) => {
        if (active) setArtifacts(r.artifacts);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [slug, experimentId, key]);
  useEffect(() => {
    if (
      !draft ||
      !experiment ||
      saveState !== 'Unsaved' ||
      error ||
      saving.current ||
      editCounter.current === savedCounter.current
    )
      return;
    const timer = window.setTimeout(async () => {
      const count = editCounter.current;
      saving.current = true;
      setSaveState('Saving');
      try {
        const saved = await workspaceApi.save(
          slug,
          experimentId,
          experiment.version,
          draft,
        );
        setExperiment(saved);
        savedCounter.current = count;
        if (count === editCounter.current) {
          setSaveState('Saved');
          try {
            sessionStorage.removeItem(key);
          } catch {
            /* optional recovery */
          }
        } else setSaveState('Unsaved');
      } catch (e) {
        setError(`Your visible edits are not saved. ${errorText(e)}`);
        setSaveState('Unsaved');
      } finally {
        saving.current = false;
      }
    }, 600);
    return () => window.clearTimeout(timer);
  }, [draft, experiment, saveState, error, slug, experimentId, key]);
  useEffect(() => {
    if (saveState === 'Saved') return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [saveState]);
  const change = (patch: Partial<Draft>) => {
    if (!draft || !experiment) return;
    const next = { ...draft, ...patch };
    setDraft(next);
    editCounter.current += 1;
    setSaveState(saving.current ? 'Saving' : 'Unsaved');
    setCheck(null);
    setPlan(null);
    setApproved(false);
    if (
      'parameters' in patch ||
      'variant_parameters' in patch ||
      'combinations' in patch
    )
      setExpandedVariants([]);
    try {
      sessionStorage.setItem(
        key,
        JSON.stringify({ version: experiment.version, draft: next }),
      );
    } catch {
      /* Visible edits are retained in memory. */
    }
  };
  const action = async (fn: () => Promise<void>) => {
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
  if (!draft || !experiment)
    return (
      <WorkspacePage title="Experiments">
        <ErrorNotice error={error} />
        <p>Loading experiment…</p>
      </WorkspacePage>
    );
  const manifest = connection?.manifest;
  const composed = draft.workflow === '__composition__';
  const workflow: Workflow | undefined = composed ? {
    title: 'Composed operations', parameters: Object.keys(manifest?.parameters ?? {}),
    stages: [], metrics: [],
  } : manifest?.workflows[draft.workflow];
  if (!workflow)
    return (
      <WorkspacePage title="Experiment">
        <ErrorNotice error="The saved workflow is unavailable in this connection. Its draft and history are preserved." />
        <JsonDetails title="Saved draft" value={draft} />
        <Link to={`/projects/${encodeURIComponent(slug)}/settings`}>
          Connection details
        </Link>
      </WorkspacePage>
    );
  const fields = (
    workflow.parameters ?? Object.keys(manifest?.parameters ?? {})
  )
    .map((id) => [id, manifest!.parameters[id]] as const)
    .filter(([, f]) => f);
  const valueFor = (id: string, f: Parameter) =>
    draft.parameters?.[id] ?? workflow.defaults?.[id] ?? f.default;
  const metrics = manifest?.metrics ?? {};
  const selectedMetrics =
    draft.metrics ??
    (workflow.metrics ?? []).filter((id) => !metrics[id]?.optional);
  const includedStages =
    draft.stages ?? workflow.stages.filter((s) => !s.optional).map((s) => s.id);
  const safe = saveState === 'Saved' && !busy && !experiment.archived;
  const toggle = <T,>(items: T[], item: T, enabled: boolean): T[] =>
    enabled ? [...new Set([...items, item])] : items.filter((v) => v !== item);
  const openFields = fields.filter(
    ([id, field]) =>
      field.default === undefined && workflow.defaults?.[id] === undefined,
  );
  const lead = workflow.stages.find((stage) => {
    const location =
      stage.location ?? manifest?.operations?.[stage.operation]?.location;
    return location !== 'controller' && includedStages.includes(stage.id);
  });
  const leadResource: Resource | null = lead
    ? {
        primitive: manifest?.default_primitive,
        mode: manifest?.default_mode,
        cpus: 1,
        gpus: 1,
        nodes: 1,
        ranks: 1,
        memory_gb: 4,
        walltime: '00:30:00',
        ...lead.resources,
        ...draft.resources?.[lead.id],
      }
    : null;
  const updateLead = (key: string, value: string | number) => {
    if (!lead) return;
    change({
      resources: {
        ...draft.resources,
        [lead.id]: { ...draft.resources?.[lead.id], [key]: value },
      },
    });
  };
  const dispatch = () =>
    void action(async () => {
      if (!plan || !check?.valid) {
        setPhase('checking');
        try {
          const result = await workspaceApi.check(slug, experimentId);
          setCheck(result);
          setExpandedVariants(result.variants ?? []);
          if (!result.valid) return;
          const created = await workspaceApi.plan(slug, experimentId);
          setPlan(created);
          setApproved(false);
        } finally {
          setPhase('idle');
        }
        return;
      }
      if (!approved) return;
      setPhase('dispatching');
      try {
        const execution = await workspaceApi.dispatch(
          slug,
          plan.id,
          `review:${plan.id}`,
        );
        navigate(
          `/projects/${encodeURIComponent(slug)}/runs?execution=${encodeURIComponent(execution.id)}`,
        );
      } finally {
        setPhase('idle');
      }
    });
  return (
    <WorkspacePage
      title="Start experiment"
      actions={
        <ButtonGroup>
          <span aria-live="polite" data-testid="autosave-status">
            {saveState}
          </span>
          <Button
            variant="primary"
            disabled={
              !safe ||
              !connection?.valid ||
              phase !== 'idle' ||
              Boolean(plan && check?.valid && !approved)
            }
            onClick={dispatch}
          >
            {phase === 'dispatching' ? 'Dispatching…' : 'Dispatch'}
          </Button>
        </ButtonGroup>
      }
    >
      <Link to={`/projects/${encodeURIComponent(slug)}/experiments`}>
        Back to library
      </Link>
      <ErrorNotice error={error} />
      {error && saveState === 'Unsaved' ? (
        <Card>
          <p>
            Your edits remain visible. A version conflict requires comparing the
            saved draft before choosing a new revision.
          </p>
          <ButtonGroup>
            <Button onClick={() => setError('')}>Retry save</Button>
            <Button
              onClick={() =>
                void action(async () => {
                  const current = await workspaceApi.experiment(
                    slug,
                    experimentId,
                  );
                  setCheck(null);
                  setSavedDraft(current.draft);
                  setError(
                    `Saved version ${current.version}; your editing version ${experiment.version}. Your edits are still here.`,
                  );
                })
              }
            >
              Inspect saved version
            </Button>
            <Button
              onClick={() =>
                void action(async () => {
                  const copy = await workspaceApi.action(
                    slug,
                    experimentId,
                    'clone',
                    { draft },
                  );
                  navigate(
                    `/projects/${encodeURIComponent(slug)}/experiments/${copy.id}`,
                  );
                })
              }
            >
              Keep edits as separate experiment
            </Button>
          </ButtonGroup>
          {savedDraft ? (
            <JsonDetails
              title="Current saved draft — compare before recovery"
              value={savedDraft}
            />
          ) : null}
          <JsonDetails
            title="Your unsaved draft (copy for recovery)"
            value={draft}
          />
        </Card>
      ) : null}
      {experiment.archived ? (
        <Card>
          Archived experiments retain their history. Restore this experiment
          from the library to edit it.
        </Card>
      ) : null}
      {search.get('repeat') ? (
        <Card>
          Repeat creates fresh outputs. Dispatch checks this setup and shows the
          exact plan before it submits.
        </Card>
      ) : null}
      <Hint>
        Revision {experiment.revision} · Saving does not run checks or submit
        jobs. Checks run on the controller host when you dispatch.
      </Hint>
      {!connection?.valid ? (
        <Card role="alert">
          <CardHeader title="Connection is not ready" />
          <p>Dispatch stays unavailable until the project connection is valid.</p>
          <Link to={`/projects/${encodeURIComponent(slug)}/settings`}>
            Open connection settings
          </Link>
        </Card>
      ) : null}
      <Card>
        <CardHeader title={draft.name || experiment.name} note={saveState} />
        <Field label="Name">
          <TextInput
            aria-label="Name"
            value={draft.name ?? experiment.name}
            onChange={(e) => change({ name: e.target.value })}
          />
        </Field>
        <Field label="Workflow">
          <TextInput
            aria-label="Workflow"
            readOnly
            value={workflow.title || draft.workflow}
          />
        </Field>
      </Card>
      {openFields.length ? (
        <Card>
          <CardHeader title="Required values" />
          <Grid>
            {openFields.map(([id, f]) => (
              <Field
                key={id}
                label={`${id}${f.unit ? ` (${f.unit})` : ''}${f.required ? ' *' : ''}`}
              >
                <TypedInput
                  label={id}
                  field={f}
                  value={valueFor(id, f)}
                  onChange={(v) =>
                    change({ parameters: { ...draft.parameters, [id]: v } })
                  }
                />
              </Field>
            ))}
          </Grid>
        </Card>
      ) : (
        <Hint>Parameters keep the workflow defaults until you open the section below.</Hint>
      )}
      <Card>
        <CardHeader title="Resources this dispatch will submit" />
        {lead && leadResource ? (
          <Grid>
            <Field label="Primitive">
              <Select
                aria-label="Dispatch primitive"
                value={String(leadResource.primitive ?? 'cpu')}
                options={['cpu', 'gpu', 'multi-cpu', 'multi-gpu'].map((v) => ({
                  value: v,
                  label: v,
                }))}
                onChange={(e) => updateLead('primitive', e.target.value)}
              />
            </Field>
            <Field label="GPUs">
              <TextInput
                aria-label="Dispatch GPUs"
                type="number"
                min={0}
                value={String(leadResource.gpus ?? 0)}
                onChange={(e) => updateLead('gpus', Number(e.target.value))}
              />
            </Field>
            <Field label="Walltime">
              <TextInput
                aria-label="Dispatch walltime"
                value={String(leadResource.walltime ?? '')}
                placeholder="01:00:00"
                onChange={(e) => updateLead('walltime', e.target.value)}
              />
            </Field>
          </Grid>
        ) : (
          <Hint>This workflow has no cluster stage on the default path.</Hint>
        )}
        {workflow.smoke_test_required ? (
          <Checkbox
            label="Include cluster smoke test"
            checked
            disabled
            onChange={() => {}}
          />
        ) : null}
        <Hint>
          {lead
            ? `Stage ${lead.id}. Other stages stay at their defaults.`
            : 'Open the section below to change stages.'}
        </Hint>
      </Card>
      <details>
        <summary style={{ cursor: 'pointer', fontWeight: 600, margin: '8px 0' }}>
          Variants, measurements, and resources
        </summary>
        <Card>
          <CardHeader title="Research notes" />
          <Field label="Research question or notes">
            <TextArea
              aria-label="Research question or notes"
              value={draft.question ?? draft.notes ?? ''}
              onChange={(e) => change({ question: e.target.value })}
            />
          </Field>
          <Field label="Outcome measure">
            <Select
              aria-label="Outcome measure"
              value={draft.outcome_measure ?? ''}
              options={[
                { value: '', label: 'Select outcome measure' },
                ...Object.keys(metrics).map((id) => ({
                  value: id,
                  label: id,
                })),
              ]}
              onChange={(e) => change({ outcome_measure: e.target.value })}
            />
          </Field>
        </Card>
        {Object.entries(metrics).map(([id, metric]) => (
            <Card key={id}>
              <Checkbox
                label={id}
                checked={selectedMetrics.includes(id)}
                onChange={(e) =>
                  change({
                    metrics: toggle(selectedMetrics, id, e.target.checked),
                  })
                }
              />
              <p>{metric.definition}</p>
              <Hint>
                Source:{' '}
                {metric.source_field || metric.collector || 'Undeclared'} ·
                Unit: {metric.unit || 'dimensionless'} · Grouping:{' '}
                {metric.dimensions?.join(', ') || 'none'}
              </Hint>
              {metric.denominator ? (
                <p>Denominator: {metric.denominator}</p>
              ) : null}
              <JsonDetails title="Definition and exclusions" value={metric} />
              {metric.aggregations?.length ? (
                <Select
                  aria-label={`${id} aggregation`}
                  value={draft.aggregations?.[id] ?? ''}
                  options={[
                    {
                      value: '',
                      label: metric.aggregation
                        ? `Declared default: ${metric.aggregation}`
                        : 'No aggregation override',
                    },
                    ...metric.aggregations.map((v) => ({
                      value: v,
                      label: v,
                    })),
                  ]}
                  onChange={(e) => {
                    const aggregations = { ...draft.aggregations };
                    if (e.target.value) aggregations[id] = e.target.value;
                    else delete aggregations[id];
                    change({ aggregations });
                  }}
                />
              ) : null}
              {metric.collection_stages?.length ? (
                <>
                  <Hint>
                    Additional collection has runtime or storage costs. Select
                    it explicitly.
                  </Hint>
                  {metric.collection_stages.map((stage) => (
                    <Checkbox
                      key={stage}
                      label={`Enable additional collection: ${stage}`}
                      checked={
                        draft.collection_stages?.includes(stage) ?? false
                      }
                      onChange={(e) =>
                        change({
                          collection_stages: toggle(
                            draft.collection_stages ?? [],
                            stage,
                            e.target.checked,
                          ),
                        })
                      }
                    />
                  ))}
                </>
              ) : (
                <Hint>Derived from existing records.</Hint>
              )}
            </Card>
          ))}
          {fields.some(([id]) => !openFields.some(([openId]) => openId === id)) ? (
            <Card>
              <CardHeader title="Parameter defaults" />
              <Grid>
                {fields
                  .filter(([id]) => !openFields.some(([openId]) => openId === id))
                  .map(([id, f]) => (
                    <Field
                      key={id}
                      label={`${id}${f.unit ? ` (${f.unit})` : ''}`}
                    >
                      <TypedInput
                        label={id}
                        field={f}
                        value={valueFor(id, f)}
                        onChange={(v) =>
                          change({ parameters: { ...draft.parameters, [id]: v } })
                        }
                      />
                      <Hint>
                        {f.min !== undefined ? `Minimum ${f.min}. ` : ''}
                        {f.max !== undefined ? `Maximum ${f.max}. ` : ''}
                        Default {String(valueFor(id, f) ?? 'unset')}.
                      </Hint>
                    </Field>
                  ))}
              </Grid>
            </Card>
          ) : null}
          <Card>
            <CardHeader title="Variants" />
            <Select
              aria-label="Combination mode"
              value={draft.combinations ? 'explicit' : 'all'}
              options={[
                { value: 'all', label: 'All combinations' },
                { value: 'explicit', label: 'Explicit combinations' },
              ]}
              onChange={(e) =>
                change({
                  combinations:
                    e.target.value === 'explicit' ? [{}] : undefined,
                })
              }
            />
            {draft.combinations ? (
              <Stack>
                {draft.combinations.map((row, index) => (
                  <Card key={index}>
                    <CardHeader title={`Combination ${index + 1}`} />
                    <Grid>
                      {fields
                        .filter(([, f]) => f.variant_eligible)
                        .map(([id, f]) => (
                          <Field key={id} label={id}>
                            <TypedInput
                              label={`Combination ${index + 1} ${id}`}
                              field={f}
                              value={row[id] ?? valueFor(id, f)}
                              onChange={(v) =>
                                change({
                                  combinations: draft.combinations!.map(
                                    (one, n) =>
                                      n === index ? { ...one, [id]: v } : one,
                                  ),
                                })
                              }
                            />
                          </Field>
                        ))}
                    </Grid>
                    <Button
                      onClick={() =>
                        change({
                          combinations: draft.combinations!.filter(
                            (_, n) => n !== index,
                          ),
                        })
                      }
                    >
                      Remove combination
                    </Button>
                  </Card>
                ))}
                <Button
                  onClick={() =>
                    change({ combinations: [...draft.combinations!, {}] })
                  }
                >
                  Add combination
                </Button>
              </Stack>
            ) : (
              fields
                .filter(([, f]) => f.variant_eligible)
                .map(([id, f]) => (
                  <Field key={id} label={`Expand ${id}`}>
                    <Checkbox
                      label={`Use ${id} as a variant axis`}
                      checked={id in (draft.variant_parameters ?? {})}
                      onChange={(e) => {
                        const axes = { ...draft.variant_parameters };
                        if (e.target.checked)
                          axes[id] = [valueFor(id, f) ?? ''];
                        else delete axes[id];
                        change({ variant_parameters: axes });
                      }}
                    />
                    {id in (draft.variant_parameters ?? {}) ? (
                      f.choices ? (
                        <div>
                          {f.choices.map((v) => (
                            <Checkbox
                              key={String(v)}
                              label={String(v)}
                              checked={draft.variant_parameters![id].includes(
                                v,
                              )}
                              onChange={(e) =>
                                change({
                                  variant_parameters: {
                                    ...draft.variant_parameters,
                                    [id]: toggle(
                                      draft.variant_parameters![id],
                                      v,
                                      e.target.checked,
                                    ),
                                  },
                                })
                              }
                            />
                          ))}
                        </div>
                      ) : (
                        <TextInput
                          aria-label={`${id} variant values`}
                          placeholder="Comma-separated values"
                          value={draft.variant_parameters![id].join(', ')}
                          onChange={(e) =>
                            change({
                              variant_parameters: {
                                ...draft.variant_parameters,
                                [id]: e.target.value
                                  .split(',')
                                  .map((v) => cast(v.trim(), f)),
                              },
                            })
                          }
                        />
                      )
                    ) : null}
                  </Field>
                ))
            )}
            <Hint>
              Dispatch shows the exact expanded list. Invalid combinations
              remain visible until corrected or explicitly excluded.
            </Hint>
          </Card>
          {composed ? <CompositionEditor draft={draft} onChange={(next) => change(next)} /> : null}
          <Card>
            <CardHeader title="Stages and resources" />
            <Field label="Variant concurrency">
              <TextInput
                aria-label="Variant concurrency"
                type="number"
                min={1}
                value={draft.variant_concurrency ?? 1}
                onChange={(e) =>
                  change({ variant_concurrency: Number(e.target.value) })
                }
              />
            </Field>
            <Hint>
              Variant concurrency limits independent variants. Coordinated ranks
              belong to a stage resource request.
            </Hint>
            {!composed ? <Checkbox
              label="Include cluster smoke test"
              checked={
                draft.include_smoke_test ??
                Boolean(workflow.smoke_test_required)
              }
              disabled={Boolean(workflow.smoke_test_required)}
              onChange={(e) => change({ include_smoke_test: e.target.checked })}
            /> : null}
            {!composed ? <Select
              aria-label="Prerequisites"
              value={draft.prerequisites ?? 'add'}
              options={[
                { value: 'add', label: 'Add prerequisite stages' },
                { value: 'existing', label: 'Use existing completed outputs' },
              ]}
              onChange={(e) =>
                change({ prerequisites: e.target.value as 'add' | 'existing' })
              }
            /> : null}
            <Stack>
              {workflow.stages.map((stage) => {
                const location =
                  stage.location ??
                  manifest?.operations?.[stage.operation]?.location;
                const local = location === 'controller';
                const resource: Resource = {
                  primitive: local ? 'cpu' : manifest?.default_primitive,
                  mode: local ? 'single' : manifest?.default_mode,
                  cpus: 1,
                  gpus: local ? 0 : 1,
                  nodes: 1,
                  ranks: 1,
                  memory_gb: 4,
                  walltime: '00:30:00',
                  ...stage.resources,
                  ...draft.resources?.[stage.id],
                };
                const updateResource = (k: string, v: string | number) =>
                  change({
                    resources: {
                      ...draft.resources,
                      [stage.id]: { ...draft.resources?.[stage.id], [k]: v },
                    },
                  });
                return (
                  <Card key={stage.id}>
                    <CardHeader
                      title={stage.id}
                      note={`Purpose: ${stage.purpose === 'smoke-test' ? 'Smoke test' : 'Experiment'}`}
                    />
                    <Checkbox
                      label={`Include ${stage.id}`}
                      checked={includedStages.includes(stage.id)}
                      disabled={stage.purpose === 'smoke-test'}
                      onChange={(e) =>
                        change({
                          stages: toggle(
                            includedStages,
                            stage.id,
                            e.target.checked,
                          ),
                        })
                      }
                    />
                    <Hint>
                      Operation: {stage.operation} · Depends on:{' '}
                      {stage.depends_on?.join(', ') || 'none'} · Location:{' '}
                      {location ?? 'cluster'}
                    </Hint>
                    {draft.prerequisites === 'existing'
                      ? (expandedVariants.length
                          ? expandedVariants
                          : [{ id: '', parameters: {} }]
                        ).map((variant) => {
                          const reference = variant.id
                            ? `${variant.id}:${stage.id}`
                            : stage.id;
                          return (
                            <Field
                              key={reference}
                              label={
                                variant.id
                                  ? `${stage.id} input for ${variant.id}`
                                  : `${stage.id} input (check setup to assign each variant)`
                              }
                            >
                              <Select
                                aria-label={`${reference} existing artifact`}
                                value={
                                  draft.existing_artifacts?.[reference] ??
                                  draft.existing_artifacts?.[stage.id] ??
                                  ''
                                }
                                options={[
                                  {
                                    value: '',
                                    label:
                                      'Choose compatible completed artifact',
                                  },
                                  ...artifacts
                                    .filter(
                                      (a) =>
                                        a.purpose !== 'smoke-test' &&
                                        a.complete,
                                    )
                                    .map((a) => ({
                                      value: a.id,
                                      label: `${a.id} · ${a.path}`,
                                    })),
                                ]}
                                onChange={(e) =>
                                  change({
                                    existing_artifacts: {
                                      ...draft.existing_artifacts,
                                      [reference]: e.target.value,
                                    },
                                  })
                                }
                              />
                            </Field>
                          );
                        })
                      : null}
                    <Grid>
                      <Field label="Primitive">
                        <Select
                          aria-label={`${stage.id} primitive`}
                          value={
                            resource.primitive ??
                            manifest?.default_primitive ??
                            'cpu'
                          }
                          options={['cpu', 'gpu', 'multi-cpu', 'multi-gpu'].map(
                            (v) => ({ value: v, label: v }),
                          )}
                          onChange={(e) =>
                            updateResource('primitive', e.target.value)
                          }
                        />
                      </Field>
                      <Field label="Execution mode">
                        <Select
                          aria-label={`${stage.id} mode`}
                          value={
                            resource.mode ??
                            manifest?.default_mode ??
                            'independent'
                          }
                          options={[
                            { value: 'single', label: 'Single process' },
                            {
                              value: 'independent',
                              label: 'Independent experiments',
                            },
                            {
                              value: 'coordinated',
                              label: 'Coordinated ranks',
                            },
                          ]}
                          onChange={(e) =>
                            updateResource('mode', e.target.value)
                          }
                        />
                      </Field>
                      {['cpus', 'gpus', 'nodes', 'ranks', 'memory_gb'].map(
                        (k) => (
                          <Field key={k} label={k}>
                            <TextInput
                              aria-label={`${stage.id} ${k}`}
                              type="number"
                              min={k === 'gpus' ? 0 : 1}
                              value={String(resource[k] ?? '')}
                              onChange={(e) =>
                                updateResource(k, Number(e.target.value))
                              }
                            />
                          </Field>
                        ),
                      )}
                      <Field label="Walltime">
                        <TextInput
                          aria-label={`${stage.id} walltime`}
                          value={resource.walltime ?? ''}
                          placeholder="01:00:00"
                          onChange={(e) =>
                            updateResource('walltime', e.target.value)
                          }
                        />
                      </Field>
                    </Grid>
                    <JsonDetails
                      title="Declared outputs and prerequisites"
                      value={stage}
                    />
                  </Card>
                );
              })}
            </Stack>
          </Card>
          <details>
            <summary>Project defaults</summary>
            <Hint>Saved drafts retain their resources. Review the differences before adopting current project defaults.</Hint>
            <Button disabled={!safe} onClick={() => void action(async () => setDefaultsPreview(await workspaceRequest(slug, `experiments/${experimentId}/defaults`, 'POST', {})))}>Preview current defaults</Button>
            {defaultsPreview ? <><JsonDetails title="Default changes" value={defaultsPreview.differences} /><Button disabled={!safe} onClick={() => void action(async () => {
              const updated = await workspaceRequest<Experiment>(slug, `experiments/${experimentId}/defaults`, 'POST', {apply:true, expected_version:defaultsPreview.expected_version, declaration_digest:defaultsPreview.declaration_digest});
              setExperiment(updated);setDraft(updated.draft);setCheck(null);setPlan(null);setApproved(false);setDefaultsPreview(null);sessionStorage.removeItem(key);
            })}>Adopt reviewed defaults</Button><Button onClick={() => setDefaultsPreview(null)}>Keep saved values</Button></> : null}
          </details>
          <Button
            onClick={() =>
              void action(async () => {
                const result = await workspaceRequest<{ revisions: unknown[] }>(
                  slug,
                  `experiments/${experimentId}/revisions`,
                );
                setRevisions(result.revisions);
              })
            }
          >
            Revision history
          </Button>
          {revisions ? (
            <Card>
              <CardHeader title="Immutable revision history" />
              <JsonDetails title="Saved revisions" value={revisions} />
            </Card>
          ) : null}
      </details>
      {check ? (
        <Card>
          <CardHeader
            title={
              check.valid ? 'Setup checks passed' : 'Setup needs attention'
            }
          />
          <ul>
            {check.errors.map((issue, index) => (
              <li key={index}>
                {[issue.field, issue.variant_id, issue.stage_id]
                  .filter(Boolean)
                  .join(' · ')}
                : {issue.message}
              </li>
            ))}
          </ul>
          <JsonDetails title="Controller-host checks" value={check.checks} />
        </Card>
      ) : null}
      {expandedVariants.length ? (
        <Card>
          <CardHeader
            title={`Expanded variants · ${expandedVariants.length}`}
          />
          <Hint>An edit clears this plan. Dispatch checks the setup again.</Hint>
          {expandedVariants.map((variant) => (
            <div key={variant.id}>
              <Checkbox
                label={`Exclude ${variant.id}`}
                checked={draft.excluded_variants?.includes(variant.id) ?? false}
                onChange={(e) =>
                  change({
                    excluded_variants: toggle(
                      draft.excluded_variants ?? [],
                      variant.id,
                      e.target.checked,
                    ),
                  })
                }
              />
              <JsonDetails title={variant.id} value={variant.parameters} />
            </div>
          ))}
        </Card>
      ) : null}
      {plan && check?.valid ? (
        <Card>
          <CardHeader
            title={`Exact plan ${plan.id}`}
            note={`${plan.variants.length} variants · ${plan.stages.length} stages`}
          />
          <p>
            This approval covers only the exact source, configuration, stages,
            resources, and outputs shown here. An edit requires a new check.
          </p>
          <KeyValue label="Source digest">{plan.source?.digest}</KeyValue>
          <JsonDetails title="Frozen configuration" value={plan.config} />
          {plan.stages.map((stage) => (
            <div key={stage.id}>
              <KeyValue label={stage.id}>
                {stage.purpose} · {stage.resources.primitive} ·{' '}
                {stage.resources.gpus ?? 0} GPUs · {stage.resources.walltime} ·{' '}
                {stage.output_dir}
              </KeyValue>
              <JsonDetails title={`${stage.id} script and outputs`} value={{
                script: stage.script,
                argv: stage.argv,
                outputs: stage.outputs,
                resources: stage.resources,
              }} />
            </div>
          ))}
          <Checkbox
            label="I reviewed this exact plan, including its scripts, resources, and outputs"
            checked={approved}
            onChange={(e) => setApproved(e.target.checked)}
          />
        </Card>
      ) : null}
    </WorkspacePage>
  );
};
