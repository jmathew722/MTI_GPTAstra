"""Drawing replication (v8): rebuild a source drawing's sheet as native, editable SolidWorks content, placed from SOURCE coordinates.

What this module owns (SolidFlow_Drawing_Replication.md sections 3-6):

* the source -> sheet frame (``srcmap.SheetFrame``) and the sheet that matches the source page's physical size (no forced default template);
* native sheet geometry for the source's border / title-block grid, detected from the page (vector strokes or scan morphology), drawn as exact sketch lines;
* verbatim editable notes (title block, general notes, tolerance block, source-only callouts) at their source positions, never placeholder text;
* source-coordinate placement of the generated dimensions with measured, minimal, recorded displacement;
* the closed loop: registered renders, structured inventories, numeric deviations, issue lists, side-by-side / overlay / difference images, and an honest status
  (verified | needs_review | blocked | failed).

Nothing here invents text, tolerances or positions: every record carries its provenance, and anything it could not reproduce is an explicit issue.
"""
from __future__ import annotations

import json
import logging
import math
import re
import statistics
from pathlib import Path
from typing import Optional

from reverse import planner, srcmap

log = logging.getLogger(__name__)

# thresholds are configurable per job (options["replication_thresholds"]); these are the spec's proposed initial values
DEFAULT_THRESHOLDS = {"view_center_mm": 1.0, "annotation_anchor_mm": 1.0, "scale_ratio_pct_inferred": 0.5, "notes_verbatim": "exact", "scale_explicit": "exact",
                      "max_unintended_clipping": 0, "max_unresolved_critical": 0}
TITLE_KINDS = ("title_block_field", "tolerance_block", "material", "revision", "finish")
CRITICAL_KINDS = ("linear", "diameter", "radius", "hole_callout", "chamfer", "angular", "thread", "gdt")
DIM_KINDS = ("linear", "diameter", "radius", "angular", "ordinate")
MARGIN_M = 0.006


def thresholds(opts: Optional[dict]) -> dict:
    t = dict(DEFAULT_THRESHOLDS)
    t.update((opts or {}).get("replication_thresholds") or {})
    return t


def active(r) -> bool:
    return bool(getattr(r, "ref_applied", False) and r.job.options.get("replicate", True))


# ------------------------------------------------------------------ sheet and frame

def sheet_target(ex_sheet: dict) -> dict:
    """The sheet to create for a source page: its physical size, snapped to the standard sheet it matches (within 3 %), never forced to a default."""
    w_pt, h_pt = float(ex_sheet.get("width_pt") or 0), float(ex_sheet.get("height_pt") or 0)
    if not (w_pt and h_pt):
        return {"ok": False, "reason": "the source page size is unknown"}
    wm, hm = srcmap.sheet_dims_mm(w_pt, h_pt)
    name = srcmap.name_sheet(wm, hm)
    if name:
        sw, sh = srcmap.STANDARD_SHEETS_MM[name]
        if wm < hm:
            sw, sh = sh, sw
        return {"ok": True, "name": name, "standard": True, "w_m": sw / 1000.0, "h_m": sh / 1000.0, "page_w_mm": round(wm, 2), "page_h_mm": round(hm, 2),
                "note": f"source page {wm:.1f} x {hm:.1f} mm matches {name}"}
    return {"ok": True, "name": "custom", "standard": False, "w_m": wm / 1000.0, "h_m": hm / 1000.0, "page_w_mm": round(wm, 2), "page_h_mm": round(hm, 2),
            "note": f"source page {wm:.1f} x {hm:.1f} mm is not a standard sheet; created at its own size"}


def make_frame(ex_sheet: dict, target: dict) -> srcmap.SheetFrame:
    return srcmap.SheetFrame.physical(float(ex_sheet["width_pt"]), float(ex_sheet["height_pt"]), target["w_m"], target["h_m"])


# ------------------------------------------------------------------ line detection (border / title block grid)

