"""Engineering-flag overlays: the artifact the viewer draws and the flattened PDF it exports (Stage 3).

Everything here is automatic. ``write_flags`` reads a run's findings, extracts each drawing page's text
(the PDF text layer, or OCR for a scan), places every source callout with ``flag_locator``, and writes:

* ``engineering_findings.json``        the findings (schema in ``pipeline/findings.py``)
* ``engineering_flag_overlays.json``   page index + normalized unrotated rectangle + method + confidence
* ``engineering_flags_annotated.pdf``  the drawing with the same red markup burned in, plus a report page

The overlay artifact is deterministic (no timestamps) and tied to the drawing by SHA-256, so an overlay
can never be drawn on a different revision. A manually authored positions file is NEVER read here; the
only override is an explicit ``developer_positions`` argument, and it is labeled in the artifact.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Optional

from pipeline.findings import Finding, findings_from_run
from pipeline.flag_locator import Box, PageData, locate_callout

OVERLAY_SCHEMA_VERSION = 1
OCR_DPI = 150
MIN_TEXT_CHARS = 12          # a page with less text than this is treated as a scan
LABEL_MAX = 60
_REASON_RANK = {"ambiguous": 5, "low_confidence": 4, "region_too_coarse": 3, "view_level": 2, "no_match": 1}
_SEV_COLOR = {"error": (0.85, 0.05, 0.05), "warning": (0.90, 0.55, 0.0), "info": (0.35, 0.45, 0.60)}
_SEV_LABEL = {"error": "ERROR", "warning": "WARNING", "info": "INFO"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# Page text (text layer, else OCR)
# --------------------------------------------------------------------------- #
def _text_layer_boxes(page) -> list:
    """Text lines in the DISPLAYED page. PyMuPDF reports text in the unrotated page, so rotate it."""
    import pymupdf as fitz
    boxes = []
    for blk in page.get_text("dict").get("blocks", []):
        if blk.get("type") != 0:
            continue
        for ln in blk.get("lines", []):
            text = " ".join(s.get("text", "") for s in ln.get("spans", [])).strip()
            if text:
                r = (fitz.Rect(ln["bbox"]) * page.rotation_matrix).normalize()
                boxes.append(Box(text=text, rect=[r.x0, r.y0, r.x1, r.y1], conf=1.0))
    return boxes


def _ocr_boxes(page) -> Optional[list]:
    """OCR of the displayed page (rapidocr, local, no API cost). None when OCR is not installed."""
    try:
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return None
    pix = page.get_pixmap(dpi=OCR_DPI)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
    res, _ = RapidOCR()(img)
    s = 72 / OCR_DPI
    return [Box(text=t, conf=float(c), rect=[min(p[0] for p in b) * s, min(p[1] for p in b) * s,
                                             max(p[0] for p in b) * s, max(p[1] for p in b) * s])
            for b, t, c in (res or [])]


def load_pages(source: Path, ocr_cache: Optional[Path] = None) -> tuple:
    """([PageData], sha256) for a PDF or an image. OCR results are cached per drawing hash."""
    import pymupdf as fitz
    source = Path(source)
    sha = sha256_file(source)
    cache: dict = {}
    if ocr_cache and Path(ocr_cache).is_file():
        try:
            c = json.loads(Path(ocr_cache).read_text(encoding="utf-8"))
            if c.get("sha256") == sha:
                cache = c.get("pages", {})
        except (OSError, ValueError):
            cache = {}
    pages, dirty = [], False
    with fitz.open(source) as doc:
        for i, page in enumerate(doc):
            boxes = _text_layer_boxes(page)
            src = "text_layer"
            if sum(len(b.text) for b in boxes) < MIN_TEXT_CHARS:
                if str(i) in cache:
                    boxes = [Box(**b) for b in cache[str(i)]]
                    src = "ocr"
                else:
                    ocr = _ocr_boxes(page)
                    if ocr is None:
                        boxes, src = [], "none"
                    else:
                        boxes, src, dirty = ocr, "ocr", True
                        cache[str(i)] = [{"text": b.text, "rect": [round(v, 2) for v in b.rect], "conf": round(b.conf, 3)} for b in ocr]
            pages.append(PageData(index=i, width=page.rect.width, height=page.rect.height, rotation=page.rotation,
                                  source=src, boxes=boxes))
    if dirty and ocr_cache:
        Path(ocr_cache).write_text(json.dumps({"sha256": sha, "pages": cache}), encoding="utf-8")
    return pages, sha


# --------------------------------------------------------------------------- #
# The artifact
# --------------------------------------------------------------------------- #
def _label(n: int, title: str) -> str:
    base = f"{n}: {title}"
    return base if len(base) <= LABEL_MAX else base[:LABEL_MAX - 1].rstrip() + "…"


def _place_labels(overlays: list) -> None:
    """Label anchors to the right of each box; stacked labels are pushed down so none overlap."""
    by_page: dict = {}
    for o in sorted(overlays, key=lambda o: (o["page_index"], o["rect_normalized"]["y"], o["rect_normalized"]["x"], o["overlay_id"])):
        r = o["rect_normalized"]
        x, y = min(1.0, r["x"] + r["width"] + 0.004), r["y"]
        taken = by_page.setdefault(o["page_index"], [])
        moved = True
        while moved:
            moved = False
            for tx, ty in taken:
                if abs(ty - y) < 0.02 and abs(tx - x) < 0.12:
                    y = round(y + 0.02, 6)
                    moved = True
        y = min(y, 0.98)
        taken.append((x, y))
        o["label_anchor_normalized"] = {"x": round(x, 6), "y": round(y, 6)}


def build_overlay_artifact(findings: list, pages: list, *, source_sha256: str, run_id: str, source_name: str,
                           hints: Optional[Mapping[str, Mapping[str, Any]]] = None,
                           developer_positions: Optional[Mapping[str, Mapping[str, Any]]] = None) -> dict:
    """Place every finding automatically. ``hints[finding_id]`` may carry hint_page / hint_region / hint_view
    from extraction. ``developer_positions`` is an explicit, labeled escape hatch for diagnostics only."""
    hints = hints or {}
    ordered = sorted(findings, key=lambda f: f.finding_id)
    overlays, unlocated = [], []
    by_page = {p.index: p for p in pages}
    for n, f in enumerate(ordered, 1):
        base = {"finding_id": f.finding_id, "number": n, "severity": f.severity, "label": _label(n, f.title)}
        if developer_positions and f.finding_id in developer_positions:
            d = developer_positions[f.finding_id]
            pg = by_page.get(d["page_index"])
            overlays.append({**base, "overlay_id": f"ov_{f.finding_id}_1", "page_index": d["page_index"], "shape": "rect",
                             "rect_normalized": dict(d["rect_normalized"]), "mapping_method": "developer_override",
                             "mapping_confidence": 1.0, "matched_text": "", "rotation_degrees": pg.rotation % 360 if pg else 0,
                             "source_callout": "", "provenance": "developer_override"})
            continue
        if not f.source_callouts:
            unlocated.append({**base, "reason": "no_source_callout", "likely_page": None, "likely_view": None,
                              "likely_region": None, "candidates": 0, "source_callouts": [], "attempts": []})
            continue
        h = hints.get(f.finding_id, {})
        placements = [locate_callout(c, pages, hint_page=h.get("hint_page"), hint_region=h.get("hint_region"),
                                     hint_view=h.get("hint_view")) for c in f.source_callouts]
        seen, k = [], 0
        for p in placements:
            if not p.located:
                continue
            key = (p.page_index, tuple(round(v, 4) for v in p.rect_normalized.values()))
            if key in seen:
                continue
            seen.append(key)
            k += 1
            overlays.append({**base, "overlay_id": f"ov_{f.finding_id}_{k}", "page_index": p.page_index, "shape": "rect",
                             "rect_normalized": {a: round(b, 6) for a, b in p.rect_normalized.items()},
                             "mapping_method": p.method, "mapping_confidence": p.confidence, "matched_text": p.matched_text,
                             "rotation_degrees": p.rotation_degrees, "source_callout": p.callout, "provenance": "automatic"})
        if not seen:
            worst = max(placements, key=lambda p: _REASON_RANK.get(p.reason, 0))
            unlocated.append({**base, "reason": worst.reason, "likely_page": worst.likely_page, "likely_view": worst.likely_view,
                              "likely_region": worst.likely_region, "candidates": worst.candidates,
                              "source_callouts": list(f.source_callouts), "attempts": worst.attempts})
    _place_labels(overlays)
    overlays.sort(key=lambda o: (o["page_index"], o["rect_normalized"]["y"], o["rect_normalized"]["x"], o["overlay_id"]))
    return {"schema_version": OVERLAY_SCHEMA_VERSION, "source_pdf_sha256": source_sha256, "source_name": source_name,
            "run_id": run_id,
            "pages": [{"page_index": p.index, "width": round(p.width, 2), "height": round(p.height, 2),
                       "rotation": p.rotation % 360, "text_source": p.source} for p in pages],
            "overlays": overlays, "unlocated_findings": unlocated}


# --------------------------------------------------------------------------- #
# Hints from the run (plan + extraction): which view a feature belongs to
# --------------------------------------------------------------------------- #
def hints_from_run(out: Path, findings: list, n_pages: int) -> dict:
    """{finding_id: {hint_page?, hint_view?}}: the view most of a feature's dimensions were read in."""
    out = Path(out)
    hints: dict = {}
    try:
        plan = (json.loads((out / "plan.json").read_text(encoding="utf-8")).get("plan") or {}).get("features", [])
        ext = next((json.loads(p.read_text(encoding="utf-8")) for p in sorted(out.glob("*_extraction.json"))), {})
    except (OSError, ValueError):
        return hints
    view_of = {d.get("id"): d.get("view") for d in ext.get("dimensions", []) if isinstance(d, dict) and d.get("view")}
    feats = {f.get("id"): f for f in plan if isinstance(f, dict)}
    for f in findings:
        votes: dict = {}
        for fid in f.feature_ids:
            feat = feats.get(fid) or {}
            ids = [v for k, v in feat.items() if k in ("u", "v") and isinstance(v, str)]
            ids += [v for v in (feat.get("spec") or {}).values() if isinstance(v, str) and re.fullmatch(r"D\d+", v)]
            for did in ids:
                if view_of.get(did):
                    votes[view_of[did]] = votes.get(view_of[did], 0) + 1
        h: dict = {}
        if votes:
            h["hint_view"] = max(sorted(votes), key=lambda k: votes[k])
        if n_pages == 1:
            h["hint_page"] = 0
        if h:
            hints[f.finding_id] = h
    return hints


