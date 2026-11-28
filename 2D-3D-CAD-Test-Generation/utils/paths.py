"""Central repository paths. Resolve every repo-relative location through this module, never from the cwd.

Layout: see REPOSITORY_MAP.md. Input drawings live under ``data/inputs``; the old top-level folder names
(``DrawingPDFs``, ``Simple Parts``, ...) are still understood by :func:`resolve_input` so stored records
and old commands keep working.
"""
from __future__ import annotations

import os
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parents[1]            # 2D-3D-CAD-Test-Generation/
REPO_ROOT = CODE_DIR.parent
INPUTS = REPO_ROOT / "data" / "inputs"
DRAWING_PDFS = INPUTS / "drawing_pdfs"
VERIFIED_DRAWINGS = INPUTS / "verified_drawings"
VIEW_DEFINED_DRAWINGS = INPUTS / "view_defined_drawings"
SIMPLE_PARTS = INPUTS / "simple_parts"
MTI_TEST_SET_CSV = INPUTS / "mti_test_set.csv"
FINAL_OUTPUTS = REPO_ROOT / "FINAL_OUTPUTs"                # live output root used by the UI (kept: stored records point here)
UI_DATA = REPO_ROOT / "FINAL_UI" / "data"
DOCS = REPO_ROOT / "docs"

# Pre-reorganisation names -> current folders (backward compatibility for stored paths and old commands).
LEGACY_INPUT_NAMES = {
    "DrawingPDFs": DRAWING_PDFS,
    "NewVerifiedDrawings": VERIFIED_DRAWINGS,
    "ViewDefinedDrawings": VIEW_DEFINED_DRAWINGS,
    "Simple Parts": SIMPLE_PARTS,
}


def resolve_input(path: str | os.PathLike) -> Path:
    """Map a path that starts with an old input-folder name (relative, or absolute under the repo root) to its new location."""
    p = Path(path)
    try:
        rel = p.relative_to(REPO_ROOT) if p.is_absolute() else p
    except ValueError:
        return p
    parts = rel.parts
    if parts and parts[0] in LEGACY_INPUT_NAMES:
        return LEGACY_INPUT_NAMES[parts[0]].joinpath(*parts[1:])
    return p if p.is_absolute() else (REPO_ROOT / rel)


def history_roots() -> list[Path]:
    """Read-only folders searched for earlier runs and source drawings."""
    return [FINAL_OUTPUTS, UI_DATA, DRAWING_PDFS]
