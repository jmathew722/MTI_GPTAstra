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

**MTI modeling convention** (``convention="mti"``, the default; spec
docs/superpowers/specs/2026-10-11-mti-modeling-standards-design.md): the plan stays in
the drawing frame, and the compiler maps it rigidly into SolidWorks so that the base
sketch is on the **Top plane**, the base body is **centered on the origin** (symmetric
about Front, Top and Right), and the base extrusion is **Mid Plane**. Through cuts are
**Up To Next**. Every one of these is verified by volume and falls back to the previous
behaviour (offset start, Through All) when SolidWorks disagrees. ``convention="drawing"``
keeps the old frame (IR = Front sketch axes, drawing origin).

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
CONVENTIONS = ("mti", "drawing")
# swEndConditions_e, read from swconst.tlb (SW 2025). Up To Next is 11: HoleWizard5 rejects
# 2 (swEndCondThroughNext), and 11 is what SolidWorks stores and labels "Up To Next".
END_THROUGH_ALL, END_UP_TO_NEXT, END_MID_PLANE = 1, 11, 6

# Hole Wizard (HoleWizard5, signature and enums read from sldworks.tlb / swconst.tlb and
# verified live on SW 2025 SP5, 2026-10-11; error log E021).
HW_TYPE = {"hole": 2, "cbore": 0}                        # swWzdHole, swWzdCounterBore
HW_STANDARD = {"inch": 0, "metric": 1}                   # swStandardAnsiInch, swStandardAnsiMetric
HW_FASTENER = {("hole", "inch"): 22, ("hole", "metric"): 40,     # ... ScrewClearances
               ("cbore", "inch"): 9, ("cbore", "metric"): 33}    # ... SocketCapScrew / SocketHeadCapScrew
UNIT_M = {"inch": 0.0254, "mm": 0.001}

Vec = tuple[float, float, float]


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _neg(a: Vec) -> Vec:
    return (-a[0], -a[1], -a[2])


def _det(a: Vec, b: Vec, c: Vec) -> float:
    return (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0]))


@dataclass
class PlaneMap:
    """Model-space unit vectors (u, v, n) of each SW base plane's sketch axes."""
    planes: dict[str, tuple[Vec, Vec, Vec]]
    basis: Optional[tuple[Vec, Vec, Vec]] = None   # IR x, y, z in model space (None = Front)

    @property
    def ir_basis(self) -> tuple[Vec, Vec, Vec]:
        """IR x, y, z in model space: by default the Front sketch (u, v, normal)."""
        return self.basis or self.planes["Front Plane"]

    def oriented(self, base_axis: str) -> "PlaneMap":
        """The same planes with the IR rotated so ``base_axis`` is the Top plane's normal
        (MTI: the base sketch is on the Top plane). A cyclic axis permutation, so the
        mapping stays a rotation, never a mirror."""
        u, v, n = self.planes["Top Plane"]
        if _det(u, v, n) <= 0:
            raise RuntimeError("Top plane axes are not right-handed; refusing a mirrored part")
        basis = {"Z": (u, v, n), "Y": (v, n, u), "X": (n, u, v)}[base_axis]
        return PlaneMap(self.planes, basis)

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
    from pipeline.solidworks_builder import _g, create_new_part, select_ref_plane

    planes = {}
    for name in PLANE_NAMES:
        d = create_new_part(sw_app, template)
        try:
            if not select_ref_plane(d, name):
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
    convention: str = "drawing"
    origin_ok: Optional[bool] = None   # MTI: base body centered on the origin (None = not checked)
    conventions: list[str] = field(default_factory=list)   # applied / fell back, for review

    @property
    def ok(self) -> bool:
        return bool(self.bbox_ok and self.volume_ok and self.origin_ok is not False and all(
            f.status in ("built", "skipped") for f in self.features))


