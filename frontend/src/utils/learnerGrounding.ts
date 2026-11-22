// frontend/src/utils/learnerGrounding.ts
// Mathematical spatial grounding, coordinate transformation, and gesture classification
// for Learner Whiteboard interactions.

import type { LearnerGestureType, LearnerMatchCandidate, LearnerIntent } from '../types';
import type { ElementBounds } from './svgBounds';

/**
 * Transforms screen client coordinates to SVG canvas viewBox coordinates,
 * taking into account zoom, pan, aspect ratio, and CSS transforms.
 */
export function screenToSvgCoordinates(
  svg: SVGSVGElement,
  clientX: number,
  clientY: number
): { x: number; y: number } {
  const pt = svg.createSVGPoint();
  pt.x = clientX;
  pt.y = clientY;
  const ctm = svg.getScreenCTM();
  if (!ctm) {
    const rect = svg.getBoundingClientRect();
    const scaleX = rect.width > 0 ? 1600 / rect.width : 1;
    const scaleY = rect.height > 0 ? 900 / rect.height : 1;
    const rx = Math.max(-50, Math.min(1650, Math.round((clientX - rect.left) * scaleX)));
    const ry = Math.max(-50, Math.min(950, Math.round((clientY - rect.top) * scaleY)));
    return { x: rx, y: ry };
  }
  const transformed = pt.matrixTransform(ctm.inverse());
  // Clamp to canvas bounds with safe margin to prevent runaway negative or unbounded values
  const clampedX = Math.max(-50, Math.min(1650, Math.round(transformed.x)));
  const clampedY = Math.max(-50, Math.min(950, Math.round(transformed.y)));
  return { x: clampedX, y: clampedY };
}

/**
 * Computes axis-aligned bounding box for a series of stroke points.
 */
export function computeStrokeBBox(points: Array<{ x: number; y: number }>): {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
} {
  if (points.length === 0) {
    return { minX: 0, minY: 0, maxX: 0, maxY: 0 };
  }
  let minX = points[0].x;
  let minY = points[0].y;
  let maxX = points[0].x;
  let maxY = points[0].y;

  for (let i = 1; i < points.length; i++) {
    const p = points[i];
    if (p.x < minX) minX = p.x;
    if (p.x > maxX) maxX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.y > maxY) maxY = p.y;
  }
  return { minX, minY, maxX, maxY };
}

/**
 * Converts an array of points into a smooth SVG path data string using quadratic bezier curves.
 */
export function pointsToSvgPath(points: Array<{ x: number; y: number }>): string {
  if (points.length === 0) return '';
  if (points.length === 1) {
    return `M ${points[0].x} ${points[0].y} L ${points[0].x + 0.1} ${points[0].y + 0.1}`;
  }
  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 1; i < points.length; i++) {
    const prev = points[i - 1];
    const curr = points[i];
    const midX = (prev.x + curr.x) / 2;
    const midY = (prev.y + curr.y) / 2;
    d += ` Q ${prev.x} ${prev.y}, ${midX} ${midY}`;
  }
  const last = points.at(-1)!;
  d += ` L ${last.x} ${last.y}`;
  return d;
}

/**
 * Classifies learner stroke gesture based on geometric features.
 * - Point: very short movement or single click
 * - Circle: closed loop with balanced aspect ratio
 * - Underline: predominantly horizontal with high width/height ratio
 * - Scribble: general freehand drawing
 */
