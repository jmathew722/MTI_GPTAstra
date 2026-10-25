"""Reference body -> answer key (spec 2026-10-23, "Answer keys").

Works on the B-rep with OCP. Round features come from cylindrical and conical faces grouped
by axis line. Each cylinder group is classified as concave (material outside it: a hole or
bore) or convex (a boss or turned diameter) by testing a point just outside the surface
against the solid. Heuristics are deliberate and documented. The cross-check and the review
sheet catch what they miss.

Conventions: the input body is in millimetres; the key is in drawing units. Positions are in
the part frame (origin at the body's bounding-box minimum). A hole's ``center`` is the axis
point at its open/start end. Every list-valued field is a plain list of Python floats.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Optional

from bench.features import HOLE_TYPES, Feature, Key

MM_PER = {"mm": 1.0, "inch": 25.4}
LIN_TOL = 1e-4          # mm: same axis line / radius / touching intervals
ANG_TOL = 1e-6          # parallel axes (|cos| within this of 1)
FULL_TURN = 2 * math.pi - 1e-6
CSINK_RATIO = 1.25      # cone on a hole axis wider than this x hole d = countersink


class KeygenError(RuntimeError):
    pass


# --- small vector helpers (tuples of float) -------------------------------------------------

def _v(p) -> tuple[float, float, float]:
    return (float(p.X()), float(p.Y()), float(p.Z()))


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    n = math.sqrt(_dot(a, a))
    return _mul(a, 1 / n)


def _canon(d):
    """Direction with its first non-zero component positive (so +Z and -Z group)."""
    for c in d:
        if abs(c) > 1e-9:
            return d if c > 0 else _mul(d, -1)
    return d


def _clean(d):
    """Snap -0.0 / 1e-17 noise in a unit direction to exact values (for readable keys)."""
    return [0.0 if abs(c) < 1e-12 else float(c) for c in d]


def _tidy(v):
    """Round float noise (1e-9 drawing units, far below any tolerance) out of key values;
    tuples become lists so keys round-trip through JSON."""
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 9) + 0.0          # + 0.0 turns -0.0 into 0.0
    if isinstance(v, (list, tuple)):
        return [_tidy(x) for x in v]
    if isinstance(v, dict):
        return {kk: (vv if kk == "count" else _tidy(vv)) for kk, vv in v.items()}
    return v


def _parallel(a, b) -> bool:
    return abs(abs(_dot(a, b)) - 1) < ANG_TOL


# --- B-rep scan ------------------------------------------------------------------------------

@dataclass
class _Round:
    """Cylinder/cone faces sharing one axis line, radius, concavity and a contiguous span."""
    kind: str                 # "cyl" | "cone"
    origin: tuple             # point on the axis line (closest to the global origin)
    axis: tuple               # canonical unit direction
    r: float                  # cylinder radius, or cone's larger radius
    r2: float = 0.0           # cone's smaller radius
    span: float = 0.0         # summed angular span (radians)
    t0: float = math.inf      # axial interval along axis from origin
    t1: float = -math.inf
    concave: Optional[bool] = None
    wide_t0: bool = False     # cone: the larger radius is at t0
    arcs: list = field(default_factory=list)   # (start, length) angular arcs of its faces

    def same_line(self, origin, axis) -> bool:
        if not _parallel(self.axis, axis):
            return False
        d = _sub(origin, self.origin)
        off = _sub(d, _mul(self.axis, _dot(d, self.axis)))
        return math.sqrt(_dot(off, off)) < LIN_TOL

    def point(self, t):
        return _add(self.origin, _mul(self.axis, t))


@dataclass
class _Plane:
    normal: tuple
    offset: float
    area: float
    bbox: tuple               # (xmin, ymin, zmin, xmax, ymax, zmax)


def _line_origin(loc, axis):
    """Point on the line closest to the global origin: a stable id for the line."""
    return _sub(loc, _mul(axis, _dot(loc, axis)))


def _solid_of(shape):
    solids = shape.Solids() if hasattr(shape, "Solids") else [shape]
    if len(solids) != 1:
        raise KeygenError(f"reference has {len(solids)} solids; a benchmark part must be one solid")
    return solids[0]


def _inside(solid, p) -> bool:
    import cadquery as cq
    return solid.isInside(cq.Vector(*p))


def _scan(solid):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane

    faces: list[_Round] = []
    planes: list[_Plane] = []
    for face in solid.Faces():
        a = BRepAdaptor_Surface(face.wrapped)
        t = a.GetType()
        u0, u1, v0, v1 = a.FirstUParameter(), a.LastUParameter(), a.FirstVParameter(), a.LastVParameter()
        if t in (GeomAbs_Cylinder, GeomAbs_Cone):
            g = a.Cylinder() if t == GeomAbs_Cylinder else a.Cone()
            ax = g.Axis()
            loc, raw_dir = _v(ax.Location()), _norm(_v(ax.Direction()))
            axis = _canon(raw_dir)
            origin = _line_origin(loc, axis)
            # Axial position depends only on v; radius (cones) too. Sample both v ends.
            pts = [_v(a.Value(u, v)) for u in (u0, (u0 + u1) / 2, u1) for v in (v0, v1)]
            ts = [_dot(_sub(p, origin), axis) for p in pts]
            radii = [math.dist(p, _add(origin, _mul(axis, tt))) for p, tt in zip(pts, ts)]
            kind = "cyl" if t == GeomAbs_Cylinder else "cone"
            r = max(radii)
            r2 = min(radii) if kind == "cone" else 0.0
            pm = _v(a.Value((u0 + u1) / 2, (v0 + v1) / 2))
            tm = _dot(_sub(pm, origin), axis)
            radial = _norm(_sub(pm, _add(origin, _mul(axis, tm))))
            eps = max(min(0.01, 0.01 * r), 1e-4)
            # material just outside the surface (away from the axis) -> concave (hole-like)
            concave = _inside(solid, _add(pm, _mul(radial, eps)))
            wide_t0 = radii[ts.index(min(ts))] > radii[ts.index(max(ts))]
            arc = _arc(a, origin, axis, u0, u1, (v0 + v1) / 2)
            faces.append(_Round(kind, origin, axis, r, r2, span=arc[1], arcs=[arc],
                                t0=min(ts), t1=max(ts), concave=concave, wide_t0=wide_t0))
        elif t == GeomAbs_Plane:
            pl = a.Plane()
            n = _canon(_norm(_v(pl.Axis().Direction())))
            p = _v(pl.Location())
            bb = face.BoundingBox()
            planes.append(_Plane(n, _dot(p, n), face.Area(),
                                 (bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax)))
    return _merge(faces), planes


def _merge(faces: list[_Round]) -> list[_Round]:
    """Union faces on the same line with the same radii and concavity whose axial intervals
    overlap or touch (OCC splits a full cylinder into halves; two separate coaxial holes of
    the same size, e.g. through both arms of a U, stay separate)."""
    groups: list[_Round] = []
    for f in sorted(faces, key=lambda f: f.t0):
        grp = next((g for g in groups if g.kind == f.kind and g.concave == f.concave
                    and g.same_line(f.origin, f.axis) and abs(g.r - f.r) < LIN_TOL
                    and abs(g.r2 - f.r2) < LIN_TOL
                    and f.t0 <= g.t1 + LIN_TOL and g.t0 <= f.t1 + LIN_TOL), None)
        if grp is None:
            groups.append(_Round(f.kind, f.origin, f.axis, f.r, f.r2, span=f.span, arcs=list(f.arcs),
                                 t0=f.t0, t1=f.t1, concave=f.concave, wide_t0=f.wide_t0))
        else:
            grp.arcs += f.arcs
            grp.span = _arc_union(grp.arcs)     # a union: split partial faces can't reach 2 pi
            grp.t0, grp.t1 = min(grp.t0, f.t0), max(grp.t1, f.t1)
    return groups


def _arc(a, origin, axis, u0, u1, v):
    """A face's angular extent about its axis as (start, length), measured in a basis fixed by
    the canonical axis (OCC's u parameter has a per-face reference direction)."""
    span = abs(u1 - u0)
    if span >= FULL_TURN:
        return (0.0, 2 * math.pi)
    e1, e2 = _basis(axis)

    def ang(u):
        p = _v(a.Value(u, v))
        d = _sub(p, origin)
        return math.atan2(_dot(d, e2), _dot(d, e1))

    a0, am = ang(u0), ang((u0 + u1) / 2)
    ccw = (am - a0) % (2 * math.pi) < math.pi      # half the span is < pi either way
    return ((a0 if ccw else a0 - span) % (2 * math.pi), span)


def _arc_union(arcs) -> float:
    """Total angle covered by a set of (start, length) arcs on a circle."""
    two_pi = 2 * math.pi
    pieces = []
    for s, length in arcs:
        if length >= FULL_TURN:
            return two_pi
        s %= two_pi
        if s + length > two_pi:
            pieces += [(s, two_pi), (0.0, s + length - two_pi)]
        else:
            pieces.append((s, s + length))
    total, cur = 0.0, None
    for s, e in sorted(pieces):
        if cur is None or s > cur[1] + 1e-9:
            if cur is not None:
                total += cur[1] - cur[0]
            cur = [s, e]
        else:
            cur[1] = max(cur[1], e)
    if cur is not None:
        total += cur[1] - cur[0]
    return min(total, two_pi)


def _closed_beyond(solid, g: _Round, t, outward) -> bool:
    """True if material closes the axis just beyond axial position t.

    Probes on the axis from 1 um out to one radius past t: a drill point (cone tip, length
    ~0.6 r) is air on the axis right at the cylinder end, but there is material within r.
    A hole exiting into free air (or an exit chamfer) has none."""
    for s in (1e-3, 0.25 * g.r, 0.5 * g.r, 0.75 * g.r, 1.0 * g.r):
        if _inside(solid, g.point(t + outward * s)):
            return True
    return False


def _chains(line: list[_Round]) -> list[list[_Round]]:
    """Split one axis line's concave cylinders into chains of axially touching intervals."""
    chains: list[list[_Round]] = []
    for g in sorted(line, key=lambda g: g.t0):
        if chains and g.t0 <= max(c.t1 for c in chains[-1]) + 1e-3:
            chains[-1].append(g)
        else:
            chains.append([g])
    return chains


# --- extraction ------------------------------------------------------------------------------

def extract(shape, *, units: str, part: str, source: str) -> Key:
    """Reference body (cadquery Shape, millimetres) -> Key in drawing units."""
    if units not in MM_PER:
        raise KeygenError(f"unknown units {units!r}")
    k = MM_PER[units]
    solid = _solid_of(shape)
    bb = solid.BoundingBox()
    lo = (bb.xmin, bb.ymin, bb.zmin)
    env = [float(bb.xlen / k), float(bb.ylen / k), float(bb.zlen / k)]
    rounds, planes = _scan(solid)

    feats: list[Feature] = []
    nid = iter(range(1, 10_000))

    def new(type_, **kw) -> Feature:
        f = Feature(id=f"K{next(nid):03d}", type=type_, **{n: _tidy(v) for n, v in kw.items()})
        feats.append(f)
        return f

    def frame(p):                       # mm global -> part frame, drawing units
        return [float((p[i] - lo[i]) / k) for i in range(3)]

    full = [g for g in rounds if g.kind == "cyl" and g.span >= FULL_TURN]
    partial = [g for g in rounds if g.kind == "cyl" and g.span < FULL_TURN]
    cones = [g for g in rounds if g.kind == "cone"]

    # Turned axis: the largest convex cylinder covering at least half a turn (a flat or slot
    # on the OD leaves it partial) and spanning ~the whole envelope across its axis.
    turned = None
    convex = sorted((g for g in rounds if g.kind == "cyl" and not g.concave
                     and g.span >= math.pi - 1e-6), key=lambda g: -g.r)
    if convex:
        g = convex[0]
        perp = [e * k for e, c in zip(env, g.axis) if abs(c) < 0.5]
        if perp and 2 * g.r >= 0.9 * max(perp):
            turned = g

    # Concave full cylinders: group by axis line, then by touching chains on that line.
    lines: list[list[_Round]] = []
    for g in (g for g in full if g.concave):
        for ln in lines:
            if ln[0].same_line(g.origin, g.axis):
                ln.append(g)
                break
        else:
            lines.append([g])
    for chain in (c for ln in lines for c in _chains(ln)):
        _hole_chain(solid, chain, turned, new, frame, k)

    for g in (g for g in full if not g.concave):
        kw = dict(axis=_clean(g.axis), center=frame(g.point(g.t0)),
                  d=float(2 * g.r / k), depth=float((g.t1 - g.t0) / k))
        if turned is not None and turned.same_line(g.origin, g.axis):
            new("turned_diameter", **kw)
        else:
            new("boss", **kw)

    _cones_and_partials(new, frame, k, cones, partial, feats, turned)
    _planar(new, k, lo, env, planes, turned, [g for g in full if g.concave])
    _patterns(new, feats, frame, k, turned)
    return Key(part=part, units=units, source=source, envelope=_tidy(env), features=feats)


def _hole_chain(solid, chain: list[_Round], turned, new, frame, k):
    """One chain of axially touching concave cylinders on one axis line.

    Smallest radius = the drill. A larger cylinder touching one end of the drill is its
    counterbore. Anything else on the chain is listed as a further bore step."""
    drill = min(chain, key=lambda g: g.r)
    cb = None
    cb_lo = cb_hi = False
    for g in sorted((g for g in chain if g is not drill), key=lambda g: g.r):
        if abs(g.t1 - drill.t0) < 1e-3:
            cb, cb_lo = g, True
        elif abs(g.t0 - drill.t1) < 1e-3:
            cb, cb_hi = g, True
        if cb is not None:
            break
    lo_open = cb_lo or not _closed_beyond(solid, drill, drill.t0, -1)
    hi_open = cb_hi or not _closed_beyond(solid, drill, drill.t1, +1)
    thru = lo_open and hi_open
    if cb is not None:
        start = cb.t0 if cb_lo else cb.t1
    else:
        start = drill.t0 if lo_open else drill.t1
    # A hole on the turned axis is a bore when it goes through or is big (>= half the largest
    # turned diameter); a small blind one in an end face is a plain blind hole, so a TAP callout
    # can claim it (rod ends tapped .375-16 / .625-11).
    on_turned_axis = (turned is not None and turned.same_line(drill.origin, drill.axis)
                      and (thru or drill.r >= 0.5 * turned.r - LIN_TOL))
    kw = dict(axis=_clean(drill.axis), center=frame(drill.point(start)), d=float(2 * drill.r / k),
              depth=float((drill.t1 - drill.t0) / k), thru=thru)
    if on_turned_axis:
        new("bore", **kw)
        cb_used = None
    elif cb is not None:
        new("counterbore", cbore_d=float(2 * cb.r / k), cbore_depth=float((cb.t1 - cb.t0) / k), **kw)
        cb_used = cb
    else:
        new("thru_hole" if thru else "blind_hole", **kw)
        cb_used = None
    for extra in chain:
        if extra is drill or extra is cb_used:
            continue
        new("bore", axis=_clean(extra.axis), center=frame(extra.point(extra.t0)),
            d=float(2 * extra.r / k), depth=float((extra.t1 - extra.t0) / k),
            note="further step on the same axis")


def _note(f: Feature, text: str) -> None:
    f.note = f"{f.note}; {text}" if f.note else text


def _cones_and_partials(new, frame, k, cones, partial, feats, turned):
    """Cones on a hole axis (concave):
      - drill point: comes to a point at the bottom of a blind hole, width = hole d -> skipped;
      - countersink: small end meets the drill (= hole d) and wide end > CSINK_RATIO x d;
      - anything else (a hole/counterbore/countersink mouth break, OD chamfers) -> chamfer.
    A hole's ``center`` then moves out through the mouth stack (countersink, chamfers) to the
    open face. Countersinks at both ends: the one at the start end is recorded, the other noted.
    Partial cylinders: <= quarter turn -> fillet; convex on the turned axis -> turned diameter
    (interrupted); other convex -> boss (rounded end); concave -> slot/notch end."""
    tol = 1e-2 / k                                  # 0.01 mm, in drawing units
    holes = [f for f in feats if f.type in HOLE_TYPES or f.type == "bore"]
    csinks: dict[str, tuple[Feature, list[_Round]]] = {}
    chamfers: list[tuple[_Round, Optional[Feature]]] = []

    def narrow_t(c):
        return c.t1 if c.wide_t0 else c.t0

    def wide_t(c):
        return c.t0 if c.wide_t0 else c.t1

    def at_center(c, t, h):
        return math.dist(frame(c.point(t)), h.center) < tol

    for c in cones:
        big, small = 2 * c.r / k, 2 * c.r2 / k
        host = next((h for h in holes if _parallel(tuple(h.axis), c.axis) and _on_axis(h, c, frame, k)),
                    None)
        if host is not None and c.concave:
            if host.type == "blind_hole" and abs(big - host.d) < tol and small < 0.05 * host.d:
                _note(host, "drill point")
                continue
            if host.type in HOLE_TYPES and abs(small - host.d) < tol and big > CSINK_RATIO * host.d:
                csinks.setdefault(host.id, (host, []))[1].append(c)
                continue
        chamfers.append((c, host))

    mouth_t: dict[str, float] = {}                  # axial position of a countersink's mouth
    main_cs: dict[str, _Round] = {}
    for host, cs in csinks.values():
        main = next((c for c in cs if at_center(c, narrow_t(c), host)), cs[0])
        host.csink_d = _tidy(2 * main.r / k)
        if host.type != "counterbore":
            host.type = "countersink"
            host.center = _tidy(frame(main.point(wide_t(main))))
            mouth_t[host.id], main_cs[host.id] = wide_t(main), main
        for other in cs:
            if other is not main:
                _note(host, f"second countersink d={_tidy(2 * other.r / k)} at the other end")

    for c, _host in chamfers:
        new("chamfer", axis=_clean(c.axis), center=frame(c.point(c.t0)),
            d=float(2 * c.r / k), depth=float((c.t1 - c.t0) / k), note="conical edge break")
    # Mouth breaks: a concave chamfer whose narrow end sits at the hole's start, as wide as the
    # current mouth, moves the start out to its wide end (repeat for stacked breaks).
    mouth = {h.id: (h.csink_d or h.cbore_d or h.d) for h in holes}
    moved = True
    while moved:
        moved = False
        for c, h in chamfers:
            if h is None or not c.concave or abs(2 * c.r2 / k - mouth[h.id]) >= tol \
                    or not at_center(c, narrow_t(c), h):
                continue
            h.center = _tidy(frame(c.point(wide_t(c))))
            mouth[h.id] = 2 * c.r / k
            if h.id in mouth_t:
                mouth_t[h.id] = wide_t(c)
            moved = True
    # Drawing convention: a countersink's diameter is where its cone meets the open face, so a
    # chamfered countersink rim is measured on the cone extended to the final mouth plane.
    for hid, t in mouth_t.items():
        c = main_cs[hid]
        tn, tw = narrow_t(c), wide_t(c)
        r = c.r2 + (t - tn) * (c.r - c.r2) / (tw - tn) if abs(tw - tn) > 1e-12 else c.r
        next(h for h in holes if h.id == hid).csink_d = _tidy(2 * r / k)

    for p in partial:
        kw = dict(axis=_clean(p.axis), d=float(2 * p.r / k), depth=float((p.t1 - p.t0) / k),
                  center=frame(p.point(p.t0)))
        if p.span <= math.pi / 2 + 1e-3:
            new("fillet", **kw)
        elif p.concave:
            new("slot", size=[0.0, float(2 * p.r / k)], note="round slot/notch end (width = d)", **kw)
        elif turned is not None and turned.same_line(p.origin, p.axis):
            new("turned_diameter", note="interrupted by flat/slot", **kw)
        else:
            new("boss", note="rounded end / partial", **kw)


def _on_axis(hole: Feature, c: _Round, frame, k) -> bool:
    """Is the cone's axis line the hole's axis line? (Both compared in the part frame.)"""
    p = frame(c.origin)
    d = [p[i] - hole.center[i] for i in range(3)]
    ax = hole.axis
    t = sum(d[i] * ax[i] for i in range(3))
    off = [d[i] - ax[i] * t for i in range(3)]
    return math.sqrt(sum(x * x for x in off)) < 10 * LIN_TOL / k


def _inside_hole(pl: _Plane, holes: list[_Round]) -> bool:
    """A hole bottom or counterbore shoulder: perpendicular to a concave cylinder's axis and
    lying entirely within that cylinder's diameter."""
    lo_c, hi_c = pl.bbox[:3], pl.bbox[3:]
    for g in holes:
        if not _parallel(pl.normal, g.axis):
            continue
        for corner in ((lo_c[0], lo_c[1], lo_c[2]), (hi_c[0], hi_c[1], hi_c[2])):
            d = _sub(corner, g.origin)
            off = _sub(d, _mul(g.axis, _dot(d, g.axis)))
            # bbox corners of a disc/annulus of radius r sit at up to r*sqrt(2) from the axis
            if math.sqrt(_dot(off, off)) > g.r * math.sqrt(2) + LIN_TOL:
                break
        else:
            return True
    return False


def _planar(new, k, lo, env, planes, turned, holes):
    """Planar faces that are not on the bounding box and not inside a hole (bottoms,
    counterbore shoulders): flats (on turned parts, parallel to the turned axis) or
    pocket/step faces. Grouped by (normal, offset); shoulders (perpendicular to the turned
    axis) are skipped."""
    bbox_offsets = {i: (lo[i], lo[i] + env[i] * k) for i in range(3)}
    seen = set()
    for pl in planes:
        # On a turned part a flat is checked first: a one-sided flat is on the bounding box.
        if turned is not None and abs(_dot(pl.normal, turned.axis)) < 1e-6 \
                and abs(_dot(turned.origin, pl.normal) - pl.offset) < turned.r - LIN_TOL:
            keyv = (tuple(round(c, 6) for c in pl.normal), round(pl.offset, 4))
            if keyv not in seen:
                seen.add(keyv)
                new("flat", normal=_clean(pl.normal), offset=float((pl.offset - _dot(lo, pl.normal)) / k),
                    size=[float((pl.bbox[i + 3] - pl.bbox[i]) / k) for i in range(3)])
            continue
        axis_i = next((i for i in range(3) if abs(abs(pl.normal[i]) - 1) < 1e-6), None)
        if axis_i is not None and any(abs(pl.offset - b) < LIN_TOL for b in bbox_offsets[axis_i]):
            continue
        if _inside_hole(pl, holes):
            continue
        keyv = (tuple(round(c, 6) for c in pl.normal), round(pl.offset, 4))
        if keyv in seen:
            continue
        seen.add(keyv)
        ext = [float((pl.bbox[i + 3] - pl.bbox[i]) / k) for i in range(3)]
        if turned is not None and _parallel(pl.normal, turned.axis):
            continue                                # shoulder of a turned part
        # offset in the part frame (origin at the bounding-box minimum), like every position
        new("pocket_step", normal=_clean(pl.normal), offset=float((pl.offset - _dot(lo, pl.normal)) / k),
            size=ext)


def _patterns(new, feats, frame, k, turned):
    """Same-type, same-size holes on parallel axes: circle (3+ concyclic about the turned
    axis, or concyclic and not a rectangle), grid (4 at rectangle corners), line (3+
    collinear), else set (2+). A 4-hole square on a turned part is a bolt circle, not a grid."""
    tol = LIN_TOL / k * 10          # drawing units
    holes = [f for f in feats if f.type in HOLE_TYPES]
    groups: list[list[Feature]] = []
    for h in holes:
        for g in groups:
            h0 = g[0]
            if h0.type == h.type and abs(h0.d - h.d) < tol and _parallel(tuple(h0.axis), tuple(h.axis)) \
                    and abs((h0.cbore_d or 0) - (h.cbore_d or 0)) < tol \
                    and abs((h0.csink_d or 0) - (h.csink_d or 0)) < tol:
                g.append(h)
                break
        else:
            groups.append([h])
    for g in groups:
        if len(g) < 2:
            continue
        e1, e2 = _basis(tuple(g[0].axis))
        pts = [(_dot(tuple(h.center), e1), _dot(tuple(h.center), e2)) for h in g]
        circ = _circle(pts, tol) if len(pts) >= 3 else None
        about_turned = False
        if circ is not None and turned is not None and _parallel(turned.axis, tuple(g[0].axis)):
            tc = tuple(frame(turned.origin))
            about_turned = math.dist(circ[0], (_dot(tc, e1), _dot(tc, e2))) < tol
        rect = len(pts) == 4 and _is_rectangle(pts, tol)
        mode, extra = "set", {}
        if circ is not None and (about_turned or not rect):
            mode, extra = "circle", {"radius": float(circ[1]), "center_2d": [float(circ[0][0]), float(circ[0][1])]}
        elif rect:
            mode = "grid"
        elif len(pts) >= 3 and _collinear(pts, tol):
            mode = "line"
        new("hole_pattern", members=[h.id for h in g], pattern={"mode": mode, "count": len(g), **extra},
            d=g[0].d)


def _basis(ax):
    """Two in-plane unit vectors perpendicular to ax (pattern centers are projected on them)."""
    ref = (1.0, 0.0, 0.0) if abs(ax[0]) < 0.9 else (0.0, 1.0, 0.0)
    e1 = _norm(_sub(ref, _mul(ax, _dot(ref, ax))))
    e2 = (ax[1] * e1[2] - ax[2] * e1[1], ax[2] * e1[0] - ax[0] * e1[2], ax[0] * e1[1] - ax[1] * e1[0])
    return e1, e2


def _is_rectangle(p, tol) -> bool:
    c = (sum(x for x, _ in p) / 4, sum(y for _, y in p) / 4)
    r = [math.dist(c, q) for q in p]
    if max(r) - min(r) > tol:
        return False
    ds = sorted(math.dist(a, b) for a, b in combinations(p, 2))
    return abs(ds[0] - ds[1]) < tol and abs(ds[2] - ds[3]) < tol and abs(ds[4] - ds[5]) < tol


def _circle(p, tol):
    """Circle through the first three non-collinear points if all points lie on it."""
    for a, b, c in combinations(p, 3):
        (ax, ay), (bx, by), (cx, cy) = a, b, c
        d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
        if abs(d) < 1e-12:
            continue
        ux = ((ax**2 + ay**2) * (by - cy) + (bx**2 + by**2) * (cy - ay) + (cx**2 + cy**2) * (ay - by)) / d
        uy = ((ax**2 + ay**2) * (cx - bx) + (bx**2 + by**2) * (ax - cx) + (cx**2 + cy**2) * (bx - ax)) / d
        r = math.dist((ux, uy), a)
        return ((ux, uy), r) if all(abs(math.dist((ux, uy), q) - r) < tol for q in p) else None
    return None


def _collinear(p, tol) -> bool:
    (x1, y1), (x2, y2) = max(combinations(p, 2), key=lambda ab: math.dist(*ab))
    L = math.dist((x1, y1), (x2, y2)) or 1.0
    return all(abs((x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)) / L < tol for x, y in p)


def from_step(step: Path, *, units: str, part: str) -> Key:
    import cadquery as cq
    # every root of the file, so a multi-body STEP is seen (and rejected) by the solid count
    shape = cq.Compound.makeCompound(cq.importers.importStep(str(step)).vals())
    return extract(shape, units=units, part=part, source=Path(step).name)
