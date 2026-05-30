import { useEffect, useMemo, useState, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  FileText,
  GitBranch,
  MessageSquare,
  Target,
  Trash2,
  Layout,
} from 'lucide-react';
import { useConfirm } from '@/components/common/ConfirmDialog';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import EmptyState from '@/components/common/EmptyState';
import { useTranslation } from 'react-i18next';
import api from '@/api/client';
import FlowCanvas from '@/pages/WorkflowDetail/FlowCanvas';
import { WorkflowEdge, WorkflowJSON, WorkflowNode } from '@/api/workflow';

interface CairnFact {
  id: string;
  description: string;
}

interface CairnIntent {
  id: string;
  from: string[];
  to: string;
  description: string;
  creator: string;
  worker: string | null;
  lastHeartbeatAt: string | null;
  createdAt: string;
  concludedAt: string | null;
}

interface CairnHint {
  id: string;
  content: string;
  creator: string;
  createdAt: string;
}

interface ProjectPayload {
  project: {
    id: string;
    title: string;
    status: 'active' | 'stopped' | 'completed';
    createdAt: string;
    reason: {
      worker: string;
      trigger: string;
      startedAt: string;
      lastHeartbeatAt: string;
    } | null;
  };
  facts: CairnFact[];
  intents: CairnIntent[];
  hints: CairnHint[];
}

// ---------------------------------------------------------------------------
// Color helpers
// ---------------------------------------------------------------------------

const PROJECT_PALETTE = [
  '#ef4444', '#f59e0b', '#10b981', '#3b82f6',
  '#8b5cf6', '#ec4899', '#6366f1', '#06b6d4',
];

function resolveColor(seed: string): string {
  let h = 0;
  for (let i = 0; i < seed.length; i++) {
    h = seed.charCodeAt(i) + ((h << 5) - h);
  }
  return PROJECT_PALETTE[Math.abs(h) % PROJECT_PALETTE.length];
}

