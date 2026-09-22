/** The attached projects, and the form that registers one more. */

import styled from '@emotion/styled';
import { IconFolderPlus } from '@tabler/icons-react';
import { useState } from 'react';
import { useRecoilValue } from 'recoil';

import { countStates, FAIL_STATES, PRIMITIVES } from '../modules/controller/format';
import { jobsState, projectsState } from '../modules/controller/state';
import { usePanels } from '../modules/panels/PanelProvider';
import { useProjectCommands } from '../modules/projects/useProjectCommands';
import { Button, ButtonGroup } from '../ui/components/Button';
import { Card, CardHeader, Grid, Hint } from '../ui/components/Card';
import { EmptyState } from '../ui/components/EmptyState';
import { Field, FieldRow, Select, TextInput } from '../ui/components/Field';
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

export const JobsProjectPage = () => {
  const projects = useRecoilValue(projectsState);
  const jobs = useRecoilValue(jobsState);
  const { openProject } = usePanels();
  const { attachProject, busy } = useProjectCommands();
  const toast = useToast();

  const [form, setForm] = useState({ path: '', slug: '', primitive: 'cpu' });

  const submit = async () => {
    if (!form.path.trim()) {
      toast('path is required', 'error');
      return;
    }
    const ok = await attachProject({
      path: form.path.trim(),
      ...(form.slug.trim() ? { slug: form.slug.trim() } : {}),
      primitive: form.primitive,
    });
    if (ok) setForm({ path: '', slug: '', primitive: form.primitive });
  };

  return (
    <Page>
      {projects.length ? (
        <Grid $min="280px">
          {projects.map((project) => {
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
                onClick={() => openProject(project.slug)}
              >
                <CardTop>
                  <div style={{ minWidth: 0 }}>
                    <Tag color="purple" text={project.primitive || 'project'} />
                    <Slug style={{ marginTop: 6 }}>{project.slug}</Slug>
                  </div>
                  <Tag
                    color={running ? 'green' : pending ? 'yellow' : 'gray'}
                    text={running ? 'running' : pending ? 'queued' : 'idle'}
                    dot={running || pending ? 'pulsing' : true}
                  />
                </CardTop>
                <PathLine title={project.path}>{project.path}</PathLine>
                <TagRow>
                  <Tag color="green" text={`${running} running`} />
                  <Tag color="yellow" text={`${pending} pending`} />
                  <Tag color="blue" text={`${done} done`} />
                  <Tag color="red" text={`${failed} failed`} />
                </TagRow>
                <PathLine>
                  {mine} ledger rows ·{' '}
                  {project.scaffold ? 'scaffold ready' : 'no scaffold'}
                </PathLine>
              </ProjectCard>
            );
          })}
        </Grid>
      ) : (
        <Card>
          <EmptyState title="No attached projects" Icon={IconFolderPlus}>
            Run <code>/unity-hpc:connect</code> from a coding agent, or register a
            path below. The controller reaches a project through its{' '}
            <code>unityHPC/run.sh</code>.
          </EmptyState>
        </Card>
      )}

      <Card>
        <CardHeader
          title="Register a path on this machine"
          note="the directory must hold unityHPC/"
        />
        <FieldRow $columns={3}>
          <Field label="Project path">
            <TextInput
              value={form.path}
              placeholder="/home/you/phd-gnn-scaling"
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
          <Field label="Primitive">
            <Select
              value={form.primitive}
              options={PRIMITIVE_OPTIONS}
              onChange={(event) => setForm({ ...form, primitive: event.target.value })}
            />
          </Field>
        </FieldRow>
        <ButtonGroup align="right" style={{ marginTop: 16 }}>
          <Button
            variant="primary"
            Icon={IconFolderPlus}
            disabled={busy}
            onClick={() => void submit()}
          >
            Register project
          </Button>
        </ButtonGroup>
        <Hint>
          Click a card to configure the project, dispatch a run, stop it, fetch
          results, or detach it.
        </Hint>
      </Card>
    </Page>
  );
};
