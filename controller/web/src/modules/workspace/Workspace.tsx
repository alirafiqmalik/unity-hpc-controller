import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { Link, Outlet, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { sectionKeys } from './navigation';
import {
  controllerApi,
  errorText,
  type ProjectRecord,
} from '../controller/api';
import { Button, ButtonGroup } from '../../ui/components/Button';
import {
  Card,
  CardHeader,
  Grid,
  Hint,
  KeyValue,
} from '../../ui/components/Card';
import { Select, TextInput } from '../../ui/components/Field';
import { Tag } from '../../ui/components/Tag';
import { Page } from '../../ui/layout/AppLayout';
import {
  workspaceApi,
  workspaceRequest,
  type Connection,
  type Experiment,
  type Draft,
  type Execution,
} from './api';
import { usePanels } from '../panels/PanelProvider';

const Context = createContext<{
  slug: string;
  connection: Connection | null;
  project: ProjectRecord | null;
  refreshConnection: () => Promise<void>;
}>({
  slug: '',
  connection: null,
  project: null,
  refreshConnection: async () => {},
});
export const useWorkspace = () => useContext(Context);
export const Workspace = () => {
  const { slug = '' } = useParams();
  const [connection, setConnection] = useState<Connection | null>(null);
  const [project, setProject] = useState<ProjectRecord | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    setConnection(null);
    setProject(null);
    Promise.allSettled([workspaceApi.connection(slug), controllerApi.project(slug)])
      .then(([c, p]) => {
        if (!active) return;
        if (c.status === 'fulfilled') setConnection(c.value);
        if (p.status === 'fulfilled') setProject(p.value.project);
        setError([c, p].filter((r): r is PromiseRejectedResult => r.status === 'rejected')
          .map((r) => errorText(r.reason)).join(' · '));
      });
    return () => {
      active = false;
    };
  }, [slug]);
  return (
    <Context.Provider
      value={{
        slug,
        connection,
        project,
        refreshConnection: async () =>
          setConnection(await workspaceApi.connection(slug)),
      }}
    >
      {error ? <ErrorNotice error={`Some project facts are unavailable: ${error}`} /> : null}
      <ScopeNotice />
      <Outlet />
    </Context.Provider>
  );
};
const ScopeNotice = () => {
  const location = useLocation();
  const [search, setSearch] = useSearchParams();
  const section = location.pathname.split('/')[3];
  const allowed = sectionKeys[section] ?? [];
  const unknown = [...search.keys()].filter((key) => !allowed.includes(key));
  if (!unknown.length) return null;
  return <Card role="status">Unknown filters: {unknown.join(', ')}. This scope needs review.
    <Button onClick={() => { const next = new URLSearchParams(search); unknown.forEach((key) => next.delete(key)); setSearch(next); }}>Reset unknown filters</Button>
  </Card>;
};
export const ErrorNotice = ({ error }: { error: string }) =>
  error ? <Card role="alert">{error}</Card> : null;
