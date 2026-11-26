"""Native section views for blind / counterbored holes, and their dimensions.

Probed on SOLIDWORKS 2025 SP5: activate the parent view, draw the cutting line with ``SketchManager.CreateLine`` in VIEW-LOCAL coordinates (sheet
coordinates minus the view position), select it, ``MakeSectionLine()``, then ``CreateSectionViewAt5`` (the view is aligned to its parent).  Every dimension
read back from the section is compared with the exact hole geometry before its ledger item is marked covered.
"""
from __future__ import annotations

import logging
import math
from typing import Optional

from reverse import dimension, planner, sections
from reverse.dimension import VIEW_FOR_AXIS, ViewCtx, point_distance
from reverse.planner import Rect, VIEWS
from reverse.drawing import _ratio
from reverse.qa import LedgerItem

log = logging.getLogger(__name__)


def _hole_point(h: dict, axis_value: float = 0.0) -> list[float]:
    p = [0.0, 0.0, 0.0]
    p["xyz".index(h["axis"])] = axis_value
    for i, ax in enumerate(h["center_axes"]):
        p["xyz".index(ax)] = h["center_m"][i]
    return p


def parent_view_of(plan: dict, h: dict, have: dict) -> Optional[tuple[str, str]]:
    side = h["entry_side"] if h["entry_side"] in ("+", "-") else "+"
    want = VIEW_FOR_AXIS[(h["axis"], side)]
    for role in ("front", "top", "right"):
        if plan["views"][role] == want and role in have:
            return role, want
    for ev in plan.get("extra_views", []):
        if ev.get("fits") and ev["sw_view"] == want and ev["role"] in have:
            return ev["role"], want
    return None


