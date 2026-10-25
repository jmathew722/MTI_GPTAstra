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
    Pair("1901001E", "Complex Parts (not weldments)/1901001E.dwg",
         "Complex Parts (Not Weldments)/1901001E.SLDPRT", "complex", "master collet (Emerson)"),
)

_MULTI = "multi-body model (4 solids); cannot be keyed as one part (parked 2026-10-24)"
_REJECTED = "pairing rejected at key review: model differs from drawing (parked 2026-10-24)"
PARKED = (
    Pair("1807408E", "Complex Parts (not weldments)/1807408E.DWG",
         "Complex Parts (Not Weldments)/1807408-021(A).SLDPRT", "complex",
         "tailstock ring, hole table (Rolls Royce)", _REJECTED),
    Pair("1801901E", "Complex Parts (not weldments)/1801901E.DWG",
         "Complex Parts (Not Weldments)/1801901.SLDPRT", "complex", "collet pad serrated (Morton)", _MULTI),
)

# Re-admitted 2026-10-24 under the drawing-is-ground-truth policy (user decision): keep every
# pair unless the differences are extreme; record differences as `drawing-wins` resolutions.
# Kept separate from CLEAN so the seeded format-dev pick above never changes. Each metric
# twin goes to the same split as its inch partner (A050381E is format dev).
READMITTED_DEV = (
    Pair("A050381M", "Simple Parts/A050381M.DWG", "Simple Parts/A050381E.SLDPRT", "simple",
         "mounting pad, metric taps (twin of A050381E)"),
)
READMITTED_HELD = (
    Pair("A050031M", "Simple Parts/A050031M.DWG", "Simple Parts/A050031E.SLDPRT", "simple",
         "adapter, metric taps (twin of A050031E)"),
    Pair("A050081M", "Simple Parts/A050081M.DWG", "Simple Parts/A050081E_OLD.SLDPRT", "simple",
         "wear plate, metric cbores (twin of A050081E_OLD)"),
    Pair("A050031E", "Simple Parts/A050031E.DWG", "Simple Parts/A050031E.SLDPRT", "simple",
         "adapter (sheet stamped OBSOLETE)"),
    Pair("A050061E", "Simple Parts/A050061E.DWG", "Simple Parts/A050061E.SLDPRT", "simple",
         "bushing (sheet stamped OBSOLETE)"),
    Pair("A050081E_OLD", "Simple Parts/A050081E_OLD.dwg", "Simple Parts/A050081E_OLD.SLDPRT", "simple",
         "wear plate (sheet stamped OBSOLETE)"),
    Pair("A050131M", "Simple Parts/A050131M.DWG", "Simple Parts/A050131M.SLDPRT", "simple",
         "key (sheet stamped OBSOLETE)"),
)
READMITTED = READMITTED_DEV + READMITTED_HELD


# Swap decided 2026-10-24 (user): the feature profile showed format dev had no turned-part
# features, so one round held-out part and one dev plate trade places, picked by a recorded
# seed (no hand picking). Twins / near-duplicates are excluded so pairs stay together.
SWAP_SEED = 20261024
SWAP_ROUND_CANDIDATES = ("A050061E", "A050071E", "A050211E", "A050221E", "A050311E")
SWAP_PLATE_CANDIDATES = ("A050291E", "A050511E")


def swap_pick() -> tuple[str, str]:
    """(round part into format dev, plate out of format dev)."""
    r = random.Random(SWAP_SEED)
    return r.choice(sorted(SWAP_ROUND_CANDIDATES)), r.choice(sorted(SWAP_PLATE_CANDIDATES))


def format_dev() -> list[str]:
    """Final format-dev parts: the seeded pick, after the seeded swap, plus re-admitted twins."""
    round_in, plate_out = swap_pick()
    return sorted((set(choose_format_dev()) - {plate_out}) | {round_in} | {p.part for p in READMITTED_DEV})


def choose_format_dev() -> list[str]:
    cands = sorted(p.part for p in CLEAN if p.complexity == "simple" and p.part not in NEAR_DUPLICATES)
    return sorted(random.Random(SEED).sample(cands, 3))


def pair(part: str) -> Pair:
    for p in CLEAN + READMITTED + PARKED:
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
