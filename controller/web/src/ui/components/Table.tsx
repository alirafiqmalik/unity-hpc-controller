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

export const THead = styled.thead<{ $fill?: boolean }>`
  th {
    background: ${({ theme }) => theme.background.secondary};
    border-bottom: 1px solid ${({ theme }) => theme.border.color.medium};
    color: ${({ theme }) => theme.font.color.tertiary};
    font-size: ${({ theme }) => theme.font.size.xs};
    font-weight: ${({ theme }) => theme.font.weight.medium};
    letter-spacing: 0.04em;
    padding: ${({ theme, $fill }) => ($fill ? '0' : theme.spacing(1.5, 2))};
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

export const TRow = styled.tr<{ $clickable?: boolean; $selected?: boolean }>`
  background: ${({ theme, $selected }) =>
    $selected ? theme.accent.tertiary : 'transparent'};
  border-bottom: 1px solid ${({ theme }) => theme.border.color.light};
  cursor: ${({ $clickable }) => ($clickable ? 'pointer' : 'default')};
  transition: background ${({ theme }) => theme.animation.duration.fast} ease;

  &:hover {
    background: ${({ theme, $clickable, $selected }) =>
      $selected
        ? theme.accent.secondary
        : $clickable
          ? theme.background.transparent.primary
          : 'transparent'};
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

/** The leading select-all cell. It stays a fixed width so the columns do not jump. */
export const SelectHead = styled.th`
  && {
    padding-left: ${({ theme }) => theme.spacing(3)};
    padding-right: ${({ theme }) => theme.spacing(1)};
    text-align: center;
    text-transform: none;
    width: 32px;
  }
`;

/** The leading selection cell on a data row. */
export const SelectCell = styled.td`
  && {
    padding-left: ${({ theme }) => theme.spacing(3)};
    padding-right: ${({ theme }) => theme.spacing(1)};
    text-align: center;
    width: 32px;
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

/**
 * A column heading that fills its cell.
 *
 * The first click sorts ascending, the next descending, the next drops the
 * column. `$on` marks a column that is currently in the sort.
 */
export const HeadButton = styled.button<{ $align: 'left' | 'right'; $on: boolean }>`
  align-items: center;
  background: ${({ theme, $on }) => ($on ? theme.accent.quaternary : 'transparent')};
  border: 0;
  color: ${({ theme, $on }) => ($on ? theme.font.color.primary : 'inherit')};
  cursor: pointer;
  display: inline-flex;
  font: inherit;
  gap: 4px;
  justify-content: ${({ $align }) => ($align === 'right' ? 'flex-end' : 'flex-start')};
  letter-spacing: inherit;
  min-height: ${({ theme }) => theme.table.headerHeight};
  padding: ${({ theme }) => theme.spacing(1.5, 1.5)};
  text-transform: inherit;
  user-select: none;
  width: 100%;

  &:hover {
    background: ${({ theme, $on }) =>
      $on ? theme.accent.tertiary : theme.background.transparent.secondary};
    color: ${({ theme }) => theme.font.color.primary};
  }

  &:focus-visible {
    outline: 2px solid ${({ theme }) => theme.border.color.accent};
    outline-offset: -2px;
  }
`;

/** The arrow, and the rank when more than one column is sorted. */
export const SortCue = styled.span<{ $live: boolean }>`
  align-items: center;
  color: ${({ theme, $live }) => ($live ? theme.accent.primary : theme.font.color.light)};
  display: inline-flex;
  flex-shrink: 0;
  gap: 2px;
  opacity: ${({ $live }) => ($live ? 1 : 0)};

  button:hover > &,
  button:focus-visible > & {
    opacity: 1;
  }
`;

export const SortRank = styled.span`
  align-items: center;
  background: ${({ theme }) => theme.accent.secondary};
  border-radius: ${({ theme }) => theme.border.radius.rounded};
  color: ${({ theme }) => theme.accent.primary};
  display: inline-flex;
  font-size: 9px;
  font-weight: ${({ theme }) => theme.font.weight.semiBold};
  height: 14px;
  justify-content: center;
  letter-spacing: 0;
  min-width: 14px;
  padding: 0 3px;
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
