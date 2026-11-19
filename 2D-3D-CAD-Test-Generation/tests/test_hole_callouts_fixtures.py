"""The five permanent regression fixtures HW-EX-001..005 (HOLE_CALLOUT_TO_BUILD_PLAN_SPEC.md) plus HoleIntentV2 (Stage 4, B/C).

Transcribed callout text only (no drawing assets). Every missing value must stay unresolved: nothing here may be invented.
"""
import pytest

from pipeline.hole_callouts import group_lines, line_of_span, parse, parse_group
from pipeline.ir.solidworks import hole_intent as v1
from pipeline.ir.solidworks import hole_intent_v2 as v2

NO_CLEARANCE = lambda d, u: False       # noqa: E731  (the confidential clearance table is never consulted in tests)

FX1 = "DRILL .44 - 2.1 DP.\nTAP .25 NPT\n2 - PLACES"
FX2 = "DRILL .50 DIA. - 1.1 DEEP\nC'BORE 1.001 DIA ±.001 X .123 +.000/-.003 DEEP\n2 - PLACES"
FX3 = ".344 DIA THRU\n.50 C'BORE - .10 DP\n4 - PLACES"
FX4 = "DR & TAP .50-13 THD.\n.8 DEEP\n4 PLACES"
FX5 = ".50 DIA. - .18 DEEP\n2 PLACES"


def lift(text, **kw):
    return v2.from_parsed(parse(text), "inch", clearance_match=NO_CLEARANCE, **kw)


def test_hw_ex_001_blind_npt_pipe_tap_never_invents_thread_depth():
    i = lift(FX1)
    assert i.general_family == "pipe_tap" and i.creation_method == "hole_wizard"
    assert i.size_designation == "1/4 NPT" and i.thread["designation"] == ".25 NPT"            # original text retained
    assert i.thread["thread_kind"] == "tapered_pipe" and i.thread["standard"] == "NPT"
    assert i.quantity == 2 and i.end_condition == {"main": "blind", "main_depth": 2.1}
    assert i.geometry["main_diameter"] == 0.44
    assert i.thread["thread_depth"] is None and "thread.thread_depth" in i.unresolved_fields
    assert i.status == "needs_review" and "standard" in i.unresolved_fields
    # variant selection is the pipe-tap blind member; it is never a plain cut
    assert i.specific_type == "swPipeTapBlind" or i.selection["code"] is not None
    assert i.creation_method != "cut_extrude"


def test_hw_ex_002_custom_tolerances_survive():
    i = lift(FX2)
    assert i.general_family == "counterbore" and i.creation_method == "hole_wizard" and i.quantity == 2
    assert i.end_condition == {"main": "blind", "main_depth": 1.1} and i.geometry["main_diameter"] == 0.50
    assert i.geometry["counterbore_diameter"] == 1.001 and i.geometry["counterbore_depth"] == 0.123
    tol = {t["field"]: t for t in i.tolerances}
    assert (tol["geometry.counterbore_diameter"]["kind"], tol["geometry.counterbore_diameter"]["plus"],
            tol["geometry.counterbore_diameter"]["minus"]) == ("bilateral", 0.001, 0.001)
    assert (tol["geometry.counterbore_depth"]["kind"], tol["geometry.counterbore_depth"]["plus"],
            tol["geometry.counterbore_depth"]["minus"]) == ("unilateral", 0.0, 0.003)
    assert i.specific_type == "swCounterBoreBlind" and i.conflicts == []


def test_hw_ex_003_through_counterbore_four_places():
    i = lift(FX3)
    assert i.general_family == "counterbore" and i.creation_method == "hole_wizard" and i.quantity == 4
    assert i.end_condition == {"main": "through_all", "main_depth": None}
    assert (i.geometry["main_diameter"], i.geometry["counterbore_diameter"], i.geometry["counterbore_depth"]) == (0.344, 0.50, 0.10)
    assert i.specific_type == "swCounterBoreThru" and i.status == "ready" and i.unresolved_fields == []


def test_hw_ex_004_straight_tap_explicit_thread_depth_class_and_tap_drill_depth_unresolved():
    i = lift(FX4)
    assert i.general_family == "straight_tap" and i.creation_method == "hole_wizard" and i.quantity == 4
    assert i.size_designation == "1/2-13" and i.thread["thread_kind"] == "straight"
    assert i.thread["thread_depth"] == 0.8 and "thread.thread_depth" in i.provenance["explicit_fields"]
    assert i.thread["series"] is None                                  # the drawing did not write UNC
    cand = [x for x in i.provenance["inferred_fields"] if x["field"] == "thread.series"]
    assert cand and cand[0]["value"] == "UNC" and "candidate" in cand[0]["note"]
    assert i.thread["class"] is None and "thread.class" in i.unresolved_fields
    assert i.thread["tap_drill_depth"] is None and "thread.tap_drill_depth" in i.unresolved_fields
    assert i.status == "needs_review"


