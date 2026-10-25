"""Feature matching (spec 2026-10-24, 'Matching').

One-to-one assignment (Hungarian) between key and generated features of the same family.
Pair cost = position error / tol + size error / tol + a type-mismatch constant; a pair farther
than gate = min(gate_tol_multiple x tol, gate_part_fraction x part size) never matches, nor does
a pair whose axes (or plane normals) are not parallel: a hole drilled from the wrong face is a
missing feature plus an extra one. Base body and hole patterns have no family (not matched here).
Both inputs are expected in the same frame (bench.align has been applied to the generated key)."""
from __future__ import annotations

import math
from typing import Callable, Optional

import numpy as np
from scipy.optimize import linear_sum_assignment

from bench.features import HOLE_TYPES, Feature
from bench.score_config import Config

_FAMILY = {**{t: "hole" for t in HOLE_TYPES}, "bore": "round", "turned_diameter": "round", "boss": "round",
           "slot": "slot", "flat": "planar", "pocket_step": "planar", "chamfer": "edge", "fillet": "edge"}
INF = 1e9          # an infeasible pair (finite: the solver needs it; sums stay exact enough)


def family(t: str) -> Optional[str]:
    return _FAMILY.get(t)


def _parallel(a, b) -> bool:
    return abs(abs(float(np.dot(a, b))) - 1.0) < 1e-6


def position_error(a: Feature, b: Feature) -> float:
    """Distance between start points. Only when both features are thru is the offset along the
    axis ignored (a thru hole has no start face); otherwise the start point is the only record
    of the face a feature is cut from (axes carry a canonical sign), so it counts in full.
    For planes, the offset difference. inf when axes or normals are not parallel or the two
    features locate differently (centre vs plane). 0 when neither has a location."""
    if a.center is not None and b.center is not None:
        if a.axis is not None and b.axis is not None and not _parallel(a.axis, b.axis):
            return math.inf
        d = np.asarray(a.center, float) - np.asarray(b.center, float)
        if a.axis is not None and a.thru and b.thru:
            ax = np.asarray(a.axis, float)
            d = d - ax * float(d @ ax)
        return float(np.linalg.norm(d))
    if a.normal is not None and b.normal is not None:
        if not _parallel(a.normal, b.normal):
            return math.inf
        s = 1.0 if float(np.dot(a.normal, b.normal)) > 0 else -1.0
        return abs(float(a.offset or 0.0) - s * float(b.offset or 0.0))
    if a.center is None and a.normal is None and b.center is None and b.normal is None:
        return 0.0
    return math.inf


def size_error(a: Feature, b: Feature) -> Optional[float]:
    """Largest difference over the size quantities both features have (diameters, extents);
    None when they share none. Type-specific quantities (a counterbore's cbore_d) are compared
    only when both have them: a missing counterbore is a type error, not a size error."""
    errs = [abs(x - y) for x, y in ((a.d, b.d), (a.cbore_d, b.cbore_d), (a.csink_d, b.csink_d))
            if x is not None and y is not None]
    if a.size and b.size:
        sa, sb = (a.size, b.size) if len(a.size) == len(b.size) else (sorted(a.size), sorted(b.size))
        errs.append(max(abs(x - y) for x, y in zip(sa, sb)))
    return max(errs) if errs else None


def match(key: list[Feature], gen: list[Feature], part_size: float,
          tol_of: Callable[[Feature, str], float], cfg: Config):
    """-> (pairs [(key_id, gen_id)], missing key ids, extra gen ids)."""
    pairs, missing, extra = [], [], []
    for fam in sorted({family(f.type) for f in key + gen} - {None}):
        ks = [f for f in key if family(f.type) == fam]
        gs = [g for g in gen if family(g.type) == fam]
        if not ks or not gs:
            missing += [f.id for f in ks]
            extra += [g.id for g in gs]
            continue
        cost = np.full((len(ks), len(gs)), INF)
        for i, f in enumerate(ks):
            tp, ts = tol_of(f, "position"), tol_of(f, "size")
            gate = min(cfg.gate_tol_multiple * tp, cfg.gate_part_fraction * part_size)
            for j, g in enumerate(gs):
                pe = position_error(f, g)
                if pe > gate * (1 + 1e-9):
                    continue
                se = size_error(f, g) or 0.0
                cost[i, j] = pe / tp + se / ts + (0.0 if f.type == g.type else cfg.type_mismatch_cost)
        rows, cols = linear_sum_assignment(cost)
        used_k, used_g = set(), set()
        for r, c in zip(rows, cols):
            if cost[r, c] < INF / 2:
                pairs.append((ks[r].id, gs[c].id))
                used_k.add(r)
                used_g.add(c)
        missing += [f.id for i, f in enumerate(ks) if i not in used_k]
        extra += [g.id for j, g in enumerate(gs) if j not in used_g]
    return pairs, missing, extra
