/**
 * Entry point. index.html loads this one file as a module.
 *
 * It builds the nav, wires the controls that are not inline handlers, exposes
 * the inline-handler surface on `window`, and starts the refresh cycle.
 */

import { chipSel, go, refresh } from './app.js';
import { drawTrend, drawUsageChart } from './chart.js';
import { TABS } from './config.js';
import { live, state } from './state.js';
import { copyPre } from './toast.js';

import {
  closeDrawer, detachProject, openJob, openProject,
  patchProject, projectPost, runProject,
} from './drawer.js';
import { attachProject } from './pages/projects.js';
import { dispatchRun, onDispProject, renderPreview } from './pages/dispatch.js';
import { render as renderJobs } from './pages/jobs.js';
import { exportUsers } from './pages/users.js';
import {
  closeSshPass, openSshPass, telCloseSession, telRunScript,
  telSaveInterval, telSaveScript, telSaveSource, telSaveSsh,
  telSchedule, telSync, telTestSsh, telUnlockSsh,
} from './pages/settings.js';

/**
 * The inline-handler bridge.
 *
 * index.html and the markup the page modules build use `onclick=` attributes,
 * which resolve against the global scope. A module's top-level binding is not
 * global, so every function an attribute names is listed here. This list is
 * the coupling surface between the markup and the modules: a handler that is
 * not on it fails silently at click time, and tests/test_controller_ui.py
 * checks the two sides against each other.
 */
Object.assign(window, {
  go, refresh, copyPre,
  openJob, openProject, closeDrawer,
  patchProject, runProject, projectPost, detachProject,
  attachProject,
  dispatchRun, onDispProject, renderPreview,
  exportUsers,
  telSync, telSchedule, telSaveInterval, telSaveSource,
  telSaveScript, telSaveSsh, telTestSsh, telRunScript, telCloseSession,
  openSshPass, closeSshPass, telUnlockSsh,
});

const nav = document.getElementById('nav');
nav.innerHTML = TABS.map(t => `<div class="tab" data-t="${t[0]}" onclick="go('${t[0]}')">${t[1]}${t[0] === 'jobs' ? '<span class="badge" id="jobsBadge">0</span>' : ''}</div>`).join('');

document.getElementById('jobChips').innerHTML = '';
['all', 'running', 'pending', 'completed', 'failed'].forEach(f => {
  const c = document.createElement('span');
  c.className = 'chip' + (f === 'all' ? ' on' : '');
  c.textContent = f === 'all' ? 'All' : f[0].toUpperCase() + f.slice(1);
  c.onclick = () => {
    document.getElementById('jobChips').querySelectorAll('.chip').forEach(x => x.classList.remove('on'));
    c.classList.add('on');
    state.jfilter = f;
    renderJobs();
  };
  document.getElementById('jobChips').appendChild(c);
});

document.getElementById('anChips').addEventListener('click', e => {
  const chip = e.target.closest('.chip');
  if (!chip) return;
  chipSel(chip);
  state.hours = Number(chip.dataset.h) || 24;
  refresh();
});

setInterval(() => {
  document.getElementById('clock').textContent = new Date().toTimeString().slice(0, 8);
}, 1000);

window.addEventListener('resize', () => {
  if (state.page === 'overview') drawUsageChart('chartUtil', 'chartUtilLegend', state.usage, ['a100', 'a40', 'preempt']);
  if (state.page === 'queue') drawTrend(((state.queue && state.queue.live) || live()).trend || []);
  if (state.page === 'analytics') drawUsageChart('chartAn', 'chartAnLegend', state.usage, ['a100', 'a40', 'cpu-only']);
});

go('overview');
refresh();
setInterval(() => refresh(), 10000);
