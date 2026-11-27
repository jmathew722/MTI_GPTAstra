"""v8 replication: DrawingSpec, tiling/merge, sheet sizing, line detection, verbatim notes, status decisions, scale parsing. Offline (PyMuPDF only)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from reverse import drawingspec as ds
from reverse import replicate as rp
from reverse import srcmap
from reverse.reflayout import parse_scale

PT = srcmap.PT_TO_M


# ---------------------------------------------------------------- scale parsing
@pytest.mark.parametrize("text,want", [('SCALE 1" = 2"', (1, 2)), ('1"=2"', (1, 2)), ("1:2", (1, 2)), ("2:1", (2, 1)), ("HALF", (1, 2)), ("FULL", (1, 1)),
                                       ("1 IN = 1 IN", (1, 1)), ("junk", None), ("", None)])
def test_parse_scale_notations(text, want):
    assert parse_scale(text) == want


# ---------------------------------------------------------------- sheet sizing
def test_sheet_target_standard_snaps_and_custom_keeps_own_size():
    t = rp.sheet_target({"width_pt": 1580, "height_pt": 1216})
    assert t["ok"] and t["name"] == "ANSI C" and t["standard"] and t["w_m"] == pytest.approx(0.5588)
    p = rp.sheet_target({"width_pt": 1216, "height_pt": 1580})            # portrait stays portrait
    assert p["name"] == "ANSI C" and p["w_m"] < p["h_m"]
    c = rp.sheet_target({"width_pt": 700, "height_pt": 700})
    assert c["name"] == "custom" and not c["standard"] and c["w_m"] == pytest.approx(700 * PT)
    assert not rp.sheet_target({"width_pt": 0, "height_pt": 0})["ok"]


def test_override_regions_uses_source_title_block_and_sheet():
    tgt = rp.sheet_target({"width_pt": 1580, "height_pt": 1216})
    fr = rp.make_frame({"width_pt": 1580, "height_pt": 1216}, tgt)
    plan = {}
    reg = rp.override_regions(plan, fr, tgt, [1000, 800, 1580, 1216])
    tb = reg["title_block"]
    assert tb[0] < tb[2] and tb[1] < tb[3] and tb[3] == pytest.approx(fr.to_sheet(0, 800)[1], abs=1e-6)
    assert plan["sheet_custom"]["w_m"] == pytest.approx(0.5588)
    assert plan["replication"]["frame"]["k_m_per_pt"] == pytest.approx(PT)


# ---------------------------------------------------------------- line detection on a synthetic page
def _pdf_with_lines(tmp_path):
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    pg = doc.new_page(width=800, height=600)
    sh = pg.new_shape()
    for y in (420, 470, 520, 580):            # title block rows (right-bottom)
        sh.draw_line((500, y), (780, y))
    for x in (500, 640, 780):
        sh.draw_line((x, 420), (x, 580))
    sh.draw_line((10, 10), (790, 10))        # border top
    sh.finish(width=1.2, color=(0, 0, 0))
    sh.commit()
    pg.insert_text((520, 445), "MATERIAL", fontsize=10)
    p = tmp_path / "s.pdf"
    doc.save(str(p))
    return p


def test_detect_lines_and_title_block(tmp_path):
    pdf = _pdf_with_lines(tmp_path)
    lines = rp.detect_lines(pdf, 0)
    assert any(abs(y - 420) < 3 and a0 <= 505 and a1 >= 775 for a0, a1, y in lines["h"])
    assert any(abs(x - 640) < 3 for a0, a1, x in lines["v"])
    ex = {"sheet": {"width_pt": 800, "height_pt": 600, "title_block_bbox_pt": [510, 430, 770, 570]}, "notes": [{"kind": "material", "bbox_pt": [520, 435, 580, 450]}]}
    tb = rp.title_block_bbox(ex, lines)
    assert tb[0] <= 502 and tb[1] <= 422 and tb[2] >= 778 and tb[3] >= 578
    fr = srcmap.SheetFrame.physical(800, 600)
    segs, rep = rp.sheet_segments(lines, tb, fr, ex)
    assert rep["title_block"] >= 6 and rep["border"] >= 1
    for x0, y0, x1, y1 in segs:
        assert 0 <= x0 <= 800 * PT + 1e-9 and 0 <= y1 <= 600 * PT + 1e-9
    # a stroke outside the title block and not on the border is never drawn as sheet geometry
    far = {"h": [(100, 300, 300)], "v": [], "page_pt": [800, 600]}
    s2, r2 = rp.sheet_segments(far, tb, fr, ex)
    assert s2 == [] and r2["skipped"] == 1


# ---------------------------------------------------------------- notes
def test_collect_notes_excludes_matched_and_dedupes():
    ex = {"notes": [{"id": "N1", "kind": "general_note", "text": "NOTE A:\nLEAVE .25 MIN.", "bbox_pt": [10, 900, 200, 960], "position_source": "ocr"},
                    {"id": "N2", "kind": "title_block_field", "text": "", "bbox_pt": [1, 1, 2, 2]}],
          "annotations": [{"id": "A1", "kind": "linear", "text": "1.406", "bbox_pt": [900, 200, 950, 215]},
                          {"id": "A2", "kind": "hole_callout", "text": ".375-16 TAP THRU\n8-HOLES", "bbox_pt": [100, 100, 300, 140]},
                          {"id": "A3", "kind": "other", "text": "NOTE A:\nLEAVE .25 MIN.", "bbox_pt": [11, 901, 201, 961]}]}
    ledger = [{"ref_id": "A1", "status": "matched"}, {"ref_id": "A2", "status": "missing"}]
    out = rp.collect_notes(ex, ledger)
    ids = [o["id"] for o in out]
    assert ids == ["N1", "A2"]                                           # empty note dropped, matched A1 dropped, A3 duplicates N1
    assert out[1]["classification"] == "source_only_non_associative"


def test_note_height_scales_with_lines_and_frame():
    fr = srcmap.SheetFrame.physical(1000, 800)
    one = rp.note_height_pt([0, 0, 100, 30], "ABC", fr)
    three = rp.note_height_pt([0, 0, 100, 30], "A\nB\nC", fr)
    assert one > three > 3.0
    half = srcmap.SheetFrame.physical(2000, 1600, 1000 * PT, 800 * PT)       # page scaled to half
    assert rp.note_height_pt([0, 0, 100, 30], "ABC", half) == pytest.approx(one / 2, rel=0.1)


class _T:
    def __init__(self, i, text, cx, cy):
        self.id, self.text = i, text
        self.x0, self.x1, self.y0, self.y1 = cx - .01, cx + .01, cy - .002, cy + .002
        self.center = (cx, cy)


def test_note_verbatim_check_is_case_and_symbol_exact():
    recs = [{"id": "N1", "placed": True, "text": "UNLESS OTHERWISE SPECIFIED:\n2-PLACE DIM. \u00b1 .020"}, {"id": "N2", "placed": True, "text": "angular \u00bc\u00b0"},
            {"id": "N3", "placed": False, "text": "never placed"}]
    pages = [SimpleNamespace(texts=[_T("a", "UNLESS OTHERWISE SPECIFIED:", 0, 0), _T("b", "2-PLACE DIM. \u00b1 .020", 0, 0), _T("c", "ANGULAR \u00bc\u00b0", 0, 0)])]
    r = rp.note_verbatim_check(recs, pages)
    assert r["matched"] == 1 and r["total"] == 3
    why = {b["id"]: b["why"] for b in r["mismatched"]}
    assert "not found" in why["N2"] and why["N3"] == "not placed"          # lower-case 'angular' is NOT verbatim


# ---------------------------------------------------------------- status decisions
GOOD = {"sheet_scale_exact": True, "view_scales": [{"match": True}], "unintended_clipping": 0, "critical_mismatches": 0, "notes_verbatim": {"mismatched": []},
        "view_center_dev_mm": {"max": 0.4}, "annotation_anchor_dev_mm": {"max": 0.9}, "missing_views": [], "pages_missing": [], "unresolved_source_items": 0}


def test_status_verified_only_when_everything_measured_passes():
    th = rp.thresholds(None)
    assert rp.decide_status(dict(GOOD), th)[0] == "verified"
    for key, val in [("sheet_scale_exact", None), ("sheet_scale_exact", False), ("unintended_clipping", 1), ("critical_mismatches", 1), ("missing_views", [{"id": "V3"}]),
                     ("pages_missing", [2]), ("unresolved_source_items", 3), ("notes_verbatim", {"mismatched": [{"id": "N"}]}),
                     ("view_center_dev_mm", {"max": 2.0}), ("annotation_anchor_dev_mm", {"max": 5.0}), ("view_scales", [{"match": False}])]:
        m = dict(GOOD, **{key: val})
        assert rp.decide_status(m, th)[0] == "needs_review", key
    assert rp.decide_status(dict(GOOD, blocked="no source"), th)[0] == "blocked"
    assert rp.decide_status(dict(GOOD, failed="export failed"), th)[0] == "failed"


def test_thresholds_are_configurable():
    th = rp.thresholds({"replication_thresholds": {"view_center_mm": 5.0}})
    assert rp.decide_status(dict(GOOD, view_center_dev_mm={"max": 3.0}), th)[0] == "verified"


# ---------------------------------------------------------------- DrawingSpec
def _ref():
    return {"sheet": {"width_pt": 1580, "height_pt": 1216, "rotation": 0, "units": "inches", "projection": "third angle", "scale_text": '1" = 2"', "title_block_bbox_pt": [1200, 800, 1580, 1216]},
            "views": [{"id": "V1", "type": "Front", "bbox_norm": [.05, .24, .5, .83], "bbox_pt": [80, 290, 790, 1010], "center_norm": [.28, .54], "scale_text": "", "parent_id": "", "position_source": "model_estimate"}],
            "annotations": [{"id": "A1", "kind": "diameter", "text": "16.250 DIA.\nBSC", "nominal": 16.25, "unit": "inch", "bbox_pt": [480, 530, 590, 570], "bbox_norm": [.3, .44, .37, .47],
                             "position_source": "ocr", "ocr_ids": ["T1"], "anchor_norm": [.31, .45]},
                            {"id": "A2", "kind": "other", "text": "\u00b1.001\n19.993", "bbox_pt": [1150, 600, 1230, 650], "bbox_norm": [.7, .5, .78, .53], "position_source": "ocr", "uncertain": True}],
            "notes": [{"id": "N1", "kind": "general_note", "text": "NOTE A:\nLEAVE .25 MIN.", "bbox_pt": [10, 1000, 200, 1100], "position_source": "ocr"}],
            "title_block": {"MATERIAL": "USS-T1", "SCALE": '1" = 2"'}, "material": {"printed": "USS-T1"}, "warnings": []}


def test_drawingspec_page_fields_and_statuses():
    pg = ds.build_page(_ref(), 1, {"items": [{"id": "T1", "font": "Arial", "size": 9.0}]})
    assert pg["sheet_scale"] == {"numerator": 1, "denominator": 2, "text": '1" = 2"', "status": "present"}
    a1 = pg["annotations"][0]
    assert a1["text"] == "16.250 DIA.\nBSC" and a1["precision"] == 3 and "diameter_word" in a1["symbols"] and a1["font"]["font"] == "Arial"
    assert a1["leader_vertices"]["status"] == "present" and a1["review_status"] == "auto"
    a2 = pg["annotations"][1]
    assert a2["review_status"] == "needs_review" and "plus_minus" in a2["symbols"] and a2["anchor"]["status"] == "missing"       # missing vs unreadable explicit
    assert pg["views"][0]["scale"]["status"] == "missing" and pg["views"][0]["section_path"]["status"] == "not_applicable"
    assert pg["physical_size"]["standard_sheet"] == "ANSI C"
    assert pg["title_block"]["fields"]["MATERIAL"]["status"] == "present"
    assert 0.0 < ds.completeness(pg) <= 1.0


def test_precision_and_symbols():
    assert ds.precision_of(".50") == 2 and ds.precision_of("16.250 DIA.") == 3 and ds.precision_of("4X") == 0 and ds.precision_of("none") is None
    assert "multiplicity" in ds.symbols_in("4X \u2300.25") and "diameter" in ds.symbols_in("\u2300.25")


def test_reuse_requires_hash_schema_and_completeness():
    spec = ds.build_spec([_ref()], "abc", "x.pdf", 1)
    assert ds.reuse_decision(spec, "abc", 1)["reuse"] is True
    assert ds.reuse_decision(spec, "zzz", 1)["reuse"] is False                                  # hash
    assert ds.reuse_decision(dict(spec, schema_version="drawingspec/0"), "abc", 1)["reuse"] is False   # schema
    d2 = ds.reuse_decision(spec, "abc", 3)                                                      # pages 2..3 missing -> supplement only those
    assert d2["reuse"] is False and d2["supplement_pages"] == [2, 3]
    thin = ds.build_spec([{"sheet": {"width_pt": 100, "height_pt": 100}, "views": [], "annotations": [], "notes": []}], "abc", "x.pdf", 1)
    assert ds.reuse_decision(thin, "abc", 1)["reuse"] is False                                  # completeness


def test_tiles_overlap_and_coordinate_roundtrip():
    tiles = ds.make_tiles(1000, 800, 2, 2, 0.15)
    assert len(tiles) == 4
    t0, t1 = tiles[0]["rect"], tiles[1]["rect"]
    assert t1[0] < t0[2]                                      # horizontal overlap
    nb = ds.tile_box_to_page([0.0, 0.0, 1.0, 1.0], t1, 1000, 800)
    assert nb == pytest.approx([t1[0] / 1000, t1[1] / 800, t1[2] / 1000, t1[3] / 800], abs=1e-4)


def test_merge_annotations_by_coordinates_keeps_existing_and_adds_new():
    existing = [{"id": "A1", "text": "19.993 DIA.", "bbox_norm": [0.70, 0.50, 0.78, 0.55]}]
    new = [{"text": "19.993 DIA", "bbox_norm": [0.705, 0.505, 0.775, 0.545]},          # duplicate (same place, same text)
           {"text": ".030 R.", "bbox_norm": [0.20, 0.20, 0.25, 0.22]},                  # new
           {"text": "7X", "bbox_norm": None},                                           # no location: reported, not merged
           {"text": "19.993 DIA.", "bbox_norm": [0.10, 0.80, 0.18, 0.83]}]              # same text elsewhere: a different annotation
    out, st = ds.merge_annotations(existing, new)
    assert st == {"added": 2, "duplicates": 1, "unlocated": 1}
    assert out[0] == existing[0] and len(out) == 3
    assert all(a["evidence"] == "tile pass" for a in out[1:])


def test_gdt_glyphs_not_printed_are_reported_separately_not_as_verbatim():
    recs = [{"id": "G1", "placed": True, "text": "⌖ | .010 DIA."}, {"id": "G2", "placed": True, "text": "⌖ | .010 DIA. EXTRA"}]
    pages = [SimpleNamespace(texts=[_T("a", ".010 DIA.", 0, 0)])]
    r = rp.note_verbatim_check(recs, pages)
    assert r["matched"] == 0 and [x["id"] for x in r["symbols_unverified"]] == ["G1"] and [x["id"] for x in r["mismatched"]] == ["G2"]
    assert rp.decide_status(dict(GOOD, notes_verbatim=r), rp.thresholds(None))[0] == "needs_review"
