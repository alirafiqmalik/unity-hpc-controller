/**
 * One trace, opened from the table: request and response, the assessments
 * with their rationale, the expectations, the spans (agent turns) and the
 * raw metadata the project recorded.
 */

import styled from '@emotion/styled';
import { IconDatabasePlus } from '@tabler/icons-react';
import { useEffect, useState, type ReactNode } from 'react';

import { errorText } from '../controller/api';
import { Button } from '../../ui/components/Button';
import { Card, CardHeader, KeyValue } from '../../ui/components/Card';
import { SidePanel } from '../../ui/components/SidePanel';
import { Tag, TagRow } from '../../ui/components/Tag';
import { genaiApi, passes, type AssessmentFull, type Span, type TraceFull, type TraceRow } from './api';
import { AssessmentTag, formatDuration, formatNumber, formatTime, Mono, Muted, StateTag, Toolbar, useGenAI } from './GenAIWorkspace';

const Pre = styled.pre`
  background: ${({ theme }) => theme.background.primary};
  border: 1px solid ${({ theme }) => theme.border.color.light};
  border-radius: ${({ theme }) => theme.border.radius.sm};
  color: ${({ theme }) => theme.font.color.primary};
  font-family: ${({ theme }) => theme.font.familyMono};
  font-size: ${({ theme }) => theme.font.size.xs};
  line-height: 1.55;
  max-height: 320px;
  overflow: auto;
  padding: ${({ theme }) => theme.spacing(2)};
  white-space: pre-wrap;
  overflow-wrap: anywhere;
`;

const Tabs = styled.div`
  border-bottom: 1px solid ${({ theme }) => theme.border.color.light};
  display: flex;
  gap: ${({ theme }) => theme.spacing(1)};
`;

const TabButton = styled.button<{ $on: boolean }>`
  background: transparent;
  border: 0;
  border-bottom: 2px solid ${({ theme, $on }) => ($on ? theme.accent.primary : 'transparent')};
  color: ${({ theme, $on }) => ($on ? theme.font.color.primary : theme.font.color.tertiary)};
  cursor: pointer;
  font-size: ${({ theme }) => theme.font.size.sm};
  font-weight: ${({ theme }) => theme.font.weight.medium};
  margin-bottom: -1px;
  padding: ${({ theme }) => theme.spacing(1.5, 2)};
`;

const SpanRow = styled.div<{ $open: boolean }>`
  border: 1px solid ${({ theme }) => theme.border.color.light};
  border-radius: ${({ theme }) => theme.border.radius.sm};
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.spacing(1.5)};
  padding: ${({ theme }) => theme.spacing(2)};
`;

const SpanHead = styled.button`
  align-items: center;
  background: transparent;
  border: 0;
  color: ${({ theme }) => theme.font.color.primary};
  cursor: pointer;
  display: flex;
  font: inherit;
  gap: ${({ theme }) => theme.spacing(2)};
  justify-content: space-between;
  text-align: left;
  width: 100%;
`;

const Assessment = styled.div`
  border-bottom: 1px solid ${({ theme }) => theme.border.color.light};
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: ${({ theme }) => theme.spacing(2, 0)};

  &:last-of-type {
    border-bottom: 0;
  }
`;

const text = (value: unknown): string => {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  return JSON.stringify(value, null, 2);
};

const Block = ({ label, value }: { label: string; value: unknown }) => {
  const body = text(value);
  if (!body) return null;
  return (
    <div>
      <Muted>{label}</Muted>
      <Pre>{body}</Pre>
    </div>
  );
};

const SpanView = ({ span }: { span: Span }) => {
  const [open, setOpen] = useState(span.index === 0);
  const tokens = typeof span.tokens === 'number' ? span.tokens : span.tokens && typeof span.tokens === 'object' ? (span.tokens as Record<string, number>).completion ?? (span.tokens as Record<string, number>).total : null;
  return (
    <SpanRow $open={open}>
      <SpanHead onClick={() => setOpen((v) => !v)}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
          <Tag color={span.type === 'LLM' ? 'purple' : span.type === 'TOOL' ? 'yellow' : 'gray'} text={span.type} />
          <span>{span.name}</span>
        </span>
        <span style={{ display: 'flex', gap: 10 }}>
          {span.status !== undefined && span.status !== null ? <Tag color="gray" text={String(span.status)} /> : null}
          {tokens !== null && tokens !== undefined ? <Mono>{formatNumber(tokens)} tok</Mono> : null}
          <Mono>{formatDuration(span.duration_s)}</Mono>
        </span>
      </SpanHead>
      {open ? (
        <>
          <Block label="Inputs" value={span.inputs} />
          <Block label="Reasoning" value={span.reasoning} />
          <Block label="Outputs" value={span.outputs} />
          <Block label="Tool calls" value={span.tool_calls} />
          <Block label="Tool results" value={span.tool_results} />
          {Object.keys(span.attributes).length ? (
            <TagRow>
              {Object.entries(span.attributes).map(([k, v]) => <Tag key={k} color="gray" text={`${k}: ${String(v)}`} mono />)}
            </TagRow>
          ) : null}
        </>
      ) : null}
    </SpanRow>
  );
};

