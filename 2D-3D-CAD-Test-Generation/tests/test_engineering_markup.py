"""Automatic Engineering Markup: findings -> marked multi-page PDF + manifest + previews (Stage 3, plan tasks 1-4)."""
import hashlib
import json

import pytest

pymupdf = pytest.importorskip("pymupdf")

from pipeline import engineering_markup as em

CALL_P1 = "M6 X 1 - 12 DEEP"
CALL_P2 = "2 X O.250 THRU ALL"
PW, PH = 600.0, 400.0


def make_pdf(path, rotation=0, pages=2):
    doc = pymupdf.open()
    pg = doc.new_page(width=PW, height=PH)
    pg.insert_text((50, 60), CALL_P1, fontsize=12)
    pg.set_rotation(rotation)
    if pages > 1:
        p2 = doc.new_page(width=PW, height=PH)
        p2.insert_text((300, 200), CALL_P2, fontsize=12)
    doc.save(path)
    return path


def make_run(tmp_path, report, features, pdf_pages=2, name="P1", rotation=0):
    out = tmp_path / name
    out.mkdir()
    pdf = make_pdf(out / "source.pdf", rotation=rotation, pages=pdf_pages)
    (out / "ir_report.json").write_text(json.dumps({"part": name, **report}), encoding="utf-8")
    (out / "plan.json").write_text(json.dumps({"plan": {"features": features}}), encoding="utf-8")
    return out, pdf


TWO = ({"cq_skipped": {"F003": "no thread depth", "F004": "bad diameter"}},
       [{"id": "F003", "source_callouts": [CALL_P1]}, {"id": "F004", "source_callouts": [CALL_P2]}])


def _manifest(out):
    return json.loads((out / em.MANIFEST).read_text(encoding="utf-8"))


def _text(pdf, page):
    return pymupdf.open(pdf)[page].get_text().replace("\n", " ")


def _red_pixels(pdf, page, dpi=72):
    pix = pymupdf.open(pdf)[page].get_pixmap(dpi=dpi)
    n = 0
    for y in range(0, pix.height, 2):
        for x in range(0, pix.width, 2):
            r, g, b = pix.pixel(x, y)[:3]
            if r > 190 and g < 90 and b < 90:
                n += 1
    return n


def test_two_page_drawing_marks_both_pages_with_rail_text_and_unchanged_source(tmp_path):
    out, pdf = make_run(tmp_path, *TWO)
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    m = em.finalize_markup(out, pdf, run_id="run_a", part="P1")
    assert m["status"] == "ready" and m["finding_count"] == 2 and m["located_count"] == 2
    assert hashlib.sha256(pdf.read_bytes()).hexdigest() == sha                       # the upload is never modified
    marked = out / m["marked_pdf"]
    assert m["marked_pdf"] == "P1_engineering_markup.pdf" and marked.is_file()
    doc = pymupdf.open(marked)
    assert len(doc) == 2 + m["report_pages"] and m["report_pages"] >= 1             # every source page + report
    assert doc[0].rect.width == pytest.approx(PW + em.RAIL_W) and doc[0].rect.height == pytest.approx(PH)
    assert _red_pixels(marked, 0) > 50 and _red_pixels(marked, 1) > 50              # visible, flattened red on BOTH pages
    p1, p2 = _text(marked, 0), _text(marked, 1)
    assert "EF-001" in p1 and "ERROR" in p1 and "Action:" in p1 and "no thread depth" in p1
    assert "EF-002" in p2 and "bad diameter" in p2
    assert CALL_P1 in p1 and CALL_P2 in p2                                           # the drawing itself is still there
    by_page = {r["id"]: r["page"] for r in m["findings"]}
    assert sorted(by_page.values()) == [1, 2]                                        # located on the right sheet
    for r in m["findings"]:
        assert r["location_status"] == "located" and r["rect_pdf_points"] and r["rect_normalized"] and r["confidence"] >= 0.7
        assert r["manual_action"] and r["expected"] and r["feature_ids"] and r["finding_id"].startswith("flag_")
    for p in m["pages"]:
        assert (out / p["preview"]).is_file() and p["preview"].startswith(em.PAGES_DIR + "/page-")


def test_previews_are_rendered_from_the_final_marked_pdf(tmp_path):
    out, pdf = make_run(tmp_path, *TWO)
    m = em.finalize_markup(out, pdf, run_id="r", part="P1")
    from PIL import Image
    im = Image.open(out / m["pages"][0]["preview"]).convert("RGB")
    reds = sum(1 for px in im.getdata() if px[0] > 190 and px[1] < 90 and px[2] < 90)
    assert reds > 100 and im.width > im.height                                       # wide: drawing + rail


