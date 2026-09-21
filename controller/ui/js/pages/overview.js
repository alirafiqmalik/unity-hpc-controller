/** Overview: KPIs, the partition heat map, alerts and the activity feed. */

import { drawUsageChart, windowNote } from '../chart.js';
import { ago, dash, esc, stUpper } from '../format.js';
import { latest, live, state } from '../state.js';

/** Colour and label for one utilisation percentage. */
export function heatColor(util) {
  if (util == null) return { c: '#3a4352', label: 'idle' };
  const v = Math.round(util);
  let c;
  if (v < 40) c = '#1f6f54'; else if (v < 70) c = '#34d399'; else if (v < 90) c = '#fbbf24'; else c = '#f87171';
  return { c, v };
}

/** Twenty-four cells, weighted by node count across the partitions. */
export function heatCells(parts, utilMap) {
  const cells = [];
  if (!parts.length) {
    for (let n = 0; n < 24; n++) {
      cells.push(`<div class="cell" style="background:#3a4352;color:#8b95a5"><span class="hn">—</span><small>idle</small></div>`);
    }
    return cells.join('');
  }
  const weights = parts.map(p => Math.max(1, Number(p.nodes) || 1));
  const sum = weights.reduce((a, b) => a + b, 0) || 1;
  parts.forEach((p, i) => {
    const gts = p.gpu_types || [];
    const avg = gts.map(g => utilMap[g]).filter(v => v != null);
    const util = avg.length ? avg.reduce((a, b) => a + b, 0) / avg.length : null;
    const { c, v } = heatColor(util);
    const sub = util == null ? 'idle' : (Math.round(v) + '%');
    const bg = util == null ? '#3a4352' : c + '22';
    const bd = util == null ? 'transparent' : c + '55';
    const fg = util == null ? '#8b95a5' : c;
    let n = Math.max(1, Math.round(weights[i] / sum * 24));
    const label = String(p.name || 'node');
    for (let k = 0; k < n && cells.length < 24; k++) {
      const name = n > 1 ? (label + '-' + k) : label;
      cells.push(`<div class="cell" style="background:${bg};border:1px solid ${bd};color:${fg}" title="${esc(p.name)} ${esc(sub)}"><span class="hn">${esc(name)}</span><small>${esc(sub)}</small></div>`);
    }
  });
  while (cells.length < 24) {
    cells.push(`<div class="cell" style="background:#3a4352;color:#8b95a5"><span class="hn">—</span><small>idle</small></div>`);
  }
  return cells.slice(0, 24).join('');
}

/** One row in the alert list or the activity feed. */
export function eventRow(e, col, ic) {
  const ok = e.ok !== false;
  col = col || (ok ? '#34d399' : '#f87171');
  ic = ic || (ok ? '&#10003;' : '&#10005;');
  return `<div class="feed-item"><div class="feed-ic" style="background:${col}22;color:${col}">${ic}</div><div>${esc(e.message || e.kind || 'event')}</div><div class="t">${esc(ago(e.ts))}</div></div>`;
}

export function render() {
  const cl = state.cluster || {};
  const L = live();
  const lat = latest();
  const bits = [cl.cluster || 'Unity HPC'];
  if (cl.slurm_version) bits.push('Slurm ' + cl.slurm_version);
  if (lat.total_nodes) bits.push(lat.total_nodes + ' nodes');
  bits.push('auto-refresh 10s');
  document.getElementById('ovSub').textContent = bits.join(' · ');

  const mineRun = state.jobs.filter(j => stUpper(j) === 'RUNNING').length;
  const minePend = state.jobs.filter(j => stUpper(j) === 'PENDING').length;
  document.getElementById('kGpu').innerHTML = L.available
    ? `${esc(dash(lat.free_nodes))}<span class="unit">${lat.total_nodes ? ('/ ' + lat.total_nodes) : ''}</span>`
    : '—';
  document.getElementById('kGpuD').textContent = lat.gpu_types_free || (L.available ? 'free nodes' : 'waiting on snapshot');
  document.getElementById('kRun').textContent = L.available ? dash(lat.gpu_running) : dash(mineRun || null);
  document.getElementById('kRunD').textContent = mineRun ? (mineRun + ' of these are yours') : 'cluster GPU jobs';
  document.getElementById('kPend').textContent = L.available ? dash(lat.gpu_pending) : dash(minePend || null);
  document.getElementById('kPendD').textContent = lat.gpu_preempt_pending ? (lat.gpu_preempt_pending + ' preempt pending') : 'GPU pending';
  const accounts = (cl.accounts || cl.users || []);
  const nUsers = Array.isArray(accounts) ? accounts.length : 0;
  document.getElementById('kUsers').textContent = nUsers ? String(nUsers) : '—';
  document.getElementById('kUsersD').textContent = nUsers ? 'in the cluster profile' : 'fairshare not in the profile';

  const byType = ((state.usage && state.usage.usage) || {}).by_type || [];
  const utilMap = {};
  byType.forEach(t => { if (t.gpu_type) utilMap[t.gpu_type] = t.avg; });
  const parts = cl.partitions || [];
  const heat = document.getElementById('heat');
  document.getElementById('heatRight').textContent = parts.length ? 'hover for detail · updated 10s' : 'no cluster profile yet';
  heat.innerHTML = heatCells(parts, utilMap);

  const ev = state.events.slice().reverse();
  const alerts = ev.filter(e => e.ok === false);
  document.getElementById('alertHead').textContent = alerts.length ? alerts.length + ' active' : 'quiet';
  document.getElementById('alerts').innerHTML = alerts.length
    ? alerts.slice(0, 6).map(e => eventRow(e, '#fbbf24', '&#9888;')).join('')
    : `<div class="feed-item"><div class="feed-ic" style="background:#34d39922;color:var(--accent)">&#10003;</div><div>No active alerts</div><div class="t">now</div></div>`;
  document.getElementById('feed').innerHTML = ev.length
    ? ev.slice(0, 8).map(e => eventRow(e)).join('')
    : `<div class="empty">No controller events yet</div>`;

  drawUsageChart('chartUtil', 'chartUtilLegend', state.usage, ['a100', 'a40', 'preempt']);
  windowNote('utilWindow', state.usage);
}
