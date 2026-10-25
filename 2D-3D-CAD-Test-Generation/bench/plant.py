"""Planted errors on a reference solid (scorer tests + calibration). Geometry edits by CadQuery
booleans on the B-rep, so the edited part goes through keygen exactly like a generated one.

Positions come from the key (part frame: origin at the body's bounding-box minimum, drawing
units) and are converted to the solid's own millimetre frame: global = bbox_min + value x MM_PER.
A hole's ``center`` is the axis point at its open/start end (keygen) and its ``axis`` carries a
canonical sign, so the direction into the material is found by probing the solid (the hole wall
is material on the drilled side, the open side is air).

The ``*_step`` wrappers read a STEP, edit, and write a STEP (a full round trip, like a generated
part). The plain functions work on a solid in memory.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Sequence

from bench.features import Feature, Key
from bench.keygen import MM_PER

PLAIN = ("thru_hole", "blind_hole", "tapped_hole", "counterbore")
_EXTRA = 1.0          # mm a thru cut runs past each face (never into the far wall of a blind hole)


class PlantError(ValueError):
    pass


def read_solid(step: Path):
    import cadquery as cq
    solids = [s for v in cq.importers.importStep(str(step)).vals() for s in v.Solids()]
    if len(solids) != 1:
        raise PlantError(f"{Path(step).name}: {len(solids)} solids; planting needs one")
    return solids[0]


def write_solid(solid, out: Path) -> Path:
    solid.exportStep(str(out))
    return Path(out)


def _lo(solid):
    bb = solid.BoundingBox()
    return (bb.xmin, bb.ymin, bb.zmin)


def _g(lo, p, k):
    import cadquery as cq
    return cq.Vector(*[lo[i] + p[i] * k for i in range(3)])


def _length(f: Feature) -> float:
    """Axial length of the whole hole from its mouth (drawing units)."""
    return (f.cbore_depth or 0.0) + (f.depth or 0.0)


def _direction(solid, f: Feature, k: float) -> int:
    """+1 if the hole runs along +axis from its center, else -1. Probes the material just outside
    the hole wall halfway down each way: the drilled side has wall material, the open side not."""
    import cadquery as cq
    lo = _lo(solid)
    ax = cq.Vector(*f.axis)
    c = _g(lo, f.center, k)
    r = (f.d or 0.0) * k / 2
    perp = ax.cross(cq.Vector(1, 0, 0) if abs(f.axis[0]) < 0.9 else cq.Vector(0, 1, 0)).normalized()
    half = _length(f) * k / 2
    votes = {+1: 0, -1: 0}
    for s in (+1, -1):
        for sign in (+1, -1):
            p = c + ax * (s * half) + perp * (sign * (r + max(0.05, 0.02 * r)))
            if solid.isInside(p):
                votes[s] += 1
    if votes[+1] == votes[-1]:
        raise PlantError(f"{f.id}: cannot tell which way the hole runs from its center")
    return +1 if votes[+1] > votes[-1] else -1


def _cylinder(c, ax, s: int, r: float, length: float, back: float, ahead: float):
    """Cylinder of radius r along s*ax from (c - back) to (c + length + ahead), in mm."""
    import cadquery as cq
    d = ax * s
    return cq.Solid.makeCylinder(r, length + back + ahead, c - d * back, d)


def _hole_tool(f: Feature, c, ax, s: int, k: float, scale: float = 1.0):
    """The material a hole removes (drill plus counterbore), from its mouth at c along s*ax.
    `scale` > 1 makes a plug that covers the hole's walls."""
    thru = bool(f.thru)
    total = _length(f) * k
    tool = _cylinder(c, ax, s, f.d * k / 2 * scale, total, _EXTRA, _EXTRA if thru else 0.0)
    if f.type == "counterbore" and f.cbore_d:
        tool = tool.fuse(_cylinder(c, ax, s, f.cbore_d * k / 2 * scale, f.cbore_depth * k, _EXTRA, 0.0))
    return tool


def _check(f: Feature) -> None:
    if f.type not in PLAIN:
        raise PlantError(f"{f.id}: planting supports {', '.join(PLAIN)}, not {f.type}")
    if f.center is None or f.axis is None or f.d is None:
        raise PlantError(f"{f.id}: needs center, axis and d")


def fill(solid, key: Key, fid: str):
    """The solid with hole `fid` filled flush (a plug fused into it): the feature is now missing."""
    import cadquery as cq
    f = key.feature(fid)
    _check(f)
    k = MM_PER[key.units]
    s = _direction(solid, f, k)
    c = _g(_lo(solid), f.center, k)
    ax = cq.Vector(*f.axis)
    total = _length(f) * k
    # flush at the mouth; through holes flush at the far face too (no protrusion)
    plug = _cylinder(c, ax, s, f.d * k / 2 * 1.002, total, 0.0, 0.0)
    if f.type == "counterbore" and f.cbore_d:
        plug = plug.fuse(_cylinder(c, ax, s, f.cbore_d * k / 2 * 1.002, f.cbore_depth * k, 0.0, 0.0))
    return solid.fuse(plug).clean()


def move(solid, key: Key, fid: str, delta: Sequence[float]):
    """Fill hole `fid`, then cut the same hole at center + delta (drawing units), same direction.
    A delta perpendicular to the axis keeps the start face."""
    import cadquery as cq
    f = key.feature(fid)
    _check(f)
    k = MM_PER[key.units]
    s = _direction(solid, f, k)
    filled = fill(solid, key, fid)
    moved = copy.deepcopy(f)
    moved.center = [f.center[i] + float(delta[i]) for i in range(3)]
    tool = _hole_tool(moved, _g(_lo(filled), moved.center, k), cq.Vector(*f.axis), s, k)
    return filled.cut(tool).clean()


def add(solid, key: Key, center: Sequence[float], d: float, axis: Sequence[float]):
    """Cut an extra through hole of diameter d (drawing units) along `axis` through `center`
    (part frame, drawing units; any point on the hole's axis line)."""
    import cadquery as cq
    k = MM_PER[key.units]
    ax = cq.Vector(*axis).normalized()
    span = max(key.envelope) * k * 2 + 2 * _EXTRA
    c = _g(_lo(solid), center, k)
    tool = cq.Solid.makeCylinder(d * k / 2, 2 * span, c - ax * span, ax)
    return solid.cut(tool).clean()


# --- STEP in, STEP out ------------------------------------------------------------------------

def fill_hole(step: Path, key: Key, fid: str, out: Path) -> Path:
    return write_solid(fill(read_solid(step), key, fid), out)


def move_hole(step: Path, key: Key, fid: str, delta: Sequence[float], out: Path) -> Path:
    return write_solid(move(read_solid(step), key, fid, delta), out)


def add_hole(step: Path, key: Key, center: Sequence[float], d: float, axis: Sequence[float], out: Path) -> Path:
    return write_solid(add(read_solid(step), key, center, d, axis), out)
