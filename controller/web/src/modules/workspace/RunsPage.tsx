import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { errorText } from '../controller/api';
import { purposeLabel } from '../controller/format';
import { Button, ButtonGroup } from '../../ui/components/Button';
import { Card, CardHeader, Hint, KeyValue } from '../../ui/components/Card';
import { Checkbox, Field, Select, TextInput } from '../../ui/components/Field';
import { Table, TableScroller, THead } from '../../ui/components/Table';
import { workspaceRequest, type Resource } from './api';
import { ErrorNotice, JsonDetails, useWorkspace, WorkspacePage } from './Workspace';
import { Schedules } from './Schedules';
import { workspaceLink } from './navigation';

type Freshness = { state: string; observed_at?: string; error?: string };
type Attempt = { id: string; state: string; number: number; previous_attempt_id?: string; job_ids?: string[] };
type Stage = { collections:string[]; scheduler_references?:unknown[]; id: string; declared_stage_id:string; variant_id?:string; resume_from?:string; state: string; lifecycle: string; purpose?: string; location: string; attempts: Attempt[]; jobs: {job_id:string;status:string}[]; job_ids: string[]; depends_on:string[]; operation:string; resources:Resource; effective_resources?:Resource; effective_resources_by_job?:Record<string,Resource>; completeness:string; retrieval:string; submission:string; output_dir:string; artifacts:string[]; error?:string; waiting_reason?:string; management_history?:{operation_id:string;kind:string}[]; allowed_actions: Record<string,{supported:boolean;reason?:string}>; continued_by?:string; progress?:unknown };
type Execution = { has_scheduler_work:boolean; id:string; version:number|string; plan_id:string; experiment_id?:string; revision?:number; summary:string; state:string; active_count:number; attention_count:number; uncertain_count:number; stages:Stage[]; updated_at:string; freshness:{scheduler:Freshness}; integrity_error?:unknown[] };
type Preview = { id:string; version:number; review_digest:string; targets:unknown[]; affected_stage_ids:string[]; fence_stage_ids:string[]; unaffected_stage_ids:string[]; warnings:string[]; proposed?:unknown };
type Receipt = {id:string;state:string; targets:{id:string;state:string;reason?:string;observed_state?:string}[]};
type Log = {retrieval_supported?:boolean;retrieval_reason?:string;remote_error?:string;text:string|null;purpose:string;stream_id:string;availability:string;reason?:string;boundary?:string;cursor?:string;path?:string;encoding:string;offset:number;next_offset:number;freshness:Freshness};

