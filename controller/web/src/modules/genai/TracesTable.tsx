/**
 * The trace table: one row per model request, with its assessments and the
 * expectations the dataset holds for it.
 *
 * This is the view MLflow opens an experiment on. The header carries a block
 * per assessment — pass rate, one bar per outcome — so the table reads as an
 * evaluation report before any row is opened. Select rows and `Actions` adds
 * them to an evaluation dataset, which is how a dataset grows from traces.
 */

import styled from '@emotion/styled';
import {
  IconAdjustmentsHorizontal,
  IconChevronDown,
  IconChevronLeft,
  IconChevronRight,
  IconColumns3,
  IconDatabasePlus,
  IconRefresh,
} from '@tabler/icons-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { errorText } from '../controller/api';
import { Button, IconButton } from '../../ui/components/Button';
import { Card } from '../../ui/components/Card';
import { Checkbox, Field, FieldRow, SearchField, Select, TextInput } from '../../ui/components/Field';
import { Modal } from '../../ui/components/SidePanel';
import { TableEmptyRow, TableScroller } from '../../ui/components/Table';
import { Tag } from '../../ui/components/Tag';
import { useToast } from '../../ui/components/Toast';
import {
  genaiApi,
  type DatasetSummary,
  type TraceFilters,
  type TraceRow,
  type TracesAnswer,
} from './api';
import {
  AssessmentSummaryBlock,
  AssessmentTag,
  formatDuration,
  formatNumber,
  formatTime,
  Muted,
  StateTag,
  Toolbar,
  useGenAI,
} from './GenAIWorkspace';
import { TracePanel } from './TracePanel';

const RANGES: { value: string; label: string; hours: number | null }[] = [
  { value: 'all', label: 'Time range: All', hours: null },
  { value: '24h', label: 'Time range: Last 24 hours', hours: 24 },
  { value: '7d', label: 'Time range: Last 7 days', hours: 24 * 7 },
  { value: '30d', label: 'Time range: Last 30 days', hours: 24 * 30 },
  { value: '90d', label: 'Time range: Last 90 days', hours: 24 * 90 },
  { value: '1y', label: 'Time range: Last year', hours: 24 * 365 },
];

const SORTS = [
  { value: 'request_time', label: 'Sort: Request time' },
  { value: 'duration_s', label: 'Sort: Execution time' },
  { value: 'tokens', label: 'Sort: Tokens' },
  { value: 'state', label: 'Sort: State' },
  { value: 'session', label: 'Sort: Session' },
  { value: 'model', label: 'Sort: Model' },
];

const BASE_COLUMNS = [
  { id: 'trace_id', label: 'Trace ID' },
  { id: 'request', label: 'Request' },
  { id: 'response', label: 'Response' },
  { id: 'tokens', label: 'Tokens' },
  { id: 'duration', label: 'Execution time' },
  { id: 'request_time', label: 'Request time' },
  { id: 'state', label: 'State' },
  { id: 'session', label: 'Session' },
  { id: 'model', label: 'Model' },
  { id: 'evaluation', label: 'Evaluation run' },
] as const;

type ColumnId = (typeof BASE_COLUMNS)[number]['id'] | `exp:${string}`;

const DEFAULT_HIDDEN: ColumnId[] = ['session', 'model', 'evaluation'];

