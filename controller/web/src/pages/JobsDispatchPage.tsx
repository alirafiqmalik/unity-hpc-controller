/**
 * Build one run request, preview the exact body, and post it.
 *
 * The preview is the request, not a description of it: it is assembled from
 * the same function that posts, so a body that reads right here is the body
 * the controller receives. Each mode only puts in the body the fields the
 * controller reads for that mode: a fan-out (`run.sh array`) takes no exp,
 * no overrides and no dry-run, so this page does not offer them there.
 */

import { IconChecks, IconPlayerPlay } from '@tabler/icons-react';
import { useEffect, useMemo, useState } from 'react';
import { useRecoilValue } from 'recoil';

import type { DispatchBody, ProjectRecord, RunResult } from '../modules/controller/api';
import { eventsState, projectsState } from '../modules/controller/state';
import { EventFeed } from '../modules/events/EventFeed';
import {
  canDispatch,
  ExperimentCatalog,
  ReadinessTags,
  ResourceList,
} from '../modules/projects/ProjectFacts';
import { useProjectCommands } from '../modules/projects/useProjectCommands';
import { Button, ButtonGroup } from '../ui/components/Button';
import { Card, CardHeader, Grid, Hint } from '../ui/components/Card';
import { CodeBlock } from '../ui/components/CodeBlock';
import { EmptyState } from '../ui/components/EmptyState';
import { Field, FieldRow, Select, TextInput } from '../ui/components/Field';
import { Chip, ChipRow, Tag } from '../ui/components/Tag';
import { useToast } from '../ui/components/Toast';
import { Page } from '../ui/layout/AppLayout';

type Mode = 'single' | 'fanout';

type Form = {
  slug: string;
  mode: Mode;
  exp: string;
  campaign: string;
  partition: string;
  gpus: string;
  cpus: string;
  memory: string;
  nodes: string;
  constraint: string;
  gpuType: string;
  walltime: string;
  command: string;
  manifest: string;
};

const EMPTY: Form = {
  slug: '',
  mode: 'single',
  exp: '',
  campaign: '',
  partition: '',
  gpus: '',
  cpus: '',
  memory: '',
  nodes: '',
  constraint: '',
  gpuType: '',
  walltime: '',
  command: '',
  manifest: '',
};

/** The exact body the Dispatch button posts. Validate adds `dry_run: true`. */
const toBody = (form: Form): DispatchBody => {
  const body: DispatchBody = {};
  if (form.campaign.trim()) body.campaign = form.campaign.trim();
  if (form.mode === 'fanout') {
    // The controller reads only manifest, campaign and extra_args here.
    if (form.manifest.trim()) body.manifest = form.manifest.trim();
    return body;
  }
  if (form.exp.trim()) body.exp = form.exp.trim();
  const overrides: Record<string, string> = {};
  if (form.command.trim()) overrides.JOB_COMMAND = form.command.trim();
  if (form.walltime.trim()) overrides.WALLTIME = form.walltime.trim();
  if (form.partition.trim()) overrides.SLURM_PARTITION = form.partition.trim();
  if (form.gpus.trim()) overrides.SLURM_GPUS = form.gpus.trim();
  if (form.cpus.trim()) overrides.SLURM_CPUS = form.cpus.trim();
  if (form.memory.trim()) overrides.SLURM_MEM = form.memory.trim();
  if (form.nodes.trim()) overrides.SLURM_NODES = form.nodes.trim();
  if (form.constraint.trim()) overrides.SLURM_CONSTRAINT = form.constraint.trim();
  if (form.gpuType.trim()) overrides.SLURM_GPU_TYPE = form.gpuType.trim();
  if (Object.keys(overrides).length) body.overrides = overrides;
  return body;
};

const MODES: { id: Mode; label: string }[] = [
  { id: 'single', label: 'Single run' },
  { id: 'fanout', label: 'Fan-out (manifest)' },
];

