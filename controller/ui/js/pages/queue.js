/** Queue: partition cards, pending jobs, reason mix and the depth trend. */

import { drawTrend } from '../chart.js';
import { esc, jq, pillFor, queuedFor, stUpper } from '../format.js';
import { live, state } from '../state.js';

export function render() {
  const q = state.queue || {};
  const parts = q.partitions || (state.cluster && state.cluster.partitions) || [];
  const box = document.getElementById('parts');
  if (!parts.length) {
    box.innerHTML = `<div class="card"><div class="lbl">partitions</div>
      <div style="font-size:22px;font-weight:650;margin:4px 0 8px">—<span style="font-size:12px;color:var(--ink-2);font-weight:500"> / — busy</span></div>
      <div class="bar"><i style="width:0%"></i></div>
      <div style="display:flex;justify-content:space-between;margin-top:9px;font-size:11.5px;color:var(--muted)"><span>queued: <b style="color:var(--ink-2)">0</b></span><span>median wait: <b style="color:var(--ink-2)">—</b></span></div></div>`;
  } else {
    box.innerHTML = parts.map(p => {
      const total = Number(p.gpus_total) || Number(p.nodes) || 0;
      const runningHere = state.jobs.filter(j => j.partition === p.name && stUpper(j) === 'RUNNING').length;
      const pendingHere = state.jobs.filter(j => j.partition === p.name && stUpper(j) === 'PENDING').length;
      const used = total ? Math.min(total, runningHere) : runningHere;
      const pct = total ? Math.round(used / total * 100) : (runningHere ? 40 : 0);
      const cls = pct > 90 ? 'hot' : pct > 70 ? 'warn' : '';
      return `<div class="card"><div class="lbl">${esc(p.name)}</div>
        <div style="font-size:22px;font-weight:650;margin:4px 0 8px;font-variant-numeric:tabular-nums">${used}<span style="font-size:12px;color:var(--ink-2);font-weight:500"> / ${total || '—'} busy</span></div>
        <div class="bar ${cls}"><i style="width:${pct}%"></i></div>
        <div style="display:flex;justify-content:space-between;margin-top:9px;font-size:11.5px;color:var(--muted)"><span>queued: <b style="color:var(--ink-2)">${pendingHere}</b></span><span>median wait: <b style="color:var(--ink-2)">—</b></span></div></div>`;
    }).join('');
  }
  const pending = state.jobs.filter(j => stUpper(j) === 'PENDING');
  document.getElementById('pendRows').innerHTML = pending.length
    ? pending.slice(0, 10).map(j => {
        const [pill, lbl] = pillFor(j.status);
        return `<tr onclick='openJob(${jq(j.job_id)})'><td class="mono">${esc(j.job_id)}</td><td>${esc(j.slug || '—')}</td><td>${esc(j.partition || '—')}</td><td class="mono">${esc(j.hardware || '—')}</td><td class="mono">${esc(queuedFor(j))}</td><td><span class="pill ${pill}">${esc(lbl)}</span></td><td class="mono">—</td></tr>`;
      }).join('')
    : `<tr><td colspan="7" class="empty" style="cursor:default">No pending jobs in attached ledgers</td></tr>`;

  const buckets = {};
  pending.forEach(j => { const k = j.partition || 'unspecified'; buckets[k] = (buckets[k] || 0) + 1; });
  const entries = Object.entries(buckets);
  const tot = Math.max(1, pending.length);
  const mix = entries.length ? entries.map(([name, n]) => [name, Math.round(n / tot * 100), n / tot > 0.6 ? 'warn' : '']) : [['none', 0, '']];
  document.getElementById('reasons').innerHTML = mix.map(r => `<div class="kv"><span>${esc(r[0])}</span><div class="bar-row" style="width:55%"><div class="bar ${r[2]}" style="flex:1"><i style="width:${r[1]}%"></i></div><span class="pct">${r[1]}%</span></div></div>`).join('');
  const trend = (q.live && q.live.available && q.live.trend) || (live().trend) || [];
  drawTrend(trend);
}