const AttemptLogs = ({ attempt, purpose }: {attempt:Attempt;purpose?:string}) => {
  const {slug} = useWorkspace();
  const [stream,setStream] = useState('stdout');
  const [job,setJob] = useState(attempt.job_ids?.[0] || '');
  const [value,setValue] = useState<Log|null>(null);
  const [error,setError] = useState('');
  const [follow,setFollow] = useState(false);
  const [search,setSearch] = useState('');
  const refresh = useCallback(async (cursor?:string) => {
    try { const params = new URLSearchParams({stream,...(job ? {job_id:job} : {}),...(cursor ? {cursor}: {})});
      const result = await workspaceRequest<Log>(slug,`attempts/${attempt.id}/logs?${params}`); setValue(result); setError('');
    } catch(e) { setError(errorText(e)); }
  },[slug,attempt.id,stream,job]);
  useEffect(() => { setValue(null); void refresh(); },[refresh]);
  useEffect(() => { if(!follow) return; const timer = window.setInterval(() => void refresh(),3000); return () => window.clearInterval(timer); },[follow,refresh]);
  return <section aria-label={`Logs for ${attempt.id}`}><h4>Attempt {attempt.id} · {purposeLabel(purpose)}</h4>
    <Select aria-label="Log stream" value={stream} options={['stdout','stderr','wrapper','controller'].map(v=>({value:v,label:v}))} onChange={e=>setStream(e.target.value)} />
    {(attempt.job_ids?.length || 0) > 1 ? <Select aria-label="Exact log job" value={job} options={attempt.job_ids!.map(v=>({value:v,label:v}))} onChange={e=>setJob(e.target.value)} /> : null}
    <ButtonGroup><Button onClick={()=>void refresh()}>Tail</Button><Button onClick={()=>setFollow(!follow)}>{follow ? 'Pause follow':'Follow'}</Button>
      <Button disabled={!value?.cursor} onClick={()=>void refresh(value?.cursor)}>Next bytes</Button><Button disabled={!['stdout','stderr'].includes(stream)||!value?.retrieval_supported} title={value?.retrieval_reason||'Read the stream to check exact retrieval capability. Local files are already available in Files.'} onClick={()=>void workspaceRequest(slug,`attempts/${attempt.id}/retrieve-log`,'POST',{stream,job_id:job || undefined}).then(()=>refresh()).catch(e=>setError(errorText(e)))}>Retrieve full exact file</Button></ButtonGroup>
    <ErrorNotice error={error}/>{!value ? <p role="status">Loading bounded log…</p> : <><Hint>{value.stream_id} · {value.availability} · {value.freshness.state} · Observed: {value.freshness.observed_at || 'Unknown'}</Hint>
      {value.boundary ? <p role="status">Stream boundary: {value.boundary}. Earlier bytes are separate.</p>:null}{value.reason ? <p>{value.reason}</p>:null}{value.remote_error ? <p role="status">Remote unavailable: {value.remote_error}. Cached bytes retain their observed age.</p>:null}
      {value.encoding === 'binary' ? <p>Binary stream. Inspect metadata and retrieve the file in Files.</p>:<><Field label="Search loaded text"><TextInput aria-label="Search loaded text" value={search} onChange={e=>setSearch(e.target.value)}/></Field>
        <pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',maxHeight:360,overflow:'auto'}}>{search ? value.text?.split('\n').filter(line=>line.toLowerCase().includes(search.toLowerCase())).join('\n') : value.text}</pre></>}
      <Hint>Showing bytes {value.offset}–{value.next_offset}; each response is limited to 64 KiB.</Hint>
      {value.path ? <Link to={workspaceLink(slug,'files',{root:'source',path:value.path.split('/').slice(0,-1).join('/'),preview:value.path,attempt:attempt.id,purpose})}>Open exact log in Files</Link>:null}</>}
  </section>;
};

export const ProjectRuns = () => {
  const {slug} = useWorkspace();
  const navigate = useNavigate();
  const [query,setQuery] = useSearchParams();
  const view = query.get('view') || 'executions';
  const [items,setItems] = useState<Execution[]|null>(null);
  const [queue,setQueue] = useState<Record<string,unknown>[]|null>(null);
  const [error,setError] = useState('');
  const [busy,setBusy] = useState(false);
  const [selected,setSelected] = useState<Record<string,string[]>>({});
  const [selectedJobs,setSelectedJobs] = useState<Record<string,string[]>>({});
  const [preview,setPreview] = useState<Preview|null>(null);
  const [receipt,setReceipt] = useState<Receipt|null>(null);
  const operationId=query.get('operation');
  useEffect(()=>{let active=true;setReceipt(null);if(operationId)void workspaceRequest<Receipt>(slug,`operations/${operationId}`).then(r=>{if(active)setReceipt(r);}).catch(e=>{if(active)setError(errorText(e));});return()=>{active=false;};},[slug,operationId]);
  const [approved,setApproved] = useState(false);
  const [logAttempt,setLogAttempt] = useState<{attempt:Attempt;purpose?:string}|null>(null);
  const [recoveryMode,setRecoveryMode] = useState('retry');
  const [walltime,setWalltime] = useState('');
  const scopeParams=new URLSearchParams();
  for(const key of ['execution','experiment','stage','variant','attempt','purpose','campaign','collection','state','attention','date','search']) {const value=query.get(key);if(value)scopeParams.set(key,value);}
  const apiQuery=scopeParams.toString();
  const refresh = useCallback(async () => {
    try {
      const [r,q] = await Promise.all([workspaceRequest<{executions:Execution[]}>(slug,`executions?${apiQuery}`),workspaceRequest<{jobs:Record<string,unknown>[]}>(slug,`queue?${apiQuery}`)]);
      setItems(r.executions);setQueue(q.jobs);setError('');
    } catch(e) {setError(errorText(e));}
  },[slug,apiQuery]);
  useEffect(()=>{void refresh();const timer=window.setInterval(()=>void refresh(),5000);return()=>window.clearInterval(timer);},[refresh]);
  const run = async (fn:()=>Promise<void>) => {setBusy(true);setError('');try{await fn();await refresh();}catch(e){setError(errorText(e));}finally{setBusy(false);}};
  const filter = (key:string,value:string) => {const next=new URLSearchParams(query);if(key==='view')next.delete('state');if(value)next.set(key,value);else next.delete(key);setQuery(next);};
  const stageInScope = (s:Stage) => (!query.get('collection') || s.collections.includes(query.get('collection')!)) && (!query.get('stage') || s.id===query.get('stage')) && (!query.get('variant') || s.variant_id===query.get('variant')) && (!query.get('attempt') || s.attempts.some(a=>a.id===query.get('attempt')));
  useEffect(()=>{ const wanted=query.get('attempt');if(!wanted||!items)return;for(const e of items)for(const s of e.stages){const a=s.attempts.find(a=>a.id===wanted);if(a){setLogAttempt({attempt:a,purpose:s.purpose});return;}}},[query,items]);
  const rows = items?.filter(e=>e.stages.some(stageInScope) && (!query.get('execution') || e.id===query.get('execution')) && (!query.get('experiment') || e.experiment_id===query.get('experiment')) && (!query.get('state') || e.summary===query.get('state')) && (!query.get('purpose') || e.stages.some(s=>s.purpose===query.get('purpose'))) && (!query.get('attention') || (query.get('attention')==='needs_attention'?e.attention_count>0:query.get('attention')==='uncertain'?e.uncertain_count>0:e.stages.some(s=>s.state===query.get('attention')))));
  const prepare = (execution:Execution,kind='cancel') => run(async()=>{
    const result=await workspaceRequest<Preview>(slug,'management-plans','POST',{kind,execution_id:execution.id,expected_version:execution.version,stage_ids:selected[execution.id] || [],...(selectedJobs[execution.id]?.length?{job_ids:selectedJobs[execution.id]}:{}),...(kind==='pending-change'?{proposed:{walltime}}:{})});
    setPreview(result);setApproved(false);setReceipt(null);
  });
  const recover = (execution:Execution) => run(async()=>{
    const stageIds=selected[execution.id]||[];
    const resources = recoveryMode==='replace' && walltime ? Object.fromEntries(execution.stages.filter(s=>stageIds.includes(s.id)).map(s=>[s.declared_stage_id,{walltime}])) : undefined;
    const plan=await workspaceRequest<{id:string}>(slug,`executions/${execution.id}/recovery`,'POST',{stage_ids:stageIds,mode:recoveryMode,resources});
    navigate(`/projects/${slug}/review/${plan.id}`);
  });
  return <WorkspacePage title="Runs" actions={<Link to={`/projects/${slug}/experiments`}>New experiment</Link>}><ErrorNotice error={error}/>
    <Card><ButtonGroup>{['executions','queue','schedules'].map(v=><Button key={v} aria-pressed={view===v} onClick={()=>filter('view',v)}>{v[0].toUpperCase()+v.slice(1)}</Button>)}<Button disabled={busy} onClick={()=>void refresh()}>Refresh</Button></ButtonGroup>
      {view!=='schedules'?<><Select aria-label="Purpose" value={query.get('purpose')||''} options={[{value:'',label:'All purposes'},{value:'experiment',label:'Experiments'},{value:'smoke-test',label:'Smoke tests'}]} onChange={e=>filter('purpose',e.target.value)}/>
        <Select aria-label={view==='queue'?'Scheduler state':'Execution state'} value={query.get('state')||''} options={(view==='queue'?['','PENDING','RUNNING','COMPLETING','COMPLETED','FAILED','CANCELLED','TIMEOUT','UNKNOWN']:['','active','waiting','needs-attention','succeeded','failed','cancelled','partial-success']).map(v=>({value:v,label:v||'All states'}))} onChange={e=>filter('state',e.target.value)}/>
        <Select aria-label="Collection" value={query.get('collection')||''} options={[{value:'',label:'All collections'},{value:'original',label:'Original corpus'},{value:'tlaibench',label:'TLAiBench · First numbers'},{value:'unknown',label:'Unknown collection'}]} onChange={e=>filter('collection',e.target.value)}/>
        <Field label="Campaign"><TextInput aria-label="Campaign" value={query.get('campaign')||''} onChange={e=>filter('campaign',e.target.value)}/></Field>
        <Field label="Search executions and jobs"><TextInput aria-label="Search executions and jobs" value={query.get('search')||''} onChange={e=>filter('search',e.target.value)}/></Field>
        <Field label="UTC approval or submission date"><TextInput aria-label="UTC approval or submission date" placeholder="YYYY-MM-DD or YYYY-MM-DD/YYYY-MM-DD" value={query.get('date')||''} onChange={e=>filter('date',e.target.value)}/></Field><Hint>Dates select execution approval or scheduler submission in UTC. Both range endpoints are included.</Hint>
        <Button onClick={()=>setQuery(view==='queue'?{view:'queue'}:{})}>Clear filters</Button></>:null}
      {query.get('execution')?<Hint>Execution filter: {query.get('execution')}</Hint>:null}</Card>
    {view==='schedules'?<Schedules/>:view==='queue'?<Card><CardHeader title="Queue and historical scheduler evidence"/><Hint>Scheduler states retain their observation age. Estimates are not reservations. Historical jobs remain Unclassified.</Hint>
      {!queue?<p role="status">Loading queue…</p>:!queue.length?<p>No scheduler jobs match these filters. Clear filters to inspect project history.</p>:<TableScroller><Table><THead><tr><th>Job</th><th>Execution / stage</th><th>Purpose</th><th>State / reason</th><th>Request</th><th>Elapsed / time limit</th><th>Estimated start</th><th>Observed</th></tr></THead><tbody>{queue.filter(j=>(!query.get('purpose')||j.purpose===query.get('purpose'))&&(!query.get('execution')||j.execution_id===query.get('execution'))&&(!query.get('experiment')||j.experiment_id===query.get('experiment'))&&(!query.get('stage')||j.stage_id===query.get('stage'))&&(!query.get('attempt')||j.attempt_id===query.get('attempt'))&&(!query.get('variant')||j.variant_id===query.get('variant'))).map((j,i)=><tr key={i}><td>{String(j.job_id)}</td><td>{j.execution_id?<Link to={`/projects/${slug}/runs?execution=${j.execution_id}`}>{String(j.execution_id)} / {String(j.stage_id)}</Link>:'Historical job'}</td><td>{purposeLabel(String(j.purpose))}</td><td>{String(j.status)} · {String(j.reason||'Unknown')}</td><td><JsonDetails title="Effective request" value={j.resources||'Unknown'}/></td><td>{j.elapsed_s===null||j.elapsed_s===undefined?'Unknown':`${j.elapsed_s} seconds`} / {String((j.resources as Resource)?.walltime||'Unknown')}</td><td>{j.estimated_start?`Estimate: ${j.estimated_start}`:'Unknown'}</td><td>{String((j.freshness as Freshness)?.observed_at||'Unknown')} · {(j.freshness as Freshness)?.state}</td></tr>)}</tbody></Table></TableScroller>}</Card>
    :!items?<p role="status">Loading executions…</p>:!rows?.length?<Card>{items.length?'No executions match these filters. Clear filters to inspect project history.':'No executions yet. Review an experiment to begin; historical jobs remain in Queue.'}</Card>:rows.map(execution=><Card key={execution.id}><CardHeader title={execution.id} note={`${execution.summary} · ${execution.active_count} active · ${execution.attention_count} need attention`}/>
      <ButtonGroup>{execution.experiment_id?<Link to={`/projects/${slug}/experiments/${execution.experiment_id}/revisions/${execution.revision}`}>Open experiment revision {execution.revision}</Link>:null}<Link to={`/projects/${slug}/review/${execution.plan_id}`}>Approved plan</Link><Link to={`/projects/${slug}/results?execution=${execution.id}`}>Results</Link></ButtonGroup>
      <Hint>{execution.has_scheduler_work?`Scheduler: ${execution.freshness.scheduler.state} · Observed ${execution.freshness.scheduler.observed_at||'Unknown'}.`:'Controller-host execution; no scheduler allocation.'} Last controller update: {execution.updated_at}</Hint>
      {execution.freshness.scheduler.error?<p role="alert">{execution.freshness.scheduler.error}</p>:null}
      {execution.integrity_error?.length?<div role="alert"><p>Execution paused: approved files changed. Retrieval, recovery, and reconciliation are unavailable until the integrity errors resolve.</p><JsonDetails title="Approved files failed integrity checks" value={execution.integrity_error}/></div>:null}
      <TableScroller><Table><THead><tr><th>Scope</th><th>Stage / attempt</th><th>Purpose</th><th>Submission / stage</th><th>Scheduler</th><th>Completeness / retrieval</th><th>Detail</th></tr></THead><tbody>{execution.stages.filter(s=>stageInScope(s)&&(!query.get('purpose')||s.purpose===query.get('purpose'))).map(stage=><tr key={stage.id}>
        <td><Checkbox label="" aria-label={`Select ${stage.id}`} checked={selected[execution.id]?.includes(stage.id)||false} onChange={e=>setSelected({...selected,[execution.id]:e.target.checked?[...(selected[execution.id]||[]),stage.id]:(selected[execution.id]||[]).filter(id=>id!==stage.id)})}/></td>
        <td>{stage.id}{stage.resume_from?<Hint>Resumed from: {stage.resume_from}</Hint>:null}<Hint>{stage.attempts.at(-1)?.id}</Hint>{stage.continued_by?<Link to={`/projects/${slug}/runs?execution=${stage.continued_by}`}>Continuation</Link>:null}</td><td>{purposeLabel(stage.purpose)}</td><td>{stage.submission} / {stage.lifecycle}<Hint>{stage.error||stage.waiting_reason}</Hint></td>
        <td>{stage.jobs.length?stage.jobs.map(j=><div key={j.job_id}>#{j.job_id}: {j.status}{stage.jobs.length>1?<Checkbox label={`Exact job ${j.job_id}`} checked={selectedJobs[execution.id]?.includes(j.job_id)||false} onChange={event=>{setSelectedJobs({...selectedJobs,[execution.id]:event.target.checked?[...(selectedJobs[execution.id]||[]),j.job_id]:(selectedJobs[execution.id]||[]).filter(id=>id!==j.job_id)});if(event.target.checked)setSelected({...selected,[execution.id]:Array.from(new Set([...(selected[execution.id]||[]),stage.id]))});}}/>:null}</div>):stage.location==='controller'?'Controller host':'Not observed'}</td><td>{stage.completeness} / {stage.retrieval}</td>
        <td><details><summary>Inspect stage</summary><KeyValue label="Operation">{stage.operation}</KeyValue><KeyValue label="Collection">{stage.collections.join(', ')}</KeyValue><JsonDetails title="Exact scheduler identities and restart attribution" value={stage.scheduler_references||[]}/><KeyValue label="Dependencies">{stage.depends_on.join(', ')||'None'}</KeyValue><KeyValue label="Output">{stage.output_dir}</KeyValue><JsonDetails title="Approved resources" value={stage.resources}/><JsonDetails title="Effective resources" value={stage.effective_resources_by_job||stage.effective_resources||stage.resources}/><JsonDetails title="Management history" value={stage.management_history||[]}/>{stage.management_history?.map((entry,i)=><Link key={`${entry.operation_id}-${i}`} to={workspaceLink(slug,'runs',{execution:execution.id,operation:entry.operation_id})}>Open {entry.kind} receipt</Link>)}<JsonDetails title="Declared progress" value={stage.progress||'Unknown'}/>{stage.attempts.map(a=><Button key={a.id} onClick={()=>setLogAttempt({attempt:a,purpose:stage.purpose})}>Logs: attempt {a.number}</Button>)}{stage.artifacts.map(id=><Link key={id} to={`/projects/${slug}/files?artifact=${id}`}>Artifact {id}</Link>)}</details></td></tr>)}</tbody></Table></TableScroller>
      <details><summary>Dependency order and conditions</summary><ol>{execution.stages.map(s=><li key={s.id}>{s.id} requires {s.depends_on.join(', ')||'no prerequisite'}; declared successful operation and checked outputs gate continuation.</li>)}</ol></details>
      <ButtonGroup><Button disabled={busy||!selected[execution.id]?.length||!execution.stages.filter(s=>selected[execution.id]?.includes(s.id)).every(s=>s.allowed_actions.cancel.supported)} onClick={()=>void prepare(execution)}>Review cancellation</Button>
        <Button disabled={busy||Boolean(execution.integrity_error?.length)||!execution.stages.some(s=>s.state==='uncertain')} onClick={()=>void run(async()=>{await workspaceRequest(slug,`executions/${execution.id}/reconcile`,'POST',{});})}>Reconcile submission</Button>
        <Button disabled={busy||Boolean(execution.integrity_error?.length)||!selected[execution.id]?.length} onClick={()=>void run(async()=>{await workspaceRequest(slug,`executions/${execution.id}/fetch`,'POST',{stage_ids:selected[execution.id]});})}>Retrieve selected outputs</Button></ButtonGroup>
      <Hint>{execution.stages.find(s=>!s.allowed_actions.cancel.supported)?.allowed_actions.cancel.reason}</Hint>
      <Select aria-label={`Recovery mode ${execution.id}`} value={recoveryMode} options={['retry','resume','replace','checked-outputs'].map(v=>({value:v,label:v==='checked-outputs'?'Use checked outputs':v}))} onChange={e=>setRecoveryMode(e.target.value)}/>
      <Field label="Replacement walltime (optional, HH:MM:SS)"><TextInput aria-label="Replacement walltime (optional, HH:MM:SS)" value={walltime} onChange={e=>setWalltime(e.target.value)}/></Field>
      <Hint>Replacement requires observed termination of its original writer. Stop work through a reviewed cancellation first. Shorter walltime never guarantees an earlier start.</Hint>
      <Button disabled={busy||Boolean(execution.integrity_error?.length)||!selected[execution.id]?.length} onClick={()=>void recover(execution)}>Review {recoveryMode}</Button>
      <Button disabled={busy||!walltime||!selected[execution.id]?.length||!execution.stages.filter(s=>selected[execution.id]?.includes(s.id)).every(s=>s.allowed_actions['pending-change'].supported)} onClick={()=>void prepare(execution,'pending-change')}>Review pending walltime change</Button>
      <Hint>{execution.stages.find(s=>!s.allowed_actions['pending-change'].supported)?.allowed_actions['pending-change'].reason}</Hint>
    </Card>)}
    {preview?<Card><CardHeader title="Review exact management scope"/><JsonDetails title="Targets and observed requests" value={preview.targets}/><KeyValue label="Affected stages">{preview.affected_stage_ids.join(', ')}</KeyValue><KeyValue label="Unsent work fenced first">{preview.fence_stage_ids.join(', ')||'None'}</KeyValue><KeyValue label="Unaffected siblings">{preview.unaffected_stage_ids.join(', ')||'None'}</KeyValue>{preview.warnings.map(w=><p key={w}>{w}</p>)}<JsonDetails title="Proposed change" value={preview.proposed}/><Checkbox label="I approve this exact target scope and its effects" checked={approved} onChange={e=>setApproved(e.target.checked)}/><Button disabled={!approved||busy} onClick={()=>void run(async()=>{const r=await workspaceRequest<Receipt>(slug,`management-plans/${preview.id}/apply`,'POST',{expected_version:preview.version,review_digest:preview.review_digest,idempotency_key:`management:${preview.id}`});setReceipt(r);filter('operation',r.id);setPreview(null);})}>Apply reviewed action</Button></Card>:null}
    {receipt?<Card><CardHeader title={`Operation ${receipt.id}`} note={receipt.state}/><Link to={workspaceLink(slug,'runs',{operation:receipt.id,execution:query.get('execution')})}>Permanent operation link</Link>{receipt.targets.map(t=><p key={t.id}>{t.id}: {t.state} · {t.reason} {t.observed_state?`Observed: ${t.observed_state}`:''}</p>)}<Button disabled={busy} onClick={()=>void run(async()=>setReceipt(await workspaceRequest<Receipt>(slug,`operations/${receipt.id}/reconcile`,'POST',{})))}>Reconcile action</Button></Card>:null}
    {logAttempt?<Card><Button onClick={()=>setLogAttempt(null)}>Close logs</Button><AttemptLogs key={logAttempt.attempt.id} {...logAttempt}/></Card>:null}
  </WorkspacePage>;
};