export const TracePanel = ({ row, onClose, onAddToDataset }: { row: TraceRow; onClose: () => void; onAddToDataset?: () => void }) => {
  const { slug } = useGenAI();
  const [full, setFull] = useState<TraceFull | null>(null);
  const [error, setError] = useState('');
  const [tab, setTab] = useState<'overview' | 'spans' | 'assessments' | 'metadata'>('overview');

  useEffect(() => {
    let live = true;
    setFull(null);
    genaiApi.trace(slug, row.evaluation_id, row.trace_id)
      .then((value) => { if (live) setFull(value); })
      .catch((reason) => { if (live) setError(errorText(reason)); });
    return () => { live = false; };
  }, [slug, row.evaluation_id, row.trace_id]);

  const assessments: [string, AssessmentFull][] = Object.entries(full?.assessments ?? row.assessments).map(
    ([name, item]) => [name, { rationale: '', source: '', ...item } as AssessmentFull],
  );
  const expectations = Object.entries(full?.expectations ?? row.expectations);

  let body: ReactNode;
  if (tab === 'overview') {
    body = (
      <>
        <Block label="Request" value={full?.request ?? row.request} />
        {full?.inputs ? <Block label="Inputs" value={full.inputs} /> : null}
        <Block label="Response" value={full ? full.response ?? '' : row.response} />
        {full?.reasoning ? <Block label="Reasoning" value={full.reasoning} /> : null}
        {row.error ? <Block label="Error" value={row.error} /> : null}
        {expectations.length ? (
          <Card>
            <CardHeader title="Expectations" note="ground truth from the dataset" />
            {expectations.map(([name, value]) => <Block key={name} label={name} value={value} />)}
          </Card>
        ) : null}
      </>
    );
  } else if (tab === 'spans') {
    body = full ? (
      full.spans.length ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {full.spans.map((span) => <SpanView key={span.index} span={span} />)}
        </div>
      ) : <Muted>This trace recorded no spans. Enable turn storage in the evaluation to keep them.</Muted>
    ) : <Muted>Loading…</Muted>;
  } else if (tab === 'assessments') {
    body = assessments.length ? (
      <div>
        {assessments.map(([name, item]) => (
          <Assessment key={name}>
            <Toolbar style={{ justifyContent: 'space-between' }}>
              <strong>{name}</strong>
              <AssessmentTag item={item} name={name} />
            </Toolbar>
            {item.rationale ? <span style={{ fontSize: 13 }}>{item.rationale}</span> : null}
            <Muted>{item.source ? `source: ${item.source}` : 'source: project'} · kind: {item.kind}{item.kind === 'pass_fail' ? ` · ${passes(item) ? 'pass' : 'fail'}` : ''}</Muted>
          </Assessment>
        ))}
      </div>
    ) : <Muted>No assessments on this trace.</Muted>;
  } else {
    body = full ? (
      <>
        <Card>
          <CardHeader title="Trace" />
          {Object.entries(full.metadata).map(([k, v]) => <KeyValue key={k} label={k}>{String(v)}</KeyValue>)}
        </Card>
        {Object.entries(full.nested).map(([group, values]) => (
          <Card key={group}>
            <CardHeader title={group} />
            {Object.entries(values as Record<string, unknown>).map(([k, v]) => <KeyValue key={k} label={k}>{String(v)}</KeyValue>)}
          </Card>
        ))}
        {Object.keys(full.tags).length ? (
          <TagRow>{Object.entries(full.tags).map(([k, v]) => <Tag key={k} color="gray" text={`${k}: ${String(v)}`} mono />)}</TagRow>
        ) : null}
      </>
    ) : <Muted>Loading…</Muted>;
  }

  return (
    <SidePanel open onClose={onClose} title={<Mono>tr-{row.trace_id}</Mono>} subtitle={`${row.evaluation}${row.session ? ` · session ${row.session}` : ''}`}>
      <TagRow>
        <StateTag state={row.state} />
        {row.model ? <Tag color="purple" text={row.model.split('/').pop() ?? row.model} title={row.model} /> : null}
        {row.tokens !== null ? <Tag color="gray" text={`${formatNumber(row.tokens)} tokens`} mono /> : null}
        <Tag color="gray" text={formatDuration(row.duration_s)} mono />
        <Tag color="gray" text={formatTime(row.request_time)} />
        {row.dataset ? <Tag color="blue" text={`dataset ${row.dataset}`} /> : null}
      </TagRow>
      {onAddToDataset ? (
        <Toolbar>
          <Button size="small" Icon={IconDatabasePlus} onClick={onAddToDataset}>Add to evaluation dataset</Button>
        </Toolbar>
      ) : null}
      {error ? <Card role="alert">{error}</Card> : null}
      <Tabs>
        {(['overview', 'spans', 'assessments', 'metadata'] as const).map((id) => (
          <TabButton key={id} $on={tab === id} onClick={() => setTab(id)}>
            {id === 'spans' ? `Spans${full ? ` (${full.spans.length})` : ''}` : id === 'assessments' ? `Assessments (${assessments.length})` : id[0].toUpperCase() + id.slice(1)}
          </TabButton>
        ))}
      </Tabs>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>{body}</div>
    </SidePanel>
  );
};
