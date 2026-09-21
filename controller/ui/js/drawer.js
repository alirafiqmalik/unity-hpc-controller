/**
 * The right-hand drawer: one job, or one project with its controls.
 *
 * Every export here is reachable from an inline handler, so main.js puts them
 * on `window`. See the bridge comment there.
 */

import { api } from './api.js';
import { refresh } from './bus.js';
import { PRIMITIVES } from './config.js';
import { esc, exitOf, fmtElapsed, jq, pillFor } from './format.js';
import { state } from './state.js';
import { toast } from './toast.js';

function open() {
  document.getElementById('ovl').classList.add('on');
  document.getElementById('drawer').classList.add('open');
}

/** Show one job from the current snapshot. */
export function openJob(id) {
  const j = state.jobs.find(x => String(x.job_id) === String(id));
  if (!j) { toast('Job not in current snapshot'); return; }
  const [pill, lbl] = pillFor(j.status);
  document.getElementById('drawer').innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:start">
      <div><h2 class="mono">${esc(j.exp || j.job_id)}</h2><div class="hint">#${esc(j.job_id)} · ${esc(j.slug)} / ${esc(j.campaign || '')}</div></div>
      <button class="icon-btn" onclick="closeDrawer()">&#10005;</button></div>
    <div class="section-gap"><span class="pill ${pill}"><span class="d"></span>${esc(lbl)}</span> <span class="pill grey">${esc(j.partition || '—')}</span> <span class="pill grey mono">${esc(j.hardware || '—')}</span></div>
    <div class="card section-gap"><h3>Metrics</h3>
      <div class="hint">No training metrics in the job ledger.</div></div>
    <div class="card section-gap"><h3>Detail</h3>
      <div class="kv"><span>Runtime</span><b class="mono">${esc(fmtElapsed(j.elapsed_s))}</b></div>
      <div class="kv"><span>Exit code</span><b class="mono">${esc(exitOf(j))}</b></div>
      <div class="kv"><span>Attempt</span><b class="mono">${esc(j.attempt ?? '—')}</b></div>
      <div class="kv"><span>Submitted</span><b class="mono">${esc(j.submitted_utc || '—')}</b></div>
      <div class="kv"><span>Updated</span><b class="mono">${esc(j.updated_utc || '—')}</b></div></div>
    <div class="section-gap" style="display:flex;gap:9px;margin-bottom:10px">
      <button class="btn sm" onclick='projectPost(${jq(j.slug)},"stop",{job:${jq(j.job_id)}})'>Cancel</button>
      <button class="btn sm" onclick='projectPost(${jq(j.slug)},"fetch",{})'>Fetch results</button>
      <button class="btn sm ghost" onclick='openProject(${jq(j.slug)})'>Open project</button>
    </div>`;
  open();
  state.drawerSlug = null;
}

/** Show one project: configure, run, control, monitor, detach. */
export async function openProject(slug) {
  try {
    const data = await api('/api/v1/projects/' + encodeURIComponent(slug));
    const p = data.project || data;
    state.drawerSlug = slug;
    const primOpts = PRIMITIVES.map(t => `<option value="${t}" ${p.primitive === t ? 'selected' : ''}>${t}</option>`).join('');
    const jobs = p.jobs || [];
    const jobRows = jobs.length ? jobs.map(j => {
      const [pill, lbl] = pillFor(j.status);
      return `<tr onclick='openJob(${jq(j.job_id)})'><td class="mono">${esc(j.job_id)}</td><td class="mono">${esc(j.exp)}</td><td><span class="pill ${pill}"><span class="d"></span>${esc(lbl)}</span></td><td>${esc(j.partition || '—')}</td></tr>`;
    }).join('') : `<tr><td colspan="4" class="empty" style="cursor:default">No jobs yet</td></tr>`;
    document.getElementById('drawer').innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:start">
        <div><h2 class="mono">${esc(p.slug)}</h2><div class="hint">${esc(p.path || '')}</div></div>
        <button class="icon-btn" onclick="closeDrawer()">&#10005;</button></div>
      <div class="section-gap"><span class="pill violet">${esc(p.primitive || '—')}</span>
        <span class="pill ${p.scaffold ? 'run' : 'grey'}">${p.scaffold ? 'scaffold ready' : 'no scaffold'}</span></div>

      <div class="card section-gap"><h3>Configure</h3>
        <div class="f-row">
          <div><label>Primitive</label><select id="cfgPrim">${primOpts}</select></div>
          <div><label>Campaign</label><input id="cfgCamp" value="${esc(p.campaign || '')}"></div>
        </div>
        <label>Remote work dir</label><input id="cfgRemote" value="${esc(p.remote_dir || '')}">
        <label>Unity host</label><input id="cfgHost" value="${esc(p.unity_host || 'unity')}">
        <div class="actions"><button class="btn primary sm" onclick='patchProject(${jq(p.slug)})'>Save</button></div>
      </div>

      <div class="card section-gap"><h3>Run</h3>
        <div class="f-row">
          <div><label>Exp</label><input id="runExp" placeholder="smoke"></div>
          <div><label>Campaign</label><input id="runCamp" placeholder="optional"></div>
        </div>
        <div class="f-row3">
          <div><label>Partition</label><input id="runPart" placeholder="optional"></div>
          <div><label>Walltime</label><input id="runWall" placeholder="optional"></div>
          <div><label>Command</label><input id="runCmd" placeholder="optional"></div>
        </div>
        <label class="check"><input type="checkbox" id="runDry"> dry-run</label>
        <div class="actions"><button class="btn primary sm" onclick='runProject(${jq(p.slug)})'>&#9654; Dispatch</button></div>
      </div>

      <div class="card section-gap"><h3>Control</h3>
        <div class="actions">
          <button class="btn sm" onclick='projectPost(${jq(p.slug)},"stop",{})'>Stop</button>
          <button class="btn sm" onclick='projectPost(${jq(p.slug)},"fetch",{})'>Fetch</button>
          <button class="btn sm" onclick='projectPost(${jq(p.slug)},"sync",{})'>Sync</button>
        </div>
      </div>

      <div class="card section-gap"><h3>Monitor</h3>
        <table><thead><tr><th>Job</th><th>Exp</th><th>Status</th><th>Partition</th></tr></thead>
        <tbody>${jobRows}</tbody></table>
      </div>

      <div class="actions">
        <button class="btn sm danger" onclick='detachProject(${jq(p.slug)})'>Detach</button>
      </div>`;
    open();
  } catch (e) { toast(String(e.message || e)); }
}