export function classifyLearnerGesture(points: Array<{ x: number; y: number }>): LearnerGestureType {
  if (points.length < 3) return 'point';

  const bbox = computeStrokeBBox(points);
  const width = bbox.maxX - bbox.minX;
  const height = bbox.maxY - bbox.minY;
  const diagonal = Math.hypot(width, height);

  if (diagonal < 18) return 'point';

  const firstPt = points[0];
  const lastPt = points.at(-1)!;
  const endpointDist = Math.hypot(firstPt.x - lastPt.x, firstPt.y - lastPt.y);

  // Circle detection: endpoints close together compared to stroke size
  const closureThreshold = Math.max(30, diagonal * 0.38);
  const aspectRatio = width / Math.max(1, height);
  if (endpointDist <= closureThreshold && width > 24 && height > 24 && aspectRatio >= 0.35 && aspectRatio <= 2.8) {
    return 'circle';
  }

  // Underline detection: wide, relatively flat
  if (width >= 40 && width / Math.max(1, height) >= 2.4) {
    return 'underline';
  }

  return 'scribble';
}

/**
 * Evaluates candidate diagram elements against a learner stroke using:
 * 1. Point Containment = (points inside element bbox) / total stroke points
 * 2. IoU Overlap = Intersection / Union of stroke BBox and element BBox
 * 3. Proximity = Normalized inverse distance between stroke center and element center
 * 4. Connecting endpoint proximity (boosts elements at start and end of linking stroke)
 *
 * Match Score = (Containment * 0.5) + (IoU * 0.3) + (Proximity * 0.2) + Enclosure/Linking Boosts
 */
export function scoreElementCandidates(
  points: Array<{ x: number; y: number }>,
  elements: Array<{ id: string; bounds: ElementBounds; label?: string }>
): LearnerMatchCandidate[] {
  if (points.length === 0 || elements.length === 0) return [];

  const strokeBBox = computeStrokeBBox(points);
  const strokeW = Math.max(1, strokeBBox.maxX - strokeBBox.minX);
  const strokeH = Math.max(1, strokeBBox.maxY - strokeBBox.minY);
  const strokeArea = strokeW * strokeH;
  const strokeCenterX = (strokeBBox.minX + strokeBBox.maxX) / 2;
  const strokeCenterY = (strokeBBox.minY + strokeBBox.maxY) / 2;

  const gesture = classifyLearnerGesture(points);
  const candidates: LearnerMatchCandidate[] = [];

  // Identify start and end segments of stroke for relationship/connecting detection
  const startPt = points[0];
  const endPt = points.at(-1)!;
  const sliceCount = Math.max(1, Math.floor(points.length * 0.3));
  const startSlice = points.slice(0, sliceCount);
  const endSlice = points.slice(-sliceCount);

  for (const el of elements) {
    const elX = el.bounds.x;
    const elY = el.bounds.y;
    const elW = Math.max(1, el.bounds.width);
    const elH = Math.max(1, el.bounds.height);
    const elArea = elW * elH;
    const elCenterX = elX + elW / 2;
    const elCenterY = elY + elH / 2;

    // 1. Point Containment: count points inside element bounding box
    let pointsInside = 0;
    for (const pt of points) {
      if (pt.x >= elX && pt.x <= elX + elW && pt.y >= elY && pt.y <= elY + elH) {
        pointsInside++;
      }
    }
    const containment = points.length > 0 ? pointsInside / points.length : 0;

    // 2. IoU Overlap
    const interMinX = Math.max(strokeBBox.minX, elX);
    const interMaxX = Math.min(strokeBBox.maxX, elX + elW);
    const interMinY = Math.max(strokeBBox.minY, elY);
    const interMaxY = Math.min(strokeBBox.maxY, elY + elH);

    const interW = Math.max(0, interMaxX - interMinX);
    const interH = Math.max(0, interMaxY - interMinY);
    const interArea = interW * interH;
    const unionArea = strokeArea + elArea - interArea;
    const iou = unionArea > 0 ? interArea / unionArea : 0;

    // 3. Center Proximity
    const dist = Math.hypot(strokeCenterX - elCenterX, strokeCenterY - elCenterY);
    const refDistance = Math.max(Math.hypot(strokeW, strokeH), Math.hypot(elW, elH), 60);
    const proximity = Math.max(0, Math.min(1, 1 - dist / refDistance));

    // 4. Boost for circle enclosure (stroke bounding box encloses element center)
    let enclosureBoost = 0;
    if (
      gesture === 'circle' &&
      elCenterX >= strokeBBox.minX &&
      elCenterX <= strokeBBox.maxX &&
      elCenterY >= strokeBBox.minY &&
      elCenterY <= strokeBBox.maxY
    ) {
      enclosureBoost = 0.22;
    }

    // 5. Endpoint linking boost: stroke begins or ends inside/near this element
    let endpointBoost = 0;
    const startInside = startSlice.some(p => p.x >= elX - 10 && p.x <= elX + elW + 10 && p.y >= elY - 10 && p.y <= elY + elH + 10);
    const endInside = endSlice.some(p => p.x >= elX - 10 && p.x <= elX + elW + 10 && p.y >= elY - 10 && p.y <= elY + elH + 10);
    if (startInside || endInside) {
      const distToClosest = Math.min(
        Math.hypot(startPt.x - elCenterX, startPt.y - elCenterY),
        Math.hypot(endPt.x - elCenterX, endPt.y - elCenterY)
      );
      if (distToClosest < Math.hypot(elW, elH) * 0.9 + 40) {
        endpointBoost = 0.20;
      }
    }

    const rawScore = containment * 0.5 + iou * 0.3 + proximity * 0.2 + enclosureBoost + endpointBoost;
    const matchScore = Number(Math.min(1, Math.max(0, rawScore)).toFixed(2));

    if (matchScore >= 0.35) {
      candidates.push({
        elementId: el.id,
        label: el.label || formatElementLabel(el.id),
        matchScore,
        containment: Number(containment.toFixed(2)),
        iou: Number(iou.toFixed(2)),
        proximity: Number(proximity.toFixed(2)),
        gesture,
      });
    }
  }

  // Sort descending by matchScore
  return candidates.sort((a, b) => b.matchScore - a.matchScore);
}

