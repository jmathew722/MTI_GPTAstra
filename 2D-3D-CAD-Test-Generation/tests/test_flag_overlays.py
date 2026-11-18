"""Overlay artifact and flattened annotated PDF, generated with no manual positions (Stage 3, task 3.3)."""
import hashlib
import json

import pytest

pymupdf = pytest.importorskip("pymupdf")

from pipeline.findings import Finding
from pipeline.flag_overlays import (
    OVERLAY_SCHEMA_VERSION, build_overlay_artifact, load_pages, render_annotated_pdf, sha256_file, write_flags,
)

CALLOUT = "M6 X 1 - 12 DEEP"
PW, PH = 600.0, 400.0


def make_pdf(path, rotation=0, extra_pages=0, callouts=((CALLOUT, (50, 60)),)):
    doc = pymupdf.open()
    pg = doc.new_page(width=PW, height=PH)
    for text, xy in callouts:
        pg.insert_text(xy, text, fontsize=12)
    pg.set_rotation(rotation)
    for _ in range(extra_pages):
        doc.new_page(width=PW, height=PH).insert_text((50, 60), "SHEET 2 NOTE", fontsize=12)
    doc.save(path)
    return path


def finding(callouts=(CALLOUT,), fid="F003", title="Tapped hole was not built", **kw):
    return Finding.create(part="P1", run_id="run_a", severity=kw.get("severity", "error"), category="feature_not_built", title=title,
                          expected="M6 × 1 tapped 12 mm deep", actual="skipped: no depth", consequence="The thread is missing.",
                          recommended_action="Add the tapped hole manually.", feature_ids=[fid] if fid else [],
                          source_callouts=list(callouts), evidence_ids=[f"plan:{fid or 'x'}"])


def red_bbox(pdf, page_index=0, dpi=72):
    pg = pymupdf.open(pdf)[page_index]
    pix = pg.get_pixmap(dpi=dpi)
    xs, ys = [], []
    for y in range(pix.height):
        for x in range(pix.width):
            r, g, b = pix.pixel(x, y)[:3]
            if r > 200 and g < 90 and b < 90:
                xs.append(x); ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


# ---- page extraction -----------------------------------------------------------------------------
def test_pages_come_from_the_text_layer_with_displayed_coordinates(tmp_path):
    pdf = make_pdf(tmp_path / "d.pdf", rotation=90)
    pages, sha = load_pages(pdf)
    p = pages[0]
    assert p.source == "text_layer" and p.rotation == 90 and (p.width, p.height) == (PH, PW)    # displayed size is swapped
    assert sha == sha256_file(pdf) == hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert any(CALLOUT in b.text for b in p.boxes)


@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_automatic_placement_is_the_same_unrotated_spot_at_every_rotation(tmp_path, rot):
    pdf = make_pdf(tmp_path / "d.pdf", rotation=rot)
    pages, sha = load_pages(pdf)
    art = build_overlay_artifact([finding()], pages, source_sha256=sha, run_id="run_a", source_name="d.pdf")
    assert len(art["overlays"]) == 1 and art["unlocated_findings"] == []
    o = art["overlays"][0]
    assert o["rotation_degrees"] == rot and o["provenance"] == "automatic" and o["mapping_method"] == "exact_tokens"
    r = o["rect_normalized"]
    # the text was inserted at x=50, baseline y=60 on the UNROTATED 600x400 page, whatever the page rotation
    assert r["x"] == pytest.approx(50 / PW, abs=0.01) and r["y"] == pytest.approx((60 - 12) / PH, abs=0.03)


# ---- artifact contract ---------------------------------------------------------------------------
def test_artifact_has_the_contract_fields_and_no_timestamps(tmp_path):
    pdf = make_pdf(tmp_path / "d.pdf")
    pages, sha = load_pages(pdf)
    art = build_overlay_artifact([finding()], pages, source_sha256=sha, run_id="run_a", source_name="d.pdf")
    assert art["schema_version"] == OVERLAY_SCHEMA_VERSION == 1
    assert art["source_pdf_sha256"] == sha and art["run_id"] == "run_a" and art["pages"][0]["rotation"] == 0
    o = art["overlays"][0]
    assert set(o) >= {"overlay_id", "finding_id", "page_index", "shape", "rect_normalized", "label_anchor_normalized",
                      "mapping_method", "mapping_confidence", "matched_text", "rotation_degrees", "provenance"}
    assert o["shape"] == "rect" and 0 <= o["mapping_confidence"] <= 1
    assert not any(k in json.dumps(art) for k in ("generated_at", "timestamp"))      # deterministic


