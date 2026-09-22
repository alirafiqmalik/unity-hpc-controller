/**
 * Build one run request, preview the exact body, and post it.
 *
 * The preview is the request, not a description of it: it is assembled from
 * the same function that posts, so a body that reads right here is the body
 * the controller receives.
 */

import { IconChecks, IconPlayerPlay } from '@tabler/icons-react';
import { useMemo, useState } from 'react';
import { useRecoilValue } from 'recoil';

import type { DispatchBody } from '../modules/controller/api';
import { eventsState, projectsState } from '../modules/controller/state';
import { EventFeed } from '../modules/events/EventFeed';
import { useProjectCommands } from '../modules/projects/useProjectCommands';
import { Button, ButtonGroup } from '../ui/components/Button';
import { Card, CardHeader, Grid, Hint } from '../ui/components/Card';
import { CodeBlock } from '../ui/components/CodeBlock';
import { EmptyState } from '../ui/components/EmptyState';
import {
  Checkbox,
  Field,
  FieldRow,
  Select,
  TextArea,
  TextInput,
} from '../ui/components/Field';
import { Tag } from '../ui/components/Tag';
import { useToast } from '../ui/components/Toast';
import { Page } from '../ui/layout/AppLayout';

type Form = {
  slug: string;
  exp: string;
  campaign: string;
  partition: string;
  gpus: string;
  walltime: string;
  command: string;
  manifest: string;
  dryRun: boolean;
};

const EMPTY: Form = {
  slug: '',
  exp: '',
  campaign: '',
  partition: '',
  gpus: '',
  walltime: '',
  command: '',
  manifest: '',
  dryRun: false,
};

/** The exact body the controller receives. */
const toBody = (form: Form): DispatchBody => {
  const body: DispatchBody = {};
  if (form.exp.trim()) body.exp = form.exp.trim();
  if (form.campaign.trim()) body.campaign = form.campaign.trim();
  if (form.manifest.trim()) body.manifest = form.manifest.trim();
  body.dry_run = form.dryRun;
  const overrides: Record<string, string> = {};
  if (form.command.trim()) overrides.JOB_COMMAND = form.command.trim();
  if (form.walltime.trim()) overrides.WALLTIME = form.walltime.trim();
  if (form.partition.trim()) overrides.SLURM_PARTITION = form.partition.trim();
  if (form.gpus.trim()) overrides.SLURM_GPUS = form.gpus.trim();
  if (Object.keys(overrides).length) body.overrides = overrides;
  return body;
};

export const JobsDispatchPage = () => {
  const projects = useRecoilValue(projectsState);
  const events = useRecoilValue(eventsState);
  const { dispatch, busy } = useProjectCommands();
  const toast = useToast();
  const [form, setForm] = useState<Form>(EMPTY);

  const slug = form.slug || projects[0]?.slug || '';
  const project = projects.find((one) => one.slug === slug);
  const body = useMemo(() => toBody(form), [form]);

  const dispatched = useMemo(
    () =>
      [...events]
        .reverse()
        .filter((event) => event.kind === 'dispatch' || event.kind === 'dry-run'),
    [events],
  );

  const send = async (forceDry: boolean) => {
    if (!slug) {
      toast('Attach a project first', 'error');
      return;
    }
    if (!body.exp && !body.manifest) {
      toast('exp is required, or a manifest path for a fan-out', 'error');
      return;
    }
    await dispatch(slug, { ...body, dry_run: forceDry || body.dry_run });
  };

  return (
    <Page
      actions={
        <Tag
          color={project?.scaffold ? 'green' : 'gray'}
          text={
            project?.scaffold
              ? 'the controller submits through run.sh'
              : 'no scaffold on the selected project'
          }
        />
      }
    >
      {projects.length === 0 ? (
        <Card>
          <EmptyState title="No attached projects">
            A dispatch goes to one attached project. Register a directory on the
            Project page first.
          </EmptyState>
        </Card>
      ) : null}

      <Grid $columns={2} $min="380px">
        <Card>
          <CardHeader title="Run request" />
          <Field label="Project">
            <Select
              value={slug}
              options={
                projects.length
                  ? projects.map((one) => ({ value: one.slug, label: one.slug }))
                  : [{ value: '', label: 'No attached projects' }]
              }
              onChange={(event) => setForm({ ...form, slug: event.target.value })}
            />
          </Field>
          <FieldRow>
            <Field label="Campaign">
              <TextInput
                value={form.campaign}
                placeholder="sweep-lr-v4"
                onChange={(event) =>
                  setForm({ ...form, campaign: event.target.value })
                }
              />
            </Field>
            <Field label="Exp">
              <TextInput
                value={form.exp}
                placeholder="smoke"
                onChange={(event) => setForm({ ...form, exp: event.target.value })}
              />
            </Field>
          </FieldRow>
          <FieldRow $columns={3}>
            <Field label="Partition">
              <TextInput
                value={form.partition}
                placeholder="gpu-a100"
                onChange={(event) =>
                  setForm({ ...form, partition: event.target.value })
                }
              />
            </Field>
            <Field label="GPUs per task">
              <TextInput
                value={form.gpus}
                placeholder="1"
                onChange={(event) => setForm({ ...form, gpus: event.target.value })}
              />
            </Field>
            <Field label="Walltime">
              <TextInput
                value={form.walltime}
                placeholder="08:00:00"
                onChange={(event) =>
                  setForm({ ...form, walltime: event.target.value })
                }
              />
            </Field>
          </FieldRow>
          <FieldRow>
            <Field label="Scaffold">
              <TextInput value={project?.primitive ?? ''} readOnly />
            </Field>
            <Field label="Command">
              <TextInput
                value={form.command}
                placeholder="optional JOB_COMMAND"
                onChange={(event) =>
                  setForm({ ...form, command: event.target.value })
                }
              />
            </Field>
          </FieldRow>
          <Field label="Manifest path — optional, dispatches a fan-out">
            <TextArea
              rows={3}
              value={form.manifest}
              placeholder="leave empty for a single exp"
              onChange={(event) => setForm({ ...form, manifest: event.target.value })}
            />
          </Field>
          <div style={{ marginTop: 12 }}>
            <Checkbox
              label="Validate only (dry-run)"
              checked={form.dryRun}
              onChange={(event) => setForm({ ...form, dryRun: event.target.checked })}
            />
          </div>
          <ButtonGroup align="right" style={{ marginTop: 16 }}>
            <Button
              Icon={IconChecks}
              disabled={busy || !slug}
              onClick={() => void send(true)}
            >
              Validate
            </Button>
            <Button
              variant="primary"
              Icon={IconPlayerPlay}
              disabled={busy || !slug}
              onClick={() => void send(false)}
            >
              Dispatch
            </Button>
          </ButtonGroup>
          <Hint>
            The controller handles environment bootstrap, fan-out, watch and
            result fetch. This page only posts the run request.
          </Hint>
        </Card>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Card>
            <CardHeader title="Request preview" note="exactly what is posted" />
            <CodeBlock
              caption={`POST /api/v1/projects/${slug || '{slug}'}/runs`}
              maxHeight="260px"
            >
              {JSON.stringify(body, null, 2)}
            </CodeBlock>
          </Card>
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
