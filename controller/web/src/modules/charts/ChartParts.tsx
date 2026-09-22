/** Pieces every chart shares: the tooltip, the legend and the frame. */

import styled from '@emotion/styled';
import type { ReactNode } from 'react';

const TooltipCard = styled.div`
  background: ${({ theme }) => theme.background.secondary};
  border: 1px solid ${({ theme }) => theme.border.color.medium};
  border-radius: ${({ theme }) => theme.border.radius.sm};
  box-shadow: ${({ theme }) => theme.boxShadow.medium};
  font-size: ${({ theme }) => theme.font.size.xs};
  min-width: 120px;
  padding: ${({ theme }) => theme.spacing(2)};
`;

const TooltipTitle = styled.div`
  color: ${({ theme }) => theme.font.color.tertiary};
  font-family: ${({ theme }) => theme.font.familyMono};
  margin-bottom: ${({ theme }) => theme.spacing(1.5)};
`;

const TooltipRow = styled.div`
  align-items: center;
  display: flex;
  gap: ${({ theme }) => theme.spacing(2)};
  justify-content: space-between;
  line-height: 1.7;
`;

const Swatch = styled.i<{ $color: string }>`
  background: ${({ $color }) => $color};
  border-radius: 2px;
  display: inline-block;
  flex-shrink: 0;
  height: 8px;
  margin-right: ${({ theme }) => theme.spacing(1.5)};
  width: 8px;
`;

const TooltipName = styled.span`
  align-items: center;
  color: ${({ theme }) => theme.font.color.secondary};
  display: flex;
`;

const TooltipValue = styled.b`
  color: ${({ theme }) => theme.font.color.primary};
  font-family: ${({ theme }) => theme.font.familyMono};
`;

type TooltipEntry = {
  name?: string | number;
  value?: string | number;
  color?: string;
  dataKey?: string | number;
};

/** The tooltip body Recharts renders through its `content` prop. */
export const ChartTooltip = ({
  active,
  payload,
  label,
  suffix = '',
}: {
  active?: boolean;
  payload?: TooltipEntry[];
  label?: string | number;
  suffix?: string;
}) => {
  if (!active || !payload?.length) return null;
  return (
    <TooltipCard>
      {label !== undefined ? <TooltipTitle>{String(label)}</TooltipTitle> : null}
      {payload.map((entry) => (
        <TooltipRow key={String(entry.dataKey ?? entry.name)}>
          <TooltipName>
            <Swatch $color={entry.color ?? 'currentColor'} />
            {String(entry.name ?? entry.dataKey ?? '')}
          </TooltipName>
          <TooltipValue>
            {entry.value === null || entry.value === undefined
              ? '—'
              : `${entry.value}${suffix}`}
          </TooltipValue>
        </TooltipRow>
      ))}
    </TooltipCard>
  );
};

const LegendRow = styled.div`
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: ${({ theme }) => theme.spacing(1)} ${({ theme }) => theme.spacing(3)};
  margin-top: ${({ theme }) => theme.spacing(2)};
`;

const LegendHint = styled.p`
  color: ${({ theme }) => theme.font.color.light};
  font-size: ${({ theme }) => theme.font.size.xxs};
  margin-top: ${({ theme }) => theme.spacing(2.5)};
`;

const LegendPick = styled.button<{ $shown: boolean }>`
  align-items: center;
  background: transparent;
  border: 1px solid transparent;
  border-radius: ${({ theme }) => theme.border.radius.sm};
  color: ${({ theme }) => theme.font.color.secondary};
  cursor: pointer;
  display: inline-flex;
  font-size: ${({ theme }) => theme.font.size.xs};
  gap: ${({ theme }) => theme.spacing(1.5)};
  opacity: ${({ $shown }) => ($shown ? 1 : 0.4)};
  padding: ${({ theme }) => theme.spacing(0.5, 1.5)};
  transition: ${({ theme }) => theme.animation.clickable};
  user-select: none;

  &:hover {
    background: ${({ theme }) => theme.background.transparent.primary};
    color: ${({ theme }) => theme.font.color.primary};
  }
`;

const LegendStatic = styled.span`
  align-items: center;
  color: ${({ theme }) => theme.font.color.secondary};
  display: inline-flex;
  font-size: ${({ theme }) => theme.font.size.xs};
  gap: ${({ theme }) => theme.spacing(1.5)};
`;

export type LegendEntry = { name: string; color: string; shown?: boolean };

/**
 * The legend.
 *
 * With `onToggle` it is also the series filter, and it says so: a first look
 * must show that a name is a control, because a hover tip does not.
 */
export const ChartLegend = ({
  entries,
  onToggle,
}: {
  entries: LegendEntry[];
  onToggle?: (name: string) => void;
}) => (
  <>
    {onToggle ? <LegendHint>Click a name to show or hide it.</LegendHint> : null}
    <LegendRow>
      {entries.map((entry) =>
        onToggle ? (
          <LegendPick
            key={entry.name}
            type="button"
            $shown={entry.shown !== false}
            aria-pressed={entry.shown !== false}
            title={`${entry.shown !== false ? 'Hide' : 'Show'} ${entry.name}`}
            onClick={() => onToggle(entry.name)}
          >
            <Swatch $color={entry.color} />
            {entry.name}
          </LegendPick>
        ) : (
          <LegendStatic key={entry.name}>
            <Swatch $color={entry.color} />
            {entry.name}
          </LegendStatic>
        ),
      )}
    </LegendRow>
  </>
);

/**
 * A fixed-height box so a chart does not resize the card while it loads.
 *
 * No negative margin: the card clips its overflow, so a chart pulled left
 * loses its axis labels rather than gaining width.
 */
export const ChartFrame = styled.div<{ $height?: number }>`
  height: ${({ $height = 190 }) => $height}px;
  min-width: 0;
  width: 100%;
`;

export const ChartPlaceholder = ({
  height = 190,
  children,
}: {
  height?: number;
  children: ReactNode;
}) => (
  <PlaceholderBox style={{ height }}>
    <span>{children}</span>
  </PlaceholderBox>
);

const PlaceholderBox = styled.div`
  align-items: center;
  background: ${({ theme }) => theme.background.primary};
  border: 1px dashed ${({ theme }) => theme.border.color.light};
  border-radius: ${({ theme }) => theme.border.radius.sm};
  color: ${({ theme }) => theme.font.color.light};
  display: flex;
  font-size: ${({ theme }) => theme.font.size.xs};
  justify-content: center;
  text-align: center;
`;
