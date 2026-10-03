/** GPU allocation by weekday and UTC hour, with distinct missing and out-of-window cells. */

import styled from '@emotion/styled';
import { useTheme } from '@emotion/react';
import { Fragment, useState } from 'react';

import { EmptyState } from '../../ui/components/EmptyState';

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const HOUR_MS = 3_600_000;
type CellState = 'value' | 'partial' | 'missing' | 'outside';
type HeatCell = { dow: number; hour: number; value: number; samples?: number };

const Grid = styled.div`
  display: grid;
  gap: 2px;
  grid-template-columns: 34px repeat(24, minmax(0, 1fr));
  min-width: 540px;
`;

const Scroller = styled.div`
  overflow-x: auto;
  padding: 2px;
`;

const DayLabel = styled.div`
  align-items: center;
  color: ${({ theme }) => theme.font.color.tertiary};
  display: flex;
  font-size: ${({ theme }) => theme.font.size.xxs};
  height: 20px;
`;

const HourLabel = styled.div`
  color: ${({ theme }) => theme.font.color.light};
  font-size: ${({ theme }) => theme.font.size.xxs};
  padding-top: ${({ theme }) => theme.spacing(1)};
  text-align: center;
`;

const Cell = styled.button<{ $color: string; $state: CellState }>`
  appearance: none;
  background: ${({ $color }) => $color};
  background-image: ${({ theme, $state }) =>
    $state === 'missing'
      ? `repeating-linear-gradient(135deg, transparent 0 3px, ${theme.border.color.strong} 3px 4px)`
      : 'none'};
  border: 1px solid ${({ theme, $state }) =>
    $state === 'missing' ? theme.border.color.strong : 'transparent'};
  border-bottom: ${({ theme, $state }) => $state === 'partial'
    ? `2px solid ${theme.color.yellow[40]}` : undefined};
  border-radius: 2px;
  cursor: pointer;
  height: 20px;
  min-width: 0;
  opacity: ${({ $state }) => $state === 'outside' ? 0.45 : 1};
  padding: 0;

  &:hover, &:focus-visible, &[data-selected='true'] {
    outline: 2px solid ${({ theme }) => theme.accent.primary};
    outline-offset: 1px;
    opacity: 1;
    position: relative;
    z-index: 1;
  }
`;

const Scale = styled.div`
  align-items: center;
  color: ${({ theme }) => theme.font.color.tertiary};
  display: flex;
  flex-wrap: wrap;
  font-size: ${({ theme }) => theme.font.size.xxs};
  gap: ${({ theme }) => theme.spacing(1)};
  justify-content: flex-end;
  margin-top: ${({ theme }) => theme.spacing(3)};
`;

const ScaleChip = styled.i<{ $color: string; $missing?: boolean; $partial?: boolean; $outside?: boolean }>`
  background: ${({ $color }) => $color};
  background-image: ${({ theme, $missing }) => $missing
    ? `repeating-linear-gradient(135deg, transparent 0 3px, ${theme.border.color.strong} 3px 4px)`
    : 'none'};
  border: 1px solid ${({ theme, $missing }) => $missing
    ? theme.border.color.strong : 'transparent'};
  border-bottom: ${({ theme, $partial }) => $partial
    ? `2px solid ${theme.color.yellow[40]}` : undefined};
  border-radius: 2px;
  height: 10px;
  opacity: ${({ $outside }) => $outside ? 0.45 : 1};
  width: 16px;
`;

const Detail = styled.div`
  color: ${({ theme }) => theme.font.color.secondary};
  font-size: ${({ theme }) => theme.font.size.sm};
  min-height: 20px;
  margin-top: ${({ theme }) => theme.spacing(2)};
`;

const formatValue = (value: number): string =>
  value.toLocaleString(undefined, { maximumFractionDigits: 1 });

/** UTC weekday/hour keys that occur anywhere inside the selected window. */
const windowCounts = (start?: string | null, end?: string | null): Map<string, number> | null => {
  const left = Date.parse(start ?? '');
  const right = Date.parse(end ?? '');
  if (!Number.isFinite(left) || !Number.isFinite(right) || left >= right) return null;
  const keys = new Map<string, number>();
  for (let time = Math.floor(left / HOUR_MS) * HOUR_MS; time < right; time += HOUR_MS) {
    const date = new Date(time);
    const key = `${(date.getUTCDay() + 6) % 7}-${date.getUTCHours()}`;
    keys.set(key, (keys.get(key) ?? 0) + 1);
  }
  return keys;
};

