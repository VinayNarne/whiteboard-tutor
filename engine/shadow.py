"""
engine/shadow.py  --  LOG-ONLY shadow validator hook (docs/SHADOW_VALIDATOR.md).

For every drawing that reaches the draw pipeline's geometry step, this records what the PROPOSED shape-level validator (engine/shape_model.py) would have
decided, next to what the EXISTING checks decide. It never rejects, changes or reorders anything: the draw handler ignores its result, any error is
caught and logged, and a time limit (TIMEOUT_S) bounds the delay it can add. The existing validator stays authoritative.

  * Switch off:  LP_SHADOW_VALIDATOR=0   (also off, false, no). On by default while data is being collected.
  * Overhead:    every event carries `ms` (compute time in a worker thread) and `wait_ms` (the time the draw actually waited for it).
  * Content:     only collision categories, bounding boxes, element ids and counts are logged: no label text, no SVG source.
  * Advisory:    label overflow, a connector or arrow head over a label and connectors on top of each other are recorded as advisories and never count towards the verdict.
  * Connector and text: `connector_text` in the record is a second, z-order-aware look at connectors over text (engine/connector_text.py): a line hidden under its own opaque
                label box is not reported, body and arrow head are counted apart, ambiguous cases are kept apart from definite ones. It is diagnostic only, never part of a verdict,
                and its own failure is caught inside `compute` (`connector_text_error`) so the rest of the record is still written.
"""
import asyncio
import os
import time
from typing import Optional

from core.events import EngineEvent
from core.log import get_logger
from engine import connector_text as ct
from engine import shape_model as sm
from engine.validator import check_overlap, validate_geometry

logger = get_logger("engine")

ENV = "LP_SHADOW_VALIDATOR"
TIMEOUT_S = 0.5          # the longest a draw can be made to wait for the shadow check; after that the check is abandoned (logged as skipped)
MAX_SHAPES = 600         # a page with more shapes than this is not checked (cost grows with the square of the shape count)
MAX_REASONS = 6          # reasons written per event (the counts are complete)
MAX_CT_ITEMS = 4         # connector-versus-text findings written per event (the counts are complete)


def enabled() -> bool:
    return os.getenv(ENV, "1").strip().lower() not in ("0", "off", "false", "no")


def _key(s: sm.Shape) -> str:
    x0, y0, x1, y1 = s.bbox
    return f"{s.kind}{f'[{len(s.text)}]' if s.kind == 'text' else ''}@{x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f}"      # a label is logged by its length, never its text


def _reason(c: sm.Collision) -> dict:
    r = {"kind": c.kind, "a": _key(c.a), "ae": c.a.element}
    if c.b is not None:
        r.update({"b": _key(c.b), "be": c.b.element})
    return r


