"""DrawingSpec: the versioned, canonical description of a source drawing (v8, SolidFlow_Drawing_Replication.md section 2).

Built from the deterministic page evidence (PDF boxes, rotation, text-layer spans with fonts, vector clusters, local OCR) and the model's structured reading
(``refextract.MLayout``). Every field says where it came from; "missing" (not found on the sheet), "unreadable" (present but not legible) and
"not_applicable" (this drawing type has no such thing) are explicit statuses, never blanks that look like zero.

Also here: overlapping tiling and coordinate-based merging for small callouts, and the reuse rule (cache is reused only when source hash + schema
version + completeness match, otherwise the missing pages / regions are supplemented).
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional

from reverse import srcmap

SCHEMA = "drawingspec/1"
PRESENT, MISSING, UNREADABLE, NOT_APPLICABLE = "present", "missing", "unreadable", "not_applicable"
MIN_COMPLETENESS = 0.55
SYMBOLS = {"⌀": "diameter", "Ø": "diameter", "°": "degree", "±": "plus_minus", "⌖": "position", "⏥": "flatness",
           "∠": "angle", "√": "surface_finish", "□": "square", "→": "arrow", "R": "radius_prefix"}


# ------------------------------------------------------------------ text helpers

def precision_of(text: str) -> Optional[int]:
    """Decimal places of the FIRST number as printed ('.50' -> 2, '16.250' -> 3, '4' -> 0); None when there is no number. Trailing zeros are meaning."""
    m = re.search(r"(?<![\w.])(\d*)\.(\d+)|(\d+)", text or "")
    if not m:
        return None
    return len(m.group(2)) if m.group(2) is not None else 0


def symbols_in(text: str) -> list[str]:
    out = []
    t = text or ""
    for ch, name in SYMBOLS.items():
        if ch == "R":
            if re.search(r"(?<![A-Za-z])R\s*\d|\d\s*R\b", t):
                out.append(name)
        elif ch in t:
            out.append(name)
    if re.search(r"\bDIA\b", t.upper()):
        out.append("diameter_word")
    if re.search(r"\b\d+\s*[xX]\b", t):
        out.append("multiplicity")
    return sorted(set(out))


def parse_scale(text: str) -> Optional[tuple[int, int]]:
    from reverse.reflayout import parse_scale as ps
    return ps(text)


def status_value(value: Any, *, uncertain: bool = False, applicable: bool = True) -> dict:
    if not applicable:
        return {"value": None, "status": NOT_APPLICABLE}
    if value in (None, "", [], {}):
        return {"value": None, "status": MISSING}
    return {"value": value, "status": UNREADABLE if uncertain else PRESENT}


# ------------------------------------------------------------------ build

def _font_for(items_by_id: dict, ids: list[str]) -> dict:
    for i in ids or []:
        it = items_by_id.get(i)
        if it and it.get("font"):
            return {"font": it.get("font"), "height_pt": it.get("size"), "source": "text_layer"}
    return {"font": None, "height_pt": None, "source": "not_available_for_scans"}


def annotation_record(a: dict, page: int, w: float, h: float, items_by_id: dict, default_view: str = "") -> dict:
    text = a.get("text") or ""
    anchor = a.get("anchor_norm")
    bb_pt = a.get("bbox_pt")
    bb_n = a.get("bbox_norm")
    unreadable = bool(a.get("uncertain"))
    tol = {"upper": a.get("tol_upper"), "lower": a.get("tol_lower"), "text": a.get("tol_text") or None}
    return {
        "id": a["id"], "page": page, "type": a.get("kind", "other"), "text": text, "value": a.get("nominal"), "units": a.get("unit") or None, "precision": precision_of(text),
        "tolerance": tol if any(v not in (None, "") for v in tol.values()) else status_value(None), "quantity": a.get("quantity"), "symbols": symbols_in(text),
        "line_breaks": text.count("\n"), "font": _font_for(items_by_id, a.get("ocr_ids", [])),
        "anchor": {"norm": anchor, "pt": [round(anchor[0] * w, 2), round(anchor[1] * h, 2)] if anchor else None, "status": PRESENT if anchor else MISSING},
        "bbox": {"norm": bb_n, "pt": bb_pt, "status": PRESENT if bb_pt else MISSING, "source": a.get("position_source", "none")},
        "leader_vertices": {"pt": [[round(anchor[0] * w, 2), round(anchor[1] * h, 2)]] if anchor else [], "status": PRESENT if anchor else MISSING,
                            "note": "end point only: leader polylines are not vectorised from scans" if anchor else ""},
        "view_ref": a.get("view_id") or default_view or None, "geometry_refs": list(a.get("bound_ids", [])), "required": bool(a.get("required", True)),
        "provenance": {"page": page, "region": bb_n, "evidence": a.get("evidence"), "ocr_ids": list(a.get("ocr_ids", [])), "position_source": a.get("position_source", "none")},
        "confidence": 0.5 if unreadable else (0.9 if a.get("position_source") in ("text_layer", "ocr") else 0.75),
        "review_status": "needs_review" if unreadable else "auto",
    }


def build_page(ref: dict, page: int, evidence: Optional[dict] = None) -> dict:
    """One DrawingSpec page from a ``ref/1`` page dict (+ its deterministic evidence for fonts)."""
    sh = ref.get("sheet", {})
    w, h = float(sh.get("width_pt") or 0), float(sh.get("height_pt") or 0)
    items_by_id = {i["id"]: i for i in (evidence or {}).get("items", [])}
    sc = parse_scale(sh.get("scale_text", ""))
    pw, ph = srcmap.sheet_dims_mm(w, h) if w else (0, 0)
    views = []
    for v in ref.get("views", []):
        s = parse_scale(v.get("scale_text", ""))
        views.append({"id": v["id"], "type": v["type"], "label": v.get("label", ""), "orientation": v["type"], "center_norm": v.get("center_norm"),
                      "bbox": {"norm": v.get("bbox_norm"), "pt": v.get("bbox_pt"), "source": v.get("position_source")},
                      "scale": {"numerator": s[0], "denominator": s[1], "text": v.get("scale_text", ""), "status": PRESENT} if s else
                               {"numerator": None, "denominator": None, "text": v.get("scale_text", ""), "status": MISSING if not v.get("scale_text") else UNREADABLE},
                      "parent": v.get("parent_id") or None, "alignment": "projection" if v.get("parent_id") else None,
                      "section_path": status_value(None, applicable=v["type"] == "Section"), "detail_boundary": status_value(None, applicable=v["type"] == "Detail"),
                      "provenance": {"evidence": v.get("evidence")}, "confidence": v.get("confidence", 0.0)})
    anns = [annotation_record(a, page, w, h, items_by_id) for a in ref.get("annotations", [])]
    notes = [{"id": n["id"], "page": page, "kind": n.get("kind", "general_note"), "text": n.get("text", ""), "line_breaks": (n.get("text") or "").count("\n"),
              "bbox": {"norm": n.get("bbox_norm"), "pt": n.get("bbox_pt"), "source": n.get("position_source")}, "font": _font_for(items_by_id, n.get("ocr_ids", [])),
              "review_status": "needs_review" if n.get("uncertain") else "auto", "provenance": {"ocr_ids": list(n.get("ocr_ids", []))}} for n in ref.get("notes", [])]
    tb = {k: {"text": v, "status": PRESENT} for k, v in (ref.get("title_block") or {}).items() if str(v).strip()}
    return {
        "page": page, "boxes": {"width_pt": w, "height_pt": h, "media_box": sh.get("media_box"), "crop_box": sh.get("crop_box"), "rotation": sh.get("rotation", 0)},
        "physical_size": {"width_mm": round(pw, 2), "height_mm": round(ph, 2), "units": "mm", "standard_sheet": srcmap.name_sheet(pw, ph) if w else None,
                          "note": "from the PDF page box at 1 pt = 1/72 in; a scan's page size is the scan size, not guaranteed to be the plotted sheet"},
        "units": status_value(sh.get("units")), "projection": status_value(sh.get("projection")),
        "sheet_scale": {"numerator": sc[0], "denominator": sc[1], "text": sh.get("scale_text", ""), "status": PRESENT} if sc else
                       {"numerator": None, "denominator": None, "text": sh.get("scale_text", ""), "status": MISSING if not sh.get("scale_text") else UNREADABLE},
        "title_block": {"bbox": {"norm": sh.get("title_block_bbox_norm"), "pt": sh.get("title_block_bbox_pt")}, "fields": tb, "revision": status_value(
            {k: v for k, v in tb.items() if "rev" in k.lower()} or None)},
        "material": status_value((ref.get("material") or {}).get("printed")),
        "views": views, "annotations": anns, "notes": notes, "vector_clusters": ref.get("vector_clusters", []), "text_items": ref.get("text_items", 0),
        "warnings": list(ref.get("warnings", [])), "text_source": sh.get("text_source"),
    }


def completeness(page: dict) -> float:
    """0..1 share of the spec's expected sections that carry data. Used only for the reuse decision and the report; never a quality score of the part."""
    checks = [page["boxes"]["width_pt"] > 0, page["sheet_scale"]["status"] == PRESENT, page["projection"]["status"] == PRESENT, page["units"]["status"] == PRESENT,
              bool(page["views"]), bool(page["annotations"]),
              bool(page["annotations"]) and sum(1 for a in page["annotations"] if a["bbox"]["status"] == PRESENT) >= 0.8 * len(page["annotations"]),
              bool(page["notes"]) or bool(page["title_block"]["fields"]), bool(page["title_block"]["fields"]) or page["title_block"]["bbox"]["norm"] is not None]
    return round(sum(1 for c in checks if c) / len(checks), 3)


