"""BuildPlan (+ CadQuery feature map) -> native SolidWorks part over COM (IR v2, Task 6).

The CadQuery reference is the source of truth. This compiler replays the plan in
SolidWorks and **checks every feature against it**: after each feature, the part's
volume must match the reference's ``volume_after`` for that feature. A cut or boss in
the wrong direction is undone and retried the other way (direction-proof, error log
E005). A mismatch that survives is reported, never hidden.

Geometry comes from the feature map wherever the reference already resolved it:
start planes (``starts``), pattern hole centers (``holes``), and edge points for
fillets/chamfers (``edge_points``, selected by point with no manual picking; PRD A5).

New SolidWorks API usage, verified live on SW 2025 SP5 (2026-10-04, error log E018):
``FeatureRevolve2`` on the active sketch with a centerline; ``SelectByID2("", "EDGE",
x, y, z, ...)``; FeatureExtrusion3/FeatureCut4 start offsets. **The template's plane
mapping is measured, not assumed** (``probe_plane_map``): on the SW 2025 template here,
Front is model YZ with normal +X.

WINDOWS ONLY at call time; imports cleanly anywhere (COM is imported lazily).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from pipeline.ir.expr import evaluate
from pipeline.ir.model import BuildPlan, EdgeOp, Hole, Pattern, Prism, Revolve
from utils.logger import get_logger

log = get_logger()

PLANE_NAMES = ("Front Plane", "Top Plane", "Right Plane")
IR_AXIS_OF = {"front": "Z", "top": "Y", "right": "X"}
VOL_REL_TOL = 1e-3
UNIT_M = {"inch": 0.0254, "mm": 0.001}

Vec = tuple[float, float, float]


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _neg(a: Vec) -> Vec:
    return (-a[0], -a[1], -a[2])


@dataclass
class PlaneMap:
    """Model-space unit vectors (u, v, n) of each SW base plane's sketch axes."""
    planes: dict[str, tuple[Vec, Vec, Vec]]

    @property
    def ir_basis(self) -> tuple[Vec, Vec, Vec]:
        """IR x, y, z in model space: IR is defined by the Front sketch (u, v, normal)."""
        return self.planes["Front Plane"]

    def to_model(self, p: Vec) -> Vec:
        x, y, z = self.ir_basis
        return tuple(p[0] * x[i] + p[1] * y[i] + p[2] * z[i] for i in range(3))  # type: ignore

    def plane_for_ir_axis(self, axis: str) -> tuple[str, int]:
        """(SW plane name, sign) whose normal is +-IR axis; sign = +1 if it points along +axis."""
        want = self.ir_basis["XYZ".index(axis)]
        for name, (_, _, n) in self.planes.items():
            d = _dot(n, want)
            if abs(abs(d) - 1) < 1e-9:
                return name, (1 if d > 0 else -1)
        raise RuntimeError(f"no SolidWorks base plane is normal to IR {axis}")

    def sketch_coords(self, plane: str, p_model: Vec) -> tuple[float, float]:
        u, v, _ = self.planes[plane]
        return _dot(p_model, u), _dot(p_model, v)


def _unit(axis_idx: int, sign: float) -> Vec:
    v = [0.0, 0.0, 0.0]
    v[axis_idx] = 1.0 if sign > 0 else -1.0
    return tuple(v)  # type: ignore


