"""MTI Std 202.02.0003 loader and hole matcher (pipeline/mti_standards.py).

The real table is confidential and never in the repo, so these tests use a synthetic
table with the same layout (values are illustrative, not MTI's).
"""
import json

import pytest

from pipeline import fasteners, mti_standards

SYNTH = {
    "inch": {"columns": ["size", "nominal", "preferred", "tap_drill", "clearance_normal", "cbore_d", "cbore_depth"],
             "rows": [["1/4", 0.25, True, 0.201, 0.266, 0.44, 0.30],
                      ["5/16", 0.3125, True, 0.257, 0.330, 0.53, 0.37]]},
    "metric": {"columns": ["size", "nominal", "preferred", "tap_drill", "clearance_normal", "clearance_loose",
                           "cbore_d", "cbore_depth"],
               "rows": [["M6", 6, True, 5.0, 6.4, 7.0, 11, 6.5],
                        ["M8", 8, True, 6.8, 8.4, 10, 15, 8.6]]},
}


@pytest.fixture
def synth(tmp_path, monkeypatch):
    p = tmp_path / "std.local.json"
    p.write_text(json.dumps(SYNTH), encoding="utf-8")
    monkeypatch.setenv("MTI_STANDARD_PATH", str(p))
    return p


def test_absent_table_means_no_matches_and_the_generic_chart():
    assert not mti_standards.available()
    assert mti_standards.match_hole(0.266, "inch") == []
    assert fasteners.shcs_counterbore(0.25) == fasteners.SHCS_INCH[0.25]
    assert fasteners.table_source() == fasteners.SOURCE


def test_plain_inch_hole_is_matched_to_its_screw(synth):
    best = mti_standards.match_hole(0.266, "inch")[0]
    assert (best.size, best.system, best.role) == ("1/4", "inch", "clearance_normal")
    assert "STANDARD-DERIVED" in best.note and "1/4" in best.note


def test_tap_drill_is_recognized(synth):
    assert mti_standards.match_hole(0.257, "inch")[0].role == "tap_drill"


def test_metric_hole_on_an_inch_drawing_ranks_after_inch_hardware(synth):
    # 8.4 mm = .3307": within tolerance of the synthetic 5/16 clearance (.330) and M8's
    matches = mti_standards.match_hole(8.4 / 25.4, "inch")
    assert [m.size for m in matches][:2] == ["5/16", "M8"]


def test_metric_drawing_prefers_metric(synth):
    assert mti_standards.match_hole(10.0, "mm")[0].size == "M8"          # loose clearance
    assert mti_standards.match_hole(10.0, "mm")[0].role == "clearance_loose"


def test_no_match_outside_tolerance(synth):
    assert mti_standards.match_hole(0.300, "inch") == []


def test_mti_counterbore_wins_over_the_generic_chart(synth):
    assert fasteners.shcs_counterbore(0.25) == (0.266, 0.44, 0.30)
    assert fasteners.table_source() == mti_standards.SOURCE
    assert fasteners.shcs_counterbore(0.375) == fasteners.SHCS_INCH[0.375]   # not in MTI table -> generic


def test_row_lookup(synth):
    assert mti_standards.row("m8")["tap_drill"] == 6.8
    assert mti_standards.row("#4") is None


def test_the_real_table_is_never_tracked_by_git():
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    out = subprocess.run(["git", "check-ignore", "-q", str(mti_standards.DEFAULT_PATH)], cwd=root)
    if out.returncode == 128:
        pytest.skip("not a git checkout")
    assert out.returncode == 0, "config/mti/*.local.json must be gitignored (confidential)"


# --------------------------------------------------------------------------- #
# Advisory MTI review of a BuildPlan (pipeline/ir/mti_review.py)
# --------------------------------------------------------------------------- #
from pipeline.ir.model import BuildPlan  # noqa: E402
from pipeline.ir.mti_review import review  # noqa: E402


def _plan(features):
    return BuildPlan.model_validate({"part": "P", "frame": {"origin_kind": "corner", "units": "inch"},
                                     "features": features})


BASE = {"id": "F001", "kind": "prism", "profile": {"shape": "rect", "w": "D001", "h": "D001"}, "depth": "D002"}
DIMS = {"D001": 4.0, "D002": 0.5, "D003": 0.266, "D004": 0.44, "D005": 0.3}


def _hole(fid, d="D003", **spec):
    return {"id": fid, "kind": "hole", "on": "face(F001,+Z)", "u": "D002", "v": "D002",
            "spec": {"type": spec.pop("type", "thru"), "d": d, **spec}}


def codes(findings):
    return [f.code for f in findings]


def test_review_proposes_hole_wizard_for_a_bolt_clearance_hole(synth):
    f = review(_plan([BASE, _hole("F002")]), DIMS)
    assert codes(f) == ["mti_hole_wizard"] and "clearance (normal) for 1/4" in f[0].message


def test_review_checks_the_counterbore_against_the_same_screw(synth):
    f = review(_plan([BASE, _hole("F002", type="cbore", cbore_d="D004", cbore_depth="D002")]), DIMS)
    assert "counterbore Ø0.44 matches" in f[0].message
    f = review(_plan([BASE, _hole("F002", type="cbore", cbore_d="D002", cbore_depth="D002")]), DIMS)
    assert "DIFFERS" in f[0].message


