/** Constants the whole dashboard agrees on. No imports, no state. */

/** Tab order in the nav bar. Each entry is [page id, label]. */
export const TABS = [
  ['overview', 'Overview'],
  ['queue', 'Queue'],
  ['jobs', 'Jobs'],
  ['users', 'Users'],
  ['analytics', 'Analytics'],
  ['dispatch', 'Dispatch'],
  ['projects', 'Projects'],
  ['settings', 'Settings'],
];

/** Series colours, in the order a chart assigns them. */
export const CHART_COLORS = ['#34d399', '#60a5fa', '#a78bfa', '#fbbf24', '#f87171'];

/** Every SLURM state that counts as a failure. */
export const FAIL_STATES = [
  'FAILED', 'TIMEOUT', 'OUT_OF_MEMORY', 'NODE_FAIL',
  'BOOT_FAIL', 'DEADLINE', 'PREEMPTED', 'REVOKED',
];

/** The five primitives. See CONTEXT.md. */
export const PRIMITIVES = ['cpu', 'gpu', 'ml', 'multi-cpu', 'multi-gpu'];
