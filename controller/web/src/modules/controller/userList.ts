/**
 * Sort and search for the cluster users list.
 *
 * A heading click adds that column ascending, the next click flips it to
 * descending, and the click after that drops it. Earlier columns stay ahead
 * of later ones, so the click order is the sort order.
 */

import type { ClusterUser } from './types';

export type SortDir = 'asc' | 'desc';

export type UserSortKey =
  | 'user'
  | 'account'
  | 'jobs'
  | 'running'
  | 'pending'
  | 'completed'
  | 'failed'
  | 'timeout'
  | 'oom'
  | 'preempted'
  | 'cancelled'
  | 'success_pct'
  | 'avg_wait_s'
  | 'hours'
  | 'gpu_jobs'
  | 'gpu_hours'
  | 'cpu_hours'
  | 'node_hours'
  | 'mem_gb_hours'
  | 'avg_cpus'
  | 'avg_gpus'
  | 'last_seen'
  | 'partition';

export type UserSort = { key: UserSortKey; dir: SortDir };

export type UserColumn = {
  key: UserSortKey;
  label: string;
  title: string;
  align: 'left' | 'right';
  /** Fixed track. The partition column is left unset so it can use the remainder. */
  width?: number;
};

export const INDEX_WIDTH = 36;

export const USER_COLUMNS: UserColumn[] = [
  { key: 'user', label: 'User', title: 'Cluster user', align: 'left', width: 120 },
  {
    key: 'account',
    label: 'Account',
    title: 'Account with the most jobs. A badge counts the other accounts.',
    align: 'left',
    width: 112,
  },
  { key: 'jobs', label: 'Jobs', title: 'Jobs in this window', align: 'right', width: 64 },
  {
    key: 'running',
    label: 'Run',
    title: 'Jobs still running',
    align: 'right',
    width: 58,
  },
  {
    key: 'pending',
    label: 'Queue',
    title: 'Jobs still pending',
    align: 'right',
    width: 68,
  },
  {
    key: 'hours',
    label: 'Hours',
    title: 'Sum of wall-clock elapsed time',
    align: 'right',
    width: 68,
  },
  {
    key: 'gpu_jobs',
    label: 'GPU',
    title: 'Jobs that allocated at least one GPU',
    align: 'right',
    width: 58,
  },
  {
    key: 'gpu_hours',
    label: 'GPU h',
    title: 'GPUs allocated × elapsed hours',
    align: 'right',
    width: 68,
  },
  {
    key: 'cpu_hours',
    label: 'CPU h',
    title: 'CPUs allocated × elapsed hours',
    align: 'right',
    width: 68,
  },
  {
    key: 'completed',
    label: 'Done',
    title: 'Jobs that reached COMPLETED',
    align: 'right',
    width: 62,
  },
  {
    key: 'failed',
    label: 'Fail',
    title: 'FAILED, NODE_FAIL, BOOT_FAIL, DEADLINE, or REVOKED',
    align: 'right',
    width: 58,
  },
  {
    key: 'success_pct',
    label: 'Success',
    title: 'Completed jobs as a share of settled jobs',
    align: 'right',
    width: 84,
  },
  {
    key: 'avg_wait_s',
    label: 'Wait',
    title: 'Mean time from submit to start',
    align: 'right',
    width: 64,
  },
  {
    key: 'timeout',
    label: 'Limit',
    title: 'Jobs that hit the time limit',
    align: 'right',
    width: 64,
  },
  {
    key: 'oom',
    label: 'OOM',
    title: 'Jobs that ran out of memory',
    align: 'right',
    width: 58,
  },
  {
    key: 'preempted',
    label: 'Preempt',
    title: 'Jobs preempted by a higher-priority job',
    align: 'right',
    width: 84,
  },
  {
    key: 'cancelled',
    label: 'Cancel',
    title: 'Cancelled jobs, including cancellation by another user',
    align: 'right',
    width: 72,
  },
  {
    key: 'node_hours',
    label: 'Node h',
    title: 'Nodes allocated × elapsed hours',
    align: 'right',
    width: 74,
  },
  {
    key: 'mem_gb_hours',
    label: 'Mem h',
    title: 'Allocated memory × elapsed time, in GB-hours',
    align: 'right',
    width: 68,
  },
  {
    key: 'avg_cpus',
    label: 'CPUs',
    title: 'Mean CPUs held over elapsed hours',
    align: 'right',
    width: 62,
  },
  {
    key: 'avg_gpus',
    label: 'GPUs',
    title: 'Mean GPUs held on jobs that allocated a GPU',
    align: 'right',
    width: 62,
  },
  {
    key: 'last_seen',
    label: 'Last',
    title: 'Newest end, else start, else submit',
    align: 'right',
    width: 72,
  },
  {
    key: 'partition',
    label: 'Partition',
    title: 'Partition with the most jobs, and the most common GPU type',
    align: 'left',
    width: 156,
  },
];

