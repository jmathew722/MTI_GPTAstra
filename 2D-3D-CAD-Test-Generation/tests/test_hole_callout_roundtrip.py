"""Hole Callout round trip: parsing of the text captured live from SOLIDWORKS 2025 SP5 and the semantic comparison."""
import pytest

from pipeline.ir.solidworks import hole_callout_roundtrip as rt
from pipeline.ir.solidworks import hole_intent as hi

# Captured with IDisplayDimension.GetText(prefix) / GetText(callout above) from real Hole Wizard parts (inches, 2 decimals).
LIVE = {
    "hole_thru": ("<MOD-DIAM> 0.25 THRU ALL", ""),
    "hole_blind": ("<MOD-DIAM> 0.25 <HOLE-DEPTH> 0.47", ""),
    "cbore_thru": ("<HOLE-SPOT><MOD-DIAM> 0.43 <HOLE-DEPTH> 0.26", "<MOD-DIAM> 0.25 THRU ALL"),
    "csink_blind": ("<HOLE-SINK><MOD-DIAM> 0.49 X 82°", "<MOD-DIAM> 0.25 <HOLE-DEPTH> 0.47"),
    "tap_blind": ("M6x1.0 - 6H <HOLE-DEPTH> 0.39", "<MOD-DIAM> 0.20 <HOLE-DEPTH> 0.47"),
    "pipe_blind": ("1/4 NPT", "<MOD-DIAM> 0.44 <HOLE-DEPTH> 0.48"),
    "cbore_slot_thru": ("<HOLE-SPOT> 0.43 <HOLE-DEPTH> 0.26", "0.25 X 0.79 THRU ALL"),
    "csink_slot_blind": ("<HOLE-SINK> 0.49 X 82°", "0.25 X 0.79 <HOLE-DEPTH> 0.47"),
    "slot_blind": ("0.25 X 0.79 <HOLE-DEPTH> 0.47", ""),
}


def test_parsing_the_live_text():
    p = rt.parse_callout(*LIVE["hole_thru"])
    assert p["main_diameter"] == 0.25 and p["through"] and p["main_depth"] is None
    p = rt.parse_callout(*LIVE["hole_blind"])
    assert p["main_diameter"] == 0.25 and not p["through"] and p["main_depth"] == 0.47
    p = rt.parse_callout(*LIVE["cbore_thru"])
    assert (p["counterbore_diameter"], p["counterbore_depth"], p["main_diameter"], p["through"]) == (0.43, 0.26, 0.25, True)
    p = rt.parse_callout(*LIVE["csink_blind"])
    assert (p["countersink_diameter"], p["countersink_angle"], p["main_depth"]) == (0.49, 82.0, 0.47)
    p = rt.parse_callout(*LIVE["tap_blind"])
    assert (p["thread_designation"], p["thread_class"], p["thread_depth"], p["main_diameter"]) == ("M6x1.0", "6H", 0.39, 0.20)
    p = rt.parse_callout(*LIVE["pipe_blind"])
    assert (p["pipe_size"], p["pipe_standard"]) == ("1/4", "NPT")


def test_counterbore_matches_within_the_printed_rounding_and_a_wrong_value_is_caught():
    i = hi.HoleIntent(family="counterbore", end="through", diameter=6.4, cbore_diameter=11.0, cbore_depth=6.5, units="mm")
    assert rt.compare_callout(i, rt.parse_callout(*LIVE["cbore_thru"])) == []
    i.cbore_depth = 9.0
    bad = rt.compare_callout(i, rt.parse_callout(*LIVE["cbore_thru"]))
    assert [b["field"] for b in bad] == ["counterbore_depth"]


def test_through_and_blind_are_not_confused():
    through = hi.HoleIntent(family="hole", end="through", diameter=6.4, units="mm")
    assert rt.compare_callout(through, rt.parse_callout(*LIVE["hole_blind"]))[0]["field"] == "end_condition"
    blind = hi.HoleIntent(family="hole", end="blind", diameter=6.4, depth=12.0, units="mm")
    assert rt.compare_callout(blind, rt.parse_callout(*LIVE["hole_blind"])) == []
    assert rt.compare_callout(blind, rt.parse_callout(*LIVE["hole_thru"]))[0]["field"] == "end_condition"


def test_countersink_angle_and_diameter():
    i = hi.HoleIntent(family="countersink", end="blind", diameter=6.4, depth=12.0, csink_diameter=12.4, csink_angle=82.0, units="mm")
    assert rt.compare_callout(i, rt.parse_callout(*LIVE["csink_blind"])) == []
    i.csink_angle = 90.0
    assert rt.compare_callout(i, rt.parse_callout(*LIVE["csink_blind"]))[0]["field"] == "countersink_angle"


def test_tap_designation_class_depth_and_the_tap_drill():
    th = {"designation": "M6x1", "class": "6H"}
    i = hi.HoleIntent(family="straight_tap", end="blind", depth=12.0, drill_depth=12.0, thread_depth=10.0, thread=th, units="mm")
    assert rt.compare_callout(i, rt.parse_callout(*LIVE["tap_blind"]), tap_drill_in=5.0 / 25.4) == []
    i.thread = {**th, "class": "6G"}
    assert rt.compare_callout(i, rt.parse_callout(*LIVE["tap_blind"]), tap_drill_in=5.0 / 25.4)[0]["field"] == "thread_class"


def test_pipe_tap_needs_its_size_and_standard():
    i = hi.HoleIntent(family="pipe_tap", end="blind", depth=0.48, thread={"size": "1/4-18", "standard": "NPT"}, units="inch")
    assert rt.compare_callout(i, rt.parse_callout(*LIVE["pipe_blind"]), tap_drill_in=0.44) == []
    i.thread = {"size": "1/4-18", "standard": "NPTF"}
    assert rt.compare_callout(i, rt.parse_callout(*LIVE["pipe_blind"]), tap_drill_in=0.44)[0]["field"] == "pipe_standard"


def test_an_unparseable_callout_never_matches():
    i = hi.HoleIntent(family="hole", end="through", diameter=6.4, units="mm")
    assert rt.compare_callout(i, rt.parse_callout("", ""))


def test_slots_are_compared_by_width_overall_length_treatment_and_end():
    cb = hi.HoleIntent(family="counterbore_slot", end="through", slot_width=6.4, slot_length=20.0, cbore_diameter=11.0,
                       cbore_depth=6.5, units="mm")
    assert rt.compare_callout(cb, rt.parse_callout(*LIVE["cbore_slot_thru"])) == []
    cb.slot_length = 30.0
    assert [b["field"] for b in rt.compare_callout(cb, rt.parse_callout(*LIVE["cbore_slot_thru"]))] == ["slot_length"]
    cs = hi.HoleIntent(family="countersink_slot", end="blind", slot_width=6.4, slot_length=20.0, depth=12.0,
                       csink_diameter=12.4, csink_angle=82.0, units="mm")
    assert rt.compare_callout(cs, rt.parse_callout(*LIVE["csink_slot_blind"])) == []
    plain = hi.HoleIntent(family="slot", end="blind", slot_width=6.4, slot_length=20.0, depth=12.0, units="mm")
    assert rt.compare_callout(plain, rt.parse_callout(*LIVE["slot_blind"])) == []
    plain.end = "through"
    assert rt.compare_callout(plain, rt.parse_callout(*LIVE["slot_blind"]))[0]["field"] == "end_condition"
