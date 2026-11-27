"""Reference vs generated drawing comparison (v7, spec 02 "Comparison and bounded repair").

Semantic first (every required reference item gets exactly one ledger status with a denominator), then spatial deltas in sheet millimetres.
Rules that matter:
* the TRUE model value is what the drawing shows. A reference value that the model does not have is reported (``value_differs``), never forced onto the
  drawing; nothing is text-overridden;
* a tolerance, finish, GD&T symbol or material is never invented. Reference tolerances are reported as ``tolerance_not_applied`` (preserved in the
  reference-note block / the QA ledger for engineering review);
* pixel similarity is never used as proof; visual evidence is saved separately.
"""
from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

UNIT_M = {"inch": 0.0254, "in": 0.0254, "mm": 0.001, "millimeter": 0.001, "millimeters": 0.001, "cm": 0.01, "m": 1.0, "deg": None, "degree": None}
NUM_RE = re.compile(r"(?<![\d.A-Za-z])(\d*\.\d+|\d+(?:\.\d*)?)")
DIAM_RE = re.compile(r"[Ø⌀ø]|\bDIA\b|\bDIAM", re.I)
QTY_RE = re.compile(r"(?<![\d.])(\d+)\s*[Xx]\b")
SPATIAL_VIEW_MM = 1.0
SPATIAL_ANN_MM = 2.0
GENERAL_NOTE_KINDS = ("general_note", "finish", "tolerance_block", "material", "revision")


def norm_unit(u: str) -> Optional[str]:
    u = (u or "").strip().lower()
    if u.startswith("in"):
        return "inch"
    if u.startswith("mm") or u.startswith("millim"):
        return "mm"
    if u.startswith("deg") or u in ("°",):
        return "deg"
    return None


@dataclass
class RefNumber:
    value: Optional[float]
    decimals: int
    qty: int
    diameter: bool
    text: str


def parse_annotation(a: dict) -> RefNumber:
    """The printed numeric characteristic of a reference annotation (string first; the model's nominal only when the string has no number)."""
    text = a.get("text") or ""
    qty = int(a.get("quantity") or 0)
    m = QTY_RE.search(text)
    if m and not qty:
        qty = int(m.group(1))
    body = QTY_RE.sub(" ", text, count=1)
    nums = NUM_RE.findall(body)
    val, dec = None, 0
    if nums:
        tok = nums[0]
        val = float(tok.rstrip("."))
        dec = len(tok.split(".")[1]) if "." in tok else 0
    elif a.get("nominal") is not None:
        val = float(a["nominal"])
        dec = len(repr(val).split(".")[1]) if "." in repr(val) else 0
    return RefNumber(val, dec, qty or 1, bool(DIAM_RE.search(text)) or a.get("kind") in ("diameter",), text)


def tol_m(num: RefNumber, unit: Optional[str]) -> float:
    um = UNIT_M.get(unit or "", None)
    if not um:
        return 0.0
    return 0.5 * 10 ** (-num.decimals) * um * 1.001 + 1e-7


@dataclass
class LedgerEntry:
    id: str
    ref_id: str
    kind: str
    text: str
    required: bool
    status: str                      # matched | matched_shared | value_differs | missing | preserved_note | tolerance_not_applied | unit_unknown | not_applicable | page_not_reconstructed
    native_id: str = ""
    expected: Optional[str] = None
    observed: Optional[str] = None
    reason: str = ""
    severity: str = "info"

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, "")}


