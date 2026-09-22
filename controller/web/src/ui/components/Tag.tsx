/** Tags and chips: one small coloured label for a state or a category. */

import styled from '@emotion/styled';
import type { ReactNode } from 'react';

import type { ThemeColor } from '../theme/colors';

const StyledTag = styled.span<{ $color: ThemeColor; $mono: boolean }>`
  align-items: center;
  background: ${({ theme, $color }) => theme.tag.background[$color]};
  border-radius: ${({ theme }) => theme.border.radius.sm};
  color: ${({ theme, $color }) => theme.tag.text[$color]};
  display: inline-flex;
  flex-shrink: 0;
  font-family: ${({ theme, $mono }) => ($mono ? theme.font.familyMono : 'inherit')};
  font-size: ${({ theme }) => theme.font.size.xs};
  font-weight: ${({ theme }) => theme.font.weight.medium};
  gap: ${({ theme }) => theme.spacing(1)};
  height: 20px;
  line-height: 1;
  max-width: 100%;
  overflow: hidden;
  padding: ${({ theme }) => theme.spacing(0, 1.5)};
  text-overflow: ellipsis;
  white-space: nowrap;
`;

const Dot = styled.span<{ $color: ThemeColor }>`
  background: ${({ theme, $color }) => theme.tag.text[$color]};
  border-radius: 50%;
  flex-shrink: 0;
  height: 5px;
  width: 5px;
`;

const PulsingDot = styled(Dot)`
  animation: pulse 1.8s ease-in-out infinite;

  @keyframes pulse {
    0%,
    100% {
      opacity: 1;
    }
    50% {
      opacity: 0.3;
    }
  }
`;

export type TagProps = {
  color?: ThemeColor;
  text: ReactNode;
  /** Draw a leading dot. `pulsing` marks a state that is still moving. */
  dot?: boolean | 'pulsing';
  mono?: boolean;
  title?: string;
  className?: string;
};

export const Tag = ({
  color = 'gray',
  text,
  dot = false,
  mono = false,
  title,
  className,
}: TagProps) => (
  <StyledTag $color={color} $mono={mono} title={title} className={className}>
    {dot === 'pulsing' ? <PulsingDot $color={color} /> : null}
    {dot === true ? <Dot $color={color} /> : null}
    {text}
  </StyledTag>
);

/** A horizontal run of tags that wraps instead of overflowing. */
export const TagRow = styled.div`
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: ${({ theme }) => theme.spacing(1.5)};
`;

/** A selectable chip, used for the job filter and the time-window picker. */
export const Chip = styled.button<{ $active: boolean }>`
  background: ${({ theme, $active }) =>
    $active ? theme.accent.tertiary : 'transparent'};
  border: 1px solid
    ${({ theme, $active }) =>
      $active ? theme.border.color.accent : theme.border.color.medium};
  border-radius: ${({ theme }) => theme.border.radius.rounded};
  color: ${({ theme, $active }) =>
    $active ? theme.accent.primary : theme.font.color.secondary};
  cursor: pointer;
  font-size: ${({ theme }) => theme.font.size.xs};
  font-weight: ${({ theme }) => theme.font.weight.medium};
  height: 24px;
  padding: ${({ theme }) => theme.spacing(0, 2)};
  transition: ${({ theme }) => theme.animation.clickable};
  white-space: nowrap;

  &:hover {
    border-color: ${({ theme }) => theme.border.color.strong};
    color: ${({ theme }) => theme.font.color.primary};
  }
`;

export const ChipRow = styled.div`
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: ${({ theme }) => theme.spacing(1.5)};
`;
