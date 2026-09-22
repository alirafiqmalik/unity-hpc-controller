/**
 * Page switching, the refresh cycle, and the header.
 *
 * This module imports every page module. A page module must never import this
 * one back: it reaches refresh() through bus.js instead.
 */

import { api } from './api.js';
import { setRefresh } from './bus.js';
import { ago, fmtAge } from './format.js';
import { live, state } from './state.js';
import { toast } from './toast.js';

import * as overview from './pages/overview.js';
import * as queue from './pages/queue.js';
import * as jobs from './pages/jobs.js';
import * as users from './pages/users.js';
import * as analytics from './pages/analytics.js';
import * as dispatch from './pages/dispatch.js';
import * as projects from './pages/projects.js';
import * as settings from './pages/settings.js';

/** Page id to the module that draws it. Keys match config.TABS. */
export const PAGES = {
  overview, queue, jobs, users, analytics, dispatch, projects, settings,
};

/** Show one page and redraw it. */
export function go(name) {
  state.page = name;
  document.querySelectorAll('.tab').forEach(x => x.classList.toggle('active', x.dataset.t === name));
  document.querySelectorAll('.page').forEach(x => x.classList.toggle('active', x.id === 'pg-' + name));
  window.scrollTo({ top: 0 });
  render();
}

/** Mark the clicked chip as the only active one in its row. */
export function chipSel(el) {
  el.parentElement.querySelectorAll('.chip').forEach(c => c.classList.remove('on'));
  el.classList.add('on');
}

/** Draw the page that is showing. Every other page keeps its old markup. */
export function render() {
  const page = PAGES[state.page];
  if (page) page.render();
}

/** Connection pill, last-sync time and the Jobs badge. */
export function renderHeader() {
  const pill = document.getElementById('envPill');
  const label = document.getElementById('envLabel');
  const cl = state.cluster || {};
  const L = live();
  const name = cl.cluster || 'unity';
  if (state.error && !state.health) {
    pill.classList.add('off');
    label.textContent = 'controller unreachable';
  } else if (L.fresh) {
    pill.classList.remove('off');
    label.textContent = 'Cluster: ' + name + ' — live sync';
  } else if (L.available) {
    // Rows exist, but the newest one is old. The collector has stopped, so
    // these numbers are history. Never call that state live.
    pill.classList.add('off');
    label.textContent = 'Cluster: ' + name + ' — snapshot ' + fmtAge(L.age_s) + ' old';
  } else {
    pill.classList.add('off');
    label.textContent = 'Cluster: ' + name + ' — waiting on snapshot';
  }
  const ts = (L.latest && L.latest.timestamp_utc) || cl.generated_utc;
  document.getElementById('lastSync').textContent = ts ? ago(ts) : '—';
  const badge = document.getElementById('jobsBadge');
  if (badge) badge.textContent = String(state.jobs.length);
}

/**
 * Read every endpoint once and redraw.
 *
 * The calls settle independently, so one dead endpoint blanks its own panel
 * and leaves the rest of the dashboard live.
 */
export async function refresh(opts) {
  opts = opts || {};
  const settled = await Promise.allSettled([
    api('/api/v1/health'),
    api('/api/v1/cluster'),
    api('/api/v1/cluster/queue'),
    api('/api/v1/cluster/usage?hours=' + state.hours),
    api('/api/v1/jobs'),
    api('/api/v1/events'),
    fetch('/api/v1/projects').then(async r => {
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.error || r.statusText);
      return j;
    }),
  ]);
  const pick = (i, fallback) => settled[i].status === 'fulfilled' ? settled[i].value : fallback;
  const failed = settled.filter(s => s.status === 'rejected');
  state.error = failed.length === settled.length ? (failed[0].reason && failed[0].reason.message) || 'controller unreachable' : null;
  state.health = pick(0, null);
  state.cluster = pick(1, null);
  state.queue = pick(2, null);
  state.usage = pick(3, null);
  state.jobs = (pick(4, { jobs: [] }).jobs) || [];
  state.events = (pick(5, { events: [] }).events) || [];
  state.projects = (pick(6, { projects: [] }).projects) || [];
  if (state.error) toast(state.error);
  else if (opts.toastOk) toast('Refreshed');
  renderHeader();
  render();
  settings.maybePromptSsh((state.health && state.health.ssh) || {});
}

setRefresh(refresh);
