"""Feature-aware dimensioning on a native drawing.

Every required characteristic goes into the coverage ledger FIRST, with exactly one preferred annotation; the annotation is then created as a native,
associative SOLIDWORKS dimension on the visible edges of the best view; its measured value is read back and compared with the exact source geometry
before the ledger item is marked ``covered``.  Anything that cannot be done safely becomes ``review_required`` with an actionable issue; nothing is
dropped silently, and no tolerance, finish, thread or datum intent is ever invented.
"""
from __future__ import annotations

import logging
import math
from typing import Optional

from reverse import qa
from reverse.planner import VIEWS
from reverse.qa import Ledger, LedgerItem

log = logging.getLogger(__name__)

LANE_STEP = 0.011            # 11 mm between stacked dimension lines on the sheet
LANE_FIRST = 0.013
SW_TEXT_PREFIX = 1           # swDimensionTextPrefix
TOL_M = 2e-6                 # a measured value must match the exact geometry within 2 micrometres (software check, not a manufacturing tolerance)
VIEW_ROLE_FOR = {"*Front": "front", "*Top": "top", "*Right": "right"}
# which standard view shows the circular end of a hole with this axis and entry side
VIEW_FOR_AXIS = {("z", "+"): "*Front", ("z", "-"): "*Back", ("y", "+"): "*Top", ("y", "-"): "*Bottom", ("x", "+"): "*Right", ("x", "-"): "*Left"}


def _sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def _norm3(v) -> float:
    return math.sqrt(sum(c * c for c in v))


def flatten(p, axis: int):
    """Drop the view-normal coordinate: a dimension is measured in the view plane, so two points at different depths along the view axis (a
    counterbore floor vs the part face) are compared in that plane."""
    q = list(p)
    q[axis] = 0.0
    return q


def point_line_distance(p, a, b, axis: Optional[int] = None) -> float:
    """Exact model-space distance (metres) from point p to the infinite line through a, b, measured in the view plane when ``axis`` is given."""
    if axis is not None:
        p, a, b = flatten(p, axis), flatten(a, axis), flatten(b, axis)
    d = _sub(b, a)
    w = _sub(p, a)
    cr = [d[1] * w[2] - d[2] * w[1], d[2] * w[0] - d[0] * w[2], d[0] * w[1] - d[1] * w[0]]
    return _norm3(cr) / (_norm3(d) or 1.0)


def point_distance(a, b, axis: Optional[int] = None) -> float:
    if axis is not None:
        a, b = flatten(a, axis), flatten(b, axis)
    return _norm3(_sub(a, b))


