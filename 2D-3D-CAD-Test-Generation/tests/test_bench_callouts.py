"""bench.callouts parses legacy hole callouts from the MTI drawings."""
import pytest

from bench.callouts import parse


@pytest.mark.parametrize("text, kind, d, thread, depth, thru, count", [
    (".500-13 TAP THRU (3) HLS.", "tap", None, ".500-13", None, True, 3),
    (".375-16 TAP .81 DP.", "tap", None, ".375-16", 0.81, False, 1),
    ("TAP M10X1.5 - .75 DP.\n4-HOLES", "tap", None, "M10X1.5", 0.75, False, 4),
    (".344 DR. THRU & .562 C'BORE\n.47 DP. 4 HOLES", "cbore", 0.344, "", 0.47, True, 4),
    ("DR. & C'BORE .38 DP. FOR .250 S.H.C.S. 6-HLS.", "cbore", None, "", 0.38, False, 6),
    (".281 DR. THRU", "drill", 0.281, "", None, True, 1),
    ("DR. & C'SINK FOR .250 FLAT HD. SCR. 12-HOLES", "csink", None, "", None, False, 12),
    (".344 DIA. THRU (6) HLS.", "drill", 0.344, "", None, True, 6),
])
def test_parse(text, kind, d, thread, depth, thru, count):
    c = parse(text)
    assert c is not None
    assert (c.kind, c.d, c.thread, c.depth, c.thru, c.count) == (kind, d, thread, depth, thru, count)


def test_screw_size():
    assert parse("DR. & C'BORE FOR #10 SOC. HD. CAP SCR. 8-HOLES AS SHOWN").screw == "#10"
    assert parse("DR. & C'BORE .38 DP. FOR .250 S.H.C.S. 6-HLS.").screw == ".250"


def test_not_a_callout():
    assert parse("4140 STL.") is None
    assert parse("BREAK SHARP EDGES") is None


def test_nominal_diameter_of_thread():
    assert parse(".500-13 TAP THRU").nominal == 0.5
    assert parse("TAP M10X1.5").nominal == pytest.approx(10 / 25.4)


@pytest.mark.parametrize("text, d", [
    ("%%C.344 THRU", 0.344),
    ("%%C2.500 THRU", 2.5),
    ("\u00d8.344 THRU", 0.344),
    ("3/8 DR. THRU", 0.375),
])
def test_diameter_prefix_forms(text, d):
    c = parse(text)
    assert c is not None and c.kind == "drill" and c.d == d and c.thru


@pytest.mark.parametrize("text", [
    "MATERIAL: 1018 THRU HARDENED",
    "(4.562%%C B.C. REF.)",
    "TOLERANCE .005 DIA.",
    "SEE DETAIL 2 DR.",
    "9.5 DIA. THRU",
    ".01 DR. THRU",
    "DECIMAL DIMENSIONS TO BE:",
    ".000 %%P.010",
    "ALL SCREW HOLE DIMENSIONS TO BE WITHIN %%P.005",
    "R/C 28-32",
    "BREAK SHARP EDGES .010-.020",
    ".06 X 45\u00b0",
    "1.678 TYP.",
    "THRU",
])
def test_false_positives_rejected(text):
    assert parse(text) is None


@pytest.mark.parametrize("text, thread, depth, thru, count", [
    ("TAP .25-20 THRU", ".25-20", None, True, 1),
    ("TAP M12 X 1.75 THRU (3) HLS.", "M12X1.75", None, True, 3),
    (".250-20 TAP .62 DP.", ".250-20", 0.62, False, 1),
    ("1.750-12 TAP THRU", "1.750-12", None, True, 1),
    (".312-18 TAP THRU 2-HOLES", ".312-18", None, True, 2),
    ("#10-32 TAP .5 DP. 4X", "#10-32", 0.5, False, 4),
])
def test_tap_variants(text, thread, depth, thru, count):
    c = parse(text)
    assert c.kind == "tap" and (c.thread, c.depth, c.thru, c.count) == (thread, depth, thru, count)


