/** A ranked horizontal bar list: a label, a bar, and the value. */

import { useTheme } from '@emotion/react';
import styled from '@emotion/styled';

import { EmptyState } from '../../ui/components/EmptyState';
import { Meter } from '../../ui/components/ProgressBar';

const List = styled.div`
  display: flex;
  flex-direction: column;
`;

export type BarRow = { label: string; value: number; text?: string };

export const BarList = ({
  rows,
  emptyTitle,
  emptyBody,
  color,
}: {
  rows: BarRow[];
  emptyTitle: string;
  emptyBody?: string;
  /** Leave unset to let the value pick the colour. */
  color?: string;
}) => {
  const theme = useTheme();
  if (!rows.length) {
    return (
      <EmptyState title={emptyTitle} compact>
        {emptyBody}
      </EmptyState>
    );
  }
  const peak = Math.max(1, ...rows.map((row) => row.value));

  return (
    <List>
      {rows.map((row) => (
        <Meter
          key={row.label}
          label={row.label}
          percent={(row.value / peak) * 100}
          value={row.text ?? String(row.value)}
          color={color ?? theme.color.blue[40]}
          title={`${row.label}: ${row.text ?? row.value}`}
        />
      ))}
    </List>
  );
};
