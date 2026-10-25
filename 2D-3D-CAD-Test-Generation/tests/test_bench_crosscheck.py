"""bench.crosscheck: a clean pair gives no flags; one seeded change gives exactly one flag."""
import math

from bench.callouts import parse
from bench.crosscheck import ALWAYS_REVIEW, check, sign_auto, sign_human
from bench.dxfread import Dim, Drawing
from bench.features import Feature, Key


def _key():
    holes = [Feature(id=f"K{i}", type="thru_hole", axis=[0, 0, 1], center=[x, y, 0], d=0.344,
                     depth=0.5, thru=True)
             for i, (x, y) in enumerate([(0.5, 0.5), (3.5, 0.5), (0.5, 2.5), (3.5, 2.5)], 1)]
    return Key(part="P", units="inch", source="s", envelope=[4.0, 3.0, 0.5], features=holes)


def _drawing(width=4.0, count=4):
    dims = [Dim("linear", width, width, "<>", False, None), Dim("linear", 3.0, 3.0, "<>", False, None),
            Dim("linear", 0.5, 0.5, "<>", False, None), Dim("linear", 3.0, 3.0, "<>", False, None),
            Dim("linear", 2.0, 2.0, "<>", False, None)]
    return Drawing(dims=dims, callouts=[parse(f".344 DIA. THRU ({count}) HLS.")],
                   general_tol={3: 0.005, 2: 0.01}, units_hint="inch")


def test_clean_pair_has_no_flags():
    assert check(_key(), _drawing()) == []


def test_changed_dimension_gives_exactly_one_flag():
    flags = check(_key(), _drawing(width=4.25))
    assert [f.kind for f in flags] == ["unexplained_drawing_value"]


def test_unplaced_hole_is_flagged():
    k = _key()
    k.features[0].center = [1.234, 1.789, 0]       # a position no drawing distance explains
    flags = check(k, _drawing())
    assert [(f.kind, f.feature) for f in flags if f.kind == "unexplained_position"] == [("unexplained_position", "K1")]


def test_count_mismatch_flag():
    flags = check(_key(), _drawing(count=3))
    assert [f.kind for f in flags] == ["count_mismatch"]


def test_units_mismatch_flag():
    d = _drawing()
    d.units_hint = "mm"
    assert "units_mismatch" in {f.kind for f in check(_key(), d)}


def test_signoff_rules():
    k = _key()
    k.flags = []
    assert sign_auto(k, tool="bench 1") and k.signoff["kind"] == "auto"
    k2 = _key()
    k2.part = next(iter(ALWAYS_REVIEW))
    assert not sign_auto(k2, tool="bench 1") and not k2.signed
    k3 = _key()
    k3.flags = check(k3, _drawing(count=3))
    assert not sign_human(k3, by="smcanuff")
    k3.flags[0].resolution = "accepted: 4th hole is on the section view"
    assert sign_human(k3, by="smcanuff") and k3.signoff["kind"] == "human"


# ---- added cases -------------------------------------------------------------------------

def _lin(v, dec=None, text="<>", measured=None, nts=False, kind="linear"):
    return Dim(kind, v if measured is None else measured, v, text, nts, dec)


def _plate_dims():
    return [_lin(4.0), _lin(3.0), _lin(0.5), _lin(3.0), _lin(2.0)]


def test_tapped_hole_is_recognised_and_relabelled():
    k = _key()
    k.features = k.features[:1]
    k.features[0].type, k.features[0].d, k.features[0].thru, k.features[0].depth = "blind_hole", 0.3125, False, 0.9
    d = Drawing(dims=[_lin(4.0), _lin(3.0), _lin(0.5)], callouts=[parse(".375-16 TAP .75 DP.")],
                general_tol={3: 0.005}, units_hint="inch")
    assert check(k, d) == []
    assert k.features[0].type == "tapped_hole" and k.features[0].thread == ".375-16"


def test_tap_callout_does_not_swallow_a_quarter_inch_drill():
    k = _key()
    k.features[0].type, k.features[0].d, k.features[0].thru = "blind_hole", 0.3125, False
    for f in k.features[1:3]:
        f.d = 0.25                                   # .25/.375 = 0.67: not a .375-16 tap drill
    k.features = k.features[:3]
    d = Drawing(dims=_plate_dims(),
                callouts=[parse(".375-16 TAP .75 DP."), parse(".250 DR. THRU (2) HLS.")],
                general_tol={3: 0.005}, units_hint="inch")
    assert check(k, d) == []
    assert [f.type for f in k.features] == ["tapped_hole", "thru_hole", "thru_hole"]


