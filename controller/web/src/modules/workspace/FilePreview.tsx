import { useState, type ReactNode } from 'react';
import { Button, ButtonGroup } from '../../ui/components/Button';
import { Hint } from '../../ui/components/Card';
import { Checkbox, TextInput } from '../../ui/components/Field';
import { Table, TableScroller, THead } from '../../ui/components/Table';

export type Preview = {
  version: string;
  path?: string;
  text: string;
  offset: number;
  loaded_bytes: number;
  size: number;
  truncated: boolean;
  next_offset?: number | null;
  encoding?: string;
  mime?: string;
  kind: string;
  reason?: string;
  line_start?: number | null;
  parse_error?: { message?: string; offset?: number; [key: string]: unknown };
  structured?: unknown;
  records?: { offset: number; bytes: number; value?: unknown; error?: string; incomplete?: boolean; schema_status?: string }[];
  rows?: string[][];
  image?: string;
  width?: number;
  height?: number;
};

const stringify = (value: unknown) => typeof value === 'string' ? value : JSON.stringify(value, null, 2);

/** Project text stays React text. No HTML parsing or script-capable rendering. */
function JsonTree({ value, name = 'root', depth = 0 }: { value: unknown; name?: string; depth?: number }) {
  const [expanded, setExpanded] = useState(depth < 1);
  if (value === null || typeof value !== 'object') return <span><strong>{name}</strong>: {JSON.stringify(value)}</span>;
  const entries = Object.entries(value);
  if (depth > 16) return <p>{name}: Nested values continue in raw source.</p>;
  return <details open={expanded} onToggle={event => setExpanded(event.currentTarget.open)} style={{ paddingLeft: depth ? 12 : 0, overflowWrap: 'anywhere' }}>
    <summary>{name} · {Array.isArray(value) ? 'Array' : 'Object'} · {entries.length} {Array.isArray(value) ? 'items' : 'fields'}</summary>
    {expanded ? entries.slice(0, 200).map(([key, child]) => <div key={key} style={{ marginBlock: 4 }}><JsonTree value={child} name={key} depth={depth + 1} /></div>) : null}
    {entries.length > 200 ? <Hint>This tree shows 200 entries. Raw source retains the complete loaded page.</Hint> : null}
  </details>;
}

function safeLink(value: string) {
  if (/[\u0000-\u001f]/.test(value)) return false;
  try { return ['http:', 'https:'].includes(new URL(value, 'https://preview.invalid/').protocol); } catch { return false; }
}

function inline(text: string): ReactNode[] {
  // This small presentation grammar never evaluates HTML or requests embeds.
  const tokens = /(!?\[[^\]\n]*\]\([^\s)]*\)|`[^`\n]+`|\*\*[^*\n]+\*\*)/g;
  const result: ReactNode[] = [];
  let at = 0;
  for (const match of text.matchAll(tokens)) {
    const index = match.index ?? 0;
    if (index > at) result.push(text.slice(at, index));
    const token = match[0];
    if (token.startsWith('![')) {
      result.push(<span key={index}>[Image omitted: {token.slice(2, token.indexOf(']'))}]</span>);
    } else if (token.startsWith('[')) {
      const split = token.indexOf('](');
      const title = token.slice(1, split), href = token.slice(split + 2, -1);
      result.push(safeLink(href) ? <a key={index} href={href} target="_blank" rel="noopener noreferrer">{title}</a> : <span key={index}>{title} (unsupported link)</span>);
    } else if (token.startsWith('`')) {
      result.push(<code key={index}>{token.slice(1, -1)}</code>);
    } else {
      result.push(<strong key={index}>{token.slice(2, -2)}</strong>);
    }
    at = index + token.length;
  }
  if (at < text.length) result.push(text.slice(at));
  return result;
}

