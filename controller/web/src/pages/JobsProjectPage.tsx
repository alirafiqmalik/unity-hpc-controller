/** The attached projects, and the form that registers one more. */

import styled from '@emotion/styled';
import { IconFolderPlus } from '@tabler/icons-react';
import { useState } from 'react';
import { useRecoilValue } from 'recoil';

import type {
  AttachBody,
  ProjectRecord,
  SyncPolicy,
} from '../modules/controller/api';
import { APPLICATIONS, countStates, FAIL_STATES, PRIMITIVES } from '../modules/controller/format';
import { jobsState, projectsState } from '../modules/controller/state';
import { usePanels } from '../modules/panels/PanelProvider';
import {
  parseResources,
  ReadinessTags,
  resourceEntries,
  ResourceTags,
} from '../modules/projects/ProjectFacts';
import { useProjectCommands } from '../modules/projects/useProjectCommands';
import { Button, ButtonGroup } from '../ui/components/Button';
import { Card, CardHeader, Grid, Hint } from '../ui/components/Card';
import { EmptyState } from '../ui/components/EmptyState';
import {
  Checkbox,
  Field,
  FieldRow,
  Select,
  TextArea,
  TextInput,
} from '../ui/components/Field';
import { Tag, TagRow } from '../ui/components/Tag';
import { useToast } from '../ui/components/Toast';
import { Page } from '../ui/layout/AppLayout';

const ProjectCard = styled.button`
  background: ${({ theme }) => theme.background.secondary};
  border: 1px solid ${({ theme }) => theme.border.color.light};
  border-radius: ${({ theme }) => theme.border.radius.md};
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.spacing(2)};
  min-width: 0;
  padding: ${({ theme }) => theme.spacing(4)};
  text-align: left;
  transition: ${({ theme }) => theme.animation.clickable};

  &:hover {
    background: ${({ theme }) => theme.background.tertiary};
    border-color: ${({ theme }) => theme.border.color.strong};
  }
`;

const CardTop = styled.div`
  align-items: flex-start;
  display: flex;
  gap: ${({ theme }) => theme.spacing(2)};
  justify-content: space-between;
`;

const Slug = styled.div`
  color: ${({ theme }) => theme.font.color.primary};
  font-size: ${({ theme }) => theme.font.size.lg};
  font-weight: ${({ theme }) => theme.font.weight.semiBold};
  letter-spacing: -0.01em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

const PathLine = styled.div`
  color: ${({ theme }) => theme.font.color.tertiary};
  font-family: ${({ theme }) => theme.font.familyMono};
  font-size: ${({ theme }) => theme.font.size.xxs};
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

const PRIMITIVE_OPTIONS = PRIMITIVES.map((one) => ({ value: one, label: one }));
const APPLICATION_OPTIONS = [
  { value: '', label: 'Resource project' },
  ...APPLICATIONS.map((one) => ({
    value: one.id,
    label: one.runnable ? one.label : `${one.label} (reserved)`,
  })),
];

const SYNC_OPTIONS: { value: SyncPolicy; label: string }[] = [
  { value: 'run_sh', label: 'run_sh — controller may run run.sh sync' },
  { value: 'disabled', label: 'disabled — controller refuses sync' },
];

type AttachForm = {
  path: string;
  slug: string;
  primitive: string;
  application: string;
  remote_dir: string;
  unity_host: string;
  campaign: string;
  sync_policy: SyncPolicy;
  resources: string;
};

const EMPTY_ATTACH: AttachForm = {
  path: '',
  slug: '',
  primitive: 'cpu',
  application: '',
  remote_dir: '',
  unity_host: '',
  campaign: '',
  sync_policy: 'run_sh',
  resources: '',
};

const SectionLabel = styled.div`
  color: ${({ theme }) => theme.font.color.tertiary};
  font-size: ${({ theme }) => theme.font.size.xxs};
  letter-spacing: 0.04em;
  text-transform: uppercase;
`;

