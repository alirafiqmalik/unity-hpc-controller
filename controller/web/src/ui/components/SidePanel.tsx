/**
 * The right-hand side panel, and the modal that sits over everything.
 *
 * Both close on Escape and on a click outside. Modal dialogs use the native
 * top layer for focus containment and an inert background.
 */

import styled from '@emotion/styled';
import { IconX } from '@tabler/icons-react';
import { useEffect, useRef, useId, type ReactNode } from 'react';

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

const ModalOverlay = styled.dialog`
  border: 0;
  height: 100dvh;
  margin: 0;
  max-height: none;
  max-width: none;
  overscroll-behavior: contain;
  width: 100vw;

  &::backdrop { background: transparent; }
  align-items: center;
  background: ${({ theme }) => theme.background.overlay};
  display: flex;
  inset: 0;
  justify-content: center;
  padding: ${({ theme }) => theme.spacing(4)};
  position: fixed;
  z-index: ${({ theme }) => theme.zIndex.modal};
`;

const ModalCard = styled.div<{ $width: number }>`
  background: ${({ theme }) => theme.background.secondary};
  border: 1px solid ${({ theme }) => theme.border.color.medium};
  border-radius: ${({ theme }) => theme.border.radius.lg};
  box-shadow: ${({ theme }) => theme.boxShadow.strong};
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.spacing(3)};
  max-height: calc(100dvh - 32px);
  max-width: 100%;
  padding: ${({ theme }) => theme.spacing(5)};
  width: ${({ $width }) => $width}px;
`;

const ModalContent = styled.div`
  overscroll-behavior: contain;
  min-height: 0;
  overflow-y: auto;
`;

const ModalFooter = styled.div`
  flex-shrink: 0;
`;

const ModalTitle = styled.h3`
  flex-shrink: 0;
  font-size: ${({ theme }) => theme.font.size.lg};
  font-weight: ${({ theme }) => theme.font.weight.semiBold};
`;

export const Modal = ({
  open,
  onClose,
  title,
  children,
  width = 420,
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  /** The card width in pixels. It never exceeds the viewport. */
  width?: number;
  footer?: ReactNode;
}) => {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    if (!open) return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog.showModal();
    return () => {
      dialog.close();
      if (trigger?.isConnected) trigger.focus({ preventScroll: true });
    };
  }, [open]);
  if (!open) return null;

  return (
    <ModalOverlay ref={dialogRef} aria-labelledby={titleId} onClick={onClose} onCancel={(event) => { event.preventDefault(); onClose(); }} onKeyDown={(event) => {
      if (event.key !== 'Tab') return;
      const controls = [...event.currentTarget.querySelectorAll<HTMLElement>('a[href], button, input, select, textarea, [tabindex]')].filter((element) => element.tabIndex >= 0 && !element.matches(':disabled') && element.getClientRects().length > 0);
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (!first) { event.preventDefault(); event.currentTarget.focus(); return; }
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }}>
      <ModalCard $width={width} onClick={(event) => event.stopPropagation()}>
        <ModalTitle id={titleId}>{title}</ModalTitle>
        <ModalContent>{children}</ModalContent>
        {footer ? <ModalFooter>{footer}</ModalFooter> : null}
      </ModalCard>
    </ModalOverlay>
  );
};