const Grouped = styled.table`
  border-collapse: collapse;
  font-size: ${({ theme }) => theme.font.size.sm};
  min-width: 100%;

  th {
    background: ${({ theme }) => theme.background.secondary};
    color: ${({ theme }) => theme.font.color.tertiary};
    font-size: ${({ theme }) => theme.font.size.xs};
    font-weight: ${({ theme }) => theme.font.weight.medium};
    padding: ${({ theme }) => theme.spacing(1.5, 2)};
    text-align: left;
    vertical-align: bottom;
    white-space: nowrap;
  }

  thead tr.groups th {
    border-bottom: 1px solid ${({ theme }) => theme.border.color.light};
    color: ${({ theme }) => theme.font.color.secondary};
    font-weight: ${({ theme }) => theme.font.weight.semiBold};
    letter-spacing: 0.02em;
  }

  thead tr.names th {
    border-bottom: 1px solid ${({ theme }) => theme.border.color.medium};
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  thead tr.summary th {
    border-bottom: 1px solid ${({ theme }) => theme.border.color.medium};
    padding-bottom: ${({ theme }) => theme.spacing(2.5)};
    padding-top: ${({ theme }) => theme.spacing(2.5)};
    vertical-align: top;
  }

  th.group {
    border-left: 1px solid ${({ theme }) => theme.border.color.light};
  }

  td {
    border-bottom: 1px solid ${({ theme }) => theme.border.color.light};
    color: ${({ theme }) => theme.font.color.primary};
    height: ${({ theme }) => theme.table.rowHeight};
    max-width: 240px;
    overflow: hidden;
    padding: ${({ theme }) => theme.spacing(1.5, 2)};
    text-overflow: ellipsis;
    vertical-align: middle;
    white-space: nowrap;
  }

  td.group {
    border-left: 1px solid ${({ theme }) => theme.border.color.light};
  }

  td.expectation {
    max-width: 150px;
  }

  tbody tr {
    cursor: pointer;
  }

  tbody tr:hover td {
    background: ${({ theme }) => theme.background.transparent.primary};
  }

  tbody tr.selected td {
    background: ${({ theme }) => theme.accent.quaternary};
  }
`;

const IdCell = styled.td`
  color: ${({ theme }) => theme.font.color.secondary};
  font-family: ${({ theme }) => theme.font.familyMono};
  font-size: ${({ theme }) => theme.font.size.xs};
`;

const LinkCell = styled.td`
  color: ${({ theme }) => theme.accent.primary};
`;

const NumCell = styled.td`
  font-family: ${({ theme }) => theme.font.familyMono};
  font-size: ${({ theme }) => theme.font.size.xs};
  text-align: right;
`;

const Count = styled.span`
  color: ${({ theme }) => theme.font.color.tertiary};
  font-size: ${({ theme }) => theme.font.size.xs};
  margin-left: auto;
  white-space: nowrap;
`;

const Popover = styled.div`
  background: ${({ theme }) => theme.background.secondary};
  border: 1px solid ${({ theme }) => theme.border.color.medium};
  border-radius: ${({ theme }) => theme.border.radius.md};
  box-shadow: ${({ theme }) => theme.boxShadow.strong};
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.spacing(1.5)};
  padding: ${({ theme }) => theme.spacing(2.5)};
  position: absolute;
  /* The menus sit at the right end of the toolbar; open them leftward. */
  right: 0;
  top: 34px;
  white-space: nowrap;
  z-index: ${({ theme }) => theme.zIndex.modal};
`;

const Anchor = styled.div`
  position: relative;
`;

const since = (range: string): string | undefined => {
  const hours = RANGES.find((r) => r.value === range)?.hours ?? null;
  if (hours === null) return undefined;
  return new Date(Date.now() - hours * 3600 * 1000).toISOString();
};

export type TracesTableProps = {
  /** Filters the page fixes, such as the evaluation run it belongs to. */
  fixed?: TraceFilters;
  /** Offer the collection select. Off inside one evaluation run. */
  collections?: boolean;
  pageSize?: number;
};

