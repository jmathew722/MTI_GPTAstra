"""plan_from_v1: deterministic DrawingData -> BuildPlan (IR v2, Task 3).

Two jobs (spec): migrate existing extractions, and act as the **baseline planner**
(the benchmark floor that any LLM planner must beat). It never guesses:

* frame: a circular base means ``axis_end`` (the part center is the axis); otherwise
  ``corner``. Same rule as the v1 fixes F1/F6 (STATE.md 3.0).
* numbers: a v1 value that equals a dimension (or half/double of one, or its
  negative) becomes that expression. Anything else becomes a literal with an
  ``untraced`` justification, visible in review.
* holes: instance positions come from the same logic the v1 builder uses
  (``macro_generator._hole_positions``: re-framing, bolt circles, seed circles).
* anything v1 can't ground is ``unresolved`` with the reason: revolves with no
  station data, turned grooves on side planes, edges with no parent.

Run ``run_models.resolve_unknowns`` on the raw extraction first, so the fastener table,
callout synthesis and counterbore folding apply (the same pipeline as v1).
"""
from __future__ import annotations

from typing import Optional

from pipeline.ir.model import BuildPlan
from pipeline.schema import DrawingData, Feature, FeatureType

_PLANES = {"front": "plane(front)", "": "plane(front)", "top": "plane(top)", "bottom": "plane(top)",
           "right": "plane(right)", "side": "plane(right)", "second_side": "plane(right)"}
TOL = 1e-6


class _Ctx:
    def __init__(self, model: DrawingData):
        self.m = model
        self.dims = {d.id: d.value for d in model.dimensions}
        self.untraced: dict[str, list[str]] = {}
        ids = {f.id for f in model.features}
        self._n = max((int(i[1:]) for i in ids if i[1:].isdigit()), default=0)

    def new_id(self) -> str:
        self._n += 1
        return f"F{self._n:03d}"

    def expr(self, value: float, fid: str, what: str, prefer: tuple[str, ...] = ()) -> str:
        """A traceable expression for ``value``, preferring the feature's own dims."""
        if abs(value) < TOL:
            return "0"
        order = list(prefer) + [d for d in self.dims if d not in prefer]
        for did in order:
            v = self.dims.get(did)
            if not v:
                continue
            for fmt, x in (("{}", v), ("-{}", -v), ("{} / 2", v / 2), ("-{} / 2", -v / 2), ("2 * {}", 2 * v)):
                if abs(value - x) < 1e-6:
                    return fmt.format(did)
        self.untraced.setdefault(fid, []).append(f"{what}={value:g}")
        return repr(round(value, 6))


def _justify(ctx: _Ctx, fid: str, extra: str = "") -> str:
    parts = []
    if fid in ctx.untraced:
        parts.append("untraced v1 values (not equal to any drawing dimension): " + ", ".join(ctx.untraced[fid]))
    if extra:
        parts.append(extra)
    return "; ".join(parts)


def _dim_of(model: DrawingData, f: Feature, *, types=("diameter",), exclude_bc=True) -> Optional[str]:
    from pipeline.macro_generator import _BOLT_CIRCLE_LABEL
    best = None
    for did in f.related_dimensions:
        d = model.dimension_by_id(did)
        if d is None or d.type.value not in types:
            continue
        if exclude_bc and _BOLT_CIRCLE_LABEL.search(d.applies_to or ""):
            continue
        if best is None or d.value > model.dimension_by_id(best).value:
            best = did
    return best


def _depth_id(model: DrawingData, f: Feature) -> Optional[str]:
    if f.depth_dimension_id and model.dimension_by_id(f.depth_dimension_id):
        return f.depth_dimension_id
    return None


