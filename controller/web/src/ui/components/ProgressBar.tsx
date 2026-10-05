/** A horizontal meter. The colour follows the value, not the caller. */

import styled from '@emotion/styled';
import type { ReactNode } from 'react';

import type { Theme } from '../theme/theme';

/** Green while there is headroom, amber when tight, red when saturated. */
export const loadColor = (theme: Theme, percent: number): string => {
  if (percent >= 90) return theme.color.red[40];
  if (percent >= 70) return theme.color.yellow[40];
  return theme.color.green[40];
};

/**
 * `flex: 1 1 auto`, not `flex: 1`.
 *
 * `flex: 1` sets a zero basis on the main axis. In a row that is the width,
 * which is what a `Meter` wants; in a column it is the height, and the bar
 * collapses to nothing. An auto basis is right in both.
 */
const Track = styled.div`
  background: ${({ theme }) => theme.background.quaternary};
  border-radius: ${({ theme }) => theme.border.radius.rounded};
  flex: 1 1 auto;
  height: 5px;
  min-width: 0;
  overflow: hidden;
  width: 100%;
`;

const Fill = styled.div<{ $percent: number; $color?: string }>`
  background: ${({ theme, $percent, $color }) => $color ?? loadColor(theme, $percent)};
  border-radius: inherit;
  height: 100%;
  transition: width ${({ theme }) => theme.animation.duration.normal} ease;
  width: ${({ $percent }) => Math.max(0, Math.min(100, $percent))}%;
`;

export const ProgressBar = ({
  percent,
  color,
  className,
}: {
  percent: number;
  color?: string;
  className?: string;
}) => (
  <Track className={className} role="meter" aria-valuenow={Math.round(percent)}>
    <Fill $percent={percent} $color={color} />
  </Track>
);

const MeterRow = styled.div`
  align-items: center;
  display: flex;
  gap: ${({ theme }) => theme.spacing(2)};
  min-height: 26px;
`;

const MeterLabel = styled.span`
  color: ${({ theme }) => theme.font.color.secondary};
  flex-shrink: 0;
  font-size: ${({ theme }) => theme.font.size.sm};
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  /* Capped, so a wide card does not push every bar into its right half. */
  width: min(40%, 190px);
`;

const MeterValue = styled.span`
  color: ${({ theme }) => theme.font.color.primary};
  flex-shrink: 0;
  font-family: ${({ theme }) => theme.font.familyMono};
  font-size: ${({ theme }) => theme.font.size.xs};
  min-width: 56px;
  text-align: right;
  white-space: nowrap;
`;

/** A labelled bar: name on the left, meter in the middle, value on the right. */
export const Meter = ({
  label,
  percent,
  value,
  color,
  title,
}: {
  label: ReactNode;
  percent: number;
  value: ReactNode;
  color?: string;
  title?: string;
}) => (
  <MeterRow title={title}>
    <MeterLabel>{label}</MeterLabel>
    <ProgressBar percent={percent} color={color} />
    <MeterValue>{value}</MeterValue>
  </MeterRow>
);
