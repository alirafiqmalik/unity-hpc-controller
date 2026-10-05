/**
 * The router.
 *
 * Every path here comes from `modules/navigation/routes.ts`, which the drawer
 * reads too, so the two cannot drift. `/` redirects to the default page, and
 * an unknown path lands there as well — the controller serves `index.html` for
 * any non-API GET, so a deep link works on a cold load.
 */

import { Navigate, Route, Routes, useParams } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { useRecoilValue } from 'recoil';

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
import { WorkflowRunnerPage } from './modules/runner/WorkflowRunnerPage';
import { ExecutionPage, ExecutionsPage } from './modules/runner/ExecutionPages';
import { DocumentPage } from './modules/runner/DocumentPage';
import { runnerRequest } from './modules/runner/api';
import { Workspace, ExperimentLibrary, ExperimentRevision, ProjectEntry } from './modules/workspace/Workspace';
import { OverviewPage } from './modules/workspace/OverviewPage';
import { SettingsPage } from './modules/workspace/SettingsPage';
import { FilesPage, ResultsPage } from './modules/workspace/ArtifactPages';
import { ExperimentEditor } from './modules/workspace/ExperimentEditor';
import { PlanReview } from './modules/workspace/ExecutionPages';
import { ProjectRuns } from './modules/workspace/RunsPage';
import { GenAIWorkspace } from './modules/genai/GenAIWorkspace';
import { SessionsPage, TracesPage } from './modules/genai/ObservabilityPages';
import { DatasetDetailPage, DatasetsPage } from './modules/genai/DatasetPages';
import { EvaluationDetailPage, EvaluationsPage } from './modules/genai/EvaluationPages';
import { AgentVersionsPage, PromptsPage } from './modules/genai/VersionPages';
import { lastSyncState, projectsState } from './modules/controller/state';
import { DEFAULT_ROUTE, GENAI_APPLICATION } from './modules/navigation/routes';

/**
 * Where `/projects/:slug` lands. An LLMs & Agents project opens on its traces,
 * while other projects open setup first and execution history afterward.
 * Until the first sync names the project, nothing is drawn, so the redirect
 * never guesses.
 */
const WorkspaceIndex = () => {
  const { slug = '' } = useParams();
  const projects = useRecoilValue(projectsState);
  const synced = useRecoilValue(lastSyncState);
  const project = projects.find((one) => one.slug === slug);
  const application = project?.application;
  const ready = Boolean(synced || project);
  const [destination, setDestination] = useState<{ slug: string; path: string } | null>(null);
  useEffect(() => {
    if (!ready || application === GENAI_APPLICATION) return;
    let active = true;
    setDestination(null);
    void runnerRequest<{ total: number }>(slug, 'executions?limit=1').then((result) => {
      if (active) setDestination({ slug, path: result.total > 0 ? 'executions' : 'runner' });
    }).catch(() => {
      if (active) setDestination({ slug, path: 'runner' });
    });
    return () => { active = false; };
  }, [slug, application, ready]);
  if (!synced && !project) return null;
  if (project?.application === GENAI_APPLICATION) return <Navigate to="traces" replace />;
  if (destination?.slug !== slug) return <p role="status">Opening project…</p>;
  return <Navigate to={destination.path} replace />;
};

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

      <Route path="/projects/:slug">
        <Route index element={<WorkspaceIndex />} />
        <Route path="runner" element={<WorkflowRunnerPage />} />
        <Route path="executions" element={<ExecutionsPage />} />
        <Route path="executions/:executionId" element={<ExecutionPage />} />
        <Route path="docs" element={<DocumentPage />} />

        <Route element={<Workspace />}>
          <Route path="research" element={<ProjectEntry />} />
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

        {/* The LLMs & Agents evaluation workspace. Paths match GENAI_SECTIONS. */}
        <Route element={<GenAIWorkspace />}>
          <Route path="traces" element={<TracesPage />} />
          <Route path="sessions" element={<SessionsPage />} />
          <Route path="datasets" element={<DatasetsPage />} />
          <Route path="datasets/:datasetId" element={<DatasetDetailPage />} />
          <Route path="evaluations" element={<EvaluationsPage />} />
          <Route path="evaluations/:evaluationId" element={<EvaluationDetailPage />} />
          <Route path="prompts" element={<PromptsPage />} />
          <Route path="agent-versions" element={<AgentVersionsPage />} />
        </Route>
        <Route path="*" element={<WorkspaceIndex />} />
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
