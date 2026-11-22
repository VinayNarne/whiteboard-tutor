// frontend/src/services/roughRenderer.ts
// Converts geometric SVG shapes into hand-drawn whiteboard marker drawings
// using Rough.js per SAD §12 (roughness: 1.0–1.2).

import rough from 'roughjs';

export interface RoughifyConfig {
  roughness?: number;
  bowing?: number;
  hachureGap?: number;
  enabled?: boolean;
}

const DEFAULT_CONFIG: Required<RoughifyConfig> = {
  roughness: 1.1,    // Locked by SAD §12
  bowing: 1.2,
  hachureGap: 8,
  enabled: true,
};

const MARKER_ATTRS = ['marker-start', 'marker-mid', 'marker-end'];

/** A stable Rough.js seed (1 to 2^31-1) from a shape's own geometry (FNV-1a). */
function seedOf(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return (h >>> 1) % 2147483646 + 1;
}

/** True when the element asks for an arrowhead (or other marker) that a rebuilt Rough.js shape would lose. */
function hasMarker(node: Element): boolean {
  return MARKER_ATTRS.some(attr => {
    const value = node.getAttribute(attr);
    return !!value && value.trim() !== 'none';
  });
}

/** `stroke-dasharray="8,5"` / `"8 5"` -> [8, 5]; undefined when absent, 'none' or not a usable pattern. */
function parseDashArray(value: string | null): number[] | undefined {
  if (!value || value.trim() === 'none') return undefined;
  const dash = value.trim().split(/[\s,]+/).map(Number);
  return dash.every(n => Number.isFinite(n) && n >= 0) && dash.some(n => n > 0) ? dash : undefined;
}

/**
 * Transforms an SVG fragment string containing <rect>, <circle>, <polygon>, <line>
 * into hand-drawn sketchy Rough.js path elements while keeping <text> crisp.
 *
 * Rough.js rebuilds a shape from its geometry and the options below, so any other attribute is lost.
 * A <line> that carries a marker (arrowhead) is therefore left as the author wrote it, like a <path>
 * arrow already is; otherwise the arrowhead would silently disappear. stroke-dasharray is passed on.
 */
