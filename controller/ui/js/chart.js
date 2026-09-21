/** Canvas line charts. The dashboard ships no charting library. */

import { CHART_COLORS } from './config.js';
import { esc, fmtAge } from './format.js';

/** First part of the storage key that holds the hidden series of a chart. */
const HIDDEN_KEY = 'uhpc.chart.hidden.';

/**
 * The hidden series of each chart, by canvas id.
 *
 * This map is the master copy in the page. localStorage is only a second
 * copy: it can throw in a private window and when the site data is blocked.
 * Thus the chart must stay correct when no storage is available.
 */
const hidden = new Map();

/** The last drawUsageChart() arguments of each legend, for a redraw. */
const lastDraw = new Map();

/**
 * The names of the series that are hidden in one chart.
 * @param {string} canvasId the id of the canvas element
 * @returns {string[]} the hidden names, empty when all series show
 */
export function hiddenSeries(canvasId) {
  if (hidden.has(canvasId)) return hidden.get(canvasId);
  let names = [];
  try {
    const raw = window.localStorage.getItem(HIDDEN_KEY + canvasId);
    const saved = raw ? JSON.parse(raw) : null;
    if (Array.isArray(saved)) names = saved.map(String);
  } catch (_err) {
    // No storage, or bad data in it. All series show.
    names = [];
  }
  hidden.set(canvasId, names);
  return names;
}

/**
 * Set the hidden series of one chart. A storage failure is not an error.
 * @param {string} canvasId the id of the canvas element
 * @param {string[]} names the names to hide
 * @returns {string[]} the new hidden names
 */
export function setHiddenSeries(canvasId, names) {
  const list = Array.from(new Set((names || []).map(String)));
  hidden.set(canvasId, list);
  try {
    window.localStorage.setItem(HIDDEN_KEY + canvasId, JSON.stringify(list));
  } catch (_err) {
    // No storage. The map above keeps the choice until the page reloads.
  }
  return list;
}

/**
 * Show a hidden series of one chart, or hide a series that shows.
 * @param {string} canvasId the id of the canvas element
 * @param {string} name the name of the series
 * @returns {string[]} the new hidden names
 */
export function toggleSeries(canvasId, name) {
  const now = hiddenSeries(canvasId);
  const next = now.includes(name) ? now.filter(n => n !== name) : now.concat(String(name));
  return setHiddenSeries(canvasId, next);
}

/**
 * Pack the usage payload into parallel series, or null when it is empty.
 *
 * A colour comes from the position of the series in the full list. Thus a
 * series keeps its colour when a different series goes off.
 */
export function usageSeries(usage) {
  if (!usage || !usage.usage) return null;
  const u = usage.usage;
  if (!u.available || !u.series || !Object.keys(u.series).length) return null;
  const names = Object.keys(u.series);
  return {
    names,
    series: names.map(n => (u.series[n] || []).map(v => v == null || v === '' ? null : Number(v))),
    colors: names.map((_, i) => CHART_COLORS[i % CHART_COLORS.length]),
  };
}

/** One legend entry. A dim entry is a series that is off, but selectable. */
function legendItem(name, color, shows) {
  const style = 'cursor:pointer;user-select:none;opacity:' + (shows ? '1' : '.4');
  const tip = (shows ? 'Hide ' : 'Show ') + name;
  return `<span data-series="${esc(name)}" role="button" tabindex="0" aria-pressed="${shows}" title="${esc(tip)}" style="${style}"><i style="background:${color}"></i>${esc(name)}</span>`;
}

/**
 * Make the legend the series selector.
 *
 * The listener is on the legend element, not on the entries. Thus it stays
 * after a redraw writes new entries, and one legend gets one listener.
 */
function wireLegend(legend, legendId) {
  if (legend.dataset.seriesWired === '1') return;
  legend.dataset.seriesWired = '1';
  const hit = e => {
    const item = e.target && e.target.closest && e.target.closest('[data-series]');
    if (!item) return;
    if (e.type === 'keydown') {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      e.preventDefault();
    }
    const args = lastDraw.get(legendId);
    if (!args) return;
    const name = item.dataset.series;
    toggleSeries(args.canvasId, name);
    drawUsageChart(args.canvasId, legendId, args.usage, args.fallbackNames);
    if (e.type === 'keydown') {
      // The redraw wrote new entries. Move the focus to the new one.
      const again = Array.from(legend.children).find(c => c.dataset.series === name);
      if (again) again.focus();
    }
  };
  legend.addEventListener('click', hit);
  legend.addEventListener('keydown', hit);
}

/**
 * Draw a usage chart, falling back to an empty frame plus a static legend.
 *
 * The legend is also the series selector: a click on an entry shows or hides
 * that series. Every series the API sends gets an entry, also the hidden
 * ones, which show dim. The choice is kept for each canvas independently.
 * @param {string} canvasId the id of the canvas element
 * @param {string} legendId the id of the legend element
 * @param {object} usage the payload from /api/v1/cluster/usage
 * @param {string[]} fallbackNames the legend names to show when no data came
 */
