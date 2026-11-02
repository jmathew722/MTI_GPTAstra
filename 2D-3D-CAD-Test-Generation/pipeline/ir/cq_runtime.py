"""Geometry runtime for scripts emitted by :mod:`pipeline.ir.compile_cadquery`.

The emitted script is a flat list of calls on :class:`Model` with numbers already
evaluated from the plan's expressions (the expressions sit beside them as comments).
All the geometry rules live here, once:

* sketch (u, v) are GLOBAL coordinates in the sketch plane (front: x, y · top: x, z ·
  right: y, z), never a local frame (IR v2 spec);
* ``face(F,±A)`` is the plane at feature F's tool-body extreme along A;
* ``op: add`` extrudes along the start ref's normal (outward for a face); ``cut`` goes
  into the material; ``depth="thru"`` cuts through everything in both directions;
* ``edge_between(A, B)`` is the set of result edges shared by a face matching A and
  a face matching B.

Lengths come in drawing units and are scaled to millimetres (STEP is written in mm).
The feature map reports both units.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Optional

import cadquery as cq

from pipeline.ir.model import parse_edge_query, parse_ref

AXES = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}
# base plane -> (normal axis, cq Plane xDir, cq Plane normal) chosen so local (u, v)
# equal the GLOBAL in-plane coordinates: front (x, y), top (x, z), right (y, z).
PLANES = {
    "front": ("Z", (1, 0, 0), (0, 0, 1)),
    "top": ("Y", (1, 0, 0), (0, -1, 0)),
    "right": ("X", (0, 1, 0), (1, 0, 0)),
}
AXIS_PLANE = {"Z": "front", "Y": "top", "X": "right"}
TOL = 1e-4  # mm


class CompileError(RuntimeError):
    """The plan can't be built as written (e.g. an ambiguous or empty ref)."""


