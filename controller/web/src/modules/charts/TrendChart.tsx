/** Queue depth over the live trend: pending against running. */

import { useTheme } from '@emotion/react';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import type { TrendPoint } from '../controller/types';
import { ChartFrame, ChartLegend, ChartPlaceholder, ChartTooltip } from './ChartParts';

/** Keep the clock time only: the full stamp does not fit an axis tick. */
const tickOf = (stamp: string): string => {
  const text = String(stamp ?? '');
  const time = text.includes(' ') ? text.split(' ')[1] : text;
  return time.slice(0, 5);
};

export const TrendChart = ({
  trend,
  height = 190,
}: {
  trend: TrendPoint[];
  height?: number;
}) => {
  const theme = useTheme();
  const series = [
    { key: 'pending', name: 'pending', color: theme.color.yellow[40] },
    { key: 'running', name: 'running', color: theme.color.green[40] },
  ];

  if (!trend.length) {
    return (
      <>
        <ChartPlaceholder height={height}>
          No queue samples in the live snapshot yet
        </ChartPlaceholder>
        <ChartLegend entries={series.map((one) => ({ name: one.name, color: one.color }))} />
      </>
    );
  }

  const rows = trend.map((point) => ({
    t: tickOf(point.t),
    pending: Number(point.pending) || 0,
    running: Number(point.running) || 0,
  }));

  return (
    <>
      <ChartFrame $height={height}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid
              stroke={theme.chart.grid}
              strokeDasharray="2 4"
              vertical={false}
            />
            <XAxis
              dataKey="t"
              tick={{ fill: theme.chart.axis, fontSize: 10 }}
              tickLine={false}
              axisLine={{ stroke: theme.chart.grid }}
              minTickGap={26}
            />
            <YAxis
              tick={{ fill: theme.chart.axis, fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              width={38}
              allowDecimals={false}
            />
            <Tooltip
              content={<ChartTooltip />}
              cursor={{ stroke: theme.border.color.strong, strokeWidth: 1 }}
            />
            {series.map((one) => (
              <Line
                key={one.key}
                type="monotone"
                dataKey={one.key}
                name={one.name}
                stroke={one.color}
                strokeWidth={1.8}
                dot={false}
                activeDot={{ r: 3, strokeWidth: 0 }}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </ChartFrame>
      <ChartLegend entries={series.map((one) => ({ name: one.name, color: one.color }))} />
    </>
  );
};
