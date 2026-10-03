/** Form controls. Every input in the dashboard is one of these. */

import styled from '@emotion/styled';
import { IconSearch, IconX } from '@tabler/icons-react';
import type {
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from 'react';

const inputSkin = `
  border-radius: 4px;
  border-style: solid;
  border-width: 1px;
  outline: none;
  width: 100%;
`;

const StyledInput = styled.input`
  ${inputSkin}
  background: ${({ theme }) => theme.background.primary};
  border-color: ${({ theme }) => theme.border.color.medium};
  color: ${({ theme }) => theme.font.color.primary};
  font-size: ${({ theme }) => theme.font.size.sm};
  height: 30px;
  padding: ${({ theme }) => theme.spacing(0, 2)};
  transition: ${({ theme }) => theme.animation.clickable};

  &::placeholder {
    color: ${({ theme }) => theme.font.color.light};
  }

  &:hover:not(:disabled) {
    border-color: ${({ theme }) => theme.border.color.strong};
  }

  &:focus {
    border-color: ${({ theme }) => theme.border.color.accent};
    box-shadow: 0 0 0 3px ${({ theme }) => theme.accent.quaternary};
  }

  &:read-only,
  &:disabled {
    background: ${({ theme }) => theme.background.tertiary};
    color: ${({ theme }) => theme.font.color.secondary};
  }
`;

const StyledTextArea = styled.textarea`
  ${inputSkin}
  background: ${({ theme }) => theme.background.primary};
  border-color: ${({ theme }) => theme.border.color.medium};
  color: ${({ theme }) => theme.font.color.primary};
  font-family: ${({ theme }) => theme.font.familyMono};
  font-size: ${({ theme }) => theme.font.size.sm};
  line-height: 1.6;
  padding: ${({ theme }) => theme.spacing(2)};
  resize: vertical;
  transition: ${({ theme }) => theme.animation.clickable};

  &::placeholder {
    color: ${({ theme }) => theme.font.color.light};
  }

  &:focus {
    border-color: ${({ theme }) => theme.border.color.accent};
    box-shadow: 0 0 0 3px ${({ theme }) => theme.accent.quaternary};
  }
`;

const StyledSelect = styled.select`
  ${inputSkin}
  appearance: none;
  background-color: ${({ theme }) => theme.background.primary};
  background-image: linear-gradient(45deg, transparent 50%, currentColor 50%),
    linear-gradient(135deg, currentColor 50%, transparent 50%);
  background-position:
    calc(100% - 14px) 13px,
    calc(100% - 9px) 13px;
  background-repeat: no-repeat;
  background-size:
    5px 5px,
    5px 5px;
  border-color: ${({ theme }) => theme.border.color.medium};
  color: ${({ theme }) => theme.font.color.primary};
  cursor: pointer;
  font-size: ${({ theme }) => theme.font.size.sm};
  height: 30px;
  padding: ${({ theme }) => theme.spacing(0, 7, 0, 2)};
  transition: ${({ theme }) => theme.animation.clickable};

  &:hover:not(:disabled) {
    border-color: ${({ theme }) => theme.border.color.strong};
  }

  &:focus {
    border-color: ${({ theme }) => theme.border.color.accent};
    box-shadow: 0 0 0 3px ${({ theme }) => theme.accent.quaternary};
  }
`;

const StyledLabel = styled.label`
  color: ${({ theme }) => theme.font.color.secondary};
  display: block;
  font-size: ${({ theme }) => theme.font.size.xs};
  font-weight: ${({ theme }) => theme.font.weight.medium};
  margin-bottom: ${({ theme }) => theme.spacing(1.5)};
`;

const FieldWrapper = styled.div`
  min-width: 0;

  & + & {
    margin-top: ${({ theme }) => theme.spacing(3)};
  }
`;

type FieldProps = { label?: ReactNode; children: ReactNode; className?: string };

/** A label above one control. */
export const Field = ({ label, children, className }: FieldProps) => (
  <FieldWrapper className={className}>
    {label ? <StyledLabel>{label}</StyledLabel> : null}
    {children}
  </FieldWrapper>
);

/** Two or three fields on one line, stacking on a narrow window. */
export const FieldRow = styled.div<{ $columns?: number }>`
  display: grid;
  gap: ${({ theme }) => theme.spacing(3)};
  grid-template-columns: repeat(${({ $columns = 2 }) => $columns}, minmax(0, 1fr));
  margin-top: ${({ theme }) => theme.spacing(3)};

  @media (max-width: 720px) {
    grid-template-columns: 1fr;
  }
`;

/**
 * An input with a button pinned to its right.
 *
 * `:first-child`, not `:first-of-type`: the row holds an `input` and a
 * `button`, and each is the first of its own type, so `:first-of-type` would
 * stretch the button as well.
 */
export const InlineRow = styled.div`
  align-items: center;
  display: flex;
  gap: ${({ theme }) => theme.spacing(2)};

  > :first-child {
    flex: 1;
    min-width: 0;
  }
`;

export const TextInput = (props: InputHTMLAttributes<HTMLInputElement>) => (
  <StyledInput {...props} />
);

const SearchShell = styled.div`
  align-items: center;
  background: ${({ theme }) => theme.background.primary};
  border: 1px solid ${({ theme }) => theme.border.color.medium};
  border-radius: ${({ theme }) => theme.border.radius.sm};
  color: ${({ theme }) => theme.font.color.tertiary};
  display: flex;
  gap: ${({ theme }) => theme.spacing(1.5)};
  height: 30px;
  min-width: 0;
  padding: ${({ theme }) => theme.spacing(0, 2)};
  transition: ${({ theme }) => theme.animation.clickable};
  width: 100%;

  &:hover {
    border-color: ${({ theme }) => theme.border.color.strong};
  }

  &:focus-within {
    border-color: ${({ theme }) => theme.border.color.accent};
    box-shadow: 0 0 0 3px ${({ theme }) => theme.accent.quaternary};
  }

  svg {
    flex-shrink: 0;
  }
`;

const SearchNative = styled.input`
  background: transparent;
  border: 0;
  color: ${({ theme }) => theme.font.color.primary};
  flex: 1;
  font-size: ${({ theme }) => theme.font.size.sm};
  min-width: 0;
  outline: none;
  padding: 0;

  &::placeholder {
    color: ${({ theme }) => theme.font.color.light};
  }
`;

const SearchClear = styled.button`
  align-items: center;
  background: transparent;
  border: 0;
  border-radius: ${({ theme }) => theme.border.radius.xs};
  color: ${({ theme }) => theme.font.color.tertiary};
  cursor: pointer;
  display: inline-flex;
  flex-shrink: 0;
  height: 18px;
  justify-content: center;
  padding: 0;
  width: 18px;

  &:hover {
    background: ${({ theme }) => theme.background.transparent.secondary};
    color: ${({ theme }) => theme.font.color.primary};
  }
`;

type SearchFieldProps = InputHTMLAttributes<HTMLInputElement> & {
  /** A count or other note, drawn after the text and before the clear control. */
  trailing?: ReactNode;
  onClear?: () => void;
};

/** A full-width search control. The value matches as the operator types. */
export const SearchField = ({
  trailing,
  onClear,
  value,
  ...rest
}: SearchFieldProps) => {
  const filled = String(value ?? '').length > 0;
  return (
    <SearchShell>
      <IconSearch size={14} stroke={1.6} />
      <SearchNative value={value} {...rest} />
      {trailing}
      {filled && onClear ? (
        <SearchClear type="button" aria-label="Clear search" onClick={onClear}>
          <IconX size={13} stroke={1.8} />
        </SearchClear>
      ) : null}
    </SearchShell>
  );
};

export const TextArea = (props: TextareaHTMLAttributes<HTMLTextAreaElement>) => (
  <StyledTextArea {...props} />
);

export type SelectOption = { value: string; label: string };

export const Select = ({
  options,
  ...rest
}: SelectHTMLAttributes<HTMLSelectElement> & { options: SelectOption[] }) => (
  <StyledSelect {...rest}>
    {options.map((option) => (
      <option key={option.value} value={option.value}>
        {option.label}
      </option>
    ))}
  </StyledSelect>
);

const CheckboxLabel = styled.label`
  align-items: center;
  color: ${({ theme }) => theme.font.color.secondary};
  cursor: pointer;
  display: inline-flex;
  font-size: ${({ theme }) => theme.font.size.sm};
  gap: ${({ theme }) => theme.spacing(2)};
  user-select: none;

  input {
    accent-color: ${({ theme }) => theme.accent.primary};
    cursor: pointer;
    height: 14px;
    margin: 0;
    width: 14px;
  }
`;

export const Checkbox = ({
  label,
  ...rest
}: InputHTMLAttributes<HTMLInputElement> & { label: ReactNode }) => (
  <CheckboxLabel>
    <input type="checkbox" {...rest} />
    {label}
  </CheckboxLabel>
);

const StyledToggle = styled.button<{ $on: boolean }>`
  background: ${({ theme, $on }) =>
    $on ? theme.accent.primary : theme.background.quaternary};
  border: none;
  border-radius: ${({ theme }) => theme.border.radius.rounded};
  cursor: pointer;
  flex-shrink: 0;
  height: 16px;
  padding: 0;
  position: relative;
  transition: background ${({ theme }) => theme.animation.duration.normal} ease;
  width: 28px;

  &::after {
    background: ${({ theme }) => theme.grayScale.gray0};
    border-radius: 50%;
    content: '';
    height: 12px;
    left: ${({ $on }) => ($on ? '14px' : '2px')};
    position: absolute;
    top: 2px;
    transition: left ${({ theme }) => theme.animation.duration.normal} ease;
    width: 12px;
  }

  &:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }
`;

export const Toggle = ({
  value,
  onChange,
  disabled,
  'aria-label': ariaLabel,
}: {
  value: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  'aria-label'?: string;
}) => (
  <StyledToggle
    type="button"
    role="switch"
    aria-checked={value}
    aria-label={ariaLabel}
    disabled={disabled}
    $on={value}
    onClick={() => onChange(!value)}
  />
);
