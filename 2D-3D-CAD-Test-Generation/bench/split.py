"""The MTI drawing-model pairs (2026-10-11 delivery) and the frozen benchmark split.

Paths are relative to the dataset folder's `New Dataset/AutoCAD/` (DWG) and
`New Dataset/AutoCAD/Corresponding Models/` (SLDPRT). Nothing here is confidential.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

SEED = 20261023
NEAR_DUPLICATES = ("A050471E", "A050481E")
DWG_ROOT = "New Dataset/AutoCAD"
MODEL_ROOT = "New Dataset/AutoCAD/Corresponding Models"


@dataclass(frozen=True)
class Pair:
    part: str
    dwg: str          # relative to DWG_ROOT
    model: str        # relative to MODEL_ROOT
    complexity: str   # simple | complex
    family: str
    reason: str = ""  # parked only


def _s(part, family):
    return Pair(part, f"Simple Parts/{part}.DWG", f"Simple Parts/{part}.SLDPRT", "simple", family)


CLEAN = (
    _s("A050071E", "rod with flat, tapped ends"),
    _s("A050181E", "mounting pad bar, 2 tapped thru"),
    _s("A050211E", "retainer disc, 6 thru holes, U-notch"),
    _s("A050221E", "flanged disc, bore, hole pattern"),
    _s("A050291E", "large plate/bracket, holes and taps"),
    _s("A050311E", "collet actuator ring"),
    _s("A050381E", "mounting pad block, 4 tapped blind"),
    _s("A050411E", "tank cover plate, 12 countersinks"),
    _s("A050471E", "locator (Wuxi), 3 counterbores"),
    _s("A050481E", "locator (Wuxi), 3 counterbores"),
    _s("A050511E", "key (Wuxi), counterbore"),
    Pair("1801901E", "Complex Parts (not weldments)/1801901E.DWG",
         "Complex Parts (Not Weldments)/1801901.SLDPRT", "complex", "collet pad serrated (Morton)"),
    Pair("1807408E", "Complex Parts (not weldments)/1807408E.DWG",
         "Complex Parts (Not Weldments)/1807408-021(A).SLDPRT", "complex",
         "tailstock ring, hole table (Rolls Royce); PROVISIONAL pairing"),
    Pair("1901001E", "Complex Parts (not weldments)/1901001E.dwg",
         "Complex Parts (Not Weldments)/1901001E.SLDPRT", "complex", "master collet (Emerson)"),
)

_TWIN = "M twin: only the inch (E) model exists, hole sizes differ"
_OBS = "OBSOLETE sheet; model may be a later revision"
PARKED = (
    Pair("A050031M", "Simple Parts/A050031M.DWG", "Simple Parts/A050031E.SLDPRT", "simple", "adapter", _TWIN),
    Pair("A050081M", "Simple Parts/A050081M.DWG", "Simple Parts/A050081E_OLD.SLDPRT", "simple", "wear plate", _TWIN),
    Pair("A050381M", "Simple Parts/A050381M.DWG", "Simple Parts/A050381E.SLDPRT", "simple", "mounting pad", _TWIN),
    Pair("A050031E", "Simple Parts/A050031E.DWG", "Simple Parts/A050031E.SLDPRT", "simple", "adapter", _OBS),
    Pair("A050061E", "Simple Parts/A050061E.DWG", "Simple Parts/A050061E.SLDPRT", "simple", "bushing", _OBS),
    Pair("A050081E_OLD", "Simple Parts/A050081E_OLD.dwg", "Simple Parts/A050081E_OLD.SLDPRT", "simple",
         "wear plate", _OBS),
    Pair("A050131M", "Simple Parts/A050131M.DWG", "Simple Parts/A050131M.SLDPRT", "simple", "key", _OBS),
)


def choose_format_dev() -> list[str]:
    cands = sorted(p.part for p in CLEAN if p.complexity == "simple" and p.part not in NEAR_DUPLICATES)
    return sorted(random.Random(SEED).sample(cands, 3))


def pair(part: str) -> Pair:
    for p in CLEAN + PARKED:
        if p.part == part:
            return p
    raise KeyError(f"unknown MTI part {part!r}")


def mti_entries(manifest: dict) -> dict[str, list[dict]]:
    """The manifest's MTI-dataset entries per split (source: mti_bench)."""
    return {s: [e for e in (manifest["splits"].get(s) or []) if e.get("source") == "mti_bench"]
            for s in ("dev", "held_out", "parked")}


def bench_parts(manifest: dict) -> list[str]:
    """Scored MTI parts (format dev + held-out), in manifest order."""
    m = mti_entries(manifest)
    return [e["part"] for e in m["dev"] + m["held_out"]]