@pytest.mark.parametrize("rot", [90, 180, 270])
def test_rotated_pages_still_get_the_box_on_the_callout(tmp_path, rot):
    out, pdf = make_run(tmp_path, {"cq_skipped": {"F003": "x"}}, [{"id": "F003", "source_callouts": [CALL_P1]}],
                        pdf_pages=1, rotation=rot)
    m = em.finalize_markup(out, pdf, run_id="r", part="P1")
    assert m["status"] == "ready"
    page = pymupdf.open(out / m["marked_pdf"])[0]
    hit = page.search_for(CALL_P1)
    assert hit, "the callout text is in the marked page"
    # the red box (displayed coordinates) must overlap the callout's displayed position
    pix = page.get_pixmap(dpi=72)
    r = hit[0]
    near = sum(1 for dx in range(-14, int(r.width) + 14) for dy in (-6, int(r.height) + 6)
               if 0 <= int(r.x0) + dx < pix.width and 0 <= int(r.y0) + dy < pix.height
               and pix.pixel(int(r.x0) + dx, int(r.y0) + dy)[0] > 190 and pix.pixel(int(r.x0) + dx, int(r.y0) + dy)[1] < 110)
    assert near > 5


def test_an_unlocatable_finding_gets_an_honest_unlocated_card_and_no_box(tmp_path):
    out, pdf = make_run(tmp_path, {"cq_skipped": {"F009": "no source"}}, [{"id": "F009", "source_callouts": ["NOT ON THIS DRAWING 77"]}])
    m = em.finalize_markup(out, pdf, run_id="r", part="P1")
    assert m["status"] == "partial" and m["unlocated_count"] == 1 and m["located_count"] == 0
    r = m["findings"][0]
    assert r["location_status"] in ("unlocated", "page_only") and r["rect_pdf_points"] is None and r["regions"] == []
    assert m["warnings"][0]["code"] == "MARKUP_LOCALIZATION_PARTIAL"
    marked = out / m["marked_pdf"]
    assert "UNLOCATED" in _text(marked, 0)
    # no precise box on the drawing area: red pixels exist only in the rail
    pix = pymupdf.open(marked)[0].get_pixmap(dpi=72)
    left = sum(1 for y in range(0, pix.height, 2) for x in range(0, int(PW), 2)
               if pix.pixel(x, y)[0] > 190 and pix.pixel(x, y)[1] < 90 and pix.pixel(x, y)[2] < 90)
    assert left == 0


def test_a_clean_run_is_not_needed_and_removes_every_stale_artifact(tmp_path):
    out, pdf = make_run(tmp_path, *TWO)
    em.finalize_markup(out, pdf, run_id="r1", part="P1")
    assert (out / "P1_engineering_markup.pdf").is_file()
    (out / "ir_report.json").write_text(json.dumps({"part": "P1"}), encoding="utf-8")        # next attempt: no findings
    m = em.finalize_markup(out, pdf, run_id="r2", part="P1")
    assert m["status"] == "not_needed" and m["finding_count"] == 0 and m["marked_pdf"] is None
    assert not list(out.glob("*_engineering_markup.pdf")) and not (out / em.PAGES_DIR).exists()
    assert not (out / "engineering_flags_annotated.pdf").exists()
    assert json.loads((out / "engineering_findings.json").read_text(encoding="utf-8"))["findings"] == []


