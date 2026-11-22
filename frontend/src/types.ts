// frontend/src/types.ts
// TypeScript interfaces for Learning Platform Phase 1

export interface Notebook {
  id: string;
  topic: string;
  title: string;
  created_at: string;
}

export interface PageSummary {
  id: string;
  page_number: number;
  title: string | null;
  summary: string | null;
  status: 'active' | 'saved';
  element_count: number;
  created_at: string;
}

export interface PageEvent {
  seq: number;
  kind: 'draw' | 'modify' | 'annotate' | 'remove_annotation';
  element_id: string;
  svg_fragment: string;
  narration: string | null;
  audio_path: string | null;
  alignment_path: string | null;
  timestamp: string;
}

export interface MarkerTiming {
  id: string;
  time: number;
  char_index: number;
  word_start_char: number;
}

export interface AlignmentData {
  audio_duration_seconds: number;
  clean_text: string;
  marker_timings: MarkerTiming[];
  raw_alignment?: {
    characters: string[];
    character_start_times_seconds: number[];
    character_end_times_seconds: number[];
  };
}

export interface ChatTurn {
  role: 'user' | 'assistant' | 'tool' | 'system';
  content: string;
  page_id?: string;
  // A tutor turn the model never answered ('failed': the model could not be reached). retry_turn_id is the learner turn to send again.
  status?: 'ok' | 'failed';
  retry_turn_id?: string;
}

// WebSocket event shapes
export interface WsElementDrawn {
  type: 'element_drawn';
  payload: {
    page_id: string;
    element_id: string;
    svg_fragment: string;
    narration: string;
    audio_url: string | null;
    alignment_url: string | null;
    voice_ok?: boolean;
  };
}

export interface WsElementModified {
  type: 'element_modified';
  payload: {
    page_id: string;
    element_id: string;
    new_svg_fragment: string;
    narration?: string | null;   // a modify that carries audio is played like a draw (replace_block's spoken correction)
    audio_url?: string | null;
    alignment_url?: string | null;
  };
}

export interface WsPageDensityNudge {
  type: 'page_density_nudge';
  payload: {
    page_id: string;
    element_count: number;
    canvas_coverage: number;
  };
}

export interface WsPageDensityHardCap {
  type: 'page_density_hard_cap';
  payload: {
    page_id: string;
    element_count: number;
  };
}

export interface WsPageSaved {
  type: 'page_saved';
  payload: { page_id: string; page_number: number };
}

export interface WsPageStarted {
  type: 'page_started';
  payload: { page_id: string; page_number: number };
}

export interface WsChatTurn {
  type: 'chat_turn';
  payload: ChatTurn;
}

export type AnnotationStyle = 'circle' | 'underline' | 'tick' | 'cross' | 'highlight' | 'arrow';
export type AnnotationLifetime = 'permanent' | 'ephemeral';

export interface AnnotationPayload {
  page_id: string;
  annotation_id: string;
  style: AnnotationStyle;
  target_element_id: string;
  from_element_id?: string | null;
  color: string;
  note?: string | null;
  lifetime: AnnotationLifetime;
  duration_ms: number;
  seed: number;
  audio_url: string | null;
  alignment_url: string | null;
  narration?: string | null;
}

export interface WsElementAnnotated {
  type: 'element_annotated';
  payload: AnnotationPayload;
}

export interface WsAnnotationRemoved {
  type: 'annotation_removed';
  payload: {
    page_id: string;
    annotation_id: string;
  };
}

export interface WsError {
  type: 'error';
  payload: { detail: string };
}

export interface WsElementRemoved {
  type: 'element_removed';
  payload: { page_id: string; element_id: string; annotation_ids: string[] };
}

export type WsEvent =
  | WsElementDrawn
  | WsElementModified
  | WsElementRemoved
  | WsElementAnnotated
  | WsAnnotationRemoved
  | WsPageDensityNudge
  | WsPageDensityHardCap
  | WsPageSaved
  | WsPageStarted
  | WsChatTurn
  | WsError;

// ---------------------------------------------------------------------------
// Learner Whiteboard Drawing & Spatial Grounding
// ---------------------------------------------------------------------------
export type LearnerTool = 'select' | 'pen' | 'highlighter' | 'eraser';
export type LearnerGestureType = 'circle' | 'underline' | 'point' | 'scribble';
export type LearnerIntentType = 'single' | 'relationship';

export interface LearnerStroke {
  id: string;
  tool: 'pen' | 'highlighter';
  color: string;
  points: Array<{ x: number; y: number }>;
  bbox: { minX: number; minY: number; maxX: number; maxY: number };
}

export interface LearnerMatchCandidate {
  elementId: string;
  label?: string;
  matchScore: number;
  containment: number;
  iou: number;
  proximity: number;
  gesture: LearnerGestureType;
}

export interface LearnerIntent {
  intentType: LearnerIntentType;
  selectedElementIds: string[];
  candidates: LearnerMatchCandidate[];
  gestureType: LearnerGestureType;
  topScore: number;
  selectionCenter: { x: number; y: number };
  relationshipLabel?: string;
}

// What the tutor remembers about the learner (GET /api/learner and every change to it return this card)
export interface LearnerCard {
  known: { id: string; name: string; description: string; level: string }[];
  misconceptions: { id: string; belief: string; corrected: boolean }[];
  preferences: { kind: string; label: string }[];
  available_preferences: { kind: string; label: string }[];
}
