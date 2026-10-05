"""Standard clearance and counterbore sizes for socket head cap screws (inch).

Drawing callouts like "DR. & C'BORE .38 DP. FOR .250 SOC. HD. CAP SCR." name the
SCREW, not the drill or counterbore diameter. A shop takes those from a standard
table, and so does this module. The values are standard, not drawing-read, so every
use is flagged ``STANDARD-DERIVED`` with its source and never applied silently
(CLAUDE.md rule 6). A depth printed on the drawing always wins over the table.

Values: the widely published SHCS counterbore chart (normal-fit drill; cbore
diameter clears the ASME B18.3 head; cbore depth = nominal size). These are the
same numbers as Machinery's Handbook "Drill and Counterbore Sizes for Socket Head
Cap Screws". **Verify against MTI's shop standard before production use.**
"""
from __future__ import annotations

import re
from typing import Optional

SOURCE = "SHCS counterbore chart (ASME B18.3 head; normal-fit drill) - verify vs MTI shop standard"

# nominal size (inch) -> (normal-fit drill, cbore diameter, cbore depth)
SHCS_INCH: dict[float, tuple[float, float, float]] = {
    0.190: (0.219, 0.375, 0.190),   # #10   drill 7/32
    0.250: (0.281, 0.438, 0.250),   # 1/4   drill 9/32,  cbore 7/16
    0.3125: (0.344, 0.531, 0.312),  # 5/16  drill 11/32, cbore 17/32
    0.375: (0.406, 0.625, 0.375),   # 3/8   drill 13/32, cbore 5/8
    0.500: (0.531, 0.812, 0.500),   # 1/2   drill 17/32, cbore 13/16
    0.625: (0.656, 1.000, 0.625),   # 5/8   drill 21/32, cbore 1
    0.750: (0.781, 1.188, 0.750),   # 3/4   drill 25/32, cbore 1-3/16
}

_SHCS_TEXT = re.compile(r"soc(?:ket)?\.?\s*h(?:ea)?d|shcs|cap\s*scr", re.IGNORECASE)
_SIZE_TEXT = re.compile(r"(#\s*10|\d+/\d+|\.\d{2,4}|\d\.\d{2,4})")
_FRACTIONS = {"1/4": 0.25, "5/16": 0.3125, "3/8": 0.375, "1/2": 0.5, "5/8": 0.625, "3/4": 0.75}


def nominal_size(value: float) -> Optional[float]:
    """Snap a read screw size (.25, .312, .3125, ...) to a table key (±0.003)."""
    for size in SHCS_INCH:
        if abs(size - value) <= 0.003:
            return size
    return None


def size_from_text(text: str) -> Optional[float]:
    """The SHCS nominal size named in callout text, if it names a cap screw."""
    if not text or not _SHCS_TEXT.search(text):
        return None
    for m in _SIZE_TEXT.finditer(text):
        tok = m.group(1).replace(" ", "")
        if tok.startswith("#"):
            return 0.190 if tok == "#10" else None
        value = _FRACTIONS.get(tok) if "/" in tok else float(tok)
        size = nominal_size(value) if value is not None else None
        if size is not None:
            return size
    return None


def shcs_counterbore(size: float) -> Optional[tuple[float, float, float]]:
    """(drill, cbore diameter, cbore depth) for a nominal size in inches."""
    key = nominal_size(size)
    return SHCS_INCH.get(key) if key is not None else None
