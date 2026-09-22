/**
 * When the cluster is busy: hour of day against day of week, in UTC.
 *
 * A grid of plain elements, not a chart library. Each cell is one average, and
 * an absent cell means no sample fell in that hour — which is a different fact
 * from an average of zero, so the two never share a colour.
 */

import styled from '@emotion/styled';
import { useTheme } from '@emotion/react';
import { Fragment } from 'react';

import { EmptyState } from '../../ui/components/EmptyState';

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

const Grid = styled.div`
  display: grid;
  gap: 2px;
  grid-template-columns: 34px repeat(24, minmax(0, 1fr));
  min-width: 540px;
`;

const Scroller = styled.div`
  overflow-x: auto;
`;

const DayLabel = styled.div`
  align-items: center;
  color: ${({ theme }) => theme.font.color.tertiary};
  display: flex;
  font-size: ${({ theme }) => theme.font.size.xxs};
  height: 17px;
`;

const HourLabel = styled.div`
  color: ${({ theme }) => theme.font.color.light};
  font-size: ${({ theme }) => theme.font.size.xxs};
  padding-top: ${({ theme }) => theme.spacing(1)};
  text-align: center;
`;

const Cell = styled.div<{ $color: string }>`
  background: ${({ $color }) => $color};
  border-radius: 2px;
  height: 17px;
`;

const Scale = styled.div`
  align-items: center;
  color: ${({ theme }) => theme.font.color.tertiary};
  display: flex;
  font-size: ${({ theme }) => theme.font.size.xxs};
  gap: ${({ theme }) => theme.spacing(1)};
  justify-content: flex-end;
  margin-top: ${({ theme }) => theme.spacing(3)};
`;

const ScaleChip = styled.i<{ $color: string }>`
  background: ${({ $color }) => $color};
  border-radius: 2px;
  height: 9px;
  width: 16px;
`;

export const HourHeatmap = ({
  cells,
}: {
  cells: { dow: number; hour: number; value: number }[];
}) => {
  const theme = useTheme();

  if (!cells.length) {
    return (
      <EmptyState title="No hourly GPU series in this window" compact>
        The map fills once the rollup holds per-hour samples for the chosen
        window.
      </EmptyState>
    );
  }

  const byCell = new Map<string, number>();
  let peak = 0;
  for (const cell of cells) {
    byCell.set(`${cell.dow}-${cell.hour}`, cell.value);
    if (cell.value > peak) peak = cell.value;
  }
  const scale = theme.chart.sequential;
  const colorOf = (value: number | undefined): string => {
    if (value === undefined) return theme.background.tertiary;
    const index = Math.min(
      scale.length - 1,
      Math.round((value / (peak || 1)) * (scale.length - 1)),
    );
    return scale[index];
  };

  return (
    <>
      <Scroller>
        <Grid>
          {DAYS.map((day, dayIndex) => (
            <Fragment key={day}>
              <DayLabel>{day}</DayLabel>
              {Array.from({ length: 24 }, (_, hour) => {
                const value = byCell.get(`${dayIndex}-${hour}`);
                return (
                  <Cell
                    key={`${day}-${hour}`}
                    $color={colorOf(value)}
                    title={
                      value === undefined
                        ? `${day} ${String(hour).padStart(2, '0')}:00 UTC · no sample`
                        : `${day} ${String(hour).padStart(2, '0')}:00 UTC · avg ${value}%`
                    }
                  />
                );
              })}
            </Fragment>
          ))}
          <div />
          {Array.from({ length: 24 }, (_, hour) => (
            <HourLabel key={`hour-${hour}`}>
              {hour % 3 === 0 ? String(hour).padStart(2, '0') : ''}
            </HourLabel>
          ))}
        </Grid>
      </Scroller>
      <Scale>
        no sample
        <ScaleChip $color={theme.background.tertiary} />
        <span style={{ marginLeft: 8 }}>0%</span>
        {scale.map((color) => (
          <ScaleChip key={color} $color={color} />
        ))}
        <span>{Math.round(peak)}%</span>
      </Scale>
    </>
  );
};