def detect_lines(pdf: Path, page_index: int = 0, dpi: int = 100, min_frac: float = 0.03) -> dict:
    """Long axis-aligned strokes of the SOURCE page in displayed points: ``{"h": [(x0, x1, y)], "v": [(y0, y1, x)], "source": "vector"|"raster"}``.
    Vector pages use the drawing paths; scans use morphological line extraction. Segments are snapped to the axis (a scan's lines are a pixel or two off)."""
    import cv2
    import fitz
    import numpy as np
    doc = fitz.open(str(pdf))
    try:
        pg = doc.load_page(page_index)
        pix = pg.get_pixmap(dpi=dpi, alpha=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) if pix.n >= 3 else img[:, :, 0]
        W_pt, H_pt = pg.rect.width, pg.rect.height
    finally:
        doc.close()
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, bw = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    L = max(20, int(min_frac * pix.width))
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (L, 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, L))
    hmask = cv2.morphologyEx(bw, cv2.MORPH_OPEN, hk)
    vmask = cv2.morphologyEx(bw, cv2.MORPH_OPEN, vk)
    s = 72.0 / dpi
    hs, vs = [], []
    n, lab, stats, _ = cv2.connectedComponentsWithStats(hmask, connectivity=8)
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if w >= L and h <= max(6, w * 0.05):
            hs.append((x * s, (x + w) * s, (y + h / 2.0) * s))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(vmask, connectivity=8)
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if h >= L and w <= max(6, h * 0.05):
            vs.append((y * s, (y + h) * s, (x + w / 2.0) * s))
    return {"h": _merge(hs), "v": _merge(vs), "source": "raster", "page_pt": [W_pt, H_pt], "dpi": dpi}


def _merge(segs: list[tuple[float, float, float]], tol_pt: float = 2.5, gap_pt: float = 8.0) -> list[tuple[float, float, float]]:
    """Merge collinear (same coordinate within ``tol_pt``) segments whose ends are within ``gap_pt``; the merged coordinate is the length-weighted mean."""
    out: list[list] = []
    for a0, a1, c in sorted(segs, key=lambda t: (round(t[2] / tol_pt), t[0])):
        for m in out:
            if abs(m[2] - c) <= tol_pt and a0 <= m[1] + gap_pt and a1 >= m[0] - gap_pt:
                wa, wb = m[1] - m[0], a1 - a0
                m[2] = (m[2] * wa + c * wb) / (wa + wb)
                m[0], m[1] = min(m[0], a0), max(m[1], a1)
                break
        else:
            out.append([a0, a1, c])
    return [(round(a, 2), round(b, 2), round(c, 2)) for a, b, c in out]


def title_block_bbox(ex: dict, lines: Optional[dict]) -> Optional[list[float]]:
    """The title block rectangle in displayed points. Seed = the union of the title-block-kind notes (their boxes come from OCR / the text layer) and the model's
    estimate; then grown to the strokes that touch it. None when the source shows no title block."""
    w, h = float(ex["sheet"]["width_pt"]), float(ex["sheet"]["height_pt"])
    boxes = [n["bbox_pt"] for n in ex.get("notes", []) if n.get("kind") in TITLE_KINDS and n.get("bbox_pt")]
    est = ex["sheet"].get("title_block_bbox_pt")
    if est:
        boxes.append(est)
    if not boxes:
        return None
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    if lines:
        pad = 0.02 * max(w, h)
        for _ in range(3):
            grew = False
            for a0, a1, y in lines["h"]:
                if y0 - pad <= y <= y1 + pad and a1 >= x0 - pad and a0 <= x1 + pad and (a1 - a0) <= 0.6 * w:
                    nx0, nx1 = min(x0, a0), max(x1, a1)
                    ny0, ny1 = min(y0, y), max(y1, y)
                    grew = grew or (nx0, nx1, ny0, ny1) != (x0, x1, y0, y1)
                    x0, x1, y0, y1 = nx0, nx1, ny0, ny1
            for a0, a1, x in lines["v"]:
                if x0 - pad <= x <= x1 + pad and a1 >= y0 - pad and a0 <= y1 + pad and (a1 - a0) <= 0.6 * h:
                    nx0, nx1 = min(x0, x), max(x1, x)
                    ny0, ny1 = min(y0, a0), max(y1, a1)
                    grew = grew or (nx0, nx1, ny0, ny1) != (x0, x1, y0, y1)
                    x0, x1, y0, y1 = nx0, nx1, ny0, ny1
            if not grew:
                break
    return [round(max(0.0, x0), 2), round(max(0.0, y0), 2), round(min(w, x1), 2), round(min(h, y1), 2)]


