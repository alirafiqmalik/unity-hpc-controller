/** The KPI tile: one big number, its unit, and a line that qualifies it. */

import styled from '@emotion/styled';
import type { ReactNode } from 'react';

import type { ThemeColor } from '../theme/colors';
import type { IconComponent } from '../types';

const Wrapper = styled.div<{ $accent?: ThemeColor }>`
  background: ${({ theme }) => theme.background.secondary};
  border: 1px solid ${({ theme }) => theme.border.color.light};
  border-radius: ${({ theme }) => theme.border.radius.md};
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.spacing(1)};
  min-width: 0;
  padding: ${({ theme }) => theme.spacing(3.5, 4)};
  position: relative;

  &::before {
    background: ${({ theme, $accent }) =>
      $accent ? theme.tag.text[$accent] : 'transparent'};
    border-radius: ${({ theme }) =>
      `${theme.border.radius.md} 0 0 ${theme.border.radius.md}`};
    bottom: 0;
    content: '';
    left: 0;
    position: absolute;
    top: 0;
    width: 2px;
  }
`;

const Label = styled.div`
  align-items: center;
  color: ${({ theme }) => theme.font.color.tertiary};
  display: flex;
  font-size: ${({ theme }) => theme.font.size.xs};
  font-weight: ${({ theme }) => theme.font.weight.medium};
  gap: ${({ theme }) => theme.spacing(1.5)};
  letter-spacing: 0.03em;
  text-transform: uppercase;
`;

const Value = styled.div`
  align-items: baseline;
  color: ${({ theme }) => theme.font.color.primary};
  display: flex;
  font-size: ${({ theme }) => theme.font.size.xxl};
  font-weight: ${({ theme }) => theme.font.weight.semiBold};
  gap: ${({ theme }) => theme.spacing(1)};
  letter-spacing: -0.02em;
  line-height: 1.1;
  min-width: 0;
`;

const Unit = styled.span`
  color: ${({ theme }) => theme.font.color.tertiary};
  font-size: ${({ theme }) => theme.font.size.md};
  font-weight: ${({ theme }) => theme.font.weight.regular};
`;

const Caption = styled.div`
  color: ${({ theme }) => theme.font.color.secondary};
  font-size: ${({ theme }) => theme.font.size.xs};
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

export type StatCardProps = {
  label: ReactNode;
  value: ReactNode;
  /** The smaller text beside the value, such as `/ 544`. */
  unit?: ReactNode;
  caption?: ReactNode;
  accent?: ThemeColor;
  Icon?: IconComponent;
};

export const StatCard = ({
  label,
  value,
  unit,
  caption,
  accent,
  Icon,
}: StatCardProps) => (
  <Wrapper $accent={accent}>
    <Label>
      {Icon ? <Icon size={13} stroke={1.8} /> : null}
      {label}
    </Label>
    <Value>
      {value}
      {unit ? <Unit>{unit}</Unit> : null}
    </Value>
    {caption ? <Caption title={typeof caption === 'string' ? caption : undefined}>{caption}</Caption> : null}
  </Wrapper>
);