def test_review_marks_an_unmatched_hole_as_a_plain_cut(synth):
    f = review(_plan([BASE, _hole("F002", d="D005")]), DIMS)
    assert "plain cut-extrude" in f[0].message


def test_review_wants_identical_holes_on_a_face_in_one_feature(synth):
    f = review(_plan([BASE, _hole("F002"), _hole("F003")]), DIMS)
    assert "mti_hole_grouping" in codes(f)


def test_review_wants_fillets_and_chamfers_last():
    edge = {"id": "F002", "kind": "edge_op", "operation": "fillet", "size": "D002",
            "edges": ["edge_between(face(F001,+Z),face(F001,+X))"]}
    assert "mti_edge_ops_last" in codes(review(_plan([BASE, edge, _hole("F003")]), DIMS))
    assert "mti_edge_ops_last" not in codes(review(_plan([BASE, _hole("F003"), {**edge, "id": "F004"}]), DIMS))


def test_review_without_the_table_skips_hole_wizard_but_never_fails():
    assert "mti_hole_wizard" not in codes(review(_plan([BASE, _hole("F002")]), DIMS))


def test_review_is_advisory_only(synth):
    f = review(_plan([BASE, _hole("F002"), _hole("F003")]), DIMS)
    assert all(x.severity in ("info", "warning") for x in f)


def test_review_messages_never_print_table_values(synth):
    # reports are committed; the MTI table is confidential
    plan = _plan([BASE, _hole("F002", type="cbore", cbore_d="D002", cbore_depth="D002"),
                  _hole("F003", d="D005")])
    dims = {**DIMS, "D005": 0.262}
    text = " ".join(f.message for f in review(plan, dims))
    for row in SYNTH["inch"]["rows"]:
        for v in row[3:]:
            if v not in dims.values():   # the drawing's own numbers may be shown
                assert f"{v:g}" not in text


# --------------------------------------------------------------------------- #
# Hole Wizard choice and same-hole grouping (pipeline/ir/compile_solidworks.py)
# --------------------------------------------------------------------------- #
from pipeline.ir.compile_solidworks import (  # noqa: E402
    END_UP_TO_NEXT, HW_FASTENER, hole_wizard_choice, mergeable_holes)
from pipeline.ir.model import HoleSpec  # noqa: E402


def test_up_to_next_is_the_value_hole_wizard_accepts():
    assert END_UP_TO_NEXT == 11   # swEndCondUpToNext; 2 is swEndCondThroughNext (HoleWizard5 rejects it)


def test_clearance_hole_becomes_a_hole_wizard_screw_clearance(synth):
    c = hole_wizard_choice(HoleSpec(type="thru", d="D003"), DIMS, "inch")
    assert (c["type"], c["standard"], c["fastener"], c["size"]) == (2, 0, HW_FASTENER[("hole", "inch")], "1/4")


def test_counterbore_carries_the_drawing_counterbore(synth):
    c = hole_wizard_choice(HoleSpec(type="cbore", d="D003", cbore_d="D004", cbore_depth="D002"), DIMS, "inch")
    assert (c["kind"], c["fastener"], c["values"][:2]) == ("cbore", 9, [0.44, 0.5])


def test_metric_hole_uses_ansi_metric(synth):
    c = hole_wizard_choice(HoleSpec(type="thru", d="D001"), {"D001": 6.4}, "mm")
    assert (c["standard"], c["fastener"], c["size"]) == (1, 40, "M6")


@pytest.mark.parametrize("spec", [
    HoleSpec(type="thru", d="D005"),                       # not a clearance size: plain cut
    HoleSpec(type="tapped", d="D003", depth="D002"),       # tapped: not yet Hole Wizard
    HoleSpec(type="thru", d="D003", thread="1/4-20"),
    HoleSpec(type="cbore", d="D003", cbore_d="D004"),      # counterbore without a depth
])
def test_not_hole_wizard(synth, spec):
    assert hole_wizard_choice(spec, DIMS, "inch") is None


def test_blind_clearance_hole_is_tried_and_left_to_the_volume_check(synth):
    assert hole_wizard_choice(HoleSpec(type="blind", d="D003", depth="D002"), DIMS, "inch")["kind"] == "hole"


def test_no_hole_wizard_without_the_mti_table():
    assert hole_wizard_choice(HoleSpec(type="thru", d="D003"), DIMS, "inch") is None


def test_only_consecutive_identical_holes_on_one_face_merge():
    plan = _plan([BASE, _hole("F002"), _hole("F003"), _hole("F004", d="D005"), _hole("F005")])
    f = plan.features
    assert [g.id for g in mergeable_holes(f[2:], f[1], DIMS, {})] == ["F003"]     # F004 differs: stop
    assert mergeable_holes(f[2:], f[1], DIMS, {"F003": "skipped"}) == []
    other_face = _plan([BASE, _hole("F002"), {**_hole("F003"), "on": "face(F001,-Z)"}]).features
    assert mergeable_holes(other_face[2:], other_face[1], DIMS, {}) == []
