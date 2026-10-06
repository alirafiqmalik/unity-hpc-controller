/**
 * The shell of the LLMs & Agents evaluation workspace.
 *
 * An `llms-agents` project opens here instead of the research workspace. The
 * drawer shows the three groups MLflow's GenAI view uses — Observability,
 * Evaluation, Prompts & versions — and every page sits under one header that
 * names the project, its application and the Share / View docs actions.
 *
 * `useGenAI()` gives a page the slug, the summary and a refresh.
 */

import styled from '@emotion/styled';
import {
  IconArrowLeft,
  IconBook2,
  IconCheck,
  IconDotsVertical,
  IconInfoCircle,
  IconShare3,
  IconX,
} from '@tabler/icons-react';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { Link, Outlet, useNavigate, useParams } from 'react-router-dom';
import { useRecoilValue } from 'recoil';

import { errorText } from '../controller/api';
import { projectsState } from '../controller/state';
import { usePanels } from '../panels/PanelProvider';
import { Button, IconButton } from '../../ui/components/Button';
import { Card } from '../../ui/components/Card';
import { Tag } from '../../ui/components/Tag';
import { useToast } from '../../ui/components/Toast';
import { Page } from '../../ui/layout/AppLayout';
import { genaiApi, passes, type AssessmentSummary, type AssessmentValue, type Summary } from './api';

type ContextValue = {
  slug: string;
  summary: Summary | null;
  error: string;
  refresh: () => Promise<void>;
};

const Context = createContext<ContextValue>({ slug: '', summary: null, error: '', refresh: async () => {} });

export const useGenAI = () => useContext(Context);

export const GenAIWorkspace = () => {
  const { slug = '' } = useParams();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState('');
  const refresh = useCallback(async () => {
    try {
      setSummary(await genaiApi.summary(slug));
      setError('');
    } catch (reason) {
      setError(errorText(reason));
    }
  }, [slug]);
  useEffect(() => {
    setSummary(null);
    void refresh();
  }, [refresh]);
  return (
    <Context.Provider value={{ slug, summary, error, refresh }}>
      <Outlet />
    </Context.Provider>
  );
};

/* ------------------------------------------------------------------------ */
/* Page chrome                                                               */
/* ------------------------------------------------------------------------ */

const Menu = styled.div`
  position: relative;
`;

const MenuList = styled.div`
  background: ${({ theme }) => theme.background.secondary};
  border: 1px solid ${({ theme }) => theme.border.color.medium};
  border-radius: ${({ theme }) => theme.border.radius.md};
  box-shadow: ${({ theme }) => theme.boxShadow.strong};
  display: flex;
  flex-direction: column;
  min-width: 220px;
  padding: ${({ theme }) => theme.spacing(1)};
  position: absolute;
  right: 0;
  top: 32px;
  z-index: ${({ theme }) => theme.zIndex.modal};
`;

const MenuItem = styled.button`
  background: transparent;
  border: 0;
  border-radius: ${({ theme }) => theme.border.radius.sm};
  color: ${({ theme }) => theme.font.color.primary};
  cursor: pointer;
  font-size: ${({ theme }) => theme.font.size.sm};
  padding: ${({ theme }) => theme.spacing(1.5, 2)};
  text-align: left;

  &:hover {
    background: ${({ theme }) => theme.background.transparent.secondary};
  }
`;

const InfoBox = styled(Card)`
  font-size: ${({ theme }) => theme.font.size.sm};
  gap: ${({ theme }) => theme.spacing(1.5)};

  code {
    font-family: ${({ theme }) => theme.font.familyMono};
    font-size: ${({ theme }) => theme.font.size.xs};
  }
`;

export const SectionHead = styled.div`
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: ${({ theme }) => theme.spacing(2)};
  justify-content: space-between;
`;

export const SectionTitle = styled.h2`
  color: ${({ theme }) => theme.font.color.primary};
  font-size: ${({ theme }) => theme.font.size.md};
  font-weight: ${({ theme }) => theme.font.weight.semiBold};
  letter-spacing: -0.01em;
`;

export const Toolbar = styled.div`
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: ${({ theme }) => theme.spacing(2)};
`;

export const Muted = styled.span`
  color: ${({ theme }) => theme.font.color.tertiary};
  font-size: ${({ theme }) => theme.font.size.xs};
`;

export const Mono = styled.span`
  font-family: ${({ theme }) => theme.font.familyMono};
  font-size: ${({ theme }) => theme.font.size.xs};
`;

/**
 * One page of the workspace: project header, Share / View docs, the body.
 * `title` names the section; the project header stays the same on every page.
 */