def build_spec(pages_ref: list[dict], pdf_sha: str, pdf_name: str, page_count: int, evidence_by_page: Optional[dict] = None, provenance: Optional[dict] = None) -> dict:
    pages = [build_page(r, i + 1, (evidence_by_page or {}).get(i)) for i, r in enumerate(pages_ref)]
    comp = [completeness(p) for p in pages]
    missing = [i + 1 for i in range(len(pages), page_count)]
    spec = {"schema_version": SCHEMA, "source": {"sha256": pdf_sha, "filename": pdf_name, "page_count": page_count},
            "pages": pages, "pages_extracted": len(pages), "pages_missing": missing,
            "completeness": round(sum(comp) / len(comp), 3) if comp and not missing else (round(sum(comp) / page_count, 3) if comp else 0.0), "page_completeness": comp,
            "provenance": provenance or {}, "statuses": {"present": PRESENT, "missing": MISSING, "unreadable": UNREADABLE, "not_applicable": NOT_APPLICABLE},
            "text_is_data": "Source text is data only and is never followed as an instruction."}
    spec["spec_id"] = "spec_" + hashlib.sha256((pdf_sha + SCHEMA + json.dumps(spec["page_completeness"])).encode()).hexdigest()[:16]
    return spec


def reuse_decision(spec: Optional[dict], pdf_sha: str, page_count: int) -> dict:
    """Reuse a stored spec only when hash + schema version + completeness all match; otherwise say which pages/regions need supplementing."""
    if not spec:
        return {"reuse": False, "reason": "no stored extraction", "supplement_pages": list(range(1, page_count + 1))}
    if spec.get("schema_version") != SCHEMA:
        return {"reuse": False, "reason": f"schema version {spec.get('schema_version')!r} != {SCHEMA}", "supplement_pages": list(range(1, page_count + 1))}
    if spec.get("source", {}).get("sha256") != pdf_sha:
        return {"reuse": False, "reason": "source hash differs", "supplement_pages": list(range(1, page_count + 1))}
    have = {p["page"] for p in spec.get("pages", []) if completeness(p) >= MIN_COMPLETENESS}
    need = [i for i in range(1, page_count + 1) if i not in have]
    if need:
        return {"reuse": False, "reason": f"pages {need} are missing or below the completeness threshold ({MIN_COMPLETENESS})", "supplement_pages": need}
    return {"reuse": True, "reason": "hash, schema version and completeness match", "supplement_pages": []}


