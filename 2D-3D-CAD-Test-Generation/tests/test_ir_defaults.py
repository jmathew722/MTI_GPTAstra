"""Callout defaults (spec 2026-10-28-callout-defaults-design.md): vague callouts get a documented
answer instead of being skipped. Cases are the audit parts the rules were measured on."""
import pytest

from pipeline.ir.defaults import apply_defaults
from pipeline.ir.model import BuildPlan

BASE = {"id": "F001", "kind": "revolve", "outer": [{"z": "0", "r": "D001"}, {"z": "D002", "r": "D001"}]}
DIMS = {"D001": 0.5, "D002": 1.0, "D003": 0.03, "D004": 0.005, "D005": 0.38, "D006": 0.12, "D007": 0.159}
EDGE = ["edge_between(face(F001,-Z,0),wall(F001,D001))"]


def plan(*features):
    return BuildPlan.model_validate({"part": "T", "frame": {"origin_kind": "axis_end", "units": "inch"},
                                     "features": [BASE, *features]})


def edge(callout, size, op="fillet"):
    return {"id": "F002", "kind": "edge_op", "status": "unresolved", "operation": op, "size": size,
            "edges": EDGE, "source_callouts": [callout] if callout else [], "rationale": "?"}


def run(*features):
    new, applied = apply_defaults(plan(*features), DIMS)
    return new, applied, new.feature("F002")


def test_d1_max_only_radius_is_built_at_the_max():          # SB12006 ".030 R. MAX."
    _, applied, f = run(edge(".030 R. MAX.", "D003"))
    assert f.status == "planned" and f.operation == "fillet" and f.size == "D003"
    assert "DEFAULT D1" in f.justification and applied[0].startswith("F002: D1")


def test_d1_general_radii_max_note():                       # 2N2664 "ALL RADII .047 MAX"
    _, _, f = run(edge("ALL RADII .047 MAX", "D003"))
    assert f.status == "planned" and "DEFAULT D1" in f.justification


def test_d2_tiny_break_is_not_modelled():                   # 4C1229 ".005 C/R MAX."
    new, applied, f = run(edge(".005 C/R MAX.", "D004", op="chamfer"))
    assert f is None and applied == ["F002: D2 not modelled: 0.005 break is at or below 0.01"]
    assert [x.id for x in new.features] == ["F001"]


def test_d3_c_or_r_is_a_chamfer():                          # 2N2664 ".12 C/R"
    _, _, f = run(edge(".12 C/R", "D006", op="fillet"))
    assert f.status == "planned" and f.operation == "chamfer" and f.angle == "45"


def test_d4_unsized_break_is_not_modelled():                # SB14306 "BREAK ALL SHARP CORNERS."
    _, applied, f = run(edge("BREAK ALL SHARP CORNERS.", "0", op="chamfer"))
    assert f is None and "D4" in applied[0]


def test_d5_tap_with_thread_depth_only_gets_a_drill_depth():   # SB12006 "#10-32 TAP .38 DEEP"
    hole = {"id": "F002", "kind": "hole", "status": "unresolved", "on": "face(F001,+Z,D002)", "u": "0", "v": "0",
            "spec": {"type": "blind", "d": "D007"}, "source_callouts": ["#10-32 TAP .38 DEEP"], "rationale": "?"}
    new, applied, f = run(hole)
    assert f.status == "planned" and f.spec.type == "tapped" and f.spec.thread == "#10-32"
    assert f.spec.depth == "D005 + 5 / 32"
    from pipeline.ir.expr import evaluate
    assert evaluate(f.spec.depth, DIMS).value == pytest.approx(0.53625)    # MTI's model: .536
    assert not [x for x in new.check(DIMS) if x.severity == "error"]      # literal is justified


def test_d6_thread_class_never_blocks_geometry():           # 2N2664 "8-32-2A THD .50 DEEP"
    hole = {"id": "F002", "kind": "hole", "status": "unresolved", "on": "face(F001,+Z,D002)", "u": "0", "v": "0",
            "spec": {"type": "tapped", "d": "D007", "depth": "D005", "thread": "8-32-2A THD"},
            "source_callouts": ["8-32-2A THD .50 DEEP"],
            "rationale": "Does the printed internal 8-32-2A thread intend class 2B?"}
    _, _, f = run(hole)
    assert f.status == "planned" and f.spec.thread == "#8-32"


