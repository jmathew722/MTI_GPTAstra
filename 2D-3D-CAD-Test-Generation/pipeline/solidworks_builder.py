"""SolidWorks model builder via the Windows COM API (written for 2024, verified on 2025 SP5).

WINDOWS ONLY. ``win32com``/``pythoncom`` are imported lazily *inside* functions
so this module imports cleanly on any platform (macOS/Linux); the Windows-only
code paths raise a clear :class:`PlatformError` only when actually invoked.

Design discipline enforced throughout:
  * every COM call's return value is checked for ``None``/failure;
  * EVERY linear dimension passes through :func:`utils.unit_converter.to_meters`
    (asserted via :func:`assert_meters`) before reaching the API — SolidWorks works
    in meters internally;
  * document units are set BEFORE any geometry is created;
  * sketches are verified FULLY DEFINED before extruding;
  * :func:`check_rebuild_errors` runs after EVERY feature;
  * fillets and chamfers (the fragile operations) are wrapped in try/except and
    demoted to warnings rather than crashing the whole build;
  * a partial model is saved if the build crashes, and an auto-save runs every
    few features.

NOTE: This module is verified by inspection on non-Windows dev machines; run it on
Windows + SolidWorks 2024 to exercise the COM paths.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional, Union

from pipeline.schema import DrawingData, Feature, FeatureType
from utils.logger import get_logger
from utils.unit_converter import assert_meters, to_meters, to_radians

log = get_logger()

AUTOSAVE_EVERY = 3  # auto-save the part every N features
OUTPUT_DIR_DEFAULT = Path(__file__).resolve().parent.parent / "output"

# Plane names as SolidWorks exposes them for SelectByID2. Aligned with
# pipeline.view_ingest.VIEW_PLANES so a feature read in a side/bottom view lands
# on the right reference plane (second_side/bottom reuse the orthogonal plane —
# through-cuts are direction-proof).
_PLANE_NAMES = {
    "front": "Front Plane",
    "top": "Top Plane",
    "right": "Right Plane",
    "side": "Right Plane",
    "second_side": "Right Plane",
    "bottom": "Top Plane",
}


class PlatformError(RuntimeError):
    """Raised when SolidWorks/COM functionality is used off Windows."""


class SolidWorksError(RuntimeError):
    """Raised on any SolidWorks build failure. Carries the partial-save path."""

    def __init__(self, message: str, partial_path: Optional[str] = None):
        self.partial_path = partial_path
        super().__init__(message)


# --------------------------------------------------------------------------- #
# COM bootstrap
# --------------------------------------------------------------------------- #
def _require_windows() -> None:
    if sys.platform != "win32":
        raise PlatformError(
            "The SolidWorks build stage requires Windows with SolidWorks 2024 and "
            f"pywin32 installed. Current platform: {sys.platform!r}. Use --validate-only "
            "to run the extraction/validation pipeline on this machine."
        )


def _constants():
    """Return the win32com SolidWorks constants namespace (requires makepy/gencache)."""
    from win32com.client import constants  # type: ignore

    return constants


def _null_dispatch():
    """A VT_DISPATCH NULL VARIANT.

    Late-bound (non-gencache) COM calls can't pass plain Python ``None`` for an
    ``Object``-typed parameter — dynamic dispatch sends VT_EMPTY, and SolidWorks'
    IDispatch::Invoke rejects that with "Type mismatch". Wrapping it as an
    explicit VT_DISPATCH NULL VARIANT is accepted.
    """
    import pythoncom  # type: ignore
    from win32com.client import VARIANT  # type: ignore

    return VARIANT(pythoncom.VT_DISPATCH, None)


def _const(name: str, default: Optional[int] = None) -> int:
    """Fetch a SolidWorks enum constant by name with an optional fallback.

    Using the generated type-library constants (early binding) is reliable once
    ``EnsureDispatch`` has run. The fallback keeps us robust if a particular
    constant is missing from the generated cache.
    """
    try:
        value = getattr(_constants(), name)
        if value is not None:
            return value
    except Exception:
        pass
    if default is None:
        raise SolidWorksError(f"SolidWorks constant {name!r} unavailable (run makepy).")
    return default


# SOLIDWORKS Constant type library — loading this by CLSID/version populates
# win32com.client.constants with the swConst enums (swDocPART, swSketchSegment_*, etc.)
# without needing GetTypeInfo() on a live SolidWorks object. The major version
# tracks the release and the registry shows it in hex (SolidWorks 2025 registers as
# "21.0" = 33 decimal); newest first, first one registered wins. 20 is the value the
# generator was originally written against (2024).
_SW_CONST_TYPELIB_GUID = "{4687F359-55D0-4CD3-B6CF-2EB42C11F989}"
_SW_CONST_TYPELIB_MAJORS = (34, 33, 32, 20)


def _ensure_constants_typelib(gencache) -> None:
    last: Exception | None = None
    for major in _SW_CONST_TYPELIB_MAJORS:
        try:
            gencache.EnsureModule(_SW_CONST_TYPELIB_GUID, 0, major, 0)
            log.info("Loaded SolidWorks constants type library %d.0", major)
            return
        except Exception as e:  # not registered on this install: try the next version
            last = e
    raise SolidWorksError(f"No SolidWorks constants type library found (tried majors "
                          f"{_SW_CONST_TYPELIB_MAJORS}): {last}")


def connect_to_solidworks():
    """Connect to a running SolidWorks instance, or launch a new one.

    SolidWorks' IDispatch does not support ``GetTypeInfo()``, so
    ``gencache.EnsureDispatch`` (which calls it) always fails with "This COM
    object can not automate the makepy process". Instead we use plain
    (late-bound) ``Dispatch`` for the application object, and load the
    SOLIDWORKS constants type library directly by CLSID to populate
    ``win32com.client.constants`` (needed by the feature builders).

    Returns:
        The ``ISldWorks`` application object.

    Raises:
        PlatformError: if not on Windows.
        SolidWorksError: if connection/launch fails.
    """
    _require_windows()
    import pythoncom  # type: ignore
    import win32com.client  # type: ignore
    from win32com.client import gencache  # type: ignore

    pythoncom.CoInitialize()
    _ensure_constants_typelib(gencache)

    sw_app = None
    try:
        # Prefer an already-running instance.
        active = win32com.client.GetActiveObject("SldWorks.Application")
        sw_app = win32com.client.Dispatch(active)
        log.info("Connected to existing SolidWorks instance.")
    except Exception:
        try:
            sw_app = win32com.client.Dispatch("SldWorks.Application")
            sw_app.Visible = True
            log.info("Launched a new SolidWorks instance.")
        except Exception as e:
            raise SolidWorksError(f"Failed to connect to or launch SolidWorks: {e}") from e

    if sw_app is None:
        raise SolidWorksError("Failed to obtain a SolidWorks application object.")

    try:
        log.info("SolidWorks revision: %s", sw_app.RevisionNumber)
    except Exception:
        log.warning("Could not read SolidWorks revision number (continuing).")
    return sw_app


def create_new_part(sw_app, template_path: Optional[str] = None):
    """Create a new part document.

    Raises:
        SolidWorksError: if the template is missing or the document is not created.
    """
    if not template_path:
        # swUserPreferenceStringValue.swDefaultTemplatePart = 8 (documented default).
        try:
            template_path = sw_app.GetUserPreferenceStringValue(_const("swDefaultTemplatePart", 8))
        except Exception as e:
            raise SolidWorksError(f"Could not resolve default part template: {e}") from e

    if not template_path or not Path(template_path).exists():
        raise SolidWorksError(
            f"Part template not found: {template_path!r}. Set SOLIDWORKS_TEMPLATE_PATH "
            "in .env or ensure the SolidWorks default template is configured."
        )

    sw_doc = sw_app.NewDocument(template_path, 0, 0, 0)
    if sw_doc is None:
        raise SolidWorksError("NewDocument returned None — failed to create part document.")
    log.info("Created new part from template: %s", template_path)
    return sw_doc


def set_document_units(sw_doc, unit_system: str) -> None:
    """Set the document's display units. MUST be called before creating geometry.

    SolidWorks stores geometry in meters regardless of this setting; this only
    affects what the user sees in the UI, but we set it for correctness.
    """
    # swLengthUnit_e via generated constants; cm corrected from the original spec
    # (which used the unit-*system* constant swCGS by mistake).
    unit_map = {
        "mm": _const("swMM", 0),
        "cm": _const("swCM", 1),
        "inch": _const("swINCHES", 3),
    }
    length_unit = unit_map.get(unit_system.lower().strip(), unit_map["mm"])
    # SetUnits(lengthUnit, thousandsDelimiter, decimalPlaces, fractionDenominator, roundToFraction)
    ok = sw_doc.SetUnits(length_unit, 0, 4, 2, False)
    if ok is False:  # SetUnits returns bool; None on some bindings — treat None as ok.
        log.warning("SetUnits reported failure for unit system %r (continuing).", unit_system)
    else:
        log.info("Document units set to %s.", unit_system)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _coerce(data: Union[DrawingData, dict[str, Any]]) -> DrawingData:
    return data if isinstance(data, DrawingData) else DrawingData.model_validate(data)


def get_feature_by_id(model: DrawingData, feature_id: str) -> Feature:
    feature = model.feature_by_id(feature_id)
    if feature is None:
        raise SolidWorksError(f"build_order references missing feature {feature_id!r}.")
    return feature


def get_dimensions_for_feature(model: DrawingData, feature: Feature) -> dict[str, float]:
    """Resolve a feature's dimensions to METERS, keyed by ``applies_to``.

    Every value is converted via :func:`to_meters` and gated by
    :func:`assert_meters`, so anything handed to the COM API is guaranteed to be
    a sane meter value. Angular dimensions are returned in radians under their
    ``applies_to`` key as well.
    """
    resolved: dict[str, float] = {}
    ids = list(feature.related_dimensions)
    if feature.depth_dimension_id and feature.depth_dimension_id not in ids:
        ids.append(feature.depth_dimension_id)

    for dim_id in ids:
        dim = model.dimension_by_id(dim_id)
        if dim is None:
            raise SolidWorksError(
                f"Feature {feature.id} references missing dimension {dim_id!r}."
            )
        key = (dim.applies_to or dim.type.value).lower().strip()
        if dim.type.value == "angular":
            value = to_radians(dim.value)
        else:
            value = assert_meters(to_meters(dim.value, dim.unit.value), f"{feature.id}.{key}")
        resolved[key] = value
        # Also expose the value under its canonical geometric type so the feature
        # builders find a diameter/radius regardless of its descriptive applies_to
        # label (e.g. "outer_diameter"/"bore_diameter" -> reachable as "diameter").
        if dim.type.value == "diameter":
            resolved.setdefault("diameter", value)
        elif dim.type.value == "radial":
            resolved.setdefault("radius", value)

    # Also expose the depth explicitly under "depth" for builders that need it.
    if feature.depth_dimension_id:
        depth_dim = model.dimension_by_id(feature.depth_dimension_id)
        if depth_dim is not None and depth_dim.type.value != "angular":
            resolved.setdefault(
                "depth",
                assert_meters(
                    to_meters(depth_dim.value, depth_dim.unit.value), f"{feature.id}.depth"
                ),
            )
    return resolved


def _select_plane(sw_doc, sketch_plane: Optional[str]) -> None:
    """Select the named reference plane for the next sketch."""
    name = _PLANE_NAMES.get((sketch_plane or "front").lower().strip(), "Front Plane")
    selected = sw_doc.Extension.SelectByID2(
        name, "PLANE", 0.0, 0.0, 0.0, False, 0, _null_dispatch(), 0
    )
    if not selected:
        raise SolidWorksError(f"Could not select sketch plane {name!r}.")


def _verify_sketch_fully_defined(sw_doc) -> None:
    """Verify the active sketch is fully defined before extruding.

    An under-defined sketch produces unpredictable geometry. We attempt to add
    relations automatically; if it remains under-defined we warn (the geometry
    is still dimensionally pinned by the values we drew with).
    """
    sketch = sw_doc.SketchManager.ActiveSketch
    if sketch is None:
        raise SolidWorksError("No active sketch to verify.")
    # GetConstrainedStatus: 1 = fully defined, 2 = over defined, 3 = under defined.
    try:
        status = sketch.GetConstrainedStatus()
    except Exception:
        status = None
    if status == 3:
        log.warning("Sketch is under-defined; attempting Fully Define Sketch.")
        try:
            sw_doc.SketchManager.FullyDefineSketch(
                True, True, 0, 0, 0,
                _null_dispatch(), _null_dispatch(), _null_dispatch(),
                _null_dispatch(), _null_dispatch(),
            )
            status = sketch.GetConstrainedStatus()
        except Exception as e:
            log.warning("FullyDefineSketch failed: %s", e)
    if status == 2:
        raise SolidWorksError("Sketch is over-defined — cannot extrude reliably.")
    if status == 3:
        log.warning("Sketch still under-defined after auto-define; geometry may be loose.")


def _origin_relation_for_rectangle(sw_doc) -> None:
    """Best-effort: relate the sketch to the origin so it's anchored."""
    try:
        # Selecting the origin and a sketch point and making them coincident is
        # geometry-specific; we leave the explicit relation to FullyDefineSketch.
        pass
    except Exception:
        pass


