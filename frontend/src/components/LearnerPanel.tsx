// "What I know about you": everything the tutor remembers, each item removable.
import { useEffect, useRef, useState } from 'react';
import * as api from '../services/api';
import type { Learner } from '../hooks/useLearner';

const small: React.CSSProperties = {
  background: 'transparent', border: '1px solid var(--border-strong)', color: 'var(--ink)', borderRadius: '6px',
  fontSize: '12px', padding: '2px 8px', cursor: 'pointer', whiteSpace: 'nowrap',
};
const row: React.CSSProperties = {
  display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '10px',
  padding: '8px 0', borderTop: '1px solid var(--border)', fontSize: '13px', color: 'var(--ink)',
};
const h4: React.CSSProperties = { fontSize: '13px', fontWeight: 600, color: 'var(--ink)', margin: '16px 0 4px' };
const empty: React.CSSProperties = { fontSize: '13px', color: 'var(--ink-2)' };

export function LearnerPanel({ learner, onClose }: Readonly<{ learner: Learner; onClose: () => void }>) {
  const { card, error, run } = learner;
  const [confirming, setConfirming] = useState(false);
  const ref = useRef<HTMLDialogElement>(null);

  // focus in, Escape closes, Tab stays inside, focus returns to the opener
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const opener = document.activeElement as HTMLElement | null;
    el.querySelector<HTMLElement>('button')?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.stopPropagation(); onClose(); return; }
      if (e.key !== 'Tab') return;
      const items = [...el.querySelectorAll<HTMLElement>('button')];
      if (!items.length) return;
      const first = items[0], last = items.at(-1)!;
      if (!el.contains(document.activeElement) || (e.shiftKey && document.activeElement === first)) {
        e.preventDefault(); (e.shiftKey ? last : first).focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault(); first.focus();
      }
    };
    document.addEventListener('keydown', onKey, true);
    return () => { document.removeEventListener('keydown', onKey, true); opener?.focus?.(); };
  }, [onClose]);

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(31, 42, 55, 0.45)', zIndex: 100,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '12px',
    }}>
      <dialog open ref={ref} tabIndex={-1} aria-modal="true" aria-labelledby="learner-title" style={{
        position: 'static', margin: 0, color: 'inherit', background: 'var(--panel)', border: '1px solid var(--border)',
        borderRadius: '16px', padding: '20px', width: '460px', maxWidth: '100%', maxHeight: '90vh', overflowY: 'auto',
        boxShadow: 'var(--shadow)',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3 id="learner-title" style={{ margin: 0, fontSize: '16px', fontWeight: 700 }}>What I know about you</h3>
          <button type="button" onClick={onClose} aria-label="Close" style={{ ...small, border: 'none', fontSize: '16px' }}>✕</button>
        </div>

        {error && <p role="alert" style={{ fontSize: '12px', color: 'var(--danger)', marginTop: '8px' }}>{error}</p>}
        {!card ? <p style={{ ...empty, marginTop: '12px' }}>Loading…</p> : (
          <>
            <h4 style={h4}>Understood</h4>
            {card.known.length === 0 ? <p style={empty}>Nothing yet. As you learn, what you understand shows up here.</p> :
              card.known.map(k => (
                <div key={k.id} style={row}>
                  <span><strong style={{ fontWeight: 600 }}>{k.name}</strong>{k.level && <span style={{ color: 'var(--ink-2)' }}> ({k.level})</span>}</span>
                  <button type="button" style={small} onClick={() => run(() => api.forgetKnown(k.id))}
                    aria-label={`I don't know ${k.name} yet`}>I don't know this yet</button>
                </div>
              ))}

            <h4 style={h4}>Things to revisit</h4>
            {card.misconceptions.length === 0 ? <p style={empty}>Nothing to revisit right now.</p> :
              card.misconceptions.map(m => (
                <div key={m.id} style={row}>
                  <span>{m.belief}{m.corrected && <em style={{ color: 'var(--ink-2)' }}> (corrected, checking)</em>}</span>
                  <button type="button" style={small} onClick={() => run(() => api.forgetMisconception(m.id))}
                    aria-label={`Remove: ${m.belief}`}>Remove</button>
                </div>
              ))}

            <h4 style={h4}>How you like to learn</h4>
            <p style={empty}>The tutor uses these in every lesson until you turn them off.</p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '8px' }}>
              {card.available_preferences.map(p => {
                const on = card.preferences.some(x => x.kind === p.kind);
                return (
                  <button key={p.kind} type="button" aria-pressed={on}
                    onClick={() => run(() => (on ? api.removePreference(p.kind) : api.addPreference(p.kind)))}
                    style={{
                      ...small, padding: '4px 12px', borderRadius: '14px', fontWeight: on ? 600 : 500,
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
                    onClick={async () => { await run(api.forgetLearner); setConfirming(false); }}>Yes, forget</button>
                  <button type="button" style={small} onClick={() => setConfirming(false)}>Cancel</button>
                </div>
              ) : (
                <button type="button" style={{ ...small, color: 'var(--danger)', border: '1px solid var(--danger)' }}
                  onClick={() => setConfirming(true)}>Forget everything</button>
              )}
            </div>
          </>
        )}
      </dialog>
    </div>
  );
}