export const JobsProjectPage = () => {
  const projects = useRecoilValue(projectsState);
  const jobs = useRecoilValue(jobsState);
  const { openProject } = usePanels();
  const { attachProject, busy } = useProjectCommands();
  const toast = useToast();

  const [form, setForm] = useState<AttachForm>(EMPTY_ATTACH);
  const [more, setMore] = useState(false);
  const [syncPolicyChanged, setSyncPolicyChanged] = useState(false);

  const parsed = parseResources(form.resources);
  const pathMissing = !form.path.trim();
  const attachedPath = projects.find((one) => one.path === form.path.trim());
  const usedSlug = projects.find((one) => one.slug === form.slug.trim());
  const slugConflict = usedSlug && usedSlug.path !== form.path.trim();
  const selectedApp = APPLICATIONS.find((one) => one.id === form.application);
  const reserved = Boolean(selectedApp && !selectedApp.runnable);

  const submit = async () => {
    if (pathMissing) {
      toast('path is required', 'error');
      return;
    }
    if (attachedPath) {
      openProject(attachedPath.slug);
      return;
    }
    if (slugConflict) {
      toast(`${usedSlug.slug} is already attached to another path`, 'error');
      return;
    }
    if (!parsed.ok) {
      toast(parsed.error, 'error');
      return;
    }
    if (reserved) {
      toast(`${selectedApp?.label} is reserved and cannot be submitted`, 'error');
      return;
    }
    const body: AttachBody = {
      path: form.path.trim(),
      primitive: form.primitive,
      application: form.application,
    };
    if (syncPolicyChanged) body.sync_policy = form.sync_policy;
    if (form.slug.trim()) body.slug = form.slug.trim();
    if (form.remote_dir.trim()) body.remote_dir = form.remote_dir.trim();
    if (form.unity_host.trim()) body.unity_host = form.unity_host.trim();
    if (form.campaign.trim()) body.campaign = form.campaign.trim();
    if (Object.keys(parsed.value).length) body.resources = parsed.value;
    const slug = await attachProject(body);
    if (slug === null) return;
    setForm({ ...EMPTY_ATTACH, primitive: form.primitive, application: form.application });
    setSyncPolicyChanged(false);
    if (slug) openProject(slug);
  };

  return (
    <Page>
      {projects.length ? (
        <Grid $min="280px">
          {projects.map((snapshot) => {
            const project: ProjectRecord = snapshot;
            const counts = project.job_counts ?? {};
            const running = countStates(counts, ['RUNNING']);
            const pending = countStates(counts, ['PENDING']);
            const done = countStates(counts, ['COMPLETED']);
            const failed = countStates(counts, FAIL_STATES);
            const mine = jobs.filter((job) => job.slug === project.slug).length;
            return (
              <ProjectCard
                key={project.slug}
                type="button"
                aria-label={`Open project ${project.slug}`}
                onClick={() => openProject(project.slug)}
              >
                <CardTop>
                  <div style={{ minWidth: 0 }}>
                    <TagRow>
                      {project.application ? (
                        <Tag
                          color="blue"
                          text={
                            APPLICATIONS.find((one) => one.id === project.application)?.label ??
                            project.application
                          }
                        />
                      ) : null}
                      <Tag color="purple" text={project.primitive || 'project'} />
                    </TagRow>
                    <Slug style={{ marginTop: 6 }}>{project.slug}</Slug>
                  </div>
                  <Tag
                    color={running ? 'green' : pending ? 'yellow' : 'gray'}
                    text={running ? 'running' : pending ? 'queued' : 'idle'}
                    dot={running || pending ? 'pulsing' : true}
                  />
                </CardTop>
                <PathLine title={project.path}>{project.path}</PathLine>
                <ReadinessTags project={project} />
                <TagRow>
                  <Tag color="green" text={`${running} running`} />
                  <Tag color="yellow" text={`${pending} pending`} />
                  <Tag color="blue" text={`${done} done`} />
                  <Tag color="red" text={`${failed} failed`} />
                </TagRow>
                {resourceEntries(project.resources).length ? (
                  <>
                    <SectionLabel>Declared needs · not enforced</SectionLabel>
                    <ResourceTags resources={project.resources} />
                  </>
                ) : null}
                <PathLine>{mine} ledger rows</PathLine>
              </ProjectCard>
            );
          })}
        </Grid>
      ) : (
        <Card>
          <EmptyState title="No attached projects" Icon={IconFolderPlus}>
            Run <code>/unity-hpc:connect</code> from a coding agent, or attach a
            local path below. The controller reaches a project through its{' '}
            <code>unityHPC/run.sh</code>.
          </EmptyState>
        </Card>
      )}

      <Card>
        <CardHeader
          title="Attach a project from a local path"
          note="the directory must hold unityHPC/"
        />
        <FieldRow $columns={3}>
          <Field label="Project path">
            <TextInput
              value={form.path}
              placeholder="/home/you/my-project"
              aria-required
              onChange={(event) => setForm({ ...form, path: event.target.value })}
            />
          </Field>
          <Field label="Slug">
            <TextInput
              value={form.slug}
              placeholder="optional — derived from the path"
              onChange={(event) => setForm({ ...form, slug: event.target.value })}
            />
          </Field>
          <Field label="Application">
            <Select
              value={form.application}
              options={APPLICATION_OPTIONS}
              onChange={(event) => setForm({ ...form, application: event.target.value })}
            />
          </Field>
        </FieldRow>
        <FieldRow $columns={3}>
          <Field label="Primitive">
            <Select
              value={form.primitive}
              options={PRIMITIVE_OPTIONS}
              onChange={(event) => setForm({ ...form, primitive: event.target.value })}
            />
          </Field>
        </FieldRow>
        <div style={{ marginTop: 12 }}>
          <Checkbox
            label="More settings: remote dir, host, campaign, sync policy, declared resources"
            checked={more}
            onChange={(event) => setMore(event.target.checked)}
          />
        </div>
        {more ? (
          <>
            <FieldRow $columns={3}>
              <Field label="Remote work dir">
                <TextInput
                  value={form.remote_dir}
                  placeholder="optional — .env REMOTE_DIR"
                  onChange={(event) =>
                    setForm({ ...form, remote_dir: event.target.value })
                  }
                />
              </Field>
              <Field label="Unity host">
                <TextInput
                  value={form.unity_host}
                  placeholder="unity"
                  onChange={(event) =>
                    setForm({ ...form, unity_host: event.target.value })
                  }
                />
              </Field>
              <Field label="Default campaign">
                <TextInput
                  value={form.campaign}
                  placeholder="default is today's UTC date"
                  onChange={(event) => setForm({ ...form, campaign: event.target.value })}
                />
              </Field>
            </FieldRow>
            <FieldRow $columns={1}>
              <Field label="Sync policy">
                <Select
                  value={form.sync_policy}
                  options={SYNC_OPTIONS}
                  onChange={(event) => {
                    setForm({ ...form, sync_policy: event.target.value as SyncPolicy });
                    setSyncPolicyChanged(true);
                  }}
                />
              </Field>
            </FieldRow>
            <Field label="Declared resources — JSON object, optional">
              <TextArea
                rows={4}
                value={form.resources}
                placeholder={'{\n  "cpus_per_task": 4,\n  "memory_gb": 16,\n  "gpus_per_task": 1,\n  "walltime": "08:00:00"\n}'}
                aria-invalid={!parsed.ok}
                onChange={(event) => setForm({ ...form, resources: event.target.value })}
              />
            </Field>
            <Hint role={parsed.ok ? undefined : 'alert'}>
              {parsed.ok
                ? 'Resources are a note of what the project needs. The controller stores and shows them; it does not reserve or enforce them.'
                : parsed.error}
            </Hint>
          </>
        ) : null}
        <ButtonGroup align="right" style={{ marginTop: 16 }}>
          <Button
            variant="primary"
            Icon={IconFolderPlus}
            disabled={busy || pathMissing || !parsed.ok || Boolean(slugConflict) || reserved}
            onClick={() => void submit()}
          >
            {attachedPath ? 'Open attached project' : 'Attach project'}
          </Button>
        </ButtonGroup>
        {slugConflict ? (
          <Hint role="alert">
            {usedSlug.slug} is already attached to another path. Open its card
            to change its configuration.
          </Hint>
        ) : null}
        <Hint>
          {reserved
            ? `${selectedApp?.label} is reserved. It has no runner, so you cannot submit it.`
            : form.application === 'llms-agents'
              ? 'An LLMs & Agents project opens as an evaluation workspace: datasets, evaluation runs, traces and assessments.'
              : 'Open a card to configure a declared workflow, review a run, and follow its execution. Project controls remain available in the project header.'}
        </Hint>
      </Card>
    </Page>
  );
};
