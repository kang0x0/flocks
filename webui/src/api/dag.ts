/**
 * DAG Explorer API 模块
 */

import apiClient from '@/api/client';

// ---- Types ----

export interface DagProject {
  id: string;
  title: string;
  description: string;
  status: 'active' | 'stopped' | 'completed';
  origin_fact_id: string;
  goal_fact_id: string;
  seed_intent_id: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface FactNode {
  id: string;
  project_id: string;
  content: string;
  fact_type: 'origin' | 'goal' | 'discovery' | 'conclusion';
  confidence: number;
  evidence?: string | null;
  source_intent_id?: string | null;
}

export interface IntentEdge {
  id: string;
  project_id: string;
  description: string;
  status: 'open' | 'claimed' | 'completed' | 'failed';
  source_fact_ids: string[];
  priority: number;
}

export interface GraphSnapshot {
  project_id: string;
  project_title: string;
  status: string;
  origin_fact: FactNode | null;
  goal_fact: FactNode | null;
  facts: FactNode[];
  open_intents: IntentEdge[];
  all_intents: IntentEdge[];
  unread_hints: string[];
  statistics: Record<string, number>;
}

export interface PreAnalysisResult {
  analyzable: boolean;
  origin: string | null;
  goal: string | null;
  confidence: number;
  missing_info: string[];
  clarification_questions: string[];
}

export interface TaskLog {
  id: number;
  project_id: string;
  task_type: 'reason' | 'explore';
  intent_id: string | null;
  session_id: string | null;
  status: string;
  rounds: number;
  tool_calls_count: number;
  result_summary: string | null;
  error_message: string | null;
  duration_seconds: number;
  created_at: string;
}

export interface SessionReplay {
  session_id: string;
  provider: string;
  model: string;
  rounds: number;
  tool_calls: unknown[];
  messages: {
    role: string;
    content: string;
    tool_calls: unknown;
    timestamp: string;
  }[];
  duration_seconds: number;
}

// ---- API ----

export const dagAPI = {
  /** 预分析用户输入 */
  analyze(input: string) {
    return apiClient.post<PreAnalysisResult>('/api/dag/projects/analyze', {
      user_input: input,
    });
  },

  /** 创建项目 */
  createProject(data: {
    title: string;
    origin: string;
    goal: string;
    description?: string;
  }) {
    return apiClient.post<{ project_id: string }>(
      '/api/dag/projects',
      data
    );
  },

  /** 列出所有项目 */
  listProjects(status?: string) {
    return apiClient.get<{ projects: DagProject[]; count: number }>(
      '/api/dag/projects',
      { params: status ? { status } : undefined }
    );
  },

  /** 获取项目详情 */
  getProject(projectId: string) {
    return apiClient.get<DagProject>(`/api/dag/projects/${projectId}`);
  },

  /** 暂停项目 */
  stopProject(projectId: string) {
    return apiClient.post(`/api/dag/projects/${projectId}/stop`);
  },

  /** 恢复项目 */
  resumeProject(projectId: string) {
    return apiClient.post(`/api/dag/projects/${projectId}/resume`);
  },

  /** 获取图快照 */
  getGraphSnapshot(projectId: string) {
    return apiClient.get<GraphSnapshot>(
      `/api/dag/projects/${projectId}/graph`
    );
  },

  /** 获取 Mermaid 源码 */
  getMermaid(projectId: string) {
    return apiClient.get<string>(
      `/api/dag/projects/${projectId}/graph/mermaid`
    );
  },

  /** 获取统计 */
  getStatistics(projectId: string) {
    return apiClient.get<Record<string, number>>(
      `/api/dag/projects/${projectId}/statistics`
    );
  },

  /** 获取 Facts */
  listFacts(projectId: string) {
    return apiClient.get<{ facts: FactNode[] }>(
      `/api/dag/projects/${projectId}/facts`
    );
  },

  /** 手动添加 Fact */
  addFact(projectId: string, fact: {
    id: string;
    content: string;
    fact_type?: string;
    confidence?: number;
    evidence?: string;
  }) {
    return apiClient.post(`/api/dag/projects/${projectId}/facts`, fact);
  },

  /** 获取 Intents */
  listIntents(projectId: string) {
    return apiClient.get<{ intents: IntentEdge[] }>(
      `/api/dag/projects/${projectId}/intents`
    );
  },

  /** 手动添加 Intent */
  addIntent(projectId: string, intent: {
    id: string;
    description: string;
    source_fact_ids?: string[];
    priority?: number;
  }) {
    return apiClient.post(`/api/dag/projects/${projectId}/intents`, intent);
  },

  /** 获取 Hints */
  listHints(projectId: string) {
    return apiClient.get<{ hints: { id: string; content: string; hint_type: string; is_read: boolean; created_at: string }[] }>(
      `/api/dag/projects/${projectId}/hints`
    );
  },

  /** 添加 Hint */
  addHint(projectId: string, content: string, hintType: string = 'guidance') {
    return apiClient.post(`/api/dag/projects/${projectId}/hints`, {
      content,
      hint_type: hintType,
    });
  },

  /** 获取任务日志 */
  listTaskLogs(projectId: string, limit: number = 50) {
    return apiClient.get<{ tasks: TaskLog[] }>(
      `/api/dag/projects/${projectId}/tasks`,
      { params: { limit } }
    );
  },

  /** 会话回放 */
  getSessionReplay(projectId: string, logId: number) {
    return apiClient.get<SessionReplay>(
      `/api/dag/projects/${projectId}/tasks/${logId}/session`
    );
  },
};

export default dagAPI;
