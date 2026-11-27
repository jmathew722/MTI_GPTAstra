"""Measured layout QA for native drawings (v7, spec 03): PDF text extents + native outlines in ONE sheet coordinate system, collision / clipping
detection, a bounded correction loop that never deletes a required annotation.

Coordinates: sheet metres, origin lower-left (SOLIDWORKS convention). PDF points (top-left origin) are converted with
``x_m = x_pt * 0.0254 / 72`` and ``y_m = (page_h_pt - y_pt) * 0.0254 / 72``; the export is made at 100 % so the page size equals the sheet size
(``check_scale`` verifies that against the native sheet size and reports a failure otherwise: no silent assumption).

Collision classes (each reported with the PDF text, boxes in sheet mm, and a severity):
  text_text      two text boxes closer than the clearance (default 1.5 mm; configurable 1-2 mm)
  text_stroke    a vector stroke runs through a text box (dimension lines are broken around text by SOLIDWORKS, so a stroke crossing the interior is a
                 real collision; leader tips and extension lines that only TOUCH the box edge are the documented intentional exemption)
  text_view      a text box inside another view's outline envelope while belonging to a different view's dimension lane is NOT flagged by itself;
                 text over a *different view's geometry* is caught by text_stroke. Text overlapping a view outline's padded rectangle is reported only
                 when it also crosses a stroke.
  view_view      two native view outlines overlap
  text_title     text inside the title-block / notes keep-out
  clipped        text outside the page or outside the usable area
Exempt by design: strokes whose bounding box lies entirely within ``touch_mm`` of the text box edge (leader tip / extension line touching),
and text inside its own view's isometric shading (shading is a fill, not a stroke).
"""
from __future__ import annotations

import itertools
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

IN = 0.0254
PT_M = IN / 72.0
DEFAULT_CLEARANCE_MM = 1.5
TOUCH_MM = 0.35
ENVELOPE_ALLOWANCE_M = 0.0056


@dataclass
class TBox:
    id: str
    text: str
    x0: float          # sheet metres
    y0: float
    x1: float
    y1: float
    sheet: int = 1
    color: Optional[int] = None
    horizontal: bool = True
    size_pt: float = 0.0

    def grow(self, d: float) -> "TBox":
        return TBox(self.id, self.text, self.x0 - d, self.y0 - d, self.x1 + d, self.y1 + d, self.sheet, self.color, self.horizontal, self.size_pt)

    def overlaps(self, o: "TBox") -> bool:
        return self.x0 < o.x1 and o.x0 < self.x1 and self.y0 < o.y1 and o.y0 < self.y1

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)

    def as_mm(self) -> list[float]:
        return [round(v * 1000, 2) for v in (self.x0, self.y0, self.x1, self.y1)]


def pt_to_m(x_pt: float, y_pt: float, page_h_pt: float) -> tuple[float, float]:
    return x_pt * PT_M, (page_h_pt - y_pt) * PT_M


@dataclass
class PageMeasure:
    page: int
    width_m: float
    height_m: float
    texts: list = field(default_factory=list)          # [TBox]
    strokes: list = field(default_factory=list)        # [(x0,y0,x1,y1) segment, sheet metres]
    shaded_fills: int = 0
    watermark: bool = False                            # the Student Edition licence stamp ("SOLIDWORKS Educational Product..."), outside our control
    nonblack_text: list = field(default_factory=list)
    nonblack_strokes: int = 0


