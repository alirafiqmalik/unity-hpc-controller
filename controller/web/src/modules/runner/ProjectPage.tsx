import type { ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useRecoilValue } from 'recoil';
import { Button } from '../../ui/components/Button';
import { Tag } from '../../ui/components/Tag';
import { Page } from '../../ui/layout/AppLayout';
import { projectsState } from '../controller/state';
import { usePanels } from '../panels/PanelProvider';

export const ProjectPage = ({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) => {
  const { slug = '' } = useParams();
  const project = useRecoilValue(projectsState).find((one) => one.slug === slug);
  const { openProjectControls } = usePanels();
  return <Page title={project?.slug ?? slug} subtitle={title}
    titleExtra={project?.application ? <Tag color="blue" text={project.application === 'llms-agents' ? 'LLMs & Agents' : project.application} /> : undefined}
    actions={<>{actions}<Link to={`/projects/${encodeURIComponent(slug)}/runner`}>Workflow runner</Link>
      <Link to={`/projects/${encodeURIComponent(slug)}/executions`}>Executions</Link>
      <Link to={`/projects/${encodeURIComponent(slug)}/research`}>Research tools</Link>
      <Button size="small" onClick={() => openProjectControls(slug)}>Project controls</Button>
      <Link to={`/projects/${encodeURIComponent(slug)}/docs`}>View docs</Link></>}>
    {children}
  </Page>;
};