def probe_plane_map(sw_app, template: Optional[str]) -> PlaneMap:
    """Measure each base plane's (u, v, n) in model space with a throwaway part:
    a 1 mm circle at sketch (10, 20) mm extruded 5 mm (default direction = +n)."""
    from pipeline.solidworks_builder import _g, _null_dispatch, create_new_part

    planes = {}
    for name in PLANE_NAMES:
        d = create_new_part(sw_app, template)
        try:
            d.ClearSelection2(True)
            if not d.Extension.SelectByID2(name, "PLANE", 0, 0, 0, False, 0, _null_dispatch(), 0):
                raise RuntimeError(f"could not select {name}")
            d.SketchManager.InsertSketch(True)
            d.SketchManager.CreateCircleByRadius(0.010, 0.020, 0, 0.001)
            d.SketchManager.InsertSketch(True)
            d.FeatureManager.FeatureExtrusion3(True, False, False, 0, 0, 0.005, 0.01, False, False, False, False,
                                               0, 0, False, False, False, False, True, True, True, 0, 0, False)
            bb = d.GetBodies2(0, False)[0].GetBodyBox()
        finally:
            sw_app.CloseDoc(_g(d, "GetTitle"))
        lo, hi = bb[:3], bb[3:]
        ext = [hi[i] - lo[i] for i in range(3)]
        n_idx = max(range(3), key=lambda i: ext[i])                 # 5 mm extrusion
        ctr = [(lo[i] + hi[i]) / 2 for i in range(3)]
        n = _unit(n_idx, 1 if hi[n_idx] > 0.004 else -1)
        u_idx = next(i for i in range(3) if i != n_idx and abs(abs(ctr[i]) - 0.010) < 1e-4)
        v_idx = next(i for i in range(3) if i not in (n_idx, u_idx))
        planes[name] = (_unit(u_idx, ctr[u_idx]), _unit(v_idx, ctr[v_idx]), n)
    log.info("SolidWorks plane map: %s", planes)
    return PlaneMap(planes)


@dataclass
class SwFeatureResult:
    fid: str
    status: str                    # built | skipped | failed | mismatch
    sw_volume: Optional[float] = None
    ref_volume: Optional[float] = None
    attempts: int = 0
    note: str = ""


@dataclass
class SwBuildReport:
    part: str
    sldprt: Optional[str]
    features: list[SwFeatureResult] = field(default_factory=list)
    bbox_ok: Optional[bool] = None
    volume_ok: Optional[bool] = None

    @property
    def ok(self) -> bool:
        return bool(self.bbox_ok and self.volume_ok and all(
            f.status in ("built", "skipped") for f in self.features))


