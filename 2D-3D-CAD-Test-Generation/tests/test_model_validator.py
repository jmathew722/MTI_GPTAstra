"""Post-build validation: completeness must fail a part that is missing features."""
import json
from pathlib import Path
from types import SimpleNamespace as NS

from pipeline.model_validator import check_completeness, validate_model
from pipeline.schema import DrawingData

SB11033 = Path(__file__).resolve().parent.parent / "output" / "SB11033" / "SB11033_extraction.json"


def _model() -> DrawingData:
    return DrawingData.model_validate(json.loads(SB11033.read_text(encoding="utf-8")))


def _doc(extents_m):
    """Fake SolidWorks part: one body with the given bbox extents (meters)."""
    x, y, z = extents_m
    body = NS(GetMassProperties=lambda d: [0, 0, 0, 1e-5, 1e-3, 0.01],
              GetBodyBox=lambda: [0, 0, 0, x, y, z])
    return NS(GetBodies2=lambda t, v: (body,))


def test_june_sb11033_build_is_incomplete():
    # The 2026-06-18 COM run built F001/F003/F002 and reported PASSED.
    r = check_completeness(_model(), ["F001", "F003", "F002"])
    assert r["built"] == 3 and r["expected"] == 7
    assert r["missing"] == ["F004", "F005", "F006", "F007"]
    assert any("F004 hole x4 not built (not in build_order)" in f for f in r["failed"])
    assert r["failed"][0].startswith("Feature completeness: 3/7")


def test_complete_build_passes_completeness():
    m = _model()
    r = check_completeness(m, [f.id for f in m.features])
    assert not r["failed"] and r["passed"][0].startswith("Feature completeness: 7/7")


def test_validate_model_fails_incomplete_part_even_if_body_exists():
    in_ = 0.0254
    rep = validate_model(_doc((1.938 * in_, 1.938 * in_, 1.971 * in_)), _model(),
                         built_feature_ids=["F001", "F003", "F002"])
    assert rep["ok"] is False
    assert rep["completeness"]["missing"] == ["F004", "F005", "F006", "F007"]


def test_overall_length_label_is_checked_against_bbox():
    # June's body was 1.781" long (boss overlapped the flange); drawing says 1.971 overall.
    m = _model()
    in_ = 0.0254
    rep = validate_model(_doc((1.938 * in_, 1.938 * in_, 1.781 * in_)), m,
                         built_feature_ids=[f.id for f in m.features])
    assert rep["ok"] is False
    assert any(f.startswith("length:") for f in rep["failed"])


def test_without_built_list_completeness_is_flagged_not_silently_passed():
    in_ = 0.0254
    rep = validate_model(_doc((1.938 * in_, 1.938 * in_, 1.971 * in_)), _model())
    assert any("completeness NOT checked" in w for w in rep["warnings"])