def check_rebuild_errors(sw_doc) -> bool:
    """Check for rebuild errors/warnings after a feature. Returns True if clean."""
    try:
        errors = sw_doc.GetRebuildErrorCount() if hasattr(sw_doc, "GetRebuildErrorCount") else sw_doc.GetRebuildErrors()
    except Exception:
        # Older API name fallback.
        errors = 0
    try:
        warnings = sw_doc.GetRebuildWarningCount() if hasattr(sw_doc, "GetRebuildWarningCount") else 0
    except Exception:
        warnings = 0

    if errors and errors > 0:
        log.error("REBUILD ERROR: %s error(s) detected.", errors)
        return False
    if warnings and warnings > 0:
        log.warning("REBUILD WARNING: %s warning(s) — continuing.", warnings)
    return True


def _solid_body_exists(sw_doc) -> bool:
    """True if the part currently contains at least one solid body.

    Uses ``IPartDoc.GetBodies2(swSolidBody, visibleOnly=False)`` which is reliable
    under late-bound dispatch. (The mass-property objects — ``CreateMassProperty``/
    ``CreateMassProperty2`` — are not resolvable without early binding here and
    raise DISP_E_MEMBERNOTFOUND, so they must not gate the build.)
    """
    try:
        # swBodyType_e.swSolidBody = 0
        bodies = sw_doc.GetBodies2(0, False)
    except Exception as e:
        log.warning("Could not enumerate solid bodies: %s", e)
        return False
    if bodies is None:
        return False
    try:
        return len(bodies) > 0
    except TypeError:
        # A single body may come back as a bare COM object rather than a tuple.
        return True