def compute(existing_svg: Optional[str], styled_fragment: str, element_id: str) -> dict:
    """Pure and synchronous (runs in a worker thread): the shadow record for one drawing. May raise; `record` catches everything."""
    t0 = time.perf_counter()
    old = sm.extract_shapes(existing_svg or "")
    new = sm.extract_shapes(styled_fragment, start_index=len(old))
    rec = {"element_id": element_id, "shapes_new": len(new), "shapes_page": len(old)}
    geo = validate_geometry(styled_fragment, existing_svg=existing_svg)       # the same two checks the draw handler applies next, for the paired verdict
    clash = check_overlap(existing_svg, styled_fragment) if geo["valid"] else None
    rec["existing"] = "reject" if (not geo["valid"] or clash) else "accept"
    rec["existing_reason"] = "geometry" if not geo["valid"] else "overlap" if clash else ""
    if len(old) + len(new) > MAX_SHAPES:
        rec.update({"proposed": "skipped", "skipped": "too_many_shapes", "differs": False})
    else:
        mine = [c for c in sm.find_collisions(old + new) if c.a.index >= len(old) or (c.b is not None and c.b.index >= len(old))]
        rej = [c for c in mine if c.severity == "reject"]
        adv = [c for c in mine if c.severity != "reject"]
        roles: dict = {}
        for sh in new:                                           # what kind of drawing this is (set by find_collisions): for coverage reports, no content
            roles[sh.role or sh.kind] = roles.get(sh.role or sh.kind, 0) + 1
        rec["roles"] = roles
        rec["proposed"] = "reject" if rej else "accept"
        rec["differs"] = rec["proposed"] != rec["existing"]
        rec["reject_kinds"] = _count(rej)
        rec["advisory_kinds"] = _count(adv)
        rec["reasons"] = [_reason(c) for c in rej[:MAX_REASONS]]
        rec["reasons_total"] = len(rej)
        rec["advisories"] = [_reason(c) for c in adv[:3]]
        try:                                                     # diagnostic only: its failure must not cost the rest of the record
            rec["connector_text"] = ct_record(ct.analyse(old + new, ct.parse_markers((existing_svg or "") + styled_fragment), charged_from=len(old)))
        except Exception as e:
            rec["connector_text_error"] = type(e).__name__
    rec["ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return rec


def _ct_item(f: ct.Finding) -> dict:
    """One connector-versus-text finding: kind, certainty, a fixed reason code, the amount (px of line, px2 of head, or share of the head), the two shapes and their element ids. No label text."""
    return {"kind": f.kind, "certainty": f.certainty, "why": f.why, "n": round(f.amount, 2), "a": _key(f.connector), "ae": f.connector.element, "b": _key(f.label), "be": f.label.element}


def ct_record(rep: ct.Report) -> dict:
    definite = [f for f in rep.findings if f.certainty == "definite"]
    ambiguous = [f for f in rep.findings if f.certainty != "definite"]
    out = {"body": sum(f.kind == "connector_body_over_text" for f in definite), "head": sum(f.kind == "arrowhead_over_text" for f in definite),
           "head_covered": sum(f.kind == "arrowhead_covered_by_label" for f in definite), "ambiguous": len(ambiguous), "hidden": len(rep.hidden),
           "connectors": rep.connectors, "labels": rep.labels}
    if rep.unsupported:
        out["unsupported"] = dict(rep.unsupported)
    out["items"] = [_ct_item(f) for f in (definite + ambiguous)[:MAX_CT_ITEMS]]
    return out


def _count(cs) -> dict:
    out: dict = {}
    for c in cs:
        out[c.kind] = out.get(c.kind, 0) + 1
    return out


async def record(existing_svg: Optional[str], styled_fragment: str, element_id: str, page_id: str) -> None:
    """Log the shadow record for one drawing. Returns None always; never raises (apart from task cancellation) and never changes what the caller does."""
    if not enabled():
        return
    t0 = time.perf_counter()
    try:
        loop = asyncio.get_running_loop()
        rec = await asyncio.wait_for(loop.run_in_executor(None, compute, existing_svg, styled_fragment, element_id), TIMEOUT_S)
    except asyncio.TimeoutError:
        logger.info(EngineEvent.SHADOW_SKIPPED, f"Shadow check of '{element_id}' abandoned after {TIMEOUT_S}s",
                    data={"element_id": element_id, "page_id": page_id, "reason": "timeout", "wait_ms": round((time.perf_counter() - t0) * 1000, 1)})
        return
    except Exception as e:                                       # a bug in the shadow check must never reach the drawing
        logger.warn(EngineEvent.SHADOW_FAILED, f"Shadow check of '{element_id}' failed: {type(e).__name__}",
                    data={"element_id": element_id, "page_id": page_id, "error": f"{type(e).__name__}: {str(e)[:120]}"})
        return
    rec["page_id"] = page_id
    rec["wait_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    logger.info(EngineEvent.SHADOW_VALIDATED, f"Shadow: existing {rec['existing']}, proposed {rec['proposed']}"
                + (f" ({', '.join(rec['reject_kinds'])})" if rec.get("reject_kinds") else ""), data=rec)