class ViewCtx:
    """One drawing view: its visible edges mapped to sheet space, and lane counters for stacked dimensions."""

    def __init__(self, dd, role: str, sw_view: str):
        self.dd, self.role, self.sw_view = dd, role, sw_view
        s = dd.s
        self.T = s.typed
        self.v = self.T(dd.views[role], "IView")
        self.outline = [float(x) for x in self.v.GetOutline()]
        self.xf = self.T(self.v.ModelToViewTransform, "IMathTransform")
        self.mu = self.T(self.T(s.app, "ISldWorks").GetMathUtility(), "IMathUtility")
        self.lanes = {"top": 0, "bottom": 0, "left": 0, "right": 0}
        self.edges: list[dict] = []
        self._read_edges()

    def to_sheet(self, p) -> tuple[float, float]:
        from pipeline.solidworks_builder import com_doubles
        mp = self.T(self.mu.CreatePoint(com_doubles(*p)), "IMathPoint")
        r = self.T(mp.MultiplyTransform(self.xf), "IMathPoint")
        a = r.ArrayData
        return (float(a[0]), float(a[1]))

    def _read_edges(self) -> None:
        ents = self.v.GetVisibleEntities2(None, 1) or ()          # swViewEntityType_Edge
        for e in ents:
            try:
                te = self.T(e, "IEdge")
                cv = self.T(te.GetCurve(), "ICurve")
                if cv.IsLine():
                    p = te.GetCurveParams2()
                    a, b = self.to_sheet(p[0:3]), self.to_sheet(p[3:6])
                    self.edges.append({"ent": e, "kind": "line", "m0": list(p[0:3]), "m1": list(p[3:6]), "s0": a, "s1": b})
                elif cv.IsCircle():
                    cp = cv.CircleParams
                    self.edges.append({"ent": e, "kind": "circle", "center_m": list(cp[0:3]), "axis": list(cp[3:6]), "radius_m": float(cp[6]),
                                       "sc": self.to_sheet(cp[0:3])})
            except Exception as ex:      # noqa: BLE001 - an edge we cannot read is skipped, not fatal
                log.debug("edge skipped: %s", ex)

    # ------------------------------------------------------------ edge finders (sheet-space, so any view orientation works)
    def silhouette(self, side: str) -> Optional[dict]:
        """The straight edge forming the left/right/bottom/top extreme of the view outline."""
        want_vertical = side in ("left", "right")
        cands = []
        for e in self.edges:
            if e["kind"] != "line":
                continue
            dx, dy = abs(e["s0"][0] - e["s1"][0]), abs(e["s0"][1] - e["s1"][1])
            if want_vertical and dx < 1e-7 and dy > 1e-6:
                cands.append((e["s0"][0], e))
            if not want_vertical and dy < 1e-7 and dx > 1e-6:
                cands.append((e["s0"][1], e))
        if not cands:
            return None
        return (min if side in ("left", "bottom") else max)(cands, key=lambda t: t[0])[1]

    def circle_for(self, hole: dict, which: str = "smallest") -> Optional[dict]:
        """A visible circle edge belonging to this hole (matched on the two perpendicular centre coordinates and the axis direction)."""
        ax = "xyz".index(hole["axis"])
        perp = [j for j in range(3) if j != ax]
        best = []
        for e in self.edges:
            if e["kind"] != "circle":
                continue
            if abs(abs(e["axis"][ax]) - 1.0) > 1e-4:
                continue
            if all(abs(e["center_m"][j] - hole["center_m"][i]) < 5e-5 for i, j in enumerate(perp)):
                best.append(e)
        if not best:
            return None
        return (min if which == "smallest" else max)(best, key=lambda e: e["radius_m"])

    def lane(self, side: str) -> float:
        """Sheet coordinate of the next free dimension lane on this side of the view."""
        n = self.lanes[side]
        self.lanes[side] += 1
        off = LANE_FIRST + n * LANE_STEP
        x0, y0, x1, y1 = self.outline
        return {"top": y1 + off, "bottom": y0 - off, "left": x0 - off, "right": x1 + off}[side]