class _SW:
    def __init__(self, sw_app, plan: BuildPlan, dims: dict[str, float], fmap: dict[str, Any],
                 pmap: PlaneMap, template: Optional[str]):
        from pipeline.solidworks_builder import create_new_part

        self.app, self.plan, self.dims, self.fmap, self.pm = sw_app, plan, dims, fmap, pmap
        self.k = UNIT_M[plan.frame.units]
        self.doc = create_new_part(sw_app, template)
        self.report = SwBuildReport(plan.part, None)

    # ---------------------------------------------------------------- utils --
    def n(self, expr) -> float:
        return evaluate(expr, self.dims).value

    def volume(self) -> float:
        from pipeline.solidworks_builder import _total_volume
        return _total_volume(self.doc) / self.k ** 3

    def select_plane(self, name: str) -> None:
        from pipeline.solidworks_builder import _null_dispatch
        self.doc.ClearSelection2(True)
        if not self.doc.Extension.SelectByID2(name, "PLANE", 0, 0, 0, False, 0, _null_dispatch(), 0):
            raise RuntimeError(f"could not select {name}")

    def sketch_on(self, ir_axis: str):
        """Open a sketch on the base plane normal to an IR axis; returns (plane, sign)."""
        plane, sign = self.pm.plane_for_ir_axis(ir_axis)
        self.select_plane(plane)
        self.doc.SketchManager.InsertSketch(True)
        return plane, sign

    def pt(self, plane: str, ir_point: Vec) -> tuple[float, float]:
        m = self.pm.to_model(tuple(c * self.k for c in ir_point))  # type: ignore
        return self.pm.sketch_coords(plane, m)

    def in_plane(self, axis: str, a: float, b: float) -> Vec:
        """IR point from in-plane coords (u, v) of an IR axis plane (front: x,y; top: x,z; right: y,z)."""
        return {"Z": (a, b, 0.0), "Y": (a, 0.0, b), "X": (0.0, a, b)}[axis]  # type: ignore

    def check(self, fid: str, attempt: int) -> bool:
        ref = self.fmap.get("volume_after", {}).get(fid)
        got = self.volume()
        if ref is None:
            return True
        ok = abs(got - ref) <= max(VOL_REL_TOL * abs(ref), 1e-6)
        log.info("  %s: SW volume %.6f vs reference %.6f (%s, attempt %d)", fid, got, ref,
                 "ok" if ok else "MISMATCH", attempt)
        return ok

    def extrude(self, *, cut: bool, reverse: bool, depth: Optional[float], start: float,
                thru: bool = False):
        fm = self.doc.FeatureManager
        t0, off, flip = (3, abs(start), start < 0) if abs(start) > 1e-12 else (0, 0.0, False)
        if cut:
            # thru = Through All (T1=1) FROM the resolved start face, into the material.
            # Through All - Both from the base plane fails when that plane misses the body
            # (SB11033's holes: Front plane is the pilot end, r = .781 is empty there; E018).
            return fm.FeatureCut4(True, False, reverse, 1 if thru else 0, 0, depth or 0.0, 0.01,
                                  False, False, False, False, 0.0, 0.0, False, False, False, False, False,
                                  True, True, True, True, False, t0, off, flip, False)
        return fm.FeatureExtrusion3(True, False, reverse, 0, 0, depth, 0.01, False, False, False, False,
                                    0.0, 0.0, False, False, False, False, True, True, True, t0, off, flip)

    def with_retry(self, fid: str, make, flippable: bool = True):
        """make(flip) creates the feature from the closed sketch. Volume-checked, retried flipped."""
        from pipeline.solidworks_builder import _reselect_last_sketch
        res = SwFeatureResult(fid, "failed", ref_volume=self.fmap.get("volume_after", {}).get(fid))
        for attempt, flip in enumerate((False, True) if flippable else (False,), start=1):
            if attempt > 1:
                _reselect_last_sketch(self.doc)
            feat = make(flip)
            res.attempts = attempt
            if feat is not None and self.check(fid, attempt):
                res.status, res.sw_volume = "built", self.volume()
                return res
            if feat is not None:
                self.doc.EditUndo2(1)
        res.sw_volume = self.volume()
        res.status = "mismatch" if res.attempts else "failed"
        res.note = "no direction matched the reference volume"
        return res

    # -------------------------------------------------------------- features --
    def prism(self, f: Prism) -> SwFeatureResult:
        st = self.fmap["starts"][f.id]
        axis, coord, d = st["axis"], st["coord"], st["dir"]
        plane, sign = self.sketch_on(axis)
        sm = self.doc.SketchManager
        p = f.profile
        if p.shape == "rect":
            w, h, u, v = self.n(p.w), self.n(p.h), self.n(p.u), self.n(p.v)
            if p.anchor == "center":
                u, v = u - w / 2, v - h / 2
            corners = [self.pt(plane, self.in_plane(axis, a, b)) for a, b in ((u, v), (u + w, v + h))]
            (x1, y1), (x2, y2) = corners
            sm.CreateCornerRectangle(x1, y1, 0, x2, y2, 0)
        elif p.shape == "circle":
            cx, cy = self.pt(plane, self.in_plane(axis, self.n(p.u), self.n(p.v)))
            sm.CreateCircleByRadius(cx, cy, 0, self.n(p.d) * self.k / 2)
        else:
            sm.InsertSketch(True)
            return SwFeatureResult(f.id, "failed", note=f"profile {p.shape} not compiled for SolidWorks yet")
        sm.InsertSketch(True)
        start = coord * self.k * sign
        thru = st.get("thru", False)
        depth = None if thru else self.n(f.depth) * self.k
        return self.with_retry(f.id, lambda flip: self.extrude(
            cut=f.op == "cut", reverse=((d * sign) < 0) != flip, depth=depth, start=start, thru=thru))

    def holes(self, fid: str, centers: list[list[float]], spec: dict, axis: str, coord: float, d: int):
        plane, sign = self.sketch_on(axis)
        sm = self.doc.SketchManager

        def circles(dia):
            for c in centers:
                x, y = self.pt(plane, self.in_plane(axis, c[0], c[1]))
                sm.CreateCircleByRadius(x, y, 0, dia * self.k / 2)
            sm.InsertSketch(True)

        circles(self.n(spec.d))
        start = coord * self.k * sign
        thru = spec.type == "thru" or (spec.type == "cbore" and spec.depth is None)
        depth = None if thru else self.n(spec.depth) * self.k

        def drill(flip):
            return self.extrude(cut=True, reverse=((d * sign) < 0) != flip, depth=depth, start=start, thru=thru)

        if not (spec.type == "cbore" and spec.cbore_d):
            return self.with_retry(fid, drill)
        # Counterbore: the reference volume includes BOTH cuts, so verify only after the
        # second one. The drill direction is validated by its own volume drop first.
        from pipeline.solidworks_builder import _reselect_last_sketch
        before = self.volume()
        feat = drill(False)
        if feat is None or self.volume() >= before - 1e-12:
            if feat is not None:
                self.doc.EditUndo2(1)
            _reselect_last_sketch(self.doc)
            feat = drill(True)
        if feat is None or self.volume() >= before - 1e-12:
            return SwFeatureResult(fid, "failed", note="counterbore drill removed no material")
        self.sketch_on(axis)
        circles(self.n(spec.cbore_d))
        res = self.with_retry(fid, lambda flip: self.extrude(
            cut=True, reverse=((d * sign) < 0) != flip, depth=self.n(spec.cbore_depth) * self.k, start=start))
        res.note = "drill + counterbore"
        return res

    def hole(self, f: Hole) -> SwFeatureResult:
        st = self.fmap["starts"][f.id]
        return self.holes(f.id, [[self.n(f.u), self.n(f.v)]], f.spec, st["axis"], st["coord"], st["dir"])

    def pattern(self, f: Pattern) -> SwFeatureResult:
        seed = self.plan.feature(f.seed)
        if not isinstance(seed, Hole):
            return SwFeatureResult(f.id, "failed", note="only hole patterns are compiled for SolidWorks yet")
        st = self.fmap["starts"][seed.id]
        centers = [h["planned_center"] for h in self.fmap["holes"].get(f.id, [])]
        return self.holes(f.id, centers, seed.spec, st["axis"], st["coord"], st["dir"])

    def revolve(self, f: Revolve) -> SwFeatureResult:
        # sketch on the base plane that contains IR z and IR x (normal = IR y)
        plane, _ = self.sketch_on("Y")
        sm = self.doc.SketchManager
        outer = [(self.n(s.z), self.n(s.r)) for s in f.outer]
        inner = [(self.n(s.z), self.n(s.r)) for s in f.inner]
        if inner:
            loop = outer + list(reversed(inner))
        else:
            loop = [(outer[0][0], 0.0)] + outer + [(outer[-1][0], 0.0)]
        loop = [p for i, p in enumerate(loop) if i == 0 or p != loop[i - 1]]
        pts = [self.pt(plane, (r, 0.0, z)) for z, r in loop]
        for a, b in zip(pts, pts[1:] + pts[:1]):
            if a != b:
                sm.CreateLine(a[0], a[1], 0, b[0], b[1], 0)
        zs = [z for z, _ in loop]
        c1 = self.pt(plane, (0.0, 0.0, min(zs) - 1.0))
        c2 = self.pt(plane, (0.0, 0.0, max(zs) + 1.0))
        sm.CreateCenterLine(c1[0], c1[1], 0, c2[0], c2[1], 0)
        res = SwFeatureResult(f.id, "failed", ref_volume=self.fmap.get("volume_after", {}).get(f.id), attempts=1)
        feat = self.doc.FeatureManager.FeatureRevolve2(
            True, True, False, f.op == "cut", False, False, 0, 0, 2 * math.pi, 0,
            False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
        if feat is not None and self.check(f.id, 1):
            res.status = "built"
        else:
            res.status = "mismatch" if feat is not None else "failed"
        res.sw_volume = self.volume()
        return res

    def nearest_edge(self, m: Vec):
        """The body edge closest to a model-space point, by true 3D distance.

        NOT ``SelectByID2("", "EDGE", x, y, z)``: that is a ray pick along the current view,
        and it picks whichever edge the ray hits first. On A040911E the z = 0 bore edge
        selected the z = 1.5 one behind it (error log E018).
        """
        from pipeline.solidworks_builder import _g
        best, best_d = None, float("inf")
        for body in self.doc.GetBodies2(0, False) or ():
            for e in _g(body, "GetEdges") or ():
                q = e.GetClosestPointOn(m[0], m[1], m[2])
                d = math.dist(m, (q[0], q[1], q[2]))
                if d < best_d:
                    best, best_d = e, d
        return best, best_d

    def edge_op(self, f: EdgeOp) -> SwFeatureResult:
        from pipeline.solidworks_builder import _empty_variant, _g
        pts = self.fmap.get("edge_points", {}).get(f.id, [])
        self.doc.ClearSelection2(True)
        data = _g(self.doc.SelectionManager, "CreateSelectData")
        picked = []
        for p in pts:
            m = self.pm.to_model(tuple(c * self.k for c in p))  # type: ignore
            e, dist = self.nearest_edge(m)
            if e is None or dist > 1e-5:
                return SwFeatureResult(f.id, "failed", note=f"no edge within 0.01 mm of {p} (nearest {dist:.2e} m)")
            if any(e is x for x in picked):
                continue
            e.Select4(True, data)
            picked.append(e)
        got = self.doc.SelectionManager.GetSelectedObjectCount2(-1)
        if got != len(pts):
            return SwFeatureResult(f.id, "failed", note=f"selected {got} of {len(pts)} edges")
        size = self.n(f.size) * self.k
        fm = self.doc.FeatureManager
        if f.operation == "fillet":
            feat = fm.FeatureFillet3(195, size, 0.0, 0.0, 0, 0, 0, *[_empty_variant() for _ in range(7)])
        else:
            feat = fm.InsertFeatureChamfer(4, 1, size, math.radians(self.n(f.angle)), 0, 0, 0, 0)
        ok = feat is not None and self.check(f.id, 1)
        return SwFeatureResult(f.id, "built" if ok else ("mismatch" if feat is not None else "failed"),
                               sw_volume=self.volume(),
                               ref_volume=self.fmap.get("volume_after", {}).get(f.id), attempts=1,
                               note=f"{len(pts)} edges selected by nearest point")


def compile_solidworks(sw_app, plan: BuildPlan, dims: dict[str, float], fmap: dict[str, Any],
                       out_dir: Path, template: Optional[str] = None,
                       pmap: Optional[PlaneMap] = None) -> SwBuildReport:
    """Build the plan in SolidWorks, verifying each feature against the CadQuery reference."""
    from pipeline.solidworks_builder import _close_open_sketch, save_model

    pmap = pmap or probe_plane_map(sw_app, template)
    sw = _SW(sw_app, plan, dims, fmap, pmap, template)
    skipped = fmap.get("skipped", {})
    for f in plan.features:
        if f.status != "planned" or f.id in skipped:
            sw.report.features.append(SwFeatureResult(f.id, "skipped", note=skipped.get(f.id, f.status)))
            continue
        try:
            res = getattr(sw, f.kind)(f)
        except Exception as e:  # COM errors: record, keep building (non-strict, like v1)
            _close_open_sketch(sw.doc)
            res = SwFeatureResult(f.id, "failed", note=f"{type(e).__name__}: {e}"[:300])
        log.info("  %s %s: %s %s", f.id, f.kind, res.status, res.note)
        sw.report.features.append(res)

    vol = sw.volume()
    sw.report.volume_ok = abs(vol - fmap["volume"]) <= max(VOL_REL_TOL * fmap["volume"], 1e-6)
    bodies = sw.doc.GetBodies2(0, False)
    if bodies:
        bb = bodies[0].GetBodyBox()
        ext = sorted((bb[i + 3] - bb[i]) / sw.k for i in range(3))
        ref = sorted(fmap["bbox"][i + 3] - fmap["bbox"][i] for i in range(3))
        sw.report.bbox_ok = all(abs(a - b) <= 1e-4 * max(1.0, b) for a, b in zip(ext, ref))
    sw.report.sldprt = save_model(sw.doc, f"{plan.part}_ir", out_dir)
    try:  # an isometric picture for review (best effort)
        sw.doc.ShowNamedView2("*Isometric", 7)
        sw.doc.ViewZoomtofit2()
        sw.doc.SaveAs3(str((Path(out_dir) / f"{plan.part}_ir.png").resolve()), 0, 1)
    except Exception as e:
        log.warning("Could not export a PNG view: %s", e)
    return sw.report
