/** A data table: sticky head, hover rows, and a full-width empty row. */

import styled from '@emotion/styled';
import type { ReactNode } from 'react';

export const TableScroller = styled.div`
  max-width: 100%;
  overflow-x: auto;
`;

export const Table = styled.table`
  border-collapse: collapse;
  font-size: ${({ theme }) => theme.font.size.sm};
  width: 100%;
`;

export const THead = styled.thead`
  th {
    background: ${({ theme }) => theme.background.secondary};
    border-bottom: 1px solid ${({ theme }) => theme.border.color.medium};
    color: ${({ theme }) => theme.font.color.tertiary};
    font-size: ${({ theme }) => theme.font.size.xs};
    font-weight: ${({ theme }) => theme.font.weight.medium};
    letter-spacing: 0.04em;
    padding: ${({ theme }) => theme.spacing(1.5, 2)};
    position: sticky;
    text-align: left;
    text-transform: uppercase;
    top: 0;
    white-space: nowrap;
    z-index: 1;
  }

  th:first-of-type {
    padding-left: 0;
  }

  th:last-of-type {
    padding-right: 0;
    text-align: right;
  }
`;

export const TRow = styled.tr<{ $clickable?: boolean }>`
  border-bottom: 1px solid ${({ theme }) => theme.border.color.light};
  cursor: ${({ $clickable }) => ($clickable ? 'pointer' : 'default')};
  transition: background ${({ theme }) => theme.animation.duration.fast} ease;

  &:hover {
    background: ${({ theme, $clickable }) =>
      $clickable ? theme.background.transparent.primary : 'transparent'};
  }

  &:last-of-type {
    border-bottom: none;
  }

  td {
    color: ${({ theme }) => theme.font.color.primary};
    height: ${({ theme }) => theme.table.rowHeight};
    padding: ${({ theme }) => theme.spacing(1.5, 2)};
    vertical-align: middle;
  }

  td:first-of-type {
    padding-left: 0;
  }

  td:last-of-type {
    padding-right: 0;
    text-align: right;
  }
`;

/** A cell that never wraps and stays monospaced, for ids and durations. */
export const MonoCell = styled.td`
  color: ${({ theme }) => theme.font.color.secondary};
  font-family: ${({ theme }) => theme.font.familyMono};
  font-size: ${({ theme }) => theme.font.size.xs};
  white-space: nowrap;
`;

export const MutedCell = styled.td`
  color: ${({ theme }) => theme.font.color.secondary};
`;

const EmptyCell = styled.td`
  color: ${({ theme }) => theme.font.color.tertiary};
  font-size: ${({ theme }) => theme.font.size.sm};
  padding: ${({ theme }) => theme.spacing(6, 0)} !important;
  text-align: center !important;
`;

/** The one row a table shows when it has nothing to draw. */
export const TableEmptyRow = ({
  colSpan,
  children,
}: {
  colSpan: number;
  children: ReactNode;
}) => (
  <tr>
    <EmptyCell colSpan={colSpan}>{children}</EmptyCell>
  </tr>
);