def measure_pdf(pdf: Path) -> list[PageMeasure]:
    """Text boxes (per text line), stroke segments and colour facts of every page, in sheet coordinates."""
    import fitz
    out: list[PageMeasure] = []
    doc = fitz.open(str(pdf))
    try:
        for pno, page in enumerate(doc, start=1):
            H = page.rect.height
            pm = PageMeasure(pno, page.rect.width * PT_M, H * PT_M)
            for bi, blk in enumerate(page.get_text("dict")["blocks"]):
                for li, line in enumerate(blk.get("lines", [])):
                    spans = [s for s in line.get("spans", []) if s["text"].strip()]
                    if not spans:
                        continue
                    txt = "".join(s["text"] for s in line["spans"]).strip()
                    if txt.upper().startswith("SOLIDWORKS EDUCATIONAL PRODUCT"):
                        pm.watermark = True            # licence watermark added by SOLIDWORKS to every export; not part of the drawing
                        continue
                    x0, y0, x1, y1 = line["bbox"]
                    d = line.get("dir", (1.0, 0.0))
                    horiz = abs(d[1]) < 0.02
                    # the font box (ascent + descent + gap) is taller than the glyphs: use the glyph band (cap height above the baseline; a descender
                    # allowance only when the text has descending letters) so a line that merely passes near the text is not a false collision
                    sz = float(spans[0].get("size", 0) or 0)
                    org = spans[0].get("origin")
                    desc = 0.22 * sz if any(c in txt for c in "gjpqy,;()Q") else 0.0
                    if sz > 0 and org is not None:
                        if horiz:
                            y0, y1 = org[1] - 0.74 * sz, org[1] + desc
                        elif abs(d[0]) < 0.02:           # vertical text (reads bottom-to-top or top-to-bottom): the band is along x
                            if d[1] < 0:                  # bottom-to-top: baseline on the right
                                x0, x1 = org[0] - 0.74 * sz, org[0] + desc
                            else:
                                x0, x1 = org[0] - desc, org[0] + 0.74 * sz
                    ax0, ay0 = pt_to_m(x0, y1, H)
                    ax1, ay1 = pt_to_m(x1, y0, H)
                    col = spans[0]["color"]
                    if col not in (0, None):
                        r, g, b = (col >> 16) & 255, (col >> 8) & 255, col & 255
                        if max(r, g, b) > 5:
                            pm.nonblack_text.append({"page": pno, "text": txt[:40], "color": col})
                    pm.texts.append(TBox(f"p{pno}t{bi}_{li}", txt, ax0, ay0, ax1, ay1, pno, col, horiz, float(spans[0].get("size", 0))))
            try:
                for d in page.get_drawings():
                    t = d.get("type", "")
                    stroke_col, fill_col = d.get("color"), d.get("fill")
                    if "s" in t and stroke_col is not None and max(stroke_col[:3]) > 0.02:
                        pm.nonblack_strokes += 1
                    if "f" in t and fill_col is not None and tuple(round(c, 2) for c in fill_col[:3]) not in ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)):
                        pm.shaded_fills += 1
                    if "s" not in t:
                        continue
                    for it in d["items"]:
                        k = it[0]
                        if k == "l":
                            p, q = it[1], it[2]
                            pm.strokes.append((*pt_to_m(p.x, p.y, H), *pt_to_m(q.x, q.y, H)))
                        elif k == "re":
                            r = it[1]
                            pts = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1), (r.x0, r.y0)]
                            for a, b in zip(pts, pts[1:]):
                                pm.strokes.append((*pt_to_m(a[0], a[1], H), *pt_to_m(b[0], b[1], H)))
                        elif k == "c":
                            p0, p1, p2, p3 = it[1], it[2], it[3], it[4]
                            prev = (p0.x, p0.y)
                            for i in range(1, 7):
                                t_ = i / 6
                                x = (1 - t_) ** 3 * p0.x + 3 * (1 - t_) ** 2 * t_ * p1.x + 3 * (1 - t_) * t_ ** 2 * p2.x + t_ ** 3 * p3.x
                                y = (1 - t_) ** 3 * p0.y + 3 * (1 - t_) ** 2 * t_ * p1.y + 3 * (1 - t_) * t_ ** 2 * p2.y + t_ ** 3 * p3.y
                                pm.strokes.append((*pt_to_m(*prev, H), *pt_to_m(x, y, H)))
                                prev = (x, y)
            except Exception as e:      # noqa: BLE001
                log.warning("PDF drawings could not be read: %s", e)
            out.append(pm)
    finally:
        doc.close()
    return out


def check_scale(pm: PageMeasure, sheet_w_m: float, sheet_h_m: float, tol: float = 0.01) -> Optional[str]:
    """None when the exported page matches the native sheet (so PDF points map to sheet metres 1:1), else a failure message."""
    if abs(pm.width_m - sheet_w_m) / sheet_w_m > tol or abs(pm.height_m - sheet_h_m) / sheet_h_m > tol:
        return (f"The exported page ({pm.width_m * 1000:.1f} x {pm.height_m * 1000:.1f} mm) does not match the native sheet "
                f"({sheet_w_m * 1000:.1f} x {sheet_h_m * 1000:.1f} mm); layout measurements from the PDF are not trusted.")
    return None


