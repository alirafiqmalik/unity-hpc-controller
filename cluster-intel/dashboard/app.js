/* Unity cluster monitor — rendering.
 *
 * Zero dependencies: charts are hand-drawn SVG so the page works over a bare
 * tailnet with no CDN. Each chart is its own small function — edit one without
 * touching the others. Colors are read from CSS custom properties (style.css),
 * so re-theming happens in the stylesheet, not here.
 */

const SVGNS = "http://www.w3.org/2000/svg";
const state = { hours: 168 };
const tip = document.getElementById("tip");

// ── palette helpers ──────────────────────────────────────────────────────────
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
// categorical slots, assigned to GPU types in fixed order (never cycled past 8)
const seriesColor = (i) => css(`--series-${(i % 8) + 1}`);
// sequential blue ramp for the heatmap (dataviz reference, blue 100→700)
const SEQ = ["#cde2fb","#b7d3f6","#9ec5f4","#86b6ef","#6da7ec","#5598e7",
             "#3987e5","#2a78d6","#256abf","#1c5cab","#184f95","#104281","#0d366b"];

const el = (tag, attrs = {}) => {
  const n = document.createElementNS(SVGNS, tag);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  return n;
};
const shortTime = (iso) => (iso || "").replace("T", " ").replace(/:00Z?$/, "").replace("Z", "");

// ── tooltip ──────────────────────────────────────────────────────────────────
function showTip(html, x, y) {
  tip.innerHTML = html;
  tip.style.opacity = "1";
  const pad = 14;
  let left = x + pad, top = y + pad;
  const r = tip.getBoundingClientRect();
  if (left + r.width > innerWidth) left = x - r.width - pad;
  if (top + r.height > innerHeight) top = y - r.height - pad;
  tip.style.left = left + "px";
  tip.style.top = top + "px";
}
const hideTip = () => { tip.style.opacity = "0"; };