export const HourHeatmap = ({
  cells,
  unit = 'percent',
  windowStartUtc,
  windowEndUtc,
  emptyMessage,
}: {
  cells: HeatCell[];
  unit?: 'gpus' | 'percent';
  windowStartUtc?: string | null;
  windowEndUtc?: string | null;
  emptyMessage?: string;
}) => {
  const theme = useTheme();
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  if (!cells.length) {
    return (
      <EmptyState title="No hourly GPU series in this window" compact>
        {emptyMessage ?? 'Collect historical allocations or hourly samples to fill this map.'}
      </EmptyState>
    );
  }

  const byCell = new Map(cells.map((cell) => [`${cell.dow}-${cell.hour}`, cell]));
  const expected = windowCounts(windowStartUtc, windowEndUtc);
  const values = [...byCell.values()].map((cell) => cell.value)
    .filter(Number.isFinite).sort((a, b) => a - b);
  const lowest = values[0] ?? 0;
  const highest = values[values.length - 1] ?? 0;
  const ranks = new Map<number, number>();
  values.forEach((value, index) => {
    if (!ranks.has(value)) ranks.set(value, index);
  });
  const scale = theme.chart.sequential;
  const colorOf = (value: number): string => {
    const index = lowest === highest
      ? Math.floor(scale.length / 2)
      : Math.min(scale.length - 1, Math.floor(((ranks.get(value) ?? 0) / values.length) * scale.length));
    return scale[index];
  };
  const unitLabel = unit === 'gpus' ? ' allocated GPUs' : '% of GPU capacity allocated';
  const describe = (key: string, day: string, hour: number): string => {
    const prefix = `${day} ${String(hour).padStart(2, '0')}:00 UTC`;
    if (expected && !expected.has(key)) return `${prefix} · outside selected window`;
    const cell = byCell.get(key);
    if (!cell) {
      return `${prefix} · no sample in selected window`;
    }
    const count = expected?.get(key);
    const coverage = cell.samples && count
      ? ` · ${cell.samples} of ${count} hours sampled`
      : '';
    return `${prefix} · average ${formatValue(cell.value)}${unitLabel}${coverage}`;
  };
  const firstKey = `${cells[0].dow}-${cells[0].hour}`;
  let selectedText = 'Select a cell to inspect its value. Use arrow keys to move through the matrix.';
  if (selectedKey) {
    const [day, hour] = selectedKey.split('-').map(Number);
    selectedText = describe(selectedKey, DAYS[day], hour);
  }
  const move = (key: string, day: number, hour: number, pressed: string,
                grid: HTMLElement | null) => {
    let nextDay = day;
    let nextHour = hour;
    if (pressed === 'ArrowRight') {
      nextHour = (hour + 1) % 24;
      if (nextHour === 0) nextDay = (day + 1) % 7;
    } else if (pressed === 'ArrowLeft') {
      nextHour = (hour + 23) % 24;
      if (hour === 0) nextDay = (day + 6) % 7;
    }
    else if (pressed === 'ArrowDown') nextDay = (day + 1) % 7;
    else if (pressed === 'ArrowUp') nextDay = (day + 6) % 7;
    else if (pressed === 'Home') nextHour = 0;
    else if (pressed === 'End') nextHour = 23;
    else return false;
    const next = `${nextDay}-${nextHour}`;
    if (next !== key) {
      setSelectedKey(next);
      grid?.querySelector<HTMLButtonElement>(`[data-cell-key="${next}"]`)?.focus();
    }
    return true;
  };

  return (
    <>
      <Scroller>
        <Grid role="group" aria-label="GPU allocation by weekday and UTC hour">
          {DAYS.map((day, dayIndex) => (
            <Fragment key={day}>
              <DayLabel>{day}</DayLabel>
              {Array.from({ length: 24 }, (_, hour) => {
                const key = `${dayIndex}-${hour}`;
                const cell = byCell.get(key);
                const state: CellState = expected && !expected.has(key)
                  ? 'outside' : !cell ? 'missing'
                  : cell.samples !== undefined && cell.samples < (expected?.get(key) ?? 0)
                    ? 'partial' : 'value';
                const label = describe(key, day, hour);
                return (
                  <Cell
                    key={key}
                    type="button"
                    data-testid="heatmap-cell"
                    data-cell-key={key}
                    data-state={state}
                    $color={(state === 'value' || state === 'partial') && cell
                      ? colorOf(cell.value) : theme.background.tertiary}
                    $state={state}
                    title={label}
                    aria-label={label}
                    data-selected={selectedKey === key}
                    tabIndex={(selectedKey ?? firstKey) === key ? 0 : -1}
                    onFocus={() => setSelectedKey(key)}
                    onClick={() => setSelectedKey(key)}
                    onKeyDown={(event) => {
                      if (move(key, dayIndex, hour, event.key, event.currentTarget.parentElement)) {
                        event.preventDefault();
                      }
                    }}
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
      <Detail data-testid="heatmap-detail">
        {selectedText}
      </Detail>
      <Scale aria-label="Relative allocation scale for the selected window">
        {expected && expected.size < 168 ? <>outside window <ScaleChip $color={theme.background.tertiary} $outside /></> : null}
        no sample <ScaleChip $color={theme.background.tertiary} $missing />
        partial data <ScaleChip $color={scale[3]} $partial />
        <span style={{ marginLeft: 8 }}>{formatValue(lowest)}{unit === 'gpus' ? ' GPUs' : '%'}</span>
        {scale.map((color) => <ScaleChip key={color} $color={color} />)}
        <span>{formatValue(highest)}{unit === 'gpus' ? ' GPUs' : '%'}</span>
        <span>· relative rank</span>
      </Scale>
    </>
  );
};
