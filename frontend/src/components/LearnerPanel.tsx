// "What I know about you": everything the tutor remembers, each item removable.
import { useEffect, useRef, useState } from 'react';
import * as api from '../services/api';
import type { Learner } from '../hooks/useLearner';

const small: React.CSSProperties = {
  background: 'transparent', border: '1px solid var(--border-strong)', color: 'var(--ink)', borderRadius: '6px',
  fontSize: '12px', padding: '6px 10px', minHeight: '32px', cursor: 'pointer', whiteSpace: 'nowrap',   // 32px: a touch target
};
const row: React.CSSProperties = {
  display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '10px',
  padding: '8px 8px 8px 0', borderTop: '1px solid var(--border)', fontSize: '13px', color: 'var(--ink)',
};
const h4: React.CSSProperties = { fontSize: '13px', fontWeight: 600, color: 'var(--ink)', margin: '16px 0 4px' };
const empty: React.CSSProperties = { fontSize: '13px', color: 'var(--ink-2)' };

export function LearnerPanel({ learner, onClose }: Readonly<{ learner: Learner; onClose: () => void }>) {
  const { card, error, run } = learner;
  const [confirming, setConfirming] = useState(false);
  const [said, setSaid] = useState('');                       // announced politely to screen readers after each change
  const ref = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const forgetRef = useRef<HTMLButtonElement>(null);
  const returnToForget = useRef(false);
  const afterRemove = useRef<{ sec: string; index: number } | null>(null);

  // The native modal (showModal) makes the page behind inert, traps Tab and gives Escape (the "cancel" event, below); we move focus in
  // and return it to the opener.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const opener = document.activeElement as HTMLElement | null;
    if (!el.open) el.showModal();                            // already open under React StrictMode's second run
    el.querySelector<HTMLElement>('button')?.focus();
    return () => {
      if (el.open) { el.close(); }       // close first: an open modal keeps the page behind inert, so focus() there would fail
      opener?.focus?.();
    };
  }, []);

  // A removed row takes its button with it: focus goes to the next row's button, else to the section heading, never to <body>.
  useEffect(() => {
    const p = afterRemove.current;
    if (!p) return;
    afterRemove.current = null;
    const el = ref.current?.querySelector<HTMLElement>(`[data-sec="${p.sec}"]`);
    (el?.querySelectorAll<HTMLElement>('button')[p.index] ?? el?.querySelector<HTMLElement>('h4'))?.focus();
  }, [card]);

  // "Forget everything" -> confirm: Cancel gets focus; when the confirm goes away focus returns to "Forget everything".
  useEffect(() => {
    if (confirming) cancelRef.current?.focus();
    else if (returnToForget.current) { returnToForget.current = false; forgetRef.current?.focus(); }
  }, [confirming]);

  const act = async (call: () => Promise<Response>, message: string, sec?: string, index = 0) => {
    if (sec) afterRemove.current = { sec, index };           // set before the card changes, so the effect above sees it
    const ok = await run(call);
    if (!ok) { afterRemove.current = null; return; }
    setSaid(message);
  };

  return (
    <dialog ref={ref} className="learner-dialog" tabIndex={-1} aria-labelledby="learner-title" onCancel={e => { e.preventDefault(); onClose(); }} style={{
        color: 'inherit', background: 'var(--panel)', border: '1px solid var(--border)',
        borderRadius: '16px', padding: '20px', width: '460px', maxWidth: 'calc(100% - 24px)', maxHeight: '90vh', overflowY: 'auto',
        scrollbarGutter: 'stable', boxShadow: 'var(--shadow)',
      }}>
        <p className="sr-only" role="status" aria-live="polite">{said}</p>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3 id="learner-title" style={{ margin: 0, fontSize: '16px', fontWeight: 700 }}>What I know about you</h3>
          <button type="button" onClick={onClose} aria-label="Close" style={{ ...small, border: 'none', fontSize: '16px' }}>✕</button>
        </div>

        {error && <p role="alert" style={{ fontSize: '12px', color: 'var(--danger)', marginTop: '8px' }}>{error}</p>}
        {card ? (
          <>
            <div data-sec="known">
            <h4 style={h4} tabIndex={-1}>Understood</h4>
            {card.known.length === 0 ? <p style={empty}>Nothing yet. As you learn, what you understand shows up here.</p> :
              card.known.map((k, i) => (
                <div key={k.id} style={row}>
                  <span><strong style={{ fontWeight: 600 }}>{k.name}</strong>{k.level && <span style={{ color: 'var(--ink-2)' }}> ({k.level})</span>}</span>
                  <button type="button" style={small} onClick={() => act(() => api.forgetKnown(k.id), 'Removed.', 'known', i)}
                    aria-label={`I don't know ${k.name} yet`}>I don't know this yet</button>
                </div>
              ))}
            </div>

            <div data-sec="misc">
            <h4 style={h4} tabIndex={-1}>Things to revisit</h4>
            {card.misconceptions.length === 0 ? <p style={empty}>Nothing to revisit right now.</p> :
              card.misconceptions.map((m, i) => (
                <div key={m.id} style={row}>
                  <span>{m.belief}{m.corrected && <em style={{ color: 'var(--ink-2)' }}> (corrected, checking)</em>}</span>
                  <button type="button" style={small} onClick={() => act(() => api.forgetMisconception(m.id), 'Removed.', 'misc', i)}
                    aria-label={`Remove: ${m.belief}`}>Remove</button>
                </div>
              ))}
            </div>

            <h4 style={h4}>How you like to learn</h4>
            <p style={empty}>The tutor uses these in every lesson until you turn them off.</p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '8px' }}>
              {card.available_preferences.map(p => {
                const on = card.preferences.some(x => x.kind === p.kind);
                return (
                  <button key={p.kind} type="button" aria-pressed={on}
                    onClick={() => act(() => (on ? api.removePreference(p.kind) : api.addPreference(p.kind)), `Preference ${on ? 'off' : 'on'}: ${p.label}`)}
                    style={{
                      ...small, padding: '6px 12px', borderRadius: '14px', fontWeight: on ? 600 : 500,
                      background: on ? 'var(--accent-soft)' : 'transparent',
                      color: on ? 'var(--accent-hover)' : 'var(--ink-2)',
                      border: `1px solid ${on ? 'var(--accent)' : 'var(--border-strong)'}`,
                    }}>{on ? '✓ ' : ''}{p.label}</button>
                );
              })}
            </div>

            <div style={{ marginTop: '20px', borderTop: '1px solid var(--border)', paddingTop: '12px' }}>
              {confirming ? (
                <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '8px', fontSize: '13px' }}>
                  <span>Forget everything about you? This cannot be undone.</span>
                  <button type="button" style={{ ...small, background: 'var(--danger)', color: 'var(--on-accent)', border: '1px solid var(--danger)' }}
                    onClick={async () => { await act(api.forgetLearner, 'Everything forgotten.'); returnToForget.current = true; setConfirming(false); }}>Yes, forget</button>
                  <button type="button" ref={cancelRef} style={small} onClick={() => { returnToForget.current = true; setConfirming(false); }}>Cancel</button>
                </div>
              ) : (
                <button type="button" ref={forgetRef} style={{ ...small, color: 'var(--danger)', border: '1px solid var(--danger)' }}
                  onClick={() => setConfirming(true)}>Forget everything</button>
              )}
            </div>
          </>
        ) : <p style={{ ...empty, marginTop: '12px' }}>Loading…</p>}
      </dialog>
  );
}
