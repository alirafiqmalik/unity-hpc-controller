/** One project: configure it, dispatch from it, control it, watch its jobs. */

import {
  IconDownload,
  IconPlayerPlay,
  IconRefresh,
  IconSquareX,
  IconTrash,
} from '@tabler/icons-react';
import { useCallback, useEffect, useState } from 'react';

import { Button, ButtonGroup } from '../../ui/components/Button';
import { Card, CardHeader } from '../../ui/components/Card';
import { EmptyState } from '../../ui/components/EmptyState';
import {
  Checkbox,
  Field,
  FieldRow,
  Select,
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
import { Tag, TagRow } from '../../ui/components/Tag';
import { useToast } from '../../ui/components/Toast';
import { controllerApi, errorText } from '../controller/api';
import { PRIMITIVES, stateTag } from '../controller/format';
import type { Project } from '../controller/types';
import { useProjectCommands } from '../projects/useProjectCommands';
import { usePanels } from './PanelProvider';

const PRIMITIVE_OPTIONS = PRIMITIVES.map((one) => ({ value: one, label: one }));

type RunForm = {
  exp: string;
  campaign: string;
  partition: string;
  walltime: string;
  command: string;
  dryRun: boolean;
};

const EMPTY_RUN: RunForm = {
  exp: '',
  campaign: '',
  partition: '',
  walltime: '',
  command: '',
  dryRun: false,
};

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

  const [project, setProject] = useState<Project | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [config, setConfig] = useState({
    primitive: 'cpu',
    campaign: '',
    remote_dir: '',
    unity_host: 'unity',
  });
  const [run, setRun] = useState<RunForm>(EMPTY_RUN);
  const [confirmDetach, setConfirmDetach] = useState(false);

  const load = useCallback(async () => {
    try {
      const answer = await controllerApi.project(slug);
      const record = answer.project;
      setProject(record);
      setConfig({
        primitive: record.primitive || 'cpu',
        campaign: record.campaign || '',
        remote_dir: record.remote_dir || '',
        unity_host: record.unity_host || 'unity',
      });
      setLoadError(null);
    } catch (error) {
      setLoadError(errorText(error));
    }
  }, [slug]);

  useEffect(() => {
    void load();
    setConfirmDetach(false);
    setRun(EMPTY_RUN);
  }, [load]);

  const saveConfig = async () => {
    if (await patchProject(slug, config)) await load();
  };

  const dispatchRun = async (forceDry: boolean) => {
    if (!run.exp.trim()) {
      toast('exp is required', 'error');
      return;
    }
    const overrides: Record<string, string> = {};
    if (run.command.trim()) overrides.JOB_COMMAND = run.command.trim();
    if (run.walltime.trim()) overrides.WALLTIME = run.walltime.trim();
    if (run.partition.trim()) overrides.SLURM_PARTITION = run.partition.trim();
    await dispatch(slug, {
      exp: run.exp.trim(),
      ...(run.campaign.trim() ? { campaign: run.campaign.trim() } : {}),
      dry_run: forceDry || run.dryRun,
      ...(Object.keys(overrides).length ? { overrides } : {}),
    });
    await load();
  };

  const command = async (name: string, note: string) => {
    await runCommand(slug, name, {}, note);
    await load();
  };

  const detach = async () => {
    if (!confirmDetach) {
      setConfirmDetach(true);
      return;
    }
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

  return (
    <SidePanel open onClose={onClose} title={slug} subtitle={project?.path ?? ''}>
      <TagRow>
        <Tag color="purple" text={project?.primitive || '—'} />
        <Tag
          color={project?.scaffold ? 'green' : 'gray'}
          text={project?.scaffold ? 'scaffold ready' : 'no scaffold'}
          dot
        />
        <Tag
          color={project?.env_present ? 'green' : 'yellow'}
          text={project?.env_present ? '.env present' : 'no .env'}
        />
      </TagRow>

      <Card>
        <CardHeader title="Configure" />
        <FieldRow>
          <Field label="Primitive">
            <Select
              value={config.primitive}
              options={PRIMITIVE_OPTIONS}
              onChange={(event) =>
                setConfig({ ...config, primitive: event.target.value })
              }
            />
          </Field>
          <Field label="Campaign">
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
        <ButtonGroup align="right" style={{ marginTop: 16 }}>
          <Button variant="primary" size="small" disabled={busy} onClick={saveConfig}>
            Save
          </Button>
        </ButtonGroup>
      </Card>

      <Card>
        <CardHeader title="Run" />
        <FieldRow>
          <Field label="Exp">
            <TextInput
              value={run.exp}
              placeholder="smoke"
              onChange={(event) => setRun({ ...run, exp: event.target.value })}
            />
          </Field>
          <Field label="Campaign">
            <TextInput
              value={run.campaign}
              placeholder="optional"
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
        <div style={{ marginTop: 12 }}>
          <Checkbox
            label="Validate only (dry-run)"
            checked={run.dryRun}
            onChange={(event) => setRun({ ...run, dryRun: event.target.checked })}
          />
        </div>
        <ButtonGroup align="right" style={{ marginTop: 16 }}>
          <Button size="small" disabled={busy} onClick={() => void dispatchRun(true)}>
            Validate
          </Button>
          <Button
            variant="primary"
            size="small"
            Icon={IconPlayerPlay}
            disabled={busy}
            onClick={() => void dispatchRun(false)}
          >
            Dispatch
          </Button>
        </ButtonGroup>
      </Card>

      <Card>
        <CardHeader title="Control" />
        <ButtonGroup>
          <Button
            size="small"
            Icon={IconSquareX}
            disabled={busy}
            onClick={() => void command('stop', 'Stop sent')}
          >
            Stop
          </Button>
          <Button
            size="small"
            Icon={IconDownload}
            disabled={busy}
            onClick={() => void command('fetch', 'Fetch started')}
          >
            Fetch
          </Button>
          <Button
            size="small"
            Icon={IconRefresh}
            disabled={busy}
            onClick={() => void command('sync', 'Sync started')}
          >
            Sync
          </Button>
        </ButtonGroup>
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
                  return (
                    <TRow
                      key={job.job_id}
                      $clickable
                      onClick={() => openJob(String(job.job_id))}
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

      <ButtonGroup>
        <Button
          variant="danger"
          size="small"
          Icon={IconTrash}
          disabled={busy}
          onClick={() => void detach()}
        >
          {confirmDetach ? 'Click again to detach' : 'Detach'}
        </Button>
      </ButtonGroup>
    </SidePanel>
  );
};
