// frontend/src/components/WhiteboardCanvas.tsx
// Center-screen whiteboard. Renders the composite SVG for the active page.
// Receives draw events over WS and appends new SVG elements with an
// "appear" animation timed to the audio word-by-word playback.
// Features: Canvas Themes (Paper, White, Blackboard), Dot Grid, Zoom & Pan,
// Export (SVG, PNG, Copy), Replay timeline scrubber & speed multiplier.

import { useEffect, useRef, useState, useMemo, useCallback } from 'react';
import { WhiteboardToolbar } from './whiteboard/WhiteboardToolbar';
import { ZoomControls } from './whiteboard/ZoomControls';
import { ReplayBar } from './whiteboard/ReplayBar';
import { NarrationCaption } from './whiteboard/NarrationCaption';
import { PaintLayer } from './whiteboard/PaintLayer';
import { CANVAS_WIDTH, CANVAS_HEIGHT, THEME_STYLES, type CanvasTheme } from './whiteboard/themes';
import type {
  WsElementDrawn,
  WsElementModified,
  AnnotationPayload,
  LearnerTool,
  LearnerStroke,
  LearnerIntent,
} from '../types';
import { roughifySvgFragment } from '../services/roughRenderer';
import { fitTextInFragments } from '../services/textFit';
import { getElementBounds, type ElementBounds } from '../utils/svgBounds';
import { renderRoughAnnotation, type RenderedAnnotationNodes } from '../utils/roughAnnotations';
import {
  screenToSvgCoordinates,
  pointsToSvgPath,
  resolveLearnerIntent,
  computeStrokeBBox,
} from '../utils/learnerGrounding';
import { debug } from '../utils/debug';
import { sleep, playAudioWithTiming, setActiveAudioRate, setActiveAudioMuted, toggleNarrationPause } from '../utils/narrationPlayback';
import { serializeSvg, downloadSvg, downloadPng, copyText } from '../utils/whiteboardExport';
import { CLOSE_ENOUGH, DEFAULT_VIEW, between, blockFrame, camBox, frame, openingView, overview, panBy, pointableParts, stepView, zoomAt, zoomOf, type Box } from '../utils/boardCamera';

export type { CanvasTheme } from './whiteboard/themes';

interface DrawItem {
  element_id: string;
  kind?: string;
  svg_fragment: string;
  narration: string | null;
  audio_url: string | null;
  alignment_url: string | null;
}

interface Props {
  notebookId: string;
  pageId: string | null;
  pendingDrawEvent: WsElementDrawn['payload'] | null;
  pendingModifyEvent: WsElementModified['payload'] | null;
  pendingAnnotateEvent?: AnnotationPayload | null;
  pendingRemoveAnnotationEvent?: { page_id: string; annotation_id: string } | null;
  pendingRemoveElementEvent?: { page_id: string; element_id: string; annotation_ids: string[] } | null;
  pageStatus?: string;
  replayEvents?: DrawItem[];
  isReplaying?: boolean;
  onReplayDone?: () => void;
  isMuted?: boolean;
  playbackSpeed?: number;
  onPlaybackSpeedChange?: (speed: number) => void;
  activeLearnerIntent?: LearnerIntent | null;
  onLearnerIntentChange?: (intent: LearnerIntent | null) => void;
  onAskAboutSelection?: (intent: LearnerIntent) => void;
}

