"""Automatic, page-aware callout localization (Stage 3, task 3.2)."""
import pytest

from pipeline.flag_locator import (
    BOX_THRESHOLD, Box, PageData, locate_callout, normalize_rect,
)

W, H = 612.0, 792.0


def page(idx, boxes, rotation=0, w=W, h=H, source="text_layer"):
    return PageData(index=idx, width=w, height=h, rotation=rotation, source=source,
                    boxes=[Box(text=t, rect=list(r), conf=c) for t, r, c in boxes])


def loc(callout, pages, **kw):
    return locate_callout(callout, pages, **kw)


# ---- strategies, in order ------------------------------------------------------------------------
def test_exact_token_sequence_on_a_text_layer_is_located_with_high_confidence():
    p = page(0, [("NOTES: UNLESS OTHERWISE SPECIFIED", (50, 700, 300, 712), 1.0),
                 ("M6 X 1 - 12 DEEP", (200, 300, 290, 312), 1.0)])
    r = loc("M6 X 1 - 12 DEEP", [p])
    assert r.located and r.method == "exact_tokens" and r.page_index == 0
    assert r.matched_text == "M6 X 1 - 12 DEEP"
    assert r.confidence >= 0.95
    n = r.rect_normalized
    assert (round(n["x"], 3), round(n["y"], 3)) == (round(200 / W, 3), round(300 / H, 3))
    assert round(n["width"], 3) == round(90 / W, 3) and round(n["height"], 3) == round(12 / H, 3)


def test_punctuation_and_unit_differences_still_match_by_normalized_text():
    p = page(0, [("M6x1-12DEEP", (200, 300, 280, 312), 0.95)])
    r = loc("M6 X 1 - 12 DEEP", [p])
    assert r.located and r.method == "normalized"
    q = page(0, [("Ø.250 THRU", (100, 100, 170, 112), 1.0)])
    assert loc("Ø.250 THRU (IN)", [q]).located


def test_ocr_diameter_symbol_confused_with_zero_or_letter_o():
    for read in ("0.250 THRU", "O.250 THRU", "⌀.250 THRU", "Ø.250 THRU"):
        r = loc("Ø.250 THRU", [page(0, [(read, (100, 100, 170, 112), 0.8)], source="ocr")])
        assert r.located, read
    r = loc("Ø6 THRU", [page(0, [("06 THRU", (100, 100, 150, 112), 0.8)], source="ocr")])
    assert r.located


def test_fractions_match_with_ocr_spacing_and_dash_noise():
    r = loc("1/4-20 UNC", [page(0, [("1/4 -20UNC", (100, 100, 170, 112), 0.85)], source="ocr")])
    assert r.located and r.confidence >= BOX_THRESHOLD


def test_constrained_fuzzy_match_requires_strict_numeric_agreement():
    p = page(0, [("M6 X 1 - 12 DEEP.", (200, 300, 290, 312), 0.9), ("THRU ALL", (10, 10, 60, 22), 0.9)])
    r = loc("M6 X 1 - 12 DEPP", [p])                  # a misread letter, every number intact
    assert r.located and r.method == "fuzzy"
    # contradictory numbers are never a match, however similar the rest looks
    q = page(0, [("M6 X 1.5 - 12 DEEP", (200, 300, 290, 312), 0.99)])
    r2 = loc("M6 X 1 - 12 DEEP", [q])
    assert not r2.located and r2.reason == "no_match"
    s = page(0, [("Ø.275 THRU", (100, 100, 170, 112), 1.0)])
    assert not loc("Ø.250 THRU", [s]).located


def test_no_match_is_honestly_unlocated():
    r = loc("1/4-20 UNC", [page(0, [("SOMETHING ELSE ENTIRELY", (10, 10, 100, 22), 1.0)])])
    assert not r.located and r.reason == "no_match" and r.rect_normalized is None and r.confidence == 0.0