def semantic(ref: dict, native_dims: list[dict], *, default_unit: Optional[str], notes_carried: set[str], native_material: Optional[str], native_views: dict) -> dict:
    """Per-item semantic comparison. ``native_dims`` = standards.Standards.inventory() rows (true model values, metres)."""
    ledger: list[LedgerEntry] = []
    used: dict[str, str] = {}
    sheet_unit = norm_unit(ref.get("sheet", {}).get("units", "")) or default_unit
    pages = ref.get("source", {}).get("pages", 1)
    for a in ref.get("annotations", []):
        req = bool(a.get("required", True))
        k = a.get("kind", "other")
        e = LedgerEntry(f"L{len(ledger) + 1:03d}", a.get("id", "?"), k, a.get("text", ""), req, "not_applicable")
        if k in ("center_mark", "finish", "gdt", "other") and not NUM_RE.search(a.get("text", "")):
            if k in ("finish", "gdt"):
                e.status, e.severity = "unresolved_requirement", "high" if req else "info"
                e.reason = f"{k} callouts are never invented or generated; the printed text is preserved in the QA ledger for engineering review"
            else:
                e.reason = "no numeric characteristic"
            ledger.append(e)
            continue
        num = parse_annotation(a)
        if num.value is None:
            e.status, e.severity, e.reason = "unresolved_requirement", "medium" if req else "info", "no number could be read from this annotation"
            ledger.append(e)
            continue
        unit = norm_unit(a.get("unit", "")) or ("deg" if k == "angular" else sheet_unit)
        if unit is None:
            e.status, e.severity, e.reason = "unit_unknown", "high" if req else "info", "the reference does not state its units; the value is not compared (units are never guessed)"
            ledger.append(e)
            continue
        if unit == "deg" or k == "angular":
            e.status, e.reason, e.severity = "unresolved_requirement", "angular dimensions are not generated by this pipeline", "medium" if req else "info"
            ledger.append(e)
            continue
        expected = num.value * UNIT_M[unit]
        tol = tol_m(num, unit)
        cands = [d for d in native_dims if "error" not in d and not d.get("dangling")]
        hit = min((d for d in cands if abs(d["value_m"] - expected) <= tol), key=lambda d: abs(d["value_m"] - expected), default=None)
        e.expected = f"{num.value:g} {unit}"
        if hit is not None:
            shared = hit["id"] in used
            e.status = "matched_shared" if shared else "matched"
            e.native_id = hit["id"]
            used.setdefault(hit["id"], e.ref_id)
            e.observed = f"{hit['value_m'] / UNIT_M[unit]:.4f} {unit}"
            e.reason = "the true model value equals the printed value within its printed precision" + (f" (the same dimension also serves {used[hit['id']]})" if shared else "")
            if a.get("tol_text") or a.get("tol_upper") not in (None, 0) or a.get("tol_lower") not in (None, 0):
                led2 = LedgerEntry(f"L{len(ledger) + 1:03d}t", e.ref_id, "tolerance", a.get("tol_text") or f"+{a.get('tol_upper')} / -{a.get('tol_lower')}", req, "tolerance_not_applied",
                                   native_id=hit["id"], reason="the reference prints a tolerance; tolerances are never invented or applied automatically, the printed text is kept for review",
                                   severity="medium" if req else "info")
                ledger.append(e)
                ledger.append(led2)
                continue
        else:
            near = min(cands, key=lambda d: abs(d["value_m"] - expected), default=None)
            if near is not None and abs(near["value_m"] - expected) <= 0.15 * max(expected, 1e-9) and expected > 0:
                e.status = "value_differs"
                e.native_id = near["id"]
                e.observed = f"{near['value_m'] / UNIT_M[unit]:.4f} {unit}"
                e.severity = "high" if req else "medium"
                e.reason = (f"the reference prints {num.value:g} {unit} but the model's true value is {near['value_m'] / UNIT_M[unit]:.4f} {unit}; the true value is shown, "
                            "nothing was overridden")
            else:
                e.status = "missing"
                e.severity = "high" if req and k in ("linear", "diameter", "radius", "hole_callout") else ("medium" if req else "info")
                e.reason = "no dimension of this value exists on the generated drawing (the model has no such geometry, or this pipeline did not dimension it)"
        ledger.append(e)
    for n in ref.get("notes", []):
        req = n.get("kind", "general_note") in GENERAL_NOTE_KINDS
        e = LedgerEntry(f"L{len(ledger) + 1:03d}", n.get("id", "?"), "note:" + n.get("kind", "general_note"), n.get("text", ""), req, "not_applicable")
        if n.get("id") in notes_carried:
            e.status, e.reason = "preserved_note", "carried verbatim into the reference-note block with provenance (not engineering approval)"
        elif req:
            e.status, e.severity, e.reason = "unresolved_requirement", "medium", "this note could not be placed on the sheet; see the QA ledger for its text"
        else:
            e.reason = "administrative text (title block data is generated from the part and template)"
        ledger.append(e)
    # material: only a printed material is compared; never inferred
    ref_mat = (ref.get("material") or {}).get("printed")
    mat = {"reference": ref_mat or None, "native": native_material, "status": "not_specified_on_reference" if not ref_mat else "unverified"}
    if ref_mat:
        a, b = re.sub(r"[^a-z0-9]", "", ref_mat.lower()), re.sub(r"[^a-z0-9]", "", (native_material or "").lower())
        if not native_material:
            mat["status"] = "reference_only"
            mat["note"] = "The reference prints a material but the model has none assigned; the drawing title block says NOT SPECIFIED (never guessed)."
        elif a and (a in b or b in a):
            mat["status"] = "consistent"
        else:
            mat["status"] = "mismatch"
            mat["note"] = "The reference material text does not match the material assigned to the model."
    if pages > 1:
        ledger.append(LedgerEntry(f"L{len(ledger) + 1:03d}", "pages", "sheet", f"{pages} reference pages", True, "page_not_reconstructed",
                                  reason=f"the reference has {pages} pages; only sheet 1 content was extracted and reconstructed", severity="high"))
    req_items = [e for e in ledger if e.required and e.kind != "tolerance"]
    ok_status = ("matched", "matched_shared", "preserved_note")
    matched = sum(1 for e in req_items if e.status in ok_status)
    unresolved = [e.as_dict() for e in ledger if e.status not in ok_status + ("not_applicable",) or (e.kind == "tolerance")]
    views = view_presence(ref, native_views)
    return {"ledger": [e.as_dict() for e in ledger], "coverage": {"matched": matched, "total": len(req_items), "unresolved": unresolved}, "material": mat, "views": views,
            "counts": {s: sum(1 for e in ledger if e.status == s) for s in sorted({e.status for e in ledger})}}


