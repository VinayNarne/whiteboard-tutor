// frontend/src/components/ChatPanel.tsx
// Right-hand chat panel. Learner types; agent responds in text and draws on the board.
// Pass 2 Features: Audio voice mute & speed controls, animated soundwave indicator,
// Context-aware follow-up pills, full code block rendering with 1-click copy,
// Markdown formatting, message timestamps, and turn counter.

import { useState, useRef, useEffect } from 'react';
import type { ChatTurn, LearnerIntent } from '../types';
import { useVoiceInput } from '../hooks/useVoiceInput';
import { Menu } from './Menu';
import { debug } from '../utils/debug';

interface Props {
  notebookId: string;
  pageId: string | null;
  chatHistory: ChatTurn[];
  isAgentThinking: boolean;
  voiceUnavailable?: boolean;
  onSendMessage?: (text: string) => void;
  onRetryStart?: () => void;
  onAgentResponse: (text: string, pageId: string) => void;
  isAudioMuted?: boolean;
  onToggleMute?: () => void;
  audioSpeed?: number;
  onSpeedChange?: (speed: number) => void;
  activeLearnerIntent?: LearnerIntent | null;
  onClearLearnerIntent?: () => void;
  layout?: 'wide' | 'compact' | 'phone';
}

const MAX_MESSAGE_CHARS = 4000;   // same limit the server enforces

const QUICK_PROMPTS = [
  { label: 'Simpler analogy', prompt: 'Can you explain this with a simple everyday analogy?' },
  { label: 'Real example', prompt: 'Give me a concrete real-world engineering or practical example.' },
  { label: 'Step by step', prompt: 'Can you break this down and draw the step-by-step flow from start to finish?' },
  { label: 'Quiz me', prompt: 'Ask me a quick conceptual question or quiz to test my understanding.' },
  { label: 'Next concept', prompt: "That makes complete sense! Let's move to the next concept on a new page." },
];