# ---- ambiguity -----------------------------------------------------------------------------------
def test_duplicate_callout_on_one_page_is_ambiguous_not_guessed():
    p = page(0, [("2X Ø.250 THRU", (100, 100, 180, 112), 1.0), ("2X Ø.250 THRU", (100, 400, 180, 412), 1.0)])
    r = loc("2X Ø.250 THRU", [p])
    assert not r.located and r.reason == "ambiguous" and r.candidates == 2 and r.likely_page == 0


def test_a_hint_inside_one_candidate_resolves_the_tie():
    p = page(0, [("2X Ø.250 THRU", (100, 100, 180, 112), 1.0), ("2X Ø.250 THRU", (100, 400, 180, 412), 1.0)])
    hint = {"x": 0.1, "y": 0.45, "width": 0.4, "height": 0.1}      # the view the feature belongs to
    r = loc("2X Ø.250 THRU", [p], hint_region=hint, hint_page=0)
    assert r.located and r.rect_normalized["y"] == pytest.approx(400 / H, abs=1e-3)


def test_same_callout_on_two_pages_is_ambiguous_unless_the_page_is_known():
    a = page(0, [("M6 X 1 - 12 DEEP", (200, 300, 290, 312), 1.0)])
    b = page(1, [("M6 X 1 - 12 DEEP", (50, 80, 140, 92), 1.0)])
    assert loc("M6 X 1 - 12 DEEP", [a, b]).reason == "ambiguous"
    r = loc("M6 X 1 - 12 DEEP", [a, b], hint_page=1)
    assert r.located and r.page_index == 1


def test_a_smaller_box_wins_when_it_lies_inside_a_larger_match():
    p = page(0, [("2X Ø.250 THRU ALL (SEE NOTE 4)", (100, 100, 330, 112), 1.0), ("Ø.250 THRU", (150, 100, 230, 112), 1.0)])
    r = loc("Ø.250 THRU", [p])
    assert r.located and r.matched_text == "Ø.250 THRU"


def test_two_line_callouts_are_matched_across_adjacent_lines():
    p = page(0, [("M6 X 1", (200, 300, 240, 312), 1.0), ("12 DEEP", (200, 313, 240, 325), 1.0), ("12 DEEP", (50, 600, 90, 612), 1.0)])
    r = loc("M6 X 1 12 DEEP", [p])
    assert r.located and r.method in ("exact_tokens", "normalized")
    assert r.rect_normalized["height"] == pytest.approx(25 / H, abs=1e-3)       # the union of both lines


# ---- rotation and scans --------------------------------------------------------------------------
@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_normalize_rect_is_expressed_in_the_unrotated_page(rot):
    Wu, Hu = 600.0, 400.0                                  # the unrotated page
    # a box at the TOP-LEFT of the unrotated page, as displayed at each rotation
    disp = {0: (Wu, Hu, [0, 0, 60, 40]), 90: (Hu, Wu, [Hu - 40, 0, Hu, 60]),
            180: (Wu, Hu, [Wu - 60, Hu - 40, Wu, Hu]), 270: (Hu, Wu, [0, Wu - 60, 40, Wu])}[rot]
    n = normalize_rect(disp[2], disp[0], disp[1], rot)
    assert n["x"] == pytest.approx(0, abs=1e-6) and n["y"] == pytest.approx(0, abs=1e-6)
    assert n["width"] == pytest.approx(60 / Wu) and n["height"] == pytest.approx(40 / Hu)


def test_a_rotated_page_returns_unrotated_coordinates_and_the_rotation():
    p = page(0, [("M6 X 1 - 12 DEEP", (360, 0, 400, 60), 1.0)], rotation=90, w=400.0, h=600.0)   # unrotated 600x400
    r = loc("M6 X 1 - 12 DEEP", [p])
    assert r.located and r.rotation_degrees == 90
    assert r.rect_normalized["x"] == pytest.approx(0, abs=1e-6) and r.rect_normalized["y"] == pytest.approx(0, abs=1e-6)