function hexAlpha(hex: string, alpha: number): string {
  const full = hex.replace('#', '').length === 3
    ? hex.replace('#', '').split('').map(c => c + c).join('')
    : hex.replace('#', '');
  const r = parseInt(full.slice(0, 2), 16);
  const g = parseInt(full.slice(2, 4), 16);
  const b = parseInt(full.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

// ---------------------------------------------------------------------------
// Detail Page Tabs
// ---------------------------------------------------------------------------

type DetailTab = 'facts' | 'intents' | 'hints';

const TAB_CONFIG: { id: DetailTab; label: string; icon: React.ReactNode }[] = [
  { id: 'facts',   label: 'Facts',   icon: <FileText className="w-3.5 h-3.5" /> },
  { id: 'intents',  label: 'Intents',  icon: <Target className="w-3.5 h-3.5" /> },
  { id: 'hints',   label: 'Hints',   icon: <MessageSquare className="w-3.5 h-3.5" /> },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function CairnProjectDetailPage() {
  const { t } = useTranslation('cairn');
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const confirm = useConfirm();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [project, setProject] = useState<ProjectPayload | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [detailTab, setDetailTab] = useState<DetailTab>('facts');
  const [layoutKey, setLayoutKey] = useState(0);

  useEffect(() => {
    const projectId = id;
    if (!projectId) {
      setError(t('empty.title'));
      setLoading(false);
      return;
    }

    const fetchProject = async () => {
      try {
        setLoading(true);
        setError(null);
        const response = await api.get<ProjectPayload>(`/api/cairn/projects/${projectId}`);
        setProject(response.data);
      } catch (err: any) {
        console.error('Failed to load Cairn project detail:', err);
        setError(err.response?.data?.detail || err.message || t('empty.description'));
      } finally {
        setLoading(false);
      }
    };

    void fetchProject();
  }, [id]);

  const workflowJson = useMemo<WorkflowJSON>(() => {
    if (!project) {
      return { start: 'start', nodes: [], edges: [] };
    }

    const nodes: WorkflowNode[] = project.facts.map((fact) => ({
      id: fact.id,
      type: 'logic',
      description: fact.description,
    }));

    const intentNodes: WorkflowNode[] = project.intents.map((intent) => ({
      id: intent.id,
      type: 'branch',
      description: intent.description,
    }));

    const edges: WorkflowEdge[] = [];
    project.intents.forEach((intent, index) => {
      intent.from.forEach((sourceId) => {
        edges.push({
          from: sourceId,
          to: intent.id,
          order: index * 2,
          label: 'from',
        });
      });
      edges.push({
        from: intent.id,
        to: intent.to,
        order: index * 2 + 1,
        label: 'to',
      });
    });

    const startId = project.facts.find((fact) => fact.id === 'origin')?.id ?? project.facts[0]?.id ?? 'start';

    return {
      start: startId,
      nodes: [...nodes, ...intentNodes],
      edges,
    };
  }, [project]);

  const handleAutoLayout = useCallback(() => {
    setLayoutKey((k) => k + 1);
  }, []);

  // ------------ Render ------------

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <LoadingSpinner />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <EmptyState
          icon={<GitBranch className="w-16 h-16 text-red-500" />}
          title={t('empty.title')}
          description={error}
          action={
            <button
              onClick={() => navigate('/cairn')}
              className="inline-flex items-center px-4 py-2 bg-indigo-600 text-white rounded-md text-sm"
            >
              {t('buttons.backToList')}
            </button>
          }
        />
      </div>
    );
  }

  if (!project) {
    return null;
  }

  const accent = resolveColor(project.project.id);

  return (
    <div className="flex flex-col h-full bg-gray-50 overflow-hidden">
      {/* Toolbar (match WorkflowDetail TopBar style) */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 bg-white flex-shrink-0">
        <div className="flex items-center gap-3">
          <div
            className="w-7 h-7 rounded-lg flex items-center justify-center"
            style={{ backgroundColor: hexAlpha(accent, 0.12) }}
          >
            <GitBranch className="w-4 h-4" style={{ color: accent }} />
          </div>
          <div>
            <h1 className="text-sm font-semibold text-gray-900">{project.project.title}</h1>
            <p className="text-[11px] text-gray-500">
              {project.project.status === 'active' ? '进行中' : project.project.status === 'stopped' ? '已停止' : '已完成'}
              {' · '}创建于 {new Date(project.project.createdAt).toLocaleDateString('zh-CN')}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => navigate('/cairn')}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-white border border-gray-200 text-gray-600 text-xs rounded-lg hover:bg-gray-50 transition-colors"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            返回列表
          </button>
          <button
            type="button"
            onClick={async () => {
              const ok = await confirm({
                title: t('confirm.deleteTitle'),
                description: t('confirm.deleteDescription'),
                confirmText: t('confirm.deleteConfirm'),
                cancelText: t('confirm.deleteCancel'),
                variant: 'danger',
              });
              if (!ok) return;
              setDeleting(true);
              try {
                await api.delete(`/api/cairn/projects/${project.project.id}`);
                navigate('/cairn');
              } catch (err: any) {
                console.error('Failed to delete Cairn project:', err);
                setError(err.response?.data?.detail || t('errors.deleteFailed'));
                setDeleting(false);
              }
            }}
            disabled={deleting}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-red-600 border border-transparent text-white text-xs rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <Trash2 className="w-3.5 h-3.5" />
            删除
          </button>
        </div>
      </div>

      {/* Main area: canvas + right panel */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Canvas area */}
        <div className="flex flex-col flex-1 min-w-0">
          {/* Canvas tab bar */}
          <div className="flex items-center border-b border-gray-200 bg-white flex-shrink-0 px-2">
            <button
              className="flex items-center gap-1.5 px-3 py-2.5 text-xs font-medium text-red-600 relative"
            >
              <GitBranch className="w-3.5 h-3.5" />
              流程图
              <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-red-600 rounded-full" />
            </button>
          </div>

          {/* Flow canvas */}
          <div className="flex-1 min-h-0 relative">
            <FlowCanvas
              workflowJson={workflowJson}
              editable={false}
              layoutKey={layoutKey}
            />
            {/* Reset layout button */}
            <button
              onClick={handleAutoLayout}
              className="absolute top-3 right-3 z-10 flex items-center gap-1.5 px-3 py-1.5 bg-white border border-gray-200 text-gray-600 text-xs rounded-lg hover:bg-gray-50 shadow-sm transition-colors"
              title="重置布局"
            >
              <Layout className="w-3.5 h-3.5" />
              重置布局
            </button>
          </div>
        </div>

        {/* Divider */}
        <div className="w-px flex-shrink-0 bg-gray-200" />

        {/* Right panel — tabs for facts / intents / hints */}
        <div className="flex flex-col w-[360px] flex-shrink-0 bg-white border-l border-gray-200">
          {/* Tab bar */}
          <div className="flex items-center border-b border-gray-200 bg-white flex-shrink-0 px-2">
            {TAB_CONFIG.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setDetailTab(tab.id)}
                className={`flex items-center gap-1.5 px-3 py-2.5 text-xs font-medium transition-colors relative ${
                  detailTab === tab.id
                    ? 'text-red-600'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {tab.icon}
                {tab.label}
                {tab.id === 'facts' && project.facts.length > 0 && (
                  <span className="ml-0.5 text-[10px] text-gray-400">({project.facts.length})</span>
                )}
                {tab.id === 'intents' && project.intents.length > 0 && (
                  <span className="ml-0.5 text-[10px] text-gray-400">({project.intents.length})</span>
                )}
                {tab.id === 'hints' && project.hints.length > 0 && (
                  <span className="ml-0.5 text-[10px] text-gray-400">({project.hints.length})</span>
                )}
                {detailTab === tab.id && (
                  <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-red-600 rounded-full" />
                )}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {detailTab === 'facts' && (
              project.facts.length === 0 ? (
                <p className="text-sm text-gray-400 text-center py-8">{t('stats.noFacts') || '暂无 Facts'}</p>
              ) : (
                project.facts.map((fact) => (
                  <div key={fact.id} className="border border-gray-200 rounded-lg p-3 bg-gray-50">
                    <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-gray-500 mb-1.5">
                      <FileText className="w-3 h-3" />
                      {fact.id}
                    </div>
                    <p className="text-sm text-gray-700 leading-relaxed">{fact.description}</p>
                  </div>
                ))
              )
            )}

            {detailTab === 'intents' && (
              project.intents.length === 0 ? (
                <p className="text-sm text-gray-400 text-center py-8">{t('stats.noIntents')}</p>
              ) : (
                project.intents.map((intent) => (
                  <div key={intent.id} className="border border-gray-200 rounded-lg p-3 bg-gray-50">
                    <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-gray-500 mb-1.5">
                      <Target className="w-3 h-3" />
                      {intent.id}
                    </div>
                    <p className="text-sm text-gray-700 leading-relaxed mb-2">{intent.description}</p>
                    <div className="flex flex-wrap gap-2 text-[10px] text-gray-500">
                      <span>From: {intent.from.join(', ')}</span>
                      <span>→ To: {intent.to}</span>
                    </div>
                    {intent.worker && (
                      <div className="mt-1.5 flex items-center gap-1 text-[10px] text-gray-500">
                        <span>Worker: {intent.worker}</span>
                      </div>
                    )}
                  </div>
                ))
              )
            )}

            {detailTab === 'hints' && (
              project.hints.length === 0 ? (
                <p className="text-sm text-gray-400 text-center py-8">{t('stats.noHints')}</p>
              ) : (
                project.hints.map((hint) => (
                  <div key={hint.id} className="border border-gray-200 rounded-lg p-3 bg-gray-50">
                    <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-gray-500 mb-1.5">
                      <MessageSquare className="w-3 h-3" />
                      {hint.creator}
                    </div>
                    <p className="text-sm text-gray-700 leading-relaxed">{hint.content}</p>
                  </div>
                ))
              )
            )}
          </div>
        </div>
      </div>
    </div>
  );
}