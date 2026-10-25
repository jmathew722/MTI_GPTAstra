"""Rigid fit of a generated key onto the answer key (spec 2026-10-24, 'Architecture: align').

Keys live in their own bbox-min frames (keygen). A pose = one of the 24 proper axis-aligned
rotations applied about the origin, then the shift that puts the rotated bounding box back at
the origin, then a translation refined from paired features.

Positions are referenced from the part's own body, so a translation beyond bbox alignment is
justified only by an envelope difference: per axis, the shift is bounded to
[min(0, d) - tol, max(0, d) + tol] with d = target envelope - rotated envelope. Equal envelopes
therefore mean no shift, and a uniform offset of every feature (a datum error) is scored, not
hidden. Within that bound the shift is a consensus, not a mean: every paired feature proposes
the shift that would put it exactly on its partner, and the admissible shift that brings the most
pairs within tolerance wins (ties: the smallest shift, so plain bbox alignment is the default).
So one misplaced hole never drags the others out of tolerance, and extra stock on the low side
of an axis (every feature offset by that stock) is shifted back.

The rotation is chosen by a cost function: by default a geometric one (unpaired features, pair
distances, envelope mismatch); the scorer passes its own (minus the part score), so the pose is
always the one that scores best and a symmetric part loses nothing to an equivalent pose."""
from __future__ import annotations

import copy
import itertools
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from bench.features import Feature, Key

_FALLBACK_TOL = {"inch": 0.005, "mm": 0.1}
_SIZED_PLANAR = ("flat", "pocket_step", "base_body")


def _rotations() -> list[np.ndarray]:
    out = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            R = np.zeros((3, 3))
            for row, (col, s) in enumerate(zip(perm, signs)):
                R[row, col] = s
            if round(np.linalg.det(R)) == 1:
                out.append(R)
    return out


ROTATIONS = _rotations()            # ROTATIONS[0] is the identity


def _canon(v: np.ndarray) -> np.ndarray:
    """Direction with its first non-zero component positive (keygen's convention)."""
    for c in v:
        if abs(c) > 1e-9:
            return v if c > 0 else -v
    return v


def _clean(v) -> list[float]:
    return [float(x) + 0.0 for x in v]          # + 0.0 turns -0.0 into 0.0


def transform(key: Key, R: np.ndarray, t=(0.0, 0.0, 0.0)) -> Key:
    """A copy of `key` rotated by R about the origin, shifted so the rotated bbox starts at the
    origin again, then translated by t. Points, axes (canonical sign), planes n.x = o (canonical
    normal sign, offset recomputed) and axis-aligned extents all move consistently."""
    k = copy.deepcopy(key)
    R = np.asarray(R, float)
    env = np.asarray(key.envelope if key.envelope and len(key.envelope) == 3 else (0.0, 0.0, 0.0), float)
    corners = np.array([[x, y, z] for x in (0, env[0]) for y in (0, env[1]) for z in (0, env[2])])
    rc = corners @ R.T
    shift = -rc.min(axis=0) + np.asarray(t, float)
    if key.envelope and len(key.envelope) == 3:
        k.envelope = _clean(rc.max(axis=0) - rc.min(axis=0))
    absR = np.abs(R)
    for f in k.features:
        if f.center is not None:
            f.center = _clean(R @ np.asarray(f.center, float) + shift)
        if f.axis is not None:
            f.axis = _clean(_canon(R @ np.asarray(f.axis, float)))
        if f.normal is not None:
            n = R @ np.asarray(f.normal, float)
            point = n * float(f.offset or 0.0) / float(n @ n) + shift      # a point on the moved plane
            cn = _canon(n)
            f.normal, f.offset = _clean(cn), float(cn @ point) + 0.0
        if f.size is not None and len(f.size) == 3 and f.type in _SIZED_PLANAR:
            f.size = _clean(absR @ np.asarray(f.size, float))              # extents per axis
    return k


@dataclass
class Fit:
    R: np.ndarray
    t: np.ndarray
    cost: float

    def apply(self, key: Key) -> Key:
        return transform(key, self.R, self.t)


def _parallel(a, b) -> bool:
    return abs(abs(float(np.dot(a, b))) - 1.0) < 1e-6


