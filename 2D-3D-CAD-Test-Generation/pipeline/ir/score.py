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
from typing import Any, Optional

import cadquery as cq

from pipeline.ir.compile_cadquery import build
from pipeline.ir.model import BuildPlan

HOLE_TOL = 0.005  # drawing units: 3-place inch tolerance class


# Exact 90-degree rotations that realise the 6 axis permutations (signs come from the mirrors).
_PERMS = {"xyz": [], "yxz": [("Z", 90)], "xzy": [("X", 90)], "zyx": [("Y", 90)],
          "yzx": [("Z", 90), ("X", 90)], "zxy": [("X", 90), ("Z", 90)]}
_AXV = {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}


def _ext(bb) -> tuple[float, float, float]:
    return (bb.xlen, bb.ylen, bb.zlen)


def _align_candidates(src: cq.Shape, dst: cq.Shape):
    """src placed on dst's bbox center over all 48 signed axis permutations, skipping
    any whose bbox extents can't match (a plate on its edge, a shaft along the wrong axis).
    Only exact rotations and mirrors are used: transformGeometry converts to NURBS and
    drifts about 1% in volume. SolidWorks exports land in model axes that differ from
    the IR frame (this template's Front plane is model YZ), hence the permutations."""
    sb, db = src.BoundingBox(), dst.BoundingBox()
    sc = cq.Vector((sb.xmin + sb.xmax) / 2, (sb.ymin + sb.ymax) / 2, (sb.zmin + sb.zmax) / 2)
    dc = cq.Vector((db.xmin + db.xmax) / 2, (db.ymin + db.ymax) / 2, (db.zmin + db.zmax) / 2)
    centered = src.translate(-sc)
    dext = _ext(db)
    for name, rots in _PERMS.items():
        base = centered
        for axis, ang in rots:
            base = base.rotate(cq.Vector(0, 0, 0), cq.Vector(*_AXV[axis]), ang)
        bext = _ext(base.BoundingBox())
        if any(abs(a - b) > 0.05 * max(b, 1e-9) for a, b in zip(bext, dext)):
            continue
        for fx, fy, fz in itertools.product((1, -1), repeat=3):
            s = base
            for flip, plane in ((fx, "YZ"), (fy, "XZ"), (fz, "XY")):
                if flip < 0:
                    s = s.mirror(plane, (0, 0, 0))
            yield (name, fx, fy, fz), s.translate(dc)


def aligned(a: cq.Shape, b: cq.Shape, key) -> cq.Shape:
    """``a`` placed on ``b`` by the alignment ``key`` that iou() returned."""
    return next(s for k, s in _align_candidates(a, b) if k == key)


CLOCK_ANGLES = sorted({round(360.0 / n * i, 6) % 360 for n in range(2, 25) for i in range(1, n)})


def turned_axis(s: cq.Shape, tol: float = 0.01) -> Optional[int]:
    """Index (0/1/2) of the bbox axis whose two cross extents agree within 1% (a turned part's
    axis; slots and flats nibble the outline: 4C1229 is 67.99 x 68.28), or None."""
    e = _ext(s.BoundingBox())
    for i in range(3):
        j, k = [n for n in range(3) if n != i]
        if abs(e[j] - e[k]) <= tol * max(e[j], e[k], 1e-9):
            return i
    return None


def clocked(a: cq.Shape, b: cq.Shape, angles=None) -> tuple[float, float, cq.Shape]:
    """Best IoU of an ALIGNED ``a`` against ``b`` over rotations about the turned axis.
    Clocking about the axis (where the first of 3 slots points) is an orientation choice,
    not a placement error (4C1229: our slots at -90/30/150 deg, MTI's at 180/+-60).
    Returns (iou, angle in degrees, rotated a); angle 0 when ``b`` isn't round."""
    ax = turned_axis(b)
    va, vb = a.Volume(), b.Volume()

    def score(c):
        inter = c.intersect(b).Volume()
        return inter / (va + vb - inter)

    best = (score(a), 0.0, a)
    if ax is None:
        return best
    bb = b.BoundingBox()
    ctr = cq.Vector((bb.xmin + bb.xmax) / 2, (bb.ymin + bb.ymax) / 2, (bb.zmin + bb.zmax) / 2)
    d = cq.Vector(*[1.0 if n == ax else 0.0 for n in range(3)])
    for ang in (angles if angles is not None else CLOCK_ANGLES):
        c = a.rotate(ctr, ctr + d, ang)
        try:
            v = score(c)
        except Exception:
            continue
        if v > best[0]:
            best = (v, ang, c)
    return best


def surface_deviation(a: cq.Shape, b: cq.Shape, samples: int = 400) -> dict[str, float]:
    """Symmetric surface distance between two ALIGNED solids, in their units: points on each
    surface (tessellation vertices, evenly subsampled) to the other surface. ``max`` is a
    sampled Hausdorff distance. IoU punishes thin parts: a 0.9 mm offset on a 1.5 mm sheet
    wall reads as IoU 0.29 (A00161E), while this reads 0.9 mm, comparable to a tolerance."""
    def pts(s: cq.Shape) -> list[cq.Vector]:
        bb = s.BoundingBox()
        verts = s.tessellate(max(bb.xlen, bb.ylen, bb.zlen) / 500)[0]
        step = max(1, len(verts) // samples)
        return verts[::step]

    def dists(src: cq.Shape, dst: cq.Shape) -> list[float]:
        skin = cq.Compound.makeCompound(dst.Faces())   # the surface: a point inside a solid is at 0
        return [skin.distance(cq.Vertex.makeVertex(p.x, p.y, p.z)) for p in pts(src)]

    d = dists(a, b) + dists(b, a)
    return {"max": max(d), "mean": sum(d) / len(d)}


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
