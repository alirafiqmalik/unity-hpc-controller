/**
 * The side panel, and the one way to open it.
 *
 * Any page can call `openJob(id)` or `openProject(slug)`. The panel itself is
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

import { SidePanel } from '../../ui/components/SidePanel';
import { JobPanel } from './JobPanel';
import { ProjectPanel } from './ProjectPanel';

type PanelTarget =
  | { kind: 'job'; jobId: string }
  | { kind: 'project'; slug: string }
  | null;

type PanelContextValue = {
  openJob: (jobId: string) => void;
  openProject: (slug: string) => void;
  closePanel: () => void;
  /** The slug the panel is showing, or null. Pages use it to keep it fresh. */
  openProjectSlug: string | null;
};

const PanelContext = createContext<PanelContextValue>({
  openJob: () => {},
  openProject: () => {},
  closePanel: () => {},
  openProjectSlug: null,
});

export const usePanels = (): PanelContextValue => useContext(PanelContext);

export const PanelProvider = ({ children }: { children: ReactNode }) => {
  const [target, setTarget] = useState<PanelTarget>(null);

  const openJob = useCallback((jobId: string) => {
    setTarget({ kind: 'job', jobId });
  }, []);

  const openProject = useCallback((slug: string) => {
    setTarget({ kind: 'project', slug });
  }, []);

  const closePanel = useCallback(() => setTarget(null), []);

  const value = useMemo(
    () => ({
      openJob,
      openProject,
      closePanel,
      openProjectSlug: target?.kind === 'project' ? target.slug : null,
    }),
    [openJob, openProject, closePanel, target],
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
    return <JobPanel jobId={target.jobId} onClose={onClose} />;
  }
  if (target?.kind === 'project') {
    return <ProjectPanel slug={target.slug} onClose={onClose} />;
  }
  return (
    <SidePanel open={false} onClose={onClose} title="">
      <span />
    </SidePanel>
  );
};