export const TracesTable = ({ fixed: fixedProp, collections = true, pageSize = 25 }: TracesTableProps) => {
  const { slug } = useGenAI();
  // Callers pass an inline object (`fixed={{ evaluation: id }}`). Key it by
  // value so a parent render does not start a new fetch.
  const fixedKey = JSON.stringify(fixedProp ?? {});
  const fixed = useMemo<TraceFilters>(() => JSON.parse(fixedKey), [fixedKey]);
  const toast = useToast();
  const [params, setParams] = useSearchParams();

  const [range, setRange] = useState(params.get('range') || 'all');
  const [search, setSearch] = useState(params.get('search') || '');
  const [state, setState] = useState(params.get('state') || '');
  const [session, setSession] = useState(params.get('session') || '');
  const [model, setModel] = useState(params.get('model') || '');
  const [assessment, setAssessment] = useState(params.get('assessment') || '');
  const [assessmentValue, setAssessmentValue] = useState(params.get('assessment_value') || '');
  const [collection, setCollection] = useState(params.get('collection') || '');
  const [superseded, setSuperseded] = useState(params.get('superseded') === '1');
  const [sort, setSort] = useState(params.get('sort') || 'request_time');
  const [order, setOrder] = useState<'asc' | 'desc'>(params.get('order') === 'asc' ? 'asc' : 'desc');
  const [offset, setOffset] = useState(0);
  const [hidden, setHidden] = useState<Set<ColumnId>>(new Set(DEFAULT_HIDDEN));
  const [showFilters, setShowFilters] = useState(Boolean(state || model || assessment || session));
  const [showColumns, setShowColumns] = useState(false);
  const [showActions, setShowActions] = useState(false);
  const [data, setData] = useState<TracesAnswer | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<TraceRow | null>(null);
  const [exporting, setExporting] = useState(false);

  const filters = useMemo<TraceFilters>(() => ({
    ...fixed,
    search: search || undefined,
    state: state || undefined,
    session: session || fixed.session,
    model: model || undefined,
    assessment: assessment || undefined,
    assessment_value: assessmentValue || undefined,
    collection: fixed.evaluation ? undefined : collection || undefined,
    superseded: superseded || undefined,
    since: since(range),
    sort,
    order,
    offset,
    limit: pageSize,
  }), [fixed, search, state, session, model, assessment, assessmentValue, collection, superseded, range, sort, order, offset, pageSize]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await genaiApi.traces(slug, filters));
      setError('');
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setLoading(false);
    }
  }, [slug, filters]);

  useEffect(() => {
    void load();
  }, [load]);

  // The URL remembers the scope so a shared link opens the same view.
  useEffect(() => {
    const next = new URLSearchParams(params);
    const entries: [string, string][] = [
      ['range', range === 'all' ? '' : range], ['search', search], ['state', state], ['session', session], ['model', model],
      ['assessment', assessment], ['assessment_value', assessmentValue], ['collection', collection],
      ['superseded', superseded ? '1' : ''], ['sort', sort === 'request_time' ? '' : sort], ['order', order === 'desc' ? '' : order],
    ];
    let changed = false;
    for (const [key, value] of entries) {
      if ((next.get(key) || '') !== value) {
        changed = true;
        if (value) next.set(key, value); else next.delete(key);
      }
    }
    if (changed) setParams(next, { replace: true });
  }, [range, search, state, session, model, assessment, assessmentValue, collection, superseded, sort, order, params, setParams]);

  const rows = data?.traces ?? [];
  const assessmentNames = Object.keys(data?.assessments ?? {});
  const expectationNames = (data?.expectations ?? []).filter((name) => !hidden.has(`exp:${name}`));
  const visible = BASE_COLUMNS.filter((c) => !hidden.has(c.id));
  const allSelected = rows.length > 0 && rows.every((r) => selected.has(`${r.evaluation_id}:${r.trace_id}`));
  const key = (row: TraceRow) => `${row.evaluation_id}:${row.trace_id}`;

  const toggleAll = () => {
    const next = new Set(selected);
    if (allSelected) rows.forEach((r) => next.delete(key(r)));
    else rows.forEach((r) => next.add(key(r)));
    setSelected(next);
  };
  const toggleOne = (row: TraceRow) => {
    const next = new Set(selected);
    const k = key(row);
    if (next.has(k)) next.delete(k); else next.add(k);
    setSelected(next);
  };

  const resetPaging = <T,>(setter: (value: T) => void) => (value: T) => {
    setter(value);
    setOffset(0);
  };

  const total = data?.total ?? 0;
  const from = total ? offset + 1 : 0;
  const to = Math.min(offset + pageSize, total);
  const colCount = 1 + visible.length + assessmentNames.length + expectationNames.length;

  return (
    <>
      <Toolbar>
        <Select aria-label="Time range" value={range} options={RANGES.map(({ value, label }) => ({ value, label }))} onChange={(e) => resetPaging(setRange)(e.target.value)} style={{ width: 'auto' }} />
        <IconButton Icon={IconRefresh} aria-label="Refresh traces" title="Refresh" onClick={() => void load()} disabled={loading} />
        {collections && !fixed.evaluation && (data?.collections.length ?? 0) > 1 ? (
          <Select aria-label="Collection" value={collection} style={{ width: 'auto' }}
            options={[{ value: '', label: 'Collections: default' }, { value: 'all', label: 'Collections: all' }, ...(data?.collections ?? []).map((c) => ({ value: c.id, label: `Collection: ${c.label}` }))]}
            onChange={(e) => resetPaging(setCollection)(e.target.value)} />
        ) : null}
        {!fixed.evaluation ? (
          <Checkbox label="Include superseded runs" checked={superseded} onChange={(e) => resetPaging(setSuperseded)(e.target.checked)} />
        ) : null}
      </Toolbar>
      <Toolbar>
        <div style={{ flex: '1 1 260px', maxWidth: 420 }}>
          <SearchField placeholder="Search traces by request, response, id or session" value={search} onChange={(e) => resetPaging(setSearch)(e.target.value)} onClear={() => resetPaging(setSearch)('')} />
        </div>
        <Button size="small" Icon={IconAdjustmentsHorizontal} onClick={() => setShowFilters((v) => !v)}>
          Filters {state || model || assessment || session ? <Tag color="blue" text={[state, model, assessment, session].filter(Boolean).length} /> : <IconChevronDown size={12} />}
        </Button>
        <Select aria-label="Sort" value={sort} options={SORTS} onChange={(e) => resetPaging(setSort)(e.target.value)} style={{ width: 'auto' }} />
        <Button size="small" onClick={() => resetPaging(setOrder)(order === 'desc' ? 'asc' : 'desc')} title="Toggle sort direction">{order === 'desc' ? '↓ newest first' : '↑ oldest first'}</Button>
        <Anchor>
          <Button size="small" Icon={IconColumns3} onClick={() => setShowColumns((v) => !v)}>Columns <IconChevronDown size={12} /></Button>
          {showColumns ? (
            <Popover onMouseLeave={() => setShowColumns(false)}>
              {BASE_COLUMNS.map((column) => (
                <Checkbox key={column.id} label={column.label} checked={!hidden.has(column.id)} onChange={() => {
                  const next = new Set(hidden);
                  if (next.has(column.id)) next.delete(column.id); else next.add(column.id);
                  setHidden(next);
                }} />
              ))}
              {(data?.expectations ?? []).length ? <Muted>Expectations</Muted> : null}
              {(data?.expectations ?? []).map((name) => (
                <Checkbox key={`exp:${name}`} label={name} checked={!hidden.has(`exp:${name}`)} onChange={() => {
                  const next = new Set(hidden);
                  const id: ColumnId = `exp:${name}`;
                  if (next.has(id)) next.delete(id); else next.add(id);
                  setHidden(next);
                }} />
              ))}
            </Popover>
          ) : null}
        </Anchor>
        <Anchor>
          <Button size="small" variant={selected.size ? 'primary' : 'secondary'} disabled={!selected.size} onClick={() => setShowActions((v) => !v)}>
            Actions{selected.size ? ` (${selected.size})` : ''} <IconChevronDown size={12} />
          </Button>
          {showActions ? (
            <Popover onMouseLeave={() => setShowActions(false)}>
              <Button size="small" Icon={IconDatabasePlus} onClick={() => { setShowActions(false); setExporting(true); }}>Add to evaluation dataset</Button>
              <Button size="small" variant="tertiary" onClick={() => { setShowActions(false); setSelected(new Set()); }}>Clear selection</Button>
            </Popover>
          ) : null}
        </Anchor>
        <Count>{loading ? 'Loading…' : `${from}–${to} of ${formatNumber(total)}`}</Count>
      </Toolbar>
      {showFilters ? (
        <Card>
          <FieldRow $columns={4}>
            <Field label="State">
              <Select value={state} options={[{ value: '', label: 'Any state' }, ...Object.entries(data?.states ?? {}).map(([k, n]) => ({ value: k, label: `${k} (${n})` }))]} onChange={(e) => resetPaging(setState)(e.target.value)} />
            </Field>
            <Field label="Model">
              <Select value={model} options={[{ value: '', label: 'Any model' }, ...(data?.models ?? []).map((m) => ({ value: m, label: m }))]} onChange={(e) => resetPaging(setModel)(e.target.value)} />
            </Field>
            <Field label="Assessment">
              <Select value={assessment} options={[{ value: '', label: 'Any assessment' }, ...assessmentNames.map((a) => ({ value: a, label: a }))]} onChange={(e) => { resetPaging(setAssessment)(e.target.value); setAssessmentValue(''); }} />
            </Field>
            <Field label="Assessment value">
              {assessment && data?.assessments[assessment]?.kind === 'pass_fail' ? (
                <Select value={assessmentValue} options={[{ value: '', label: 'Pass or fail' }, { value: 'pass', label: 'Pass' }, { value: 'fail', label: 'Fail' }]} onChange={(e) => resetPaging(setAssessmentValue)(e.target.value)} />
              ) : assessment && data?.assessments[assessment]?.kind === 'category' ? (
                <Select value={assessmentValue} options={[{ value: '', label: 'Any value' }, ...Object.keys(data.assessments[assessment].values).map((v) => ({ value: v, label: v }))]} onChange={(e) => resetPaging(setAssessmentValue)(e.target.value)} />
              ) : (
                <TextInput value={assessmentValue} placeholder="exact value" onChange={(e) => resetPaging(setAssessmentValue)(e.target.value)} disabled={!assessment} />
              )}
            </Field>
          </FieldRow>
          {!fixed.session ? (
            <FieldRow $columns={4} style={{ marginTop: 8 }}>
              <Field label="Session">
                <TextInput value={session} placeholder="exact session id" onChange={(e) => resetPaging(setSession)(e.target.value)} />
              </Field>
            </FieldRow>
          ) : null}
        </Card>
      ) : null}
      {error ? <Card role="alert">{error}</Card> : null}
      <Card $padded={false}>
        <TableScroller>
          <Grouped>
            <thead>
              <tr className="groups">
                <th colSpan={1 + visible.length} />
                {assessmentNames.length ? <th className="group" colSpan={assessmentNames.length}>Assessments ({assessmentNames.length}/{assessmentNames.length})</th> : null}
                {expectationNames.length ? <th className="group" colSpan={expectationNames.length}>Expectations ({expectationNames.length}/{data?.expectations.length ?? expectationNames.length})</th> : null}
              </tr>
              <tr className="names">
                <th style={{ width: 28 }}><input type="checkbox" aria-label="Select all traces on this page" checked={allSelected} onChange={toggleAll} /></th>
                {visible.map((column) => <th key={column.id}>{column.label}</th>)}
                {assessmentNames.map((name, index) => <th key={name} className={index === 0 ? 'group' : undefined}>{name}</th>)}
                {expectationNames.map((name, index) => <th key={name} className={index === 0 ? 'group' : undefined}>{name}</th>)}
              </tr>
              {assessmentNames.length ? (
                <tr className="summary">
                  <th colSpan={1 + visible.length}><Muted>{formatNumber(total)} traces in scope · {data?.sessions ?? 0} sessions · {data?.models.length ?? 0} models</Muted></th>
                  {assessmentNames.map((name, index) => (
                    <th key={name} className={index === 0 ? 'group' : undefined}>
                      <AssessmentSummaryBlock name={name} summary={data!.assessments[name]} />
                    </th>
                  ))}
                  {expectationNames.map((name, index) => <th key={name} className={index === 0 ? 'group' : undefined} />)}
                </tr>
              ) : null}
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <TableEmptyRow colSpan={colCount}>{loading ? 'Loading traces…' : 'No traces match this scope. Run an evaluation, widen the time range, or change the collection.'}</TableEmptyRow>
              ) : rows.map((row) => (
                <tr key={key(row)} className={selected.has(key(row)) ? 'selected' : undefined} onClick={() => setOpen(row)}>
                  <td onClick={(e) => e.stopPropagation()}><input type="checkbox" aria-label={`Select trace ${row.trace_id}`} checked={selected.has(key(row))} onChange={() => toggleOne(row)} /></td>
                  {visible.map((column) => {
                    switch (column.id) {
                      case 'trace_id': return <IdCell key={column.id} title={row.trace_id}>tr-{row.trace_id.slice(0, 12)}</IdCell>;
                      case 'request': return <LinkCell key={column.id} title={row.request}>{row.request || <Muted>—</Muted>}</LinkCell>;
                      case 'response': return <td key={column.id} title={row.response}>{row.response || <Muted>{row.error || '—'}</Muted>}</td>;
                      case 'tokens': return <NumCell key={column.id}>{row.tokens === null ? '—' : <Tag color="gray" text={formatNumber(row.tokens)} mono />}</NumCell>;
                      case 'duration': return <NumCell key={column.id}>{formatDuration(row.duration_s)}</NumCell>;
                      case 'request_time': return <td key={column.id}>{formatTime(row.request_time)}</td>;
                      case 'state': return <td key={column.id}><StateTag state={row.state} /></td>;
                      case 'session': return <td key={column.id} title={row.session}>{row.session || '—'}</td>;
                      case 'model': return <td key={column.id} title={row.model}>{row.model.split('/').pop()}</td>;
                      case 'evaluation': return <td key={column.id} title={row.evaluation}>{row.evaluation}</td>;
                      default: return null;
                    }
                  })}
                  {assessmentNames.map((name, index) => (
                    <td key={name} className={index === 0 ? 'group' : undefined}>
                      {row.assessments[name] ? <AssessmentTag item={row.assessments[name]} name={name} /> : <Muted>—</Muted>}
                    </td>
                  ))}
                  {expectationNames.map((name, index) => (
                    <td key={name} className={`expectation${index === 0 ? ' group' : ''}`} title={row.expectations[name]}>
                      {row.expectations[name] ? <Tag color="purple" text={row.expectations[name]} /> : <Muted>—</Muted>}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </Grouped>
        </TableScroller>
      </Card>
      <Toolbar style={{ justifyContent: 'flex-end' }}>
        <Count>{from}–{to} of {formatNumber(total)}</Count>
        <IconButton Icon={IconChevronLeft} aria-label="Previous page" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - pageSize))} />
        <IconButton Icon={IconChevronRight} aria-label="Next page" disabled={to >= total} onClick={() => setOffset(offset + pageSize)} />
      </Toolbar>
      {open ? <TracePanel row={open} onClose={() => setOpen(null)} onAddToDataset={() => { setSelected(new Set([key(open)])); setOpen(null); setExporting(true); }} /> : null}
      {exporting ? (
        <ExportDialog
          slug={slug}
          traces={[...selected].map((k) => { const [evaluation_id, ...rest] = k.split(':'); return { evaluation_id, trace_id: rest.join(':') }; })}
          onClose={() => setExporting(false)}
          onDone={(message) => { setExporting(false); setSelected(new Set()); toast(message, 'success'); }}
        />
      ) : null}
    </>
  );
};

