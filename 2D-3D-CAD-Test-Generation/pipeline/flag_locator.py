"""Automatic, page-aware placement of a finding's drawing callout (Stage 3).

No human positions anything. For a source callout the locator tries, in order:

1. exact normalized token sequence on a page's text (text layer or OCR);
2. punctuation/unit/diameter-symbol-insensitive match;
3. constrained fuzzy match: similar text AND strict numeric agreement AND the same thread-class words;
4. a *small* region recorded during extraction (a large region is only "likely", never a box);
5. view-level only (page / view named, no box);
6. an honest "no match".

Every result carries the page index, a rectangle in the **unrotated** page (normalized, top-left origin),
the page rotation, the method, a confidence and the attempts made. A precise box needs confidence at or
above ``BOX_THRESHOLD``; below it (or when several equally good matches remain) the finding is returned
*unlocated* with the likely page/view. A wrong box is worse than no box.

``BOX_THRESHOLD`` is calibrated against labeled fixtures (tests/test_flag_locator.py): it sits at or
below the weakest correct match and above every near-miss.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

BOX_THRESHOLD = 0.70
_BASE = {"exact_tokens": 0.97, "normalized": 0.90}
_FUZZY_MIN_RATIO = 0.80
_TIE = 0.02
_DIA = "ØøΦφ⌀∅"
_UNIT_WORDS = re.compile(r"\b(?:IN|INCH|INCHES|MM|TYP|PLCS|PLC|PLACES)\b")
_THREAD_WORDS = {"UNC", "UNF", "UNEF", "NPT", "NPTF", "BSPT", "BSPP", "NC", "NF"}
_NUM = re.compile(r"\d*\.\d+|\d+")
_FRACTION = re.compile(r"\d+\s*/\s*\d+")


@dataclass
class Box:
    text: str
    rect: list           # [x0, y0, x1, y1] in the DISPLAYED page, points
    conf: float = 1.0


@dataclass
class PageData:
    index: int
    width: float         # displayed page size, points
    height: float
    rotation: int = 0    # page /Rotate, degrees clockwise (0, 90, 180, 270)
    source: str = "text_layer"     # "text_layer" | "ocr"
    boxes: list = field(default_factory=list)


@dataclass
class Placement:
    located: bool
    callout: str
    page_index: Optional[int] = None
    rect_normalized: Optional[dict] = None
    rotation_degrees: int = 0
    method: str = "none"
    confidence: float = 0.0
    matched_text: str = ""
    reason: str = ""                       # when not located: no_match | ambiguous | region_too_coarse | view_level
    candidates: int = 0
    likely_page: Optional[int] = None
    likely_view: Optional[str] = None
    likely_region: Optional[dict] = None
    attempts: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


# --------------------------------------------------------------------------- #
# Geometry
# --------------------------------------------------------------------------- #
def normalize_rect(rect: list, disp_w: float, disp_h: float, rotation: int) -> dict:
    """A rectangle in the displayed page -> normalized {x, y, width, height} in the UNROTATED page
    (top-left origin). ``rotation`` is the page's clockwise /Rotate."""
    rotation = rotation % 360
    if rotation not in (0, 90, 180, 270):
        raise ValueError("rotation must be a multiple of 90")
    x0, y0, x1, y1 = rect
    pts = []
    for xd, yd in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        if rotation == 0:
            xu, yu = xd, yd
        elif rotation == 90:
            xu, yu = yd, disp_w - xd
        elif rotation == 180:
            xu, yu = disp_w - xd, disp_h - yd
        else:
            xu, yu = disp_h - yd, xd
        pts.append((xu, yu))
    Wu, Hu = (disp_h, disp_w) if rotation in (90, 270) else (disp_w, disp_h)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    nx0, ny0 = max(0.0, min(xs) / Wu), max(0.0, min(ys) / Hu)
    nx1, ny1 = min(1.0, max(xs) / Wu), min(1.0, max(ys) / Hu)
    return {"x": nx0, "y": ny0, "width": max(0.0, nx1 - nx0), "height": max(0.0, ny1 - ny0)}