# ------------------------------------------------------------------ geometry helpers

def _seg_hits_box(seg: tuple[float, float, float, float], b: TBox, shrink: float) -> bool:
    """Does the segment pass through the INTERIOR of box ``b`` shrunk by ``shrink`` (Liang-Barsky clip)?"""
    x0, y0, x1, y1 = seg
    bx0, by0, bx1, by1 = b.x0 + shrink, b.y0 + shrink, b.x1 - shrink, b.y1 - shrink
    if bx1 <= bx0 or by1 <= by0:
        return False
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - bx0), (dx, bx1 - x0), (-dy, y0 - by0), (dy, by1 - y0)):
        if abs(p) < 1e-12:
            if q < 0:
                return False
        else:
            r = q / p
            if p < 0:
                if r > t1:
                    return False
                t0 = max(t0, r)
            else:
                if r < t0:
                    return False
                t1 = min(t1, r)
    return t0 < t1 - 1e-9 and (t1 - t0) * math.hypot(dx, dy) > 0.0004          # >0.4 mm of the stroke inside the box


@dataclass
class Collision:
    kind: str
    page: int
    a: str
    b: str = ""
    severity: str = "high"
    a_text: str = ""
    b_text: str = ""
    box_a_mm: Optional[list] = None
    box_b_mm: Optional[list] = None
    detail: str = ""

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, "")}


def detect(pages: list[PageMeasure], *, clearance_m: float = DEFAULT_CLEARANCE_MM / 1000.0, view_outlines: Optional[dict] = None,
           keepout: Optional[dict] = None, usable: Optional[tuple] = None, sheet: int = 1, ours: Optional[set] = None) -> list[Collision]:
    """All unintended overlaps / clippings on the PAGE that belongs to ``sheet`` (native outlines and keep-outs are given for that sheet)."""
    out: list[Collision] = []
    for pm in pages:
        if pm.page != sheet:
            continue
        texts = pm.texts
        for a, b in itertools.combinations(texts, 2):
            if a.id.rsplit("_", 1)[0] == b.id.rsplit("_", 1)[0] and not a.overlaps(b):
                continue          # exemption: lines of ONE multi-line annotation are spaced by SOLIDWORKS itself
            if (a.text.upper().startswith("SCALE") or b.text.upper().startswith("SCALE")) and not a.overlaps(b):
                continue          # exemption: a view title ("SECTION A-A") stacked over its "SCALE 1:2" line is one SOLIDWORKS view label; only a true overlap is flagged
            if a.grow(clearance_m / 2).overlaps(b.grow(clearance_m / 2)):
                hard = a.overlaps(b)
                out.append(Collision("text_text", pm.page, a.id, b.id, "high" if hard else "medium", a.text, b.text, a.as_mm(), b.as_mm(),
                                     "overlap" if hard else f"closer than {clearance_m * 1000:.1f} mm"))
        has_section = any(k.startswith("section") for k in (view_outlines or {}))
        for t in texts:
            if has_section and len(t.text) == 1 and t.text.isalpha() and t.text.isupper():
                continue          # exemption: a section cut-line letter sits against its arrow by definition
            shr = max(0.0003, TOUCH_MM / 1000.0)
            for sg in pm.strokes:
                # quick reject on bounding boxes
                if max(sg[0], sg[2]) < t.x0 or min(sg[0], sg[2]) > t.x1 or max(sg[1], sg[3]) < t.y0 or min(sg[1], sg[3]) > t.y1:
                    continue
                if _seg_hits_box(sg, t, shr):
                    out.append(Collision("text_stroke", pm.page, t.id, "", "high", t.text, "", t.as_mm(), None, "a drawn line runs through this text"))
                    break
        if view_outlines:
            names = list(view_outlines)
            for a, b in itertools.combinations(names, 2):
                ra, rb = view_outlines[a], view_outlines[b]
                if ra[0] < rb[2] and rb[0] < ra[2] and ra[1] < rb[3] and rb[1] < ra[3]:
                    # SOLIDWORKS' outline includes the centre-mark / centreline overshoot (~5.6 mm each side). Envelopes that overlap only inside that allowance
                    # have no overlapping linework: advisory ("envelope_touch"), not a collision. Overlap beyond it is a real overlap of drawn geometry.
                    s_ = ENVELOPE_ALLOWANCE_M
                    real = (ra[0] + s_ < rb[2] - s_ and rb[0] + s_ < ra[2] - s_ and ra[1] + s_ < rb[3] - s_ and rb[1] + s_ < ra[3] - s_)
                    out.append(Collision("view_view" if real else "envelope_touch", pm.page, a, b, "high" if real else "low", "", "", [round(v * 1000, 2) for v in ra],
                                         [round(v * 1000, 2) for v in rb], "view outlines overlap" if real else "view envelopes overlap inside the centre-mark allowance; drawn geometry does not"))
        for name, kr in (keepout or {}).items():
            for t in texts:
                if ours is not None and t.id not in ours:
                    continue          # the template's own title-block text is not ours
                if t.x0 < kr[2] and kr[0] < t.x1 and t.y0 < kr[3] and kr[1] < t.y1:
                    # text that IS part of the title block / notes template is not ours: only text outside the keep-out's own content counts when
                    # it was added by the drawing (callers pass keepouts for zones that must stay free of dimensions)
                    out.append(Collision("text_keepout", pm.page, t.id, name, "high", t.text, "", t.as_mm(), [round(v * 1000, 2) for v in kr], f"text inside the {name} zone"))
        for t in texts:
            if ours is not None and t.id not in ours:
                continue
            if t.x0 < -1e-6 or t.y0 < -1e-6 or t.x1 > pm.width_m + 1e-6 or t.y1 > pm.height_m + 1e-6:
                out.append(Collision("clipped", pm.page, t.id, "", "high", t.text, "", t.as_mm(), None, "text extends beyond the page"))
            elif usable and (t.x0 < usable[0] - 1e-6 or t.y0 < usable[1] - 1e-6 or t.x1 > usable[2] + 1e-6 or t.y1 > usable[3] + 1e-6):
                out.append(Collision("clipped", pm.page, t.id, "", "medium", t.text, "", t.as_mm(), None, "text outside the drawing border"))
    return out


