// Dictation: microphone -> backend relay (/api/ws/voice) -> Deepgram, with a REST fallback.
//  - live words appear as you speak; "hands-free" sends them after you pause
//  - speaking over the tutor interrupts it (a `tutor_barge_in` window event that the board and chat listen to)
//  - every failure is reported through `error`, never silently ignored
import { useState, useRef, useCallback, useEffect } from 'react';

import { BACKEND_WS_PORT } from '../utils/backend';
const SEND_DELAY_MS = 700;      // hands-free: quiet time after the last words before the message is sent
const UTTERANCE_END_DELAY_MS = 300;
const FLUSH_WAIT_MS = 1500;     // after Done, how long we wait for Deepgram's last words
const LOUD_LEVEL = 0.18;
const LOUD_FRAMES = 15;         // ~250 ms of sustained sound counts as the learner speaking (not a cough or a click)
const MIN_FALLBACK_BYTES = 1500; // a recording shorter than this is not worth transcribing

export interface UseVoiceInputOptions {
  notebookId: string | null;
  autoSend?: boolean;
  onTranscriptChange?: (fullText: string, isFinal: boolean) => void;
  onAutoSend?: (finalText: string) => void;
  onError?: (errorMsg: string) => void;
}

export function micErrorMessage(err: unknown): string {
  const name = err instanceof DOMException ? err.name : '';
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return "Microphone access is blocked. Allow it from the address bar's site settings, then try again.";
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'No microphone was found.';
  if (name === 'NotReadableError') return 'The microphone is being used by another app.';
  return 'Could not start the microphone.';
}