export const GenAIPage = ({
  title,
  subtitle,
  actions,
  children,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
}) => {
  const { slug, summary, error } = useGenAI();
  const projects = useRecoilValue(projectsState);
  const project = projects.find((one) => one.slug === slug);
  const navigate = useNavigate();
  const toast = useToast();
  const { openProjectControls } = usePanels();
  const [menu, setMenu] = useState(false);
  const [info, setInfo] = useState(false);

  const share = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      toast('Link copied', 'success');
    } catch {
      toast(window.location.href, 'info');
    }
  };
  const docs = `/projects/${encodeURIComponent(slug)}/docs`;

  return (
    <Page
      title={project?.slug ?? slug}
      subtitle={`${title}${subtitle ? ` · ${subtitle}` : ''}`}
      lead={
        <IconButton Icon={IconArrowLeft} aria-label="Back to projects" title="Projects" onClick={() => navigate('/jobs/project')} />
      }
      titleExtra={
        <>
          <Tag color="blue" text="LLMs & Agents" />
          <IconButton Icon={IconInfoCircle} aria-label="About this workspace" title="About this workspace" active={info} onClick={() => setInfo((v) => !v)} />
        </>
      }
      actions={
        <>
          {actions}
          <Menu>
            <IconButton Icon={IconDotsVertical} aria-label="More" title="More" active={menu} onClick={() => setMenu((v) => !v)} />
            {menu ? (
              <MenuList onMouseLeave={() => setMenu(false)}>
                <MenuItem onClick={() => { setMenu(false); navigate(`/projects/${encodeURIComponent(slug)}/runner`); }}>Workflow runner</MenuItem>
                <MenuItem onClick={() => { setMenu(false); navigate(`/projects/${encodeURIComponent(slug)}/executions`); }}>Executions</MenuItem>
                <MenuItem onClick={() => { setMenu(false); openProjectControls(slug); }}>Project controls</MenuItem>
              </MenuList>
            ) : null}
          </Menu>
          <Button size="small" Icon={IconShare3} onClick={() => void share()}>Share</Button>
          <Button size="small" Icon={IconBook2} onClick={() => navigate(docs)}>View docs</Button>
        </>
      }
    >
      {error ? <Card role="alert">{error}</Card> : null}
      {info && summary ? (
        <InfoBox>
          <SectionHead>
            <strong>LLMs & Agents evaluation workspace</strong>
            <IconButton Icon={IconX} aria-label="Close" onClick={() => setInfo(false)} />
          </SectionHead>
          <span>Project directory <code>{summary.path}</code>.</span>
          <span>
            Datasets live under <code>{String(summary.connector.datasets_dir ?? 'dataset')}/</code>; evaluation runs are read from{' '}
            {summary.collections.map((c, i) => (
              <span key={c.id}>
                {i ? ', ' : ''}<code>{c.path}</code>{c.default ? '' : ' (on request)'}
              </span>
            ))}
            . The connector is the <code>genai</code> block of <code>unityHPC/project.json</code>
            {summary.connector.declared ? '' : ' (defaults; nothing declared)'}.
          </span>
          <span>
            Evaluations launch through the workflow runner: check setup, freeze a plan, and approve it. The controller then follows the declared stages.
          </span>
        </InfoBox>
      ) : null}
      {children}
    </Page>
  );
};

/* ------------------------------------------------------------------------ */
/* Shared formatting                                                         */
/* ------------------------------------------------------------------------ */

