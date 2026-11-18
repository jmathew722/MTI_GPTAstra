"""Drawing-callout parser for hole and thread callouts (Stage 4, task 4.4)."""
import pytest

from pipeline.hole_callouts import parse


def val(f):
    return None if f is None else f.value


def test_through_hole_with_quantity_and_diameter_keeps_source_spans():
    r = parse("2X Ø.250 THRU")
    assert val(r.quantity) == 2 and val(r.diameter) == pytest.approx(0.25) and val(r.end) == "through"
    assert r.family == "hole"
    assert r.raw[r.diameter.span[0]:r.diameter.span[1]].replace(" ", "") == "Ø.250"
    assert r.raw[r.quantity.span[0]:r.quantity.span[1]].strip().upper().startswith("2")
    assert r.diameter.confidence >= 0.9 and r.diameter.rule


@pytest.mark.parametrize("text,qty", [("4 PLCS Ø6.5 THRU", 4), ("(2) Ø6.5 THRU", 2), ("3X Ø6.5 THRU", 3), ("Ø6.5 THRU", None),
                                      ("6 HOLES Ø6.5 THRU", 6), ("4 PLACES Ø6.5 THRU", 4)])
def test_quantity_forms(text, qty):
    assert val(parse(text).quantity) == qty


def test_blind_hole_depth():
    r = parse("Ø.375 X .75 DEEP")
    assert r.family == "hole" and val(r.end) == "blind" and val(r.depth) == pytest.approx(0.75)
    r2 = parse("Ø6 ↧ 12")
    assert val(r2.end) == "blind" and val(r2.depth) == 12


def test_counterbore_and_countersink():
    cb = parse("Ø.250 THRU ⌴ Ø.438 X .25 DEEP")
    assert cb.family == "counterbore" and val(cb.cbore_diameter) == pytest.approx(0.438) and val(cb.cbore_depth) == pytest.approx(0.25)
    assert val(cb.diameter) == pytest.approx(0.25) and val(cb.end) == "through"
    cs = parse("Ø.250 THRU ⌵ Ø.500 X 82°")
    assert cs.family == "countersink" and val(cs.csink_diameter) == pytest.approx(0.5) and val(cs.csink_angle) == 82
    assert parse("Ø8.5 THRU CSK Ø16 X 90°").family == "countersink"
    assert parse("Ø6.6 CBORE Ø11 X 6.5 DEEP").family == "counterbore"


def test_straight_threads_metric_and_inch_with_class_and_series():
    m = parse("M6 X 1 - 6H")
    assert m.family == "straight_tap" and m.thread["system"] == "metric" and m.thread["size"] == "M6" and m.thread["pitch"] == 1.0
    assert m.thread["class"] == "6H" and m.thread["designation"].startswith("M6")
    i = parse("1/4-20 UNC-2B")
    assert i.thread["system"] == "inch" and i.thread["size"] == "1/4" and i.thread["tpi"] == 20 and i.thread["series"] == "UNC" and i.thread["class"] == "2B"
    n = parse("#10-32 UNF-2B")
    assert n.thread["size"] == "#10" and n.thread["tpi"] == 32 and n.thread["series"] == "UNF"
    assert parse("3/8-16 UNC THRU").family == "straight_tap" and val(parse("3/8-16 UNC THRU").end) == "through"


def test_thread_depth_and_drill_depth_are_separate_when_labeled_and_ambiguous_when_not():
    both = parse("M6 X 1 - 6H THD DEPTH 10 DRILL DEPTH 12")
    assert val(both.thread_depth) == 10 and val(both.drill_depth) == 12 and "depth_applies_to_thread_or_drill" not in both.ambiguities
    one = parse("M6 X 1 - 12 DEEP")
    assert val(one.depth) == 12 and "depth_applies_to_thread_or_drill" in one.ambiguities       # one number, two possible meanings
    assert one.thread_depth is None and one.drill_depth is None                                   # never copied to both
    alt = parse("1/4-20 UNC Ø.201 DRILL .75 DEEP THD .50 DEEP")
    assert val(alt.thread_depth) == pytest.approx(0.5) and val(alt.drill_depth) == pytest.approx(0.75)


def test_pipe_taps_are_a_separate_family_and_the_standard_is_never_inferred():
    for text, std in (("1/4 NPT", "NPT"), ("1/8-27 NPT", "NPT"), ("1/4 NPTF", "NPTF"), ("1/4 BSPT", "BSPT"), ("Rc 1/4", "Rc")):
        r = parse(text)
        assert r.family == "pipe_tap" and r.thread["standard"] == std, text
    vague = parse("1/4 PIPE TAP")
    assert vague.family == "pipe_tap" and vague.thread.get("standard") is None and "pipe_standard_unspecified" in vague.ambiguities
    assert parse("1/4-20 UNC").family == "straight_tap"


