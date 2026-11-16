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
from pipeline.ir.model import BuildPlan, EdgeOp, Hole, Pattern, Prism, Revolve, parse_ref
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
HW_TYPE = {"hole": 2, "cbore": 0, "tap": 4}              # swWzdHole, swWzdCounterBore, swWzdTap
HW_STANDARD = {"inch": 0, "metric": 1}                   # swStandardAnsiInch, swStandardAnsiMetric
HW_FASTENER = {("hole", "inch"): 22, ("hole", "metric"): 40,     # ... ScrewClearances
               ("cbore", "inch"): 9, ("cbore", "metric"): 33,    # ... SocketCapScrew / SocketHeadCapScrew
               ("tap", "inch"): 27, ("tap", "metric"): 43}       # ... TappedHole
HW_THREAD_DEPTH, HW_COSMETIC = 0, 6      # Value1 = thread depth, Value7 = swWzdHoleCosmeticThreadTypes_e
COSMETIC_WITH_CALLOUT = 1                # MTI: tap drill + cosmetic thread, never real threads
DRILL_POINT_DEG = 118.0                  # Hole Wizard blind holes end in a 118 deg drill point
SW_DISPLAY_COSMETIC_THREADS = 41         # swUserPreferenceToggle_e (MTI ToggleCosmeticThreads macro)

# Inch thread sizes as SolidWorks names them; ISO 261 coarse pitches for "M8"-style callouts.
_INCH_SIZES = {0.112: "#4", 0.138: "#6", 0.164: "#8", 0.190: "#10", 0.216: "#12", 0.25: "1/4",
               0.3125: "5/16", 0.375: "3/8", 0.4375: "7/16", 0.5: "1/2", 0.5625: "9/16", 0.625: "5/8",
               0.75: "3/4", 0.875: "7/8", 1.0: "1"}
