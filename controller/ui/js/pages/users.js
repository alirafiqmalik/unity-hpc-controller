/** Users: people on the cluster and their usage, plus this account's fairshare. */

import { esc, fmtHours } from '../format.js';
import { state } from '../state.js';
import { toast } from '../toast.js';

export function render() {
  const cl = state.cluster || {};
  const fs = cl.fairshare || {};
  const people = cl.users || {};
  const rows = people.available ? (people.rows || []) : [];
  const hours = rows.reduce((a, r) => a + (Number(r.hours) || 0), 0);
  document.getElementById('uHours').textContent = rows.length
    ? String(rows.length)
    : '—';
  document.getElementById('uHoursD').textContent = rows.length
    ? 'accounts in the job history'
    : 'no user history in the archive';
  document.getElementById('uWait').textContent = hours ? fmtHours(hours) : '—';
  document.getElementById('uWaitD').textContent = hours
    ? 'elapsed across those accounts'
    : 'no elapsed time in the job history';
  if (fs.available && fs.factor != null) {
    const pct = Math.round(Number(fs.factor) * 100);
    const used = fs.effective_usage != null ? Math.round(Number(fs.effective_usage) * 100) : null;
    document.getElementById('uRank').textContent = Number.isFinite(pct) ? pct + '%' : '—';
    document.getElementById('uRankD').textContent = used != null
      ? 'fairshare factor · usage ' + used + '%'
      : 'fairshare factor';
  } else {
    document.getElementById('uRank').textContent = '—';
    document.getElementById('uRankD').textContent = 'not in the cluster profile';
  }
  const account = (fs.account && !String(fs.account).includes('${')) ? fs.account : '';
  document.getElementById('userSub').textContent = rows.length
    ? (rows.length.toLocaleString() + ' people · job history')
    : (fs.available
      ? ((account || 'this account') + ' · waiting on user history')
      : 'no user history in the archive');
  if (rows.length) {
    const peak = Math.max(...rows.map(r => Number(r.hours) || 0), 1);
    document.getElementById('userRows').innerHTML = rows.map((r, i) => {
      const pct = Math.round((Number(r.hours) || 0) / peak * 100);
      const cls = pct > 80 ? 'hot' : pct > 60 ? 'warn' : '';
      return `<tr><td>${i + 1}</td><td><b>${esc(r.user)}</b></td><td style="color:var(--muted)">${esc(r.account || '—')}</td><td class="mono">${esc((r.jobs || 0).toLocaleString())}</td><td class="mono">${esc(fmtHours(r.hours))}</td>
        <td><div class="bar-row"><div class="bar ${cls}" style="flex:1"><i style="width:${pct}%"></i></div><span class="pct">${esc(fmtHours(r.gpu_hours))}</span></div></td></tr>`;
    }).join('');
  } else {
    document.getElementById('userRows').innerHTML = `<tr><td colspan="6" class="empty" style="cursor:default">No cluster users in the job history</td></tr>`;
  }
}

/** Download the rendered user table. Bound from an inline handler. */
export function exportUsers() {
  const rows = [...document.querySelectorAll('#userRows tr')].map(tr => [...tr.children].map(td => td.innerText.replace(/\s+/g, ' ').trim()).join(','));
  const csv = ['#,User,Account,Jobs,Hours,GPU-hrs', ...rows].join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'users.csv';
  a.click();
  toast('Exported users.csv');
}