export const JsonDetails = ({
  title,
  value,
}: {
  title: string;
  value: unknown;
}) => (
  <details>
    <summary>{title}</summary>
    <pre
      style={{
        whiteSpace: 'pre-wrap',
        overflowWrap: 'anywhere',
        fontSize: 12,
        padding: 12,
      }}
    >
      {typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
    </pre>
  </details>
);
export const WorkspacePage = ({
  title,
  actions,
  children,
}: {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
}) => {
  const { connection, project } = useWorkspace();
  const manifest = connection?.manifest;
  return (
    <Page
      title={title}
      subtitle={`${manifest?.application ?? 'Application undeclared'} · ${manifest?.default_primitive ?? project?.primitive ?? 'Primitive undeclared'} · ${manifest?.default_mode ?? 'Mode undeclared'}`}
      actions={actions}
    >
      {children}
    </Page>
  );
};
export const ProjectOverview = () => {
  const { slug, connection, project } = useWorkspace();
  return (
    <WorkspacePage
      title="Overview"
      actions={<Link to={`../experiments`}>Open Experiments</Link>}
    >
      <Card>
        <CardHeader title={slug} />
        <KeyValue label="Project directory">
          {project?.path ?? 'Loading…'}
        </KeyValue>
        <KeyValue label="Connection">
          {connection
            ? connection.valid
              ? 'Ready'
              : 'Needs attention'
            : 'Loading…'}
        </KeyValue>
        <Hint>
          Scientific code, inputs, tests, analysis, and plotting remain in this
          project. Approved execution continues on the controller when this
          browser closes.
        </Hint>
      </Card>
      <Card>
        <CardHeader title="Research question" />
        <p>
          {connection?.manifest?.research_question ||
            'Record the research question in the project connection, or add a question to an experiment.'}
        </p>
      </Card>
      <Card>
        <CardHeader title="Project connection" />
        {connection?.valid ? (
          <p>
            {Object.keys(connection.manifest?.workflows ?? {}).length} declared
            workflows available.
          </p>
        ) : (
          <>
            <p>
              A valid connection is required to create runnable experiments.
            </p>
            <JsonDetails
              title="Connection errors"
              value={connection?.errors ?? []}
            />
          </>
        )}
        <Link to="../settings">Connection details</Link>
      </Card>
    </WorkspacePage>
  );
};
export const ProjectConnection = ({
  section = 'Settings',
}: {
  section?: string;
}) => {
  const { slug, connection, project } = useWorkspace();
  const { openLegacyProject } = usePanels();
  return (
    <WorkspacePage title={section}>
      <Card>
        <CardHeader
          title={
            section === 'Files' ? 'Project-owned files' : 'Connection details'
          }
        />
        <p>
          {section === 'Files'
            ? 'Source and input files remain in the attached project directory.'
            : 'These declarations define the operations and capabilities available to Experiments.'}
        </p>
        <KeyValue label="Project directory">{project?.path}</KeyValue>
        <KeyValue label="Sync policy">
          {project?.sync_policy ?? 'run_sh'}
        </KeyValue>
        <JsonDetails title="Versioned connection" value={connection} />
        {section === 'Settings' ? (
          <Button onClick={() => openLegacyProject(slug)}>
            Legacy project controls
          </Button>
        ) : null}
        <Hint>The broader {section} interface is planned separately.</Hint>
      </Card>
    </WorkspacePage>
  );
};
export const ExperimentLibrary = () => {
  const { slug, connection } = useWorkspace();
  const navigate = useNavigate();
  const [query] = useSearchParams();
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [search, setSearch] = useState('');
  const [archived, setArchived] = useState('active');
  const [workflow, setWorkflow] = useState('');
  const [readiness, setReadiness] = useState('');
  const [newWorkflow, setNewWorkflow] = useState('');
  const [name, setName] = useState('');
  const [creating, setCreating] = useState(query.get('new') === '1');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const workflows = Object.entries(connection?.manifest?.workflows ?? {});
  const composition = (connection?.manifest?.required_features as Record<string, number> | undefined)?.composition === 1;
  const choices = [...workflows.map(([id, w]) => ({ value: id, label: w.title || id })),
    ...(composition ? [{ value: '__composition__', label: 'Compose operations' }] : [])];
  const refresh = () =>
    workspaceApi.experiments(slug).then((r) => setExperiments(r.experiments));
  useEffect(() => {
    workspaceApi
      .experiments(slug)
      .then((r) => setExperiments(r.experiments))
      .catch((e) => setError(errorText(e)));
  }, [slug]);
  const run = async (operation: () => Promise<unknown>) => {
    setBusy(true);
    setError('');
    try {
      await operation();
      await refresh();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const rows = experiments.filter(
    (e) =>
      (archived === 'all' || e.archived === (archived === 'archived')) &&
      (!workflow || e.workflow === workflow) &&
      (!readiness || (e.readiness ?? 'draft') === readiness) &&
      `${e.name} ${e.workflow}`.toLowerCase().includes(search.toLowerCase()),
  );
  return (
    <WorkspacePage
      title="Experiments"
      actions={
        <Button
          variant="primary"
          disabled={!connection?.valid || !choices.length}
          onClick={() => setCreating(true)}
        >
          New experiment
        </Button>
      }
    >
      <ErrorNotice error={error} />
      {!connection?.valid ? (
        <Card>
          <p>Experiments need a valid project connection.</p>
          <Link to="../settings">Inspect connection details</Link>
        </Card>
      ) : null}
      {creating ? (
        <Card>
          <CardHeader title="New experiment" />
          <TextInput
            aria-label="Experiment name"
            placeholder="Experiment name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <Select
            aria-label="Declared workflow"
            value={newWorkflow || choices[0]?.value || ''}
            options={choices}
            onChange={(e) => setNewWorkflow(e.target.value)}
          />
          <ButtonGroup>
            <Button
              disabled={busy || !name.trim()}
              onClick={() =>
                void run(async () => {
                  const e = await workspaceApi.create(
                    slug,
                    newWorkflow || choices[0].value,
                    name.trim(),
                  );
                  navigate(e.id);
                })
              }
            >
              Create experiment
            </Button>
            <Button onClick={() => setCreating(false)}>Cancel</Button>
          </ButtonGroup>
        </Card>
      ) : null}
      <Card>
        <CardHeader title="Experiment library" />
        <Grid>
          <TextInput
            aria-label="Search experiments"
            placeholder="Search experiments"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <Select
            aria-label="Workflow filter"
            value={workflow}
            onChange={(e) => setWorkflow(e.target.value)}
            options={[
              { value: '', label: 'All workflows' },
              ...workflows.map(([id, w]) => ({
                value: id,
                label: w.title || id,
              })),
            ]}
          />
          <Select
            aria-label="Readiness filter"
            value={readiness}
            onChange={(e) => setReadiness(e.target.value)}
            options={[
              { value: '', label: 'All readiness' },
              { value: 'draft', label: 'Draft' },
              { value: 'ready', label: 'Ready' },
              { value: 'needs-input', label: 'Needs input' },
            ]}
          />
          <Select
            aria-label="Archive filter"
            value={archived}
            onChange={(e) => setArchived(e.target.value)}
            options={[
              { value: 'active', label: 'Active' },
              { value: 'archived', label: 'Archived' },
              { value: 'all', label: 'All experiments' },
            ]}
          />
        </Grid>
      </Card>
      {!rows.length ? (
        <Card>
          No experiments match this view. Create an experiment from a declared
          workflow.
        </Card>
      ) : (
        rows.map((e) => (
          <Card key={e.id}>
            <CardHeader
              title={<Link to={e.id}>{e.name}</Link>}
              note={e.workflow}
            />
            <p>
              Configuration: <Tag text={e.readiness ?? 'Draft'} /> · Revision{' '}
              {e.revision}
            </p>
            <p>
              Latest execution:{' '}
              {e.executions?.length ? (
                <Link
                  to={`../runs?execution=${e.executions[e.executions.length - 1]}`}
                >
                  {e.executions[e.executions.length - 1]}
                </Link>
              ) : (
                'None'
              )}
            </p>
            <ButtonGroup>
              <Button onClick={() => navigate(e.id)}>Continue editing</Button>
              <Button
                disabled={busy || e.archived}
                onClick={() =>
                  void run(async () => {
                    await workspaceApi.action(slug, e.id, 'revisions');
                    navigate(e.id);
                  })
                }
              >
                New revision
              </Button>
              <Button
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    const copy = await workspaceApi.action(slug, e.id, 'clone');
                    navigate(copy.id);
                  })
                }
              >
                Clone
              </Button>
              {e.executions?.length ? (
                <Button
                  disabled={busy || e.archived}
                  onClick={() => navigate(`${e.id}?repeat=1`)}
                >
                  Repeat
                </Button>
              ) : null}
              <Button
                disabled={busy}
                onClick={() =>
                  void run(() =>
                    workspaceApi.action(
                      slug,
                      e.id,
                      e.archived ? 'restore' : 'archive',
                    ),
                  )
                }
              >
                {e.archived ? 'Restore' : 'Archive'}
              </Button>
              {!e.executions?.length ? (
                <Button
                  disabled={busy}
                  onClick={() =>
                    void run(() => workspaceApi.remove(slug, e.id))
                  }
                >
                  Delete unused draft
                </Button>
              ) : null}
            </ButtonGroup>
          </Card>
        ))
      )}
    </WorkspacePage>
  );
};

