"""Parse drafting hole callouts (legacy MTI style) into structured facts.

Depth is a value followed by DP; the "C'BORE .38 DP." form gives the counterbore depth.
A count comes from "(3) HLS", "6-HLS", "4 HOLES", "12-HOLES", "4X". Nominal thread size
is in inches.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

NUM = r"(\d*\.\d+|\d+(?:/\d+)?)"
_THREAD_IN = re.compile(r"(#\d+|\d*\.\d+|\d+/\d+|\d+)\s*-\s*(\d+)(?:\s*UN[CF])?\s*TAP")
_THREAD_M = re.compile(r"M(\d+(?:\.\d+)?)\s*X\s*(\d+(?:\.\d+)?)")
_COUNT = re.compile(r"\((\d+)\)\s*HLS?|(\d+)\s*-\s*HLS?|(\d+)\s*-?\s*HOLES?|\b(\d+)\s*X\b")
_DEPTH = re.compile(NUM + r"\s*DP")
_DRILL = re.compile(NUM + r"\s*(?:DR\b|DR\.|DRILL|DIA\.?|%%C|Ø)")
_SCREW = re.compile(r"FOR\s+(#\d+|\d*\.\d+|\d+/\d+)\s*(?:SOC|S\.?H\.?C\.?S|FLAT|SHCS|CAP)")
_SCREW_NO = {"#4": 0.112, "#5": 0.125, "#6": 0.138, "#8": 0.164, "#10": 0.190, "#12": 0.216}


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

    @property
    def nominal(self) -> Optional[float]:
        """Thread major diameter in inches (None if not a tap)."""
        if not self.thread:
            return None
        if self.thread.startswith("M"):
            return float(_THREAD_M.match(self.thread).group(1)) / 25.4
        size = self.thread.split("-")[0]
        return _SCREW_NO[size] if size.startswith("#") else _num(size)


def parse(text: str) -> Optional[Callout]:
    t = " ".join(text.upper().replace("\\P", " ").split())
    is_cbore = "C'BORE" in t or "CBORE" in t or "COUNTERBORE" in t
    is_csink = "C'SINK" in t or "CSINK" in t or "CSK" in t or "COUNTERSINK" in t
    m_in, m_m = _THREAD_IN.search(t), _THREAD_M.search(t)
    if m_m and "TAP" in t:
        kind, thread = "tap", f"M{m_m.group(1)}X{m_m.group(2)}"
    elif m_in:
        kind, thread = "tap", f"{m_in.group(1)}-{m_in.group(2)}"
    elif is_cbore:
        kind, thread = "cbore", ""
    elif is_csink:
        kind, thread = "csink", ""
    elif _DRILL.search(t) or ("THRU" in t and re.search(NUM, t)):
        kind, thread = "drill", ""
    else:
        return None
    m = _COUNT.search(t)
    count = int(next(g for g in m.groups() if g)) if m else 1
    dm = _DEPTH.search(t)
    depth = _num(dm.group(1)) if dm else None
    dr = _DRILL.search(t)
    d = _num(dr.group(1)) if dr and kind != "tap" else None
    sm = _SCREW.search(t)
    return Callout(kind=kind, text=text, d=d, thread=thread, depth=depth, thru="THRU" in t,
                   count=count, screw=sm.group(1) if sm else "")
