/**
 * The left navigation drawer.
 *
 * The brand block at the top carries the connection state, because that is the
 * one fact an operator must never have to hunt for: a stale snapshot is not a
 * live cluster, and the pill says which of the two this is.
 */

import styled from '@emotion/styled';
import {
  IconHome,
  IconChevronLeft,
  IconChevronRight,
  IconMoon,
  IconSun,
} from '@tabler/icons-react';
import { useEffect } from 'react';
import { NavLink, useLocation, useMatch } from 'react-router-dom';
import { useRecoilValue } from 'recoil';

import {
  connectionSelector,
  jobsState,
  projectsState,
} from '../../modules/controller/state';
import { NAVIGATION, PROJECT_SECTIONS } from '../../modules/navigation/routes';
import { useColorScheme } from '../theme/AppThemeProvider';

const Drawer = styled.nav<{ $collapsed: boolean }>`
  background: ${({ theme }) => theme.background.secondary};
  border-right: 1px solid ${({ theme }) => theme.border.color.light};
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  height: 100vh;
  position: sticky;
  top: 0;
  transition: width ${({ theme }) => theme.animation.duration.normal} ease;
  width: ${({ theme, $collapsed }) =>
    $collapsed ? theme.navigationDrawer.collapsedWidth : theme.navigationDrawer.width};
  z-index: ${({ theme }) => theme.zIndex.drawer};

  @media (max-width: 860px) {
    height: auto;
    position: static;
    width: 100%;
  }
`;

const Brand = styled.div<{ $collapsed: boolean }>`
  align-items: center;
  border-bottom: 1px solid ${({ theme }) => theme.border.color.light};
  display: flex;
  gap: ${({ theme }) => theme.spacing(2)};
  min-height: ${({ theme }) => theme.pageHeader.height};
  padding: ${({ theme, $collapsed }) =>
    $collapsed ? theme.spacing(0, 2) : theme.spacing(0, 3)};
`;

const Logo = styled.div`
  align-items: center;
  background: ${({ theme }) => theme.accent.primary};
  border-radius: ${({ theme }) => theme.border.radius.sm};
  color: ${({ theme }) =>
    theme.name === 'dark' ? theme.grayScale.gray95 : theme.grayScale.gray0};
  display: flex;
  flex-shrink: 0;
  font-size: ${({ theme }) => theme.font.size.sm};
  font-weight: ${({ theme }) => theme.font.weight.bold};
  height: 22px;
  justify-content: center;
  width: 22px;
`;

const BrandText = styled.div`
  min-width: 0;
`;

const BrandName = styled.div`
  color: ${({ theme }) => theme.font.color.primary};
  font-size: ${({ theme }) => theme.font.size.sm};
  font-weight: ${({ theme }) => theme.font.weight.semiBold};
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

const StatusLine = styled.div<{ $kind: string }>`
  align-items: center;
  color: ${({ theme, $kind }) =>
    $kind === 'live'
      ? theme.color.green[40]
      : $kind === 'down'
        ? theme.color.red[40]
        : theme.color.yellow[40]};
  display: flex;
  font-size: ${({ theme }) => theme.font.size.xxs};
  gap: ${({ theme }) => theme.spacing(1)};
  margin-top: 1px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;

  &::before {
    background: currentColor;
    border-radius: 50%;
    content: '';
    flex-shrink: 0;
    height: 5px;
    width: 5px;
  }
`;

const Sections = styled.div`
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: ${({ theme }) => theme.spacing(4)};
  overflow-y: auto;
  padding: ${({ theme }) => theme.spacing(4, 2)};
`;

const SectionLabel = styled.div<{ $collapsed: boolean }>`
  color: ${({ theme }) => theme.font.color.light};
  font-size: ${({ theme }) => theme.font.size.xxs};
  font-weight: ${({ theme }) => theme.font.weight.semiBold};
  letter-spacing: 0.07em;
  margin-bottom: ${({ theme }) => theme.spacing(1.5)};
  padding: ${({ theme }) => theme.spacing(0, 2)};
  text-transform: uppercase;
  visibility: ${({ $collapsed }) => ($collapsed ? 'hidden' : 'visible')};
  white-space: nowrap;
`;

const Item = styled(NavLink)<{ $collapsed: boolean }>`
  align-items: center;
  border-radius: ${({ theme }) => theme.border.radius.sm};
  color: ${({ theme }) => theme.font.color.secondary};
  display: flex;
  font-size: ${({ theme }) => theme.font.size.sm};
  font-weight: ${({ theme }) => theme.font.weight.medium};
  gap: ${({ theme }) => theme.spacing(2)};
  height: 30px;
  justify-content: ${({ $collapsed }) => ($collapsed ? 'center' : 'flex-start')};
  padding: ${({ theme, $collapsed }) =>
    $collapsed ? theme.spacing(0) : theme.spacing(0, 2)};
  transition: ${({ theme }) => theme.animation.clickable};

  svg {
    flex-shrink: 0;
  }

  &:hover {
    background: ${({ theme }) => theme.background.transparent.secondary};
    color: ${({ theme }) => theme.font.color.primary};
  }

  &.active {
    background: ${({ theme }) => theme.accent.tertiary};
    color: ${({ theme }) => theme.accent.primary};
  }
