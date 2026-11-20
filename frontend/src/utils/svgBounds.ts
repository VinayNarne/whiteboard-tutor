/**
 * frontend/src/utils/svgBounds.ts
 * Transform-aware bounding box measurement for SVG elements within a root SVG coordinate space.
 * Uses getScreenCTM() matrix inversion to properly account for nested transforms, scaling, and panning.
 */

export interface ElementBounds {
  x: number;
  y: number;
  width: number;
  height: number;
  centerX: number;
  centerY: number;
  left: number;
  right: number;
  top: number;
  bottom: number;
}

export function getElementBounds(
  rootSvg: SVGSVGElement | null,
  elementId: string,
  padding: number = 8,
  minSize: number = 24
): ElementBounds | null {
  if (!rootSvg) return null;

  const targetEl = rootSvg.querySelector(`[id="${elementId}"]`) as SVGGraphicsElement | null;
  if (!targetEl || typeof targetEl.getBBox !== 'function') return null;

  try {
    const b = targetEl.getBBox();
    const rootScreen = rootSvg.getScreenCTM();
    const elScreen = targetEl.getScreenCTM();
    const m = rootScreen && elScreen ? rootScreen.inverse().multiply(elScreen) : targetEl.getCTM();

    const pt = (px: number, py: number) => {
      if (rootSvg.createSVGPoint && m) {
        const p = rootSvg.createSVGPoint();
        p.x = px;
        p.y = py;
        return p.matrixTransform(m);
      }
      if (m) {
        return { x: m.a * px + m.c * py + m.e, y: m.b * px + m.d * py + m.f };
      }
      return { x: px, y: py };
    };

    const p1 = pt(b.x, b.y);
    const p2 = pt(b.x + b.width, b.y);
    const p3 = pt(b.x + b.width, b.y + b.height);
    const p4 = pt(b.x, b.y + b.height);

    const minX = Math.min(p1.x, p2.x, p3.x, p4.x);
    const maxX = Math.max(p1.x, p2.x, p3.x, p4.x);
    const minY = Math.min(p1.y, p2.y, p3.y, p4.y);
    const maxY = Math.max(p1.y, p2.y, p3.y, p4.y);

    let w = maxX - minX;
    let h = maxY - minY;
    let x = minX;
    let y = minY;

    // Minimum size clamp for tiny/text nodes
    if (w < minSize) {
      x -= (minSize - w) / 2;
      w = minSize;
    }
    if (h < minSize) {
      y -= (minSize - h) / 2;
      h = minSize;
    }

    // Apply padding
    const rx = x - padding;
    const ry = y - padding;
    const rw = w + padding * 2;
    const rh = h + padding * 2;

    return {
      x: rx,
      y: ry,
      width: rw,
      height: rh,
      centerX: rx + rw / 2,
      centerY: ry + rh / 2,
      left: rx,
      right: rx + rw,
      top: ry,
      bottom: ry + rh,
    };
  } catch (err) {
    console.warn(`[svgBounds] Failed measuring element '${elementId}':`, err);
    return null;
  }
}
