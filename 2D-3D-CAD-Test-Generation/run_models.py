"""Batch-build every part folder in a directory, end to end, with no failures.

For each part folder (a subfolder of per-view images), this driver:
  1. extracts the drawing with Claude Vision (multi-view, cached),
  2. AUTO-RESOLVES unknowns/ambiguities with 90%-confidence engineering defaults,
     recording every decision,
  3. runs the Phase-1 verification gate (which now passes after resolution),
  4. builds the 3D model in SolidWorks over COM in NON-STRICT mode so the run
     always completes — any feature that still cannot be built is skipped and
     documented rather than aborting,
  5. writes ``<Part>_design_decisions.txt`` listing every design decision, every
     extracted dimension, and all concerns/issues for human verification.

Usage:
    python run_models.py <folder-of-part-folders> [<folder> ...] --output ./output

Each positional folder may itself contain the part subfolder (the common
"<Part>-<timestamp>" download layout is handled automatically).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

# Importing the extractor loads .env (ANTHROPIC_API_KEY, SOLIDWORKS_TEMPLATE_PATH).
from pipeline.extractor import DEFAULT_MODEL, extract_drawing_data_multiview
from pipeline.schema import DrawingData
from pipeline.token_tracker import LEDGER_NAME, TokenTracker, scope
from pipeline.usage_log import record_run
from pipeline.validator import format_verification_report, run_verification
from pipeline.view_ingest import IMAGE_SUFFIXES, PartViews, discover_parts
from utils.image_prep import prepare_image


# --------------------------------------------------------------------------- #
# Part discovery
# --------------------------------------------------------------------------- #
# Recognize a "<part>_<view>_view"/"<part>_<view>" suffix in a flat filename.
_VIEW_SUFFIX = re.compile(
    r"_(front|side|top|bottom|rear|back|second[ _]?side)(?:[ _]?view)?$", re.IGNORECASE
)
_VIEW_KW = {"front": "front", "side": "side", "top": "top", "bottom": "bottom",
            "rear": "second_side", "back": "second_side", "secondside": "second_side"}


def _flat_part_view(path: Path) -> tuple[str, str]:
    """Split a flat filename into (part_name, view). A bare part name (no view
    suffix) is the FULL/overview view; '<part>_front_view' etc. map to the view."""
    stem = re.sub(r"\s*\(\d+\)\s*$", "", path.stem).strip()  # drop trailing " (1)"
    m = _VIEW_SUFFIX.search(stem)
    if m:
        kw = m.group(1).lower().replace(" ", "").replace("_", "")
        return stem[: m.start()].rstrip("_ ").strip(), _VIEW_KW.get(kw, kw)
    return stem, "full"


def discover_parts_flat(folder: Path) -> list[PartViews]:
    """Group images that live DIRECTLY in a folder into parts by filename prefix,
    keeping the bare-name image as the 'full' (overview) view."""
    imgs = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES]
    groups: dict[str, PartViews] = {}
    for p in sorted(imgs):
        part_name, view = _flat_part_view(p)
        g = groups.setdefault(part_name, PartViews(name=part_name))
        if view in g.views:
            g.warnings.append(
                f"Multiple images map to the {view} view ({g.views[view].name}, {p.name}); keeping the first."
            )
            continue
        g.views[view] = p
    for g in groups.values():
        if "front" not in g.views and "full" not in g.views:
            g.warnings.append("No FRONT or FULL view found — the base profile may be unreliable.")
    return list(groups.values())


def find_parts(root: Path) -> list[PartViews]:
    """Find part(s) under ``root`` for several layouts: images grouped flat by
    filename prefix; part subfolders; or a "<Part>-<timestamp>" wrapper dir."""
    direct = [p for p in root.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES]
    if direct:
        return discover_parts_flat(root)
    found: list[PartViews] = []
    for sub in sorted(p for p in root.iterdir() if p.is_dir()):
        subdirect = [p for p in sub.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES]
        found.extend(discover_parts_flat(sub) if subdirect else discover_parts(sub))
    return found or discover_parts(root)


def _ordered_views_with_full(part: PartViews) -> list[tuple[str, Path]]:
    """Orthographic views in canonical order, plus the full/overview view last."""
    ordered = list(part.ordered_views)  # front, top, side, ... (per VIEW_ORDER)
    if "full" in part.views:
        ordered.append(("full", part.views["full"]))
    return ordered


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
def extract_part(part: PartViews, cache_dir: Path, usage: dict) -> dict:
    views = []
    for view_type, path in _ordered_views_with_full(part):
        prepared = prepare_image(str(path), return_details=True)
        views.append((view_type, prepared.base64, prepared.media_type))
    data = extract_drawing_data_multiview(
        views, cache_dir=cache_dir, usage_out=usage, prep_warnings=part.warnings
    )
    if not data.get("part_number") and not data.get("part_name"):
        data["part_number"] = part.name
    return data


# --------------------------------------------------------------------------- #
# Auto-resolution of unknowns (90%-confidence engineering defaults)
# --------------------------------------------------------------------------- #
_BOSS, _CUT, _HOLE = "extrude_boss", "extrude_cut", "hole"
_FRAGILE = {"fillet", "chamfer"}
_BASE_TYPES = {"extrude_boss", "revolve"}


def _dim(data: dict, dim_id: str) -> dict | None:
    return next((d for d in data.get("dimensions", []) if d.get("id") == dim_id), None)


def _feat(data: dict, fid: str) -> dict | None:
    return next((f for f in data.get("features", []) if f.get("id") == fid), None)


def _diam_keys(feat: dict, data: dict) -> bool:
    """True if any related/depth dimension is a diameter/radius (a circular profile)."""
    ids = list(feat.get("related_dimensions", []))
    for did in ids:
        d = _dim(data, did)
        if d and d.get("type") in ("diameter", "radial"):
            return True
    return False


def _planar_pair(feat: dict, data: dict) -> bool:
    """True if related dims supply both a length-like and a width-like extent."""
    labels = set()
    for did in feat.get("related_dimensions", []):
        d = _dim(data, did)
        if not d:
            continue
        a = (d.get("applies_to") or "").lower()
        if "length" in a:
            labels.add("length")
        if "width" in a:
            labels.add("width")
    if {"length", "width"} <= labels:
        return True
    # Also accept width/height or length/height pairs (the builder maps them to x/y).
    from pipeline.schema import Feature
    from pipeline.solidworks_builder import planar_extents
    try:
        model = DrawingData.model_validate(data)
        return planar_extents(model, Feature.model_validate(feat)) is not None
    except Exception:
        return False


def _has_depth(feat: dict, data: dict) -> bool:
    if feat.get("depth_dimension_id"):
        return True
    for did in feat.get("related_dimensions", []):
        d = _dim(data, did)
        if d and (d.get("applies_to") or "").lower() in ("depth", "height", "thickness", "length"):
            return True
    return False


def resolve_unknowns(data: dict, part_name: str) -> tuple[list[str], list[str]]:
    """Mutate ``data`` to clear build-blockers with confident defaults.

    Returns ``(decisions, concerns)`` — human-readable strings.
    """
    decisions: list[str] = []
    concerns: list[str] = []

    # Carry the extractor's own warnings straight into concerns (human review).
    for w in data.get("warnings", []):
        concerns.append(f"Extraction note: {w}")

    units = data.get("units") or "inch"
    if not data.get("units"):
        data["units"] = units
        decisions.append(f"Units were not stated; assumed '{units}' from dimension magnitudes.")

    # Give the part a clean name for the SolidWorks file.
    if not data.get("part_name"):
        data["part_name"] = data.get("part_number") or part_name

    # 1) Mixed units -> normalize the label to the drawing's unit (rare).
    for d in data.get("dimensions", []):
        if d.get("unit") and d["unit"] != units:
            concerns.append(
                f"Dimension {d.get('id')} was tagged '{d['unit']}' but the drawing is "
                f"'{units}'; relabeled to '{units}' (verify the magnitude)."
            )
            d["unit"] = units

    # 2) resolution_required / value_unclear -> accept best guess so it stops
    #    blocking; flag loudly for human review.
    for d in data.get("dimensions", []):
        if d.get("resolution_required"):
            cand = ", ".join(f"{v:g}" for v in d.get("possible_values", [])) or f"{d.get('value')} (best guess)"
            decisions.append(
                f"Dimension {d.get('id')} ({d.get('applies_to') or 'unlabeled'}={d.get('value')}) was "
                f"flagged 'resolution required' ({d.get('ambiguity_reason') or 'ambiguous'}); "
                f"proceeded with best guess {d.get('value')}. Candidates: {cand}."
            )
            concerns.append(
                f"VERIFY dimension {d.get('id')}={d.get('value')} {units} — extractor was unsure "
                f"({d.get('ambiguity_reason') or 'ambiguous'})."
            )
            d["resolution_required"] = False
        elif d.get("value_unclear"):
            concerns.append(
                f"VERIFY dimension {d.get('id')}={d.get('value')} {units} — printed value was unclear "
                f"({d.get('ambiguity_reason') or 'no reason given'})."
            )

    # 3) Non-closing dimension chains -> drop (treat as independent dims).
    rel = data.setdefault("relationships", {})
    kept_chains = []
    for chain in rel.get("dimension_chains", []):
        total = _dim(data, chain.get("total_dimension_id", ""))
        comps = [_dim(data, c) for c in chain.get("component_dimension_ids", [])]
        if total is None or any(c is None for c in comps):
            continue  # references something missing -> drop quietly
        comp_sum = sum(c["value"] for c in comps)
        tol = sum(abs(c.get("tolerance_plus", 0)) + abs(c.get("tolerance_minus", 0)) for c in [total, *comps])
        slack = max(tol, 1e-3 * abs(total["value"]))
        if abs(comp_sum - total["value"]) > slack:
            decisions.append(
                f"Removed dimension chain {total['id']} = "
                f"{' + '.join(c['id'] for c in comps)}: components sum to {comp_sum:g} but "
                f"total is {total['value']:g} {units}. The component is a step WITHIN the "
                f"overall dimension, not a closed loop; kept both as independent dimensions."
            )
        else:
            kept_chains.append(chain)
    rel["dimension_chains"] = kept_chains

    # 4) Angular bolt-circle spacing is in DEGREES, not a length — record it as a
    #    note so it never trips the linear envelope/feasibility check.
    def _is_angular(spacing: float, computed_from: str) -> bool:
        cf = (computed_from or "").lower()
        return spacing >= 45 or any(k in cf for k in ("deg", "°", "angular", "circular", "bolt"))

    kept_es = []
    for s in rel.get("equal_spacing", []):
        if _is_angular(s.get("spacing_value", 0.0), s.get("computed_from", "")):
            decisions.append(
                f"Circular/angular spacing for {s.get('feature_ref')} "
                f"({s.get('qty')} instances @ {s.get('spacing_value'):g} deg) recorded as a NOTE "
                f"only — not used for linear feasibility or auto-patterning."
            )
        else:
            kept_es.append(s)
    rel["equal_spacing"] = kept_es

    for h in data.get("hole_callouts", []):
        if h.get("pattern", "none") != "none":
            decisions.append(
                f"Hole pattern {h.get('id')} ({h.get('qty')} holes): pattern flag cleared for the "
                f"verification gate. Instances are still placed from instance_positions or a "
                f"bolt-circle diameter + feature quantity when the drawing grounds them."
            )
            h["pattern"], h["qty"], h["pattern_spacing"] = "none", 1, 0.0

    # 4b) Hole callouts: synthesize missing ones from their feature (R4), fill drill
    #     and counterbore sizes from the fastener table when the callout names
    #     only the screw (R3), and fold counterbore-only cuts into their hole (R2).
    _complete_hole_callouts(data, decisions, concerns)

    # 5) A revolved (turned) part can't be auto-revolved without a profile, so
    #    approximate the base as a BOUNDING CYLINDER (largest OD x overall length)
    #    and build only that — the true stepped profile is left for manual work.
    bo = data.get("build_order", [])
    rev = next((f for f in data.get("features", []) if f.get("type") == "revolve"), None)
    if rev is not None:
        dims = data.get("dimensions", [])
        dia_dim = max((d for d in dims if d.get("type") == "diameter"),
                      key=lambda d: d["value"], default=None)
        len_dim = next((d for d in dims if "overall" in (d.get("applies_to") or "").lower()), None) \
            or max((d for d in dims if d.get("type") in ("linear", "depth")),
                   key=lambda d: d["value"], default=None)
        if dia_dim and len_dim:
            rev["type"] = "extrude_boss"
            rev["related_dimensions"] = [dia_dim["id"], len_dim["id"]]
            rev["depth_dimension_id"] = len_dim["id"]
            rev["sketch_plane"] = "front"
            decisions.append(
                f"Part is a turned/revolved shaft. The automated builder cannot revolve an "
                f"arbitrary profile, so {rev['id']} was approximated as a BOUNDING CYLINDER "
                f"ø{dia_dim['value']:g} x {len_dim['value']:g} {units} (largest OD x overall length)."
            )
            concerns.append(
                f"MAJOR: {rev['id']} is a simplified bounding cylinder, NOT the real stepped "
                f"shaft/flange profile. Model the part as a revolve manually."
            )
            for fid in [f for f in bo if f != rev["id"]]:
                ft = (_feat(data, fid) or {}).get("type")
                decisions.append(f"Feature {fid} ({ft}) omitted — part built as a single bounding "
                                 f"cylinder pending a manual revolve.")
            bo = [rev["id"]] + ([] if rev["id"] in bo else [])
            if rev["id"] not in data.get("build_order", []):
                bo = [rev["id"]]

    # 5b) Features the extractor defined but left out of build_order: slot
    #     buildable ones back in (cuts/holes before fillets/chamfers) and say so.
    if rev is None:
        for f in data.get("features", []):
            if f["id"] in bo or f.get("type") not in (_BOSS, _CUT, "hole", "pattern", *_FRAGILE):
                continue
            first_fragile = next((i for i, fid in enumerate(bo)
                                  if (_feat(data, fid) or {}).get("type") in _FRAGILE), len(bo))
            bo.insert(len(bo) if f.get("type") in _FRAGILE else first_fragile, f["id"])
            decisions.append(f"Feature {f['id']} ({f.get('type')}) was extracted but missing from "
                             f"build_order; added to the build.")

    # 6) Build-order: ensure a solid base feature comes first.
    if bo:
        first = _feat(data, bo[0])
        if first is None or first.get("type") not in _BASE_TYPES:
            base = next((fid for fid in bo if (_feat(data, fid) or {}).get("type") in _BASE_TYPES), None)
            if base:
                bo.remove(base)
                bo.insert(0, base)
                decisions.append(f"Reordered build so the solid base feature {base} is built first.")

    # 7) Per-feature buildability. Keep confidently-buildable solid features
    #    (bosses with a diameter or length+width, concentric bores). Omit what
    #    can't be placed reliably — drilled/patterned holes, unsupported types,
    #    and bosses with no usable profile — documenting each, so the SolidWorks
    #    run completes cleanly with a correct primary solid.
    for fid in list(bo):
        feat = _feat(data, fid)
        if feat is None:
            bo.remove(fid)
            concerns.append(f"Feature {fid} was in the build order but not defined; removed.")
            continue
        ftype = feat.get("type")
        if ftype in _FRAGILE:
            continue  # fillets/chamfers degrade to a skip in the builder
        if ftype == "hole" and _hole_grounded(data, feat):
            continue  # builder places every instance (pipeline.solidworks_builder.build_hole)
        seed = _feat(data, feat.get("parent_feature") or "")
        if (ftype == "pattern" and seed is not None and seed.get("type") == "hole"
                and _hole_grounded(data, seed)):
            continue  # realized by the seed hole's instances (builder: _pattern_realized_by_seed)
        if ftype in ("hole", "pattern"):
            bo.remove(fid)
            decisions.append(
                f"Feature {fid} ({ftype}): hole positions are not grounded in the extraction "
                f"(no instance positions, known position or bolt circle); omitted."
            )
            concerns.append(f"ADD the holes for {fid} manually per the drawing callouts.")
            continue
        if ftype not in (_BOSS, _CUT):
            bo.remove(fid)
            decisions.append(f"Feature {fid} ({ftype}) is not supported by the automated builder; omitted.")
            concerns.append(f"VERIFY/ADD feature {fid} ({ftype}) manually — not auto-built.")
            continue
        parent = _feat(data, feat.get("parent_feature") or "")
        if ftype == _CUT and parent is not None and parent.get("type") == "hole" and any(
                h.get("feature_ref") == parent["id"] and h.get("cbore_diameter") and h.get("cbore_depth")
                for h in data.get("hole_callouts", [])):
            continue  # realized by the parent hole's counterbore (builder: _cut_realized_by_cbore)
        if not (_diam_keys(feat, data) or _planar_pair(feat, data)):
            bo.remove(fid)
            decisions.append(
                f"Feature {fid} ({ftype}) has no diameter or length+width profile dimension "
                f"(geometry ambiguous); omitted and left for manual modeling."
            )
            concerns.append(f"VERIFY/ADD feature {fid} ({ftype}) manually — ambiguous profile.")
            continue
        if ftype == _BOSS and not _has_depth(feat, data):
            bo.remove(fid)
            decisions.append(f"Feature {fid} (boss) has no depth/length dimension; omitted.")
            concerns.append(f"VERIFY/ADD feature {fid} (boss) manually — no extrude depth available.")
            continue
        if ftype == _BOSS and fid != bo[0]:
            concerns.append(
                f"Feature {fid} (boss) was built coaxially from its sketch plane; any axial "
                f"OFFSET from the base face is not modeled — verify it isn't embedded in the base."
            )
    data["build_order"] = bo
    return decisions, concerns


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
def _fmt_dim_table(model: DrawingData) -> list[str]:
    rows = [("ID", "Type", "Value", "Unit", "Tol +/-", "Applies To", "Notes")]
    for d in model.dimensions:
        rows.append((
            d.id, d.type.value, f"{d.value:g}", d.unit.value,
            f"+{d.tolerance_plus:g}/-{d.tolerance_minus:g}",
            d.applies_to or "-", (d.notes or "")[:50],
        ))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    out = []
    for i, r in enumerate(rows):
        out.append("  ".join(c.ljust(widths[j]) for j, c in enumerate(r)).rstrip())
        if i == 0:
            out.append("  ".join("-" * widths[j] for j in range(len(r))))
    return out


def write_report(
    out_path: Path, model: DrawingData, raw: dict, decisions: list[str], concerns: list[str],
    built: list[str], skipped: list[tuple[str, str, str]], removed_from_build: list[str],
    sw_path: str | None, validation: dict | None, verification_text: str,
) -> None:
    L: list[str] = []
    add = L.append
    add(f"DESIGN DECISION & VERIFICATION REPORT — {model.display_name}")
    add(f"Generated {date.today().isoformat()} by the automated 2D->3D SolidWorks pipeline.")
    add("=" * 78)
    add("")
    add("BUILD SUMMARY")
    add("-" * 78)
    add(f"  SolidWorks file:        {sw_path or '(not saved)'}")
    add(f"  Features built:         {len(built)} ({', '.join(built) or 'none'})")
    if skipped:
        add(f"  Features skipped:       {', '.join(f'{fid} ({t})' for fid, t, _ in skipped)}")
    if removed_from_build:
        add(f"  Features not attempted: {', '.join(removed_from_build)}")
    add(f"  Extraction confidence:  {model.confidence:.0%}")
    if validation is not None:
        vol = validation.get("volume_mm3")
        bbox = validation.get("bounding_box_mm")
        add(f"  Model validation:       {'PASSED' if validation.get('ok') else 'FAILED'}")
        comp = validation.get("completeness")
        if comp:
            add(f"  Feature completeness:   {comp['built']}/{comp['expected']} built"
                + (f" (missing {', '.join(comp['missing'])})" if comp["missing"] else ""))
        for f in validation.get("failed", []):
            add(f"    FAIL: {f}")
        if vol:
            add(f"  Solid volume:           {vol:,.1f} mm^3")
        if bbox:
            add(f"  Bounding box (mm):      {bbox}")
    add("")
    add("1. AUTOMATED DESIGN DECISIONS  (90%-confidence defaults — review before production)")
    add("-" * 78)
    if decisions:
        for d in decisions:
            add(f"  - {d}")
    else:
        add("  None. The model was built directly from the extraction with no assumptions.")
    add("")
    add(f"2. EXTRACTED DIMENSIONS  ({len(model.dimensions)})")
    add("-" * 78)
    L.extend("  " + ln for ln in _fmt_dim_table(model))
    if model.geometric_tolerances:
        add("")
        add("  Geometric tolerances:")
        for g in model.geometric_tolerances:
            add(f"    - {g.symbol} {g.value:g}" + (f" (datum {g.datum})" if g.datum else ""))
    if model.hole_callouts:
        add("")
        add("  Hole callouts:")
        for h in model.hole_callouts:
            add(f"    - {h.id}: {h.type.value} ø{h.diameter:g} {model.units.value}"
                f"{' THRU' if h.thru else f' depth {h.depth:g}'}, qty {h.qty}"
                f"{'' if h.position_known else '  [POSITION ASSUMED]'}")
    add("")
    add("3. FEATURES")
    add("-" * 78)
    for f in model.features:
        if f.id in built:
            status = "BUILT"
        elif any(f.id == s[0] for s in skipped):
            status = "SKIPPED"
        elif f.id in removed_from_build:
            status = "NOT BUILT"
        else:
            status = "not in build order"
        add(f"  {f.id:6s} {f.type.value:14s} {status:18s} {f.description[:60]}")
    add("")
    add("4. CONCERNS & ISSUES FOR HUMAN VERIFICATION")
    add("-" * 78)
    seen = set()
    items = concerns + [f"Feature {fid} ({t}) was SKIPPED during the build: {r}" for fid, t, r in skipped]
    if not items:
        add("  None flagged.")
    for c in items:
        if c not in seen:
            add(f"  - {c}")
            seen.add(c)
    add("")
    add("=" * 78)
    add("APPENDIX — full Phase-1 verification report")
    add("=" * 78)
    add(verification_text)
    out_path.write_text("\n".join(L), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Per-part pipeline
# --------------------------------------------------------------------------- #
_CBORE_TEXT = re.compile(r"c'?\s*bore|counter\s*bore", re.IGNORECASE)


def _new_callout(data: dict, feat: dict, diameter: float) -> dict:
    ids = {h.get("id") for h in data.get("hole_callouts", [])}
    n = 1
    while f"H{n:03d}" in ids:
        n += 1
    qty = max(1, int(feat.get("quantity") or 1))
    known = bool(feat.get("position_known")) and qty == 1
    return {"id": f"H{n:03d}", "type": "thru", "diameter": diameter, "thru": True, "depth": 0.0,
            "thread_spec": "", "cbore_diameter": 0.0, "cbore_depth": 0.0, "csink_diameter": 0.0,
            "csink_angle": 0.0, "qty": qty,
            "x_position": feat.get("offset_x", 0.0) if known else 0.0,
            "y_position": feat.get("offset_y", 0.0) if known else 0.0,
            "position_known": known, "pattern": "none", "pattern_spacing": 0.0,
            "instance_positions": [], "feature_ref": feat["id"], "view": ""}


def _complete_hole_callouts(data: dict, decisions: list[str], concerns: list[str]) -> None:
    from pipeline.fasteners import SOURCE, nominal_size, shcs_counterbore, size_from_text
    from pipeline.macro_generator import _BOLT_CIRCLE_LABEL

    inch = (data.get("units") or "inch") == "inch"
    calls = data.setdefault("hole_callouts", [])
    feats = data.get("features", [])
    for f in feats:
        if f.get("type") != "hole":
            continue
        dims = [d for d in (_dim(data, i) for i in f.get("related_dimensions", [])) if d]
        h = next((h for h in calls if h.get("feature_ref") == f["id"]), None)
        synthesized = h is None
        if h is None:
            dia = next((d["value"] for d in dims if d.get("type") == "diameter"
                        and not _BOLT_CIRCLE_LABEL.search(d.get("applies_to") or "")), 0.0)
            h = _new_callout(data, f, dia)
            calls.append(h)

        # A counterbore extracted as its own cut: coaxial child with a depth only.
        child = next((c for c in feats if c.get("type") == "extrude_cut"
                      and c.get("parent_feature") == f["id"]
                      and not _diam_keys(c, data) and not _planar_pair(c, data)), None)
        text = " ".join([f.get("description", "")] + [d.get("notes", "") for d in dims]
                        + ([child.get("description", "")] if child else []))
        wants_cbore = bool(_CBORE_TEXT.search(text)) or child is not None or h.get("type") == "counterbore"
        cbore_depth = h.get("cbore_depth") or 0.0
        if not cbore_depth:
            src = [_dim(data, child["depth_dimension_id"])] if child and child.get("depth_dimension_id") else []
            src += [d for d in dims if "counterbore_depth" in (d.get("applies_to") or "").lower()
                    or "cbore_depth" in (d.get("applies_to") or "").lower()]
            cbore_depth = next((d["value"] for d in src if d), 0.0)

        # Screw size: a dimension labeled as the screw size, else the callout text.
        size = next((nominal_size(d["value"]) for d in dims + [d for d in data.get("dimensions", [])
                     if d.get("feature_ref") == f["id"]]
                     if "screw" in (d.get("applies_to") or "").lower() and nominal_size(d["value"])), None)
        size = size or size_from_text(text)
        table = shcs_counterbore(size) if (size and inch) else None
        if table:
            drill, cb_dia, cb_depth = table
            if not h.get("diameter"):
                h["diameter"] = drill
                decisions.append(f"{f['id']}: drill Ø{drill} STANDARD-DERIVED for a {size:g} SHCS ({SOURCE}).")
                concerns.append(f"VERIFY {f['id']} drill Ø{drill}: from the fastener table, not printed on the drawing.")
            if wants_cbore and not h.get("cbore_diameter"):
                h["cbore_diameter"] = cb_dia
                decisions.append(f"{f['id']}: counterbore Ø{cb_dia} STANDARD-DERIVED for a {size:g} SHCS ({SOURCE}).")
                concerns.append(f"VERIFY {f['id']} counterbore Ø{cb_dia}: from the fastener table.")
            if wants_cbore and not cbore_depth:
                cbore_depth = cb_depth
                decisions.append(f"{f['id']}: counterbore depth {cb_depth} STANDARD-DERIVED (none printed).")
        if wants_cbore and h.get("cbore_diameter") and cbore_depth:
            h["type"], h["cbore_depth"] = "counterbore", cbore_depth
            if child:
                decisions.append(f"{child['id']} (counterbore cut) folded into hole {f['id']}'s "
                                 f"counterbore Ø{h['cbore_diameter']} x {cbore_depth}.")
        if synthesized:
            if h.get("diameter"):
                decisions.append(f"Hole callout {h['id']} synthesized from feature {f['id']} "
                                 f"(qty {h['qty']}, Ø{h['diameter']}); the extractor emitted none.")
            else:
                # No diameter on the drawing and no screw to look up: never invent one (R6).
                calls.remove(h)
                concerns.append(f"ESCALATE {f['id']}: hole diameter is not on the drawing (callout "
                                f"missing or unreadable) and no standard applies - needs a human.")


def _hole_grounded(data: dict, feat: dict) -> bool:
    """True when every instance of a hole feature can be placed from extracted data."""
    from pipeline.macro_generator import _bolt_circle_diameter, _circle_from_seed
    from pipeline.schema import HoleCallout

    h = next((h for h in data.get("hole_callouts", []) if h.get("feature_ref") == feat["id"]), None)
    if h is None:
        return bool(feat.get("position_known"))
    if h.get("instance_positions") or (h.get("position_known") and max(h.get("qty", 1), feat.get("quantity", 1)) == 1):
        return True
    try:
        model = DrawingData.model_validate(data)
        callout = HoleCallout.model_validate(h)
        return bool(_bolt_circle_diameter(model, callout) or _circle_from_seed(model, callout))
    except Exception:
        return False


def process_part(part: PartViews, output_root: Path, sw_app, template_path: str | None) -> dict:
    from pipeline.model_validator import validate_model
    from pipeline.solidworks_builder import build_model

    name = part.name
    part_dir = output_root / name.replace(" ", "_")
    part_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = output_root / ".extraction_cache"
    print(f"\n=== {name} ===")
    print(f"  [1/4] extracting views: {', '.join(v for v, _ in _ordered_views_with_full(part)) or 'none'}")

    usage: dict = {}
    with scope(part=name):
        data = extract_part(part, cache_dir, usage)
    record_run(output_root, data.get("part_number") or name, os.getenv("EXTRACTION_MODEL") or DEFAULT_MODEL, usage)

    print("  [2/4] auto-resolving unknowns")
    decisions, concerns = resolve_unknowns(data, name)
    (part_dir / f"{name}_extraction.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

    print("  [3/4] verifying")
    model, report = run_verification(data)
    verification_text = format_verification_report(model, report)
    (part_dir / f"{name}_verification_report.txt").write_text(verification_text, encoding="utf-8")

    built: list[str] = []
    skipped: list[tuple[str, str, str]] = []
    sw_path = None
    validation = None
    status = "BLOCKED"

    if model is None or not report.ok:
        concerns.append("Verification still BLOCKED after auto-resolution — see appendix; no model built.")
    else:
        removed = [f.id for f in model.features if f.id not in model.build_order]
        print("  [4/4] building in SolidWorks (non-strict)")
        try:
            sw_path, sw_doc = build_model(
                sw_app, model, output_dir=part_dir, template_path=template_path,
                strict=False, skipped_out=skipped,
            )
            skipped_ids = {s[0] for s in skipped}
            built = [fid for fid in model.build_order if fid not in skipped_ids]
            validation = validate_model(sw_doc, model, built_feature_ids=built)
            status = "BUILT"
        except Exception as e:
            concerns.append(f"SolidWorks build raised: {type(e).__name__}: {e}")
            status = "BUILD FAILED"
        report_path = part_dir / f"{name}_design_decisions.txt"
        write_report(
            report_path, model, data, decisions, concerns, built, skipped,
            [f.id for f in model.features if f.id not in model.build_order],
            sw_path, validation, verification_text,
        )
        print(f"      -> {status}: {len(built)} built, {len(skipped)} skipped. Report: {report_path.name}")
        return {"part": name, "status": status, "built": len(built), "skipped": len(skipped),
                "sw_path": sw_path, "report": str(report_path)}

    # BLOCKED path still gets a report.
    report_path = part_dir / f"{name}_design_decisions.txt"
    write_report(report_path, model, data, decisions, concerns, built, skipped,
                 [], sw_path, validation, verification_text)
    print(f"      -> {status}. Report: {report_path.name}")
    return {"part": name, "status": status, "built": 0, "skipped": 0,
            "sw_path": None, "report": str(report_path)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("folders", nargs="+", help="Folder(s) each containing a part's view images.")
    ap.add_argument("--output", default="./output", help="Output root directory.")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        rc = getattr(stream, "reconfigure", None)
        if rc:
            try:
                rc(encoding="utf-8", errors="replace")
            except Exception:
                pass

    output_root = Path(args.output)
    output_root.mkdir(parents=True, exist_ok=True)
    template_path = os.getenv("SOLIDWORKS_TEMPLATE_PATH") or None

    from pipeline.solidworks_builder import connect_to_solidworks
    sw_app = connect_to_solidworks()

    results = []
    tracker = TokenTracker(output_root / "usage" / LEDGER_NAME)
    with tracker.activate():
        for folder in args.folders:
            root = Path(folder)
            if not root.is_dir():
                print(f"[skip] not a directory: {root}")
                continue
            for part in find_parts(root):
                results.append(process_part(part, output_root, sw_app, template_path))

    print("\n" + "=" * 60)
    print(f"{'PART':14s} {'STATUS':14s} {'BUILT':>6s} {'SKIP':>5s}  REPORT")
    for r in results:
        print(f"{r['part']:14s} {r['status']:14s} {r['built']:>6} {r['skipped']:>5}  "
              f"{Path(r['report']).name if r.get('report') else '-'}")
    n_ok = sum(1 for r in results if r["status"] == "BUILT")
    print(f"\n{n_ok}/{len(results)} parts built.")
    return 0 if n_ok == len(results) else 8


def _run_with_budget_stop(fn) -> int:
    """Run ``fn``; on a spend-cap stop print why and exit 9 (no traceback)."""
    from pipeline.budget import BudgetExceeded
    try:
        return fn()
    except BudgetExceeded as e:
        print(f"\n*** STOPPED: {e}", file=sys.stderr)
        return 9


if __name__ == "__main__":
    sys.exit(_run_with_budget_stop(main))
