/**
 * The frame every page sits in: the drawer, the page header, the scroll body.
 *
 * `Page` is what a route module renders. It takes the title and the actions,
 * so a page file holds its content and nothing about the chrome.
 */

import styled from '@emotion/styled';
import { IconRefresh } from '@tabler/icons-react';
import {
  useCallback,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { useRecoilValue } from 'recoil';

import { useSync } from '../../modules/controller/ControllerSync';
import { ago, clockText } from '../../modules/controller/format';
import { lastSyncState, syncErrorState } from '../../modules/controller/state';
import { findNavigationItem } from '../../modules/navigation/routes';
import { IconButton } from '../components/Button';
import { NavigationDrawer } from './NavigationDrawer';

const STORAGE_KEY = 'unity-hpc.drawer-collapsed';

const Shell = styled.div`
  display: flex;
  min-height: 100vh;

  @media (max-width: 860px) {
    flex-direction: column;
  }
`;

const Main = styled.main`
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
`;

const Header = styled.header`
  align-items: center;
  background: ${({ theme }) => theme.background.primary};
  border-bottom: 1px solid ${({ theme }) => theme.border.color.light};
  display: flex;
  gap: ${({ theme }) => theme.spacing(4)};
  justify-content: space-between;
  min-height: ${({ theme }) => theme.pageHeader.height};
  padding: ${({ theme }) => theme.spacing(2, 5)};
  position: sticky;
  top: 0;
  z-index: ${({ theme }) => theme.zIndex.header};

  @media (max-width: 720px) {
    align-items: stretch;
    flex-direction: column;
    gap: ${({ theme }) => theme.spacing(2)};
    padding: ${({ theme }) => theme.spacing(2, 3)};

    > div:first-of-type > div > div {
      flex-wrap: wrap;
    }
  }
`;

const Title = styled.h1`
  color: ${({ theme }) => theme.font.color.primary};
  font-size: ${({ theme }) => theme.font.size.lg};
  font-weight: ${({ theme }) => theme.font.weight.semiBold};
  letter-spacing: -0.015em;
  line-height: 1.25;

  @media (max-width: 720px) {
    min-width: 0;
    overflow-wrap: anywhere;
  }
`;

const Subtitle = styled.div`
  color: ${({ theme }) => theme.font.color.tertiary};
  font-size: ${({ theme }) => theme.font.size.xs};
  margin-top: 1px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

const HeaderRight = styled.div`
  align-items: center;
  display: flex;
  flex-shrink: 0;
  gap: ${({ theme }) => theme.spacing(2)};

  @media (max-width: 720px) {
    flex-wrap: wrap;
    min-width: 0;
  }
`;

const SyncNote = styled.span`
  color: ${({ theme }) => theme.font.color.tertiary};
  font-size: ${({ theme }) => theme.font.size.xs};
  white-space: nowrap;

  @media (max-width: 720px) {
    display: none;
  }
`;

const Clock = styled.span`
  color: ${({ theme }) => theme.font.color.secondary};
  font-family: ${({ theme }) => theme.font.familyMono};
  font-size: ${({ theme }) => theme.font.size.xs};

  @media (max-width: 720px) {
    display: none;
  }
`;

const Body = styled.div`
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: ${({ theme }) => theme.spacing(3)};
  padding: ${({ theme }) => theme.spacing(5)};

  @media (max-width: 720px) {
    padding: ${({ theme }) => theme.spacing(4, 3)};
  }
`;

const ErrorBanner = styled.div`
  align-items: center;
  background: ${({ theme }) => theme.background.transparent.danger};
  border: 1px solid ${({ theme }) => theme.border.color.danger};
  border-radius: ${({ theme }) => theme.border.radius.sm};
  color: ${({ theme }) => theme.font.color.danger};
  display: flex;
  font-size: ${({ theme }) => theme.font.size.sm};
  gap: ${({ theme }) => theme.spacing(2)};
  padding: ${({ theme }) => theme.spacing(2, 3)};
`;

const readCollapsed = (): boolean => {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    return false;
  }
};

/** The page chrome: a title, an optional action row, and the content. */
export const Page = ({
  actions,
  children,
  title,
  subtitle,
  lead,
  titleExtra,
}: {
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  /** Drawn before the title: a back control, an icon. */
  lead?: ReactNode;
  /** Drawn after the title on the same line: a chip, a menu. */
  titleExtra?: ReactNode;
  children: ReactNode;
}) => {
  const location = useLocation();
  const item = findNavigationItem(location.pathname);
  const lastSync = useRecoilValue(lastSyncState);
  const error = useRecoilValue(syncErrorState);
  const { refresh, syncing } = useSync();
  const [clock, setClock] = useState(() => clockText());

  useEffect(() => {
    const timer = window.setInterval(() => setClock(clockText()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    document.title = title ? `${title} · Unity HPC` : item ? `${item.title} · Unity HPC` : 'Unity HPC Controller';
  }, [item, title]);

  return (
    <>
      <Header>
        <div style={{ minWidth: 0, display: 'flex', alignItems: 'center', gap: 10 }}>
          {lead}
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
              <Title>{title ?? item?.title ?? 'Unity HPC'}</Title>
              {titleExtra}
            </div>
            {(subtitle ?? item?.subtitle) ? <Subtitle>{subtitle ?? item?.subtitle}</Subtitle> : null}
          </div>
        </div>
        <HeaderRight>
          {actions}
          <SyncNote>
            Last sync{' '}
            {lastSync ? ago(new Date(lastSync).toISOString()) : '—'}
          </SyncNote>
          <Clock>{clock}</Clock>
          <IconButton
            Icon={IconRefresh}
            onClick={() => void refresh()}
            disabled={syncing}
            aria-label="Refresh now"
            title="Refresh now"
          />
        </HeaderRight>
      </Header>
      <Body>
        {error ? <ErrorBanner>{error}</ErrorBanner> : null}
        {children}
      </Body>
    </>
  );
};

export const AppLayout = () => {
  const [collapsed, setCollapsed] = useState(readCollapsed);

  const toggle = useCallback(() => {
    setCollapsed((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(STORAGE_KEY, next ? '1' : '0');
      } catch {
        // No storage. The choice holds until the page reloads.
      }
      return next;
    });
  }, []);

  return (
    <Shell>
      <NavigationDrawer collapsed={collapsed} onToggleCollapsed={toggle} />
      <Main>
        <Outlet />
      </Main>
    </Shell>
  );
};
