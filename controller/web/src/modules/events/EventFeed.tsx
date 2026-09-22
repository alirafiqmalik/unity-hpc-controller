/** The controller event log, as a list. Overview, Dispatch and Logs share it. */

import styled from '@emotion/styled';
import { IconAlertTriangle, IconCheck, IconX } from '@tabler/icons-react';

import { EmptyState } from '../../ui/components/EmptyState';
import { ago } from '../controller/format';
import type { ControllerEvent } from '../controller/types';

const List = styled.div`
  display: flex;
  flex-direction: column;
`;

const Item = styled.div`
  align-items: center;
  border-bottom: 1px solid ${({ theme }) => theme.border.color.light};
  display: flex;
  gap: ${({ theme }) => theme.spacing(2.5)};
  padding: ${({ theme }) => theme.spacing(2, 0)};

  &:last-of-type {
    border-bottom: none;
  }
`;

const Badge = styled.div<{ $tone: 'ok' | 'fail' | 'warn' }>`
  align-items: center;
  background: ${({ theme, $tone }) =>
    $tone === 'ok'
      ? theme.tag.background.green
      : $tone === 'warn'
        ? theme.tag.background.yellow
        : theme.tag.background.red};
  border-radius: ${({ theme }) => theme.border.radius.sm};
  color: ${({ theme, $tone }) =>
    $tone === 'ok'
      ? theme.tag.text.green
      : $tone === 'warn'
        ? theme.tag.text.yellow
        : theme.tag.text.red};
  display: flex;
  flex-shrink: 0;
  height: 22px;
  justify-content: center;
  width: 22px;
`;

const Message = styled.div`
  color: ${({ theme }) => theme.font.color.primary};
  flex: 1;
  font-size: ${({ theme }) => theme.font.size.sm};
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

const Kind = styled.span`
  color: ${({ theme }) => theme.font.color.tertiary};
  font-family: ${({ theme }) => theme.font.familyMono};
  font-size: ${({ theme }) => theme.font.size.xxs};
  margin-right: ${({ theme }) => theme.spacing(2)};
`;

const When = styled.div`
  color: ${({ theme }) => theme.font.color.tertiary};
  flex-shrink: 0;
  font-size: ${({ theme }) => theme.font.size.xxs};
  white-space: nowrap;
`;

export const EventFeed = ({
  events,
  limit = 8,
  tone = 'auto',
  emptyTitle = 'No controller events yet',
  emptyBody,
  showKind = false,
}: {
  events: ControllerEvent[];
  limit?: number;
  /** `warn` draws every row as an alert, for the alerts panel. */
  tone?: 'auto' | 'warn';
  emptyTitle?: string;
  emptyBody?: string;
  showKind?: boolean;
}) => {
  if (!events.length) {
    return (
      <EmptyState title={emptyTitle} compact>
        {emptyBody}
      </EmptyState>
    );
  }

  return (
    <List>
      {events.slice(0, limit).map((event, index) => {
        const ok = event.ok !== false;
        const badge: 'ok' | 'fail' | 'warn' = tone === 'warn' ? 'warn' : ok ? 'ok' : 'fail';
        const Icon =
          badge === 'ok' ? IconCheck : badge === 'warn' ? IconAlertTriangle : IconX;
        return (
          <Item key={`${event.ts ?? index}-${index}`}>
            <Badge $tone={badge}>
              <Icon size={12} stroke={2} />
            </Badge>
            <Message title={event.message ?? event.kind ?? 'event'}>
              {showKind && event.kind ? <Kind>{event.kind}</Kind> : null}
              {event.message || event.kind || 'event'}
            </Message>
            <When>{ago(event.ts)}</When>
          </Item>
        );
      })}
    </List>
  );
};
