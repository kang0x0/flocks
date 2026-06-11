import { useState, useEffect, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, Play, Pause, RefreshCw, Plus, Lightbulb } from 'lucide-react';

import LoadingSpinner from '@/components/common/LoadingSpinner';
import dagAPI, { type GraphSnapshot, type TaskLog, type FactNode, type IntentEdge } from '@/api/dag';

interface Props {
  projectId: string;
  onBack: () => void;
}

// ---- Mermaid Graph Component ----

function MermaidGraph({ projectId }: { projectId: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [mermaidSrc, setMermaidSrc] = useState('');
  const [loading, setLoading] = useState(true);

  const fetchGraph = useCallback(async () => {
    try {
      const res = await dagAPI.getMermaid(projectId);
      setMermaidSrc(res.data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { fetchGraph(); }, [fetchGraph]);

  // Auto-refresh graph every 5s
  useEffect(() => {
    const timer = setInterval(fetchGraph, 5000);
    return () => clearInterval(timer);
  }, [fetchGraph]);

  // Render Mermaid as SVG
  useEffect(() => {
    if (!mermaidSrc || !containerRef.current) return;
    // Dynamic import mermaid
    const renderMermaid = async () => {
      try {
        const mermaid = (await import('mermaid')).default;
        mermaid.initialize({ startOnLoad: false, theme: 'default' });
        const { svg } = await mermaid.render('dag-graph-' + projectId, mermaidSrc);
        if (containerRef.current) {
          containerRef.current.innerHTML = svg;
        }
      } catch {
        if (containerRef.current) {
          containerRef.current.innerHTML = `<pre class="text-xs text-gray-500 p-4 overflow-auto">${mermaidSrc}</pre>`;
        }
      }
    };
    renderMermaid();
  }, [mermaidSrc, projectId]);

  if (loading) return <LoadingSpinner />;

  return (
    <div
      ref={containerRef}
      className="bg-white rounded-lg border border-gray-200 p-4 overflow-auto min-h-[300px] flex items-center justify-center"
    />
  );
}

// ---- Task Log Panel ----

function TaskLogPanel({ projectId }: { projectId: string }) {
  const { t } = useTranslation('dag');
  const [logs, setLogs] = useState<TaskLog[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchLogs = useCallback(async () => {
    try {
      const res = await dagAPI.listTaskLogs(projectId);
      setLogs(res.data.tasks || []);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { fetchLogs(); }, [fetchLogs]);

  if (loading) return <LoadingSpinner />;

  return (
    <div className="space-y-2 max-h-60 overflow-auto">
      {logs.length === 0 && (
        <p className="text-xs text-gray-400 py-4 text-center">{t('noProjects')}</p>
      )}
      {logs.map((log) => (
        <div key={log.id} className="flex items-center gap-3 text-xs bg-gray-50 rounded-lg px-3 py-2">
          <span className={`w-2 h-2 rounded-full ${
            log.status === 'completed' ? 'bg-green-400' :
            log.status === 'failed' ? 'bg-red-400' :
            log.status === 'timeout' ? 'bg-yellow-400' : 'bg-slate-400'
          }`} />
          <span className="font-medium text-gray-600 w-16">{log.task_type}</span>
          <span className="text-gray-400">{log.status}</span>
          <span className="text-gray-300">|</span>
          <span className="text-gray-400">{t('rounds')}: {log.rounds}</span>
          <span className="text-gray-300">|</span>
          <span className="text-gray-400">{t('toolCalls')}: {log.tool_calls_count}</span>
          {log.result_summary && (
            <span className="text-gray-400 truncate flex-1" title={log.result_summary}>
              {log.result_summary.slice(0, 60)}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

// ---- Fact/Intent List ----

function FactIntentList({ projectId }: { projectId: string }) {
  const { t } = useTranslation('dag');
  const [facts, setFacts] = useState<FactNode[]>([]);
  const [intents, setIntents] = useState<IntentEdge[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [fRes, iRes] = await Promise.all([
        dagAPI.listFacts(projectId),
        dagAPI.listIntents(projectId),
      ]);
      setFacts(fRes.data.facts || []);
      setIntents(iRes.data.intents || []);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  if (loading) return <LoadingSpinner />;

  return (
    <div className="space-y-3">
      {/* Facts */}
      <div>
        <h4 className="text-xs font-semibold text-gray-500 mb-2">{t('facts')} ({facts.length})</h4>
        <div className="space-y-1 max-h-40 overflow-auto">
          {facts.map((f) => (
            <div key={f.id} className="bg-slate-50 rounded px-3 py-1.5 text-xs">
              <span className="font-medium text-gray-800">{f.id}</span>
              <span className="text-gray-600 ml-2">[{f.fact_type}]</span>
              <span className="text-gray-600 ml-2">{f.content.slice(0, 80)}</span>
              {f.confidence < 1 && (
                <span className="text-gray-400 ml-2">({(f.confidence * 100).toFixed(0)}%)</span>
              )}
            </div>
          ))}
        </div>
      </div>
      {/* Intents */}
      <div>
        <h4 className="text-xs font-semibold text-gray-500 mb-2">{t('intents')} ({intents.length})</h4>
        <div className="space-y-1 max-h-40 overflow-auto">
          {intents.map((i) => (
            <div
              key={i.id}
              className={`rounded px-3 py-1.5 text-xs ${
                i.status === 'completed' ? 'bg-green-50' :
                i.status === 'open' ? 'bg-yellow-50' :
                i.status === 'failed' ? 'bg-red-50' : 'bg-gray-50'
              }`}
            >
              <span className="font-medium text-gray-700">{i.id}</span>
              <span className="text-gray-400 ml-2">[{i.status}]</span>
              <span className="text-gray-600 ml-2">{i.description.slice(0, 80)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ---- Add Hint Panel ----

function HintSection({ projectId }: { projectId: string }) {
  const { t } = useTranslation('dag');
  const [hintText, setHintText] = useState('');
  const [hints, setHints] = useState<{ id: string; content: string; hint_type: string }[]>([]);
  const [submitting, setSubmitting] = useState(false);

  const fetchHints = useCallback(async () => {
    try {
      const res = await dagAPI.listHints(projectId);
      setHints(res.data.hints || []);
    } catch { /* ignore */ }
  }, [projectId]);

  useEffect(() => { fetchHints(); }, [fetchHints]);

  const handleSubmit = async () => {
    if (!hintText.trim()) return;
    setSubmitting(true);
    try {
      await dagAPI.addHint(projectId, hintText, 'guidance');
      setHintText('');
      fetchHints();
    } catch {
      // ignore
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <input
          value={hintText}
          onChange={(e) => setHintText(e.target.value)}
          placeholder={t('hintPlaceholder')}
          className="flex-1 px-3 py-1.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-slate-400"
          onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
        />
        <button
          onClick={handleSubmit}
          disabled={submitting || !hintText.trim()}
          className="px-3 py-1.5 bg-red-600 text-white text-xs font-medium rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors"
        >
          <Lightbulb className="w-3 h-3" />
        </button>
      </div>
      {hints.length > 0 && (
        <div className="space-y-1 max-h-24 overflow-auto">
          {hints.map((h) => (
            <div key={h.id} className="text-xs text-gray-500 bg-yellow-50 rounded px-2 py-1">
              {h.content.slice(0, 100)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---- Main Detail Component ----

export default function ProjectDetail({ projectId, onBack }: Props) {
  const { t } = useTranslation('dag');
  const [snapshot, setSnapshot] = useState<GraphSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const fetchSnapshot = useCallback(async () => {
    try {
      const res = await dagAPI.getGraphSnapshot(projectId);
      setSnapshot(res.data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { fetchSnapshot(); }, [fetchSnapshot]);

  const handleToggleStatus = async () => {
    if (!snapshot) return;
    try {
      if (snapshot.status === 'active') {
        await dagAPI.stopProject(projectId);
      } else if (snapshot.status === 'stopped') {
        await dagAPI.resumeProject(projectId);
      }
      fetchSnapshot();
    } catch { /* ignore */ }
  };

  if (loading) return <LoadingSpinner />;
  if (error) return (
    <div className="flex flex-col items-center justify-center py-20 text-red-500 gap-2 text-sm">
      <p>{error}</p>
      <button onClick={fetchSnapshot} className="text-gray-600 hover:underline">{t('retry')}</button>
    </div>
  );

  const stats = snapshot?.statistics ?? {};

  return (
    <div className="flex flex-col h-full">
      {/* Top bar */}
      <div className="flex items-center gap-4 px-6 py-3 border-b border-gray-100 bg-white shrink-0">
        <button onClick={onBack} className="p-1 text-gray-400 hover:text-gray-600">
          <ArrowLeft className="w-5 h-5" />
        </button>
        <h2 className="font-semibold text-gray-900 flex-1">{snapshot?.project_title}</h2>
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <span>{t('facts')}: {stats.total_facts ?? 0}</span>
          <span className="text-gray-300">|</span>
          <span>{t('intents')}: {stats.total_intents ?? 0}</span>
        </div>
        <button
          onClick={fetchSnapshot}
          className="p-1 text-gray-400 hover:text-gray-600"
          title={t('refresh')}
        >
          <RefreshCw className="w-4 h-4" />
        </button>
        <button
          onClick={handleToggleStatus}
          className={`inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
            snapshot?.status === 'active'
              ? 'bg-yellow-50 text-yellow-700 hover:bg-yellow-100'
              : 'bg-green-50 text-green-700 hover:bg-green-100'
          }`}
        >
          {snapshot?.status === 'active' ? (
            <><Pause className="w-3 h-3" />{t('stopProject')}</>
          ) : (
            <><Play className="w-3 h-3" />{t('resumeProject')}</>
          )}
        </button>
      </div>

      {/* Content grid */}
      <div className="flex-1 overflow-auto p-6 space-y-4">
        {/* Graph */}
        <MermaidGraph projectId={projectId} />

        {/* Bottom panels */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">{t('facts')} & {t('intents')}</h3>
            <FactIntentList projectId={projectId} />
          </div>

          <div className="space-y-4">
            <div className="bg-white rounded-lg border border-gray-200 p-4">
              <h3 className="text-sm font-semibold text-gray-700 mb-3">{t('hints')}</h3>
              <HintSection projectId={projectId} />
            </div>
            <div className="bg-white rounded-lg border border-gray-200 p-4">
              <h3 className="text-sm font-semibold text-gray-700 mb-3">{t('taskLogs')}</h3>
              <TaskLogPanel projectId={projectId} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