class _SW:
    def __init__(self, sw_app, plan: BuildPlan, dims: dict[str, float], fmap: dict[str, Any],
                 pmap: PlaneMap, template: Optional[str], convention: str = "drawing"):
        from pipeline.solidworks_builder import create_new_part

        self.app, self.plan, self.dims, self.fmap = sw_app, plan, dims, fmap
        self.k = UNIT_M[plan.frame.units]
        self.convention = convention
        self.base = fmap.get("base") if convention == "mti" else None
        self.shift: Vec = (0.0, 0.0, 0.0)   # IR point of the model origin (base body center)
        if self.base:
            pmap = pmap.oriented(base_axis(plan, fmap))
            bb = self.base["bbox"]
            self.shift = tuple((bb[i] + bb[i + 3]) / 2 for i in range(3))  # type: ignore
        self.pm = pmap
        self.doc = create_new_part(sw_app, template)
        # Sketch entities go straight into the database: no inference snapping. With a
        # centered origin, a hole .005" off the origin snapped onto it (115-C F006, E020).
        self.doc.SketchManager.AddToDB = True
        self.report = SwBuildReport(plan.part, None, convention="mti" if self.base else "drawing")
        self.flips: dict[str, bool] = {}   # direction each feature was verified with (pattern copies reuse it)

    # ---------------------------------------------------------------- utils --
    def n(self, expr) -> float:
        return evaluate(expr, self.dims).value

    def volume(self) -> float:
        from pipeline.solidworks_builder import _total_volume
        return _total_volume(self.doc) / self.k ** 3

    def select_plane(self, name: str) -> None:
        from pipeline.solidworks_builder import select_ref_plane
        if not select_ref_plane(self.doc, name):
            raise RuntimeError(f"could not select {name}")

    def local(self, p) -> Vec:
        """IR (drawing-frame) point -> IR point relative to the model origin."""
        return tuple(p[i] - self.shift[i] for i in range(3))  # type: ignore

    def sketch_on(self, ir_axis: str):
        """Open a sketch on the base plane normal to an IR axis; returns (plane, sign)."""
        plane, sign = self.pm.plane_for_ir_axis(ir_axis)
        self.select_plane(plane)
        self.doc.SketchManager.InsertSketch(True)
        return plane, sign

    def pt(self, plane: str, ir_point: Vec) -> tuple[float, float]:
        m = self.pm.to_model(tuple(c * self.k for c in self.local(ir_point)))  # type: ignore
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
                thru: bool = False, end: Optional[int] = None):
        """``end`` overrides the end condition (Up To Next, Mid Plane); the default is
        Blind, or Through All when ``thru``."""
        fm = self.doc.FeatureManager
        t0, off, flip = (3, abs(start), start < 0) if abs(start) > 1e-12 else (0, 0.0, False)
        t1 = end if end is not None else (END_THROUGH_ALL if thru else 0)
        if cut:
            # thru = FROM the resolved start face, into the material (Up To Next per MTI,
            # else Through All). Through All - Both from the base plane fails when that
            # plane misses the body (SB11033's holes: r = .781 is empty there; E018).
            return fm.FeatureCut4(True, False, reverse, t1, 0, depth or 0.0, 0.01,
                                  False, False, False, False, 0.0, 0.0, False, False, False, False, False,
                                  True, True, True, True, False, t0, off, flip, False)
        return fm.FeatureExtrusion3(True, False, reverse, t1, 0, depth, 0.01, False, False, False, False,
                                    0.0, 0.0, False, False, False, False, True, True, True, t0, off, flip)

    def thru_cut(self, fid: str, make):
        """A through cut: Up To Next first (MTI), Through All when the volume says it
        stopped short (a hole crossing a gap or pocket). ``make(flip, end)``."""
        from pipeline.solidworks_builder import _reselect_last_sketch
        modes = [(END_THROUGH_ALL, "Through All")]
        if self.convention == "mti":
            modes.insert(0, (END_UP_TO_NEXT, "Up To Next"))
        res = None
        for i, (end, label) in enumerate(modes):
            if i:
                _reselect_last_sketch(self.doc)
            res = self.with_retry(fid, lambda fl, end=end: make(fl, end))
            if res.status == "built":
                res.note = label
                if i:
                    self.report.conventions.append(f"{fid}: Up To Next did not match; used Through All")
                return res
        return res

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
                self.flips[fid] = flip
                return res
            if feat is not None:
                self.doc.EditUndo2(1)
        res.sw_volume = self.volume()
        res.status = "mismatch" if res.attempts else "failed"
        res.note = "no direction matched the reference volume"
        return res

    # -------------------------------------------------------------- features --
    def prism(self, f: Prism, shift: Vec = (0.0, 0.0, 0.0), flip: Optional[bool] = None) -> SwFeatureResult:
        """Build a prism; ``shift`` (IR units) and a fixed ``flip`` are used for pattern copies."""
        st = self.fmap["starts"][f.id]
        axis, coord, d = st["axis"], st["coord"], st["dir"]
        ai = "XYZ".index(axis)
        coord += shift[ai] - self.shift[ai]
        su, sv = [shift[i] for i in range(3) if i != ai]
        plane, sign = self.sketch_on(axis)
        sm = self.doc.SketchManager
        p = f.profile
        if p.shape == "rect":
            w, h, u, v = self.n(p.w), self.n(p.h), self.n(p.u) + su, self.n(p.v) + sv
            if p.anchor == "center":
                u, v = u - w / 2, v - h / 2
            corners = [self.pt(plane, self.in_plane(axis, a, b)) for a, b in ((u, v), (u + w, v + h))]
            (x1, y1), (x2, y2) = corners
            if self.base and abs(x1 + x2) < 1e-9 and abs(y1 + y2) < 1e-9:
                sm.CreateCenterRectangle(0, 0, 0, x2, y2, 0)   # centered on the origin (MTI)
            else:
                sm.CreateCornerRectangle(x1, y1, 0, x2, y2, 0)
        elif p.shape == "circle":
            cx, cy = self.pt(plane, self.in_plane(axis, self.n(p.u) + su, self.n(p.v) + sv))
            sm.CreateCircleByRadius(cx, cy, 0, self.n(p.d) * self.k / 2)
        else:
            sm.InsertSketch(True)
            return SwFeatureResult(f.id, "failed", note=f"profile {p.shape} not compiled for SolidWorks yet")
        sm.InsertSketch(True)
        start = coord * self.k * sign
        thru = st.get("thru", False)
        depth = None if thru else self.n(f.depth) * self.k

        def make(fl, end=None):
            return self.extrude(cut=f.op == "cut", reverse=((d * sign) < 0) != fl, depth=depth,
                                start=start, thru=thru, end=end)

        if flip is not None:   # a pattern copy: same direction as the verified seed, checked as a whole
            feat = make(flip)
            return SwFeatureResult(f.id, "built" if feat is not None else "failed", attempts=1)
        if (self.base and f.id == self.base["fid"] and depth
                and abs(coord + d * self.n(f.depth) / 2) < 1e-9):
            res = self.mid_plane(f.id, depth)
            if res is not None:
                return res
        if thru and f.op == "cut":
            return self.thru_cut(f.id, make)
        return self.with_retry(f.id, make)

    def mid_plane(self, fid: str, depth: float) -> Optional[SwFeatureResult]:
        """MTI base body: sketch on the plane through the origin, extrude Mid Plane.
        Returns None (sketch reselected, for the offset-start fallback) if the volume
        does not match."""
        from pipeline.solidworks_builder import _reselect_last_sketch
        feat = self.extrude(cut=False, reverse=False, depth=depth, start=0.0, end=END_MID_PLANE)
        if feat is not None and self.check(fid, 1):
            self.flips[fid] = False
            self.report.conventions.append(f"{fid}: base sketch on the Top plane, Mid Plane extrude")
            return SwFeatureResult(fid, "built", sw_volume=self.volume(),
                                   ref_volume=self.fmap.get("volume_after", {}).get(fid), attempts=1,
                                   note="Mid Plane")
        if feat is not None:
            self.doc.EditUndo2(1)
        _reselect_last_sketch(self.doc)
        self.report.conventions.append(f"{fid}: Mid Plane did not match; used an offset start")
        return None

    def holes(self, fid: str, centers: list[list[float]], spec: dict, axis: str, coord: float, d: int):
        if self.convention == "mti":
            choice = hole_wizard_choice(spec, self.dims, self.plan.frame.units)
            if choice:
                res = self.hole_wizard(fid, centers, spec, axis, coord, d, choice)
                if res is not None:
                    return res
        coord -= self.shift["XYZ".index(axis)]
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

        def drill(flip, end=None):
            return self.extrude(cut=True, reverse=((d * sign) < 0) != flip, depth=depth, start=start,
                                thru=thru, end=end)

        if not (spec.type == "cbore" and spec.cbore_d):
            return self.thru_cut(fid, drill) if thru else self.with_retry(fid, drill)
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

    def hole_wizard(self, fid: str, centers: list[list[float]], spec, axis: str, coord: float, d: int,
                    choice: dict) -> Optional[SwFeatureResult]:
        """One Hole Wizard feature for every center (MTI: same size on a face = one feature).

        Recipe (verified live, error log E021): pick the start face with a ray cast into
        the material at the first center, ``HoleWizard5`` (Up To Next, the drawing's
        diameters), then edit its placement sketch: set the first point exactly and add
        the rest. Points are read back and the volume is checked against the reference.
        On any mismatch the feature is deleted and None is returned (plain-cut fallback).
        """
        ai = "XYZ".index(axis)

        def model_pt(c) -> Vec:
            p = list(self.in_plane(axis, c[0], c[1]))
            p[ai] = coord
            return self.pm.to_model(tuple(v * self.k for v in self.local(p)))  # type: ignore

        into = self.pm.to_model(tuple(float(d) if i == ai else 0.0 for i in range(3)))  # type: ignore
        before = self.volume()
        p0 = model_pt(centers[0])
        self.doc.ClearSelection2(True)
        eps = 1e-3   # start the ray 1 mm outside the face, cast into the material
        if not self.doc.Extension.SelectByRay(*(p0[i] - into[i] * eps for i in range(3)), *into,
                                               1e-5, 2, False, 0, 0):   # swSelFACES
            self.report.conventions.append(f"{fid}: no start face under the hole; plain cut")
            return None
        vals = [v * self.k if v != -1.0 else -1.0 for v in choice["values"]]
        feat = self.doc.FeatureManager.HoleWizard5(
            choice["type"], choice["standard"], choice["fastener"], choice["size"], END_UP_TO_NEXT,
            self.n(spec.d) * self.k, 0.0, -1.0, *vals, "", False, True, True, True, True, False)
        if feat is None:
            self.report.conventions.append(f"{fid}: HoleWizard5 refused {choice['label']}; plain cut")
            return None
        placed = self.place_hole_points(feat, [model_pt(c) for c in centers])
        if placed and self.check(fid, 1):
            res = SwFeatureResult(fid, "built", sw_volume=self.volume(),
                                  ref_volume=self.fmap.get("volume_after", {}).get(fid), attempts=1,
                                  note=f"{choice['label']}, Up To Next, {len(centers)} hole(s)")
            self.report.conventions.append(f"{fid}: {res.note}")
            return res
        from pipeline.solidworks_builder import typed
        self.doc.ClearSelection2(True)
        typed(feat, "IFeature").Select2(False, 0)
        self.doc.Extension.DeleteSelection2(2)   # swDelete_Absorbed: the feature and its sketches
        if abs(self.volume() - before) > 1e-9:
            raise RuntimeError(f"{fid}: could not remove the mismatched Hole Wizard feature")
        self.report.conventions.append(f"{fid}: {choice['label']} did not match the reference "
                                       f"({'volume' if placed else 'points'}); plain cut")
        return None

    def place_hole_points(self, feat, model_pts: list[Vec]) -> bool:
        """Put the Hole Wizard placement sketch's points exactly at ``model_pts``."""
        from pipeline.solidworks_builder import _g, com_doubles, typed
        sub, best = typed(feat, "IFeature").GetFirstSubFeature(), None
        while sub is not None:   # placement sketch = the sub-sketch with the fewest points
            sf = typed(sub, "IFeature")
            sk = typed(sf.GetSpecificFeature2(), "ISketch")
            if best is None or sk.GetSketchPointsCount2() < best[1].GetSketchPointsCount2():
                best = (sf, sk)
            sub = sf.GetNextSubFeature()
        if best is None:
            return False
        sf, sk = best
        xf = sk.ModelToSketchTransform
        mu = typed(_g(self.app, "GetMathUtility"), "IMathUtility")

        def to_sketch(m):
            a = typed(typed(mu.CreatePoint(com_doubles(*m)), "IMathPoint").MultiplyTransform(xf),
                      "IMathPoint").ArrayData
            return a[0], a[1]

        want = [to_sketch(m) for m in model_pts]
        sm = self.doc.SketchManager
        self.doc.ClearSelection2(True)
        sf.Select2(False, 0)
        self.doc.EditSketch()
        sm.AddToDB = False   # Hole Wizard only picks up points added this way (E021)
        try:
            pts = sk.GetSketchPoints2() or ()
            if len(pts) != 1:
                return False
            typed(pts[0], "ISketchPoint").SetCoords(want[0][0], want[0][1], 0.0)
            for x, y in want[1:]:
                # SetCoords after creating: with AddToDB off, inference can snap a point
                # .005" off an axis onto it (117-C; same cause as E020)
                pt = sm.CreatePoint(x, y, 0.0)
                if pt is not None:
                    typed(pt, "ISketchPoint").SetCoords(x, y, 0.0)
        finally:
            sm.InsertSketch(True)
            sm.AddToDB = True
        got = sorted((p.X, p.Y) for p in (typed(q, "ISketchPoint") for q in (sk.GetSketchPoints2() or ())))
        ok = len(got) == len(want) and all(math.dist(a, b) <= 1e-7 for a, b in zip(got, sorted(want)))
        if not ok:
            log.info("  Hole Wizard points: wanted %s, got %s (m, sketch)", sorted(want), got)
        return ok

    def hole_group(self, group: list[Hole]) -> SwFeatureResult:
        """Identical consecutive holes on one face as ONE feature (MTI practice), verified
        against the reference volume after the last of them."""
        st = self.fmap["starts"][group[0].id]
        centers = [[self.n(g.u), self.n(g.v)] for g in group]
        return self.holes(group[-1].id, centers, group[0].spec, st["axis"], st["coord"], st["dir"])

    def hole(self, f: Hole) -> SwFeatureResult:
        st = self.fmap["starts"][f.id]
        return self.holes(f.id, [[self.n(f.u), self.n(f.v)]], f.spec, st["axis"], st["coord"], st["dir"])

    def pattern(self, f: Pattern) -> SwFeatureResult:
        seed = self.plan.feature(f.seed)
        if isinstance(seed, Prism) and f.mode in ("linear", "grid"):
            return self.prism_pattern(f, seed)
        if not isinstance(seed, Hole):
            return SwFeatureResult(f.id, "failed", note="only hole patterns and linear/grid prism "
                                                        "patterns are compiled for SolidWorks yet")
        st = self.fmap["starts"][seed.id]
        centers = [h["planned_center"] for h in self.fmap["holes"].get(f.id, [])]
        return self.holes(f.id, centers, seed.spec, st["axis"], st["coord"], st["dir"])

    def prism_pattern(self, f: Pattern, seed: Prism) -> SwFeatureResult:
        """Linear/grid copies of a prism seed: replayed shifted, then verified as a whole."""
        unit = {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}

        def vec(direction: str, dist: float) -> Vec:
            s = 1 if direction[0] == "+" else -1
            return tuple(s * dist * c for c in unit[direction[1]])  # type: ignore

        n1, p1 = int(round(self.n(f.count))), self.n(f.pitch)
        n2, p2 = (int(round(self.n(f.count2))), self.n(f.pitch2)) if f.mode == "grid" else (1, 0.0)
        flip = self.flips.get(seed.id, False)
        k = 0
        for j in range(n2):
            for i in range(n1):
                if (i, j) != (0, 0) and k not in f.skip:
                    a, b = vec(f.dir, i * p1), vec(f.dir2, j * p2)
                    r = self.prism(seed, shift=tuple(a[m] + b[m] for m in range(3)), flip=flip)  # type: ignore
                    if r.status != "built":
                        return SwFeatureResult(f.id, "failed", note=f"copy {i},{j} failed")
                k += 1
        ok = self.check(f.id, 1)
        return SwFeatureResult(f.id, "built" if ok else "mismatch", sw_volume=self.volume(),
                               ref_volume=self.fmap.get("volume_after", {}).get(f.id), attempts=1,
                               note="prism copies")

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
            m = self.pm.to_model(tuple(c * self.k for c in self.local(p)))  # type: ignore
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