/** Execution links address the frozen revision, never a newer editable draft. */
export const ExperimentRevision = () => {
  const { slug } = useWorkspace();
  const { experimentId = '', revision = '' } = useParams();
  const [snapshot, setSnapshot] = useState<{
    revision: number;
    draft: Draft;
  } | null>(null);
  const [executions, setExecutions] = useState<Execution[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    Promise.all([
      workspaceRequest<{ revisions: { revision: number; draft: Draft }[] }>(
        slug,
        `experiments/${experimentId}/revisions`,
      ),
      workspaceApi.executions(slug),
    ])
      .then(([history, runs]) => {
        if (!active) return;
        const found = history.revisions.find(
          (entry) => String(entry.revision) === revision,
        );
        if (!found) {
          setError('This immutable revision is not recorded.');
          return;
        }
        setSnapshot(found);
        setExecutions(
          runs.executions.filter(
            (run) =>
              run.experiment_id === experimentId &&
              String(run.revision) === revision,
          ),
        );
      })
      .catch((e) => {
        if (active) setError(errorText(e));
      });
    return () => {
      active = false;
    };
  }, [slug, experimentId, revision]);
  return (
    <WorkspacePage title={`Experiment revision ${revision}`}>
      <ErrorNotice error={error} />
      <Card>
        <CardHeader title={snapshot?.draft.name || experimentId} />
        <Hint>
          This dispatched revision is immutable. Later edits are saved
          separately.
        </Hint>
        <JsonDetails
          title="Frozen experiment configuration"
          value={snapshot?.draft}
        />
        <Link
          to={`/projects/${encodeURIComponent(slug)}/experiments/${experimentId}`}
        >
          Open current draft
        </Link>
      </Card>
      {executions.map((run) => (
        <Card key={run.id}>
          <Link
            to={`/projects/${encodeURIComponent(slug)}/runs?execution=${run.id}`}
          >
            Execution {run.id}
          </Link>
          <Link
            to={`/projects/${encodeURIComponent(slug)}/review/${run.plan_id}`}
          >
            Approved source and execution plan
          </Link>
        </Card>
      ))}
    </WorkspacePage>
  );
};
