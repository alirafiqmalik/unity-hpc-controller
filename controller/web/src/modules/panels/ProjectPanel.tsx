/**
 * One project: its readiness, what it declares, its catalog, a single run,
 * its controls, its jobs and its configuration.
 *
 * The panel reads the project detail once when it opens and again after
 * every write, so what it shows is what the controller last answered.
 */

import {
  IconActivity,
  IconChecks,
  IconDownload,
  IconPlayerPlay,
  IconRefresh,
  IconSquareX,
  IconTrash,
} from '@tabler/icons-react';
import { useCallback, useEffect, useState } from 'react';

import { Button, ButtonGroup } from '../../ui/components/Button';
import { Card, CardHeader, Hint } from '../../ui/components/Card';
import { CodeBlock } from '../../ui/components/CodeBlock';
import { EmptyState } from '../../ui/components/EmptyState';
import {
  Field,
  FieldRow,
  Select,
  TextArea,
  TextInput,
} from '../../ui/components/Field';
import { SidePanel } from '../../ui/components/SidePanel';
import {
  MonoCell,
  Table,
  TableEmptyRow,
  TableScroller,
  THead,
  TRow,
} from '../../ui/components/Table';
import { Tag } from '../../ui/components/Tag';
import { useToast } from '../../ui/components/Toast';
import {
  controllerApi,
  errorText,
  type FetchResult,
  type ProjectRecord,
  type RunResult,
  type SyncPolicy,
} from '../controller/api';
import { PRIMITIVES, stateTag } from '../controller/format';
import {
  canDispatch,
  ExperimentCatalog,
  parseResources,
  ReadinessTags,
  ResourceList,
  resourcesText,
  syncAllowed,
  SyncNote,
} from '../projects/ProjectFacts';
import { useProjectCommands } from '../projects/useProjectCommands';
import { usePanels } from './PanelProvider';

const PRIMITIVE_OPTIONS = PRIMITIVES.map((one) => ({ value: one, label: one }));

const SYNC_OPTIONS: { value: SyncPolicy; label: string }[] = [
  { value: 'run_sh', label: 'run_sh — controller may run run.sh sync' },
  { value: 'disabled', label: 'disabled — controller refuses sync' },
];

type RunForm = {
  exp: string;
  campaign: string;
  partition: string;
  walltime: string;
  command: string;
};

const EMPTY_RUN: RunForm = {
  exp: '',
  campaign: '',
  partition: '',
  walltime: '',
  command: '',
};

type ConfigForm = {
  primitive: string;
  campaign: string;
  remote_dir: string;
  unity_host: string;
  sync_policy: SyncPolicy;
  resources: string;
};

/** A two-click action: the first click arms it, the second runs it. */
type Armed = 'run' | 'stop' | 'sync' | 'detach' | null;