_ISO_COARSE = {3: 0.5, 4: 0.7, 5: 0.8, 6: 1.0, 8: 1.25, 10: 1.5, 12: 1.75, 14: 2.0, 16: 2.0, 20: 2.5,
               24: 3.0, 30: 3.5, 36: 4.0}
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
    stl: Optional[str] = None          # <part>_ir.stl beside the .sldprt (None = export failed)
    bbox_ok: Optional[bool] = None
    volume_ok: Optional[bool] = None
    convention: str = "drawing"
    origin_ok: Optional[bool] = None   # MTI: base body centered on the origin (None = not checked)
    conventions: list[str] = field(default_factory=list)   # applied / fell back, for review
    sketches: dict[str, int] = field(default_factory=dict)  # sketch -> swConstrainedStatus_e (3 = fully defined)

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
        self.feat_obj: dict[str, Any] = {}   # SolidWorks feature built for each IR feature (pattern seeds)
        self._part_axis = None               # reference axis along IR z (circular patterns)
        self.extra_removed = 0.0             # Hole Wizard drill-point cones (drawing units^3)
        self.layout_drawn = ""               # construction geometry under the last Hole Wizard
        self.sketch_status: dict[str, int] = {}   # MTI: every sketch fully defined (3 = fully)
        self._hw_fid = ""
        self.cosmetic_threads = False

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

    def define_sketch(self, fid: str, relations: bool = False, anchor_ok: bool = True, datum=None) -> None:
        """MTI: every sketch fully defined, dimensioned from model edges (practices 3 and 7).

        SolidWorks' own Fully Define Sketch on the ACTIVE sketch (verified live, E023):

        1. Regular (baseline) dimensions from datum edges: the body's straight edges
           parallel to the sketch, leftmost and lowest (MTI: locate from model edges).
        2. If that leaves the sketch under-defined (it does on base-plane sketches), an
           anchor point tied to the origin by an explicit coincident relation is the datum.

        Relations are limited to horizontal, vertical, midpoint and coincident. Fully
        Define's relations were checked not to move nearly-aligned geometry (0.0005" off
        stayed put), unlike sketch inference. Dimensions record the geometry and never
        move it. The status is recorded and advisory: the volume checks still decide.

        ``anchor_ok=False`` for Hole Wizard placement sketches: Hole Wizard drills at every
        free sketch point, so an anchor would become a hole. ``relations`` is kept for
        callers' intent; relations are always limited to the exact set."""
        if self.convention != "mti":
            return
        from pipeline.solidworks_builder import typed
        sm = self.doc.SketchManager
        try:
            sk = typed(sm.ActiveSketch, "ISketch")
            tsm = typed(sm, "ISketchManager")
            hd, vd = self.datum_edges(sk)
            r = tsm.FullyDefineSketch(AUTODIM_ALL, True, EXACT_RELATIONS, True, AUTODIM_BASELINE, hd,
                                      AUTODIM_BASELINE, vd, 1, 1)
            how = "model edges" if (hd is not None or vd is not None) else "no datum"
            if datum is not None and sk.GetConstrainedStatus() != FULLY_CONSTRAINED:
                # Hole Wizard placement sketch: a point already tied to the origin (hw_datum)
                r = tsm.FullyDefineSketch(AUTODIM_ALL, True, EXACT_RELATIONS, True, AUTODIM_BASELINE,
                                          datum, AUTODIM_BASELINE, datum, 1, 1)
                how += " + origin-tied hole point"
                if sk.GetConstrainedStatus() != FULLY_CONSTRAINED:
                    how += f" + {self.dimension_free_points(sk, datum)} explicit dimension(s)"
            if anchor_ok and sk.GetConstrainedStatus() != FULLY_CONSTRAINED:
                anchor = self.origin_anchor()
                if anchor is not None:
                    r = tsm.FullyDefineSketch(AUTODIM_ALL, True, EXACT_RELATIONS, True, AUTODIM_BASELINE,
                                              anchor, AUTODIM_BASELINE, anchor, 1, 1)
                    how += " + origin anchor"
            self.sketch_status[fid] = sk.GetConstrainedStatus()
            log.info("  %s sketch: fully define (%s) -> %s, status %s", fid, how, r, self.sketch_status[fid])
        except Exception as e:   # never fail a build over sketch definition (practices, not rules)
            log.info("  %s: could not fully define the sketch: %s", fid, e)
            self.sketch_status[fid] = 0

    def origin_anchor(self):
        """A sketch point at (0, 0) of the active sketch, tied to the part origin with a
        coincident relation. It is drawn without inference: a point snapped onto an
        origin-centered circle's center would float with it (E023). The origin is found by
        type in the feature tree, not by a hard-coded name (rule 4)."""
        from pipeline.solidworks_builder import _g, _null_dispatch, typed
        sm = self.doc.SketchManager
        prev = sm.AddToDB
        sm.AddToDB = True
        try:
            pt = sm.CreatePoint(0.0, 0.0, 0.0)
        finally:
            sm.AddToDB = prev
        if pt is None:
            return None
        pt = typed(pt, "ISketchPoint")
        if not getattr(self, "_origin_name", None):
            f = _g(self.doc, "FirstFeature")
            while f is not None:
                tf = typed(f, "IFeature")
                if tf.GetTypeName2() == "OriginProfileFeature":
                    self._origin_name = tf.Name
                    break
                f = tf.GetNextFeature()
        sel = typed(_g(self.doc, "SelectionManager"), "ISelectionMgr")
        self.doc.ClearSelection2(True)
        pt.Select4(False, sel.CreateSelectData())
        if self.doc.Extension.SelectByID2(f"Point1@{getattr(self, '_origin_name', 'Origin')}", "EXTSKETCHPOINT",
                                          0, 0, 0, True, 0, _null_dispatch(), 0):
            self.doc.SketchAddConstraints("sgCOINCIDENT")
        self.doc.ClearSelection2(True)
        return pt

    def datum_edges(self, sk):
        """(horizontal-dimension datum, vertical-dimension datum): the leftmost body edge
        parallel to the sketch's y axis and the lowest one parallel to its x axis, among
        straight edges in planes parallel to the sketch (nearest plane first). MTI: locate
        features from model edges, not from the origin or other holes."""
        from pipeline.solidworks_builder import _g, com_doubles, typed
        bodies = self.doc.GetBodies2(0, False) or ()
        if not bodies:
            return None, None
        xf = sk.ModelToSketchTransform
        mu = typed(_g(self.app, "GetMathUtility"), "IMathUtility")

        def to_sketch(p):
            return typed(typed(mu.CreatePoint(com_doubles(*p[:3])), "IMathPoint").MultiplyTransform(xf),
                         "IMathPoint").ArrayData

        vert = horz = None   # (sort key, edge)
        for body in bodies:
            for e in _g(body, "GetEdges") or ():
                e = typed(e, "IEdge")
                if not typed(e.GetCurve(), "ICurve").IsLine():
                    continue
                sv, ev = e.GetStartVertex(), e.GetEndVertex()
                if sv is None or ev is None:
                    continue
                a = to_sketch(typed(sv, "IVertex").GetPoint())
                b = to_sketch(typed(ev, "IVertex").GetPoint())
                if abs(a[2] - b[2]) > 1e-9:
                    continue   # not parallel to the sketch plane
                z = round(abs(a[2]), 9)
                if abs(a[0] - b[0]) < 1e-9 and abs(a[1] - b[1]) > 1e-9:      # along sketch y
                    key = (z, a[0])
                    if vert is None or key < vert[0]:
                        vert = (key, e)
                elif abs(a[1] - b[1]) < 1e-9 and abs(a[0] - b[0]) > 1e-9:    # along sketch x
                    key = (z, a[1])
                    if horz is None or key < horz[0]:
                        horz = (key, e)
        return (vert[1] if vert else None), (horz[1] if horz else None)

    def check(self, fid: str, attempt: int, extra: float = 0.0) -> bool:
        """SW volume vs the reference after ``fid``. Hole Wizard drill points are the one
        deliberate difference: their exact cone volume (``extra_removed`` so far, plus
        ``extra`` for the feature being checked) is credited."""
        ref = self.fmap.get("volume_after", {}).get(fid)
        got = self.volume()
        if ref is None:
            return True
        ref -= self.extra_removed + extra
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
                self.feat_obj[fid] = feat
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
        elif p.shape == "slot":
            # Straight slot, as CadQuery's slot2D(length + width, width, angle) centered on
            # (u, v): arc centers +-length/2 along `angle` (degrees from +u). SolidWorks' own
            # slot tool, center-to-center (CreateSketchSlot; signature from sldworks.tlb, E028).
            cu, cv, half = self.n(p.u) + su, self.n(p.v) + sv, self.n(p.length) / 2
            a = math.radians(self.n(p.angle))
            ends = [self.pt(plane, self.in_plane(axis, cu + sgn * half * math.cos(a), cv + sgn * half * math.sin(a)))
                    for sgn in (-1, 1)]
            (x1, y1), (x2, y2) = ends
            slot = sm.CreateSketchSlot(SLOT_STRAIGHT, SLOT_CENTER_TO_CENTER, self.n(p.width) * self.k,
                                       x1, y1, 0, x2, y2, 0, 0, 0, 0, 1, False)
            if not slot:
                sm.InsertSketch(True)
                return SwFeatureResult(f.id, "failed", note="CreateSketchSlot refused the slot")
        elif p.shape == "polygon":
            # A closed outline of lines (L-shaped and stepped plates; A00121E/M, 2026-10-26).
            # Drawn like the revolve profile: no inference, exact endpoints; the volume check
            # confirms SolidWorks closed it.
            pts = [self.pt(plane, self.in_plane(axis, self.n(a) + su, self.n(b) + sv)) for a, b in p.points]
            for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
                if (x1, y1) != (x2, y2):
                    sm.CreateLine(x1, y1, 0, x2, y2, 0)
        else:
            sm.InsertSketch(True)
            return SwFeatureResult(f.id, "failed", note=f"profile {p.shape} not compiled for SolidWorks yet")
        self.define_sketch(f.id if flip is None else f"{f.id}+copy",
                           relations=bool(self.base) and f.id == self.base["fid"] and flip is None)
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
            self.feat_obj[fid] = feat
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

    def holes(self, fid: str, centers: list[list[float]], spec: dict, axis: str, coord: float, d: int,
              layout: Optional[str] = None):
        if self.convention == "mti":
            choice = hole_wizard_choice(spec, self.dims, self.plan.frame.units)
            if choice:
                res = self.hole_wizard(fid, centers, spec, axis, coord, d, choice, layout)
                if res is not None:
                    return res
        coord -= self.shift["XYZ".index(axis)]
        plane, sign = self.sketch_on(axis)
        sm = self.doc.SketchManager

        def circles(dia, tag=""):
            for c in centers:
                x, y = self.pt(plane, self.in_plane(axis, c[0], c[1]))
                sm.CreateCircleByRadius(x, y, 0, dia * self.k / 2)
            self.define_sketch(fid + tag)
            sm.InsertSketch(True)

        circles(self.n(spec.d))
        start = coord * self.k * sign
        thru = spec.type == "thru" or spec.depth is None  # null depth = through (tapped THRU too)
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
        circles(self.n(spec.cbore_d), "+cbore")
        res = self.with_retry(fid, lambda flip: self.extrude(
            cut=True, reverse=((d * sign) < 0) != flip, depth=self.n(spec.cbore_depth) * self.k, start=start))
        res.note = "drill + counterbore"
        return res

    def hole_wizard(self, fid: str, centers: list[list[float]], spec, axis: str, coord: float, d: int,
                    choice: dict, layout: Optional[str] = None) -> Optional[SwFeatureResult]:
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
        vals =[v if (n in choice.get("unitless", ()) or v == -1.0) else v * self.k
                for n, v in enumerate(choice["values"])]
        # Up To Next first (MTI: through holes). A hole planned with a depth is then tried
        # Blind: Hole Wizard measures to the shoulder and adds a 118 deg drill point, whose
        # exact volume is credited in the check (verified live, E022).
        modes = [(END_UP_TO_NEXT, 0.0, 0.0, "Up To Next")]
        if spec.depth is not None:
            modes.append((0, self.n(spec.depth) * self.k,
                          len(centers) * drill_point_volume(self.n(spec.d)), "Blind + drill point"))
        why = "volume"
        for end, depth, extra, label in modes:
            p0 = model_pt(centers[0])
            self.doc.ClearSelection2(True)
            eps = 1e-3   # start the ray 1 mm outside the face, cast into the material
            if not self.doc.Extension.SelectByRay(*(p0[i] - into[i] * eps for i in range(3)), *into,
                                                   1e-5, 2, False, 0, 0):   # swSelFACES
                self.report.conventions.append(f"{fid}: no start face under the hole; plain cut")
                return None
            feat = self.doc.FeatureManager.HoleWizard5(
                choice["type"], choice["standard"], choice["fastener"], choice["size"], end,
                self.n(spec.d) * self.k, depth, -1.0, *vals, "", False, True, True, True, True, False)
            if feat is None:
                why = f"HoleWizard5 refused {label}"
                continue
            self._hw_fid = fid
            placed = self.place_hole_points(feat, [model_pt(c) for c in centers], layout)
            if placed and self.check(fid, 1, extra):
                self.extra_removed += extra
                if choice["kind"] == "tap":
                    self.cosmetic_threads = True
                res = SwFeatureResult(fid, "built", sw_volume=self.volume(),
                                      ref_volume=self.fmap.get("volume_after", {}).get(fid), attempts=1,
                                      note=f"{choice['label']}, {label}, {len(centers)} hole(s)"
                                           + (f" on a construction {self.layout_drawn}"
                                              if self.layout_drawn else ""))
                self.report.conventions.append(f"{fid}: {res.note}")
                return res
            why = "volume" if placed else "points"
            self.delete_feature(feat, before, fid)
        self.report.conventions.append(f"{fid}: {choice['label']} did not match the reference ({why}); plain cut")
        return None

    def delete_feature(self, feat, volume_before: float, fid: str) -> None:
        from pipeline.solidworks_builder import typed
        self.doc.ClearSelection2(True)
        typed(feat, "IFeature").Select2(False, 0)
        self.doc.Extension.DeleteSelection2(2)   # swDelete_Absorbed: the feature and its sketches
        if abs(self.volume() - volume_before) > 1e-9:
            raise RuntimeError(f"{fid}: could not remove the mismatched Hole Wizard feature")

    def place_hole_points(self, feat, model_pts: list[Vec], layout: Optional[str] = None) -> bool:
        """Put the Hole Wizard placement sketch's points exactly at ``model_pts``.

        ``layout`` (MTI: patterned holes sit on sketch geometry): ``"circle"`` adds a
        construction bolt circle, ``"line"`` a construction line, ``"grid"`` a construction
        rectangle through the outer holes; each point gets a coincident relation to the
        geometry it lies on. Hole Wizard ignores construction geometry (verified live, E022).
        """
        from pipeline.solidworks_builder import _g, com_doubles, typed
        sub, best = typed(feat, "IFeature").GetFirstSubFeature(), None
        while sub is not None:   # placement sketch = the sub-sketch with the fewest points
            sf = typed(sub, "IFeature")
            spec = sf.GetSpecificFeature2() if sf.GetTypeName2() == "ProfileFeature" else None
            if spec is not None:   # taps also carry a cosmetic-thread sub-feature (not a sketch)
                sk = typed(spec, "ISketch")
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
            points = [typed(pts[0], "ISketchPoint")]
            for x, y in want[1:]:
                # SetCoords after creating: with AddToDB off, inference can snap a point
                # .005" off an axis onto it (117-C; same cause as E020)
                pt = sm.CreatePoint(x, y, 0.0)
                if pt is None:
                    return False
                points.append(typed(pt, "ISketchPoint"))
                points[-1].SetCoords(x, y, 0.0)
            self.layout_drawn = ""
            if layout:
                self.layout_geometry(sk, points, want, layout)
            self.define_sketch(self._hw_fid, anchor_ok=False, datum=self.hw_datum(sk, to_sketch((0.0, 0.0, 0.0)), points))
            status = sk.GetConstrainedStatus()
        finally:
            sm.InsertSketch(True)
            sm.AddToDB = True
        # construction geometry brings its own points (circle center, line ends): every
        # wanted point must be present, and the sketch must have solved
        got = [(p.X, p.Y) for p in (typed(q, "ISketchPoint") for q in (sk.GetSketchPoints2() or ()))]
        ok = status not in BAD_SKETCH_STATUS and all(
            any(math.dist(w, g) <= 1e-7 for g in got) for w in want)
        if not ok:
            log.info("  Hole Wizard points: wanted %s, got %s (m, sketch), status %s", want, got, status)
        return ok

    def hw_datum(self, sk, origin_xy: tuple[float, float], points: list):
        """A point of the Hole Wizard placement sketch tied to the part origin, WITHOUT a new
        free sketch point (Hole Wizard drills at every one; E023). Verified live (SB12006): a
        hole point related coincident to the origin takes the sketch to fully defined with the
        point count and the volume unchanged; Fully Define with the origin as datum alone doesn't.

        * a hole point or a layout centre already at the origin: relate it (coincident);
        * otherwise a CONSTRUCTION line from the origin to the first hole (Hole Wizard ignores
          construction geometry and its end points, E022): its start tied to the origin, its end
          to the hole. The start point is the datum for Fully Define Sketch."""
        from pipeline.solidworks_builder import _g, _null_dispatch, typed
        sm = self.doc.SketchManager
        ox, oy = origin_xy
        sel = typed(_g(self.doc, "SelectionManager"), "ISelectionMgr")

        def tie_to_origin(pt) -> bool:
            if not getattr(self, "_origin_name", None):
                self.origin_anchor_name()
            self.doc.ClearSelection2(True)
            pt.Select4(False, sel.CreateSelectData())
            ok = self.doc.Extension.SelectByID2(f"Point1@{getattr(self, '_origin_name', 'Origin')}", "EXTSKETCHPOINT",
                                                0, 0, 0, True, 0, _null_dispatch(), 0)
            if ok:
                self.doc.SketchAddConstraints("sgCOINCIDENT")
            self.doc.ClearSelection2(True)
            return bool(ok)

        try:
            at_origin = [typed(q, "ISketchPoint") for q in (sk.GetSketchPoints2() or ())]
            at_origin = [q for q in at_origin if abs(q.X - ox) < 1e-9 and abs(q.Y - oy) < 1e-9]
            if at_origin:
                return at_origin[0] if tie_to_origin(at_origin[0]) else None
            if not points:
                return None
            # not the first point: that is Hole Wizard's own placement point, and a coincident to
            # it did not apply (A00144E: the line stayed free at that end; merge did not either).
            # Points we added take relations; among them the one with the fewest.
            target = min(points[1:] or points, key=lambda q: q.GetRelationsCount())
            prev = sm.AddToDB
            sm.AddToDB = True                       # no inference: the line lands exactly (E020)
            try:
                seg = sm.CreateLine(ox, oy, 0.0, target.X, target.Y, 0.0)
            finally:
                sm.AddToDB = prev
            if seg is None:
                return None
            typed(seg, "ISketchSegment").ConstructionGeometry = True
            line = typed(seg, "ISketchLine")
            start, end = typed(line.GetStartPoint2(), "ISketchPoint"), typed(line.GetEndPoint2(), "ISketchPoint")
            self.doc.ClearSelection2(True)
            end.Select4(False, sel.CreateSelectData())
            target.Select4(True, sel.CreateSelectData())
            self.doc.SketchAddConstraints("sgCOINCIDENT")
            self.doc.ClearSelection2(True)
            return start if tie_to_origin(start) else None
        except Exception as e:   # practices, not rules: never fail a build over sketch definition
            log.info("  Hole Wizard sketch datum: %s", e)
            return None

    def dimension_free_points(self, sk, datum) -> int:
        """Horizontal and vertical dimensions from ``datum`` to every point still free.
        Fully Define Sketch skips Hole Wizard's own placement point (A00144E: every other hole got
        a distance, that one only its coincidents, and stayed free along the layout line). A
        dimension that over-defines the sketch is undone. The "enter dimension value" dialog
        (swInputDimValOnCreate) is switched off while adding them, then restored. Returns the
        number kept."""
        from pipeline.solidworks_builder import _g, typed
        sel = typed(_g(self.doc, "SelectionManager"), "ISelectionMgr")
        prev = self.app.GetUserPreferenceToggle(SW_INPUT_DIM_ON_CREATE)
        self.app.SetUserPreferenceToggle(SW_INPUT_DIM_ON_CREATE, False)
        kept = 0
        try:
            for q in [typed(x, "ISketchPoint") for x in (sk.GetSketchPoints2() or ())]:
                # horizontal dimension measures dx, vertical dy; a zero offset can't be a
                # dimension (A00173E: a bolt-circle hole level with the origin), so it becomes
                # the matching alignment relation (types 26 / 25, as Fully Define uses them)
                for add, offset, relation in ((self.doc.AddHorizontalDimension2, q.X - datum.X, "sgVERTICALPOINTS2D"),
                                              (self.doc.AddVerticalDimension2, q.Y - datum.Y, "sgHORIZONTALPOINTS2D")):
                    if q.Status != 2 or sk.GetConstrainedStatus() == FULLY_CONSTRAINED:
                        break
                    self.doc.ClearSelection2(True)
                    q.Select4(False, sel.CreateSelectData())
                    datum.Select4(True, sel.CreateSelectData())
                    if abs(offset) < 1e-9:
                        self.doc.SketchAddConstraints(relation)
                    elif add(q.X + 0.005, q.Y + 0.005, 0.0) is None:
                        continue
                    if sk.GetConstrainedStatus() in BAD_SKETCH_STATUS:
                        self.doc.EditUndo2(1)          # redundant: it over-defined the sketch
                    else:
                        kept += 1
            self.doc.ClearSelection2(True)
        finally:
            self.app.SetUserPreferenceToggle(SW_INPUT_DIM_ON_CREATE, prev)
        return kept

    def origin_anchor_name(self) -> None:
        """The origin feature's name, found by type (rule 4)."""
        from pipeline.solidworks_builder import _g, typed
        f = _g(self.doc, "FirstFeature")
        while f is not None:
            tf = typed(f, "IFeature")
            if tf.GetTypeName2() == "OriginProfileFeature":
                self._origin_name = tf.Name
                return
            f = tf.GetNextFeature()

    def layout_geometry(self, sk, points: list, want: list[tuple[float, float]], layout: str) -> None:
        """Construction geometry under patterned holes, with coincident relations."""
        from pipeline.solidworks_builder import _g, typed
        sm = self.doc.SketchManager
        shapes = layout_shapes(want, layout)
        segs = []
        # Construction geometry is not tracked by Hole Wizard, so it is drawn with AddToDB on:
        # no inference. A bolt circle 7 um off the origin snapped onto it (A040911E, E022).
        sm.AddToDB = True
        for kind, a in shapes:
            if kind == "circle":
                (cx, cy), r = a
                seg = sm.CreateCircleByRadius(cx, cy, 0.0, r)
            else:
                (x1, y1), (x2, y2) = a
                seg = sm.CreateLine(x1, y1, 0.0, x2, y2, 0.0)
            if seg is not None:
                seg = typed(seg, "ISketchSegment")
                seg.ConstructionGeometry = True
                segs.append((kind, a, seg))
        sm.AddToDB = False
        self.layout_drawn = "circle" if any(k == "circle" for k, _, _ in segs) else (
            ("rectangle" if len(segs) == 4 else "line") if segs else "")
        sel = typed(_g(self.doc, "SelectionManager"), "ISelectionMgr")
        ends = {}   # line endpoints, so a hole AT an end ties the line's length (else it floats)
        for kind, a, seg in segs:
            if kind != "circle":
                ln = typed(seg, "ISketchLine")
                ends[id(seg)] = [typed(ln.GetStartPoint2(), "ISketchPoint"), typed(ln.GetEndPoint2(), "ISketchPoint")]
        for p, w in zip(points, want):
            for kind, a, seg in segs:
                if not on_shape(w, kind, a):   # only the geometry the point lies on (else: invalid sketch)
                    continue
                end = next((e for e in ends.get(id(seg), []) if math.dist((e.X, e.Y), w) <= 1e-9), None)
                data = sel.CreateSelectData()
                self.doc.ClearSelection2(True)
                p.Select4(False, data)
                # a hole at a line's end: point-to-point with that end (point-on-line left the
                # line's length free and the sketch under-defined, A00144E); else on the line
                (end or seg).Select4(True, data)
                self.doc.SketchAddConstraints("sgCOINCIDENT")
        self.doc.ClearSelection2(True)

    def hole_and_pattern(self, seed: Hole, pat: Pattern) -> SwFeatureResult:
        """A hole and its pattern as ONE feature whose points sit on construction geometry
        (MTI: patterned holes sit on sketch geometry), verified against the reference
        after the pattern."""
        st = self.fmap["starts"][seed.id]
        centers = [[self.n(seed.u), self.n(seed.v)]] + [
            h["planned_center"] for h in self.fmap["holes"].get(pat.id, [])]
        layout = {"circular": "circle", "linear": "line", "grid": "grid"}.get(pat.mode)
        return self.holes(pat.id, centers, seed.spec, st["axis"], st["coord"], st["dir"], layout)

    def hole_group(self, group: list[Hole]) -> SwFeatureResult:
        """Identical consecutive holes on one face as ONE feature (MTI practice), verified
        against the reference volume after the last of them."""
        st = self.fmap["starts"][group[0].id]
        centers = [[self.n(g.u), self.n(g.v)] for g in group]
        return self.holes(group[-1].id, centers, group[0].spec, st["axis"], st["coord"], st["dir"], "auto")

    def hole(self, f: Hole) -> SwFeatureResult:
        st = self.fmap["starts"][f.id]
        if st.get("radial"):
            return self.radial_hole(f)
        return self.holes(f.id, [[self.n(f.u), self.n(f.v)]], f.spec, st["axis"], st["coord"], st["dir"])

    def radial_hole(self, f: Hole) -> SwFeatureResult:
        """A hole drilled into the outside of a turned part toward its axis (spec
        2026-10-28-radial-holes-design.md). Volume can't tell a radial hole at the wrong angle
        or mirrored from the right one, so the geometry is made unambiguous:

        1. a line on the base plane normal to the part axis, from the axis to P just OUTSIDE
           the part at angle u (explicit coordinates, read back);
        2. a reference plane perpendicular to that line through P (InsertRefPlane,
           Perpendicular + Coincident; sldworks.tlb / swconst.tlb);
        3. the hole circle on that plane at P + z (ISketch.ModelToSketchTransform);
        4. a blind cut from outside, inward: aimed the wrong way it removes nothing, which the
           volume check catches, so flip-and-retry is safe.

        A plain cut (MTI would use a Hole Wizard on the curved face: a follow-up)."""
        from pipeline.solidworks_builder import _g, com_doubles, typed
        st, k = self.fmap["starts"][f.id], self.k
        a = math.radians(self.n(f.u))
        z, r = self.n(f.v), st["r"]
        bb = self.fmap["bbox"]
        rmax = max(abs(c) for c in (bb[0], bb[1], bb[3], bb[4]))
        reach = rmax + max(0.1 * rmax, 0.05)               # P is this far from the axis
        depth = reach + rmax if st["depth"] is None else reach - r + self.n(st["depth"])
        res = SwFeatureResult(f.id, "failed", ref_volume=self.fmap.get("volume_after", {}).get(f.id))

        sm, fm = self.doc.SketchManager, self.doc.FeatureManager
        plane, _ = self.sketch_on("Z")
        (x0, y0), (x1, y1) = self.pt(plane, (0.0, 0.0, 0.0)), self.pt(plane, (reach * math.cos(a), reach * math.sin(a), 0.0))
        seg = sm.CreateLine(x0, y0, 0, x1, y1, 0)
        # CreateLine hands back the ISketchSegment view: endpoints are on ISketchLine
        end = typed(typed(seg, "ISketchLine").GetEndPoint2(), "ISketchPoint") if seg is not None else None
        if end is None or abs(end.X - x1) > 1e-9 or abs(end.Y - y1) > 1e-9:   # no inference (E020)
            sm.InsertSketch(True)
            res.note = "the radial direction line did not land where it was drawn"
            return res
        sm.InsertSketch(True)

        self.doc.ClearSelection2(True)
        data = _g(self.doc.SelectionManager, "CreateSelectData")
        data.Mark = 0
        typed(seg, "ISketchSegment").Select4(False, data)
        data.Mark = 1
        end.Select4(True, data)
        if fm.InsertRefPlane(REFPLANE_PERPENDICULAR, 0.0, REFPLANE_COINCIDENT, 0.0, 0, 0.0) is None:
            res.note = "InsertRefPlane refused the plane at the hole start"
            return res
        ref = typed(self.doc.FeatureByPositionReverse(0), "IFeature")   # IRefPlane can't be selected
        if ref.GetTypeName2() != "RefPlane":
            res.note = f"expected the new reference plane, got {ref.GetTypeName2()}"
            return res

        self.doc.ClearSelection2(True)
        ref.Select2(False, 0)
        sm.InsertSketch(True)
        xf = typed(sm.ActiveSketch, "ISketch").ModelToSketchTransform
        mu = typed(_g(self.app, "GetMathUtility"), "IMathUtility")
        q = self.pm.to_model(tuple(c * k for c in self.local((reach * math.cos(a), reach * math.sin(a), z))))
        cx, cy, _ = typed(typed(mu.CreatePoint(com_doubles(*q)), "IMathPoint").MultiplyTransform(xf),
                          "IMathPoint").ArrayData
        sm.CreateCircleByRadius(cx, cy, 0, self.n(f.spec.d) * k / 2)
        sm.InsertSketch(True)
        res = self.with_retry(f.id, lambda flip: self.extrude(cut=True, reverse=flip, depth=depth * k, start=0.0))
        if res.status == "built":
            res.note = f"radial, {self.n(f.u):g} deg, plain cut"
        return res

    def pattern(self, f: Pattern) -> SwFeatureResult:
        seed = self.plan.feature(f.seed)
        if isinstance(seed, Prism) and f.mode in ("linear", "grid"):
            return self.prism_pattern(f, seed)
        if f.mode == "circular" and (isinstance(seed, Prism) or is_radial(seed)):
            return self.circular_pattern(f, seed)
        if not isinstance(seed, Hole):
            return SwFeatureResult(f.id, "failed", note="only hole and prism patterns are compiled "
                                                        "for SolidWorks yet")
        st = self.fmap["starts"][seed.id]
        centers = [h["planned_center"] for h in self.fmap["holes"].get(f.id, [])]
        return self.holes(f.id, centers, seed.spec, st["axis"], st["coord"], st["dir"])

    def part_axis(self):
        """A reference axis along IR z through the IR origin (the turning axis of an
        axis_end part): the intersection of the two base planes that contain it. Made once."""
        from pipeline.solidworks_builder import _g, select_ref_plane, typed
        if self._part_axis is not None:
            return self._part_axis
        z = self.pm.ir_basis[2]
        planes = [name for name, (_, _, n) in self.pm.planes.items() if abs(_dot(n, z)) < 1e-9]
        if len(planes) != 2 or any(abs(c) > 1e-9 for c in self.local((0.0, 0.0, 0.0))[:2]):
            return None   # the IR axis must pass through the model origin
        self.doc.ClearSelection2(True)
        if not (select_ref_plane(self.doc, planes[0]) and select_ref_plane(self.doc, planes[1], append=True)):
            return None
        if not self.doc.InsertAxis2(True):
            return None
        feat = typed(self.doc.FeatureByPositionReverse(0), "IFeature")
        if feat.GetTypeName2() != "RefAxis":
            return None
        self._part_axis = feat
        self.doc.ClearSelection2(True)
        return feat

    def circular_pattern(self, f: Pattern, seed: Prism) -> SwFeatureResult:
        """A circular pattern of a prism seed (radial slots and pockets) as ONE native
        SolidWorks circular pattern about the part axis, as MTI models them (SB14306:
        CirPattern). FeatureCircularPattern5, signature from sldworks.tlb (E028). Verified
        against the reference volume, tried both directions."""
        from pipeline.solidworks_builder import typed
        res = SwFeatureResult(f.id, "failed", ref_volume=self.fmap.get("volume_after", {}).get(f.id))
        if f.axis.replace(" ", "") != "axis(part)" or f.skip:
            res.note = "circular prism patterns are compiled about axis(part), with no skipped instances"
            return res
        if f.seed not in self.feat_obj:
            res.note = f"seed {f.seed} was not built"
            return res
        axis = self.part_axis()
        if axis is None:
            res.note = "could not make a reference axis along the part axis"
            return res
        count = int(round(self.n(f.count)))
        equal = f.step == "equal"
        spacing = 2 * math.pi if equal else math.radians(self.n(f.step))
        seed_feat = typed(self.feat_obj[f.seed], "IFeature")
        for attempt, flip in enumerate((False, True), start=1):
            self.doc.ClearSelection2(True)
            axis.Select2(False, 1)            # mark 1: pattern axis
            seed_feat.Select2(True, 4)        # mark 4: features to pattern
            feat = self.doc.FeatureManager.FeatureCircularPattern5(
                count, spacing, flip, "", False, equal, False, False, False, False, 1, 0.0, "", False)
            res.attempts = attempt
            if feat is not None and self.check(f.id, attempt):
                res.status, res.sw_volume = "built", self.volume()
                res.note = f"native circular pattern, {count} instances"
                self.feat_obj[f.id] = feat
                return res
            if feat is not None:
                self.doc.EditUndo2(1)
        res.status = "mismatch" if res.attempts else "failed"
        res.sw_volume = self.volume()
        res.note = "circular pattern did not match the reference volume"
        return res

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
        self.define_sketch(f.id, relations=True)   # stations are exact: H/V relations are safe
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