export const formatDuration = (seconds: number | null | undefined): string => {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return '—';
  if (seconds < 0.01) return `${(seconds * 1000).toFixed(2)}ms`;
  if (seconds < 1) return `${(seconds * 1000).toFixed(0)}ms`;
  if (seconds < 90) return `${seconds.toFixed(seconds < 10 ? 3 : 1)}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 90) return `${minutes}m ${Math.round(seconds % 60)}s`;
  return `${(seconds / 3600).toFixed(1)}h`;
};

export const elapsedSeconds = (started: string | null | undefined, finished: string | null | undefined): number | null => {
  if (!started || !finished) return null;
  const start = Date.parse(started);
  const end = Date.parse(finished);
  return Number.isFinite(start) && Number.isFinite(end) && end >= start ? (end - start) / 1000 : null;
};

export const formatTime = (value: string | null | undefined): string => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: '2-digit', day: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
};

export const formatNumber = (value: number | null | undefined): string =>
  value === null || value === undefined ? '—' : value.toLocaleString();

export const percent = (ratio: number | undefined | null): string =>
  ratio === null || ratio === undefined ? '—' : `${Math.round(ratio * 100)}%`;

export const shortId = (value: string, keep = 10): string => (value.length > keep ? `${value.slice(0, keep)}…` : value);

/* ------------------------------------------------------------------------ */
/* Assessment widgets                                                        */
/* ------------------------------------------------------------------------ */

export const AssessmentTag = ({ item, name }: { item: AssessmentValue; name?: string }) => {
  if (item.kind === 'pass_fail') {
    const ok = passes(item);
    return <Tag color={ok ? 'green' : 'red'} text={ok ? 'Pass' : 'Fail'} dot title={name} />;
  }
  if (item.kind === 'score') {
    const value = typeof item.value === 'number' ? item.value : Number(item.value);
    return <Tag color="blue" text={Number.isFinite(value) ? value.toLocaleString() : String(item.value)} mono title={name} />;
  }
  return <Tag color="gray" text={String(item.value)} title={name} />;
};

const BarRow = styled.div`
  align-items: center;
  display: grid;
  font-size: ${({ theme }) => theme.font.size.xxs};
  gap: ${({ theme }) => theme.spacing(1.5)};
  grid-template-columns: 52px 1fr 36px;
`;

const BarTrack = styled.div`
  background: ${({ theme }) => theme.background.quaternary};
  border-radius: 2px;
  height: 6px;
  overflow: hidden;
`;

const BarFill = styled.div<{ $color: string; $ratio: number }>`
  background: ${({ $color }) => $color};
  height: 100%;
  width: ${({ $ratio }) => Math.max(0, Math.min(100, $ratio * 100))}%;
`;

const SummaryBox = styled.div`
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 150px;
`;

const Big = styled.div`
  color: ${({ theme }) => theme.font.color.primary};
  font-size: ${({ theme }) => theme.font.size.lg};
  font-weight: ${({ theme }) => theme.font.weight.semiBold};
  letter-spacing: -0.01em;
  line-height: 1.1;
`;

const Lead = styled.div<{ $color: string }>`
  color: ${({ $color }) => $color};
  font-size: 10px;
  font-weight: ${({ theme }) => theme.font.weight.semiBold};
  letter-spacing: 0.06em;
  text-transform: uppercase;
`;

/**
 * The per-assessment block in the table header: the headline rate and one
 * bar per outcome, as MLflow draws it above the Assessments columns.
 */
export const AssessmentSummaryBlock = ({ name, summary }: { name: string; summary: AssessmentSummary }) => {
  if (!summary.count) return <Muted>no values</Muted>;
  if (summary.kind === 'pass_fail') {
    const rate = summary.pass_rate ?? summary.pass / summary.count;
    return (
      <SummaryBox>
        <Lead $color="#22a06b">Pass</Lead>
        <Big>{percent(rate)}</Big>
        <BarRow><span>Pass</span><BarTrack><BarFill $color="#22a06b" $ratio={summary.pass / summary.count} /></BarTrack><span>{percent(summary.pass / summary.count)}</span></BarRow>
        <BarRow><span>Fail</span><BarTrack><BarFill $color="#e5484d" $ratio={summary.fail / summary.count} /></BarTrack><span>{percent(summary.fail / summary.count)}</span></BarRow>
      </SummaryBox>
    );
  }
  if (summary.kind === 'score') {
    return (
      <SummaryBox>
        <Lead $color="#3b82f6">Mean</Lead>
        <Big>{summary.mean === undefined ? '—' : summary.mean.toLocaleString(undefined, { maximumFractionDigits: 2 })}</Big>
        <Muted>{name} · n={summary.count}</Muted>
      </SummaryBox>
    );
  }
  const entries = Object.entries(summary.values).sort((a, b) => b[1] - a[1]);
  const [top] = entries;
  return (
    <SummaryBox>
      <Lead $color="#8b5cf6">{top ? top[0] : name}</Lead>
      <Big>{top ? percent(top[1] / summary.count) : '—'}</Big>
      {entries.slice(0, 4).map(([value, count]) => (
        <BarRow key={value}>
          <span title={value} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</span>
          <BarTrack><BarFill $color="#8b5cf6" $ratio={count / summary.count} /></BarTrack>
          <span>{percent(count / summary.count)}</span>
        </BarRow>
      ))}
    </SummaryBox>
  );
};

export const StateTag = ({ state }: { state: string }) => {
  const upper = (state || '').toUpperCase();
  if (upper === 'OK' || upper === 'COMPLETE' || upper === 'COMPLETED') return <Tag color="green" text={<><IconCheck size={11} /> {upper === 'OK' ? 'OK' : 'complete'}</>} />;
  if (upper === 'ERROR' || upper === 'FAILED') return <Tag color="red" text={<><IconX size={11} /> {upper.toLowerCase()}</>} />;
  if (upper === 'IN_PROGRESS' || upper === 'RUNNING' || upper === 'APPROVED') return <Tag color="yellow" text={upper.toLowerCase().replace('_', ' ')} dot="pulsing" />;
  if (upper === 'SUPERSEDED') return <Tag color="gray" text="superseded" />;
  return <Tag color="gray" text={upper.toLowerCase() || '—'} />;
};

export const BackLink = ({ to, children }: { to: string; children: ReactNode }) => (
  <Link to={to} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
    <IconArrowLeft size={13} /> {children}
  </Link>
);
