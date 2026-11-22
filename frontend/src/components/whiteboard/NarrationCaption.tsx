// What the tutor is saying, under the board, with the words already spoken in full ink and the rest dimmed.
// Follows the clip that is playing (narrationPlayback announces it). Hidden from screen readers: the chat panel carries the same text.
import { useEffect, useState } from 'react';
import type { CaptionWord } from '../../utils/narrationPlayback';

export function NarrationCaption() {
  const [clip, setClip] = useState<{ words: CaptionWord[]; audio: HTMLAudioElement } | null>(null);
  const [spoken, setSpoken] = useState(0);

  useEffect(() => {
    const onCaption = (e: Event) => { setClip((e as CustomEvent).detail); setSpoken(0); };
    globalThis.addEventListener('narration_caption', onCaption);
    return () => globalThis.removeEventListener('narration_caption', onCaption);
  }, []);

  useEffect(() => {
    if (!clip) return;
    let frame = 0;
    const tick = () => {
      const t = clip.audio.currentTime;
      let n = 0;
      while (n < clip.words.length && clip.words[n].start <= t) n++;
      setSpoken(n);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [clip]);

  if (!clip) return null;
  return (
    <div aria-hidden="true" className="narration-caption">
      {clip.words.map((w, i) => (
        <span key={i} style={{ color: i < spoken ? 'var(--ink)' : 'var(--ink-2)' }}>{w.text} </span>
      ))}
    </div>
  );
}