export const JobsDispatchPage = () => {
  const projects = useRecoilValue(projectsState);
  const events = useRecoilValue(eventsState);
  const { dispatch, busy } = useProjectCommands();
  const toast = useToast();
  const [form, setForm] = useState<Form>(EMPTY);
  const [armed, setArmed] = useState(false);
  const [lastRun, setLastRun] = useState<{
    slug: string;
    label: string;
    answer: RunResult;
  } | null>(null);

  // A selection that is no longer attached falls back to the first project.
  const selected = projects.some((one) => one.slug === form.slug)
    ? form.slug
    : projects[0]?.slug ?? '';
  const project: ProjectRecord | null =
    projects.find((one) => one.slug === selected) ?? null;
  const body = useMemo(() => toBody(form), [form]);
  const fanout = form.mode === 'fanout';
  const ready = canDispatch(project);
  const target = fanout ? body.manifest : body.exp;
  const restrictedMatches = project?.experiments?.filter(
    (one) => one.ledger_exp === body.exp && one.status !== 'ready',
  ) ?? [];

  // Any change to the request disarms a pending fan-out confirmation.
  useEffect(() => setArmed(false), [form, selected]);
  useEffect(() => {
    if (!armed) return;
    const timer = window.setTimeout(() => setArmed(false), 10000);
    return () => window.clearTimeout(timer);
  }, [armed]);

  const dispatched = useMemo(
    () =>
      [...events]
        .reverse()
        .filter((event) => event.kind === 'dispatch' || event.kind === 'dry-run'),
    [events],
  );

  const blocker = !selected
    ? 'Attach a project first.'
    : !ready
      ? `${selected} has no unityHPC/run.sh. Run /unity-hpc:connect in the project first.`
      : !target
        ? fanout
          ? 'A fan-out needs a manifest path.'
          : 'A single run needs an exp.'
        : null;

  const send = async (dry: boolean) => {
    if (blocker) {
      toast(blocker, 'error');
      return;
    }
    if (!dry && !armed) {
      setArmed(true);
      return;
    }
    setArmed(false);
    const posted = dry ? { ...body, dry_run: true } : body;
    const answer = await dispatch(selected, posted);
    if (answer) {
      setLastRun({
        slug: selected,
        label: fanout ? 'fan-out' : dry ? 'validate' : 'dispatch',
        answer,
      });
    }
  };

  const set = (change: Partial<Form>) => setForm({ ...form, ...change });

  return (
    <Page
      actions={
        <Tag
          color={ready ? 'green' : 'gray'}
          text={
            ready
              ? 'the controller submits through run.sh'
              : 'no scaffold on the selected project'
          }
        />
      }
    >
      {projects.length === 0 ? (
        <Card>
          <EmptyState title="No attached projects">
            A dispatch goes to one attached project. Attach a directory on the
            Project page first.
          </EmptyState>
        </Card>
      ) : null}

      <Grid $columns={2} $min="380px">
        <Card>
          <CardHeader title="Run request" />
          <Field label="Project">
            <Select
              value={selected}
              options={
                projects.length
                  ? projects.map((one) => ({ value: one.slug, label: one.slug }))
                  : [{ value: '', label: 'No attached projects' }]
              }
              onChange={(event) => set({ slug: event.target.value })}
            />
          </Field>
          {project ? (
            <div style={{ marginTop: 8 }}>
              <ReadinessTags project={project} />
            </div>
          ) : null}

          <div style={{ marginTop: 16 }}>
            <ChipRow role="radiogroup" aria-label="Dispatch mode">
              {MODES.map((one) => (
                <Chip
                  key={one.id}
                  type="button"
                  role="radio"
                  aria-checked={form.mode === one.id}
                  $active={form.mode === one.id}
                  onClick={() => set({ mode: one.id })}
                >
                  {one.label}
                </Chip>
              ))}
            </ChipRow>
          </div>

          {fanout ? (
            <>
              <FieldRow>
                <Field label="Manifest path">
                  <TextInput
                    value={form.manifest}
                    placeholder="unityHPC/manifests/sweep.tsv"
                    aria-required
                    onChange={(event) => set({ manifest: event.target.value })}
                  />
                </Field>
                <Field label="Campaign">
                  <TextInput
                    value={form.campaign}
                    placeholder={project?.campaign || "default: today's UTC date"}
                    onChange={(event) => set({ campaign: event.target.value })}
                  />
                </Field>
              </FieldRow>
              <Hint>
                A fan-out calls <code>run.sh array &lt;manifest&gt;</code>. A
                relative path is read from the project directory. The manifest
                sets each task; this page sends no exp, no overrides and no
                dry-run, because <code>run.sh array</code> does not take them.
                There is no validate step, so Dispatch asks you to confirm.
              </Hint>
            </>
          ) : (
            <>
              <FieldRow>
                <Field label="Exp">
                  <TextInput
                    value={form.exp}
                    placeholder="smoke"
                    aria-required
                    onChange={(event) => set({ exp: event.target.value })}
                  />
                </Field>
                <Field label="Campaign">
                  <TextInput
                    value={form.campaign}
                    placeholder={project?.campaign || "default: today's UTC date"}
                    onChange={(event) => set({ campaign: event.target.value })}
                  />
                </Field>
              </FieldRow>
              <FieldRow $columns={3}>
                <Field label="Partition">
                  <TextInput
                    value={form.partition}
                    placeholder="optional"
                    onChange={(event) => set({ partition: event.target.value })}
                  />
                </Field>
                <Field label="GPUs">
                  <TextInput
                    value={form.gpus}
                    placeholder="optional"
                    onChange={(event) => set({ gpus: event.target.value })}
                  />
                </Field>
                <Field label="Walltime">
                  <TextInput
                    value={form.walltime}
                    placeholder="optional, 08:00:00"
                    onChange={(event) => set({ walltime: event.target.value })}
                  />
                </Field>
              </FieldRow>
              <FieldRow $columns={1}>
                <Field label="Command">
                  <TextInput
                    value={form.command}
                    placeholder="optional JOB_COMMAND"
                    onChange={(event) => set({ command: event.target.value })}
                  />
                </Field>
              </FieldRow>
              <FieldRow $columns={3}>
                <Field label="CPUs per task">
                  <TextInput value={form.cpus} placeholder="optional" onChange={(event) => set({ cpus: event.target.value })} />
                </Field>
                <Field label="Memory">
                  <TextInput value={form.memory} placeholder="optional, 16G" onChange={(event) => set({ memory: event.target.value })} />
                </Field>
                <Field label="Nodes">
                  <TextInput value={form.nodes} placeholder="optional" onChange={(event) => set({ nodes: event.target.value })} />
                </Field>
              </FieldRow>
              <FieldRow>
                <Field label="GPU type">
                  <TextInput value={form.gpuType} placeholder="optional, a100" onChange={(event) => set({ gpuType: event.target.value })} />
                </Field>
                <Field label="Constraint">
                  <TextInput value={form.constraint} placeholder="optional Slurm constraint" onChange={(event) => set({ constraint: event.target.value })} />
                </Field>
              </FieldRow>
              <Hint>
                A single run calls <code>run.sh run &lt;exp&gt;</code>. Filled
                resource fields go as the matching Slurm environment overrides;
                run.sh refuses a key it does not list in{' '}
                <code>UNITY_OVERRIDABLE</code>. Validate calls{' '}
                <code>run.sh run --dry-run</code> and submits nothing.
              </Hint>
            </>
          )}

          <ButtonGroup align="right" style={{ marginTop: 16 }}>
            {fanout ? null : (
              <Button
                Icon={IconChecks}
                disabled={busy || Boolean(blocker)}
                onClick={() => void send(true)}
              >
                Validate
              </Button>
            )}
            <Button
              variant={armed ? 'danger' : 'primary'}
              Icon={IconPlayerPlay}
              disabled={busy || Boolean(blocker)}
              onClick={() => void send(false)}
            >
              {armed
                ? fanout ? 'Click again to submit the fan-out' : 'Click again to dispatch'
                : 'Dispatch'}
            </Button>
          </ButtonGroup>
          {blocker && projects.length ? (
            <Hint role="status">{blocker}</Hint>
          ) : null}
          {!fanout && restrictedMatches.length ? (
            <Hint role="alert">
              This exp matches a catalog entry that is not ready to run. Manual
              dispatch uses the fields above and does not apply the catalog gate.
            </Hint>
          ) : null}
        </Card>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Card>
            <CardHeader
              title="Request preview"
              note={fanout ? 'exactly what Dispatch posts' : 'Validate adds "dry_run": true'}
            />
            <CodeBlock
              caption={`POST /api/v1/projects/${selected || '{slug}'}/runs`}
              maxHeight="260px"
            >
              {JSON.stringify(body, null, 2)}
            </CodeBlock>
            {lastRun ? (
              <div style={{ marginTop: 12 }} aria-live="polite">
                <CodeBlock
                  caption={`${lastRun.slug} · ${lastRun.label} · ${
                    lastRun.answer.ok ? 'ok' : 'failed'
                  }`}
                  maxHeight="220px"
                >
                  {lastRun.answer.output || lastRun.answer.error || '(no output)'}
                </CodeBlock>
              </div>
            ) : null}
          </Card>
          {project ? (
            <Card>
              <CardHeader
                title={`${project.slug} · declared needs`}
                note="declared by the project · not enforced"
              />
              <ResourceList
                resources={project.resources}
                empty="The project declares no resources."
              />
              <Hint>
                These values are not added to the request. To ask Slurm for
                them, fill the matching fields.
              </Hint>
            </Card>
          ) : null}
          {project && (project.experiments?.length || project.experiments_error) ? (
            <Card>
              <CardHeader
                title="Experiment catalog"
                note={`${project.experiments?.length ?? 0} in unityHPC/experiments.json`}
              />
              <ExperimentCatalog
                key={selected}
                slug={selected}
                experiments={project.experiments}
                error={project.experiments_error}
              />
            </Card>
          ) : null}
          <Card>
            <CardHeader
              title="Recently dispatched"
              note={dispatched.length ? `${dispatched.length} in the log` : undefined}
            />
            <EventFeed
              events={dispatched}
              limit={8}
              emptyTitle="Nothing dispatched yet"
              emptyBody="A dispatch and a dry-run both appear here as soon as the controller answers."
            />
          </Card>
        </div>
      </Grid>
    </Page>
  );
};