def view_presence(ref: dict, native_views: dict) -> list[dict]:
    """Reference view types vs the generated views: presence and scale text (never claims orientation equality beyond the standard-view type)."""
    have: dict = {}
    for role, info in native_views.items():
        have.setdefault(info.get("ref_view") or info["type"], []).append(role)      # a silhouette-matched role answers for its reference view
        have.setdefault(info["type"], []).append(role)
    out = []
    for v in ref.get("views", []):
        t = v["type"]
        roles = have.get(v["id"]) or have.get(t) or []
        out.append({"ref_view": v["id"], "type": t, "reference_scale": v.get("scale_text", ""), "present": bool(roles), "native_roles": roles,
                    "note": "" if roles else f"no matching {t} view was generated (this pipeline generates front/top/right, an isometric and hole sections)"})
    return out


# ------------------------------------------------------------------ spatial

def spatial(ref: dict, W: float, H: float, native_view_centers: dict, ann_boxes: dict, ledger: list[dict], *, view_mm: float = SPATIAL_VIEW_MM,
            ann_mm: float = SPATIAL_ANN_MM) -> dict:
    """Deltas in sheet millimetres on a common normalized-sheet frame: reference normalized (x, 1-y) * (W, H) vs the generated centres."""
    views = []
    for v in ref.get("views", []):
        for role, info in native_view_centers.items():
            if (info.get("ref_view") and info["ref_view"] != v["id"]) or (not info.get("ref_view") and info["type"] != v["type"]):
                continue
            cx, cy = v["center_norm"][0] * W, (1 - v["center_norm"][1]) * H
            dx, dy = (info["center_m"][0] - cx) * 1000, (info["center_m"][1] - cy) * 1000
            views.append({"ref_view": v["id"], "native": role, "type": v["type"], "delta_mm": [round(dx, 2), round(dy, 2)], "distance_mm": round(math.hypot(dx, dy), 2),
                          "within_target": math.hypot(dx, dy) <= view_mm, "target_mm": view_mm})
            break
    anns = []
    by_ref = {a["id"]: a for a in ref.get("annotations", [])}
    for e in ledger:
        if e.get("status") not in ("matched", "matched_shared") or not e.get("native_id"):
            continue
        a = by_ref.get(e["ref_id"])
        box = ann_boxes.get(e["native_id"])
        if not a or not a.get("bbox_norm") or box is None:
            continue
        bx = a["bbox_norm"]
        cx, cy = (bx[0] + bx[2]) / 2 * W, (1 - (bx[1] + bx[3]) / 2) * H
        dx, dy = (box[0] - cx) * 1000, (box[1] - cy) * 1000
        anns.append({"ref_id": e["ref_id"], "native": e["native_id"], "text": e.get("text", ""), "delta_mm": [round(dx, 1), round(dy, 1)], "distance_mm": round(math.hypot(dx, dy), 1),
                     "within_target": math.hypot(dx, dy) <= ann_mm, "target_mm": ann_mm, "position_source": a.get("position_source")})
    d = [x["distance_mm"] for x in anns]
    vd = [x["distance_mm"] for x in views]
    return {"views": views, "annotations": anns,
            "summary": {"views_compared": len(views), "views_within_target": sum(1 for x in views if x["within_target"]), "view_median_mm": round(statistics.median(vd), 1) if vd else None,
                        "annotations_compared": len(anns), "annotations_within_target": sum(1 for x in anns if x["within_target"]),
                        "annotation_median_mm": round(statistics.median(d), 1) if d else None, "annotation_max_mm": max(d) if d else None,
                        "targets_note": "Spatial targets (1 mm views, 2 mm annotations) are drafting-comparison targets, not manufacturing tolerances. Positions from a scan are OCR/model estimates "
                                        "with the stated position_source; the reference page proportions may differ from the supported sheet formats (see sheet deviation)."},
            "transform": {"x": "nx * W", "y": "(1 - ny) * H", "W_m": W, "H_m": H}}


