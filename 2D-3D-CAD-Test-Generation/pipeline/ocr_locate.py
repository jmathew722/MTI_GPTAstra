"""Find drawing callouts on a scanned sheet (no text layer) with RapidOCR, for markups.

OCR on old scans is close but not exact: ".377" reads "377", ".188 R" reads "R~", "ALL RADII"
reads "ALL RADH". Matching is therefore fuzzy: a callout matches an OCR box by the digits of its
main number, or by keyword similarity. A number that appears several times on the sheet (".188")
is resolved by distance to the callouts that are unique. OCR runs once per drawing and is cached
as ocr.json next to the part. No API cost; rapidocr-onnxruntime runs locally.
"""
from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

OCR_DPI = 150
_NUM = re.compile(r"\d*\.\d+|\d+")


def _norm(t: str) -> str:
    t = t.upper()
    t = re.sub(r"(?<=[\d.])O|O(?=[\d.])", "0", t)        # O next to digits is a zero
    return re.sub(r"[^A-Z0-9.]", "", t)


def ocr_boxes(pdf: Path, cache: Path) -> list[dict]:
    """[{text, conf, rect: [x0, y0, x1, y1] in PDF points}] for page 1, cached."""
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    import numpy as np
    import pymupdf as fitz
    from rapidocr_onnxruntime import RapidOCR
    pix = fitz.open(pdf)[0].get_pixmap(dpi=OCR_DPI)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
    res, _ = RapidOCR()(img)
    s = 72 / OCR_DPI
    out = [{"text": t, "conf": round(float(c), 3),
            "rect": [round(min(p[0] for p in b) * s, 1), round(min(p[1] for p in b) * s, 1),
                     round(max(p[0] for p in b) * s, 1), round(max(p[1] for p in b) * s, 1)]}
           for b, t, c in (res or [])]
    cache.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def _number_match(num: str, ocr_text: str) -> bool:
    """The callout's number appears in the OCR text: the same value (".377" = "0.377"), or the
    same digits with only the decimal point lost (".377" read "377"). "7.50" is not ".75"."""
    want = float(num)
    key = num.replace(".", "").lstrip("0")
    for tok in _NUM.findall(ocr_text):
        if "." in tok and abs(float(tok) - want) < 1e-9:
            return True
        if "." not in tok and len(key) >= 2 and tok.lstrip("0") == key:
            return True
    return False


def _candidates(callout: str, boxes: list[dict]) -> list[dict]:
    nums = [n for n in _NUM.findall(callout) if any(ch.isdigit() for ch in n)]
    words = [w for w in re.findall(r"[A-Z]{4,}", callout.upper()) if w not in ("UNLESS", "OTHERWISE", "SPECIFIED")]
    radius = bool(nums) and bool(re.search(r"\d\s*R\.?\s*$", callout.upper()))
    hits = []
    for b in boxes:
        nt = _norm(b["text"])
        if nums and _number_match(nums[0], nt):
            hits.append((2.0 + ("R" in nt) * ("R" in callout.upper()), b))
            continue
        if radius and len(nt) <= 3 and "R" in nt:          # ".188 R" read as "R~": the R alone
            hits.append((1.0, b))
            continue
        if words:
            best = max(difflib.SequenceMatcher(None, w, nt).find_longest_match(0, len(w), 0, len(nt)).size / len(w)
                       for w in words)
            if best >= 0.6:                                 # "ALL RADII" reads "ALL RADH"
                hits.append((best, b))
    hits.sort(key=lambda h: -h[0])
    return [b for _, b in hits]


def locate(callouts: list[str], boxes: list[dict]) -> dict[str, list[float]]:
    """{callout: rect} for the callouts found. Unique matches anchor the ambiguous ones."""
    cands = {c: _candidates(c, boxes) for c in callouts}
    found = {c: v[0]["rect"] for c, v in cands.items() if len(v) == 1}
    anchors = list(found.values())
    for c, v in cands.items():
        v = [b for b in v if b["rect"] not in found.values()]   # one box per callout
        if c in found or not v:
            continue
        if anchors:
            cx = sum((r[0] + r[2]) / 2 for r in anchors) / len(anchors)
            cy = sum((r[1] + r[3]) / 2 for r in anchors) / len(anchors)
            v = sorted(v, key=lambda b: ((b["rect"][0] + b["rect"][2]) / 2 - cx) ** 2 + ((b["rect"][1] + b["rect"][3]) / 2 - cy) ** 2)
        found[c] = v[0]["rect"]
    return found
