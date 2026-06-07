import { useEffect, useState, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import { cairnApi, type ProjectSummary } from '@/api/cairn';

function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  const now = Date.now();
  const diff = now - d.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return d.toLocaleDateString();
}

function statusBadgeClass(status: string): string {
  switch (status) {
    case 'active': return 'bg-teal-50 text-teal-700 border-teal-200';
    case 'stopped': return 'bg-amber-50 text-amber-700 border-amber-200';
    case 'completed': return 'bg-slate-100 text-slate-500 border-slate-200';
    default: return 'bg-slate-100 text-slate-500 border-slate-200';
  }
}

function reasonBadgeText(reason: { worker: string | null; trigger: string | null }): string {
  if (reason.trigger) return `${reason.worker} · ${reason.trigger}`;
  return reason.worker || 'Reasoning';
}

function workingIntentBadgeText(count: number): string {
  return `${count} working`;
}

export default function CairnProjectsList() {
  const navigate = useNavigate();
  const { t } = useTranslation('cairn');
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showNewProject, setShowNewProject] = useState(false);
  const [showRename, setShowRename] = useState<{ id: string; title: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await cairnApi.listProjects();
      setProjects(data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Dispatcher auto mode — start ON by default
  const [dispatcherRunning, setDispatcherRunning] = useState(false);
  const [dispatcherStarting, setDispatcherStarting] = useState(false);
  const autoStartedRef = useRef(false);

  // Auto-start dispatcher on first mount
  useEffect(() => {
    if (autoStartedRef.current) return;
    autoStartedRef.current = true;
    cairnApi.startDispatcher().then(() => setDispatcherRunning(true)).catch(() => {});
  }, []);

  // Poll dispatcher status
  useEffect(() => {
    const poll = async () => {
      try {
        const status = await cairnApi.getDispatcherStatus();
        setDispatcherRunning(status.running);
      } catch { /* ignore */ }
    };
    poll();
    const timer = setInterval(poll, 3000);
    return () => clearInterval(timer);
  }, []);

  async function handleStartDispatcher() {
    setDispatcherStarting(true);
    try {
      await cairnApi.startDispatcher();
      setDispatcherRunning(true);
    } catch { alert('Failed to start dispatcher'); }
    finally { setDispatcherStarting(false); }
  }

  async function handleStopDispatcher() {
    try {
      await cairnApi.stopDispatcher();
      setDispatcherRunning(false);
    } catch {
      try {
        const status = await cairnApi.getDispatcherStatus();
        if (!status.running) setDispatcherRunning(false);
      } catch { /* ignore */ }
    }
  }

  const countByStatus = (status: string) => projects.filter((p) => p.status === status).length;

  const hasActive = () => countByStatus('active') > 0;

  async function handleStopAll() {
    const active = projects.filter((p) => p.status === 'active');
    if (!active.length) return;
    if (!confirm(`Stop ${active.length} active project(s)?`)) return;
    try {
      await Promise.all(active.map((p) => cairnApi.updateProjectStatus(p.id, 'stopped')));
      await load();
    } catch {
      alert('Failed to stop all projects');
    }
  }

  async function toggleStop(project: ProjectSummary) {
    try {
      await cairnApi.updateProjectStatus(project.id, project.status === 'active' ? 'stopped' : 'active');
      await load();
    } catch (err: any) {
      alert(err?.response?.data?.detail || 'Failed to update status');
    }
  }

  async function handleDelete(project: ProjectSummary) {
    if (!confirm(`Delete "${project.title}"?`)) return;
    try {
      await cairnApi.deleteProject(project.id);
      setProjects((prev) => prev.filter((p) => p.id !== project.id));
    } catch (err: any) {
      alert(err?.response?.data?.detail || 'Failed to delete');
    }
  }

  async function handleRename(id: string, title: string) {
    try {
      await cairnApi.updateProjectTitle(id, title);
      await load();
      setShowRename(null);
    } catch (err: any) {
      alert(err?.response?.data?.detail || 'Failed to rename');
    }
  }

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <header className="bg-white/80 backdrop-blur border-b border-slate-200/60 px-4 py-2.5 flex items-center gap-3 shrink-0">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="h-8 w-8 rounded-lg border border-slate-200 bg-white shadow-sm shadow-slate-200/40 flex items-center justify-center shrink-0 overflow-hidden">
            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H19a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H6.5a2.5 2.5 0 0 1 0-5H20"/><path d="M8 7h8"/><path d="M8 11h8"/><path d="M8 15h5"/></svg>
          </div>
          <span className="font-semibold text-slate-700 tracking-tight">Cairn</span>
        </div>
        <div className="flex-1" />
        <div className="flex items-center gap-3 text-[11px] text-slate-400">
          <span className="inline-flex items-center gap-1.5 shrink-0" title={t('stats.all')}>
            <span className="font-medium uppercase tracking-[0.12em] text-slate-400">{t('buttons.all')}</span>
            <span className="font-semibold text-slate-600 tabular-nums">{projects.length}</span>
          </span>
          <span className="inline-flex items-center gap-1.5 shrink-0" title={t('stats.statusActive')}>
            <span className="h-1.5 w-1.5 rounded-full bg-teal-500" />
            <span className="font-semibold text-teal-700 tabular-nums">{countByStatus('active')}</span>
          </span>
          <span className="inline-flex items-center gap-1.5 shrink-0" title={t('stats.statusStopped')}>
            <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
            <span className="font-semibold text-amber-700 tabular-nums">{countByStatus('stopped')}</span>
          </span>
          <span className="inline-flex items-center gap-1.5 shrink-0" title={t('stats.statusCompleted')}>
            <span className="h-1.5 w-1.5 rounded-full bg-slate-400" />
            <span className="font-semibold text-slate-600 tabular-nums">{countByStatus('completed')}</span>
          </span>
          {hasActive() && (
            <button
              onClick={handleStopAll}
              className="h-7 px-2.5 rounded-lg border border-amber-200 text-xs text-amber-700 hover:bg-amber-50 transition inline-flex items-center gap-1.5 shrink-0"
              title={t('confirm.stopAllTitle')}
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24"><path d="M6 6h12v12H6z"/></svg>
              {t('buttons.stopAll')}
            </button>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={dispatcherRunning ? handleStopDispatcher : handleStartDispatcher}
            disabled={dispatcherStarting}
            title={dispatcherRunning ? t('dispatcher.stopTooltip') : t('dispatcher.startTooltip')}
            className={`px-2.5 h-7 rounded-lg text-xs font-medium transition inline-flex items-center gap-1.5 border shrink-0 ${
              dispatcherRunning
                ? 'bg-emerald-50 border-emerald-200 text-emerald-600 hover:bg-emerald-100'
                : 'bg-white/90 border-slate-200 text-slate-600 hover:bg-slate-50'
            }`}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${dispatcherRunning ? 'bg-emerald-500 animate-pulse' : 'bg-slate-300'}`}></span>
            {dispatcherRunning ? t('dispatcher.autoOn') : t('dispatcher.autoOff')}
          </button>
          <button
            onClick={() => setShowNewProject(true)}
            className="h-7 px-2.5 rounded-lg border border-brand-200 text-xs text-brand-600 hover:bg-brand-50 transition inline-flex items-center gap-1.5"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.9" viewBox="0 0 24 24"><path d="M12 5v14"/><path d="M5 12h14"/></svg>
            {t('create.open')}
          </button>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto p-4">
        {error && (
          <div className="mb-4 flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm">
            <span className="w-1.5 h-1.5 rounded-full bg-red-500 shrink-0" />
            {error}
          </div>
        )}

        {projects.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-400">
            <svg className="w-20 h-20 mb-5 opacity-30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H19a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H6.5a2.5 2.5 0 0 1 0-5H20"/><path d="M8 7h8"/><path d="M8 11h8"/><path d="M8 15h5"/></svg>
            <p className="text-lg font-medium text-slate-500">{t('empty.title')}</p>
            <p className="text-sm mt-1">{t('empty.action')}</p>
            <button
              onClick={() => setShowNewProject(true)}
              className="mt-4 h-8 px-4 rounded-lg border border-slate-300 text-xs font-medium text-slate-600 hover:bg-slate-100 transition inline-flex items-center gap-1.5"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.9" viewBox="0 0 24 24"><path d="M12 5v14"/><path d="M5 12h14"/></svg>
              {t('create.open')}
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
            {projects.map((p) => (
              <div
                key={p.id}
                onClick={() => navigate(`/cairn/${p.id}`)}
                className="group h-full flex flex-col bg-white rounded-2xl border border-slate-200/60 p-5 cursor-pointer transition-all duration-200 hover:shadow-lg hover:shadow-slate-200/50 hover:border-slate-300 hover:-translate-y-0.5"
              >
                <div className="flex items-start justify-between mb-3">
                  <span className="text-[11px] font-mono text-slate-400 tracking-wide">{p.id}</span>
                  <span className={`px-1.5 py-0.5 rounded-full text-[9px] font-semibold uppercase tracking-[0.12em] border ${statusBadgeClass(p.status)}`}>
                    {p.status}
                  </span>
                </div>
                <div className="mb-3 flex-1">
                  <div className="title-action-trigger flex items-start gap-2">
                    <h3 className="min-w-0 flex-1 text-[15px] font-semibold text-slate-700 break-words group-hover:text-brand-600 transition-colors">
                      {p.title}
                    </h3>
                    <button
                      onClick={(e) => { e.stopPropagation(); setShowRename({ id: p.id, title: p.title }); }}
                      className="title-action-button mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-slate-200 text-slate-400 hover:border-slate-300 hover:bg-slate-50 hover:text-slate-600"
                      title={t('buttons.rename')}
                    >
                      <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24"><path d="m16.862 4.487 1.65-1.65a1.875 1.875 0 1 1 2.652 2.652l-9.193 9.193a4.5 4.5 0 0 1-1.897 1.13L6 17l1.188-4.074a4.5 4.5 0 0 1 1.13-1.897l8.544-8.542Z"/><path d="M19.5 7.125 16.875 4.5"/><path d="M5.25 18.75h13.5"/></svg>
                    </button>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    {p.reason && (
                      <div className="inline-flex items-center gap-1.5 rounded-full border border-sky-200 bg-sky-50 px-2 py-1 text-[10px] font-medium text-sky-700 reason-chip-running">
                        <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
                          <path d="M12 3v3"/><path d="M18.364 5.636 16.95 7.05"/><path d="M21 12h-3"/><path d="m18.364 18.364-1.414-1.414"/><path d="M12 21v-3"/><path d="m7.05 16.95-1.414 1.414"/><path d="M6 12H3"/><path d="M7.05 7.05 5.636 5.636"/><circle cx="12" cy="12" r="3.5"/>
                        </svg>
                        <span>{reasonBadgeText(p.reason)}</span>
                      </div>
                    )}
                    {p.working_intent_count > 0 && (
                      <div className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-2 py-1 text-[10px] font-medium text-amber-700 intent-chip-running">
                        <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24"><path d="M12 6v6l4 2"/><circle cx="12" cy="12" r="8.5"/></svg>
                        <span>{workingIntentBadgeText(p.working_intent_count)}</span>
                      </div>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-3 text-[11px] text-slate-400">
                  <span className="flex items-center gap-1">
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M12 2v4m0 12v4m10-10h-4M6 12H2m15.07-7.07l-2.83 2.83M9.76 14.24l-2.83 2.83m11.14 0l-2.83-2.83M9.76 9.76L6.93 6.93"/></svg>
                    <span>{p.fact_count}</span>
                  </span>
                  <span className="flex items-center gap-1">
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24"><path d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3"/></svg>
                    <span>{p.intent_count}</span>
                  </span>
                  {p.working_intent_count > 0 && (
                    <span className="flex items-center gap-1 text-amber-500">
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M12 6v6l4 2"/><circle cx="12" cy="12" r="10"/></svg>
                      <span>{p.working_intent_count}</span>
                    </span>
                  )}
                  {p.unclaimed_intent_count > 0 && (
                    <span className="flex items-center gap-1 text-slate-400">
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3 2" viewBox="0 0 24 24">
                        <circle cx="12" cy="12" r="10" /><path d="M12 8v4m0 4h.01" />
                      </svg>
                      <span>{p.unclaimed_intent_count}</span>
                    </span>
                  )}
                  <span className="flex items-center gap-1">
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24"><path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 1 1 7.072 0l-.548.547A3.374 3.374 0 0 0 14 18.469V19a2 2 0 1 1-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547Z"/></svg>
                    <span>{p.hint_count}</span>
                  </span>
                </div>
                <div className="mt-1.5 flex items-center gap-1.5 text-[11px] text-slate-400">
                  <svg className="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.6" viewBox="0 0 24 24">
                    <path d="M8 2v3M16 2v3" /><path d="M3.5 9.5h17" /><rect x="3.5" y="4.5" width="17" height="16" rx="2.5" /><path d="M8 13h3M8 16h6" />
                  </svg>
                  <span>{formatDate(p.created_at)}</span>
                </div>
                <div className="mt-3 pt-3 border-t border-slate-100 flex items-center justify-end gap-1.5">
                  <div className="flex items-center justify-end gap-1.5 flex-wrap">
                    <button
                      onClick={(e) => { e.stopPropagation(); navigate(`/cairn/${p.id}`); }}
                      className="px-2 py-1 rounded-lg border border-slate-200 text-[11px] text-slate-500 hover:bg-slate-50 hover:text-slate-700 transition flex items-center gap-1"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><path d="M14.25 3H7.5A2.25 2.25 0 0 0 5.25 5.25v13.5A2.25 2.25 0 0 0 7.5 21h9a2.25 2.25 0 0 0 2.25-2.25V8.25L14.25 3Z"/><path d="M14.25 3v5.25h4.5"/><path d="M8.25 12h7.5M8.25 15h5.25"/></svg>
                      {t('buttons.snapshot')}
                    </button>
                    {p.status !== 'completed' && (
                      <button
                        onClick={(e) => { e.stopPropagation(); toggleStop(p); }}
                        className={`px-2 py-1 rounded-lg border text-[11px] transition flex items-center gap-1 ${
                          p.status === 'active'
                            ? 'border-amber-200 text-amber-600 hover:bg-amber-50'
                            : 'border-teal-200 text-teal-600 hover:bg-teal-50'
                        }`}
                      >
                        {p.status === 'active' ? (
                          <><svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24"><path d="M6 6h12v12H6z"/></svg>{t('buttons.stop')}</>
                        ) : (
                          <><svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24"><path d="m8 5 11 7-11 7V5Z"/></svg>{t('buttons.resume')}</>
                        )}
                      </button>
                    )}
                    {p.status === 'completed' && (
                      <button
                        onClick={(e) => { e.stopPropagation(); alert('Reopen not yet implemented in UI'); }}
                        className="px-2 py-1 rounded-lg border border-sky-200 text-[11px] text-sky-600 hover:bg-sky-50 transition flex items-center gap-1"
                      >
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 3-6.708"/><path d="M3 3v6h6"/></svg>
                        {t('buttons.reopen')}
                      </button>
                    )}
                    <button
                      onClick={(e) => { e.stopPropagation(); handleDelete(p); }}
                      className="px-2 py-1 rounded-lg border border-rose-200 text-[11px] text-rose-500 hover:bg-rose-50 hover:text-rose-600 transition flex items-center gap-1"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><path d="M3 6h18"/><path d="M8 6V4.75A1.75 1.75 0 0 1 9.75 3h4.5A1.75 1.75 0 0 1 16 4.75V6"/><path d="M19 6l-.63 11.338A2 2 0 0 1 16.37 19.5H7.63a2 2 0 0 1-1.997-2.162L5 6"/><path d="M10 10.5v5"/><path d="M14 10.5v5"/></svg>
                      {t('buttons.delete')}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {showNewProject && (
        <NewProjectModal
          onClose={() => setShowNewProject(false)}
          onCreated={(id) => { setShowNewProject(false); navigate(`/cairn/${id}`); }}
        />
      )}

      {showRename && (
        <RenameModal
          projectId={showRename.id}
          currentTitle={showRename.title}
          onClose={() => setShowRename(null)}
          onRenamed={(title) => handleRename(showRename.id, title)}
        />
      )}
    </div>
  );
}

function NewProjectModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const { t } = useTranslation('cairn');
  const [title, setTitle] = useState('');
  const [origin, setOrigin] = useState('');
  const [goal, setGoal] = useState('');
  const [hints, setHints] = useState<string[]>(['']);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.SyntheticEvent) {
    e.preventDefault();
    if (!title.trim() || !origin.trim() || !goal.trim()) {
      setError(t('errors.missingFields'));
      return;
    }
    setCreating(true);
    setError(null);
    try {
      const hintList = hints.filter((h) => h.trim()).map((h) => ({ content: h.trim(), creator: 'user' }));
      const project = await cairnApi.createProject({ title: title.trim(), origin: origin.trim(), goal: goal.trim(), hints: hintList.length > 0 ? hintList : undefined });
      onCreated(project.project.id);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || t('errors.createFailed'));
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center overlay" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg p-6 border border-slate-200/60 mx-4" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-base font-semibold text-slate-700 mb-4">{t('create.title')}</h3>
        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-brand-100 focus:border-brand-400 transition placeholder:text-slate-300"
            placeholder={t('form.renamePlaceholder')}
          />
          <textarea
            value={origin}
            onChange={(e) => setOrigin(e.target.value)}
            className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-brand-100 focus:border-brand-400 transition placeholder:text-slate-300"
            placeholder={t('form.originLabel')}
            rows={2}
          />
          <textarea
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-brand-100 focus:border-brand-400 transition placeholder:text-slate-300"
            placeholder={t('form.goalLabel')}
            rows={2}
          />
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-[11px] text-slate-400 font-medium uppercase tracking-wider">{t('form.hintsLabel')}</span>
              <button type="button" onClick={() => setHints([...hints, ''])} className="text-[11px] text-brand-500 hover:text-brand-600 font-medium">+ {t('buttons.add')}</button>
            </div>
            {hints.map((h, idx) => (
              <div key={idx} className="flex gap-2 mb-2">
                <input value={h} onChange={(e) => { const n = [...hints]; n[idx] = e.target.value; setHints(n); }} placeholder={t('form.hintContentPlaceholder')}
                  className="flex-1 px-3 py-1.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100 focus:border-brand-400 transition placeholder:text-slate-300" />
                {hints.length > 1 && (
                  <button type="button" onClick={() => setHints(hints.filter((_, i) => i !== idx))} className="px-2 text-slate-300 hover:text-red-400 transition text-sm">&times;</button>
                )}
              </div>
            ))}
            <p className="text-[11px] text-slate-400">{t('modals.createIntent.actor')}: <span className="font-medium text-slate-600">user</span></p>
          </div>
          {error && <p className="text-xs text-rose-600">{error}</p>}
          <div className="flex justify-end gap-2 mt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-slate-500 hover:bg-slate-50 rounded-xl transition">{t('buttons.cancel')}</button>
            <button type="submit" disabled={creating || !title.trim() || !origin.trim() || !goal.trim()} className="px-5 py-2 text-sm bg-brand-500 text-white rounded-xl font-medium hover:bg-brand-600 transition disabled:opacity-30 shadow-sm shadow-brand-200">
              {creating ? t('form.creating') : t('buttons.create')}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function RenameModal({
  projectId,
  currentTitle,
  onClose,
  onRenamed,
}: {
  projectId: string;
  currentTitle: string;
  onClose: () => void;
  onRenamed: (title: string) => void;
}) {
  const { t } = useTranslation('cairn');
  const [title, setTitle] = useState(currentTitle);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center overlay" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg p-6 border border-slate-200/60 mx-4" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-base font-semibold text-slate-700 mb-1">{t('modals.rename.title')}</h3>
        <p className="text-xs text-slate-400 mb-4"><span className="font-mono text-slate-500">{projectId}</span> — {currentTitle}</p>
        <div className="space-y-3">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && title.trim()) onRenamed(title.trim()); }}
            className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-brand-100 focus:border-brand-400 transition placeholder:text-slate-300"
            placeholder={t('form.renamePlaceholder')}
            autoFocus
          />
          <p className="text-[11px] text-slate-400">{t('modals.rename.help')}</p>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="px-4 py-2 text-sm text-slate-500 hover:bg-slate-50 rounded-xl transition">{t('buttons.cancel')}</button>
          <button onClick={() => { if (title.trim()) onRenamed(title.trim()); }} disabled={!title.trim()}
            className="px-5 py-2 text-sm bg-slate-800 text-white rounded-xl font-medium hover:bg-slate-900 transition disabled:opacity-30 shadow-sm">{t('buttons.save')}</button>
        </div>
      </div>
    </div>
  );
}