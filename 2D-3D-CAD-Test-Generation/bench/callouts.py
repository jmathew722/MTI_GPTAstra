"""Parse drafting hole callouts (legacy MTI style) into structured facts.

Depth is a value followed by DP or DEEP; the "C'BORE .38 DP." form gives the counterbore
depth. A count comes from "(3) HLS", "(24) HOLES", "6-HLS", "4 HOLES", "12-HOLES", "4X".
Nominal thread size is in inches. A SPOTFACE is a (shallow) counterbore. In "1.500 DRILL THRU &
1.9685 RM." the reamed step is recorded as the drill callout's ``cbore_d``.

A bare size with no THRU, no depth, no count and no DR/DRILL word ("OVER .5000 DIA.",
"%%C2.750") is a diameter note, not a hole callout: parse returns None.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

NUM = r"(\d*\.\d+|\d+(?:/\d+)?)"
_THREAD_IN = re.compile(r"(#\d+|\d*\.\d+|\d+/\d+|\d+)\s*-\s*(\d+)(?:\s*UN[CF])?\s*TAP")
_THREAD_TAP_FIRST = re.compile(r"TAP\s+(#\d+|\d*\.\d+|\d+/\d+|\d+)\s*-\s*(\d+)\b")
_THREAD_M = re.compile(r"M(\d+(?:\.\d+)?)\s*X\s*(\d+(?:\.\d+)?)")
_COUNT = re.compile(r"\((\d+)\)\s*(?:HLS?|HOLES?)|(\d+)\s*-\s*HLS?|(\d+)\s*-?\s*HOLES?|\b(\d+)\s*X\b")
_DEPTH = re.compile(NUM + r"\s*(?:DP|DEEP)\b")
_DRILL_PRE = re.compile(r"(?:%%C|\u00d8)\s*" + NUM)
_DRILL_POST = re.compile(NUM + r"\s*(?:DR\b|DR\.|DRILL|DIA\.?)")
# "2.504 %%P.002 %%C THRU": a (toleranced) size with a trailing diameter mark, then THRU
_DRILL_MARK_THRU = re.compile(NUM + r"(?:\s*(?:%%P|\u00b1)\s*\d*\.\d+)?\s*(?:%%C|\u00d8)\s*(?=THRU)")
_DRILL_WORD = re.compile(r"\bDR\b|\bDR\.|DRILL")
_CBORE_WORD = r"(?:C'BORE|CBORE|COUNTERBORE|SPOT\s*FACE)"
_CBORE_D = re.compile(NUM + r"\s*(?:%%C|\u00d8)?\s*" + _CBORE_WORD)
_REAM = re.compile(NUM + r"\s*(?:RM\b|REAM)")
_NOT_A_HOLE = ("B.C.", " REF", "TOL", "DETAIL", "SEE ", "SCALE", "WITHIN", "MATERIAL")
_D_MIN, _D_MAX = 0.04, 3.0   # plausible drill diameter, inches
_BC_MARK = r"(?:%%C|\u00d8)?\s*B\.?\s*C\b\.?"
_BC_AFTER = re.compile(NUM + r"\s*" + _BC_MARK)   # "3.000 B.C.", "4.000%%C B.C."
_BC_BEFORE = re.compile(_BC_MARK + r"\s*(?:%%C|\u00d8)?\s*" + NUM)   # "B.C. 2.500"
_SCREW = re.compile(r"FOR\s+(#\d+|\d*\.\d+|\d+/\d+)\s*(?:SOC|S\.?H\.?C\.?S|FLAT|SHCS|CAP)")
_SCREW_NO = {"#0": 0.060, "#1": 0.073, "#2": 0.086, "#3": 0.099, "#4": 0.112, "#5": 0.125,
             "#6": 0.138, "#8": 0.164, "#10": 0.190, "#12": 0.216}


def _num(s: str) -> float:
    if "/" in s:
        a, b = s.split("/")
        return float(a) / float(b)
    return float(s)


@dataclass
class Callout:
    kind: str                 # tap | cbore | csink | drill
    text: str
    d: Optional[float] = None
    thread: str = ""
    depth: Optional[float] = None
    thru: bool = False
    count: int = 1
    screw: str = ""
    cbore_d: Optional[float] = None   # counterbore diameter; for kind "cbore", `depth` is the
                                      # counterbore depth (drawing convention)
    bc_d: Optional[float] = None      # bolt-circle diameter ("... EQ. SP. ON 3.000 B.C.")

    @property
    def nominal(self) -> Optional[float]:
        """Thread major diameter in inches (None if not a tap)."""
        if not self.thread:
            return None
        if self.thread.startswith("M"):
            return float(_THREAD_M.match(self.thread).group(1)) / 25.4
        size = self.thread.split("-")[0]
        return _SCREW_NO[size] if size.startswith("#") else _num(size)


def _drill_d(t: str) -> Optional[float]:
    """First drill diameter in t, ignoring a number that labels a counterbore."""
    found = []
    for rx in (_DRILL_PRE, _DRILL_POST, _DRILL_MARK_THRU):
        for m in rx.finditer(t):
            if re.match(r"\s*(?:%%C|Ø)?\s*(?:" + _CBORE_WORD + "|" + _BC_MARK + ")", t[m.end():]):
                continue                      # a counterbore or bolt-circle size, not the drill
            found.append((m.start(), _num(m.group(1))))
    return min(found)[1] if found else None


def parse(text: str) -> Optional[Callout]:
    t = " ".join(text.upper().replace("\\P", " ").split())
    t = re.sub(r"C'\s+(BORE|SINK)", r"C'\1", t)          # "C' BORE" -> "C'BORE"
    is_cbore = re.search(_CBORE_WORD, t) is not None
    is_csink = "C'SINK" in t or "CSINK" in t or "CSK" in t or "COUNTERSINK" in t
    m_in = _THREAD_IN.search(t) or _THREAD_TAP_FIRST.search(t)
    m_m = _THREAD_M.search(t)
    if m_m and "TAP" in t:
        kind, thread = "tap", f"M{m_m.group(1)}X{m_m.group(2)}"
    elif m_in:
        kind, thread = "tap", f"{m_in.group(1)}-{m_in.group(2)}"
    elif is_cbore:
        kind, thread = "cbore", ""
    elif is_csink:
        kind, thread = "csink", ""
    elif _drill_d(t) is not None and (_COUNT.search(t) or not any(w in t for w in _NOT_A_HOLE)):
        # a counted drill callout is a hole even with "B.C." in it (".344 DIA. THRU (6) HLS. EQ. SP.
        # ON 3.000 B.C."); an uncounted one with a veto word is a note ("(4.562%%C B.C. REF.)")
        kind, thread = "drill", ""
    else:
        return None
    m = _COUNT.search(t)
    count = int(next(g for g in m.groups() if g)) if m else 1
    dm = _DEPTH.search(t)
    depth = _num(dm.group(1)) if dm else None
    d = _drill_d(t) if kind != "tap" else None
    if kind == "drill" and not (_D_MIN <= d <= _D_MAX):
        return None
    if kind == "drill" and not ("THRU" in t or dm or m or _DRILL_WORD.search(t)):
        return None                       # a diameter note ("OVER .5000 DIA.", "%%C2.750")
    cm = _CBORE_D.search(t) if kind == "cbore" else None
    if kind == "drill":                   # "1.500 DRILL THRU & 1.9685 RM.": the reamed step
        rm = _REAM.search(t)
        cm = rm if rm and abs(_num(rm.group(1)) - d) > 1e-9 else None
    sm = _SCREW.search(t)
    return Callout(kind=kind, text=text, d=d, thread=thread, depth=depth, thru="THRU" in t,
                   count=count, screw=sm.group(1) if sm else "",
                   cbore_d=_num(cm.group(1)) if cm else None, bc_d=_bc_d(t))


def _bc_d(t: str) -> Optional[float]:
    m = _BC_AFTER.search(t) or _BC_BEFORE.search(t)
    return _num(m.group(1)) if m else None
