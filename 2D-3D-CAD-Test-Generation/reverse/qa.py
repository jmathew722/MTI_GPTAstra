"""Engineering QA for generated drawings: coverage ledger, semantic de-duplication, review issues, text-box collision checks and PDF checks.

Separation of concerns (QA spec): geometric coverage, design-intent completeness and layout quality are reported separately; a hard failure is
never hidden by a high score; software QA is never manufacturing approval.
"""
from __future__ import annotations

import itertools
import json
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from reverse.planner import Rect

SOURCES = ("model_dimension", "feature_parameter", "geometry_derived", "PMI", "user_approved")
STATUSES = ("covered", "not_applicable", "unresolved", "review_required")
SEVERITIES = ("critical", "high", "medium", "low", "info")
CLEARANCE_MIN_M = 0.002          # 2 mm clear space between unrelated text boxes (profile may raise it to 3 mm)
BLACK_TOL = 0.02


# ---------------------------------------------------------------- review issues

_issue_seq = itertools.count(1)


def issue(severity: str, code: str, message: str, *, source_ref: str = "", view: str = "", sheet: Optional[int] = None, observed: str = "",
          expected: str = "", next_action: str = "", part_id: str = "") -> dict:
    assert severity in SEVERITIES, severity
    return {"id": f"{(part_id or 'P')}-{code}-{next(_issue_seq):03d}", "severity": severity, "code": code, "message": message, "source_ref": source_ref,
            "view": view, "sheet": sheet, "observed": observed, "expected": expected, "next_action": next_action, "history": []}


# ---------------------------------------------------------------- coverage ledger

@dataclass
class LedgerItem:
    id: str
    characteristic: str               # semantic key: "<feature>:<what>", e.g. "F003:diameter"
    category: str                     # size | location | orientation | feature
    source: str
    value: Optional[float] = None
    units: str = "m"
    tolerance: str = "not specified"  # provenance of any tolerance - never guessed
    feature_id: str = ""
    view: str = ""
    annotation_id: str = ""
    status: str = "unresolved"
    evidence: str = ""
    reason: str = ""                  # why excluded / unresolved


class Ledger:
    def __init__(self) -> None:
        self.items: list[LedgerItem] = []

    def add(self, item: LedgerItem) -> LedgerItem:
        assert item.source in SOURCES and item.status in STATUSES
        self.items.append(item)
        return item

    def by_char(self) -> dict[str, list[LedgerItem]]:
        d: dict[str, list[LedgerItem]] = {}
        for it in self.items:
            d.setdefault(it.characteristic, []).append(it)
        return d

    def duplicates(self) -> list[dict]:
        """Two covered annotations for the same semantic characteristic are a duplicate controlling dimension. Equal numbers alone never make
        a duplicate (two different features may share a value)."""
        out = []
        for ch, items in self.by_char().items():
            cov = [i for i in items if i.status == "covered"]
            if len(cov) > 1:
                out.append({"characteristic": ch, "annotations": [i.annotation_id for i in cov]})
        return out

    def coverage(self) -> dict:
        """Verified applicable characteristics / identified applicable characteristics. The denominator and exclusions stay visible; the value
        is None when nothing was identified (unknown is not 100 %)."""
        applicable = [i for i in self.items if i.status != "not_applicable"]
        covered = [i for i in applicable if i.status == "covered"]
        by: dict[str, int] = {}
        for i in self.items:
            by[i.status] = by.get(i.status, 0) + 1
        return {"covered": len(covered), "applicable": len(applicable), "percent": (100.0 * len(covered) / len(applicable)) if applicable else None,
                "by_status": by, "excluded": [{"id": i.id, "characteristic": i.characteristic, "reason": i.reason} for i in self.items if i.status == "not_applicable"],
                "note": "Diagnostic only: geometric coverage is not manufacturing completeness or approval."}

    def to_json(self) -> dict:
        return {"items": [asdict(i) for i in self.items], "coverage": self.coverage(), "duplicates": self.duplicates()}


# ---------------------------------------------------------------- layout / text-box collisions

@dataclass
class TextBox:
    id: str
    rect: Rect
    kind: str = "dimension"            # dimension | note | label | title
    sheet: int = 1


