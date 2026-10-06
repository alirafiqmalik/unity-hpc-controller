/**
 * Evaluation datasets: the test suites an evaluation runs against.
 *
 * A dataset is a directory under `<datasets_dir>/` in the project: metadata in
 * `dataset.json`, records (inputs + expectations) in `records.jsonl`. The
 * list shows profile and linked runs; the detail page shows the records,
 * lets you add records by hand, and links to the runs that used it.
 */

import styled from '@emotion/styled';
import { IconDatabase, IconDatabasePlus, IconPlayerPlay, IconPlus, IconRefresh, IconTag } from '@tabler/icons-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { errorText } from '../controller/api';
import { Button, IconButton } from '../../ui/components/Button';
import { Card, CardHeader, Grid, Hint, KeyValue } from '../../ui/components/Card';
import { EmptyState } from '../../ui/components/EmptyState';
import { Field, SearchField, Select, TextArea, TextInput } from '../../ui/components/Field';
import { Modal } from '../../ui/components/SidePanel';
import { StatCard } from '../../ui/components/StatCard';
import { MonoCell, Table, TableEmptyRow, TableScroller, THead, TRow } from '../../ui/components/Table';
import { Tag, TagRow } from '../../ui/components/Tag';
import { useToast } from '../../ui/components/Toast';
import { genaiApi, type DatasetColumn, type DatasetDetail, type DatasetRecord, type DatasetSummary } from './api';
import { BackLink, formatNumber, formatTime, GenAIPage, Mono, Muted, percent, SectionHead, SectionTitle, StateTag, Toolbar, useGenAI } from './GenAIWorkspace';

