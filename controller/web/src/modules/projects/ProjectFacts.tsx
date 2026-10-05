/**
 * What a project record says about itself: readiness, declared resources,
 * the experiment catalog and the sync policy.
 *
 * Everything here is read from the project's own files through the
 * controller. Declared resources are what the project asks for, not what a
 * job used, and the controller does not enforce them. Catalog launches use
 * the project's fixed profile through the controller.
 */

import styled from '@emotion/styled';
import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { useRecoilValue } from 'recoil';

import type { ThemeColor } from '../../ui/theme/colors';
import { Button, ButtonGroup } from '../../ui/components/Button';
import { Hint } from '../../ui/components/Card';
import { CodeBlock } from '../../ui/components/CodeBlock';
import { Select, TextInput } from '../../ui/components/Field';
import { Tag, TagRow } from '../../ui/components/Tag';
import type {
  Experiment,
  ProjectRecord,
  ProjectResources,
} from '../controller/api';
import type { Project } from '../controller/types';
import { stateTag } from '../controller/format';
import { jobsState } from '../controller/state';
import { useProjectCommands } from './useProjectCommands';

/** The snapshot keeps projects as `Project`; the extra fields ride along. */
export const asRecord = (project: Project | null | undefined): ProjectRecord | null =>
  (project as ProjectRecord | null | undefined) ?? null;

/** Sync runs `run.sh sync` unless the project turned it off. */
export const syncAllowed = (project: ProjectRecord | null): boolean =>
  Boolean(project) && project?.sync_policy !== 'disabled';

/** Dispatch needs `unityHPC/run.sh`; the controller refuses without it. */
export const canDispatch = (project: ProjectRecord | null): boolean =>
  Boolean(project?.scaffold);

const RESOURCE_LABELS: Record<string, string> = {
  cpus_per_task: 'CPUs per task',
  memory_gb: 'Memory',
  gpus_per_task: 'GPUs per task',
  gpu_type: 'GPU type',
  walltime: 'Walltime',
  nodes: 'Nodes',
  partition: 'Partition',
  notes: 'Notes',
};

const RESOURCE_ORDER = Object.keys(RESOURCE_LABELS);

const humanKey = (key: string): string =>
  RESOURCE_LABELS[key] ?? key.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());

const resourceValue = (key: string, value: unknown): string => {
  if (value === null || value === undefined || value === '') return '—';
  if (key === 'memory_gb' && typeof value === 'number') return `${value} GB`;
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
};

/** Known keys first in a fixed order, then any other key the project set. */
export const resourceEntries = (
  resources: ProjectResources | null | undefined,
): { key: string; label: string; value: string }[] => {
  if (!resources || typeof resources !== 'object' || Array.isArray(resources)) {
    return [];
  }
  const keys = Object.keys(resources).sort((a, b) => {
    const ia = RESOURCE_ORDER.indexOf(a);
    const ib = RESOURCE_ORDER.indexOf(b);
    if (ia === -1 && ib === -1) return a.localeCompare(b);
    if (ia === -1) return 1;
    if (ib === -1) return -1;
    return ia - ib;
  });
  return keys.map((key) => ({
    key,
    label: humanKey(key),
    value: resourceValue(key, resources[key]),
  }));
};

/**
 * Parse the resources editor. Empty text is an empty object; anything else
 * must be a JSON object, because the controller stores it as one.
 */
export const parseResources = (
  text: string,
): { ok: true; value: ProjectResources } | { ok: false; error: string } => {
  if (!text.trim()) return { ok: true, value: {} };
  try {
    const value = JSON.parse(text) as unknown;
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      return { ok: false, error: 'Resources must be a JSON object, like {"gpus_per_task": 1}' };
    }
    return { ok: true, value: value as ProjectResources };
  } catch (error) {
    return { ok: false, error: `Not valid JSON: ${(error as Error).message}` };
  }
};

export const resourcesText = (resources: ProjectResources | null | undefined): string =>
  resources && Object.keys(resources).length ? JSON.stringify(resources, null, 2) : '';

const ResourceGrid = styled.dl`
  display: grid;
  font-size: ${({ theme }) => theme.font.size.sm};
  gap: ${({ theme }) => theme.spacing(1, 3)};
  grid-template-columns: max-content minmax(0, 1fr);
  margin: 0;

  dt {
    color: ${({ theme }) => theme.font.color.secondary};
  }

  dd {
    color: ${({ theme }) => theme.font.color.primary};
    font-family: ${({ theme }) => theme.font.familyMono};
    margin: 0;
    overflow-wrap: anywhere;
  }
`;

const Muted = styled.p`
  color: ${({ theme }) => theme.font.color.tertiary};
  font-size: ${({ theme }) => theme.font.size.sm};
`;

/** A definition list of declared resources, or a line that says there are none. */
export const ResourceList = ({
  resources,
  empty = 'No resources declared.',
}: {
  resources: ProjectResources | null | undefined;
  empty?: ReactNode;
}) => {
  const entries = resourceEntries(resources);
  if (!entries.length) return <Muted>{empty}</Muted>;
  return (
    <ResourceGrid>
      {entries.map((entry) => (
        <div key={entry.key} style={{ display: 'contents' }}>
          <dt>{entry.label}</dt>
          <dd>{entry.value}</dd>
        </div>
      ))}
    </ResourceGrid>
  );
};

