"""Hole Wizard capability registry, pinned to the installed type library (Stage 4, task 4.6)."""
import json
from pathlib import Path

import pytest

from pipeline.ir.solidworks.hole_capabilities import (
    BY_NAME, GENERAL_ENUM_NAMES, GENERAL_FAMILIES, PROPERTY_GROUPS, SPECIFIC, STATUSES, VARIANTS, classify,
    family_counts, unknown_members,
)

SNAP = json.loads((Path(__file__).parent / "fixtures" / "sw_hole_enums_2025.json").read_text(encoding="utf-8"))


def test_the_registry_matches_the_installed_enums_exactly():
    live = {int(v): k for k, v in SNAP["specific"].items()}
    assert len(live) == 81 and len(SPECIFIC) == 81
    assert unknown_members(SNAP["specific"]) == {"unknown_to_registry": {}, "missing_in_install": {}, "renamed": {}}
    assert {int(v): k for k, v in SNAP["general"].items()} == GENERAL_ENUM_NAMES


def test_all_nine_general_families_are_classified_and_enum_values_are_not_contiguous():
    assert sorted(GENERAL_FAMILIES) == list(range(9)) and len(set(GENERAL_FAMILIES.values())) == 9
    values = sorted(SPECIFIC)
    assert values[-1] == 90 and values != list(range(len(values)))          # 80-89 do not exist: never index by position
    assert all(v.general in GENERAL_FAMILIES for v in VARIANTS.values())


def test_family_totals_match_the_documented_counts():
    assert family_counts() == {"legacy": 10, "counterbore": 12, "hole": 6, "countersink": 6, "straight_tap": 17, "pipe_tap": 6,
                               "counterbore_slot": 12, "slot": 6, "countersink_slot": 6}
    assert sum(family_counts().values()) == 81


@pytest.mark.parametrize("name,end,treat,thread,head", [
    ("swCounterBoreBlind", "blind", (), None, None),
    ("swCounterBoreBlindCounterSinkTopmiddle", "blind", ("near", "middle"), None, None),          # irregular capitalisation
    ("swCounterBoreThruCounterSinkTopMiddleBottom", "through", ("near", "middle", "far"), None, None),
    ("swHoleThruCounterSinkBottom", "through", ("far",), None, None),
    ("swCounterSinkBlind", "blind", (), None, True),
    ("swCounterSinkBlindWithoutHeadClearance", "blind", (), None, False),
    ("swCounterSinkThruCounterSinkBottomWithoutHeadClearance", "through", ("far",), None, False),
    ("swTapBlindCosmeticThread", "blind", (), "cosmetic", None),
    ("swTapThruThreadThruCountersinkTopBottom", "through", ("near", "far"), "thread_through", None),      # lowercase 's'
    ("swTapBlindRemoveThread", "blind", (), "remove", None),
    ("swTapThru", "through", (), "plain", None),
    ("swPipeTapThruCounterSinkTopBottom", "through", ("near", "far"), "plain", None),
    ("swSlotThru", "through", (), None, None),
    ("swCounterSinkSlotThruCounterSinkBottomWithoutHeadClearance", "through", ("far",), None, False),
    ("swCounterBoreSlotBlindCounterSinkTopMiddle", "blind", ("near", "middle"), None, None),
])
def test_names_classify_into_end_condition_side_treatments_thread_mode_and_head_clearance(name, end, treat, thread, head):
    v = BY_NAME[name]
    assert (v.end, v.treatments, v.thread, v.head_clearance) == (end, treat, thread, head)


def test_specific_to_general_mapping_for_the_awkward_names():
    assert BY_NAME["swHoleBlind"].family == "hole" and BY_NAME["swCounterSinkBlind"].family == "countersink"
    assert BY_NAME["swSlotBlind"].family == "slot" and BY_NAME["swCounterSinkSlotBlind"].family == "countersink_slot"
    assert BY_NAME["swPipeTapBlind"].general == 3 and BY_NAME["swTapBlind"].general == 4
    assert all(v.legacy and v.family == "legacy" and v.end is None for v in VARIANTS.values() if v.value < 10)
    assert BY_NAME["swHoleBlindCounterSinkTop"].family == "hole" and BY_NAME["swHoleBlindCounterSinkTop"].treatments == ("near",)


def test_every_candidate_property_exists_on_the_installed_interface():
    members = set(SNAP["IWizardHoleFeatureData2_members"])
    missing = {p for names in PROPERTY_GROUPS.values() for p in names if p not in members}
    assert missing == set(), f"properties that do not exist on IWizardHoleFeatureData2: {missing}"


def test_property_groups_follow_the_treatments():
    far = BY_NAME["swHoleThruCounterSinkBottom"].properties
    assert "FarCounterSinkDiameter" in far and "NearCounterSinkDiameter" not in far and "MidCounterSinkDiameter" not in far
    all3 = BY_NAME["swCounterBoreThruCounterSinkTopMiddleBottom"].properties
    assert {"NearCounterSinkAngle", "MidCounterSinkAngle", "FarCounterSinkAngle", "CounterBoreDepth"} <= set(all3)
    assert "ThreadClass" in BY_NAME["swTapBlind"].properties and "ThreadClass" not in BY_NAME["swHoleBlind"].properties
    assert "Length" in BY_NAME["swSlotBlind"].properties and "Length" not in BY_NAME["swHoleBlind"].properties
    assert all("scope" in v.property_groups and "identity" in v.property_groups for v in VARIANTS.values())


def test_unknown_future_members_fail_closed():
    r = classify(81)
    assert r["known"] is False and r["status"] == "not_implemented" and r["reason"] == "unknown_variant"
    rep = unknown_members({**SNAP["specific"], "swFutureHole": 91})
    assert rep["unknown_to_registry"] == {91: "swFutureHole"} and rep["missing_in_install"] == {}
    gone = dict(SNAP["specific"]); gone.pop("swSlotThru")
    assert unknown_members(gone)["missing_in_install"] == {72: "swSlotThru"}


def test_nothing_starts_verified_and_statuses_use_the_fixed_vocabulary():
    assert STATUSES == ("verified", "implemented_not_live_verified", "unsupported_by_installed_catalog", "not_implemented",
                        "ambiguous_source", "failed_verification")
    assert all(v.status in STATUSES and v.status != "verified" for v in VARIANTS.values())


def test_interface_facts_that_shape_the_design():
    assert "HoleWizard5" in SNAP["IFeatureManager_hole_methods"] and "AdvancedHole" in SNAP["IFeatureManager_hole_methods"]
    assert SNAP["IAssemblyDoc_hole_methods"] == []                       # Hole Series has no API in this release
    assert "InitializeHole" in SNAP["IWizardHoleFeatureData2_members"]
    assert len(SNAP["swWzdHoleStandards_e"]) == 19 and len(SNAP["swWzdHoleStandardFastenerTypes_e"]) == 404