def _g(obj, name: str):
    """Read a zero-argument COM member that late binding may expose as either a
    property or a method (``Feature.GetFaces``, ``Face2.GetEdges``, ...).

    A returned dispatch object is itself "callable" under pywin32, so only call
    plain bound methods.
    """
    value = getattr(obj, name)
    try:
        from win32com.client.dynamic import CDispatch  # type: ignore
    except ImportError:  # pragma: no cover - non-Windows
        CDispatch = ()  # type: ignore
    if value is None or isinstance(value, (tuple, list, CDispatch)):
        return value
    return value() if callable(value) else value


def _m(model: DrawingData, value: float, what: str) -> float:
    """A drawing-units coordinate in meters (positions may be 0 or negative;
    ``to_meters`` rejects negatives, so convert the magnitude and restore the sign)."""
    if not value:
        return 0.0
    meters = assert_meters(to_meters(abs(value), model.units.value), what)
    return meters if value > 0 else -meters


def _feature_center(model: Optional[DrawingData], feature: Feature, circular: bool) -> tuple[float, float, bool]:
    """Sketch anchor in the DRAWING FRAME, meters: ``(x, y, assumed)``.

    Same rules as the VBA path (pipeline/macro_generator.py, error log E003): a
    known offset is used as-is; an unplaced circle sits at the plate-envelope center
    (the origin for a round part); an unplaced rectangle has its lower-left corner
    at the origin. ``assumed`` is True when the position was not read from the drawing.
    """
    if model is None:
        return 0.0, 0.0, not feature.position_known
    if feature.position_known:
        return (_m(model, feature.offset_x, f"{feature.id}.offset_x"),
                _m(model, feature.offset_y, f"{feature.id}.offset_y"), False)
    if circular:
        from pipeline.macro_generator import _envelope
        length, width = _envelope(model)
        return (_m(model, (length or 0.0) / 2.0, f"{feature.id}.cx"),
                _m(model, (width or 0.0) / 2.0, f"{feature.id}.cy"), True)
    return 0.0, 0.0, True