def sheet_segments(lines: Optional[dict], tb: Optional[list[float]], frame: srcmap.SheetFrame, ex: dict) -> tuple[list[tuple[float, float, float, float]], dict]:
    """Native sheet-geometry segments (sheet metres): the page border (strokes hugging the page edge, spanning most of it) and the title-block grid (strokes inside
    the title block rectangle). Everything else the scan contains (view geometry, dimension lines) is NOT sheet geometry and is never drawn."""
    rep = {"border": 0, "title_block": 0, "skipped": 0}
    segs: list[tuple[float, float, float, float]] = []
    if not lines:
        return segs, rep
    W, H = frame.page_w_pt, frame.page_h_pt
    edge = 0.03 * max(W, H)
    pad = 2.0
    for a0, a1, y in lines["h"]:
        on_edge = (y <= edge or y >= H - edge) and (a1 - a0) >= 0.8 * W
        in_tb = tb is not None and tb[0] - pad <= a0 and a1 <= tb[2] + pad and tb[1] - pad <= y <= tb[3] + pad
        if on_edge or in_tb:
            p, q = frame.to_sheet(a0, y), frame.to_sheet(a1, y)
            segs.append((p[0], p[1], q[0], p[1]))
            rep["border" if on_edge else "title_block"] += 1
        else:
            rep["skipped"] += 1
    for a0, a1, x in lines["v"]:
        on_edge = (x <= edge or x >= W - edge) and (a1 - a0) >= 0.8 * H
        in_tb = tb is not None and tb[1] - pad <= a0 and a1 <= tb[3] + pad and tb[0] - pad <= x <= tb[2] + pad
        if on_edge or in_tb:
            p, q = frame.to_sheet(x, a0), frame.to_sheet(x, a1)
            segs.append((p[0], p[1], p[0], q[1]))
            rep["border" if on_edge else "title_block"] += 1
        else:
            rep["skipped"] += 1
    return segs, rep


# ------------------------------------------------------------------ region override (source authority)

def override_regions(plan: dict, frame: srcmap.SheetFrame, target: dict, tb_pt: Optional[list[float]]) -> dict:
    """Replace the planner's template-derived keep-outs with the SOURCE's: usable area = sheet minus a thin margin, title block = the source title block,
    notes zone = empty (notes live where the source put them). Also records the sheet on the plan."""
    W, H = target["w_m"], target["h_m"]
    usable = planner.Rect(MARGIN_M, MARGIN_M, W - MARGIN_M, H - MARGIN_M)
    if tb_pt:
        b = frame.box_to_sheet(tb_pt)
        title = planner.Rect(b[0], b[1], b[2], b[3])
    else:
        title = planner.Rect(W - 0.002, 0.001, W - 0.001, 0.002)               # source has no title block: a harmless sliver
    notes = planner.Rect(title.x0 - 0.0015, title.y0, title.x0 - 0.001, title.y0 + 0.0005)
    plan["regions_m"] = {"sheet": [0.0, 0.0, W, H], "usable": usable.as_list(), "title_block": title.as_list(), "notes": notes.as_list()}
    plan["sheet_custom"] = {"w_m": W, "h_m": H, "name": target["name"], "standard": target["standard"]}
    plan["replication"] = {"frame": {"page_w_pt": frame.page_w_pt, "page_h_pt": frame.page_h_pt, "k_m_per_pt": frame.k, "ox_m": frame.ox, "oy_m": frame.oy, "notes": frame.notes},
                           "title_block_pt": tb_pt}
    return plan["regions_m"]


