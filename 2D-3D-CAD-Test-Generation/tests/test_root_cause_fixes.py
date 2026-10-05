"""Regression tests for the 2026-10-04 failure deep dive (STATE.md 3.0, fixes F1-F6).

All run on any OS against the saved extractions. They need no SolidWorks and no API.
"""
import json
from pathlib import Path

import pytest

from pipeline.fasteners import nominal_size, shcs_counterbore, size_from_text
from pipeline.macro_generator import _hole_positions, _reframe, part_center, round_base
from pipeline.schema import DrawingData
from pipeline.solidworks_builder import _feature_center, get_dimensions_for_feature
from pipeline.validator import run_verification
from run_models import resolve_unknowns

OUT = Path(__file__).resolve().parent.parent / "output"
IN = 0.0254


def _load(rel: str) -> dict:
    return json.loads((OUT / rel).read_text(encoding="utf-8"))


def _resolved(rel: str) -> DrawingData:
    raw = _load(rel)
    resolve_unknowns(raw, Path(rel).parent.name)
    return DrawingData.model_validate(raw)


# --- F1: one frame per round part -------------------------------------------- #
def test_round_base_detected_and_is_part_center():
    m = _resolved("A040911E/A040911E_extraction.json")
    assert round_base(m) == (0.0, 0.0, pytest.approx(3.249))
    assert part_center(m) == (0.0, 0.0)  # NOT (0, 1.375) from the mislabeled 2.75 "width"


def test_unplaced_round_base_is_centered_on_axis_not_envelope():
    m = _resolved("A040911E/A040911E_extraction.json")
    f = m.feature_by_id("F001")
    x, y, _ = _feature_center(m, f, circular=True)
    assert (x, y) == (0.0, 0.0)


def test_shaft_not_offset_by_its_length():
    m = _resolved("SB11780/SB11780_extraction.json")
    x, y, _ = _feature_center(m, m.feature_by_id("F001"), circular=True)
    assert (x, y) == (0.0, 0.0)  # was (38.44 in, 0): centered on the 76.88 length


def test_plate_parts_keep_the_envelope_center():
    raw = json.loads((Path(__file__).resolve().parent.parent / "demo" / "simple_plate"
                      / "extraction_no_api.json").read_text(encoding="utf-8"))
    m = DrawingData.model_validate(raw)
    assert round_base(m) is None and part_center(m) == (50.0, 30.0)


# --- F6: frames inside one callout + in-part gate ---------------------------- #
def test_corner_frame_bore_is_moved_onto_the_axis():
    m = _resolved("astra_2026-10-04/SB11842/SB11842_extraction.json")
    h = next(h for h in m.hole_callouts if h.feature_ref == "F002")
    assert h.instance_positions == [[2.5, 2.5]]
    pts, fixed = _reframe(m, [(2.5, 2.5)])
    assert fixed and pts == [(0.0, 0.0)]
    assert _hole_positions(m, h) == [(0.0, 0.0)]


def test_gate_blocks_holes_outside_part_in_both_frames():
    raw = _load("astra_2026-10-04/SB11842/SB11842_extraction.json")
    resolve_unknowns(raw, "SB11842")
    h = next(h for h in raw["hole_callouts"] if h["feature_ref"] == "F002")
    h["instance_positions"] = [[9.0, 9.0]]
    _, report = run_verification(raw)
    assert not report.ok and any("outside the part" in e for e in report.errors)


# --- F3/F4: callout synthesis + fastener table ------------------------------- #
def test_fastener_table_and_text_parsing():
    assert shcs_counterbore(0.25) == (0.281, 0.438, 0.250)
    assert shcs_counterbore(0.312) == (0.344, 0.531, 0.312)  # .312 snaps to 5/16
    assert nominal_size(0.272) is None
    assert size_from_text("DR. & C'BORE .38 DP. FOR .250 SOC. HD. CAP SCR. 3-HLS") == 0.25
    assert size_from_text("4X FOR 5/16 SOCKET HEAD CAP SCREW") == 0.3125
    assert size_from_text("Ø.250 THRU") is None  # not a cap-screw callout


