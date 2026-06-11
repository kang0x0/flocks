import { useState, useEffect, useCallback } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Plus, Play, Pause, CheckCircle, GitBranch, RefreshCw } from 'lucide-react';

import PageHeader from '@/components/common/PageHeader';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import dagAPI, { type DagProject } from '@/api/dag';
import ProjectDetail from './ProjectDetail';

// ---- Status helpers ----

function statusBadge(status: string) {
  const map: Record<string, { label: string; cls: string }> = {
    active: { label: '●', cls: 'bg-green-100 text-green-700' },
    stopped: { label: '⏸', cls: 'bg-yellow-100 text-yellow-700' },
    completed: { label: '✓', cls: 'bg-gray-100 text-gray-600' },
  };
  const s = map[status] ?? { label: status, cls: 'bg-gray-100 text-gray-500' };
  return (
    <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium ${s.cls}`}>
      {s.label}
    </span>
  );
}

// ---- Create Modal ----

function CreateModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const { t } = useTranslation('dag');
  const navigate = useNavigate();
  const [mode, setMode] = useState<'analyze' | 'manual'>('analyze');
  const [input, setInput] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const [result, setResult] = useState<{
    origin: string;
    goal: string;
    confidence: number;
    missing_info: string[];
    clarification_questions: string[];
  } | null>(null);

  const [manualTitle, setManualTitle] = useState('');
  const [manualOrigin, setManualOrigin] = useState('');
  const [manualGoal, setManualGoal] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');

  const handleAnalyze = useCallback(async () => {
    if (!input.trim()) return;
    setAnalyzing(true);
    setError('');
    try {
      const res = await dagAPI.analyze(input);
      const r = res.data;
      if (r.analyzable) {
        setResult({
          origin: r.origin || '',
          goal: r.goal || '',
          confidence: r.confidence,
          missing_info: r.missing_info || [],
          clarification_questions: r.clarification_questions || [],
        });
      } else {
        setResult({
          origin: '',
          goal: '',
          confidence: 0,
          missing_info: r.missing_info || [],
          clarification_questions: r.clarification_questions || [],
        });
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setAnalyzing(false);
    }
  }, [input]);

  const handleCreate = useCallback(async () => {
    setCreating(true);
    setError('');
    try {
      let origin: string, goal: string, title: string;
      if (mode === 'analyze' && result?.origin) {
        origin = result.origin;
        goal = result.goal;
        title = manualTitle || input.slice(0, 60) || 'DAG Project';
      } else {
        origin = manualOrigin;
        goal = manualGoal;
        title = manualTitle || 'DAG Project';
      }

      const res = await dagAPI.createProject({ title, origin, goal });
      onCreated(res.data.project_id);
      navigate(`/dag?project=${res.data.project_id}`);
      onClose();
    } catch (e) {
      setError(String(e));
    } finally {
      setCreating(false);
    }
  }, [mode, result, manualTitle, manualOrigin, manualGoal, input, onCreated, onClose, navigate]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h2 className="text-lg font-semibold text-gray-900">{t('createProject')}</h2>
      <button onClick={onClose} className="text-gray-400 hover:text-gray-600 p-1 transition-colors">
        ✕
      </button>
    </div>

    <div className="p-6 space-y-4">
      {/* Mode switch */}
      <div className="flex gap-2">
        <button
          onClick={() => { setMode('analyze'); setResult(null); setError(''); }}
          className={`flex-1 py-2 text-sm rounded-lg border font-medium transition-colors ${
            mode === 'analyze'
              ? 'border-slate-400 bg-slate-50 text-slate-700'
              : 'border-gray-200 text-gray-500 hover:border-gray-300 hover:text-gray-700'
          }`}
        >
          {t('autoAnalyze')}
        </button>
        <button
          onClick={() => setMode('manual')}
          className={`flex-1 py-2 text-sm rounded-lg border font-medium transition-colors ${
            mode === 'manual'
              ? 'border-slate-400 bg-slate-50 text-slate-700'
              : 'border-gray-200 text-gray-500 hover:border-gray-300 hover:text-gray-700'
          }`}
        >
          {t('manualInput')}
        </button>
      </div>

          {mode === 'analyze' && (
            <>
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={t('analyzePlaceholder')}
                rows={3}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-slate-400 resize-none"
              />
              <button
                onClick={handleAnalyze}
                disabled={analyzing || !input.trim()}
              className="w-full py-2 bg-red-600 text-white text-sm font-medium rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors"
            >
              {analyzing ? t('analyzing') : t('autoAnalyze')}
              </button>
            </>
          )}

          {/* Analyze result */}
          {result && mode === 'analyze' && (
            <div className="bg-gray-50 rounded-lg p-4 space-y-3">
              <div className="flex items-center gap-2 text-sm text-gray-600">
                <span>{t('confidence')}:</span>
                <span className="font-semibold">{(result.confidence * 100).toFixed(0)}%</span>
              </div>
              {result.origin ? (
                <>
                  <div>
                    <label className="block text-xs font-medium text-gray-500 mb-1">
                      {t('origin')}
                    </label>
                    <textarea
                      value={result.origin}
                      onChange={(e) => setResult({ ...result, origin: e.target.value })}
                      rows={2}
                      className="w-full px-3 py-1.5 border border-gray-200 rounded text-sm focus:outline-none focus:ring-1 focus:ring-slate-400 resize-none"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-500 mb-1">
                      {t('goal')}
                    </label>
                    <textarea
                      value={result.goal}
                      onChange={(e) => setResult({ ...result, goal: e.target.value })}
                      rows={2}
                      className="w-full px-3 py-1.5 border border-gray-200 rounded text-sm focus:outline-none focus:ring-1 focus:ring-slate-400 resize-none"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-500 mb-1">
                      {t('projectTitle')}
                    </label>
                    <input
                      type="text"
                      value={manualTitle}
                      onChange={(e) => setManualTitle(e.target.value)}
                      placeholder="Enter project title..."
                      className="w-full px-3 py-1.5 border border-gray-200 rounded text-sm focus:outline-none focus:ring-1 focus:ring-slate-400"
                    />
                  </div>
                </>
              ) : (
                <div className="text-sm text-red-600 space-y-1">
                  <p className="font-medium">{t('unanalyzable')}</p>
                  {result.missing_info?.length > 0 && (
                    <ul className="list-disc list-inside text-gray-500 text-xs">
                      {result.missing_info.map((m, i) => (
                        <li key={i}>{m}</li>
                      ))}
                    </ul>
                  )}
                  {result.clarification_questions?.length > 0 && (
                    <div className="text-xs text-gray-400 mt-1">
                      <p className="font-medium">{t('pleaseProvide')}</p>
                      {result.clarification_questions.map((q, i) => (
                        <p key={i}>• {q}</p>
                      ))}
                    </div>
                  )}
                </div>
              )}
              <button
                onClick={handleCreate}
                disabled={creating || (!result.origin && mode === 'analyze')}
                className="w-full py-2 bg-red-600 text-white text-sm font-medium rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors"
              >
                {creating ? t('analyzing') : result.origin ? t('confirmCreate') : t('editBeforeCreate')}
              </button>
            </div>
          )}

          {/* Manual */}
          {mode === 'manual' && (
            <div className="space-y-3">
              <input
                type="text"
                value={manualTitle}
                onChange={(e) => setManualTitle(e.target.value)}
                placeholder={t('projectTitle')}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-slate-400"
              />
              <textarea
                value={manualOrigin}
                onChange={(e) => setManualOrigin(e.target.value)}
                placeholder={t('origin')}
                rows={3}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-slate-400 resize-none"
              />
              <textarea
                value={manualGoal}
                onChange={(e) => setManualGoal(e.target.value)}
                placeholder={t('goal')}
                rows={3}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-slate-400 resize-none"
              />
              <button
                onClick={handleCreate}
                disabled={creating || !manualTitle || !manualOrigin || !manualGoal}
                className="w-full py-2 bg-red-600 text-white text-sm font-medium rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors"
              >
                {creating ? t('analyzing') : t('confirmCreate')}
              </button>
            </div>
          )}

          {error && <div className="text-sm text-red-500">{error}</div>}
        </div>
      </div>
    </div>
  );
}

// ---- Main Page ----

export default function DagPage() {
  const { t } = useTranslation('dag');
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const selectedProjectId = searchParams.get('project');

  const [projects, setProjects] = useState<DagProject[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showCreate, setShowCreate] = useState(false);

  const fetchProjects = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await dagAPI.listProjects();
      setProjects(res.data.projects || []);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  // Show project detail if ?project=id is set
  if (selectedProjectId) {
    return (
      <ProjectDetail
        projectId={selectedProjectId}
        onBack={() => navigate('/dag')}
      />
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <PageHeader
        title={t('title')}
        description={t('subtitle')}
        icon={<GitBranch className="w-5 h-5 text-red-600" />}
        action={
          <div className="flex items-center gap-2">
            <button
              onClick={fetchProjects}
              className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100 transition-colors"
              title={t('refresh')}
            >
              <RefreshCw className="w-4 h-4" />
            </button>
            <button
              onClick={() => setShowCreate(true)}
              className="inline-flex items-center gap-2 px-4 py-2 bg-red-600 text-white text-sm font-medium rounded-lg hover:bg-red-700 transition-colors"
            >
              <Plus className="w-4 h-4" />
              {t('createProject')}
            </button>
          </div>
        }
      />

      {/* Content */}
      <div className="flex-1 overflow-auto p-6">
        {loading && <LoadingSpinner />}

        {error && !loading && (
          <div className="flex flex-col items-center justify-center py-20 text-gray-400 gap-3">
            <p className="text-sm text-red-500">{t('error')}: {error}</p>
            <button
              onClick={fetchProjects}
              className="px-4 py-2 text-sm text-red-600 hover:bg-slate-50 rounded-lg transition-colors"
            >
              {t('retry')}
            </button>
          </div>
        )}

        {!loading && !error && projects.length === 0 && (
          <div className="flex flex-col items-center justify-center py-20 text-gray-400 gap-3">
            <GitBranch className="w-12 h-12" />
            <p className="text-sm">{t('noProjects')}</p>
            <p className="text-xs text-gray-300">{t('noProjectsHint')}</p>
          </div>
        )}

        {!loading && !error && projects.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {projects.map((p) => (
              <div
                key={p.id}
                onClick={() => navigate(`/dag?project=${p.id}`)}
                className="bg-white rounded-xl border border-gray-200 p-5 hover:shadow-md hover:border-gray-300 cursor-pointer transition-all duration-150"
              >
                <div className="flex items-start justify-between mb-3">
                  <h3 className="font-semibold text-gray-900 truncate flex-1 mr-2">
                    {p.title}
                  </h3>
                  {statusBadge(p.status)}
                </div>
                {p.description && (
                  <p className="text-xs text-gray-400 mb-3 line-clamp-2">{p.description}</p>
                )}
                <div className="flex items-center gap-4 text-xs text-gray-400">
                  <span>ID: {p.id.slice(0, 12)}</span>
                  <span>{new Date(p.created_at).toLocaleDateString()}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Create Modal */}
      <CreateModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={() => fetchProjects()}
      />
    </div>
  );
}
