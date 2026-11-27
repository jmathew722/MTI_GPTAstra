"""v8 source-coordinate transforms: all four rotations, crop offsets, Y inversion, and an empirical check against real PyMuPDF text boxes."""
from __future__ import annotations

import pytest

from reverse import srcmap
from reverse.srcmap import PT_TO_M, PageBox, SheetFrame


@pytest.mark.parametrize("rot", [0, 90, 180, 270])
@pytest.mark.parametrize("crop", [(0, 0, 600, 400), (50, 30, 650, 430), (-20, -10, 580, 390)])
def test_raw_displayed_roundtrip_and_corners(rot, crop):
    pb = PageBox((crop[0] - 10, crop[1] - 10, crop[2] + 10, crop[3] + 10), crop, rot)
    W, H = pb.unrotated_size
    dw, dh = pb.displayed_size
    assert (dw, dh) == ((H, W) if rot in (90, 270) else (W, H))
    for x, y in [(crop[0], crop[1]), (crop[2], crop[3]), (crop[0] + 123.4, crop[1] + 56.7)]:
        d = pb.raw_to_displayed(x, y)
        assert -1e-9 <= d[0] <= dw + 1e-9 and -1e-9 <= d[1] <= dh + 1e-9
        assert pb.displayed_to_raw(*d) == pytest.approx((x, y))


def test_corner_mapping_each_rotation():
    crop = (0, 0, 600, 400)                       # raw top-left is (0, 400)
    tl = (0, 400)
    assert PageBox(crop, crop, 0).raw_to_displayed(*tl) == pytest.approx((0, 0))
    assert PageBox(crop, crop, 90).raw_to_displayed(*tl) == pytest.approx((400, 0))        # top-left goes to top-right (clockwise)
    assert PageBox(crop, crop, 180).raw_to_displayed(*tl) == pytest.approx((600, 400))
    assert PageBox(crop, crop, 270).raw_to_displayed(*tl) == pytest.approx((0, 600))


def test_invalid_rotation():
    with pytest.raises(ValueError):
        PageBox((0, 0, 1, 1), (0, 0, 1, 1), 45)


@pytest.mark.parametrize("rot", [0, 90, 180, 270])
@pytest.mark.parametrize("crop_off", [(0, 0), (40, 25)])
def test_matches_real_pymupdf_text_box(rot, crop_off):
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    pg = doc.new_page(width=600, height=400)
    pg.insert_text((100, 300), "HELLO", fontsize=20)           # fitz insert: top-left coordinates of the unrotated page
    if crop_off != (0, 0):
        # CropBox in fitz is top-left based relative to the unrotated MediaBox
        pg.set_cropbox(fitz.Rect(crop_off[0], crop_off[1], 600, 400))
    pg.set_rotation(rot)
    pg = doc.reload_page(pg)
    pb = PageBox.from_fitz_page(pg)
    words = pg.get_text("words")
    assert words, "no text found"
    # PyMuPDF text boxes are in UNROTATED page space: the displayed box needs pg.rotation_matrix (found by this test; refextract applies it)
    x0, y0, x1, y1 = srcmap.fitz_displayed_rect(pg, words[0][:4])
    # the raw (y up) position of the text origin baseline start: insert_text y is measured from the top of the unrotated page
    raw_x, raw_y = 100.0, pb.media[3] - 300.0
    dx, dy = pb.raw_to_displayed(raw_x, raw_y)
    # the baseline origin lies inside / on the word's displayed box (within the glyph height)
    assert x0 - 1.5 <= dx <= x1 + 1.5 and y0 - 1.5 <= dy <= y1 + 1.5, (rot, crop_off, (dx, dy), (x0, y0, x1, y1))
    assert pb.displayed_size == pytest.approx((pg.rect.width, pg.rect.height))


def test_sheet_frame_y_inversion_and_origin():
    f = SheetFrame.physical(1584, 1224)
    assert f.sheet_w_m == pytest.approx(1584 * PT_TO_M)
    # displayed top-left is the sheet's upper-left: x=0, y=H
    assert f.to_sheet(0, 0) == pytest.approx((0, 1224 * PT_TO_M))
    assert f.to_sheet(1584, 1224) == pytest.approx((1584 * PT_TO_M, 0))
    assert f.norm_to_sheet(0.5, 0.25) == pytest.approx((792 * PT_TO_M, 0.75 * 1224 * PT_TO_M))
    x, y = f.to_sheet(321.0, 456.0)
    assert f.to_page(x, y) == pytest.approx((321.0, 456.0))


def test_sheet_frame_box_orientation():
    f = SheetFrame.physical(1000, 800)
    b = f.box_to_sheet([100, 100, 300, 200])                 # displayed box (top-left): x0,y0,x1,y1
    assert b[0] < b[2] and b[1] < b[3]
    assert b[0] == pytest.approx(100 * PT_TO_M) and b[3] == pytest.approx((800 - 100) * PT_TO_M)
    assert f.box_from_sheet(b) == pytest.approx([100, 100, 300, 200])


def test_sheet_frame_larger_sheet_centres_at_true_size():
    pw, ph = 1580 * PT_TO_M, 1216 * PT_TO_M                     # 21.94 x 16.89 in
    f = SheetFrame.physical(1580, 1216, 0.5588, 0.4318)          # ANSI C
    assert f.k == pytest.approx(PT_TO_M)                           # not rescaled
    assert f.ox == pytest.approx((0.5588 - pw) / 2) and f.oy == pytest.approx((0.4318 - ph) / 2)
    assert "centred" in f.notes[0]


def test_sheet_frame_different_size_fits_uniformly_and_says_so():
    f = SheetFrame.physical(1000, 500, 0.1, 0.1)
    assert f.k == pytest.approx(0.1 / 1000)
    assert "scaled" in f.notes[0]
    assert f.to_sheet(500, 250)[0] == pytest.approx(0.05)


def test_name_sheet():
    assert srcmap.name_sheet(*srcmap.sheet_dims_mm(1580, 1216)) == "ANSI C"
    assert srcmap.name_sheet(420, 297) == "A3"
    assert srcmap.name_sheet(300, 300) is None
