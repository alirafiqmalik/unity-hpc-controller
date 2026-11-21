/**
 * Prompts & versions: the prompt templates the project ships and the prompt
 * versions observed in evaluation runs; the agent versions (model, engine,
 * runner) those runs used, with the model revisions the project pinned.
 */

import styled from '@emotion/styled';
import { IconFileText, IconRobot } from '@tabler/icons-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { errorText } from '../controller/api';
import { Card, CardHeader, Grid, Hint, KeyValue } from '../../ui/components/Card';
import { EmptyState } from '../../ui/components/EmptyState';
import { StatCard } from '../../ui/components/StatCard';
import { MonoCell, Table, TableEmptyRow, TableScroller, THead, TRow } from '../../ui/components/Table';
import { Tag, TagRow } from '../../ui/components/Tag';
import { genaiApi, type AgentVersion, type PromptFile, type PromptVersion } from './api';
import { formatNumber, formatTime, GenAIPage, Mono, Muted, percent, SectionHead, SectionTitle, StateTag, useGenAI } from './GenAIWorkspace';

const Pre = styled.pre`
  background: ${({ theme }) => theme.background.primary};
  border: 1px solid ${({ theme }) => theme.border.color.light};
  border-radius: ${({ theme }) => theme.border.radius.sm};
  font-family: ${({ theme }) => theme.font.familyMono};
  font-size: ${({ theme }) => theme.font.size.xs};
  line-height: 1.5;
  max-height: 420px;
  overflow: auto;
  padding: ${({ theme }) => theme.spacing(2)};
  white-space: pre-wrap;
  overflow-wrap: anywhere;
`;

export const PromptsPage = () => {
  const { slug } = useGenAI();
  const [data, setData] = useState<{ files: PromptFile[]; observed: PromptVersion[]; prompts_dir: string } | null>(null);
  const [error, setError] = useState('');
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    genaiApi.prompts(slug).then(setData).catch((reason) => setError(errorText(reason)));
  }, [slug]);

  return (
    <GenAIPage title="Prompts" subtitle={`prompt templates in ${data?.prompts_dir ?? 'prompts/'} and the prompt versions evaluation runs recorded`}>
      {error ? <Card role="alert">{error}</Card> : null}
      <Grid $min="160px">
        <StatCard label="Prompt files" value={formatNumber(data?.files.length ?? 0)} Icon={IconFileText} caption={data?.prompts_dir} />
        <StatCard label="Observed versions" value={formatNumber(data?.observed.length ?? 0)} caption="distinct prompt identities in run manifests" />
      </Grid>
      <SectionHead><SectionTitle>Observed prompt versions</SectionTitle></SectionHead>
      {data && !data.observed.length ? (
        <Card><EmptyState title="No prompt version recorded" Icon={IconFileText} compact>Run manifests carry a prompt block once the connector names it (`evaluation_fields.prompt`).</EmptyState></Card>
      ) : (
        <Card $padded={false}>
          <TableScroller>
            <Table>
              <THead><tr><th>Version</th><th>Digest</th><th>Details</th><th>Models</th><th>Runs</th><th>First</th><th>Last</th></tr></THead>
              <tbody>
                {!data ? <TableEmptyRow colSpan={7}>Loading…</TableEmptyRow> : data.observed.map((version) => (
                  <TRow key={version.id}>
                    <td><Tag color="purple" text={version.version} /></td>
                    <MonoCell title={version.sha256}>{version.sha256 ? `${version.sha256.slice(0, 12)}…` : '—'}</MonoCell>
                    <td><TagRow>{Object.entries(version.details).filter(([k]) => !['prompt_version', 'prompt_sha256', 'version', 'sha256'].includes(k)).map(([k, v]) => <Tag key={k} color="gray" text={`${k}: ${String(v).length > 24 ? `${String(v).slice(0, 23)}…` : String(v)}`} mono title={String(v)} />)}</TagRow></td>
                    <td title={version.models.join(', ')}>{version.models.map((m) => m.split('/').pop()).join(', ') || '—'}</td>
                    <td>{version.evaluations.slice(0, 3).map((e) => <div key={e.id}><Link to={`../evaluations/${encodeURIComponent(e.id)}`}>{e.name}</Link></div>)}{version.evaluations.length > 3 ? <Muted>+{version.evaluations.length - 3} more</Muted> : null}</td>
                    <MonoCell>{formatTime(version.first)}</MonoCell>
                    <MonoCell>{formatTime(version.last)}</MonoCell>
                  </TRow>
                ))}
              </tbody>
            </Table>
          </TableScroller>
        </Card>
      )}
      <SectionHead><SectionTitle>Prompt files</SectionTitle></SectionHead>
      {data && !data.files.length ? (
        <Card><EmptyState title="No prompt files" Icon={IconFileText} compact>Point <Mono>genai.prompts_dir</Mono> in <Mono>unityHPC/project.json</Mono> at the directory (or file) that holds the prompt templates.</EmptyState></Card>
      ) : (
        <Grid $min="320px">
          {(data?.files ?? []).map((file) => (
            <Card key={file.path}>
              <CardHeader title={file.name} note={`${formatNumber(file.size)} bytes`} />
              <KeyValue label="Path">{file.path}</KeyValue>
              <KeyValue label="sha256" title={file.sha256}>{file.sha256.slice(0, 16)}…</KeyValue>
              <details open={open === file.path} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open ? file.path : null)}>
                <summary style={{ cursor: 'pointer', fontSize: 12, marginTop: 8 }}>Source</summary>
                <Pre>{file.preview}</Pre>
              </details>
            </Card>
          ))}
        </Grid>
      )}
      <Hint>A prompt version is identified by what the run manifest recorded — version label, digest, tool protocol — so a change to the template shows up as a new row the next time an evaluation runs.</Hint>
    </GenAIPage>
  );
};

