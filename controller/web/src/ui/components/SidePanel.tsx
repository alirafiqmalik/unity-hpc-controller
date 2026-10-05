/**
 * The right-hand side panel, and the modal that sits over everything.
 *
 * Both close on Escape and on a click outside, and both trap nothing: the
 * dashboard has no nested panel, so the browser's own focus order is correct.
 */

import styled from '@emotion/styled';
import { IconX } from '@tabler/icons-react';
import { useEffect, type ReactNode } from 'react';

import { IconButton } from './Button';

const Overlay = styled.div<{ $open: boolean }>`
  background: ${({ theme }) => theme.background.overlay};
  inset: 0;
  opacity: ${({ $open }) => ($open ? 1 : 0)};
  pointer-events: ${({ $open }) => ($open ? 'auto' : 'none')};
  position: fixed;
  transition: opacity ${({ theme }) => theme.animation.duration.normal} ease;
  z-index: ${({ theme }) => theme.zIndex.overlay};
`;

const Panel = styled.aside<{ $open: boolean }>`
  background: ${({ theme }) => theme.background.primary};
  border-left: 1px solid ${({ theme }) => theme.border.color.medium};
  bottom: 0;
  box-shadow: ${({ theme }) => theme.boxShadow.strong};
  display: flex;
  flex-direction: column;
  max-width: 100vw;
  position: fixed;
  right: 0;
  top: 0;
  transform: translateX(${({ $open }) => ($open ? '0' : '100%')});
  transition: transform ${({ theme }) => theme.animation.duration.normal} ease;
  width: ${({ theme }) => theme.sidePanel.width};
  z-index: ${({ theme }) => theme.zIndex.sidePanel};
`;

const Head = styled.header`
  align-items: flex-start;
  border-bottom: 1px solid ${({ theme }) => theme.border.color.light};
  display: flex;
  gap: ${({ theme }) => theme.spacing(3)};
  justify-content: space-between;
  padding: ${({ theme }) => theme.spacing(4)};
`;

const Title = styled.h2`
  font-family: ${({ theme }) => theme.font.familyMono};
  font-size: ${({ theme }) => theme.font.size.lg};
  font-weight: ${({ theme }) => theme.font.weight.semiBold};
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

const Subtitle = styled.div`
  color: ${({ theme }) => theme.font.color.tertiary};
  font-size: ${({ theme }) => theme.font.size.xs};
  margin-top: ${({ theme }) => theme.spacing(1)};
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

const Body = styled.div`
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: ${({ theme }) => theme.spacing(3)};
  min-height: 0;
  overflow-y: auto;
  padding: ${({ theme }) => theme.spacing(4)};

  > * {
    flex-shrink: 0;
  }
`;

/** Close on Escape while `open`. */
const useEscape = (open: boolean, onClose: () => void) => {
  useEffect(() => {
    if (!open) return;
    const listen = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', listen);
    return () => window.removeEventListener('keydown', listen);
  }, [open, onClose]);
};

export const SidePanel = ({
  open,
  onClose,
  title,
  subtitle,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
}) => {
  useEscape(open, onClose);

  return (
    <>
      <Overlay $open={open} onClick={onClose} />
      <Panel $open={open} aria-hidden={!open}>
        {open ? (
          <>
            <Head>
              <div style={{ minWidth: 0 }}>
                <Title>{title}</Title>
                {subtitle ? <Subtitle>{subtitle}</Subtitle> : null}
              </div>
              <IconButton Icon={IconX} onClick={onClose} aria-label="Close panel" />
            </Head>
            <Body>{children}</Body>
          </>
        ) : null}
      </Panel>
    </>
  );
};

const ModalOverlay = styled.div`
  align-items: center;
  background: ${({ theme }) => theme.background.overlay};
  display: flex;
  inset: 0;
  justify-content: center;
  padding: ${({ theme }) => theme.spacing(4)};
  position: fixed;
  z-index: ${({ theme }) => theme.zIndex.modal};
`;

const ModalCard = styled.div`
  background: ${({ theme }) => theme.background.secondary};
  border: 1px solid ${({ theme }) => theme.border.color.medium};
  border-radius: ${({ theme }) => theme.border.radius.lg};
  box-shadow: ${({ theme }) => theme.boxShadow.strong};
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.spacing(3)};
  max-width: 100%;
  padding: ${({ theme }) => theme.spacing(5)};
  width: 420px;
`;

const ModalTitle = styled.h3`
  font-size: ${({ theme }) => theme.font.size.lg};
  font-weight: ${({ theme }) => theme.font.weight.semiBold};
`;

export const Modal = ({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
}) => {
  useEscape(open, onClose);
  if (!open) return null;

  return (
    <ModalOverlay onClick={onClose} role="dialog" aria-modal="true">
      <ModalCard onClick={(event) => event.stopPropagation()}>
        <ModalTitle>{title}</ModalTitle>
        {children}
      </ModalCard>
    </ModalOverlay>
  );
};