def parse_thread(text: str) -> Optional[tuple[str, str, str]]:
    """``"3/8-16 UNC"`` -> ``("inch", "3/8-16", "3/8")``; ``"M8 x 1.25"`` -> ``("metric",
    "M8x1.25", "M8")``. None for pipe threads (NPT/NPTF: tapered, not a Hole Wizard tap
    yet) and anything unreadable. Sizes are written the way SolidWorks names them."""
    import re
    t = (text or "").upper().replace(" ", "")
    if not t or "NPT" in t or "PIPE" in t:
        return None
    m = re.match(r"M(\d+(?:\.\d+)?)(?:[X×](\d+(?:\.\d+)?))?", t)
    if m:
        dia = float(m.group(1))
        pitch = float(m.group(2)) if m.group(2) else _ISO_COARSE.get(int(dia)) if dia.is_integer() else None
        if pitch is None:
            return None
        return "metric", f"M{dia:g}x{pitch:g}", f"M{dia:g}"
    m = re.match(r"(#\d+|\d+/\d+|\d*\.\d+|\d+)-(\d+)", t)
    if not m:
        return None
    tok, tpi = m.groups()
    if tok.startswith("#"):
        size = tok
    else:
        a, _, b = tok.partition("/")
        value = float(a) / float(b) if b else float(tok)
        size = next((n for v, n in _INCH_SIZES.items() if abs(v - value) <= 0.002), None)
        if size is None:
            return None
    return "inch", f"{size}-{tpi}", size