def test_generation_failure_keeps_the_flags_and_serves_nothing_stale(tmp_path, monkeypatch):
    out, pdf = make_run(tmp_path, *TWO)
    em.finalize_markup(out, pdf, run_id="r1", part="P1")
    monkeypatch.setattr(em, "render_marked_pdf", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    m = em.finalize_markup(out, pdf, run_id="r2", part="P1")
    assert m["status"] == "failed" and m["failure"]["code"] == "MARKUP_GENERATION_FAILED" and "boom" in m["failure"]["detail"]
    assert m["finding_count"] == 2 and m["marked_pdf"] is None
    assert not list(out.glob("*_engineering_markup.pdf")) and not (out / em.PAGES_DIR).exists()
    flags = json.loads((out / "engineering_findings.json").read_text(encoding="utf-8"))
    assert len(flags["findings"]) == 2                                                       # still visible in Results


def test_missing_drawing_is_reported_not_hidden(tmp_path):
    out, pdf = make_run(tmp_path, *TWO)
    m = em.finalize_markup(out, tmp_path / "gone.pdf", run_id="r", part="P1")
    assert m["status"] == "failed" and m["failure"]["code"] == "MARKUP_SOURCE_PDF_MISSING" and m["finding_count"] == 2


def test_image_sources_and_views_folders_are_supported(tmp_path):
    out, pdf = make_run(tmp_path, {"cq_skipped": {"F003": "x"}}, [{"id": "F003", "source_callouts": [CALL_P1]}], pdf_pages=1)
    png = tmp_path / "views"
    png.mkdir()
    pymupdf.open(pdf)[0].get_pixmap(dpi=150).save(png / "P1.png")
    assert em.resolve_source(png, "P1") == png / "P1.png"
    assert em.resolve_source(tmp_path / "nope", "P1") is None


def test_disabled_by_env_does_nothing(tmp_path):
    out, pdf = make_run(tmp_path, *TWO)
    assert em.finalize_markup(out, pdf, run_id="r", part="P1", env={"GPTASTRA_AUTO_ENGINEERING_FLAGS": "0"}) is None
    assert not (out / em.MANIFEST).exists()


def test_the_human_marked_view_is_never_touched(tmp_path):
    out, pdf = make_run(tmp_path, *TWO)
    human = out / "full_marked_view.jpg"
    human.write_bytes(b"HUMAN")
    em.finalize_markup(out, pdf, run_id="r", part="P1")
    em.clear_stale(out)
    assert human.read_bytes() == b"HUMAN"


def test_progress_ticks_are_emitted_once_per_stage(tmp_path):
    out, pdf = make_run(tmp_path, *TWO)
    seen = []
    em.finalize_markup(out, pdf, run_id="r", part="P1", tick=seen.append)
    assert seen == ["collect", "localize", "render", "publish"]


def test_unicode_engineering_symbols_do_not_break_rendering(tmp_path):
    out, pdf = make_run(tmp_path, {"cq_skipped": {"F003": "Ø6.4 ±.05 ⌴ depth"}}, [{"id": "F003", "source_callouts": [CALL_P1]}], pdf_pages=1)
    m = em.finalize_markup(out, pdf, run_id="r", part="P1")
    assert m["status"] in ("ready", "partial") and (out / m["marked_pdf"]).is_file()
    assert "Ø" in _text(out / m["marked_pdf"], 0)


def test_many_findings_on_one_page_never_overflow_and_point_to_the_report(tmp_path):
    feats = [{"id": f"F{i:03d}", "source_callouts": [CALL_P1]} for i in range(1, 25)]
    skipped = {f["id"]: "reason " + "long " * 12 for f in feats}
    out, pdf = make_run(tmp_path, {"cq_skipped": skipped}, feats, pdf_pages=1)
    m = em.finalize_markup(out, pdf, run_id="r", part="P1")
    assert m["status"] in ("ready", "partial") and (out / m["marked_pdf"]).is_file()
    doc = pymupdf.open(out / m["marked_pdf"])
    assert len(doc) == 1 + m["report_pages"]
    assert "EF-001" in doc[1].get_text()


def test_a_large_sheet_scales_the_rail_and_type_so_labels_stay_readable(tmp_path):
    out = tmp_path / "P1"
    out.mkdir()
    doc = pymupdf.open()
    pg = doc.new_page(width=2592, height=1728)             # a 36 x 24 in D-size sheet
    pg.insert_text((400, 500), CALL_P1, fontsize=40)
    doc.save(out / "big.pdf")
    (out / "ir_report.json").write_text(json.dumps({"part": "P1", "cq_skipped": {"F003": "no depth"}}), encoding="utf-8")
    (out / "plan.json").write_text(json.dumps({"plan": {"features": [{"id": "F003", "source_callouts": [CALL_P1]}]}}), encoding="utf-8")
    m = em.finalize_markup(out, out / "big.pdf", run_id="r", part="P1")
    p = m["pages"][0]
    assert m["status"] == "ready" and p["rail_width_pt"] > em.RAIL_W * 2.5            # scaled with the sheet
    sizes = {round(s["size"], 1) for b in pymupdf.open(out / m["marked_pdf"])[0].get_text("dict")["blocks"] if b["type"] == 0
             for ln in b["lines"] for s in ln["spans"] if "EF-001" in s["text"] or "Action" in s["text"]}
    assert sizes and min(sizes) > 15                                                  # not 7 pt text on a 36 in sheet