def plan_from_v1(model: DrawingData) -> BuildPlan:
    from pipeline.macro_generator import _hole_positions, round_base
    from pipeline.solidworks_builder import planar_extents

    ctx = _Ctx(model)
    rb = round_base(model)
    frame = {"origin_kind": "axis_end" if rb else "corner", "units": model.units.value}
    base_id = model.build_order[0] if model.build_order else ""
    out: list[dict] = []
    notes: list[str] = [f"plan_from_v1 baseline from {model.part_number or model.part_name}"]

    def unresolved(f: Feature, why: str) -> None:
        """Placeholder feature (geometry fields are inert zeros); Gate 1 reports it."""
        common = {"id": f.id, "status": "unresolved", "rationale": f"{why} [{f.description[:120]}]"}
        if f.type in (FeatureType.FILLET, FeatureType.CHAMFER):
            out.append({"kind": "edge_op", "operation": f.type.value, "size": "0",
                        "edges": ["edge_between(plane(front), plane(front))"], **common})
        else:
            out.append({"kind": "prism", "profile": {"shape": "circle", "d": "0"}, "depth": "0", **common})

    def stack_offset(f: Feature) -> str:
        """Sum of the depths of earlier bosses in a dimension chain with this one (v1 rule)."""
        if not f.depth_dimension_id:
            return "0"
        chains = [set(c.component_dimension_ids) for c in model.relationships.dimension_chains
                  if f.depth_dimension_id in c.component_dimension_ids]
        parts = []
        for pid in model.build_order:
            if pid == f.id:
                break
            p = model.feature_by_id(pid)
            if (p is not None and p.type == FeatureType.EXTRUDE_BOSS and p.depth_dimension_id
                    and (p.sketch_plane or "front") == (f.sketch_plane or "front")
                    and any(p.depth_dimension_id in c for c in chains)):
                parts.append(p.depth_dimension_id)
        return " + ".join(parts) or "0"

    for fid in model.build_order:
        f = model.feature_by_id(fid)
        if f is None:
            continue
        on = _PLANES.get((f.sketch_plane or "front").lower(), "plane(front)")
        if f.type == FeatureType.REVOLVE:
            unresolved(f, "v1 revolve has no profile stations; needs a planner or a human")
            continue
        if f.type in (FeatureType.EXTRUDE_BOSS, FeatureType.EXTRUDE_CUT):
            op = "add" if f.type == FeatureType.EXTRUDE_BOSS else "cut"
            dia = _dim_of(model, f)
            depth = _depth_id(model, f)
            if op == "add" and not depth:
                unresolved(f, "boss has no depth dimension")
                continue
            if rb and on != "plane(front)" and dia and model.dimension_by_id(dia).value >= rb[2]:
                unresolved(f, "circular cut on a side plane of a turned part: a neck/groove that needs "
                              "revolve stations (v1 can't express it)")
                continue
            if dia:
                if f.position_known:
                    u = ctx.expr(f.offset_x, fid, "u", tuple(f.related_dimensions))
                    v = ctx.expr(f.offset_y, fid, "v", tuple(f.related_dimensions))
                else:
                    u, v = "0", "0"   # coaxial: the part center (axis_end) / v1 rule F1
                    if not rb:
                        from pipeline.macro_generator import part_center
                        cx, cy = part_center(model)
                        u, v = ctx.expr(cx, fid, "u"), ctx.expr(cy, fid, "v")
                profile = {"shape": "circle", "d": dia, "u": u, "v": v}
            else:
                xy = planar_extents(model, f)
                if not xy:
                    unresolved(f, "no circle or rectangle profile in the v1 dimensions")
                    continue
                ids = [d for d in f.related_dimensions if d != f.depth_dimension_id]
                w = ctx.expr(xy[0], fid, "w", tuple(ids))
                h = ctx.expr(xy[1], fid, "h", tuple(ids))
                u = ctx.expr(f.offset_x, fid, "u") if f.position_known else "0"
                v = ctx.expr(f.offset_y, fid, "v") if f.position_known else "0"
                profile = {"shape": "rect", "anchor": "corner", "w": w, "h": h, "u": u, "v": v}
            offset = stack_offset(f) if (op == "add" and fid != base_id) else "0"
            feat = {"kind": "prism", "id": fid, "on": on, "offset": offset, "op": op, "profile": profile,
                    "depth": depth if depth else "thru", "rationale": f.description[:200],
                    "justification": _justify(ctx, fid)}
            out.append(feat)
            continue
        if f.type == FeatureType.HOLE:
            h = model.hole_callout_for_feature(fid)
            if h is None or not h.diameter:
                unresolved(f, "hole has no diameter (callout missing or unreadable)")
                continue
            pts = _hole_positions(model, h)
            prefer = tuple(f.related_dimensions)
            spec = {"type": {"thru": "thru", "blind": "blind", "counterbore": "cbore",
                             "countersink": "csink", "tapped": "tapped"}.get(h.type.value, "thru"),
                    "d": ctx.expr(h.diameter, fid, "d", prefer)}
            if spec["type"] == "cbore" and not h.thru and h.depth:
                spec["depth"] = ctx.expr(h.depth, fid, "depth", prefer)
            if spec["type"] in ("blind", "tapped"):
                if not h.depth:
                    unresolved(f, "blind/tapped hole with no depth")
                    continue
                spec["depth"] = ctx.expr(h.depth, fid, "depth", prefer)
            if spec["type"] == "cbore":
                spec["cbore_d"] = ctx.expr(h.cbore_diameter, fid, "cbore_d", prefer)
                spec["cbore_depth"] = ctx.expr(h.cbore_depth, fid, "cbore_depth", prefer)
            if spec["type"] == "csink":
                unresolved(f, "countersinks are not compiled yet")
                continue
            spec_note = _justify(ctx, fid)      # untraced spec values (e.g. STANDARD-DERIVED sizes)
            ctx.untraced.pop(fid, None)
            for n, (x, y) in enumerate(pts):
                hid = fid if n == 0 else ctx.new_id()
                u, v = ctx.expr(x, hid, "u", prefer), ctx.expr(y, hid, "v", prefer)
                why = [s for s in (spec_note, _justify(ctx, hid),
                                   "positions from v1 _hole_positions" if len(pts) > 1 else "") if s]
                out.append({"kind": "hole", "id": hid, "on": "plane(front)", "u": u, "v": v, "spec": spec,
                            "rationale": f"{f.description[:150]} (instance {n + 1}/{len(pts)})",
                            "source_callouts": [h.thread_spec] if h.thread_spec else [],
                            "justification": "; ".join(why)})
            continue
        if f.type == FeatureType.PATTERN:
            notes.append(f"{fid} (pattern) is realized by its seed's instances.")
            continue
        if f.type in (FeatureType.FILLET, FeatureType.CHAMFER):
            parent = model.feature_by_id(f.parent_feature) if f.parent_feature else None
            size_id = next((d for d in f.related_dimensions if model.dimension_by_id(d)
                            and model.dimension_by_id(d).type.value != "angular"), None)
            if parent is None or size_id is None or parent.type not in (FeatureType.HOLE, FeatureType.EXTRUDE_CUT) \
                    or not any(x["id"] == parent.id and x.get("status", "planned") == "planned" for x in out):
                unresolved(f, "v1 has no edge data; edges need a planner or a human")
                continue
            out.append({"kind": "edge_op", "id": fid, "operation": f.type.value, "size": size_id,
                        "edges": [f"edge_between(face({base_id},-Z), wall({parent.id}))",
                                  f"edge_between(face({base_id},+Z), wall({parent.id}))"],
                        "rationale": f"EDGES INFERRED (v1 rule: both mouths of {parent.id}). {f.description[:120]}"})
            continue
        unresolved(f, f"v1 feature type {f.type.value} has no IR mapping here")

    return BuildPlan.model_validate({"part": model.part_number or model.part_name or "part",
                                     "frame": frame, "features": out, "notes": notes})


def dims_of(model: DrawingData) -> dict[str, float]:
    return {d.id: d.value for d in model.dimensions}


def reference_ids(model: DrawingData) -> frozenset[str]:
    return frozenset({d.id for d in model.dimensions if d.is_reference}
                     | set(model.relationships.reference_dimension_ids))
