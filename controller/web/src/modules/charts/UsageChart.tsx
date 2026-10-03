/**
 * The GPU-utilisation chart: one area per GPU type, over the chosen window.
 *
 * The legend is also the filter. Every series the API returned keeps an entry,
 * including the hidden ones, which show dim — otherwise there is no way back
 * to a series once it is off. A series keeps its colour when a sibling goes
 * off, because the colour comes from its place in the full list.
 *
 * A real cluster reports sixteen GPU types. Sixteen filled areas on one axis
 * is not a reading, so until the operator chooses otherwise the chart draws
 * the busiest few and says how many it left out.
 */

import { useTheme } from '@emotion/react';
import { useMemo } from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import type { UsageBlock } from '../controller/types';
import { CHART_SERIES_COLORS } from '../../ui/theme/colors';
import {
  ChartFrame,
  ChartLegend,
  ChartPlaceholder,
  ChartTooltip,
} from './ChartParts';
import { slotTicks, slotTitle } from './slots';
import { useHiddenSeries } from './useHiddenSeries';

/** How many series one chart draws before the rest start as hidden. */
const DEFAULT_VISIBLE = 6;

/** One row per slot: `{ slot, a100: 42, a40: null, … }`. */
const toRows = (usage: UsageBlock, names: string[]) =>
  usage.slots.map((slot, index) => {
    const row: Record<string, string | number | null> = { slot };
    for (const name of names) {
      const value = usage.series[name]?.[index];
      row[name] =
        value === null || value === undefined || value === ('' as unknown)
          ? null
          : Number(value);
    }
    return row;
  });

/**
 * The series to hide on a first look: everything past the busiest few.
 *
 * `by_type` carries the average the API already computed. Without it the
 * order the API sent stands in, which keeps the rule stable rather than
 * arbitrary.
 */
const quietest = (usage: UsageBlock, names: string[]): string[] => {
  if (names.length <= DEFAULT_VISIBLE) return [];
  const average = new Map(
    (usage.by_type ?? []).map((one) => [one.gpu_type, Number(one.avg) || 0]),
  );
  const ranked = [...names].sort(
    (a, b) => (average.get(b) ?? -1) - (average.get(a) ?? -1),
  );
  return ranked.slice(DEFAULT_VISIBLE);
};

export const UsageChart = ({
  chartId,
  usage,
  height = 190,
  /** The legend to draw when the API returned no series at all. */
  fallbackNames = [],
}: {
  chartId: string;
  usage?: UsageBlock | null;
  height?: number;
  fallbackNames?: string[];
}) => {
  const theme = useTheme();

  const names = useMemo(
    () => (usage?.available && usage.series ? Object.keys(usage.series) : []),
    [usage],
  );
  const hiddenByDefault = useMemo(
    () => (usage && names.length ? quietest(usage, names) : []),
    [usage, names],
  );

  const { isHidden, toggle, usingDefault } = useHiddenSeries(
    chartId,
    hiddenByDefault,
  );
  const tick = useMemo(() => slotTicks(usage?.slots ?? []), [usage]);

  if (!usage?.available || names.length === 0) {
    return (
      <>
        <ChartPlaceholder height={height}>
          No rolled-up GPU series in this window yet
        </ChartPlaceholder>
        {fallbackNames.length ? (
          <ChartLegend
            entries={fallbackNames.map((name, index) => ({
              name,
              color: CHART_SERIES_COLORS[index % CHART_SERIES_COLORS.length],
            }))}
          />
        ) : null}
      </>
    );
  }

  const colorOf = (name: string) =>
    CHART_SERIES_COLORS[names.indexOf(name) % CHART_SERIES_COLORS.length];
  const shown = names.filter((name) => !isHidden(name));
  const rows = toRows(usage, shown);
  const countMode = usage.unit === 'gpus';

  const note =
    usingDefault && hiddenByDefault.length
      ? `Showing the ${DEFAULT_VISIBLE} busiest of ${names.length} types.`
      : undefined;

  return (
    <>
      <ChartFrame $height={height}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <defs>
              {shown.map((name) => (
                <linearGradient
                  key={name}
                  id={`${chartId}-${name}`}
                  x1="0"
                  y1="0"
                  x2="0"
                  y2="1"
                >
                  <stop offset="0%" stopColor={colorOf(name)} stopOpacity={0.2} />
                  <stop offset="100%" stopColor={colorOf(name)} stopOpacity={0} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid
              stroke={theme.chart.grid}
              strokeDasharray="2 4"
              vertical={false}
            />
            <XAxis
              dataKey="slot"
              tickFormatter={tick}
              tick={{ fill: theme.chart.axis, fontSize: 10 }}
              tickLine={false}
              axisLine={{ stroke: theme.chart.grid }}
              minTickGap={18}
            />
            <YAxis
              tick={{ fill: theme.chart.axis, fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              width={38}
              domain={countMode ? [0, 'auto'] : [0, 100]}
              unit={countMode ? '' : '%'}
            />
            <Tooltip
              content={<ChartTooltip suffix={countMode ? ' GPUs' : '%'} />}
              labelFormatter={(label) => slotTitle(String(label ?? ''))}
              cursor={{ stroke: theme.border.color.strong, strokeWidth: 1 }}
            />
            {shown.map((name) => (
              <Area
                key={name}
                type="monotone"
                dataKey={name}
                stroke={colorOf(name)}
                strokeWidth={1.8}
                fill={`url(#${chartId}-${name})`}
                connectNulls={false}
                dot={false}
                activeDot={{ r: 3, strokeWidth: 0 }}
                isAnimationActive={false}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </ChartFrame>
      <ChartLegend
        entries={names.map((name) => ({
          name,
          color: colorOf(name),
          shown: !isHidden(name),
        }))}
        onToggle={toggle}
        note={note}
      />
    </>
  );
};