def drill_point_volume(d: float) -> float:
    """Volume of a Hole Wizard drill point (118 deg cone) of diameter ``d``."""
    r = d / 2
    return math.pi * r * r * (r / math.tan(math.radians(DRILL_POINT_DEG / 2))) / 3


def hole_wizard_choice(spec, dims: dict[str, float], units: str) -> Optional[dict]:
    """The Hole Wizard feature for a planned hole, or None to keep a plain cut (MTI:
    Hole Wizard for bolt holes, cut-extrude for everything else).

    A bolt hole is a clearance hole (optionally counterbored) whose diameter is a
    clearance size in MTI Std 202.02.0003. It is built Up To Next. A hole planned with a
    depth is tried too (plans often drill "to the full thickness"); the volume check keeps
    the Hole Wizard feature only if the hole really goes through, otherwise the caller
    deletes it and cuts a plain blind hole. The drawing's diameters are always used;
    the screw size records intent.

    A **tapped** hole (a readable thread callout) is a Hole Wizard tap: the drawing's tap
    drill, and a cosmetic thread (MTI: never real threads). Its cosmetic thread depth is
    MTI's standard tap depth, capped at the drill depth (STANDARD-DERIVED; the IR has no
    printed thread depth yet). The thread names the hardware, so no table is needed.
    Pipe taps stay plain cuts.
    """
    from pipeline import mti_standards
    if spec.thread or spec.type == "tapped":
        th = parse_thread(spec.thread)
        if th is None:
            return None
        system, size, nominal = th
        values = [-1.0] * 12
        values[HW_COSMETIC] = float(COSMETIC_WITH_CALLOUT)
        row = mti_standards.row(nominal) or {}
        tap_depth = row.get("tap_depth")
        if tap_depth:
            if (system == "metric") != (units == "mm"):
                tap_depth = tap_depth / 25.4 if units == "inch" else tap_depth * 25.4
            if spec.depth is not None:
                tap_depth = min(tap_depth, evaluate(spec.depth, dims).value)
            values[HW_THREAD_DEPTH] = tap_depth
        return {"kind": "tap", "type": HW_TYPE["tap"], "standard": HW_STANDARD[system],
                "fastener": HW_FASTENER[("tap", system)], "size": size, "values": values,
                "unitless": {HW_COSMETIC}, "label": f"Hole Wizard {size} tapped, cosmetic thread"}
    if spec.type not in ("thru", "blind", "cbore"):
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
            "unitless": set(),
            "label": f"Hole Wizard {best.size} {'SHCS counterbore' if kind == 'cbore' else 'clearance'}"}