def test_tap_count_is_matched_by_thread():
    k = _key()
    for f in k.features:
        f.d = 0.201
    d = Drawing(dims=_plate_dims(), callouts=[parse("1/4-20 TAP THRU (3) HLS")],
                general_tol={3: 0.005}, units_hint="inch")
    assert [f.kind for f in check(k, d)] == ["count_mismatch"]
    assert all(f.thread == "1/4-20" for f in k.features)


def _cbore_key(cbore_depth=0.47):
    k = _key()
    for f in k.features:
        f.type, f.cbore_d, f.cbore_depth = "counterbore", 0.562, cbore_depth
    return k


def test_counterbore_with_stated_cbore_size_has_no_flags():
    d = Drawing(dims=_plate_dims(), callouts=[parse(".344 DR. THRU & .562 C'BORE .47 DP. 4 HOLES")],
                general_tol={3: 0.005, 2: 0.01}, units_hint="inch")
    assert check(_cbore_key(), d) == []


def test_counterbore_depth_compared_to_cbore_depth():
    d = Drawing(dims=_plate_dims(), callouts=[parse(".344 DR. THRU & .562 C'BORE .47 DP. 4 HOLES")],
                general_tol={3: 0.005, 2: 0.01}, units_hint="inch")
    flags = check(_cbore_key(cbore_depth=0.40), d)
    assert [f.kind for f in flags] == ["unexplained_key_value"] * 4
    assert all("cbore_depth" in f.detail for f in flags)


def test_counterbore_by_screw_standard_needs_no_printed_size():
    holes = [Feature(id=f"K{i}", type="counterbore", axis=[0, 0, 1], center=[x, y, 0], d=0.201,
                     depth=0.5, thru=True, cbore_d=0.332, cbore_depth=0.19)
             for i, (x, y) in enumerate([(x, y) for y in (0.5, 3.5) for x in (0.5, 1.5, 2.5, 3.5)], 1)]
    k = Key(part="P", units="inch", source="s", envelope=[4.0, 4.0, 0.5], features=holes)
    d = Drawing(dims=[_lin(4.0), _lin(4.0), _lin(0.5), _lin(1.0), _lin(3.0)],
                callouts=[parse("DR. & C'BORE FOR #10 SOC. HD. CAP SCR. 8-HOLES")],
                general_tol={3: 0.005}, units_hint="inch")
    assert check(k, d) == []


def test_bolt_circle_position_explained_by_pattern_diameter():
    holes = [Feature(id=f"H{i}", type="thru_hole", axis=[0, 0, 1],
                     center=[2 + 1.5 * math.cos(math.radians(a)), 2 + 1.5 * math.sin(math.radians(a)), 0],
                     d=0.281, depth=0.5, thru=True)
             for i, a in enumerate(range(15, 360, 60), 1)]
    pat = Feature(id="P1", type="hole_pattern", members=[h.id for h in holes],
                  pattern={"mode": "circle", "count": 6, "radius": 1.5})
    k = Key(part="P", units="inch", source="s", envelope=[4.0, 4.0, 0.5], features=holes + [pat])
    d = Drawing(dims=[_lin(4.0), _lin(4.0), _lin(0.5), _lin(3.0, text="<> B.C.", kind="diameter")],
                callouts=[parse(".281 DIA. THRU (6) HLS.")], general_tol={3: 0.005}, units_hint="inch")
    assert check(k, d) == []


def test_bolt_circle_diameter_does_not_explain_a_hole_diameter():
    k = _key()
    for f in k.features:
        f.d = 2.0
    d = _drawing()
    d.callouts = []
    d.dims.append(_lin(2.0, text="<> B.C.", kind="diameter"))
    kinds = [f.kind for f in check(k, d)]
    assert kinds.count("unexplained_key_value") == 4


def test_two_decimal_dim_uses_its_own_general_tolerance():
    d = _drawing()
    d.dims[1] = _lin(2.99, dec=2)               # 3.00 in the key; general_tol[2] = .01
    assert check(_key(), d) == []
    d.dims[1] = _lin(2.99, dec=3)               # general_tol[3] = .005 -> flagged
    assert [f.kind for f in check(_key(), d)] == ["unexplained_drawing_value"]


def test_fallback_tolerance_without_general_tol():
    d = _drawing()
    d.general_tol = {}
    d.dims[0] = _lin(4.004, dec=3)
    assert check(_key(), d) == []