const Cell = styled.td`
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

const NameCell = styled.td`
  max-width: 420px;
  min-width: 260px;

  & > div:last-of-type {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
`;

const Pre = styled.pre`
  background: ${({ theme }) => theme.background.primary};
  border: 1px solid ${({ theme }) => theme.border.color.light};
  border-radius: ${({ theme }) => theme.border.radius.sm};
  font-family: ${({ theme }) => theme.font.familyMono};
  font-size: ${({ theme }) => theme.font.size.xs};
  line-height: 1.5;
  max-height: 260px;
  overflow: auto;
  padding: ${({ theme }) => theme.spacing(2)};
  white-space: pre-wrap;
  overflow-wrap: anywhere;
`;

const ViewerCell = styled.td`
  min-width: 260px;
  max-width: 460px;
  width: 360px;
  vertical-align: top;
  white-space: normal !important;
  overflow-wrap: anywhere;
  line-height: 1.55;
  border-right: 1px solid ${({ theme }) => theme.border.color.light};
  details > summary { cursor: pointer; }
  details[open] > summary { margin-bottom: 8px; }
  pre { margin: 0; max-height: 440px; }
`;

const Histogram = styled.div`
  display: flex;
  align-items: flex-end;
  gap: 3px;
  height: 34px;
  margin-top: 10px;
  border-bottom: 1px solid ${({ theme }) => theme.border.color.light};
  span { flex: 1; background: ${({ theme }) => theme.accent.primary}; opacity: 0.75; min-height: 2px; border-radius: 2px 2px 0 0; }
`;

const ColumnHead = ({ column }: { column: DatasetColumn }) => {
  const { stats } = column;
  const peak = Math.max(...stats.histogram, 1);
  const category = stats.categories[0];
  return <th style={{ minWidth: 260, verticalAlign: 'top', textTransform: 'none' }}>
    <Mono>{column.label}</Mono>
    <div style={{ fontWeight: 400, marginTop: 4 }}><Muted>{column.type} · {column.group === 'expectations' ? 'expected' : column.group}</Muted></div>
    {stats.histogram.length ? <Histogram aria-label={`${column.type === 'string' ? 'Text length' : 'Value'} distribution: ${stats.min} to ${stats.max}`}>
      {stats.histogram.map((count, index) => <span key={index} title={`${formatNumber(count)} rows`} style={{ height: `${Math.max(4, count / peak * 100)}%` }} />)}
    </Histogram> : null}
    <div style={{ fontWeight: 400, marginTop: 6 }}><Muted>
      {category ? `${category.label.slice(0, 26)} · ${percent(category.count / Math.max(stats.count, 1))}` : stats.min !== undefined ? `${formatNumber(stats.min)}–${formatNumber(stats.max ?? stats.min)}${column.type === 'string' ? ' characters' : ''}` : `${formatNumber(stats.count)} values`}
      {stats.missing ? ` · ${formatNumber(stats.missing)} missing` : ''}
    </Muted></div>
  </th>;
};

const ValuePreview = ({ value, type }: { value: unknown; type: string }) => {
  if (value === null || value === undefined) return <Muted>—</Muted>;
  if (typeof value === 'boolean') return <Tag color={value ? 'green' : 'gray'} text={String(value)} mono />;
  if (typeof value === 'number') return <Mono>{formatNumber(value)}</Mono>;
  if (typeof value === 'string') {
    if (value.length <= 260) return <div style={{ whiteSpace: 'pre-wrap' }}>{value}</div>;
    return <details><summary>{value.slice(0, 230)}… <Muted>Show full text</Muted></summary><Pre>{value}</Pre></details>;
  }
  if (type === 'messages' && Array.isArray(value)) {
    return <details><summary>{value.length} messages · <Muted>Expand conversation</Muted></summary>
      {value.map((message: Record<string, unknown>, index) => <div key={index} style={{ marginBottom: 12 }}><Tag color={message.role === 'assistant' ? 'purple' : 'blue'} text={String(message.role ?? message.from ?? 'message')} /><Pre>{typeof (message.content ?? message.value) === 'string' ? String(message.content ?? message.value) : JSON.stringify(message.content ?? message.value, null, 2)}</Pre></div>)}
    </details>;
  }
  const object = value as Record<string, unknown>;
  const src = String(object.src ?? object.url ?? object.path ?? '');
  const safeMedia = /^https:\/\//.test(src);
  if (type === 'image' && safeMedia) return <a href={src} target="_blank" rel="noreferrer"><img src={src} alt="Dataset image" loading="lazy" style={{ maxWidth: 220, maxHeight: 160 }} /></a>;
  if (type === 'audio' && safeMedia) return <audio controls preload="none" src={src} style={{ maxWidth: 250 }} />;
  if (type === 'video' && safeMedia) return <video controls preload="none" src={src} style={{ maxWidth: 250 }} />;
  return <details><summary>{Array.isArray(value) ? `${value.length} items` : Object.keys(object).join(', ').slice(0, 90)} · <Muted>Expand {type}</Muted></summary><Pre>{JSON.stringify(value, null, 2)}</Pre></details>;
};

const recordValue = (record: DatasetRecord, column: DatasetColumn): unknown =>
  record[column.group as 'inputs' | 'expectations' | 'tags'][column.key.slice(column.group.length + 1)];

const sourceColor = (type: unknown): 'blue' | 'green' | 'purple' | 'gray' => (type === 'TRACE' ? 'blue' : type === 'HUMAN' ? 'green' : type === 'DOCUMENT' ? 'purple' : 'gray');

/* ------------------------------------------------------------------------ */

const CreateDialog = ({ onClose, onCreated }: { onClose: () => void; onCreated: (dataset: DatasetDetail) => void }) => {
  const { slug } = useGenAI();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [tags, setTags] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const parseTags = (): Record<string, string> => Object.fromEntries(
    tags.split(/[,\n]/).map((part) => part.trim()).filter(Boolean).map((part) => {
      const [k, ...rest] = part.split('=');
      return [k.trim(), rest.join('=').trim()];
    }),
  );
  const create = async () => {
    setBusy(true);
    try {
      onCreated(await genaiApi.createDataset(slug, { name: name.trim(), description, tags: parseTags() }));
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open onClose={onClose} title="Create evaluation dataset">
      {error ? <Card role="alert">{error}</Card> : null}
      <Field label="Name"><TextInput value={name} placeholder="regression_test_suite" onChange={(e) => setName(e.target.value)} autoFocus /></Field>
      <Field label="Description"><TextArea rows={3} value={description} placeholder="What this set tests, and why it exists" onChange={(e) => setDescription(e.target.value)} /></Field>
      <Field label="Tags — key=value, comma separated"><TextInput value={tags} placeholder="type=regression, priority=critical" onChange={(e) => setTags(e.target.value)} /></Field>
      <Hint>Writes <Mono>dataset/{name.trim() || '<name>'}/dataset.json</Mono> and an empty <Mono>records.jsonl</Mono> in the project. Add records from traces or by hand afterwards.</Hint>
      <Toolbar style={{ justifyContent: 'flex-end' }}>
        <Button size="small" onClick={onClose}>Cancel</Button>
        <Button size="small" variant="primary" disabled={busy || !name.trim()} onClick={() => void create()}>Create</Button>
      </Toolbar>
    </Modal>
  );
};

export const DatasetsPage = () => {
  const { slug, refresh } = useGenAI();
  const navigate = useNavigate();
  const [datasets, setDatasets] = useState<DatasetSummary[] | null>(null);
  const [dir, setDir] = useState('dataset');
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const [search, setSearch] = useState('');

  const load = useCallback(async () => {
    try {
      const answer = await genaiApi.datasets(slug);
      setDatasets(answer.datasets);
      setDir(answer.datasets_dir);
      setError('');
    } catch (reason) {
      setError(errorText(reason));
    }
  }, [slug]);
  useEffect(() => { void load(); }, [load]);

  const shown = (datasets ?? []).filter((d) => !search || `${d.name} ${d.description} ${Object.entries(d.tags).map(([k, v]) => `${k}=${v}`).join(' ')}`.toLowerCase().includes(search.toLowerCase()));
  const total = (datasets ?? []).reduce((n, d) => n + d.profile.records, 0);

  return (
    <GenAIPage
      title="Datasets"
      subtitle={`evaluation datasets under ${dir}/ — inputs, expectations and their provenance`}
      actions={<Button size="small" variant="primary" Icon={IconDatabasePlus} onClick={() => setCreating(true)}>Create dataset</Button>}
    >
      <Grid $min="160px">
        <StatCard label="Datasets" value={formatNumber(datasets?.length ?? 0)} Icon={IconDatabase} />
        <StatCard label="Records" value={formatNumber(total)} caption="across all datasets" />
        <StatCard label="Labeled" value={percent(total ? (datasets ?? []).reduce((n, d) => n + d.profile.labeled, 0) / total : 0)} caption="records with expectations" />
        <StatCard label="Linked runs" value={formatNumber((datasets ?? []).reduce((n, d) => n + d.evaluations, 0))} caption="evaluation runs naming a dataset" />
      </Grid>
      <Toolbar>
        <div style={{ flex: '1 1 260px', maxWidth: 420 }}>
          <SearchField placeholder="Search datasets by name, description or tag" value={search} onChange={(e) => setSearch(e.target.value)} onClear={() => setSearch('')} />
        </div>
        <IconButton Icon={IconRefresh} aria-label="Refresh datasets" onClick={() => void load()} />
        <Muted>{shown.length} of {datasets?.length ?? 0}</Muted>
      </Toolbar>
      {error ? <Card role="alert">{error}</Card> : null}
      {datasets && !datasets.length ? (
        <Card>
          <EmptyState title="No evaluation datasets" Icon={IconDatabase} action={<Button size="small" variant="primary" Icon={IconPlus} onClick={() => setCreating(true)}>Create dataset</Button>}>
            A dataset is a directory under <code>{dir}/</code> with <code>dataset.json</code> and <code>records.jsonl</code>. Create one here, or select traces on the Traces page and add them to a dataset.
          </EmptyState>
        </Card>
      ) : (
        <Card $padded={false}>
          <TableScroller>
            <Table>
              <THead>
                <tr>
                  <th>Name</th>
                  <th>Records</th>
                  <th>Labeled</th>
                  <th>Inputs</th>
                  <th>Expectations</th>
                  <th>Sources</th>
                  <th>Tags</th>
                  <th>Evaluation runs</th>
                  <th>Last run</th>
                  <th>Updated</th>
                </tr>
              </THead>
              <tbody>
                {!datasets ? <TableEmptyRow colSpan={10}>Loading datasets…</TableEmptyRow> : shown.map((dataset) => (
                  <TRow key={dataset.id} $clickable onClick={() => navigate(encodeURIComponent(dataset.id))}>
                    <NameCell>
                      <div style={{ fontWeight: 500 }}><Link to={encodeURIComponent(dataset.id)} onClick={(event) => event.stopPropagation()}>{dataset.name}</Link></div>
                      <div><Muted title={dataset.description}>{dataset.description || dataset.path}</Muted></div>
                    </NameCell>
                    <MonoCell>{formatNumber(dataset.profile.records)}</MonoCell>
                    <MonoCell>{dataset.profile.records ? percent(dataset.profile.labeled / dataset.profile.records) : '—'}</MonoCell>
                    <Cell title={dataset.profile.inputs_schema.join(', ')}><TagRow>{dataset.profile.inputs_schema.slice(0, 3).map((k) => <Tag key={k} color="gray" text={k} mono />)}{dataset.profile.inputs_schema.length > 3 ? <Muted>+{dataset.profile.inputs_schema.length - 3}</Muted> : null}</TagRow></Cell>
                    <Cell title={dataset.profile.expectations_schema.join(', ')}><TagRow>{dataset.profile.expectations_schema.slice(0, 3).map((k) => <Tag key={k} color="purple" text={k} mono />)}{dataset.profile.expectations_schema.length > 3 ? <Muted>+{dataset.profile.expectations_schema.length - 3}</Muted> : null}</TagRow></Cell>
                    <td><TagRow>{Object.entries(dataset.profile.sources).map(([type, n]) => <Tag key={type} color={sourceColor(type)} text={`${type} ${n}`} />)}</TagRow></td>
                    <Cell><TagRow>{Object.entries(dataset.tags).slice(0, 3).map(([k, v]) => <Tag key={k} color="blue" text={`${k}=${v}`} />)}</TagRow></Cell>
                    <MonoCell>{formatNumber(dataset.evaluations)}</MonoCell>
                    <MonoCell>{formatTime(dataset.last_evaluation_utc)}</MonoCell>
                    <MonoCell>{formatTime(dataset.updated_utc || dataset.modified_utc)}</MonoCell>
                  </TRow>
                ))}
              </tbody>
            </Table>
          </TableScroller>
        </Card>
      )}
      <Hint>
        Evaluation datasets are the test suites of this project: labeled records carry ground-truth expectations, unlabeled ones only inputs. An evaluation run names the dataset it used, which is how the two link.
      </Hint>
      {creating ? <CreateDialog onClose={() => setCreating(false)} onCreated={(created) => { setCreating(false); void refresh(); navigate(encodeURIComponent(created.id)); }} /> : null}
    </GenAIPage>
  );
};

/* ------------------------------------------------------------------------ */

const RecordDialog = ({ record, onClose }: { record: DatasetRecord; onClose: () => void }) => (
  <Modal open onClose={onClose} title={<Mono>record {record.record_id}</Mono>}>
    <div><Muted>Inputs</Muted><Pre>{JSON.stringify(record.inputs, null, 2)}</Pre></div>
    <div><Muted>Expectations</Muted><Pre>{Object.keys(record.expectations).length ? JSON.stringify(record.expectations, null, 2) : '(unlabeled)'}</Pre></div>
    <TagRow>
      <Tag color={sourceColor(record.source.type)} text={`source ${String(record.source.type ?? 'UNKNOWN')}`} />
      {Object.entries(record.source).filter(([k]) => k !== 'type').map(([k, v]) => <Tag key={k} color="gray" text={`${k}: ${String(v)}`} mono />)}
      {Object.entries(record.tags).map(([k, v]) => <Tag key={k} color="blue" text={`${k}=${String(v)}`} />)}
    </TagRow>
    <Toolbar style={{ justifyContent: 'flex-end' }}><Button size="small" onClick={onClose}>Close</Button></Toolbar>
  </Modal>
);

const AddRecordDialog = ({ datasetId, onClose, onAdded }: { datasetId: string; onClose: () => void; onAdded: (detail: DatasetDetail) => void }) => {
  const { slug } = useGenAI();
  const [inputs, setInputs] = useState('{\n  "question": ""\n}');
  const [expectations, setExpectations] = useState('{\n  "expected_response": ""\n}');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const add = async () => {
    setBusy(true);
    try {
      const parsedInputs = JSON.parse(inputs) as Record<string, unknown>;
      const parsedExpectations = expectations.trim() ? (JSON.parse(expectations) as Record<string, unknown>) : {};
      onAdded(await genaiApi.addRecords(slug, datasetId, { records: [{ inputs: parsedInputs, expectations: parsedExpectations, source: { type: 'HUMAN', created_by: 'unity-hpc dashboard' } }] }));
    } catch (reason) {
      setError(reason instanceof SyntaxError ? `Not valid JSON: ${reason.message}` : errorText(reason));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open onClose={onClose} title="Add a record by hand">
      {error ? <Card role="alert">{error}</Card> : null}
      <Field label="Inputs — JSON object"><TextArea rows={5} value={inputs} onChange={(e) => setInputs(e.target.value)} /></Field>
      <Field label="Expectations — JSON object, optional"><TextArea rows={4} value={expectations} onChange={(e) => setExpectations(e.target.value)} /></Field>
      <Hint>The record id is derived from the inputs, so adding the same inputs twice keeps one record.</Hint>
      <Toolbar style={{ justifyContent: 'flex-end' }}>
        <Button size="small" onClick={onClose}>Cancel</Button>
        <Button size="small" variant="primary" disabled={busy} onClick={() => void add()}>Add record</Button>
      </Toolbar>
    </Modal>
  );
};

export const DatasetDetailPage = () => {
  const { slug, refresh } = useGenAI();
  const { datasetId = '' } = useParams();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<DatasetDetail | null>(null);
  const [error, setError] = useState('');
  const [search, setSearch] = useState(params.get('search') || '');
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<DatasetRecord | null>(null);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState(false);
  const [description, setDescription] = useState('');
  const [tags, setTags] = useState('');
  const [subset, setSubset] = useState(params.get('subset') || '');
  const [split, setSplit] = useState(params.get('split') || '');
  const [busy, setBusy] = useState(false);
  const requestId = useRef(0);
  const pageSize = 25;

  const load = useCallback(async () => {
    const current = ++requestId.current;
    setBusy(true);
    try {
      const answer = await genaiApi.dataset(slug, datasetId, { offset, limit: pageSize, search: search || undefined, subset: subset || undefined, split: split || undefined });
      if (current !== requestId.current) return;
      setData(answer);
      setError('');
    } catch (reason) {
      if (current === requestId.current) setError(errorText(reason));
    } finally {
      if (current === requestId.current) setBusy(false);
    }
  }, [slug, datasetId, offset, search, subset, split]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const next = new URLSearchParams(params);
    let changed = false;
    for (const [key, value] of [['search', search], ['subset', subset], ['split', split]]) {
      if ((next.get(key) || '') !== value) {
        if (value) next.set(key, value); else next.delete(key);
        changed = true;
      }
    }
    if (changed) setParams(next, { replace: true });
  }, [search, subset, split, params, setParams]);

  const save = async () => {
    try {
      const parsed = Object.fromEntries(tags.split(/[,\n]/).map((p) => p.trim()).filter(Boolean).map((p) => { const [k, ...rest] = p.split('='); return [k.trim(), rest.join('=').trim()]; }));
      await genaiApi.updateDataset(slug, datasetId, { description, tags: parsed });
      // The answer is the first page, unfiltered; reload the page the user is on.
      await load();
      setEditing(false);
      toast('Dataset updated', 'success');
    } catch (reason) {
      toast(errorText(reason), 'error');
    }
  };

  const total = data?.total ?? 0;
  const from = total ? offset + 1 : 0;
  const to = Math.min(offset + pageSize, total);
  const inputKeys = data?.profile.inputs_schema ?? [];
  const expectationKeys = data?.profile.expectations_schema ?? [];
  const viewer = data?.viewer;
  const columns: DatasetColumn[] = viewer?.columns ?? [
    ...inputKeys.map((key) => ({ key: `inputs.${key}`, label: key, group: 'inputs', type: 'mixed', stats: { count: total, missing: 0, histogram: [], categories: [] } })),
    ...expectationKeys.map((key) => ({ key: `expectations.${key}`, label: key, group: 'expectations', type: 'mixed', stats: { count: total, missing: 0, histogram: [], categories: [] } })),
  ];

  return (
    <GenAIPage
      title={`Dataset · ${data?.name ?? datasetId}`}
      subtitle={data?.path}
      actions={
        <>
          <Button size="small" Icon={IconPlus} onClick={() => setAdding(true)}>Add record</Button>
          <Link to={`../evaluations?new=1&dataset=${encodeURIComponent(datasetId)}${subset ? `&subset=${encodeURIComponent(subset)}` : ''}${split ? `&split=${encodeURIComponent(split)}` : ''}`}><Button size="small" variant="primary" Icon={IconPlayerPlay}>Run evaluation</Button></Link>
        </>
      }
    >
      <BackLink to="../datasets">All datasets</BackLink>
      {error ? <Card role="alert">{error}</Card> : null}
      {data ? (
        <>
          <Grid $min="150px">
            <StatCard label="Records" value={formatNumber(data.profile.records)} Icon={IconDatabase} />
            <StatCard label="Labeled" value={formatNumber(data.profile.labeled)} unit={data.profile.records ? `/ ${data.profile.records}` : undefined} caption="records with expectations" accent={data.profile.labeled ? 'green' : undefined} />
            <StatCard label="Evaluation runs" value={formatNumber(data.evaluations.length)} caption={data.evaluations.length ? `latest ${formatTime(data.evaluations[0].started)}` : 'none yet'} />
            <StatCard label="Sources" value={Object.keys(data.profile.sources).length} caption={Object.entries(data.profile.sources).map(([t, n]) => `${t} ${n}`).join(' · ') || '—'} />
          </Grid>
          <Grid $min="320px">
            <Card>
              <CardHeader title="About" action={editing ? null : <Button size="small" variant="tertiary" Icon={IconTag} onClick={() => { setDescription(data.description); setTags(Object.entries(data.tags).map(([k, v]) => `${k}=${v}`).join(', ')); setEditing(true); }}>Edit</Button>} />
              {editing ? (
                <>
                  <Field label="Description"><TextArea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
                  <Field label="Tags — key=value, comma separated"><TextInput value={tags} onChange={(e) => setTags(e.target.value)} /></Field>
                  <Toolbar style={{ justifyContent: 'flex-end', marginTop: 8 }}>
                    <Button size="small" onClick={() => setEditing(false)}>Cancel</Button>
                    <Button size="small" variant="primary" onClick={() => void save()}>Save</Button>
                  </Toolbar>
                </>
              ) : (
                <>
                  <p style={{ fontSize: 13, lineHeight: 1.55 }}>{data.description || <Muted>No description. Edit to add one.</Muted>}</p>
                  <TagRow style={{ marginTop: 8 }}>{Object.entries(data.tags).map(([k, v]) => <Tag key={k} color="blue" text={`${k}=${v}`} />)}{!Object.keys(data.tags).length ? <Muted>no tags</Muted> : null}</TagRow>
                  <div style={{ marginTop: 12 }}>
                    <KeyValue label="Created">{formatTime(data.created_utc)}</KeyValue>
                    <KeyValue label="Updated">{formatTime(data.updated_utc)}</KeyValue>
                    <KeyValue label="Records file">{data.records_file}</KeyValue>
                    {data.license ? <KeyValue label="License">{data.license}</KeyValue> : null}
                    {Object.entries(data.source).map(([k, v]) => <KeyValue key={k} label={`source ${k}`}>{String(v)}</KeyValue>)}
                  </div>
                </>
              )}
            </Card>
            <Card>
              <CardHeader title="Schema" note={`${data.files.length} files in the directory`} />
              <KeyValue label="Inputs" mono={false}><TagRow>{inputKeys.map((k) => <Tag key={k} color="gray" text={k} mono />)}{!inputKeys.length ? <Muted>—</Muted> : null}</TagRow></KeyValue>
              <KeyValue label="Expectations" mono={false}><TagRow>{expectationKeys.map((k) => <Tag key={k} color="purple" text={k} mono />)}{!expectationKeys.length ? <Muted>unlabeled</Muted> : null}</TagRow></KeyValue>
              <KeyValue label="Record tags" mono={false}><TagRow>{data.profile.tag_keys.map((k) => <Tag key={k} color="blue" text={k} mono />)}{!data.profile.tag_keys.length ? <Muted>—</Muted> : null}</TagRow></KeyValue>
              <Hint>Files: {data.files.slice(0, 6).map((f) => f.path).join(', ')}{data.files.length > 6 ? ` … +${data.files.length - 6}` : ''}</Hint>
            </Card>
          </Grid>
          <Card $padded={false} aria-busy={busy}>
            <div style={{ padding: '16px 18px' }}>
              <Toolbar style={{ justifyContent: 'space-between', marginBottom: 14 }}>
                <SectionTitle>Dataset Viewer</SectionTitle>
                <TagRow><Tag color="purple" text={viewer?.kind ?? 'Dataset'} /><Muted>{formatNumber(viewer?.total_rows ?? data.profile.records)} rows available</Muted></TagRow>
              </Toolbar>
              <Grid $min="220px">
                <Field label={`Subset (${viewer?.subsets.length ?? 1})`}>
                  <Select aria-label="Dataset subset" value={subset} options={[{ value: '', label: 'All subsets' }, ...(viewer?.subsets ?? []).map((item) => ({ value: item.name, label: `${item.name} · ${formatNumber(item.rows)} rows` }))]} onChange={(e) => { setSubset(e.target.value); setSplit(''); setOffset(0); }} />
                </Field>
                <Field label={`Split (${viewer?.splits.length ?? 1})`}>
                  <Select aria-label="Dataset split" value={split} options={[{ value: '', label: 'All available rows' }, ...(viewer?.splits ?? []).map((item) => ({ value: item.name, label: `${item.name === 'local' ? 'Local corpus' : item.name} · ${formatNumber(item.rows)} rows` }))]} onChange={(e) => { setSplit(e.target.value); setOffset(0); }} />
                </Field>
              </Grid>
              <Toolbar style={{ marginTop: 14 }}>
                <div style={{ flex: '1 1 260px' }}><SearchField aria-label="Search this dataset" placeholder="Search this dataset" value={search} onChange={(e) => { setSearch(e.target.value); setOffset(0); }} onClear={() => { setSearch(''); setOffset(0); }} /></div>
                <IconButton Icon={IconRefresh} aria-label="Refresh dataset viewer" onClick={() => void load()} />
              </Toolbar>
            </div>
            <TableScroller>
              <Table>
                <THead><tr><th style={{ minWidth: 110 }}>Row</th>{columns.map((column) => <ColumnHead key={column.key} column={column} />)}</tr></THead>
                <tbody>
                  {!data.records.length ? <TableEmptyRow colSpan={columns.length + 1}>{search ? 'No rows match your search.' : 'No rows in this selection.'}</TableEmptyRow> : data.records.map((record, index) => (
                    <TRow key={record.record_id}>
                      <td style={{ verticalAlign: 'top' }}><Button size="small" variant="tertiary" onClick={() => setOpen(record)} aria-label={`Open row ${offset + index + 1}`} title={record.record_id}>{offset + index + 1}</Button></td>
                      {columns.map((column) => <ViewerCell key={column.key}><ValuePreview value={recordValue(record, column)} type={column.type} /></ViewerCell>)}
                    </TRow>
                  ))}
                </tbody>
              </Table>
            </TableScroller>
            <Toolbar style={{ justifyContent: 'center', padding: '14px 18px' }}>
              <Button size="small" disabled={offset === 0 || busy} onClick={() => setOffset(Math.max(0, offset - pageSize))}>Previous</Button>
              <Muted aria-live="polite">{busy ? 'Loading…' : `${formatNumber(from)}–${formatNumber(to)} of ${formatNumber(total)} rows`}</Muted>
              <Button size="small" disabled={to >= total || busy} onClick={() => setOffset(offset + pageSize)}>Next</Button>
            </Toolbar>
          </Card>
          {viewer ? <Hint>{viewer.note} Column statistics describe this selection before search. Select a row number for provenance and expectations.</Hint> : null}
          <SectionHead><SectionTitle>Evaluation runs on this dataset</SectionTitle><Muted>{data.evaluations.length} runs</Muted></SectionHead>
          <Card $padded={false}>
            <TableScroller>
              <Table>
                <THead><tr><th>Run</th><th>Model</th><th>State</th><th>Traces</th><th>Metrics</th><th>Started</th></tr></THead>
                <tbody>
                  {!data.evaluations.length ? <TableEmptyRow colSpan={6}>No evaluation run names this dataset yet.</TableEmptyRow> : data.evaluations.map((run) => (
                    <TRow key={run.id}>
                      <td><Link to={`../evaluations/${encodeURIComponent(run.id)}`}>{run.name}</Link>{run.purpose === 'smoke-test' ? <> <Tag color="yellow" text="smoke" /></> : null}</td>
                      <td title={run.model}>{run.model.split('/').pop() || '—'}</td>
                      <td><StateTag state={run.state} /></td>
                      <MonoCell>{run.traces === null ? '…' : formatNumber(run.traces)}</MonoCell>
                      <td><TagRow>{Object.entries(run.metrics).slice(0, 3).map(([k, v]) => <Tag key={k} color="gray" text={`${k} ${typeof v === 'number' && v <= 1 && k !== 'errors' && k !== 'pass' ? percent(v) : v}`} mono />)}</TagRow></td>
                      <MonoCell>{formatTime(run.started)}</MonoCell>
                    </TRow>
                  ))}
                </tbody>
              </Table>
            </TableScroller>
          </Card>
        </>
      ) : !error ? <Muted>Loading dataset…</Muted> : null}
      {open ? <RecordDialog record={open} onClose={() => setOpen(null)} /> : null}
      {adding ? <AddRecordDialog datasetId={datasetId} onClose={() => setAdding(false)} onAdded={(detail) => { setAdding(false); void load(); void refresh(); toast(`Added ${detail.added ?? 0} record${detail.added === 1 ? '' : 's'}${detail.updated ? `, updated ${detail.updated}` : ''}${detail.skipped ? ` (${detail.skipped} already present)` : ''}`, 'success'); }} /> : null}
    </GenAIPage>
  );
};