SLOT_STRAIGHT, SLOT_CENTER_TO_CENTER = 0, 0
REFPLANE_PERPENDICULAR, REFPLANE_COINCIDENT = 2, 4   # swRefPlaneReferenceConstraints_e (swconst.tlb)   # swSketchSlotCreationType_line, swSketchSlotLengthType_CenterCenter
BAD_SKETCH_STATUS = (4, 5, 6)   # swConstrainedStatus_e: over-constrained, no / invalid solution
FULLY_CONSTRAINED = 3           # swConstrainedStatus_e
SW_INPUT_DIM_ON_CREATE = 10     # swUserPreferenceToggle_e.swInputDimValOnCreate (swconst.tlb)
# FullyDefineSketch (signature from sldworks.tlb; verified live 2026-10-12, E023): all entities,
# baseline (regular, not ordinate) dimensions, and only these relations: H | V | Midpoint |
# Coincident (checked not to move nearly-aligned geometry, unlike sketch inference).
AUTODIM_ALL, AUTODIM_BASELINE = 1, 1
EXACT_RELATIONS = 2 | 4 | 256 | 512


def layout_shapes(pts: list[tuple[float, float]], layout: str) -> list[tuple[str, Any]]:
    """Construction geometry for a hole layout, in sketch coordinates.

    ``circle``: the circle through the first three points (a bolt circle; needs 3+).
    ``line``: first to last point. ``grid``: the rectangle through the outer points
    (axis-aligned in the sketch; skipped if the grid is rotated). ``auto`` (holes planned
    one by one): a circle if 3+ holes are concyclic, else a line if they are collinear."""
    if layout == "auto":
        if len(pts) >= 3:
            circle = layout_shapes(pts, "circle")
            if circle:
                return circle
            ends = max(((a, b) for a in pts for b in pts), key=lambda ab: math.dist(*ab))
            if all(on_shape(p, "line", ends) for p in pts):
                return [("line", ends)]
        return []
    if layout == "circle" and len(pts) >= 3:
        (ax, ay), (bx, by), (cx, cy) = pts[:3]
        dd = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
        if abs(dd) < 1e-15:
            return []
        ux = ((ax**2 + ay**2) * (by - cy) + (bx**2 + by**2) * (cy - ay) + (cx**2 + cy**2) * (ay - by)) / dd
        uy = ((ax**2 + ay**2) * (cx - bx) + (bx**2 + by**2) * (ax - cx) + (cx**2 + cy**2) * (bx - ax)) / dd
        r = math.dist((ux, uy), (ax, ay))
        if all(abs(math.dist((ux, uy), p) - r) <= 1e-7 for p in pts):
            return [("circle", ((ux, uy), r))]
        return []
    if layout == "line" and len(pts) >= 2:
        return [("line", (pts[0], pts[-1]))]
    if layout == "grid" and len(pts) >= 4:
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        if all(any(math.dist(c, p) <= 1e-7 for p in pts) for c in corners):
            return [("line", (corners[i], corners[(i + 1) % 4])) for i in range(4)]
    return []


