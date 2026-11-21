/**
 * The selection bar from twenty's record table.
 *
 * It sits at the bottom of the viewport while the user has rows selected.
 * The page puts the count, the delete action, and clear-selection in it.
 * A confirmation `Modal` still has to run before anything is removed.
 */

import styled from '@emotion/styled';
import type { ReactNode } from 'react';

const Bar = styled.div`
  align-items: center;
  background: ${({ theme }) => theme.background.secondary};
  border: 1px solid ${({ theme }) => theme.border.color.medium};
  border-radius: ${({ theme }) => theme.border.radius.md};
  bottom: 28px;
  box-shadow: ${({ theme }) => theme.boxShadow.strong};
  display: flex;
  flex-wrap: wrap;
  gap: ${({ theme }) => theme.spacing(1)};
  left: 50%;
  max-width: calc(100% - 32px);
  min-height: 48px;
  padding: ${({ theme }) => theme.spacing(1, 2)};
  position: fixed;
  transform: translateX(-50%);
  width: max-content;
  z-index: ${({ theme }) => theme.zIndex.actionBar};
`;

export const ActionBarCount = styled.span`
  color: ${({ theme }) => theme.font.color.secondary};
  font-size: ${({ theme }) => theme.font.size.sm};
  font-weight: ${({ theme }) => theme.font.weight.medium};
  padding: ${({ theme }) => theme.spacing(0, 1)};
  white-space: nowrap;
`;

export const ActionBarDivider = styled.span`
  background: ${({ theme }) => theme.border.color.medium};
  flex-shrink: 0;
  height: 16px;
  margin: ${({ theme }) => theme.spacing(0, 1)};
  width: 1px;
`;

export const ActionBar = ({
  children,
  label = 'Selection actions',
}: {
  children: ReactNode;
  label?: string;
}) => (
  <Bar role="toolbar" aria-label={label}>
    {children}
  </Bar>
);
