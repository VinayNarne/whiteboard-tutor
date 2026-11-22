// Narration playback for the whiteboard: one clip at a time, element reveal synced to the word alignment,
// and an instant stop when the learner interrupts the tutor (barge-in).
import { debug } from './debug';

let activeAudio: HTMLAudioElement | null = null;
let interruptActive: (() => void) | null = null;   // ends the clip that may be interrupted right now

/** Apply the learner's speed choice to the clip that is playing right now. */
export function setActiveAudioRate(rate: number): void {
  if (activeAudio) activeAudio.playbackRate = rate;
}

/** Pause the clip that is playing, or resume it. The drawing follows the audio clock, so it holds and continues with it. */
export function toggleNarrationPause(): void {
  if (!activeAudio) return;
  if (activeAudio.paused) void activeAudio.play().catch(() => { /* blocked: stay paused */ });
  else activeAudio.pause();
}

/** The pause button follows this: `narration_state` says whether a clip is loaded and whether it is paused. */
function announceState(active: boolean, paused: boolean): void {
  if (typeof globalThis.window !== 'undefined') globalThis.dispatchEvent(new CustomEvent('narration_state', { detail: { active, paused } }));
}

/** Mute or unmute the clip that is playing right now. */
export function setActiveAudioMuted(muted: boolean): void {
  if (activeAudio) {
    activeAudio.muted = muted;
    activeAudio.volume = muted ? 0 : 1;
  }
}

// The learner speaks over the tutor: stop talking at once. The clip is finished (its element still appears and
// the caller's `await` returns), so the drawing queue never gets stuck behind a silenced clip.
if (typeof globalThis.window !== 'undefined') {
  globalThis.addEventListener('tutor_barge_in', () => interruptActive?.());
}

export function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/** A clip's words and when each starts (seconds), from the ElevenLabs character alignment. */
export interface CaptionWord { text: string; start: number }

export function captionWords(alignment: { characters?: string[]; character_start_times_seconds?: number[] } | undefined): CaptionWord[] {
  const chars = alignment?.characters ?? [], times = alignment?.character_start_times_seconds ?? [];
  const words: CaptionWord[] = [];
  let cur: CaptionWord | null = null;
  chars.forEach((c, i) => {
    if (/\s/.test(c)) { cur = null; return; }
    if (!cur) { cur = { text: '', start: times[i] ?? 0 }; words.push(cur); }
    cur.text += c;
  });
  return words;
}

/** The caption (NarrationCaption) follows the clip that is playing: `narration_caption` with the words and the audio, then null when it ends. */
function announceCaption(detail: { words: CaptionWord[]; audio: HTMLAudioElement } | null): void {
  if (typeof globalThis.window !== 'undefined') globalThis.dispatchEvent(new CustomEvent('narration_caption', { detail }));
}

export async function playAudioWithTiming(
  audioUrl: string,
  alignmentUrl: string | null,
  elementId: string,
  onReveal: () => void,
  cancelledRef?: { current: boolean },
  playbackRate: number = 1,
  isMuted: boolean = false,
  interruptible: boolean = false   // live tutor narration yes, replay no
): Promise<void> {
  let revealTime = 0;
  let audioSeconds = 0;
  let words: CaptionWord[] = [];

  if (alignmentUrl) {
    try {
      const res = await fetch(alignmentUrl);
      if (res.ok) {
        const alignData = await res.json();
        audioSeconds = Number(alignData.audio_duration_seconds) || 0;
        words = captionWords(alignData.raw_alignment);
        const marker = (alignData.marker_timings ?? []).find(
          (m: { id?: string; time?: number }) => m.id === elementId
        );
        if (marker && typeof marker.time === 'number') {
          revealTime = marker.time;
        } else if (alignData.marker_timings && alignData.marker_timings.length > 0) {
          revealTime = alignData.marker_timings[0].time;
        } else if (alignData.raw_alignment?.character_start_times_seconds?.length) {
          revealTime = alignData.raw_alignment.character_start_times_seconds[0];
        }
      }
    } catch (e) {
      console.warn('[playAudioWithTiming] Failed to fetch alignment:', e);
    }
  }

  if (cancelledRef?.current) return;

  return new Promise<void>((resolve) => {
    let revealed = false;
    let animFrameId: number | null = null;
    const audio = new Audio(audioUrl);
    activeAudio = audio;
    audio.playbackRate = playbackRate;
    if (isMuted) {
      audio.muted = true;
      audio.volume = 0;
    }

    const triggerReveal = () => {
      if (revealed || cancelledRef?.current) return;
      revealed = true;
      if (typeof globalThis.window !== 'undefined') {
        const detail = {
          elementId,
          revealTime,
          audioCurrentTime: audio.currentTime,
          wallClock: performance.now(),
        };
        (globalThis as unknown as Record<string, unknown>).__LAST_REVEAL_TIMING = detail;
        globalThis.dispatchEvent(new CustomEvent('element_revealed', { detail }));
      }
      onReveal();
    };

    let watchdog: ReturnType<typeof setTimeout> | null = null;
    announceState(true, false);

    if (words.length) announceCaption({ words, audio });

    const cleanup = () => {
      if (words.length) announceCaption(null);
      if (watchdog) clearTimeout(watchdog);
      audio.onpause = null;
      if (activeAudio === audio) {
        activeAudio = null;
        announceState(false, false);
      }
      if (interruptActive === finish) interruptActive = null;
      audio.onplay = null;
      audio.ontimeupdate = null;
      audio.onended = null;
      audio.onerror = null;
      if (animFrameId !== null) {
        cancelAnimationFrame(animFrameId);
        animFrameId = null;
      }
      try {
        audio.pause();
      } catch {
        /* ignore */
      }
    };

    // End the clip now, whatever state it is in: show the element, free the player, let the caller continue.
    const finish = () => {
      triggerReveal();
      cleanup();
      resolve();
    };
    if (interruptible) interruptActive = finish;
    // A clip that never plays, ends or errors (stalled network, odd codec) must not freeze the board.
    const armWatchdog = () => {
      if (watchdog) clearTimeout(watchdog);
      watchdog = setTimeout(finish, ((audioSeconds || 60) + 15) * 1000);
    };
    armWatchdog();
    // While the learner has paused, the watchdog must not fire; it starts again on resume.
    audio.onpause = () => {
      if (audio.ended) return;
      if (watchdog) clearTimeout(watchdog);
      announceState(true, true);
    };

    const checkTiming = () => {
      if (cancelledRef?.current) {
        cleanup();
        resolve();
        return;
      }
      if (!revealed && audio.currentTime >= revealTime) {
        triggerReveal();
      }
      if (!audio.ended && !audio.paused) {
        animFrameId = requestAnimationFrame(checkTiming);
      }
    };

    if (revealTime <= 0.05) {
      triggerReveal();
    }

    audio.onplay = () => {
      armWatchdog();
      announceState(true, false);
      if (!revealed) {
        animFrameId = requestAnimationFrame(checkTiming);
      }
    };

    audio.ontimeupdate = () => {
      if (!revealed && audio.currentTime >= revealTime) {
        triggerReveal();
      }
    };

    audio.onended = () => {
      triggerReveal();
      cleanup();
      resolve();
    };

    audio.onerror = (e) => {
      console.warn('[playAudioWithTiming] Audio error:', e);
      cleanup();
      triggerReveal();
      resolve();
    };

    audio.play()
      .then(() => {
        debug('[audio] play() started OK for:', elementId);
      })
      .catch((err) => {
        console.warn('[audio] play() blocked/failed for', elementId, err.message);
        cleanup();
        triggerReveal();
        resolve();
      });
  });
}