def box_collisions(boxes: list[TextBox], clearance: float = CLEARANCE_MIN_M, keep_out: Optional[list[Rect]] = None,
                   usable: Optional[Rect] = None) -> list[dict]:
    """Hard failures: text overlapping text (or closer than ``clearance``), text inside a keep-out region (title block), text outside the sheet."""
    out = []
    by_sheet: dict[int, list[TextBox]] = {}
    for b in boxes:
        by_sheet.setdefault(b.sheet, []).append(b)
    for sheet, bs in by_sheet.items():
        for a, b in itertools.combinations(bs, 2):
            if a.rect.grow(clearance / 2).overlaps(b.rect.grow(clearance / 2)):
                out.append({"kind": "text_overlap" if a.rect.overlaps(b.rect) else "text_too_close", "sheet": sheet, "a": a.id, "b": b.id})
        for b in bs:
            if usable is not None and not b.rect.inside(usable):
                out.append({"kind": "outside_sheet", "sheet": sheet, "a": b.id})
            for k in keep_out or []:
                if b.rect.overlaps(k):
                    out.append({"kind": "title_block_collision", "sheet": sheet, "a": b.id})
    return out


# ---------------------------------------------------------------- PDF checks

def _is_black(rgb) -> bool:
    if rgb is None:
        return True
    if isinstance(rgb, int):
        return rgb == 0
    return all(c <= BLACK_TOL for c in rgb[:3])


def pdf_checks(pdf: Path, expected_sheets: int, preview_dir: Optional[Path] = None, dpi: int = 130) -> dict:
    """Vector-PDF facts: page count, non-black text/strokes, text overlaps, clipping, and a raster of every page for visual review.
    Anti-aliased grey pixels in the raster are expected; colour is judged on the vector data."""
    import fitz
    res: dict = {"exists": Path(pdf).is_file(), "pages": 0, "expected_pages": expected_sheets, "nonblack_text": [], "nonblack_strokes": 0, "color_fills": 0,
                 "text_overlaps": [], "text_clipped": [], "previews": [], "vector": True, "errors": []}
    if not res["exists"]:
        res["errors"].append("PDF not found")
        return res
    try:
        doc = fitz.open(str(pdf))
    except Exception as e:      # noqa: BLE001
        res["errors"].append(f"PDF unreadable: {e}")
        return res
    res["pages"] = doc.page_count
    for pno, page in enumerate(doc, start=1):
        page_rect = page.rect
        spans = []
        for blk in page.get_text("dict")["blocks"]:
            for line in blk.get("lines", []):
                for sp in line.get("spans", []):
                    if not sp["text"].strip():
                        continue
                    if not _is_black(sp["color"]):
                        res["nonblack_text"].append({"page": pno, "text": sp["text"][:40], "color": sp["color"]})
                    r = fitz.Rect(sp["bbox"])
                    if not page_rect.contains(r):
                        res["text_clipped"].append({"page": pno, "text": sp["text"][:40]})
                    spans.append((sp["text"], r))
        for (t1, r1), (t2, r2) in itertools.combinations(spans, 2):
            inter = r1 & r2
            if (t1.upper().startswith("SCALE") or t2.upper().startswith("SCALE")) and inter.get_area() < 0.6 * min(r1.get_area(), r2.get_area()):
                continue          # a view title stacked over its "SCALE 1:2" line is one SOLIDWORKS label whose font boxes touch; real overlaps are measured by reverse.layout
            if not inter.is_empty and inter.get_area() > 0.25 * min(r1.get_area(), r2.get_area()) and t1 != t2:
                res["text_overlaps"].append({"page": pno, "a": t1[:30], "b": t2[:30]})
        try:
            for d in page.get_drawings():
                if d.get("color") is not None and not _is_black(d["color"]):
                    res["nonblack_strokes"] += 1
                if d.get("fill") is not None and not _is_black(d["fill"]) and d["fill"] != (1.0, 1.0, 1.0):
                    res["color_fills"] += 1
        except Exception as e:      # noqa: BLE001
            res["errors"].append(f"drawings: {e}")
        if not page.get_text("text").strip() and not page.get_drawings():
            res["errors"].append(f"page {pno} is empty")
        if preview_dir is not None:
            preview_dir = Path(preview_dir)
            preview_dir.mkdir(parents=True, exist_ok=True)
            out = preview_dir / f"page-{pno:03d}.png"
            page.get_pixmap(dpi=dpi, alpha=False).save(str(out))
            res["previews"].append(out.name)
    res["vector"] = any(True for _ in range(1)) and (doc.page_count > 0 and bool(doc[0].get_text("text").strip() or doc[0].get_drawings()))
    res["ok"] = (res["pages"] == expected_sheets and not res["nonblack_text"] and res["nonblack_strokes"] == 0 and not res["text_overlaps"]
                 and not res["text_clipped"] and not res["errors"])
    doc.close()
    return res
