/** Pure formatters. No DOM, no state, no network. */

import { FAIL_STATES } from './config.js';

/** Escape a value for interpolation into an HTML string. */
export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

/** Quote a value for an inline handler argument. */
export function jq(s) {
  return JSON.stringify(String(s ?? ''));
}

/** An em dash for a missing value, the value itself otherwise. */
export function dash(v) {
  return (v === 0 || v) ? v : '—';
}

/** "3m ago" for a recent ISO timestamp, the timestamp itself when old. */
export function ago(iso) {
  if (!iso) return '—';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return String(iso);
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return Math.round(s) + 's ago';
  if (s < 3600) return Math.round(s / 60) + 'm ago';
  if (s < 86400) return (s / 3600).toFixed(1) + 'h ago';
  return iso.replace('T', ' ').replace('Z', ' UTC');
}

/** Seconds as h:mm:ss, or m:ss below one hour. */
export function fmtElapsed(s) {
  if (s == null || s === '') return '—';
  s = Number(s);
  if (!Number.isFinite(s)) return '—';
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
  return (h > 0 ? h + ':' : '') + String(m).padStart(h > 0 ? 2 : 1, '0') + ':' + String(sec).padStart(2, '0');
}

/** A job's status in upper case, or '' when it has none. */
export function stUpper(j) {
  return String((j && j.status) || '').toUpperCase();
}

/** The [pill class, label] pair for a SLURM state. */
export function pillFor(st) {
  const u = String(st || '').toUpperCase();
  if (u === 'RUNNING') return ['run', 'Running'];
  if (u === 'PENDING') return ['pend', 'Pending'];
  if (u === 'COMPLETED') return ['done', 'Completed'];
  if (u === 'CANCELLED') return ['grey', 'Cancelled'];
  if (FAIL_STATES.includes(u)) return ['fail', u.replaceAll('_', ' ')];
  return ['grey', u || 'unknown'];
}

/** Sum the counts whose state name is in `names`. */
export function jobCount(counts, names) {
  const c = counts || {};
  let n = 0;
  for (const k of Object.keys(c)) {
    if (names.includes(String(k).toUpperCase())) n += Number(c[k]) || 0;
  }
  return n;
}

/** How long a pending job has waited. */
export function queuedFor(j) {
  if (!j.submitted_utc) return '—';
  const t = Date.parse(j.submitted_utc);
  if (Number.isNaN(t)) return '—';
  return fmtElapsed((Date.now() - t) / 1000);
}

/** A job's exit column: '0', an em dash while live, or the failure state. */
export function exitOf(j) {
  const u = stUpper(j);
  if (u === 'COMPLETED') return '0';
  if (u === 'RUNNING' || u === 'PENDING' || !u) return '—';
  return u;
}

/** Elapsed seconds over a job list, as hours. */
export function gpuHours(list) {
  const s = (list || []).reduce((a, j) => a + (Number(j.elapsed_s) || 0), 0);
  return s / 3600;
}

/** A coarse age for an operator: "59d", "3h", "12m", "45s". */
export function fmtAge(seconds) {
  if (seconds == null) return '';
  const s = Number(seconds);
  if (!Number.isFinite(s) || s < 0) return '';
  if (s < 90) return Math.round(s) + 's';
  if (s < 5400) return Math.round(s / 60) + 'm';
  if (s < 172800) return Math.round(s / 3600) + 'h';
  return Math.round(s / 86400) + 'd';
}
