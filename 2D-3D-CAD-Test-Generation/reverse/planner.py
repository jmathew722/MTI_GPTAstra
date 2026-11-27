"""View and sheet planning (pure geometry, no SOLIDWORKS): front-view choice, standard scale, third/first-angle placement, extra sheets.

All sheet coordinates are metres with the origin at the sheet's lower-left corner (SOLIDWORKS drawing convention).  ``plan_views`` returns a
JSON-serialisable plan that is written to ``drawing_plan.json`` BEFORE any drawing mutation.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, asdict
from typing import Optional

IN = 0.0254
# ANSI B landscape 17 x 11 in; margins: 0.5 in left, 0.25 in others (design choices to check against company standard)
SHEETS = {
    "ANSI_B": {"w": 17 * IN, "h": 11 * IN, "ml": 0.5 * IN, "mr": 0.25 * IN, "mb": 0.25 * IN, "mt": 0.25 * IN, "tb_w": 6.5 * IN, "tb_h": 1.6 * IN,
               "notes_w": 4.0 * IN, "paper": "ANSI B (17x11 in)"},
    "ANSI_C": {"w": 22 * IN, "h": 17 * IN, "ml": 0.5 * IN, "mr": 0.25 * IN, "mb": 0.25 * IN, "mt": 0.25 * IN, "tb_w": 6.5 * IN, "tb_h": 1.6 * IN,
               "notes_w": 4.0 * IN, "paper": "ANSI C (22x17 in)"},
    "A3": {"w": 0.420, "h": 0.297, "ml": 0.020, "mr": 0.010, "mb": 0.010, "mt": 0.010, "tb_w": 0.180, "tb_h": 0.045, "notes_w": 0.100, "paper": "A3 (420x297 mm)"},
}
SCALES_INCH = [(10, 1), (5, 1), (4, 1), (2, 1), (1, 1), (1, 2), (1, 4), (1, 8), (1, 16)]
SCALES_METRIC = [(10, 1), (5, 1), (2, 1), (1, 1), (1, 2), (1, 5), (1, 10), (1, 20), (1, 50)]
PROFILES = {
    "us_third_angle_inch": {"projection": "third", "sheet": "ANSI_B", "scales": SCALES_INCH, "units": "inch"},
    "us_third_angle_inch_c": {"projection": "third", "sheet": "ANSI_C", "scales": SCALES_INCH, "units": "inch"},
    "metric_a3_third_angle": {"projection": "third", "sheet": "A3", "scales": SCALES_METRIC, "units": "mm"},
    "iso_first_angle_a3": {"projection": "first", "sheet": "A3", "scales": SCALES_METRIC, "units": "mm"},
}
GAP_MIN = 0.045            # clear room around a view for dimensions and labels (45 mm on the sheet)
# SOLIDWORKS standard view that looks along each principal direction, with the model axes shown (horizontal, vertical)
VIEWS = {"*Front": ("x", "y", "z"), "*Back": ("x", "y", "z"), "*Top": ("x", "z", "y"), "*Bottom": ("x", "z", "y"),
         "*Right": ("z", "y", "x"), "*Left": ("z", "y", "x")}


@dataclass
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def w(self) -> float:
        return self.x1 - self.x0

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    def grow(self, d: float) -> "Rect":
        return Rect(self.x0 - d, self.y0 - d, self.x1 + d, self.y1 + d)

    def overlaps(self, o: "Rect", eps: float = 1e-9) -> bool:
        return self.x0 < o.x1 - eps and o.x0 < self.x1 - eps and self.y0 < o.y1 - eps and o.y0 < self.y1 - eps

    def inside(self, o: "Rect", eps: float = 1e-9) -> bool:
        return self.x0 >= o.x0 - eps and self.y0 >= o.y0 - eps and self.x1 <= o.x1 + eps and self.y1 <= o.y1 + eps

    def as_list(self) -> list[float]:
        return [round(v, 6) for v in (self.x0, self.y0, self.x1, self.y1)]


def sheet_regions(name: str) -> dict:
    s = SHEETS[name]
    full = Rect(0, 0, s["w"], s["h"])
    usable = Rect(s["ml"], s["mb"], s["w"] - s["mr"], s["h"] - s["mt"])
    title = Rect(usable.x1 - s["tb_w"], usable.y0, usable.x1, usable.y0 + s["tb_h"])
    notes = Rect(title.x0 - s["notes_w"], usable.y0, title.x0, usable.y0 + s["tb_h"])
    return {"sheet": full, "usable": usable, "title_block": title, "notes": notes}


def extents(bbox_m: tuple[float, float, float]) -> dict:
    return {"x": bbox_m[0], "y": bbox_m[1], "z": bbox_m[2]}


def score_front(view: str, ext: dict, hole_axes: dict) -> float:
    """Higher = shows more of the part. ``hole_axes`` = {"x": n, "y": n, "z": n} counts of holes/bores whose axis is along that model axis (such
    holes read as true circles when we look along the axis, so the view that looks along the busiest axis shows them best)."""
    h, v, n = VIEWS[view]
    area = ext[h] * ext[v]
    circles = hole_axes.get(n, 0)
    bonus = 1.0 if view == "*Front" else 0.0           # prefer the model's own front on a tie
    return area * 1.0 + circles * 1e-3 + bonus * 1e-9


def choose_front(ext: dict, hole_axes: dict, override: Optional[str] = None) -> str:
    if override in VIEWS:
        return override
    best = max(("*Front", "*Top", "*Right"), key=lambda v: (round(score_front(v, ext, hole_axes), 12)))
    return best


VIEW_PAD = 0.0065        # SOLIDWORKS' real view outline includes centre-mark / centreline overshoot (measured ~5.6 mm each side): plan with it


def _view_dims(view: str, ext: dict) -> tuple[float, float]:
    """Raw part extents (metres, model scale) of the view. Callers scale these and then add ``2 * VIEW_PAD`` on the sheet."""
    h, v, _ = VIEWS[view]
    return ext[h], ext[v]


def find_spot(w: float, h: float, placed: list, keep_out: list, usable: Rect, gap: float, step: float = 0.005) -> Optional[Rect]:
    """First collision-free w x h rectangle in the usable area (scanning top-right first, where an isometric reads best), else None."""
    y = usable.y1 - gap * 0.5 - h
    while y >= usable.y0 + gap * 0.3:
        x = usable.x1 - gap * 0.5 - w
        while x >= usable.x0 + gap * 0.3:
            r = Rect(x, y, x + w, y + h)
            if r.inside(usable) and not any(r.grow(gap * 0.4).overlaps(o) for o in list(placed) + list(keep_out)):
                return r
            x -= step
        y -= step
    return None


def _ortho_rects(front: str, ext: dict, s: float, projection: str, x0: float, y0: float, gap: float) -> dict:
    top_view, right_view = _projected_names(front)
    fw, fh = (d * s + 2 * VIEW_PAD for d in _view_dims(front, ext))
    tw, th = (d * s + 2 * VIEW_PAD for d in _view_dims(top_view, ext))
    rw, rh = (d * s + 2 * VIEW_PAD for d in _view_dims(right_view, ext))
    if projection == "third":   # top ABOVE the front, right to the RIGHT of the front
        front_r = Rect(x0, y0, x0 + fw, y0 + fh)
        top_r = Rect(front_r.x0, front_r.y1 + gap, front_r.x0 + tw, front_r.y1 + gap + th)
        right_r = Rect(front_r.x1 + gap, front_r.y0, front_r.x1 + gap + rw, front_r.y0 + rh)
    else:                       # first angle: top BELOW the front, right to the LEFT (the views swap sides)
        right_r = Rect(x0, y0 + th + gap, x0 + rw, y0 + th + gap + rh)
        front_r = Rect(right_r.x1 + gap, right_r.y0, right_r.x1 + gap + fw, right_r.y0 + fh)
        top_r = Rect(front_r.x0, y0, front_r.x0 + tw, y0 + th)
    return {"front": front_r, "top": top_r, "right": right_r}


def _ok(rects: dict, usable: Rect, keep_out: list, gap: float) -> bool:
    for r in rects.values():
        if not r.inside(usable) or any(r.grow(gap * 0.4).overlaps(k) for k in keep_out):
            return False
    names = list(rects)
    for a, b in itertools.combinations(names, 2):
        if rects[a].grow(gap * 0.4).overlaps(rects[b]) and not ({a, b} <= {"front", "top", "right"} and _adjacent_ok(rects, a, b, gap)):
            return False
    return True


def _adjacent_ok(rects: dict, a: str, b: str, gap: float) -> bool:
    """Projected neighbours are meant to sit a gap apart; they only fail if their rectangles actually overlap."""
    return not rects[a].overlaps(rects[b])


def layout_at_scale(front: str, ext: dict, s: float, projection: str, regions: dict, gap: float = GAP_MIN) -> Optional[dict]:
    """Rects (sheet metres) for front + projected top + projected right at scale s, plus the isometric block when it fits (``iso`` is None when
    it does not: the plan then puts it on a second sheet instead of shrinking the drawing). None when the orthographic views cannot fit."""
    usable, title, notes = regions["usable"], regions["title_block"], regions["notes"]
    keep_out = [title.grow(gap * 0.3), notes.grow(gap * 0.3)]
    top_view, right_view = _projected_names(front)
    pad = gap * 0.8
    xs = [usable.x0 + pad, usable.x0 + gap]
    ys = [usable.y0 + pad, title.y1 + gap * 0.5, title.y1 + gap, usable.y0 + gap]
    ortho = None
    for x0, y0 in itertools.product(xs, ys):
        r = _ortho_rects(front, ext, s, projection, x0, y0, gap)
        if _ok(r, usable, keep_out, gap):
            ortho = r
            break
    if ortho is None:
        return None
    iso_scale, iso = s, None
    for factor in (1.0, 0.5, 0.25):
        side = max(ext.values()) * s * factor * 1.35 + 2 * VIEW_PAD
        iso = find_spot(side, side * 0.85, list(ortho.values()), keep_out, usable, gap)
        if iso is not None:
            iso_scale = s * factor
            break
    rects = dict(ortho)
    if iso is not None:
        rects["iso"] = iso
    return {"rects": rects, "views": {"front": front, "top": top_view, "right": right_view, "iso": "*Isometric" if iso is not None else None},
            "iso_on_sheet": 1 if iso is not None else 2, "iso_scale": iso_scale}


def _projected_names(front: str) -> tuple[str, str]:
    """For a given base view, the SOLIDWORKS standard views that sit above it and beside it in third-angle projection."""
    return {"*Front": ("*Top", "*Right"), "*Top": ("*Back", "*Right"), "*Right": ("*Top", "*Back")}[front]


def plan_views(bbox_m: tuple[float, float, float], profile: str = "us_third_angle_inch", hole_axes: Optional[dict] = None,
               front_override: Optional[str] = None, needs_section: bool = False, scale_override: Optional[tuple[int, int]] = None, force_scale: bool = False) -> dict:
    """The complete view/sheet plan. Never silently crowds: if nothing fits at an acceptable scale, the isometric (and any section/detail) moves
    to an additional sheet; if even the orthographic block does not fit at the smallest scale, the plan says so and the job needs review."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}")
    prof = PROFILES[profile]
    if not (len(bbox_m) == 3 and all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in bbox_m)):
        raise ValueError("the part has no usable bounding box")
    ext = extents(bbox_m)
    front = choose_front(ext, hole_axes or {}, front_override)
    regions = sheet_regions(prof["sheet"])
    scales = [scale_override] if scale_override else prof["scales"]
    chosen = None
    for num, den in scales:                       # largest scale first
        lay = layout_at_scale(front, ext, num / den, prof["projection"], regions)
        if lay is not None:
            chosen = ((num, den), lay)
            break
    notes: list[str] = []
    sheets = [{"index": 1, "name": "Sheet1", "contents": ["front", "top", "right", "iso"]}]
    scale_fit = chosen is not None
    if chosen is None:
        notes.append("No standard scale fits the orthographic views on one sheet; needs a larger sheet or a manual layout.")
        num, den = scales[-1]
        lay = {"rects": {}, "views": {}}
        if force_scale and scale_override:
            # replication mode: the SOURCE scale is authoritative. Build the arrangement at that scale even though this profile's sheet cannot hold it;
            # the source positions are applied afterwards and any overlap is reported there, never hidden by rescaling.
            top_view, right_view = _projected_names(front)
            r0 = _ortho_rects(front, ext, num / den, prof["projection"], regions["usable"].x0 + GAP_MIN * 0.8, regions["usable"].y0 + GAP_MIN * 0.8, GAP_MIN)
            lay = {"rects": r0, "views": {"front": front, "top": top_view, "right": right_view, "iso": None}, "iso_on_sheet": 2, "iso_scale": num / den}
        chosen = ((num, den), lay)
    (num, den), lay = chosen
    if lay.get("iso_on_sheet") == 2 and not (force_scale and not scale_fit):
        sheets = [{"index": 1, "name": "Sheet1", "contents": ["front", "top", "right"]}, {"index": 2, "name": "Sheet2", "contents": ["iso"]}]
        notes.append("The isometric view does not fit beside the orthographic views at this scale; it is placed on a second sheet instead of crowding sheet 1.")
    iso_scale = lay.get("iso_scale", num / den)
    if lay.get("iso_on_sheet") == 1 and abs(iso_scale - num / den) > 1e-9:
        notes.append(f"The isometric view is shown at a smaller scale ({iso_scale:g}) than the orthographic views; it is labelled on the sheet.")
    rects = {k: v.as_list() for k, v in lay["rects"].items()}
    return {"profile": profile, "projection": prof["projection"], "units": prof["units"], "sheet_size": prof["sheet"], "paper": SHEETS[prof["sheet"]]["paper"],
            "front_view": front, "views": lay["views"], "scale": {"num": num, "den": den, "label": f"{num}:{den}"}, "scale_fits": scale_fit,
            "rects_m": rects, "iso_scale": iso_scale, "regions_m": {k: v.as_list() for k, v in regions.items()}, "sheets": sheets, "needs_section": needs_section,
            "bbox_m": list(bbox_m), "hole_axes": hole_axes or {}, "notes": notes,
            "basis": "front chosen for the largest silhouette (ties: the model's own Front); scale = largest standard scale that fits without collisions"}
