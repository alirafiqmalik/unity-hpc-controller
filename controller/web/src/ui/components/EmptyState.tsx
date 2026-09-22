/**
 * What a panel shows when it has nothing to draw.
 *
 * An empty panel must say which of the two cases it is in: no data has ever
 * arrived, or data arrived and this filter excludes all of it. The two need
 * different actions from the operator, so they never share one sentence.
 */

import styled from '@emotion/styled';
import type { ReactNode } from 'react';

import type { IconComponent } from '../types';

const Wrapper = styled.div<{ $compact: boolean }>`
  align-items: center;
  color: ${({ theme }) => theme.font.color.tertiary};
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.spacing(2)};
  justify-content: center;
  padding: ${({ theme, $compact }) =>
    $compact ? theme.spacing(5, 3) : theme.spacing(9, 4)};
  text-align: center;
`;

const IconCircle = styled.div`
  align-items: center;
  background: ${({ theme }) => theme.background.tertiary};
  border-radius: 50%;
  color: ${({ theme }) => theme.font.color.light};
  display: flex;
  height: 34px;
  justify-content: center;
  width: 34px;
`;

const Title = styled.div`
  color: ${({ theme }) => theme.font.color.secondary};
  font-size: ${({ theme }) => theme.font.size.sm};
  font-weight: ${({ theme }) => theme.font.weight.medium};
`;

const Body = styled.div`
  font-size: ${({ theme }) => theme.font.size.xs};
  line-height: 1.6;
  max-width: 46ch;
`;

export const EmptyState = ({
  title,
  children,
  Icon,
  action,
  compact = false,
}: {
  title: ReactNode;
  children?: ReactNode;
  Icon?: IconComponent;
  action?: ReactNode;
  compact?: boolean;
}) => (
  <Wrapper $compact={compact}>
    {Icon ? (
      <IconCircle>
        <Icon size={17} stroke={1.6} />
      </IconCircle>
    ) : null}
    <Title>{title}</Title>
    {children ? <Body>{children}</Body> : null}
    {action}
  </Wrapper>
);
