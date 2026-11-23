// A clean recap of the current lesson page: path, board contents, the learner's answers, corrected beliefs.
// Refetches on open and whenever `refreshKey` changes (ChatPanel passes the tutor-reply count).
import { useEffect, useState } from 'react';
import type { CSSProperties } from 'react';
import type { LessonRecap } from '../types';
import * as api from '../services/api';

const KIND: Record<string, string> = {
  notes: 'Notes', recap: 'Recap card', code: 'Code', diagram: 'Diagram', graph: 'Graph', table: 'Table', chart: 'Chart', venn: 'Venn',
};
const RESULT: Record<string, string> = { right: 'Right ✓', partial: 'Partly ◐', wrong: 'Not yet ✗' };
const LEVEL: Record<string, string> = { understood: '✓ Understood', remembered: '✓ Remembered', taught: 'Taught' };

const h: CSSProperties = { margin: '18px 0 8px', fontSize: '13px', fontWeight: 600, color: 'var(--ink-2)', textTransform: 'uppercase', letterSpacing: '0.04em' };
const card: CSSProperties = { padding: '10px 12px', background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', marginBottom: '8px', fontSize: '14px', lineHeight: 1.5, color: 'var(--ink)' };
const list: CSSProperties = { margin: '4px 0 0', paddingLeft: '20px' };
const muted: CSSProperties = { color: 'var(--ink-2)', fontSize: '13px' };

export function RecapView({ notebookId, pageId, refreshKey }: Readonly<{ notebookId: string; pageId: string | null; refreshKey: number }>) {
  const [recap, setRecap] = useState<LessonRecap | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!pageId) return;
    let live = true;
    setLoading(true);
    api.getRecap(notebookId, pageId)
      .then(r => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then((d: LessonRecap) => { if (live) { setRecap(d); setError(false); } })
      .catch(() => { if (live) setError(true); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [notebookId, pageId, refreshKey]);

  const empty = recap && !recap.goal && !recap.steps.length && !recap.board.length && !recap.answers.length && !recap.corrected.length;

  return (
    <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '4px 16px 20px' }}>
      {!pageId && <p style={muted}>Open a lesson page to see its recap.</p>}
      {loading && !recap && <p role="status" style={muted}>Loading the recap…</p>}
      {error && <p role="alert" style={{ ...muted, color: 'var(--danger)' }}>The recap could not be loaded{recap ? ', so this may be out of date' : ''}.</p>}
      {recap && (empty ? (
        <p style={muted}>Nothing to recap yet: the recap fills in as the lesson goes.</p>
      ) : (
        <>
          <h3 style={{ margin: '16px 0 4px', fontSize: '17px', color: 'var(--ink)' }}>{recap.title}</h3>
          {recap.goal && <p style={{ margin: 0, fontSize: '14px', color: 'var(--ink-2)' }}>Goal: {recap.goal}</p>}

          {recap.steps.length > 0 && <>
            <h4 style={h}>Your path</h4>
            <ol style={{ ...list, paddingLeft: '22px', fontSize: '14px', color: 'var(--ink)' }}>
              {recap.steps.map((s, i) => (
                <li key={i} style={{ marginBottom: '4px' }}>{s.title} <span style={muted}>· {LEVEL[s.level] ?? 'Not started'}</span></li>
              ))}
            </ol>
          </>}

          {recap.board.length > 0 && <>
            <h4 style={h}>On the board</h4>
            {recap.board.map((b, i) => (
              <div key={i} style={b.kind === 'recap' ? { ...card, borderColor: 'var(--accent)', background: 'var(--accent-soft)', fontWeight: 500 } : card}>
                <div style={{ ...muted, fontWeight: 600 }}>{KIND[b.kind] ?? b.kind}{b.title ? ` · ${b.title}` : ''}</div>
                {b.lines.length > 0 && <ul style={list}>{b.lines.map((l, j) => <li key={j}>{l}</li>)}</ul>}
              </div>
            ))}
          </>}

          {recap.answers.length > 0 && <>
            <h4 style={h}>Your answers</h4>
            {recap.answers.map((a, i) => (
              <div key={i} style={card}>
                {a.question && <div style={muted}>{a.question}</div>}
                <blockquote style={{ margin: '4px 0', padding: '0 0 0 10px', borderLeft: '3px solid var(--border-strong)' }}>{a.answer}</blockquote>
                {a.result && <div style={{ fontWeight: 600, color: a.result === 'right' ? 'var(--ok)' : a.result === 'partial' ? 'var(--warn)' : 'var(--danger)' }}>{RESULT[a.result]}</div>}
                <div style={muted}>{a.source === 'grader' ? 'checked by the grader' : "the tutor's mark"}</div>
              </div>
            ))}
          </>}

          {recap.corrected.length > 0 && <>
            <h4 style={h}>Corrected</h4>
            {recap.corrected.map((c, i) => (
              <div key={i} style={card}>
                You believed: {c.belief}
                <div style={{ fontWeight: 600, color: c.cleared ? 'var(--ok)' : 'var(--warn)' }}>{c.cleared ? 'cleared ✓' : 'still to check'}</div>
              </div>
            ))}
          </>}
        </>
      ))}
    </div>
  );
}
