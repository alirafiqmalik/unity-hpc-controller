/** Analytics: the usage chart, the outcome donut and GPU-hours by project. */

import { drawUsageChart, windowNote } from '../chart.js';
import { esc, gpuHours } from '../format.js';
import { state } from '../state.js';

export function render() {
  drawUsageChart('chartAn', 'chartAnLegend', state.usage, ['a100', 'a40', 'cpu-only']);
  windowNote('anWindow', state.usage);
  const out = (state.usage && state.usage.outcomes) || {};
  const box = document.getElementById('outcomesBox');
  const counts = (out.available && out.counts) || {};
  const labels = [['COMPLETED', 'Completed', '#60a5fa'], ['FAILED', 'Failed', '#f87171'], ['TIMEOUT', 'Timeout', '#fbbf24'], ['CANCELLED', 'Cancelled', '#3a4352']];
  const known = labels.reduce((a, x) => a + (Number(counts[x[0]]) || 0), 0);
  const total = Object.values(counts).reduce((a, b) => a + (Number(b) || 0), 0) || 0;
  let acc = 0, stops = [];
  if (total) {
    labels.forEach(([key, , col]) => {
      const frac = (Number(counts[key]) || 0) / total * 100;
      if (frac) { stops.push(`${col} ${acc}% ${acc + frac}%`); acc += frac; }
    });
    if (acc < 100) stops.push(`#3a4352 ${acc}% 100%`);
  }
  const donut = stops.length ? `conic-gradient(${stops.join(',')})` : '#3a4352';
  box.innerHTML = `<div style="display:flex;align-items:center;gap:26px">
    <div style="width:150px;height:150px;border-radius:50%;flex-shrink:0;background:${donut}"></div>
    <div class="stack" style="flex:1">
      ${labels.map(([key, label, col]) => `<div class="kv"><span><b style="color:${col}">&#9679;</b>&nbsp; ${label}</span><b>${counts[key] != null ? esc(counts[key]) : '—'}</b></div>`).join('')}
    </div></div>`;
  if (!known && !total) { /* keep the empty dashes */ }
  const bars = document.getElementById('projBars');
  if (!state.projects.length) {
    bars.innerHTML = '<div class="empty">No attached projects</div>';
  } else {
    const rows = state.projects.map(p => {
      const mine = state.jobs.filter(j => j.slug === p.slug);
      const h = gpuHours(mine);
      return { slug: p.slug, h };
    });
    const max = Math.max(1, ...rows.map(r => r.h));
    bars.innerHTML = rows.map(r => {
      const pct = Math.round(r.h / max * 100);
      const label = r.h ? r.h.toFixed(1) + 'h' : '0h';
      return `<div class="kv"><span class="mono">${esc(r.slug)}</span><div class="bar-row" style="width:65%"><div class="bar" style="flex:1"><i style="width:${pct}%;background:var(--blue)"></i></div><span class="pct">${label}</span></div></div>`;
    }).join('');
  }
}
