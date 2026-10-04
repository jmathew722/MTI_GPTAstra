"""Score a planned part against a golden (hand-checked) plan of the same drawing.

Both plans are compiled with the CadQuery reference compiler. A planner may legitimately
choose the other end face as z = 0, or swap x/y on a plate, so the candidate solid is
aligned to the golden one by bounding box over all axis flips and x/y swaps. The best
alignment is kept, and the scores are:

* ``iou``: volume(A ∩ B) / volume(A ∪ B) of the aligned solids. Placement errors
  (a hole in the wrong place, a missing slot) lower it.
* ``volume_err``: relative volume error.
* ``bbox_err``: max relative error of the sorted bounding-box extents.
* ``holes``: the multiset of measured hole diameters, matched within tolerance.
* ``unresolved`` / ``gate1_errors``: how honest and how well-formed the plan is.

This is a dev-set tool. The benchmark's headline scores (PRD C2) use MTI reference
STEP, not golden plans.
"""
from __future__ import annotations

import itertools
from typing import Any

import cadquery as cq

from pipeline.ir.compile_cadquery import build
from pipeline.ir.model import BuildPlan

HOLE_TOL = 0.005  # drawing units: 3-place inch tolerance class


def _align_candidates(src: cq.Shape, dst: cq.Shape):
    """src transformed so its bbox sits on dst's bbox, over flips and x/y swaps."""
    sb, db = src.BoundingBox(), dst.BoundingBox()
    sc = cq.Vector((sb.xmin + sb.xmax) / 2, (sb.ymin + sb.ymax) / 2, (sb.zmin + sb.zmax) / 2)
    dc = cq.Vector((db.xmin + db.xmax) / 2, (db.ymin + db.ymax) / 2, (db.zmin + db.zmax) / 2)
    centered = src.translate(-sc)
    for swap in (False, True):
        base = centered.rotate(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), 90) if swap else centered
        for fx, fy, fz in itertools.product((1, -1), repeat=3):
            # exact mirrors (transformGeometry would convert to NURBS and drift ~1% in volume)
            s = base
            for flip, plane in ((fx, "YZ"), (fy, "XZ"), (fz, "XY")):
                if flip < 0:
                    s = s.mirror(plane, (0, 0, 0))
            yield (swap, fx, fy, fz), s.translate(dc)


def iou(a: cq.Shape, b: cq.Shape) -> tuple[float, Any]:
    va = b.Volume()
    best = (0.0, None)
    for key, cand in _align_candidates(a, b):
        try:
            inter = cand.intersect(b).Volume()
        except Exception:
            continue
        union = cand.Volume() + va - inter
        if union > 0 and inter / union > best[0]:
            best = (inter / union, key)
    return best


def _holes(fmap: dict) -> list[float]:
    return sorted(h["d"] for hs in fmap.get("holes", {}).values() for h in hs if h.get("measured"))


def match_holes(cand: list[float], gold: list[float]) -> tuple[int, int, int]:
    """(matched, missing, extra) by diameter within HOLE_TOL."""
    left = list(cand)
    matched = 0
    for d in gold:
        hit = next((c for c in left if abs(c - d) <= HOLE_TOL), None)
        if hit is not None:
            left.remove(hit)
            matched += 1
    return matched, len(gold) - matched, len(left)


def score(plan: BuildPlan, dims: dict[str, float], golden: BuildPlan, golden_dims: dict[str, float],
          reference_ids: frozenset[str] = frozenset()) -> dict[str, Any]:
    findings = plan.check(dims, reference_ids)
    out: dict[str, Any] = {
        "features": len(plan.features),
        "unresolved": [f.feature for f in findings if f.code == "unresolved"],
        "gate1_errors": [f"{f.code}:{f.feature}" for f in findings if f.severity == "error" and f.code != "unresolved"],
    }
    g = build(golden, golden_dims, strict=False)
    try:
        c = build(plan, dims, strict=False)
    except Exception as e:  # the plan can't compile at all
        out.update(compiled=False, error=f"{type(e).__name__}: {e}"[:300], iou=0.0)
        return out
    gm, cm = g.model, c.model
    ka, kb = cm.k, gm.k
    if abs(ka - kb) > 1e-12:  # different units: scale the candidate to the golden's mm
        out["units_mismatch"] = True
    value, key = iou(cm.solid, gm.solid)
    gv, cv = g.feature_map["volume"], c.feature_map["volume"]
    gext = sorted(g.feature_map["bbox"][i + 3] - g.feature_map["bbox"][i] for i in range(3))
    cext = sorted(c.feature_map["bbox"][i + 3] - c.feature_map["bbox"][i] for i in range(3))
    m, miss, extra = match_holes(_holes(c.feature_map), _holes(g.feature_map))
    out.update(
        compiled=True, iou=round(value, 4), alignment=key,
        volume_err=round((cv - gv) / gv, 4),
        bbox_err=round(max(abs(a - b) / b for a, b in zip(cext, gext)), 4),
        holes_matched=m, holes_missing=miss, holes_extra=extra, holes_expected=m + miss,
        cq_skipped=list(c.feature_map.get("skipped", {})),
    )
    return out