export function WhiteboardCanvas({
  notebookId,
  pageId,
  pendingDrawEvent,
  pendingModifyEvent,
  pendingAnnotateEvent,
  pendingRemoveAnnotationEvent,
  pendingRemoveElementEvent,
  pageStatus,
  replayEvents,
  isReplaying = false,
  onReplayDone,
  isMuted = false,
  playbackSpeed: propSpeed = 1.0,
  onPlaybackSpeedChange,
  activeLearnerIntent,
  onLearnerIntentChange,
  onAskAboutSelection,
}: Props) {
  const [playbackSpeed, setPlaybackSpeedState] = useState<number>(propSpeed);
  const playbackSpeedRef = useRef(playbackSpeed);
  playbackSpeedRef.current = playbackSpeed;

  const isMutedRef = useRef(isMuted);
  isMutedRef.current = isMuted;

  const onReplayDoneRef = useRef(onReplayDone);
  onReplayDoneRef.current = onReplayDone;

  useEffect(() => {
    setPlaybackSpeedState(propSpeed);
  }, [propSpeed]);

  useEffect(() => {
    setActiveAudioRate(playbackSpeed);
  }, [playbackSpeed]);

  useEffect(() => {
    setActiveAudioMuted(isMuted);
  }, [isMuted]);

  const setPlaybackSpeed = (spd: number) => {
    setPlaybackSpeedState(spd);
    onPlaybackSpeedChange?.(spd);
  };
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // 5-Layer SVG Refs
  const highlightsGRef = useRef<SVGGElement>(null);
  const annotationsGRef = useRef<SVGGElement>(null);
  const labelsGRef = useRef<SVGGElement>(null);
  const activeAnnotationsRef = useRef<Map<string, { payload: AnnotationPayload; nodes: RenderedAnnotationNodes; timerId?: any }>>(new Map());

  const [elements, setElements] = useState<Map<string, string>>(new Map());
  const [isPlaying, setIsPlaying] = useState(false);
  const [activeElementId, setActiveElementId] = useState<string | null>(null);
  const [hoveredElementId, setHoveredElementId] = useState<string | null>(null);
  const [isHandDrawn, setIsHandDrawn] = useState(true);

  // Canvas visual controls
  const [theme, setTheme] = useState<CanvasTheme>('paper');
  const [showGrid, setShowGrid] = useState(true);
  const [isPanning, setIsPanning] = useState(false);
  const dragRef = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  // The camera follows the tutor until the learner moves the board themselves (drag, wheel, keys, zoom buttons); "Follow tutor" hands it back
  const [following, setFollowing] = useState(true);
  const followingRef = useRef(true);
  followingRef.current = following;

  // Lesson-board camera (scene mode): the viewBox glides to the block being explained. Instant when the learner prefers reduced motion.
  const [view, setView] = useState<Box>(DEFAULT_VIEW);
  const viewRef = useRef(view);
  viewRef.current = view;
  const camAnimRef = useRef(0);
  const moveCamera = useCallback((to: Box, ms = 650) => {
    cancelAnimationFrame(camAnimRef.current);
    if (ms === 0 || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) { setView(to); return; }
    const from = viewRef.current, t0 = performance.now();
    const step = (t: number) => {
      const k = Math.min(1, (t - t0) / ms);
      setView(between(from, to, k));
      if (k < 1) camAnimRef.current = requestAnimationFrame(step);
    };
    camAnimRef.current = requestAnimationFrame(step);
  }, []);
  useEffect(() => () => cancelAnimationFrame(camAnimRef.current), []);
  /** The learner moves the board: their view, at once, and the tutor's camera stops following until they ask for it again. */
  const takeCamera = useCallback((to: Box) => {
    cancelAnimationFrame(camAnimRef.current);
    setFollowing(false);
    setView(to);
  }, []);
  const zoom = zoomOf(view);
  /** Follow a block that is about to be explained (a fragment without a block box leaves the view alone). Inside a big block
   *  that is already being followed step by step, focusStep moves the camera: going back out to the block first made it bounce. */
  const followedBlockRef = useRef('');
  const followFragment = useCallback((fragment: string) => {
    const b = camBox(fragment), f = blockFrame(fragment);
    if (!b || !f || !followingRef.current) return;
    const key = `${b.x},${b.y}`;
    if (f.w > CLOSE_ENOUGH && followedBlockRef.current === key) return;
    followedBlockRef.current = key;
    moveCamera(f);
  }, [moveCamera]);
  /** A block too big to read whole (a tall flowchart): once a step is on the board, frame that step and the one before it. */
  const focusStep = useCallback((elementId: string, fragment: string) => {
    const f = blockFrame(fragment), m = /^(b\d+_s)(\d+)$/.exec(elementId);
    if (!f || f.w <= CLOSE_ENOUGH || !m || !followingRef.current) return;
    requestAnimationFrame(() => requestAnimationFrame(() => {   // after React has put the step on the board
      const svg = svgRef.current;
      const ids = [elementId, +m[2] > 1 ? `${m[1]}${+m[2] - 1}` : ''].filter(Boolean);
      const bs = svg ? ids.map(id => getElementBounds(svg, id, 0, 0)).filter((b): b is ElementBounds => !!b) : [];
      const block = camBox(fragment);
      if (!bs.length || !block) return;
      moveCamera(stepView(block, bs.map(b => ({ x: b.left, y: b.top, w: b.right - b.left, h: b.bottom - b.top }))));
    }));
  }, [moveCamera]);

  // Replay timeline & copy toast
  const [replayStep, setReplayStep] = useState(0);
  const [toast, setToast] = useState<string | null>(null);

  // Learner drawing & spatial grounding state (local to active page)
  const [learnerTool, setLearnerTool] = useState<LearnerTool>('select');
  const [learnerColor, setLearnerColor] = useState<string>('#facc15');
  const [learnerStrokes, setLearnerStrokes] = useState<LearnerStroke[]>([]);
  const [narration, setNarration] = useState({ active: false, paused: false });
  useEffect(() => {
    const on = (e: Event) => setNarration((e as CustomEvent<{ active: boolean; paused: boolean }>).detail);
    window.addEventListener('narration_state', on);
    return () => window.removeEventListener('narration_state', on);
  }, []);
  const [redoStrokes, setRedoStrokes] = useState<LearnerStroke[]>([]);   // strokes taken back by undo; a new stroke or clear empties it
  const [activeIntent, setActiveIntent] = useState<LearnerIntent | null>(activeLearnerIntent || null);
  const [isDrawing, setIsDrawing] = useState(false);
  const [currentPoints, setCurrentPoints] = useState<Array<{ x: number; y: number }>>([]);

  useEffect(() => {
    if (activeLearnerIntent !== undefined) {
      setActiveIntent(activeLearnerIntent);
    }
  }, [activeLearnerIntent]);

  useEffect(() => {
    setLearnerStrokes([]);
    setRedoStrokes([]);   // each page starts with no stroke history (the strokes themselves are per page and not kept)
    setActiveIntent(null);
    onLearnerIntentChange?.(null);
  }, [pageId]);

  // ---------------------------------------------------------------------------
  // Live FIFO audio queue (Draw + Annotate)
  // ---------------------------------------------------------------------------
  type LiveQueueItem =
    | { type: 'draw'; payload: WsElementDrawn['payload'] }
    | { type: 'annotate'; payload: AnnotationPayload };

  const liveQueueRef = useRef<Array<LiveQueueItem>>([]);
  const liveProcessingRef = useRef(false);
  const liveCancelledRef = useRef(false);
  const processLiveQueueRef = useRef<() => void>(() => {});

  useEffect(() => {
    liveCancelledRef.current = false;
    liveQueueRef.current = [];
    liveProcessingRef.current = false;
    return () => {
      liveCancelledRef.current = true;
    };
  }, [pageId]);

  // Learner interrupts the tutor: narrationPlayback ends the clip that is playing; everything still queued is shown
  // straight away without sound, so the board matches what was saved and nothing is left waiting behind the cut.
  const flushLiveQueueRef = useRef<() => void>(() => {});
  useEffect(() => {
    const handleBargeIn = () => {
      debug('[WhiteboardCanvas] Barge-in: showing queued drawings without narration');
      flushLiveQueueRef.current();
    };
    window.addEventListener('tutor_barge_in', handleBargeIn);
    return () => window.removeEventListener('tutor_barge_in', handleBargeIn);
  }, []);

  // ---------------------------------------------------------------------------
  // Annotation DOM operations & ephemeral auto-fade
  // ---------------------------------------------------------------------------
  const removeAnnotationDom = useCallback((annotationId: string) => {
    const entry = activeAnnotationsRef.current.get(annotationId);
    if (!entry) return;
    if (entry.timerId) clearTimeout(entry.timerId);
    entry.nodes.underlayNode?.remove();
    entry.nodes.annotationNode?.remove();
    entry.nodes.labelNode?.remove();
    activeAnnotationsRef.current.delete(annotationId);
  }, []);

  const fadeAndRemoveAnnotation = useCallback((annotationId: string) => {
    const entry = activeAnnotationsRef.current.get(annotationId);
    if (!entry) return;
    const { nodes } = entry;
    const elementsToFade = [nodes.underlayNode, nodes.annotationNode, nodes.labelNode].filter(Boolean) as SVGElement[];
    elementsToFade.forEach(el => {
      el.style.transition = 'opacity 0.6s ease-out';
      el.style.opacity = '0';
    });
    setTimeout(() => {
      removeAnnotationDom(annotationId);
    }, 650);
  }, [removeAnnotationDom]);

  const drawAnnotation = useCallback((payload: AnnotationPayload) => {
    if (!svgRef.current) return;
    const svgRoot = svgRef.current;

    // Remove any previous instance of this annotation_id
    if (activeAnnotationsRef.current.has(payload.annotation_id)) {
      removeAnnotationDom(payload.annotation_id);
    }

    const targetBounds = getElementBounds(svgRoot, payload.target_element_id);
    if (!targetBounds) {
      console.warn(`[drawAnnotation] Could not find target bounds for '${payload.target_element_id}'`);
      return;
    }

    const fromBounds = payload.from_element_id ? getElementBounds(svgRoot, payload.from_element_id) : null;
    // On a lesson board, bring a mark the learner cannot see into view
    const v = viewRef.current;
    if (followingRef.current && svgRoot.querySelector('desc.cam') && (targetBounds.left < v.x || targetBounds.right > v.x + v.w || targetBounds.top < v.y || targetBounds.bottom > v.y + v.h)) {
      moveCamera(frame({ x: targetBounds.x, y: targetBounds.y, w: targetBounds.width, h: targetBounds.height }, 80));
    }
    const nodes = renderRoughAnnotation(svgRoot, payload, targetBounds, fromBounds);

    if (nodes.underlayNode && highlightsGRef.current) {
      highlightsGRef.current.appendChild(nodes.underlayNode);
    }
    if (nodes.annotationNode && annotationsGRef.current) {
      annotationsGRef.current.appendChild(nodes.annotationNode);
    }
    if (nodes.labelNode && labelsGRef.current) {
      labelsGRef.current.appendChild(nodes.labelNode);
    }

    let timerId: any = null;
    if (payload.lifetime === 'ephemeral' && payload.duration_ms > 0) {
      timerId = setTimeout(() => {
        fadeAndRemoveAnnotation(payload.annotation_id);
      }, payload.duration_ms);
    }

    activeAnnotationsRef.current.set(payload.annotation_id, { payload, nodes, timerId });
  }, [removeAnnotationDom, fadeAndRemoveAnnotation, moveCamera]);

  // Remove annotation event listener from WS
  useEffect(() => {
    if (!pendingRemoveAnnotationEvent || pendingRemoveAnnotationEvent.page_id !== pageId) return;
    removeAnnotationDom(pendingRemoveAnnotationEvent.annotation_id);
  }, [pendingRemoveAnnotationEvent, pageId, removeAnnotationDom]);

  // ---------------------------------------------------------------------------
  // Replay mode: clear board, re-emit all events in seq order with audio + reveal
  // ---------------------------------------------------------------------------
  useEffect(() => {
    if (!isReplaying || !replayEvents || replayEvents.length === 0) return;
    const cancelledRef = { current: false };

    const run = async () => {
      setElements(new Map());
      activeAnnotationsRef.current.forEach(entry => {
        if (entry.timerId) clearTimeout(entry.timerId);
        entry.nodes.underlayNode?.remove();
        entry.nodes.annotationNode?.remove();
        entry.nodes.labelNode?.remove();
      });
      activeAnnotationsRef.current.clear();
      setReplayStep(0);
      if (typeof window !== 'undefined') {
        window.dispatchEvent(
          new CustomEvent('replay_started', {
            detail: { totalEvents: replayEvents.length },
          })
        );
      }
      await sleep(60);

      let step = 0;
      for (const item of replayEvents) {
        if (cancelledRef.current) break;
        step++;
        setReplayStep(step);
        setActiveElementId(item.element_id);

        if (item.kind === 'annotate') {
          try {
            const payload: AnnotationPayload = JSON.parse(item.svg_fragment);
            if (item.audio_url) {
              await playAudioWithTiming(
                item.audio_url,
                item.alignment_url ?? null,
                item.element_id,
                () => {
                  drawAnnotation(payload);
                },
                cancelledRef,
                playbackSpeedRef.current,
                isMutedRef.current
              );
            } else {
              drawAnnotation(payload);
              await sleep(500 / playbackSpeedRef.current);
            }
          } catch (e) {
            console.warn('[Replay] Failed to parse annotation payload:', e);
          }
        } else if (item.kind === 'remove_annotation') {
          removeAnnotationDom(item.element_id);
          await sleep(200 / playbackSpeedRef.current);
        } else {
          // Standard draw or modify
          followFragment(item.svg_fragment);
          if (item.audio_url) {
            const audioFull = item.audio_url;
            const alignFull = item.alignment_url ?? null;

            await playAudioWithTiming(
              audioFull,
              alignFull,
              item.element_id,
              () => {
                setElements(prev => new Map(prev).set(item.element_id, item.svg_fragment));
                focusStep(item.element_id, item.svg_fragment);
              },
              cancelledRef,
              playbackSpeedRef.current,
              isMutedRef.current
            );
          } else {
            setElements(prev => new Map(prev).set(item.element_id, item.svg_fragment));
            await sleep(600 / playbackSpeedRef.current);
          }
        }
      }

      setActiveElementId(null);
      setIsPlaying(false);
      setReplayStep(0);
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('replay_completed'));
      }
      onReplayDoneRef.current?.();
    };

    setIsPlaying(true);
    run();
    return () => {
      cancelledRef.current = true;
      setActiveElementId(null);
      setReplayStep(0);
    };
  }, [isReplaying, replayEvents, drawAnnotation, removeAnnotationDom, followFragment, focusStep]);

  // ---------------------------------------------------------------------------
  // Live draw & annotate events from WS: enqueue into FIFO live queue
  // ---------------------------------------------------------------------------
  useEffect(() => {
    if (!pendingDrawEvent || pendingDrawEvent.page_id !== pageId) return;
    liveQueueRef.current.push({ type: 'draw', payload: pendingDrawEvent });
    processLiveQueueRef.current();
  }, [pendingDrawEvent, pageId]);

  useEffect(() => {
    if (!pendingAnnotateEvent || pendingAnnotateEvent.page_id !== pageId) return;
    liveQueueRef.current.push({ type: 'annotate', payload: pendingAnnotateEvent });
    processLiveQueueRef.current();
  }, [pendingAnnotateEvent, pageId]);

  useEffect(() => {
    const processLiveQueue = () => {
      if (liveProcessingRef.current) return;
      liveProcessingRef.current = true;
      setIsPlaying(true);

      const drain = async () => {
        while (liveQueueRef.current.length > 0 && !liveCancelledRef.current) {
          const item = liveQueueRef.current.shift()!;
          if (item.type === 'draw') {
            const { element_id, svg_fragment, audio_url, alignment_url } = item.payload;
            setActiveElementId(element_id);
            followFragment(svg_fragment);

            if (audio_url) {
              const audioFull = audio_url;
              const alignFull = alignment_url ?? null;

              await playAudioWithTiming(
                audioFull,
                alignFull,
                element_id,
                () => {
                  setElements(prev => new Map(prev).set(element_id, svg_fragment));
                  focusStep(element_id, svg_fragment);
                },
                liveCancelledRef,
                playbackSpeedRef.current,
                isMutedRef.current,
                true
              );
            } else {
              setElements(prev => new Map(prev).set(element_id, svg_fragment));
              focusStep(element_id, svg_fragment);
              await sleep(400 / playbackSpeedRef.current);
            }
          } else if (item.type === 'annotate') {
            const ann = item.payload;
            setActiveElementId(ann.annotation_id);

            if (ann.audio_url) {
              await playAudioWithTiming(
                ann.audio_url,
                ann.alignment_url ?? null,
                ann.annotation_id,
                () => {
                  drawAnnotation(ann);
                },
                liveCancelledRef,
                playbackSpeedRef.current,
                isMutedRef.current,
                true
              );
            } else {
              drawAnnotation(ann);
              await sleep(400 / playbackSpeedRef.current);
            }
          }
        }
        liveProcessingRef.current = false;
        setActiveElementId(null);
        setIsPlaying(false);
      };

      drain();
    };

    processLiveQueueRef.current = processLiveQueue;
    flushLiveQueueRef.current = () => {
      for (const item of liveQueueRef.current.splice(0)) {
        if (item.type === 'draw') {
          const { element_id, svg_fragment } = item.payload;
          setElements(prev => new Map(prev).set(element_id, svg_fragment));
        } else {
          drawAnnotation(item.payload);
        }
      }
    };
  }, [drawAnnotation, followFragment, focusStep]);

  // ---------------------------------------------------------------------------
  // Modify event handling
  // ---------------------------------------------------------------------------
  useEffect(() => {
    if (!pendingModifyEvent || pendingModifyEvent.page_id !== pageId) return;
    const { element_id, new_svg_fragment } = pendingModifyEvent;
    setElements(prev => {
      const next = new Map(prev);
      next.set(element_id, new_svg_fragment);
      return next;
    });
  }, [pendingModifyEvent, pageId]);

  // ---------------------------------------------------------------------------
  // Page change: load existing page events & permanent annotations
  // ---------------------------------------------------------------------------
  const loadPage = useCallback(async () => {
    if (!notebookId || !pageId) {
      setElements(new Map());
      moveCamera(DEFAULT_VIEW, 0);
      activeAnnotationsRef.current.forEach(entry => {
        if (entry.timerId) clearTimeout(entry.timerId);
        entry.nodes.underlayNode?.remove();
        entry.nodes.annotationNode?.remove();
        entry.nodes.labelNode?.remove();
      });
      activeAnnotationsRef.current.clear();
      return;
    }

    try {
      const res = await fetch(`/api/notebooks/${notebookId}/pages/${pageId}/events`);
      if (!res.ok) return;
      const data = await res.json();

      const eventMap = new Map<string, string>();
      const permanentAnns: AnnotationPayload[] = [];
      const removedAnnIds = new Set<string>();

      for (const ev of data.events ?? []) {
        if (ev.kind === 'draw' && ev.element_id && ev.svg_fragment) {
          eventMap.set(ev.element_id, ev.svg_fragment);
        } else if (ev.kind === 'modify' && ev.element_id && ev.svg_fragment) {
          eventMap.set(ev.element_id, ev.svg_fragment);
        } else if (ev.kind === 'annotate' && ev.svg_fragment) {
          try {
            const ann: AnnotationPayload = JSON.parse(ev.svg_fragment);
            if (ann.lifetime === 'permanent') {
              permanentAnns.push(ann);
            }
          } catch (err) {}
        } else if (ev.kind === 'remove_annotation' && ev.element_id) {
          removedAnnIds.add(ev.element_id);
        }
      }
      setElements(eventMap);
      // A lesson board opens on the whole board, unless the tutor is already explaining a block (new page, reconnect): keep following it
      if (!liveProcessingRef.current) {
        followedBlockRef.current = '';
        setFollowing(true);   // another page: the camera follows the tutor again
        const svg = svgRef.current, scale = svg ? Math.min(svg.clientWidth / CANVAS_WIDTH, svg.clientHeight / CANVAS_HEIGHT) : 1;
        moveCamera(openingView([...eventMap.values()], scale) ?? DEFAULT_VIEW, 0);
      }

      // Render surviving permanent annotations with DOM measurement retry
      const activePermanent = permanentAnns.filter(a => !removedAnnIds.has(a.annotation_id));
      if (activePermanent.length > 0) {
        const renderWithRetry = (remaining: AnnotationPayload[], attempts = 0) => {
          if (remaining.length === 0 || attempts > 6) return;
          const stillMissing: AnnotationPayload[] = [];
          for (const ann of remaining) {
            const bounds = svgRef.current ? getElementBounds(svgRef.current, ann.target_element_id) : null;
            if (bounds) {
              drawAnnotation(ann);
            } else {
              stillMissing.push(ann);
            }
          }
          if (stillMissing.length > 0 && attempts < 6) {
            setTimeout(() => renderWithRetry(stillMissing, attempts + 1), 60);
          }
        };
        setTimeout(() => renderWithRetry(activePermanent, 0), 40);
      }
    } catch (e) {
      console.error('[WhiteboardCanvas] Failed to load page events:', e);
    }
  }, [notebookId, pageId, drawAnnotation, moveCamera]);

  useEffect(() => {
    loadPage();
    return () => {
      activeAnnotationsRef.current.forEach(entry => {
        if (entry.timerId) clearTimeout(entry.timerId);
        entry.nodes.underlayNode?.remove();
        entry.nodes.annotationNode?.remove();
        entry.nodes.labelNode?.remove();
      });
      activeAnnotationsRef.current.clear();
    };
  }, [loadPage]);

  // Re-sync canvas on network reconnect
  useEffect(() => {
    const handleReconnect = () => {
      debug('[WhiteboardCanvas] Network reconnected — re-syncing canvas elements and annotations');
      loadPage();
    };
    window.addEventListener('notebook_reconnected', handleReconnect);
    return () => window.removeEventListener('notebook_reconnected', handleReconnect);
  }, [loadPage]);

  // ---------------------------------------------------------------------------
  // Zoom & Pan Handlers
  // ---------------------------------------------------------------------------
  // The zoom used to scale the paper card inside its frame and the pan worked only above 100%, while the tutor's camera kept moving
  // the view back: the board felt fixed (owner, 2026-11-05). Now every control moves the one camera (the SVG viewBox).
  const handleZoomIn = () => takeCamera(zoomAt(viewRef.current, 1.25));
  const handleZoomOut = () => takeCamera(zoomAt(viewRef.current, 1 / 1.25));
  const handleResetZoom = () => {
    setFollowing(false);
    followedBlockRef.current = '';
    moveCamera(overview(elements.values()) ?? DEFAULT_VIEW);   // the whole board
  };
  const followTutor = () => {
    setFollowing(true);
    followedBlockRef.current = '';
    const last = [...elements.values()].at(-1);
    moveCamera((last ? blockFrame(last) : null) ?? overview(elements.values()) ?? DEFAULT_VIEW);   // an empty last element falls back too
  };
  /** Board units per screen pixel (the viewBox is letterboxed into the paper). */
  const unitsPerPx = () => { const m = svgRef.current?.getScreenCTM(); return m && m.a ? 1 / m.a : 1; };
  const handleBoardKeyDown = (e: React.KeyboardEvent) => {
    if (e.target !== e.currentTarget) return;   // keys typed into something inside the board are theirs
    const v = viewRef.current, step = { ArrowLeft: [-0.15, 0], ArrowRight: [0.15, 0], ArrowUp: [0, -0.15], ArrowDown: [0, 0.15] }[e.key];
    if (step) takeCamera(panBy(v, step[0] * v.w, step[1] * v.h));
    else if (e.key === '+' || e.key === '=') handleZoomIn();
    else if (e.key === '-') handleZoomOut();
    else if (e.key === '0') handleResetZoom();
    else return;
    e.preventDefault();
  };
  useEffect(() => {   // the wheel zooms around the pointer (a native listener: React's wheel listener cannot stop the page scrolling)
    const svg = svgRef.current;
    if (!svg) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const p = screenToSvgCoordinates(svg, e.clientX, e.clientY);
      takeCamera(zoomAt(viewRef.current, Math.exp(-e.deltaY * 0.0015), p.x, p.y));
    };
    svg.addEventListener('wheel', onWheel, { passive: false });
    return () => svg.removeEventListener('wheel', onWheel);
  }, [takeCamera]);

  const handleMouseMove = (e: React.MouseEvent) => {
    // Detect hovered element id
    const target = e.target as SVGElement | null;
    const parentGroup = target?.closest('#whiteboard-elements > g');
    if (parentGroup && parentGroup.id) {
      setHoveredElementId(parentGroup.id);
    } else {
      setHoveredElementId(null);
    }
  };

  // ---------------------------------------------------------------------------
  // Learner Pointer & Freehand Drawing Handlers
  // ---------------------------------------------------------------------------
  const handleSvgPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    if (learnerTool === 'select' && e.button === 0) { dragRef.current = { x: e.clientX, y: e.clientY, moved: false }; return; }   // Pan: drag the board
    if (learnerTool !== 'pen' && learnerTool !== 'highlighter') return;
    if (!svgRef.current) return;
    const pt = screenToSvgCoordinates(svgRef.current, e.clientX, e.clientY);
    setIsDrawing(true);
    setCurrentPoints([pt]);
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {}
  };

  const handleSvgPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const d = dragRef.current;
    if (d) {
      if (!d.moved && Math.hypot(e.clientX - d.x, e.clientY - d.y) < 4) return;   // a click stays a click
      if (!d.moved) { d.moved = true; setIsPanning(true); try { e.currentTarget.setPointerCapture(e.pointerId); } catch {} }
      const u = unitsPerPx();
      takeCamera(panBy(viewRef.current, -(e.clientX - d.x) * u, -(e.clientY - d.y) * u));
      d.x = e.clientX; d.y = e.clientY;
      return;
    }
    if (!isDrawing) return;
    if (!svgRef.current) return;
    const pt = screenToSvgCoordinates(svgRef.current, e.clientX, e.clientY);
    setCurrentPoints(prev => [...prev, pt]);
  };

  const handleSvgPointerUp = (e: React.PointerEvent<SVGSVGElement>) => {
    if (dragRef.current) {
      const clicked = !dragRef.current.moved;
      dragRef.current = null;
      setIsPanning(false);
      try { e.currentTarget.releasePointerCapture(e.pointerId); } catch {}
      if (clicked && svgRef.current) {   // a click on a board item: ask about just that item (Explain, Simpler, Example, Ask…)
        const pt = screenToSvgCoordinates(svgRef.current, e.clientX, e.clientY);
        const hit = boardItems()
          .filter(el => pt.x >= el.bounds.left && pt.x <= el.bounds.right && pt.y >= el.bounds.top && pt.y <= el.bounds.bottom)
          .sort((a, b) => a.bounds.width * a.bounds.height - b.bounds.width * b.bounds.height)[0];   // the smallest: a node, not its whole step
        const intent: LearnerIntent | null = hit ? {
          intentType: 'single', selectedElementIds: [hit.id], gestureType: 'point', topScore: 1,
          candidates: [{ elementId: hit.id, label: hit.label, matchScore: 1, containment: 1, iou: 1, proximity: 1, gesture: 'point' }],
          selectionCenter: { x: hit.bounds.x + hit.bounds.width / 2, y: hit.bounds.top },
        } : null;
        setActiveIntent(intent);
        onLearnerIntentChange?.(intent);
      }
      return;
    }
    if (!isDrawing) return;
    setIsDrawing(false);
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {}

    if (currentPoints.length === 0) {
      setCurrentPoints([]);
      return;
    }

    // For a single click (tap), add a tiny offset point to form a valid dot stroke
    const effectivePoints =
      currentPoints.length === 1
        ? [currentPoints[0], { x: currentPoints[0].x + 0.5, y: currentPoints[0].y + 0.5 }]
        : currentPoints;

    const strokeBBox = computeStrokeBBox(effectivePoints);
    const newStroke: LearnerStroke = {
      id: `stroke_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
      tool: learnerTool as 'pen' | 'highlighter',
      color: learnerColor,
      points: effectivePoints,
      bbox: strokeBBox,
    };
    setLearnerStrokes(prev => [...prev, newStroke]);
    setRedoStrokes([]);

    // Perform spatial hit-testing against active diagram elements
    if (svgRef.current) {
      const intent = resolveLearnerIntent(effectivePoints, boardItems());
      if (intent) {
        setActiveIntent(intent);
        onLearnerIntentChange?.(intent);
      }
    }
    setCurrentPoints([]);
  };

  /** What the learner can point at, with its bounds on the board: whole drawings, or the nodes inside a lesson-board step. */
  const boardItems = () => {
    const svg = svgRef.current;
    if (!svg) return [];
    return Array.from(elements.keys()).flatMap(id => pointableParts(svg, id))
      .map(({ id, label }) => {
        const bounds = getElementBounds(svg, id);
        return bounds ? { id, bounds, label } : null;
      })
      .filter((el): el is { id: string; bounds: ElementBounds; label: string | undefined } => el !== null);
  };
  const closeItemActions = () => { setActiveIntent(null); onLearnerIntentChange?.(null); };
  /** Simpler / Example on the selected item: the same chat send as a typed question, with the item attached. */
  const askAboutItem = (prompt: (label: string) => string) => {
    if (!activeIntent) return;
    const label = activeIntent.candidates[0]?.label || activeIntent.selectedElementIds[0];
    window.dispatchEvent(new CustomEvent('send_chat_query', { detail: { message: prompt(label), intent: activeIntent } }));
    closeItemActions();
  };
  /** Ask…: the item stays selected and the learner types their own question about it. */
  const askTyped = () => window.dispatchEvent(new CustomEvent('focus_chat_input'));

  const handleExplainThis = () => {
    if (!activeIntent) return;
    if (onAskAboutSelection) {
      onAskAboutSelection(activeIntent);
    } else {
      window.dispatchEvent(
        new CustomEvent('ask_tutor_about_selection', { detail: activeIntent })
      );
    }
    setActiveIntent(null);
    onLearnerIntentChange?.(null);
  };

  // ---------------------------------------------------------------------------
  // Export Handlers
  // ---------------------------------------------------------------------------
  const showToast = (message: string) => {
    setToast(message);
    setTimeout(() => setToast(null), 2500);
  };

  // ---------------------------------------------------------------------------
  // Undo the last drawing (server removes it and announces element_removed)
  // ---------------------------------------------------------------------------
  const canUndo = pageStatus === 'active' && elements.size > 0 && !isReplaying;

  const handleUndo = useCallback(async () => {
    if (!notebookId || !pageId) return;
    try {
      const res = await fetch(`/api/notebooks/${notebookId}/pages/${pageId}/undo`, { method: 'POST' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: '' }));
        showToast(typeof err.detail === 'string' && err.detail ? err.detail : 'Could not undo that.');
      }
    } catch {
      showToast('Could not reach the server.');
    }
  }, [notebookId, pageId]);

  // The learner's own strokes are client-side only: undo/redo just moves the last stroke between two lists.
  const undoStroke = useCallback(() => {
    const last = learnerStrokes[learnerStrokes.length - 1];
    if (!last) return;
    setLearnerStrokes(learnerStrokes.slice(0, -1));
    setRedoStrokes(r => [...r, last]);
    setActiveIntent(null);
    onLearnerIntentChange?.(null);
  }, [learnerStrokes, onLearnerIntentChange]);
  const redoStroke = useCallback(() => {
    const last = redoStrokes[redoStrokes.length - 1];
    if (!last) return;
    setRedoStrokes(redoStrokes.slice(0, -1));
    setLearnerStrokes(s => [...s, last]);
  }, [redoStrokes]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const typing = !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable);
      if (e.key === ' ' && !typing && !e.ctrlKey && !e.metaKey && !e.altKey && narration.active
          && !['BUTTON', 'SELECT', 'A'].includes(el?.tagName ?? '')) {
        e.preventDefault();
        toggleNarrationPause();
        return;
      }
      if (typing || !(e.ctrlKey || e.metaKey)) return;
      const k = e.key.toLowerCase();
      if (k === 'z' && e.shiftKey || k === 'y') {
        if (redoStrokes.length) { e.preventDefault(); redoStroke(); }
      } else if (k === 'z') {
        // Ctrl+Z takes back the learner's own last stroke first; with none left it undoes the tutor's last drawing as before.
        if (learnerStrokes.length) { e.preventDefault(); undoStroke(); }
        else if (canUndo) { e.preventDefault(); handleUndo(); }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [canUndo, handleUndo, learnerStrokes.length, redoStrokes.length, undoStroke, redoStroke, narration.active]);

  // The server removed an element (undo from any tab): drop it and any annotations drawn on it
  useEffect(() => {
    if (!pendingRemoveElementEvent || pendingRemoveElementEvent.page_id !== pageId) return;
    const { element_id, annotation_ids } = pendingRemoveElementEvent;
    setElements(prev => {
      if (!prev.has(element_id)) return prev;
      const next = new Map(prev);
      next.delete(element_id);
      return next;
    });
    annotation_ids.forEach(removeAnnotationDom);
  }, [pendingRemoveElementEvent, pageId, removeAnnotationDom]);

  const isLessonBoard = useMemo(() => overview(elements.values()) !== null, [elements]);
  // Exports show the whole board, not the camera's current view
  const exportView = useCallback(() => overview(elements.values()) ?? DEFAULT_VIEW, [elements]);
  const getFullSvgString = useCallback(() => serializeSvg(svgRef.current, exportView()), [exportView]);

  const handleExportSvg = () => {
    const svgStr = getFullSvgString();
    if (svgStr) downloadSvg(svgStr, `whiteboard-${pageId || 'concept'}.svg`);
  };

  const handleExportPng = () => {
    const svgStr = getFullSvgString();
    const v = exportView();
    if (svgStr) downloadPng(svgStr, `whiteboard-${pageId || 'concept'}.png`, THEME_STYLES[theme].canvasBg, Math.round(v.w), Math.round(v.h));
  };

  const handleCopySvg = async () => {
    const svgStr = getFullSvgString();
    if (svgStr && (await copyText(svgStr))) {
      showToast('SVG copied to clipboard');
    }
  };

  // ---------------------------------------------------------------------------
  // Compose SVG content
  // ---------------------------------------------------------------------------
  // Overflowing labels in a unique rect/circle/ellipse are drawn smaller (render-time copy; stored fragments are untouched).
  // Recomputed from the written fragments after every change, so the result only ever depends on the current board.
  const [fittedFragments, setFittedFragments] = useState<Map<string, string>>(new Map());
  useEffect(() => {
    let stale = false;
    fitTextInFragments(Array.from(elements.values())).then(m => { if (!stale) setFittedFragments(m); });
    return () => { stale = true; };
  }, [elements]);

  const composedSvgContent = useMemo(() => {
    return Array.from(elements.values())
      .map(frag => fittedFragments.get(frag) ?? frag)
      .map(frag => (isHandDrawn ? roughifySvgFragment(frag, { roughness: 1.1 }) : frag))
      .join('\n');
  }, [elements, isHandDrawn, fittedFragments]);

  const themeStyles = THEME_STYLES[theme];

  return (
    <div
      ref={containerRef}
      className="wb-surface"
      onMouseMove={handleMouseMove}
      style={{
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--bg)',
        padding: '64px 24px 64px',   // the toolbar sits above and the zoom controls below: the board never slides under them (200% zoom)
        position: 'relative',
        overflow: 'hidden',
        userSelect: 'none',
      }}
    >
      <WhiteboardToolbar
        isPlaying={isPlaying}
        activeElementId={activeElementId}
        hoveredElementId={hoveredElementId}
        learnerTool={learnerTool}
        setLearnerTool={setLearnerTool}
        learnerColor={learnerColor}
        setLearnerColor={setLearnerColor}
        hasMarks={learnerStrokes.length > 0}
        onClearMarks={() => {
          setLearnerStrokes([]);
          setRedoStrokes([]);
          setActiveIntent(null);
          onLearnerIntentChange?.(null);
        }}
        narrationActive={narration.active}
        narrationPaused={narration.paused}
        onTogglePause={toggleNarrationPause}
        canUndoStroke={learnerStrokes.length > 0}
        canRedoStroke={redoStrokes.length > 0}
        onUndoStroke={undoStroke}
        onRedoStroke={redoStroke}
        theme={theme}
        setTheme={setTheme}
        showGrid={showGrid}
        setShowGrid={setShowGrid}
        isHandDrawn={isHandDrawn}
        setIsHandDrawn={setIsHandDrawn}
        handleExportSvg={handleExportSvg}
        handleExportPng={handleExportPng}
        handleCopySvg={handleCopySvg}
        canUndo={canUndo}
        handleUndo={handleUndo}
      />

      {/* Short confirmation / error message */}
      {toast && (
        <div role="status" style={{
          position: 'absolute', top: 60, right: 16,
          background: 'var(--ink)', color: 'var(--panel)',
          padding: '6px 14px', borderRadius: '8px',
          fontSize: '13px', fontWeight: 500,
          boxShadow: 'var(--shadow)',
          zIndex: 50,
          animation: 'fadeIn 0.2s',
        }}>
          {toast}
        </div>
      )}

      {/* Whiteboard surface */}
      <div className={`wb-board-${theme} wb-paper`} tabIndex={0} onKeyDown={handleBoardKeyDown}
           aria-label="Whiteboard. Arrow keys move the view, plus and minus zoom, 0 shows the whole board." style={{
        width: '100%',
        maxWidth: `${CANVAS_WIDTH}px`,
        maxHeight: '100%',   // on a short window the paper gets wider than 3:2 instead of overflowing; the SVG letterboxes inside
        aspectRatio: `${CANVAS_WIDTH} / ${CANVAS_HEIGHT}`,
        background: themeStyles.canvasBg,
        borderRadius: '12px',
        boxShadow: themeStyles.shadow,
        overflow: 'hidden',
        position: 'relative',
      }}>
        {/* Natural-media paint under the dot grid and the SVG, from the blocks' paint recipes (none unless the server sets LP_PAINT=1) */}
        {isLessonBoard && <PaintLayer svgRef={svgRef} view={view} version={composedSvgContent} paper={themeStyles.canvasBg} />}

        {/* Background Dot Grid */}
        {showGrid && (
          <div style={{
            position: 'absolute', inset: 0,
            backgroundImage: `radial-gradient(${themeStyles.dotColor} 1.5px, transparent 1.5px)`,
            backgroundSize: '24px 24px',
            pointerEvents: 'none',
          }} />
        )}

        {/* Center SVG canvas — always mounted */}
        <svg
          ref={svgRef}
          // A lesson board is real text in teaching order (notes, titles, labels), so screen readers can read it; a raw-SVG drawing stays one image
          role={isLessonBoard ? 'document' : 'img'}
          aria-roledescription={isLessonBoard ? 'lesson board' : undefined}
          aria-label={isLessonBoard
            ? "Whiteboard drawing: lesson board. Notes, diagrams and recaps in the order the tutor taught them."
            : "Whiteboard drawing. The tutor's spoken explanation of each element appears in the chat panel."}
          xmlns="http://www.w3.org/2000/svg"
          viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
          width="100%"
          height="100%"
          onPointerDown={handleSvgPointerDown}
          onPointerMove={handleSvgPointerMove}
          onPointerUp={handleSvgPointerUp}
          style={{
            display: 'block',
            position: 'relative',
            zIndex: 1,
            cursor:
              learnerTool === 'pen' || learnerTool === 'highlighter'
                ? 'crosshair'
                : learnerTool === 'eraser'
                ? 'pointer'
                : isPanning ? 'grabbing' : 'grab',
            touchAction: 'none',
          }}
        >
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
              <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#2563eb" />
            </marker>
            <marker id="arrow-dark" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
              <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#1e293b" />
            </marker>
            <marker id="arrow-green" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
              <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#059669" />
            </marker>
            {/* Watercolour for shapes marked `wash` (texture proof, LP_PAINT=svg), in board units so it scales with zoom and stays sharp:
                ragged edge (noise displacement), uneven pigment (noise in the alpha), a slightly darker dried rim. Fixed seeds: same every load. */}
            <filter id="wb-watercolour" x="-12%" y="-12%" width="124%" height="124%" primitiveUnits="userSpaceOnUse">
              <feMorphology in="SourceGraphic" operator="dilate" radius="3" result="spread" />
              <feTurbulence type="fractalNoise" baseFrequency="0.03" numOctaves="3" seed="7" result="warp" />
              <feDisplacementMap in="spread" in2="warp" scale="13" xChannelSelector="R" yChannelSelector="G" result="ragged" />
              <feTurbulence type="fractalNoise" baseFrequency="0.07" numOctaves="2" seed="11" result="mottle" />
              <feColorMatrix in="mottle" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -1.1 1.2" result="pigment" />
              <feComposite in="ragged" in2="pigment" operator="in" result="body" />
              <feMorphology in="ragged" operator="erode" radius="2.5" result="inner" />
              <feComposite in="ragged" in2="inner" operator="out" result="rim" />
              <feColorMatrix in="rim" type="matrix" values="0.62 0 0 0 0  0 0.62 0 0 0  0 0 0.62 0 0  0 0 0 0.9 0" result="dried" />
              <feMerge><feMergeNode in="body" /><feMergeNode in="dried" /></feMerge>
            </filter>
          </defs>
          {/* Layer 1: Highlighter Underlay (beneath diagram cards & text) */}
          <g id="whiteboard-highlights" ref={highlightsGRef} />

          {/* Layer 2: Vector diagram components */}
          <g id="whiteboard-elements" dangerouslySetInnerHTML={{ __html: composedSvgContent }} />

          {/* Layer 3: Organic Marks (Rough.js circles, underlines, ticks, crosses, arrows) */}
          <g id="whiteboard-annotations" ref={annotationsGRef} />

          {/* Layer 4: Callout notes and badges */}
          <g id="whiteboard-labels" ref={labelsGRef} />

          {/* Layer 5: Learner Freehand Drawings & Highlighters */}
          <g id="whiteboard-learner-drawings">
            {learnerStrokes.map(stroke => (
              <path
                key={stroke.id}
                d={pointsToSvgPath(stroke.points)}
                fill="none"
                stroke={stroke.color}
                strokeWidth={stroke.tool === 'highlighter' ? 22 : 3.5}
                strokeLinecap="round"
                strokeLinejoin="round"
                opacity={stroke.tool === 'highlighter' ? 0.30 : 0.95}
                style={{
                  cursor: learnerTool === 'eraser' ? 'pointer' : 'default',
                  pointerEvents: learnerTool === 'eraser' ? 'auto' : 'none',
                  transition: 'opacity 0.15s ease',
                }}
                onClick={(e) => {
                  if (learnerTool === 'eraser') {
                    e.stopPropagation();
                    setLearnerStrokes(prev => prev.filter(s => s.id !== stroke.id));
                    setActiveIntent(null);
                    onLearnerIntentChange?.(null);
                  }
                }}
              />
            ))}
            {isDrawing && currentPoints.length > 0 && (
              <path
                d={pointsToSvgPath(currentPoints)}
                fill="none"
                stroke={learnerColor}
                strokeWidth={learnerTool === 'highlighter' ? 22 : 3.5}
                strokeLinecap="round"
                strokeLinejoin="round"
                opacity={learnerTool === 'highlighter' ? 0.30 : 0.95}
                style={{ pointerEvents: 'none' }}
              />
            )}
          </g>
        </svg>

        {/* What the learner can do with the item they circled or clicked: real buttons (the old chip was a div, out of keyboard reach) */}
        {activeIntent && activeIntent.candidates.length > 0 && (() => {
          const pair = activeIntent.intentType === 'relationship';
          const label = activeIntent.relationshipLabel || activeIntent.candidates[0].label || activeIntent.selectedElementIds[0];
          return (
            <div
              id="explain-this-chip"
              data-intent={activeIntent.intentType}
              role="toolbar"
              aria-label={`Ask about ${label}`}
              className={`wb-item-actions${pair ? ' pair' : ''}`}
              onKeyDown={e => { if (e.key === 'Escape') closeItemActions(); }}
              style={{
                left: `${Math.max(12, Math.min(88, ((activeIntent.selectionCenter.x - view.x) / view.w) * 100))}%`,
                top: `${Math.max(10, Math.min(88, ((activeIntent.selectionCenter.y - view.y) / view.h) * 100 - 2))}%`,
              }}
            >
              <span className="wb-item-label">{label}</span>
              <button type="button" onClick={handleExplainThis}>{pair ? 'Explain connection' : 'Explain'}</button>
              {!pair && <button type="button" onClick={() => askAboutItem(l => `Explain ${l} more simply, with an everyday analogy.`)}>Simpler</button>}
              {!pair && <button type="button" onClick={() => askAboutItem(l => `Give me a concrete real-world example of ${l}.`)}>Example</button>}
              <button type="button" onClick={askTyped}>Ask…</button>
              <button type="button" className="wb-item-close" aria-label="Close" onClick={closeItemActions}>✕</button>
            </div>
          );
        })()}

        <NarrationCaption />

        {/* Empty state hint */}
        {elements.size === 0 && (
          <div style={{
            position: 'absolute', inset: 0,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            flexDirection: 'column', gap: '12px',
            color: theme === 'blackboard' ? 'var(--ink-2)' : 'var(--ink-2)',
            pointerEvents: 'none',
            zIndex: 2,
          }}>
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <path d="M3 9h18M9 21V9" />
            </svg>
            <span style={{ fontSize: '14px', fontWeight: 500 }}>
              {!pageId ? 'Select or create a page to begin' : 'Ask a question in chat to start drawing'}
            </span>
          </div>
        )}
      </div>

      <ZoomControls zoom={zoom} handleZoomIn={handleZoomIn} handleZoomOut={handleZoomOut} handleResetZoom={handleResetZoom} />
      {isLessonBoard && !following && (
        <button type="button" onClick={followTutor} className="wb-follow"
                title="The camera follows what the tutor is explaining again">
          Follow tutor
        </button>
      )}

      <ReplayBar
        isReplaying={isReplaying}
        replayStep={replayStep}
        replayTotal={replayEvents?.length || 0}
        playbackSpeed={playbackSpeed}
        setPlaybackSpeed={setPlaybackSpeed}
      />
    </div>
  );
}