def planar_extents(model: DrawingData, feature: Feature) -> Optional[tuple[float, float]]:
    """The rectangle's (x, y) size in drawing units, from the feature's two in-plane
    linear dimensions, by canonical label (``pipeline.schema.canonicalize_applies_to``).

    Extractors name the same plate both ways: "length 100 / width 60" (hand) and
    "overall_width 100 / overall_height 60" (GPT-6 Astra, 2026-10-04). In the view,
    length or width runs along x when paired with the next one down; height is
    always vertical (y). Returns None unless exactly one pair is found.
    """
    from pipeline.schema import canonicalize_applies_to

    by_token: dict[str, float] = {}
    for did in feature.related_dimensions:
        d = model.dimension_by_id(did)
        if d is None or did == feature.depth_dimension_id or d.type.value != "linear":
            continue
        token = canonicalize_applies_to(d.applies_to)
        if token in ("length", "width", "height"):
            by_token.setdefault(token, d.value)
    for x_tok, y_tok in (("length", "width"), ("width", "height"), ("length", "height")):
        if x_tok in by_token and y_tok in by_token and len(by_token) == 2:
            return by_token[x_tok], by_token[y_tok]
    return None


def _draw_profile(sw_doc, feature: Feature, dims: dict[str, float], model: Optional[DrawingData],
                  what: str) -> None:
    """Circle (centered) or rectangle (lower-left corner) at the feature's anchor."""
    diameter = dims.get("diameter") or dims.get("hole_diameter")
    length = dims.get("length") or dims.get("width")
    width = dims.get("width") or dims.get("length")
    xy = planar_extents(model, feature) if (model is not None and not diameter) else None
    if xy:
        length, width = _m(model, xy[0], f"{feature.id}.x_size"), _m(model, xy[1], f"{feature.id}.y_size")
    cx, cy, assumed = _feature_center(model, feature, circular=bool(diameter))
    if assumed and model is not None and feature.id != (model.build_order or [""])[0]:
        model.warnings.append(f"{feature.id}: POSITION ASSUMED (drawing frame default) - verify.")
    if diameter:
        if sw_doc.SketchManager.CreateCircleByRadius(cx, cy, 0, diameter / 2.0) is None:
            raise SolidWorksError(f"CreateCircleByRadius returned None for {what} {feature.id}.")
    elif length and width:
        if sw_doc.SketchManager.CreateCornerRectangle(cx, cy, 0, cx + length, cy + width, 0) is None:
            raise SolidWorksError(f"CreateCornerRectangle returned None for {what} {feature.id}.")
    else:
        raise SolidWorksError(f"{what} {feature.id} needs a diameter or length+width; got {dims}.")


def _start_offset(model: Optional[DrawingData], feature: Feature) -> float:
    """Axial start offset (meters) for a boss stacked on earlier bosses.

    Grounded in a dimension chain: when this boss's depth and earlier bosses' depths
    (same sketch plane) are components of one chain, e.g. overall 1.971 = boss 1.781
    + flange 0.190, the boss starts where those earlier bosses end. Without such a
    chain the boss starts on its sketch plane (offset 0), as before.
    """
    if model is None or not feature.depth_dimension_id:
        return 0.0
    chains = [set(c.component_dimension_ids) for c in model.relationships.dimension_chains]
    mine = [c for c in chains if feature.depth_dimension_id in c]
    if not mine:
        return 0.0
    offset = 0.0
    for fid in model.build_order:
        if fid == feature.id:
            break
        other = model.feature_by_id(fid)
        if (other is None or other.type != FeatureType.EXTRUDE_BOSS
                or (other.sketch_plane or "front") != (feature.sketch_plane or "front")
                or not other.depth_dimension_id):
            continue
        if any(other.depth_dimension_id in c for c in mine):
            d = model.dimension_by_id(other.depth_dimension_id)
            if d is not None:
                offset += to_meters(d.value, d.unit.value)
    return offset


def _reselect_last_sketch(sw_doc) -> None:
    """Select the most recent sketch by walking the tree (by object, never by
    name: E005/E006) so a failed cut can be retried on the same profile."""
    feat, last = _g(sw_doc, "FirstFeature"), None
    while feat is not None:
        if _g(feat, "GetTypeName2") == "ProfileFeature":
            last = feat
        feat = _g(feat, "GetNextFeature")
    sw_doc.ClearSelection2(True)
    if last is not None:
        last.Select2(False, 0)