def hole_wizard_choice(spec, dims: dict[str, float], units: str) -> Optional[dict]:
    """The Hole Wizard feature for a planned hole, or None to keep a plain cut (MTI:
    Hole Wizard for bolt holes, cut-extrude for everything else).

    A bolt hole is a clearance hole (optionally counterbored) whose diameter is a
    clearance size in MTI Std 202.02.0003. It is built Up To Next. A hole planned with a
    depth is tried too (plans often drill "to the full thickness"); the volume check keeps
    the Hole Wizard feature only if the hole really goes through, otherwise the caller
    deletes it and cuts a plain blind hole. Not Hole Wizard: tapped holes (Hole Wizard
    cuts the thread major diameter by default), and any hole when the local MTI table is
    absent. The drawing's diameters are always used; the screw size records intent.
    """
    from pipeline import mti_standards
    if spec.thread or spec.type not in ("thru", "blind", "cbore"):
        return None
    kind = "cbore" if spec.type == "cbore" else "hole"
    if kind == "cbore" and not (spec.cbore_d and spec.cbore_depth):
        return None
    d = evaluate(spec.d, dims).value
    match = mti_standards.match_hole(d, units, ("clearance_normal", "clearance_loose"))
    if not match:
        return None
    best = match[0]
    values = [-1.0] * 12
    if kind == "cbore":   # Value1 = counterbore diameter, Value2 = depth (drawing units here)
        values[0], values[1] = evaluate(spec.cbore_d, dims).value, evaluate(spec.cbore_depth, dims).value
    return {"kind": kind, "type": HW_TYPE[kind], "standard": HW_STANDARD[best.system],
            "fastener": HW_FASTENER[(kind, best.system)], "size": best.size, "values": values,
            "label": f"Hole Wizard {best.size} {'SHCS counterbore' if kind == 'cbore' else 'clearance'}"}