def test_d7_typ_with_a_size_uses_the_planned_edges():      # SB12008 ".030 R. TYP."
    _, _, f = run(edge(".030 R. TYP.", "D003"))
    assert f.status == "planned" and "DEFAULT D7" in f.justification


@pytest.mark.parametrize("callouts", [[".094", "30°", "1.188 DIA."],      # SB12010 bevel conflict
                                      ["*.375 R", "18.625 DIA."]])        # SB14306 blend question
def test_real_questions_stay_unresolved(callouts):
    f = edge(None, "D006")
    f["source_callouts"] = callouts
    _, applied, g = run(f)
    assert g.status == "unresolved" and applied == []


def test_tap_with_no_printed_depth_stays_a_question():      # A00173E "5/16-18 2B TH'D", no depth
    hole = {"id": "F002", "kind": "hole", "status": "unresolved", "on": "face(F001,+Z,D002)", "u": "0", "v": "0",
            "spec": {"type": "tapped", "d": "D007", "thread": "5/16-18 2B"},
            "source_callouts": ["5/16-18 2B TH'D", "2-HOLES."], "rationale": "through or blind?"}
    _, applied, f = run(hole)
    assert f.status == "unresolved" and applied == []


def test_planned_features_are_never_touched():
    f = edge(".030 R. MAX.", "D003")
    f["status"] = "planned"
    _, applied, g = run(f)
    assert applied == [] and g.justification == ""


def test_switch_turns_the_rules_off(monkeypatch):
    monkeypatch.setenv("MTI_CALLOUT_DEFAULTS", "0")
    _, applied, f = run(edge(".030 R. MAX.", "D003"))
    assert f.status == "unresolved" and applied == []


def test_never_defaults_a_hole_the_ir_cannot_start():      # a wall start with no radius
    hole = {"id": "F002", "kind": "hole", "status": "unresolved", "on": "wall(F001)", "u": "0", "v": "0",
            "spec": {"type": "blind", "d": "D007"}, "source_callouts": [".375-24 TAP .38 DEEP"], "rationale": "?"}
    _, applied, f = run(hole)
    assert f.status == "unresolved" and applied == []


def test_radial_tap_with_thread_depth_only_is_defaulted():   # SB12059 F005, now that radial holes exist
    hole = {"id": "F002", "kind": "hole", "status": "unresolved", "on": "wall(F001,D001)", "u": "45", "v": "0",
            "spec": {"type": "blind", "d": "D007"}, "source_callouts": [".375-24 TAP .38 DEEP"], "rationale": "?"}
    _, applied, f = run(hole)
    assert f.status == "planned" and f.spec.thread == ".375-24" and "D5" in applied[0]


def test_d5_merges_a_pilot_drill_into_its_tap():             # SB12006: tap F002 + unresolved pilot F003
    tap = {"id": "F002", "kind": "hole", "on": "face(F001,+Z,D002)", "u": "0", "v": "0",
           "spec": {"type": "tapped", "d": "D007", "depth": "D005", "thread": "#10-32"},
           "source_callouts": ["#10-32 TAP .38 DEEP"]}
    pilot = {"id": "F003", "kind": "hole", "status": "unresolved", "on": "face(F001,+Z,D002)", "u": "0", "v": "0",
             "spec": {"type": "blind", "d": "D007"}, "source_callouts": ["#10-32 TAP .38 DEEP"], "rationale": "?"}
    new, applied, f = run(tap, pilot)
    assert [x.id for x in new.features] == ["F001", "F002"]           # one tap, no second hole
    assert f.spec.depth == "D005 + 5 / 32" and "pilot F003 merged" in f.justification
    assert applied == ["F003: D5 pilot drill merged into tap F002 (drill = thread + 5 pitches)"]


def test_d6_merges_a_tap_into_its_drill():                   # 2N2664: drill F002 .69 deep + tap F003 .50
    drill = {"id": "F002", "kind": "hole", "on": "face(F001,+Z,D002)", "u": "0", "v": "0",
             "spec": {"type": "blind", "d": "D007", "depth": "D002"}}
    tap = {"id": "F003", "kind": "hole", "status": "unresolved", "on": "face(F001,+Z,D002)", "u": "0", "v": "0",
           "spec": {"type": "tapped", "d": "D007", "depth": "D005", "thread": "8-32-2A THD"},
           "source_callouts": ["8-32-2A THD .50 DEEP"], "rationale": "Does the 2A thread intend class 2B?"}
    new, applied, f = run(drill, tap)
    assert [x.id for x in new.features] == ["F001", "F002"]
    assert f.spec.type == "tapped" and f.spec.thread == "#8-32" and f.spec.depth == "D002"
    assert applied == ["F003: D6 tap #8-32 merged into drill F002"]