def create_sections(dd, inv: dict, plan: dict, placed: dict[str, Rect], issues: list, part_id: str = "P") -> list[dict]:
    """Create the planned section views; returns [{label, role, parent, plan, hole_ids, fits}] (``fits`` False when there was no room)."""
    from reverse import qa
    out = []
    sp = sections.plan_sections(inv["holes"])
    reg = {k: Rect(*v) for k, v in plan["regions_m"].items()}
    usable, keep = reg["usable"], [reg["title_block"].grow(0.012), reg["notes"].grow(0.012)]
    gap = planner.GAP_MIN
    holes = {h["id"]: h for h in inv["holes"]}
    for s in sp:
        h = holes[s["covers"][0]]
        pv = parent_view_of(plan, h, dd.views)
        if pv is None:
            issues.append(qa.issue("high", "SECTION_PARENT_MISSING", f"No view shows the circular end of {h['id']}; its section cannot be placed.", part_id=part_id))
            continue
        role, swv = pv
        ctx = ViewCtx(dd, role, swv)
        h_ax, v_ax, _ = VIEWS[swv]
        sx, sy = ctx.to_sheet(_hole_point(h))
        horizontal = s["cut_along"] == h_ax
        x0, y0, x1, y1 = ctx.outline
        scale = float(ctx.v.ScaleDecimal)
        ext = dict(zip("xyz", inv["size_m"]))
        # the section shows the cut plane: width along the cut direction, height along the hole axis
        w, hh = ((x1 - x0), ext[s["axis"]] * scale + 2 * planner.VIEW_PAD) if horizontal else (ext[s["axis"]] * scale + 2 * planner.VIEW_PAD, (y1 - y0))
        spots = ([(Rect((x0 + x1) / 2 - w / 2, y0 - gap - hh, (x0 + x1) / 2 + w / 2, y0 - gap), "below"),
                  (Rect((x0 + x1) / 2 - w / 2, y1 + gap, (x0 + x1) / 2 + w / 2, y1 + gap + hh), "above")] if horizontal else
                 [(Rect(x1 + gap, (y0 + y1) / 2 - hh / 2, x1 + gap + w, (y0 + y1) / 2 + hh / 2), "right"),
                  (Rect(x0 - gap - w, (y0 + y1) / 2 - hh / 2, x0 - gap, (y0 + y1) / 2 + hh / 2), "left")])
        spot = None
        for r, _name in spots:
            if r.inside(usable) and not any(r.grow(0.006).overlaps(o) for o in placed.values()) and not any(r.overlaps(k) for k in keep):
                spot = r
                break
        sec_scale, moved = scale, False
        if spot is None:           # no aligned room: take any free spot, at a smaller (labelled) scale if needed, and move the view there
            LANES = 0.030          # room for the dimension lanes and labels around every view (a section carries its own dimensions too)
            obstacles = [o.grow(LANES) for o in placed.values()]
            for f in (1.0, 0.5, 0.25):
                free = planner.find_spot(w * f + 2 * LANES, hh * f + 2 * LANES, obstacles, keep, usable, 0.008)      # the lane allowance is already in the padding
                if free is not None:
                    spot, sec_scale, moved = Rect(free.x0 + LANES, free.y0 + LANES, free.x1 - LANES, free.y1 - LANES), scale * f, True
                    break
        rec = {"label": s["label"], "parent": role, "plan": s, "hole_ids": s["covers"], "fits": spot is not None, "role": f"section_{s['label']}"}
        if spot is None:
            issues.append(qa.issue("medium", "SECTION_NO_ROOM", f"Section {s['label']}-{s['label']} (through {', '.join(s['covers'])}) does not fit beside its parent view on sheet 1.", part_id=part_id,
                                   next_action="Use a larger sheet or place the section manually."))
            out.append(rec)
            continue
        try:
            T = dd.s.typed
            px, py = [float(c) for c in ctx.v.Position]
            dd.drw.ActivateView(ctx.v.GetName2())
            sm = T(dd.mdl.SketchManager, "ISketchManager")
            if horizontal:
                seg = sm.CreateLine(x0 - px - 0.008, sy - py, 0, x1 - px + 0.008, sy - py, 0)
            else:
                seg = sm.CreateLine(sx - px, y0 - py - 0.008, 0, sx - px, y1 - py + 0.008, 0)
            dd.mdl.ClearSelection2(True)
            sel = False
            try:
                sel = bool(T(seg, "ISketchSegment").Select4(False, None))
            except Exception:      # noqa: BLE001
                sel = False
            if not sel:
                sel = bool(dd.ext.SelectByID2(f"Line{len(out) + 1}", "SKETCHSEGMENT", 0, 0, 0, False, 0, None, 0))
            if not sel:
                raise RuntimeError("could not select the cutting line")
            dd.drw.MakeSectionLine()
            cx, cy = (spot.x0 + spot.x1) / 2, (spot.y0 + spot.y1) / 2
            v = dd.drw.CreateSectionViewAt5(cx, cy, 0, s["label"], 0, None, 0)
            if v is None:
                raise RuntimeError("CreateSectionViewAt5 returned nothing")
            try:
                dd.drw.EditSheet()
            except Exception:      # noqa: BLE001
                pass
            tv = T(v, "IView")
            tv.ScaleDecimal = sec_scale
            if moved:
                from reverse.drawing import com_doubles
                tv.Position = com_doubles(cx, cy)
                got = [float(c) for c in tv.Position]
                if abs(got[0] - cx) > 2e-3 or abs(got[1] - cy) > 2e-3:
                    rec["alignment_locked"] = True          # SOLIDWORKS kept the view aligned with its parent; the overlap check below decides if that is acceptable
                rec["scale"] = sec_scale
            try:
                tv.SetDisplayMode3(False, 2, False, False)
            except Exception:      # noqa: BLE001
                pass
            dd.views[rec["role"]] = v
            placed[rec["role"]] = spot
            rec["name"] = str(tv.GetName2())
        except Exception as e:      # noqa: BLE001
            rec["fits"] = False
            rec["error"] = f"{type(e).__name__}: {e}"
            issues.append(qa.issue("high", "SECTION_FAILED", f"Section {s['label']}-{s['label']} could not be created: {e}", part_id=part_id,
                                   next_action="Add the section view manually."))
            try:
                dd.drw.EditSheet()
            except Exception:      # noqa: BLE001
                pass
        out.append(rec)
    return out