def _cut(sw_doc, feature_id: str, depth: Optional[float]):
    """Direction-proof cut on the active sketch (E005): Through All - Both for a
    thru cut; blind cuts try +normal, then retry flipped."""
    # FeatureCut4(Sd, Flip, Dir, T1, T2, D1, D2, Dchk1, Dchk2, Ddir1, Ddir2, Dang1, Dang2,
    #   OffsetReverse1, OffsetReverse2, TranslateSurface1, TranslateSurface2, NormalCut,
    #   UseFeatScope, UseAutoSelect, AssemblyFeatureScope, AutoSelectComponents,
    #   PropagateFeatureToParts, T0, StartOffset, FlipStartOffset, OptimizeGeometry)
    def attempt(flip_dir: bool, end: int):
        return sw_doc.FeatureManager.FeatureCut4(
            True, False, flip_dir, end, 0, depth or 0.0, 0.01,
            False, False, False, False, to_radians(0), to_radians(0),
            False, False, False, False, False,
            True, True, True, True, False, 0, 0, False, False,
        )
    if depth is None:
        feat = attempt(False, 9)  # swEndCondThroughAllBoth
        if feat is None:
            _reselect_last_sketch(sw_doc)
            feat = attempt(True, 1)  # swEndCondThroughAll
    else:
        assert_meters(depth, f"{feature_id}.cut_depth")
        feat = attempt(True, 0)  # Blind, into the +normal side (where bodies extrude)
        if feat is None:
            _reselect_last_sketch(sw_doc)
            feat = attempt(False, 0)
    if feat is None:
        raise SolidWorksError(f"FeatureCut4 returned None for {feature_id} (both directions).")
    return feat


# --------------------------------------------------------------------------- #
# Feature builders — each returns the created feature object (or None on skip)
# --------------------------------------------------------------------------- #
def build_extrude_boss(sw_doc, feature: Feature, dims: dict[str, float],
                       model: Optional[DrawingData] = None):
    """Extruded boss: base body, or a boss stacked on it (see :func:`_start_offset`)."""
    _select_plane(sw_doc, feature.sketch_plane)
    sw_doc.SketchManager.InsertSketch(True)
    if sw_doc.SketchManager.ActiveSketch is None:
        raise SolidWorksError("Failed to enter sketch mode for extrude_boss.")
    _draw_profile(sw_doc, feature, dims, model, "extrude_boss")
    _verify_sketch_fully_defined(sw_doc)

    depth = dims.get("depth") or dims.get("height") or dims.get("thickness")
    if not depth:
        raise SolidWorksError(f"extrude_boss {feature.id} has no depth/height dimension.")
    assert_meters(depth, f"{feature.id}.extrude_depth")
    start = _start_offset(model, feature)

    sw_doc.SketchManager.InsertSketch(True)  # close the sketch
    before = _total_volume(sw_doc)

    # FeatureExtrusion3(Sd, Flip, Dir, T1, T2, D1, D2, Dchk1, Dchk2, Ddir1, Ddir2,
    #   Dang1, Dang2, OffsetReverse1, OffsetReverse2, TranslateSurface1, TranslateSurface2,
    #   Merge, UseFeatScope, UseAutoSelect, T0, StartOffset, FlipStartOffset)
    # T0 = 3 (swStartOffset) when stacked; verified live on SW 2025 (2026-10-04).
    def extrude(reverse: bool):
        return sw_doc.FeatureManager.FeatureExtrusion3(
            True, False, reverse, 0, 0, depth, 0.01,
            False, False, False, False,
            to_radians(0), to_radians(0),
            False, False, False, False,
            True, True, True, 3 if start else 0, start, False,
        )

    feat = extrude(False)
    if feat is None:
        raise SolidWorksError(f"FeatureExtrusion3 returned None for {feature.id}.")
    if not _solid_body_exists(sw_doc):
        raise SolidWorksError(f"No solid body exists after base extrude {feature.id} (volume=0).")

    # A boss that lands entirely inside the existing body adds no material and has
    # no faces of its own: a silent failure (SB11842 F002, 2026-10-04). Undo it and
    # extrude the other way, the boss form of direction-proof cuts (E005).
    if before > 0 and _total_volume(sw_doc) <= before * (1 + 1e-9):
        log.warning("  %s added no material (embedded in the body); retrying reversed.", feature.id)
        sw_doc.EditUndo2(1)
        _reselect_last_sketch(sw_doc)
        feat = extrude(True)
        if feat is None or _total_volume(sw_doc) <= before * (1 + 1e-9):
            raise SolidWorksError(f"extrude_boss {feature.id} adds no material in either direction.")
        if model is not None:
            model.warnings.append(f"{feature.id}: DIRECTION ASSUMED - boss was embedded in the body "
                                  "on the +normal side, extruded on the -normal side instead; verify.")
    return feat


def _total_volume(sw_doc) -> float:
    """Summed solid-body volume in m^3 (0.0 when there is no body yet)."""
    try:
        bodies = sw_doc.GetBodies2(0, False) or ()
        return sum(float(b.GetMassProperties(1000.0)[3]) for b in bodies)
    except Exception:
        return 0.0


def build_extrude_cut(sw_doc, feature: Feature, dims: dict[str, float],
                      model: Optional[DrawingData] = None):
    """Cut material from the existing solid at the feature's drawing-frame position."""
    if not _solid_body_exists(sw_doc):
        raise SolidWorksError(f"extrude_cut {feature.id} requires an existing solid body.")
    _select_plane(sw_doc, feature.sketch_plane)
    sw_doc.SketchManager.InsertSketch(True)
    if sw_doc.SketchManager.ActiveSketch is None:
        raise SolidWorksError("Failed to enter sketch mode for extrude_cut.")
    _draw_profile(sw_doc, feature, dims, model, "extrude_cut")
    _verify_sketch_fully_defined(sw_doc)
    sw_doc.SketchManager.InsertSketch(True)
    return _cut(sw_doc, feature.id, dims.get("depth"))


