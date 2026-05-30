import { useState, useEffect, type MouseEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  GitBranch,
  Plus,
  RefreshCw,
  Clock,
  CheckCircle2,
  PauseCircle,
  Activity,
  FileText,
  Target,
  Trash2,
  X,
  ChevronRight,
} from 'lucide-react';
import { useConfirm } from '@/components/common/ConfirmDialog';
import PageHeader from '@/components/common/PageHeader';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import EmptyState from '@/components/common/EmptyState';
import { useTranslation } from 'react-i18next';
import api from '@/api/client';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CairnProjectSummary {
  id: string;
  title: string;
  status: 'active' | 'stopped' | 'completed';
  createdAt: string;
  factCount: number;
  intentCount: number;
  workingIntentCount: number;
  unclaimedIntentCount: number;
  hintCount: number;
  reason?: {
    worker: string;
    trigger: string;
    startedAt: string;
    lastHeartbeatAt: string;
  } | null;
}

// ---------------------------------------------------------------------------
// Color helpers (mirrors Workflow page)
// ---------------------------------------------------------------------------

const PROJECT_PALETTE = [
  '#ef4444', // red-500
  '#f59e0b', // amber-500
  '#10b981', // emerald-500
  '#3b82f6', // blue-500
  '#8b5cf6', // violet-500
  '#ec4899', // pink-500
  '#6366f1', // indigo-500
  '#06b6d4', // cyan-500
];

function resolveProjectColor(project: CairnProjectSummary): string {
  let h = 0;
  const seed = project.id || project.title;
  for (let i = 0; i < seed.length; i++) {
    h = seed.charCodeAt(i) + ((h << 5) - h);
  }
  return PROJECT_PALETTE[Math.abs(h) % PROJECT_PALETTE.length];
}

