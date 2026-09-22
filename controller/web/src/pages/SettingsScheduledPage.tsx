/**
 * The schedule, the cluster script it runs, and the login-node session.
 *
 * The schedule sends the saved script into the cluster session, waits for it,
 * then pulls. The session closes after a quiet period of one and a half
 * intervals, so the interval is also a statement about how long a login-node
 * shell stays open. ADR 0003 and ADR 0004.
 */

import { IconPlayerPlay, IconPlugX } from '@tabler/icons-react';
import { useEffect, useState } from 'react';

import { controllerApi, errorText } from '../modules/controller/api';
import { ago } from '../modules/controller/format';
import { useTelemetry } from '../modules/telemetry/TelemetryProvider';
import { Button, ButtonGroup } from '../ui/components/Button';
import { Card, CardHeader, Grid, Hint, KeyValue } from '../ui/components/Card';
import { Field, InlineRow, Select, TextInput, Toggle } from '../ui/components/Field';
import { Tag } from '../ui/components/Tag';
import { useToast } from '../ui/components/Toast';
import { Page } from '../ui/layout/AppLayout';

const SCRIPT_LABELS: Record<string, string> = {
  once: 'once — sample and prune',
  sample: 'sample',
  prune: 'prune',
};

/** "closes after 45 min with no command". */
const idleText = (seconds?: number): string => {
  if (!seconds) return '—';
  const minutes = seconds / 60;
  const shown = Number.isInteger(minutes) ? String(minutes) : minutes.toFixed(1);
  return `closes after ${shown} min with no command`;
};

export const SettingsScheduledPage = () => {
  const { telemetry, reload, save, busy } = useTelemetry();
  const toast = useToast();
  const [interval, setIntervalMinutes] = useState('60');
  const [script, setScript] = useState('once');

  useEffect(() => {
    if (!telemetry) return;
    const active = document.activeElement;
    if (active?.id !== 'schedule-interval') {
      setIntervalMinutes(String(telemetry.schedule.interval_minutes || 60));
    }
    if (active?.id !== 'schedule-script') {
      setScript(telemetry.schedule.script || 'once');
    }
  }, [telemetry]);

  const schedule = telemetry?.schedule;
  const configured = telemetry?.source.configured ?? false;
  const scripts = schedule?.scripts ?? ['once', 'sample', 'prune'];

  const runScript = async () => {
    try {
      await controllerApi.telemetrySettings({ script_mode: script });
      const answer = await controllerApi.telemetryScript(script, 'manual');
      toast(
        answer.started
          ? 'Script started'
          : answer.message || answer.error || answer.status || 'not started',
        answer.started ? 'success' : 'info',
      );
    } catch (caught) {
      toast(errorText(caught), 'error');
    }
    await reload();
  };

  const closeSession = async () => {
    try {
      const answer = await controllerApi.telemetryCloseSession();
      toast(
        answer.ok
          ? answer.skipped
            ? 'No remote session was open'
            : 'Session closed'
          : answer.message || answer.error || 'not closed',
        answer.ok ? 'success' : 'error',
      );
    } catch (caught) {
      toast(errorText(caught), 'error');
    }
    await reload();
  };

  const saveInterval = async () => {
    const minutes = Number(interval);
    if (!Number.isFinite(minutes)) {
      toast('interval must be a number', 'error');
      return;
    }
    await save({ interval_minutes: Math.round(minutes) }, 'Interval saved');
  };

  return (
    <Page>
      <Grid $columns={2} $min="380px">
        <Card>
          <CardHeader
            title="Schedule"
            action={
              <Tag
                color={schedule?.enabled ? 'green' : 'gray'}
                text={
                  schedule?.enabled
                    ? schedule.thread_alive
                      ? 'on'
                      : 'on · thread not started'
                    : 'off'
                }
                dot
              />
            }
          />
          <div
            style={{
              alignItems: 'center',
              display: 'flex',
              gap: 12,
              justifyContent: 'space-between',
              paddingBottom: 12,
            }}
          >
            <span style={{ fontSize: 12, opacity: 0.75 }}>
              Run the saved script on a timer, then pull
            </span>
            <Toggle
              value={schedule?.enabled ?? false}
              disabled={busy}
              aria-label="Scheduled retrieval"
              onChange={(next) =>
                void save(
                  { schedule_enabled: next },
                  next ? 'Schedule on' : 'Schedule off',
                )
              }
            />
          </div>
          <KeyValue label="Next run">
            {schedule?.enabled ? ago(schedule.next_run_utc) : 'schedule is off'}
          </KeyValue>
          <KeyValue label="Cluster session">
            {idleText(schedule?.inactivity_timeout_s)}
          </KeyValue>
          <KeyValue label="tmux session">{schedule?.session || '—'}</KeyValue>

          <Field
            label={`Interval — minutes${
              schedule?.min_interval_minutes
                ? ` (${schedule.min_interval_minutes}–${schedule.max_interval_minutes})`
                : ''
            }`}
          >
            <InlineRow>
              <TextInput
                id="schedule-interval"
                type="number"
                min={schedule?.min_interval_minutes ?? 5}
                max={schedule?.max_interval_minutes ?? 1440}
                step={5}
                value={interval}
                onChange={(event) => setIntervalMinutes(event.target.value)}
              />
              <Button size="small" disabled={busy} onClick={() => void saveInterval()}>
                Save
              </Button>
            </InlineRow>
          </Field>
          <Hint>
            The session closes after a quiet period of one and a half intervals,
            so a longer interval also keeps a login-node shell open longer.
          </Hint>
        </Card>

        <Card>
          <CardHeader
            title="Cluster script"
            action={
              <Tag
                color={telemetry?.running ? 'yellow' : 'gray'}
                text={telemetry?.running ? 'running' : 'idle'}
                dot={telemetry?.running ? 'pulsing' : true}
              />
            }
          />
          <Field label="Script the schedule sends">
            <InlineRow>
              <Select
                id="schedule-script"
                value={script}
                options={scripts.map((one) => ({
                  value: one,
                  label: SCRIPT_LABELS[one] ?? one,
                }))}
                onChange={(event) => setScript(event.target.value)}
              />
              <Button
                size="small"
                disabled={busy}
                onClick={() => void save({ script_mode: script }, 'Script saved')}
              >
                Save
              </Button>
            </InlineRow>
          </Field>
          <ButtonGroup style={{ marginTop: 16 }}>
            <Button
              variant="primary"
              Icon={IconPlayerPlay}
              disabled={telemetry?.running || !configured}
              onClick={() => void runScript()}
            >
              Run script now
            </Button>
            <Button Icon={IconPlugX} onClick={() => void closeSession()}>
              Close session
            </Button>
          </ButtonGroup>
          <Hint>
            Run script now does the scheduled step immediately: it sends the
            script into the cluster session, waits, then pulls. Sample logs stay
            on this machine. Close session ends the login-node shell and removes
            the remote <code>/tmp</code> files.
          </Hint>
          {!configured ? (
            <Hint>
              No telemetry source is configured, so a script run has nothing to
              pull afterwards. Set one on the Config page.
            </Hint>
          ) : null}
        </Card>
      </Grid>
    </Page>
  );
};
