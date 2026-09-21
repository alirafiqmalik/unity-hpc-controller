/**
 * Settings: controller facts, and the controls for Unity telemetry retrieval.
 *
 * app.js reads the endpoints every page shares. Telemetry state is only useful
 * on this tab, so this module reads /api/v1/telemetry itself. app.js calls
 * render() for the showing page alone, so that request stops when the operator
 * leaves the tab.
 */

import { api } from '../api.js';
import { ago, esc } from '../format.js';
import { state } from '../state.js';
import { toast } from '../toast.js';

/** The last payload from /api/v1/telemetry. */
let tel = null;
/** The error text from the last failed read, or null. */
let telError = null;
/** True while a read is in flight, so two renders do not stack requests. */
let reading = false;
/** The pending fast-poll timer, used while a retrieval runs. */
let poll = null;

const STATE_PILL = {
  ok: ['done', 'ok'],
  failed: ['fail', 'failed'],
  'already-running': ['pend', 'already running'],
  running: ['run', 'running'],
  unconfigured: ['grey', 'no source'],
};

function pill(status) {
  const [cls, label] = STATE_PILL[status] || ['grey', String(status || 'unknown')];
  return `<span class="pill ${cls}">${esc(label)}</span>`;
}

/** "2.4 MB", "780 kB", "512 B". */
function bytes(n) {
  if (n == null) return '—';
  if (n >= 1e9) return (n / 1e9).toFixed(1) + ' GB';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + ' MB';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + ' kB';
  return n + ' B';
}

/** A store line: how old the file is, and how big. */
function store(rec) {
  if (!rec || !rec.present) return 'absent';
  return ago(rec.mtime_utc) + ' · ' + bytes(rec.size_bytes);
}

/** Write a value into a field the operator is not typing in. */
function fill(id, value) {
  const el = document.getElementById(id);
  if (!el || el === document.activeElement) return;
  el.value = value;
}