class Dimensioner:
    def __init__(self, dd, inventory: dict, plan: dict, part_id: str = "P"):
        self.dd = dd
        self.s = dd.s
        self.T = dd.s.typed
        self.inv = inventory
        self.plan = plan
        self.part_id = part_id
        self.ledger = Ledger()
        self.issues: list[dict] = []
        self.ctx: dict[str, ViewCtx] = {}
        self.annotations: list[dict] = []
        self.units = dd.units
        self._n = 0

    # ------------------------------------------------------------ plumbing
    def _id(self, p: str) -> str:
        self._n += 1
        return f"{p}{self._n:03d}"

    def _clear(self):
        self.dd.mdl.ClearSelection2(True)

    def _select(self, ents: list, ) -> bool:
        self._clear()
        for i, e in enumerate(ents):
            if not self.T(e, "IEntity").Select4(i > 0, None):
                return False
        return True

    def _measured_m(self, dd_obj) -> Optional[float]:
        try:
            dim = self.T(self.T(dd_obj, "IDisplayDimension").GetDimension2(0), "IDimension")
            return float(dim.SystemValue)        # SI metres regardless of the document's display units (verified on 2025 SP5)
        except Exception:      # noqa: BLE001
            return None

    def _record(self, dd_obj, ann_id: str, text_hint: str = "") -> Optional[float]:
        prec = 3 if self.units == "inch" else 2          # explicit display precision; exact values stay in the ledger
        try:
            self.T(dd_obj, "IDisplayDimension").SetPrecision3(prec, prec, prec, prec)
        except Exception as e:      # noqa: BLE001
            self.dd.warnings.append(f"display precision: {e}")
        val = self._measured_m(dd_obj)
        try:
            an = self.T(self.T(dd_obj, "IDisplayDimension").GetAnnotation(), "IAnnotation")
            pos = [float(x) for x in an.GetPosition()]
        except Exception:      # noqa: BLE001
            pos = None
        self.annotations.append({"id": ann_id, "text": text_hint, "measured_m": val, "position": pos})
        return val

    def view(self, role: str, sw_view: str) -> ViewCtx:
        if role not in self.ctx:
            self.ctx[role] = ViewCtx(self.dd, role, sw_view)
        return self.ctx[role]

    def _flag(self, sev: str, code: str, msg: str, **kw) -> dict:
        i = qa.issue(sev, code, msg, part_id=self.part_id, **kw)
        self.issues.append(i)
        return i

    def _check(self, item: LedgerItem, measured: Optional[float], expected: float, ann: str, view: str, text: str = "") -> None:
        item.annotation_id, item.view = ann, view
        if measured is None:
            item.status, item.reason = "review_required", "the dimension was created but its value could not be read back"
            self._flag("medium", "VALUE_UNREAD", f"{item.characteristic}: value not read back", source_ref=ann, view=view)
        elif abs(measured - expected) <= TOL_M:
            item.status = "covered"
            item.evidence = f"measured {measured * 1000:.4f} mm vs source {expected * 1000:.4f} mm"
        else:
            item.status, item.reason = "review_required", f"measured {measured * 1000:.4f} mm differs from source {expected * 1000:.4f} mm"
            self._flag("high", "VALUE_MISMATCH", f"{item.characteristic}: drawing shows {measured * 1000:.4f} mm, geometry is {expected * 1000:.4f} mm",
                       source_ref=ann, view=view, observed=f"{measured * 1000:.4f} mm", expected=f"{expected * 1000:.4f} mm",
                       next_action="Check the dimension references; do not release until corrected.")

    # ------------------------------------------------------------ overall size
    def overall(self) -> None:
        size = self.inv["size_m"]
        plan_views = self.plan["views"]
        f_name, t_name = plan_views["front"], plan_views["top"]
        fh, fv, _ = VIEWS[f_name]
        th, tv, _ = VIEWS[t_name]
        ext = dict(zip("xyz", size))
        front = self.view("front", f_name)
        top = self.view("top", t_name)
        # width (front horizontal), height (front vertical), depth (top vertical) - three characteristics, three annotations, no repeats
        jobs = [("length", fh, front, "horizontal", "left", "right", "top"), ("height", fv, front, "vertical", "bottom", "top", "left"),
                ("depth", tv if tv not in (fh, fv) else th, top, "vertical", "bottom", "top", "left")]
        if len({fh, fv, tv}) < 3:        # the top view shows the third axis vertically unless the front uses it; fall back to its other axis
            third = [a for a in "xyz" if a not in (fh, fv)][0]
            jobs[2] = ("depth", third, top, "vertical" if tv == third else "horizontal", "bottom", "top", "left")
        for name, axis, ctx, orient, ea, eb, lane_side in jobs:
            item = self.ledger.add(LedgerItem(id=self._id("L"), characteristic=f"body:extent_{axis}", category="size", source="geometry_derived",
                                              value=ext[axis], feature_id="BODY"))
            try:
                a, b = ctx.silhouette(ea if orient == "vertical" else "left"), ctx.silhouette(eb if orient == "vertical" else "right")
                if a is None or b is None:
                    raise RuntimeError("silhouette edges not found")
                if not self._select([a["ent"], b["ent"]]):
                    raise RuntimeError("could not select the silhouette edges")
                x0, y0, x1, y1 = ctx.outline
                if orient == "horizontal":
                    dd_obj = self.dd.mdl.AddHorizontalDimension2((x0 + x1) / 2, ctx.lane("top"), 0)
                else:
                    dd_obj = self.dd.mdl.AddVerticalDimension2(ctx.lane("left"), (y0 + y1) / 2, 0)
                if dd_obj is None:
                    raise RuntimeError("SOLIDWORKS returned no dimension")
                aid = self._id("D")
                m = self._record(dd_obj, aid, f"{name} {axis}")
                self._check(item, m, ext[axis], aid, ctx.role)
            except Exception as e:      # noqa: BLE001
                item.status, item.reason = "unresolved", f"{type(e).__name__}: {e}"
                self._flag("high", "OVERALL_DIM_FAILED", f"Overall {name} ({axis}) could not be dimensioned: {e}", view=ctx.role,
                           next_action="Dimension this overall size manually in the drawing.")
        self._clear()

    # ------------------------------------------------------------ holes
    def _hole_view(self, hole: dict) -> tuple[str, str]:
        """(role, sw view name) of the view that shows this hole's circular end; adds an extra view when it is not one of the three."""
        side = hole["entry_side"] if hole["entry_side"] in ("+", "-") else "+"
        want = VIEW_FOR_AXIS[(hole["axis"], side)]
        views = self.plan["views"]
        for role in ("front", "top", "right"):
            if views[role] == want:
                return role, want
        role = "extra_" + want.strip("*").lower()
        return role, want

    def holes(self) -> None:
        inv = self.inv
        pats = {tuple(p["ids"]): p for p in inv["patterns"]}
        in_pattern = {i for p in inv["patterns"] if p["rectangular_grid"] for i in p["ids"]}
        done_pattern: set[tuple] = set()
        by_id = {h["id"]: h for h in inv["holes"]}
        callout_y: dict[str, float] = {}
        for h in inv["holes"]:
            role, sw_view = self._hole_view(h)
            if role not in self.dd.views:
                it = self.ledger.add(LedgerItem(id=self._id("L"), characteristic=f"{h['id']}:callout", category="feature", source="geometry_derived",
                                                feature_id=h["id"], status="review_required",
                                                reason=f"the {sw_view} view that shows this hole was not created"))
                self._flag("high", "HOLE_VIEW_MISSING", f"{h['id']} (axis {h['axis']}) is only visible from {sw_view}; that view is not on the sheet", view=role,
                           next_action="Add the view or a section through the hole and dimension it.")
                continue
            ctx = self.view(role, sw_view)
            pat = next((p for p in inv["patterns"] if h["id"] in p["ids"] and p["rectangular_grid"]), None)
            key = tuple(pat["ids"]) if pat else (h["id"],)
            first_of_pattern = pat is None or key not in done_pattern
            if pat is not None:
                done_pattern.add(key)
            if first_of_pattern:
                self._callout(h, ctx, pat, callout_y, [by_id[i] for i in pat["ids"]] if pat else None)
                self._locate(h, ctx, pat, by_id)
            elif pat is not None:
                it = self.ledger.add(LedgerItem(id=self._id("L"), characteristic=f"{h['id']}:callout", category="feature", source="geometry_derived", feature_id=h["id"],
                                                status="covered", evidence=f"one callout and one location scheme cover the {pat['count']}-hole pattern ({', '.join(pat['ids'])})"))
        self._clear()

    def _callout(self, h: dict, ctx: ViewCtx, pat: Optional[dict], ys: dict, holes_in_pattern: Optional[list] = None) -> None:
        item = self.ledger.add(LedgerItem(id=self._id("L"), characteristic=f"{h['id']}:diameter", category="feature", source="geometry_derived",
                                          value=h["diameter_m"], feature_id=h["id"]))
        cands = [c for c in (ctx.circle_for(x, "smallest") for x in (holes_in_pattern or [h])) if c is not None]
        circ = max(cands, key=lambda c: (round(c["sc"][0], 6), round(c["sc"][1], 6))) if cands else None   # rightmost, then topmost: nearest the right-hand lane
        if circ is None:
            item.status, item.reason = "unresolved", f"no visible circle edge for this hole in the {ctx.role} view"
            self._flag("high", "HOLE_EDGE_NOT_FOUND", f"{h['id']}: no visible circular edge in {ctx.role}", view=ctx.role,
                       next_action="Add a section or detail view through this hole.")
            return
        try:
            if not self._select([circ["ent"]]):
                raise RuntimeError("could not select the hole circle")
            x0, y0, x1, y1 = ctx.outline
            cx, cy = circ["sc"]
            ly = ys.setdefault(ctx.role, y1 + 0.004)
            lx = ctx.lane("right")
            co = self.dd.drw.AddHoleCallout2(lx, cy + 0.006, 0)
            if co is None:
                raise RuntimeError("AddHoleCallout2 returned nothing")
            aid = self._id("C")
            if pat is not None and pat["count"] > 1:
                try:
                    self.T(co, "IDisplayDimension").SetText(SW_TEXT_PREFIX, f"{pat['count']}X <MOD-DIAM>")
                except Exception as e:      # noqa: BLE001
                    self.dd.warnings.append(f"hole multiplier text: {e}")
            m = self._record(co, aid, "hole callout")
            self._check(item, m, h["diameter_m"], aid, ctx.role)
        except Exception as e:      # noqa: BLE001
            item.status, item.reason = "unresolved", f"{type(e).__name__}: {e}"
            self._flag("high", "HOLE_CALLOUT_FAILED", f"{h['id']}: hole callout failed: {e}", view=ctx.role, next_action="Dimension this hole manually.")
        # depth / counterbore characteristics
        if not h["through"]:
            d = self.ledger.add(LedgerItem(id=self._id("L"), characteristic=f"{h['id']}:depth", category="feature", source="geometry_derived", value=h["depth_m"],
                                           feature_id=h["id"], view=ctx.role, status="review_required",
                                           reason="blind-hole depth: the native callout is checked by the engineer (no section view is generated in this version)"))
            self._flag("medium", "BLIND_DEPTH_REVIEW", f"{h['id']}: blind depth {h['depth_m'] * 1000:.3f} mm is carried by the callout/hidden geometry; confirm or add a section view",
                       view=ctx.role, observed=f"{h['depth_m'] * 1000:.3f} mm", next_action="Confirm the depth on the drawing or add a section view.")
        if h.get("counterbore"):
            c = self.ledger.add(LedgerItem(id=self._id("L"), characteristic=f"{h['id']}:counterbore", category="feature", source="geometry_derived",
                                           value=h["counterbore"]["diameter_m"], feature_id=h["id"], view=ctx.role, status="review_required",
                                           reason="counterbore diameter and depth need a section or detail view"))
            self._flag("medium", "COUNTERBORE_REVIEW",
                       f"{h['id']}: counterbore dia {h['counterbore']['diameter_m'] * 1000:.3f} mm x {h['counterbore']['depth_m'] * 1000:.3f} mm needs a section view",
                       view=ctx.role, next_action="Add a section view through the hole and dimension the counterbore.")
        if h.get("cone"):
            self._flag("low", "CONE_PRESENT", f"{h['id']}: a conical face (drill point or countersink) is present; its size is not dimensioned automatically", view=ctx.role,
                       next_action="Confirm whether the drill point is a requirement or cosmetic.")

    def _dim_between(self, ents: list, orient: str, at: tuple[float, float]):
        if not self._select(ents):
            return None
        return (self.dd.mdl.AddHorizontalDimension2 if orient == "h" else self.dd.mdl.AddVerticalDimension2)(at[0], at[1], 0)

    def _locate(self, h: dict, ctx: ViewCtx, pat: Optional[dict], by_id: dict) -> None:
        """Location of the hole (pattern): first row/column from the part's own silhouette edges, then ONE pitch per direction. Circles are dimensioned
        to their centre (SOLIDWORKS defaults the circle end of an edge-to-circle dimension to the arc centre; verified by reading the value back)."""
        holes = [by_id[i] for i in pat["ids"]] if pat else [h]
        ax = "xyz".index(h["axis"])
        perp = [j for j in range(3) if j != ax]
        circles = {x["id"]: ctx.circle_for(x, "smallest") for x in holes}
        if any(c is None for c in circles.values()):
            it = self.ledger.add(LedgerItem(id=self._id("L"), characteristic=f"{h['id']}:location", category="location", source="geometry_derived", feature_id=h["id"],
                                            status="unresolved", reason=f"hole circles not all visible in {ctx.role}"))
            self._flag("high", "HOLE_LOCATION_FAILED", f"{h['id']}: hole circles are not all visible in {ctx.role}", view=ctx.role)
            return
        # sheet-space rows/columns
        xs = sorted({round(c["sc"][0], 6) for c in circles.values()})
        ys = sorted({round(c["sc"][1], 6) for c in circles.values()})
        left, bottom = ctx.silhouette("left"), ctx.silhouette("bottom")
        x0, y0, x1, y1 = ctx.outline
        plan_items = []
        # horizontal: left edge -> first column; pitch between adjacent columns (using the bottom-most row's circles)
        row_circles = sorted(circles.values(), key=lambda c: (round(c["sc"][1], 6), c["sc"][0]))
        bottom_row = [c for c in row_circles if abs(c["sc"][1] - ys[0]) < 1e-6]
        left_col = sorted(circles.values(), key=lambda c: (round(c["sc"][0], 6), c["sc"][1]))
        left_col = [c for c in left_col if abs(c["sc"][0] - xs[0]) < 1e-6]
        # expected values are computed in exact MODEL space (not from the sheet), so the check is independent of the drawing
        scale = self.plan["scale"]["num"] / self.plan["scale"]["den"]
        lane_h = ctx.lane("bottom")
        # first column from the left edge
        ref_l = left
        if ref_l is not None:
            c0 = sorted(bottom_row, key=lambda c: c["sc"][0])[0]
            exp = point_line_distance(c0["center_m"], ref_l["m0"], ref_l["m1"], ax)
            item = self.ledger.add(LedgerItem(id=self._id("L"), characteristic=f"{h['id']}:location_h_from_edge", category="location", source="geometry_derived",
                                              value=exp, feature_id=h["id"]))
            try:
                dd_obj = self._dim_between([c0["ent"], ref_l["ent"]], "h", ((c0["sc"][0] + ref_l["s0"][0]) / 2, lane_h))
                if dd_obj is None:
                    raise RuntimeError("no dimension created")
                aid = self._id("D")
                self._check(item, self._record(dd_obj, aid, "hole x from edge"), exp, aid, ctx.role)
            except Exception as e:      # noqa: BLE001
                item.status, item.reason = "unresolved", str(e)
                self._flag("high", "HOLE_LOCATION_FAILED", f"{h['id']} horizontal location: {e}", view=ctx.role)
        if len(xs) > 1:
            cs = sorted(bottom_row, key=lambda c: c["sc"][0])[:2]
            exp = point_distance(cs[0]["center_m"], cs[1]["center_m"], ax)
            item = self.ledger.add(LedgerItem(id=self._id("L"), characteristic=f"{h['id']}:pitch_h", category="location", source="geometry_derived", value=exp,
                                              feature_id=h["id"]))
            try:
                dd_obj = self._dim_between([cs[0]["ent"], cs[1]["ent"]], "h", ((cs[0]["sc"][0] + cs[1]["sc"][0]) / 2, ctx.lane("bottom")))
                if dd_obj is None:
                    raise RuntimeError("no dimension created")
                aid = self._id("D")
                self._check(item, self._record(dd_obj, aid, "hole pitch x"), exp, aid, ctx.role)
            except Exception as e:      # noqa: BLE001
                item.status, item.reason = "unresolved", str(e)
                self._flag("high", "HOLE_LOCATION_FAILED", f"{h['id']} horizontal pitch: {e}", view=ctx.role)
        # vertical: bottom edge -> first row (left-most column); pitch between rows
        if bottom is not None:
            c0 = sorted(left_col, key=lambda c: c["sc"][1])[0]
            exp = point_line_distance(c0["center_m"], bottom["m0"], bottom["m1"], ax)
            item = self.ledger.add(LedgerItem(id=self._id("L"), characteristic=f"{h['id']}:location_v_from_edge", category="location", source="geometry_derived",
                                              value=exp, feature_id=h["id"]))
            try:
                dd_obj = self._dim_between([c0["ent"], bottom["ent"]], "v", (ctx.lane("left"), (c0["sc"][1] + bottom["s0"][1]) / 2))
                if dd_obj is None:
                    raise RuntimeError("no dimension created")
                aid = self._id("D")
                self._check(item, self._record(dd_obj, aid, "hole y from edge"), exp, aid, ctx.role)
            except Exception as e:      # noqa: BLE001
                item.status, item.reason = "unresolved", str(e)
                self._flag("high", "HOLE_LOCATION_FAILED", f"{h['id']} vertical location: {e}", view=ctx.role)
        if len(ys) > 1:
            cs = sorted(left_col, key=lambda c: c["sc"][1])[:2]
            exp = point_distance(cs[0]["center_m"], cs[1]["center_m"], ax)
            item = self.ledger.add(LedgerItem(id=self._id("L"), characteristic=f"{h['id']}:pitch_v", category="location", source="geometry_derived", value=exp,
                                              feature_id=h["id"]))
            try:
                dd_obj = self._dim_between([cs[0]["ent"], cs[1]["ent"]], "v", (ctx.lane("left"), (cs[0]["sc"][1] + cs[1]["sc"][1]) / 2))
                if dd_obj is None:
                    raise RuntimeError("no dimension created")
                aid = self._id("D")
                self._check(item, self._record(dd_obj, aid, "hole pitch y"), exp, aid, ctx.role)
            except Exception as e:      # noqa: BLE001
                item.status, item.reason = "unresolved", str(e)
                self._flag("high", "HOLE_LOCATION_FAILED", f"{h['id']} vertical pitch: {e}", view=ctx.role)

    # ------------------------------------------------------------ everything else the inventory knows about
    def residual_review(self) -> None:
        """Characteristics we deliberately do not invent: material/finish/tolerance/thread/datum intent, fillets/chamfers, bosses, unsupported geometry."""
        inv = self.inv
        if inv["faces"]["tori"]:
            self.ledger.add(LedgerItem(id=self._id("L"), characteristic="BODY:fillets_chamfers", category="feature", source="geometry_derived", status="review_required",
                                       reason=f"{inv['faces']['tori']} toroidal faces (fillets/rounds): radii are not dimensioned automatically in this version"))
            self._flag("medium", "FILLETS_REVIEW", f"{inv['faces']['tori']} rounded faces (fillets) are present and not dimensioned", next_action="Add fillet radii (or a general note).")
        if inv["faces"]["cones"] and not any(h.get("cone") for h in inv["holes"]):
            self._flag("medium", "CONES_REVIEW", f"{inv['faces']['cones']} conical faces (chamfers/countersinks) are not dimensioned automatically", next_action="Dimension chamfers.")
        for b in inv["bosses"]:
            self.ledger.add(LedgerItem(id=self._id("L"), characteristic=f"BOSS:{b['face']}", category="feature", source="geometry_derived", status="review_required",
                                       reason="a cylindrical boss/shaft diameter and length are not dimensioned automatically in this version"))
        if inv["bosses"]:
            self._flag("medium", "BOSSES_REVIEW", f"{len(inv['bosses'])} cylindrical bosses/shafts need diameters and axial lengths", next_action="Dimension revolved features.")
        for u in inv["unsupported"]:
            self._flag("medium", "UNSUPPORTED_GEOMETRY", u["note"], source_ref=str(u.get("face")), next_action="Review this feature manually.")
        if inv.get("freeform_or_multibody"):
            self._flag("high", "MULTIBODY_OR_FREEFORM", "; ".join(inv.get("notes") or ["multibody or freeform geometry"]), next_action="Engineering review of body selection and interfaces.")
        for what in ("tolerances", "surface finish", "thread specification", "datum scheme / GD&T"):
            self.ledger.add(LedgerItem(id=self._id("L"), characteristic=f"INTENT:{what}", category="feature", source="user_approved", status="review_required",
                                       reason=f"{what} are manufacturing intent that geometry cannot supply; not invented"))
        self._flag("info", "DESIGN_INTENT", "Tolerances, surface finish, thread specifications and datum scheme/GD&T are not in the part geometry and were not invented.",
                   next_action="Add them from the source design intent before release.")

    def run(self) -> dict:
        self.overall()
        self.holes()
        self.residual_review()
        return {"ledger": self.ledger.to_json(), "issues": self.issues, "annotations": self.annotations}
