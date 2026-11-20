// frontend/src/services/textFit.ts
// Render-time text fitting: shrinks a <text> that is wider than the rect / circle / ellipse it sits in.
// Works on COPIES of the fragment strings: the stored drawing and the model's coordinates are never touched,
// nothing moves, only the font size of an overflowing label gets smaller (floor below).
//
// Ported from the tested proof of concept (its replay over the 33 benchmark boards is described in docs/PROJECT_BRIEF.md):
// real browser-measured text, a shape is named only when exactly one shape contains the label's centre and no other
// shape is touched by it; every other label is left exactly as written.

const NS = 'http://www.w3.org/2000/svg';
const CANVAS_W = 1200;
const CANVAS_H = 800;
const MIN_SCALE = 0.7;       // never below 70 % of the written size ...
const MIN_PX = 11;           // ... nor below 11 px
const STEP = 0.03;           // 0.97, 0.94, ... like the PoC
const MIN_SHAPE_W = 24;      // dots, rules and bars are not label containers
const MIN_SHAPE_H = 14;
const HORIZONTAL_SLACK = 1;  // px a label may touch the edge before it counts as overflowing (vertical is always 1)

interface Shape { kind: 'rect' | 'ellipse'; x: number; y: number; w: number; h: number }
interface Box { l: number; r: number; t: number; b: number; w: number }
interface Resize { frag: number; textIndex: number; factor: number; size: number }

const inDefs = (el: Element) => !!el.closest('defs,marker,symbol,pattern,clipPath,mask');
const area = (r: { l: number; r: number; t: number; b: number }) => Math.max(0, r.r - r.l) * Math.max(0, r.b - r.t);
const inter = (a: Box, c: Box) => area({ l: Math.max(a.l, c.l), r: Math.min(a.r, c.r), t: Math.max(a.t, c.t), b: Math.min(a.b, c.b) });
const shapeBox = (s: Shape): Box => ({ l: s.x, r: s.x + s.w, t: s.y, b: s.y + s.h, w: s.w });

function shapesOf(root: Element): Shape[] {
  const out: Shape[] = [];
  root.querySelectorAll('rect,circle,ellipse').forEach(e => {
    if (inDefs(e)) return;
    const tag = e.tagName.toLowerCase();
    const f = (k: string) => parseFloat(e.getAttribute(k) || '0');
    let s: Shape;
    if (tag === 'rect') s = { kind: 'rect', x: f('x'), y: f('y'), w: f('width'), h: f('height') };
    else if (tag === 'circle') s = { kind: 'ellipse', x: f('cx') - f('r'), y: f('cy') - f('r'), w: 2 * f('r'), h: 2 * f('r') };
    else s = { kind: 'ellipse', x: f('cx') - f('rx'), y: f('cy') - f('ry'), w: 2 * f('rx'), h: 2 * f('ry') };
    if (![s.x, s.y, s.w, s.h].every(Number.isFinite)) return;
    if (s.w * s.h >= 0.5 * CANVAS_W * CANVAS_H) return;       // background frame
    if (s.w < MIN_SHAPE_W || s.h < MIN_SHAPE_H) return;
    out.push(s);
  });
  return out;
}

const inside = (s: Shape, px: number, py: number) => s.kind === 'rect'
  ? px >= s.x && px <= s.x + s.w && py >= s.y && py <= s.y + s.h
  : ((px - (s.x + s.w / 2)) / (s.w / 2)) ** 2 + ((py - (s.y + s.h / 2)) / (s.h / 2)) ** 2 <= 1;

// vertical extent = glyph band (15 %..85 % of the font box), not the whole font box
function boxOf(t: SVGTextElement): Box {
  const b = t.getBBox();
  return { l: b.x, r: b.x + b.width, t: b.y + 0.15 * b.height, b: b.y + 0.85 * b.height, w: b.width };
}

function fits(s: Shape, b: Box): boolean {
  const tol = HORIZONTAL_SLACK;
  if (s.kind === 'rect') return b.l >= s.x - tol && b.r <= s.x + s.w + tol && b.t >= s.y - 1 && b.b <= s.y + s.h + 1;
  return ([[b.l, b.t], [b.r, b.t], [b.l, b.b], [b.r, b.b]] as const).every(([px, py]) => {
    const rx = s.w / 2 + tol, ry = s.h / 2 + tol;
    return ((px - (s.x + s.w / 2)) / rx) ** 2 + ((py - (s.y + s.h / 2)) / ry) ** 2 <= 1;
  });
}

/** The one shape this label belongs to, or null when any other reading is plausible (nested, overlapping, straddling, outside). */
function uniqueShape(box: Box, shapes: Shape[]): Shape | null {
  const cx = (box.l + box.r) / 2, cy = (box.t + box.b) / 2;
  const containing = shapes.filter(s => inside(s, cx, cy));
  if (containing.length !== 1) return null;
  const ta = Math.max(1, area(box));
  const touchesAnother = shapes.some(s => s !== containing[0] && inter(box, shapeBox(s)) / ta > 0.15);
  return touchesAnother ? null : containing[0];
}

