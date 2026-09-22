/** Retrieval history, the output of the last run, and the controller log. */

import styled from '@emotion/styled';
import { useRecoilValue } from 'recoil';

import { ago } from '../modules/controller/format';
import { eventsState } from '../modules/controller/state';
import { EventFeed } from '../modules/events/EventFeed';
import type { TelemetryRun } from '../modules/controller/types';
import { useTelemetry } from '../modules/telemetry/TelemetryProvider';
import { Card, CardHeader, Grid } from '../ui/components/Card';
import { CodeBlock } from '../ui/components/CodeBlock';
import { EmptyState } from '../ui/components/EmptyState';
import { Tag } from '../ui/components/Tag';
import type { ThemeColor } from '../ui/theme/colors';
import { Page } from '../ui/layout/AppLayout';

const STATUS: Record<string, { color: ThemeColor; label: string }> = {
  ok: { color: 'green', label: 'ok' },
  failed: { color: 'red', label: 'failed' },
  'already-running': { color: 'yellow', label: 'already running' },
  running: { color: 'blue', label: 'running' },
  unconfigured: { color: 'gray', label: 'no source' },
};

const RunRow = styled.div`
  align-items: center;
  border-bottom: 1px solid ${({ theme }) => theme.border.color.light};
  display: flex;
  gap: ${({ theme }) => theme.spacing(2.5)};
  padding: ${({ theme }) => theme.spacing(2, 0)};

  &:last-of-type {
    border-bottom: none;
  }
`;

const RunDetail = styled.div`
  color: ${({ theme }) => theme.font.color.secondary};
  flex: 1;
  font-size: ${({ theme }) => theme.font.size.xs};
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

const RunWhen = styled.div`
  color: ${({ theme }) => theme.font.color.tertiary};
  flex-shrink: 0;
  font-size: ${({ theme }) => theme.font.size.xxs};
  white-space: nowrap;
`;

/** "manual · once · 12s · rc 0". */
const detailOf = (run: TelemetryRun): string =>
  [
    run.reason,
    run.mode,
    run.duration_s !== null && run.duration_s !== undefined
      ? `${run.duration_s}s`
      : null,
    run.rc !== null && run.rc !== undefined ? `rc ${run.rc}` : null,
  ]
    .filter(Boolean)
    .join(' · ');

export const SettingsLogsPage = () => {
  const { telemetry, error } = useTelemetry();
  const events = useRecoilValue(eventsState);

  const history = telemetry?.history ?? [];
  const current = telemetry?.in_flight ?? telemetry?.last_run ?? null;
  const activity = [...events].reverse();

  return (
    <Page>
      {error ? (
        <Card>
          <EmptyState title="Telemetry state is unavailable">{error}</EmptyState>
        </Card>
      ) : null}

      <Grid $columns={2} $min="380px">
        <Card>
          <CardHeader
            title="Retrieval history"
            note={history.length ? `${history.length} kept` : undefined}
          />
          {history.length ? (
            <div>
              {history.map((run, index) => {
                const status = STATUS[run.status ?? ''] ?? {
                  color: 'gray' as ThemeColor,
                  label: run.status ?? 'unknown',
                };
                return (
                  <RunRow key={`${run.started_utc ?? index}-${index}`}>
                    <Tag color={status.color} text={status.label} />
                    <RunDetail title={detailOf(run)}>{detailOf(run)}</RunDetail>
                    <RunWhen>{ago(run.finished_utc || run.started_utc)}</RunWhen>
                  </RunRow>
                );
              })}
            </div>
          ) : (
            <EmptyState title="No retrieval has run from this controller yet" compact>
              Start one from the Config page, or switch the schedule on.
            </EmptyState>
          )}
        </Card>

        <Card>
          <CardHeader
            title="Last retrieval output"
            note={current ? `${current.reason ?? ''} · ${current.status ?? ''}` : undefined}
          />
          {current ? (
            <CodeBlock maxHeight="320px">
              {current.output ||
                (current.status === 'running'
                  ? 'Running. The output arrives when the retrieval ends.'
                  : 'The retrieval produced no output.')}
            </CodeBlock>
          ) : (
            <EmptyState title="Nothing to show yet" compact>
              The output of the newest retrieval appears here.
            </EmptyState>
          )}
        </Card>
      </Grid>

      <Card>
        <CardHeader
          title="Controller event log"
          note={activity.length ? `${activity.length} events kept` : undefined}
        />
        <EventFeed
          events={activity}
          limit={50}
          showKind
          emptyTitle="No controller events yet"
          emptyBody="Attach, dispatch, configure and retrieval events all land here."
        />
      </Card>
    </Page>
  );
};
