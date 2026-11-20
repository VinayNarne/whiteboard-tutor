/**
 * PaintLayer — natural-media paint (p5.brush, MIT) under the lesson board's SVG (proof, server flag LP_PAINT=1).
 *
 * The SVG stays the source of truth: text, ids, pointing, screen readers. Blocks carry paint recipes (<desc class="paint">{json}</desc>,
 * board coordinates and a seed, engine/scene.py paint()), and this layer repaints them on one WebGL2 canvas: sharp at any zoom (repainted
 * once the camera settles; moved with a CSS transform meanwhile) and identical on every replay (same seed). Painted shapes keep their SVG
 * fill, marked paint-fill; it is hidden (.painting) only once the paint is on screen, so without WebGL2 the board looks as before.
 */
import { useCallback, useEffect, useRef, type RefObject } from 'react';
import * as brush from 'p5.brush/standalone';
import type { Box } from '../../utils/boardCamera';

interface Recipe { kind: 'wash' | 'hatch'; points: [number, number][]; color: string; seed: number }

/** The paint recipes on the board, in board order; anything malformed is skipped. */
export function readRecipes(root: ParentNode): Recipe[] {
  const out: Recipe[] = [];
  root.querySelectorAll('desc.paint').forEach(d => {
    try {
      const r = JSON.parse(d.textContent || '');
      const ok = (r.kind === 'wash' || r.kind === 'hatch') && Array.isArray(r.points) && r.points.length >= 3
        && r.points.every((p: unknown) => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite))
        && typeof r.color === 'string' && /^#[0-9a-f]{6}$/i.test(r.color) && Number.isFinite(r.seed);
      if (ok) out.push(r);
    } catch { /* not a recipe */ }
  });
  return out;
}

/** The viewBox letterboxed into the SVG box (preserveAspectRatio meet): scale and offset in CSS pixels. */
const fit = (v: Box, cw: number, ch: number) => {
  const s = Math.min(cw / v.w, ch / v.h);
  return { s, ox: (cw - v.w * s) / 2, oy: (ch - v.h * s) / 2 };
};

export function PaintLayer({ svgRef, view, version, paper }: { svgRef: RefObject<SVGSVGElement | null>; view: Box; version: string; paper: string }) {
  const holder = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const painted = useRef<{ view: Box; s: number; ox: number; oy: number } | null>(null);
  const viewRef = useRef(view);
  viewRef.current = view;
  const timer = useRef(0);
  const broken = useRef(false);

  const paintNow = useCallback(() => {
    const svg = svgRef.current, el = holder.current;
    if (!svg || !el || broken.current) return;
    const recipes = readRecipes(svg);
    const cw = svg.clientWidth, ch = svg.clientHeight;
    if (!recipes.length || !cw || !ch) {
      svg.classList.remove('painting');
      if (canvas.current) canvas.current.style.visibility = 'hidden';
      painted.current = null;
      return;
    }
    try {
      const density = Math.min(2, window.devicePixelRatio || 1);
      if (!canvas.current) {   // one canvas for the session: browsers allow only a few WebGL contexts
        canvas.current = brush.createCanvas(cw, ch, { parent: el, pixelDensity: density });
        brush.angleMode(brush.DEGREES);
      } else if (canvas.current.width !== Math.round(cw * density) || canvas.current.height !== Math.round(ch * density)) {
        canvas.current.width = Math.round(cw * density);
        canvas.current.height = Math.round(ch * density);
        canvas.current.style.width = `${cw}px`;
        canvas.current.style.height = `${ch}px`;
      }
      brush.load(canvas.current);
      const v = viewRef.current, { s, ox, oy } = fit(v, cw, ch);
      brush.clear(paper);   // pigment needs paper: a cleared (transparent) canvas came out opaque white over the board
      brush.push();
      brush.translate(-cw / 2, -ch / 2);   // the WebGL origin is the centre
      brush.translate(ox, oy);
      brush.scale(s);
      brush.translate(-v.x, -v.y);
      for (const r of recipes) {
        brush.seed(r.seed);
        brush.noiseSeed(r.seed);
        brush.noStroke();
        if (r.kind === 'wash') {
          brush.noHatch();
          brush.fill(r.color, 45);   // light enough that grey detail text on top stays readable (110 was too strong, live)
          brush.fillBleed(0.18);
          brush.fillTexture(0.5, 0.6);
          brush.polygon(r.points);
          brush.noFill();
        } else {
          brush.noFill();
          brush.hatch(14, 45, { rand: 0.1 });   // spaced and thin: at 7 and weight 1 the lines merged into a solid block (live)
          brush.hatchStyle('2H', r.color, 0.5);
          brush.polygon(r.points);
          brush.noHatch();
        }
      }
      brush.pop();
      brush.render();
      canvas.current.style.transform = '';
      canvas.current.style.visibility = 'visible';
      painted.current = { view: v, s, ox, oy };
      svg.classList.add('painting');                 // now the SVG fills underneath can give way to the paint
    } catch (e) {
      broken.current = true;                         // no WebGL2, or the library failed: the SVG fills stay
      svg.classList.remove('painting');
      if (canvas.current) canvas.current.style.visibility = 'hidden';
      console.warn('[paint] off:', e);
    }
  }, [svgRef, paper]);

  // The camera moves every frame: shift and scale the last painting with CSS (cheap), then repaint sharp once it settles
  useEffect(() => {
    const p = painted.current, svg = svgRef.current, c = canvas.current;
    if (p && svg && c) {
      const { s, ox, oy } = fit(view, svg.clientWidth, svg.clientHeight);
      const k = s / p.s;
      const tx = ox - view.x * s - (p.ox - p.view.x * p.s) * k, ty = oy - view.y * s - (p.oy - p.view.y * p.s) * k;
      c.style.transform = `translate(${tx}px, ${ty}px) scale(${k})`;
    }
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(paintNow, 220);
  }, [view, version, paintNow, svgRef]);

  useEffect(() => {
    const again = () => { window.clearTimeout(timer.current); timer.current = window.setTimeout(paintNow, 220); };
    window.addEventListener('resize', again);
    return () => { window.removeEventListener('resize', again); window.clearTimeout(timer.current); };
  }, [paintNow]);

  return <div ref={holder} className="wb-paint" aria-hidden="true" />;
}
