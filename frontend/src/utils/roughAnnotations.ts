/**
 * frontend/src/utils/roughAnnotations.ts
 * Generates organic, hand-drawn Rough.js SVG nodes for the 6 annotation styles:
 *   - circle: hand-drawn elliptical loop enclosing element
 *   - underline: wavy brush stroke beneath text/card
 *   - tick: emerald-green checkmark (✓)
 *   - cross: rose-red crossmark (✗)
 *   - highlight: broad translucent underlay marker
 *   - arrow: curved pointer arrow from source to destination
 * Plus optional callout note badges.
 */

import rough from 'roughjs';
import type { ElementBounds } from './svgBounds';
import type { AnnotationPayload } from '../types';

export interface RenderedAnnotationNodes {
  underlayNode?: SVGElement;    // For highlights (Layer 1)
  annotationNode?: SVGElement;  // For marks (Layer 3)
  labelNode?: SVGElement;       // For callout notes (Layer 4)
}

export function renderRoughAnnotation(
  svgRoot: SVGSVGElement,
  payload: AnnotationPayload,
  targetBounds: ElementBounds,
  fromBounds?: ElementBounds | null
): RenderedAnnotationNodes {
  const rc = rough.svg(svgRoot);
  const result: RenderedAnnotationNodes = {};

  const baseOptions = {
    stroke: payload.color || '#f59e0b',
    strokeWidth: 2.2,
    roughness: 1.3,
    bowing: 1.5,
    seed: payload.seed || 42,
  };

  const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  g.setAttribute('id', payload.annotation_id);
  g.setAttribute('class', 'rough-annotation-mark');
  g.dataset.lifetime = payload.lifetime;

  switch (payload.style) {
    case 'circle': {
      // Loop ellipse around element bounds with double pass
      const roughNode = rc.ellipse(
        targetBounds.centerX,
        targetBounds.centerY,
        targetBounds.width + 6,
        targetBounds.height + 6,
        {
          ...baseOptions,
          strokeWidth: 2.4,
          roughness: 1.4,
          bowing: 2,
        }
      );
      g.appendChild(roughNode);
      result.annotationNode = g;
      break;
    }

    case 'underline': {
      // Wavy underline beneath element
      const y = targetBounds.bottom + 2;
      const x1 = targetBounds.left;
      const x2 = targetBounds.right;
      const roughNode = rc.curve(
        [
          [x1, y],
          [x1 + (x2 - x1) * 0.33, y + 2],
          [x1 + (x2 - x1) * 0.66, y - 1],
          [x2, y + 1],
        ],
        {
          ...baseOptions,
          strokeWidth: 3,
          roughness: 1.5,
        }
      );
      g.appendChild(roughNode);
      result.annotationNode = g;
      break;
    }

    case 'tick': {
      // Green checkmark (✓) at top-right or centered
      const size = Math.min(32, Math.max(20, targetBounds.height * 0.5));
      const startX = targetBounds.right - size * 0.8;
      const startY = targetBounds.top + size * 0.4;
      const midX = startX + size * 0.35;
      const midY = startY + size * 0.45;
      const endX = startX + size * 0.9;
      const endY = startY - size * 0.35;

      const tickG = rc.path(
        `M ${startX} ${midY - 4} L ${midX} ${midY} L ${endX} ${endY}`,
        {
          ...baseOptions,
          stroke: payload.color || '#10b981',
          strokeWidth: 3.2,
          roughness: 1.2,
        }
      );
      g.appendChild(tickG);
      result.annotationNode = g;
      break;
    }

    case 'cross': {
      // Red crossmark (✗) over target
      const pad = 6;
      const l1 = rc.line(
        targetBounds.left + pad,
        targetBounds.top + pad,
        targetBounds.right - pad,
        targetBounds.bottom - pad,
        {
          ...baseOptions,
          stroke: payload.color || '#ef4444',
          strokeWidth: 3,
          roughness: 1.4,
        }
      );
      const l2 = rc.line(
        targetBounds.right - pad,
        targetBounds.top + pad,
        targetBounds.left + pad,
        targetBounds.bottom - pad,
        {
          ...baseOptions,
          stroke: payload.color || '#ef4444',
          strokeWidth: 3,
          roughness: 1.4,
        }
      );
      g.appendChild(l1);
      g.appendChild(l2);
      result.annotationNode = g;
      break;
    }

    case 'highlight': {
      // Broad translucent highlighter underlay (Layer 1)
      const underlayG = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      underlayG.setAttribute('id', `highlight_${payload.annotation_id}`);
      underlayG.setAttribute('class', 'rough-highlight-mark');
      underlayG.dataset.lifetime = payload.lifetime;

      const hRect = rc.rectangle(
        targetBounds.left,
        targetBounds.top,
        targetBounds.width,
        targetBounds.height,
        {
          fill: payload.color || '#fbbf24',
          fillStyle: 'solid',
          stroke: 'none',
          roughness: 1.8,
          seed: payload.seed,
        }
      );
      hRect.setAttribute('opacity', '0.35');
      underlayG.appendChild(hRect);
      result.underlayNode = underlayG;
      break;
    }

    case 'arrow': {
      if (fromBounds) {
        // Compute arrow endpoints between fromBounds and targetBounds centers
        const sx = fromBounds.centerX;
        const sy = fromBounds.centerY;
        const tx = targetBounds.centerX;
        const ty = targetBounds.centerY;

        // Curve control point with slight bow
        const mx = (sx + tx) / 2 + (ty - sy) * 0.15;
        const my = (sy + ty) / 2 - (tx - sx) * 0.15;

        // Curved line
        const arrowLine = rc.curve(
          [[sx, sy], [mx, my], [tx, ty]],
          {
            ...baseOptions,
            strokeWidth: 2.6,
            roughness: 1.3,
          }
        );
        g.appendChild(arrowLine);

        // Arrow head angle
        const angle = Math.atan2(ty - my, tx - mx);
        const headLen = 14;
        const a1x = tx - headLen * Math.cos(angle - Math.PI / 6);
        const a1y = ty - headLen * Math.sin(angle - Math.PI / 6);
        const a2x = tx - headLen * Math.cos(angle + Math.PI / 6);
        const a2y = ty - headLen * Math.sin(angle + Math.PI / 6);

        const headLine1 = rc.line(tx, ty, a1x, a1y, { ...baseOptions, strokeWidth: 2.6 });
        const headLine2 = rc.line(tx, ty, a2x, a2y, { ...baseOptions, strokeWidth: 2.6 });
        g.appendChild(headLine1);
        g.appendChild(headLine2);

        result.annotationNode = g;
      }
      break;
    }
  }

  // -------------------------------------------------------------------------
  // Optional handwritten callout note badge (Layer 4)
  // -------------------------------------------------------------------------
  if (payload.note?.trim()) {
    const labelG = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    labelG.setAttribute('id', `note_${payload.annotation_id}`);
    labelG.setAttribute('class', 'rough-annotation-label');
    labelG.dataset.lifetime = payload.lifetime;

    const noteX = targetBounds.right + 10;
    const noteY = targetBounds.top - 6;

    // Background pill rect
    const textWidth = Math.max(60, payload.note.length * 8 + 16);
    const pill = rc.rectangle(noteX, noteY - 14, textWidth, 22, {
      fill: '#1e293b',
      fillStyle: 'solid',
      stroke: payload.color || '#f59e0b',
      strokeWidth: 1.5,
      roughness: 1,
      seed: payload.seed,
    });
    labelG.appendChild(pill);

    // Text element
    const textEl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    textEl.setAttribute('x', String(noteX + 8));
    textEl.setAttribute('y', String(noteY + 1));
    textEl.setAttribute('fill', '#f8fafc');
    textEl.setAttribute('font-family', 'Inter, system-ui, sans-serif');
    textEl.setAttribute('font-size', '11');
    textEl.setAttribute('font-weight', '600');
    textEl.textContent = payload.note;
    labelG.appendChild(textEl);

    result.labelNode = labelG;
  }

  return result;
}