function hexAlpha(hex: string, alpha: number): string {
  const h = hex.replace('#', '');
  const full = h.length === 3 ? h.split('').map(c => c + c).join('') : h;
  const r = parseInt(full.slice(0, 2), 16);
  const g = parseInt(full.slice(2, 4), 16);
  const b = parseInt(full.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

// ---------------------------------------------------------------------------
// Helper functions
// ---------------------------------------------------------------------------

function getStatusIcon(status: string) {
  switch (status) {
    case 'active':
      return <Activity className="w-4 h-4 text-green-500" />;
    case 'stopped':
      return <PauseCircle className="w-4 h-4 text-yellow-500" />;
    case 'completed':
      return <CheckCircle2 className="w-4 h-4 text-blue-500" />;
    default:
      return <Clock className="w-4 h-4 text-gray-500" />;
  }
}

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function getStatusLabel(status: string): string {
  switch (status) {
    case 'active':
      return '进行中';
    case 'stopped':
      return '已停止';
    case 'completed':
      return '已完成';
    default:
      return status;
  }
}

// ---------------------------------------------------------------------------
// CairnProjectsPage
// ---------------------------------------------------------------------------

export default function CairnProjectsPage() {
  const { t } = useTranslation('cairn');
  const navigate = useNavigate();
  const confirm = useConfirm();
  const [projects, setProjects] = useState<CairnProjectSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newOrigin, setNewOrigin] = useState('');
  const [newGoal, setNewGoal] = useState('');
  const [newHints, setNewHints] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [deletingProjectId, setDeletingProjectId] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);

  const fetchProjects = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await api.get('/api/cairn/projects');
      setProjects(response.data);
    } catch (err: any) {
      console.error('Failed to fetch Cairn projects:', err);
      setError(err.response?.data?.detail || 'Failed to load projects');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchProjects();
  }, []);

  const handleRefresh = async () => {
    if (refreshing) return;
    setRefreshing(true);
    await fetchProjects();
  };

  const handleCreateProject = () => {
    setCreateError(null);
    setShowCreateModal(true);
  };

  const handleCloseCreateModal = () => {
    setShowCreateModal(false);
    setCreateError(null);
    setNewTitle('');
    setNewOrigin('');
    setNewGoal('');
    setNewHints('');
  };

  const handleSubmitCreateProject = async () => {
    if (!newTitle.trim() || !newOrigin.trim() || !newGoal.trim()) {
      setCreateError(t('errors.missingFields'));
      return;
    }

    setSubmitting(true);
    setCreateError(null);

    try {
      const hints = newHints
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
        .map((content) => ({ content, creator: 'user' }));

      const response = await api.post('/api/cairn/projects', {
        title: newTitle.trim(),
        origin: newOrigin.trim(),
        goal: newGoal.trim(),
        hints: hints.length > 0 ? hints : undefined,
      });

      handleCloseCreateModal();
      navigate(`/cairn/${response.data.id}`);
    } catch (err: any) {
      console.error('Failed to create Cairn project:', err);
      setCreateError(err.response?.data?.detail || err.message || t('errors.createFailed'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeleteProject = async (projectId: string, event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    const ok = await confirm({
      title: t('confirm.deleteTitle'),
      description: t('confirm.deleteDescription'),
      confirmText: t('confirm.deleteConfirm'),
      cancelText: t('confirm.deleteCancel'),
      variant: 'danger',
    });

    if (!ok) return;
    setDeletingProjectId(projectId);

    try {
      await api.delete(`/api/cairn/projects/${projectId}`);
      await fetchProjects();
    } catch (err: any) {
      console.error('Failed to delete Cairn project:', err);
      setError(err.response?.data?.detail || t('errors.deleteFailed'));
    } finally {
      setDeletingProjectId(null);
    }
  };

  const handleViewProject = (projectId: string) => {
    navigate(`/cairn/${projectId}`);
  };

  if (loading && !refreshing) {
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
          title="加载项目失败"
          description={error}
          action={
            <button
              onClick={handleRefresh}
              className="inline-flex items-center px-3 py-1.5 bg-indigo-600 text-white rounded-md text-sm"
            >
              重试
            </button>
          }
        />
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-slate-50 text-slate-900 dark:text-slate-100">
      {/* Header */}
      <PageHeader
        title={t('title')}
        description={t('description')}
        icon={<GitBranch className="w-8 h-8 text-red-600 dark:text-red-400" />}
      />

      {/* Toolbar (match Workflow page style) */}
      <div className="px-4 py-2 border-b border-gray-100 flex items-center gap-3">
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            title={refreshing ? t('buttons.refresh') : t('buttons.refresh')}
            className={`p-1.5 rounded-lg border transition-all ${
              refreshing ? 'border-green-200 text-green-600' : 'border-gray-200 text-gray-400 hover:bg-gray-50 hover:text-gray-600 disabled:opacity-50'
            }`}
          >
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} />
          </button>

          <button
            onClick={handleCreateProject}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors text-sm"
          >
            <Plus className="w-4 h-4" />
            {t('create.open')}
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto px-6 pb-6">
        {projects.length === 0 ? (
          <EmptyState
            icon={<GitBranch className="w-16 h-16 text-slate-400" />}
            title={t('empty.title')}
            description={t('empty.description')}
          />
        ) : (
          <div className="grid gap-3 grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {projects.map((project) => {
              const color = resolveProjectColor(project);
              return (
                <div
                  key={project.id}
                  onClick={() => handleViewProject(project.id)}
                  className="group relative bg-white rounded-xl border border-gray-200 flex flex-col overflow-hidden cursor-pointer transition-all duration-150 hover:border-gray-300 hover:shadow-md"
                >
                  {/* Top accent bar */}
                  <div style={{ height: 3, backgroundColor: color }} />

                  {/* Card body */}
                  <div className="flex-1 px-4 pt-3 pb-2 flex flex-col gap-2 min-w-0">
                    {/* Avatar + name row */}
                    <div className="flex items-start gap-2.5">
                      <div
                        className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
                        style={{ backgroundColor: hexAlpha(color, 0.12) }}
                      >
                        <GitBranch className="w-4 h-4" style={{ color }} />
                      </div>

                      <div className="min-w-0 flex-1">
                        <span className="block text-sm font-semibold text-gray-900 truncate leading-snug">
                          {project.title}
                        </span>
                        <div className="flex items-center gap-1 mt-0.5 flex-wrap">
                          {/* Status badge */}
                          <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium border ${
                            project.status === 'active'
                              ? 'bg-green-50 text-green-600 border-green-200'
                              : project.status === 'stopped'
                              ? 'bg-yellow-50 text-yellow-600 border-yellow-200'
                              : 'bg-blue-50 text-blue-600 border-blue-200'
                          }`}>
                            {getStatusLabel(project.status)}
                          </span>
                        </div>
                      </div>

                      <ChevronRight className="w-4 h-4 text-gray-300 shrink-0 mt-1 group-hover:text-gray-500 transition-colors" />
                    </div>

                    {/* Created date */}
                    <p className="text-xs text-gray-400">
                      创建于 {formatDate(project.createdAt)}
                    </p>
                  </div>

                  {/* Stats footer — grid of 4 columns like Workflow style */}
                  <div className="border-t border-gray-100 px-4 py-2.5 grid grid-cols-4 gap-1">
                    <div>
                      <div className="text-base font-bold text-gray-900 tabular-nums">
                        {project.factCount}
                      </div>
                      <div className="text-[10px] text-gray-500">{t('stats.fact')}</div>
                    </div>
                    <div>
                      <div className="text-base font-bold text-gray-900 tabular-nums">
                        {project.intentCount}
                      </div>
                      <div className="text-[10px] text-gray-500">{t('stats.intent')}</div>
                    </div>
                    <div>
                      <div className="text-base font-bold tabular-nums"
                           style={{ color: project.workingIntentCount > 0 ? '#16a34a' : '#9ca3af' }}>
                        {project.workingIntentCount}
                      </div>
                      <div className="text-[10px] text-gray-500">{t('stats.working')}</div>
                    </div>
                    <div>
                      <div className="text-base font-bold text-gray-900 tabular-nums flex items-center gap-0.5">
                        <Clock className="w-3 h-3 text-gray-400 shrink-0" />
                        {project.unclaimedIntentCount}
                      </div>
                      <div className="text-[10px] text-gray-500">{t('stats.unclaimed')}</div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-transparent p-4">
          <div className="w-full max-w-2xl rounded-3xl bg-white shadow-2xl overflow-hidden ring-1 ring-black/10">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
              <div>
                <h2 className="text-xl font-semibold text-slate-900">{t('create.title')}</h2>
                <p className="text-sm text-slate-500 mt-1">{t('create.subtitle')}</p>
              </div>
              <button
                type="button"
                onClick={handleCloseCreateModal}
                className="inline-flex h-10 w-10 items-center justify-center rounded-full text-slate-500 hover:bg-slate-100 hover:text-slate-700"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4 px-6 py-5">
              {createError && (
                <div className="rounded-2xl bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
                  {createError}
                </div>
              )}

              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className="block text-sm font-medium text-slate-700"><span className="text-rose-600 mr-1">*</span>{t('form.titleLabel')}</label>
                  <input
                    value={newTitle}
                    onChange={(e) => setNewTitle(e.target.value)}
                    className="mt-2 block w-full rounded-2xl border border-slate-300 bg-slate-50 px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200"
                    placeholder={t('form.titlePlaceholder')}
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700"><span className="text-rose-600 mr-1">*</span>{t('form.originLabel')}</label>
                <textarea
                  value={newOrigin}
                  onChange={(e) => setNewOrigin(e.target.value)}
                  rows={3}
                  className="mt-2 block w-full rounded-2xl border border-slate-300 bg-slate-50 px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200"
                  placeholder={t('form.originPlaceholder')}
                />
              </div>

              <div className="mt-4">
                <label className="block text-sm font-medium text-slate-700"><span className="text-rose-600 mr-1">*</span>{t('form.goalLabel')}</label>
                <input
                  value={newGoal}
                  onChange={(e) => setNewGoal(e.target.value)}
                  className="mt-2 block w-full rounded-2xl border border-slate-300 bg-slate-50 px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200"
                  placeholder={t('form.goalPlaceholder')}
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700">{t('form.hintsLabel')}</label>
                <textarea
                  value={newHints}
                  onChange={(e) => setNewHints(e.target.value)}
                  rows={4}
                  className="mt-2 block w-full rounded-2xl border border-slate-300 bg-slate-50 px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200"
                  placeholder={t('form.hintsPlaceholder')}
                />
                <p className="mt-2 text-xs text-slate-500">{t('form.hintsHelp')}</p>
              </div>
            </div>

            <div className="flex flex-col gap-3 border-t border-slate-200 bg-slate-50 px-6 py-4 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={handleCloseCreateModal}
                className="inline-flex items-center justify-center rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
              >
                {t('buttons.cancel')}
              </button>
              <button
                type="button"
                onClick={handleSubmitCreateProject}
                disabled={submitting}
                className="inline-flex items-center justify-center rounded-2xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-400"
              >
                {submitting ? t('form.creating') : t('buttons.create')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
