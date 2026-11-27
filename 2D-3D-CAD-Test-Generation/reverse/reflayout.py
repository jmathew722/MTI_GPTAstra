"""Plan the drawing from a reference extraction (v7, spec 02 "Native reconstruction"): sheet format, scale and view placement, in the SAME sheet
coordinates the planner uses (metres, lower-left origin).

Pure geometry, no SOLIDWORKS. The reference page is a scan or a PDF export whose point size is NOT authoritative for the original sheet, so:

* the sheet format is the supported standard sheet whose aspect ratio is nearest to the reference page (deviation recorded when it is not close);
* normalized top-left page coordinates map to sheet metres with  x = nx * W,  y = (1 - ny) * H  (the source-to-sheet transform, stored in the plan);
* a view keeps the planner's size (the model's true size at the chosen scale); only its CENTRE is taken from the reference. Orthographic projections
  stay aligned to their base view (SOLIDWORKS enforces that), so the base takes the reference centre and projected views take the reference's other axis;
* a placement that would overlap another view, the title block / notes, or leave the usable area is NOT copied: the planner's position is kept and the
  deviation explained ("intentional source overlaps trigger safe deviation, not copied defects").
"""
from __future__ import annotations

import math
import re
from typing import Optional

from reverse import planner
from reverse.planner import Rect

ASPECT_TOLERANCE = 0.06            # relative aspect difference accepted as "the same sheet format"


def parse_scale(text: str) -> Optional[tuple[int, int]]:
    """'1:1' -> (1, 1); '2:1' -> (2, 1); '1:2' -> (1, 2); anything else -> None (never guessed)."""
    t = (text or "").upper()
    for word, sc in (("HALF", (1, 2)), ("FULL", (1, 1)), ("TWICE", (2, 1)), ("DOUBLE", (2, 1))):         # a printed scale word is a scale statement (never inferred from geometry)
        if re.search(r"\b" + word + r"\b", t) and not re.search(r"\d\s*[:/]\s*\d", t):
            return sc
    m = re.search(r"(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)", text or "")
    if not m:       # imperial notation: 1"=2" / 1 IN = 2 IN / 1"= 2": drawing length = model length (printed 1 inch stands for 2 inches -> 1:2)
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:\"|''|”|IN(?:CH(?:ES)?)?\.?|MM)?\s*=\s*(\d+(?:\.\d+)?)\s*(?:\"|''|”|IN(?:CH(?:ES)?)?\.?|MM)?", t)
    if not m:
        return None
    a, b = float(m.group(1)), float(m.group(2))
    if a <= 0 or b <= 0 or a != int(a) or b != int(b):
        return None
    return int(a), int(b)


def pick_profile(ref: dict, job_profile: str, units_hint: str = "") -> tuple[str, list[str]]:
    """The planner profile whose sheet best matches the reference page (same projection and units as the reference states, else the job's)."""
    dev: list[str] = []
    prof0 = planner.PROFILES[job_profile]
    sheet = ref.get("sheet", {})
    w, h = float(sheet.get("width_pt") or 0), float(sheet.get("height_pt") or 0)
    proj = (sheet.get("projection") or "").lower()
    units = (sheet.get("units") or units_hint or "").lower()
    want_proj = "first" if "first" in proj else "third" if "third" in proj else prof0["projection"]
    want_units = "mm" if units.startswith("m") else "inch" if units.startswith("in") else prof0["units"]
    if "third" not in proj and "first" not in proj:
        dev.append("The reference does not state its projection; the job profile's projection was kept.")
    if not units:
        dev.append("The reference does not state its units; the job profile's units were kept.")
    if not (w and h):
        return job_profile, dev + ["The reference page size is unknown; the job profile's sheet was kept."]
    aspect = max(w, h) / min(w, h)
    best, best_d = job_profile, 9e9
    for name, p in planner.PROFILES.items():
        if p["projection"] != want_proj or p["units"] != want_units:
            continue
        s = planner.SHEETS[p["sheet"]]
        d = abs(max(s["w"], s["h"]) / min(s["w"], s["h"]) - aspect) / aspect
        if d < best_d:
            best, best_d = name, d
    if best_d > 8e9:        # no profile with that projection+units: keep the job's and say so
        dev.append(f"No sheet profile exists for {want_proj}-angle / {want_units}; the job profile ({job_profile}) was kept.")
        return job_profile, dev
    if best != job_profile:
        dev.append(f"Sheet format {planner.PROFILES[best]['sheet']} was chosen from the reference page proportions (aspect {aspect:.3f}); the requested profile used {prof0['sheet']}.")
    if best_d > ASPECT_TOLERANCE:
        dev.append(f"The reference page proportions differ by {best_d * 100:.1f} % from the nearest supported sheet; the original sheet format is not reproduced exactly.")
    return best, dev