def on_shape(p: tuple[float, float], kind: str, a, tol: float = 1e-7) -> bool:
    """Is sketch point ``p`` on a construction circle / line segment?"""
    if kind == "circle":
        (cx, cy), r = a
        return abs(math.dist(p, (cx, cy)) - r) <= tol
    (x1, y1), (x2, y2) = a
    L = math.dist((x1, y1), (x2, y2))
    if L < tol:
        return False
    cross = abs((x2 - x1) * (p[1] - y1) - (y2 - y1) * (p[0] - x1)) / L
    t = ((p[0] - x1) * (x2 - x1) + (p[1] - y1) * (y2 - y1)) / (L * L)
    return cross <= tol and -1e-9 <= t <= 1 + 1e-9


def hole_signature(f: Hole, dims: dict[str, float]) -> tuple:
    """Holes that are the same hole on the same face (MTI: one Hole Wizard feature)."""
    sp = f.spec

    def v(e):
        return None if e is None else round(evaluate(e, dims).value, 9)
    return (f.on.replace(" ", ""), sp.type, v(sp.d), v(sp.depth), v(sp.cbore_d), v(sp.cbore_depth),
            v(sp.csink_d), v(sp.csink_angle), sp.thread)


def is_radial(f) -> bool:
    """A hole that starts on wall(F, r): drilled into a turned part toward its axis."""
    return isinstance(f, Hole) and parse_ref(f.on)[0] == "wall"


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