const FIXED_WIDTH = USER_COLUMNS.reduce((sum, column) => sum + (column.width ?? 0), 0);

/** The table's packed width: index column plus every fixed track. */
export const USER_TABLE_WIDTH = INDEX_WIDTH + FIXED_WIDTH;

export const cycleSort = (current: UserSort[], key: UserSortKey): UserSort[] => {
  const index = current.findIndex((item) => item.key === key);
  if (index < 0) return [...current, { key, dir: 'asc' }];
  if (current[index].dir === 'asc') {
    return current.map((item, itemIndex) =>
      itemIndex === index ? { key, dir: 'desc' } : item,
    );
  }
  return current.filter((item) => item.key !== key);
};

export const sortHint = (column: UserColumn, sorts: UserSort[]): string => {
  const current = sorts.find((item) => item.key === column.key);
  if (!current) return `Sort by ${column.label}, ascending`;
  if (current.dir === 'asc') return `${column.label} is ascending. Click for descending.`;
  return `${column.label} is descending. Click to remove it from the sort.`;
};

export const sortSummary = (sorts: UserSort[]): string =>
  sorts
    .map((item) => {
      const column = USER_COLUMNS.find((candidate) => candidate.key === item.key);
      return `${column?.label ?? item.key} ${item.dir === 'asc' ? '↑' : '↓'}`;
    })
    .join(', then ');

const listedNames = (values: string[] | undefined, primary?: string): string[] => {
  const listed = (values ?? []).map((item) => item.trim()).filter(Boolean);
  if (listed.length) return listed;
  const fallback = (primary ?? '').trim();
  return fallback ? [fallback] : [];
};

export const accountsOf = (row: ClusterUser): string[] => listedNames(row.accounts, row.account);

export const partitionsOf = (row: ClusterUser): string[] =>
  listedNames(row.partitions, row.partition);

/** Letters and digits only, so `alice@umass.edu` can meet `alice_umass_edu`. */
const fold = (value: string): string => value.toLowerCase().replace(/[^a-z0-9]+/g, '');

/** Each word, or each piece of a word split on punctuation, must match somewhere. */
export const searchPieces = (query: string): string[] =>
  query
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((piece) => piece.length > 0);

/** The account to show while searching: one that contains the query, else the primary. */
export const matchingAccount = (row: ClusterUser, query: string): string => {
  const accounts = accountsOf(row);
  const pieces = searchPieces(query);
  if (!pieces.length || !accounts.length) return accounts[0] ?? '';
  const contains = (item: string, piece: string) =>
    item.toLowerCase().includes(piece) || fold(item).includes(piece);
  return (
    accounts.find((item) => pieces.every((piece) => contains(item, piece))) ??
    accounts.find((item) => pieces.some((piece) => contains(item, piece))) ??
    accounts[0] ??
    ''
  );
};

export const rowMatches = (row: ClusterUser, query: string): boolean => {
  const pieces = searchPieces(query);
  if (!pieces.length) return true;
  const user = row.user.toLowerCase();
  const userFold = fold(row.user);
  const accounts = accountsOf(row);
  const raw = accounts.map((item) => item.toLowerCase());
  const folded = accounts.map(fold);
  return pieces.every(
    (piece) =>
      user.includes(piece) ||
      userFold.includes(piece) ||
      raw.some((item) => item.includes(piece)) ||
      folded.some((item) => item.includes(piece)),
  );
};

export type TextPart = { text: string; hit: boolean };