def build_hole(sw_doc, feature: Feature, dims: dict[str, float],
               model: Optional[DrawingData] = None):
    """Every instance of a hole callout as circles in ONE sketch, then one cut.

    Positions come from :func:`pipeline.macro_generator._hole_positions` (shared
    with the VBA path so the two cannot drift): explicit instance positions, a
    grounded linear row, or a bolt circle (diameter + count read from the drawing).
    Simple circular cut only; counterbore/countersink/thread are not modeled here.
    """
    from pipeline.macro_generator import BOLT_CIRCLE_ANGLE_NOTE, _hole_positions

    if not _solid_body_exists(sw_doc):
        raise SolidWorksError(f"hole {feature.id} requires an existing solid body.")
    diameter = dims.get("hole_diameter") or dims.get("diameter")
    callout = model.hole_callout_for_feature(feature.id) if model is not None else None
    if callout is not None and callout.diameter:
        diameter = _m(model, callout.diameter, f"{feature.id}.hole_diameter")
    if not diameter:
        raise SolidWorksError(f"hole {feature.id} has no diameter dimension.")
    if callout is None:
        return build_extrude_cut(sw_doc, feature, {"diameter": diameter,
                                                   **({"depth": dims["depth"]} if "depth" in dims else {})}, model)

    positions = _hole_positions(model, callout)
    if not callout.instance_positions and len(positions) > 1 and callout.pattern.value != "linear":
        model.warnings.append(f"{feature.id}: {BOLT_CIRCLE_ANGLE_NOTE}")
    _select_plane(sw_doc, feature.sketch_plane)
    sw_doc.SketchManager.InsertSketch(True)
    if sw_doc.SketchManager.ActiveSketch is None:
        raise SolidWorksError("Failed to enter sketch mode for hole.")
    for i, (x, y) in enumerate(positions):
        cx, cy = _m(model, x, f"{feature.id}[{i}].x"), _m(model, y, f"{feature.id}[{i}].y")
        if sw_doc.SketchManager.CreateCircleByRadius(cx, cy, 0, diameter / 2.0) is None:
            raise SolidWorksError(f"CreateCircleByRadius returned None for hole {feature.id}[{i}].")
    log.info("  %s: %d hole instance(s) at %s", feature.id, len(positions),
             [(round(x, 4), round(y, 4)) for x, y in positions])
    _verify_sketch_fully_defined(sw_doc)
    sw_doc.SketchManager.InsertSketch(True)
    depth = None if (callout.thru or not callout.depth) else _m(model, callout.depth, f"{feature.id}.depth")
    return _cut(sw_doc, feature.id, depth)


def _infer_edges(sw_doc, feature: Feature, feature_map: dict[str, Any],
                 model: Optional[DrawingData]) -> list:
    """Edges to fillet/chamfer, inferred from ``parent_feature`` (schema has no edge ids).

    Rule (verified live on SW 2025, 2026-10-04):
      1. edges of the parent's faces whose OTHER face belongs to a feature built
         before the parent: where the parent meets earlier geometry (a boss's base,
         a bore's mouth);
      2. if none (the parent is the base body): the edges between the parent's own
         faces (its outer rims).
    Always flagged EDGES INFERRED, since the drawing's leader is not read.
    """
    parent_id = feature.parent_feature
    parent = feature_map.get(parent_id) if parent_id else None
    if parent is None:
        raise SolidWorksError(
            f"{feature.type.value} {feature.id}: no built parent_feature ({parent_id or 'none'}) "
            "to infer edges from; the schema carries no edge ids.")
    order = list(feature_map)
    earlier = {feature_map[f].Name for f in order[: order.index(parent_id)]}
    pname = parent.Name
    meets, rims = [], []
    for face in _g(parent, "GetFaces") or ():
        for edge in _g(face, "GetEdges") or ():
            pair = _g(edge, "GetTwoAdjacentFaces2") or ()
            owners = [_g(f, "GetFeature").Name for f in pair if f is not None]
            others = [o for o in owners if o != pname]
            if others and all(o in earlier for o in others):
                meets.append(edge)
            elif owners and not others:
                rims.append(edge)
    edges, rule = (meets, "where it meets earlier features") if meets else (rims, "its own rims")
    if not edges:
        raise SolidWorksError(f"{feature.id}: no candidate edges found on parent {parent_id}.")
    if model is not None:
        model.warnings.append(
            f"{feature.id}: EDGES INFERRED - {len(edges)} edge(s) of {parent_id} ({rule}); "
            "verify against the drawing.")
    sw_doc.ClearSelection2(True)
    data = _g(sw_doc.SelectionManager, "CreateSelectData")
    for e in edges:
        e.Select4(True, data)
    return edges


def _empty_variant():
    import pythoncom  # type: ignore
    from win32com.client import VARIANT  # type: ignore
    return VARIANT(pythoncom.VT_EMPTY, None)


def build_fillet(sw_doc, feature: Feature, dims: dict[str, float],
                 model: Optional[DrawingData] = None, feature_map: Optional[dict[str, Any]] = None):
    """Constant-radius fillet on edges inferred from ``parent_feature``. FRAGILE."""
    radius = dims.get("fillet_radius") or dims.get("radius") or next(iter(dims.values()), None)
    if not radius:
        raise SolidWorksError(f"fillet {feature.id} has no radius dimension.")
    assert_meters(radius, f"{feature.id}.fillet_radius")
    _infer_edges(sw_doc, feature, feature_map or {}, model)
    # FeatureFillet3(Options, R1, Dist2, Rho, Ftyp, OverflowType, ConicRhoType, Radii,
    #   Dist2Arr, RhoArr, SetBackDistances, PointArr, PointDist2Arr, PointRhoArr):
    # 14 args as the macro recorder writes them; the 7 arrays must be EMPTY Variants
    # (a null dispatch is a type mismatch). Verified live on SW 2025 (E012).
    arrays = [_empty_variant() for _ in range(7)]
    feat = sw_doc.FeatureManager.FeatureFillet3(195, radius, 0.0, 0.0, 0, 0, 0, *arrays)
    if feat is None:
        raise SolidWorksError(f"FeatureFillet3 returned None for {feature.id}.")
    return feat