export function drawUsageChart(canvasId, legendId, usage, fallbackNames) {
  const cv = document.getElementById(canvasId);
  const legend = document.getElementById(legendId);
  const packed = usageSeries(usage);
  if (cv) cv.style.display = 'block';
  if (legend) lastDraw.set(legendId, { canvasId, usage, fallbackNames });
  if (!packed) {
    if (cv) lineChart(cv, [[]], ['#34d399'], false);
    if (legend && fallbackNames) {
      legend.innerHTML = fallbackNames.map((n, i) => `<span><i style="background:${CHART_COLORS[i % CHART_COLORS.length]}"></i>${esc(n)}</span>`).join('');
    }
    return;
  }
  const off = hiddenSeries(canvasId);
  const shows = packed.names.map(n => !off.includes(n));
  if (legend) {
    legend.innerHTML = packed.names.map((n, i) => legendItem(n, packed.colors[i], shows[i])).join('');
    wireLegend(legend, legendId);
  }
  const keep = packed.names.map((_, i) => i).filter(i => shows[i]);
  if (!keep.length) {
    // All the series are off. Keep the empty frame, which has the grid lines
    // but no data. The legend stays complete, thus the operator can select a
    // series again.
    lineChart(cv, [[]], [CHART_COLORS[0]], false);
    return;
  }
  lineChart(cv, keep.map(i => packed.series[i]), keep.map(i => packed.colors[i]), true);
}

/** Draw the queue-depth trend: pending over running. */
export function drawTrend(trend) {
  const cv = document.getElementById('chartQ');
  const legend = document.getElementById('chartQLegend');
  if (legend) legend.innerHTML = '<span><i style="background:#fbbf24"></i>pending</span><span><i style="background:#34d399"></i>running</span>';
  if (!cv) return;
  cv.style.display = 'block';
  if (!trend || !trend.length) {
    lineChart(cv, [[]], ['#fbbf24'], false);
    return;
  }
  lineChart(cv, [trend.map(r => Number(r.pending) || 0), trend.map(r => Number(r.running) || 0)], ['#fbbf24', '#34d399'], false);
}

/** Draw `series` onto `cv`, one stroke each, optionally filled. */
export function lineChart(cv, series, colors, fill) {
  if (!cv) return;
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth || cv.parentElement.clientWidth || 300;
  // Read the authored height once and cache it. Setting the `height`
  // PROPERTY below reflects back into the `height` ATTRIBUTE, so a later
  // call must never re-read the attribute: it would see the already
  // dpr-scaled value and scale it again on every re-render.
  if (cv.dataset.h === undefined) cv.dataset.h = cv.getAttribute('height') || '150';
  const h = +cv.dataset.h || 150;
  if (!w) return;
  cv.width = w * dpr; cv.height = h * dpr;
  // Pin the CSS layout height explicitly. The CSS rule only sets `width`,
  // so layout height would otherwise follow the (now dpr-scaled) `height`
  // attribute and grow the element on screen.
  cv.style.height = h + 'px';
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = '#232b38'; ctx.lineWidth = 1;
  for (let i = 1; i < 4; i++) { ctx.beginPath(); ctx.moveTo(0, h * i / 4); ctx.lineTo(w, h * i / 4); ctx.stroke(); }
  const flat = series.flat().filter(v => v != null && !Number.isNaN(v));
  if (!flat.length) return;
  const max = Math.max(...flat, 1) * 1.1, min = Math.min(0, ...flat);
  const span = max - min || 1;
  series.forEach((s, si) => {
    const n = Math.max(s.length, 2);
    ctx.beginPath();
    let drawing = false;
    s.forEach((v, i) => {
      if (v == null || Number.isNaN(v)) { drawing = false; return; }
      const x = i / (n - 1) * w, y = h - ((v - min) / span) * (h - 6) - 3;
      if (!drawing) { ctx.moveTo(x, y); drawing = true; } else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = colors[si]; ctx.lineWidth = 1.8; ctx.stroke();
    if (fill && s.every(v => v != null)) {
      ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.closePath();
      const g = ctx.createLinearGradient(0, 0, 0, h);
      g.addColorStop(0, colors[si] + '44'); g.addColorStop(1, colors[si] + '00');
      ctx.fillStyle = g; ctx.fill();
    }
  });
}

/**
 * Say which window a usage chart actually drew.
 *
 * The API slides the window back to the newest data that exists when the last
 * `hours` hold none, so a chart headed "last 24h" can be showing much older
 * rows. Saying so is the difference between history and a wrong reading.
 */
export function windowNote(spanId, usage) {
  const el = document.getElementById(spanId);
  if (!el) return;
  const u = (usage && usage.usage) || {};
  if (!u.available) { el.textContent = ''; el.style.color = ''; return; }
  if (u.window === 'latest-available') {
    el.textContent = 'newest data ' + fmtAge(u.stale_s) + ' old';
    el.style.color = 'var(--amber)';
  } else {
    el.textContent = '';
    el.style.color = '';
  }
}
