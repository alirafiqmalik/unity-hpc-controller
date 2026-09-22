/**
 * Transient notices, in the bottom-right corner.
 *
 * `useToast()` returns one function. The provider holds the queue, so a notice
 * outlives the component that raised it — a page can navigate away while a
 * dispatch is still reporting its answer.
 */

import styled from '@emotion/styled';
import { IconAlertTriangle, IconCheck, IconInfoCircle } from '@tabler/icons-react';
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

export type ToastVariant = 'info' | 'success' | 'error';

type ToastRecord = { id: number; text: string; variant: ToastVariant };

type ToastFn = (text: string, variant?: ToastVariant) => void;

const ToastContext = createContext<ToastFn>(() => {});

export const useToast = (): ToastFn => useContext(ToastContext);

const Region = styled.div`
  bottom: ${({ theme }) => theme.spacing(4)};
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.spacing(2)};
  position: fixed;
  right: ${({ theme }) => theme.spacing(4)};
  z-index: ${({ theme }) => theme.zIndex.toast};
`;

const Item = styled.div<{ $variant: ToastVariant }>`
  align-items: flex-start;
  animation: slide-in ${({ theme }) => theme.animation.duration.normal} ease;
  background: ${({ theme }) => theme.background.secondary};
  border: 1px solid
    ${({ theme, $variant }) =>
      $variant === 'error'
        ? theme.border.color.danger
        : $variant === 'success'
          ? theme.color.green[40]
          : theme.border.color.strong};
  border-radius: ${({ theme }) => theme.border.radius.md};
  box-shadow: ${({ theme }) => theme.boxShadow.strong};
  color: ${({ theme }) => theme.font.color.primary};
  display: flex;
  font-size: ${({ theme }) => theme.font.size.sm};
  gap: ${({ theme }) => theme.spacing(2)};
  line-height: 1.5;
  max-width: 440px;
  padding: ${({ theme }) => theme.spacing(2.5, 3)};
  word-break: break-word;

  svg {
    flex-shrink: 0;
    margin-top: 1px;
  }

  @keyframes slide-in {
    from {
      opacity: 0;
      transform: translateY(6px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }
`;

const ICON = {
  info: IconInfoCircle,
  success: IconCheck,
  error: IconAlertTriangle,
};

export const ToastProvider = ({ children }: { children: ReactNode }) => {
  const [items, setItems] = useState<ToastRecord[]>([]);
  const nextId = useRef(1);

  const toast = useCallback<ToastFn>((text, variant = 'info') => {
    const id = nextId.current++;
    setItems((current) => [...current, { id, text, variant }].slice(-4));
    window.setTimeout(
      () => setItems((current) => current.filter((item) => item.id !== id)),
      variant === 'error' ? 6000 : 3200,
    );
  }, []);

  const value = useMemo(() => toast, [toast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <Region role="status" aria-live="polite">
        {items.map((item) => {
          const Icon = ICON[item.variant];
          return (
            <Item key={item.id} $variant={item.variant}>
              <Icon size={15} stroke={1.8} />
              <span>{item.text}</span>
            </Item>
          );
        })}
      </Region>
    </ToastContext.Provider>
  );
};
