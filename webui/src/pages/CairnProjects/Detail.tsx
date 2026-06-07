import { useEffect, useState, useMemo, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams, useNavigate } from 'react-router-dom';
import cytoscape, { type Core, type EventObject } from 'cytoscape';
import dagre from 'cytoscape-dagre';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import { cairnApi, type ProjectDetail, type Fact, type Intent, type Hint, type SessionLogEntry } from '@/api/cairn';
import { sessionApi } from '@/api/session';
import type { Message, MessagePart } from '@/types';

cytoscape.use(dagre as any);

function formatTime(dateStr: string | null): string {
  if (!dateStr) return '-';
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

const FACT_COLORS: Record<string, string> = {
  origin: '#059669',
  goal: '#d97706',
};
const FACT_DEFAULT_COLOR = '#6366f1';

function intentStatusClass(intent: Intent): string {
  if (intent.concluded_at) return 'text-teal-600';
  if (intent.worker) return 'text-amber-600';
  return 'text-slate-400';
}

function intentStatusLabel(intent: Intent): string {
  if (intent.concluded_at) return 'Concluded';
  if (intent.worker) return 'In Progress';
  return 'Pending';
}

function getProducingIntent(factId: string, intents: Intent[]): Intent | undefined {
  return intents.find((i) => i.to === factId);
}

function reasonBadgeText(reason: { worker: string | null; trigger: string | null }): string {
  if (reason.trigger) return `${reason.worker} · ${reason.trigger}`;
  return reason.worker || 'Reasoning';
}

function summarizeFactLabel(fact: Fact): string {
  if (fact.id === 'origin') return 'Origin';
  if (fact.id === 'goal') return 'Goal';
  const normalized = fact.description.replace(/\s+/g, ' ').trim();
  const chars = Array.from(normalized);
  if (chars.length <= 24) return normalized || fact.id;
  return `${chars.slice(0, 24).join('')}…`;
}

function measureWrappedText(text: string, maxWidth: number, fontSize: number): { width: number; height: number } {
  const content = (text || '').trim() || ' ';
  const avgCharWidth = fontSize * 0.6;
  let maxLineWidth = 0;
  let lineWidth = 0;
  let lineCount = 1;

  for (const char of Array.from(content)) {
    if (char === '\n') {
      maxLineWidth = Math.max(maxLineWidth, lineWidth);
      lineWidth = 0;
      lineCount++;
      continue;
    }
    const charWidth = char === ' ' ? avgCharWidth * 0.4 : avgCharWidth * 0.85;
    if (lineWidth + charWidth > maxWidth) {
      maxLineWidth = Math.max(maxLineWidth, lineWidth);
      lineWidth = charWidth;
      lineCount++;
    } else {
      lineWidth += charWidth;
    }
  }
  maxLineWidth = Math.max(maxLineWidth, lineWidth);
  const lineHeight = fontSize * 1.4;
  return { width: Math.min(maxLineWidth, maxWidth), height: lineHeight * lineCount };
}

function factNodeSize(label: string, isOriginOrGoal: boolean): { width: number; height: number } {
  const preset = isOriginOrGoal
    ? { fontSize: 11, maxTextWidth: 92, minWidth: 58, minHeight: 38, paddingX: 10, paddingY: 10 }
    : { fontSize: 10, maxTextWidth: 116, minWidth: 52, minHeight: 34, paddingX: 10, paddingY: 10 };
  const measured = measureWrappedText(label, preset.maxTextWidth, preset.fontSize);
  return {
    width: Math.max(preset.minWidth, Math.ceil(measured.width + preset.paddingX * 2)),
    height: Math.max(preset.minHeight, Math.ceil(measured.height + preset.paddingY * 2)),
  };
}

interface TimelineEvent {
  id: string;
  type: 'project_created' | 'hint_added' | 'intent_declared' | 'intent_concluded' | 'project_completed' | 'reason_started' | 'intent_running';
  timestamp: string;
  actor: string;
  title: string;
  meta: string[];
}

function buildTimelineEvents(project: ProjectDetail | null): TimelineEvent[] {
  if (!project) return [];
  const events: TimelineEvent[] = [];

  events.push({
    id: `project-created-${project.project.id}`,
    type: 'project_created',
    timestamp: project.project.created_at,
    actor: 'system',
    title: project.project.title,
    meta: [],
  });

  for (const hint of project.hints) {
    events.push({
      id: `hint-${hint.id}`,
      type: 'hint_added',
      timestamp: hint.created_at,
      actor: hint.creator,
      title: hint.content,
      meta: [],
    });
  }

  for (const intent of project.intents) {
    events.push({
      id: `intent-declared-${intent.id}`,
      type: 'intent_declared',
      timestamp: intent.created_at,
      actor: intent.creator,
      title: intent.description,
      meta: [intent.id, `from ${intent.from.join(', ')}`],
    });

    if (!intent.concluded_at || !intent.to) continue;

    if (intent.to === 'goal') {
      events.push({
        id: `project-completed-${intent.id}`,
        type: 'project_completed',
        timestamp: intent.concluded_at,
        actor: intent.worker || intent.creator,
        title: intent.description,
        meta: [intent.id, `from ${intent.from.join(', ')}`],
      });
      continue;
    }

    events.push({
      id: `intent-concluded-${intent.id}`,
      type: 'intent_concluded',
      timestamp: intent.concluded_at,
      actor: intent.worker || intent.creator,
      title: intent.description,
      meta: [intent.id, `produced ${intent.to}`, `from ${intent.from.join(', ')}`],
    });
  }

  events.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  return events;
}

const TIMELINE_BADGE_LABELS: Record<string, string> = {
  project_created: 'Project',
  hint_added: 'Hint',
  reason_started: 'Reason',
  intent_declared: 'Intent',
  intent_running: 'Execute',
  intent_concluded: 'Conclude',
  project_completed: 'Complete',
};

const TIMELINE_BADGE_CLASSES: Record<string, string> = {
  project_created: 'bg-slate-100 text-slate-600',
  hint_added: 'bg-amber-50 text-amber-700',
  reason_started: 'bg-sky-50 text-sky-700',
  intent_declared: 'bg-violet-50 text-violet-700',
  intent_running: 'bg-amber-50 text-amber-700',
  intent_concluded: 'bg-teal-50 text-teal-700',
  project_completed: 'bg-rose-50 text-rose-700',
};

const TIMELINE_DOT_CLASSES: Record<string, string> = {
  project_created: 'bg-slate-400',
  hint_added: 'bg-amber-400',
  reason_started: 'bg-sky-400',
  intent_declared: 'bg-violet-400',
  intent_running: 'bg-amber-400',
  intent_concluded: 'bg-teal-400',
  project_completed: 'bg-rose-400',
};

function timelineBadgeLabel(type: string): string {
  return TIMELINE_BADGE_LABELS[type] || 'Event';
}

function timelineBadgeClass(type: string): string {
  return TIMELINE_BADGE_CLASSES[type] || 'bg-slate-100 text-slate-600';
}

function timelineDotClass(type: string): string {
  return TIMELINE_DOT_CLASSES[type] || 'bg-slate-300';
}

function formatTimestamp(ts: string): string {
  if (!ts) return '';
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatDateOnly(ts: string): string {
  if (!ts) return '';
  const d = new Date(ts);
  return d.toLocaleDateString([], { year: 'numeric', month: 'short', day: 'numeric' });
}

export default function CairnProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const { t } = useTranslation('cairn');
  const navigate = useNavigate();
  const cyRef = useRef<Core | null>(null);
  const cyContainerRef = useRef<HTMLDivElement>(null);
  const prevProjectRef = useRef('');

  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [sideTab, setSideTab] = useState<'detail' | 'hints' | 'log'>('detail');
  const [sidePanelWidth, setSidePanelWidth] = useState(360);
  const [isResizingPanel, setIsResizingPanel] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedNodeType, setSelectedNodeType] = useState<'fact' | 'intent' | null>(null);
  const [selectedFacts, setSelectedFacts] = useState<Set<string>>(new Set());
  const [layoutMode, setLayoutMode] = useState('dagre_tb');

  // Session log state
  const [sessionLogs, setSessionLogs] = useState<SessionLogEntry[]>([]);
  const [relatedSessionLogs, setRelatedSessionLogs] = useState<SessionLogEntry[]>([]);
  // Map from sessionId -> messages or 'loading' — inline expand
  const [expandedSessions, setExpandedSessions] = useState<Record<string, Message[] | 'loading'>>({});

  const loadProject = useCallback(async () => {
    if (!id) return;
    try {
      const data = await cairnApi.getProject(id);
      setProject(data);
      setError(null);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Failed to load project');
    }
  }, [id]);

  // Poll project data — matches original Cairn behavior (2s interval).
  // Only updates state when data actually changes to avoid unnecessary graph rebuilds.
  useEffect(() => {
    if (!id) return;
    const poll = async () => {
      try {
        const data = await cairnApi.getProject(id);
        const serialized = JSON.stringify(data);
        if (serialized !== prevProjectRef.current) {
          prevProjectRef.current = serialized;
          setProject(data);
          setError(null);
        }
      } catch { /* ignore */ }
    };
    const timer = setInterval(poll, 2000);
    return () => clearInterval(timer);
  }, [id]);

  // Load session logs when Log tab is active
  useEffect(() => {
    if (sideTab === 'log' && id) {
      cairnApi.getSessionLogs(id).then(setSessionLogs).catch(() => setSessionLogs([]));
    }
  }, [sideTab, id]);

  // Load related session logs when fact/intent is selected
  useEffect(() => {
    if (!id || !selectedNodeType || !selectedNodeId) {
      setRelatedSessionLogs([]);
      return;
    }
    const load = async () => {
      try {
        const logs = selectedNodeType === 'intent'
          ? await cairnApi.getIntentSessionLogs(id, selectedNodeId)
          : await cairnApi.getFactSessionLogs(id, selectedNodeId);
        setRelatedSessionLogs(logs);
      } catch { setRelatedSessionLogs([]); }
    };
    load();
  }, [id, selectedNodeType, selectedNodeId]);

  // Toggle inline session messages expand/collapse
  const handleToggleSession = useCallback(async (sessionId: string) => {
    // If already expanded, collapse; otherwise start loading
    const shouldFetch = await new Promise<boolean>((resolve) => {
      setExpandedSessions((prev) => {
        if (sessionId in prev) {
          const next = { ...prev };
          delete next[sessionId];
          resolve(false);
          return next;
        }
        resolve(true);
        return { ...prev, [sessionId]: 'loading' };
      });
    });

    if (!shouldFetch) return;

    try {
      const rawData = await sessionApi.getMessages(sessionId);
      const transformed = (Array.isArray(rawData) ? rawData : []).map((item: any) => {
        const info = item.info || item;
        return {
          ...info,
          parts: item.parts || info.parts || [],
        };
      });
      setExpandedSessions((prev) => {
        if (!(sessionId in prev)) return prev;
        return { ...prev, [sessionId]: transformed };
      });
    } catch {
      setExpandedSessions((prev) => {
        if (!(sessionId in prev)) return prev;
        return { ...prev, [sessionId]: [] };
      });
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    loadProject().finally(() => setLoading(false));
  }, [loadProject]);

  const { facts, intents, hints } = useMemo(() => {
    if (!project) return { facts: [] as Fact[], intents: [] as Intent[], hints: [] as Hint[] };
    return {
      facts: project.facts,
      intents: project.intents,
      hints: project.hints,
    };
  }, [project]);

  const meta = project?.project;

  const concludedIntents = useMemo(() => intents.filter((i) => i.to), [intents]);

  const cytoscapeElements = useMemo(() => {
    const elements: cytoscape.ElementDefinition[] = [];
    const hasOrigin = facts.some((f) => f.id === 'origin');
    const hasGoal = facts.some((f) => f.id === 'goal');

    for (const f of facts) {
      const color = FACT_COLORS[f.id] || FACT_DEFAULT_COLOR;
      const isOrigin = f.id === 'origin';
      const isGoal = f.id === 'goal';
      const label = summarizeFactLabel(f);
      const size = factNodeSize(label, isOrigin || isGoal);
      elements.push({
        data: {
          id: f.id,
          type: 'fact',
          nodeType: isOrigin ? 'origin' : isGoal ? 'goal' : 'fact',
          label,
          description: f.description,
          color,
          isOrigin,
          isGoal,
          width: size.width,
          height: size.height,
        },
      });
    }

    // Hidden layout-only edge from origin to goal to ensure dagre places
    // them in different ranks (origin at top, goal at bottom).
    // Matches the original Cairn's pattern of having a path from origin to goal
    // through bootstrap intents.
    if (hasOrigin && hasGoal) {
      elements.push({
        data: {
          id: '_layout_origin_goal',
          source: 'origin',
          target: 'goal',
          isLayoutEdge: true,
        },
        classes: 'layout-edge',
      });
    }

    // Hidden layout edges from non-origin-goal facts to goal,
    // ensuring dagre places them between origin and goal (not on the same row as goal).
    // Without these, a bootstrap-produced fact would have origin→fact edge
    // but no path to goal, causing dagre to put fact and goal on the same rank.
    if (hasGoal) {
      for (const f of facts) {
        if (f.id !== 'origin' && f.id !== 'goal') {
          const hasEdgeToGoal = concludedIntents.some(
            (intent) => intent.from.includes(f.id) && intent.to === 'goal',
          );
          if (!hasEdgeToGoal) {
            elements.push({
              data: {
                id: `_layout_${f.id}_goal`,
                source: f.id,
                target: 'goal',
                isLayoutEdge: true,
              },
              classes: 'layout-edge',
            });
          }
        }
      }
    }

    for (const intent of concludedIntents) {
      for (const from of intent.from) {
        const isBootstrap = intent.description === 'bootstrap' && intent.creator === 'dispatcher.bootstrap' && from === 'origin';
        elements.push({
          data: {
            id: `edge-${intent.id}-${from}`,
            source: from,
            target: intent.to!,
            intentId: intent.id,
            description: intent.description,
            status: 'concluded',
            label: intent.description || '',
          },
        });
      }
    }

    for (const intent of intents) {
      if (!intent.to) {
        const isBootstrap = intent.description === 'bootstrap' && intent.creator === 'dispatcher.bootstrap' && intent.from.length === 1 && intent.from[0] === 'origin';
        const nodeType = isBootstrap
          ? (intent.worker ? 'bootstrap_running' : 'bootstrap_pending')
          : (intent.worker ? 'in_progress' : 'unclaimed');
        const label = isBootstrap ? 'Bootstrap' : '?';
        const size = isBootstrap
          ? { width: Math.max(58, Math.ceil(Array.from('Bootstrap').length * 10 * 0.6 + 24)), height: Math.max(34, Math.ceil(14 + 16)) }
          : { width: 20, height: 20 };
        elements.push({
          data: {
            id: intent.id,
            type: 'intent',
            nodeType,
            label,
            description: intent.description,
            creator: intent.creator,
            worker: intent.worker,
            from: intent.from,
            concluded: !!intent.concluded_at,
            width: size.width,
            height: size.height,
          },
        });
        // Bootstrap scope edge from bootstrap intent to goal (matching original Cairn)
        // This creates a visual path: origin → bootstrap → goal
        if (isBootstrap && hasGoal) {
          elements.push({
            data: {
              id: `edge-bootstrap-${intent.id}-goal`,
              source: intent.id,
              target: 'goal',
              intentId: intent.id,
              isBootstrapScope: true,
            },
            classes: 'bootstrap-scope',
          });
        }
        for (const from of intent.from) {
          elements.push({
            data: {
              id: `edge-from-${intent.id}-${from}`,
              source: from,
              target: intent.id,
              intentId: intent.id,
              status: nodeType,
              label: intent.description || '',
            },
          });
        }
        // Hidden layout edges from non-bootstrap unclaimed intents to goal,
        // ensuring dagre places intent nodes between origin and goal (not same rank).
        // Without these, an intent with origin as source would share the same dagre
        // rank as goal (since both have only incoming edges from origin).
        if (!isBootstrap && hasGoal) {
          elements.push({
            data: {
              id: `_layout_intent_${intent.id}_goal`,
              source: intent.id,
              target: 'goal',
              isLayoutEdge: true,
            },
            classes: 'layout-edge',
          });
        }
      }
    }

    return elements;
  }, [facts, concludedIntents, intents]);

  useEffect(() => {
    if (!cyContainerRef.current || cytoscapeElements.length === 0) return;

    if (cyRef.current) {
      // === INCREMENTAL UPDATE — no dagre layout to preserve user-dragged positions ===
      // Matches original Cairn's updateGraph pattern but skips the layout call.

      const wantNodeIds = new Set<string>();
      const wantEdgeIds = new Set<string>();
      for (const el of cytoscapeElements) {
        const id = el.data.id as string;
        if (id) {
          if (el.data.source) wantEdgeIds.add(id);
          else wantNodeIds.add(id);
        }
      }

      // Snapshot positions before any changes (like original Cairn's snapshotNodePositions)
      const previousPositions = new Map<string, { x: number; y: number }>();
      cyRef.current.nodes().forEach((n) => {
        previousPositions.set(n.id(), { x: n.position('x'), y: n.position('y') });
      });

      const isLR = layoutMode.endsWith('lr');

      // Like original Cairn's anchorPositionFromIds
      function anchorPositionFromIds(nodeIds: string[], offset: number): { x: number; y: number } | null {
        const anchors: { x: number; y: number }[] = [];
        for (const nodeId of nodeIds) {
          const existing = cyRef.current!.getElementById(nodeId);
          if (existing.length > 0) {
            anchors.push({ x: existing.position('x'), y: existing.position('y') });
            continue;
          }
          const prev = previousPositions.get(nodeId);
          if (prev) anchors.push(prev);
        }
        if (anchors.length === 0) return null;
        const avgX = anchors.reduce((s, p) => s + p.x, 0) / anchors.length;
        const avgY = anchors.reduce((s, p) => s + p.y, 0) / anchors.length;
        return isLR
          ? { x: avgX + offset, y: avgY }
          : { x: avgX, y: avgY + offset };
      }

      let nodeAdded = false;

      // Remove stale nodes
      cyRef.current.nodes().forEach((n) => {
        if (!wantNodeIds.has(n.id())) n.remove();
      });
      // Remove stale edges
      cyRef.current.edges().forEach((e) => {
        if (!wantEdgeIds.has(e.id())) e.remove();
      });

      // Process nodes — add new ones with anchor-based positions, update existing data
      for (const el of cytoscapeElements) {
        if (el.data.source) continue;
        const nid = el.data.id as string;
        if (!nid) continue;
        const ex = cyRef.current.getElementById(nid);
        if (ex.length === 0) {
          // New node — calculate initial position like original Cairn's initialPositionForNode
          let pos: { x: number; y: number } | null = null;

          // For intent nodes, anchor from their source facts
          const from = el.data.from as string[] | undefined;
          if (from && from.length > 0) {
            pos = anchorPositionFromIds(from, 60);
          }

          // For fact nodes produced by a concluded intent, anchor from the intent's sources
          if (!pos && !from) {
            const producingIntent = intents.find((i) => i.to === nid);
            if (producingIntent && producingIntent.from.length > 0) {
              pos = anchorPositionFromIds(producingIntent.from, 70);
            }
          }

          cyRef.current.add(pos ? { ...el, position: pos } : el);
          nodeAdded = true;
        } else if (
          ex.data('nodeType') !== el.data.nodeType ||
          ex.data('label') !== el.data.label ||
          ex.data('worker') !== el.data.worker
        ) {
          ex.data(el.data);
        }
      }

      // Process edges — new edges get a temporary "edge-new" class
      // so they can fade in via the edge.edge-new style (opacity: 0 → 1).
      let edgeAdded = false;
      const newEdgeIds: string[] = [];
      for (const el of cytoscapeElements) {
        if (!el.data.source) continue;
        const eid = el.data.id as string;
        if (!eid) continue;
        const ex = cyRef.current.getElementById(eid);
        if (ex.length === 0) {
          const elWithClass = {
            ...el,
            classes: `${el.classes || ''} edge-new`.trim(),
          };
          cyRef.current.add(elWithClass);
          newEdgeIds.push(eid);
          edgeAdded = true;
        }
      }
      // Fade in new edges after a brief delay (after layout animation starts)
      if (edgeAdded) {
        setTimeout(() => {
          const cy = cyRef.current;
          if (!cy) return;
          for (const eid of newEdgeIds) {
            cy.getElementById(eid).removeClass('edge-new');
          }
        }, 100);
      }

      // Run dagre layout when new nodes are added to properly position them.
      // Without this, new intent and fact nodes are only anchor-positioned
      // (simple offset from source), which places them on the same rank as
      // their source — e.g. new "?" intents appear on the same row as origin.
      if (nodeAdded) {
        const [name, dir] = layoutMode.split('_');
        cyRef.current.layout({
          name: 'dagre',
          rankDir: dir === 'lr' ? 'LR' : 'TB',
          nodeSep: 60,
          rankSep: 80,
          padding: 50,
          fit: true,
          animate: true,
          animationDuration: 300,
        } as any).run();
      }

      // Start edge flow animation for in_progress and bootstrap_running edges,
      // matching original Cairn's animated dash-offset effect.
      startEdgeFlowAnimation(cyRef.current);
      return;
    }

    const commonFactStyle = {
      'text-valign': 'center',
      'text-halign': 'center',
      'font-family': '-apple-system, BlinkMacSystemFont, Inter, sans-serif',
      color: '#fff',
      'font-weight': 'bold',
      'text-wrap': 'wrap',
      'text-overflow-wrap': 'anywhere',
      'border-width': 0,
    };

    const cy = cytoscape({
      container: cyContainerRef.current,
      elements: cytoscapeElements,
      style: [
        {
          selector: 'node[nodeType="origin"]',
          style: {
            ...commonFactStyle,
            shape: 'round-rectangle',
            'background-color': '#14b8a6',
            label: 'data(label)',
            'font-size': '11px',
            'text-max-width': '92px',
            width: 'data(width)',
            height: 'data(height)',
          },
        },
        {
          selector: 'node[nodeType="goal"]',
          style: {
            ...commonFactStyle,
            shape: 'round-rectangle',
            'background-color': '#f43f5e',
            label: 'data(label)',
            'font-size': '11px',
            'text-max-width': '92px',
            width: 'data(width)',
            height: 'data(height)',
          },
        },
        {
          selector: 'node[nodeType="fact"]',
          style: {
            ...commonFactStyle,
            shape: 'round-rectangle',
            'background-color': '#6366f1',
            label: 'data(label)',
            'font-size': '10px',
            'text-max-width': '116px',
            width: 'data(width)',
            height: 'data(height)',
          },
        },
        {
          selector: 'node[nodeType="in_progress"]',
          style: {
            'text-valign': 'center',
            'text-halign': 'center',
            'font-family': '-apple-system, BlinkMacSystemFont, Inter, sans-serif',
            shape: 'round-rectangle',
            'background-color': '#fbbf24',
            label: 'data(label)',
            color: '#92400e',
            'font-size': '10px',
            'font-weight': 'bold',
            width: 'data(width)',
            height: 'data(height)',
            'border-width': 2,
            'border-color': '#f59e0b',
            'text-wrap': 'wrap',
            'text-max-width': '70px',
          },
        },
        {
          selector: 'node[nodeType="unclaimed"]',
          style: {
            'text-valign': 'center',
            'text-halign': 'center',
            'font-family': '-apple-system, BlinkMacSystemFont, Inter, sans-serif',
            shape: 'ellipse',
            'background-color': '#cbd5e1',
            'background-opacity': 0.5,
            label: '?',
            color: '#94a3b8',
            'font-size': '11px',
            'font-weight': 'bold',
            width: 20,
            height: 20,
            'border-width': 1.5,
            'border-color': '#94a3b8',
            'border-style': 'dashed',
          },
        },
        {
          selector: 'node[nodeType="bootstrap_pending"]',
          style: {
            'text-valign': 'center',
            'text-halign': 'center',
            'font-family': '-apple-system, BlinkMacSystemFont, Inter, sans-serif',
            shape: 'round-rectangle',
            'background-color': '#fff7ed',
            'background-opacity': 0.96,
            label: 'data(label)',
            color: '#c2410c',
            'font-size': '10px',
            'font-weight': 'bold',
            width: 'data(width)',
            height: 'data(height)',
            'border-width': 1.5,
            'border-color': '#fdba74',
            'border-style': 'dashed',
            'text-wrap': 'wrap',
            'text-max-width': '70px',
          },
        },
        {
          selector: 'node[nodeType="bootstrap_running"]',
          style: {
            'text-valign': 'center',
            'text-halign': 'center',
            'font-family': '-apple-system, BlinkMacSystemFont, Inter, sans-serif',
            shape: 'round-rectangle',
            'background-color': '#fb923c',
            'background-opacity': 0.96,
            label: 'data(label)',
            color: '#fff7ed',
            'font-size': '10px',
            'font-weight': 'bold',
            width: 'data(width)',
            height: 'data(height)',
            'border-width': 2,
            'border-color': '#ea580c',
            'text-wrap': 'wrap',
            'text-max-width': '70px',
          },
        },
        {
          selector: 'edge',
          style: {
            'transition-property': 'opacity, line-color, width',
            'transition-duration': '0.6s',
            'transition-timing-function': 'ease-in-out',
          },
        },
        {
          selector: 'edge.edge-new',
          style: {
            opacity: 0,
            width: 0,
          },
        },
        // edge status styles (matching original Cairn patterns)
        {
          selector: 'edge[status="concluded"]',
          style: {
            width: 2,
            'line-color': '#6ee7b7',
            'target-arrow-color': '#6ee7b7',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            label: 'data(label)',
            'font-size': '7px',
            color: '#94a3b8',
            'text-rotation': 'autorotate',
            'text-margin-y': -9,
            'text-max-width': '80px',
            'text-wrap': 'ellipsis',
            'text-background-color': '#f8fafc',
            'text-background-opacity': 0.85,
            'text-background-padding': '2px',
            'text-events': 'yes',
            'arrow-scale': 0.9,
          },
        },
        {
          selector: 'edge[status="in_progress"]',
          style: {
            width: 2,
            'line-color': '#fbbf24',
            'line-style': 'dashed',
            'line-dash-pattern': [8, 4],
            'line-dash-offset': 0,
            'target-arrow-color': '#fbbf24',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            label: 'data(label)',
            'font-size': '7px',
            color: '#b45309',
            'text-rotation': 'autorotate',
            'text-margin-y': -9,
            'text-max-width': '80px',
            'text-wrap': 'ellipsis',
            'text-background-color': '#fffbeb',
            'text-background-opacity': 0.85,
            'text-background-padding': '2px',
            'text-events': 'yes',
            'arrow-scale': 0.9,
          },
        },
        {
          selector: 'edge[status="unclaimed"]',
          style: {
            width: 1.5,
            'line-color': '#cbd5e1',
            'line-style': 'dashed',
            'line-dash-pattern': [5, 5],
            'target-arrow-color': '#cbd5e1',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            label: 'data(label)',
            'font-size': '7px',
            color: '#94a3b8',
            'text-rotation': 'autorotate',
            'text-margin-y': -9,
            'text-max-width': '80px',
            'text-wrap': 'ellipsis',
            'text-background-color': '#f8fafc',
            'text-background-opacity': 0.85,
            'text-background-padding': '2px',
            'text-events': 'yes',
            'arrow-scale': 0.7,
          },
        },
        {
          selector: 'edge[status="bootstrap_pending"]',
          style: {
            width: 2,
            'line-color': '#fdba74',
            'line-style': 'dashed',
            'line-dash-pattern': [8, 4],
            'line-dash-offset': 0,
            'target-arrow-color': '#fdba74',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            label: 'data(label)',
            'font-size': '7px',
            color: '#c2410c',
            'text-rotation': 'autorotate',
            'text-margin-y': -9,
            'text-max-width': '88px',
            'text-wrap': 'ellipsis',
            'text-background-color': '#fff7ed',
            'text-background-opacity': 0.92,
            'text-background-padding': '2px',
            'text-events': 'yes',
            'arrow-scale': 0.85,
          },
        },
        {
          selector: 'edge[status="bootstrap_running"]',
          style: {
            width: 2.5,
            'line-color': '#fb923c',
            'line-style': 'dashed',
            'line-dash-pattern': [10, 4],
            'line-dash-offset': 0,
            'target-arrow-color': '#fb923c',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            label: 'data(label)',
            'font-size': '7px',
            color: '#c2410c',
            'text-rotation': 'autorotate',
            'text-margin-y': -9,
            'text-max-width': '88px',
            'text-wrap': 'ellipsis',
            'text-background-color': '#fff7ed',
            'text-background-opacity': 0.92,
            'text-background-padding': '2px',
            'text-events': 'yes',
            'arrow-scale': 0.95,
          },
        },
        {
          selector: 'edge.layout-edge',
          style: {
            opacity: 0,
            width: 0,
          },
        },
        {
          selector: 'edge.bootstrap-scope',
          style: {
            label: '',
            width: 1.8,
            'curve-style': 'bezier',
            'line-style': 'dotted',
            'line-dash-pattern': [2, 5],
            'target-arrow-shape': 'triangle-backcurve',
            'arrow-scale': 0.75,
            'target-distance-from-node': 2,
          },
        },
        {
          selector: 'node:selected',
          style: {
            'border-width': 3,
            'border-color': '#f59e0b',
            'shadow-blur': 10,
            'shadow-color': '#f59e0b',
            'shadow-opacity': 0.4,
          } as any,
        },
      ],
      layout: { name: 'grid' },
      wheelSensitivity: 0.3,
      minZoom: 0.2,
      maxZoom: 3,
    });

    cy.on('tap', 'node', (evt: EventObject) => {
      const node = evt.target;
      const type = node.data('type');
      const nid = node.id();
      if (type === 'fact') {
        setSelectedNodeType('fact');
        setSelectedNodeId(nid);
        if (evt.originalEvent?.shiftKey) {
          setSelectedFacts((prev) => {
            const next = new Set(prev);
            if (next.has(nid)) next.delete(nid);
            else next.add(nid);
            return next;
          });
        } else {
          setSelectedFacts(new Set([nid]));
        }
      } else if (type === 'intent') {
        setSelectedNodeType('intent');
        setSelectedNodeId(nid);
        setSelectedFacts(new Set());
      }
    });

    cy.on('tap', (evt: EventObject) => {
      if (evt.target === cy) {
        setSelectedNodeId(null);
        setSelectedNodeType(null);
        setSelectedFacts(new Set());
      }
    });

    cyRef.current = cy;
    applyLayout(cy, layoutMode);

    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [cytoscapeElements]);

  useEffect(() => {
    if (cyRef.current) {
      applyLayout(cyRef.current, layoutMode);
    }
  }, [layoutMode]);

  function startEdgeFlowAnimation(cy: Core) {
    if (!cy || cy.destroyed()) return;
    cy.edges('[status="in_progress"], [status="bootstrap_running"]').forEach(edge => {
      if (edge.scratch('_flowActive')) return;
      edge.scratch('_flowActive', true);
      const isBootstrap = edge.data('status') === 'bootstrap_running';
      const dashOffset = isBootstrap ? -16 : -12;
      const flow = () => {
        if (!edge.inside() || !['in_progress', 'bootstrap_running'].includes(edge.data('status') as string)) {
          edge.removeScratch('_flowActive');
          return;
        }
        edge.animate({ style: { 'line-dash-offset': dashOffset } } as any, {
          duration: isBootstrap ? 620 : 700,
          complete: () => {
            if (!edge.inside() || !['in_progress', 'bootstrap_running'].includes(edge.data('status') as string)) {
              edge.removeScratch('_flowActive');
              return;
            }
            edge.style('line-dash-offset', 0);
            flow();
          },
        });
      };
      flow();
    });
  }

  function applyLayout(cy: Core, mode: string) {
    const [name, dir] = mode.split('_');
    const isLR = dir === 'lr';
    cy.layout({
      name: 'dagre',
      rankDir: isLR ? 'LR' : 'TB',
      nodeSep: 60,
      rankSep: 80,
      padding: 50,
      fit: true,
      animate: false,
    } as any).run();
    startEdgeFlowAnimation(cy);
  }

  function fitGraph() {
    if (cyRef.current) {
      cyRef.current.fit(undefined, 40);
      cyRef.current.center();
    }
  }

  const selectedFactRecord = useCallback(() => {
    if (selectedNodeType !== 'fact' || !selectedNodeId) return null;
    return facts.find((f) => f.id === selectedNodeId) || null;
  }, [selectedNodeType, selectedNodeId, facts]);

  const selectedIntentRecord = useCallback(() => {
    if (selectedNodeType !== 'intent' || !selectedNodeId) return null;
    return intents.find((i) => i.id === selectedNodeId) || null;
  }, [selectedNodeType, selectedNodeId, intents]);

  const selectedFactRecords = useCallback(() => {
    return facts.filter((f) => selectedFacts.has(f.id));
  }, [facts, selectedFacts]);

  const actorName = 'user';

  const selectedOpenIntentRecord = useCallback(() => {
    if (selectedNodeType !== 'intent' || !selectedNodeId) return null;
    const intent = intents.find((i) => i.id === selectedNodeId);
    if (!intent || intent.to) return null;
    return intent;
  }, [selectedNodeType, selectedNodeId, intents]);

  const selectedActionableOpenIntentRecord = useCallback(() => {
    const intent = selectedOpenIntentRecord();
    if (!intent) return null;
    return !intent.worker || intent.worker === actorName ? intent : null;
  }, [selectedOpenIntentRecord]);

  const selectedReleasableOpenIntentRecord = useCallback(() => {
    const intent = selectedOpenIntentRecord();
    if (!intent?.worker) return null;
    return intent.worker === actorName ? intent : null;
  }, [selectedOpenIntentRecord]);

  const selectedIntentPrimaryActionLabel = useCallback(() => {
    const intent = selectedOpenIntentRecord();
    if (!intent || !intent.worker) return t('detail.actions.claim');
    return intent.worker === actorName ? t('detail.actions.heartbeat') : t('detail.actions.claimed');
  }, [selectedOpenIntentRecord, t]);

  const isActive = meta?.status === 'active';
  const isCompleted = meta?.status === 'completed';
  const showReasonPanel = meta?.reason && isActive;

  async function handleDispatch() {
    if (!id) return;
    try {
      await cairnApi.dispatchProject(id);
      await loadProject();
    } catch (err: any) {
      alert(err?.response?.data?.detail || err.message || 'Failed to dispatch');
    }
  }

  async function handleStop() {
    if (!id) return;
    try {
      await cairnApi.updateProjectStatus(id, 'stopped');
      await loadProject();
    } catch (err: any) {
      alert(err?.response?.data?.detail || err.message || 'Failed to stop project');
    }
  }

  async function handleResume() {
    if (!id) return;
    try {
      await cairnApi.updateProjectStatus(id, 'active');
      await loadProject();
    } catch (err: any) {
      alert(err?.response?.data?.detail || err.message || 'Failed to resume project');
    }
  }

  async function handleDelete() {
    if (!id) return;
    if (!confirm('Delete this project? This action cannot be undone.')) return;
    try {
      await cairnApi.deleteProject(id);
      navigate('/cairn');
    } catch (err: any) {
      alert(err?.response?.data?.detail || err.message || 'Failed to delete');
    }
  }

  function handleComplete() {
    if (!id || !project) return;
    setShowCompleteModal(true);
  }

  async function handleReopen() {
    if (!id) return;
    const description = prompt('Reopen feedback/description:');
    if (!description) return;
    try {
      await cairnApi.reopenProject(id, { description, creator: 'user' });
      await loadProject();
    } catch (err: any) {
      alert(err?.response?.data?.detail || err.message || 'Failed to reopen');
    }
  }

  const [showHintModal, setShowHintModal] = useState(false);
  const [showCompleteModal, setShowCompleteModal] = useState(false);
  const [showIntentModal, setShowIntentModal] = useState(false);
  const [showConcludeModal, setShowConcludeModal] = useState(false);
  const [showSnapshotModal, setShowSnapshotModal] = useState(false);
  const [snapshotContent, setSnapshotContent] = useState('');
  const [snapshotLoading, setSnapshotLoading] = useState(false);

  async function handleIntentHeartbeat() {
    const intent = selectedActionableOpenIntentRecord();
    if (!intent || !id) return;
    try {
      await cairnApi.heartbeatIntent(id, intent.id, { worker: actorName });
      await loadProject();
    } catch (err: any) {
      alert(err?.response?.data?.detail || 'Failed to claim/heartbeat intent');
    }
  }

  async function handleIntentRelease() {
    const intent = selectedReleasableOpenIntentRecord();
    if (!intent || !id) return;
    try {
      await cairnApi.releaseIntent(id, intent.id, { worker: actorName });
      await loadProject();
    } catch (err: any) {
      alert(err?.response?.data?.detail || 'Failed to release intent');
    }
  }

  function handleOpenConclude() {
    const intent = selectedActionableOpenIntentRecord();
    if (!intent) return;
    setShowConcludeModal(true);
  }

  async function handleConcludeIntent(description: string) {
    const intent = selectedActionableOpenIntentRecord();
    if (!intent || !id || !description.trim()) return;
    try {
      await cairnApi.concludeIntent(id, intent.id, { worker: actorName, description: description.trim() });
      await loadProject();
      setShowConcludeModal(false);
    } catch (err: any) {
      alert(err?.response?.data?.detail || 'Failed to conclude intent');
    }
  }

  async function handleSnapshot() {
    if (!id) return;
    setSnapshotLoading(true);
    try {
      const yaml = await cairnApi.exportProject(id, 'yaml');
      setSnapshotContent(yaml);
      setShowSnapshotModal(true);
    } catch (err: any) {
      alert(err?.response?.data?.detail || err.message || 'Failed to export snapshot');
    } finally {
      setSnapshotLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  if (error || !project || !meta) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="max-w-md text-center">
          <button onClick={() => navigate('/cairn')} className="inline-flex items-center text-sm text-slate-500 hover:text-slate-700 mb-4 transition">
            <svg className="w-4 h-4 mr-1" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M15 19l-7-7 7-7"/></svg>
            {t('buttons.backToList')}
          </button>
          <div className="flex items-center gap-2 p-4 bg-rose-50 border border-rose-200 rounded-xl text-rose-700 text-sm">
            <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 8v4m0 4h.01"/></svg>
            {error || 'Project not found'}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-hidden bg-slate-50">
      <header className="bg-white/80 backdrop-blur border-b border-slate-200/60 px-4 py-2.5 flex items-center gap-3 shrink-0 z-20">
        <button onClick={() => navigate('/cairn')} className="p-1.5 rounded-lg hover:bg-slate-100 transition text-slate-400 hover:text-slate-600">
          <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M15 19l-7-7 7-7"/></svg>
        </button>
        <div className="title-action-trigger flex items-center gap-2 min-w-0">
          <span className="text-[11px] font-mono text-slate-400">{meta.id}</span>
          <h2 className="text-[15px] font-semibold text-slate-700 truncate">{meta.title}</h2>
          <span className={`px-1.5 py-0.5 rounded-full text-[9px] font-semibold uppercase tracking-[0.12em] shrink-0 border ${
            isActive ? 'bg-teal-50 text-teal-700 border-teal-200' :
            isCompleted ? 'bg-slate-100 text-slate-500 border-slate-200' :
            'bg-amber-50 text-amber-700 border-amber-200'
          }`}>
            {meta.status}
          </span>
        </div>
        <div className="flex-1" />
        <div className="flex items-center gap-4 text-xs text-slate-400">
          <span>{t('stats.facts', { count: facts.length })}</span>
          <span>{t('stats.intents', { count: intents.length })}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <button onClick={handleSnapshot} disabled={snapshotLoading} className="px-2.5 py-1 rounded-lg border border-slate-200 text-xs text-slate-500 hover:bg-slate-50 hover:text-slate-700 transition flex items-center gap-1.5">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><path d="M14.25 3H7.5A2.25 2.25 0 0 0 5.25 5.25v13.5A2.25 2.25 0 0 0 7.5 21h9a2.25 2.25 0 0 0 2.25-2.25V8.25L14.25 3Z"/><path d="M14.25 3v5.25h4.5"/><path d="M8.25 12h7.5M8.25 15h5.25"/></svg>
            {snapshotLoading ? t('detail.exporting') : t('buttons.snapshot')}
          </button>
          {!isCompleted && (
            <button onClick={isActive ? handleStop : handleResume}
              className={`px-2.5 py-1 rounded-lg border text-xs transition flex items-center gap-1.5 ${
                isActive
                  ? 'border-amber-200 text-amber-600 hover:bg-amber-50'
                  : 'border-teal-200 text-teal-600 hover:bg-teal-50'
              }`}>
              {isActive ? (
                <><svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.9" viewBox="0 0 24 24"><path d="M6 6h12v12H6z"/></svg>{t('buttons.stop')}</>
              ) : (
                <><svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.9" viewBox="0 0 24 24"><path d="m8 5 11 7-11 7V5Z"/></svg>{t('buttons.resume')}</>
              )}
            </button>
          )}
          {isCompleted && (
            <button onClick={handleReopen} className="px-2.5 py-1 rounded-lg border border-sky-200 text-xs text-sky-600 hover:bg-sky-50 transition flex items-center gap-1.5">
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 3-6.708"/><path d="M3 3v6h6"/></svg>
              {t('buttons.reopen')}
            </button>
          )}
          <button onClick={handleDelete} className="px-2.5 py-1 rounded-lg border border-rose-200 text-xs text-rose-500 hover:bg-rose-50 hover:text-rose-600 transition flex items-center gap-1.5">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24"><path d="M3 6h18"/><path d="M8 6V4.75A1.75 1.75 0 0 1 9.75 3h4.5A1.75 1.75 0 0 1 16 4.75V6"/><path d="M19 6l-.63 11.338A2 2 0 0 1 16.37 19.5H7.63a2 2 0 0 1-1.997-2.162L5 6"/><path d="M10 10.5v5"/><path d="M14 10.5v5"/></svg>
            {t('buttons.delete')}
          </button>
        </div>
      </header>

      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 relative min-w-0">
          <div className="absolute top-3 left-3 z-10 flex items-center gap-1.5">
            <button onClick={fitGraph} className="h-7 w-7 bg-white/90 backdrop-blur rounded-lg shadow-sm border border-slate-200/60 text-slate-500 hover:text-slate-700 hover:bg-white transition inline-flex items-center justify-center" title={t('detail.fitGraph')}>
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M16 3h3a2 2 0 0 1 2 2v3"/><path d="M8 21H5a2 2 0 0 1-2-2v-3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/></svg>
            </button>
            <select value={layoutMode} onChange={(e) => setLayoutMode(e.target.value)}
              className="h-7 bg-white/90 backdrop-blur rounded-lg shadow-sm border border-slate-200/60 px-2.5 text-xs text-slate-600 hover:bg-white focus:outline-none focus:ring-2 focus:ring-brand-100 focus:border-brand-300 transition">
              <option value="dagre_tb">Dagre ↓</option>
              <option value="dagre_lr">Dagre →</option>
            </select>
          </div>

          {showReasonPanel && (
            <div className="absolute top-14 right-3 z-10 max-w-80">
              <div className="relative overflow-hidden rounded-2xl border border-sky-200/80 bg-white/92 px-3.5 py-3 shadow-lg shadow-sky-100/60 backdrop-blur">
                <div className="flex items-start gap-3">
                  <span className="relative w-[10px] h-[10px] rounded-full bg-sky-500 mt-1 shrink-0 shadow-[0_0_0_4px_rgba(14,165,233,0.16)]">
                    <span className="absolute inset-[-6px] rounded-full border-[1.5px] border-sky-300/34 animate-ping opacity-75"></span>
                  </span>
                  <div className="min-w-0">
                    <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-sky-500">{t('detail.reason.running')}</div>
                    <div className="mt-0.5 text-sm font-semibold text-slate-700 truncate">{meta.reason?.worker}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500">
                      {meta.reason?.trigger && <span>{t('detail.reason.trigger')} {meta.reason.trigger}</span>}
                      <span>{t('detail.reason.heartbeat')} {formatTime(meta.reason?.last_heartbeat_at ?? null)}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {isActive && (
            <div className="absolute top-3 right-3 z-10 flex flex-wrap justify-end gap-2">
              <div className="flex gap-1.5">
                <button onClick={() => setShowIntentModal(true)}
                  className="px-3 py-1.5 bg-white/90 backdrop-blur border border-brand-200 text-brand-600 rounded-lg shadow-sm text-xs font-medium hover:bg-brand-50 transition flex items-center gap-1">
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M5 12h14"/><path d="m13 6 6 6-6 6"/></svg>
                  {t('detail.actions.intent')}
                </button>
                <button onClick={handleComplete}
                  className="px-3 py-1.5 bg-white/90 backdrop-blur border border-teal-200 text-teal-600 rounded-lg shadow-sm text-xs font-medium hover:bg-teal-50 transition flex items-center gap-1">
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"/></svg>
                  {t('detail.actions.complete')}
                </button>
              </div>
              <div className="flex gap-1.5">
                <button onClick={() => setShowHintModal(true)}
                  className="px-3 py-1.5 bg-white/90 backdrop-blur border border-amber-200 text-amber-600 rounded-lg shadow-sm text-xs font-medium hover:bg-amber-50 transition flex items-center gap-1">
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 1 1 7.072 0l-.548.547A3.374 3.374 0 0 0 14 18.469V19a2 2 0 1 1-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547Z"/></svg>
                  {t('detail.actions.hint')}
                </button>
              </div>
              <div className="flex gap-1.5">
                <button onClick={handleIntentHeartbeat} disabled={!selectedActionableOpenIntentRecord()}
                  className="px-3 py-1.5 bg-white/90 backdrop-blur border border-slate-200 text-slate-600 rounded-lg shadow-sm text-xs font-medium hover:bg-slate-50 transition disabled:opacity-30 disabled:cursor-not-allowed flex items-center gap-1">
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24"><path d="M3 12h3.5l2.75-6 3.5 12 2.75-7H21"/></svg>
                  {selectedIntentPrimaryActionLabel()}
                </button>
                <button onClick={handleIntentRelease} disabled={!selectedReleasableOpenIntentRecord()}
                  className="px-3 py-1.5 bg-white/90 backdrop-blur border border-amber-200 text-amber-700 rounded-lg shadow-sm text-xs font-medium hover:bg-amber-50 transition disabled:opacity-30 disabled:cursor-not-allowed flex items-center gap-1">
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M9 10V7.75A3.75 3.75 0 1 1 16.5 7"/><path d="M7.5 10.5h9A1.5 1.5 0 0 1 18 12v6A1.5 1.5 0 0 1 16.5 19.5h-9A1.5 1.5 0 0 1 6 18v-6A1.5 1.5 0 0 1 7.5 10.5Z"/><path d="M12 14.25v1.5"/></svg>
                  {t('detail.actions.release')}
                </button>
                <button onClick={handleOpenConclude} disabled={!selectedActionableOpenIntentRecord()}
                  className="px-3 py-1.5 bg-white/90 backdrop-blur border border-teal-200 text-teal-600 rounded-lg shadow-sm text-xs font-medium hover:bg-teal-50 transition disabled:opacity-30 disabled:cursor-not-allowed flex items-center gap-1">
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M14.25 3H7.5A2.25 2.25 0 0 0 5.25 5.25v13.5A2.25 2.25 0 0 0 7.5 21h9a2.25 2.25 0 0 0 2.25-2.25V8.25L14.25 3Z"/><path d="M14.25 3v5.25h4.5"/><path d="M9 13.5 10.875 15.375 15 11.25"/></svg>
                  {t('detail.actions.conclude')}
                </button>
              </div>
            </div>
          )}

          <div ref={cyContainerRef} id="cy" className="absolute inset-0 z-0" />
        </div>

        <div
          onPointerDown={(e) => {
            setIsResizingPanel(true);
            const startX = e.clientX;
            const startWidth = sidePanelWidth;
            const onMove = (ev: PointerEvent) => {
              const newWidth = startWidth - (ev.clientX - startX);
              setSidePanelWidth(Math.max(280, Math.min(600, newWidth)));
            };
            const onUp = () => {
              setIsResizingPanel(false);
              document.removeEventListener('pointermove', onMove);
              document.removeEventListener('pointerup', onUp);
            };
            document.addEventListener('pointermove', onMove);
            document.addEventListener('pointerup', onUp);
          }}
          className="w-2 shrink-0 cursor-col-resize group flex items-stretch justify-center touch-none relative z-20"
        >
          <div className={`w-px bg-slate-200/70 transition group-hover:bg-brand-300 ${isResizingPanel ? 'bg-brand-400' : ''}`} />
        </div>

        <div
          className="border-l border-slate-200/60 bg-white flex flex-col overflow-hidden shrink-0 relative z-20"
          style={{ width: sidePanelWidth, minWidth: sidePanelWidth, flexBasis: sidePanelWidth }}
        >
          <div className="flex border-b border-slate-100 shrink-0">
            <button onClick={() => setSideTab('detail')}
              className={`flex-1 px-3 py-2.5 text-xs font-medium transition ${sideTab === 'detail' ? 'text-brand-600 border-b-2 border-brand-500' : 'text-slate-400 hover:text-slate-600'}`}>
              {t('detail.tabs.detail')}
            </button>
            <button onClick={() => setSideTab('hints')}
              className={`flex-1 px-3 py-2.5 text-xs font-medium transition ${sideTab === 'hints' ? 'text-brand-600 border-b-2 border-brand-500' : 'text-slate-400 hover:text-slate-600'}`}>
              {t('detail.tabs.hints')} <span className="ml-0.5 text-[10px] opacity-60">{hints.length}</span>
            </button>
            <button onClick={() => setSideTab('log')}
              className={`flex-1 px-3 py-2.5 text-xs font-medium transition ${sideTab === 'log' ? 'text-brand-600 border-b-2 border-brand-500' : 'text-slate-400 hover:text-slate-600'}`}>
              {t('detail.tabs.log')}
            </button>
          </div>

          {sideTab === 'detail' && (
            <div className="flex-1 overflow-y-auto p-4 space-y-4 bg-slate-50/40">
              {(!selectedNodeId || !selectedNodeType) && (
                <div className="rounded-2xl border border-dashed border-slate-200 bg-white/80 px-5 py-10 text-center shadow-sm">
                  <p className="text-sm text-slate-400">{t('detail.clickNodeHint')}</p>
                  <p className="text-xs text-slate-300 mt-1">{t('detail.shiftSelectHint')}</p>
                </div>
              )}

              {selectedNodeType === 'fact' && selectedFacts.size > 1 && (
                <div className="space-y-3">
                  {selectedFactRecords().map((fact) => {
                    const color = FACT_COLORS[fact.id] || FACT_DEFAULT_COLOR;
                    return (
                      <article key={fact.id} className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
                        <div className="px-4 py-3 border-b border-slate-100 bg-slate-50/80">
                          <div className="flex items-center justify-between gap-3">
                            <div className="flex items-center gap-2 min-w-0">
                              <span className={`px-2 py-0.5 rounded-md text-[10px] font-mono font-bold shrink-0 ${
                                fact.id === 'origin' ? 'bg-teal-50 text-teal-700' :
                                fact.id === 'goal' ? 'bg-rose-50 text-rose-600' :
                                'bg-brand-50 text-brand-700'
                              }`}>{fact.id}</span>
                              <span className="text-[11px] text-slate-400 uppercase tracking-wider">{t('stats.fact')}</span>
                            </div>
                            <button onClick={() => setSelectedFacts((prev) => { const n = new Set(prev); n.delete(fact.id); return n; })}
                              className="text-[11px] text-slate-400 hover:text-slate-600 transition">{t('detail.remove')}</button>
                          </div>
                        </div>
                        <div className="p-4">
                          <p className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap break-words">{fact.description}</p>
                        </div>
                      </article>
                    );
                  })}
                </div>
              )}

              {selectedNodeType === 'fact' && selectedFacts.size <= 1 && selectedFactRecord() && (
                <section className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
                  <div className="px-4 py-3 border-b border-slate-100 bg-slate-50/80">
                    <div className="flex items-center gap-2">
                      <span className={`px-2 py-0.5 rounded-md text-[10px] font-mono font-bold ${
                        selectedNodeId === 'origin' ? 'bg-teal-50 text-teal-700' :
                        selectedNodeId === 'goal' ? 'bg-rose-50 text-rose-600' :
                        'bg-brand-50 text-brand-700'
                      }`}>{selectedNodeId}</span>
                      <span className="text-[11px] text-slate-400 font-medium uppercase tracking-wider">{t('stats.fact')}</span>
                    </div>
                  </div>
                  <div className="p-4 space-y-4">
                    <p className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap break-words">{selectedFactRecord()!.description}</p>
                    <div className="space-y-3 text-xs">
                      {selectedNodeId === 'origin' && (
                        <div className="pt-4 border-t border-slate-100">
                          <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest mb-3">{t('detail.originLabel')}</p>
                          <div className="flex items-start justify-between gap-3"><span className="text-slate-400 shrink-0">{t('detail.role')}</span><span className="text-slate-600 text-right break-words">{t('detail.roleOrigin')}</span></div>
                        </div>
                      )}
                      {selectedNodeId === 'goal' && (() => {
                        const producingIntent = getProducingIntent('goal', intents);
                        return (
                          <div className="pt-4 border-t border-slate-100 space-y-3">
                            <p className="text-[10px] font-semibold text-rose-500 uppercase tracking-widest">{t('detail.goalLabel')}</p>
                            <div className="flex items-start justify-between gap-3"><span className="text-slate-400 shrink-0">{t('detail.role')}</span><span className="text-slate-600 text-right break-words">{t('detail.roleGoal')}</span></div>
                            {producingIntent && (
                              <>
                                <div className="flex items-start justify-between gap-3"><span className="text-slate-400 shrink-0">{t('detail.completedBy')}</span><span className="font-mono text-slate-600 text-right break-all">{producingIntent.id}</span></div>
                                <div className="flex items-start justify-between gap-3"><span className="text-slate-400 shrink-0">{t('detail.workerLabel')}</span><span className="text-slate-600 text-right break-all">{producingIntent.worker || '—'}</span></div>
                              </>
                            )}
                          </div>
                        );
                      })()}
                      {selectedNodeId !== 'origin' && selectedNodeId !== 'goal' && (() => {
                        const producingIntent = getProducingIntent(selectedNodeId!, intents);
                        return producingIntent ? (
                          <div className="pt-4 border-t border-slate-100 space-y-3">
                            <p className="text-[10px] font-semibold text-brand-500 uppercase tracking-widest">{t('detail.producedBy')}</p>
                            <div className="flex items-start justify-between gap-3"><span className="text-slate-400 shrink-0">{t('detail.intentLabel')}</span><span className="font-mono text-slate-600 text-right break-all">{producingIntent.id}</span></div>
                            <div className="flex items-start justify-between gap-3"><span className="text-slate-400 shrink-0">{t('detail.fromLabel')}</span><span className="font-mono text-slate-600 text-right break-all">{producingIntent.from.join(', ')}</span></div>
                            <div className="flex items-start justify-between gap-3"><span className="text-slate-400 shrink-0">{t('detail.creatorLabel')}</span><span className="text-slate-600 text-right break-all">{producingIntent.creator}</span></div>
                            <div className="flex items-start justify-between gap-3"><span className="text-slate-400 shrink-0">{t('detail.workerLabel')}</span><span className="text-slate-600 text-right break-all">{producingIntent.worker || '—'}</span></div>
                          </div>
                        ) : null;
                      })()}
                    </div>
                    {/* Related session logs for this fact */}
                    {relatedSessionLogs.length > 0 && (
                      <div className="pt-4 border-t border-slate-100 space-y-2">
                        <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest mb-2">{t('detail.llmSessions')}</p>
                        {relatedSessionLogs.map((log) => (
                          <SessionLogMiniCard key={log.id} log={log} onToggle={handleToggleSession} expandedSessions={expandedSessions} />
                        ))}
                      </div>
                    )}
                  </div>
                </section>
              )}

              {selectedNodeType === 'intent' && selectedIntentRecord() && (
                <section className="rounded-2xl border border-violet-200/80 bg-white shadow-sm overflow-hidden">
                  <div className="px-4 py-3 border-b border-violet-100 bg-violet-50/70">
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 rounded-md bg-violet-100 text-violet-700 text-[10px] font-mono font-bold">{selectedNodeId}</span>
                      <span className={`text-[11px] font-medium ${intentStatusClass(selectedIntentRecord()!)}`}>
                        {intentStatusLabel(selectedIntentRecord()!)}
                      </span>
                    </div>
                  </div>
                  <div className="p-4 space-y-4">
                    <p className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap break-words">{selectedIntentRecord()!.description}</p>
                    <div className="pt-4 border-t border-slate-100 space-y-3 text-xs">
                      <div className="flex items-start justify-between gap-3"><span className="text-slate-400 shrink-0">{t('detail.fromLabel')}</span><span className="font-mono text-slate-600 text-right break-all">{selectedIntentRecord()!.from.join(', ')}</span></div>
                      <div className="flex items-start justify-between gap-3"><span className="text-slate-400 shrink-0">{t('detail.toLabel')}</span><span className="font-mono text-slate-600 text-right break-all">{selectedIntentRecord()!.to || '—'}</span></div>
                      <div className="flex items-start justify-between gap-3"><span className="text-slate-400 shrink-0">{t('detail.creatorLabel')}</span><span className="text-slate-600 text-right break-all">{selectedIntentRecord()!.creator}</span></div>
                      <div className="flex items-start justify-between gap-3"><span className="text-slate-400 shrink-0">{t('detail.workerLabel')}</span><span className="text-slate-600 text-right break-all">{selectedIntentRecord()!.worker || '—'}</span></div>
                      <div className="flex items-start justify-between gap-3"><span className="text-slate-400 shrink-0">{t('detail.heartbeatLabel')}</span><span className="text-slate-600 text-right break-words">{selectedIntentRecord()!.last_heartbeat_at ? formatTime(selectedIntentRecord()!.last_heartbeat_at) : '—'}</span></div>
                      <div className="flex items-start justify-between gap-3"><span className="text-slate-400 shrink-0">{t('detail.createdLabel')}</span><span className="text-slate-600 text-right break-words">{formatTime(selectedIntentRecord()!.created_at)}</span></div>
                      {selectedIntentRecord()!.concluded_at && (
                        <div className="flex items-start justify-between gap-3"><span className="text-slate-400 shrink-0">{t('detail.concludedLabel')}</span><span className="text-slate-600 text-right break-words">{formatTime(selectedIntentRecord()!.concluded_at)}</span></div>
                      )}
                    </div>
                    {/* Related session logs for this intent */}
                    {relatedSessionLogs.length > 0 && (
                      <div className="pt-4 border-t border-slate-100 space-y-2">
                        <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest mb-2">{t('detail.llmSessions')}</p>
                        {relatedSessionLogs.map((log) => (
                          <SessionLogMiniCard key={log.id} log={log} onToggle={handleToggleSession} expandedSessions={expandedSessions} />
                        ))}
                      </div>
                    )}
                  </div>
                </section>
              )}
            </div>
          )}

          {sideTab === 'hints' && (
            <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-amber-50/25">
              {hints.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-amber-200 bg-white/80 px-5 py-10 text-center shadow-sm">
                  <p className="text-sm text-slate-300">{t('stats.noHints')}</p>
                </div>
              ) : (
                hints.map((h) => (
                  <div key={h.id}
                    className="w-full text-left rounded-2xl border border-amber-200/80 bg-white shadow-sm overflow-hidden">
                    <div className="px-4 py-3 border-b border-amber-100 bg-amber-50/80">
                      <div className="flex items-center justify-between gap-3 text-[11px]">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="w-2 h-2 rounded-full bg-amber-400 shrink-0"></span>
                          <span className="font-medium text-amber-800 truncate">{h.creator}</span>
                        </div>
                        <span className="text-amber-600/80 shrink-0 tabular-nums">{formatTime(h.created_at)}</span>
                      </div>
                    </div>
                    <div className="p-4">
                      <p className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap break-words">{h.content}</p>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}

          {sideTab === 'log' && (
  <div className="flex-1 overflow-y-auto p-4 space-y-3">
    {/* Timeline section */}
    {buildTimelineEvents(project).length > 0 && (
      <section className="sticky top-0 z-10 rounded-2xl border border-slate-200 bg-white/95 backdrop-blur px-4 py-3 shadow-sm">
        <div className="space-y-2.5">
          <div className="space-y-1">
            <div className="flex items-center justify-between gap-3 text-[11px]">
              <span className="text-slate-400">{t('detail.sequence')}</span>
              <span className="font-mono text-slate-600">
                {buildTimelineEvents(project).length} / {buildTimelineEvents(project).length}
              </span>
            </div>
            <div className="h-1.5 rounded-full bg-slate-100 overflow-hidden">
              <div className="h-full rounded-full bg-brand-400 transition-all duration-300" style={{ width: '100%' }}></div>
            </div>
          </div>
          <div className="space-y-1">
            <div className="flex items-center justify-between gap-3 text-[11px]">
              <span className="text-slate-400">{t('detail.timeSpan')}</span>
              <span className="font-mono text-slate-600 text-right">
                {(() => {
                  const events = buildTimelineEvents(project);
                  if (events.length < 2) return '\u2014';
                  const first = new Date(events[0].timestamp).getTime();
                  const last = new Date(events[events.length - 1].timestamp).getTime();
                  const diff = last - first;
                  if (diff < 60000) return `${Math.round(diff / 1000)}s`;
                  if (diff < 3600000) return `${Math.round(diff / 60000)}m`;
                  return `${Math.round(diff / 3600000)}h`;
                })()}
              </span>
            </div>
            <div className="h-1.5 rounded-full bg-slate-100 overflow-hidden">
              <div className="h-full rounded-full bg-teal-400 transition-all duration-300" style={{ width: '100%' }}></div>
            </div>
          </div>
        </div>
      </section>
    )}
    {buildTimelineEvents(project).length === 0 && sessionLogs.length === 0 ? (
      <p className="text-sm text-slate-300 text-center mt-12">{t('detail.noActivity')}</p>
    ) : (
      <>
        {/* Timeline entries */}
        {buildTimelineEvents(project).map((entry, index) => (
          <div key={entry.id} className="flex items-stretch gap-3">
            <div className="flex flex-col items-center shrink-0">
              <div className={`w-2.5 h-2.5 rounded-full mt-1.5 ${timelineDotClass(entry.type)}`}></div>
              {index < buildTimelineEvents(project).length - 1 && (
                <div className="w-px flex-1 bg-slate-100 mt-2"></div>
              )}
            </div>
            <div className="min-w-0 flex-1 text-left rounded-xl px-0.5 py-0.5 transition">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[11px] font-medium text-slate-400 tabular-nums">{formatTimestamp(entry.timestamp)}</span>
                <span className={`px-2 py-0.5 rounded-md text-[10px] font-semibold uppercase tracking-wide ${timelineBadgeClass(entry.type)}`}>
                  {timelineBadgeLabel(entry.type)}
                </span>
                <span className="text-[11px] text-slate-300">{formatDateOnly(entry.timestamp)}</span>
              </div>
              {entry.title && (
                <p className="text-sm text-slate-700 leading-relaxed break-words mt-1">{entry.title}</p>
              )}
              {entry.actor && (
                <p className="text-[11px] text-slate-400 mt-1 break-words">{entry.actor}</p>
              )}
            </div>
          </div>
        ))}

        {/* Session logs section */}
        {sessionLogs.length > 0 && (
          <>
            <div className="flex items-center gap-2 pt-4 pb-1">
              <div className="h-px flex-1 bg-slate-100"></div>
              <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest">{t('detail.workerSessions')}</span>
              <div className="h-px flex-1 bg-slate-100"></div>
            </div>
            {sessionLogs.map((log) => (
              <SessionLogCard key={log.id} log={log} onToggle={handleToggleSession} expandedSessions={expandedSessions} />
            ))}
          </>
        )}
      </>
    )}
  </div>
)}
        </div>
      </div>

      {showHintModal && (
        <ModalBase title={t('modals.hint.title')} onClose={() => setShowHintModal(false)}>
          <HintFormContent projectId={id!} onClose={() => setShowHintModal(false)} onAdded={() => { setShowHintModal(false); loadProject(); }} />
        </ModalBase>
      )}

      {showIntentModal && (
        <ModalBase title={t('modals.createIntent.title')} onClose={() => setShowIntentModal(false)}>
          <IntentFormContent
            projectId={id!}
            selectedFacts={Array.from(selectedFacts)}
            onClose={() => setShowIntentModal(false)}
            onCreated={() => { setShowIntentModal(false); loadProject(); }}
          />
        </ModalBase>
      )}

      {showCompleteModal && (
        <ModalBase title={t('modals.complete.title')} onClose={() => setShowCompleteModal(false)}>
          <CompleteFormContent
            projectId={id!}
            facts={facts}
            onClose={() => setShowCompleteModal(false)}
            onCompleted={() => { setShowCompleteModal(false); loadProject(); }}
          />
        </ModalBase>
      )}

      {showConcludeModal && (
        <ModalBase title={t('modals.conclude.title')} onClose={() => setShowConcludeModal(false)}>
          <ConcludeIntentFormContent
            intentDescription={selectedActionableOpenIntentRecord()?.description || ''}
            onClose={() => setShowConcludeModal(false)}
            onConclude={(description) => handleConcludeIntent(description)}
          />
        </ModalBase>
      )}
      {showSnapshotModal && (
        <ModalBase title={`${t('buttons.snapshot')} — ${meta.title}`} onClose={() => setShowSnapshotModal(false)}>
          <div className="space-y-3">
            <pre className="max-h-[60vh] overflow-auto text-[11px] font-mono leading-relaxed bg-slate-50 border border-slate-200 rounded-xl p-4 text-slate-700 whitespace-pre-wrap break-words">{snapshotContent}</pre>
            <div className="flex justify-end pt-1">
              <button onClick={() => setShowSnapshotModal(false)} className="px-4 py-2 text-sm text-slate-500 hover:bg-slate-50 rounded-xl transition">{t('buttons.close')}</button>
            </div>
          </div>
        </ModalBase>
      )}
    </div>
  );
}

function ModalBase({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center overlay bg-slate-900/25 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg p-6 border border-slate-200/60 mx-4" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-base font-semibold text-slate-700 mb-4">{title}</h3>
        {children}
      </div>
    </div>
  );
}

// ── Session Log Components ────────────────────────────────────────────────

function formatSessionTime(dateStr: string): string {
  const d = new Date(dateStr);
  const now = Date.now();
  const diff = now - d.getTime();
  if (diff < 60000) return 'just now';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

const PHASE_LABELS: Record<string, string> = {
  bootstrap: 'Bootstrap',
  reason: 'Reason',
  explore: 'Explore',
};
const PHASE_COLORS: Record<string, string> = {
  bootstrap: 'bg-amber-100 text-amber-700',
  reason: 'bg-sky-100 text-sky-700',
  explore: 'bg-violet-100 text-violet-700',
};

function getPhaseLabel(phase: string): string {
  return PHASE_LABELS[phase] || phase;
}

function getPhaseColor(phase: string): string {
  return PHASE_COLORS[phase] || 'bg-slate-100 text-slate-600';
}

/** Card for session log in the Log panel */
function SessionLogCard({ log, onToggle, expandedSessions }: {
  log: SessionLogEntry;
  onToggle: (sessionId: string) => void;
  expandedSessions: Record<string, Message[] | 'loading'>;
}) {
  const { t } = useTranslation('cairn');
  const statusColor = log.status === 'success' ? 'text-teal-600' : 'text-rose-500';
  const isExpanded = log.session_id in expandedSessions;
  const messages = expandedSessions[log.session_id];
  const isLoading = messages === 'loading';
  const sessionMessages = isLoading ? [] : (messages as Message[] | undefined) || [];

  return (
    <div className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-100 bg-slate-50/80 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className={`px-2 py-0.5 rounded-md text-[10px] font-semibold ${getPhaseColor(log.phase)}`}>
            {getPhaseLabel(log.phase)}
          </span>
          <span className="text-[11px] font-mono text-slate-500 truncate">{log.worker}</span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className={`text-[10px] font-medium ${statusColor}`}>{log.status}</span>
          <span className="text-[10px] text-slate-400 tabular-nums">{formatSessionTime(log.created_at)}</span>
        </div>
      </div>
      <div className="px-4 py-3 flex items-center justify-between gap-3">
        <p className="text-xs text-slate-600 leading-relaxed break-words line-clamp-2 min-w-0 flex-1">{log.prompt_preview || '—'}</p>
        <button
          onClick={() => onToggle(log.session_id)}
          className={`px-3 py-1.5 rounded-lg border text-[10px] font-medium transition shrink-0 whitespace-nowrap ${
            isExpanded
              ? 'border-slate-300 bg-slate-100 text-slate-600 hover:bg-slate-200'
              : 'border-brand-200 text-brand-600 hover:bg-brand-50'
          }`}
        >
          {isExpanded ? t('detail.collapse') : t('detail.view')}
        </button>
      </div>
      {/* Inline expanded messages */}
      {isExpanded && (
        <div className="border-t border-slate-100">
          {isLoading ? (
            <div className="flex items-center justify-center py-6">
              <LoadingSpinner size="md" />
            </div>
          ) : sessionMessages.length === 0 ? (
            <div className="text-center py-6 text-xs text-slate-400">{t('detail.noMessagesInSession')}</div>
          ) : (
            <div className="px-4 py-3 space-y-3 max-h-80 overflow-y-auto">
              {sessionMessages.map((msg) => (
                <SessionMessageRow key={msg.id} message={msg} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Mini card for session log in the Detail panel (fact/intent) */
function SessionLogMiniCard({ log, onToggle, expandedSessions }: {
  log: SessionLogEntry;
  onToggle: (sessionId: string) => void;
  expandedSessions: Record<string, Message[] | 'loading'>;
}) {
  const { t } = useTranslation('cairn');
  const isExpanded = log.session_id in expandedSessions;
  const messages = expandedSessions[log.session_id];
  const isLoading = messages === 'loading';
  const sessionMessages = isLoading ? [] : (messages as Message[] | undefined) || [];

  return (
    <div>
      <div className="flex items-center justify-between gap-2 rounded-xl border border-slate-200 bg-slate-50/60 px-3 py-2 text-xs">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <span className={`px-1.5 py-0.5 rounded text-[9px] font-semibold ${getPhaseColor(log.phase)}`}>
            {getPhaseLabel(log.phase)}
          </span>
          <span className="font-mono text-slate-500 truncate">{log.worker}</span>
          <span className="text-slate-400 text-[10px]">{formatSessionTime(log.created_at)}</span>
        </div>
        <button
          onClick={() => onToggle(log.session_id)}
          className={`px-2 py-1 rounded-lg border text-[9px] font-medium transition shrink-0 ${
            isExpanded
              ? 'border-slate-300 bg-slate-100 text-slate-500'
              : 'border-brand-200 text-brand-600 hover:bg-brand-50'
          }`}
        >
          {isExpanded ? t('detail.collapse') : t('detail.view')}
        </button>
      </div>
      {/* Inline expanded messages */}
      {isExpanded && (
        <div className="ml-1 mt-1.5 border-l-2 border-slate-200 pl-3">
          {isLoading ? (
            <div className="flex items-center justify-center py-4">
              <LoadingSpinner size="sm" />
            </div>
          ) : sessionMessages.length === 0 ? (
            <div className="text-center py-4 text-[11px] text-slate-400">{t('detail.noMessages')}</div>
          ) : (
            <div className="space-y-2 max-h-60 overflow-y-auto">
              {sessionMessages.map((msg) => (
                <SessionMessageRow key={msg.id} message={msg} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Single message row rendered in the inline expanded view */
function SessionMessageRow({ message }: { message: Message }) {
  const { t } = useTranslation('cairn');
  const parts: MessagePart[] = Array.isArray((message as any).parts) ? (message as any).parts : [];
  const isUser = message.role === 'user';

  return (
    <div className="flex gap-2.5">
      <div className={`shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-[8px] font-bold text-white mt-0.5 ${
        isUser ? 'bg-slate-400' : 'bg-rose-400'
      }`}>
        {isUser ? 'U' : 'A'}
      </div>
      <div className="flex-1 min-w-0 space-y-1">
        <div className="text-[10px] font-semibold text-slate-400 flex items-center gap-2">
          <span>{isUser ? t('detail.user') : t('detail.assistant')}</span>
          {(message as any).modelID && <span className="font-mono text-slate-300">{(message as any).modelID}</span>}
        </div>
        <div className="space-y-2">
          {parts.length === 0 && !isUser && (
            <div className="flex items-center gap-1 py-1">
              <span className="w-1 h-1 rounded-full bg-slate-400 animate-bounce" />
              <span className="w-1 h-1 rounded-full bg-slate-400 animate-bounce [animation-delay:0.15s]" />
              <span className="w-1 h-1 rounded-full bg-slate-400 animate-bounce [animation-delay:0.3s]" />
            </div>
          )}
          {parts.map((part: MessagePart, i: number) => (
            <div key={part.id || i} className="first:mt-0">
              {/* Text */}
              {part.type === 'text' && part.text && (
                <div className={`text-sm leading-relaxed break-words whitespace-pre-wrap ${
                  isUser ? 'text-slate-700' : 'text-slate-700'
                }`}>
                  {part.text.length > 500 ? part.text.slice(0, 500) + '…' : part.text}
                </div>
              )}

              {/* Tool call */}
              {part.type === 'tool' && (
                <SessionToolPart part={part} />
              )}

              {/* Reasoning / thinking */}
              {(part.type === 'reasoning' || part.type === 'thinking') && (part.text || (part as any).thinking) && (
                <details className="group rounded-lg border border-slate-200 bg-slate-50/60">
                  <summary className="px-2 py-1.5 cursor-pointer list-none flex items-center gap-1.5 text-[11px] text-violet-600 font-medium select-none hover:bg-slate-100/50 transition-colors rounded-lg">
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24"><path d="M12 3v3m0 12v3m-7.07-7.07 2.12-2.12m9.9-1.42 2.12-2.12M4.5 12h3m9 0h3M7.05 7.05l-1.41-1.41M16.95 16.95l1.41 1.41"/><circle cx="12" cy="12" r="3.5"/></svg>
                    <span className="truncate">Thinking</span>
                    <svg className="w-2.5 h-2.5 ml-auto text-slate-400 transition-transform group-open:rotate-180" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>
                  </summary>
                  <div className="px-2.5 py-2 text-[11px] text-slate-500 font-mono whitespace-pre-wrap leading-relaxed max-h-32 overflow-y-auto border-t border-slate-200/60">
                    {part.text || (part as any).thinking || ''}
                  </div>
                </details>
              )}

              {/* File / image attachment */}
              {part.type === 'file' && (part as any).url && (
                <div className="flex items-center gap-2 text-xs text-slate-500 bg-slate-50 rounded-lg px-2.5 py-1.5 border border-slate-200">
                  <svg className="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.6" viewBox="0 0 24 24"><path d="M14.25 3H7.5A2.25 2.25 0 0 0 5.25 5.25v13.5A2.25 2.25 0 0 0 7.5 21h9a2.25 2.25 0 0 0 2.25-2.25V8.25L14.25 3Z"/><path d="M14.25 3v5.25h4.5"/></svg>
                  <span className="truncate">{(part as any).filename || 'file'}</span>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/** Simplified tool call card for inline session view */
function SessionToolPart({ part }: { part: MessagePart }) {
  const { t } = useTranslation('cairn');
  const toolName = part.tool || 'unknown';
  const state = (part as any).state || {};
  const status = state.status || 'completed';

  return (
    <details className="group/tool rounded-lg bg-slate-50 border border-slate-200 overflow-hidden">
      <summary className="px-2.5 py-1.5 cursor-pointer list-none flex items-center gap-1.5 min-w-0 select-none hover:bg-slate-100/50 transition-colors">
        <span className="text-slate-500 flex-shrink-0">
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24"><path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 0 0 2.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 0 0 1.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 0 0-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 0 0-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 0 0-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 0 0-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 0 0 1.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065Z"/><path d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z"/></svg>
        </span>
        <span className="text-[11px] font-medium text-slate-700">{toolName.replace(/_/g, ' ')}</span>
        <span className={`ml-auto text-[10px] font-medium px-1.5 py-0.5 rounded ${
          status === 'completed' ? 'bg-teal-50 text-teal-600' :
          status === 'running' ? 'bg-sky-50 text-sky-600' :
          status === 'error' ? 'bg-red-50 text-red-500' :
          'bg-slate-100 text-slate-500'
        }`}>
          {status}
        </span>
        <svg className="w-2.5 h-2.5 text-slate-400 transition-transform group-open/tool:rotate-180" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>
      </summary>
      {state.input && (
        <div className="border-t border-slate-200/60 px-2.5 py-2">
          <div className="text-[10px] font-medium text-slate-400 mb-1">{t('detail.input')}</div>
          <pre className="p-2 bg-slate-800 text-slate-200 rounded-md text-[10px] overflow-x-auto font-mono leading-relaxed max-h-32 overflow-y-auto">
            {JSON.stringify(state.input, null, 2)}
          </pre>
        </div>
      )}
      {status === 'completed' && state.output !== undefined && (
        <div className="border-t border-slate-200/60 px-2.5 py-2">
          <div className="text-[10px] font-medium text-slate-400 mb-1">{t('detail.output')}</div>
          <pre className="p-2 bg-slate-800 text-green-300 rounded-md text-[10px] overflow-x-auto font-mono leading-relaxed max-h-32 overflow-y-auto">
            {typeof state.output === 'string' ? state.output : JSON.stringify(state.output, null, 2)}
          </pre>
        </div>
      )}
      {status === 'error' && state.error && (
        <div className="px-2.5 py-1.5 bg-red-50 border-t border-red-100 text-[11px] text-red-600">
          {state.error}
        </div>
      )}
    </details>
  );
}

function HintFormContent({ projectId, onClose, onAdded }: { projectId: string; onClose: () => void; onAdded: () => void }) {
  const { t } = useTranslation('cairn');
  const [content, setContent] = useState('');
  const [adding, setAdding] = useState(false);
  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!content.trim()) return;
    setAdding(true);
    try {
      await cairnApi.createHint(projectId, { content: content.trim(), creator: 'user' });
      onAdded();
    } catch { alert('Failed to add hint'); setAdding(false); }
  }
  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <textarea value={content} onChange={(e) => setContent(e.target.value)} placeholder={t('form.hintContentPlaceholder')} rows={3}
        className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-brand-100 focus:border-brand-400 transition placeholder:text-slate-300" />
      <div className="px-3 py-2 rounded-xl bg-slate-50 border border-slate-200 text-sm text-slate-500">
        {t('modals.preferences.actor')}: <span className="font-medium text-slate-700">user</span>
      </div>
      <div className="flex justify-end gap-2 pt-1">
        <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-slate-500 hover:bg-slate-50 rounded-xl transition">{t('buttons.cancel')}</button>
        <button type="submit" disabled={adding || !content.trim()} className="px-5 py-2 text-sm bg-amber-500 text-white rounded-xl font-medium hover:bg-amber-600 transition disabled:opacity-30 shadow-sm shadow-amber-200">{t('buttons.add')}</button>
      </div>
    </form>
  );
}

function IntentFormContent({ projectId, selectedFacts, onClose, onCreated }: {
  projectId: string; selectedFacts: string[]; onClose: () => void; onCreated: () => void;
}) {
  const { t } = useTranslation('cairn');
  const [description, setDescription] = useState('');
  const [creating, setCreating] = useState(false);
  async function handleSubmit(claim: boolean) {
    if (!description.trim()) return;
    setCreating(true);
    try {
      await cairnApi.createIntent(projectId, {
        from_: selectedFacts.length > 0 ? selectedFacts : ['origin'],
        description: description.trim(),
        creator: 'user',
        worker: claim ? 'user' : undefined,
      });
      onCreated();
    } catch { alert('Failed to create intent'); setCreating(false); }
  }
  return (
    <div className="space-y-3">
      <div>
        <label className="text-[11px] text-slate-400 mb-1 block font-medium">{t('modals.createIntent.fromFacts')}</label>
        <div className="w-full px-3 py-2 border border-slate-200 rounded-xl bg-slate-50 min-h-[42px] flex flex-wrap gap-1.5 items-center">
          {(selectedFacts.length > 0 ? selectedFacts : ['origin']).map((fid) => (
            <span key={fid} className="px-2 py-1 rounded-lg bg-white border border-slate-200 text-[11px] font-mono text-slate-600">{fid}</span>
          ))}
        </div>
      </div>
      <textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder={t('modals.createIntent.descriptionPlaceholder')} rows={3}
        className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-brand-100 focus:border-brand-400 transition placeholder:text-slate-300" />
      <div className="px-3 py-2 rounded-xl bg-slate-50 border border-slate-200 text-sm text-slate-500">
        {t('modals.preferences.actor')}: <span className="font-medium text-slate-700">user</span>
      </div>
      <div className="flex justify-end gap-2 pt-1">
        <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-slate-500 hover:bg-slate-50 rounded-xl transition">{t('buttons.cancel')}</button>
        <button onClick={() => handleSubmit(false)} disabled={creating || !description.trim()}
          className="px-5 py-2 text-sm border border-slate-200 text-slate-600 rounded-xl font-medium hover:bg-slate-50 transition disabled:opacity-30">{t('detail.actions.declare')}</button>
        <button onClick={() => handleSubmit(true)} disabled={creating || !description.trim()}
          className="px-5 py-2 text-sm bg-brand-500 text-white rounded-xl font-medium hover:bg-brand-600 transition disabled:opacity-30 shadow-sm shadow-brand-200">{t('detail.actions.declareClaim')}</button>
      </div>
    </div>
  );
}

function CompleteFormContent({ projectId, facts, onClose, onCompleted }: {
  projectId: string; facts: Fact[]; onClose: () => void; onCompleted: () => void;
}) {
  const { t } = useTranslation('cairn');
  const [description, setDescription] = useState('');
  const [completing, setCompleting] = useState(false);
  const fromIds = facts.filter((f) => f.id !== 'origin' && f.id !== 'goal').map((f) => f.id);
  async function handleSubmit() {
    if (!description.trim() || fromIds.length === 0) return;
    setCompleting(true);
    try {
      await cairnApi.completeProject(projectId, { from_: fromIds, description: description.trim(), worker: 'user' });
      onCompleted();
    } catch { alert('Failed to complete project'); setCompleting(false); }
  }
  return (
    <div className="space-y-3">
      <div>
        <label className="text-[11px] text-slate-400 mb-1 block font-medium">{t('modals.createIntent.fromFacts')}</label>
        <div className="w-full px-3 py-2 border border-slate-200 rounded-xl bg-slate-50 min-h-[42px] flex flex-wrap gap-1.5 items-center">
          {fromIds.map((fid) => (
            <span key={fid} className="px-2 py-1 rounded-lg bg-white border border-slate-200 text-[11px] font-mono text-slate-600">{fid}</span>
          ))}
        </div>
      </div>
      <textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder={t('form.completePlaceholder')} rows={2}
        className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-brand-100 focus:border-brand-400 transition placeholder:text-slate-300" />
      <div className="px-3 py-2 rounded-xl bg-slate-50 border border-slate-200 text-sm text-slate-500">
        {t('modals.preferences.actor')}: <span className="font-medium text-slate-700">user</span>
      </div>
      <div className="flex justify-end gap-2 pt-1">
        <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-slate-500 hover:bg-slate-50 rounded-xl transition">{t('buttons.cancel')}</button>
        <button onClick={handleSubmit} disabled={completing || !description.trim() || fromIds.length === 0}
          className="px-5 py-2 text-sm bg-teal-500 text-white rounded-xl font-medium hover:bg-teal-600 transition disabled:opacity-30 shadow-sm shadow-teal-200">{t('buttons.complete')}</button>
      </div>
    </div>
  );
}

function ConcludeIntentFormContent({ intentDescription, onClose, onConclude }: {
  intentDescription: string; onClose: () => void; onConclude: (description: string) => void;
}) {
  const { t } = useTranslation('cairn');
  const [description, setDescription] = useState('');
  const [concluding, setConcluding] = useState(false);
  async function handleSubmit() {
    if (!description.trim()) return;
    setConcluding(true);
    try {
      await onConclude(description.trim());
    } catch { setConcluding(false); }
  }
  return (
    <div className="space-y-3">
      <div className="px-3 py-2 rounded-xl bg-slate-50 border border-slate-200 text-sm text-slate-500">
        {t('detail.intentLabel')}: <span className="font-medium text-slate-700">{intentDescription}</span>
      </div>
      <textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder={t('form.concludePlaceholder')} rows={3}
        className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-brand-100 focus:border-brand-400 transition placeholder:text-slate-300" />
      <div className="px-3 py-2 rounded-xl bg-slate-50 border border-slate-200 text-sm text-slate-500">
        {t('modals.preferences.actor')}: <span className="font-medium text-slate-700">user</span>
      </div>
      <div className="flex justify-end gap-2 pt-1">
        <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-slate-500 hover:bg-slate-50 rounded-xl transition">{t('buttons.cancel')}</button>
        <button onClick={handleSubmit} disabled={concluding || !description.trim()}
          className="px-5 py-2 text-sm bg-teal-500 text-white rounded-xl font-medium hover:bg-teal-600 transition disabled:opacity-30 shadow-sm shadow-teal-200">{t('buttons.conclude')}</button>
      </div>
    </div>
  );
}