def score(collisions: list[Collision]) -> float:
    w = {"high": 3.0, "medium": 1.0, "low": 0.05}
    return sum(w.get(c.severity, 1.0) for c in collisions)


def summarize(collisions: list[Collision], clearance_mm: float, extra: Optional[dict] = None) -> dict:
    by: dict[str, int] = {}
    for c in collisions:
        by[c.kind] = by.get(c.kind, 0) + 1
    hard = [c for c in collisions if c.severity != "low"]
    adv = [c for c in collisions if c.severity == "low"]
    return {"count": len(hard), "by_kind": by, "clearance_mm": clearance_mm, "items": [c.as_dict() for c in hard[:60]], "advisory": [c.as_dict() for c in adv[:20]],
            "truncated": max(0, len(hard) - 60), "exemptions": ["strokes touching a text box edge (leader tip / extension line) are not collisions",
                                                                      "shaded isometric fills are not strokes", "the template's own title block and border are part of the sheet format"],
            **(extra or {})}


# ------------------------------------------------------------------ mapping PDF text to native annotations

def map_text_to_annotations(texts: list[TBox], ann_pos: dict, max_dist_m: float = 0.03) -> dict:
    """annotation id -> TBox id: greedy nearest numeric/text line to the native annotation position (one-to-one). Honest: unmapped ids are simply absent."""
    cand = []
    for aid, (x, y) in ann_pos.items():
        for t in texts:
            if not any(ch.isdigit() for ch in t.text):
                continue
            cx, cy = t.center
            d = math.hypot(cx - x, cy - y)
            if d <= max_dist_m:
                cand.append((d, aid, t.id))
    cand.sort()
    used_a, used_t, res = set(), set(), {}
    for d, aid, tid in cand:
        if aid in used_a or tid in used_t:
            continue
        used_a.add(aid)
        used_t.add(tid)
        res[aid] = tid
    return res


