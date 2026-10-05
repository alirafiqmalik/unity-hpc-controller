import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Button, ButtonGroup } from '../../ui/components/Button';
import { Card, CardHeader, Hint } from '../../ui/components/Card';
import { Checkbox, Field, TextInput } from '../../ui/components/Field';
import { workspaceRequest } from './api';
import { ErrorNotice, useWorkspace } from './Workspace';
import { errorText } from '../controller/api';

type Schedule = { invalidated_at?: string; id: string; version: number; plan_id: string; state: string; earliest_dispatch: string; latest_dispatch: string; timezone: string; execution_id?: string; reason?: string };

export const SchedulePlan = ({ planId, reviewed }: { planId: string; reviewed: boolean }) => {
  const { slug } = useWorkspace();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [earliest, setEarliest] = useState('');
  const [latest, setLatest] = useState('');
  const [zone, setZone] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC');
  const [approved, setApproved] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const schedule = async () => {
    setBusy(true); setError('');
    try {
      const review = await workspaceRequest<{expected_version: string | number}>(slug, `plans/${planId}/schedule-review`);
      const value = await workspaceRequest<Schedule>(slug, 'schedules', 'POST', { plan_id: planId, expected_version: review.expected_version,
        idempotency_key: `schedule:${planId}:${earliest}:${latest}:${zone}`, approved: true,
        earliest_dispatch: earliest, latest_dispatch: latest || undefined, timezone: zone });
      navigate(`/projects/${encodeURIComponent(slug)}/runs?view=schedules&schedule=${encodeURIComponent(value.id)}`);
    } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  };
  return <Card><CardHeader title="Future dispatch" /><Button disabled={!reviewed || busy} onClick={() => setOpen(!open)}>Schedule this plan</Button>
    {open ? <><p>Approve one dispatch within a window. This does not reserve resources or promise a cluster start time.</p>
      <Field label="Earliest dispatch (ISO date and time, with offset)"><TextInput aria-label="Earliest dispatch (ISO date and time, with offset)" value={earliest} placeholder="2030-01-01T09:00:00-05:00" onChange={e => { setEarliest(e.target.value); setApproved(false); }} /></Field>
      <Field label="Timezone"><TextInput aria-label="Timezone" value={zone} onChange={e => { setZone(e.target.value); setApproved(false); }} /></Field>
      <Field label="Latest dispatch (default: one hour later)"><TextInput aria-label="Latest dispatch (default: one hour later)" value={latest} onChange={e => { setLatest(e.target.value); setApproved(false); }} /></Field>
      <Hint>Times retain your timezone and are stored in UTC. An ambiguous daylight-saving time requires an explicit offset.</Hint>
      <Checkbox label="I approve this exact plan and dispatch window" checked={approved} onChange={e => setApproved(e.target.checked)} />
      <ErrorNotice error={error} /><Button disabled={!reviewed || !approved || !earliest || busy} onClick={() => void schedule()}>{busy ? 'Saving approval…' : 'Approve schedule'}</Button>
    </> : null}</Card>;
};

export const Schedules = () => {
  const { slug } = useWorkspace();
  const [search] = useSearchParams();
  const [items, setItems] = useState<Schedule[] | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<Schedule | null>(null);
  const [earliest, setEarliest] = useState('');
  const [latest, setLatest] = useState('');
  const [approved, setApproved] = useState(false);
  const refresh = useCallback(async () => { try { const r = await workspaceRequest<{schedules: Schedule[]}>(slug, 'schedules'); setItems(r.schedules); setError(''); } catch(e) { setError(errorText(e)); } }, [slug]);
  useEffect(() => { void refresh(); const timer = window.setInterval(() => void refresh(), 5000); return () => window.clearInterval(timer); }, [refresh]);
  const change = async (item: Schedule, cancel: boolean) => {
    setBusy(true); setError('');
    try {
      await workspaceRequest(slug, `schedules/${item.id}${cancel ? '/cancel' : ''}`, cancel ? 'POST' : 'PATCH',
        cancel ? { expected_version: item.version } : { expected_version: item.version, approved, earliest_dispatch: earliest, latest_dispatch: latest, timezone: item.timezone });
      setEditing(null); await refresh();
    } catch(e) { setError(errorText(e)); } finally { setBusy(false); }
  };
  const visible = items?.filter(s => !search.get('schedule') || s.id === search.get('schedule'));
  return <><ErrorNotice error={error} /><Hint>One-off approved windows only. A missed window never dispatches late. Cluster start remains unreserved.</Hint>
    {!items ? <p role="status">Loading schedules…</p> : !visible?.length ? <Card>No schedules in this view. Check and review an experiment to schedule its plan.</Card> : visible.map(item => <Card key={item.id}>
      <CardHeader title={item.id} note={item.state} />
      <p>Earliest: <time>{item.earliest_dispatch}</time> · Latest: <time>{item.latest_dispatch}</time> (UTC)</p>
      <p>Selected timezone: {item.timezone} · Local window: {new Date(item.earliest_dispatch).toLocaleString(undefined,{timeZone:item.timezone})} – {new Date(item.latest_dispatch).toLocaleString(undefined,{timeZone:item.timezone})}</p>
      {item.reason ? <p role="status">{item.reason}</p> : null}
      <ButtonGroup><Link to={`/projects/${slug}/review/${item.plan_id}`}>Frozen plan</Link>{item.execution_id ? <Link to={`/projects/${slug}/runs?execution=${item.execution_id}`}>Open execution</Link> : null}
        {['scheduled','blocked','missed'].includes(item.state) ? <>{!item.invalidated_at && item.state!=='blocked'?<Button disabled={busy} onClick={() => { setEditing(item); setEarliest(item.earliest_dispatch); setLatest(item.latest_dispatch); setApproved(false); }}>Review a new window</Button>:<Link to={`/projects/${slug}/experiments`}>Check and review a fresh plan</Link>}
          <Button disabled={busy} onClick={() => void change(item,true)}>Cancel schedule approval</Button></> : null}</ButtonGroup>
      {editing?.id === item.id ? <><p>Editing revokes the prior approval. Review and approve the new window.</p>
        <Field label="Earliest dispatch with timezone offset"><TextInput aria-label="Earliest dispatch with timezone offset" value={earliest} onChange={e => { setEarliest(e.target.value); setApproved(false); }} /></Field>
        <Field label="Latest dispatch with timezone offset"><TextInput aria-label="Latest dispatch with timezone offset" value={latest} onChange={e => { setLatest(e.target.value); setApproved(false); }} /></Field>
        <Checkbox label="I reviewed and approve this changed window" checked={approved} onChange={e => setApproved(e.target.checked)} />
        <Button disabled={!approved || busy} onClick={() => void change(item,false)}>Approve new window</Button></> : null}
    </Card>)}</>;
};
