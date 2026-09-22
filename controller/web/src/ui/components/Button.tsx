/** Buttons. One shape, four variants, three sizes. */

import styled from '@emotion/styled';
import type { ButtonHTMLAttributes } from 'react';

import type { IconComponent } from '../types';

export type ButtonVariant = 'primary' | 'secondary' | 'tertiary' | 'danger';
export type ButtonSize = 'small' | 'medium' | 'large';

type Base = {
  variant?: ButtonVariant;
  size?: ButtonSize;
};

const HEIGHT: Record<ButtonSize, string> = {
  small: '26px',
  medium: '30px',
  large: '36px',
};

const StyledButton = styled.button<Required<Base>>`
  align-items: center;
  border-radius: ${({ theme }) => theme.border.radius.sm};
  border-style: solid;
  border-width: 1px;
  cursor: pointer;
  display: inline-flex;
  flex-shrink: 0;
  font-size: ${({ theme, size }) =>
    size === 'large' ? theme.font.size.md : theme.font.size.sm};
  font-weight: ${({ theme }) => theme.font.weight.medium};
  gap: ${({ theme }) => theme.spacing(1.5)};
  height: ${({ size }) => HEIGHT[size]};
  justify-content: center;
  padding: ${({ theme, size }) =>
    size === 'small' ? theme.spacing(0, 2) : theme.spacing(0, 2.5)};
  transition: ${({ theme }) => theme.animation.clickable};
  white-space: nowrap;

  ${({ theme, variant }) => {
    if (variant === 'primary') {
      return `
        background: ${theme.accent.primary};
        border-color: ${theme.accent.primary};
        color: ${theme.name === 'dark' ? theme.grayScale.gray95 : theme.grayScale.gray0};
        &:hover:not(:disabled) { filter: brightness(1.08); }
      `;
    }
    if (variant === 'danger') {
      return `
        background: ${theme.background.transparent.danger};
        border-color: ${theme.border.color.danger};
        color: ${theme.font.color.danger};
        &:hover:not(:disabled) { background: ${theme.background.danger}; }
      `;
    }
    if (variant === 'tertiary') {
      return `
        background: transparent;
        border-color: transparent;
        color: ${theme.font.color.secondary};
        &:hover:not(:disabled) {
          background: ${theme.background.transparent.secondary};
          color: ${theme.font.color.primary};
        }
      `;
    }
    return `
      background: ${theme.background.secondary};
      border-color: ${theme.border.color.medium};
      color: ${theme.font.color.primary};
      &:hover:not(:disabled) {
        background: ${theme.background.tertiary};
        border-color: ${theme.border.color.strong};
      }
    `;
  }}

  &:disabled {
    cursor: not-allowed;
    opacity: 0.45;
  }
`;

export type ButtonProps = Base &
  ButtonHTMLAttributes<HTMLButtonElement> & {
    /** A small icon from `@tabler/icons-react`, drawn before the label. */
    Icon?: IconComponent;
  };

export const Button = ({
  variant = 'secondary',
  size = 'medium',
  Icon,
  children,
  type = 'button',
  ...rest
}: ButtonProps) => (
  <StyledButton variant={variant} size={size} type={type} {...rest}>
    {Icon ? <Icon size={14} stroke={1.8} /> : null}
    {children}
  </StyledButton>
);

const StyledIconButton = styled.button<{ $active: boolean }>`
  align-items: center;
  background: ${({ theme, $active }) =>
    $active ? theme.background.transparent.secondary : 'transparent'};
  border: 1px solid transparent;
  border-radius: ${({ theme }) => theme.border.radius.sm};
  color: ${({ theme, $active }) =>
    $active ? theme.font.color.primary : theme.font.color.tertiary};
  cursor: pointer;
  display: inline-flex;
  height: 26px;
  justify-content: center;
  transition: ${({ theme }) => theme.animation.clickable};
  width: 26px;

  &:hover:not(:disabled) {
    background: ${({ theme }) => theme.background.transparent.secondary};
    color: ${({ theme }) => theme.font.color.primary};
  }

  &:disabled {
    cursor: not-allowed;
    opacity: 0.45;
  }
`;

export type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  Icon: IconComponent;
  active?: boolean;
};

export const IconButton = ({
  Icon,
  active = false,
  type = 'button',
  ...rest
}: IconButtonProps) => (
  <StyledIconButton $active={active} type={type} {...rest}>
    <Icon size={16} stroke={1.8} />
  </StyledIconButton>
);

/** A row of buttons, right-aligned by default. */
export const ButtonGroup = styled.div<{ align?: 'left' | 'right' }>`
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: ${({ theme }) => theme.spacing(2)};
  justify-content: ${({ align = 'left' }) =>
    align === 'right' ? 'flex-end' : 'flex-start'};
`;