function Markdown({ text }: { text: string }) {
  const lines = text.split('\n'), blocks: ReactNode[] = [];
  let position = 0;
  while (position < lines.length) {
    const line = lines[position], key = position;
    if (line.startsWith('```')) {
      const code: string[] = [];
      position += 1;
      while (position < lines.length && !lines[position].startsWith('```')) code.push(lines[position++]);
      position += 1;
      blocks.push(<pre key={key} tabIndex={0} style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}><code>{code.join('\n')}</code></pre>);
      continue;
    }
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) {
      const value = inline(heading[2]);
      blocks.push(heading[1].length < 3 ? <h3 key={key}>{value}</h3> : <h4 key={key}>{value}</h4>);
      position += 1; continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const entries: ReactNode[] = [];
      while (position < lines.length && /^\s*[-*]\s+/.test(lines[position])) {
        entries.push(<li key={position}>{inline(lines[position].replace(/^\s*[-*]\s+/, ''))}</li>);
        position += 1;
      }
      blocks.push(<ul key={key}>{entries}</ul>); continue;
    }
    if (line.startsWith('> ')) blocks.push(<blockquote key={key}>{inline(line.slice(2))}</blockquote>);
    else if (line.trim()) blocks.push(<p key={key}>{inline(line)}</p>);
    position += 1;
  }
  return <article aria-label="Rendered Markdown report" style={{ overflowWrap: 'anywhere' }}>{blocks}</article>;
}

function marked(text: string, search: string): ReactNode {
  if (!search) return text || '\u00a0';
  const lower = text.toLocaleLowerCase(), needle = search.toLocaleLowerCase(), fragments: ReactNode[] = [];
  let start = 0, found = lower.indexOf(needle);
  while (found !== -1 && fragments.length < 2000) {
    fragments.push(text.slice(start, found), <mark key={found}>{text.slice(found, found + needle.length)}</mark>);
    start = found + needle.length;
    found = lower.indexOf(needle, start);
  }
  fragments.push(text.slice(start));
  return fragments;
}