def test_two_builds_are_byte_identical(tmp_path):
    pdf = make_pdf(tmp_path / "d.pdf")
    pages, sha = load_pages(pdf)
    a = json.dumps(build_overlay_artifact([finding()], pages, source_sha256=sha, run_id="r", source_name="d.pdf"), sort_keys=True)
    b = json.dumps(build_overlay_artifact([finding()], pages, source_sha256=sha, run_id="r", source_name="d.pdf"), sort_keys=True)
    assert a == b


def test_unlocated_findings_are_listed_with_a_reason_never_boxed(tmp_path):
    pdf = make_pdf(tmp_path / "d.pdf")
    pages, sha = load_pages(pdf)
    fs = [finding(callouts=("NOT ON THIS DRAWING 99",), fid="F009"), finding(callouts=(), fid=None, title="Volume mismatch")]
    art = build_overlay_artifact(fs, pages, source_sha256=sha, run_id="r", source_name="d.pdf")
    assert art["overlays"] == []
    reasons = {u["finding_id"]: u["reason"] for u in art["unlocated_findings"]}
    assert sorted(reasons.values()) == ["no_match", "no_source_callout"]


def test_ambiguous_duplicate_is_unlocated_not_guessed(tmp_path):
    pdf = make_pdf(tmp_path / "d.pdf", callouts=((CALLOUT, (50, 60)), (CALLOUT, (50, 300))))
    pages, sha = load_pages(pdf)
    art = build_overlay_artifact([finding()], pages, source_sha256=sha, run_id="r", source_name="d.pdf")
    assert art["overlays"] == [] and art["unlocated_findings"][0]["reason"] == "ambiguous" and art["unlocated_findings"][0]["candidates"] == 2


def test_multi_page_source_and_page_index(tmp_path):
    pdf = make_pdf(tmp_path / "d.pdf", extra_pages=1, callouts=(("OTHER NOTE", (50, 60)),))
    doc = pymupdf.open(pdf)
    doc[1].insert_text((50, 200), CALLOUT, fontsize=12)
    doc.saveIncr()
    pages, sha = load_pages(pdf)
    art = build_overlay_artifact([finding()], pages, source_sha256=sha, run_id="r", source_name="d.pdf")
    assert [o["page_index"] for o in art["overlays"]] == [1] and len(art["pages"]) == 2


def test_labels_do_not_collide_and_stay_on_the_page(tmp_path):
    pdf = make_pdf(tmp_path / "d.pdf", callouts=(("CALLOUT ONE 111", (400, 60)), ("CALLOUT TWO 222", (400, 74))))
    pages, sha = load_pages(pdf)
    fs = [finding(callouts=("CALLOUT ONE 111",), fid="F001"), finding(callouts=("CALLOUT TWO 222",), fid="F002")]
    art = build_overlay_artifact(fs, pages, source_sha256=sha, run_id="r", source_name="d.pdf")
    a, b = (o["label_anchor_normalized"] for o in art["overlays"])
    assert abs(a["y"] - b["y"]) >= 0.02 - 1e-9                                       # never stacked on each other
    assert all(0 <= x["x"] <= 1 and 0 <= x["y"] <= 1 for x in (a, b))


# ---- flattened PDF from the same contract ------------------------------------------------------
@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_annotated_pdf_puts_the_red_box_over_the_callout_at_every_rotation(tmp_path, rot):
    pdf = make_pdf(tmp_path / "d.pdf", rotation=rot)
    pages, sha = load_pages(pdf)
    art = build_overlay_artifact([finding()], pages, source_sha256=sha, run_id="r", source_name="d.pdf")
    out = tmp_path / "annotated.pdf"
    render_annotated_pdf(art, [finding()], pdf, out)
    bb = red_bbox(out)
    assert bb is not None, "no red markup drawn"
    # the callout's displayed rectangle (from the text layer) must lie inside the red outline's extent
    disp = next(b.rect for b in pages[0].boxes if CALLOUT in b.text)
    assert bb[0] <= disp[0] + 3 and bb[1] <= disp[1] + 3 and bb[2] >= disp[2] - 3 and bb[3] >= disp[3] - 3
    assert (bb[2] - bb[0]) < 0.6 * pages[0].width           # a box around the callout, not a page wash