/** The same, as a compact row of tags for a card. `notes` is left out. */
export const ResourceTags = ({
  resources,
}: {
  resources: ProjectResources | null | undefined;
}) => {
  const entries = resourceEntries(resources).filter((entry) => entry.key !== 'notes');
  if (!entries.length) return null;
  return (
    <TagRow aria-label="Declared resources">
      {entries.map((entry) => (
        <Tag
          key={entry.key}
          text={`${entry.label}: ${entry.value}`}
          title="Declared by the project. Not enforced by the controller."
        />
      ))}
    </TagRow>
  );
};

/** Scaffold, `.env`, sync policy and catalog size, as tags. */
export const ReadinessTags = ({ project }: { project: ProjectRecord | null }) => {
  const experiments = project?.experiments ?? [];
  const ready = experiments.filter((one) => one.status === 'ready').length;
  return (
    <TagRow>
      <Tag
        color={project?.scaffold ? 'green' : 'red'}
        text={project?.scaffold ? 'run.sh present' : 'no scaffold'}
        title={
          project?.scaffold
            ? 'unityHPC/run.sh exists; the controller can dispatch'
            : 'No unityHPC/run.sh. Run /unity-hpc:connect in the project first.'
        }
        dot
      />
      <Tag
        color={project?.env_present ? 'green' : 'yellow'}
        text={project?.env_present ? '.env present' : 'no .env'}
        title="run.sh and sync.sh read REMOTE_DIR and UNITY_HOST from .env"
      />
      <Tag
        color={syncAllowed(project) ? 'blue' : 'gray'}
        text={syncAllowed(project) ? 'sync on' : 'sync off'}
        title={
          syncAllowed(project)
            ? 'The controller may run run.sh sync for this project'
            : 'sync_policy is disabled; the controller refuses sync'
        }
      />
      {experiments.length ? (
        <Tag
          color="purple"
          text={`${experiments.length} catalogued · ${ready} ready`}
          title="Entries in unityHPC/experiments.json"
        />
      ) : null}
    </TagRow>
  );
};

/** What the Sync button does, or why it is off. */
export const SyncNote = ({ project }: { project: ProjectRecord | null }) =>
  syncAllowed(project) ? (
    <Hint>
      Sync runs <code>run.sh sync</code>, which calls the project&apos;s{' '}
      <code>unityHPC/sync.sh</code>. The generated script mirrors this
      directory to the remote work dir with <code>rsync --delete</code>: remote
      files that are not in the local copy are deleted. It skips{' '}
      <code>.git/</code>, <code>_results/</code>, <code>_slurm/</code> and{' '}
      <code>.unity_state/</code>. A hand-edited <code>sync.sh</code> may do
      something else.
    </Hint>
  ) : (
    <Hint>
      Sync is off: this project sets <code>sync_policy</code> to{' '}
      <code>disabled</code>, and the controller refuses the request. Follow the project&apos;s documented transfer
      workflow for its datasets and results.
    </Hint>
  );

const STATUS_TAG: Record<string, { color: ThemeColor; label: string }> = {
  ready: { color: 'green', label: 'ready' },
  needs_input: { color: 'yellow', label: 'needs input' },
  historical: { color: 'gray', label: 'historical' },
};

const statusTag = (status?: string | null) =>
  STATUS_TAG[status ?? ''] ?? { color: 'gray' as ThemeColor, label: status || 'unknown' };

const CatalogList = styled.ul`
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.spacing(2)};
  list-style: none;
  margin: 0;
  max-height: min(60vh, 600px);
  overflow-y: auto;
  padding: 0;
  padding-right: ${({ theme }) => theme.spacing(1)};
`;

const CatalogItem = styled.li`
  border: 1px solid ${({ theme }) => theme.border.color.light};
  border-radius: ${({ theme }) => theme.border.radius.sm};
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.spacing(2)};
  padding: ${({ theme }) => theme.spacing(3)};
`;

const ItemTop = styled.div`
  align-items: flex-start;
  display: flex;
  gap: ${({ theme }) => theme.spacing(2)};
  justify-content: space-between;
`;

const ItemTitle = styled.div`
  color: ${({ theme }) => theme.font.color.primary};
  font-size: ${({ theme }) => theme.font.size.sm};
  font-weight: ${({ theme }) => theme.font.weight.semiBold};
  min-width: 0;
`;

const ItemId = styled.div`
  color: ${({ theme }) => theme.font.color.tertiary};
  font-family: ${({ theme }) => theme.font.familyMono};
  font-size: ${({ theme }) => theme.font.size.xxs};
  overflow-wrap: anywhere;
`;

const ItemText = styled.p`
  color: ${({ theme }) => theme.font.color.secondary};
  font-size: ${({ theme }) => theme.font.size.xs};
  line-height: 1.5;
  margin: 0;
`;

