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


# Pipe/straight thread helpers ---------------------------------------------------------------------------------------
_DECIMAL_FRACTIONS = {0.0625: "1/16", 0.125: "1/8", 0.1875: "3/16", 0.25: "1/4", 0.3125: "5/16", 0.375: "3/8", 0.4375: "7/16",
                      0.5: "1/2", 0.5625: "9/16", 0.625: "5/8", 0.75: "3/4", 0.875: "7/8", 1.0: "1", 1.25: "1 1/4", 1.5: "1 1/2",
                      2.0: "2"}
# The coarse (UNC) pitch of the common fractional sizes. Used ONLY to propose a series as an inference; a drawing that
# does not write UNC never gets it as an explicit value.
_UNC_TPI = {"1/4": 20, "5/16": 18, "3/8": 16, "7/16": 14, "1/2": 13, "9/16": 12, "5/8": 11, "3/4": 10, "7/8": 9, "1": 8}


def decimal_to_fraction(size: str) -> Optional[str]:
    """'.25' -> '1/4' when the decimal is an exact standard fraction (tolerance 5e-4), else None. Never rounds loosely."""
    try:
        v = _num(size)
    except ValueError:
        return None
    for k, frac in _DECIMAL_FRACTIONS.items():
        if abs(v - k) < 5e-4:
            return frac
    return None


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
    tolerances: list = field(default_factory=list)   # [{field, kind: bilateral|unilateral, plus, minus, span, rule}]
    confidence: float = 0.0

    _FIELDS = ("quantity", "diameter", "end", "depth", "thread_depth", "drill_depth", "cbore_diameter", "cbore_depth",
               "csink_diameter", "csink_angle", "slot_width", "slot_length", "slot_scheme", "fit", "tolerance", "datum")

    def to_dict(self) -> dict:
        d = {"raw": self.raw, "family": self.family, "thread": self.thread, "sides": list(self.sides),
             "ambiguities": list(self.ambiguities), "tolerances": [dict(t) for t in self.tolerances],
             "confidence": self.confidence}
        for k in self._FIELDS:
            f = getattr(self, k)
            d[k] = f.to_dict() if f else None
        return d