def body_box(body) -> list[float]:
    """Tight box [xmin, ymin, zmin, xmax, ymax, zmax] (m) from IBody2.GetExtremePoint along
    the six axis directions (sldworks.tlb: X, Y, Z in; Outx, Outy, Outz byref; returns bool).
    IBody2.GetBodyBox is NOT tight on curved faces: SB14306's filleted rim read 10.7281" for
    10.7218" and failed the bbox check (E030). Falls back to GetBodyBox."""
    from pipeline.solidworks_builder import typed
    try:
        tb = typed(body, "IBody2")
        box = [0.0] * 6
        for i in range(6):
            d = [0.0, 0.0, 0.0]
            d[i % 3] = -1.0 if i < 3 else 1.0
            ok, *pt = tb.GetExtremePoint(*d)
            if not ok:
                raise RuntimeError("GetExtremePoint returned False")
            box[i] = pt[i % 3]
        return box
    except Exception:
        return list(body.GetBodyBox())


def parts_box(bodies) -> list[float]:
    """Box around EVERY body. A sawcut part is several bodies by design (SB12059's four collet
    pads); the first body's box alone failed a correct part (E031)."""
    boxes = [body_box(b) for b in bodies]
    return [min(x[i] for x in boxes) for i in range(3)] + [max(x[i] for x in boxes) for i in range(3, 6)]