// ── generic multi-series line chart ──────────────────────────────────────────
// series: [{ name, color, values:[num|null] }], labels: [str]
function lineChart(mount, labels, series, yLabel) {
  mount.innerHTML = "";
  if (!labels.length) { mount.innerHTML = `<div class="empty">No data in this window.</div>`; return; }

  const W = 720, H = 260, m = { l: 40, r: 14, t: 12, b: 26 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  let max = 0;
  for (const s of series) for (const v of s.values) if (v != null && v > max) max = v;
  max = max || 1;
  const nx = labels.length;
  const x = (i) => m.l + (nx === 1 ? iw / 2 : (i / (nx - 1)) * iw);
  const y = (v) => m.t + ih - (v / max) * ih;

  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" });

  // y gridlines + ticks (4 steps)
  for (let k = 0; k <= 4; k++) {
    const val = (max / 4) * k, yy = y(val);
    svg.appendChild(el("line", { x1: m.l, y1: yy, x2: W - m.r, y2: yy, class: "gridline" }));
    const t = el("text", { x: m.l - 6, y: yy + 3, class: "ax", "text-anchor": "end" });
    t.textContent = Number.isInteger(val) ? val : val.toFixed(0);
    svg.appendChild(t);
  }
  // x ticks: first / middle / last
  [0, Math.floor((nx - 1) / 2), nx - 1].forEach((i, k) => {
    const t = el("text", { x: x(i), y: H - 8, class: "ax",
      "text-anchor": k === 0 ? "start" : k === 2 ? "end" : "middle" });
    t.textContent = shortTime(labels[i]);
    svg.appendChild(t);
  });
  const yl = el("text", { x: m.l - 6, y: m.t - 2, class: "ax", "text-anchor": "end" });
  yl.textContent = yLabel; svg.appendChild(yl);

  // lines (break on null so gaps show)
  for (const s of series) {
    let d = "", pen = false;
    s.values.forEach((v, i) => {
      if (v == null) { pen = false; return; }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)} `;
      pen = true;
    });
    svg.appendChild(el("path", { d, fill: "none", stroke: s.color,
      "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
  }

  // hover: crosshair + nearest-index tooltip
  const cross = el("line", { class: "axline", y1: m.t, y2: m.t + ih, opacity: 0 });
  svg.appendChild(cross);
  const dots = series.map((s) => {
    const c = el("circle", { r: 3.5, fill: s.color, stroke: css("--surface"),
      "stroke-width": 1.5, opacity: 0 });
    svg.appendChild(c); return c;
  });
  const hit = el("rect", { x: m.l, y: m.t, width: iw, height: ih, fill: "transparent" });
  svg.appendChild(hit);
  hit.addEventListener("mousemove", (e) => {
    const box = svg.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * W;
    let i = Math.round(((px - m.l) / iw) * (nx - 1));
    i = Math.max(0, Math.min(nx - 1, i));
    cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("opacity", 1);
    let rows = `<b>${shortTime(labels[i])}</b>`;
    series.forEach((s, k) => {
      const v = s.values[i];
      dots[k].setAttribute("opacity", v == null ? 0 : 1);
      if (v != null) { dots[k].setAttribute("cx", x(i)); dots[k].setAttribute("cy", y(v)); }
      rows += `<br><span class="sw" style="background:${s.color}"></span>${s.name}: <b>${v == null ? "—" : v}</b>`;
    });
    showTip(rows, e.clientX, e.clientY);
  });
  hit.addEventListener("mouseleave", () => {
    hideTip(); cross.setAttribute("opacity", 0); dots.forEach((d) => d.setAttribute("opacity", 0));
  });

  mount.appendChild(svg);
}

function legend(mount, items) {
  mount.innerHTML = items.map((it) =>
    `<span><i style="background:${it.color}"></i>${it.name}</span>`).join("");
}

// ── per-type bar chart (avg fill + peak cap) ─────────────────────────────────
function barChart(mount, rows) {
  mount.innerHTML = "";
  if (!rows.length) { mount.innerHTML = `<div class="empty">No historical data.</div>`; return; }
  const W = 360, H = 260, m = { l: 34, r: 12, t: 12, b: 44 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const max = Math.max(...rows.map((r) => r.peak)) || 1;
  const y = (v) => m.t + ih - (v / max) * ih;
  const bw = iw / rows.length;
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" });

  for (let k = 0; k <= 4; k++) {
    const val = (max / 4) * k, yy = y(val);
    svg.appendChild(el("line", { x1: m.l, y1: yy, x2: W - m.r, y2: yy, class: "gridline" }));
    const t = el("text", { x: m.l - 6, y: yy + 3, class: "ax", "text-anchor": "end" });
    t.textContent = val.toFixed(0); svg.appendChild(t);
  }

  rows.forEach((r, i) => {
    const color = seriesColor(i);
    const cx = m.l + i * bw + bw / 2;
    const w = Math.min(46, bw * 0.6);
    // avg bar, rounded top
    svg.appendChild(el("rect", { x: cx - w / 2, y: y(r.avg), width: w, height: (m.t + ih) - y(r.avg),
      rx: 4, fill: color }));
    // peak cap line
    svg.appendChild(el("line", { x1: cx - w / 2, y1: y(r.peak), x2: cx + w / 2, y2: y(r.peak),
      stroke: css("--ink-2"), "stroke-width": 2, "stroke-dasharray": "3 2" }));
    // labels
    const lab = el("text", { x: cx, y: H - 26, class: "ax", "text-anchor": "middle" });
    lab.textContent = r.gpu_type; svg.appendChild(lab);
    const val = el("text", { x: cx, y: y(r.avg) - 5, class: "ax", "text-anchor": "middle" });
    val.style.fill = css("--ink-2"); val.textContent = r.avg; svg.appendChild(val);

    const hit = el("rect", { x: m.l + i * bw, y: m.t, width: bw, height: ih, fill: "transparent" });
    hit.addEventListener("mousemove", (e) => showTip(
      `<b>${r.gpu_type}</b><br>avg <b>${r.avg}%</b> · median ${r.median}%<br>peak <b>${r.peak}%</b>`,
      e.clientX, e.clientY));
    hit.addEventListener("mouseleave", hideTip);
    svg.appendChild(hit);
  });
  const cap = el("text", { x: m.l, y: H - 8, class: "ax" });
  cap.textContent = "— — peak · bar = avg"; svg.appendChild(cap);
  mount.appendChild(svg);
}

// ── heatmap (hour × day-of-week) ─────────────────────────────────────────────
const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
function heatmap(mount, cells) {
  mount.innerHTML = "";
  if (!cells.length) { mount.innerHTML = `<div class="empty">No historical data.</div>`; return; }
  const grid = new Map();          // "dow-hour" -> value
  let max = 0;
  for (const c of cells) { grid.set(`${c.dow}-${c.hour}`, c.value); if (c.value > max) max = c.value; }
  max = max || 1;

  const wrap = document.createElement("div");
  wrap.className = "heatmap";
  for (let d = 0; d < 7; d++) {
    const lab = document.createElement("div");
    lab.className = "hlabel"; lab.textContent = DOW[d]; wrap.appendChild(lab);
    for (let h = 0; h < 24; h++) {
      const cell = document.createElement("div");
      cell.className = "hcell";
      const v = grid.get(`${d}-${h}`);
      if (v == null) {
        cell.style.background = css("--grid");
      } else {
        const idx = Math.min(SEQ.length - 1, Math.round((v / max) * (SEQ.length - 1)));
        cell.style.background = SEQ[idx];
      }
      cell.addEventListener("mousemove", (e) => showTip(
        `<b>${DOW[d]} ${String(h).padStart(2, "0")}:00 UTC</b><br>avg <b>${v == null ? "—" : v}%</b> GPU usage`,
        e.clientX, e.clientY));
      cell.addEventListener("mouseleave", hideTip);
      wrap.appendChild(cell);
    }
  }
  // bottom hour axis
  const spacer = document.createElement("div"); wrap.appendChild(spacer);
  for (let h = 0; h < 24; h++) {
    const hl = document.createElement("div");
    hl.className = "hhour"; hl.textContent = h % 3 === 0 ? String(h).padStart(2, "0") : "";
    wrap.appendChild(hl);
  }
  mount.appendChild(wrap);
}

// ── KPI tiles (live snapshot) ────────────────────────────────────────────────
function renderKPIs(live) {
  const box = document.getElementById("kpis");
  if (!live.available) {
    box.innerHTML = `<div class="kpi"><div class="label">Live queue</div>
      <div class="foot">snapshot.csv not synced yet — run the poller / sync.</div></div>`;
    return;
  }
  const L = live.latest;
  const freePct = L.total_nodes ? Math.round((L.free_nodes / L.total_nodes) * 100) : 0;
  const pendColor = L.gpu_pending > 20 ? "--critical" : L.gpu_pending > 5 ? "--warning" : "--good";
  const tiles = [
    { label: "GPU jobs running", value: L.gpu_running, foot: `partition: gpu` },
    { label: "GPU jobs pending", value: L.gpu_pending, dot: pendColor,
      foot: `+${L.gpu_preempt_pending} on gpu-preempt` },
    { label: "Free GPU nodes", value: L.free_nodes, unit: `/ ${L.total_nodes}`,
      foot: `${freePct}% idle` },
    { label: "GPU types free", value: (L.gpu_types_free || "—").split("|").length,
      foot: (L.gpu_types_free || "none").replace(/\|/g, " · ") },
  ];
  box.innerHTML = tiles.map((t) => `
    <div class="kpi">
      <div class="label">${t.label}</div>
      <div class="value">${t.dot ? `<span class="dot" style="background:var(${t.dot})"></span>` : ""}${t.value}${t.unit ? `<span class="unit">${t.unit}</span>` : ""}</div>
      <div class="foot">${t.foot}</div>
    </div>`).join("");
}

// ── cluster profile panel (renders the /unity-hpc:recon markdown) ──────────────────
const esc = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const inline = (s) => esc(s)
  .replace(/`([^`]+)`/g, "<code>$1</code>")
  .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");

// Minimal markdown → HTML: headings, tables, lists, blockquotes, paragraphs.
function mdToHtml(md) {
  const lines = md.split("\n");
  let html = "", i = 0;
  const closeList = (buf) => (buf ? `<ul>${buf}</ul>` : "");
  while (i < lines.length) {
    let ln = lines[i];
    if (/^#\s/.test(ln)) { i++; continue; }                    // drop the H1 title (shown in card head)
    if (/^_.*_$/.test(ln.trim())) { i++; continue; }           // drop the italic "last updated" line
    if (/^###?\s/.test(ln)) {                                   // ## / ### headings
      const lvl = ln.startsWith("###") ? 4 : 3;
      html += `<h${lvl}>${inline(ln.replace(/^#+\s/, ""))}</h${lvl}>`; i++; continue;
    }
    if (/^\s*>/.test(ln)) {                                     // blockquote
      let q = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) { q.push(inline(lines[i].replace(/^\s*>\s?/, ""))); i++; }
      html += `<blockquote>${q.join(" ")}</blockquote>`; continue;
    }
    if (/^\s*\|/.test(ln)) {                                    // table block
      const rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) { rows.push(lines[i]); i++; }
      const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      let t = "<div style='overflow-x:auto'><table>";
      rows.forEach((r, idx) => {
        if (/^\s*\|?[\s:|-]+\|?\s*$/.test(r)) return;           // separator row
        const tag = idx === 0 ? "th" : "td";
        t += "<tr>" + cells(r).map((c) => `<${tag}>${inline(c)}</${tag}>`).join("") + "</tr>";
      });
      html += t + "</table></div>"; continue;
    }
    if (/^\s*[-*]\s/.test(ln)) {                                // unordered list
      let buf = "";
      while (i < lines.length && /^\s*[-*]\s/.test(lines[i])) { buf += `<li>${inline(lines[i].replace(/^\s*[-*]\s/, ""))}</li>`; i++; }
      html += closeList(buf); continue;
    }
    if (ln.trim() === "") { i++; continue; }
    html += `<p>${inline(ln)}</p>`; i++;                        // paragraph
  }
  return html;
}

function renderProfile(profile) {
  const card = document.getElementById("profile-card");
  if (!profile || !profile.present || !profile.markdown) { card.hidden = true; return; }
  document.getElementById("profile-updated").textContent = profile.updated || "";
  document.getElementById("profile-body").innerHTML = mdToHtml(profile.markdown);
  card.hidden = false;
}

// ── orchestration ────────────────────────────────────────────────────────────
async function load() {
  const meta = document.getElementById("meta");
  meta.textContent = "loading…";
  let data;
  try {
    data = await (await fetch(`/api/data?hours=${state.hours}`)).json();
  } catch (e) {
    meta.textContent = "failed to reach server";
    return;
  }

  // GPU allocation over time
  const H = data.historical;
  const gpuTypes = Object.keys(H.series || {}).sort();
  const allocSeries = gpuTypes.map((name, i) => ({
    name, color: seriesColor(i), values: H.series[name],
  }));
  lineChart(document.getElementById("chart-alloc"), H.slots || [], allocSeries, "GPU usage %");
  legend(document.getElementById("legend-alloc"), allocSeries);

  // per-type bars
  barChart(document.getElementById("chart-bytype"), H.by_type || []);

  // heatmap
  heatmap(document.getElementById("chart-heat"), H.heatmap || []);

  // live queue trend
  const live = data.live;
  if (live.available && live.trend.length) {
    const labels = live.trend.map((r) => r.t);
    const qs = [
      { name: "running", color: seriesColor(0), values: live.trend.map((r) => r.running) },
      { name: "pending", color: seriesColor(5), values: live.trend.map((r) => r.pending) },
    ];
    lineChart(document.getElementById("chart-queue"), labels, qs, "jobs");
    legend(document.getElementById("legend-queue"), qs);
  } else {
    document.getElementById("chart-queue").innerHTML = `<div class="empty">No live snapshot yet.</div>`;
  }

  renderKPIs(live);
  renderProfile(data.profile);

  // header + footer meta
  const span = H.span ? `${shortTime(H.span.from)} → ${shortTime(H.span.to)}` : "no history";
  meta.textContent = `${span} · ${(H.span && H.span.count) || 0} hours` +
    (H.freshness_utc ? ` · fresh through ${shortTime(H.freshness_utc)}` : "");
  const s = data.summary || {};
  const prof = data.profile && data.profile.present ? ` · profile ${data.profile.updated || "present"}` : "";
  document.getElementById("footer").innerHTML =
    `Generated ${data.generated_utc} UTC${prof}. Source: sacct history + live queue poller. ` +
    (s.best_submit_hours_utc ? `Best submit hours (UTC): ${s.best_submit_hours_utc.map((h)=>String(h).padStart(2,"0")).join(", ")}.` : "");
}

// ── controls ─────────────────────────────────────────────────────────────────
document.getElementById("window").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-h]");
  if (!b) return;
  document.querySelectorAll("#window button").forEach((x) => x.classList.remove("on"));
  b.classList.add("on");
  state.hours = +b.dataset.h;
  load();
});

const themeBtn = document.getElementById("theme");
function applyTheme(t) {
  if (t) document.documentElement.setAttribute("data-theme", t);
  else document.documentElement.removeAttribute("data-theme");
  localStorage.setItem("unity-monitor-theme", t || "");
}
themeBtn.addEventListener("click", () => {
  const cur = document.documentElement.getAttribute("data-theme");
  const isDark = cur === "dark" ||
    (!cur && matchMedia("(prefers-color-scheme: dark)").matches);
  applyTheme(isDark ? "light" : "dark");
  load(); // re-read themed CSS colors into the SVGs
});
applyTheme(localStorage.getItem("unity-monitor-theme") || "");

load();
setInterval(load, 60000); // refresh every minute