/**
 * Builds a structured LearnerIntent for single element or multi-element relationship
 * if matching score meets the interaction threshold.
 */
export function resolveLearnerIntent(
  points: Array<{ x: number; y: number }>,
  elements: Array<{ id: string; bounds: ElementBounds; label?: string }>
): LearnerIntent | null {
  const candidates = scoreElementCandidates(points, elements);
  if (candidates.length === 0 || candidates[0].matchScore < 0.38) {
    return null;
  }

  const bbox = computeStrokeBBox(points);
  const selectionCenter = {
    x: Math.round((bbox.minX + bbox.maxX) / 2),
    y: Math.round((bbox.minY + bbox.maxY) / 2),
  };

  // Multi-element relationship detection:
  // If 2nd candidate is also well-matched (>= 0.42), classify as relationship intent
  const isRelationship = candidates.length > 1 && candidates[1].matchScore >= 0.42 && candidates[0].elementId !== candidates[1].elementId;

  if (isRelationship) {
    const cand0 = candidates[0];
    const cand1 = candidates[1];
    const combinedScore = Number(((cand0.matchScore + cand1.matchScore) / 2).toFixed(2));

    return {
      intentType: 'relationship',
      selectedElementIds: [cand0.elementId, cand1.elementId],
      candidates: [cand0, cand1],
      gestureType: cand0.gesture,
      topScore: combinedScore,
      selectionCenter,
      relationshipLabel: `${cand0.label} ↔ ${cand1.label}`,
    };
  }

  // Single element intent
  return {
    intentType: 'single',
    selectedElementIds: [candidates[0].elementId],
    candidates: [candidates[0]],
    gestureType: candidates[0].gesture,
    topScore: candidates[0].matchScore,
    selectionCenter,
    relationshipLabel: candidates[0].label,
  };
}

/**
 * Clean up an element ID into a readable title if no explicit label exists.
 */
export function formatElementLabel(id: string): string {
  return id
    .replaceAll(/_/g, ' ')
    .replaceAll(/-/g, ' ')
    .split(' ')
    .map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(' ');
}