/** Save the Configure block. */
export async function patchProject(slug) {
  const body = {
    primitive: document.getElementById('cfgPrim').value,
    remote_dir: document.getElementById('cfgRemote').value.trim(),
    unity_host: document.getElementById('cfgHost').value.trim(),
    campaign: document.getElementById('cfgCamp').value.trim(),
  };
  try {
    await api('/api/v1/projects/' + encodeURIComponent(slug), { method: 'PATCH', body: JSON.stringify(body) });
    toast('Updated ' + slug);
    await refresh();
    openProject(slug);
  } catch (e) { toast(String(e.message || e)); }
}

/** Dispatch the Run block. */
export async function runProject(slug) {
  const exp = document.getElementById('runExp').value.trim();
  if (!exp) { toast('exp is required'); return; }
  const body = { exp, dry_run: document.getElementById('runDry').checked };
  const camp = document.getElementById('runCamp').value.trim();
  if (camp) body.campaign = camp;
  const ov = {};
  const cmd = document.getElementById('runCmd').value.trim();
  const wall = document.getElementById('runWall').value.trim();
  const part = document.getElementById('runPart').value.trim();
  if (cmd) ov.JOB_COMMAND = cmd;
  if (wall) ov.WALLTIME = wall;
  if (part) ov.SLURM_PARTITION = part;
  if (Object.keys(ov).length) body.overrides = ov;
  try {
    const r = await api('/api/v1/projects/' + encodeURIComponent(slug) + '/runs', { method: 'POST', body: JSON.stringify(body) });
    toast((r.ok === false ? 'Failed: ' : 'Ran: ') + String(r.output || r.error || 'ok').slice(0, 180));
    await refresh();
    openProject(slug);
  } catch (e) { toast(String(e.message || e)); }
}

/** POST one of the project sub-routes: stop, fetch, sync. */
export async function projectPost(slug, rest, body) {
  try {
    const r = await api('/api/v1/projects/' + encodeURIComponent(slug) + '/' + rest, { method: 'POST', body: JSON.stringify(body || {}) });
    toast((r.ok === false ? 'Failed: ' : 'ok: ') + String(r.output || r.error || rest).slice(0, 180));
    await refresh();
    if (state.drawerSlug === slug) openProject(slug);
  } catch (e) { toast(String(e.message || e)); }
}

/** Detach a project after the operator confirms. */
export async function detachProject(slug) {
  if (!confirm('Detach ' + slug + ' from the controller?')) return;
  try {
    await api('/api/v1/projects/' + encodeURIComponent(slug), { method: 'DELETE' });
    toast('Detached ' + slug);
    closeDrawer();
    await refresh();
  } catch (e) { toast(String(e.message || e)); }
}

/** Close the drawer and drop the slug it was bound to. */
export function closeDrawer() {
  document.getElementById('ovl').classList.remove('on');
  document.getElementById('drawer').classList.remove('open');
  state.drawerSlug = null;
}
