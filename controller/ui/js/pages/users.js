/** Users: fairshare rows from the cluster profile, plus a CSV export. */

import { esc, gpuHours } from '../format.js';
import { state } from '../state.js';
import { toast } from '../toast.js';

export function render() {
  const cl = state.cluster || {};
  const accounts = Array.isArray(cl.accounts) ? cl.accounts : (Array.isArray(cl.users) ? cl.users : []);
  const hrs = gpuHours(state.jobs);
  document.getElementById('uHours').textContent = hrs ? hrs.toFixed(1) : '—';
  document.getElementById('uHoursD').textContent = hrs ? 'summed from job ledgers' : 'no elapsed time in the ledgers';
  document.getElementById('userSub').textContent = accounts.length
    ? (accounts.length + ' accounts · cluster profile')
    : 'fairshare is not in the cluster profile';
  document.getElementById('userRows').innerHTML = accounts.length
    ? accounts.map((u, i) => {
        const name = u.user || u.name || u.id || '—';
        const group = u.group || u.account || '—';
        const active = u.active_jobs != null ? u.active_jobs : '—';
        const gh = u.gpu_hours != null ? u.gpu_hours : '—';
        const share = Number(u.fairshare);
        const pct = Number.isFinite(share) ? Math.round(share) : 0;
        const cls = pct > 80 ? 'hot' : pct > 60 ? 'warn' : '';
        return `<tr><td>${i + 1}</td><td><b>${esc(name)}</b></td><td style="color:var(--muted)">${esc(group)}</td><td class="mono">${esc(active)}</td><td class="mono">${esc(gh)}</td>
          <td><div class="bar-row"><div class="bar ${cls}" style="flex:1"><i style="width:${pct}%"></i></div><span class="pct">${Number.isFinite(share) ? pct + '%' : '—'}</span></div></td></tr>`;
      }).join('')
    : `<tr><td colspan="6" class="empty" style="cursor:default">No user or fairshare rows in the cluster profile</td></tr>`;
}

/** Download the rendered user table. Bound from an inline handler. */
export function exportUsers() {
  const rows = [...document.querySelectorAll('#userRows tr')].map(tr => [...tr.children].map(td => td.innerText.replace(/\s+/g, ' ').trim()).join(','));
  const csv = ['#,User,Group,Active jobs,GPU-hrs,Fairshare', ...rows].join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'users.csv';
  a.click();
  toast('Exported users.csv');
}