def _inside(inner: dict, outer: dict, slack: float = 1e-6) -> bool:
    return (inner["x"] >= outer["x"] - slack and inner["y"] >= outer["y"] - slack and
            inner["x"] + inner["width"] <= outer["x"] + outer["width"] + slack and
            inner["y"] + inner["height"] <= outer["y"] + outer["height"] + slack)


def _center_in(r: dict, region: dict) -> bool:
    cx, cy = r["x"] + r["width"] / 2, r["y"] + r["height"] / 2
    return region["x"] <= cx <= region["x"] + region["width"] and region["y"] <= cy <= region["y"] + region["height"]


# --------------------------------------------------------------------------- #
# Text normalization (the OCR-tolerant, number-strict part)
# --------------------------------------------------------------------------- #
def _prep(text: str) -> str:
    t = unicodedata.normalize("NFKC", str(text)).upper().replace("×", "X")
    for ch in _DIA:
        t = t.replace(ch.upper(), "").replace(ch, "")
    t = re.sub(r"(?<=[\d.])O|O(?=[\d.])", "0", t)         # OCR reads the letter O (or a diameter symbol) as zero
    return _UNIT_WORDS.sub(" ", t)


def _canon(tok: str) -> str:
    try:
        d = Decimal(tok)
    except InvalidOperation:
        return tok
    return format(d.normalize(), "f") if d != d.to_integral() else str(int(d))


def _numbers(text: str) -> Counter:
    t = _prep(text)
    out: list[str] = []
    for fr in _FRACTION.findall(t):
        out.append(re.sub(r"\s+", "", fr))
    t = _FRACTION.sub(" ", t)
    out += [_canon(n) for n in _NUM.findall(t)]
    return Counter(out)


def _squash(text: str) -> str:
    t = _prep(text)
    t = _NUM.sub(lambda m: _canon(m.group()), t)
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", "", t)
    return re.sub(r"[^A-Z0-9./]", "", t)


def _thread_words(text: str) -> set:
    return set(re.findall(r"[A-Z]+", _prep(text))) & _THREAD_WORDS


def _tokens(text: str) -> list:
    return unicodedata.normalize("NFKC", str(text)).upper().split()


def _contains_seq(hay: list, needle: list) -> bool:
    n = len(needle)
    return n > 0 and any(hay[i:i + n] == needle for i in range(len(hay) - n + 1))


def _subset(a: Counter, b: Counter) -> bool:
    return all(b[k] >= v for k, v in a.items())


# --------------------------------------------------------------------------- #
# Candidates
# --------------------------------------------------------------------------- #
@dataclass
class _Span:
    page: PageData
    text: str
    rect: list
    conf: float
    nrect: dict


def _spans(page: PageData) -> list:
    """Single boxes plus vertically adjacent pairs (a callout often wraps onto a second line)."""
    items = [b for b in page.boxes if str(b.text).strip()]
    out = [_Span(page, b.text, list(b.rect), b.conf, normalize_rect(b.rect, page.width, page.height, page.rotation)) for b in items]
    ordered = sorted(items, key=lambda b: (b.rect[1], b.rect[0]))
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:i + 6]:
            h = max(a.rect[3] - a.rect[1], b.rect[3] - b.rect[1])
            gap = b.rect[1] - a.rect[3]
            if gap > 0.8 * h or gap < -0.5 * h:
                continue
            w = max(a.rect[2] - a.rect[0], b.rect[2] - b.rect[0])
            if abs(a.rect[0] - b.rect[0]) > 0.5 * w:
                continue
            r = [min(a.rect[0], b.rect[0]), min(a.rect[1], b.rect[1]), max(a.rect[2], b.rect[2]), max(a.rect[3], b.rect[3])]
            out.append(_Span(page, f"{a.text} {b.text}", r, min(a.conf, b.conf),
                             normalize_rect(r, page.width, page.height, page.rotation)))
    return out


def _confidence(base: float, ocr_conf: float) -> float:
    return round(base * (0.85 + 0.15 * max(0.0, min(1.0, ocr_conf))), 4)


