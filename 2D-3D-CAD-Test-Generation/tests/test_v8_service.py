"""v8 service surface: estimate_run, job_view accounting fields, rotated-page text evidence, multipage cache supplementation. Offline, no SOLIDWORKS."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from reverse import refextract, state
from reverse.service import ReverseService


def _sldprt(tmp_path, name="P.SLDPRT"):
    p = tmp_path / name
    p.write_bytes(b"\xd0\xcf\x11\xe0" + b"0" * 4096)           # passes the cheap signature check used by check_part_file
    return p


def _pdf(tmp_path, pages=1, name="d.pdf", scanned=True):
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    for i in range(pages):
        pg = doc.new_page(width=1580, height=1216)
        pg.draw_rect(fitz.Rect(100, 100, 600, 500))
        if not scanned:
            for k in range(30):
                pg.insert_text((50 + 40 * k, 60), f"{k}.5", fontsize=9)
    p = tmp_path / name
    doc.save(str(p))
    return p


def _svc(tmp_path):
    from tools.v7_env import make_service
    return make_service(tmp_path / "data", reference_roots=[], roots=[tmp_path])


def test_estimate_run_standard_has_no_model_cost_and_never_raises_for_bad_path(tmp_path):
    svc = _svc(tmp_path)
    try:
        part = _sldprt(tmp_path)
    except Exception:
        pytest.skip("part fixture not accepted")
    r = svc.estimate_run([part, tmp_path / "missing.SLDPRT"])
    assert r["mode"] == "standard" and r["schema_version"] == 1
    good, bad = r["parts"]
    if good["estimate"] is not None:
        assert good["estimate"]["cost"]["expected"] == 0.0 and good["estimate"]["duration"]["source"] == "fallback"
    assert bad["estimate"] is None and bad["reference"]["status"] == "blocked" and bad["warning"]
    assert r["budget"]["cap_usd"] > 0 and "remaining_usd" in r["budget"]


def test_estimate_run_match_uses_pdf_pages_and_cache(tmp_path):
    svc = _svc(tmp_path)
    part = _sldprt(tmp_path)
    pdf = _pdf(tmp_path, pages=3)
    saved = svc.save_reference_pdf(str(pdf))
    assert saved["ok"], saved
    ref = {"mode": "match", "per_part": {str(part): {"source": "upload", "pdf_path": saved["pdf_path"]}}}
    r = svc.estimate_run([part], ref)
    e = r["parts"][0]["estimate"]
    if e is None:
        pytest.skip("part fixture not accepted by the safety check")
    assert r["parts"][0]["reference"]["pages"] == 3 and r["parts"][0]["reference"]["extraction_cache"] == "fresh"
    c = e["cost"]
    assert 0 < c["low"] < c["expected"] < c["high"] and e["duration"]["source"] == "fallback" and "fallback_tokens" in e["labels"]
    one = svc.estimate_run([part], {"mode": "match", "per_part": {str(part): {"source": "upload", "pdf_path": _saved(svc, _pdf(tmp_path, 1, "one.pdf"))}}})
    assert one["total"]["cost"]["expected"] < c["expected"]                       # more pages cost more
    # a complete cached extraction (all 3 pages) makes the expected cost $0 and says so
    sha = saved["sha256"]
    ex = {"schema_version": refextract.SCHEMA, "source": {"sha256": sha}, "provenance": {"prompt_version": refextract.PROMPT_VERSION}, "quality": {"ok": True}, "warnings": []}
    ex["more_pages"] = [dict(ex), dict(ex)]
    p = refextract.cache_path(svc.refs.cache_root, sha)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(ex), encoding="utf-8")
    hit = svc.estimate_run([part], ref)
    assert hit["parts"][0]["reference"]["extraction_cache"] == "hit" and hit["total"]["cost"]["expected"] == 0.0


def _saved(svc, pdf):
    return svc.save_reference_pdf(str(pdf))["pdf_path"]


def test_multipage_cache_is_partial_until_every_page_is_present(tmp_path):
    sha = "a" * 64
    ex = {"schema_version": refextract.SCHEMA, "source": {"sha256": sha}, "provenance": {"prompt_version": refextract.PROMPT_VERSION}, "quality": {"ok": True}}
    p = refextract.cache_path(tmp_path, sha)
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(ex), encoding="utf-8")
    assert refextract.load_cached(tmp_path, sha) is not None                       # legacy single page = complete for a 1-page PDF
    assert refextract.load_cached(tmp_path, sha, 3) is None                        # 3-page PDF: supplement pages 2..3, never trust a partial
    assert len(refextract._page_list(refextract.load_partial(tmp_path, sha))) == 1


def test_text_evidence_is_in_displayed_space_for_rotated_pages(tmp_path):
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    pg = doc.new_page(width=600, height=400)
    for k in range(10):
        pg.insert_text((100, 50 + 30 * k), f"WORD{k}", fontsize=14)
    pg.set_rotation(90)
    p = tmp_path / "rot.pdf"
    doc.save(str(p))
    ev = refextract.text_evidence(p, 0)
    assert ev["source"] == "text_layer"
    W, H = 400, 600                                                                # displayed size after a 90 degree rotation
    for it in ev["items"]:
        x0, y0, x1, y1 = it["rect"]
        assert 0 <= x0 < x1 <= W + 1 and 0 <= y0 < y1 <= H + 1
    assert all(it.get("font") for it in ev["items"])


def test_job_view_accounting_fields(tmp_path):
    svc = _svc(tmp_path)
    job = state.Job(job_id="jobx", template_id="t")
    pa = state.PartState(part_id="a", source="x", name="a.SLDPRT")
    pa.state, pa.seconds, pa.started, pa.ended = "completed", 12.0, "2026-01-01T00:00:05+00:00", "2026-01-01T00:00:17+00:00"
    job.created = "2026-01-01T00:00:00+00:00"
    job.parts = [pa]
    svc.store.save(job)
    d = svc.store.dir("jobx") / "usage"
    d.mkdir(parents=True, exist_ok=True)
    row = {"row_id": "r1", "role": "extractor", "provider": "openai", "model": "gpt-6-astra", "part": "a", "input_tokens": 1000, "output_tokens": 200, "cache_read_tokens": 0,
           "cache_write_tokens": 0, "cache_hit": False, "ok": True, "extra": {"response_id": "resp_1", "gate": "reference_layout"}}
    (d / "usage_ledger.jsonl").write_text(json.dumps(row) + "\n" + json.dumps(dict(row, row_id="r2")) + "\n", encoding="utf-8")       # replayed event: same response id
    v = svc.job_view("jobx")
    u = v["usage"]
    assert u["calls"] == 1 and u["cost_status"] == "priced" and u["cost_usd"] > 0 and "extraction" in u["by_stage"]
    assert v["timing"]["queued_s"] == 5.0 and v["timing"]["elapsed_s"] == 12.0 and v["parts"][0]["usage"]["calls"] == 1
    assert v["estimate"] is None and v["parts"][0]["replication"] is None
    assert set(v["parts"][0]["files_availability"]) >= {"drawing_spec", "replication_report", "usage_log"}
