"""The legacy hand-positions file is developer-only (Stage 3, task 3.3)."""
import json

import pytest

pymupdf = pytest.importorskip("pymupdf")

import mti_markup


def _part(tmp_path):
    d = tmp_path / "P1"
    (d / "source").mkdir(parents=True)
    doc = pymupdf.open()
    doc.new_page(width=600, height=400).insert_text((50, 60), "SAMPLE", fontsize=12)
    doc.save(d / "source" / "P1.pdf")
    (d / "discrepancies.json").write_text(json.dumps({"part": "P1", "iou": 0.9, "gap_pct": 10.0, "explained_pct": 9.0, "pieces": [],
                                                      "questions": [], "defaults": [], "general_notes": []}), encoding="utf-8")
    (d / "markup_positions.json").write_text(json.dumps({"items": [{"n": 1, "label": "HAND", "rect": [10, 10, 80, 40], "color": "red"}]}), encoding="utf-8")
    return d


def red_boxes(pdf):
    page = pymupdf.open(pdf)[0]
    return [a for a in page.annots() if a.type[1] in ("Square", "Circle")]


def test_production_markup_ignores_the_manual_positions_file(tmp_path):
    d = _part(tmp_path)
    out = mti_markup.markup(d, "P1", ocr=False)
    assert red_boxes(out) == []                                   # the hand-placed box was NOT drawn


def test_the_override_needs_the_explicit_flag(tmp_path):
    d = _part(tmp_path)
    out = mti_markup.markup(d, "P1", ocr=False, developer_override_positions=True)
    assert len(red_boxes(out)) == 1


def test_cli_exposes_the_flag_as_developer_only():
    import subprocess, sys
    helptext = subprocess.run([sys.executable, "mti_markup.py", "--help"], capture_output=True, text=True, encoding="utf-8").stdout
    assert "--developer-override-positions" in helptext and "DEVELOPER ONLY" in helptext