# ------------------------------------------------------------------ notes (verbatim, source positions)

def norm_text(t: str) -> str:
    """Whitespace-insensitive but otherwise exact: used to decide 'verbatim'. Case, symbols, digits, zeros and punctuation all count."""
    return re.sub(r"\s+", " ", (t or "").replace("\r", "")).strip()


def note_height_pt(bbox_pt: list[float], text: str, frame: srcmap.SheetFrame) -> float:
    """Character height (pt) that makes the note's lines fit the source box: line pitch ~ 1.35 x character height, scaled when the sheet is not at physical size."""
    lines = max(1, len((text or "").split("\n")))
    pitch_pt = max(1.0, (bbox_pt[3] - bbox_pt[1]) / lines)
    h = pitch_pt / 1.35 * (frame.k / srcmap.PT_TO_M)
    return round(max(3.0, min(h, 24.0)), 1)


def collect_notes(ex: dict, ledger: Optional[list[dict]]) -> list[dict]:
    """Every source text that is not an associative dimension: all notes (verbatim) and every annotation the generated drawing does not carry as a dimension
    (callouts, GD&T, finish symbols, unmatched dimensions). Each record keeps its provenance and its classification."""
    matched = {e["ref_id"] for e in (ledger or []) if e.get("status") in ("matched", "matched_shared")}
    out: list[dict] = []
    for n in ex.get("notes", []):
        t = (n.get("text") or "").strip()
        if not t or not n.get("bbox_pt"):
            continue
        out.append({"id": n["id"], "source": "note", "kind": n.get("kind", "general_note"), "text": t, "bbox_pt": n["bbox_pt"], "position_source": n.get("position_source"),
                    "classification": "source_note", "uncertain": bool(n.get("uncertain"))})
    from reverse.drawingspec import _iou
    for a in ex.get("annotations", []):
        t = (a.get("text") or "").strip()
        if a["id"] in matched or not t or not a.get("bbox_pt"):
            continue
        if any(norm_text(o["text"]) == norm_text(t) and _iou(o["bbox_pt"], a["bbox_pt"]) >= 0.5 for o in out):
            continue
        out.append({"id": a["id"], "source": "annotation", "kind": a.get("kind", "other"), "text": t, "bbox_pt": a["bbox_pt"], "position_source": a.get("position_source"),
                    "classification": "source_only_non_associative", "uncertain": bool(a.get("uncertain")),
                    "why": "no associative dimension with this value exists on the generated drawing (the model has no such geometry, or it is a callout / symbol / note)"})
    return out


