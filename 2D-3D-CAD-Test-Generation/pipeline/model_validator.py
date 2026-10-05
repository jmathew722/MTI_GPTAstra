"""Post-build model validation.

After SolidWorks builds the part, confirm it actually represents the drawing:
a non-zero solid body exists, the model's overall bounding box matches the
drawing's overall dimensions within tolerance, and EVERY extracted feature was
built. A part missing features FAILS (:func:`check_completeness`). Before
2026-10-04 this check did not exist, and parts with 2 of 5 features passed.

WINDOWS ONLY at call time (operates on a live SolidWorks document), but imports
cleanly anywhere. Public entry point: :func:`validate_model`.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional, Union

from pipeline.schema import DrawingData
from utils.logger import get_logger
from utils.unit_converter import to_meters

log = get_logger()

# Allowed mismatch between a model bounding-box edge and a drawing dimension.
# Only overall/envelope dims are compared, and those should equal a bbox extent.
# 5% was too loose: on SB11033 it let a 1.781" body "match" the 1.971" overall length
# via the 1.938" flange diameter extent. 1% plus a 0.5 mm floor.
REL_TOLERANCE = 0.01      # 1%
ABS_TOLERANCE_M = 0.0005  # 0.5 mm floor


def _coerce(data: Union[DrawingData, dict[str, Any]]) -> DrawingData:
    return data if isinstance(data, DrawingData) else DrawingData.model_validate(data)


def _dims_in_meters(model: DrawingData, applies_to: str) -> list[float]:
    """All dimension values (in meters) whose applies_to is ``applies_to`` or
    ``overall_<applies_to>`` (extractors write both forms)."""
    out = []
    for d in model.dimensions:
        label = (d.applies_to or "").lower().strip()
        if label in (applies_to, f"overall_{applies_to}"):
            out.append(to_meters(d.value, d.unit.value))
    return out


def check_completeness(model: DrawingData, built_feature_ids: Iterable[str]) -> dict[str, Any]:
    """Compare the features the drawing calls for with the features actually built.

    Pure (no SolidWorks), so it is unit-tested on any OS. Every extracted feature
    that was not built is a FAILURE: a model missing a feature does not represent
    the drawing, whatever its bounding box says.
    """
    built = set(built_feature_ids)
    expected = [f for f in model.features]
    missing = [f for f in expected if f.id not in built]
    report: dict[str, Any] = {"passed": [], "failed": [], "expected": len(expected),
                              "built": len(expected) - len(missing),
                              "missing": [f.id for f in missing]}
    for f in missing:
        why = "not in build_order" if f.id not in model.build_order else "build skipped/failed"
        qty = f" x{f.quantity}" if f.quantity > 1 else ""
        report["failed"].append(
            f"INCOMPLETE: {f.id} {f.type.value}{qty} not built ({why}) - {f.description[:70]}"
        )
    pct = 100 * report["built"] / report["expected"] if expected else 100
    line = f"Feature completeness: {report['built']}/{report['expected']} built ({pct:.0f}%)."
    (report["passed"] if not missing else report["failed"]).insert(0, line)
    return report


def _matches_any(actual_m: float, expected_values_m: list[float]) -> bool:
    for exp in expected_values_m:
        tol = max(ABS_TOLERANCE_M, REL_TOLERANCE * exp)
        if abs(actual_m - exp) <= tol:
            return True
    return False


def validate_model(sw_doc, drawing_data: Union[DrawingData, dict[str, Any]],
                   built_feature_ids: Optional[Iterable[str]] = None) -> dict[str, Any]:
    """Verify the built model matches the drawing's dimensions and features.

    Args:
        sw_doc: The live SolidWorks document returned by ``build_model``.
        drawing_data: The validated drawing data the model was built from.
        built_feature_ids: ids of the features that were actually built. When
            given, any extracted feature not among them fails validation.

    Returns:
        A report dict with ``passed`` / ``failed`` / ``warnings`` lists, plus
        ``volume_mm3``, ``surface_area_mm2``, and the measured bounding box.
    """
    model = _coerce(drawing_data)
    report: dict[str, Any] = {"passed": [], "failed": [], "warnings": []}

    # --- Completeness: every extracted feature must have been built ---
    if built_feature_ids is not None:
        comp = check_completeness(model, built_feature_ids)
        report["passed"] += comp["passed"]
        report["failed"] += comp["failed"]
        report["completeness"] = {k: comp[k] for k in ("expected", "built", "missing")}
    else:
        report["warnings"].append("Feature completeness NOT checked (no built-feature list given).")

    # --- Mass properties: confirms a solid body exists ---
    # The document-level mass-property objects (CreateMassProperty/2) are not
    # resolvable under late-bound dispatch (DISP_E_MEMBERNOTFOUND), so read mass
    # properties from the solid body itself: IBody2.GetMassProperties(density)
    # returns [comX, comY, comZ, Volume, SurfaceArea, Mass, ...] in SI units.
    try:
        bodies = sw_doc.GetBodies2(0, True)  # swBodyType_e.swSolidBody = 0
    except Exception as e:
        report["failed"].append(f"Could not enumerate solid bodies: {e}")
        report["ok"] = False
        return report
    if not bodies:
        report["failed"].append("CRITICAL: no solid body exists — no body was created.")
        report["ok"] = False
        return report

    # Measure the LARGEST solid body so a stray/disjoint body can't mask the part.
    def _body_volume(b) -> float:
        try:
            return float(b.GetMassProperties(1000.0)[3])
        except Exception:
            return 0.0

    body = max(bodies, key=_body_volume)
    if len(bodies) > 1:
        report["warnings"].append(
            f"{len(bodies)} disjoint solid bodies present — measuring the largest. "
            "Verify the part is a single connected body."
        )
    try:
        mp = body.GetMassProperties(1000.0)  # density irrelevant to volume/area
        volume_m3 = float(mp[3])
    except Exception as e:
        report["failed"].append(f"Could not read volume from body: {e}")
        report["ok"] = False
        return report

    if volume_m3 <= 0:
        report["failed"].append("CRITICAL: Part has zero volume — no solid body was created.")
        report["ok"] = False
        return report
    report["passed"].append("Solid body exists (volume > 0).")
    report["volume_mm3"] = volume_m3 * 1e9
    try:
        report["surface_area_mm2"] = float(mp[4]) * 1e6
    except Exception:
        report["warnings"].append("Could not read surface area.")

    # --- Bounding box vs overall drawing dimensions ---
    # IModelDoc2 has no GetModelBoundingBox; read the box from the solid body
    # itself (IBody2::GetBodyBox). [xmin,ymin,zmin,xmax,ymax,zmax] in meters.
    try:
        bbox = body.GetBodyBox()
        if bbox is None:
            report["warnings"].append("No solid body found to read a bounding box from.")
    except Exception as e:
        report["warnings"].append(f"Could not read bounding box: {e}")
        bbox = None

    if bbox and len(bbox) >= 6:
        extents_m = sorted(
            [bbox[3] - bbox[0], bbox[4] - bbox[1], bbox[5] - bbox[2]], reverse=True
        )
        report["bounding_box_mm"] = [round(e * 1000, 4) for e in extents_m]

        # Compare each declared overall dimension to the closest bbox extent.
        for label in ("length", "width", "height"):
            expected = _dims_in_meters(model, label)
            if not expected:
                continue
            matched = any(_matches_any(e, expected) for e in extents_m)
            exp_mm = [round(v * 1000, 3) for v in expected]
            if matched:
                report["passed"].append(
                    f"{label}: a model extent matches drawing value(s) {exp_mm} mm."
                )
            else:
                report["failed"].append(
                    f"{label}: drawing value(s) {exp_mm} mm not found among model extents "
                    f"{report['bounding_box_mm']} mm (tolerance {REL_TOLERANCE:.0%})."
                )

    log.info(
        "Model validation: %d passed, %d failed, %d warnings.",
        len(report["passed"]),
        len(report["failed"]),
        len(report["warnings"]),
    )
    for f in report["failed"]:
        log.error("  [FAIL] %s", f)
    for w in report["warnings"]:
        log.warning("  [WARN] %s", w)

    report["ok"] = not report["failed"]
    return report