def _match(strategy: str, callout: str, span: _Span) -> Optional[float]:
    """Score 0..1 when ``span`` matches ``callout`` under ``strategy``, else None."""
    if strategy == "exact_tokens":
        return 1.0 if _contains_seq(_tokens(span.text), _tokens(callout)) else None
    want, got = _squash(callout), _squash(span.text)
    if not want or not got:
        return None
    nc, ns = _numbers(callout), _numbers(span.text)
    if not _subset(nc, ns) or not _thread_words(callout) <= _thread_words(span.text):
        return None                                           # strict numeric / thread agreement, always
    if strategy == "normalized":
        if got == want and len(want) >= 2:
            return 1.0
        return 1.0 if len(want) >= 4 and want in got else None
    ratio = difflib.SequenceMatcher(None, want, got).ratio()  # fuzzy
    return ratio if ratio >= _FUZZY_MIN_RATIO and len(want) >= 4 else None


def _resolve(matches: list, strategy: str, hint_page, hint_region) -> tuple:
    """(span, score) of the unique winner, or (None, candidates, likely_page) when it stays ambiguous."""
    matches = sorted(matches, key=lambda m: -m[1])
    top = [m for m in matches if m[1] >= matches[0][1] - _TIE]
    if len(top) > 1 and hint_page is not None:
        on = [m for m in top if m[0].page.index == hint_page]
        top = on or top
    if len(top) > 1 and hint_region is not None:
        inside = [m for m in top if _center_in(m[0].nrect, hint_region)]
        top = inside or top
    if len(top) > 1:        # one box lying inside every other: the tightest evidence wins
        for cand in top:
            if all(o is cand or (o[0].page.index == cand[0].page.index and _inside(cand[0].nrect, o[0].nrect)) for o in top):
                top = [cand]
                break
    if len(top) == 1:
        return top[0][0], top[0][1], 1, top[0][0].page.index
    return None, 0.0, len(top), top[0][0].page.index


def locate_callout(callout: str, pages: list, *, hint_page: Optional[int] = None, hint_region: Optional[dict] = None,
                   hint_view: Optional[str] = None) -> Placement:
    """Place ``callout`` on the drawing. Never raises on a miss; the result says why it did not locate."""
    attempts: list = []
    spans = [s for p in pages for s in _spans(p)]
    for strategy in ("exact_tokens", "normalized", "fuzzy"):
        matches = [(s, sc) for s in spans for sc in [_match(strategy, callout, s)] if sc is not None]
        attempts.append({"strategy": strategy, "candidates": len(matches)})
        if not matches:
            continue
        span, score, n, likely = _resolve(matches, strategy, hint_page, hint_region)
        if span is None:
            return Placement(False, callout, method=strategy, reason="ambiguous", candidates=n, likely_page=likely, attempts=attempts)
        base = _BASE.get(strategy) or round(0.60 + 0.25 * score, 4)
        conf = _confidence(base, span.conf)
        if conf < BOX_THRESHOLD:
            return Placement(False, callout, method=strategy, reason="low_confidence", confidence=conf, candidates=1,
                             likely_page=span.page.index, attempts=attempts)
        return Placement(True, callout, page_index=span.page.index, rect_normalized=span.nrect, rotation_degrees=span.page.rotation % 360,
                         method=strategy, confidence=conf, matched_text=span.text, candidates=1, likely_page=span.page.index,
                         attempts=attempts)
    # No text evidence at all: weaker, honest fallbacks.
    if hint_region is not None and hint_page is not None:
        area = max(0.0, hint_region["width"]) * max(0.0, hint_region["height"])
        conf = round(0.80 - min(0.5, area * 5.0), 4)
        attempts.append({"strategy": "extraction_region", "area_fraction": round(area, 5), "confidence": conf})
        page = next((p for p in pages if p.index == hint_page), None)
        if conf >= BOX_THRESHOLD:
            return Placement(True, callout, page_index=hint_page, rect_normalized=dict(hint_region),
                             rotation_degrees=(page.rotation % 360) if page else 0, method="extraction_region",
                             confidence=conf, likely_page=hint_page, attempts=attempts)
        return Placement(False, callout, reason="region_too_coarse", confidence=conf, likely_page=hint_page,
                         likely_region=dict(hint_region), likely_view=hint_view, attempts=attempts)
    if hint_view is not None and hint_page is not None:
        attempts.append({"strategy": "view_level", "view": hint_view})
        return Placement(False, callout, reason="view_level", likely_page=hint_page, likely_view=hint_view, attempts=attempts)
    return Placement(False, callout, reason="no_match", attempts=attempts)