export const AgentVersionsPage = () => {
  const { slug } = useGenAI();
  const [data, setData] = useState<{ versions: AgentVersion[]; pinned: Record<string, { revision: string; source: string }> } | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    genaiApi.agentVersions(slug).then(setData).catch((reason) => setError(errorText(reason)));
  }, [slug]);

  const detailKeys = [...new Set((data?.versions ?? []).flatMap((v) => Object.keys(v.details)))];

  return (
    <GenAIPage title="Agent versions" subtitle="each distinct model, engine and runner combination that produced an evaluation run">
      {error ? <Card role="alert">{error}</Card> : null}
      <Grid $min="160px">
        <StatCard label="Agent versions" value={formatNumber(data?.versions.length ?? 0)} Icon={IconRobot} />
        <StatCard label="Models" value={formatNumber(new Set((data?.versions ?? []).map((v) => v.model)).size)} />
        <StatCard label="Pinned revisions" value={formatNumber(Object.keys(data?.pinned ?? {}).length)} caption="unityHPC/model-lock.json" />
      </Grid>
      {data && !data.versions.length ? (
        <Card><EmptyState title="No agent version observed" Icon={IconRobot}>Run manifests name the model and engine once the connector maps them (`evaluation_fields.agent`).</EmptyState></Card>
      ) : (
        <Card $padded={false}>
          <TableScroller>
            <Table>
              <THead>
                <tr>
                  <th>Model</th>
                  {detailKeys.map((k) => <th key={k}>{k}</th>)}
                  <th>Pinned revision</th>
                  <th>Runs</th>
                  <th>Traces</th>
                  <th>Pass rate</th>
                  <th>Last run</th>
                </tr>
              </THead>
              <tbody>
                {!data ? <TableEmptyRow colSpan={6 + detailKeys.length}>Loading…</TableEmptyRow> : data.versions.map((version) => (
                  <TRow key={version.id}>
                    <td title={version.model}><div style={{ fontWeight: 500 }}>{version.model.split('/').pop() || '—'}</div><Muted>{version.model.split('/').slice(0, -1).join('/')}</Muted></td>
                    {detailKeys.map((k) => <MonoCell key={k}>{version.details[k] === undefined ? '—' : String(version.details[k])}</MonoCell>)}
                    <MonoCell title={version.pinned_revision}>{version.pinned_revision ? `${version.pinned_revision.slice(0, 10)}…` : <Muted>not pinned</Muted>}</MonoCell>
                    <td>
                      {version.evaluations.slice(0, 2).map((e) => <div key={e.id} style={{ display: 'flex', gap: 6, alignItems: 'center' }}><Link to={`../evaluations/${encodeURIComponent(e.id)}`}>{e.name.length > 36 ? `${e.name.slice(0, 35)}…` : e.name}</Link><StateTag state={e.state} /></div>)}
                      {version.evaluations.length > 2 ? <Muted>+{version.evaluations.length - 2} more</Muted> : null}
                    </td>
                    <MonoCell>{formatNumber(version.traces)}</MonoCell>
                    <td>{version.pass_rate === null ? <Muted>no pass/fail assessment indexed</Muted> : <Tag color={version.pass_rate > 0 ? 'green' : 'red'} text={percent(version.pass_rate)} />}</td>
                    <MonoCell>{formatTime(version.last)}</MonoCell>
                  </TRow>
                ))}
              </tbody>
            </Table>
          </TableScroller>
        </Card>
      )}
      <Hint>Pass rate sums the pass/fail assessments of indexed runs. Open a run to index it; the Original corpus collection indexes on request.</Hint>
    </GenAIPage>
  );
};
