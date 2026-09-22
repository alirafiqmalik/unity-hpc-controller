/** Analytics: the usage chart, the outcome donut and GPU-hours. */

import { drawUsageChart, windowNote } from '../chart.js';
import { esc, fmtHours, gpuHours } from '../format.js';
import { state } from '../state.js';

const DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const SEQ = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b'];

export function render() {
  drawUsageChart('chartAn', 'chartAnLegend', state.usage, ['a100', 'a40', 'cpu-only']);
  windowNote('anWindow', state.usage);
  const out = (state.usage && state.usage.outcomes) || {};
  const box = document.getElementById('outcomesBox');
  const counts = (out.available && out.counts) || {};
  const labels = [['COMPLETED', 'Completed', '#60a5fa'], ['FAILED', 'Failed', '#f87171'], ['TIMEOUT', 'Timeout', '#fbbf24'], ['CANCELLED', 'Cancelled', '#3a4352']];
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
      ${labels.map(([key, label, col]) => `<div class="kv"><span><b style="color:${col}">&#9679;</b>&nbsp; ${label}</span><b>${counts[key] != null ? esc(Number(counts[key]).toLocaleString()) : '—'}</b></div>`).join('')}
    </div></div>`;
  paintBars();
  paintHeat();
}

function paintBars() {
  const bars = document.getElementById('projBars');
  if (!bars) return;
  const head = document.getElementById('projBarsHead');
  if (state.projects.length) {
    if (head) head.textContent = 'GPU-hours by project — last 30 days';
    const rows = state.projects.map(p => {
      const mine = state.jobs.filter(j => j.slug === p.slug);
      return { label: p.slug, h: gpuHours(mine) };
    });
    drawBars(bars, rows);
    return;
  }
  const stats = (state.usage && state.usage.stats) || (state.cluster && state.cluster.stats) || {};
  const hw = stats.by_hardware || [];
  if (head) head.textContent = hw.length
    ? 'GPU-hours by hardware — rollup'
    : 'GPU-hours by project — last 30 days';
  if (!hw.length) {
    bars.innerHTML = '<div class="empty">No attached projects and no rollup yet</div>';
    return;
  }
  drawBars(bars, hw.map(r => ({ label: r.hardware, h: Number(r.gpu_hours) || 0 })));
}

function drawBars(mount, rows) {
  const max = Math.max(1, ...rows.map(r => r.h));
  mount.innerHTML = rows.map(r => {
    const pct = Math.round(r.h / max * 100);
    return `<div class="kv"><span class="mono">${esc(r.label)}</span><div class="bar-row" style="width:65%"><div class="bar" style="flex:1"><i style="width:${pct}%;background:var(--blue)"></i></div><span class="pct">${fmtHours(r.h)}</span></div></div>`;
  }).join('');
}

function paintHeat() {
  const mount = document.getElementById('anHeat');
  if (!mount) return;
  const cells = ((state.usage && state.usage.usage) || {}).heatmap || [];
  if (!cells.length) {
    mount.innerHTML = '<div class="empty">No hourly GPU series in this window</div>';
    return;
  }
  const grid = new Map();
  let max = 0;
  cells.forEach(c => {
    grid.set(c.dow + '-' + c.hour, c.value);
    if (c.value > max) max = c.value;
  });
  max = max || 1;
  const wrap = document.createElement('div');
  wrap.className = 'heat-dow';
  for (let d = 0; d < 7; d++) {
    const lab = document.createElement('div');
    lab.className = 'hlabel';
    lab.textContent = DOW[d];
    wrap.appendChild(lab);
    for (let h = 0; h < 24; h++) {
      const cell = document.createElement('div');
      cell.className = 'hcell';
      const v = grid.get(d + '-' + h);
      if (v == null) {
        cell.style.background = 'var(--panel-2)';
      } else {
        const idx = Math.min(SEQ.length - 1, Math.round((v / max) * (SEQ.length - 1)));
        cell.style.background = SEQ[idx];
        cell.title = DOW[d] + ' ' + String(h).padStart(2, '0') + ':00 UTC · avg ' + v;
      }
      wrap.appendChild(cell);
    }
  }
  const spacer = document.createElement('div');
  wrap.appendChild(spacer);
  for (let h = 0; h < 24; h++) {
    const hl = document.createElement('div');
    hl.className = 'hhour';
    hl.textContent = h % 3 === 0 ? String(h).padStart(2, '0') : '';
    wrap.appendChild(hl);
  }
  mount.innerHTML = '';
  mount.appendChild(wrap);
}