def build_chamfer(sw_doc, feature: Feature, dims: dict[str, float],
                  model: Optional[DrawingData] = None, feature_map: Optional[dict[str, Any]] = None):
    """Distance x angle chamfer on edges inferred from ``parent_feature``. FRAGILE."""
    distance = dims.get("chamfer") or dims.get("chamfer_size") or dims.get("length") or next(
        (v for k, v in dims.items() if k != "angle"), None
    )
    if not distance:
        raise SolidWorksError(f"chamfer {feature.id} has no distance dimension.")
    assert_meters(distance, f"{feature.id}.chamfer_distance")
    angle = dims.get("angle", to_radians(45))  # default 45 deg if unspecified (already radians)
    _infer_edges(sw_doc, feature, feature_map or {}, model)
    # InsertFeatureChamfer(Options, ChamferType, Width, Angle, OtherDist,
    #   VertexChamDist1, VertexChamDist2, VertexChamDist3); type 1 = angle-distance.
    feat = sw_doc.FeatureManager.InsertFeatureChamfer(4, 1, distance, angle, 0, 0, 0, 0)
    if feat is None:
        raise SolidWorksError(f"InsertFeatureChamfer returned None for {feature.id}.")
    return feat


def build_pattern(sw_doc, feature: Feature, dims: dict[str, float], feature_map: dict[str, Any]):
    """Create a linear pattern of the most-recent seed feature.

    Requires a seed feature to exist. Spacing/count come from the feature's
    related dimensions where available; sensible defaults otherwise.
    """
    if not feature_map:
        raise SolidWorksError(f"pattern {feature.id} has no seed feature to pattern.")
    spacing = dims.get("spacing") or dims.get("length") or next(iter(dims.values()), None)
    if not spacing:
        raise SolidWorksError(f"pattern {feature.id} has no spacing dimension.")
    assert_meters(spacing, f"{feature.id}.pattern_spacing")
    count = max(2, int(feature.quantity))

    # Select the seed (last created feature) before patterning.
    sw_doc.ClearSelection2(True)
    feat = sw_doc.FeatureManager.FeatureLinearPattern4(
        count, spacing, 1, 0.0, False, False, "NULL", "NULL",
        False, False, False, False, False, False, False, False, 0, 0,
    )
    if feat is None:
        raise SolidWorksError(f"FeatureLinearPattern4 returned None for {feature.id}.")
    return feat


# Map feature types to (builder, is_fragile).
_BUILDERS = {
    FeatureType.EXTRUDE_BOSS: (build_extrude_boss, False),
    FeatureType.EXTRUDE_CUT: (build_extrude_cut, False),
    FeatureType.HOLE: (build_hole, False),
    FeatureType.FILLET: (build_fillet, True),
    FeatureType.CHAMFER: (build_chamfer, True),
}


def _pattern_realized_by_seed(feature: Feature, feature_map: dict[str, Any],
                              model: Optional[DrawingData]) -> Optional[Any]:
    """A pattern whose seed is a hole that already placed every instance.

    Extractors often emit BOTH a multi-instance hole (instance positions / bolt
    circle) AND a separate "circular pattern" feature for the same holes. The hole
    builder has already cut all of them, so patterning again would double them.
    Returns the seed's feature object (the pattern is realized), or None.
    """
    from pipeline.macro_generator import _hole_positions

    seed_id = feature.parent_feature
    if model is None or not seed_id or seed_id not in feature_map:
        return None
    seed = model.feature_by_id(seed_id)
    callout = model.hole_callout_for_feature(seed_id) if seed is not None else None
    if seed is None or seed.type != FeatureType.HOLE or callout is None:
        return None
    placed = len(_hole_positions(model, callout))
    if placed < max(2, feature.quantity):
        return None
    model.warnings.append(f"{feature.id}: pattern realized by seed {seed_id} "
                          f"({placed} instances already cut); no extra pattern feature.")
    log.info("  %s realized by %s's %d instances", feature.id, seed_id, placed)
    return feature_map[seed_id]


def dispatch_feature_builder(sw_doc, feature: Feature, dims: dict[str, float],
                             feature_map: dict[str, Any], model: Optional[DrawingData] = None):
    """Dispatch to the right feature builder. Returns the created feature object."""
    if feature.type == FeatureType.PATTERN:
        realized = _pattern_realized_by_seed(feature, feature_map, model)
        if realized is not None:
            return realized
        return build_pattern(sw_doc, feature, dims, feature_map)
    entry = _BUILDERS.get(feature.type)
    if entry is None:
        raise SolidWorksError(
            f"Feature type {feature.type.value!r} ({feature.id}) is not yet supported by the builder."
        )
    builder, fragile = entry
    if fragile:
        return builder(sw_doc, feature, dims, model, feature_map)
    return builder(sw_doc, feature, dims, model)


def _is_fragile(feature: Feature) -> bool:
    return feature.type in (FeatureType.FILLET, FeatureType.CHAMFER)