def test_not_to_scale_dim_is_matched_by_its_shown_value():
    d = _drawing()
    d.dims[0] = _lin(4.0, measured=4.37, nts=True)
    assert check(_key(), d) == []


def test_no_units_hint_gives_no_units_flag():
    d = _drawing()
    d.units_hint = None
    assert check(_key(), d) == []


def test_callout_for_a_hole_the_key_lacks_is_flagged():
    d = _drawing()
    d.callouts.append(parse(".125 DIA. THRU"))
    assert [f.kind for f in check(_key(), d)] == ["count_mismatch"]


def test_mm_key_with_metric_tap():
    holes = [Feature(id="K1", type="blind_hole", axis=[0, 0, 1], center=[10.0, 10.0, 0], d=5.0,
                     depth=12.0, thru=False)]
    k = Key(part="P", units="mm", source="s", envelope=[40.0, 20.0, 15.0], features=holes)
    d = Drawing(dims=[_lin(40.0, dec=1), _lin(20.0, dec=1), _lin(15.0, dec=1), _lin(10.0, dec=1)],
                callouts=[parse("M6 X 1.0 TAP 10 DP.")], general_tol={1: 0.1}, units_hint="mm")
    assert check(k, d) == []
    assert k.features[0].type == "tapped_hole" and k.features[0].thread == "M6X1.0"


def test_bolt_circle_about_the_part_centre_without_a_pattern():
    h = Feature(id="H1", type="thru_hole", axis=[0, 0, 1],
                center=[2 + 1.5 * math.cos(0.3), 2 + 1.5 * math.sin(0.3), 0], d=0.281, depth=0.5, thru=True)
    k = Key(part="P", units="inch", source="s", envelope=[4.0, 4.0, 0.5], features=[h])
    d = Drawing(dims=[_lin(4.0), _lin(0.5), _lin(3.0, text="<> B.C.", kind="diameter")],
                callouts=[parse(".281 DIA. THRU")], general_tol={3: 0.005}, units_hint="inch")
    assert check(k, d) == []


def test_section_view_linear_dim_with_diameter_symbol_states_a_hole_size():
    d = _drawing()
    d.callouts = []
    d.dims.append(_lin(0.344, text="\u00d8<>"))
    d.dims.append(_lin(0.344, text="%%C<>"))
    assert [f.kind for f in check(_key(), d)] == []
    d.dims = d.dims[:-2] + [_lin(0.344, text="<>")]     # no diameter mark: not a hole size
    assert {f.kind for f in check(_key(), d)} == {"unexplained_key_value"}


# ---- review fixes ----------------------------------------------------------------------------

def _holes(spec):
    """[(d, x, y)] -> thru holes on a 4 x 3 x .5 plate."""
    return Key(part="P", units="inch", source="s", envelope=[4.0, 3.0, 0.5],
               features=[Feature(id=f"K{i}", type="thru_hole", axis=[0, 0, 1], center=[x, y, 0], d=d,
                                 depth=0.5, thru=True) for i, (d, x, y) in enumerate(spec, 1)])


def test_stated_plain_hole_at_tap_major_diameter_is_not_relabelled():
    k = _holes([(0.201, 0.5, 0.5), (0.201, 3.5, 0.5), (0.250, 0.5, 2.5)])
    d = Drawing(dims=_plate_dims(), callouts=[parse("1/4-20 TAP THRU (2) HLS."), parse(".250 DIA. THRU")],
                general_tol={3: 0.005}, units_hint="inch")
    assert check(k, d) == []
    assert [f.type for f in k.features] == ["tapped_hole", "tapped_hole", "thru_hole"]


def test_stated_drill_inside_a_tap_window_is_not_relabelled():
    k = _holes([(0.2031, 0.5, 0.5), (0.2130, 3.5, 0.5)])
    d = Drawing(dims=[_lin(4.0), _lin(3.0), _lin(0.5), _lin(3.0)],
                callouts=[parse(".2031 DR. THRU"), parse(".250-28 TAP")],
                general_tol={3: 0.005, 4: 0.0005}, units_hint="inch")
    assert check(k, d) == []
    assert [(f.type, f.thread) for f in k.features] == [("thru_hole", ""), ("tapped_hole", ".250-28")]


def test_small_screw_tap_works():
    k = _holes([(0.070, 0.5, 0.5)])
    d = Drawing(dims=[_lin(4.0), _lin(3.0), _lin(0.5)], callouts=[parse("#2-56 TAP .25 DP.")],
                general_tol={3: 0.005}, units_hint="inch")
    assert check(k, d) == []
    assert k.features[0].thread == "#2-56"


