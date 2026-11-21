/**
 * The side panel, and the one way to open it.
 *
 * Any page can call `openJob(id, slug)` or `openProject(slug)`. The panel itself is
 * mounted once at the app root, so a page that navigates away does not take
 * the panel with it.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import { useNavigate } from 'react-router-dom';

import { SidePanel } from '../../ui/components/SidePanel';
import { JobPanel } from './JobPanel';
import { ProjectPanel } from './ProjectPanel';

type PanelTarget =
  | { kind: 'job'; jobId: string; slug?: string }
  | { kind: 'project'; slug: string }
  | null;

type PanelContextValue = {
  openJob: (jobId: string, slug?: string) => void;
  openProject: (slug: string) => void;
  openProjectControls: (slug: string) => void;
  closePanel: () => void;
  /** The slug the panel is showing, or null. Pages use it to keep it fresh. */
  openProjectSlug: string | null;
};

const PanelContext = createContext<PanelContextValue>({
  openJob: () => {},
  openProject: () => {},
  openProjectControls: () => {},
  closePanel: () => {},
  openProjectSlug: null,
});

export const usePanels = (): PanelContextValue => useContext(PanelContext);

export const PanelProvider = ({ children }: { children: ReactNode }) => {
  const navigate = useNavigate();
  const [target, setTarget] = useState<PanelTarget>(null);

  const openJob = useCallback((jobId: string, slug?: string) => {
    setTarget({ kind: 'job', jobId, slug });
  }, []);

  const openProject = useCallback((slug: string) => {
    setTarget(null);
    // The index route picks the landing page: Traces for LLMs & Agents, Workflow runner otherwise.
    navigate(`/projects/${encodeURIComponent(slug)}`);
  }, [navigate]);

  const closePanel = useCallback(() => setTarget(null), []);
  const openProjectControls = useCallback((slug: string) => setTarget({ kind: 'project', slug }), []);

  const value = useMemo(
    () => ({
      openJob,
      openProject,
      openProjectControls,
      closePanel,
      openProjectSlug: target?.kind === 'project' ? target.slug : null,
    }),
    [openJob, openProject, openProjectControls, closePanel, target],
  );

  return (
    <PanelContext.Provider value={value}>
      {children}
      <PanelHost target={target} onClose={closePanel} />
    </PanelContext.Provider>
  );
};

const PanelHost = ({
  target,
  onClose,
}: {
  target: PanelTarget;
  onClose: () => void;
}) => {
  if (target?.kind === 'job') {
    return <JobPanel jobId={target.jobId} slug={target.slug} onClose={onClose} />;
  }
  if (target?.kind === 'project') {
    return <ProjectPanel key={target.slug} slug={target.slug} onClose={onClose} />;
  }
  return (
    <SidePanel open={false} onClose={onClose} title="">
      <span />
    </SidePanel>
  );
};