def test_cbore_diameter():
    c = parse(".344 DR. THRU & .562 C'BORE .47 DP. 4 HOLES")
    assert (c.kind, c.d, c.cbore_d, c.depth) == ("cbore", 0.344, 0.562, 0.47)
    assert parse("DR. & C'BORE .38 DP. FOR .250 S.H.C.S. 6-HLS.").cbore_d is None
    c = parse("DR. & C'BORE FOR #10 SOC. HD. CAP SCR. 8-HOLES AS SHOWN")
    assert (c.kind, c.count, c.screw) == ("cbore", 8, "#10")


@pytest.mark.parametrize("thread, nominal", [("#0-80", 0.060), ("#1-72", 0.073), ("#2-56", 0.086),
                                             ("#3-48", 0.099)])
def test_small_screw_numbers(thread, nominal):
    c = parse(f"{thread} TAP .25 DP.")
    assert c.thread == thread and c.nominal == nominal


def test_bolt_circle_hole_callout_is_kept_with_its_bc_diameter():
    c = parse(".344 DIA. THRU (6) HLS. EQ. SP. ON 3.000 B.C.")
    assert c is not None and (c.kind, c.d, c.count, c.bc_d) == ("drill", 0.344, 6, 3.0)
    c = parse(".281 DR. THRU 4-HOLES EQ. SP. ON B.C. 2.500")
    assert (c.d, c.count, c.bc_d) == (0.281, 4, 2.5)
    c = parse(".250-20 TAP THRU (6) HLS. ON 4.000%%C B.C.")
    assert (c.kind, c.thread, c.bc_d) == ("tap", ".250-20", 4.0)
    assert parse(".344 DIA. THRU (6) HLS.").bc_d is None
    assert parse("(4.562%%C B.C. REF.)") is None


# ---- legacy forms seen on the first real-data run (synthetic strings) ------------------------

@pytest.mark.parametrize("text", ["OVER .5000 DIA.", "Ø2.750", "%%C1.250", ".750 DIA."])
def test_bare_diameter_note_is_not_a_hole_callout(text):
    assert parse(text) is None


def test_drill_word_alone_keeps_a_callout():
    c = parse(".250 DRILL")
    assert c is not None and c.kind == "drill" and c.d == 0.25


def test_cbore_with_diameter_mark_and_spaced_apostrophe():
    c = parse("1.750 %%C C'BORE 1.50 DP.")
    assert (c.kind, c.cbore_d, c.depth) == ("cbore", 1.75, 1.5)
    assert parse("DR. & C' BORE (FAR SIDE) FOR .375 SOC. HD. CAP SCR. (5) HLS.").kind == "cbore"


def test_spotface_is_a_counterbore_size():
    c = parse(".656 DR. THRU 1.062 %%C SPOTFACE (3) HOLES")
    assert (c.kind, c.d, c.cbore_d, c.thru, c.count) == ("cbore", 0.656, 1.062, True, 3)


def test_deep_is_a_depth_word_and_paren_count_before_holes():
    c = parse(".250-20 TAP .75 DEEP (7)HOLES")
    assert (c.thread, c.depth, c.count) == (".250-20", 0.75, 7)
    assert parse(".250-20 TAP THRU (9) HOLES").count == 9


def test_toleranced_size_with_trailing_diameter_mark_thru():
    c = parse("1.502 %%P.001 %%C THRU")
    assert (c.kind, c.d, c.thru) == ("drill", 1.502, True)


def test_drill_and_ream_gives_the_ream_as_step_diameter():
    c = parse('"X"=.875 DRILL THRU & 1.1811 RM. AS SHOWN (16)HOLES')
    assert (c.kind, c.d, c.cbore_d, c.count, c.thru) == ("drill", 0.875, 1.1811, 16, True)
