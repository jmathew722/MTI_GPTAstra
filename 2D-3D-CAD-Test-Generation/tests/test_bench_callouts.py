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
