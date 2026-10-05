/** Observability: the trace table, and traces grouped into sessions. */

import { IconMessages } from '@tabler/icons-react';
import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { errorText } from '../controller/api';
import { Card } from '../../ui/components/Card';
import { EmptyState } from '../../ui/components/EmptyState';
import { Select } from '../../ui/components/Field';
import { StatCard } from '../../ui/components/StatCard';
import { Grid } from '../../ui/components/Card';
import { MonoCell, Table, TableEmptyRow, TableScroller, THead, TRow } from '../../ui/components/Table';
import { Tag, TagRow } from '../../ui/components/Tag';
import { genaiApi, type Session } from './api';
import { formatDuration, formatNumber, formatTime, GenAIPage, Muted, percent, Toolbar, useGenAI } from './GenAIWorkspace';
import { TracesTable } from './TracesTable';

export const TracesPage = () => {
  const { summary } = useGenAI();
  return (
    <GenAIPage title="Traces" subtitle="every model request in scope, with its assessments and expectations">
      {summary ? (
        <Grid $min="160px">
          <StatCard label="Traces" value={formatNumber(summary.counts.traces)} caption="default collections, superseded runs excluded" />
          <StatCard label="Sessions" value={formatNumber(summary.counts.sessions)} caption="distinct session ids" />
          <StatCard label="Evaluation runs" value={formatNumber(summary.counts.evaluations_complete)} unit={`/ ${summary.counts.evaluations}`} caption="complete / all collections" />
          {Object.entries(summary.assessments).filter(([, s]) => s.kind === 'pass_fail').slice(0, 2).map(([name, s]) => (
            <StatCard key={name} label={name} value={percent(s.pass_rate)} caption={`${s.pass} pass · ${s.fail} fail`} accent={(s.pass_rate ?? 0) >= 0.5 ? 'green' : 'red'} />
          ))}
        </Grid>
      ) : null}
      <TracesTable />
    </GenAIPage>
  );
};

export const SessionsPage = () => {
  const { slug } = useGenAI();
  const [params, setParams] = useSearchParams();
  const collection = params.get('collection') || '';
  const [data, setData] = useState<{ sessions: Session[]; collections: { id: string; label: string }[] } | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    genaiApi.sessions(slug, { collection: collection || undefined })
      .then((value) => { if (live) { setData(value); setError(''); } })
      .catch((reason) => { if (live) setError(errorText(reason)); });
    return () => { live = false; };
  }, [slug, collection]);

  const sessions = data?.sessions ?? [];
  const assessmentNames = [...new Set(sessions.flatMap((s) => Object.keys(s.assessments)))];

  return (
    <GenAIPage title="Sessions" subtitle="traces grouped by session — for TLAiBench, one puzzle is one session">
      <Toolbar>
        {(data?.collections.length ?? 0) > 1 ? (
          <Select aria-label="Collection" value={collection} style={{ width: 'auto' }}
            options={[{ value: '', label: 'Collections: default' }, { value: 'all', label: 'Collections: all' }, ...(data?.collections ?? []).map((c) => ({ value: c.id, label: `Collection: ${c.label}` }))]}
            onChange={(e) => { const next = new URLSearchParams(params); if (e.target.value) next.set('collection', e.target.value); else next.delete('collection'); setParams(next); }} />
        ) : null}
        <Muted>{sessions.length} sessions</Muted>
      </Toolbar>
      {error ? <Card role="alert">{error}</Card> : null}
      {data && !sessions.length ? (
        <Card><EmptyState title="No sessions" Icon={IconMessages}>Traces carry a session id once an evaluation has run.</EmptyState></Card>
      ) : (
        <Card $padded={false}>
          <TableScroller>
            <Table>
              <THead>
                <tr>
                  <th>Session</th>
                  <th>Traces</th>
                  <th>States</th>
                  {assessmentNames.map((name) => <th key={name}>{name}</th>)}
                  <th>Models</th>
                  <th>Tokens</th>
                  <th>Time</th>
                  <th>Last request</th>
                </tr>
              </THead>
              <tbody>
                {!data ? <TableEmptyRow colSpan={7 + assessmentNames.length}>Loading sessions…</TableEmptyRow> : sessions.map((session) => (
                  <TRow key={session.session}>
                    <td><Link to={`../traces?session=${encodeURIComponent(session.session)}${collection ? `&collection=${collection}` : ''}`}>{session.session}</Link></td>
                    <MonoCell>{formatNumber(session.traces)}</MonoCell>
                    <td>
                      <TagRow>
                        {Object.entries(session.states).map(([state, n]) => <Tag key={state} color={state === 'OK' ? 'green' : state === 'ERROR' ? 'red' : 'gray'} text={`${n} ${state.toLowerCase()}`} />)}
                      </TagRow>
                    </td>
                    {assessmentNames.map((name) => {
                      const s = session.assessments[name];
                      if (!s) return <td key={name}><Muted>—</Muted></td>;
                      if (s.kind === 'pass_fail') return <td key={name}><Tag color={(s.pass_rate ?? 0) > 0 ? 'green' : 'red'} text={`${percent(s.pass_rate)} pass`} /></td>;
                      if (s.kind === 'score') return <td key={name}><Tag color="blue" text={`mean ${s.mean?.toLocaleString(undefined, { maximumFractionDigits: 1 }) ?? '—'}`} mono /></td>;
                      const [top] = Object.entries(s.values).sort((a, b) => b[1] - a[1]);
                      return <td key={name}>{top ? <Tag color="gray" text={`${top[0]} ${percent(top[1] / s.count)}`} /> : <Muted>—</Muted>}</td>;
                    })}
                    <td title={session.models.join(', ')}>{session.models.map((m) => m.split('/').pop()).join(', ') || '—'}</td>
                    <MonoCell>{formatNumber(session.tokens)}</MonoCell>
                    <MonoCell>{formatDuration(session.duration_s)}</MonoCell>
                    <MonoCell>{formatTime(session.last)}</MonoCell>
                  </TRow>
                ))}
              </tbody>
            </Table>
          </TableScroller>
        </Card>
      )}
    </GenAIPage>
  );
};
