// frontend/src/App.tsx
// Root application. Three-column layout: sidebar | whiteboard | chat.
// Pass 3 Features: Recent notebook search filter, inline notebook renaming,
// notebook summary modal with Markdown export, and page deletion support.

import { useState, useEffect, useCallback, useRef } from 'react';
import { WhiteboardCanvas } from './components/WhiteboardCanvas';
import { ChatPanel } from './components/ChatPanel';
import { PageSidebar } from './components/PageSidebar';
import { Menu } from './components/Menu';
import { LearnerPanel } from './components/LearnerPanel';
import { useLearner } from './hooks/useLearner';
import { THEME_CHOICES, useThemePref } from './utils/theme';
import { useMediaQuery } from './utils/useMediaQuery';
import { useNotebookWebSocket } from './hooks/useNotebookWebSocket';
import type {
  Notebook, PageSummary, ChatTurn,
  WsEvent, WsElementDrawn, WsElementModified, AnnotationPayload,
  LearnerIntent, Intake,
} from './types';
import { debug } from './utils/debug';
import * as api from './services/api';

const STARTER_TOPICS = [
  'How vaccines train the immune system',
  'Causes of the First World War',
  'What a derivative is',
  'How supply and demand set prices',
  'TCP/IP 3-way handshake',
  'Binary search trees',
];

const LEVELS = [
  { id: 'beginner', label: 'Beginner', hint: 'Intuition first, with minimal jargon.' },
  { id: 'intermediate', label: 'Standard', hint: 'Core concepts with clear examples.' },
  { id: 'deep-dive', label: 'Deep dive', hint: 'The internals and the details behind them.' },
] as const;

const INTAKE_QUESTIONS = [
  { key: 'purpose', legend: 'Why are you learning this?', choices: [
    ['curiosity', 'Curious'], ['exam', 'Exam'], ['work', 'Work / interview'], ['project', 'A project']] },
  { key: 'time_budget', legend: 'How much time do you have?', choices: [
    ['quick', 'Under 30 min'], ['session', 'About an hour'], ['course', 'Over several days']] },
  { key: 'self_level', legend: 'How well do you know it?', choices: [
    ['new', 'New to me'], ['some', 'I know some'], ['comfortable', 'Comfortable']] },
] as const;

// Notebook topics created with a depth other than Standard are stored as "[Deep-dive] topic".
function parseTopic(topic: string): { text: string; tag: string | null } {
  const m = /^\[(Beginner|Deep-dive)\]\s*/i.exec(topic);
  if (!m) return { text: topic, tag: null };
  return { text: topic.slice(m[0].length), tag: m[1].toLowerCase() === 'beginner' ? 'Beginner' : 'Deep dive' };
}