export function roughifySvgFragment(
  svgFragment: string,
  config: RoughifyConfig = {}
): string {
  const cfg = { ...DEFAULT_CONFIG, ...config };
  if (!cfg.enabled || typeof globalThis.window === 'undefined') {
    return svgFragment;
  }

  try {
    const parser = new DOMParser();
    const doc = parser.parseFromString(
      `<svg xmlns="http://www.w3.org/2000/svg">${svgFragment}</svg>`,
      'image/svg+xml'
    );

    const errorNode = doc.querySelector('parsererror');
    if (errorNode) {
      // If parsing fails for any reason, return the original fragment safely
      return svgFragment;
    }

    const dummySvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    const rc = rough.svg(dummySvg);

    const transformNode = (node: Element): Element | null => {
      const tag = node.tagName.toLowerCase();
      const classes = (node.getAttribute('class') || '').split(/\s+/);
      const hatch = classes.includes('hatch');   // texture proof (LP_PAINT=svg): chart shading as pencil hatching
      const id = node.getAttribute('id') || undefined;
      const stroke = node.getAttribute('stroke') || '#1e293b';
      const strokeWidth = Number.parseFloat(node.getAttribute('stroke-width') || '2') || 2;
      const fill = node.getAttribute('fill') || 'none';
      const hasFill = fill !== 'none' && fill !== 'transparent';
      const dash = parseDashArray(node.getAttribute('stroke-dasharray'));

      const commonOpts = {
        roughness: cfg.roughness,
        bowing: cfg.bowing,
        stroke,
        strokeWidth,
        fill: hasFill ? fill : undefined,
        fillStyle: hatch ? 'hachure' : 'solid',
        fillWeight: hatch ? 0.9 : 0.5,
        hachureGap: 8,
        hachureAngle: -40,
        // the same shape gets the same wobble every time: a reload or replay used to redraw every shape a little differently
        seed: seedOf(`${tag}|${['x', 'y', 'width', 'height', 'cx', 'cy', 'r', 'rx', 'ry', 'points', 'x1', 'y1', 'x2', 'y2'].map(a => node.getAttribute(a) ?? '').join(',')}`),
        ...(dash ? { strokeLineDash: dash } : {}),
      };

      let roughNode: Element | null = null;

      if (tag === 'rect') {
        const x = Number.parseFloat(node.getAttribute('x') || '0');
        const y = Number.parseFloat(node.getAttribute('y') || '0');
        const w = Number.parseFloat(node.getAttribute('width') || '0');
        const h = Number.parseFloat(node.getAttribute('height') || '0');
        if (w > 0 && h > 0) {
          roughNode = rc.rectangle(x, y, w, h, commonOpts);
        }
      } else if (tag === 'circle') {
        const cx = Number.parseFloat(node.getAttribute('cx') || '0');
        const cy = Number.parseFloat(node.getAttribute('cy') || '0');
        const r = Number.parseFloat(node.getAttribute('r') || '0');
        if (r > 0) {
          roughNode = rc.circle(cx, cy, r * 2, commonOpts);
        }
      } else if (tag === 'ellipse') {
        const cx = Number.parseFloat(node.getAttribute('cx') || '0');
        const cy = Number.parseFloat(node.getAttribute('cy') || '0');
        const rx = Number.parseFloat(node.getAttribute('rx') || '0');
        const ry = Number.parseFloat(node.getAttribute('ry') || '0');
        if (rx > 0 && ry > 0) {
          roughNode = rc.ellipse(cx, cy, rx * 2, ry * 2, commonOpts);
        }
      } else if (tag === 'line' && !hasMarker(node)) {
        const x1 = Number.parseFloat(node.getAttribute('x1') || '0');
        const y1 = Number.parseFloat(node.getAttribute('y1') || '0');
        const x2 = Number.parseFloat(node.getAttribute('x2') || '0');
        const y2 = Number.parseFloat(node.getAttribute('y2') || '0');
        roughNode = rc.line(x1, y1, x2, y2, commonOpts);
      } else if (tag === 'polygon') {
        const pointsStr = node.getAttribute('points') || '';
        const points = pointsStr
          .trim()
          .split(/[\s,]+/)
          .reduce<[number, number][]>((acc, val, idx, arr) => {
            if (idx % 2 === 0 && arr[idx + 1] !== undefined) {
              acc.push([Number.parseFloat(val), Number.parseFloat(arr[idx + 1])]);
            }
            return acc;
          }, []);
        if (points.length >= 3) {
          roughNode = rc.polygon(points, commonOpts);
        }
      } else if (tag === 'g') {
        // Clone the group and recursively transform its children
        const groupClone = doc.createElementNS('http://www.w3.org/2000/svg', 'g');
        for (const attr of node.attributes) {
          groupClone.setAttribute(attr.name, attr.value);
        }
        Array.from(node.children).forEach(child => {
          const transformed = transformNode(child);
          if (transformed) {
            groupClone.appendChild(transformed);
          } else {
            groupClone.appendChild(child.cloneNode(true));
          }
        });
        return groupClone;
      }

      if (roughNode) {
        if (id) roughNode.setAttribute('id', id);
        // Copy data attributes or class if present
        const cls = node.getAttribute('class');
        if (cls) roughNode.setAttribute('class', cls);
        // Rough.js rebuilds the shape without them: a light 18% chart shading came back solid (paint-layer proof);
        // hatching lines are drawn at full strength, their spacing does the shading
        for (const a of hatch ? ['opacity'] : ['fill-opacity', 'opacity']) {
          const v = node.getAttribute(a);
          if (v) roughNode.setAttribute(a, v);
        }
        if (classes.includes('wash')) {   // the watercolour filter roughens the fill only (the fill path has stroke="none"), not the outline
          roughNode.setAttribute('class', classes.filter(c => c !== 'wash').join(' '));
          roughNode.querySelectorAll('path[stroke="none"]').forEach(p => p.setAttribute('class', 'wash'));
        }
        return roughNode;
      }

      // Return null to keep original node (e.g. <text>, <tspan>, <path>, or custom filters)
      return null;
    };

    const rootChildren = Array.from(doc.documentElement.children);
    const serializer = new XMLSerializer();
    const resultParts: string[] = [];

    for (const child of rootChildren) {
      const transformed = transformNode(child);
      if (transformed) {
        resultParts.push(serializer.serializeToString(transformed));
      } else {
        resultParts.push(serializer.serializeToString(child));
      }
    }

    return resultParts.join('\n');
  } catch (err) {
    console.warn('[roughRenderer] Failed to roughify fragment, using raw:', err);
    return svgFragment;
  }
}