def test_sb11842_bolt_holes_synthesized_grounded_and_counterbored():
    raw = _load("astra_2026-10-04/SB11842/SB11842_extraction.json")
    decisions, concerns = resolve_unknowns(raw, "SB11842")
    h = next(h for h in raw["hole_callouts"] if h["feature_ref"] == "F003")
    assert h["diameter"] == 0.344 and h["type"] == "counterbore"       # 5/16 SHCS
    assert h["cbore_diameter"] == 0.531 and h["cbore_depth"] == 0.38   # depth from the drawing
    assert "F003" in raw["build_order"] and "F004" in raw["build_order"]
    assert any("STANDARD-DERIVED" in d for d in decisions)
    assert any("VERIFY F003" in c for c in concerns)
    m = DrawingData.model_validate(raw)
    pts = _hole_positions(m, m.hole_callout_by_id(h["id"]))
    assert len(pts) == 4 and all(abs((x * x + y * y) ** 0.5 - 2.125) < 1e-9 for x, y in pts)


def test_a040911e_june_values_read_from_drawing_are_never_overwritten_by_the_table():
    raw = _load("A040911E/A040911E_extraction.json")
    decisions, _ = resolve_unknowns(raw, "A040911E")
    h = raw["hole_callouts"][0]
    assert h["diameter"] == 0.272 and h["cbore_diameter"] == 0.4375  # extracted values kept
    assert h["cbore_depth"] == 0.38                                  # depth from the drawing
    assert not any("STANDARD-DERIVED" in d and "F003" in d for d in decisions)


def test_no_screw_named_means_no_table_values():
    raw = _load("SB11033/SB11033_extraction.json")
    resolve_unknowns(raw, "SB11033")
    h = raw["hole_callouts"][0]
    assert h["diameter"] == 0.218 and not h["cbore_diameter"]


# --- F3 guard: never synthesize a callout without a diameter (R6) ------------- #
def test_cropped_callout_escalates_instead_of_blocking_the_part():
    raw = _load("astra_2026-10-04/A040911E/A040911E_extraction.json")
    _, concerns = resolve_unknowns(raw, "A040911E")
    assert not any(h["feature_ref"] == "F005" for h in raw["hole_callouts"])
    assert any(c.startswith("ESCALATE F005") for c in concerns)
    _, report = run_verification(raw)
    assert report.ok, report.errors      # one unknown hole no longer blocks the whole part


# --- turned-part guard: a neck is not a cross hole ---------------------------- #
def test_neck_on_turned_part_is_refused_not_drilled_sideways():
    from pipeline.solidworks_builder import turned_feature_reason
    m = _resolved("astra_2026-10-04/SB11780/SB11780_extraction.json")
    neck = m.feature_by_id("F003")
    reason = turned_feature_reason(m, neck, get_dimensions_for_feature(m, neck))
    assert reason and "revolved cut" in reason


def test_bore_on_the_end_plane_is_not_refused():
    from pipeline.solidworks_builder import turned_feature_reason
    m = _resolved("A040921E/A040921E_extraction.json")
    bore = m.feature_by_id("F002")
    assert turned_feature_reason(m, bore, get_dimensions_for_feature(m, bore)) is None


# --- pattern through one placed hole, confirmed by the drawing's dims --------- #
def test_three_holes_through_placed_seed_match_drawing_dims():
    from pipeline.macro_generator import _circle_from_seed
    raw = _load("astra_2026-10-04/A040911E/A040911E_extraction.json")
    resolve_unknowns(raw, "A040911E")
    assert "F003" in raw["build_order"]
    m = DrawingData.model_validate(raw)
    h = next(h for h in m.hole_callouts if h.feature_ref == "F003")
    pts = _circle_from_seed(m, h)
    assert pts is not None and len(pts) == 3
    assert pts[0] == (pytest.approx(0.0, abs=1e-9), pytest.approx(2.875))
    for x, y in pts[1:]:
        assert abs(abs(x) - 2.49) < 0.003 and abs(y + 1.438) < 0.003  # drawing dims D005/D004


def test_seed_circle_rejected_when_dims_do_not_confirm_it():
    from pipeline.macro_generator import _circle_from_seed
    raw = _load("astra_2026-10-04/A040911E/A040911E_extraction.json")
    for d in raw["dimensions"]:
        if d["id"] in ("D004", "D005", "D020"):
            d["value"] = 9.9   # the other holes' coordinates no longer match equal spacing
    resolve_unknowns(raw, "A040911E")
    m = DrawingData.model_validate(raw)
    h = next((h for h in m.hole_callouts if h.feature_ref == "F003"), None)
    assert h is None or _circle_from_seed(m, h) is None