def _normalize(text: str) -> str:
    t = unicodedata.normalize("NFC", str(text or ""))
    for ch in "’′´`":
        t = t.replace(ch, "'")
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
    tol = rf"(?:±\s*({NUM})|\+\s*({NUM})\s*/\s*-\s*({NUM}))"        # groups: bilateral | unilateral plus, minus

    def take_tol(m, g0: int, fld: str) -> None:
        """Tolerance groups (g0 = ±, g0+1/g0+2 = +/-) of a match -> r.tolerances (never merged with the generic ± field)."""
        if m.group(g0):
            r.tolerances.append({"field": fld, "kind": "bilateral", "plus": _num(m.group(g0)), "minus": _num(m.group(g0)),
                                 "span": list(m.span(g0)), "rule": "plus_minus"})
        elif m.group(g0 + 1):
            r.tolerances.append({"field": fld, "kind": "unilateral", "plus": _num(m.group(g0 + 1)), "minus": _num(m.group(g0 + 2)),
                                 "span": [m.start(g0 + 1), m.end(g0 + 2)], "rule": "plus_slash_minus"})

    m = find(rf"(?:CBORE|C'BORE|COUNTERBORE)\s*(?:Ø\s*)?({NUM})\s*(?:DIA\.?)?\s*(?:{tol})?"
             rf"(?:\s*(?:X|,|-)\s*({NUM})\s*(?:{tol})?\s*(?:DEEP|DP|DEPTH)?\.?)?")
    if m:
        r.cbore_diameter = F(m, 1, "cbore_segment", 0.93)
        take_tol(m, 2, "counterbore_diameter")
        if m.group(5):
            r.cbore_depth = F(m, 5, "cbore_segment", 0.93)
            take_tol(m, 6, "counterbore_depth")
        eat(*m.span())
    else:    # number first: ".50 C'BORE - .10 DP"
        m = find(rf"(?<![\d./])({NUM})\s*(?:DIA\.?)?\s*(?:CBORE|C'BORE|COUNTERBORE)\s*(?:-|X|,)\s*({NUM})\s*(?:{tol})?\s*(?:DEEP|DP|DEPTH)\.?")
        if m:
            r.cbore_diameter = F(m, 1, "cbore_number_first", 0.9)
            r.cbore_depth = F(m, 2, "cbore_number_first", 0.9)
            take_tol(m, 3, "counterbore_depth")
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
                      (r"(\d+)\s*-?\s*(?:PLCS|PLC|PLACES|PLACE|HOLES|HLS)\b", "quantity_places")):
        m = find(pat)
        if m:
            r.quantity = F(m, 1, rule, 0.95, int)
            eat(*m.span())
            break

    # -- "DRILL .44 - 2.1 DP." / "DRILL .50 DIA. - 1.1 DEEP": a number after DRILL followed by "- depth" is the bore
    #    DIAMETER (a number directly followed by DEEP/DP stays a labeled drill DEPTH, handled below) -----------------
    m = find(rf"\bDRILL\s*(?:Ø\s*)?({NUM})\s*(?:DIA\.?)?\s*-\s*({NUM})\s*(?:DEEP|DP)\b\.?")
    if m:
        r.diameter = F(m, 1, "drill_dia_dash_depth", 0.93)
        r.depth = F(m, 2, "drill_dia_dash_depth", 0.93)
        eat(*m.span())

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
    if th is None:
        # ".50-13 THD." / ".50-13 UNC": a decimal inch size is only a thread when THD/THREAD or a series follows it.
        m = find(rf"(?<![\d./])(\.\d+|\d+\.\d+)\s*-\s*(\d+)\s*(?:(UNC|UNF|UNEF|NC|NF)(?:\s*-\s*([123][AB]))?|((?:THD|THREADS?)\b\.?))")
        if m:
            frac = decimal_to_fraction(m.group(1))
            th = {"kind": "straight", "system": "inch", "size": frac or m.group(1), "size_as_written": m.group(1), "tpi": int(m.group(2)),
                  "series": (m.group(3) or "").upper() or None, "class": (m.group(4) or "").upper() or None,
                  "designation": m.group(0).strip(), "span": list(m.span()), "thd_marker": bool(m.group(5))}
            if frac is None:
                r.ambiguities.append("thread_size_not_a_standard_fraction")
            eat(*m.span())
    if th is not None:
        if th["kind"] == "pipe" and th.get("size") and th["size"][:1] in ".0123456789":
            f = decimal_to_fraction(th["size"]) if "/" not in th["size"] else th["size"]
            if f:
                th["size_normalized"] = f
                th["normalized_designation"] = f"{f} {th['standard']}" if th.get("standard") else f
        if th["kind"] == "straight" and th["system"] == "inch" and not th.get("series") and th.get("tpi") and th.get("size") in _UNC_TPI \
                and _UNC_TPI[th["size"]] == th["tpi"]:
            # arithmetic only: the drawing did not write UNC, so it is a candidate with its rule, never an explicit value
            th["inferred"] = {"series": "UNC", "rule": "coarse_pitch_for_fractional_size", "confidence": 0.7}
        if th["kind"] == "straight" and th["system"] == "inch" and th.get("size"):
            th["normalized_designation"] = f"{th['size']}-{th['tpi']}"
    r.thread = th

    # -- labeled depths: a number labeled THD or DRILL is never the same number as the other ---------------------
    # Drill first: in "DRILL .75 DEEP THD .50 DEEP" the .75 belongs to DRILL, and the THD pattern that accepts
    # a number *before* the label ("NUM DEEP THD") would otherwise steal it.
    m = find(rf"\bDRILL(?:\s*DEPTH)?\s*({NUM})(?:\s*(?:DEEP|DP))?")
    if m:
        r.drill_depth = F(m, 1, "labeled_drill_depth", 0.95)
        eat(*m.span())
    m = find(rf"\bTHD\b\.?(?:\s*DEPTH)?\s*({NUM})(?:\s*(?:DEEP|DP))?|({NUM})\s*(?:DEEP\s*)?THD\b")
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
    if r.thread and r.depth and not (r.thread_depth or r.drill_depth) and r.depth.rule != "drill_dia_dash_depth":
        # "DR & TAP .50-13 THD. / .8 DEEP": the depth directly after the THD marker is the thread depth (explicit order).
        gap = r.raw[r.thread["span"][1]:r.depth.span[0]] if r.thread["span"][1] <= r.depth.span[0] else None
        if r.thread.get("thd_marker") and gap is not None and not re.search(r"[A-Za-z0-9]", gap.replace("\x01", "")):
            r.thread_depth = Field(r.depth.value, r.depth.span, "depth_follows_THD_label", 0.88)
            r.depth = None
        else:
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


