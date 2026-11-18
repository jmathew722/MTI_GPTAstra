"""Parse a drawing's hole/thread callout into normalized intent fields (Stage 4).

Layered and rule-based, with no model call. Every extracted field keeps its source span (an index into
``ParsedCallout.raw``, the symbol-normalized text), the rule that produced it and a confidence. What the text
does not say stays unsaid: an unlabeled single depth on a threaded hole is *ambiguous* between thread and drill
depth (never copied to both), an unspecified slot length scheme is flagged, and a pipe thread's standard is never
inferred from its diameter. Text that is not a hole callout yields ``family = None``.

Layers: symbol normalization -> counterbore/countersink segments -> quantity -> thread -> labeled depths -> slot
-> diameter -> end condition/depth -> fit/tolerance/datum/sides -> family and ambiguities.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Optional

NUM = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d*\.\d+|\d+)"
_DIA_SYMBOLS = "Øø⌀∅Φφ"
_SYMBOLS = {"⌴": " CBORE ", "⌵": " CSK ", "↧": " DEPTH ", "×": "X"}


def _num(s: str) -> float:
    s = s.strip()
    m = re.fullmatch(r"(\d+)\s+(\d+)/(\d+)", s)
    if m:
        return int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    m = re.fullmatch(r"(\d+)/(\d+)", s)
    if m:
        return int(m.group(1)) / int(m.group(2))
    return float(s)


@dataclass
class Field:
    value: Any
    span: tuple
    rule: str
    confidence: float

    def to_dict(self) -> dict:
        return {"value": self.value, "span": list(self.span), "rule": self.rule, "confidence": self.confidence}


@dataclass
class ParsedCallout:
    raw: str
    original: str = ""
    family: Optional[str] = None
    quantity: Optional[Field] = None
    diameter: Optional[Field] = None
    end: Optional[Field] = None
    depth: Optional[Field] = None
    thread_depth: Optional[Field] = None
    drill_depth: Optional[Field] = None
    cbore_diameter: Optional[Field] = None
    cbore_depth: Optional[Field] = None
    csink_diameter: Optional[Field] = None
    csink_angle: Optional[Field] = None
    slot_width: Optional[Field] = None
    slot_length: Optional[Field] = None
    slot_scheme: Optional[Field] = None
    fit: Optional[Field] = None
    tolerance: Optional[Field] = None
    datum: Optional[Field] = None
    thread: Optional[dict] = None
    sides: list = field(default_factory=list)
    ambiguities: list = field(default_factory=list)
    confidence: float = 0.0

    _FIELDS = ("quantity", "diameter", "end", "depth", "thread_depth", "drill_depth", "cbore_diameter", "cbore_depth",
               "csink_diameter", "csink_angle", "slot_width", "slot_length", "slot_scheme", "fit", "tolerance", "datum")

    def to_dict(self) -> dict:
        d = {"raw": self.raw, "family": self.family, "thread": self.thread, "sides": list(self.sides),
             "ambiguities": list(self.ambiguities), "confidence": self.confidence}
        for k in self._FIELDS:
            f = getattr(self, k)
            d[k] = f.to_dict() if f else None
        return d


def _normalize(text: str) -> str:
    t = unicodedata.normalize("NFC", str(text or ""))
    for ch in _DIA_SYMBOLS:
        t = t.replace(ch, "Ø")
    for k, v in _SYMBOLS.items():
        t = t.replace(k, v)
    return re.sub(r"[ \t]+", " ", t).strip()


def parse(text: str) -> ParsedCallout:
    t = _normalize(text)
    r = ParsedCallout(raw=t, original=str(text or ""))
    if not t:
        return r
    mask = list(t)

    def view() -> str:
        return "".join(mask)

    def eat(a: int, b: int) -> None:
        # Consumed text becomes \x01, not a space: a space would let ``\s*`` in a later pattern bridge across the
        # gap and attach a number to a label it never belonged to (".201" + masked drill depth + "THD").
        for i in range(a, b):
            mask[i] = "\x01"

    def find(pat: str, flags=re.I):
        return re.search(pat, view(), flags)

    def F(m, g: int, rule: str, conf: float, conv=_num) -> Field:
        return Field(conv(m.group(g)), m.span(g), rule, conf)

    # -- counterbore / countersink segments (masked so their numbers never become the main bore) --------------
    m = find(rf"(?:CBORE|C'BORE|COUNTERBORE)\s*(?:Ø\s*)?({NUM})(?:\s*(?:X|,)\s*({NUM})\s*(?:DEEP|DP|DEPTH)?)?")
    if m:
        r.cbore_diameter = F(m, 1, "cbore_segment", 0.93)
        if m.group(2):
            r.cbore_depth = F(m, 2, "cbore_segment", 0.93)
        eat(*m.span())
    m = find(rf"(?:CSK|CSINK|C'SINK|COUNTERSINK)\s*(?:Ø\s*)?(?:({NUM})\s*)?(?:X|,)?\s*(\d{{2,3}}(?:\.\d+)?)\s*°")
    if m:
        if m.group(1):
            r.csink_diameter = F(m, 1, "csink_segment", 0.93)
        r.csink_angle = F(m, 2, "csink_segment", 0.95)
        eat(*m.span())

    # -- quantity ---------------------------------------------------------------------------------------------
    # "2X Ø.25" is a quantity; "6 X 20 SLOT" is a width times a length. A number after "NX" only counts as a
    # quantity when the callout is not a slot.
    nx = r"^\s*(\d+)\s*X(?!\s*[\d.])" if re.search(r"\bSLOT\b", t, re.I) else r"^\s*(\d+)\s*X\b"
    for pat, rule in ((nx, "quantity_nx"), (r"\((\d+)\)", "quantity_parens"),
                      (r"(\d+)\s*(?:PLCS|PLC|PLACES|PLACE|HOLES|HLS)\b", "quantity_places")):
        m = find(pat)
        if m:
            r.quantity = F(m, 1, rule, 0.95, int)
            eat(*m.span())
            break

    # -- thread ------------------------------------------------------------------------------------------------
    th = None
    m = find(rf"({NUM})\s*(?:-\s*(\d+))?\s*(NPTF|NPT|BSPT|BSPP)\b")
    if m:
        th = {"kind": "pipe", "system": "inch" if m.group(3).upper().startswith("NPT") else "metric", "size": re.sub(r"\s+", "", m.group(1)),
              "tpi": int(m.group(2)) if m.group(2) else None, "standard": m.group(3).upper(), "series": None, "class": None,
              "designation": m.group(0).strip(), "span": list(m.span())}
        eat(*m.span())
    if th is None:
        m = find(r"\bR([CP])\s*(\d+/\d+|\d+)\b")
        if m:
            th = {"kind": "pipe", "system": "metric", "size": m.group(2), "tpi": None, "standard": "R" + m.group(1).lower(),
                  "series": None, "class": None, "designation": m.group(0).strip(), "span": list(m.span())}
            eat(*m.span())
    if th is None:
        m = find(r"(\d+/\d+|\d+)?\s*PIPE\s*TAP\b")
        if m:
            th = {"kind": "pipe", "system": None, "size": (m.group(1) or None), "tpi": None, "standard": None, "series": None,
                  "class": None, "designation": m.group(0).strip(), "span": list(m.span())}
            r.ambiguities.append("pipe_standard_unspecified")
            eat(*m.span())
    if th is None:
        m = find(rf"\bM(\d+(?:\.\d+)?)(?:\s*X\s*({NUM}))?")
        if m:
            th = {"kind": "straight", "system": "metric", "size": "M" + m.group(1), "pitch": _num(m.group(2)) if m.group(2) else None,
                  "series": None, "class": None, "designation": m.group(0).strip(), "span": list(m.span())}
            if th["pitch"] is None:
                r.ambiguities.append("metric_pitch_unspecified")
            eat(*m.span())
            cm = find(r"\b([4-9][HG])\b")
            if cm:
                th["class"] = cm.group(1).upper()
                eat(*cm.span())
    if th is None:
        m = find(r"(#\d+|\d+/\d+)\s*-\s*(\d+)\s*(UNC|UNF|UNEF|NC|NF)?(?:\s*-\s*([123][AB]))?")
        if m:
            th = {"kind": "straight", "system": "inch", "size": m.group(1), "tpi": int(m.group(2)), "series": (m.group(3) or "").upper() or None,
                  "class": (m.group(4) or "").upper() or None, "designation": m.group(0).strip(), "span": list(m.span())}
            eat(*m.span())
    r.thread = th

    # -- labeled depths: a number labeled THD or DRILL is never the same number as the other ---------------------
    # Drill first: in "DRILL .75 DEEP THD .50 DEEP" the .75 belongs to DRILL, and the THD pattern that accepts
    # a number *before* the label ("NUM DEEP THD") would otherwise steal it.
    m = find(rf"\bDRILL(?:\s*DEPTH)?\s*({NUM})(?:\s*(?:DEEP|DP))?")
    if m:
        r.drill_depth = F(m, 1, "labeled_drill_depth", 0.95)
        eat(*m.span())
    m = find(rf"\bTHD(?:\s*DEPTH)?\s*({NUM})(?:\s*(?:DEEP|DP))?|({NUM})\s*(?:DEEP\s*)?THD\b")
    if m:
        g = 1 if m.group(1) else 2
        r.thread_depth = F(m, g, "labeled_thread_depth", 0.95)
        eat(*m.span())

    # -- slot --------------------------------------------------------------------------------------------------
    sm = find(rf"({NUM})\s*X\s*({NUM})\s*(OVERALL\s*)?SLOT\b")
    if sm:
        r.slot_width, r.slot_length = F(sm, 1, "slot_w_x_l", 0.93), F(sm, 2, "slot_w_x_l", 0.93)
        if sm.group(3):
            r.slot_scheme = Field("overall", sm.span(3), "slot_overall_word", 0.95)
        eat(*sm.span())
    else:
        sm = find(rf"Ø\s*({NUM})\s*SLOT\s*({NUM})")
        if sm:
            r.slot_width, r.slot_length = F(sm, 1, "slot_dia_length", 0.9), F(sm, 2, "slot_dia_length", 0.9)
            eat(*sm.span())
    if r.slot_width:
        scheme = find(r"\bC[-/ ]?C\b|\bCTR\b|\bCENTER[- ]TO[- ]CENTER\b")
        if scheme:
            r.slot_scheme = Field("center_to_center", scheme.span(), "slot_cc_word", 0.95)
        elif not r.slot_scheme:
            r.ambiguities.append("slot_length_scheme_unspecified")

    # -- diameter ----------------------------------------------------------------------------------------------
    m = find(rf"Ø\s*({NUM})")
    if m:
        r.diameter = Field(_num(m.group(1)), m.span(), "diameter_symbol", 0.95)     # span covers symbol + number
        eat(*m.span())
    if r.diameter is None:
        # Many drawings write the symbol after the number: ".188 Ø", ".281 Ø-B" (found by the corpus inventory).
        m = find(rf"(?<![\d./])({NUM})\s*Ø")
        if m:
            r.diameter = Field(_num(m.group(1)), m.span(), "diameter_symbol_trailing", 0.9)
            eat(*m.span())
    if r.diameter is None:
        m = find(rf"({NUM})\s*DIA(?:M|METER)?\b")
        if m:
            r.diameter = Field(_num(m.group(1)), m.span(), "dia_word", 0.9)
            eat(*m.span())
    if r.diameter is None:
        m = find(r"(?<![A-Za-z0-9.])O\s*(\.\d+)")
        if m and (r.thread is None):
            r.diameter = Field(_num(m.group(1)), m.span(), "ocr_diameter_symbol", 0.6)       # an OCR 'O' for the diameter symbol: lower confidence
            eat(*m.span())

    # -- end condition and plain depth -------------------------------------------------------------------------
    tm = find(r"\bTHRU(?:\s*ALL)?\b|\bTHROUGH\b")
    if tm:
        r.end = Field("through", tm.span(), "thru_word", 0.97)
        eat(*tm.span())
    dm = find(rf"({NUM})\s*(?:DEEP|DP)\b") or find(rf"\bDEPTH\s*({NUM})")
    if dm:
        r.depth = F(dm, 1, "depth_word", 0.93)
        eat(*dm.span())
    if r.end is None and (r.depth or r.thread_depth or r.drill_depth):
        d = r.depth or r.drill_depth or r.thread_depth
        r.end = Field("blind", d.span, "implied_by_depth", 0.85)
    if r.thread and r.depth and not (r.thread_depth or r.drill_depth):
        r.ambiguities.append("depth_applies_to_thread_or_drill")      # one number, two possible meanings: never copied to both

    # -- fit, tolerance, datum, sides (case-sensitive fits: H7, not 'h7' in running text) -------------------------
    fm = re.search(r"\b((?:[HGFEDKNP]|JS)\d{1,2})(?:/([a-z]{1,2}\d{1,2}))?\b", t)
    if fm and not (r.thread and fm.start() >= r.thread["span"][0] and fm.end() <= r.thread["span"][1]):
        r.fit = Field(fm.group(0), fm.span(), "iso_fit", 0.9)
    else:
        pm = find(r"\b(PRESS|SLIP|LOCATIONAL|RUNNING|SLIDING)\s+FIT\b")
        if pm:
            r.fit = Field(pm.group(0).upper(), pm.span(), "fit_word", 0.9)
    tl = find(rf"±\s*({NUM})")
    if tl:
        r.tolerance = F(tl, 1, "plus_minus", 0.93)
    dt = re.search(r"\bDATUM\s+([A-Z])\b", t)
    if dt:
        r.datum = Field(dt.group(1), dt.span(1), "datum_word", 0.9)
    sides = set()
    if re.search(r"\bBOTH\s+SIDES\b", t, re.I):
        sides |= {"near", "far"}
    if re.search(r"\bNEAR\s+SIDE\b", t, re.I):
        sides.add("near")
    if re.search(r"\bFAR\s+SIDE\b|\bOPP(?:OSITE)?\s+SIDE\b", t, re.I):
        sides.add("far")
    r.sides = sorted(sides)
    if (re.search(r"\bNEAR\s+SIDE\b", t, re.I) and re.search(r"\bFAR\s+SIDE\b", t, re.I)
            and len(re.findall(rf"Ø\s*{NUM}", t)) >= 2 and not (r.cbore_diameter or r.csink_angle)):
        r.ambiguities.append("advanced_hole_candidate")                 # separate near/far elements: not a basic Hole Wizard hole

    # -- family ------------------------------------------------------------------------------------------------
    if r.slot_width:
        r.family = "counterbore_slot" if r.cbore_diameter else "countersink_slot" if (r.csink_angle or r.csink_diameter) else "slot"
    elif r.thread:
        r.family = "pipe_tap" if r.thread["kind"] == "pipe" else "straight_tap"
    elif r.cbore_diameter:
        r.family = "counterbore"
    elif r.csink_angle or r.csink_diameter:
        r.family = "countersink"
    elif r.diameter or r.end or r.depth:
        r.family = "hole"
    confs = [f.confidence for k in ParsedCallout._FIELDS for f in [getattr(r, k)] if f]
    r.confidence = round(sum(confs) / len(confs), 3) if (confs and r.family) else 0.0
    if r.family is None:
        r.quantity = r.fit = r.tolerance = r.datum = None
    return r