/* ------------------------------------------------------------------------ */
/* Export traces to an evaluation dataset                                    */
/* ------------------------------------------------------------------------ */

const DatasetRow = styled.div`
  align-items: center;
  border-bottom: 1px solid ${({ theme }) => theme.border.color.light};
  display: flex;
  gap: ${({ theme }) => theme.spacing(2)};
  justify-content: space-between;
  padding: ${({ theme }) => theme.spacing(1.5, 0)};

  &:last-of-type {
    border-bottom: 0;
  }
`;

const ExportDialog = ({
  slug,
  traces,
  onClose,
  onDone,
}: {
  slug: string;
  traces: { trace_id: string; evaluation_id: string }[];
  onClose: () => void;
  onDone: (message: string) => void;
}) => {
  const [datasets, setDatasets] = useState<DatasetSummary[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [asExpectation, setAsExpectation] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    genaiApi.datasets(slug).then((r) => setDatasets(r.datasets)).catch((e) => setError(errorText(e)));
  }, [slug]);

  const exportTo = async (datasetId: string) => {
    setBusy(true);
    try {
      const result = await genaiApi.addRecords(slug, datasetId, { traces, response_as_expectation: asExpectation });
      onDone(`Added ${result.added ?? 0} record${result.added === 1 ? '' : 's'} to ${result.name}${result.updated ? `, updated ${result.updated}` : ''}${result.skipped ? ` (${result.skipped} already present)` : ''}`);
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  };

  const create = async () => {
    setBusy(true);
    try {
      const created = await genaiApi.createDataset(slug, { name, description });
      setDatasets([...(datasets ?? []), { ...created, raw_files: 0, evaluations: 0, last_evaluation_utc: '', modified_utc: created.updated_utc }]);
      setCreating(false);
      setName('');
      setDescription('');
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open onClose={onClose} title={`Export ${traces.length} trace${traces.length === 1 ? '' : 's'} to evaluation dataset`}>
      {error ? <Card role="alert">{error}</Card> : null}
      <Muted>Each trace becomes one record: its request as inputs, its logged expectations as expectations, with the trace as source.</Muted>
      <Checkbox label="Also store the response as expected_response" checked={asExpectation} onChange={(e) => setAsExpectation(e.target.checked)} />
      {datasets === null ? <Muted>Loading datasets…</Muted> : datasets.length === 0 && !creating ? (
        <Muted>No evaluation dataset exists for this project yet.</Muted>
      ) : (
        <div>
          {datasets.map((dataset) => (
            <DatasetRow key={dataset.id}>
              <div style={{ minWidth: 0 }}>
                <div>{dataset.name}</div>
                <Muted>{dataset.profile.records} records · {dataset.profile.labeled} labeled</Muted>
              </div>
              <Button size="small" variant="primary" disabled={busy} onClick={() => void exportTo(dataset.id)}>Export</Button>
            </DatasetRow>
          ))}
        </div>
      )}
      {creating ? (
        <>
          <Field label="Dataset name"><TextInput value={name} placeholder="production_validation_set" onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Description"><TextInput value={description} placeholder="optional" onChange={(e) => setDescription(e.target.value)} /></Field>
          <Toolbar style={{ justifyContent: 'flex-end' }}>
            <Button size="small" onClick={() => setCreating(false)}>Cancel</Button>
            <Button size="small" variant="primary" disabled={busy || !name.trim()} onClick={() => void create()}>Create</Button>
          </Toolbar>
        </>
      ) : (
        <Toolbar style={{ justifyContent: 'space-between' }}>
          <Button size="small" Icon={IconDatabasePlus} onClick={() => setCreating(true)}>Create new dataset</Button>
          <Button size="small" variant="tertiary" onClick={onClose}>Close</Button>
        </Toolbar>
      )}
    </Modal>
  );
};