def test_unknown_thread_size_is_flagged_not_raised():
    k = _holes([(0.070, 0.5, 0.5)])
    c = parse("#14-20 TAP .5 DP.")
    assert c is not None and c.kind == "tap"
    d = Drawing(dims=[_lin(4.0), _lin(3.0), _lin(0.5)], callouts=[c, parse(".070 DIA. THRU")],
                general_tol={3: 0.005}, units_hint="inch")
    assert [f.kind for f in check(k, d)] == ["unparsed_thread"]


def test_bc_from_callout_locates_pattern_holes():
    holes = [Feature(id=f"H{i}", type="thru_hole", axis=[0, 0, 1],
                     center=[3 + 1.5 * math.cos(math.radians(a)), 2 + 1.5 * math.sin(math.radians(a)), 0],
                     d=0.344, depth=0.5, thru=True)
             for i, a in enumerate(range(15, 360, 60), 1)]
    pat = Feature(id="P1", type="hole_pattern", members=[h.id for h in holes],
                  pattern={"mode": "circle", "count": 6, "radius": 1.5})
    k = Key(part="P", units="inch", source="s", envelope=[6.0, 4.0, 0.5], features=holes + [pat])
    d = Drawing(dims=[_lin(6.0), _lin(4.0), _lin(0.5)],
                callouts=[parse(".344 DIA. THRU (6) HLS. EQ. SP. ON 3.000 B.C.")],
                general_tol={3: 0.005}, units_hint="inch")
    flags = check(k, d)
    assert [f.kind for f in flags] == []


def test_small_chamfer_dims_are_not_flagged():
    d = _drawing()
    d.dims.append(_lin(0.03, text="<> X 45%%D"))
    d.dims.append(_lin(0.02, text="BREAK EDGES <>"))
    assert check(_key(), d) == []
    d.dims.append(_lin(0.03))
    assert [f.kind for f in check(_key(), d)] == ["unexplained_drawing_value"]


def _ring(n=50, r=4.0):
    holes = [Feature(id=f"H{i}", type="thru_hole", axis=[0, 0, 1],
                     center=[5 + r * math.cos(2 * math.pi * i / n), 5 + r * math.sin(2 * math.pi * i / n), 0],
                     d=0.201, depth=0.75, thru=True) for i in range(n)]
    return Key(part="P", units="inch", source="s", envelope=[10.0, 10.0, 0.75], features=holes)


def test_hole_dense_part_does_not_explain_random_dims_by_chance():
    import random
    rng = random.Random(7)
    k = _ring()
    good = Drawing(dims=[_lin(10.0), _lin(10.0), _lin(0.75), _lin(8.0, text="<> B.C.", kind="diameter")],
                   callouts=[parse(".201 DIA. THRU (50) HLS.")], general_tol={3: 0.005}, units_hint="inch")
    assert check(k, good) == []
    junk = [_lin(round(rng.uniform(0.1, 10.0), 3), dec=3) for _ in range(30)]
    bad = Drawing(dims=good.dims + junk, callouts=good.callouts, general_tol={3: 0.005}, units_hint="inch")
    flagged = sum(1 for f in check(k, bad) if f.kind == "unexplained_drawing_value")
    assert flagged >= 0.8 * len(junk)


def test_baseline_dims_from_a_datum_hole():
    """Legacy style: first hole located from the edge, the rest baseline-dimensioned from it."""
    k = Key(part="P", units="inch", source="s", envelope=[5.25, 1.75, 0.25],
            features=[Feature(id=f"K{i}", type="thru_hole", axis=[0, 0, 1], center=[x, 0.875, 0], d=0.201,
                              depth=0.25, thru=True) for i, x in enumerate([0.5, 1.5, 3.0, 4.25], 1)])
    d = Drawing(dims=[_lin(5.25), _lin(1.75), _lin(0.25), _lin(0.5), _lin(1.0), _lin(2.5), _lin(3.75)],
                callouts=[parse(".201 DIA. THRU (4) HLS.")], general_tol={3: 0.005, 2: 0.01},
                units_hint="inch")
    assert check(k, d) == []