def test_scanned_pages_with_low_ocr_confidence_lose_confidence_but_can_still_place():
    hi = loc("M6 X 1 - 12 DEEP", [page(0, [("M6 X 1 - 12 DEEP", (200, 300, 290, 312), 1.0)], source="ocr")])
    lo = loc("M6 X 1 - 12 DEEP", [page(0, [("M6 X 1 - 12 DEEP", (200, 300, 290, 312), 0.55)], source="ocr")])
    assert hi.located and lo.confidence < hi.confidence


# ---- weaker evidence never draws a misleading precise box --------------------------------------
def test_a_big_extraction_region_is_unlocated_with_the_likely_page_not_a_box():
    big = {"x": 0.05, "y": 0.1, "width": 0.7, "height": 0.6}
    r = loc("NO SUCH TEXT", [page(0, [("OTHER", (10, 10, 50, 22), 1.0)])], hint_region=big, hint_page=0)
    assert not r.located and r.likely_page == 0 and r.likely_region == big and r.reason == "region_too_coarse"


def test_a_tiny_extraction_region_may_be_boxed_at_lower_confidence():
    tiny = {"x": 0.30, "y": 0.40, "width": 0.10, "height": 0.02}
    r = loc("NO SUCH TEXT", [page(0, [("OTHER", (10, 10, 50, 22), 1.0)])], hint_region=tiny, hint_page=0)
    assert r.located and r.method == "extraction_region" and BOX_THRESHOLD <= r.confidence < 0.9


def test_a_view_hint_without_text_evidence_gives_view_level_only():
    r = loc("NO SUCH TEXT", [page(0, [("OTHER", (10, 10, 50, 22), 1.0)])], hint_view="FRONT", hint_page=0)
    assert not r.located and r.likely_view == "FRONT" and r.likely_page == 0 and r.reason == "view_level"


# ---- calibration: the threshold is derived from labeled fixtures, not chosen for convenience -----
CAL_TRUE = [  # (callout, page) -> must be located with confidence >= BOX_THRESHOLD
    ("M6 X 1 - 12 DEEP", page(0, [("M6 X 1 - 12 DEEP", (200, 300, 290, 312), 1.0)])),
    ("M6 X 1 - 12 DEEP", page(0, [("M6x1-12DEEP", (200, 300, 280, 312), 0.7)], source="ocr")),
    ("Ø.250 THRU", page(0, [("0.250 THRU", (100, 100, 170, 112), 0.6)], source="ocr")),
    ("1/4-20 UNC", page(0, [("1/4 -20UNC", (100, 100, 170, 112), 0.6)], source="ocr")),
    ("M6 X 1 - 12 DEPP", page(0, [("M6 X 1 - 12 DEEP", (200, 300, 290, 312), 0.6)], source="ocr")),
]
CAL_FALSE = [  # near-misses that must NOT yield a precise box
    ("M6 X 1 - 12 DEEP", page(0, [("M6 X 1.5 - 12 DEEP", (200, 300, 290, 312), 1.0)])),
    ("Ø.250 THRU", page(0, [("Ø.275 THRU", (100, 100, 170, 112), 1.0)])),
    ("2X Ø.250 THRU", page(0, [("2X Ø.250 THRU", (10, 10, 80, 22), 1.0), ("2X Ø.250 THRU", (10, 400, 80, 412), 1.0)])),
    ("1/4-20 UNC", page(0, [("1/4-28 UNF", (100, 100, 170, 112), 1.0)])),
]


def test_box_threshold_separates_the_calibration_fixtures():
    true_conf = [locate_callout(c, [p]).confidence for c, p in CAL_TRUE if locate_callout(c, [p]).located]
    assert len(true_conf) == len(CAL_TRUE), "every true fixture must be located"
    false_boxed = [c for c, p in CAL_FALSE if locate_callout(c, [p]).located]
    assert false_boxed == [], "a near-miss was boxed"
    assert min(true_conf) >= BOX_THRESHOLD
    # and the threshold is not looser than needed: it sits at or below the weakest true match
    assert BOX_THRESHOLD <= min(true_conf) <= BOX_THRESHOLD + 0.20
