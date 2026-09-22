/** Job outcomes over the window: a donut with the counts beside it. */

import { useTheme } from '@emotion/react';
import styled from '@emotion/styled';
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts';

import { fmtCount } from '../controller/format';
import { ChartTooltip } from './ChartParts';
import { EmptyState } from '../../ui/components/EmptyState';

const Row = styled.div`
  align-items: center;
  display: flex;
  gap: ${({ theme }) => theme.spacing(5)};

  @media (max-width: 620px) {
    flex-direction: column;
    gap: ${({ theme }) => theme.spacing(3)};
  }
`;

const DonutBox = styled.div`
  flex-shrink: 0;
  height: 150px;
  position: relative;
  width: 150px;
`;

const Center = styled.div`
  align-items: center;
  display: flex;
  flex-direction: column;
  inset: 0;
  justify-content: center;
  pointer-events: none;
  position: absolute;
`;

const CenterValue = styled.div`
  color: ${({ theme }) => theme.font.color.primary};
  font-size: ${({ theme }) => theme.font.size.xl};
  font-weight: ${({ theme }) => theme.font.weight.semiBold};
  letter-spacing: -0.02em;
`;

const CenterLabel = styled.div`
  color: ${({ theme }) => theme.font.color.tertiary};
  font-size: ${({ theme }) => theme.font.size.xxs};
  letter-spacing: 0.04em;
  text-transform: uppercase;
`;

const Legend = styled.div`
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
`;

const LegendRow = styled.div`
  align-items: center;
  border-bottom: 1px solid ${({ theme }) => theme.border.color.light};
  display: flex;
  font-size: ${({ theme }) => theme.font.size.sm};
  gap: ${({ theme }) => theme.spacing(2)};
  justify-content: space-between;
  padding: ${({ theme }) => theme.spacing(1.5, 0)};

  &:last-of-type {
    border-bottom: none;
  }
`;

const LegendName = styled.span`
  align-items: center;
  color: ${({ theme }) => theme.font.color.secondary};
  display: flex;
  gap: ${({ theme }) => theme.spacing(2)};
`;

const Swatch = styled.i<{ $color: string }>`
  background: ${({ $color }) => $color};
  border-radius: 2px;
  height: 8px;
  width: 8px;
`;

const Value = styled.b`
  color: ${({ theme }) => theme.font.color.primary};
  font-family: ${({ theme }) => theme.font.familyMono};
  font-size: ${({ theme }) => theme.font.size.sm};
`;

const Share = styled.span`
  color: ${({ theme }) => theme.font.color.tertiary};
  font-family: ${({ theme }) => theme.font.familyMono};
  font-size: ${({ theme }) => theme.font.size.xxs};
  margin-left: ${({ theme }) => theme.spacing(1.5)};
`;

export const OutcomeDonut = ({
  counts,
}: {
  counts: Record<string, number> | undefined;
}) => {
  const theme = useTheme();
  const slices = [
    { key: 'COMPLETED', label: 'Completed', color: theme.color.blue[40] },
    { key: 'FAILED', label: 'Failed', color: theme.color.red[40] },
    { key: 'TIMEOUT', label: 'Timeout', color: theme.color.yellow[40] },
    { key: 'CANCELLED', label: 'Cancelled', color: theme.color.gray[40] },
  ];

  const rows = slices.map((slice) => ({
    ...slice,
    name: slice.label,
    value: Number(counts?.[slice.key]) || 0,
  }));
  const total = rows.reduce((sum, row) => sum + row.value, 0);

  if (!total) {
    return (
      <EmptyState title="No finished jobs in this window" compact>
        The outcome mix appears once the rollup holds terminal states for the
        chosen window.
      </EmptyState>
    );
  }

  return (
    <Row>
      <DonutBox>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={rows.filter((row) => row.value > 0)}
              dataKey="value"
              nameKey="name"
              innerRadius={48}
              outerRadius={72}
              paddingAngle={1.5}
              stroke="none"
              isAnimationActive={false}
            >
              {rows
                .filter((row) => row.value > 0)
                .map((row) => (
                  <Cell key={row.key} fill={row.color} />
                ))}
            </Pie>
            <Tooltip content={<ChartTooltip />} />
          </PieChart>
        </ResponsiveContainer>
        <Center>
          <CenterValue>{fmtCount(total)}</CenterValue>
          <CenterLabel>jobs</CenterLabel>
        </Center>
      </DonutBox>
      <Legend>
        {rows.map((row) => (
          <LegendRow key={row.key}>
            <LegendName>
              <Swatch $color={row.color} />
              {row.label}
            </LegendName>
            <span>
              <Value>{fmtCount(row.value)}</Value>
              <Share>{Math.round((row.value / total) * 100)}%</Share>
            </span>
          </LegendRow>
        ))}
      </Legend>
    </Row>
  );
};