def _disc_with_bc_callout(bc):
    holes = [Feature(id=f"H{i}", type="thru_hole", axis=[0, 0, 1],
                     center=[2 + 1.5 * math.cos(math.radians(a)), 2 + 1.5 * math.sin(math.radians(a)), 0],
                     d=0.344, depth=0.5, thru=True)
             for i, a in enumerate(range(45, 360, 90), 1)]
    pat = Feature(id="P1", type="hole_pattern", members=[h.id for h in holes],
                  pattern={"mode": "circle", "count": 4, "radius": 1.5})
    k = Key(part="P", units="inch", source="s", envelope=[4.0, 4.0, 0.5], features=holes + [pat])
    d = Drawing(dims=[_lin(4.0, kind="diameter"), _lin(0.5)],
                callouts=[parse(f".344 DIA. THRU (4) HLS. EQ. SP. ON {bc} B.C.")],
                general_tol={3: 0.005}, units_hint="inch")
    return k, d


def test_callout_bolt_circle_is_checked_against_the_key():
    assert check(*_disc_with_bc_callout("3.000")) == []
    flags = check(*_disc_with_bc_callout("3.500"))
    wrong = [f for f in flags if f.kind == "unexplained_drawing_value"]
    assert len(wrong) == 1 and "3.500 B.C." in wrong[0].detail


# ---- first real-data run (synthetic) ---------------------------------------------------------

def _screw_cbores():
    """4 counterbores sized for a .500 screw and 2 big ones that are not."""
    pts = [(0.5, 0.5), (3.5, 0.5), (0.5, 3.5), (3.5, 3.5)]
    holes = [Feature(id=f"S{i}", type="counterbore", axis=[0, 0, 1], center=[x, y, 0], d=0.531,
                     depth=1.0, thru=True, cbore_d=0.812, cbore_depth=0.53) for i, (x, y) in enumerate(pts, 1)]
    holes += [Feature(id=f"B{i}", type="counterbore", axis=[0, 0, 1], center=[x, 2.0, 0], d=1.25,
                      depth=1.0, thru=True, cbore_d=1.75, cbore_depth=0.6) for i, x in enumerate((1.5, 2.5), 1)]
    return Key(part="P", units="inch", source="s", envelope=[4.0, 4.0, 1.0], features=holes)


_BIG = "1.250 DR. THRU & 1.750 C'BORE .60 DP. (2) HOLES"


def _screw_drawing(*extra):
    return Drawing(dims=[_lin(4.0), _lin(1.0), _lin(0.5), _lin(3.0), _lin(2.0), _lin(1.5)],
                   callouts=[parse("DR. & C'BORE AS SHOWN FOR .500 SOC. HD. SCR. (4)HOLES"), *extra],
                   general_tol={3: 0.005, 2: 0.01}, units_hint="inch")


def test_screw_cbore_skips_sizes_only_of_counterbores_that_fit_the_screw():
    assert check(_screw_cbores(), _screw_drawing(parse(_BIG))) == []
    flags = check(_screw_cbores(), _screw_drawing())
    assert {f.feature for f in flags if f.kind == "unexplained_key_value"} == {"B1", "B2"}


def test_screw_cbore_count_uses_counterbores_that_fit_the_screw():
    k = _screw_cbores()
    k.features = k.features[1:]
    flags = check(k, _screw_drawing(parse(_BIG)))
    assert [f.kind for f in flags if f.kind == "count_mismatch"] == ["count_mismatch"]
    assert "says 4, key has 3" in flags[-1].detail


def test_generic_cbore_depth_note_does_not_bind_every_counterbore():
    """A bare "C'BORE .38 DP." leader note names no size: other counterbores may take their
    depth from a dimension."""
    d = Drawing(dims=_plate_dims() + [_lin(0.47)],
                callouts=[parse(".344 DR. THRU & .562 C'BORE (4) HOLES"), parse("C'BORE .38 DP.")],
                general_tol={3: 0.005, 2: 0.01}, units_hint="inch")
    assert check(_cbore_key(cbore_depth=0.47), d) == []


def test_same_thread_callouts_add_up():
    k = Key(part="P", units="inch", source="s", envelope=[6.0, 1.0, 1.0],
            features=[Feature(id=f"K{i}", type="blind_hole", axis=[0, 0, 1], center=[float(i), 0.5, 1.0],
                              d=0.4219, depth=1.0, thru=False) for i in range(1, 6)])
    d = Drawing(dims=[_lin(6.0), _lin(1.0), _lin(0.5)],
                callouts=[parse(".500-13 TAP FOR LIFT RING"), parse(".500-13 TAP 1.00 DP. (4) HOLES")],
                general_tol={3: 0.005, 2: 0.01}, units_hint="inch")
    assert [f for f in check(k, d) if f.kind == "count_mismatch"] == []
    d.callouts[1] = parse(".500-13 TAP 1.00 DP. (3) HOLES")
    assert [f.kind for f in check(k, d) if f.kind == "count_mismatch"] == ["count_mismatch"]