def test_hw_ex_005_plain_blind_bore_method_comes_from_policy_and_is_recorded():
    i = lift(FX5)
    assert i.general_family == "simple" and i.quantity == 2
    assert i.end_condition == {"main": "blind", "main_depth": 0.18} and i.geometry["main_diameter"] == 0.50
    assert i.creation_method == "cut_extrude"
    pol = i.provenance["policy_fields"][0]
    assert pol["policy"] == v2.POLICY_VERSION and pol["rule"] == "plain_non_fastener_bore_is_cut_extrude"
    j = v2.from_parsed(parse(FX5), "inch", clearance_match=lambda d, u: True)      # policy flips with a clearance match
    assert j.creation_method == "hole_wizard" and j.specific_type == "swHoleBlind"


def test_through_is_an_end_condition_only_and_never_picks_the_creation_method():
    thru = lift(".50 DIA THRU\n2 PLACES")
    assert thru.end_condition["main"] == "through_all" and thru.creation_method == "cut_extrude"


# ---- multi-line grouping --------------------------------------------------------------------------------------------
def test_ocr_lines_group_into_the_five_callouts_and_map_fields_back_to_their_lines():
    lines = ["NOTES:"] + FX1.split("\n") + FX2.split("\n") + FX3.split("\n") + FX4.split("\n") + FX5.split("\n")
    groups = group_lines(lines)
    texts = ["\n".join(lines[k] for k in g) for g in groups]
    for fx in (FX1, FX2, FX3, FX4, FX5):
        assert fx in texts
    pc = parse_group(FX3.split("\n"))
    assert line_of_span(pc, pc.cbore_depth.span) == 1 and line_of_span(pc, pc.diameter.span) == 0 and line_of_span(pc, pc.quantity.span) == 2
    i = lift(FX3)
    assert i.source["raw_lines"] == FX3.split("\n") and i.source["field_spans"]["geometry.counterbore_depth"]["line"] == 1


# ---- V2 contract ---------------------------------------------------------------------------------------------------
def test_v2_round_trips_rejects_other_versions_and_unknown_fields():
    i = lift(FX3)
    d = i.to_dict()
    assert d["schema_version"] == 2 and v2.from_dict(d) == i
    with pytest.raises(v2.IntentV2Error) as e:
        v2.from_dict({**d, "schema_version": 1})
    assert e.value.code == "HW_INTENT_VERSION"
    with pytest.raises(v2.IntentV2Error) as e2:
        v2.from_dict({**d, "surprise": 1})
    assert e2.value.code == "HW_INTENT_FIELD"
    with pytest.raises(v2.IntentV2Error):
        v2.from_dict({**d, "creation_method": "magic"})


def test_v1_migrates_forward_without_adding_anything_and_bridges_back():
    old = v1.from_callout(parse("Ø.266 THRU ⌴ Ø.438 X .25 DEEP"), "inch")
    new = v2.migrate(old.to_dict())
    assert new.schema_version == 2 and new.general_family == "counterbore" and new.end_condition["main"] == "through_all"
    assert new.geometry["counterbore_diameter"] == 0.438 and new.specific_type == "swCounterBoreThru"
    back = v2.to_v1(new)
    assert back.family == "counterbore" and back.end == "through" and back.cbore_diameter == 0.438
    with pytest.raises(v2.IntentV2Error):
        v2.migrate({"schema_version": 9})


def test_advanced_hole_candidate_is_unsupported_and_keeps_the_source():
    i = v2.from_parsed(parse("NEAR SIDE Ø6 X 8 DEEP, FAR SIDE Ø4 X 5 DEEP"), "mm")
    assert i.creation_method == "advanced_hole" and i.status == "unsupported" and i.selection["code"] == "HW_ADVANCED_HOLE"
    assert i.source["raw_lines"]


def test_a_contradiction_is_kept_as_a_conflict_not_resolved():
    i = lift(".50 DIA THRU - .18 DEEP\n2 PLACES")
    assert any(c["code"] == "through_with_depth" for c in i.conflicts) and i.status == "needs_review"


def test_dimension_reports_canonical_millimetres():
    i = lift(FX3)
    assert i.dimension("main_diameter") == pytest.approx(0.344 * 25.4)
