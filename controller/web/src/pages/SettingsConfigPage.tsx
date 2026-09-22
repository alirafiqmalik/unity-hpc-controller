/**
 * Config: where telemetry comes from, how the controller reaches the cluster,
 * and what this controller currently is.
 *
 * The source line says which layer answered — the saved setting, the
 * environment, or a project's `.env` — because "not configured" and
 * "configured somewhere else" need different actions.
 */

import { IconDownload, IconLock, IconPlugConnected } from '@tabler/icons-react';
import { useEffect, useState } from 'react';
import { useRecoilValue } from 'recoil';

import { controllerApi, errorText } from '../modules/controller/api';
import { ago, fmtBytes } from '../modules/controller/format';
import {
  clusterState,
  healthState,
  jobsState,
  projectsState,
  syncErrorState,
  usageState,
} from '../modules/controller/state';
import { useTelemetry } from '../modules/telemetry/TelemetryProvider';
import { Button, ButtonGroup } from '../ui/components/Button';
import { Card, CardHeader, Grid, Hint, KeyValue } from '../ui/components/Card';
import { Field, InlineRow, TextInput } from '../ui/components/Field';
import { Modal } from '../ui/components/SidePanel';
import { Tag } from '../ui/components/Tag';
import { useToast } from '../ui/components/Toast';
import { Page } from '../ui/layout/AppLayout';

/** How old a store file is, and how big. */
const storeLine = (record?: {
  present: boolean;
  mtime_utc?: string | null;
  size_bytes?: number | null;
}): string =>
  record?.present
    ? `${ago(record.mtime_utc)} · ${fmtBytes(record.size_bytes)}`
    : 'absent';