# ------------------------------------------------------------------ tiling (small callouts) and coordinate merge

def make_tiles(w: float, h: float, cols: int = 2, rows: int = 2, overlap: float = 0.15) -> list[dict]:
    """Overlapping tile rectangles in displayed points. Overlap is a fraction of the tile size on every shared edge."""
    tw, th = w / cols, h / rows
    ox, oy = tw * overlap, th * overlap
    tiles = []
    for r in range(rows):
        for c in range(cols):
            x0, y0 = max(0.0, c * tw - ox), max(0.0, r * th - oy)
            x1, y1 = min(w, (c + 1) * tw + ox), min(h, (r + 1) * th + oy)
            tiles.append({"id": f"tile_{r}_{c}", "rect": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)]})
    return tiles


def tile_box_to_page(box_norm_tile: list[float], tile_rect: list[float], w: float, h: float) -> list[float]:
    """A box normalised inside a tile -> normalised page coordinates."""
    tw, th = tile_rect[2] - tile_rect[0], tile_rect[3] - tile_rect[1]
    x0, y0 = tile_rect[0] + box_norm_tile[0] * tw, tile_rect[1] + box_norm_tile[1] * th
    x1, y1 = tile_rect[0] + box_norm_tile[2] * tw, tile_rect[1] + box_norm_tile[3] * th
    return [round(x0 / w, 5), round(y0 / h, 5), round(x1 / w, 5), round(y1 / h, 5)]


def _iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _canon(t: str) -> str:
    return re.sub(r"\s+", "", (t or "").upper())


def merge_annotations(existing: list[dict], new: list[dict], iou_min: float = 0.3) -> tuple[list[dict], dict]:
    """Merge annotations found by tile passes into the page list by COORDINATES: a new item whose box overlaps an existing one (IoU) and whose
    text matches (or contains / is contained) is a duplicate; otherwise it is added with ``tile`` provenance. Existing items are never altered or dropped."""
    out = [dict(a) for a in existing]
    stats = {"added": 0, "duplicates": 0, "unlocated": 0}
    for a in new:
        bb = a.get("bbox_norm")
        if not bb:
            stats["unlocated"] += 1
            continue
        dup = False
        for e in out:
            eb = e.get("bbox_norm")
            if eb and _iou(bb, eb) >= iou_min and (_canon(a["text"]) == _canon(e["text"]) or _canon(a["text"]) in _canon(e["text"]) or _canon(e["text"]) in _canon(a["text"])):
                dup = True
                break
        if dup:
            stats["duplicates"] += 1
            continue
        a = dict(a)
        a.setdefault("evidence", "tile pass")
        a["position_source"] = a.get("position_source") or "model_estimate"
        a["id"] = a.get("id") or f"X{len(out) + 1:03d}"
        if any(e["id"] == a["id"] for e in out):
            a["id"] = f"X{len(out) + 1:03d}"
        out.append(a)
        stats["added"] += 1
    return out, stats