# --------------------------------------------------------------------------- #
# The flattened PDF (same contract as the live overlay)
# --------------------------------------------------------------------------- #
def _wrap(text: str, width: int) -> list:
    import textwrap
    return textwrap.wrap(text, width) or [""]


def render_annotated_pdf(artifact: Mapping[str, Any], findings: list, source: Path, out_pdf: Path) -> Path:
    """Burn the overlays into a copy of the drawing and append a report page. Refuses a drawing whose
    hash is not the one the overlays were computed for."""
    import pymupdf as fitz
    source = Path(source)
    if sha256_file(source) != artifact["source_pdf_sha256"]:
        raise ValueError("source hash does not match the overlay artifact (a different drawing revision)")
    src = fitz.open(source)
    doc = fitz.open("pdf", src.convert_to_pdf()) if not src.is_pdf else src
    by_id = {f.finding_id: f for f in findings}
    used: dict = {}                                   # page index -> label rectangles already placed (displayed page)
    for o in artifact["overlays"]:
        page = doc[o["page_index"]]
        rot = page.rotation % 360
        Wu, Hu = (page.rect.height, page.rect.width) if rot in (90, 270) else (page.rect.width, page.rect.height)
        n = o["rect_normalized"]
        r = fitz.Rect(n["x"] * Wu, n["y"] * Hu, (n["x"] + n["width"]) * Wu, (n["y"] + n["height"]) * Hu)   # unrotated page
        col = _SEV_COLOR.get(o["severity"], _SEV_COLOR["error"])
        page.draw_rect(r, color=col, fill=col, fill_opacity=0.12, width=2.0)
        # The label is placed in the DISPLAYED page (upright text, never past an edge, never on another label).
        box = (r * page.rotation_matrix).normalize()
        fs = 8.0
        tw = fitz.get_text_length(o["label"], fontname="helv", fontsize=fs)
        x = box.x1 + 3 if box.x1 + 3 + tw <= page.rect.width - 2 else max(2.0, box.x0 - 3 - tw)
        y = min(page.rect.height - 3, max(fs + 1, box.y0 + fs))
        taken = used.setdefault(o["page_index"], [])
        while any(abs(ty - y) < fs + 2 and tx < x + tw and x < tx + tww for tx, ty, tww in taken) and y < page.rect.height - 3:
            y = min(page.rect.height - 3, y + fs + 2)
        taken.append((x, y, tw))
        pt = fitz.Point(x, y) * page.derotation_matrix
        page.insert_text(pt, o["label"], fontsize=fs, color=(0.45, 0.0, 0.0), rotate=rot)
    meta = {o["finding_id"]: o for o in artifact["overlays"]}
    rows = sorted(list(artifact["overlays"]) + list(artifact["unlocated_findings"]), key=lambda x: (x["number"], x.get("overlay_id", "")))
    seen, lines = set(), []
    for x in rows:
        if x["finding_id"] in seen:
            continue
        seen.add(x["finding_id"])
        f = by_id.get(x["finding_id"])
        if f is None:
            continue
        where = (f"page {x['page_index'] + 1}, {x['mapping_method']} ({x['mapping_confidence']:.2f})" if "overlay_id" in x
                 else f"not located on the drawing ({x['reason']}" + (f"; likely page {x['likely_page'] + 1}" if x.get('likely_page') is not None else "")
                 + (f"; view {x['likely_view']}" if x.get("likely_view") else "") + ")")
        lines += [f"{x['number']}. [{_SEV_LABEL.get(f.severity, f.severity)}] {f.title}", f"   Where: {where}",
                  f"   Expected: {f.expected}", f"   Actual: {f.actual}", f"   Consequence: {f.consequence}",
                  f"   Recommended: {f.recommended_action}", ""]
    pw, ph, per, margin = 612, 792, 62, 40
    chunks = [lines[i:i + per] for i in range(0, max(len(lines), 1), per)] or [[]]
    for ci, chunk in enumerate(chunks):
        pg = doc.new_page(width=pw, height=ph)
        head = f"Engineering flags ({len(seen)})" + (f" - page {ci + 1}" if len(chunks) > 1 else "")
        pg.insert_text((margin, margin), head, fontsize=13, fontname="hebo", color=(0.55, 0.0, 0.0))
        body = "\n".join(w for ln in chunk for w in _wrap(ln, 100))
        pg.insert_textbox(fitz.Rect(margin, margin + 12, pw - margin, ph - margin), body, fontsize=8.5, fontname="helv")
    Path(out_pdf).parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_pdf, garbage=3, deflate=True)
    return Path(out_pdf)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def write_flags(out: Path, source: Path, *, run_id: str, developer_positions: Optional[Mapping[str, Mapping[str, Any]]] = None) -> dict:
    """Findings -> automatic placement -> artifacts beside the run's other outputs. Returns a small summary.
    ``out/markup_positions*.json`` is never read."""
    out = Path(out)
    findings = findings_from_run(out, run_id)
    pages, sha = load_pages(source, ocr_cache=out / "flags_ocr.json")
    art = build_overlay_artifact(findings, pages, source_sha256=sha, run_id=run_id, source_name=Path(source).name,
                                 hints=hints_from_run(out, findings, len(pages)), developer_positions=developer_positions)
    part = findings[0].part if findings else out.name
    (out / "engineering_findings.json").write_text(json.dumps({"schema_version": 1, "run_id": run_id, "part": part,
                                                               "findings": [f.to_dict() for f in findings]}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "engineering_flag_overlays.json").write_text(json.dumps(art, indent=2, ensure_ascii=False), encoding="utf-8")
    annotated = render_annotated_pdf(art, findings, source, out / "engineering_flags_annotated.pdf")
    return {"findings": len(findings), "overlays": len(art["overlays"]), "unlocated": len(art["unlocated_findings"]),
            "source_sha256": sha, "annotated_pdf": str(annotated)}