export function useVoiceInput(options: UseVoiceInputOptions) {
  // Always call the latest callbacks/flags (e.g. hands-free switched on while already listening).
  const opts = useRef(options);
  opts.current = options;

  const [isListening, setIsListening] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [interimText, setInterimText] = useState('');
  const [audioLevel, setAudioLevel] = useState(0); // 0.0 to 1.0
  const [error, setError] = useState<string | null>(null);

  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const frameRef = useRef<number | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const finalRef = useRef('');         // words Deepgram has confirmed
  const interimRef = useRef('');       // words it is still working on
  const sendTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startingRef = useRef(false);   // microphone permission prompt is open
  const cancelStartRef = useRef(false);
  const stoppingRef = useRef(false);   // we closed the socket ourselves
  const discardRef = useRef(false);    // ignore anything still arriving (message sent, or cancelled)
  const liveOkRef = useRef(false);     // the live socket is connected and healthy
  const lastBargeRef = useRef(0);

  const fail = useCallback((msg: string) => {
    setError(msg);
    opts.current.onError?.(msg);
  }, []);

  const clearSendTimer = () => {
    if (sendTimerRef.current) clearTimeout(sendTimerRef.current);
    sendTimerRef.current = null;
  };

  const triggerBargeIn = useCallback(() => {
    const now = Date.now();
    if (now - lastBargeRef.current > 1000) {
      lastBargeRef.current = now;
      globalThis.dispatchEvent(new CustomEvent('tutor_barge_in', { detail: { timestamp: now } }));
    }
  }, []);

  /** Keep words Deepgram has heard but not finalised yet, so pressing Done never drops the last phrase. */
  const commitInterim = () => {
    if (!interimRef.current || discardRef.current) return;
    finalRef.current = finalRef.current ? `${finalRef.current} ${interimRef.current}` : interimRef.current;
    interimRef.current = '';
    setInterimText('');
    setTranscript(finalRef.current);
    opts.current.onTranscriptChange?.(finalRef.current, true);
  };

  const stopListening = useCallback((o?: { discard?: boolean }) => {
    if (o?.discard) discardRef.current = true;
    if (startingRef.current) cancelStartRef.current = true;
    clearSendTimer();
    commitInterim();
    stoppingRef.current = true;
    setIsListening(false);

    streamRef.current?.getTracks().forEach(t => t.stop());
    streamRef.current = null;

    if (recorderRef.current && recorderRef.current.state !== 'inactive') {
      try { recorderRef.current.stop(); } catch { /* already stopped */ }
    }
    if (frameRef.current) cancelAnimationFrame(frameRef.current);
    frameRef.current = null;
    if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
      audioCtxRef.current.close().catch(() => {});
    }
    audioCtxRef.current = null;
    setAudioLevel(0);

    // Tell Deepgram we are done, then keep the socket open briefly so its final words still arrive.
    const ws = wsRef.current;
    if (ws) {
      if (ws.readyState === WebSocket.OPEN) {
        try { ws.send(JSON.stringify({ type: 'CloseStream' })); } catch { /* closing anyway */ }
      }
      const timer = setTimeout(() => { try { ws.close(); } catch { /* closed */ } }, FLUSH_WAIT_MS);
      ws.onclose = () => {
        clearTimeout(timer);
        if (wsRef.current === ws) wsRef.current = null;
      };
    }
  }, []);

  useEffect(() => () => stopListening({ discard: true }), [stopListening]);

  const sendNow = useCallback(() => {
    sendTimerRef.current = null;
    const msg = finalRef.current.trim();
    if (!opts.current.autoSend || msg.length <= 2) return;
    discardRef.current = true;                 // anything Deepgram says from here on belongs to the next question
    opts.current.onAutoSend?.(msg);
    stopListening({ discard: true });
  }, [stopListening]);

  const armSend = (delay: number) => {
    clearSendTimer();
    if (opts.current.autoSend) sendTimerRef.current = setTimeout(sendNow, delay);
  };

  const transcribeRecording = useCallback(async (blob: Blob) => {
    setIsTranscribing(true);
    try {
      const res = await fetch('/api/transcribe-voice', { method: 'POST', headers: { 'Content-Type': blob.type || 'audio/webm' }, body: blob });
      if (!res.ok) {
        fail(res.status === 429
          ? "You're using voice very quickly. Please wait a few seconds and try again."
          : "Couldn't transcribe that. Please try again, or type your question.");
        return;
      }
      const text = ((await res.json()).transcript || '').trim();
      if (!text) { fail("I didn't catch anything. Check your microphone and try again."); return; }
      finalRef.current = text;
      setTranscript(text);
      opts.current.onTranscriptChange?.(text, true);
      if (opts.current.autoSend && text.length > 2) opts.current.onAutoSend?.(text);
    } catch {
      fail("Couldn't reach the server to transcribe that. Please try again, or type your question.");
    } finally {
      setIsTranscribing(false);
    }
  }, [fail]);

  const startListening = useCallback(async () => {
    if (startingRef.current || streamRef.current) return;     // already starting or listening
    startingRef.current = true;
    cancelStartRef.current = false;
    stoppingRef.current = false;
    discardRef.current = false;
    liveOkRef.current = false;
    setError(null);
    setInterimText('');
    chunksRef.current = [];
    finalRef.current = '';
    interimRef.current = '';
    clearSendTimer();

    try {
      if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
        throw new Error('Voice input needs a secure page (https or localhost) in a browser that supports recording.');
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      if (cancelStartRef.current) { stream.getTracks().forEach(t => t.stop()); return; }   // Done was pressed during the prompt
      streamRef.current = stream;

      // Level meter for the waveform, and sustained loud sound = the learner is speaking over the tutor.
      try {
        const AudioCtx = globalThis.AudioContext || (globalThis as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
        const ctx = new AudioCtx();
        audioCtxRef.current = ctx;
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 128;
        analyser.smoothingTimeConstant = 0.4;
        ctx.createMediaStreamSource(stream).connect(analyser);
        const bins = new Uint8Array(analyser.frequencyBinCount);
        let lastPaint = 0, loud = 0;
        const tick = (now: number) => {
          if (!streamRef.current) return;
          analyser.getByteFrequencyData(bins);
          const level = Math.min(1, bins.reduce((a, b) => a + b, 0) / bins.length / 128);
          if (now - lastPaint > 90) { lastPaint = now; setAudioLevel(level); }   // ~11 repaints/s, not 60
          loud = level > LOUD_LEVEL ? loud + 1 : 0;
          if (loud === LOUD_FRAMES) triggerBargeIn();
          frameRef.current = requestAnimationFrame(tick);
        };
        frameRef.current = requestAnimationFrame(tick);
      } catch (meterErr) {
        console.warn('Audio level meter unavailable:', meterErr);
      }

      // Live transcription through the backend relay (keeps the Deepgram key on the server).
      try {
        const proto = globalThis.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const ws = new WebSocket(`${proto}//${globalThis.location.hostname}:${BACKEND_WS_PORT}/api/ws/voice/${opts.current.notebookId || 'global'}`);
        wsRef.current = ws;
        ws.onopen = () => { liveOkRef.current = true; };
        ws.onerror = () => { liveOkRef.current = false; };
        ws.onclose = () => {
          liveOkRef.current = false;
          if (wsRef.current === ws) wsRef.current = null;
          if (!stoppingRef.current) {
            fail('Live transcription stopped. Keep talking, then press Done and I will transcribe the recording.');
          }
        };
        ws.onmessage = (event) => {
          if (discardRef.current) return;
          let data: any;
          try { data = JSON.parse(event.data); } catch { return; }

          if (data.type === 'SpeechStarted') { clearSendTimer(); triggerBargeIn(); return; }
          if (data.type === 'UtteranceEnd') { if (finalRef.current) armSend(UTTERANCE_END_DELAY_MS); return; }
          if (data.type !== 'Results') return;

          const text = (data.channel?.alternatives?.[0]?.transcript || '').trim();
          if (!text) return;
          clearSendTimer();                      // still talking: do not send yet
          triggerBargeIn();
          if (data.is_final) {
            finalRef.current = finalRef.current ? `${finalRef.current} ${text}` : text;
            interimRef.current = '';
            setTranscript(finalRef.current);
            setInterimText('');
            opts.current.onTranscriptChange?.(finalRef.current, true);
            if (data.speech_final) armSend(SEND_DELAY_MS);
          } else {
            interimRef.current = text;
            setInterimText(text);
            opts.current.onTranscriptChange?.(finalRef.current ? `${finalRef.current} ${text}` : text, false);
          }
        };
      } catch (wsErr) {
        console.warn('Live transcription unavailable, will transcribe the recording instead:', wsErr);
      }

      const mime = ['audio/webm;codecs=opus', 'audio/webm'].find(t => MediaRecorder.isTypeSupported(t)) || '';
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      recorderRef.current = recorder;
      recorder.ondataavailable = (e) => {
        if (!e.data || e.data.size === 0) return;
        chunksRef.current.push(e.data);
        const ws = wsRef.current;
        if (ws?.readyState === WebSocket.OPEN) ws.send(e.data);
      };
      recorder.onstop = () => {
        // The live socket was down: transcribe the whole recording instead. Not after a send or cancel.
        const size = chunksRef.current.reduce((n, b) => n + b.size, 0);
        if (!liveOkRef.current && !discardRef.current && size >= MIN_FALLBACK_BYTES) {
          transcribeRecording(new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' }));
        }
      };
      recorder.start(200);
      setIsListening(true);
    } catch (err) {
      const msg = err instanceof Error && !(err instanceof DOMException) ? err.message : micErrorMessage(err);
      console.warn('Failed to start voice input:', err);
      stopListening({ discard: true });
      fail(msg);
    } finally {
      startingRef.current = false;
    }
  }, [fail, stopListening, transcribeRecording, triggerBargeIn]);

  const resetTranscript = useCallback(() => {
    setTranscript('');
    setInterimText('');
    finalRef.current = '';
    interimRef.current = '';
    clearSendTimer();
  }, []);

  return { isListening, isTranscribing, transcript, interimText, audioLevel, error, startListening, stopListening, resetTranscript };
}
