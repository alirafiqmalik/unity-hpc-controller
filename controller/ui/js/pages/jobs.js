/** Jobs: every ledger row across the attached projects, with a state filter. */

import { FAIL_STATES } from '../config.js';
import { esc, exitOf, fmtElapsed, jq, pillFor, stUpper } from '../format.js';
import { state } from '../state.js';

export function render() {
  const rows = state.jobs.filter(j => {
    const u = stUpper(j);
    if (state.jfilter === 'all') return true;
    if (state.jfilter === 'running') return u === 'RUNNING';
    if (state.jfilter === 'pending') return u === 'PENDING';
    if (state.jfilter === 'completed') return u === 'COMPLETED';
    if (state.jfilter === 'failed') return FAIL_STATES.includes(u);
    return true;
  });
  document.getElementById('jobRows').innerHTML = rows.length ? rows.map(j => {
    const [pill, lbl] = pillFor(j.status);
    const liveSt = stUpper(j) !== 'COMPLETED' && !FAIL_STATES.includes(stUpper(j)) && stUpper(j) !== 'CANCELLED';
    const warn = FAIL_STATES.includes(stUpper(j)) ? '<span style="color:var(--fail)">&#9888;</span>' : '';
    return `<tr onclick='openJob(${jq(j.job_id)})'>
      <td>${warn}</td>
      <td class="mono"><b>${esc(j.exp || j.job_id)}</b><br><span style="color:var(--muted);font-size:11px">#${esc(j.job_id)}</span></td>
      <td style="color:var(--ink-2)">${esc(j.slug || '')} / ${esc(j.campaign || '')}</td>
      <td><span class="pill ${pill}"><span class="d"></span>${esc(lbl)}</span></td>
      <td>${esc(j.partition || '—')}</td>
      <td class="mono">${esc(j.hardware || '—')}</td>
      <td class="mono">${esc(fmtElapsed(j.elapsed_s))}</td>
      <td class="mono" style="color:${exitOf(j) === '0' ? 'var(--done)' : exitOf(j) === '—' ? 'var(--muted)' : 'var(--fail)'}">${esc(exitOf(j))}</td>
      <td>${liveSt ? `<button class="btn sm ghost" onclick='event.stopPropagation();projectPost(${jq(j.slug)},"stop",{job:${jq(j.job_id)}})'>Cancel</button>` : ''}</td></tr>`;
  }).join('') : `<tr><td colspan="9" class="empty" style="cursor:default">No jobs match this filter</td></tr>`;
}