def _pairs(target: Key, moving: Key) -> list[tuple[Feature, Feature]]:
    """Nearest same-type pairing: centred features with parallel axes by axis-line distance;
    planar features with parallel normals by offset."""
    used, out = set(), []
    for f in target.features:
        if f.center is not None:
            cands = [g for g in moving.features if g.id not in used and g.type == f.type and g.center is not None
                     and (f.axis is None or g.axis is None or _parallel(f.axis, g.axis))]
            dist = lambda g: _residual(f, g, np.zeros(3))  # noqa: E731
        elif f.normal is not None:
            cands = [g for g in moving.features if g.id not in used and g.type == f.type and g.normal is not None
                     and _parallel(f.normal, g.normal)]
            dist = lambda g: _residual(f, g, np.zeros(3))  # noqa: E731
        else:
            continue
        if cands:
            g = min(cands, key=dist)
            used.add(g.id)
            out.append((f, g))
    return out


def _residual(f: Feature, g: Feature, t: np.ndarray) -> float:
    """Distance of g (shifted by t) from f, ignoring the offset along f's axis (a hole may start
    at either end); for planes, the offset difference."""
    if f.center is not None and g.center is not None:
        d = np.asarray(f.center, float) - (np.asarray(g.center, float) + t)
        if f.axis is not None:
            ax = np.asarray(f.axis, float)
            d = d - ax * float(d @ ax)
        return float(np.linalg.norm(d))
    n = np.asarray(f.normal, float)
    gn = np.asarray(g.normal, float)
    go = float(g.offset or 0.0) * (1.0 if float(n @ gn) > 0 else -1.0)
    return abs(float(f.offset or 0.0) - (go + float(n @ t)))


def _default_tol(key: Key) -> Callable[[Feature], float]:
    fallback = _FALLBACK_TOL.get(key.units, 0.005)
    return lambda f: float((f.tol or {}).get("position") or fallback)


def _translation(pairs, tol: Callable[[Feature], float], lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Consensus shift within the per-axis bound [lo, hi] (widened by the pair's tolerance): the
    admissible candidate bringing the most pairs within tolerance; ties -> the smallest."""
    cands = [np.zeros(3)]
    for f, g in pairs:
        if f.center is not None and g.center is not None:
            t = np.asarray(f.center, float) - np.asarray(g.center, float)
            slack = tol(f) * (1 + 1e-9) + 1e-12
            if np.all(t >= lo - slack) and np.all(t <= hi + slack):
                cands.append(t)
    best, best_key = cands[0], None
    for t in cands:
        inliers = sum(1 for f, g in pairs if _residual(f, g, t) <= tol(f) * (1 + 1e-9) + 1e-12)
        k = (-inliers, float(np.linalg.norm(t)))
        if best_key is None or k < best_key:
            best, best_key = t, k
    return best


def _translate(k: Key, t: np.ndarray) -> Key:
    """Shift a key in place by t (no rotation): centres move, plane offsets gain n.t."""
    if not np.any(t):
        return k
    for f in k.features:
        if f.center is not None:
            f.center = _clean(np.asarray(f.center, float) + t)
        if f.normal is not None:
            f.offset = float(f.offset or 0.0) + float(np.asarray(f.normal, float) @ t) + 0.0
    return k


def _geometric_cost(target: Key, moved: Key) -> float:
    pairs = _pairs(target, moved)
    scale = max(target.envelope) if target.envelope else 1.0
    unpaired = len(target.features) + len(moved.features) - 2 * len(pairs)
    dist = sum(_residual(f, g, np.zeros(3)) for f, g in pairs)
    env = 0.0
    if target.envelope and moved.envelope and len(moved.envelope) == len(target.envelope):
        env = float(np.abs(np.asarray(moved.envelope) - np.asarray(target.envelope)).sum())
    return unpaired * scale + dist + env


def best_fit(target: Key, moving: Key, cost: Optional[Callable[[Key], float]] = None,
             tol: Optional[Callable[[Feature], float]] = None) -> Fit:
    """Try all 24 rotations; for each, refine the translation by consensus (bounded by the
    envelope difference, see the module docstring) and evaluate
    `cost(moved key)` (lower is better; default: geometric). Ties keep the earlier rotation,
    so the identity wins among equivalent poses. A key without an envelope is not moved."""
    if not moving.envelope or len(moving.envelope) != 3:
        return Fit(np.eye(3), np.zeros(3), 0.0)
    tol = tol or _default_tol(target)
    cost = cost or (lambda g: _geometric_cost(target, g))
    best = None
    env_t = np.asarray(target.envelope, float) if target.envelope and len(target.envelope) == 3 else None
    for R in ROTATIONS:
        moved = transform(moving, R)
        d = env_t - np.asarray(moved.envelope, float) if env_t is not None else np.zeros(3)
        t = _translation(_pairs(target, moved), tol, np.minimum(0.0, d), np.maximum(0.0, d))
        c = float(cost(_translate(moved, t)))
        if best is None or c < best.cost - 1e-9:
            best = Fit(R, t, c)
    return best