def to_sheet_m(norm_xy: tuple[float, float], W: float, H: float) -> tuple[float, float]:
    return norm_xy[0] * W, (1.0 - norm_xy[1]) * H


def from_sheet_m(xy: tuple[float, float], W: float, H: float) -> tuple[float, float]:
    return xy[0] / W, 1.0 - xy[1] / H


def _type_of(sw_view: str) -> str:
    return (sw_view or "").strip("*")


def apply_reference(plan: dict, ref: dict, ext: dict, frame=None, replicate: bool = False) -> dict:
    ext = dict(ext)
    """Mutate ``plan`` in place: view rects moved to the reference centres where safe. Returns the ``reference_layout`` record (also stored in the plan)."""
    W = plan["regions_m"]["sheet"][2]
    H = plan["regions_m"]["sheet"][3]
    rec = {"applied": False, "transform": {"x": "nx * W", "y": "(1 - ny) * H", "W_m": W, "H_m": H, "origin": "sheet lower-left (SOLIDWORKS)"}, "views": {}, "deviations": [],
           "reference_scale": ref.get("sheet", {}).get("scale_text", "")}
    refviews = ref.get("views", [])
    if not refviews or not plan.get("rects_m"):
        rec["deviations"].append("The reference has no usable view positions; the standard layout was used.")
        plan["reference_layout"] = rec
        return rec
    rects = {k: Rect(*v) for k, v in plan["rects_m"].items()}
    regions = {k: Rect(*v) for k, v in plan["regions_m"].items()}
    gap = planner.GAP_MIN
    keep = [regions["title_block"].grow(gap * 0.3), regions["notes"].grow(gap * 0.3)]
    usable = regions["usable"]
    # which reference view corresponds to which role. The reference may call the big face "Top" while this model's own Front is that face, so the type name is only a
    # tie-breaker: orthographic views are matched by the shape of what they show (width / height of the part's silhouette), isometric by type.
    wanted: dict[str, dict] = {}
    ortho_types = ("Front", "Top", "Right", "Left", "Back", "Bottom", "Auxiliary", "Other") + (("Section",) if replicate else ())
    pw, ph = float(ref.get("sheet", {}).get("width_pt") or 1), float(ref.get("sheet", {}).get("height_pt") or 1)
    ortho_refs = [v for v in refviews if v["type"] in ortho_types and v.get("bbox_norm")]
    roles = [r_ for r_ in ("front", "top", "right") if r_ in rects and plan["views"].get(r_)]

    def role_aspect(role: str) -> float:
        hd, vd = planner._view_dims(plan["views"][role], ext)
        return hd / vd

    def ref_aspect(v: dict) -> float:
        bb = v["bbox_norm"]
        return max(1e-6, (bb[2] - bb[0]) * pw) / max(1e-6, (bb[3] - bb[1]) * ph)

    import itertools as _it
    options = [None] + [v["id"] for v in ortho_refs]
    byid = {v["id"]: v for v in ortho_refs}
    best_cost, best_assign, runner = 9e9, None, 9e9
    for perm in _it.product(options, repeat=len(roles)):
        ids = [x for x in perm if x]
        if len(ids) != len(set(ids)):
            continue
        cost = 0.0
        for role, vid in zip(roles, perm):
            if vid is None:
                cost += 0.5
                continue
            c = abs(math.log(role_aspect(role) / ref_aspect(byid[vid])))
            c += 0.0 if byid[vid]["type"] == _type_of(plan["views"][role]) else 0.12
            if c > 0.35:
                c += 5.0                          # an obviously different shape is never accepted
            cost += c
            if replicate and role in ("top", "right") and "front" in roles:
                # two roles can have the SAME silhouette (a thin ring seen from two sides): projection geometry decides. In third angle the view to the RIGHT of
                # the front (same band) is the right view and the one ABOVE it is the top; first angle mirrors both. Position, never the label, resolves it.
                fid = perm[roles.index("front")]
                if fid:
                    fc, vc = byid[fid]["center_norm"], byid[vid]["center_norm"]
                    dx, dy = vc[0] - fc[0], vc[1] - fc[1]
                    third = plan.get("projection", "third") == "third"
                    ok = (abs(dy) <= abs(dx) and (dx > 0) == third) if role == "right" else (abs(dx) < abs(dy) and (dy < 0) == third)
                    cost += 0.0 if ok else 2.0
        if cost < best_cost - 1e-9:
            best_cost, best_assign, runner = cost, perm, best_cost
        elif cost < runner:
            runner = cost
    if best_assign is not None:
        ambiguous = (runner - best_cost) < 0.03 and len(roles) > 1 and len({role_aspect(r_) for r_ in roles}) < len(roles) and not replicate
        for role, vid in zip(roles, best_assign):
            if vid is None or ambiguous:
                rec["views"][role] = {"status": "no_reference_view" if not ambiguous else "ambiguous_shape",
                                      "note": ("no reference view has this view's silhouette; the planner's position is kept" if not ambiguous else
                                               "two views of this model have the same silhouette; their reference positions cannot be told apart, so the planner's positions are kept")}
                continue
            wanted[role] = byid[vid]
            rec["views"].setdefault(role, {})["matched_by"] = "silhouette proportions" + (" and type" if byid[vid]["type"] == _type_of(plan["views"][role]) else "")
    iso_cands = [v for v in refviews if v["type"] == "Isometric" and v.get("bbox_norm")]
    if replicate:
        # replication: only the views the source shows are created (no added isometric, no projected view without a source counterpart)
        for role in ("top", "right"):
            if role in rects and role not in wanted:
                rec["views"][role] = {"status": "omitted_not_in_source", "note": f"the source drawing shows no view matching this model's {plan['views'].get(role)} silhouette; not created in replication mode"}
                rects.pop(role)
        if "iso" in rects and not iso_cands:
            rects.pop("iso")
            rec["views"]["iso"] = {"status": "omitted_not_in_source", "note": "the source drawing has no isometric view; none is added in replication mode"}
        plan["rects_m"] = {k: v.as_list() for k, v in rects.items()}
    if "iso" in rects and iso_cands:
        wanted["iso"] = max(iso_cands, key=lambda v: (v.get("confidence") or 0))
    elif "iso" in rects and not replicate:
        rec["views"]["iso"] = {"status": "no_reference_view", "type": "Isometric", "note": "The reference has no isometric view (this pipeline always adds one, Shaded With Edges); placed by the planner."}
    new = dict(rects)
    moved: dict[str, list] = {}

    def centre(r: Rect) -> tuple[float, float]:
        return ((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)

    def target(role: str) -> Optional[tuple[float, float]]:
        v = wanted.get(role)
        if not v:
            return None
        cx, cy = frame.norm_to_sheet(*v["center_norm"]) if frame is not None else to_sheet_m(tuple(v["center_norm"]), W, H)
        rec["views"].setdefault(role, {}).update({"reference_view": v["id"], "type": v["type"], "reference_center_m": [round(cx, 6), round(cy, 6)]})
        rec["views"][role].pop("note", None)
        return cx, cy

    def fits(cand: Rect, others: list[Rect]) -> str:
        if not cand.inside(usable):
            return "is outside the usable sheet area"
        if any(cand.grow(gap * 0.4).overlaps(k) for k in keep):
            return "falls in the title block / notes zone"
        if any(cand.grow(gap * 0.4).overlaps(o) for o in others):
            return "would overlap another view"
        return ""

    # --- the orthographic trio is placed as ONE group: the projected views must stay aligned to the front, so either every reference-driven position is
    #     valid together or the planner's whole arrangement is kept
    if "front" in rects:
        tf = target("front")
        if tf is not None:
            fr = rects["front"]
            fcx, fcy = tf
            trial = {"front": Rect(fcx - fr.w / 2, fcy - fr.h / 2, fcx + fr.w / 2, fcy + fr.h / 2)}
            for role in ("top", "right"):
                if role not in rects:
                    continue
                r0 = rects[role]
                tgt = target(role)
                if role == "top":
                    ty = tgt[1] if tgt else (fcy + (centre(r0)[1] - centre(rects["front"])[1]))        # no reference top: keep its planner offset from the front
                    trial[role] = Rect(fcx - r0.w / 2, ty - r0.h / 2, fcx + r0.w / 2, ty + r0.h / 2)
                else:
                    tx = tgt[0] if tgt else (fcx + (centre(r0)[0] - centre(rects["front"])[0]))
                    trial[role] = Rect(tx - r0.w / 2, fcy - r0.h / 2, tx + r0.w / 2, fcy + r0.h / 2)
            why = ""
            names = list(trial)
            for nme in names:
                others = [o for k, o in trial.items() if k != nme] + [o for k, o in rects.items() if k not in trial and k != "iso"]
                why = fits(trial[nme], others)
                if why:
                    why = f"{nme} view {why}"
                    break
            if not why and "front" in trial and "top" in trial and trial["top"].overlaps(trial["front"]):
                why = "top view would overlap the front view"
            if not why and "front" in trial and "right" in trial and trial["right"].overlaps(trial["front"]):
                why = "right view would overlap the front view"
            if not why:
                for nme, r in trial.items():
                    new[nme] = r
                    moved[nme] = [round(centre(r)[0], 6), round(centre(r)[1], 6)]
                    rec["views"].setdefault(nme, {})["target_center_m"] = moved[nme]
                    rec["views"][nme]["status"] = "placed_from_reference"
            else:
                for nme in ("front", "top", "right"):
                    if nme in rects:
                        rec["views"].setdefault(nme, {})["status"] = "kept_planner_position"
                        rec["views"][nme]["deviation"] = f"The reference arrangement was not copied: {why} at the model's true size; the planner's arrangement was kept."
                rec["deviations"].append(f"orthographic views: the reference arrangement was not copied ({why}); the planner's arrangement was kept.")
    # --- the isometric is free
    if "iso" in rects:
        tiso = target("iso")
        if tiso is not None:
            r = rects["iso"]
            cand = Rect(tiso[0] - r.w / 2, tiso[1] - r.h / 2, tiso[0] + r.w / 2, tiso[1] + r.h / 2)
            why = fits(cand, [o for k, o in new.items() if k != "iso"])
            if not why:
                new["iso"] = cand
                moved["iso"] = [round(tiso[0], 6), round(tiso[1], 6)]
                rec["views"]["iso"]["target_center_m"] = moved["iso"]
                rec["views"]["iso"]["status"] = "placed_from_reference"
            else:
                rec["views"]["iso"]["status"] = "kept_planner_position"
                rec["views"]["iso"]["deviation"] = f"The reference isometric position {why}; the planner's position was kept."
                rec["deviations"].append(f"isometric view: {rec['views']['iso']['deviation']}")
    plan["rects_m"] = {k: r.as_list() for k, r in new.items()}
    rec["applied"] = bool(moved)
    rec["moved"] = moved
    plan["reference_layout"] = rec
    return rec


def reference_scale(ref: dict) -> Optional[tuple[int, int]]:
    s = parse_scale(ref.get("sheet", {}).get("scale_text", ""))
    if s is None:
        for v in ref.get("views", []):
            s = parse_scale(v.get("scale_text", ""))
            if s:
                break
    return s
