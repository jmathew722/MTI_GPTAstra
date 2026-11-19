"""FastAPI exposure of the automatic Engineering Markup artifacts (Stage 3, plan task 5)."""
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pymupdf = pytest.importorskip("pymupdf")
from fastapi.testclient import TestClient  # noqa: E402

REPO = Path(__file__).resolve().parents[3] / "2D-3D-CAD-Test-Generation"
os.environ.setdefault("MCAGENT_REPO", str(REPO))
os.environ.setdefault("MCAGENT_DATA", tempfile.mkdtemp(prefix="mcagent_test_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
sys.path.insert(0, str(REPO))
import app as appmod  # noqa: E402
from pipeline import engineering_markup as em  # noqa: E402

SESSION = "t" + "9" * 11
client = TestClient(appmod.app)
CALL = "M6 X 1 - 12 DEEP"


def _setup(part, *, findings=True, pages=2, break_after=None):
    """A part whose output was produced by the REAL markup stage (no hand-made artifacts)."""
    sdir = appmod._session_dir(SESSION)
    (sdir / appmod.ORIGINALS_DIRNAME).mkdir(parents=True, exist_ok=True)
    out = sdir / part / "output"
    out.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    pg = doc.new_page(width=600, height=400)
    pg.insert_text((50, 60), CALL, fontsize=12)
    for _ in range(pages - 1):
        doc.new_page(width=600, height=400).insert_text((300, 200), "2 X O.250 THRU ALL", fontsize=12)
    orig = sdir / appmod.ORIGINALS_DIRNAME / f"{part}.pdf"
    doc.save(orig)
    rep = {"part": part, "cq_skipped": {"F003": "no depth"} if findings else {}}
    (out / "ir_report.json").write_text(json.dumps(rep), encoding="utf-8")
    (out / "plan.json").write_text(json.dumps({"plan": {"features": [{"id": "F003", "source_callouts": [CALL]}]}}), encoding="utf-8")
    manifest = em.finalize_markup(out, orig, run_id="run_a", part=part)
    return out, orig, manifest


def test_markup_summary_is_in_the_part_payload_with_no_absolute_paths():
    out, orig, m = _setup("ZZMK1")
    cat = appmod._categorize_output(out, session=SESSION)["categories"]["engineering_markup"]
    assert cat["present"] and cat["status"] == "ready" and cat["finding_count"] == 1 and cat["has_pdf"]
    assert cat["pages"][0]["has_preview"] and cat["findings"][0]["location_status"] == "located"
    assert cat["findings"][0]["rect_pdf_points"] and cat["findings"][0]["page"] == 1
    blob = json.dumps(cat)
    assert str(out) not in blob and ":\\" not in blob and "/Users" not in blob


def test_manifest_pdf_and_page_endpoints_serve_the_generated_artifacts():
    out, orig, m = _setup("ZZMK2")
    base = f"/api/parts/{SESSION}/ZZMK2/engineering-markup"
    r = client.get(base)
    assert r.status_code == 200 and r.json()["status"] == "ready" and r.headers["etag"] == f'"{m["generation_key"]}"'
    assert client.get(base, headers={"If-None-Match": r.headers["etag"]}).status_code == 304
    pdf = client.get(base + ".pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    assert len(pymupdf.open(stream=pdf.content, filetype="pdf")) >= 3
    png = client.get(base + "/page/1.png")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png" and png.content.startswith(b"\x89PNG")
    assert client.get(base + "/page/2.png").status_code == 200


def test_invalid_pages_unknown_parts_and_traversal_are_refused():
    _setup("ZZMK3")
    base = f"/api/parts/{SESSION}/ZZMK3/engineering-markup"
    assert client.get(base + "/page/0.png").status_code == 404
    assert client.get(base + "/page/99.png").status_code == 404
    assert client.get(base + "/page/abc.png").status_code in (404, 422)
    assert client.get(f"/api/parts/{SESSION}/NOPE/engineering-markup").status_code == 404
    assert client.get(f"/api/parts/{SESSION}/NOPE/engineering-markup.pdf").status_code == 404
    assert client.get(base + "/page/..%2f..%2fir_report.json.png").status_code in (404, 422)


def test_a_manifest_naming_a_foreign_file_is_never_served(tmp_path):
    out, orig, m = _setup("ZZMK4")
    (out / "secret.pdf").write_bytes(b"%PDF-1.4 secret")
    mf = json.loads((out / "engineering_markup.json").read_text(encoding="utf-8"))
    for bad in ("secret.pdf", "../secret.pdf", "..\\secret.pdf", "sub/x_engineering_markup.pdf"):
        mf["marked_pdf"] = bad
        (out / "engineering_markup.json").write_text(json.dumps(mf), encoding="utf-8")
        assert client.get(f"/api/parts/{SESSION}/ZZMK4/engineering-markup.pdf").status_code == 404


def test_a_clean_run_reports_not_needed_and_serves_no_artifact():
    out, orig, m = _setup("ZZMK5", findings=False)
    cat = appmod._categorize_output(out, session=SESSION)["categories"]["engineering_markup"]
    assert cat["status"] == "not_needed" and cat["finding_count"] == 0 and not cat["has_pdf"] and cat["pages"] == []
    assert client.get(f"/api/parts/{SESSION}/ZZMK5/engineering-markup.pdf").status_code == 404
    assert client.get(f"/api/parts/{SESSION}/ZZMK5/engineering-markup/page/1.png").status_code == 404


def test_a_failed_generation_is_reported_with_its_code_and_the_flags_remain(monkeypatch):
    out, orig, _ = _setup("ZZMK6")
    monkeypatch.setattr(em, "render_marked_pdf", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    em.finalize_markup(out, orig, run_id="run_b", part="ZZMK6")
    cats = appmod._categorize_output(out, session=SESSION)["categories"]
    assert cats["engineering_markup"]["status"] == "failed"
    assert cats["engineering_markup"]["failure"]["code"] == "MARKUP_GENERATION_FAILED"
    assert cats["engineering_markup"]["finding_count"] == 1 and not cats["engineering_markup"]["has_pdf"]
    assert len(cats["flags"]["findings"]) == 1                                   # flags are never hidden
    assert client.get(f"/api/parts/{SESSION}/ZZMK6/engineering-markup.pdf").status_code == 404


def test_a_new_drawing_revision_withholds_the_old_markup():
    out, orig, _ = _setup("ZZMK7")
    orig.write_bytes(orig.read_bytes() + b"\n% revised")
    cat = appmod._categorize_output(out, session=SESSION)["categories"]["engineering_markup"]
    assert cat["status"] == "stale" and cat["stale"] and not cat["has_pdf"] and cat["findings"] == []
    assert client.get(f"/api/parts/{SESSION}/ZZMK7/engineering-markup.pdf").status_code == 404


def test_the_human_marked_view_endpoint_is_a_different_artifact():
    out, orig, _ = _setup("ZZMK8")
    human = appmod._session_dir(SESSION) / "ZZMK8" / appmod.MARKED_VIEW_FILENAME
    human.write_bytes(b"\xff\xd8\xffHUMAN")
    r = client.get(f"/api/parts/{SESSION}/ZZMK8/marked-view.jpg")
    assert r.status_code == 200 and r.content.endswith(b"HUMAN")
    em.finalize_markup(out, orig, run_id="run_c", part="ZZMK8")
    assert human.read_bytes().endswith(b"HUMAN")                                  # untouched by the pipeline stage
    assert not (appmod._session_dir(SESSION) / "ZZMK8" / "output" / appmod.MARKED_VIEW_FILENAME).exists()
