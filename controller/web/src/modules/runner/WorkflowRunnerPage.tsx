import styled from '@emotion/styled';
import { useEffect, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Button, ButtonGroup } from '../../ui/components/Button';
import { Card, CardHeader, Grid, Hint, KeyValue, Stack } from '../../ui/components/Card';
import { Field, Select, TextInput } from '../../ui/components/Field';
import { Tag } from '../../ui/components/Tag';
import { ApiError, errorText } from '../controller/api';
import { runnerRequest, type Catalog, type Execution, type Parameter, type Plan, type Prepared } from './api';
import { ProjectPage } from './ProjectPage';

const Layout = styled.div`
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(260px, 1fr);
  gap: ${({ theme }) => theme.spacing(4)};
  @media (max-width: 950px) { grid-template-columns: 1fr; }
`;

export const WorkflowRunnerPage = () => {
  const { slug = '' } = useParams();
  const [search, setSearch] = useSearchParams();
  const navigate = useNavigate();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [workflowId, setWorkflowId] = useState(search.get('workflow') ?? '');
  const [name, setName] = useState('');
  const [values, setValues] = useState<Record<string, string>>({});
  const [step, setStep] = useState(1);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [checks, setChecks] = useState<unknown>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const workflow = catalog?.workflows.find((one) => one.id === workflowId);
  const planId = search.get('plan');

  useEffect(() => {
    let active = true;
    setCatalog(null); setError(''); setPlan(null); setStep(1);
    void runnerRequest<Catalog>(slug, 'workflows').then((result) => {
      if (!active) return;
      setCatalog(result);
      setWorkflowId((current) => result.workflows.some((one) => one.id === current) ? current : result.workflows[0]?.id ?? '');
    }).catch((reason) => { if (active) setError(errorText(reason)); });
    return () => { active = false; };
  }, [slug]);
  useEffect(() => {
    setValues(Object.fromEntries((workflow?.parameters ?? []).map((one) => [one.name, String(one.default ?? '')])));
    setPlan((current) => current?.config?.workflow === workflow?.id ? current : null);
    setChecks(null); setStep((current) => current === 2 ? current : 1);
    setName(workflow?.title ?? '');
  }, [workflow]);
  useEffect(() => {
    if (!planId || !catalog) return;
    let active = true;
    void runnerRequest<Plan>(slug, `plans/${encodeURIComponent(planId)}`).then((value) => {
      if (active) {
        const declared = catalog.workflows.find((one) => one.id === value.config?.workflow);
        if (declared) {
          setWorkflowId(declared.id);
          setValues(Object.fromEntries(declared.parameters.map((one) => [one.name, String(value.config?.parameters?.[one.name] ?? one.default ?? '')])));
          setName(value.config?.name ?? declared.title);
        }
        setPlan(value); setStep(2);
      }
    }).catch((reason) => { if (active) setError(errorText(reason)); });
    return () => { active = false; };
  }, [slug, planId, catalog, workflowId]);

  const invalidate = () => {
    setPlan(null); setChecks(null); setError('');
    if (planId) { const next = new URLSearchParams(search); next.delete('plan'); setSearch(next, { replace: true }); }
  };
  const setParameter = (key: string, value: string) => { invalidate(); setValues((current) => ({ ...current, [key]: value })); };
  const parameter = (one: Parameter) => <Field key={one.name} label={`${one.label}${one.unit ? ` (${one.unit})` : ''}`}>
    {one.type === 'boolean' || one.choices?.length ? <Select disabled={busy} aria-label={one.label} value={values[one.name] ?? ''}
      options={(one.type === 'boolean' ? ['false', 'true'] : one.choices!).map((value) => ({ value: String(value), label: String(value) }))}
      onChange={(event) => setParameter(one.name, event.target.value)} /> : <TextInput disabled={busy} aria-label={one.label} value={values[one.name] ?? ''}
      type={one.type === 'integer' || one.type === 'number' ? 'number' : 'text'} min={one.min} max={one.max} required={one.required}
      step={one.type === 'number' ? 'any' : undefined} onChange={(event) => setParameter(one.name, event.target.value)} />}
  </Field>;
  const prepare = async () => {
    if (!workflow) return;
    setBusy(true); setError(''); setPlan(null);
    try {
      const parameters = Object.fromEntries(workflow.parameters.filter((one) => values[one.name] !== '' && values[one.name] !== undefined).map((one) => [one.name,
        one.type === 'boolean' ? values[one.name] === 'true' : one.type === 'number' || one.type === 'integer' ? Number(values[one.name]) : values[one.name]]));
      const result = await runnerRequest<Prepared>(slug, 'plans', 'POST', { workflow: workflow.id, name: name.trim(), parameters });
      setChecks(result.checks); setPlan(result.plan ?? null); setStep(2);
      const next = new URLSearchParams(search); next.set('workflow', workflow.id);
      if (result.plan_id) next.set('plan', result.plan_id);
      setSearch(next, { replace: true });
    } catch (reason) {
      setError(errorText(reason)); setStep(2);
      setChecks(reason instanceof ApiError ? reason.payload.checks ?? reason.payload.errors ?? null : null);
    }
    finally { setBusy(false); }
  };
  const approve = async () => {
    if (!plan) return;
    setBusy(true); setError('');
    try {
      const execution = await runnerRequest<Execution>(slug, `plans/${encodeURIComponent(plan.id)}/approve`, 'POST', { idempotency_key: `runner-${plan.id}` });
      navigate(`/projects/${encodeURIComponent(slug)}/executions/${encodeURIComponent(execution.id)}`);
    } catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  };

  return <ProjectPage title="Workflow runner">
    {error ? <Card role="alert">{error}</Card> : null}
    {!catalog ? <p role="status">Loading workflows…</p> : <>
      {!catalog.valid ? <Card role="alert"><strong>Project connection needs attention</strong><Hint>Update this project’s workflow setup before preparing a new run. Execution history remains available.</Hint><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(catalog.errors, null, 2)}</pre></Card> : null}
      {!catalog.workflows.length && !plan ? <Card><CardHeader title="No declared workflows" /><p>Declare this project’s operations and workflows in unityHPC/project.json to configure a run here.</p></Card> : <>
        <Layout><Stack>
          {step !== 2 ? <Card>
            <CardHeader title="Workflow setup" />
            <Field label="Workflow">
              <Select disabled={busy} aria-label="Workflow" value={workflowId}
                options={catalog.workflows.map((one) => ({ value: one.id, label: one.title }))}
                onChange={(event) => { invalidate(); setWorkflowId(event.target.value); }} />
            </Field>
            <Hint>{workflow?.purpose === 'smoke-test' ? 'Smoke test' : 'Experiment'} · {workflow?.stages.length} stages</Hint>
            <Field label="Run name">
              <TextInput disabled={busy} aria-label="Run name" value={name}
                onChange={(event) => { invalidate(); setName(event.target.value); }} />
            </Field>
            <Grid>{workflow?.parameters.map(parameter)}</Grid>
            <ButtonGroup align="right">
              <Button variant="primary" disabled={busy || !catalog.valid || !name.trim()}
                onClick={() => void prepare()}>{busy ? 'Checking setup…' : 'Check setup and review'}</Button>
            </ButtonGroup>
          </Card> : null}
          {step === 2 ? <Card><CardHeader title="Review the run" note={plan?.id} /><Tag color={plan?.valid ? 'green' : 'yellow'} text={plan?.valid ? 'Setup checked' : 'Approval blocked'} />
            {plan ? <><KeyValue label="Source digest">{plan.source?.digest ?? 'Recorded in plan'}</KeyValue><KeyValue label="Variants">{plan.variants.length}</KeyValue>
              {plan.stages.map((stage) => <details key={stage.id}><summary>{stage.id} · {stage.location} · {stage.purpose}</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify({ resources: stage.resources, depends_on: stage.depends_on, argv: stage.argv, output_dir: stage.output_dir, outputs: stage.outputs }, null, 2)}</pre><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{stage.script}</pre></details>)}
              <details><summary>Inputs and check results</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify({ inputs: plan.inputs, checks: checks ?? plan.checks, errors: plan.errors, recovery: plan.recovery }, null, 2)}</pre></details></> : null}
            {!plan && checks ? <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(checks, null, 2)}</pre> : null}
            <Hint>Approval starts this frozen plan. Changes to setup, source, or inputs require a new review.</Hint>
            <ButtonGroup align="right"><Button disabled={busy} onClick={() => setStep(1)}>Back to setup</Button><Button variant="primary" disabled={busy || !plan?.valid} onClick={() => void approve()}>{busy ? 'Approving…' : 'Approve run'}</Button></ButtonGroup>
          </Card> : null}
        </Stack><Card><CardHeader title="Stages" />{(plan?.stages ?? workflow?.stages ?? []).map((stage) => <Stack key={stage.id} $gap={1} style={{ paddingBottom: 16 }}><strong>{stage.id}</strong><Hint>{stage.operation} · {stage.location} · {stage.purpose}</Hint><Hint>Depends on: {stage.depends_on?.join(', ') || 'None'}</Hint><Hint>{Object.entries(stage.resources ?? {}).map(([key, value]) => `${key.replaceAll('_', ' ')}: ${value}`).join(' · ')}</Hint></Stack>)}</Card></Layout>
      </>}
    </>}
  </ProjectPage>;
};