def hole_signature(f: Hole, dims: dict[str, float]) -> tuple:
    """Holes that are the same hole on the same face (MTI: one Hole Wizard feature)."""
    sp = f.spec

    def v(e):
        return None if e is None else round(evaluate(e, dims).value, 9)
    return (f.on.replace(" ", ""), sp.type, v(sp.d), v(sp.depth), v(sp.cbore_d), v(sp.cbore_depth),
            v(sp.csink_d), v(sp.csink_angle), sp.thread)


def mergeable_holes(rest: list, first: Hole, dims: dict[str, float], skipped: dict) -> list[Hole]:
    """The holes right after ``first`` that are the same hole on the same face. Only
    consecutive ones: the merged feature is checked against the last one's reference
    volume, which is only valid when nothing else was built in between."""
    out = []
    sig = hole_signature(first, dims)
    for g in rest:
        if not (isinstance(g, Hole) and g.status == "planned" and g.id not in skipped
                and hole_signature(g, dims) == sig):
            break
        out.append(g)
    return out


def base_axis(plan: BuildPlan, fmap: dict[str, Any]) -> str:
    """IR axis normal to the base feature's sketch: a prism's extrusion axis, or IR Y for a
    revolve (its profile is sketched on the plane through the axis, normal to IR Y)."""
    fid = (fmap.get("base") or {}).get("fid")
    f = plan.feature(fid) if fid else None
    if isinstance(f, Revolve):
        return "Y"
    st = fmap.get("starts", {}).get(fid)
    return st["axis"] if st else "Z"