const sizeOf = (t: Element) => parseFloat(getComputedStyle(t).fontSize);

function scaleText(t: SVGTextElement, factor: number, orig: { size: number; own: string; tspans: (string | null)[] }) {
  t.style.fontSize = `${orig.size * factor}px`;
  t.querySelectorAll('tspan').forEach((x, i) => {
    const fs = orig.tspans[i];
    if (fs) x.setAttribute('font-size', String(parseFloat(fs) * factor));
  });
}

function restoreText(t: SVGTextElement, orig: { own: string; tspans: (string | null)[] }) {
  t.style.fontSize = orig.own;
  t.querySelectorAll('tspan').forEach((x, i) => {
    const fs = orig.tspans[i];
    if (fs) x.setAttribute('font-size', fs);
  });
}

/** Decides, from real rendering, which labels to shrink and by how much. Pure measurement: returns the factors, applies nothing. */
async function measureResizes(fragments: string[]): Promise<Resize[]> {
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('width', String(CANVAS_W));
  svg.setAttribute('height', String(CANVAS_H));
  svg.setAttribute('viewBox', `0 0 ${CANVAS_W} ${CANVAS_H}`);
  svg.setAttribute('aria-hidden', 'true');
  svg.style.cssText = 'position:fixed;left:-99999px;top:0;visibility:hidden;pointer-events:none';
  svg.innerHTML = fragments.map((f, i) => `<g data-fit-frag="${i}">${f}</g>`).join('\n');
  document.body.appendChild(svg);
  try {
    await document.fonts.ready;       // the fragment's own @font-face (Inter) must be in before anything is measured
    const shapes = shapesOf(svg);
    const out: Resize[] = [];
    svg.querySelectorAll('g[data-fit-frag]').forEach(g => {
      const frag = Number(g.getAttribute('data-fit-frag'));
      g.querySelectorAll('text').forEach((el, textIndex) => {
        const t = el as SVGTextElement;
        if (inDefs(t) || !t.textContent?.trim()) return;
        const box0 = boxOf(t);
        const shape = uniqueShape(box0, shapes);
        if (!shape || fits(shape, box0)) return;
        const orig = { size: sizeOf(t), own: t.style.fontSize || '', tspans: [...t.querySelectorAll('tspan')].map(x => x.getAttribute('font-size')) };
        let chosen = 0;
        for (let f = 1 - STEP; f >= MIN_SCALE - 1e-9 && orig.size * f >= MIN_PX; f -= STEP) {
          scaleText(t, f, orig);
          const nb = boxOf(t);
          // the shrunk label must sit inside its old footprint, so it cannot start touching anything new
          if (fits(shape, nb) && nb.l >= box0.l - 0.6 && nb.r <= box0.r + 0.6 && nb.t >= box0.t - 0.6 && nb.b <= box0.b + 0.6) { chosen = f; break; }
        }
        restoreText(t, orig);
        if (chosen) out.push({ frag, textIndex, factor: chosen, size: orig.size * chosen });
      });
    });
    return out;
  } finally {
    svg.remove();
  }
}

/**
 * Same fragments, with overflowing labels in a unique rect / circle / ellipse made smaller.
 * Returns a Map original -> fitted for the fragments that changed (the rest are unchanged strings).
 */
export async function fitTextInFragments(fragments: string[]): Promise<Map<string, string>> {
  const result = new Map<string, string>();
  if (typeof window === 'undefined' || !fragments.length) return result;
  try {
    const resizes = await measureResizes(fragments);
    const byFrag = new Map<number, Resize[]>();
    resizes.forEach(r => byFrag.set(r.frag, [...(byFrag.get(r.frag) ?? []), r]));
    byFrag.forEach((rs, i) => {
      const fitted = applyFactors(fragments[i], rs);
      if (fitted !== fragments[i]) result.set(fragments[i], fitted);
    });
  } catch (err) {
    console.warn('[textFit] skipped, drawing shown as written:', err);
  }
  return result;
}

/** Writes the chosen sizes into a copy of one fragment. Anything that does not parse, or whose texts do not line up, is returned untouched. */
function applyFactors(fragment: string, rs: Resize[]): string {
  const doc = new DOMParser().parseFromString(`<svg xmlns="${NS}">${fragment}</svg>`, 'image/svg+xml');
  if (doc.querySelector('parsererror')) return fragment;
  const texts = doc.querySelectorAll('text');
  if (rs.some(r => !texts[r.textIndex])) return fragment;
  for (const r of rs) {
    const t = texts[r.textIndex];
    (t as SVGElement).style.setProperty('font-size', `${r.size}px`);
    t.querySelectorAll('tspan').forEach(x => {
      const fs = x.getAttribute('font-size');
      if (fs) x.setAttribute('font-size', String(parseFloat(fs) * r.factor));
    });
  }
  return [...doc.documentElement.childNodes].map(n => new XMLSerializer().serializeToString(n)).join('\n');
}