def test_unlocated_findings_draw_no_box_but_appear_in_the_report_page(tmp_path):
    pdf = make_pdf(tmp_path / "d.pdf")
    pages, sha = load_pages(pdf)
    f = finding(callouts=("NOT ON THIS DRAWING 99",), fid="F009", title="Unlocated defect")
    art = build_overlay_artifact([f], pages, source_sha256=sha, run_id="r", source_name="d.pdf")
    out = tmp_path / "annotated.pdf"
    render_annotated_pdf(art, [f], pdf, out)
    doc = pymupdf.open(out)
    assert red_bbox(out, 0) is None                                   # nothing drawn on the sheet
    assert doc.page_count == 2
    text = doc[1].get_text()
    assert "Unlocated defect" in text and "Expected" in text and "Recommended" in text.replace("recommended", "Recommended")


def test_report_page_has_expected_actual_consequence_and_repair_text(tmp_path):
    pdf = make_pdf(tmp_path / "d.pdf")
    pages, sha = load_pages(pdf)
    art = build_overlay_artifact([finding()], pages, source_sha256=sha, run_id="r", source_name="d.pdf")
    out = tmp_path / "annotated.pdf"
    render_annotated_pdf(art, [finding()], pdf, out)
    t = pymupdf.open(out)[1].get_text()
    for needle in ("Tapped hole was not built", "M6", "skipped: no depth", "The thread is missing.", "Add the tapped hole manually."):
        assert needle in t, needle


def test_stale_source_hash_is_refused(tmp_path):
    pdf = make_pdf(tmp_path / "d.pdf")
    pages, sha = load_pages(pdf)
    art = build_overlay_artifact([finding()], pages, source_sha256=sha, run_id="r", source_name="d.pdf")
    other = make_pdf(tmp_path / "new_revision.pdf", callouts=(("DIFFERENT SHEET", (50, 60)),))
    with pytest.raises(ValueError, match="hash"):
        render_annotated_pdf(art, [finding()], other, tmp_path / "x.pdf")


def test_long_titles_are_clipped_in_the_label_but_complete_in_the_report(tmp_path):
    pdf = make_pdf(tmp_path / "d.pdf")
    pages, sha = load_pages(pdf)
    long_title = "A very long engineering finding title " * 4
    f = finding(title=long_title.strip())
    art = build_overlay_artifact([f], pages, source_sha256=sha, run_id="r", source_name="d.pdf")
    assert len(art["overlays"][0]["label"]) <= 60
    out = tmp_path / "annotated.pdf"
    render_annotated_pdf(art, [f], pdf, out)
    assert "very long engineering finding title" in pymupdf.open(out)[1].get_text().replace("\n", " ")


# ---- the production path never reads a manual position file ------------------------------------
def test_write_flags_ignores_manual_position_files(tmp_path):
    out = tmp_path / "P1"
    out.mkdir()
    pdf = make_pdf(out / "d.pdf")
    (out / "ir_report.json").write_text(json.dumps({"part": "P1", "cq_skipped": {"F003": "no depth"}}), encoding="utf-8")
    (out / "plan.json").write_text(json.dumps({"plan": {"features": [{"id": "F003", "source_callouts": [CALLOUT]}]}}), encoding="utf-8")
    (out / "markup_positions.json").write_text(json.dumps({"items": [{"n": 1, "label": "HAND PLACED", "rect": [1, 1, 20, 20]}]}), encoding="utf-8")
    res = write_flags(out, pdf, run_id="r")
    art = json.loads((out / "engineering_flag_overlays.json").read_text(encoding="utf-8"))
    assert [o["provenance"] for o in art["overlays"]] == ["automatic"]
    assert "HAND PLACED" not in json.dumps(art) and art["overlays"][0]["rect_normalized"]["x"] > 0.05      # not the hand rect at (1,1)
    assert res["overlays"] == 1 and (out / "engineering_findings.json").is_file() and (out / "engineering_flags_annotated.pdf").is_file()