export const SettingsConfigPage = () => {
  const { telemetry, error, reload, save, busy } = useTelemetry();
  const toast = useToast();
  const cluster = useRecoilValue(clusterState);
  const health = useRecoilValue(healthState);
  const jobs = useRecoilValue(jobsState);
  const projects = useRecoilValue(projectsState);
  const syncError = useRecoilValue(syncErrorState);
  const usage = useRecoilValue(usageState);

  const [source, setSource] = useState('');
  const [sshHost, setSshHost] = useState('unity');
  const [sshIdentity, setSshIdentity] = useState('');
  const [sshState, setSshState] = useState<string>('—');
  const [passOpen, setPassOpen] = useState(false);
  const [passphrase, setPassphrase] = useState('');
  const [passError, setPassError] = useState('');

  // Fill the fields from the server once, and never while they are focused.
  useEffect(() => {
    if (!telemetry) return;
    const active = document.activeElement;
    const src = telemetry.source;
    if (active?.id !== 'telemetry-source') {
      setSource(src.origin === 'settings' ? (src.value ?? '') : '');
    }
    if (active?.id !== 'ssh-host') setSshHost(telemetry.ssh.host || 'unity');
    if (active?.id !== 'ssh-identity') setSshIdentity(telemetry.ssh.identity || '');
    if (telemetry.ssh.last_probe) {
      setSshState(telemetry.ssh.last_probe.ok ? 'ok' : 'failed');
    } else if (telemetry.ssh.needs_passphrase) {
      setSshState('key locked');
    } else if (telemetry.ssh.unlocked) {
      setSshState('unlocked');
    }
  }, [telemetry]);

  const probeSsh = async () => {
    try {
      const answer = await controllerApi.sshTest();
      setSshState(answer.ok ? 'ok' : 'failed');
      toast(
        answer.ok ? 'ssh ok' : answer.output || answer.error || 'ssh failed',
        answer.ok ? 'success' : 'error',
      );
    } catch (caught) {
      setSshState('failed');
      toast(errorText(caught), 'error');
    }
  };

  const unlock = async () => {
    try {
      const answer = await controllerApi.sshUnlock(passphrase);
      setPassphrase('');
      if (answer.ok) {
        setPassOpen(false);
        setPassError('');
        toast('SSH key unlocked', 'success');
        await reload();
        return;
      }
      setPassError(answer.output || answer.error || 'unlock failed');
    } catch (caught) {
      setPassphrase('');
      setPassError(errorText(caught));
    }
  };

  const runSync = async () => {
    try {
      const answer = await controllerApi.telemetrySync('manual');
      toast(
        answer.started
          ? 'Retrieval started'
          : answer.message || answer.status || 'not started',
        answer.started ? 'success' : 'info',
      );
    } catch (caught) {
      toast(errorText(caught), 'error');
    }
    await reload();
  };

  const stores = telemetry?.stores;
  const configured = telemetry?.source.configured ?? false;
  const usageBlock = usage?.usage;

  return (
    <Page>
      {error ? (
        <Card>
          <CardHeader title="Telemetry state is unavailable" />
          <Hint>{error}</Hint>
        </Card>
      ) : null}

      <Grid $columns={2} $min="380px">
        <Card>
          <CardHeader
            title="Telemetry retrieval"
            action={
              <Tag
                color={telemetry?.running ? 'yellow' : configured ? 'green' : 'gray'}
                text={
                  telemetry?.running
                    ? 'a retrieval is running'
                    : configured
                      ? 'idle'
                      : 'no source'
                }
                dot={telemetry?.running ? 'pulsing' : true}
              />
            }
          />
          <KeyValue label="Source">{telemetry?.source.value || 'not configured'}</KeyValue>
          <KeyValue label="Source from">
            {configured ? telemetry?.source.origin : 'nothing names a source'}
          </KeyValue>
          <KeyValue label="Last success">
            {telemetry?.last_success
              ? ago(telemetry.last_success.finished_utc)
              : 'never from this controller'}
          </KeyValue>
          <KeyValue label="Rollup">
            {telemetry?.rollup?.last_rollup_utc
              ? `${ago(telemetry.rollup.last_rollup_utc)} · ${
                  telemetry.rollup.current ? 'current' : 'behind the raw files'
                }`
              : 'never'}
          </KeyValue>
          <KeyValue label="summaries.db">{storeLine(stores?.summaries_db)}</KeyValue>
          <KeyValue label="snapshot.csv">{storeLine(stores?.snapshot_csv)}</KeyValue>
          <KeyValue label="Raw telemetry">
            {stores?.telemetry?.present
              ? `${stores.telemetry.days} days · newest ${stores.telemetry.newest_day || '—'}`
              : 'absent'}
          </KeyValue>
          <KeyValue label="GPU series">
            {usageBlock?.available
              ? `${usageBlock.slots.length} slots · newest ${ago(usageBlock.freshness_utc)}`
              : 'no rolled-up GPU series yet'}
          </KeyValue>

          <Field label="Telemetry source">
            <InlineRow>
              <TextInput
                id="telemetry-source"
                value={source}
                placeholder="unity:/work/<account>/<user>/cluster-intel/telemetry/"
                onChange={(event) => setSource(event.target.value)}
              />
              <Button
                size="small"
                disabled={busy}
                onClick={() => void save({ source: source.trim() }, 'Source saved')}
              >
                Save
              </Button>
            </InlineRow>
          </Field>

          <ButtonGroup style={{ marginTop: 16 }}>
            <Button
              variant="primary"
              Icon={IconDownload}
              disabled={telemetry?.running || !configured}
              onClick={() => void runSync()}
            >
              {telemetry?.running ? 'Retrieval running…' : 'Retrieve now'}
            </Button>
          </ButtonGroup>
          <Hint>
            {configured
              ? 'One retrieval pulls the raw telemetry, rolls it up, and removes archived days from the cluster. The final copy stays on this machine.'
              : 'Set a telemetry source above. Give it the rsync source that holds the cluster telemetry directory.'}
          </Hint>
        </Card>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Card>
            <CardHeader
              title="SSH access"
              action={
                <Tag
                  color={
                    sshState === 'ok' || sshState === 'unlocked'
                      ? 'green'
                      : sshState === 'failed'
                        ? 'red'
                        : 'gray'
                  }
                  text={sshState}
                />
              }
            />
            <KeyValue label="Command">
              {telemetry?.ssh.command || `ssh ${sshHost}`}
            </KeyValue>
            <Field label="SSH host — config alias">
              <InlineRow>
                <TextInput
                  id="ssh-host"
                  value={sshHost}
                  placeholder="unity"
                  autoComplete="off"
                  onChange={(event) => setSshHost(event.target.value)}
                />
                <Button
                  size="small"
                  disabled={busy}
                  onClick={() =>
                    void save(
                      {
                        ssh_host: sshHost.trim() || 'unity',
                        ssh_identity: sshIdentity.trim(),
                      },
                      'SSH access saved',
                    )
                  }
                >
                  Save
                </Button>
              </InlineRow>
            </Field>
            <Field label="Identity file — optional">
              <InlineRow>
                <TextInput
                  id="ssh-identity"
                  value={sshIdentity}
                  placeholder="~/.ssh/id_ed25519"
                  autoComplete="off"
                  onChange={(event) => setSshIdentity(event.target.value)}
                />
                <Button
                  size="small"
                  Icon={IconPlugConnected}
                  onClick={() => void probeSsh()}
                >
                  Test
                </Button>
              </InlineRow>
            </Field>
            <ButtonGroup style={{ marginTop: 16 }}>
              <Button Icon={IconLock} size="small" onClick={() => setPassOpen(true)}>
                Unlock key
              </Button>
            </ButtonGroup>
            <Hint>
              The controller runs this alias the same way a shell does:{' '}
              <code>ssh {sshHost || 'unity'}</code>. Put the host entry in{' '}
              <code>~/.ssh/config</code>. An identity file is only needed when
              that config does not already name one.
            </Hint>
          </Card>

          <Card>
            <CardHeader title="This controller" />
            <KeyValue label="Cluster">{cluster?.cluster || '—'}</KeyValue>
            <KeyValue label="Slurm">{cluster?.slurm_version || '—'}</KeyValue>
            <KeyValue label="This page">{window.location.origin}</KeyValue>
            <KeyValue label="Poll cadence">every 10s</KeyValue>
            <KeyValue label="Attached projects">{projects.length}</KeyValue>
            <KeyValue label="Job ledger">{`sqlite · ${jobs.length} rows`}</KeyValue>
            <KeyValue label="Health">
              {health ? (health.ok ? 'ok' : 'down') : (syncError ?? '—')}
            </KeyValue>
          </Card>
        </div>
      </Grid>

      <Modal
        open={passOpen}
        onClose={() => setPassOpen(false)}
        title="Unlock SSH key"
      >
        <Hint style={{ marginTop: 0 }}>
          {`ssh ${telemetry?.ssh.host || sshHost || 'unity'}`}
          <br />
          {`Enter passphrase for key '${telemetry?.ssh.key_path || telemetry?.ssh.identity || ''}':`}
        </Hint>
        <Field label="Passphrase">
          <TextInput
            type="password"
            autoComplete="off"
            value={passphrase}
            autoFocus
            onChange={(event) => setPassphrase(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void unlock();
            }}
          />
        </Field>
        {passError ? <Hint style={{ color: 'inherit' }}>{passError}</Hint> : null}
        <ButtonGroup align="right">
          <Button variant="tertiary" onClick={() => setPassOpen(false)}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => void unlock()}>
            Unlock
          </Button>
        </ButtonGroup>
      </Modal>
    </Page>
  );
};