`;

const ItemLabel = styled.span`
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

const Counter = styled.span`
  background: ${({ theme }) => theme.background.quaternary};
  border-radius: ${({ theme }) => theme.border.radius.rounded};
  color: ${({ theme }) => theme.font.color.secondary};
  font-family: ${({ theme }) => theme.font.familyMono};
  font-size: ${({ theme }) => theme.font.size.xxs};
  padding: 1px 6px;
`;

const Footer = styled.div<{ $collapsed: boolean }>`
  align-items: center;
  border-top: 1px solid ${({ theme }) => theme.border.color.light};
  display: flex;
  gap: ${({ theme }) => theme.spacing(1)};
  justify-content: ${({ $collapsed }) => ($collapsed ? 'center' : 'space-between')};
  padding: ${({ theme }) => theme.spacing(2)};
`;

const FooterButton = styled.button`
  align-items: center;
  background: transparent;
  border: none;
  border-radius: ${({ theme }) => theme.border.radius.sm};
  color: ${({ theme }) => theme.font.color.tertiary};
  cursor: pointer;
  display: flex;
  height: 26px;
  justify-content: center;
  transition: ${({ theme }) => theme.animation.clickable};
  width: 26px;

  &:hover {
    background: ${({ theme }) => theme.background.transparent.secondary};
    color: ${({ theme }) => theme.font.color.primary};
  }
`;

export const NavigationDrawer = ({
  collapsed,
  onToggleCollapsed,
}: {
  collapsed: boolean;
  onToggleCollapsed: () => void;
}) => {
  const match = useMatch('/projects/:slug/*');
  const location = useLocation();
  useEffect(() => {
    if (location.pathname === '/jobs/project') {
      try { sessionStorage.setItem('unity-hpc.projects-return', location.pathname + location.search + location.hash); } catch { /* Optional browser state. */ }
    }
  }, [location]);
  let projectsReturn = '/jobs/project';
  try {
    const saved = sessionStorage.getItem('unity-hpc.projects-return');
    if (saved && /^\/jobs\/project(?:[?#]|$)/.test(saved)) projectsReturn = saved;
  } catch { /* The stable Projects route remains available. */ }
  const projects = useRecoilValue(projectsState);
  const project = projects.find((one) => one.slug === match?.params.slug);
  const connection = useRecoilValue(connectionSelector);
  const jobs = useRecoilValue(jobsState);
  const { resolved, toggleColorScheme } = useColorScheme();

  return (
    <Drawer $collapsed={collapsed} aria-label="Main navigation">
      <Brand $collapsed={collapsed}>
        {match ? <NavLink to={projectsReturn} style={{ display: 'flex', alignItems: 'center', gap: 8 }} aria-label="Home — Projects"><Logo><IconHome size={16} /></Logo>{collapsed ? null : <BrandName>Home</BrandName>}</NavLink> : <>
        <Logo>U</Logo>
        {collapsed ? null : (
          <BrandText>
            <BrandName>Unity HPC</BrandName>
            <StatusLine
              $kind={connection.kind}
              title={connection.label}
              data-testid="connection-state"
            >
              {connection.clusterName} · {connection.label}
            </StatusLine>
          </BrandText>
        )}
        </>}
      </Brand>

      <Sections>
        {match ? <div><SectionLabel $collapsed={collapsed}>{project?.slug ?? match.params.slug}</SectionLabel>{PROJECT_SECTIONS.map((label) => <Item key={label} to={`/projects/${encodeURIComponent(match.params.slug!)}/${label.toLowerCase()}`} $collapsed={collapsed} title={label}><ItemLabel>{collapsed ? label[0] : label}</ItemLabel></Item>)}</div> : NAVIGATION.map((section) => (
          <div key={section.id}>
            <SectionLabel $collapsed={collapsed}>{section.label}</SectionLabel>
            {section.items.map((item) => (
              <Item
                key={item.path}
                to={item.path}
                $collapsed={collapsed}
                title={collapsed ? item.label : undefined}
              >
                <item.Icon size={16} stroke={1.7} />
                {collapsed ? null : <ItemLabel>{item.label}</ItemLabel>}
                {!collapsed && item.path === '/jobs/monitor' && jobs.length > 0 ? (
                  <Counter>{jobs.length}</Counter>
                ) : null}
              </Item>
            ))}
          </div>
        ))}
      </Sections>

      <Footer $collapsed={collapsed}>
        <FooterButton
          type="button"
          data-testid="theme-toggle"
          onClick={toggleColorScheme}
          aria-label={resolved === 'dark' ? 'Use the light theme' : 'Use the dark theme'}
          title={resolved === 'dark' ? 'Light theme' : 'Dark theme'}
        >
          {resolved === 'dark' ? <IconSun size={15} /> : <IconMoon size={15} />}
        </FooterButton>
        <FooterButton
          type="button"
          data-testid="collapse-toggle"
          onClick={onToggleCollapsed}
          aria-label={collapsed ? 'Open the navigation' : 'Collapse the navigation'}
          title={collapsed ? 'Open the navigation' : 'Collapse the navigation'}
        >
          {collapsed ? <IconChevronRight size={15} /> : <IconChevronLeft size={15} />}
        </FooterButton>
      </Footer>
    </Drawer>
  );
};