def test_d8_general_notes_cover_every_edge_on_turned_parts():   # 2N2664: ALL CHAMFERS .06 / ALL RADII .047 MAX
    chamfer = {"id": "F002", "kind": "edge_op", "operation": "chamfer", "size": "D006", "edges": EDGE,
               "source_callouts": ["UNLESS OTHERWISE SPECIFIED ALL CHAMFERS .06 x 45°"]}
    radii = {"id": "F003", "kind": "edge_op", "status": "unresolved", "operation": "fillet", "size": "D003",
             "edges": EDGE, "source_callouts": ["ALL RADII .047 MAX"], "rationale": "?"}
    new, applied, _ = run(chamfer, radii)
    extra = [f for f in new.features if f.id in ("F004", "F005")]
    assert [(f.operation, f.edges) for f in extra] == [("chamfer", ["edges(convex)"]), ("fillet", ["edges(concave)"])]
    assert all("DEFAULT D8" in f.justification for f in extra)
    assert sum("D8" in a for a in applied) == 2
    assert not [x for x in new.check(DIMS) if x.severity == "error"]


def test_d8_is_for_turned_parts_only():
    plate = BuildPlan.model_validate({"part": "P", "frame": {"origin_kind": "corner", "units": "inch"}, "features": [
        {"id": "F001", "kind": "prism", "on": "plane(front)", "profile": {"shape": "rect", "w": "D001", "h": "D001"}, "depth": "D002"},
        {"id": "F002", "kind": "edge_op", "operation": "chamfer", "size": "D006",
         "edges": ["edge_between(face(F001,+Z),face(F001,+X))"], "source_callouts": ["ALL CHAMFERS .06 x 45"]}]})
    new, applied = apply_defaults(plate, DIMS)
    assert len(new.features) == 2 and not applied


def _d9_plan(origin_kind="corner"):
    return BuildPlan.model_validate({"part": "P", "frame": {"origin_kind": origin_kind, "units": "inch"}, "features": [
        {"id": "F001", "kind": "prism", "on": "plane(front)", "profile": {"shape": "rect", "w": "D001", "h": "D002"},
         "depth": "D003"}] if origin_kind == "corner" else [BASE]})


EXTRACTION = {"general_tolerance": "UNLESS OTHERWISE SPECIFIED: 3 PLACE DIM. ±.010; 2 PLACE DIM. ±.02; ANGULAR ±1°",
              "dimensions": [{"id": "D001", "tolerance_plus": 0.02, "tolerance_minus": 0.02},      # 34.38 two-place
                             {"id": "D002", "tolerance_plus": 0.01, "tolerance_minus": 0.01},      # .440 three-place
                             {"id": "D003", "tolerance_plus": 0.02, "tolerance_minus": 0.02},      # .38 plate
                             {"id": "D004", "tolerance_plus": 0.0, "tolerance_minus": 0.0}]}       # derived


def test_d9_two_place_prints_of_fractions_become_the_fraction_on_plates():   # A00122E: .38 plate, 34.38 wide
    dims = {"D001": 34.38, "D002": 0.44, "D003": 0.38, "D004": 0.31}
    from pipeline.ir.defaults import nominal_fractions
    out, applied = nominal_fractions(_d9_plan(), dims, EXTRACTION)
    assert out == {"D001": 34.375, "D002": 0.44, "D003": 0.375, "D004": 0.31}   # .440 and derived untouched
    assert len(applied) == 2 and all("D9" in a for a in applied)


def test_d9_leaves_turned_parts_and_unreadable_title_blocks_alone():   # SB12055 keeps its printed 6.12
    from pipeline.ir.defaults import nominal_fractions
    dims = {"D001": 34.38, "D003": 0.38}
    assert nominal_fractions(_d9_plan("axis_end"), dims, EXTRACTION) == (dims, [])
    assert nominal_fractions(_d9_plan(), dims, {**EXTRACTION, "general_tolerance": "PLACE DIM. ±; PLACE DIM. ±"}) == (dims, [])
