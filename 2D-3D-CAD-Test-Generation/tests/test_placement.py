"""Placement logic shared by the COM builder and the VBA generator (runs on any OS)."""
import copy
import json
import math
from pathlib import Path

import pytest

from pipeline.macro_generator import _bolt_circle_diameter, _hole_positions
from pipeline.schema import DrawingData
from pipeline.solidworks_builder import _feature_center, _start_offset

SB11033 = Path(__file__).resolve().parent.parent / "output" / "SB11033" / "SB11033_extraction.json"
IN = 0.0254


def _raw() -> dict:
    return json.loads(SB11033.read_text(encoding="utf-8"))


def _model(raw=None) -> DrawingData:
    return DrawingData.model_validate(raw or _raw())


def test_bolt_circle_diameter_found_by_label():
    m = _model()
    assert _bolt_circle_diameter(m, m.hole_callouts[0]) == pytest.approx(1.562)


def test_bolt_circle_places_feature_quantity_holes_when_no_instance_positions():
    raw = _raw()
    raw["hole_callouts"][0]["instance_positions"] = []
    m = _model(raw)
    pts = _hole_positions(m, m.hole_callouts[0])
    # callout qty is 1 but feature F004 says 4 -> 4 holes on r = 0.781, from 0 deg
    assert len(pts) == 4
    for (x, y), ang in zip(pts, (0, 90, 180, 270)):
        assert x == pytest.approx(0.781 * math.cos(math.radians(ang)), abs=1e-9)
        assert y == pytest.approx(0.781 * math.sin(math.radians(ang)), abs=1e-9)


def test_instance_positions_win_over_bolt_circle():
    m = _model()
    assert _hole_positions(m, m.hole_callouts[0]) == [(0.781, 0.0), (0.0, 0.781), (-0.781, 0.0), (0.0, -0.781)]


def test_no_bolt_circle_label_no_invented_circle():
    raw = _raw()
    raw["hole_callouts"][0]["instance_positions"] = []
    for d in raw["dimensions"]:
        if d["id"] == "D003":
            d["applies_to"] = "reference_diameter"
    m = _model(raw)
    assert len(_hole_positions(m, m.hole_callouts[0])) == 1  # single fallback, never a guessed circle


def test_stacked_boss_starts_where_chain_partner_ends():
    m = _model()  # chain D004 (1.971) = D005 (boss 1.781) + D007 (flange 0.190)
    assert _start_offset(m, m.feature_by_id("F001")) == 0.0
    assert _start_offset(m, m.feature_by_id("F003")) == pytest.approx(0.190 * IN)


def test_boss_without_chain_starts_on_sketch_plane():
    raw = _raw()
    raw["relationships"]["dimension_chains"] = []
    m = _model(raw)
    assert _start_offset(m, m.feature_by_id("F003")) == 0.0


def test_rectangle_unplaced_anchor_is_drawing_frame_origin():
    m = _model()
    f = copy.deepcopy(m.feature_by_id("F002"))
    f.position_known = False
    assert _feature_center(m, f, circular=False) == (0.0, 0.0, True)
    f.position_known, f.offset_x, f.offset_y = True, 1.0, 0.5
    x, y, assumed = _feature_center(m, f, circular=True)
    assert (x, y, assumed) == (pytest.approx(IN), pytest.approx(0.5 * IN), False)


def test_resolver_keeps_grounded_bolt_circle_hole_and_restores_build_order():
    from run_models import resolve_unknowns
    raw = _raw()  # F004 is NOT in the extracted build_order
    decisions, _ = resolve_unknowns(raw, "SB11033")
    bo = raw["build_order"]
    assert "F004" in bo
    assert bo.index("F004") < min(bo.index(f) for f in ("F005", "F006", "F007"))
    assert any("F004" in d and "added to the build" in d for d in decisions)


def test_resolver_drops_hole_with_no_grounded_position():
    from run_models import resolve_unknowns
    raw = _raw()
    raw["hole_callouts"][0]["instance_positions"] = []
    raw["hole_callouts"][0]["position_known"] = False
    for d in raw["dimensions"]:
        if d["id"] == "D003":
            d["applies_to"] = "reference_diameter"
    raw["features"] = [f for f in raw["features"]]
    next(f for f in raw["features"] if f["id"] == "F004")["position_known"] = False
    resolve_unknowns(raw, "SB11033")
    assert "F004" not in raw["build_order"]


def test_negative_drawing_coordinates_convert_with_sign():
    from pipeline.solidworks_builder import _m
    m = _model()
    assert _m(m, -0.781, "x") == pytest.approx(-0.781 * IN)
    assert _m(m, 0.0, "x") == 0.0


def test_bolt_circle_given_as_radius_is_doubled():
    raw = _raw()
    raw["hole_callouts"][0]["instance_positions"] = []
    for d in raw["dimensions"]:
        if d["id"] == "D003":
            d.update(type="linear", value=0.781, applies_to="bolt_circle_radius")
    m = _model(raw)
    assert _bolt_circle_diameter(m, m.hole_callouts[0]) == pytest.approx(1.562)
    assert _hole_positions(m, m.hole_callouts[0])[0] == (pytest.approx(0.781), pytest.approx(0.0))


def test_resolver_keeps_pattern_whose_seed_hole_is_grounded():
    from run_models import resolve_unknowns
    raw = _raw()
    raw["features"].append({"id": "F008", "type": "pattern", "description": "circular pattern of F004",
                            "related_dimensions": ["D003"], "sketch_plane": "front",
                            "depth_dimension_id": "", "parent_feature": "F004", "offset_x": 0.0,
                            "offset_y": 0.0, "position_known": False, "quantity": 4})
    resolve_unknowns(raw, "SB11033")
    bo = raw["build_order"]
    assert "F008" in bo and bo.index("F004") < bo.index("F008")


# --- plate labels: length/width vs width/height (DEMO-PLATE-001, 2026-10-04) --- #
DEMO = Path(__file__).resolve().parent.parent / "demo" / "simple_plate"


def _demo(name):
    return json.loads((DEMO / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["extraction_no_api.json", "extraction_astra.json"])
def test_planar_extents_maps_both_label_styles_to_100_by_60(name):
    from pipeline.solidworks_builder import planar_extents
    m = DrawingData.model_validate(_demo(name))
    assert planar_extents(m, m.feature_by_id("F001")) == (100.0, 60.0)


def test_resolver_keeps_width_height_labeled_base():
    from run_models import resolve_unknowns
    raw = _demo("extraction_astra.json")   # overall_width 100 / overall_height 60
    resolve_unknowns(raw, "DEMO-PLATE-001")
    assert raw["build_order"][0] == "F001"


def test_planar_extents_none_when_ambiguous():
    from pipeline.solidworks_builder import planar_extents
    m = DrawingData.model_validate(_demo("extraction_no_api.json"))
    f = m.feature_by_id("F001").model_copy(update={"related_dimensions": ["D001", "D003"]})
    assert planar_extents(m, f) is None  # length only (D003 is the depth)