export const ProjectPanel = ({
  slug,
  onClose,
}: {
  slug: string;
  onClose: () => void;
}) => {
  const toast = useToast();
  const { openJob } = usePanels();
  const { dispatch, patchProject, detachProject, runCommand, busy } =
    useProjectCommands();

  const [project, setProject] = useState<ProjectRecord | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [config, setConfig] = useState<ConfigForm>({
    primitive: 'cpu',
    campaign: '',
    remote_dir: '',
    unity_host: 'unity',
    sync_policy: 'run_sh',
    resources: '',
  });
  const [run, setRun] = useState<RunForm>(EMPTY_RUN);
  const [lastRun, setLastRun] = useState<{ dry: boolean; answer: RunResult } | null>(
    null,
  );
  const [armed, setArmed] = useState<Armed>(null);
  const [pendingCommand, setPendingCommand] = useState<string | null>(null);
  const [fetchResult, setFetchResult] = useState<FetchResult | null>(null);
  const [selectedCampaign, setSelectedCampaign] = useState('');
  const campaigns = project?.campaigns ?? [];
  const controlCampaign = campaigns.includes(selectedCampaign)
    ? selectedCampaign
    : project?.campaign && campaigns.includes(project.campaign)
      ? project.campaign
      : campaigns[0] ?? '';

  const load = useCallback(async (resetConfig = false) => {
    try {
      const answer = await controllerApi.project(slug);
      let record = answer.project;
      // An older detail answer may leave the catalog out; ask its own route.
      if (record.experiments === undefined) {
        try {
          const catalog = await controllerApi.experiments(slug);
          record = { ...record, experiments: catalog.experiments };
        } catch {
          // No catalog route on this controller. The panel shows "no catalog".
        }
      }
      setProject(record);
      if (resetConfig) {
        setConfig({
          primitive: record.primitive || 'cpu',
          campaign: record.campaign || '',
          remote_dir: record.remote_dir || '',
          unity_host: record.unity_host || 'unity',
          sync_policy: record.sync_policy === 'disabled' ? 'disabled' : 'run_sh',
          resources: resourcesText(record.resources),
        });
      }
      setLoadError(null);
    } catch (error) {
      setLoadError(errorText(error));
    }
  }, [slug]);

  useEffect(() => {
    void load(true);
    setArmed(null);
    setRun(EMPTY_RUN);
    setLastRun(null);
  }, [load]);

  useEffect(() => setArmed(null), [run]);
  useEffect(() => {
    if (!armed) return;
    const timer = window.setTimeout(() => setArmed(null), 10000);
    return () => window.clearTimeout(timer);
  }, [armed]);

  const parsedResources = parseResources(config.resources);

  const saveConfig = async () => {
    if (!parsedResources.ok) {
      toast(parsedResources.error, 'error');
      return;
    }
    const { resources: _text, ...rest } = config;
    if (await patchProject(slug, { ...rest, resources: parsedResources.value })) {
      await load(true);
    }
  };

  const dispatchRun = async (dry: boolean) => {
    const exp = run.exp.trim();
    if (!exp) {
      toast('exp is required', 'error');
      return;
    }
    if (!dry && armed !== 'run') {
      setArmed('run');
      return;
    }
    setArmed(null);
    const overrides: Record<string, string> = {};
    if (run.command.trim()) overrides.JOB_COMMAND = run.command.trim();
    if (run.walltime.trim()) overrides.WALLTIME = run.walltime.trim();
    if (run.partition.trim()) overrides.SLURM_PARTITION = run.partition.trim();
    const answer = await dispatch(slug, {
      exp,
      ...(run.campaign.trim() ? { campaign: run.campaign.trim() } : {}),
      dry_run: dry,
      ...(Object.keys(overrides).length ? { overrides } : {}),
    });
    if (answer) setLastRun({ dry, answer });
    await load();
  };

  const command = async (name: string, note: string) => {
    setArmed(null);
    setPendingCommand(name);
    if (name === 'fetch') setFetchResult(null);
    try {
      const body = (name === 'stop' || name === 'fetch' || name === 'status') && controlCampaign
        ? { campaign: controlCampaign }
        : {};
      const answer = await runCommand(slug, name, body, note);
      if (name === 'fetch') setFetchResult(answer);
      await load();
    } finally {
      setPendingCommand(null);
    }
  };

  const confirmThen = (what: Exclude<Armed, null>, action: () => void) => {
    if (armed !== what) {
      setArmed(what);
      return;
    }
    action();
  };

  const detach = async () => {
    setArmed(null);
    if (await detachProject(slug)) onClose();
  };

  if (loadError) {
    return (
      <SidePanel open onClose={onClose} title={slug} subtitle="project">
        <EmptyState title="The controller could not read this project">
          {loadError}
        </EmptyState>
      </SidePanel>
    );
  }

  const jobs = project?.jobs ?? [];
  const ready = canDispatch(project);
  const syncOn = syncAllowed(project);
  const expMissing = !run.exp.trim();
  const campaign = project?.campaign || "today's UTC date";

  return (
    <SidePanel open onClose={onClose} title={slug} subtitle={project?.path ?? ''}>
      {project ? <ReadinessTags project={project} /> : null}
      {project && !ready ? (
        <Hint role="status">
          This project has no <code>unityHPC/run.sh</code>, so dispatch, stop,
          fetch and sync are off. Run <code>/unity-hpc:connect</code> in the
          project, then reopen this panel.
        </Hint>
      ) : null}

      <Card>
        <CardHeader title="Declared resources" note="declared by the project · not enforced" />
        <ResourceList
          resources={project?.resources}
          empty="This project declares no resources. Add them under Configure."
        />
      </Card>

      <Card>
        <CardHeader
          title="Experiment catalog"
          note={
            project?.experiments?.length
              ? `${project.experiments.length} in unityHPC/experiments.json`
              : undefined
          }
        />
        <ExperimentCatalog
          slug={slug}
          experiments={project?.experiments}
          error={project?.experiments_error}
          onRun={() => void load()}
        />
      </Card>

      <Card>
        <CardHeader title="Run" note="one exp through run.sh run" />
        <FieldRow>
          <Field label="Exp">
            <TextInput
              value={run.exp}
              placeholder="smoke"
              aria-required
              onChange={(event) => setRun({ ...run, exp: event.target.value })}
            />
          </Field>
          <Field label="Campaign">
            <TextInput
              value={run.campaign}
              placeholder={`default: ${campaign}`}
              onChange={(event) => setRun({ ...run, campaign: event.target.value })}
            />
          </Field>
        </FieldRow>
        <FieldRow $columns={3}>
          <Field label="Partition">
            <TextInput
              value={run.partition}
              placeholder="optional"
              onChange={(event) => setRun({ ...run, partition: event.target.value })}
            />
          </Field>
          <Field label="Walltime">
            <TextInput
              value={run.walltime}
              placeholder="optional"
              onChange={(event) => setRun({ ...run, walltime: event.target.value })}
            />
          </Field>
          <Field label="Command">
            <TextInput
              value={run.command}
              placeholder="optional"
              onChange={(event) => setRun({ ...run, command: event.target.value })}
            />
          </Field>
        </FieldRow>
        <Hint>
          Partition, walltime and command go as <code>SLURM_PARTITION</code>,{' '}
          <code>WALLTIME</code> and <code>JOB_COMMAND</code> overrides. run.sh
          refuses a key it does not list in <code>UNITY_OVERRIDABLE</code>.
          Validate calls <code>run.sh run --dry-run</code>; nothing is submitted.
        </Hint>
        <ButtonGroup align="right" style={{ marginTop: 16 }}>
          <Button
            size="small"
            Icon={IconChecks}
            disabled={busy || !ready || expMissing}
            onClick={() => void dispatchRun(true)}
          >
            Validate
          </Button>
          <Button
            variant={armed === 'run' ? 'danger' : 'primary'}
            size="small"
            Icon={IconPlayerPlay}
            disabled={busy || !ready || expMissing}
            onClick={() => void dispatchRun(false)}
          >
            {armed === 'run' ? 'Click again to dispatch' : 'Dispatch'}
          </Button>
        </ButtonGroup>
        {lastRun ? (
          <div style={{ marginTop: 12 }} aria-live="polite">
            <CodeBlock
              caption={`${lastRun.dry ? 'validate' : 'dispatch'} · ${
                lastRun.answer.ok ? 'ok' : 'failed'
              }${
                lastRun.dry && lastRun.answer.ok && !lastRun.answer.dry_run
                  ? ' · run.sh printed no [dry-run] marker'
                  : ''
              }`}
              maxHeight="220px"
            >
              {lastRun.answer.output || lastRun.answer.error || '(no output)'}
            </CodeBlock>
          </div>
        ) : null}
      </Card>

      <Card>
        <CardHeader title="Control" />
        {campaigns.length ? (
          <Field label="Campaign for status, stop and fetch">
            <Select
              value={controlCampaign}
              options={campaigns.map((one) => ({ value: one, label: one }))}
              onChange={(event) => {
                setSelectedCampaign(event.target.value);
                setArmed(null);
              }}
            />
          </Field>
        ) : null}
        <ButtonGroup>
          <Button
            size="small"
            Icon={IconActivity}
            disabled={busy || !ready}
            onClick={() => void command('status', 'Status')}
            title="run.sh status: ask sacct for the ledger's job states"
          >
            Refresh status
          </Button>
          <Button
            size="small"
            Icon={IconSquareX}
            variant={armed === 'stop' ? 'danger' : 'secondary'}
            disabled={busy || !ready || !controlCampaign}
            onClick={() => confirmThen('stop', () => void command('stop', 'Stop sent'))}
          >
            {armed === 'stop' ? 'Click again to stop' : 'Stop campaign'}
          </Button>
          <Button
            size="small"
            Icon={IconDownload}
            disabled={busy || !ready}
            onClick={() => void command('fetch', 'Fetch finished')}
          >
            {pendingCommand === 'fetch'
              ? 'Fetching…'
              : project?.artifact_fetch ? 'Fetch logs + artifacts' : 'Fetch results'}
          </Button>
          <Button
            size="small"
            Icon={IconRefresh}
            variant={armed === 'sync' ? 'danger' : 'secondary'}
            disabled={busy || !ready || !syncOn}
            aria-describedby="project-sync-note"
            onClick={() => confirmThen('sync', () => void command('sync', 'Sync done'))}
          >
            {armed === 'sync' ? 'Click again to sync' : 'Sync'}
          </Button>
        </ButtonGroup>
        {armed === 'stop' ? (
          <Hint role="alert">
            Stop runs <code>run.sh cancel</code> for the campaign{' '}
            <code>{controlCampaign}</code>: every live job in that ledger is cancelled.
            To cancel one job, open it from the table below.
          </Hint>
        ) : null}
        {pendingCommand === 'fetch' ? (
          <Hint role="status">
            Fetching scheduler logs{project?.artifact_fetch ? ' and project artifacts' : ''}.
            The request remains open until both steps finish.
          </Hint>
        ) : null}
        {fetchResult ? (
          <div aria-live="polite">
            {fetchResult.logs ? (
              <CodeBlock caption={`Scheduler logs · ${fetchResult.logs.ok ? 'ok' : 'failed'}`} maxHeight="180px">
                {fetchResult.logs.output || fetchResult.logs.error || '(no output)'}
              </CodeBlock>
            ) : null}
            {fetchResult.artifacts ? (
              <CodeBlock caption={`Project artifacts · ${fetchResult.artifacts.ok ? 'ok' : 'failed'}`} maxHeight="180px">
                {fetchResult.artifacts.output || fetchResult.artifacts.error || '(no output)'}
              </CodeBlock>
            ) : null}
            {!fetchResult.logs && !fetchResult.artifacts ? (
              <CodeBlock caption={`Fetch · ${fetchResult.ok ? 'ok' : 'failed'}`} maxHeight="180px">
                {fetchResult.output || fetchResult.error || '(no output)'}
              </CodeBlock>
            ) : null}
          </div>
        ) : null}
        <div id="project-sync-note">
          <SyncNote project={project} />
        </div>
      </Card>

      <Card>
        <CardHeader
          title="Monitor"
          note={jobs.length ? `${jobs.length} newest rows` : undefined}
        />
        <TableScroller>
          <Table>
            <THead>
              <tr>
                <th>Job</th>
                <th>Exp</th>
                <th>Status</th>
                <th>Partition</th>
              </tr>
            </THead>
            <tbody>
              {jobs.length ? (
                [...jobs].reverse().map((job) => {
                  const tag = stateTag(job.status);
                  const open = () => openJob(String(job.job_id), slug);
                  return (
                    <TRow
                      key={job.job_id}
                      $clickable
                      tabIndex={0}
                      aria-label={`Open job ${job.job_id}`}
                      onClick={open}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault();
                          open();
                        }
                      }}
                    >
                      <MonoCell>{job.job_id}</MonoCell>
                      <MonoCell>{job.exp || '—'}</MonoCell>
                      <td>
                        <Tag
                          color={tag.color}
                          text={tag.label}
                          dot={tag.live ? 'pulsing' : true}
                        />
                      </td>
                      <td>{job.partition || '—'}</td>
                    </TRow>
                  );
                })
              ) : (
                <TableEmptyRow colSpan={4}>No jobs in this ledger yet</TableEmptyRow>
              )}
            </tbody>
          </Table>
        </TableScroller>
      </Card>

      <Card>
        <CardHeader title="Configure" />
        <FieldRow>
          <Field label="Primitive">
            {config.primitive === 'ml' ? <TextInput readOnly value="ml (legacy coordinated execution)" aria-label="Legacy primitive" /> : <Select
              value={config.primitive}
              options={PRIMITIVE_OPTIONS}
              onChange={(event) =>
                setConfig({ ...config, primitive: event.target.value })
              }
            />}
          </Field>
          <Field label="Default campaign">
            <TextInput
              value={config.campaign}
              placeholder="default is today's UTC date"
              onChange={(event) =>
                setConfig({ ...config, campaign: event.target.value })
              }
            />
          </Field>
        </FieldRow>
        <FieldRow>
          <Field label="Remote work dir">
            <TextInput
              value={config.remote_dir}
              onChange={(event) =>
                setConfig({ ...config, remote_dir: event.target.value })
              }
            />
          </Field>
          <Field label="Unity host">
            <TextInput
              value={config.unity_host}
              onChange={(event) =>
                setConfig({ ...config, unity_host: event.target.value })
              }
            />
          </Field>
        </FieldRow>
        <FieldRow $columns={1}>
          <Field label="Sync policy">
            <Select
              value={config.sync_policy}
              options={SYNC_OPTIONS}
              onChange={(event) =>
                setConfig({ ...config, sync_policy: event.target.value as SyncPolicy })
              }
            />
          </Field>
        </FieldRow>
        <FieldRow $columns={1}>
          <Field label="Declared resources — JSON object">
            <TextArea
              rows={5}
              value={config.resources}
              placeholder={'{\n  "cpus_per_task": 4,\n  "memory_gb": 16,\n  "gpus_per_task": 1,\n  "gpu_type": "a100",\n  "walltime": "08:00:00"\n}'}
              aria-invalid={!parsedResources.ok}
              onChange={(event) =>
                setConfig({ ...config, resources: event.target.value })
              }
            />
          </Field>
        </FieldRow>
        <Hint role={parsedResources.ok ? undefined : 'alert'}>
          {parsedResources.ok
            ? 'Resources are a declaration. The controller stores and shows them; it does not pass them to Slurm or enforce them. Empty clears them.'
            : parsedResources.error}
        </Hint>
        <ButtonGroup align="right" style={{ marginTop: 16 }}>
          <Button
            variant="primary"
            size="small"
            disabled={busy || !project || !parsedResources.ok}
            onClick={() => void saveConfig()}
          >
            Save
          </Button>
        </ButtonGroup>
      </Card>

      <ButtonGroup>
        <Button
          variant="danger"
          size="small"
          Icon={IconTrash}
          disabled={busy}
          onClick={() => confirmThen('detach', () => void detach())}
        >
          {armed === 'detach' ? 'Click again to detach' : 'Detach'}
        </Button>
      </ButtonGroup>
      <Hint>
        Detach removes the project from the controller only. The project
        directory, its ledger and remote data stay as they are.
      </Hint>
    </SidePanel>
  );
};