def test_slots_with_an_unspecified_length_scheme_are_flagged():
    r = parse(".250 X .750 SLOT")
    assert r.family == "slot" and val(r.slot_width) == pytest.approx(0.25) and val(r.slot_length) == pytest.approx(0.75)
    assert "slot_length_scheme_unspecified" in r.ambiguities
    assert "slot_length_scheme_unspecified" not in parse(".250 X .750 OVERALL SLOT").ambiguities
    assert "slot_length_scheme_unspecified" not in parse("Ø6 SLOT 20 C-C THRU").ambiguities
    assert parse(".250 X .750 SLOT THRU ⌴ Ø.5 X .2 DEEP").family == "counterbore_slot"
    assert parse("6 X 20 SLOT ⌵ Ø12 X 90°").family == "countersink_slot"


def test_fits_and_tolerances():
    assert parse("Ø.2500 H7 THRU").fit.value == "H7"
    assert parse("Ø6 H7/h6").fit.value == "H7/h6"
    assert parse("Ø6 PRESS FIT").fit.value == "PRESS FIT" and parse("Ø6 SLIP FIT THRU").fit.value == "SLIP FIT"
    r = parse("Ø6.5 ±0.1 THRU")
    assert val(r.diameter) == pytest.approx(6.5) and val(r.tolerance) == pytest.approx(0.1)
    assert parse("M6 X 1").fit is None                                    # a metric thread is not a fit


def test_sides_datums_and_advanced_hole_candidates():
    assert parse("Ø6 THRU NEAR SIDE ⌵ Ø12 X 90°").sides == ["near"]
    assert sorted(parse("Ø6 THRU BOTH SIDES ⌵ Ø12 X 90°").sides) == ["far", "near"]
    d = parse("DATUM A Ø.250 THRU")
    assert d.datum.value == "A" and d.family == "hole"
    adv = parse("NEAR SIDE Ø6 X 8 DEEP, FAR SIDE Ø4 X 5 DEEP")
    assert "advanced_hole_candidate" in adv.ambiguities and adv.family == "hole"


def test_ocr_damage_lowers_confidence_but_is_still_read():
    r = parse("O.250 THRU")
    assert val(r.diameter) == pytest.approx(0.25) and r.diameter.confidence < 0.8 and r.diameter.rule == "ocr_diameter_symbol"
    assert parse("⌀.250 THRU").diameter.confidence >= 0.9
    assert val(parse("0.250 THRU").diameter) is None or parse("0.250 THRU").diameter.confidence < 0.8   # a bare number is not asserted to be a diameter


def test_fractions_and_dia_word():
    assert val(parse("1/4 DIA THRU").diameter) == pytest.approx(0.25)
    assert val(parse(".375 DIA X .5 DEEP").diameter) == pytest.approx(0.375)
    assert val(parse("Ø1 1/4 THRU").diameter) == pytest.approx(1.25)


@pytest.mark.parametrize("text", ["SCALE 1:2", "MATERIAL: 6061-T6", "BREAK ALL EDGES .02 MAX", "REV A", "", "   "])
def test_non_hole_text_yields_no_family_and_no_invented_fields(text):
    r = parse(text)
    assert r.family is None and r.diameter is None and r.thread is None and r.confidence == 0.0


def test_legacy_dashed_and_spaced_variants_and_unicode_normalization():
    assert val(parse("2 X ∅.250 THRU").diameter) == pytest.approx(0.25)
    assert val(parse("2× Ø.250 THRU").quantity) == 2
    assert val(parse("  Ø.250   THRU  ").diameter) == pytest.approx(0.25)
    assert parse("Ø.250 THRU ALL").end.value == "through"


def test_result_serializes_with_every_field_traceable():
    import json
    r = parse("2X Ø.250 THRU ⌴ Ø.438 X .25 DEEP")
    d = r.to_dict()
    json.dumps(d)
    assert d["raw"] and d["family"] == "counterbore"
    for key in ("quantity", "diameter", "end", "cbore_diameter", "cbore_depth"):
        assert set(d[key]) >= {"value", "span", "rule", "confidence"}


@pytest.mark.parametrize("text,d", [(".188 \u00d8", 0.188), (".281 \u00d8-B", 0.281), (".5003 \u00d8 \u00b1.0003", 0.5003), ("1/4 \u00d8 THRU", 0.25), (".203 \u2300", 0.203)])
def test_trailing_diameter_symbol_as_written_on_the_real_drawings(text, d):
    r = parse(text)
    assert val(r.diameter) == pytest.approx(d) and r.diameter.rule == "diameter_symbol_trailing" and r.family == "hole"
    assert r.raw[r.diameter.span[0]:r.diameter.span[1]].replace(" ", "").endswith("\u00d8")


def test_trailing_symbol_does_not_steal_a_leading_symbol_or_a_quantity():
    r = parse("2X \u00d8.250 THRU")
    assert r.diameter.rule == "diameter_symbol" and val(r.quantity) == 2
    assert parse("4X .188 \u00d8").quantity.value == 4