def _cylinder(face):
    """gp_Cylinder of a CYLINDER face. Read through BRepAdaptor_Surface: a face trimmed by a
    later cut (e.g. a slot through a revolved disc) has a Geom_RectangularTrimmedSurface, whose
    raw _geomAdaptor() has no .Cylinder() (A050211E official run and 4C1229, 2026-10-26)."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    return BRepAdaptor_Surface(face.wrapped).Cylinder()


def _guarded(fn):
    """In non-strict mode a failing feature is recorded as skipped, not fatal (v1 parity)."""
    def wrapper(self, fid, *a, **kw):
        if self.strict:
            return fn(self, fid, *a, **kw)
        try:
            return fn(self, fid, *a, **kw)
        except Exception as e:  # OCC raises assorted types; record and continue
            self.skipped[fid] = f"failed: {type(e).__name__}: {e}"[:300]
    wrapper.__name__ = fn.__name__
    return wrapper


def _has_radius(face, radius: float) -> bool:
    """wall(F,r): a cylinder of radius r, or a cone with a rim circle of radius r (a taper is
    dimensioned at its end; SB14306 F003). _faces_for prefers the cylinder when both match."""
    if face.geomType() == "CYLINDER":
        return abs(_cylinder(face).Radius() - radius) <= TOL * 10
    if face.geomType() == "CONE":
        return any(e.geomType() == "CIRCLE" and abs(e.radius() - radius) <= TOL * 10 for e in face.Edges())
    return False


def _idx(axis: str) -> int:
    return "XYZ".index(axis)


class Model:
    def __init__(self, part: str, origin_kind: str, units: str, strict: bool = True):
        self.strict = strict
        self.part = part
        self.origin_kind = origin_kind
        self.units = units
        self.k = 25.4 if units == "inch" else 1.0
        self.solid: Optional[cq.Shape] = None
        self.tools: dict[str, cq.Shape] = {}
        self.axes: dict[str, tuple[tuple[float, float, float], str]] = {}
        self.order: list[str] = []
        self.holes: dict[str, list[dict]] = {}
        self.cut_ops: set[str] = set()
        self.edge_points: dict[str, list[list[float]]] = {}
        self.skipped: dict[str, str] = {}
        self.starts: dict[str, dict] = {}         # resolved start plane per prism/hole (drawing units)
        self.volume_after: dict[str, float] = {}  # solid volume after each feature (drawing units^3)
        self.base: Optional[dict] = None          # the first body (MTI: the origin centers on it)

    # ------------------------------------------------------------------ refs --
    def _start(self, on: str, offset: float) -> tuple[str, float, int]:
        """(normal axis, plane coordinate in mm, outward sign) for a start ref."""
        kind, args = parse_ref(on)
        if kind == "plane":
            axis = PLANES[args[0]][0]
            return axis, offset * self.k, +1
        if kind == "face":
            fid, sd = args[0], args[1]
            tool = self._tool(fid)
            axis, sign = sd[1], (+1 if sd[0] == "+" else -1)
            if len(args) == 3:   # explicit coordinate (stepped bodies)
                coord = float(args[2]) * self.k
            else:
                bb = tool.BoundingBox()
                coord = (bb.xmax, bb.ymax, bb.zmax)[_idx(axis)] if sign > 0 else (bb.xmin, bb.ymin, bb.zmin)[_idx(axis)]
            return axis, coord + sign * offset * self.k, sign
        raise CompileError(f"{on} can't be a start ref (use plane(...) or face(...))")

    def _tool(self, fid: str) -> cq.Shape:
        if fid not in self.tools:
            raise CompileError(f"ref to {fid}, which has no geometry (not built or skipped)")
        return self.tools[fid]

    def _workplane(self, axis: str, coord: float) -> cq.Workplane:
        name = AXIS_PLANE[axis]
        _, xdir, normal = PLANES[name]
        origin = [0.0, 0.0, 0.0]
        origin[_idx(axis)] = coord
        return cq.Workplane(cq.Plane(origin=tuple(origin), xDir=xdir, normal=normal))

    def _plane_sign(self, axis: str) -> int:
        """+1 if the cq plane normal for this axis points along +axis."""
        return -1 if axis == "Y" else +1

    # -------------------------------------------------------------- apply --
    def _apply(self, fid: str, tool: cq.Shape, op: str) -> None:
        self._apply_inner(fid, tool, op)
        self.volume_after[fid] = round(self.solid.Volume() / self.k ** 3, 9)

    def _apply_inner(self, fid: str, tool: cq.Shape, op: str) -> None:
        self.tools[fid] = tool
        self.order.append(fid)
        if op != "add":
            self.cut_ops.add(fid)
        if self.solid is None:
            if op != "add":
                raise CompileError(f"{fid}: the first feature must add material")
            self.solid = tool
            bb = tool.BoundingBox()
            self.base = {"fid": fid, "bbox": [round(v / self.k, 9) for v in (
                bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax)]}
        elif op == "add":
            self.solid = self.solid.fuse(tool).clean()
        else:
            before = self.solid.Volume()
            self.solid = self.solid.cut(tool).clean()
            if self.solid.Volume() >= before - 1e-9:
                raise CompileError(f"{fid}: cut removed no material (check position/direction)")

    def _big(self) -> float:
        if self.solid is None:
            return 1e4
        bb = self.solid.BoundingBox()
        return 4 * max(bb.xlen, bb.ylen, bb.zlen, 1.0)

    # -------------------------------------------------------------- prism --
    @_guarded
    def prism(self, fid: str, *, on: str, offset: float, profile: dict, depth, op: str) -> None:
        axis, coord, outward = self._start(on, offset)
        is_face0 = parse_ref(on)[0] == "face"
        self.starts[fid] = {"axis": axis, "coord": round(coord / self.k, 9),
                            "dir": (outward if (op == "add" or not is_face0) else -outward),
                            "thru": depth == "thru"}
        wp = self._workplane(axis, coord)
        k = self.k
        shape = profile["shape"]
        if shape == "rect":
            wp = wp.center(profile["u"] * k, profile["v"] * k).rect(
                profile["w"] * k, profile["h"] * k, centered=profile["anchor"] == "center")
        elif shape == "circle":
            wp = wp.center(profile["u"] * k, profile["v"] * k).circle(profile["d"] * k / 2)
            self.axes[fid] = (self._point(axis, coord, profile["u"] * k, profile["v"] * k), axis)
        elif shape == "slot":
            wp = wp.center(profile["u"] * k, profile["v"] * k).slot2D(
                (profile["length"] + profile["width"]) * k, profile["width"] * k, profile["angle"])
        elif shape == "polygon":
            wp = wp.polyline([(u * k, v * k) for u, v in profile["points"]]).close()
        else:
            raise CompileError(f"{fid}: unknown profile {shape}")
        # From a face: add goes outward, cut goes into the material. From a base plane
        # there is no "outward", so both go along +normal (offset sets the start).
        is_face = parse_ref(on)[0] == "face"
        direction = outward if (op == "add" or not is_face) else -outward
        ps = self._plane_sign(axis)
        if depth == "thru":
            if op == "add":
                raise CompileError(f"{fid}: depth 'thru' is only valid for a cut")
            big = self._big()
            tool = wp.extrude(big, both=True).val()
        else:
            tool = wp.extrude(depth * k * direction * ps).val()
        self._apply(fid, tool, op)

    def _point(self, axis: str, coord: float, u: float, v: float) -> tuple[float, float, float]:
        if axis == "Z":
            return (u, v, coord)
        if axis == "Y":
            return (u, coord, v)
        return (coord, u, v)

    # ------------------------------------------------------------ revolve --
    @_guarded
    def revolve(self, fid: str, *, outer: list, inner: list, op: str) -> None:
        if self.origin_kind != "axis_end":
            raise CompileError(f"{fid}: revolve about axis(part) needs frame origin_kind 'axis_end'")
        k = self.k
        o = [(r * k, z * k) for z, r in outer]
        if inner:
            i = [(r * k, z * k) for z, r in inner]
            if abs(i[0][1] - o[0][1]) > TOL or abs(i[-1][1] - o[-1][1]) > TOL:
                raise CompileError(f"{fid}: inner and outer stations must start and end at the same z")
            pts = o + list(reversed(i))
        else:
            pts = [(0.0, o[0][1])] + o + [(0.0, o[-1][1])]
        pts = [p for n, p in enumerate(pts) if n == 0 or (abs(p[0] - pts[n - 1][0]) > TOL or abs(p[1] - pts[n - 1][1]) > TOL)]
        wp = cq.Workplane(cq.Plane(origin=(0, 0, 0), xDir=(1, 0, 0), normal=(0, -1, 0)))
        tool = wp.polyline(pts).close().revolve(360, (0, 0, 0), (0, 1, 0)).val()
        self.axes[fid] = ((0.0, 0.0, 0.0), "Z")
        self._apply(fid, tool, op)

    # --------------------------------------------------------------- hole --
    @_guarded
    def hole(self, fid: str, *, on: str, u: float, v: float, spec: dict) -> None:
        if parse_ref(on)[0] == "wall":
            return self._radial_hole(fid, on, u, v, spec)
        axis, coord, outward = self._start(on, 0.0)
        k = self.k
        into = -outward if parse_ref(on)[0] == "face" else +1
        start = self._point(axis, coord, u * k, v * k)
        self.starts[fid] = {"axis": axis, "coord": round(coord / k, 9), "dir": into}
        d = spec["d"] * k
        dvec = [0.0, 0.0, 0.0]
        dvec[_idx(axis)] = float(into)
        dirv = cq.Vector(*dvec)
        if spec["type"] == "thru" or spec.get("depth") is None:  # null depth = through (".750-10 TAP THRU")
            big = self._big()
            tool = cq.Solid.makeCylinder(d / 2, 2 * big, cq.Vector(*start) - dirv * big, dirv)
        elif spec["type"] in ("blind", "tapped", "cbore"):
            tool = cq.Solid.makeCylinder(d / 2, spec["depth"] * k, cq.Vector(*start), dirv)
        else:
            raise CompileError(f"{fid}: hole type {spec['type']} is not supported yet")
        if spec["type"] == "cbore":
            cb = cq.Solid.makeCylinder(spec["cbore_d"] * k / 2, spec["cbore_depth"] * k, cq.Vector(*start), dirv)
            tool = tool.fuse(cb).clean()
        self.axes[fid] = (start, axis)
        self.holes[fid] = [{"center_mm": list(start), "axis": axis, "into": into, "d_mm": d,
                            "spec": spec}]
        self._apply(fid, tool, "cut")

    def _radial_hole(self, fid: str, on: str, u: float, v: float, spec: dict) -> None:
        """Radial hole (spec 2026-10-28-radial-holes-design.md): from wall(F, r) toward the part
        axis, u = angle in degrees from +X about +Z, v = axial station z. Not added to
        self.holes (measure_holes assumes X/Y/Z holes); verified by volume like any feature."""
        _, args = parse_ref(on)
        if self.origin_kind != "axis_end":
            raise CompileError(f"{fid}: a radial hole needs frame origin_kind 'axis_end'")
        if len(args) != 2:
            raise CompileError(f"{fid}: a radial hole needs the wall radius: wall(F, r)")
        if spec["type"] in ("cbore", "csink"):
            raise CompileError(f"{fid}: radial {spec['type']} holes are not supported yet")
        k = self.k
        r, z, th = float(args[1]) * k, v * k, math.radians(u)
        out = cq.Vector(math.cos(th), math.sin(th), 0.0)
        big = self._big()
        thru = spec["type"] == "thru" or spec.get("depth") is None
        length = 2 * big if thru else big + spec["depth"] * k
        start = out * (big if thru else r + big) + cq.Vector(0.0, 0.0, z)
        tool = cq.Solid.makeCylinder(spec["d"] * k / 2, length, start, out * -1)
        self.starts[fid] = {"radial": True, "angle": u, "z": v, "r": float(args[1]),
                            "depth": None if thru else spec["depth"]}
        self._apply(fid, tool, "cut")

    # ------------------------------------------------------------ pattern --
    @_guarded
    def pattern(self, fid: str, *, seed: str, mode: str, count: int, pitch: float, dir: str,
                count2: int, pitch2: float, dir2: str, axis: str, step, skip: list[int], op: str) -> None:
        tool = self._tool(seed)
        k = self.k
        copies = []
        if mode in ("linear", "grid"):
            d1 = cq.Vector(*AXES[dir[1]]) * (1 if dir[0] == "+" else -1)
            d2 = cq.Vector(*AXES[dir2[1]]) * (1 if dir2[0] == "+" else -1)
            n2 = count2 if mode == "grid" else 1
            n = 0
            for j in range(n2):
                for i in range(count):
                    if (i, j) != (0, 0) and n not in skip:
                        copies.append(tool.translate(d1 * (i * pitch * k) + d2 * (j * pitch2 * k)))
                    n += 1
        else:
            kind, args = parse_ref(axis)
            if args[0] == "part":
                if self.origin_kind != "axis_end":
                    raise CompileError(f"{fid}: axis(part) needs frame origin_kind 'axis_end'")
                p0, ax = (0.0, 0.0, 0.0), "Z"
            else:
                if args[0] not in self.axes:
                    raise CompileError(f"{fid}: {axis} has no axis (not a revolve, circle or hole)")
                p0, ax = self.axes[args[0]]
            ang = 360.0 / count if step == "equal" else float(step)
            for i in range(1, count):
                if i not in skip:
                    copies.append(tool.rotate(cq.Vector(*p0), cq.Vector(*p0) + cq.Vector(*AXES[ax]), ang * i))
        if not copies:
            raise CompileError(f"{fid}: pattern produced no instances")
        merged = copies[0]
        for c in copies[1:]:
            merged = merged.fuse(c)
        if seed in self.holes:
            base = self.holes[seed][0]
            inst = []
            for c in copies:
                bb = c.BoundingBox()
                ctr = [(bb.xmin + bb.xmax) / 2, (bb.ymin + bb.ymax) / 2, (bb.zmin + bb.zmax) / 2]
                ctr[_idx(base["axis"])] = base["center_mm"][_idx(base["axis"])]
                inst.append({**base, "center_mm": ctr})
            self.holes[fid] = inst
        self._apply(fid, merged, op)

    # ------------------------------------------------------------ edge_op --
    def _faces_for(self, ref: str) -> list:
        kind, args = parse_ref(ref)
        faces = self.solid.Faces()
        if kind == "face":
            sd = args[1]
            axis, coord, _ = self._start(ref, 0.0)
            want = cq.Vector(*AXES[axis]) * (1 if sd[0] == "+" else -1)
            # a cut's +X wall faces -X, into the pocket (2N2664 F023); its +Z opening is the
            # surrounding material's +Z face: for a cut, either normal at that coordinate
            wants = (want, want * -1) if args[0] in self.cut_ops else (want,)
            out = []
            for f in faces:
                if f.geomType() != "PLANE":
                    continue
                n = f.normalAt()
                c = f.Center()
                if any((n - w).Length < 1e-6 for w in wants) and abs((c.x, c.y, c.z)[_idx(axis)] - coord) < TOL * 10:
                    out.append(f)
            return out
        if kind == "plane":
            axis = PLANES[args[0]][0]
            return [f for f in faces if f.geomType() == "PLANE" and abs((lambda c: (c.x, c.y, c.z))(f.Center())[_idx(axis)]) < TOL * 10]
        if kind == "wall":
            tool = self._tool(args[0])
            radius = float(args[1]) * self.k if len(args) == 2 else None
            out = []
            for f in faces:
                if f.geomType() == "PLANE":
                    continue
                if radius is not None and not _has_radius(f, radius):
                    continue
                c = f.positionAt(0.5, 0.5)   # on the surface; a revolved face's Center() is on the axis
                if cq.Vertex.makeVertex(c.x, c.y, c.z).distance(tool) < TOL * 10:
                    out.append(f)
            if radius is not None and any(f.geomType() == "CYLINDER" for f in out):
                out = [f for f in out if f.geomType() == "CYLINDER"]   # cone rims only as a fallback
            return out
        raise CompileError(f"{ref} can't be used in an edge query")

    @_guarded
    def edge_op(self, fid: str, *, operation: str, size: float, angle: float, edges: list[str]) -> None:
        targets = []
        for q in edges:
            a, b = parse_edge_query(q)
            fa, fb = self._faces_for(a), self._faces_for(b)
            # two DISTINCT faces: wall(F001) also matches wall(F001,r), and a cylinder's seam
            # is an edge "between" the face and itself (4C1229 F004)
            found = [e for x in fa for e in x.Edges()
                     if any(e.isSame(y) for g in fb if not g.isSame(x) for y in g.Edges())]
            if not found:
                raise CompileError(f"{fid}: {q} matched no edges")
            for e in found:
                if not any(e.isSame(t) for t in targets):
                    targets.append(e)
        k = self.k
        if operation == "fillet":
            new = self.solid.fillet(size * k, targets)
        else:
            d2 = size * k * math.tan(math.radians(angle))
            new = self.solid.chamfer(size * k, None if abs(angle - 45) < 1e-9 else d2, targets)
        self.edge_points[fid] = [[round(c / k, 6) for c in e.positionAt(0.5).toTuple()] for e in targets]
        self.tools[fid] = new
        self.order.append(fid)
        self.solid = new.clean()
        self.volume_after[fid] = round(self.solid.Volume() / k ** 3, 9)

    def contains(self, x: float, y: float, z: float) -> bool:
        """Is the point (drawing units) inside the solid? (tests, Gate 2 probes)"""
        k = self.k
        return self.solid.isInside(cq.Vector(x * k, y * k, z * k))

    def skip(self, fid: str, reason: str) -> None:
        self.skipped[fid] = reason

    # ------------------------------------------------------------ measure --
    def measure_holes(self) -> dict[str, list[dict]]:
        """Each planned hole instance matched to a cylindrical face of the RESULT."""
        out: dict[str, list[dict]] = {}
        cyl = [f for f in self.solid.Faces() if f.geomType() == "CYLINDER"]
        for fid, insts in self.holes.items():
            rows = []
            for h in insts:
                ax = h["axis"]
                i, j = [n for n in range(3) if n != _idx(ax)]
                best = None
                for f in cyl:
                    c = _cylinder(f)
                    r, loc, dirn = c.Radius(), c.Location(), c.Axis().Direction()
                    p = (loc.X(), loc.Y(), loc.Z())
                    if abs(abs((dirn.X(), dirn.Y(), dirn.Z())[_idx(ax)]) - 1) > 1e-6:
                        continue
                    dist = math.hypot(p[i] - h["center_mm"][i], p[j] - h["center_mm"][j])
                    if abs(2 * r - h["d_mm"]) < 1e-3 and dist < 1e-3 and (best is None or dist < best[0]):
                        bb = f.BoundingBox()
                        best = (dist, [p[i], p[j]], 2 * r, (bb.xlen, bb.ylen, bb.zlen)[_idx(ax)])
                k = self.k
                rows.append({
                    "planned_center": [round(h["center_mm"][i] / k, 6), round(h["center_mm"][j] / k, 6)],
                    "planned_d": round(h["d_mm"] / k, 6),
                    "measured": best is not None,
                    "center": [round(best[1][0] / k, 6), round(best[1][1] / k, 6)] if best else None,
                    "d": round(best[2] / k, 6) if best else None,
                    "depth": round(best[3] / k, 6) if best else None,
                    "axis": ax,
                })
            out[fid] = rows
        return out

    def feature_map(self) -> dict[str, Any]:
        bb = self.solid.BoundingBox()
        k = self.k
        return {
            "part": self.part, "units": self.units, "origin_kind": self.origin_kind,
            "bbox": [round(v / k, 6) for v in (bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax)],
            "volume": round(self.solid.Volume() / k ** 3, 6),
            "volume_mm3": round(self.solid.Volume(), 3),
            "features": self.order,
            "skipped": self.skipped,
            "holes": self.measure_holes(),
            "edge_points": self.edge_points,
            "starts": self.starts,
            "volume_after": self.volume_after,
            "base": self.base,
        }

    def finish(self, out_dir: Optional[str] = None) -> dict[str, Any]:
        if self.solid is None:
            raise CompileError("plan produced no solid")
        fmap = self.feature_map()
        if out_dir:
            out = Path(out_dir)
            out.mkdir(parents=True, exist_ok=True)
            cq.exporters.export(cq.Workplane().add(self.solid), str(out / "reference.step"))
            (out / "feature_map.json").write_text(json.dumps(fmap, indent=2), encoding="utf-8")
        return fmap