/**
 * Split `text` around the query pieces so the match can be marked.
 *
 * A piece also matches through punctuation, so `pilab` marks `pi_lab`.
 */
export const highlightParts = (text: string, query: string): TextPart[] => {
  const pieces = searchPieces(query).sort((a, b) => b.length - a.length);
  if (!text || !pieces.length) return [{ text, hit: false }];
  const lower = text.toLowerCase();
  const marks = new Array<boolean>(text.length).fill(false);
  const foldedAt: number[] = [];
  let folded = '';
  for (let index = 0; index < text.length; index += 1) {
    const char = lower[index];
    if ((char >= 'a' && char <= 'z') || (char >= '0' && char <= '9')) {
      folded += char;
      foldedAt.push(index);
    }
  }
  const markSpan = (start: number, length: number) => {
    for (let index = start; index < start + length && index < marks.length; index += 1) {
      marks[index] = true;
    }
  };
  for (const piece of pieces) {
    let from = 0;
    while (from < lower.length) {
      const at = lower.indexOf(piece, from);
      if (at < 0) break;
      markSpan(at, piece.length);
      from = at + piece.length;
    }
    from = 0;
    while (from < folded.length) {
      const at = folded.indexOf(piece, from);
      if (at < 0) break;
      const start = foldedAt[at];
      const end = foldedAt[at + piece.length - 1];
      if (start !== undefined && end !== undefined) markSpan(start, end - start + 1);
      from = at + piece.length;
    }
  }
  const parts: TextPart[] = [];
  let index = 0;
  while (index < text.length) {
    const hit = marks[index];
    let end = index + 1;
    while (end < text.length && marks[end] === hit) end += 1;
    parts.push({ text: text.slice(index, end), hit });
    index = end;
  }
  return parts.length ? parts : [{ text, hit: false }];
};

const textValue = (row: ClusterUser, key: UserSortKey): string => {
  if (key === 'user') return row.user;
  if (key === 'account') return accountsOf(row)[0] ?? '';
  if (key === 'partition') return partitionsOf(row)[0] ?? '';
  if (key === 'last_seen') return row.last_seen ?? '';
  return '';
};

const numberValue = (row: ClusterUser, key: UserSortKey): number | null => {
  const raw: Partial<Record<UserSortKey, number | null | undefined>> = {
    jobs: row.jobs,
    running: row.running,
    pending: row.pending,
    completed: row.completed,
    failed: row.failed,
    timeout: row.timeout,
    oom: row.oom,
    preempted: row.preempted,
    cancelled: row.cancelled,
    success_pct: row.success_pct,
    avg_wait_s: row.avg_wait_s,
    hours: row.hours,
    gpu_jobs: row.gpu_jobs,
    gpu_hours: row.gpu_hours,
    cpu_hours: row.cpu_hours,
    node_hours: row.node_hours,
    mem_gb_hours: row.mem_gb_hours,
    avg_cpus: row.avg_cpus,
    avg_gpus: row.avg_gpus,
  };
  const value = raw[key];
  if (value === null || value === undefined) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
};

const TEXT_KEYS = new Set<UserSortKey>(['user', 'account', 'partition', 'last_seen']);

/** Missing numbers and blank text stay at the bottom in either direction. */
export const compareUsers = (a: ClusterUser, b: ClusterUser, sorts: UserSort[]): number => {
  for (const sort of sorts) {
    if (!TEXT_KEYS.has(sort.key)) {
      const left = numberValue(a, sort.key);
      const right = numberValue(b, sort.key);
      if (left === null || right === null) {
        if (left === right) continue;
        return left === null ? 1 : -1;
      }
      if (left !== right) return sort.dir === 'asc' ? left - right : right - left;
      continue;
    }
    const left = textValue(a, sort.key);
    const right = textValue(b, sort.key);
    if (!left || !right) {
      if (left === right) continue;
      return left ? -1 : 1;
    }
    const diff = left.localeCompare(right, undefined, { numeric: true, sensitivity: 'base' });
    if (diff !== 0) return sort.dir === 'asc' ? diff : -diff;
  }
  return a.user.localeCompare(b.user, undefined, { sensitivity: 'base' });
};

export const csvCell = (value: unknown): string => {
  const text = value === null || value === undefined ? '' : String(value);
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
};
