import apiClient from './client';

export interface Fact {
  id: string;
  description: string;
}

export interface Intent {
  id: string;
  from: string[];
  to: string | null;
  description: string;
  creator: string;
  worker: string | null;
  last_heartbeat_at: string | null;
  created_at: string;
  concluded_at: string | null;
}

export interface Hint {
  id: string;
  content: string;
  creator: string;
  created_at: string;
}

export interface ProjectMeta {
  id: string;
  title: string;
  status: string;
  created_at: string;
  reason: {
    worker: string | null;
    trigger: string | null;
    started_at: string | null;
    last_heartbeat_at: string | null;
  } | null;
}

export interface ProjectSummary {
  id: string;
  title: string;
  status: string;
  created_at: string;
  reason: {
    worker: string | null;
    trigger: string | null;
    started_at: string | null;
    last_heartbeat_at: string | null;
  } | null;
  fact_count: number;
  intent_count: number;
  working_intent_count: number;
  unclaimed_intent_count: number;
  hint_count: number;
}

export interface ProjectDetail {
  project: ProjectMeta;
  facts: Fact[];
  intents: Intent[];
  hints: Hint[];
}

export interface CreateProjectRequest {
  title: string;
  origin: string;
  goal: string;
  hints?: { content: string; creator: string }[];
}

export interface CreateHintRequest {
  content: string;
  creator: string;
}

export interface CreateIntentRequest {
  from_: string[];
  description: string;
  creator: string;
  worker?: string;
}

export interface ConcludeRequest {
  worker: string;
  description: string;
}

export interface ConcludeResponse {
  fact: Fact;
  intent: Intent;
}

export interface CompleteRequest {
  from_: string[];
  description: string;
  worker: string;
}

export interface ReopenRequest {
  description: string;
  creator: string;
}

export interface ReopenResponse {
  project: ProjectMeta;
  fact: Fact;
  intent: Intent;
}

export interface SessionLogEntry {
  id: string;
  project_id: string;
  intent_id: string | null;
  session_id: string;
  phase: string;
  worker: string;
  prompt_preview: string;
  status: string;
  created_at: string;
}

export interface Settings {
  intent_timeout: number;
  reason_timeout: number;
}

async function listProjects(): Promise<ProjectSummary[]> {
  const res = await apiClient.get('/api/cairn/projects');
  return res.data;
}

async function getProject(projectId: string): Promise<ProjectDetail> {
  const res = await apiClient.get(`/api/cairn/projects/${projectId}`);
  return res.data;
}

async function createProject(body: CreateProjectRequest): Promise<ProjectDetail> {
  const res = await apiClient.post('/api/cairn/projects', body);
  return res.data;
}

async function deleteProject(projectId: string): Promise<void> {
  await apiClient.delete(`/api/cairn/projects/${projectId}`);
}

async function updateProjectTitle(projectId: string, title: string): Promise<ProjectMeta> {
  const res = await apiClient.put(`/api/cairn/projects/${projectId}/title`, { title });
  return res.data;
}

async function updateProjectStatus(projectId: string, status: string): Promise<ProjectMeta> {
  const res = await apiClient.put(`/api/cairn/projects/${projectId}/status`, { status });
  return res.data;
}

async function dispatchProject(projectId: string): Promise<void> {
  await apiClient.post(`/api/cairn/projects/${projectId}/dispatch`);
}

async function completeProject(projectId: string, body: CompleteRequest): Promise<Intent> {
  const res = await apiClient.post(`/api/cairn/projects/${projectId}/complete`, body);
  return res.data;
}

async function reopenProject(projectId: string, body: ReopenRequest): Promise<ReopenResponse> {
  const res = await apiClient.post(`/api/cairn/projects/${projectId}/reopen`, body);
  return res.data;
}

async function createHint(projectId: string, body: CreateHintRequest): Promise<Hint> {
  const res = await apiClient.post(`/api/cairn/projects/${projectId}/hints`, body);
  return res.data;
}

async function createIntent(projectId: string, body: CreateIntentRequest): Promise<Intent> {
  const body_ = { ...body, from: body.from_ };
  delete (body_ as any).from_;
  const res = await apiClient.post(`/api/cairn/projects/${projectId}/intents`, body_);
  return res.data;
}

async function concludeIntent(projectId: string, intentId: string, body: ConcludeRequest): Promise<ConcludeResponse> {
  const res = await apiClient.post(`/api/cairn/projects/${projectId}/intents/${intentId}/conclude`, body);
  return res.data;
}

async function heartbeatIntent(projectId: string, intentId: string, body: { worker: string }): Promise<Intent> {
  const res = await apiClient.post(`/api/cairn/projects/${projectId}/intents/${intentId}/heartbeat`, body);
  return res.data;
}

async function releaseIntent(projectId: string, intentId: string, body: { worker: string }): Promise<Intent> {
  const res = await apiClient.post(`/api/cairn/projects/${projectId}/intents/${intentId}/release`, body);
  return res.data;
}

async function getSettings(): Promise<Settings> {
  const res = await apiClient.get('/api/cairn/settings');
  return res.data;
}

async function updateSettings(body: Settings): Promise<Settings> {
  const res = await apiClient.put('/api/cairn/settings', body);
  return res.data;
}

async function getDispatcherStatus(): Promise<{ running: boolean; project_id: string | null }> {
  const res = await apiClient.get('/api/cairn/dispatcher/status');
  return res.data;
}

async function startDispatcher(): Promise<{ status: string }> {
  const res = await apiClient.post('/api/cairn/dispatcher/start');
  return res.data;
}

async function stopDispatcher(): Promise<{ status: string }> {
  const res = await apiClient.post('/api/cairn/dispatcher/stop');
  return res.data;
}

async function exportProject(projectId: string, format: string = 'yaml'): Promise<string> {
  const res = await apiClient.get(`/api/cairn/projects/${projectId}/export`, { params: { format } });
  return res.data;
}

async function getSessionLogs(projectId: string): Promise<SessionLogEntry[]> {
  const res = await apiClient.get(`/api/cairn/projects/${projectId}/session-logs`);
  return res.data;
}

async function getIntentSessionLogs(projectId: string, intentId: string): Promise<SessionLogEntry[]> {
  const res = await apiClient.get(`/api/cairn/projects/${projectId}/intents/${intentId}/session-logs`);
  return res.data;
}

async function getFactSessionLogs(projectId: string, factId: string): Promise<SessionLogEntry[]> {
  const res = await apiClient.get(`/api/cairn/projects/${projectId}/facts/${factId}/session-logs`);
  return res.data;
}

export const cairnApi = {
  listProjects,
  getProject,
  createProject,
  deleteProject,
  updateProjectTitle,
  updateProjectStatus,
  dispatchProject,
  completeProject,
  reopenProject,
  createHint,
  createIntent,
  concludeIntent,
  heartbeatIntent,
  releaseIntent,
  getSettings,
  updateSettings,
  getDispatcherStatus,
  startDispatcher,
  stopDispatcher,
  exportProject,
  getSessionLogs,
  getIntentSessionLogs,
  getFactSessionLogs,
};