export function FilePreview({ value }: { value: Preview | null }) {
  // A new preview version starts with the same read-only controls; typed search
  // remains scoped to the currently loaded page, never the entire file.
  const [raw, setRaw] = useState(false), [wrap, setWrap] = useState(true), [search, setSearch] = useState('');
  if (!value) return <p>Select a file to load a bounded preview.</p>;
  const markdown = value.mime === 'text/markdown' || /\.(md|markdown)$/i.test(value.path || '');
  const rich = value.structured !== undefined || value.records !== undefined || value.rows !== undefined || markdown || value.kind === 'image';
  const lines = value.text.split('\n');
  if (lines[lines.length - 1] === '' && lines.length > 1) lines.pop();
  const matches = search ? lines.filter(line => line.toLocaleLowerCase().includes(search.toLocaleLowerCase())).length : 0;
  const firstLine = value.line_start ?? (value.offset === 0 ? 1 : null);
  const raster = value.image, width = value.width || 0, height = value.height || 0;
  const permittedRaster = raster && raster.length <= 6 * 1024 * 1024 && /^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(raster)
    && width > 0 && height > 0 && width <= 4096 && height <= 4096 && width * height <= 16000000;
  return <div style={{ minWidth: 0 }}>
    <Hint>{value.loaded_bytes.toLocaleString()} loaded bytes · Byte range {value.offset.toLocaleString()}–{(value.offset + value.loaded_bytes).toLocaleString()} of {value.size.toLocaleString()} bytes · {value.mime || 'Unknown MIME'} · {value.encoding || 'Encoding not supplied'}</Hint>
    {value.reason ? <p>{value.reason}</p> : null}
    {value.parse_error ? <p role="alert">JSON parse error at offset {value.parse_error.offset ?? 'unknown'}: {value.parse_error.message || stringify(value.parse_error)}. Raw source remains available.</p> : null}
    {rich ? <ButtonGroup><Button aria-pressed={!raw} onClick={() => setRaw(false)}>Structured preview</Button><Button aria-pressed={raw} onClick={() => setRaw(true)}>Raw source</Button></ButtonGroup> : null}
    {!raw && value.kind === 'image' ? permittedRaster ? <figure style={{ margin: 0 }}><img src={raster} alt={`Raster preview of ${value.path || 'selected file'}`} width={width} height={height} style={{ maxWidth: '100%', height: 'auto' }} /><figcaption>{width} × {height} pixels · {value.mime} · Bounded local preview</figcaption></figure> : <p>Raster preview is unavailable within the image safety limits. Use the file download.</p> : null}
    {!raw && value.structured !== undefined ? <div aria-label="JSON tree"><JsonTree value={value.structured} /></div> : null}
    {!raw && value.records ? <div aria-label="JSONL records"><Hint>{value.records.length} records loaded. Record indices are local to this page; byte locators identify the source.</Hint>{value.records.map((record, index) => <details key={record.offset}><summary>Record {index + 1} · Byte {record.offset} · {record.bytes} bytes · {record.incomplete ? 'Incomplete final record' : record.error ? 'Invalid JSON' : record.schema_status || 'JSON syntax valid; schema not checked'}</summary>{record.error ? <p role="alert">{record.error}</p> : <JsonTree value={record.value} name="record" />}</details>)}</div> : null}
    {!raw && value.rows ? <div aria-label="Delimited table"><Hint>{Math.max(0, value.rows.length - (value.offset === 0 ? 1 : 0))} rows loaded. Total row count: {value.truncated || value.offset > 0 ? 'Unknown' : Math.max(0, value.rows.length - 1)}. Values retain their source text.</Hint><TableScroller><Table>{value.offset === 0 && value.rows.length ? <THead><tr>{value.rows[0].map((cell, index) => <th scope="col" key={index}>{cell || `Column ${index + 1}`}</th>)}</tr></THead> : null}<tbody>{value.rows.slice(value.offset === 0 ? 1 : 0).map((row, index) => <tr key={index}>{row.map((cell, column) => <td key={column} style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxWidth: 350 }}>{cell}</td>)}</tr>)}</tbody></Table></TableScroller>{value.offset > 0 ? <Hint>The file header is on the first page. This page contains continuation rows.</Hint> : null}</div> : null}
    {!raw && markdown ? <Markdown text={value.text} /> : null}
    {raw || !rich || value.parse_error ? <div><ButtonGroup><Checkbox label="Wrap source lines" checked={wrap} onChange={event => setWrap(event.target.checked)} /><TextInput aria-label="Search loaded preview page" placeholder="Search loaded page" value={search} onChange={event => setSearch(event.target.value)} /></ButtonGroup><Hint>{firstLine === null ? `Page lines 1–${lines.length}; absolute line range unknown at byte ${value.offset}.` : `Lines ${firstLine}–${firstLine + lines.length - 1}.`} Search covers only these loaded bytes.{search ? ` ${matches} matching lines.` : ''}</Hint><div role="region" aria-label="Escaped source preview" tabIndex={0} style={{ maxHeight: 520, overflow: 'auto', border: '1px solid currentColor', borderRadius: 4 }}><pre style={{ margin: 0, whiteSpace: wrap ? 'pre-wrap' : 'pre', overflowWrap: wrap ? 'anywhere' : 'normal' }}>{lines.map((line, index) => <div key={index} style={{ display: 'flex', minWidth: wrap ? 0 : 'max-content', width: wrap ? '100%' : undefined }}><span aria-hidden="true" style={{ width: 44, flexShrink: 0, textAlign: 'right', paddingRight: 12, opacity: 0.65, userSelect: 'none' }}>{(firstLine ?? 1) + index}</span><code style={{ minWidth: 0, flex: 1 }}>{marked(line, search)}</code></div>)}</pre></div></div> : null}
    {value.truncated ? <Hint>Truncated preview. Use Next bounded page to inspect more of this exact version.</Hint> : null}
  </div>;
}