def spatial_score(sp: dict) -> float:
    """Lower is better: mean of per-item distances (mm); used only to choose between layout revisions, never as a pass criterion."""
    d = [x["distance_mm"] for x in sp.get("annotations", [])] + [x["distance_mm"] * 3 for x in sp.get("views", [])]
    return statistics.fmean(d) if d else 0.0


# ------------------------------------------------------------------ evidence images

def render_side_by_side(ref_pdf: Path, new_pdf: Path, out_png: Path, *, ref_ex: Optional[dict] = None, collisions_boxes_mm: Optional[list] = None,
                        native_ann_boxes: Optional[dict] = None, height_px: int = 1000, W: float = 0.0, H: float = 0.0) -> Path:
    """Reference page (green = reference annotations, blue = reference views) next to the generated page (red = collisions, orange = generated annotation text)."""
    import fitz
    from PIL import Image, ImageDraw
    def page_img(pdf: Path) -> Image.Image:
        d = fitz.open(str(pdf))
        try:
            pg = d.load_page(0)
            zoom = height_px / pg.rect.height
            pix = pg.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        finally:
            d.close()
    a, b = page_img(ref_pdf), page_img(new_pdf)
    da, db = ImageDraw.Draw(a), ImageDraw.Draw(b)
    if ref_ex:
        for an in ref_ex.get("annotations", []):
            bb = an.get("bbox_norm")
            if bb:
                da.rectangle([bb[0] * a.width, bb[1] * a.height, bb[2] * a.width, bb[3] * a.height], outline=(0, 160, 0), width=2)
        for v in ref_ex.get("views", []):
            bb = v["bbox_norm"]
            da.rectangle([bb[0] * a.width, bb[1] * a.height, bb[2] * a.width, bb[3] * a.height], outline=(0, 90, 220), width=3)
    if W and H:
        for box in (native_ann_boxes or {}).values():
            pass
        for bx in collisions_boxes_mm or []:
            x0, y0, x1, y1 = (bx[0] / 1000 / W * b.width, (1 - bx[3] / 1000 / H) * b.height, bx[2] / 1000 / W * b.width, (1 - bx[1] / 1000 / H) * b.height)
            db.rectangle([x0 - 3, y0 - 3, x1 + 3, y1 + 3], outline=(230, 0, 0), width=3)
    gap = 12
    out = Image.new("RGB", (a.width + b.width + gap, max(a.height, b.height)), (255, 255, 255))
    out.paste(a, (0, 0))
    out.paste(b, (a.width + gap, 0))
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    out.save(str(out_png), optimize=True)
    return Path(out_png)
