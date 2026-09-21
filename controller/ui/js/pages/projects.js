/** Projects: one card per attached directory, plus the register form. */

import { api } from '../api.js';
import { refresh } from '../bus.js';
import { FAIL_STATES } from '../config.js';
import { esc, jobCount, jq } from '../format.js';
import { state } from '../state.js';
import { toast } from '../toast.js';

export function render() {
  const box = document.getElementById('projCards');
  if (!state.projects.length) {
    box.innerHTML = `<div class="card" style="grid-column:1/-1"><div class="empty">No attached projects. Use /unity-hpc:connect in a coding agent, or register a path below.</div></div>`;
    return;
  }
  box.innerHTML = state.projects.map(p => {
    const c = p.job_counts || {};
    const run = jobCount(c, ['RUNNING']);
    const pend = jobCount(c, ['PENDING']);
    const done = jobCount(c, ['COMPLETED']);
    const fail = jobCount(c, FAIL_STATES);
    return `<div class="card proj-card" onclick='openProject(${jq(p.slug)})'>
      <div style="display:flex;justify-content:space-between;align-items:start;gap:8px">
        <div><div class="lbl">${esc(p.primitive || 'project')}</div>
          <div style="font-size:16px;font-weight:650;margin-top:4px">${esc(p.slug)}</div></div>
        <span class="pill ${run ? 'run' : pend ? 'pend' : 'grey'}"><span class="d"></span>${run ? 'running' : pend ? 'queued' : 'idle'}</span>
      </div>
      <div class="proj-path">${esc(p.path || '')}</div>
      <div class="proj-meta">
        <span class="pill run">${run} running</span>
        <span class="pill pend">${pend} pending</span>
        <span class="pill done">${done} done</span>
        <span class="pill fail">${fail} failed</span>
      </div>
    </div>`;
  }).join('');
}

/** Register a path on this machine. Bound from an inline handler. */
export async function attachProject() {
  const path = document.getElementById('attachPath').value.trim();
  const slug = document.getElementById('attachSlug').value.trim();
  const primitive = document.getElementById('attachPrim').value;
  if (!path) { toast('path is required'); return; }
  const body = { path, primitive };
  if (slug) body.slug = slug;
  try {
    const r = await api('/api/v1/projects', { method: 'POST', body: JSON.stringify(body) });
    toast('Attached ' + (r.project && r.project.slug || slug || path));
    document.getElementById('attachPath').value = '';
    document.getElementById('attachSlug').value = '';
    await refresh();
  } catch (e) { toast(String(e.message || e)); }
}
