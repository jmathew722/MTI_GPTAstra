"""Fuzzy callout matching on OCR boxes (pipeline/ocr_locate.py). Boxes are what RapidOCR read
on the 2N2664 scan: '377' for '.377', 'R~' for '.188 R', 'ALL RADH.O47 MAX' for 'ALL RADII'."""
from pipeline.ocr_locate import locate

BOXES = [
    {"text": "377", "conf": 1.0, "rect": [1257, 116, 1305, 138]},
    {"text": ".188-", "conf": 0.87, "rect": [1097, 153, 1146, 175]},
    {"text": "R~", "conf": 0.77, "rect": [1006, 175, 1081, 198]},
    {"text": "1.812", "conf": 0.92, "rect": [1280, 366, 1328, 388]},
    {"text": ".188 Ø", "conf": 0.9, "rect": [400, 1100, 450, 1120]},          # another .188, far away
    {"text": "ALLCHAMFERS.O6X45", "conf": 0.94, "rect": [1602, 1330, 1854, 1351]},
    {"text": "ALL RADH.O47 MAX", "conf": 0.9, "rect": [1597, 1354, 1826, 1381]},
]


def test_numbers_match_without_the_dot_and_ambiguity_resolves_near_the_anchors():
    got = locate([".377 ±.001", ".188 ±.001", "1.812"], BOXES)
    assert got[".377 ±.001"] == [1257, 116, 1305, 138]
    assert got["1.812"] == [1280, 366, 1328, 388]
    assert got[".188 ±.001"] == [1097, 153, 1146, 175]          # the nearby .188, not the one at the bottom


def test_a_radius_read_as_r_alone_is_found_and_boxes_are_not_shared():
    got = locate([".377 ±.001", ".188 ±.001", ".188 R"], BOXES)
    assert got[".188 R"] == [1006, 175, 1081, 198]
    assert len({tuple(r) for r in got.values()}) == 3


def test_general_notes_match_despite_ocr_misreads():
    got = locate(["ALL CHAMFERS", "ALL RADII"], BOXES)
    assert got["ALL CHAMFERS"] == [1602, 1330, 1854, 1351] and got["ALL RADII"] == [1597, 1354, 1826, 1381]


def test_a_different_number_with_the_same_digits_is_not_a_match():   # A00155E: ".75" is not "7.50"
    boxes = [{"text": "7.50", "conf": 1.0, "rect": [130, 120, 160, 130]},
             {"text": "75", "conf": 1.0, "rect": [60, 270, 80, 280]}]
    assert locate([".75"], boxes)[".75"] == [60, 270, 80, 280]
