"""Automatic Engineering Markup: the post-run, pipeline-generated marked copy of the drawing (Stage 3).

Whenever a run produces findings, ``finalize_markup`` (called by ``run_part`` before the terminal event)

1. normalizes them (``pipeline/findings.py``) and writes ``engineering_findings.json`` FIRST, so the flags
   stay visible even if everything after it fails;
2. places them on the right page automatically (``flag_overlays`` / ``flag_locator``: text layer or OCR, never a
   human-drawn position);
3. renders ``<part>_engineering_markup.pdf``: every page of the drawing, unmodified, plus a right-hand label rail.
   Red boxes, number badges, leader lines and label cards are drawn as visible vector/text content (not annotation
   objects), so every viewer shows them. A finding that cannot be located gets an explicit red ``UNLOCATED`` card,
   never a guessed box. Full finding text goes on appended report pages;
4. renders ``engineering_markup_pages/page-NNNN.png`` previews from the final marked PDF;
5. writes ``engineering_markup.json``, the manifest the API and the viewer consume.

This is local and deterministic: no model call, no secrets. The uploaded drawing is never modified, and the
human pre-run ``full_marked_view.jpg`` is a different artifact that this module never touches.

Status: ``not_needed`` (no findings; no stale artifact), ``ready`` (every finding located), ``partial`` (some are
not located precisely), ``failed`` (flags are kept, the marked PDF could not be made; ``failure.code`` says why).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from pipeline.findings import Finding, findings_from_run
from utils.logger import get_logger

log = get_logger()

SCHEMA_VERSION = 1
GENERATOR_VERSION = "engineering_markup/1"
MANIFEST = "engineering_markup.json"
PAGES_DIR = "engineering_markup_pages"
FINDINGS = "engineering_findings.json"
RAIL_W = 290.0
PAD = 8.0
PREVIEW_MAX_PX = 4000
_RED = (0.85, 0.05, 0.05)
_AMBER = (0.80, 0.45, 0.0)
_BLUE = (0.30, 0.40, 0.55)
_SEV = {"error": ("ERROR", _RED), "warning": ("WARNING", _AMBER), "info": ("INFO", _BLUE)}

CODES = ("MARKUP_SOURCE_PDF_MISSING", "MARKUP_FINDINGS_INVALID", "MARKUP_LOCALIZATION_PARTIAL",
         "MARKUP_GENERATION_FAILED", "MARKUP_PREVIEW_FAILED")
_SOURCE_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


class MarkupError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def marked_pdf_name(part: str) -> str:
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in part) or "part"
    return f"{safe}_engineering_markup.pdf"


def eid(n: int) -> str:
    return f"EF-{n:03d}"


def _latin(text: Any) -> str:
    """The built-in PDF fonts are WinAnsi: keep Ø ± ° and friends, replace what they cannot draw."""
    return str(text if text is not None else "").encode("cp1252", "replace").decode("cp1252")


def _wrap(text: str, fs: float, width: float, font: str = "helv") -> list:
    import pymupdf as fitz
    cpl = max(8, int(width / (fitz.get_text_length("n", fontname=font, fontsize=fs) * 1.0)))
    out = []
    for para in str(text).split("\n"):
        out += textwrap.wrap(para, cpl, break_long_words=True) or [""]
    return out


def resolve_source(source: Path, part: str) -> Optional[Path]:
    """The drawing file the run read: a PDF/image, or the full sheet inside a views folder."""
    src = Path(source)
    if src.is_dir():
        for pat in ("00_full.*", f"{part}.*"):
            for p in sorted(src.glob(pat)):
                if p.suffix.lower() in _SOURCE_SUFFIXES:
                    return p
        return None
    return src if src.is_file() and src.suffix.lower() in _SOURCE_SUFFIXES else None


# --------------------------------------------------------------------------- #
# Stale artifacts
# --------------------------------------------------------------------------- #
def clear_stale(out: Path) -> None:
    """Remove every post-run markup artifact of an earlier attempt (never the human full_marked_view.jpg)."""
    out = Path(out)
    for p in list(out.glob("*_engineering_markup.pdf")) + [out / MANIFEST]:
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    shutil.rmtree(out / PAGES_DIR, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def _entries(artifact: Mapping[str, Any], findings: list) -> dict:
    """Per displayed page: the cards to draw. {page_index: [entry]}; page-less / unlocated cards go to page 0."""
    by_id = {f.finding_id: f for f in findings}
    pages: dict = {}
    seen_located = set()
    for o in artifact["overlays"]:
        f = by_id.get(o["finding_id"])
        if f is None:
            continue
        key = (o["finding_id"], o["page_index"])
        e = {"n": o["number"], "finding": f, "located": True, "rects": [o["rect_normalized"]], "page": o["page_index"],
             "note": ""}
        if key in seen_located:                      # several regions of one finding on one page: one card
            for x in pages[o["page_index"]]:
                if x["finding"].finding_id == f.finding_id:
                    x["rects"].append(o["rect_normalized"])
            continue
        seen_located.add(key)
        pages.setdefault(o["page_index"], []).append(e)
    for u in artifact["unlocated_findings"]:
        f = by_id.get(u["finding_id"])
        if f is None:
            continue
        pg = u.get("likely_page")
        pg = 0 if pg is None else int(pg)
        why = u.get("reason", "no_match")
        note = f"Not located precisely ({why})" + (f"; likely view {u['likely_view']}" if u.get("likely_view") else "")
        pages.setdefault(pg, []).append({"n": u["number"], "finding": f, "located": False, "rects": [], "page": pg,
                                         "note": note})
    return pages


def _card_lines(e: dict, fs: float, width: float) -> list:
    f: Finding = e["finding"]
    lines = []
    def add(label, text, limit=170):
        text = _latin(text)
        if text:
            text = text if len(text) <= limit else text[:limit - 1].rstrip() + "..."
            lines.extend(_wrap(f"{label}{text}", fs, width))
    if e["note"]:
        add("", e["note"])
    add("Expected: ", f.expected)
    add("Actual: ", f.actual)
    add("Action: ", f.recommended_action)
    return lines


def _draw_rail(page, entries: list, W: float, H: float, rect_of, k: float = 1.0) -> None:
    """Label rail to the right of the drawing. ``k`` scales type and strokes with the sheet (a D-size drawing is 3x a letter page)."""
    import pymupdf as fitz
    pad = PAD * k
    x0, x1 = W + pad, W + RAIL_W * k - pad
    inner = x1 - x0 - 8 * k
    chosen = None
    for fs in tuple(v * k for v in (7.5, 7.0, 6.5, 6.0, 5.5)):
        cards, total = [], 0.0
        for e in entries:
            title = _latin(f"{eid(e['n'])} [{_SEV.get(e['finding'].severity, _SEV['error'])[0]}] {e['finding'].title}")
            head = _wrap(("UNLOCATED  " if not e["located"] else "") + title, fs + 0.5, inner, "hebo")[:3]
            body = _card_lines(e, fs, inner)
            h = (len(head) * (fs + 3.2 * k)) + 4 * k + (len(body) * (fs + 1.8 * k)) + 5 * k
            cards.append((e, head, body, h))
            total += h + 6 * k
        chosen = (fs, cards)
        if total <= H - 2 * pad:
            break
    fs, cards = chosen
    y = pad
    shown = 0
    for e, head, body, h in cards:
        if y + h > H - pad - (fs + 6 * k if shown < len(cards) - 1 else 0):
            break
        sev_label, col = _SEV.get(e["finding"].severity, _SEV["error"])
        card = fitz.Rect(x0, y, x1, y + h)
        hh = len(head) * (fs + 3.2 * k) + 2 * k
        page.draw_rect(card, color=col, fill=(1, 1, 1), width=1.2 * k)
        page.draw_rect(fitz.Rect(x0, y, x1, y + hh), color=col, fill=col, width=0)
        ty = y + fs + 1.5 * k
        for ln in head:
            page.insert_text((x0 + 4 * k, ty), ln, fontsize=fs + 0.5 * k, fontname="hebo", color=(1, 1, 1))
            ty += fs + 3.2 * k
        ty = y + hh + fs + 1.5 * k
        for ln in body:
            page.insert_text((x0 + 4 * k, ty), ln, fontsize=fs, fontname="helv", color=(0.1, 0.1, 0.1))
            ty += fs + 1.8 * k
        e["_card"] = card
        y += h + 6 * k
        shown += 1
    if shown < len(cards):
        page.insert_text((x0, H - pad), _latin(f"+{len(cards) - shown} more flag(s): see the report pages"),
                         fontsize=fs, fontname="hebo", color=_RED)
    for e, *_ in cards[:shown]:                         # leaders last, so they sit on top of the card edge
        card = e.get("_card")
        for r in e["rects"]:
            box = rect_of(r)
            col = _SEV.get(e["finding"].severity, _SEV["error"])[1]
            page.draw_line(fitz.Point(box.x1, (box.y0 + box.y1) / 2), fitz.Point(card.x0, card.y0 + 8 * k), color=col,
                           width=0.8 * k)


def _report_pages(doc, findings: list, by_number: Mapping[str, int], status_of: Mapping[str, str]) -> int:
    import pymupdf as fitz
    pw, ph, margin = 612.0, 792.0, 40.0
    lines = []
    for f in sorted(findings, key=lambda f: by_number.get(f.finding_id, 10 ** 6)):
        n = by_number.get(f.finding_id, 0)
        lab = _SEV.get(f.severity, _SEV["error"])[0]
        lines += [f"{eid(n)}  [{lab}]  {f.title}", f"   Location: {status_of.get(f.finding_id, 'unlocated')}",
                  f"   Expected: {f.expected}", f"   Actual: {f.actual}", f"   Consequence: {f.consequence}",
                  f"   Manual action: {f.recommended_action}", ""]
        if f.source_callouts:
            lines.insert(len(lines) - 1, f"   Source callout: {'; '.join(f.source_callouts)}")
    wrapped = []
    for ln in lines:
        wrapped += textwrap.wrap(_latin(ln), 105, subsequent_indent="      ") or [""]
    per = 64
    chunks = [wrapped[i:i + per] for i in range(0, max(len(wrapped), 1), per)] or [[]]
    for ci, chunk in enumerate(chunks):
        pg = doc.new_page(width=pw, height=ph)
        pg.insert_text((margin, margin), f"Engineering markup report - {len(findings)} flag(s)"
                       + (f" (page {ci + 1}/{len(chunks)})" if len(chunks) > 1 else ""),
                       fontsize=13, fontname="hebo", color=_RED)
        y = margin + 26
        for ln in chunk:                         # explicit lines: insert_textbox draws nothing when it overflows
            pg.insert_text((margin, y), ln, fontsize=8.5, fontname="helv", color=(0.1, 0.1, 0.1))
            y += 10.5
    return len(chunks)


def render_marked_pdf(artifact: Mapping[str, Any], findings: list, source: Path, out_pdf: Path,
                      pages_dir: Path) -> dict:
    """Write the marked PDF and the per-page PNG previews. Returns {pages: [...], report_pages: n, status_of: {...}}.
    Refuses a drawing whose hash differs from the one the overlays were computed for."""
    import pymupdf as fitz
    from pipeline.flag_overlays import sha256_file
    source = Path(source)
    if sha256_file(source) != artifact["source_pdf_sha256"]:
        raise MarkupError("MARKUP_GENERATION_FAILED", "source hash does not match the overlay artifact")
    src = fitz.open(source)
    if not src.is_pdf:
        src = fitz.open("pdf", src.convert_to_pdf())
    entries = _entries(artifact, findings)
    by_number = {}
    status_of = {}
    for o in artifact["overlays"]:
        by_number[o["finding_id"]] = o["number"]
        status_of[o["finding_id"]] = "located"
    for u in artifact["unlocated_findings"]:
        by_number.setdefault(u["finding_id"], u["number"])
        status_of.setdefault(u["finding_id"], "page_only" if u.get("likely_page") is not None else "unlocated")
    doc = fitz.open()
    page_info = []
    display: dict = {}          # finding_id -> {"regions": [{page, rect}], "card": {page, rect}} in MARKED-page points
    for i in range(len(src)):
        sp = src[i]
        W, H = sp.rect.width, sp.rect.height                  # the DISPLAYED size
        srot, rmat = sp.rotation % 360, sp.rotation_matrix
        sp.set_rotation(0)        # show_pdf_page ignores /Rotate; draw the plain page and rotate it ourselves
        k = max(1.0, max(W, H) / 792.0)                       # type and rail scale with the sheet
        rail = RAIL_W * k
        np_ = doc.new_page(width=W + rail, height=H)
        np_.show_pdf_page(fitz.Rect(0, 0, W, H), src, i, rotate=(360 - srot) % 360)
        np_.draw_rect(fitz.Rect(W, 0, W + rail, H), color=None, fill=(0.97, 0.97, 0.97))
        np_.draw_line(fitz.Point(W, 0), fitz.Point(W, H), color=(0.6, 0.6, 0.6), width=0.6 * k)
        Wu, Hu = (H, W) if srot in (90, 270) else (W, H)       # unrotated page size

        def rect_of(n, rmat=rmat, Wu=Wu, Hu=Hu):
            r = fitz.Rect(n["x"] * Wu, n["y"] * Hu, (n["x"] + n["width"]) * Wu, (n["y"] + n["height"]) * Hu)
            return (r * rmat).normalize()

        page_entries = sorted(entries.get(i, []), key=lambda e: (not e["located"], e["n"]))
        for e in page_entries:
            col = _SEV.get(e["finding"].severity, _SEV["error"])[1]
            for r in e["rects"]:
                box = rect_of(r)
                display.setdefault(e["finding"].finding_id, {"regions": [], "card": None})["regions"].append(
                    {"page": i + 1, "rect": [round(box.x0, 2), round(box.y0, 2), round(box.x1, 2), round(box.y1, 2)]})
                np_.draw_rect(box, color=col, fill=col, fill_opacity=0.10, width=2.2 * k)
                np_.draw_circle(fitz.Point(box.x0, box.y0), 7.5 * k, color=col, fill=col)
                np_.insert_text(fitz.Point(box.x0 - 3.2 * k * len(str(e["n"])), box.y0 + 2.8 * k), str(e["n"]), fontsize=8 * k,
                                fontname="hebo", color=(1, 1, 1))
        if page_entries:
            _draw_rail(np_, page_entries, W, H, rect_of, k)
            for e in page_entries:
                card = e.get("_card")
                if card is not None:
                    display.setdefault(e["finding"].finding_id, {"regions": [], "card": None})["card"] = {
                        "page": i + 1, "rect": [round(card.x0, 2), round(card.y0, 2), round(card.x1, 2), round(card.y1, 2)]}
        page_info.append({"page": i + 1, "width_pt": round(W + rail, 2), "height_pt": round(H, 2),
                          "drawing_width_pt": round(W, 2), "rail_width_pt": round(rail, 2),
                          "source_rotation": srot,
                          "finding_ids": [eid(e["n"]) for e in page_entries]})
    n_report = _report_pages(doc, findings, by_number, status_of) if findings else 0
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_pdf, garbage=3, deflate=True)
    # previews come from the FINAL marked PDF
    pages_dir = Path(pages_dir)
    shutil.rmtree(pages_dir, ignore_errors=True)
    pages_dir.mkdir(parents=True, exist_ok=True)
    try:
        with fitz.open(out_pdf) as final:
            for i, info in enumerate(page_info):
                pg = final[i]
                dpi = int(max(40, min(110, PREVIEW_MAX_PX / (max(pg.rect.width, pg.rect.height) / 72.0))))
                name = f"page-{i + 1:04d}.png"
                pg.get_pixmap(dpi=dpi).save(pages_dir / name)
                info["preview"] = f"{PAGES_DIR}/{name}"
                info["preview_dpi"] = dpi
    except Exception as e:   # noqa: BLE001
        raise MarkupError("MARKUP_PREVIEW_FAILED", f"{type(e).__name__}: {e}") from e
    return {"pages": page_info, "report_pages": n_report, "status_of": status_of, "by_number": by_number,
            "display": display}


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #
def _finding_record(f: Finding, artifact: Mapping[str, Any], rendered: Mapping[str, Any]) -> dict:
    n = rendered["by_number"].get(f.finding_id, 0)
    st = rendered["status_of"].get(f.finding_id, "unlocated")
    regions = [o for o in artifact["overlays"] if o["finding_id"] == f.finding_id]
    unl = next((u for u in artifact["unlocated_findings"] if u["finding_id"] == f.finding_id), None)
    rec = {"id": eid(n), "number": n, "finding_id": f.finding_id, "severity": f.severity.upper(),
           "code": f.category, "title": f.title,
           "explanation": f"Expected: {f.expected}. Actual: {f.actual}. {f.consequence}".strip(),
           "expected": f.expected, "actual": f.actual, "consequence": f.consequence,
           "manual_action": f.recommended_action, "location_status": st,
           "source_callout": "; ".join(f.source_callouts), "feature_ids": list(f.feature_ids),
           "page": None, "location_method": None, "confidence": 0.0, "rect_pdf_points": None, "rect_normalized": None,
           "regions": []}
    if regions:
        first = regions[0]
        pg = next((p for p in rendered["pages"] if p["page"] == first["page_index"] + 1), None)
        rec.update(page=first["page_index"] + 1, location_method=first["mapping_method"],
                   confidence=first["mapping_confidence"],
                   rect_normalized=[first["rect_normalized"][k] for k in ("x", "y", "width", "height")])
        pages_meta = {p["page_index"]: p for p in artifact["pages"]}
        for o in regions:
            pm = pages_meta.get(o["page_index"], {})
            Wu, Hu = pm.get("width", 0), pm.get("height", 0)
            n_ = o["rect_normalized"]
            rec["regions"].append({"page": o["page_index"] + 1, "method": o["mapping_method"], "confidence": o["mapping_confidence"],
                                   "rect_normalized": [n_["x"], n_["y"], n_["width"], n_["height"]],
                                   "rect_pdf_points": [round(n_["x"] * Wu, 2), round(n_["y"] * Hu, 2),
                                                       round((n_["x"] + n_["width"]) * Wu, 2),
                                                       round((n_["y"] + n_["height"]) * Hu, 2)]})
        rec["rect_pdf_points"] = rec["regions"][0]["rect_pdf_points"]
        _ = pg
        for g, d in zip(rec["regions"], (rendered.get("display", {}).get(f.finding_id) or {}).get("regions", [])):
            g["rect_marked_pt"] = d["rect"]
    elif unl is not None:
        rec["page"] = None if unl.get("likely_page") is None else int(unl["likely_page"]) + 1
        rec["location_method"] = unl.get("reason")
    card = (rendered.get("display", {}).get(f.finding_id) or {}).get("card")
    if card:
        rec["card"] = card
        if rec["page"] is None:
            rec["page"] = card["page"]          # an unlocated card sits on page 1 (or its likely page)
    return rec


def build_manifest(part: str, run_id: str, source: Path, findings: list, artifact: Mapping[str, Any],
                   rendered: Mapping[str, Any], pdf_name: str) -> dict:
    recs = [_finding_record(f, artifact, rendered) for f in findings]
    recs.sort(key=lambda r: r["number"])
    located = sum(1 for r in recs if r["location_status"] == "located")
    return {"schema_version": SCHEMA_VERSION, "part": part, "run_id": run_id, "source_pdf": Path(source).name,
            "source_sha256": artifact["source_pdf_sha256"], "marked_pdf": pdf_name,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "generator_version": GENERATOR_VERSION, "finding_count": len(recs), "located_count": located,
            "unlocated_count": len(recs) - located,
            "status": "ready" if located == len(recs) else "partial",
            "warnings": ([{"code": "MARKUP_LOCALIZATION_PARTIAL",
                           "detail": f"{len(recs) - located} of {len(recs)} flag(s) could not be placed precisely"}]
                         if located != len(recs) else []),
            "report_pages": rendered["report_pages"], "pages": rendered["pages"], "findings": recs,
            "generation_key": hashlib.sha1(f"{run_id}|{artifact['source_pdf_sha256']}|{len(recs)}".encode()).hexdigest()[:12]}


def _write_manifest(out: Path, manifest: dict) -> dict:
    (Path(out) / MANIFEST).write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _empty_manifest(part: str, run_id: str, status: str, *, count: int = 0, failure: Optional[dict] = None,
                    source: str = "") -> dict:
    m = {"schema_version": SCHEMA_VERSION, "part": part, "run_id": run_id, "source_pdf": source, "marked_pdf": None,
         "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "generator_version": GENERATOR_VERSION, "finding_count": count, "located_count": 0, "unlocated_count": count,
         "status": status, "pages": [], "findings": [], "warnings": [], "report_pages": 0,
         "generation_key": hashlib.sha1(f"{run_id}|{status}|{count}".encode()).hexdigest()[:12]}
    if failure:
        m["failure"] = failure
    return m


def _write_findings(out: Path, run_id: str, part: str, findings: list) -> None:
    (Path(out) / FINDINGS).write_text(json.dumps({"schema_version": 1, "run_id": run_id, "part": part,
                                                  "findings": [f.to_dict() for f in findings]}, indent=2,
                                                 ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------- #
# The pipeline stage
# --------------------------------------------------------------------------- #
def enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    return env.get("GPTASTRA_AUTO_ENGINEERING_FLAGS", "1") != "0"


def finalize_markup(out: Path, source: Path, *, run_id: str, part: Optional[str] = None,
                    env: Optional[Mapping[str, str]] = None, tick=None) -> Optional[dict]:
    """Collect -> localize -> render -> publish. Never raises: every outcome is a manifest.
    ``tick(stage)`` is called once per stage (collect|localize|render|publish) so progress counts real work."""
    out = Path(out)
    tick = tick or (lambda stage: None)
    if not enabled(env):
        return None
    part = part or out.name
    clear_stale(out)
    stage = "collect"
    try:
        findings = findings_from_run(out, run_id)
        if findings:
            part = findings[0].part or part
        _write_findings(out, run_id, part, findings)           # flags survive any later failure
        tick("collect")
    except Exception as e:   # noqa: BLE001
        log.warning("engineering markup: findings invalid for %s: %s", part, e)
        for s in ("collect", "localize", "render", "publish"):
            tick(s)
        return _write_manifest(out, _empty_manifest(part, run_id, "failed",
                                                    failure={"code": "MARKUP_FINDINGS_INVALID",
                                                             "detail": f"{type(e).__name__}: {e}"[:300]}))
    if not findings:
        for fn in ("engineering_flag_overlays.json", "engineering_flags_annotated.pdf"):
            try:
                (out / fn).unlink()
            except FileNotFoundError:
                pass
        for s in ("localize", "render", "publish"):
            tick(s)
        return _write_manifest(out, _empty_manifest(part, run_id, "not_needed"))
    src = resolve_source(source, part)
    if src is None:
        for s in ("localize", "render", "publish"):
            tick(s)
        return _write_manifest(out, _empty_manifest(part, run_id, "failed", count=len(findings),
                                                    failure={"code": "MARKUP_SOURCE_PDF_MISSING",
                                                             "detail": "the drawing file for this run is not available"}))
    try:
        from pipeline.flag_overlays import (build_overlay_artifact, hints_from_run, load_pages,
                                            render_annotated_pdf)
        stage = "localize"
        pages, sha = load_pages(src, ocr_cache=out / "flags_ocr.json")
        art = build_overlay_artifact(findings, pages, source_sha256=sha, run_id=run_id, source_name=src.name,
                                     hints=hints_from_run(out, findings, len(pages)))
        (out / "engineering_flag_overlays.json").write_text(json.dumps(art, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            render_annotated_pdf(art, findings, src, out / "engineering_flags_annotated.pdf")   # the Stage 3 export
        except Exception as e:   # noqa: BLE001 - the new marked PDF below is the canonical one
            log.warning("engineering markup: legacy annotated export failed: %s", e)
        tick("localize")
        stage = "render"
        pdf_name = marked_pdf_name(part)
        rendered = render_marked_pdf(art, findings, src, out / pdf_name, out / PAGES_DIR)
        tick("render")
        stage = "publish"
        manifest = _write_manifest(out, build_manifest(part, run_id, src, findings, art, rendered, pdf_name))
        tick("publish")
        return manifest
    except MarkupError as e:
        code, detail = e.code, e.detail
    except Exception as e:   # noqa: BLE001
        code, detail = "MARKUP_GENERATION_FAILED", f"{stage}: {type(e).__name__}: {e}"[:300]
    log.error("engineering markup failed for %s: %s %s", part, code, detail)
    clear_stale(out)                                             # never leave a half-made artifact to be served
    for s in ("localize", "render", "publish"):
        tick(s)
    return _write_manifest(out, _empty_manifest(part, run_id, "failed", count=len(findings), source=src.name,
                                                failure={"code": code, "detail": detail}))