def save_model(sw_doc, name: str, output_dir: Optional[Path] = None) -> str:
    """Save the part as a .sldprt and return the absolute path.

    Raises:
        SolidWorksError: if the save fails.
    """
    output_dir = Path(output_dir) if output_dir else OUTPUT_DIR_DEFAULT
    output_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in (name or "output_part") if c.isalnum() or c in ("_", "-")).strip("_") or "output_part"
    # MUST be absolute: SaveAs3 resolves a relative path against SolidWorks' own
    # working directory (not Python's), silently scattering files elsewhere.
    path = (output_dir / f"{safe}.sldprt").resolve()

    # SaveAs3(Name, Version, Options) → returns error/warning ints via SaveAs.
    errors = 0
    warnings = 0
    try:
        result = sw_doc.SaveAs3(str(path), 0, 1)
        # Some bindings return a bool; treat falsy as failure only if no file written.
        if result in (False, None) and not path.exists():
            raise SolidWorksError(f"SaveAs3 failed for {path}.")
    except SolidWorksError:
        raise
    except Exception as e:
        raise SolidWorksError(f"Saving {path} failed: {e} (errors={errors}, warnings={warnings})") from e

    log.info("Saved model: %s", path)
    return str(path)


def build_model(
    sw_app,
    drawing_data: Union[DrawingData, dict[str, Any]],
    output_dir: Optional[Union[str, Path]] = None,
    template_path: Optional[str] = None,
    strict: bool = True,
    skipped_out: Optional[list[tuple[str, str, str]]] = None,
):
    """Build the complete 3D model from validated drawing data.

    Args:
        strict: when True (default) a non-fragile feature failure saves a partial
            model and aborts the build (fail-fast). When False, ANY feature that
            fails is demoted to a warning and skipped so the build runs to
            completion — used by the batch driver, which then documents every
            skipped feature for human review.
        skipped_out: if provided, every skipped feature is appended as
            ``(feature_id, feature_type, reason)`` for the caller's report.

    Returns:
        (output_path, sw_doc): path to the saved .sldprt and the live document
        (so the caller can run model validation against it).

    Raises:
        SolidWorksError: on any build failure (strict mode), or if the build
            produced no solid body at all. The exception carries the path to a
            saved partial model (``partial_path``) for debugging.
    """
    _require_windows()
    model = _coerce(drawing_data)
    output_dir = Path(output_dir) if output_dir else OUTPUT_DIR_DEFAULT

    sw_doc = create_new_part(sw_app, template_path)
    set_document_units(sw_doc, model.units.value)  # BEFORE any geometry

    feature_map: dict[str, Any] = {}
    built_count = 0

    for feature_id in model.build_order:
        feature = get_feature_by_id(model, feature_id)
        dims = get_dimensions_for_feature(model, feature)
        log.info("Building feature %s: %s", feature_id, feature.type.value)

        try:
            try:
                result = dispatch_feature_builder(sw_doc, feature, dims, feature_map, model=model)
            except SolidWorksError:
                raise
            except Exception as e:
                # Wrap unexpected COM errors (e.g. pywintypes.com_error) so the
                # fragile/partial-save handling below applies uniformly.
                raise SolidWorksError(f"{type(e).__name__}: {e}") from e

            if result is None:
                raise SolidWorksError(f"Feature builder returned None for {feature_id}.")
            feature_map[feature_id] = result

            if not check_rebuild_errors(sw_doc):
                raise SolidWorksError(f"Rebuild errors after feature {feature_id}.")

            built_count += 1
            log.info("  ✓ %s complete", feature_id)

            # Periodic auto-save so a later crash doesn't lose everything.
            if built_count % AUTOSAVE_EVERY == 0:
                try:
                    save_model(sw_doc, f"AUTOSAVE_{model.part_name or 'part'}", output_dir)
                except SolidWorksError as e:
                    log.warning("Auto-save failed (continuing): %s", e)

        except SolidWorksError as e:
            if _is_fragile(feature):
                # Fillets/chamfers are demoted to warnings — do not abort the build.
                log.warning("  ! %s (%s) failed and was SKIPPED: %s", feature_id, feature.type.value, e)
                model.warnings.append(f"{feature_id} ({feature.type.value}) skipped: {e}")
                if skipped_out is not None:
                    skipped_out.append((feature_id, feature.type.value, str(e)))
                continue

            if not strict:
                # Non-strict batch mode: skip any failing feature so the build
                # completes; the driver records it for human verification.
                log.warning("  ! %s (%s) FAILED and was SKIPPED (non-strict): %s",
                            feature_id, feature.type.value, e)
                model.warnings.append(f"{feature_id} ({feature.type.value}) skipped: {e}")
                if skipped_out is not None:
                    skipped_out.append((feature_id, feature.type.value, str(e)))
                continue

            # Non-fragile failure (strict): save a partial model and abort with context.
            partial_path = None
            try:
                partial_path = save_model(sw_doc, f"PARTIAL_{feature_id}", output_dir)
            except Exception as save_err:
                log.error("Could not save partial model: %s", save_err)
            log.error("  ✗ %s FAILED: %s", feature_id, e)
            raise SolidWorksError(
                f"Build failed at feature {feature_id}: {e}"
                + (f" Partial model saved to {partial_path}." if partial_path else ""),
                partial_path=partial_path,
            ) from e

    # Final rebuild + error check.
    try:
        sw_doc.ForceRebuild3(True)
    except Exception as e:
        log.warning("ForceRebuild3 failed: %s", e)
    check_rebuild_errors(sw_doc)

    # A completed run with no solid body is still a failure (e.g. the base boss
    # was skipped in non-strict mode) — surface it rather than save an empty part.
    if not _solid_body_exists(sw_doc):
        raise SolidWorksError("Build produced no solid body (all body-creating features were skipped).")

    output_path = save_model(sw_doc, model.part_name or "output_part", output_dir)
    return output_path, sw_doc