def propose_offsets(box: TBox, horizontal_lane: bool, step_m: float = 0.004, steps: int = 14):
    """Candidate (dx, dy) moves for a colliding annotation, nearest first, alternating sides, along its own lane first."""
    cands = []
    for k in range(1, steps + 1):
        d = k * step_m
        if horizontal_lane:
            cands += [(0.0, d), (0.0, -d), (d, 0.0), (-d, 0.0)]
        else:
            cands += [(d, 0.0), (-d, 0.0), (0.0, d), (0.0, -d)]
    return cands


def free_at(box: TBox, dx: float, dy: float, others: list[TBox], strokes: list, view_outlines: Optional[dict], usable: Optional[tuple], keepout: Optional[dict],
            clearance_m: float, own_view: str = "") -> bool:
    """Would ``box`` moved by (dx, dy) be free of text/stroke/keep-out/outline collisions against everything that stays put?"""
    nb = TBox(box.id, box.text, box.x0 + dx, box.y0 + dy, box.x1 + dx, box.y1 + dy, box.sheet)
    for o in others:
        if o.id != box.id and nb.grow(clearance_m / 2).overlaps(o.grow(clearance_m / 2)):
            return False
    shr = max(0.0003, TOUCH_MM / 1000.0)
    for sg in strokes:
        if max(sg[0], sg[2]) < nb.x0 or min(sg[0], sg[2]) > nb.x1 or max(sg[1], sg[3]) < nb.y0 or min(sg[1], sg[3]) > nb.y1:
            continue
        if _seg_hits_box(sg, nb, shr):
            return False
    if usable and (nb.x0 < usable[0] or nb.y0 < usable[1] or nb.x1 > usable[2] or nb.y1 > usable[3]):
        return False
    for kr in (keepout or {}).values():
        if nb.x0 < kr[2] and kr[0] < nb.x1 and nb.y0 < kr[3] and kr[1] < nb.y1:
            return False
    for vn, r in (view_outlines or {}).items():
        if vn != own_view and nb.x0 < r[2] and r[0] < nb.x1 and nb.y0 < r[3] and r[1] < nb.y1:
            return False
    return True


def render_overlay(pdf: Path, collisions: list[Collision], out_png: Path, page: int = 1, dpi: int = 110) -> Path:
    """The page as a PNG with every collision box outlined (evidence image; the PDF itself is never modified)."""
    import fitz
    doc = fitz.open(str(pdf))
    try:
        pg = doc.load_page(page - 1)
        H = pg.rect.height
        for c in collisions:
            if c.page != page:
                continue
            for box, col in ((c.box_a_mm, (1, 0, 0)), (c.box_b_mm, (1, 0.5, 0))):
                if not box:
                    continue
                x0, y0, x1, y1 = (v / 1000.0 / PT_M for v in box)
                r = fitz.Rect(x0, H - y1, x1, H - y0)
                pg.draw_rect(r + (-2, -2, 2, 2), color=col, width=1.2)
        Path(out_png).parent.mkdir(parents=True, exist_ok=True)
        pg.get_pixmap(dpi=dpi, alpha=False).save(str(out_png))
    finally:
        doc.close()
    return Path(out_png)


def map_notes_to_texts(texts: list[TBox], notes: list[dict]) -> dict:
    """note id -> TBox id by the note's own text (first characters, whitespace-normalised) and proximity. Notes are our own labels, so the text is known exactly."""
    res, used = {}, set()
    for n in notes:
        key = "".join((n.get("text") or "").split()).upper()[:10]
        if len(key) < 4:
            continue
        best = None
        for t in texts:
            if t.id in used:
                continue
            tk = "".join(t.text.split()).upper()
            if tk.startswith(key) or key.startswith(tk[:10]) and len(tk) >= 4:
                d = math.hypot(t.x0 - n["position_m"][0], t.y1 - n["position_m"][1])
                if best is None or d < best[0]:
                    best = (d, t.id)
        if best and best[0] < 0.05:
            res[n["id"]] = best[1]
            used.add(best[1])
    return res
