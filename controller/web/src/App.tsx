/**
 * The router.
 *
 * Every path here comes from `modules/navigation/routes.ts`, which the drawer
 * reads too, so the two cannot drift. `/` redirects to the default page, and
 * an unknown path lands there as well — the controller serves `index.html` for
 * any non-API GET, so a deep link works on a cold load.
 */

import { Navigate, Route, Routes } from 'react-router-dom';

import { TelemetryProvider } from './modules/telemetry/TelemetryProvider';
import { ClusterAnalyticsPage } from './pages/ClusterAnalyticsPage';
import { ClusterOverviewPage } from './pages/ClusterOverviewPage';
import { ClusterQueuePage } from './pages/ClusterQueuePage';
import { ClusterUsersPage } from './pages/ClusterUsersPage';
import { JobsDispatchPage } from './pages/JobsDispatchPage';
import { JobsMonitorPage } from './pages/JobsMonitorPage';
import { JobsProjectPage } from './pages/JobsProjectPage';
import { SettingsConfigPage } from './pages/SettingsConfigPage';
import { SettingsLogsPage } from './pages/SettingsLogsPage';
import { SettingsScheduledPage } from './pages/SettingsScheduledPage';
import { AppLayout } from './ui/layout/AppLayout';
import { Workspace, ExperimentLibrary, ExperimentRevision } from './modules/workspace/Workspace';
import { OverviewPage } from './modules/workspace/OverviewPage';
import { SettingsPage } from './modules/workspace/SettingsPage';
import { FilesPage, ResultsPage } from './modules/workspace/ArtifactPages';
import { ExperimentEditor } from './modules/workspace/ExperimentEditor';
import { PlanReview } from './modules/workspace/ExecutionPages';
import { ProjectRuns } from './modules/workspace/RunsPage';
import { DEFAULT_ROUTE } from './modules/navigation/routes';

export const App = () => (
  <Routes>
    <Route element={<AppLayout />}>
      <Route path="/" element={<Navigate to={DEFAULT_ROUTE} replace />} />

      <Route path="/cluster/overview" element={<ClusterOverviewPage />} />
      <Route path="/cluster/queue" element={<ClusterQueuePage />} />
      <Route path="/cluster/users" element={<ClusterUsersPage />} />
      <Route path="/cluster/analytics" element={<ClusterAnalyticsPage />} />

      <Route path="/jobs/monitor" element={<JobsMonitorPage />} />
      <Route path="/jobs/project" element={<JobsProjectPage />} />
      <Route path="/jobs/dispatch" element={<JobsDispatchPage />} />

      <Route path="/projects/:slug" element={<Workspace />}>
        <Route index element={<Navigate to="overview" replace />} />
        <Route path="overview" element={<OverviewPage />} />
        <Route path="experiments" element={<ExperimentLibrary />} />
        <Route path="experiments/:experimentId" element={<ExperimentEditor />} />
        <Route path="experiments/:experimentId/revisions/:revision" element={<ExperimentRevision />} />
        <Route path="review/:planId" element={<PlanReview />} />
        <Route path="runs" element={<ProjectRuns />} />
        <Route path="results" element={<ResultsPage />} />
        <Route path="files" element={<FilesPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>

      {/* The three Settings pages share one telemetry reader. */}
      <Route path="/settings" element={<TelemetryProvider />}>
        <Route path="config" element={<SettingsConfigPage />} />
        <Route path="scheduled" element={<SettingsScheduledPage />} />
        <Route path="logs" element={<SettingsLogsPage />} />
      </Route>

      <Route path="*" element={<Navigate to={DEFAULT_ROUTE} replace />} />
    </Route>
  </Routes>
);