/** The project-owned catalog, with actions routed through fixed launch profiles. */
export const ExperimentCatalog = ({
  slug,
  experiments,
  error,
  onRun,
}: {
  slug: string;
  experiments: Experiment[] | null | undefined;
  error?: string | null;
  onRun?: () => void;
}) => {
  const list = useMemo(() => experiments ?? [], [experiments]);
  const jobs = useRecoilValue(jobsState);
  const { launchExperiment, busy } = useProjectCommands();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('all');
  const [armed, setArmed] = useState<string | null>(null);
  const [result, setResult] = useState<{ id: string; dry: boolean; output: string } | null>(null);
  useEffect(() => {
    if (!armed) return;
    const timer = window.setTimeout(() => setArmed(null), 10000);
    return () => window.clearTimeout(timer);
  }, [armed]);
  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return list.filter((item) =>
      (status === 'all' || item.status === status) &&
      (!needle || [item.id, item.title, item.description, JSON.stringify(item.resources ?? {})]
        .some((part) => String(part ?? '').toLowerCase().includes(needle))),
    );
  }, [list, search, status]);
  const launch = async (id: string, dry: boolean) => {
    if (!dry && armed !== id) {
      setArmed(id);
      return;
    }
    setArmed(null);
    const answer = await launchExperiment(slug, id, dry);
    if (answer) setResult({ id, dry, output: answer.output || answer.error || '(no output)' });
    if (answer?.ok && !dry) onRun?.();
  };
  if (!list.length) {
    return (
      <Muted role={error ? 'alert' : undefined}>
        {error || <>No catalog. A project lists its experiments in <code>unityHPC/experiments.json</code>.</>}
      </Muted>
    );
  }
  return (
    <>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
        <TextInput
          aria-label="Search experiments"
          placeholder="Search experiments and resources"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setArmed(null);
          }}
          style={{ flex: '1 1 200px' }}
        />
        <Select
          aria-label="Filter experiment status"
          value={status}
          options={[
            { value: 'all', label: 'All statuses' },
            { value: 'ready', label: 'Ready' },
            { value: 'needs_input', label: 'Needs input' },
            { value: 'historical', label: 'Historical' },
          ]}
          onChange={(event) => {
            setStatus(event.target.value);
            setArmed(null);
          }}
          style={{ flex: '0 1 150px' }}
        />
      </div>
      <Hint>{shown.length} of {list.length} experiments</Hint>
      <CatalogList>
        {shown.map((one) => {
          const tag = statusTag(one.status);
          const matchingJobs = one.ledger_exp
            ? jobs.filter((job) => job.slug === slug && job.exp === one.ledger_exp)
            : [];
          const latestJob = [...matchingJobs].sort((a, b) =>
            String(b.submitted_utc || '').localeCompare(String(a.submitted_utc || '')))[0];
          const latestTag = latestJob ? stateTag(latestJob.status) : null;
          return (
            <CatalogItem key={one.id}>
              <ItemTop>
                <div style={{ minWidth: 0 }}>
                  <ItemTitle>{one.title || one.id}</ItemTitle>
                  <ItemId>{one.id}</ItemId>
                </div>
                <Tag color={tag.color} text={tag.label} dot />
              </ItemTop>
              {one.description ? <ItemText>{one.description}</ItemText> : null}
              {one.ledger_exp ? (
                <ItemText>
                  Ledger exp: {one.ledger_exp} · {matchingJobs.length} recorded run{matchingJobs.length === 1 ? '' : 's'}
                  {latestJob && latestTag ? ` · latest #${latestJob.job_id}: ${latestTag.label}` : ''}
                </ItemText>
              ) : null}
              <ResourceTags resources={one.resources} />
              {one.launch ? (
                <>
                  <ItemText>
                    Fixed {one.launch.kind === 'script' ? 'project script' : 'run.sh'} launch
                    {one.status === 'needs_input' ? ' · preview available; input required before run' : ''}
                  </ItemText>
                  <ButtonGroup>
                    <Button
                      size="small"
                      disabled={busy || (one.status !== 'ready' && one.status !== 'needs_input')}
                      onClick={() => void launch(one.id, true)}
                    >
                      Preview
                    </Button>
                    <Button
                      size="small"
                      variant={armed === one.id ? 'danger' : 'primary'}
                      disabled={busy || one.status !== 'ready'}
                      onClick={() => void launch(one.id, false)}
                    >
                      {armed === one.id ? 'Click again to run' : 'Run'}
                    </Button>
                  </ButtonGroup>
                  {result?.id === one.id ? (
                    <CodeBlock caption={result.dry ? 'Preview output' : 'Run output'} maxHeight="220px">
                      {result.output}
                    </CodeBlock>
                  ) : null}
                </>
              ) : <ItemText>No launch profile declared.</ItemText>}
            </CatalogItem>
          );
        })}
      </CatalogList>
      <Hint>Preview and Run use the project&apos;s fixed launch profile. Resource values are declared requirements; review the preview before running.</Hint>
    </>
  );
};