function text(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

/** "closes after 45 min with no command". */
function idleText(seconds) {
  if (!seconds) return '—';
  const minutes = seconds / 60;
  const shown = Number.isInteger(minutes) ? String(minutes) : minutes.toFixed(1);
  return 'closes after ' + shown + ' min with no command';
}

export function render() {
  const cl = state.cluster || {};
  text('setSub', (cl.cluster || location.host) + ' · '
    + (state.health && state.health.ok ? 'up' : 'waiting'));
  text('setLogin', cl.cluster || 'unity');
  text('setOrigin', location.origin);
  text('setLedger', 'sqlite · ' + state.jobs.length + ' rows');
  text('setHealth', state.health ? (state.health.ok ? 'ok' : 'down') : (state.error || '—'));
  paint();
  load();
}

/** Read /api/v1/telemetry once and repaint. */
async function load() {
  if (reading) return;
  reading = true;
  try {
    const answer = await api('/api/v1/telemetry?limit=10');
    tel = answer.telemetry || null;
    telError = null;
  } catch (e) {
    telError = String((e && e.message) || e);
  } finally {
    reading = false;
    paint();
    schedulePoll();
  }
}

/** While a retrieval runs, read again in two seconds. */
function schedulePoll() {
  if (poll) { clearTimeout(poll); poll = null; }
  if (state.page !== 'settings') return;
  if (!tel || !tel.running) return;
  poll = setTimeout(() => { poll = null; load(); }, 2000);
}

function paint() {
  paintUsage();
  if (telError) {
    text('telState', telError);
    return;
  }
  if (!tel) {
    text('telState', 'reading…');
    return;
  }
  const src = tel.source || {};
  const sched = tel.schedule || {};
  const stores = tel.stores || {};
  const rollup = tel.rollup || {};
  const run = tel.in_flight || tel.last_run;

  text('telState', tel.running ? 'a retrieval is running' : 'idle');
  text('telSource', src.value || 'not configured');
  text('telOrigin', src.configured ? src.origin : 'nothing names a source');
  text('telRunning', tel.running ? (run && run.reason ? 'yes · ' + run.reason : 'yes') : 'no');
  text('telLastOk', tel.last_success ? ago(tel.last_success.finished_utc) : 'never from this controller');
  text('telRollup', rollup.last_rollup_utc
    ? ago(rollup.last_rollup_utc) + (rollup.current ? ' · current' : ' · behind the raw files')
    : 'never');
  text('telDb', store(stores.summaries_db));
  text('telCsv', store(stores.snapshot_csv));
  const raw = stores.telemetry || {};
  text('telRaw', raw.present
    ? raw.days + ' days · newest ' + (raw.newest_day || '—')
    : 'absent');

  const button = document.getElementById('telSyncBtn');
  if (button) {
    button.disabled = !!tel.running || !src.configured;
    button.textContent = tel.running ? 'Retrieval running…' : '⇣ Retrieve now';
  }
  const hint = document.getElementById('telHint');
  if (hint) {
    hint.textContent = src.configured
      ? 'One retrieval pulls the raw telemetry, then rolls it up. The pull and the rollup hold one lock, so two retrievals cannot overlap.'
      : 'Set a telemetry source below. Give it the rsync source that holds the cluster telemetry directory.';
  }

  const toggle = document.getElementById('telSchedTgl');
  if (toggle) toggle.classList.toggle('on', !!sched.enabled);
  text('telSchedState', sched.enabled
    ? (sched.thread_alive ? 'on' : 'on · thread not started')
    : 'off');
  text('telNext', sched.enabled ? ago(sched.next_run_utc) : 'schedule is off');
  text('telIdle', idleText(sched.inactivity_timeout_s));
  fill('telInterval', sched.interval_minutes || 60);
  fill('telSourceInput', src.origin === 'settings' ? src.value : '');

  paintHistory(tel.history || []);
  paintOutput(run);
}

/** Say which window the charts are drawing, and how old it is. */
function paintUsage() {
  const usage = (state.usage && state.usage.usage) || {};
  if (!usage.available) {
    text('telSeries', 'no rolled-up GPU series yet');
    return;
  }
  const window = usage.window === 'latest-available'
    ? 'last available window' : 'last ' + usage.hours + 'h';
  text('telSeries', usage.slots.length + ' slots · ' + window
    + ' · newest ' + ago(usage.freshness_utc));
}

function paintHistory(rows) {
  const box = document.getElementById('telHistory');
  if (!box) return;
  text('telHistHead', rows.length ? rows.length + ' kept' : '');
  if (!rows.length) {
    box.innerHTML = '<div class="empty">No retrieval has run from this controller yet.</div>';
    return;
  }
  box.innerHTML = rows.map(r => `<div class="tel-run">
    ${pill(r.status)}
    <span class="rs">${esc(r.reason || '')}${r.duration_s != null ? ' · ' + r.duration_s + 's' : ''}${r.rc != null ? ' · rc ' + r.rc : ''}</span>
    <span class="t">${esc(ago(r.finished_utc || r.started_utc))}</span>
  </div>`).join('');
}

function paintOutput(run) {
  const box = document.getElementById('telOutput');
  if (!box) return;
  if (!run) {
    box.textContent = 'No retrieval has run from this controller yet.';
    text('telOutHead', '');
    return;
  }
  text('telOutHead', (run.reason || '') + ' · ' + (run.status || ''));
  box.textContent = run.output || (run.status === 'running'
    ? 'Running. The output arrives when the retrieval ends.'
    : 'The retrieval produced no output.');
}

/** Send one settings change and repaint from the answer. */
async function save(change, note) {
  try {
    const answer = await api('/api/v1/telemetry/settings', {
      method: 'PATCH', body: JSON.stringify(change),
    });
    tel = answer.telemetry || tel;
    telError = null;
    toast(note);
  } catch (e) {
    toast(String((e && e.message) || e));
  }
  paint();
}

/** Start one retrieval. Bound from an inline handler. */
export async function telSync() {
  try {
    const answer = await api('/api/v1/telemetry/sync', {
      method: 'POST', body: JSON.stringify({ reason: 'manual' }),
    });
    if (answer.started) toast('Retrieval started');
    else toast(answer.message || answer.status || 'not started');
  } catch (e) {
    toast(String((e && e.message) || e));
  }
  load();
}

/** Turn the schedule on or off. Bound from an inline handler. */
export async function telSchedule(el) {
  const on = !el.classList.contains('on');
  await save({ schedule_enabled: on }, on ? 'Schedule on' : 'Schedule off');
}

/** Save the schedule interval. Bound from an inline handler. */
export async function telSaveInterval() {
  const el = document.getElementById('telInterval');
  const minutes = Number(el && el.value);
  if (!Number.isFinite(minutes)) { toast('interval must be a number'); return; }
  await save({ interval_minutes: Math.round(minutes) }, 'Interval saved');
}

/** Save the telemetry source. Bound from an inline handler. */
export async function telSaveSource() {
  const el = document.getElementById('telSourceInput');
  await save({ source: (el && el.value.trim()) || '' }, 'Source saved');
}