def origin_centered(bbox: list[float], tol_m: float = 1e-6) -> bool:
    """MTI: the base body is symmetric about the three base planes (box centered on the
    origin). ``bbox`` is a SolidWorks body box in meters."""
    return all(abs(bbox[i] + bbox[i + 3]) / 2 <= tol_m for i in range(3))


def compile_solidworks(sw_app, plan: BuildPlan, dims: dict[str, float], fmap: dict[str, Any],
                       out_dir: Path, template: Optional[str] = None,
                       pmap: Optional[PlaneMap] = None, progress=None,
                       convention: str = "mti") -> SwBuildReport:
    """Build the plan in SolidWorks, verifying each feature against the CadQuery reference.

    ``convention``: ``"mti"`` (centered origin, Top-plane base, Mid Plane, Up To Next) or
    ``"drawing"`` (the drawing frame as-is). ``progress(feature, result)``, if given, is
    called after each feature (live demos)."""
    from pipeline.solidworks_builder import _close_open_sketch, save_model

    if convention not in CONVENTIONS:
        raise ValueError(f"convention must be one of {CONVENTIONS}")
    pmap = pmap or probe_plane_map(sw_app, template)
    sw = _SW(sw_app, plan, dims, fmap, pmap, template, convention)
    skipped = fmap.get("skipped", {})
    features = list(plan.features)
    i = 0
    while i < len(features):
        f = features[i]
        i += 1
        if f.status != "planned" or f.id in skipped:
            sw.report.features.append(SwFeatureResult(f.id, "skipped", note=skipped.get(f.id, f.status)))
            continue
        group = [f]
        if convention == "mti" and isinstance(f, Hole):   # same hole, same face: one feature
            group += mergeable_holes(features[i:], f, dims, skipped)
            i += len(group) - 1
        try:
            if len(group) > 1:
                res = sw.hole_group(group)
            else:
                res = getattr(sw, f.kind)(f)
        except Exception as e:  # COM errors: record, keep building (non-strict, like v1)
            _close_open_sketch(sw.doc)
            res = SwFeatureResult(group[-1].id, "failed", note=f"{type(e).__name__}: {e}"[:300])
        if len(group) > 1:
            ids = ", ".join(g.id for g in group)
            res.note = f"{res.note}; one feature for {ids}".lstrip("; ")
            res.fid = f.id
            sw.report.features.append(res)
            sw.report.features += [SwFeatureResult(g.id, res.status, note=f"in {f.id} (one feature)")
                                   for g in group[1:]]
        else:
            sw.report.features.append(res)
        log.info("  %s %s: %s %s", f.id, f.kind, res.status, res.note)
        if sw.base and f.id == sw.base["fid"] and res.status == "built":
            body = (sw.doc.GetBodies2(0, False) or [None])[0]
            sw.report.origin_ok = body is not None and origin_centered(list(body.GetBodyBox()))
        if progress is not None:
            progress(f, res)

    vol = sw.volume()
    sw.report.volume_ok = abs(vol - fmap["volume"]) <= max(VOL_REL_TOL * fmap["volume"], 1e-6)
    bodies = sw.doc.GetBodies2(0, False)
    if bodies:
        bb = bodies[0].GetBodyBox()
        ext = sorted((bb[i + 3] - bb[i]) / sw.k for i in range(3))
        ref = sorted(fmap["bbox"][i + 3] - fmap["bbox"][i] for i in range(3))
        sw.report.bbox_ok = all(abs(a - b) <= 1e-4 * max(1.0, b) for a, b in zip(ext, ref))
    sw.doc.SketchManager.AddToDB = False   # hand the part back with normal sketch behaviour
    sw.report.sldprt = save_model(sw.doc, f"{plan.part}_ir", out_dir)
    try:  # an isometric picture for review (best effort)
        sw.doc.ShowNamedView2("*Isometric", 7)
        sw.doc.ViewZoomtofit2()
        sw.doc.SaveAs3(str((Path(out_dir) / f"{plan.part}_ir.png").resolve()), 0, 1)
    except Exception as e:
        log.warning("Could not export a PNG view: %s", e)
    return sw.report
