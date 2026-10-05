import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { Button, ButtonGroup } from '../../ui/components/Button';
import { Card, CardHeader, Hint, KeyValue, Stack } from '../../ui/components/Card';
import { Field, Select, TextInput } from '../../ui/components/Field';
import { Table, TableScroller, THead } from '../../ui/components/Table';
import { Tag } from '../../ui/components/Tag';
import { errorText } from '../controller/api';
import { runnerRequest, type Execution, type Log } from './api';
import { ProjectPage } from './ProjectPage';

export const ExecutionsPage = () => {
  const { slug = '' } = useParams();
  const [search, setSearch] = useSearchParams();
  const [data, setData] = useState<{ executions: Execution[]; total: number; next_offset: number | null } | null>(null);
  const [error, setError] = useState('');
  const query = search.toString();
  useEffect(() => {
    let active = true;
    const load = async () => {
      try { const result = await runnerRequest<typeof data>(slug, `executions?${query}`); if (active) { setData(result); setError(''); } }
      catch (reason) { if (active) setError(errorText(reason)); }
    };
    setData(null); void load();
    const timer = window.setInterval(() => void load(), 5000);
    return () => { active = false; window.clearInterval(timer); };
  }, [slug, query]);
  const filter = (key: string, value: string) => {
    const next = new URLSearchParams(search); next.delete('offset');
    if (value) next.set(key, value); else next.delete(key);
    setSearch(next);
  };
  return <ProjectPage title="Workflow executions">
    {error ? <Card role="alert">{error}</Card> : null}
    <Card><CardHeader title="Executions" note={data ? `${data.total} runs` : 'Loading…'} />
      <ButtonGroup><Field label="State"><Select aria-label="Execution state" value={search.get('state') ?? ''} options={['', 'active', 'waiting', 'needs-attention', 'succeeded', 'failed', 'cancelled', 'partial-success'].map((one) => ({ value: one, label: one || 'All states' }))} onChange={(event) => filter('state', event.target.value)} /></Field>
        <Field label="Search"><TextInput aria-label="Search executions" value={search.get('search') ?? ''} onChange={(event) => filter('search', event.target.value)} /></Field></ButtonGroup>
      <TableScroller><Table><THead><tr><th>Run</th><th>State</th><th>Stages</th><th>Updated</th></tr></THead><tbody>{data?.executions.map((one) => <tr key={one.id}>
        <td><Link to={`/projects/${encodeURIComponent(slug)}/executions/${encodeURIComponent(one.id)}`}>{one.experiment_name || one.id}</Link><Hint>{one.id}</Hint></td>
        <td><Tag color={one.summary === 'succeeded' ? 'green' : one.summary === 'needs-attention' ? 'yellow' : 'gray'} text={one.summary} /></td><td>{one.stages.length}</td><td>{one.updated_at ? new Date(one.updated_at).toLocaleString() : 'Unknown'}</td>
      </tr>)}</tbody></Table></TableScroller>
      {data && !data.executions.length ? <p>No executions match this view.</p> : null}
      <ButtonGroup><Button disabled={!search.get('offset')} onClick={() => { const next = new URLSearchParams(search); next.delete('offset'); setSearch(next); }}>First page</Button>
        <Button disabled={data?.next_offset == null} onClick={() => { const next = new URLSearchParams(search); next.set('offset', String(data?.next_offset)); setSearch(next); }}>Next page</Button></ButtonGroup>
    </Card>
  </ProjectPage>;
};

