// "Your map": every notebook > lesson > step the learner has met, with the level reached for each concept.
import { useEffect, useRef, useState } from 'react';
import * as api from '../services/api';
import type { LearnerMap, MapLevel } from '../types';

const LABEL: Record<MapLevel, string> = { new: 'New', taught: 'Taught', understood: 'Understood', remembered: 'Remembered' };

export function LearnerMapDialog({ currentNotebookId, onClose }: Readonly<{ currentNotebookId: string; onClose: () => void }>) {
  const [map, setMap] = useState<LearnerMap | null>(null);
  const [error, setError] = useState('');
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const opener = document.activeElement as HTMLElement | null;
    if (!el.open) el.showModal();                            // already open under React StrictMode's second run
    el.querySelector<HTMLElement>('button')?.focus();
    return () => { if (el.open) el.close(); opener?.focus?.(); };
  }, []);

  useEffect(() => {
    let live = true;
    api.getLearnerMap()
      .then(r => (r.ok ? r.json() : Promise.reject(new Error('bad status'))))
      .then((d: LearnerMap) => { if (live) setMap(d); })
      .catch(() => { if (live) setError('Could not load your map. Close this and try again.'); });
    return () => { live = false; };
  }, []);

  const notebooks = map?.notebooks ?? [];
  return (
    <dialog ref={ref} className="learner-dialog map-dialog" tabIndex={-1} aria-labelledby="map-title" onCancel={e => { e.preventDefault(); onClose(); }}>
      <div className="map-head">
        <h3 id="map-title">Your map</h3>
        <button type="button" className="map-close" onClick={onClose} aria-label="Close">✕</button>
      </div>
      <p className="map-legend">Levels: New (met, not taught yet), Taught (explained), Understood (you showed it), Remembered (still there after a later check).</p>
      {error && <p role="alert" className="map-error">{error}</p>}
      {!map && !error && <p className="map-note" role="status">Loading…</p>}
      {map && notebooks.length === 0 && <p className="map-note">Your map grows as you learn: each lesson adds its steps here.</p>}
      {notebooks.map(nb => (
        <details key={nb.id} className="map-notebook" open={nb.id === currentNotebookId}>
          <summary>{nb.topic || 'Untitled notebook'}{nb.id === currentNotebookId && <span className="map-here"> (this notebook)</span>}</summary>
          {nb.goal && <p className="map-goal">Goal: {nb.goal}</p>}
          {nb.lessons.length === 0 && <p className="map-note">No lessons yet.</p>}
          {nb.lessons.map(l => (
            <section key={l.page_id} className="map-lesson" aria-label={`Lesson: ${l.title}`}>
              <h4>{l.title}</h4>
              <ul>
                {l.steps.map((s, i) => (
                  <li key={i}>
                    <span className="map-step">{s.title}</span>
                    {s.concept && s.level && <span className={`map-level lvl-${s.level}`}>{LABEL[s.level]}</span>}
                    {s.shared > 0 && <span className="map-shared">also in {s.shared} other lesson{s.shared === 1 ? '' : 's'}</span>}
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </details>
      ))}
    </dialog>
  );
}
