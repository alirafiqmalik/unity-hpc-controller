/** Cards, section headings and the grids that hold them. */

import styled from '@emotion/styled';
import type { ReactNode } from 'react';

export const Card = styled.section<{ $padded?: boolean }>`
  background: ${({ theme }) => theme.background.secondary};
  border: 1px solid ${({ theme }) => theme.border.color.light};
  border-radius: ${({ theme }) => theme.border.radius.md};
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  padding: ${({ theme, $padded = true }) => ($padded ? theme.spacing(4) : '0')};
`;

const StyledCardHeader = styled.header`
  align-items: baseline;
  display: flex;
  gap: ${({ theme }) => theme.spacing(3)};
  justify-content: space-between;
  margin-bottom: ${({ theme }) => theme.spacing(3)};
  min-height: 20px;

  @media (max-width: 600px) {
    align-items: flex-start;
    flex-direction: column;
    gap: ${({ theme }) => theme.spacing(1)};
  }
`;

const CardTitle = styled.h3`
  color: ${({ theme }) => theme.font.color.primary};
  font-size: ${({ theme }) => theme.font.size.md};
  font-weight: ${({ theme }) => theme.font.weight.semiBold};
  letter-spacing: -0.01em;
`;

const CardNote = styled.div<{ $warn?: boolean }>`
  color: ${({ theme, $warn }) =>
    $warn ? theme.color.yellow[40] : theme.font.color.tertiary};
  flex-shrink: 0;
  font-size: ${({ theme }) => theme.font.size.xs};
  text-align: right;

  @media (max-width: 600px) {
    flex-shrink: 1;
    text-align: left;
    overflow-wrap: anywhere;
  }
`;

export type CardHeaderProps = {
  title: ReactNode;
  /** The right-hand note: a window, a count, a staleness warning. */
  note?: ReactNode;
  /** Draw the note in the warning colour. */
  warn?: boolean;
  action?: ReactNode;
};

export const CardHeader = ({ title, note, warn, action }: CardHeaderProps) => (
  <StyledCardHeader>
    <CardTitle>{title}</CardTitle>
    {action ?? (note ? <CardNote $warn={warn}>{note}</CardNote> : null)}
  </StyledCardHeader>
);

/** A responsive grid. `min` is the narrowest a column may get. */
export const Grid = styled.div<{ $min?: string; $columns?: number }>`
  display: grid;
  gap: ${({ theme }) => theme.spacing(3)};
  grid-template-columns: ${({ $min = '240px', $columns }) =>
    $columns
      ? `repeat(${$columns}, minmax(0, 1fr))`
      : `repeat(auto-fit, minmax(min(${$min}, 100%), 1fr))`};

  @media (max-width: 900px) {
    grid-template-columns: 1fr;
  }
`;

/** Two columns where the first is twice the width of the second. */
export const SplitGrid = styled.div`
  display: grid;
  gap: ${({ theme }) => theme.spacing(3)};
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);

  @media (max-width: 1100px) {
    grid-template-columns: 1fr;
  }
`;

/** A vertical run of cards that keeps the page gap. */
export const Stack = styled.div<{ $gap?: number }>`
  display: flex;
  flex-direction: column;
  gap: ${({ theme, $gap = 3 }) => theme.spacing($gap)};
  min-width: 0;
`;

/** One label-and-value line inside a card. */
const StyledKeyValue = styled.div`
  align-items: center;
  border-bottom: 1px solid ${({ theme }) => theme.border.color.light};
  display: flex;
  font-size: ${({ theme }) => theme.font.size.sm};
  gap: ${({ theme }) => theme.spacing(3)};
  justify-content: space-between;
  min-height: 30px;
  padding: ${({ theme }) => theme.spacing(1, 0)};

  &:last-of-type {
    border-bottom: none;
  }
`;

const KeyLabel = styled.span`
  color: ${({ theme }) => theme.font.color.secondary};
  flex-shrink: 0;
`;

const KeyValueBody = styled.span<{ $mono: boolean }>`
  color: ${({ theme }) => theme.font.color.primary};
  font-family: ${({ theme, $mono }) => ($mono ? theme.font.familyMono : 'inherit')};
  font-weight: ${({ theme }) => theme.font.weight.medium};
  min-width: 0;
  overflow: hidden;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

export const KeyValue = ({
  label,
  children,
  mono = true,
  title,
}: {
  label: ReactNode;
  children: ReactNode;
  mono?: boolean;
  title?: string;
}) => (
  <StyledKeyValue>
    <KeyLabel>{label}</KeyLabel>
    <KeyValueBody $mono={mono} title={title}>
      {children}
    </KeyValueBody>
  </StyledKeyValue>
);

/** The explanatory sentence under a control. */
export const Hint = styled.p`
  color: ${({ theme }) => theme.font.color.tertiary};
  font-size: ${({ theme }) => theme.font.size.xs};
  line-height: 1.55;
  margin-top: ${({ theme }) => theme.spacing(3)};

  code {
    background: ${({ theme }) => theme.background.tertiary};
    border-radius: ${({ theme }) => theme.border.radius.xs};
    font-size: ${({ theme }) => theme.font.size.xxs};
    padding: 1px 4px;
  }
`;

/** Monospaced inline text: a job id, a path, a host. */
export const Mono = styled.span`
  font-family: ${({ theme }) => theme.font.familyMono};
  font-size: ${({ theme }) => theme.font.size.sm};
`;