export const ExecutionPage = () => {
  const { slug = '', executionId = '' } = useParams();
  const [execution, setExecution] = useState<Execution | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState('');
  const [stream, setStream] = useState('stdout');
  const [job, setJob] = useState('');
  const [log, setLog] = useState<Log | null>(null);
  const logGeneration = useRef(0);
  const attempts = execution?.stages.flatMap((stage) => (stage.attempts ?? []).map((one) => ({ ...one, stage: stage.id }))) ?? [];
  const selected = attempts.find((one) => one.id === attempt);
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const result = await runnerRequest<Execution>(slug, `executions/${encodeURIComponent(executionId)}`);
        if (active) { setExecution(result); setError(''); }
      } catch (reason) { if (active) setError(errorText(reason)); }
    };
    setExecution(null); setAttempt(''); setLog(null); void load();
    const timer = window.setInterval(() => void load(), 5000);
    return () => { active = false; window.clearInterval(timer); };
  }, [slug, executionId]);
  const jobKey = selected?.job_ids?.join(',') ?? '';
  useEffect(() => { setJob(jobKey.split(',')[0]); }, [attempt, jobKey]);
  const loadLogs = useCallback(async (cursor?: string) => {
    if (!attempt) return;
    const generation = ++logGeneration.current;
    try {
      const params = new URLSearchParams({ attempt, stream, ...(job ? { job_id: job } : {}), ...(cursor ? { cursor } : {}) });
      const result = await runnerRequest<Log>(slug, `executions/${encodeURIComponent(executionId)}/logs?${params}`);
      if (generation === logGeneration.current) { setLog(result); setError(''); }
    } catch (reason) { if (generation === logGeneration.current) setError(errorText(reason)); }
  }, [slug, executionId, attempt, stream, job]);
  useEffect(() => { setLog(null); void loadLogs(); return () => { logGeneration.current += 1; }; }, [loadLogs]);
  return <ProjectPage title={execution?.experiment_name || 'Workflow execution'}>
    {error ? <Card role="alert">{error}</Card> : null}
    {!execution ? <p role="status">Loading execution…</p> : <>
      <Card><CardHeader title={execution.id} note={execution.summary} /><KeyValue label="Plan">{execution.plan_id}</KeyValue><KeyValue label="State">{execution.state}</KeyValue>
        <ButtonGroup>
          <Link to={`/projects/${encodeURIComponent(slug)}/runner?plan=${encodeURIComponent(execution.plan_id)}`}>Inspect frozen plan</Link>
          <Link to={`/projects/${encodeURIComponent(slug)}/runs?execution=${encodeURIComponent(execution.id)}`}>Recovery and run controls</Link>
        </ButtonGroup></Card>
      {execution.stages.map((stage) => <Card key={stage.id}><CardHeader title={stage.id} note={stage.state} />
        <Hint>{stage.operation} · {stage.location} · {stage.purpose}</Hint><KeyValue label="Depends on">{stage.depends_on?.join(', ') || 'None'}</KeyValue>
        <KeyValue label="Output checks">{stage.completeness || 'Unknown'}</KeyValue><KeyValue label="Retrieval">{stage.retrieval || 'Not requested'}</KeyValue>
        <KeyValue label="Jobs">{stage.job_ids?.join(', ') || 'No scheduler jobs'}</KeyValue>
        {stage.error || stage.waiting_reason ? <p>{stage.error || stage.waiting_reason}</p> : null}
        <ButtonGroup>{stage.attempts?.map((one) => <Button key={one.id} onClick={() => setAttempt(one.id)}>Logs: {one.id} · {one.state}</Button>)}</ButtonGroup>
      </Card>)}
      {attempt ? <Card><CardHeader title={`Logs · ${selected?.stage ?? attempt}`} /><ButtonGroup>
        <Select aria-label="Log stream" value={stream} options={['stdout', 'stderr', 'controller', 'wrapper'].map((one) => ({ value: one, label: one }))} onChange={(event) => setStream(event.target.value)} />
        {selected?.job_ids?.length ? <Select aria-label="Log job" value={job} options={selected.job_ids.map((one) => ({ value: one, label: one }))} onChange={(event) => setJob(event.target.value)} /> : null}
        <Button onClick={() => void loadLogs()}>Refresh logs</Button><Button disabled={!log?.cursor} onClick={() => void loadLogs(log?.cursor)}>Next bounded page</Button></ButtonGroup>
        <Hint>{log?.availability} {log?.reason} {log?.boundary}</Hint><pre tabIndex={0} style={{ maxHeight: 450, overflow: 'auto', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{log?.text ?? 'Loading logs…'}</pre>
      </Card> : null}
      <Card><CardHeader title="Artifacts" />{execution.artifacts?.length ? <Stack>{execution.artifacts.map((artifact) => <div key={artifact.id}><strong>{artifact.id}</strong><Hint>{artifact.complete ? 'Complete' : 'Incomplete'} · {artifact.purpose}</Hint>
        {(artifact.files ?? [{ path: artifact.path }]).map((file) => <p key={file.path}><a download href={`/api/v1/projects/${encodeURIComponent(slug)}/runner/artifacts/${encodeURIComponent(artifact.id)}?path=${encodeURIComponent(file.path)}`}>{file.path}</a></p>)}
      </div>)}</Stack> : <p>No indexed artifacts yet.</p>}</Card>
    </>}
  </ProjectPage>;
};