export function ChatPanel({
  notebookId,
  pageId,
  chatHistory,
  isAgentThinking,
  voiceUnavailable,
  onSendMessage,
  onRetryStart,
  onAgentResponse,
  isAudioMuted = false,
  onToggleMute,
  audioSpeed = 1.0,
  onSpeedChange,
  activeLearnerIntent,
  onClearLearnerIntent,
  layout = 'wide',
}: Props) {
  const [input, setInput] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [dismissVoiceError, setDismissVoiceError] = useState(false);
  const [isHandsFree, setIsHandsFree] = useState(() => {
    try { return localStorage.getItem('handsFree') === '1'; } catch { return false; }
  });
  const dictationBase = useRef('');   // what was already in the box when dictation started
  const [bargeInNotice, setBargeInNotice] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  // Fit the box to its text on every change: typing, dictation, and clearing after Send (which fires no input event).
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  }, [input]);

  const {
    isListening,
    isTranscribing,
    audioLevel,
    error: voiceError,
    startListening,
    stopListening,
    resetTranscript,
  } = useVoiceInput({
    notebookId,
    autoSend: isHandsFree,
    onTranscriptChange: (text) => {
      setInput((dictationBase.current ? `${dictationBase.current} ${text}` : text).slice(0, MAX_MESSAGE_CHARS));
    },
    onAutoSend: (finalText) => {
      debug('[ChatPanel] VAD Hands-Free auto-dispatching:', finalText);
      sendQuery(finalText);
    },
    onError: (err) => {
      setDismissVoiceError(false);
      console.warn('Voice input error:', err);
    },
  });

  const toggleVoiceInput = () => {
    if (isListening) {
      stopListening();
    } else {
      setDismissVoiceError(false);
      resetTranscript();
      dictationBase.current = input.trim();
      startListening();
    }
  };

  const toggleHandsFree = (on: boolean) => {
    setIsHandsFree(on);
    try { localStorage.setItem('handsFree', on ? '1' : '0'); } catch { /* remembered for this visit only */ }
  };

  useEffect(() => {
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      if (e.altKey && e.code === 'KeyM') {
        e.preventDefault();
        toggleVoiceInput();
      }
    };
    window.addEventListener('keydown', handleGlobalKeyDown);
    return () => window.removeEventListener('keydown', handleGlobalKeyDown);
  }, [isListening]);

  // Phase 2: Listen for barge-in interruption events
  useEffect(() => {
    const handleBargeInEvent = () => {
      if (isAgentThinking) {
        fetch(`/api/notebooks/${notebookId}/interrupt`, { method: 'POST' }).catch(() => {});
        setBargeInNotice(true);
        setTimeout(() => setBargeInNotice(false), 2500);
      }
    };
    window.addEventListener('tutor_barge_in', handleBargeInEvent);
    return () => window.removeEventListener('tutor_barge_in', handleBargeInEvent);
  }, [isAgentThinking, notebookId]);

  // "Today's path": the lesson plan's step titles with the level each has earned (taught, understood, remembered after a surprise review),
  // worked out on the server from what the tutor recorded (scene mode; empty otherwise). Fetched on open and when a tutor reply arrives:
  // the reply is sent after the turn and its records are saved ("thinking" ends at the first drawing, which showed the previous turn's levels).
  const [path, setPath] = useState<Array<{ title: string; level: '' | 'taught' | 'understood' | 'remembered' }>>([]);
  // the end-of-lesson check: one question per step, then a problem that needs them together; weak = steps to review
  const [final, setFinal] = useState<{ active: boolean; next: number | 'problem' | null; checked: number; of: number; weak: number[]; passed: boolean } | null>(null);
  const [goal, setGoal] = useState<string | null>(null);   // the learner's overall goal (the course), shown above the current lesson's path
  const tutorReplies = chatHistory.filter(t => t.role === 'assistant').length;
  useEffect(() => {
    let live = true;
    fetch(`/api/notebooks/${notebookId}`).then(r => (r.ok ? r.json() : null)).then(d => { if (live && d) { setPath(d.lesson_path ?? []); setFinal(d.lesson_final ?? null); setGoal(d.goal ?? null); } }).catch(() => {});
    return () => { live = false; };
  }, [notebookId, tutorReplies]);

  useEffect(() => {
    const calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    // Scroll the conversation list only: scrollIntoView also scrolled the whole page, which hid the toolbar and left an empty strip below the app
    const list = bottomRef.current?.parentElement;
    list?.scrollTo({ top: list.scrollHeight, behavior: calm ? 'auto' : 'smooth' });
  }, [chatHistory, isAgentThinking]);

  // retryTurnId: the learner turn the tutor never answered; the server sends that same turn again (no second learner turn is created).
  const sendQuery = async (queryText: string, overrideIntent?: LearnerIntent | null, retryTurnId?: string) => {
    const message = queryText.trim();
    if (!message || isSending) return;

    stopListening({ discard: true });   // also drops words Deepgram is still sending, so they cannot refill the box

    if (!retryTurnId) setInput('');
    setSendError(null);
    setIsSending(true);
    if (retryTurnId) {
      onRetryStart?.();
    } else if (onSendMessage) {
      onSendMessage(message);
    }

    const intentToUse = overrideIntent !== undefined ? overrideIntent : activeLearnerIntent;

    try {
      const payload: Record<string, any> = { message, page_id: pageId };
      if (retryTurnId) payload.retry_turn_id = retryTurnId;
      if (intentToUse && intentToUse.selectedElementIds && intentToUse.selectedElementIds.length > 0) {
        payload.selected_element_ids = intentToUse.selectedElementIds;
        payload.gesture_type = intentToUse.gestureType;
        payload.match_score = intentToUse.topScore;
      }

      const res = await fetch(`/api/notebooks/${notebookId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        const data = await res.json();
        onAgentResponse(data.response, data.page_id);
      } else {
        const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
        if (err.retryable === true && typeof err.error === 'string') {
          // A typed failure (model_unreachable, empty_reply, turn_failed): the server keeps the question and sends the failed reply as a tutor turn
          // (an error bubble with "Try again"); nothing else to show.
          onAgentResponse('', pageId || '');
          return;
        }
        if (res.status === 429 || res.status === 422) setInput(message); // keep what the learner typed
        const friendly = res.status === 422
          ? 'That message could not be sent. Please keep it under 4,000 characters.'
          : typeof err.detail === 'string' ? err.detail : 'Something went wrong. Please try again.';
        setSendError(friendly);
        onAgentResponse(friendly, pageId || '');
      }
    } catch (e) {
      const down = 'Could not reach the server. Check that it is running, then try again.';
      setSendError(down);
      setInput(message);
      onAgentResponse(down, pageId || '');
    } finally {
      setIsSending(false);
      onClearLearnerIntent?.();
      inputRef.current?.focus();
    }
  };

  useEffect(() => {
    const handleAskSelection = (e: any) => {
      const intent: LearnerIntent = e.detail;
      if (!intent || !intent.candidates || intent.candidates.length === 0) return;

      if (intent.intentType === 'relationship' && intent.candidates.length > 1) {
        const c0 = intent.candidates[0].label || intent.selectedElementIds[0];
        const c1 = intent.candidates[1].label || intent.selectedElementIds[1];
        sendQuery(`Can you explain how ${c0} and ${c1} connect and interact with each other in this system?`, intent);
      } else {
        const label = intent.candidates[0]?.label || intent.selectedElementIds[0];
        sendQuery(`Can you explain what ${label} does and how it works?`, intent);
      }
    };

    const handleSendChatQuery = (e: any) => {
      if (e.detail?.message) {
        sendQuery(e.detail.message, e.detail.intent);
      }
    };

    const focusInput = () => inputRef.current?.focus();   // "Ask…" on a board item: the learner types a question about it

    window.addEventListener('ask_tutor_about_selection', handleAskSelection);
    window.addEventListener('send_chat_query', handleSendChatQuery);
    window.addEventListener('focus_chat_input', focusInput);
    return () => {
      window.removeEventListener('ask_tutor_about_selection', handleAskSelection);
      window.removeEventListener('send_chat_query', handleSendChatQuery);
      window.removeEventListener('focus_chat_input', focusInput);
    };
  }, [notebookId, pageId, isSending, isListening, activeLearnerIntent]);

  const handleSend = () => sendQuery(input);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleCopyMessage = (text: string, index: number) => {
    navigator.clipboard.writeText(text);
    setCopiedIndex(index);
    setTimeout(() => setCopiedIndex(null), 1500);
  };

  const busy = isSending || isAgentThinking;
  const quickPrimary = QUICK_PROMPTS.slice(0, 3);
  const quickMore = QUICK_PROMPTS.slice(3);

  const strip: React.CSSProperties = {
    padding: '8px 16px', borderTop: '1px solid var(--border)', background: 'var(--panel-2)',
    fontSize: '13px', color: 'var(--ink-2)', display: 'flex', alignItems: 'center',
    justifyContent: 'space-between', gap: '10px',
  };
  const linkBtn: React.CSSProperties = {
    background: 'transparent', border: 'none', color: 'var(--ink)', fontSize: '13px', fontWeight: 500,
    cursor: 'pointer', padding: '2px 6px', borderRadius: '6px', textDecoration: 'underline', textUnderlineOffset: '2px',
  };
  const dot = (color: string, pulse = false): React.CSSProperties => ({
    width: '7px', height: '7px', borderRadius: '50%', background: color, flexShrink: 0,
    animation: pulse ? 'pulse 1s infinite' : undefined,
  });
  const groundedLabel = activeLearnerIntent?.relationshipLabel || activeLearnerIntent?.candidates[0]?.label;

  return (
    <div role="complementary" aria-label="AI tutor chat" style={{
      width: layout === 'phone' ? '100%' : layout === 'compact' ? '320px' : '380px',
      minWidth: layout === 'phone' ? 0 : layout === 'compact' ? '280px' : '320px',
      flex: layout === 'phone' ? 1 : undefined, minHeight: 0, display: 'flex', flexDirection: 'column',
      background: 'var(--bg)', borderLeft: layout === 'phone' ? 'none' : '1px solid var(--border)',
    }}>
      {/* Header: the tutor's name, a quiet working indicator, and the tutor's voice menu */}
      <div style={{
        padding: '8px 10px 8px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        borderBottom: '1px solid var(--border)', minHeight: '48px',
      }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '10px', fontSize: '15px', fontWeight: 600, color: 'var(--ink)' }}>
          Tutor
          {isAgentThinking && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '12px', fontWeight: 400, color: 'var(--ink-2)' }}>
              <span aria-hidden="true" style={dot('var(--accent)', true)} />
              Working…
            </span>
          )}
        </span>
        <Menu label={isAudioMuted ? "Tutor's voice: off" : "Tutor's voice"} items={[
          { heading: 'What you hear' },
          { label: 'Speak aloud', kind: 'toggle', checked: !isAudioMuted, onSelect: () => onToggleMute?.() },
          { heading: 'Speaking speed' },
          ...[1.0, 1.25, 1.5].map(spd => ({
            label: `${spd}x`, kind: 'radio' as const, checked: audioSpeed === spd, onSelect: () => onSpeedChange?.(spd),
          })),
        ]} />
      </div>

      {voiceUnavailable && (
        <div role="status" style={{ ...strip, background: 'var(--warn-soft)', color: 'var(--warn)', fontWeight: 500 }}>
          Voice is unavailable right now, so this explanation is text only. The drawing and chat still work.
        </div>
      )}

      {path.length > 0 && (
        <details className="lesson-path" open>
          <summary>Today's path · {path.filter(s => s.level === 'understood' || s.level === 'remembered').length} of {path.length} understood
            {path.some(s => s.level === 'remembered') && <>, {path.filter(s => s.level === 'remembered').length} remembered</>}</summary>
          {goal && <p className="lesson-path-goal">Your goal: {goal}</p>}
          <ol>
            {path.map((s, i) => (
              <li key={i} className={s.level ? `lvl-${s.level}` : undefined}>
                <span className="lesson-path-mark" aria-hidden="true">{s.level === 'remembered' ? '★' : s.level === 'understood' ? '✓' : i + 1}</span>
                <span className="lesson-path-title">{s.title}</span>
                {s.level && <span className="lesson-path-level">{s.level}</span>}
                {final?.passed && final.weak.includes(i + 1) && <span className="lesson-path-review">review</span>}
              </li>
            ))}
            {final?.active && (
              <li className={final.passed ? 'lvl-remembered' : undefined}>
                <span className="lesson-path-mark" aria-hidden="true">{final.passed ? '★' : '?'}</span>
                <span className="lesson-path-title">Final check</span>
                <span className="lesson-path-level">
                  {final.passed ? 'passed' : final.next === 'problem' ? 'final problem' : `${final.checked} of ${final.of} checked`}
                </span>
              </li>
            )}
          </ol>
        </details>
      )}

      {/* Conversation — a polite live log so screen readers hear the tutor's replies */}
      <div role="log" aria-live="polite" aria-label="Conversation with the AI tutor" style={{
        flex: 1, overflowY: 'auto', padding: '20px 16px', display: 'flex', flexDirection: 'column', gap: '18px',
        position: 'relative',   // holds the screen-reader-only "You:"/"Tutor:" labels: unheld, they sat below the window and made the page scroll
      }}>
        {chatHistory.length === 0 && (
          <div style={{ margin: '48px 12px 0', color: 'var(--ink-2)', fontSize: '13px', lineHeight: 1.6 }}>
            <div style={{ color: 'var(--ink)', fontSize: '15px', fontWeight: 600, marginBottom: '4px' }}>Ask anything</div>
            The tutor explains out loud and draws on the whiteboard as it goes.
          </div>
        )}

        {chatHistory.map((turn, i) => {
          const isUser = turn.role === 'user';
          if (!isUser && turn.status !== 'failed' && !(turn.content || '').trim()) return null;   // a tutor turn with no text (old notebooks) is never drawn
          if (turn.status === 'failed') {
            const lastTurn = i === chatHistory.length - 1;
            const question = chatHistory.slice(0, i).reverse().find(t => t.role === 'user')?.content;
            return (
              <div key={i} className="chat-turn-container" role="alert" style={{
                display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '8px 12px', padding: '8px 12px', borderRadius: '10px',
                background: 'var(--danger-soft)', color: 'var(--danger)', fontSize: '13px', lineHeight: 1.5,
              }}>
                <span>{lastTurn ? turn.content : "The tutor couldn't answer this one."}</span>
                {lastTurn && turn.retry_turn_id && question && (
                  <button type="button" disabled={busy} onClick={() => sendQuery(question, null, turn.retry_turn_id)}
                    style={{ ...linkBtn, color: 'var(--danger)', fontWeight: 600 }}>Try again</button>
                )}
              </div>
            );
          }
          return (
            <div
              key={i}
              className="chat-turn-container"
              style={{ display: 'flex', flexDirection: 'column', alignItems: isUser ? 'flex-end' : 'flex-start', gap: '4px' }}
            >
              <div style={isUser ? {
                maxWidth: '88%', padding: '8px 12px', borderRadius: '12px 12px 2px 12px',
                background: 'var(--panel)', border: '1px solid var(--border)',
                color: 'var(--ink)', fontSize: '13px', lineHeight: 1.6,
              } : {
                maxWidth: '100%', color: 'var(--ink)', fontSize: '14px', lineHeight: 1.65,
              }}>
                <span className="sr-only">{isUser ? 'You: ' : 'Tutor: '}</span>
                {renderRichContent(turn.content)}
              </div>
              {!isUser && (
                <div className="msg-actions">
                  <button onClick={() => handleCopyMessage(turn.content, i)} title="Copy explanation" style={{ ...linkBtn, color: 'var(--ink-2)', textDecoration: 'none', fontSize: '12px' }}>
                    {copiedIndex === i ? 'Copied' : 'Copy'}
                  </button>
                </div>
              )}
            </div>
          );
        })}

        {isAgentThinking && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--ink-2)', fontSize: '13px' }}>
            <span aria-hidden="true" style={dot('var(--accent)', true)} />
            Drawing and preparing the voice…
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Quick follow-ups: three plain chips, the rest behind "More" */}
      <div style={{ padding: '8px 12px 0', display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '6px' }}>
        {quickPrimary.map(qp => (
          <button
            key={qp.label}
            onClick={() => sendQuery(qp.prompt)}
            disabled={busy}
            className="quick-chip"
            style={{ opacity: busy ? 0.5 : 1, cursor: busy ? 'default' : 'pointer' }}
          >
            {qp.label}
          </button>
        ))}
        <Menu label="More" align="left" items={quickMore.map(q => ({
          label: q.label, onSelect: () => { if (!busy) sendQuery(q.prompt); },
        }))} />
      </div>

      {/* One consistent strip for every transient status */}
      {bargeInNotice && (
        <div role="status" style={{ ...strip, marginTop: '8px' }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
            <span aria-hidden="true" style={dot('var(--violet)')} />Tutor interrupted. Listening to your question…
          </span>
        </div>
      )}

      {sendError && (
        <div role="alert" style={{ ...strip, marginTop: '8px', background: 'var(--danger-soft)', color: 'var(--danger)' }}>
          <span>{sendError}</span>
          <button onClick={() => setSendError(null)} style={{ ...linkBtn, color: 'var(--danger)' }}>Dismiss</button>
        </div>
      )}

      {voiceError && !dismissVoiceError && (
        <div role="alert" style={{ ...strip, marginTop: '8px', background: 'var(--danger-soft)', color: 'var(--danger)' }}>
          <span>{voiceError}</span>
          <button onClick={() => setDismissVoiceError(true)} style={{ ...linkBtn, color: 'var(--danger)' }}>Dismiss</button>
        </div>
      )}

      {isTranscribing && (
        <div role="status" style={strip}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', color: 'var(--ink)' }}>
            <span aria-hidden="true" style={dot('var(--accent)', true)} />Transcribing your recording…
          </span>
        </div>
      )}

      {isListening && (
        <div style={{ ...strip, marginTop: '8px', flexWrap: 'wrap' }}>
          <span role="status" style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', color: 'var(--ink)' }}>
            <span aria-hidden="true" style={dot('var(--danger)', true)} />
            {isHandsFree ? 'Listening. I will send when you pause.' : 'Listening. Press Done when finished.'}
          </span>
          <span aria-hidden="true" style={{ display: 'flex', alignItems: 'center', gap: '3px', height: '16px' }}>
            {[0.4, 0.9, 1.2, 0.7, 0.5, 1.0, 0.6].map((mult, idx) => (
              <span key={idx} style={{
                width: '3px', borderRadius: '2px', background: 'var(--ink-2)', transition: 'height 0.08s ease',
                height: `${Math.max(3, Math.min(16, Math.round(audioLevel * 16 * mult)))}px`,
              }} />
            ))}
          </span>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', cursor: 'pointer', minHeight: '28px' }}>
            <input type="checkbox" checked={isHandsFree} onChange={e => toggleHandsFree(e.target.checked)} />
            Send when I pause
          </label>
          <button type="button" onClick={() => stopListening()} style={linkBtn}>Done</button>
        </div>
      )}

      {activeLearnerIntent && activeLearnerIntent.candidates.length > 0 && (
        <div style={{ ...strip, marginTop: '8px' }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
            <span aria-hidden="true" style={dot(activeLearnerIntent.intentType === 'relationship' ? 'var(--violet)' : 'var(--accent)')} />
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {activeLearnerIntent.intentType === 'relationship' ? 'Asking how these connect: ' : 'Asking about: '}
              <strong style={{ color: 'var(--ink)', fontWeight: 600 }}>{groundedLabel}</strong>
            </span>
          </span>
          <button onClick={() => onClearLearnerIntent?.()} style={linkBtn} aria-label="Remove the selection from my question">Remove</button>
        </div>
      )}

      {/* Input */}
      <div style={{ padding: '10px 12px 14px', display: 'flex', gap: '8px', alignItems: 'flex-end' }}>
        <textarea
          ref={inputRef}
          id="chat-input"
          aria-label="Message the tutor"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask a question…"
          rows={1}
          maxLength={MAX_MESSAGE_CHARS}
          disabled={isSending}
          style={{
            flex: 1, resize: 'none', background: 'var(--panel)',
            border: isListening ? '1px solid var(--danger)' : '1px solid var(--border-strong)',
            borderRadius: '10px', color: 'var(--ink)', fontSize: '14px', padding: '9px 12px',
            lineHeight: 1.5, maxHeight: '120px', overflowY: 'auto', fontFamily: 'inherit',
          }}
        />

        <button
          id="voice-mic-btn"
          type="button"
          onClick={toggleVoiceInput}
          aria-label="Speak your question"
          aria-pressed={isListening}
          title="Speak your question instead of typing (Alt+M)"
          style={{
            width: '40px', height: '40px', borderRadius: '10px', cursor: 'pointer',
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            background: isListening ? 'var(--danger)' : 'transparent',
            color: isListening ? 'var(--on-accent)' : 'var(--ink-2)',
            border: isListening ? '1px solid var(--danger)' : '1px solid var(--border-strong)',
          }}
        >
          {isTranscribing ? <span aria-hidden="true">…</span> : (
            <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <rect x="6.5" y="2" width="5" height="9" rx="2.5" /><path d="M3.5 8.5a5.5 5.5 0 0 0 11 0M9 14v2.5" />
            </svg>
          )}
        </button>

        <button
          id="chat-send-btn"
          onClick={handleSend}
          disabled={isSending || !input.trim()}
          style={{
            height: '40px', padding: '0 16px', borderRadius: '10px', border: 'none', fontSize: '14px', fontWeight: 600,
            background: isSending || !input.trim() ? 'var(--panel-2)' : 'var(--accent)',
            color: isSending || !input.trim() ? 'var(--ink-2)' : 'var(--on-accent)',
            cursor: isSending || !input.trim() ? 'default' : 'pointer', whiteSpace: 'nowrap',
          }}
        >
          {isSending ? '…' : 'Send'}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Markdown-lite text renderer (code blocks, inline code, bold, bullets)
// ---------------------------------------------------------------------------
function renderRichContent(content: string) {
  if (!content) return null;

  // Clean any lingering spoken markers as defense-in-depth
  const cleanText = content.replace(/\[{1,2}\s*mark\s*:[^[\]\n]*\]{1,2}\s*/gi, '');

  // Split by code blocks first
  const codeBlockRegex = /```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g;
  const segments: Array<{ type: 'text' | 'code'; lang?: string; code?: string }> = [];

  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = codeBlockRegex.exec(cleanText)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ type: 'text', code: cleanText.slice(lastIndex, match.index) });
    }
    segments.push({ type: 'code', lang: match[1] || 'code', code: match[2] });
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < cleanText.length) {
    segments.push({ type: 'text', code: cleanText.slice(lastIndex) });
  }

  return (
    <div>
      {segments.map((seg, idx) => {
        if (seg.type === 'code') {
          return (
            <CodeBlockView key={idx} lang={seg.lang || 'code'} code={seg.code || ''} />
          );
        }

        const lines = (seg.code || '').split('\n');
        return (
          <div key={idx}>
            {lines.map((line, lIdx) => {
              const isBullet = line.trim().startsWith('- ') || line.trim().startsWith('* ');
              const cleanLine = isBullet ? line.trim().slice(2) : line;

              // Format bold and inline code
              const parts = cleanLine.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);

              return (
                <div
                  key={lIdx}
                  style={{
                    minHeight: line.trim() ? 'auto' : '8px',
                    display: isBullet ? 'flex' : 'block',
                    alignItems: 'flex-start',
                    gap: isBullet ? '6px' : '0',
                    paddingLeft: isBullet ? '4px' : '0',
                  }}
                >
                  {isBullet && <span style={{ color: 'var(--accent)' }}>•</span>}
                  <div>
                    {parts.map((p, pIdx) => {
                      if (p.startsWith('`') && p.endsWith('`')) {
                        return (
                          <code
                            key={pIdx}
                            style={{
                              background: 'var(--panel-2)',
                              color: 'var(--ink)',
                              padding: '1px 5px',
                              borderRadius: '4px',
                              fontFamily: 'monospace',
                              fontSize: '12px',
                              border: '1px solid var(--border)',
                            }}
                          >
                            {p.slice(1, -1)}
                          </code>
                        );
                      }
                      if (p.startsWith('**') && p.endsWith('**')) {
                        return (
                          <strong key={pIdx} style={{ color: 'inherit', fontWeight: 600 }}>
                            {p.slice(2, -2)}
                          </strong>
                        );
                      }
                      return p;
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

function CodeBlockView({ lang, code }: { lang: string; code: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div style={{
      margin: '8px 0',
      background: 'var(--panel)',
      border: '1px solid var(--border)',
      borderRadius: '8px',
      overflow: 'hidden',
    }}>
      <div style={{
        padding: '4px 10px',
        background: 'var(--panel)',
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        fontSize: '12px',
        color: 'var(--ink-2)',
      }}>
        <span style={{ fontWeight: 600 }}>{lang}</span>
        <button
          onClick={handleCopy}
          style={{
            background: 'transparent',
            border: 'none',
            color: copied ? 'var(--ok)' : 'var(--ink-2)',
            fontSize: '12px',
            cursor: 'pointer',
            padding: '2px 4px',
          }}
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre style={{
        margin: 0,
        padding: '10px 12px',
        fontFamily: 'monospace',
        fontSize: '12px',
        color: 'var(--ink)',
        overflowX: 'auto',
        lineHeight: 1.5,
      }}>
        <code>{code}</code>
      </pre>
    </div>
  );
}