// ---------------------------------------------------------------------------
// Notebook creation screen (shown before a notebook is active)
// ---------------------------------------------------------------------------
function storedSetting(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
function storeSetting(key: string, value: string): void {
  try { localStorage.setItem(key, value); } catch { /* private window: lasts until reload */ }
}

function NewNotebookScreen({ onCreate }: Readonly<{ onCreate: (nb: Notebook) => void }>) {
  const [themePref, setThemePref] = useThemePref();
  const [topic, setTopic] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [level, setLevel] = useState<(typeof LEVELS)[number]['id']>('intermediate');
  const [intake, setIntake] = useState<Intake>({});
  const [isCreating, setIsCreating] = useState(false);
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);

  useEffect(() => {
    api.listNotebooks()
      .then(r => r.json())
      .then(setNotebooks)
      .catch(() => {});
  }, []);

  const handleCreate = async (topicToUse?: string) => {
    const rawTopic = (topicToUse || topic).trim();
    if (!rawTopic || isCreating) return;
    setIsCreating(true);

    const formattedTopic = level === 'intermediate'
      ? rawTopic
      : `[${level.charAt(0).toUpperCase() + level.slice(1)}] ${rawTopic}`;

    try {
      const res = await api.createNotebook(formattedTopic, intake);
      if (res.ok) {
        const nb = await res.json();
        onCreate(nb);
      }
    } finally {
      setIsCreating(false);
    }
  };

  const handleDeleteNotebook = async (nb: Notebook) => {
    if (!confirm(`Delete "${parseTopic(nb.topic).text}"? This can't be undone.`)) return;
    try {
      const res = await api.deleteNotebook(nb.id);
      if (res.ok) setNotebooks(prev => prev.filter(n => n.id !== nb.id));
    } catch (err) {
      console.error('Failed to delete notebook', err);
    }
  };

  const filteredNotebooks = notebooks.filter(nb =>
    nb.topic.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (nb.title?.toLowerCase().includes(searchQuery.toLowerCase()))
  );
  const canStart = !!topic.trim() && !isCreating;
  const hint = LEVELS.find(l => l.id === level)?.hint;

  return (
    <main style={{
      minHeight: '100vh', width: '100%', background: 'var(--bg)', boxSizing: 'border-box', position: 'relative',
      display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '72px 20px 56px',
    }}>
      <div style={{ position: 'absolute', top: 14, right: 16 }}>
        <Menu label="Appearance" items={THEME_CHOICES.map(t => ({
          label: t.label, kind: 'radio' as const, checked: themePref === t.id, onSelect: () => setThemePref(t.id),
        }))} />
      </div>
      <div style={{ width: '560px', maxWidth: '100%' }}>
        <h1 style={{ color: 'var(--ink)', fontSize: '28px', fontWeight: 600, margin: 0, letterSpacing: '-0.02em' }}>
          Learning Platform
        </h1>
        <p style={{ color: 'var(--ink-2)', fontSize: '15px', margin: '8px 0 32px', lineHeight: 1.6 }}>
          Name a concept. Your tutor explains it out loud and draws it as you go.
        </p>

        <form onSubmit={e => { e.preventDefault(); handleCreate(); }}>
          <label htmlFor="topic-input" style={{ display: 'block', color: 'var(--ink)', fontSize: '13px', fontWeight: 600, marginBottom: '8px' }}>
            What do you want to learn?
          </label>
          <div style={{ display: 'flex', gap: '8px' }}>
            <input
              id="topic-input"
              value={topic}
              onChange={e => setTopic(e.target.value)}
              placeholder="For example: how vaccines work"
              maxLength={300}
              autoFocus
              style={{
                flex: 1, minWidth: 0, height: '48px', padding: '0 16px', background: 'var(--panel)',
                border: '1px solid var(--border-strong)', borderRadius: '10px', color: 'var(--ink)',
                fontSize: '16px', fontFamily: 'inherit',
              }}
            />
            <button
              id="create-notebook-btn"
              type="submit"
              disabled={!canStart}
              style={{
                height: '48px', padding: '0 22px', border: 'none', borderRadius: '10px', fontSize: '15px', fontWeight: 600,
                background: canStart ? 'var(--accent)' : 'var(--panel-2)',
                color: canStart ? 'var(--on-accent)' : 'var(--ink-2)',
                cursor: canStart ? 'pointer' : 'default', whiteSpace: 'nowrap',
              }}
            >
              {isCreating ? 'Opening…' : 'Start'}
            </button>
          </div>
        </form>

        {/* Depth: a quiet segmented choice with a one-line explanation */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginTop: '14px', flexWrap: 'wrap' }}>
          <div
            role="radiogroup"
            tabIndex={-1}
            aria-label="Learning depth"
            onKeyDown={e => {
              const step = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0;
              if (!step) return;
              e.preventDefault();
              const i = LEVELS.findIndex(l => l.id === level);
              const next = LEVELS[(i + step + LEVELS.length) % LEVELS.length];
              setLevel(next.id);
              document.getElementById(`level-${next.id}`)?.focus();
            }}
            style={{
            display: 'inline-flex', gap: '2px', padding: '2px', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--panel)',
          }}>
            {LEVELS.map(l => (
              <button
                key={l.id}
                id={`level-${l.id}`}
                type="button"
                role="radio"
                tabIndex={level === l.id ? 0 : -1}
                aria-checked={level === l.id}
                onClick={() => setLevel(l.id)}
                style={{
                  padding: '4px 12px', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px',
                  background: level === l.id ? 'var(--panel-2)' : 'transparent',
                  color: level === l.id ? 'var(--ink)' : 'var(--ink-2)',
                  fontWeight: level === l.id ? 600 : 500,
                }}
              >
                {l.label}
              </button>
            ))}
          </div>
          <span style={{ color: 'var(--ink-2)', fontSize: '13px' }}>{hint}</span>
        </div>

        {/* Optional intake: each chip toggles; none preselected */}
        <div style={{ marginTop: '18px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div id="intake-caption" style={{ color: 'var(--ink-2)', fontSize: '12px' }}>Optional — helps the tutor choose how to teach you</div>
          {INTAKE_QUESTIONS.map(q => (
            <fieldset key={q.key} aria-describedby="intake-caption" style={{ border: 'none', margin: 0, padding: 0, minWidth: 0 }}>
              <legend style={{ color: 'var(--ink)', fontSize: '13px', fontWeight: 600, padding: 0, marginBottom: '6px' }}>{q.legend}</legend>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                {q.choices.map(([value, label]) => {
                  const on = intake[q.key] === value;
                  return (
                    <button
                      key={value}
                      type="button"
                      className="intake-chip"
                      aria-pressed={on}
                      onClick={() => setIntake(prev => {
                        const { [q.key]: _drop, ...rest } = prev;
                        return on ? rest : { ...prev, [q.key]: value };
                      })}
                    >
                      {on ? '✓ ' : ''}{label}
                    </button>
                  );
                })}
              </div>
            </fieldset>
          ))}
        </div>

        {/* Starters: plain chips across a range of subjects */}
        <div style={{ marginTop: '28px' }}>
          <div style={{ color: 'var(--ink-2)', fontSize: '13px', marginBottom: '8px' }}>Or start with one of these</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
            {STARTER_TOPICS.map(st => (
              <button
                key={st}
                type="button"
                className="quick-chip"
                disabled={isCreating}
                style={{ cursor: isCreating ? 'default' : 'pointer' }}
                onClick={() => { setTopic(st); handleCreate(st); }}
              >
                {st}
              </button>
            ))}
          </div>
        </div>

        {/* Recent notebooks: a simple list, not a card of cards */}
        {notebooks.length > 0 && (
          <section aria-labelledby="recent-heading" style={{ marginTop: '56px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '8px' }}>
              <h2 id="recent-heading" style={{ margin: 0, fontSize: '13px', fontWeight: 600, color: 'var(--ink)' }}>
                Recent <span style={{ color: 'var(--ink-2)', fontWeight: 400 }}>({notebooks.length})</span>
              </h2>
              {notebooks.length > 6 && (
                <input
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                  placeholder="Filter"
                  aria-label="Filter notebooks"
                  style={{
                    background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: '6px', color: 'var(--ink)',
                    fontSize: '13px', padding: '4px 10px', width: '140px',
                  }}
                />
              )}
            </div>

            <ul style={{ listStyle: 'none', margin: 0, padding: 0, borderTop: '1px solid var(--border)', maxHeight: '420px', overflowY: 'auto' }}>
              {filteredNotebooks.length === 0 ? (
                <li style={{ padding: '16px 4px', color: 'var(--ink-2)', fontSize: '13px' }}>No notebooks match your filter.</li>
              ) : filteredNotebooks.map(nb => {
                const { text, tag } = parseTopic(nb.topic);
                return (
                  <li key={nb.id} className="page-row" style={{ display: 'flex', alignItems: 'center', borderBottom: '1px solid var(--border)' }}>
                    <button
                      id={`recent-notebook-${nb.id}`}
                      type="button"
                      onClick={() => onCreate(nb)}
                      style={{
                        flex: 1, minWidth: 0, textAlign: 'left', background: 'transparent', border: 'none', cursor: 'pointer',
                        padding: '12px 8px', display: 'flex', alignItems: 'baseline', gap: '10px',
                      }}
                    >
                      <span style={{ color: 'var(--ink)', fontSize: '14px', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {text}
                      </span>
                      {tag && <span style={{ color: 'var(--ink-2)', fontSize: '12px', flexShrink: 0 }}>{tag}</span>}
                      <span style={{ color: 'var(--ink-2)', fontSize: '12px', marginLeft: 'auto', flexShrink: 0 }}>
                        {new Date(nb.created_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}
                      </span>
                    </button>
                    <span className="row-actions">
                      <Menu label={`Actions for ${text}`} icon="dots" items={[
                        { label: 'Delete notebook', onSelect: () => handleDeleteNotebook(nb) },
                      ]} />
                    </span>
                  </li>
                );
              })}
            </ul>
          </section>
        )}
      </div>
    </main>
  );
}

// ---------------------------------------------------------------------------
// Dialog support: native showModal() (inert page behind, Tab trap, Escape = "cancel"), focus moved in, restored to the opener on close
// ---------------------------------------------------------------------------
function useDialogFocus(open: boolean) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!open || !el) return;
    const opener = document.activeElement as HTMLElement | null;
    if (!el.open) el.showModal();
    (el.querySelector<HTMLElement>("button") ?? el).focus();
    return () => {
      if (el.open) el.close();   // close first: an open modal keeps the page behind inert, so focus() there would fail
      opener?.focus?.();
    };
  }, [open]);
  return ref;
}

// ---------------------------------------------------------------------------
// Phone / small tablet: one pane at a time, switched with tabs (all three stay mounted so audio and state persist)
// ---------------------------------------------------------------------------
type PaneTab = 'board' | 'chat' | 'pages';
const PANE_TABS: { id: PaneTab; label: string }[] = [
  { id: 'board', label: 'Board' },
  { id: 'chat', label: 'Chat' },
  { id: 'pages', label: 'Pages' },
];

function PhoneTabs({ tab, onChange, unread }: Readonly<{
  tab: PaneTab; onChange: (t: PaneTab) => void; unread: Partial<Record<PaneTab, boolean>>;
}>) {
  const onKey = (e: React.KeyboardEvent) => {
    const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = PANE_TABS[(PANE_TABS.findIndex(t => t.id === tab) + step + PANE_TABS.length) % PANE_TABS.length];
    onChange(next.id);
    document.getElementById(`tab-${next.id}`)?.focus();
  };
  return (
    <div role="tablist" tabIndex={-1} aria-label="Sections" onKeyDown={onKey} style={{
      display: 'flex', borderBottom: '1px solid var(--border)', background: 'var(--bg)', flexShrink: 0,
    }}>
      {PANE_TABS.map(t => (
        <button
          key={t.id}
          id={`tab-${t.id}`}
          role="tab"
          aria-selected={tab === t.id}
          aria-controls={`pane-${t.id}`}
          tabIndex={tab === t.id ? 0 : -1}
          onClick={() => onChange(t.id)}
          style={{
            flex: 1, minHeight: '44px', background: 'transparent', border: 'none', cursor: 'pointer',
            borderBottom: tab === t.id ? '2px solid var(--accent)' : '2px solid transparent',
            color: tab === t.id ? 'var(--ink)' : 'var(--ink-2)', fontSize: '14px', fontWeight: tab === t.id ? 600 : 500,
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '6px',
          }}
        >
          {t.label}
          {unread[t.id] && tab !== t.id && (
            <>
              <span aria-hidden="true" style={{ width: '7px', height: '7px', borderRadius: '50%', background: 'var(--accent)' }} />
              <span className="sr-only"> (new)</span>
            </>
          )}
        </button>
      ))}
    </div>
  );
}

function Pane({ id, active, phone, children }: { id: PaneTab; active: boolean; phone: boolean; children: React.ReactNode }) {
  // Wide screens: transparent wrapper (children lay out as before). Phones: only the active pane is displayed.
  return phone ? (
    <div id={`pane-${id}`} role="tabpanel" aria-labelledby={`tab-${id}`}
         style={{ display: active ? 'flex' : 'none', flex: 1, minWidth: 0, minHeight: 0, flexDirection: 'column' }}>
      {children}
    </div>
  ) : (
    <div style={{ display: 'contents' }}>{children}</div>
  );
}

// ---------------------------------------------------------------------------
// Main tutor UI
// ---------------------------------------------------------------------------
function TutorApp({ notebook, onExit }: Readonly<{ notebook: Notebook; onExit: () => void }>) {
  const [pages, setPages] = useState<PageSummary[]>([]);
  const phone = useMediaQuery('(max-width: 820px)');
  const compact = useMediaQuery('(max-width: 1200px)');
  const layout = phone ? 'phone' : compact ? 'compact' : 'wide';
  const [tab, setTab] = useState<PaneTab>('board');
  const [unread, setUnread] = useState<Partial<Record<PaneTab, boolean>>>({});
  const tabRef = useRef(tab);
  tabRef.current = tab;
  const phoneRef = useRef(phone);
  phoneRef.current = phone;
  const switchTab = (t: PaneTab) => {
    setTab(t);
    setUnread(u => ({ ...u, [t]: false }));
  };
  const [activePageId, setActivePageId] = useState<string | null>(null);
  const [chatHistory, setChatHistory] = useState<ChatTurn[]>([]);
  const [isAgentThinking, setIsAgentThinking] = useState(false);
  const [voiceNotice, setVoiceNotice] = useState(false);
  const [isReplaying, setIsReplaying] = useState(false);
  const [replayEvents, setReplayEvents] = useState<any[]>([]);

  // Pass 3 Modals & Inline edits
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [showLearner, setShowLearner] = useState(false);
  const learner = useLearner();
  const [showSummaryModal, setShowSummaryModal] = useState(false);
  const summaryDialogRef = useDialogFocus(showSummaryModal);
  const shortcutsDialogRef = useDialogFocus(showShortcuts);
  const [isEditingNotebook, setIsEditingNotebook] = useState(false);
  const [themePref, setThemePref] = useThemePref();
  const [notebookTopic, setNotebookTopic] = useState(notebook.topic);

  // Audio settings
  // (remembered between visits: a learner who turned the voice off or up should not have to do it every time)
  const [isAudioMuted, setIsAudioMuted] = useState(() => storedSetting('voiceMuted') === '1');
  const [audioSpeed, setAudioSpeed] = useState(() => {
    const v = Number(storedSetting('voiceSpeed'));
    return [0.75, 1, 1.25, 1.5].includes(v) ? v : 1;
  });
  useEffect(() => { storeSetting('voiceMuted', isAudioMuted ? '1' : '0'); }, [isAudioMuted]);
  useEffect(() => { storeSetting('voiceSpeed', String(audioSpeed)); }, [audioSpeed]);

  // Learner spatial grounding intent
  const [activeLearnerIntent, setActiveLearnerIntent] = useState<LearnerIntent | null>(null);

  // WS event routing
  const [pendingDraw, setPendingDraw] = useState<WsElementDrawn['payload'] | null>(null);
  const [pendingModify, setPendingModify] = useState<WsElementModified['payload'] | null>(null);
  const [pendingAnnotate, setPendingAnnotate] = useState<AnnotationPayload | null>(null);
  const [pendingRemoveAnnotation, setPendingRemoveAnnotation] = useState<{ page_id: string; annotation_id: string } | null>(null);
  const [pendingRemoveElement, setPendingRemoveElement] = useState<{ page_id: string; element_id: string; annotation_ids: string[] } | null>(null);

  // -------------------------------------------------------------------------
  // Load notebook pages on mount & restore exact page
  // -------------------------------------------------------------------------
  const [lessonBoard, setLessonBoard] = useState(false);   // scene mode: a page never fills up, so no fullness meter
  const fetchPages = useCallback(async () => {
    const res = await api.getNotebook(notebook.id);
    if (res.ok) {
      const data = await res.json();
      const ps: PageSummary[] = data.pages ?? [];
      setPages(ps);
      setLessonBoard(!!data.lesson_board);

      const urlParams = new URLSearchParams(globalThis.location.search);
      const urlPageId = urlParams.get('page_id') || localStorage.getItem(`last_page_${notebook.id}`);
      const matchedPage = ps.find(p => p.id === urlPageId);

      const target = matchedPage || ps.findLast(p => p.status === 'active') || ps.at(-1);
      if (target && !activePageId) setActivePageId(target.id);
      if (data.chat_turns && Array.isArray(data.chat_turns)) {
        setChatHistory(data.chat_turns);
      }
    }
  }, [notebook.id, activePageId]);

  useEffect(() => { fetchPages(); }, [notebook.id]);

  useEffect(() => {
    if (activePageId) {
      localStorage.setItem(`last_page_${notebook.id}`, activePageId);
      const url = new URL(globalThis.location.href);
      url.searchParams.set('notebook_id', notebook.id);
      url.searchParams.set('page_id', activePageId);
      globalThis.history.replaceState({}, '', url.toString());
    }
  }, [activePageId, notebook.id]);

  useEffect(() => {
    const handleReconnect = () => {
      debug('[App] Network reconnected — refreshing pages and chat history');
      fetchPages();
    };
    globalThis.addEventListener('notebook_reconnected', handleReconnect);
    return () => globalThis.removeEventListener('notebook_reconnected', handleReconnect);
  }, [fetchPages]);

  // -------------------------------------------------------------------------
  // WebSocket event handling
  // -------------------------------------------------------------------------
  const handleWsEvent = useCallback((ev: WsEvent) => {
    switch (ev.type) {
      case 'element_drawn':
        if (phoneRef.current && tabRef.current !== 'board') setUnread(u => ({ ...u, board: true }));
        setIsAgentThinking(false);
        if (ev.payload.voice_ok === false) {
          setVoiceNotice(true);
          setTimeout(() => setVoiceNotice(false), 10000);
        }
        setPendingDraw(ev.payload);
        setPages(prev => prev.map(p =>
          p.id === ev.payload.page_id ? { ...p, element_count: (p.element_count || 0) + 1 } : p
        ));
        break;
      case 'element_removed':
        setPendingRemoveElement(ev.payload);
        setPages(prev => prev.map(p =>
          p.id === ev.payload.page_id ? { ...p, element_count: Math.max(0, (p.element_count || 0) - 1) } : p
        ));
        break;
      case 'element_modified':
        setPendingModify(ev.payload);
        break;
      case 'element_annotated':
        setPendingAnnotate(ev.payload);
        break;
      case 'annotation_removed':
        setPendingRemoveAnnotation(ev.payload);
        break;
      case 'page_density_nudge':
        debug('[Density nudge]', ev.payload);
        break;
      case 'page_density_hard_cap':
        console.warn('[Density hard cap]', ev.payload);
        break;
      case 'page_saved':
        setPages(prev => prev.map(p =>
          p.id === ev.payload.page_id ? { ...p, status: 'saved' } : p
        ));
        break;
      case 'page_started':
        fetchPages();
        setActivePageId(ev.payload.page_id);
        break;
      case 'chat_turn':
        if (ev.payload.role === 'assistant') {
          if (phoneRef.current && tabRef.current !== 'chat') setUnread(u => ({ ...u, chat: true }));
          setIsAgentThinking(false);
          const cleanTurn = {
            ...ev.payload,
            content: (ev.payload.content || '').replaceAll(/\[{1,2}\s*mark\s*:[^[\]\n]*\]{1,2}\s*/gi, ''),
          };
          setChatHistory(prev => [...prev, cleanTurn as ChatTurn]);
        }
        break;
      case 'error':
        console.error('[Server error]', ev.payload.detail);
        setIsAgentThinking(false);
        break;
    }
  }, [fetchPages]);

  const { isConnected } = useNotebookWebSocket(notebook.id, handleWsEvent);

  // -------------------------------------------------------------------------
  // Chat
  // -------------------------------------------------------------------------
  const handleUserMessage = (text: string) => {
    setChatHistory(prev => [...prev, { role: 'user', content: text }]);
    setIsAgentThinking(true);
  };

  // "Try again" on an unanswered question: the failed reply goes away and the same learner turn is sent again (no second learner bubble).
  const handleRetryStart = () => {
    setChatHistory(prev => prev.filter(t => t.status !== 'failed'));
    setIsAgentThinking(true);
  };

  const handleAgentResponse = (_text: string, pageId: string) => {
    setIsAgentThinking(false);
    if (pageId !== activePageId) {
      setActivePageId(pageId);
      fetchPages();
    }
  };

  // -------------------------------------------------------------------------
  // Page actions
  // -------------------------------------------------------------------------
  const activeIndex = pages.findIndex(p => p.id === activePageId);

  const handleBack = () => {
    if (activeIndex > 0) setActivePageId(pages[activeIndex - 1].id);
  };

  const handleForward = () => {
    if (activeIndex < pages.length - 1) setActivePageId(pages[activeIndex + 1].id);
  };

  const handleNewPage = async () => {
    const res = await api.createPage(notebook.id);
    if (res.ok) {
      const p = await res.json();
      await fetchPages();
      setActivePageId(p.id);
    }
  };

  const handleSavePage = async () => {
    if (!activePageId) return;
    await api.savePage(notebook.id, activePageId);
    setPages(prev => prev.map(p =>
      p.id === activePageId ? { ...p, status: 'saved' } : p
    ));
  };

  const handleRenamePage = async (pageId: string, newTitle: string) => {
    setPages(prev => prev.map(p => p.id === pageId ? { ...p, title: newTitle } : p));
    try {
      await api.renamePage(notebook.id, pageId, newTitle);
    } catch (err) {
      console.warn('Failed to persist page title', err);
    }
  };

  const handleDeletePage = async (pageId: string) => {
    try {
      await api.deletePage(notebook.id, pageId);
      const remaining = pages.filter(p => p.id !== pageId);
      setPages(remaining);
      if (activePageId === pageId && remaining.length > 0) {
        setActivePageId(remaining[0].id);
      }
    } catch (err) {
      console.warn('Failed to delete page', err);
    }
  };

  const handleSaveNotebookTopic = async () => {
    if (!notebookTopic.trim()) {
      setIsEditingNotebook(false);
      return;
    }
    try {
      await api.updateNotebook(notebook.id, { topic: notebookTopic.trim(), title: notebookTopic.trim() });
    } catch (err) {
      console.warn('Failed to update notebook topic', err);
    }
    setIsEditingNotebook(false);
  };

  const [replayFrom, setReplayFrom] = useState<string | null>(null);
  const handleReplay = async (fromId?: string) => {
    if (!activePageId || (isReplaying && !fromId)) return;
    if (fromId) globalThis.dispatchEvent(new CustomEvent('tutor_barge_in'));   // stop live narration / a running replay's clip first
    const res = await api.getPageEvents(notebook.id, activePageId);
    if (!res.ok) return;
    const data = await res.json();
    const replayableEvents = (data.events ?? []).filter((e: any) =>
      e.kind === 'draw' || e.kind === 'modify' || e.kind === 'annotate' || e.kind === 'remove_annotation'
    );
    if (replayableEvents.length === 0) return;
    setReplayFrom(fromId ?? null);
    setReplayEvents(replayableEvents);
    setIsReplaying(true);
  };

  const handleReplayDone = useCallback(() => {
    setIsReplaying(false);
    setReplayEvents([]);
  }, []);

  const handleDownloadMarkdownSummary = () => {
    let md = `# Learning Notebook: ${notebookTopic}\n`;
    md += `Created on: ${new Date(notebook.created_at).toLocaleDateString()}\n`;
    md += `Total Pages: ${pages.length} | Total Discussion Turns: ${chatHistory.length}\n\n`;
    md += `---\n\n## Table of Contents\n`;
    pages.forEach((p, idx) => {
      md += `${idx + 1}. **${p.title || `Page ${idx + 1}`}** (${p.status})\n`;
      if (p.summary) md += `   - *${p.summary}*\n`;
    });
    md += `\n---\n\n## Discussion Transcript\n\n`;
    chatHistory.filter(t => t.status !== 'failed' && (t.content || '').trim()).forEach(turn => {
      md += `### ${turn.role === 'user' ? 'Learner' : 'Tutor'}\n${turn.content}\n\n`;
    });

    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${notebookTopic.replaceAll(/[^a-zA-Z0-9_-]/g, '_')}_summary.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // Keyboard shortcut listener
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const t = e.target instanceof Element ? e.target : null;   // WCAG 2.1.4: '?' is a shortcut only outside form fields and buttons (document/window targets: no element)
      if (e.key === '?' && !t?.closest('input, textarea, select, button, [contenteditable], [role="button"], [role="textbox"]')) {
        e.preventDefault();
        setShowShortcuts(v => !v);
      }
      if (e.key === 'Escape') {
        setShowShortcuts(false);
        setShowSummaryModal(false);
        setIsEditingNotebook(false);
      }
    };
    globalThis.addEventListener('keydown', handleKeyDown);
    return () => globalThis.removeEventListener('keydown', handleKeyDown);
  }, []);

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', background: 'var(--bg)' }}>
      {/* Top bar */}
      <header style={{
        height: '48px',
        background: 'var(--bg)',
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        alignItems: 'center',
        padding: '0 16px',
        gap: '14px',
        flexShrink: 0,
      }}>
        <button
          onClick={onExit}
          style={{
            background: 'transparent', border: 'none', color: 'var(--ink-2)', cursor: 'pointer',
            fontSize: '13px', fontWeight: 500, padding: '4px 6px', borderRadius: '6px',
          }}
        >
          Notebooks
        </button>

        {isEditingNotebook ? (
          <input
            value={notebookTopic}
            onChange={e => setNotebookTopic(e.target.value)}
            onBlur={handleSaveNotebookTopic}
            onKeyDown={e => {
              if (e.key === 'Enter') handleSaveNotebookTopic();
              if (e.key === 'Escape') setIsEditingNotebook(false);
            }}
            aria-label="Notebook name"
            maxLength={300}
            autoFocus
            style={{
              background: 'var(--panel)', border: '1px solid var(--accent)', borderRadius: '6px',
              color: 'var(--ink)', fontSize: '15px', fontWeight: 600, padding: '3px 8px', minWidth: '220px',
            }}
          />
        ) : (
          <h1
            onDoubleClick={() => setIsEditingNotebook(true)}
            title="Double-click to rename"
            style={{
              margin: 0, color: 'var(--ink)', fontSize: '15px', fontWeight: 600, letterSpacing: '-0.01em',
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '50vw',
            }}
          >
            {parseTopic(notebookTopic).text}
          </h1>
        )}

        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '10px' }}>
          <output
            title={isConnected ? 'Connected' : 'Reconnecting…'}
            style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', color: 'var(--ink-2)', fontSize: '12px' }}
          >
            <span aria-hidden="true" style={{
              width: '7px', height: '7px', borderRadius: '50%',
              background: isConnected ? 'var(--ok)' : 'var(--danger)',
            }} />
            {isConnected ? <span className="sr-only">Connected</span> : 'Reconnecting…'}
          </output>
          <Menu label="Notebook" items={[
            { label: 'Overview and export', onSelect: () => setShowSummaryModal(true) },
            { label: 'Rename notebook', onSelect: () => setIsEditingNotebook(true) },
            { label: 'What I know about you', onSelect: () => setShowLearner(true) },
            { label: 'Keyboard shortcuts', onSelect: () => setShowShortcuts(true) },
            { heading: 'Appearance' },
            ...THEME_CHOICES.map(t => ({
              label: t.label, kind: 'radio' as const, checked: themePref === t.id, onSelect: () => setThemePref(t.id),
            })),
          ]} />
        </div>
      </header>

      {phone && <PhoneTabs tab={tab} onChange={switchTab} unread={unread} />}

      {/* Main layout: three columns; on phones one pane at a time */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
        <Pane id="pages" active={tab === 'pages'} phone={phone}>
        <PageSidebar
          layout={layout}
          pages={pages}
          activePageId={activePageId}
          isReplaying={isReplaying}
          onSelectPage={(id) => { setActivePageId(id); if (phone) switchTab('board'); }}
          onNewPage={async () => { await handleNewPage(); if (phone) switchTab('board'); }}
          onSavePage={handleSavePage}
          onReplayPage={() => { handleReplay(); if (phone) switchTab('board'); }}
          onBack={handleBack}
          onForward={handleForward}
          onRenamePage={handleRenamePage}
          onDeletePage={handleDeletePage}
          showFullness={!lessonBoard}
        />
        </Pane>

        <Pane id="board" active={tab === 'board'} phone={phone}>
        <WhiteboardCanvas
          notebookId={notebook.id}
          pageId={activePageId}
          pendingDrawEvent={pendingDraw}
          pendingModifyEvent={pendingModify}
          pendingAnnotateEvent={pendingAnnotate}
          pendingRemoveAnnotationEvent={pendingRemoveAnnotation}
          pendingRemoveElementEvent={pendingRemoveElement}
          pageStatus={pages.find(p => p.id === activePageId)?.status}
          replayEvents={replayEvents}
          isReplaying={isReplaying}
          onReplayDone={handleReplayDone}
          replayFrom={replayFrom}
          onReplayFrom={id => handleReplay(id)}
          isMuted={isAudioMuted}
          playbackSpeed={audioSpeed}
          onPlaybackSpeedChange={setAudioSpeed}
          activeLearnerIntent={activeLearnerIntent}
          onLearnerIntentChange={setActiveLearnerIntent}
          onAskAboutSelection={(intent) => {
            setActiveLearnerIntent(intent);
            globalThis.dispatchEvent(
              new CustomEvent('ask_tutor_about_selection', { detail: intent })
            );
          }}
        />
        </Pane>

        <Pane id="chat" active={tab === 'chat'} phone={phone}>
        <ChatPanel
          onOpenLearnerPanel={() => setShowLearner(true)}
          layout={layout}
          notebookId={notebook.id}
          pageId={activePageId}
          chatHistory={chatHistory}
          isAgentThinking={isAgentThinking}
          voiceUnavailable={voiceNotice}
          onSendMessage={handleUserMessage}
          onRetryStart={handleRetryStart}
          onAgentResponse={handleAgentResponse}
          isAudioMuted={isAudioMuted}
          onToggleMute={() => setIsAudioMuted(v => !v)}
          audioSpeed={audioSpeed}
          onSpeedChange={setAudioSpeed}
          activeLearnerIntent={activeLearnerIntent}
          onClearLearnerIntent={() => setActiveLearnerIntent(null)}
        />
        </Pane>
      </div>

      {/* Notebook Summary Modal */}
      {showSummaryModal && (
        <>
          <dialog ref={summaryDialogRef} className="learner-dialog" tabIndex={-1} aria-label="Notebook summary"
                  onCancel={e => { e.preventDefault(); setShowSummaryModal(false); }} style={{
            color: 'inherit', maxWidth: 'calc(100% - 24px)',
            background: 'var(--panel)',
            border: '1px solid var(--border)',
            borderRadius: '16px',
            padding: '24px',
            width: '480px',
            maxHeight: '80vh',
            display: 'flex',
            flexDirection: 'column',
            boxShadow: '0 25px 50px -12px rgba(31, 42, 55, 0.18)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div>
                <h3 style={{ margin: 0, color: 'var(--ink)', fontSize: '16px', fontWeight: 700 }}>
                  📑 Notebook Overview
                </h3>
                <span style={{ color: 'var(--ink-2)', fontSize: '12px' }}>{parseTopic(notebookTopic).text}</span>
              </div>
              <button
                onClick={() => setShowSummaryModal(false)}
                aria-label="Close notebook overview"
                style={{ background: 'transparent', border: 'none', color: 'var(--ink-2)', cursor: 'pointer', fontSize: '16px' }}
              >
                ✕
              </button>
            </div>

            {/* Metrics */}
            <div style={{ display: 'flex', gap: '12px', marginBottom: '16px' }}>
              <div style={{ flex: 1, background: 'var(--panel-2)', padding: '10px 14px', borderRadius: '8px' }}>
                <span style={{ fontSize: '12px', color: 'var(--ink-2)', display: 'block' }}>PAGES</span>
                <strong style={{ fontSize: '18px', color: 'var(--accent)' }}>{pages.length}</strong>
              </div>
              <div style={{ flex: 1, background: 'var(--panel-2)', padding: '10px 14px', borderRadius: '8px' }}>
                <span style={{ fontSize: '12px', color: 'var(--ink-2)', display: 'block' }}>CHAT TURNS</span>
                <strong style={{ fontSize: '18px', color: 'var(--ok)' }}>{chatHistory.length}</strong>
              </div>
            </div>

            {/* Pages Table of Contents */}
            <div style={{ flex: 1, overflowY: 'auto', marginBottom: '16px' }}>
              <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--ink-2)', textTransform: 'uppercase', marginBottom: '8px' }}>
                Concept Outline
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {pages.map((p, idx) => (
                  <div key={p.id} style={{ background: 'var(--panel-2)', padding: '8px 12px', borderRadius: '6px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: 'var(--ink)', fontWeight: 500 }}>
                      <span>{idx + 1}. {p.title || `Page ${idx + 1}`}</span>
                      <span style={{ fontSize: '12px', color: p.status === 'active' ? 'var(--ok)' : 'var(--ink-2)' }}>
                        {p.status}
                      </span>
                    </div>
                    {p.summary && (
                      <p style={{ margin: '4px 0 0', fontSize: '12px', color: 'var(--ink-2)' }}>{p.summary}</p>
                    )}
                  </div>
                ))}
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', flexWrap: 'wrap' }}>
              <button
                onClick={handleDownloadMarkdownSummary}
                style={{
                  padding: '8px 14px', borderRadius: '6px',
                  background: 'var(--panel-2)', border: '1px solid var(--border-strong)', color: 'var(--ink)',
                  fontSize: '12px', fontWeight: 600, cursor: 'pointer',
                }}
              >
                Chat transcript (.md)
              </button>
              <button
                onClick={() => globalThis.open(`/api/notebooks/${notebook.id}/export?download=true`, '_self')}
                style={{
                  padding: '8px 14px', borderRadius: '6px',
                  background: 'var(--panel-2)', border: '1px solid var(--border-strong)', color: 'var(--ink)',
                  fontSize: '12px', fontWeight: 600, cursor: 'pointer',
                }}
              >
                Download notebook (.html)
              </button>
              <button
                onClick={() => globalThis.open(`/api/notebooks/${notebook.id}/export?print=1`, '_blank', 'noopener')}
                style={{
                  padding: '8px 14px', borderRadius: '6px',
                  background: 'var(--accent)', border: 'none', color: 'var(--on-accent)',
                  fontSize: '12px', fontWeight: 600, cursor: 'pointer',
                }}
              >
                Save as PDF
              </button>
            </div>
          </dialog>
        </>
      )}

      {showLearner && <LearnerPanel learner={learner} onClose={() => setShowLearner(false)} />}

      {/* Keyboard Shortcuts Modal */}
      {showShortcuts && (
        <>
          <dialog ref={shortcutsDialogRef} className="learner-dialog" tabIndex={-1} aria-label="Keyboard shortcuts"
                  onCancel={e => { e.preventDefault(); setShowShortcuts(false); }} style={{
            color: 'inherit', maxWidth: 'calc(100% - 24px)',
            background: 'var(--panel)',
            border: '1px solid var(--border)',
            borderRadius: '16px',
            padding: '24px',
            width: '400px',
            boxShadow: '0 25px 50px -12px rgba(31, 42, 55, 0.18)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h3 style={{ margin: 0, color: 'var(--ink)', fontSize: '16px', fontWeight: 700 }}>
                ⌨️ Keyboard Shortcuts
              </h3>
              <button
                onClick={() => setShowShortcuts(false)}
                aria-label="Close keyboard shortcuts"
                style={{ background: 'transparent', border: 'none', color: 'var(--ink-2)', cursor: 'pointer', fontSize: '16px' }}
              >
                ✕
              </button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '13px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--ink)' }}>
                <span>Send message</span>
                <kbd style={{ background: 'var(--panel-2)', padding: '2px 8px', borderRadius: '4px', fontSize: '12px', color: 'var(--accent)' }}>Enter</kbd>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--ink)' }}>
                <span>New line in chat</span>
                <kbd style={{ background: 'var(--panel-2)', padding: '2px 8px', borderRadius: '4px', fontSize: '12px', color: 'var(--accent)' }}>Shift + Enter</kbd>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--ink)' }}>
                <span>Zoom canvas in / out</span>
                <kbd style={{ background: 'var(--panel-2)', padding: '2px 8px', borderRadius: '4px', fontSize: '12px', color: 'var(--accent)' }}>+ / −</kbd>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--ink)' }}>
                <span>Undo the last drawing</span>
                <kbd style={{ background: 'var(--panel-2)', padding: '2px 8px', borderRadius: '4px', fontSize: '12px', color: 'var(--accent)' }}>Ctrl + Z</kbd>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--ink)' }}>
                <span>Pan canvas</span>
                <kbd style={{ background: 'var(--panel-2)', padding: '2px 8px', borderRadius: '4px', fontSize: '12px', color: 'var(--accent)' }}>Click + Drag</kbd>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--ink)' }}>
                <span>Toggle shortcuts dialog</span>
                <kbd style={{ background: 'var(--panel-2)', padding: '2px 8px', borderRadius: '4px', fontSize: '12px', color: 'var(--accent)' }}>?</kbd>
              </div>
            </div>

            <div style={{ marginTop: '20px', textAlign: 'right' }}>
              <button
                onClick={() => setShowShortcuts(false)}
                style={{
                  padding: '6px 14px', borderRadius: '6px',
                  background: 'var(--accent)', border: 'none', color: 'var(--on-accent)',
                  fontSize: '12px', fontWeight: 600, cursor: 'pointer',
                }}
              >
                Got it
              </button>
            </div>
          </dialog>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Root App
// ---------------------------------------------------------------------------
export default function App() {
  const [activeNotebook, setActiveNotebook] = useState<Notebook | null>(null);

  useEffect(() => {
    let unlocked = false;
    const unlock = () => {
      if (unlocked) return;
      unlocked = true;
      const silentAudio = new Audio(
        'data:audio/mp3;base64,SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjU4LjI5LjEwMAAAAAAAAAAAAAAA//tQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAWGluZwAAAA8AAAACAAABhgC2trb/////////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB//sQRAAP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAETEFNRTMuMTAwVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV'
      );
      silentAudio.volume = 0;
      silentAudio.play().catch(() => {});
      document.removeEventListener('click', unlock, true);
      document.removeEventListener('keydown', unlock, true);
    };
    document.addEventListener('click', unlock, true);
    document.addEventListener('keydown', unlock, true);
    return () => {
      document.removeEventListener('click', unlock, true);
      document.removeEventListener('keydown', unlock, true);
    };
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(globalThis.location.search);
    const nbId = params.get('notebook_id') || localStorage.getItem('last_active_notebook_id');
    if (nbId) {
      api.getNotebook(nbId)
        .then(r => r.json())
        .then(nb => {
          if (nb?.id) {
            setActiveNotebook(nb);
            const url = new URL(globalThis.location.href);
            url.searchParams.set('notebook_id', nb.id);
            globalThis.history.replaceState({}, '', url.toString());
          }
        })
        .catch(console.error);
    }
  }, []);

  const handleSelectNotebook = (nb: Notebook) => {
    setActiveNotebook(nb);
    localStorage.setItem('last_active_notebook_id', nb.id);
    const url = new URL(globalThis.location.href);
    url.searchParams.set('notebook_id', nb.id);
    globalThis.history.replaceState({}, '', url.toString());
  };

  const handleExit = () => {
    localStorage.removeItem('last_active_notebook_id');
    globalThis.history.replaceState({}, '', globalThis.location.pathname);
    setActiveNotebook(null);
  };

  return activeNotebook ? (
    <TutorApp notebook={activeNotebook} onExit={handleExit} />
  ) : (
    <NewNotebookScreen onCreate={handleSelectNotebook} />
  );
}
