/** Dispatch: build one run request, preview the exact body, post it. */

import { api } from '../api.js';
import { refresh } from '../bus.js';
import { ago, esc } from '../format.js';
import { state } from '../state.js';
import { toast } from '../toast.js';

export function render() {
  const sel = document.getElementById('dispProject');
  const cur = sel.value;
  sel.innerHTML = state.projects.length
    ? state.projects.map(p => `<option value="${esc(p.slug)}">${esc(p.slug)}</option>`).join('')
    : `<option value="">No attached projects</option>`;
  if (cur && [...sel.options].some(o => o.value === cur)) sel.value = cur;
  onDispProject();
  const disp = state.events.filter(e => e.kind === 'dispatch' || e.kind === 'dry-run').slice().reverse();
  document.getElementById('dispList').innerHTML = disp.length
    ? disp.slice(0, 8).map(e => {
        const ok = e.ok !== false;
        return `<div class="feed-item"><span class="pill ${ok ? 'run' : 'fail'}"><span class="d"></span>${ok ? 'ok' : 'fail'}</span><div class="mono">${esc(e.message || e.kind)}</div><div class="t">${esc(ago(e.ts))}</div></div>`;
      }).join('')
    : `<div class="empty">Nothing dispatched yet</div>`;
}

/** Mirror the selected project's primitive into the read-only scaffold box. */
export function onDispProject() {
  const slug = document.getElementById('dispProject').value;
  const p = state.projects.find(x => x.slug === slug);
  const sc = document.getElementById('dispScaffold');
  if (sc) sc.value = p ? (p.primitive || '') : '';
  renderPreview();
}

/** Read the form into the exact body the controller will receive. */
export function dispatchPayload() {
  const slug = document.getElementById('dispProject').value;
  const body = {};
  const exp = document.getElementById('dispExp').value.trim();
  if (exp) body.exp = exp;
  const camp = document.getElementById('dispCampaign').value.trim();
  if (camp) body.campaign = camp;
  const manifest = document.getElementById('dispManifest').value.trim();
  if (manifest) body.manifest = manifest;
  body.dry_run = document.getElementById('dispDry').checked;
  const ov = {};
  const cmd = document.getElementById('dispCmd').value.trim();
  const wall = document.getElementById('dispWall').value.trim();
  const part = document.getElementById('dispPart').value.trim();
  const gpus = document.getElementById('dispGpus').value.trim();
  if (cmd) ov.JOB_COMMAND = cmd;
  if (wall) ov.WALLTIME = wall;
  if (part) ov.SLURM_PARTITION = part;
  if (gpus) ov.SLURM_GPUS = gpus;
  if (Object.keys(ov).length) body.overrides = ov;
  return { slug, body };
}

/** Redraw the request preview. Bound from every field's inline handler. */
export function renderPreview() {
  const { slug, body } = dispatchPayload();
  const path = slug ? `/api/v1/projects/${slug}/runs` : '/api/v1/projects/{slug}/runs';
  document.getElementById('dispatchPrev').innerHTML =
    `<button class="copy-btn" onclick="copyPre(this)">Copy</button><span class="c">POST ${esc(path)}</span>\n${esc(JSON.stringify(body, null, 2))}`;
}

/** Post the run request. `forceDry` overrides the checkbox. */
export async function dispatchRun(forceDry) {
  const { slug, body } = dispatchPayload();
  if (!slug) { toast('Attach a project first'); return; }
  if (!body.exp && !body.manifest) { toast('exp is required'); return; }
  if (forceDry) body.dry_run = true;
  try {
    const r = await api('/api/v1/projects/' + encodeURIComponent(slug) + '/runs', { method: 'POST', body: JSON.stringify(body) });
    toast((r.ok === false ? 'Failed: ' : 'Dispatched: ') + String(r.output || r.error || 'ok').slice(0, 180));
    await refresh();
  } catch (e) { toast(String(e.message || e)); }
}
