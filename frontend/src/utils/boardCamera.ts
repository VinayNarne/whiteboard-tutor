// Camera for the lesson board (scene mode). Each element the server publishes for a notes or diagram block carries its block's box in
// an empty <desc class="cam cam-x-y-w-h"> (engine/scene.py). The board's viewBox follows the block being explained; boards without
// those boxes (raw-SVG pages) keep the fixed 1200x800 view.
import { CANVAS_WIDTH, CANVAS_HEIGHT } from '../components/whiteboard/themes';

export interface Box { x: number; y: number; w: number; h: number }

export const DEFAULT_VIEW: Box = { x: 0, y: 0, w: CANVAS_WIDTH, h: CANVAS_HEIGHT };
const CAM = /class="cam cam-(\d+)-(\d+)-(\d+)-(\d+)"/;
const ASPECT = CANVAS_WIDTH / CANVAS_HEIGHT;

/** The block box a fragment carries, or null. */
export function camBox(fragment: string): Box | null {
  const m = CAM.exec(fragment);
  return m ? { x: +m[1], y: +m[2], w: +m[3], h: +m[4] } : null;
}

/** A view of the board's shape around `b` with `pad` of margin; never closer than half the board width (at most 2x zoom). */
export function frame(b: Box, pad = 40, minW = CANVAS_WIDTH / 2): Box {
  let w = Math.max(b.w + 2 * pad, minW);
  let h = b.h + 2 * pad;
  if (w / h < ASPECT) w = h * ASPECT; else h = w / ASPECT;
  return { x: b.x + b.w / 2 - w / 2, y: b.y + b.h / 2 - h / 2, w, h };
}

/** The whole board (all blocks, at least the default view), or null when the fragments carry no block boxes. */
export function overview(fragments: Iterable<string>): Box | null {
  let bottom = -1;
  for (const f of fragments) {
    const b = camBox(f);
    if (b) bottom = Math.max(bottom, b.y + b.h);
  }
  return bottom < 0 ? null : frame({ x: 0, y: 0, w: CANVAS_WIDTH, h: Math.max(CANVAS_HEIGHT, bottom + 32) }, 0, CANVAS_WIDTH);
}

/** Ease-in-out between two views (k from 0 to 1). */
export function between(a: Box, b: Box, k: number): Box {
  const e = k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2;
  return { x: a.x + (b.x - a.x) * e, y: a.y + (b.y - a.y) * e, w: a.w + (b.w - a.w) * e, h: a.h + (b.h - a.h) * e };
}

/** Board units kept free under a framed block for the caption (about 3 lines), so it never covers the block. */
/** The learner's own camera: zoom by `factor` (>1 = closer) keeping the board point (px, py) under the pointer, within 8x in and 5x out. */
export const MIN_VIEW_W = CANVAS_WIDTH / 8, MAX_VIEW_W = CANVAS_WIDTH * 5;
export function zoomAt(v: Box, factor: number, px = v.x + v.w / 2, py = v.y + v.h / 2): Box {
  const w = Math.min(MAX_VIEW_W, Math.max(MIN_VIEW_W, v.w / factor)), k = w / v.w;
  return { x: px - (px - v.x) * k, y: py - (py - v.y) * k, w, h: v.h * k };
}
export function panBy(v: Box, dx: number, dy: number): Box {
  return { ...v, x: v.x + dx, y: v.y + dy };
}
/** How close the view is, as the zoom controls show it: 100% = the whole default board. */
export const zoomOf = (v: Box) => CANVAS_WIDTH / v.w;

export const CAPTION_ROOM = 110;
/** A block framed wider than this reads small (~16 px labels): the camera follows its steps instead of the whole block. */
export const CLOSE_ENOUGH = 900;

/** The view for a block a fragment belongs to (with room for the caption), or null for raw-SVG fragments. */
export function blockFrame(fragment: string): Box | null {
  const b = camBox(fragment);
  return b && frame({ ...b, h: b.h + CAPTION_ROOM });
}

/** The view while a big block is followed step by step: the parts on screen now (this step and the one before), stretched up to the
 *  block's top (its title) whenever that still frames close enough, so the learner keeps seeing what the block is about. */
export function stepView(block: Box, parts: Box[]): Box {
  const x0 = Math.min(...parts.map(b => b.x)), y0 = Math.min(...parts.map(b => b.y));
  const x1 = Math.max(...parts.map(b => b.x + b.w)), y1 = Math.max(...parts.map(b => b.y + b.h));
  const withTitle = frame({ x: x0, y: block.y, w: x1 - x0, h: y1 - block.y + CAPTION_ROOM }, 60);
  return withTitle.w <= CLOSE_ENOUGH ? withTitle : frame({ x: x0, y: y0, w: x1 - x0, h: y1 - y0 + CAPTION_ROOM }, 60);
}

/** Below this many screen pixels per board unit, a whole-board overview is too small to read (200% zoom, phones). It is the scale
 *  the board draws at (the smaller of width/1200 and height/800): at 200% zoom the board is wide but short, so width alone misleads. */
export const SMALL_BOARD_SCALE = 0.4;

/** Where a lesson board opens: the whole board, or on a small screen the latest block (reset still shows the whole board). */
export function openingView(fragments: string[], boardScale: number): Box | null {
  const whole = overview(fragments);
  if (!whole || boardScale >= SMALL_BOARD_SCALE) return whole;
  const last = [...fragments].reverse().find(f => camBox(f));
  return last ? blockFrame(last) : whole;
}

/** What a learner's pen can point at inside element `id`: on a lesson board (a step that carries its block box) the nodes and groups
 *  inside it, named by their own text, arrows left out so circling a box never matches the line through it; anything else whole. */
export function pointableParts(root: ParentNode, id: string): Array<{ id: string; label?: string }> {
  const el = root.querySelector(`[id="${CSS.escape(id)}"]`);
  if (!el?.querySelector(':scope > desc.cam')) return [{ id }];
  const inner = Array.from(el.querySelectorAll(':scope > g[id]:not(:has(> path.edge))'));
  return inner.length
    ? inner.map(e => ({ id: e.id, label: textOf(e) || undefined }))
    : [{ id }];
}

/** A part's words, each <text> line its own words ("Left Heart" + "to Body", not "Left Heartto Body": seen live), at most 40 characters. */
function textOf(e: Element): string {
  return Array.from(e.querySelectorAll('text'), t => t.textContent ?? '').join(' ').replaceAll(/\s+/g, ' ').trim().slice(0, 40);
}