def test_developer_override_requires_an_explicit_argument_and_is_labeled(tmp_path):
    pdf = make_pdf(tmp_path / "d.pdf")
    pages, sha = load_pages(pdf)
    override = {"flag": {"page_index": 0, "rect_normalized": {"x": 0.1, "y": 0.1, "width": 0.1, "height": 0.05}}}
    f = finding()
    plain = build_overlay_artifact([f], pages, source_sha256=sha, run_id="r", source_name="d.pdf")
    dev = build_overlay_artifact([f], pages, source_sha256=sha, run_id="r", source_name="d.pdf",
                                 developer_positions={f.finding_id: override["flag"]})
    assert plain["overlays"][0]["provenance"] == "automatic"
    assert dev["overlays"][0]["provenance"] == "developer_override" and dev["overlays"][0]["mapping_method"] == "developer_override"


def test_a_pdf_without_findings_still_writes_an_empty_valid_artifact(tmp_path):
    out = tmp_path / "P1"
    out.mkdir()
    pdf = make_pdf(out / "d.pdf")
    (out / "ir_report.json").write_text(json.dumps({"part": "P1"}), encoding="utf-8")
    res = write_flags(out, pdf, run_id="r")
    art = json.loads((out / "engineering_flag_overlays.json").read_text(encoding="utf-8"))
    assert art["overlays"] == [] and art["unlocated_findings"] == [] and res["findings"] == 0


# ---- scanned pages go through OCR --------------------------------------------------------------
def test_a_scanned_page_without_a_text_layer_is_placed_through_ocr(tmp_path):
    pytest.importorskip("rapidocr_onnxruntime")
    src = pymupdf.open()
    pg = src.new_page(width=PW, height=PH)
    pg.insert_text((60, 120), CALLOUT, fontsize=26)
    pix = pg.get_pixmap(dpi=150)
    scan = pymupdf.open()
    sp = scan.new_page(width=PW, height=PH)
    sp.insert_image(sp.rect, pixmap=pix)                       # an image only: no text layer
    path = tmp_path / "scan.pdf"
    scan.save(path)
    pages, sha = load_pages(path, ocr_cache=tmp_path / "ocr.json")
    assert pages[0].source == "ocr"
    art = build_overlay_artifact([finding()], pages, source_sha256=sha, run_id="r", source_name="scan.pdf")
    assert len(art["overlays"]) == 1
    r = art["overlays"][0]["rect_normalized"]
    assert r["x"] == pytest.approx(60 / PW, abs=0.03) and 0.15 < r["y"] < 0.4
    assert art["overlays"][0]["mapping_confidence"] >= 0.70


@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_labels_stay_fully_on_the_displayed_page_and_upright(tmp_path, rot):
    pdf = make_pdf(tmp_path / "d.pdf", rotation=rot, callouts=((CALLOUT, (480, 60)),))     # near the unrotated right edge
    pages, sha = load_pages(pdf)
    f = finding(title="Tapped hole depth is too shallow")
    art = build_overlay_artifact([f], pages, source_sha256=sha, run_id="r", source_name="d.pdf")
    out = tmp_path / "annotated.pdf"
    render_annotated_pdf(art, [f], pdf, out)
    page = pymupdf.open(out)[0]
    words = [w for w in page.get_text("words") if w[4] in ("Tapped", "shallow", "1:")]
    assert {w[4] for w in words} >= {"1:", "Tapped", "shallow"}, "the label text is missing or garbled"
    shown = [(pymupdf.Rect(w[:4]) * page.rotation_matrix).normalize() for w in words]       # text extraction is unrotated
    for r in shown:
        assert r.x0 >= -0.5 and r.y0 >= -0.5 and r.x1 <= page.rect.width + 0.5 and r.y1 <= page.rect.height + 0.5
    assert max(r.y0 for r in shown) - min(r.y0 for r in shown) < 3        # one horizontal line as displayed: upright, not stacked
    assert min(r.x0 for r in shown) < max(r.x0 for r in shown)           # and reading left to right