def place_notes(r, dd, frame: srcmap.SheetFrame, notes: list[dict]) -> list[dict]:
    """Insert each source text as an editable native note at its source position (top-left of the box). Records every placement (the residual shift to the
    measured position is applied later by ``refine_note_positions``)."""
    recs = []
    for n in notes:
        bx = n["bbox_pt"]
        h_pt = note_height_pt(bx, n["text"], frame)
        x, y = frame.to_sheet(bx[0], bx[1])
        an = dd.add_note(n["text"], x, y, h_pt)
        rec = {**{k: n[k] for k in ("id", "source", "kind", "classification", "position_source", "uncertain")}, "text": n["text"], "height_pt": h_pt,
               "bbox_pt": bx, "target_center_m": list(frame.to_sheet((bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2)), "placed": an is not None, "first_xy_m": [x, y]}
        if an is None:
            rec["error"] = "SOLIDWORKS did not create the note"
        else:
            rec["_an"] = an
        recs.append(rec)
    return recs


def native_note_text(an, s) -> str:
    try:
        tn = s.typed(an.GetSpecificAnnotation(), "INote")
        return str(tn.GetText() or "")
    except Exception:      # noqa: BLE001
        return ""


def refine_note_positions(r, dd, recs: list[dict], pages, frame, max_shift_mm: float = 60.0) -> dict:
    """One measured correction: the rendered text box of each note (found by its own text in the exported PDF) vs its source box centre; shift the annotation by the
    residual. A note whose text cannot be found in the PDF is reported, never guessed."""
    from reverse import layout
    if not pages:
        return {"shifted": 0, "unmeasured": [x["id"] for x in recs if x.get("placed")]}
    texts = pages[0].texts
    used: set = set()
    shifted, unmeasured, deltas = 0, [], []
    for rec in recs:
        an = rec.get("_an")
        if an is None:
            continue
        lines = [norm_text(t) for t in rec["text"].split("\n") if norm_text(t)]
        tx, ty = rec["target_center_m"]
        near = [t for t in texts if t.id not in used and norm_text(t.text) in lines and math.hypot(t.center[0] - tx, t.center[1] - ty) <= max_shift_mm / 1000.0 + 0.15]
        # keep only the lines closest to the target: duplicates of a line elsewhere on the sheet must not pull the note
        near = [t for t in near if math.hypot(t.center[0] - tx, t.center[1] - ty) <= 0.25]
        if not near or (len(near) < max(1, len(lines) // 2)):
            unmeasured.append(rec["id"])
            continue
        box = (min(t.x0 for t in near), min(t.y0 for t in near), max(t.x1 for t in near), max(t.y1 for t in near))
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        dx, dy = tx - cx, ty - cy
        used.update(t.id for t in near)
        rec["measured_center_m"] = [cx, cy]
        rec["residual_mm"] = [round(dx * 1000, 2), round(dy * 1000, 2)]
        if math.hypot(dx, dy) > 0.0003:
            try:
                p = an.GetPosition()
                an.SetPosition2(p[0] + dx, p[1] + dy, 0)
                shifted += 1
                deltas.append(math.hypot(dx, dy) * 1000)
            except Exception as e:      # noqa: BLE001
                rec["error"] = f"{type(e).__name__}: {e}"
    return {"shifted": shifted, "unmeasured": unmeasured, "median_residual_mm": round(statistics.median(deltas), 2) if deltas else 0.0}


# ------------------------------------------------------------------ verification: structured comparison

def view_scale_checks(ex: dict, dd, plan: dict) -> list[dict]:
    """Per-view scale: what the source states vs what the native view carries (exact ratio comparison; never guessed when the source states none)."""
    out = []
    by_role = (plan.get("reference_layout") or {}).get("views", {})
    for role, info in by_role.items():
        rv = info.get("reference_view")
        if not rv or role not in dd.views:
            continue
        v = next((x for x in ex.get("views", []) if x["id"] == rv), None)
        try:
            gen = float(dd.views[role].ScaleDecimal)
        except Exception:      # noqa: BLE001
            gen = None
        from reverse.reflayout import parse_scale
        stated = parse_scale((v or {}).get("scale_text", ""))
        sheet = parse_scale(ex.get("sheet", {}).get("scale_text", ""))
        src = stated or sheet
        origin = "view label" if stated else ("sheet scale" if sheet else None)
        row = {"role": role, "ref_view": rv, "source_scale": f"{src[0]}:{src[1]}" if src else None, "source_scale_origin": origin, "generated_decimal": gen}
        if src and gen is not None:
            want = src[0] / src[1]
            row["generated_scale"] = f"{gen:g}"
            row["match"] = abs(gen - want) <= 1e-9 * max(1.0, want)
        else:
            row["match"] = None
            row["note"] = "the source states no scale for this view; none is assumed" if not src else "generated scale unreadable"
        out.append(row)
    return out


def title_block_scale_from_pdf(pdf: Path, page: int = 0) -> Optional[str]:
    """The SCALE text the exported template/sheet prints (e.g. '1:2'); None when the sheet prints none."""
    import fitz
    d = fitz.open(str(pdf))
    try:
        t = d[page].get_text("text")
    finally:
        d.close()
    m = re.search(r"SCALE\s*[:\n ]\s*(\d+(?:\.\d+)?\s*:\s*\d+(?:\.\d+)?)", t)
    return re.sub(r"\s+", "", m.group(1)) if m else None


_KEEP_NONASCII = set("±°²¼½¾Ø⌀")


def _strip_symbols(t: str) -> str:
    """Remove GD&T / frame glyphs the sheet font cannot print (position, runout, perpendicularity, frame bars); everything else must still be exact."""
    return norm_text("".join(ch for ch in t if (ord(ch) < 128 or ch in _KEEP_NONASCII) and ch != "|"))


def note_verbatim_check(recs: list[dict], pages) -> dict:
    """Is every placed source text present, verbatim (line by line, whitespace-normalised, case-exact), in the EXPORTED pdf? Read from the PDF, not from our own record.
    A line that differs ONLY by GD&T / frame glyphs the export did not print is reported separately as ``symbols_unverified`` (never counted as verbatim)."""
    texts = [norm_text(t.text) for t in (pages[0].texts if pages else [])]
    joined = " ".join(texts)
    stripped = [_strip_symbols(t) for t in texts]
    ok, bad, symb = 0, [], []
    for rec in recs:
        if not rec.get("placed"):
            bad.append({"id": rec["id"], "why": "not placed", "text": rec["text"][:60]})
            continue
        lines = [norm_text(t) for t in rec["text"].split(chr(10)) if norm_text(t)]
        missing = [ln for ln in lines if ln not in texts and ln not in joined]
        if not missing:
            ok += 1
            continue
        still = [ln for ln in missing if _strip_symbols(ln) and _strip_symbols(ln) not in stripped and _strip_symbols(ln) not in " ".join(stripped)]
        if not still:
            symb.append({"id": rec["id"], "text": rec["text"][:60], "why": "the GD&T / frame glyphs were not printed by the export; the remaining text is exact"})
        else:
            bad.append({"id": rec["id"], "why": "text not found verbatim in the exported PDF", "missing_lines": still[:4], "text": rec["text"][:60]})
    return {"matched": ok, "total": len(recs), "mismatched": bad, "symbols_unverified": symb}


def decide_status(m: dict, th: dict) -> tuple[str, str]:
    """verified | needs_review | blocked | failed, from MEASURED results only. Verified needs every explicit scale exact, zero unintended clipping, zero unresolved
    critical mismatches, notes verbatim, and view / annotation anchors within the thresholds."""
    if m.get("blocked"):
        return "blocked", m["blocked"]
    if m.get("failed"):
        return "failed", m["failed"]
    reasons = []
    if m.get("sheet_scale_exact") is not True:
        reasons.append("sheet scale / title block scale not confirmed equal to the source")
    if any(v.get("match") is False for v in m.get("view_scales", [])):
        reasons.append("a view scale differs from the source")
    if m.get("unintended_clipping", 0) > th["max_unintended_clipping"]:
        reasons.append(f"{m['unintended_clipping']} unintended clipping / off-sheet item(s)")
    if m.get("critical_mismatches", 0) > th["max_unresolved_critical"]:
        reasons.append(f"{m['critical_mismatches']} unresolved critical mismatch(es)")
    nv = m.get("notes_verbatim") or {}
    if nv.get("mismatched"):
        reasons.append(f"{len(nv['mismatched'])} note(s) not verbatim in the export")
    if nv.get("symbols_unverified"):
        reasons.append(f"{len(nv['symbols_unverified'])} note(s) carry GD&T / frame glyphs the export did not print")
    vc = m.get("view_center_dev_mm") or {}
    if vc.get("max") is not None and vc["max"] > th["view_center_mm"]:
        reasons.append(f"view centre deviation up to {vc['max']:.1f} mm (limit {th['view_center_mm']} mm)")
    ac = m.get("annotation_anchor_dev_mm") or {}
    if ac.get("max") is not None and ac["max"] > th["annotation_anchor_mm"]:
        reasons.append(f"annotation anchor deviation up to {ac['max']:.1f} mm (limit {th['annotation_anchor_mm']} mm)")
    if m.get("missing_views"):
        reasons.append(f"{len(m['missing_views'])} source view(s) not reproduced")
    if m.get("pages_missing"):
        reasons.append(f"{len(m['pages_missing'])} source page(s) not reconstructed")
    if m.get("unresolved_source_items"):
        reasons.append(f"{m['unresolved_source_items']} source item(s) are non-associative notes or missing and need engineer review")
    if reasons:
        return "needs_review", "; ".join(reasons[:4]) + (" ..." if len(reasons) > 4 else "")
    return "verified", "every measured criterion is within its threshold"


STATUS_LABEL = {"verified": "Verified", "needs_review": "Needs Review", "blocked": "Blocked", "failed": "Failed", "pending": "Pending"}


# ------------------------------------------------------------------ evidence images (registered by sheet coordinates)

def render_evidence(src_pdf: Path, gen_pdf: Path, frame: srcmap.SheetFrame, out_dir: Path, page: int = 0, gen_page: int = 0, width_px: int = 1500, tag: str = "page-001") -> dict:
    """Side-by-side, overlay and difference images with both pages drawn into ONE sheet-registered canvas (no warping: the source is placed by the frame's own
    scale and offset, so a scale error stays visible). Dark pixels: source = red, generated = blue, both = black."""
    import fitz
    import numpy as np
    from PIL import Image
    out_dir.mkdir(parents=True, exist_ok=True)
    gd = fitz.open(str(gen_pdf))
    try:
        gp = gd.load_page(gen_page)
        zoom = width_px / gp.rect.width
        gpix = gp.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        gimg = Image.frombytes("RGB", (gpix.width, gpix.height), gpix.samples)
        sheet_w_pt = gp.rect.width
    finally:
        gd.close()
    sd = fitz.open(str(src_pdf))
    try:
        sp = sd.load_page(page)
        # canvas px per generated-sheet point = zoom; the source is placed at k/PT_TO_M x its own size with the frame offset
        s = zoom * (frame.k / srcmap.PT_TO_M)
        spix = sp.get_pixmap(matrix=fitz.Matrix(s, s), alpha=False)
        simg = Image.frombytes("RGB", (spix.width, spix.height), spix.samples)
    finally:
        sd.close()
    canvas = (gimg.width, gimg.height)
    src_on = Image.new("RGB", canvas, (255, 255, 255))
    ox_px = int(round(frame.ox / srcmap.PT_TO_M * zoom))
    oy_px = int(round(frame.oy / srcmap.PT_TO_M * zoom))
    # the frame's oy is measured from the sheet BOTTOM; the source page's bottom sits oy above the canvas bottom
    top_px = canvas[1] - oy_px - simg.height
    src_on.paste(simg, (ox_px, top_px))
    a = np.array(src_on.convert("L")) < 170
    b = np.array(gimg.convert("L")) < 170
    ov = np.full((canvas[1], canvas[0], 3), 255, np.uint8)
    ov[a & ~b] = (220, 40, 40)
    ov[b & ~a] = (40, 70, 230)
    ov[a & b] = (0, 0, 0)
    diff = np.full((canvas[1], canvas[0], 3), 255, np.uint8)
    diff[a ^ b] = (0, 0, 0)
    gap = 14
    sbs = Image.new("RGB", (canvas[0] * 2 + gap, canvas[1]), (255, 255, 255))
    sbs.paste(src_on, (0, 0))
    sbs.paste(gimg, (canvas[0] + gap, 0))
    paths = {"side_by_side": out_dir / f"{tag}_side_by_side.png", "overlay": out_dir / f"{tag}_overlay.png", "difference": out_dir / f"{tag}_diff.png"}
    sbs.save(paths["side_by_side"], optimize=True)
    Image.fromarray(ov).save(paths["overlay"], optimize=True)
    Image.fromarray(diff).save(paths["difference"], optimize=True)
    return {"paths": {k: str(v) for k, v in paths.items()}, "pixel_similarity": round(float(1.0 - (a ^ b).sum() / max(1, (a | b).sum())), 4),
            "note": "Pixel similarity is a diagnostic only; it is not proof of equivalence (scan artifacts and hand lettering differ from CAD text by nature)."}