# ---- multi-line grouping -------------------------------------------------------------------------------------------
# A drawing prints one callout as several text lines (OCR returns them separately). ``group_lines`` assigns consecutive
# lines to callout groups; ``parse_group`` parses one group and keeps which source line every field came from.
_TERMINAL = re.compile(r"(?:\b\d+\s*-?\s*(?:PLCS|PLC|PLACES|PLACE)\b|\(\d+\)\s*$)", re.I)
_CONTINUATION = re.compile(r"(?:C'?\s?BORE|CBORE|CSK|CSINK|C'SINK|COUNTERBORE|COUNTERSINK|\bTHRU\b|\bTHD\b|\bNPT[F]?\b|\bTAP\b)", re.I)
_BORE_START = re.compile(r"^\s*(?:\d+\s*X\s+)?(?:DRILL\b|DR\s*&|DR\.|[ØøΦφ⌀∅]|\d*\.\d+\s*(?:DIA|Ø)|M\d|#\d|\d+/\d+\s*-\s*\d)", re.I)


def group_lines(lines: list) -> list:
    """Indices of ``lines`` grouped into callouts: a group closes after a PLACES/quantity line, and a new bore-start line
    (DRILL, Ø, ".344 DIA", M6, 1/4-20 ...) opens a new group when the current one already has a bore. Non-callout text between
    callouts is left in its own single-line group (it parses to ``family None``)."""
    groups: list = []
    cur: list = []
    has_bore = False
    closed = False
    for i, ln in enumerate(lines):
        starts = bool(_BORE_START.match(ln)) and not (_CONTINUATION.search(ln) and has_bore and not _BORE_START.match(ln))
        cont_only = bool(_CONTINUATION.search(ln)) and not re.match(r"^\s*(?:DRILL\b|DR\s*&|[ØøΦφ⌀∅]|\d*\.\d+\s*DIA)", ln, re.I)
        looks_hole = starts or cont_only or bool(_TERMINAL.search(ln)) or bool(re.search(r"\d", ln))
        noise_before = bool(cur) and not has_bore and not closed and not any(
            _CONTINUATION.search(lines[k]) or _TERMINAL.search(lines[k]) or re.search(r"\d", lines[k]) for k in cur)
        if cur and (closed or (starts and has_bore and not cont_only) or (noise_before and looks_hole)):
            groups.append(cur)
            cur, has_bore, closed = [], False, False
        cur.append(i)
        if starts:
            has_bore = True
        if _TERMINAL.search(ln):
            closed = True
    if cur:
        groups.append(cur)
    return groups


def parse_group(lines: list) -> ParsedCallout:
    """Parse the lines of one group as a single callout (joined with newlines so spans map back to lines)."""
    return parse("\n".join(lines))


def line_of_span(pc: ParsedCallout, span) -> Optional[int]:
    """Index (within the group) of the source line holding a field's span in ``pc.raw``."""
    if not span:
        return None
    return pc.raw[:int(span[0])].count("\n")
