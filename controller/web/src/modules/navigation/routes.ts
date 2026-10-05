/**
 * The navigation map. This file is the single source of truth for it.
 *
 * Three sections, eleven pages. The drawer, the router and the document title
 * all read this list, so a page cannot appear in one and be missing from
 * another.
 */

import {
  IconActivityHeartbeat,
  IconAdjustmentsHorizontal,
  IconChartHistogram,
  IconClockHour4,
  IconDatabase,
  IconFileDescription,
  IconFileText,
  IconFlask,
  IconFolders,
  IconLayoutDashboard,
  IconMessages,
  IconRobot,
  IconRocket,
  IconRoute,
  IconServer2,
  IconSettings,
  IconStack2,
  IconUsers,
} from '@tabler/icons-react';
import type { IconComponent } from '../../ui/types';

export type { IconComponent };

export type NavigationItem = {
  path: string;
  label: string;
  /** The `<h1>` of the page, when it is longer than the drawer label. */
  title: string;
  subtitle: string;
  Icon: IconComponent;
};

export type NavigationSection = {
  id: string;
  label: string;
  Icon: IconComponent;
  items: NavigationItem[];
};

export const NAVIGATION: NavigationSection[] = [
  {
    id: 'cluster',
    label: 'Cluster',
    Icon: IconServer2,
    items: [
      {
        path: '/cluster/overview',
        label: 'Overview',
        title: 'Cluster Overview',
        subtitle: 'Capacity, partition load and what the controller has seen',
        Icon: IconLayoutDashboard,
      },
      {
        path: '/cluster/queue',
        label: 'Queue',
        title: 'Queue & Partitions',
        subtitle: 'squeue snapshot — load, pending work and queue depth',
        Icon: IconStack2,
      },
      {
        path: '/cluster/users',
        label: 'Users',
        title: 'Users & Fairshare',
        subtitle: 'Live cluster users in the selected window, and this account’s fairshare',
        Icon: IconUsers,
      },
      {
        path: '/cluster/analytics',
        label: 'Analytics',
        title: 'Usage Analytics',
        subtitle: 'Historical telemetry from the cluster-intel rollups',
        Icon: IconChartHistogram,
      },
    ],
  },
  {
    id: 'jobs',
    label: 'User Jobs',
    Icon: IconRocket,
    items: [
      {
        path: '/jobs/monitor',
        label: 'Monitor',
        title: 'Job Monitor',
        subtitle: 'Every ledger row across the attached projects',
        Icon: IconActivityHeartbeat,
      },
      {
        path: '/jobs/project',
        label: 'Project',
        title: 'Projects',
        subtitle: 'Directories registered with the controller',
        Icon: IconFolders,
      },
      {
        path: '/jobs/dispatch',
        label: 'Dispatch',
        title: 'Dispatch Run',
        subtitle: 'Build one run request and post it to the controller',
        Icon: IconRocket,
      },
    ],
  },
  {
    id: 'settings',
    label: 'Settings',
    Icon: IconSettings,
    items: [
      {
        path: '/settings/config',
        label: 'Config',
        title: 'Configuration',
        subtitle: 'Telemetry source, SSH access and controller facts',
        Icon: IconAdjustmentsHorizontal,
      },
      {
        path: '/settings/scheduled',
        label: 'Scheduled',
        title: 'Scheduled Retrieval',
        subtitle: 'The schedule, the cluster script and the login-node session',
        Icon: IconClockHour4,
      },
      {
        path: '/settings/logs',
        label: 'Logs',
        title: 'Logs & History',
        subtitle: 'Retrieval history, the last output and the controller event log',
        Icon: IconFileDescription,
      },
    ],
  },
];

/** The page the app opens on, and the target of `/`. */
export const DEFAULT_ROUTE = '/cluster/overview';

/** Project sections replace global navigation inside the dedicated workspace. */
export const RUNNER_SECTIONS = [{ path: 'runner', label: 'Workflow runner', Icon: IconRocket }, { path: 'executions', label: 'Executions', Icon: IconActivityHeartbeat }];

/** Research tools retain saved drafts, recovery, schedules, and artifact management. */
export const PROJECT_SECTIONS = ['Overview', 'Experiments', 'Runs', 'Results', 'Files', 'Settings'] as const;

/**
 * The sections of an LLMs & Agents project. They follow MLflow's GenAI view:
 * observability over traces, evaluation over datasets and runs, and the
 * versioned prompts and agents behind them. Paths are relative to
 * `/projects/:slug/`.
 */
export const GENAI_SECTIONS: { id: string; label: string; items: { path: string; label: string; Icon: IconComponent }[] }[] = [
  {
    id: 'observability',
    label: 'Observability',
    items: [
      { path: 'traces', label: 'Traces', Icon: IconRoute },
      { path: 'sessions', label: 'Sessions', Icon: IconMessages },
    ],
  },
  {
    id: 'evaluation',
    label: 'Evaluation',
    items: [
      { path: 'datasets', label: 'Datasets', Icon: IconDatabase },
      { path: 'evaluations', label: 'Evaluation runs', Icon: IconFlask },
    ],
  },
  {
    id: 'versions',
    label: 'Prompts & versions',
    items: [
      { path: 'prompts', label: 'Prompts', Icon: IconFileText },
      { path: 'agent-versions', label: 'Agent versions', Icon: IconRobot },
    ],
  },
];

/** The application id whose projects open in the GenAI workspace. */
export const GENAI_APPLICATION = 'llms-agents';

export const ALL_NAVIGATION_ITEMS: NavigationItem[] = NAVIGATION.flatMap(
  (section) => section.items,
);

export const findNavigationItem = (
  pathname: string,
): NavigationItem | undefined =>
  ALL_NAVIGATION_ITEMS.find((item) => item.path === pathname);