def origin_centered(bbox: list[float], tol_m: float = 1e-6) -> bool:
    """MTI: the base body is symmetric about the three base planes (box centered on the
    origin). ``bbox`` is a SolidWorks body box in meters."""
    return all(abs(bbox[i] + bbox[i + 3]) / 2 <= tol_m for i in range(3))


def compile_solidworks(sw_app, plan: BuildPlan, dims: dict[str, float], fmap: dict[str, Any],
                       out_dir: Path, template: Optional[str] = None,
                       pmap: Optional[PlaneMap] = None, progress=None,
                       convention: str = "mti", keep_open: bool = False) -> SwBuildReport:
    """Build the plan in SolidWorks, verifying each feature against the CadQuery reference.

    ``convention``: ``"mti"`` (centered origin, Top-plane base, Mid Plane, Up To Next) or
    ``"drawing"`` (the drawing frame as-is). ``progress(feature, result)``, if given, is
    called after each feature (live demos). The part is closed after it is saved unless
    ``keep_open``: a batch that leaves every part open stops SolidWorks creating new ones
    (86 open parts: NewDocument returned None; error log E024)."""
    from pipeline.solidworks_builder import _close_open_sketch, export_stl, save_model

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
        if convention == "mti" and isinstance(f, Hole) and not is_radial(f):   # same hole, same face: one feature
            nxt = features[i] if i < len(features) else None
            if (isinstance(nxt, Pattern) and nxt.seed == f.id and nxt.status == "planned"
                    and nxt.id not in skipped):
                group.append(nxt)                          # seed + its pattern: one feature
            else:
                group += mergeable_holes(features[i:], f, dims, skipped)
            i += len(group) - 1
        try:
            if len(group) == 2 and isinstance(group[1], Pattern):
                res = sw.hole_and_pattern(*group)
            elif len(group) > 1:
                res = sw.hole_group(group)
            else:
                res = getattr(sw, f.kind)(f)
        except Exception as e:  # COM errors: record, keep building (non-strict, like v1)
            _close_open_sketch(sw.doc)
            import traceback
            ours = [t for t in traceback.extract_tb(e.__traceback__) if t.filename == __file__]
            at = (ours or traceback.extract_tb(e.__traceback__))[-1]   # COM errors don't say which call
            res = SwFeatureResult(group[-1].id, "failed",
                                  note=f"{type(e).__name__}: {e} (at {at.name}:{at.lineno})"[:300])
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
            sw.report.origin_ok = body is not None and origin_centered(body_box(body))
        if progress is not None:
            progress(f, res)

    vol = sw.volume()
    sw.report.sketches = dict(sw.sketch_status)
    under = [k for k, v in sw.sketch_status.items() if v != FULLY_CONSTRAINED]
    if sw.sketch_status:
        sw.report.conventions.append(
            f"sketches fully defined: {len(sw.sketch_status) - len(under)}/{len(sw.sketch_status)}"
            + (f" (not: {', '.join(under)})" if under else ""))
    ref_vol = fmap["volume"] - sw.extra_removed   # Hole Wizard drill points (exact cones)
    sw.report.volume_ok = abs(vol - ref_vol) <= max(VOL_REL_TOL * ref_vol, 1e-6)
    if sw.cosmetic_threads:   # show them, as MTI's ToggleCosmeticThreads macro does
        sw.doc.Extension.SetUserPreferenceToggle(SW_DISPLAY_COSMETIC_THREADS, 0, True)
    bodies = sw.doc.GetBodies2(0, False)
    if bodies:
        bb = parts_box(bodies)
        ext = sorted((bb[i + 3] - bb[i]) / sw.k for i in range(3))
        ref = sorted(fmap["bbox"][i + 3] - fmap["bbox"][i] for i in range(3))
        sw.report.bbox_ok = all(abs(a - b) <= 1e-4 * max(1.0, b) for a, b in zip(ext, ref))
    sw.doc.SketchManager.AddToDB = False   # hand the part back with normal sketch behaviour
    sw.report.sldprt = save_model(sw.doc, f"{plan.part}_ir", out_dir)
    sw.report.stl = export_stl(sw.doc, sw.report.sldprt)   # viewing copy beside the .sldprt
    try:  # an isometric picture for review (best effort)
        sw.doc.ShowNamedView2("*Isometric", 7)
        sw.doc.ViewZoomtofit2()
        sw.doc.SaveAs3(str((Path(out_dir) / f"{plan.part}_ir.png").resolve()), 0, 1)
    except Exception as e:
        log.warning("Could not export a PNG view: %s", e)
    if not keep_open:
        from pipeline.solidworks_builder import _g
        sw_app.CloseDoc(_g(sw.doc, "GetTitle"))
    return sw.report
