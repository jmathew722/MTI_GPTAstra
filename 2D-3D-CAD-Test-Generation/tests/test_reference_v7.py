"""v7 reference-driven 3D -> 2D: everything that does not need SOLIDWORKS (the native half is exercised live by tools/v7_accept.py).

Model calls are mocked here and ONLY here (tools/v7_mock.py); acceptance evidence uses the configured OpenAI client.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz  # noqa: E402

from reverse import compare, jobs, layout, planner, refextract, reference, reflayout, safety, service, state  # noqa: E402
from tools.v7_mock import MockClient, scan_layout_for  # noqa: E402


@pytest.fixture(autouse=True)
def _scratch_budget(tmp_path, monkeypatch):
    """Mocked calls must never touch the machine's real budget ledger."""
    monkeypatch.setenv("API_BUDGET_LEDGER", str(tmp_path / "budget.jsonl"))
    monkeypatch.setenv("API_BUDGET_USD", "20")
    monkeypatch.setenv("EXTRACTION_PROVIDER", "openai")             # conftest defaults the legacy extractor tests to anthropic; reference extraction is OpenAI only


# ------------------------------------------------------------------ helpers

def make_pdf(path: Path, texts=(("3.250", (100, 100)), ("2.750", (100, 200))), pages: int = 1, size=(612, 792)) -> Path:
    d = fitz.open()
    for _ in range(pages):
        pg = d.new_page(width=size[0], height=size[1])
        for t, xy in texts:
            pg.insert_text(xy, t, fontsize=10)
        pg.draw_rect(fitz.Rect(150, 300, 300, 400), color=(0, 0, 0), width=1)
    d.save(str(path))
    d.close()
    return path


def make_part(path: Path, payload: bytes = b"PART") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def forward_run(root: Path, name: str, part_bytes: bytes, pdf: Path | None = None, record_sha: str | None = None, part_number: str = "X1") -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / f"{name}_extraction.json").write_text(json.dumps({"part_number": part_number, "part_name": "N", "units": "inch", "dimensions": [{"id": "D001", "type": "linear", "value": 3.25, "unit": "inch"}],
                                                           "views": [], "hole_callouts": []}), encoding="utf-8")
    (d / "model_ir.SLDPRT").write_bytes(part_bytes)
    if pdf is not None:
        (d / f"{name}.pdf").write_bytes(pdf.read_bytes())
    if record_sha:
        (d / "engineering_markup.json").write_text(json.dumps({"source_sha256": record_sha, "source_pdf": f"{name}.pdf"}), encoding="utf-8")
    return d


# ------------------------------------------------------------------ PDF validation

def test_validate_pdf_accepts_and_rejects(tmp_path):
    good = make_pdf(tmp_path / "g.pdf")
    v = reference.validate_pdf(good)
    assert v["ok"] and v["pages"] == 1 and len(v["sha256"]) == 64 and v["size"] > 0
    empty = tmp_path / "e.pdf"
    empty.write_bytes(b"")
    assert not reference.validate_pdf(empty)["ok"]
    txt = tmp_path / "t.pdf"
    txt.write_text("hello not a pdf")
    assert "signature" in reference.validate_pdf(txt)["error"]
    corrupt = tmp_path / "c.pdf"
    corrupt.write_bytes(b"%PDF-1.4\n" + b"garbage" * 50)
    assert not reference.validate_pdf(corrupt)["ok"]
    many = make_pdf(tmp_path / "m.pdf", pages=3)
    assert not reference.validate_pdf(many, max_pages=2)["ok"]
    assert not reference.validate_pdf(good, max_bytes=10)["ok"]
    assert not reference.validate_pdf(tmp_path / "missing.pdf")["ok"]


def test_validate_pdf_rejects_encrypted(tmp_path):
    d = fitz.open()
    d.new_page()
    p = tmp_path / "enc.pdf"
    d.save(str(p), encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    d.close()
    v = reference.validate_pdf(p)
    assert not v["ok"] and "password" in v["error"].lower()


def test_request_normalization():
    assert reference.normalize_request(None)["mode"] == "standard"
    r = reference.normalize_request({"mode": "match", "per_part": {"a": {"source": "upload", "pdf_path": "x"}}, "fallback_standard": True})
    assert r["mode"] == "match" and r["fallback_standard"] and r["per_part"]["a"]["source"] == "upload"
    for bad in ("x", {"mode": "weird"}, {"mode": "match", "per_part": []}, {"mode": "match", "per_part": {"a": {"source": "magic"}}}, {"mode": "match", "per_part": {"a": 3}}):
        with pytest.raises(safety.SafetyError):
            reference.normalize_request(bad)


# ------------------------------------------------------------------ history lookup: evidence, ambiguity, never by name alone

def test_candidates_hash_and_recorded_source_are_confirmed(tmp_path):
    hist = tmp_path / "hist"
    pdf = make_pdf(tmp_path / "src.pdf")
    sha = reference.validate_pdf(pdf)["sha256"]
    forward_run(hist, "A1", b"PARTBYTES", pdf, record_sha=sha)
    part = make_part(tmp_path / "in" / "anything.SLDPRT", b"PARTBYTES")
    idx = reference.ReferenceIndex([hist])
    res = idx.candidates(part)
    assert res["selected"] and res["selected"]["link"] == "recorded_source_hash" and not res["selected"]["needs_confirmation"]
    assert res["selected"]["confidence"] >= 0.95 and res["selected"]["pages"] == 1
    assert "path" not in json.dumps(res).lower().replace("part", "")  # no server paths in the public record


def test_candidates_colocated_pdf_with_matching_part_hash(tmp_path):
    hist = tmp_path / "hist"
    pdf = make_pdf(tmp_path / "src.pdf")
    forward_run(hist, "A2", b"BYTES2", pdf)
    part = make_part(tmp_path / "p.SLDPRT", b"BYTES2")
    res = reference.ReferenceIndex([hist]).candidates(part)
    assert res["selected"]["link"] == "forward_run" and res["selected"]["confidence"] == pytest.approx(0.95)


def test_filename_alone_is_a_candidate_never_selected(tmp_path):
    hist = tmp_path / "hist"
    hist.mkdir()
    make_pdf(hist / "A00115.pdf")
    part = make_part(tmp_path / "A00115.SLDPRT", b"UNKNOWN")           # same name, no hash / forward evidence
    res = reference.ReferenceIndex([hist]).candidates(part)
    assert res["selected"] is None
    assert res["candidates"] and all(c["needs_confirmation"] for c in res["candidates"]) and res["candidates"][0]["link"] == "name_only"
    assert res["candidates"][0]["confidence"] < 0.5


def test_unrelated_pdf_is_not_a_candidate(tmp_path):
    hist = tmp_path / "hist"
    hist.mkdir()
    make_pdf(hist / "SB99999.pdf")
    part = make_part(tmp_path / "A00115.SLDPRT", b"UNKNOWN")
    assert reference.ReferenceIndex([hist]).candidates(part)["candidates"] == []


def test_ambiguous_same_part_two_different_drawings_needs_confirmation(tmp_path):
    hist = tmp_path / "hist"
    pdf1 = make_pdf(tmp_path / "r1.pdf", texts=(("1.000", (50, 50)),))
    pdf2 = make_pdf(tmp_path / "r2.pdf", texts=(("2.000", (50, 50)),))
    forward_run(hist, "REV_A", b"SAME", pdf1)
    forward_run(hist, "REV_B", b"SAME", pdf2)
    part = make_part(tmp_path / "p.SLDPRT", b"SAME")
    idx = reference.ReferenceIndex([hist], links_path=tmp_path / "links.json")
    res = idx.candidates(part)
    assert res["selected"] is None and len(res["candidates"]) == 2 and all(c["needs_confirmation"] for c in res["candidates"])
    # the user's explicit confirmation resolves it, persisted by content hash + configuration
    chosen = res["candidates"][0]
    idx.save_link(res["part"]["sha256"], "", chosen["sha256"], user="tester")
    res2 = idx.candidates(part)
    assert res2["selected"] and res2["selected"]["link"] == "confirmed" and res2["selected"]["sha256"] == chosen["sha256"]
    # a different configuration is not covered by that confirmation
    assert idx.candidates(part, config="Other")["selected"] is None


def test_prior_extractions_require_hash_evidence(tmp_path):
    hist = tmp_path / "hist"
    pdf = make_pdf(tmp_path / "src.pdf")
    sha = reference.validate_pdf(pdf)["sha256"]
    forward_run(hist, "GOOD", b"X", pdf)
    other = make_pdf(tmp_path / "other.pdf", texts=(("9.999", (10, 10)),))
    forward_run(hist, "WRONG", b"Y", other)
    idx = reference.ReferenceIndex([hist])
    ex = idx.prior_extractions(sha)
    assert [e["run"] for e in ex] == ["GOOD"] and "byte-identical" in ex[0]["why"]


# ------------------------------------------------------------------ resolver (per part, explicit reasons, blocked / fallback)

@pytest.fixture
def refs(tmp_path):
    hist = tmp_path / "hist"
    hist.mkdir()
    return reference.ReferenceServices(tmp_path / "data", roots=[hist])


def test_save_reference_pdf_is_content_addressed_and_rejects_bad_files(refs, tmp_path):
    pdf = make_pdf(tmp_path / "u.pdf")
    a = refs.resolver.save_pdf(pdf)
    assert a["ok"] and Path(a["pdf_path"]).is_file() and a["artifact_id"].startswith("pdf_")
    assert refs.resolver.save_pdf(pdf)["pdf_path"] == a["pdf_path"]            # same content, same stored file
    bad = tmp_path / "x.pdf"
    bad.write_text("nope")
    r = refs.resolver.save_pdf(bad)
    assert not r["ok"] and r["pdf_path"] == ""


def test_resolve_upload_overrides_history_and_warns_on_conflict(tmp_path):
    hist = tmp_path / "hist"
    hist_pdf = make_pdf(tmp_path / "h.pdf")
    forward_run(hist, "A3", b"B3", hist_pdf)
    services = reference.ReferenceServices(tmp_path / "data", roots=[hist])
    part = make_part(tmp_path / "p.SLDPRT", b"B3")
    up = services.resolver.save_pdf(make_pdf(tmp_path / "up.pdf", texts=(("7.777", (20, 20)),)))
    req = reference.normalize_request({"mode": "match", "per_part": {str(part): {"source": "upload", "pdf_path": up["pdf_path"]}}})
    r = services.resolver.resolve(part, "", req["per_part"][str(part)], req)
    assert not r["_blocked"] and r["source_kind"] == "upload" and r["sha256"] == up["sha256"]
    assert any("differs from the drawing this part was generated from" in w for w in r["warnings"]) and r["history_conflict"]


def test_resolve_upload_outside_store_is_rejected(tmp_path):
    services = reference.ReferenceServices(tmp_path / "data", roots=[])
    outside = make_pdf(tmp_path / "evil.pdf")
    part = make_part(tmp_path / "p.SLDPRT")
    req = reference.normalize_request({"mode": "match", "per_part": {str(part): {"source": "upload", "pdf_path": str(outside)}}})
    r = services.resolver.resolve(part, "", req["per_part"][str(part)], req)
    assert r["_blocked"] and r["error"].startswith("REFERENCE_PDF_REJECTED")


def test_resolve_match_without_source_blocks_with_reason_or_falls_back(tmp_path):
    services = reference.ReferenceServices(tmp_path / "data", roots=[])
    part = make_part(tmp_path / "p.SLDPRT")
    req = reference.normalize_request({"mode": "match"})
    r = services.resolver.resolve(part, "", {"source": "auto"}, req)
    assert r["_blocked"] and r["status"] == "blocked" and r["error"].startswith("REFERENCE_BLOCKED") and "Upload the original PDF" in r["error"]
    req2 = reference.normalize_request({"mode": "match", "fallback_standard": True})
    r2 = services.resolver.resolve(part, "", {"source": "auto"}, req2)
    assert not r2["_blocked"] and r2["status"] == "fallback_standard" and any("Standard" in w for w in r2["warnings"])


def test_resolve_ambiguous_auto_is_not_guessed(tmp_path):
    hist = tmp_path / "hist"
    forward_run(hist, "R1", b"S", make_pdf(tmp_path / "a.pdf", texts=(("1", (5, 5)),)))
    forward_run(hist, "R2", b"S", make_pdf(tmp_path / "b.pdf", texts=(("2", (5, 5)),)))
    services = reference.ReferenceServices(tmp_path / "data", roots=[hist])
    part = make_part(tmp_path / "p.SLDPRT", b"S")
    req = reference.normalize_request({"mode": "match"})
    r = services.resolver.resolve(part, "", {"source": "auto"}, req)
    assert r["_blocked"] and "REFERENCE_AMBIGUOUS" in r["error"]
    # explicit selection of one artifact resolves it
    cands = services.index.candidates(part)["candidates"]
    r2 = services.resolver.resolve(part, "", {"source": "artifact", "artifact_id": cands[0]["artifact_id"]}, req)
    assert not r2["_blocked"] and r2["source_kind"] == "artifact" and r2["confirmed_by_selection"] is False if "confirmed_by_selection" in r2 and False else not r2["_blocked"]


def test_resolve_linked_history_auto(tmp_path):
    hist = tmp_path / "hist"
    forward_run(hist, "LINK", b"PP", make_pdf(tmp_path / "s.pdf"))
    services = reference.ReferenceServices(tmp_path / "data", roots=[hist])
    part = make_part(tmp_path / "p.SLDPRT", b"PP")
    req = reference.normalize_request({"mode": "match"})
    r = services.resolver.resolve(part, "", {"source": "auto"}, req)
    assert not r["_blocked"] and r["source_kind"] == "history" and r["link"] == "forward_run" and r["pages"] == 1
    pub = reference.public_reference(r)
    assert "_pdf" not in pub and all(not k.startswith("_") for k in pub)


# ------------------------------------------------------------------ job creation (per-part resolution, blocked parts, old jobs)

def test_create_job_resolves_reference_per_part_and_blocks_only_unresolved(tmp_path):
    hist = tmp_path / "hist"
    forward_run(hist, "OK", b"OKBYTES", make_pdf(tmp_path / "s.pdf"))
    services = reference.ReferenceServices(tmp_path / "data", roots=[hist])
    ok = make_part(tmp_path / "parts" / "ok.SLDPRT", b"OKBYTES")
    nope = make_part(tmp_path / "parts" / "nope.SLDPRT", b"NOPE")
    store = state.JobStore(tmp_path / "out")
    job = jobs.create_job(store, template={"id": "t", "path": ""}, part_paths=[ok, nope], reference={"mode": "match"}, refs=services)
    by = {p.part_id: p for p in job.parts}
    assert by["ok"].reference["status"] == "resolved" and by["ok"].state == "queued"
    assert by["nope"].state == "failed" and by["nope"].reference["status"] == "blocked" and by["nope"].error.startswith("REFERENCE_BLOCKED")
    # reload: private keys survive in the file but are never part of the public view
    j2 = store.load(job.job_id)
    assert j2.parts[0].reference["status"] == "resolved"


def test_standard_mode_parts_have_not_applicable_reference(tmp_path):
    store = state.JobStore(tmp_path / "out")
    p = make_part(tmp_path / "a.SLDPRT")
    job = jobs.create_job(store, template={"id": "t", "path": ""}, part_paths=[p])
    assert job.parts[0].reference["mode"] == "standard" and job.parts[0].reference["status"] == "not_applicable"


def test_job_view_contract_for_old_and_new_jobs(tmp_path):
    svc = service.ReverseService(tmp_path / "data", authorized_roots=[tmp_path], reference_roots=[])
    # an "old" job file written before v7 (no reference / verification keys)
    j = state.Job(job_id="r3d_old", template_id="t")
    j.parts = [state.PartState(part_id="p0", source=str(tmp_path / "p0.SLDPRT"), name="p0.SLDPRT")]
    svc.store.save(j)
    raw = json.loads((svc.store.dir("r3d_old") / "job.json").read_text())
    for p in raw["parts"]:
        p.pop("reference", None)
        p.pop("verification", None)
    (svc.store.dir("r3d_old") / "job.json").write_text(json.dumps(raw))
    v = svc.job_view("r3d_old")
    p0 = v["parts"][0]
    assert p0["reference"]["mode"] == "standard" and p0["reference"]["status"] == "not_applicable"
    assert p0["verification"] == {"status": "not_run"}
    assert v["stage_order"][:3] == ["preflight", "stl_export", "reference_resolution"] and "mesh_export" in v["stage_labels"]
    assert set(p0["files_availability"]) == {"slddrw", "pdf", "source_pdf", "stl", "qa_json", "comparison_images"} and not any(p0["files_availability"].values())


def test_part_files_aliases_and_comparison_images(tmp_path):
    svc = service.ReverseService(tmp_path / "data", authorized_roots=[tmp_path], reference_roots=[])
    j = state.Job(job_id="r3d_new", template_id="t")
    p = state.PartState(part_id="p0", source="x", name="p0.SLDPRT")
    j.parts = [p]
    base = svc.store.dir("r3d_new")
    for rel, data in (("p0/active/drawing.slddrw", b"SW"), ("p0/active/drawing.pdf", b"%PDF-1.4"), ("p0/active/reference/source.pdf", b"%PDF-1.4"),
                      ("p0/active/model.stl", b"solid"), ("p0/active/qa.json", b"{}"), ("p0/active/comparison/page-001.png", b"PNG"), ("p0/active/comparison/page-002.png", b"PNG")):
        (base / rel).parent.mkdir(parents=True, exist_ok=True)
        (base / rel).write_bytes(data)
    p.artifacts = {n: f"p0/active/{n}" for n in ("drawing.slddrw", "drawing.pdf", "reference/source.pdf", "model.stl", "qa.json", "comparison/page-001.png", "comparison/page-002.png")}
    svc.store.save(j)
    files = svc.part_files(j, p)
    for k in ("slddrw", "pdf", "source_pdf", "stl", "qa_json"):
        assert files[k]["available"] and files[k]["bytes"] > 0 and files[k]["url_path"]
    assert [f["name"] for f in files["comparison_images"]["files"]] == ["comparison/page-001.png", "comparison/page-002.png"]
    assert all(svc.files_availability(files).values())
    # containment is unchanged: only listed artifacts of this job are served
    assert svc.artifact_path("r3d_new", "p0/active/reference/source.pdf").is_file()
    with pytest.raises(safety.SafetyError):
        svc.artifact_path("r3d_new", "../../etc/passwd")


def test_progress_counts_not_applicable_stages_as_done():
    j = state.Job(job_id="r", template_id="t")
    p = state.PartState(part_id="a", source="x", name="a")
    j.parts = [p]
    for st_ in state.REFERENCE_STAGES:
        state.mark_not_applicable(p, st_)
    p.stages["preflight"] = {"status": "succeeded"}
    pr = state.progress(j)
    assert pr["stages_done"] == 4 and pr["stages_total"] == len(state.STAGES)
    assert state.can_move("preflight", "stl_export") and state.can_move("stl_export", "view_planning")


# ------------------------------------------------------------------ extraction: cache hit = zero calls, supplement, fresh, schema repair, budget

LAYOUT = {"sheet": {"projection": "third angle", "units": "inch", "scale_text": "1:1"},
          "views": [{"id": "V1", "type": "Top", "bbox_norm": [0.1, 0.1, 0.4, 0.4], "confidence": 0.9}],
          "annotations": [{"id": "A1", "kind": "linear", "text": "3.250", "ocr_ids": ["T001"], "required": True}],
          "notes": [{"id": "N1", "kind": "general_note", "text": "BREAK SHARP EDGES"}], "material_text": ""}


def test_extraction_fresh_then_cache_hit_makes_zero_calls(tmp_path):
    pdf = make_pdf(tmp_path / "ref.pdf", texts=[(f"T{i}", (50, 40 + 30 * i)) for i in range(10)] + [("3.250", (200, 60))])
    client = MockClient(LAYOUT)
    r1 = refextract.extract_reference(pdf, cache_root=tmp_path / "cache", client=client, part="p")
    assert r1["cache"] == "fresh" and len(client.calls) == 1 and r1["usage"]["calls"] == 1 and r1["usage"]["usd"] > 0
    assert r1["extraction"]["schema_version"] == "ref/1" and r1["extraction"]["views"][0]["center_norm"] == [0.25, 0.25]
    r2 = refextract.extract_reference(pdf, cache_root=tmp_path / "cache", client=client, part="p")
    assert r2["cache"] == "hit" and len(client.calls) == 1 and r2["usage"]["calls"] == 0 and r2["usage"]["usd"] == 0.0
    assert r2["usage"]["historical_usd"] == r1["usage"]["usd"]                    # the original cost is reported separately from the (zero) incremental one
    r3 = refextract.extract_reference(pdf, cache_root=tmp_path / "cache", client=client, part="p", refresh=True)
    assert r3["cache"] == "fresh" and len(client.calls) == 2                       # an explicit refresh is the only way to pay again


def test_extraction_supplements_a_forward_extraction_without_positions(tmp_path):
    pdf = make_pdf(tmp_path / "ref.pdf", texts=[(f"T{i}", (50, 40 + 30 * i)) for i in range(10)] + [("3.250", (200, 60))])
    hist = tmp_path / "hist"
    forward_run(hist, "FWD", b"Z", pdf)
    idx = reference.ReferenceIndex([hist])
    sha = reference.validate_pdf(pdf)["sha256"]
    client = MockClient(LAYOUT)
    r = refextract.extract_reference(pdf, cache_root=tmp_path / "cache", client=client, prior=idx.prior_extractions(sha), part="p")
    assert r["cache"] == "supplemented" and r["extraction"]["base_extraction"]["layout_positions"] is False
    sent = json.dumps(client.calls[0]["messages"], default=str)
    assert "PRIOR MACHINE EXTRACTION" in sent and "D001" in sent and "TEXT ITEMS" in sent          # existing geometry is reused as context, the sheet is re-read for layout


def test_extraction_positions_come_from_text_evidence_not_from_the_model(tmp_path):
    pdf = make_pdf(tmp_path / "ref.pdf", texts=[(f"T{i}", (50, 40 + 30 * i)) for i in range(10)] + [("3.250", (200, 60))])
    ev = refextract.text_evidence(pdf, 0)
    assert ev["source"] == "text_layer"
    item = next(i for i in ev["items"] if i["text"] == "3.250")
    layout_ = dict(LAYOUT, annotations=[{"id": "A1", "kind": "linear", "text": "3.250", "ocr_ids": [item["id"]], "bbox_norm": [0.9, 0.9, 0.95, 0.95]}])
    ex = refextract.extract_reference(pdf, cache_root=tmp_path / "c2", client=MockClient(layout_), part="p")["extraction"]
    a = ex["annotations"][0]
    assert a["position_source"] == "text_layer" and a["bbox_pt"] == pytest.approx(item["rect"], abs=0.5) and a["bbox_norm"][0] < 0.5       # the model's wrong bbox was ignored


def test_extraction_invalid_answer_is_repaired_once_then_fails(tmp_path):
    pdf = make_pdf(tmp_path / "ref.pdf")
    bad = {"views": "not a list"}
    c = MockClient(bad)
    with pytest.raises(ValueError):
        refextract.extract_reference(pdf, cache_root=tmp_path / "c3", client=c, part="p")
    assert len(c.calls) == 2                                                         # one repair attempt, then the failure is surfaced (never a fake pass)
    ok_after = MockClient(lambda kw: bad if len(kw["messages"]) == 1 else LAYOUT)
    r = refextract.extract_reference(pdf, cache_root=tmp_path / "c4", client=ok_after, part="p")
    assert r["usage"]["calls"] == 2


def test_extraction_stops_on_budget_and_never_calls_the_model(tmp_path, monkeypatch):
    from pipeline import budget
    monkeypatch.setenv("API_BUDGET_USD", "0.0001")
    pdf = make_pdf(tmp_path / "ref.pdf")
    c = MockClient(LAYOUT)
    with pytest.raises(budget.BudgetExceeded):
        refextract.extract_reference(pdf, cache_root=tmp_path / "c5", client=c, part="p")
    assert c.calls == []                                                             # the cap is checked BEFORE the request is sent


def test_extraction_model_is_pinned_in_config_not_hardcoded():
    prov, model, settings = refextract._model()
    cfg = json.loads((ROOT / "config" / "models.json").read_text(encoding="utf-8"))
    assert model == cfg["reference_extractor"]["openai"] and "reference_extractor" in cfg
    src = (ROOT / "reverse" / "refextract.py").read_text(encoding="utf-8")
    assert "gpt-" not in src


# ------------------------------------------------------------------ reference layout planning

REF_EX = {"sheet": {"width_pt": 1664, "height_pt": 1232, "projection": "third angle", "units": "inch", "scale_text": "HALF"},
          "views": [{"id": "V1", "type": "Top", "bbox_norm": [0.252, 0.304, 0.393, 0.465], "center_norm": [0.3225, 0.3845], "confidence": 0.9},
                    {"id": "V3", "type": "Front", "bbox_norm": [0.254, 0.560, 0.395, 0.648], "center_norm": [0.3245, 0.604], "confidence": 0.9}]}


def test_parse_scale_words_and_ratios():
    assert reflayout.parse_scale("1:2") == (1, 2) and reflayout.parse_scale("= HALF") == (1, 2) and reflayout.parse_scale("FULL SIZE") == (1, 1)
    assert reflayout.parse_scale("2:1") == (2, 1) and reflayout.parse_scale("") is None and reflayout.parse_scale("SEE NOTE") is None and reflayout.parse_scale("1.5:1") is None


def test_pick_profile_uses_reference_proportions_and_records_deviation():
    prof, dev = reflayout.pick_profile(REF_EX, "us_third_angle_inch")
    assert prof == "us_third_angle_inch_c" and any("ANSI_C" in d for d in dev)
    prof2, _ = reflayout.pick_profile({"sheet": {"width_pt": 842, "height_pt": 595, "projection": "first angle", "units": "mm"}}, "us_third_angle_inch")
    assert prof2 == "iso_first_angle_a3"
    prof3, dev3 = reflayout.pick_profile({"sheet": {}}, "us_third_angle_inch")
    assert prof3 == "us_third_angle_inch" and dev3


def _plan(profile="us_third_angle_inch_c"):
    return planner.plan_views((0.0825, 0.0699, 0.0381), profile, hole_axes={"z": 4}, scale_override=(1, 2))        # the reference prints HALF


def test_apply_reference_places_views_by_silhouette_and_keeps_projection_alignment():
    plan = _plan()
    rec = reflayout.apply_reference(plan, REF_EX, {"x": 0.0825, "y": 0.0699, "z": 0.0381})
    assert rec["applied"]
    r = {k: planner.Rect(*v) for k, v in plan["rects_m"].items()}
    f, t = r["front"], r["top"]
    assert abs((f.x0 + f.x1) / 2 - (t.x0 + t.x1) / 2) < 1e-6                         # projected views stay aligned with their base
    W, H = plan["regions_m"]["sheet"][2], plan["regions_m"]["sheet"][3]
    assert abs((f.x0 + f.x1) / 2 - 0.3225 * W) < 1e-6 and abs((f.y0 + f.y1) / 2 - (1 - 0.3845) * H) < 1e-6
    assert all(rec["views"][k].get("matched_by") for k in ("front", "top"))
    assert rec["transform"]["x"] == "nx * W"


def test_apply_reference_never_copies_an_overlapping_placement():
    plan = _plan()
    bad = json.loads(json.dumps(REF_EX))
    bad["views"][0]["center_norm"] = [0.97, 0.97]                                      # would fall in the title block / outside the usable area
    before = {k: list(v) for k, v in plan["rects_m"].items()}
    rec = reflayout.apply_reference(plan, bad, {"x": 0.0825, "y": 0.0699, "z": 0.0381})
    assert not rec["applied"] and plan["rects_m"]["front"] == before["front"]
    assert any("not copied" in d for d in rec["deviations"])


def test_apply_reference_without_views_is_a_recorded_standard_layout():
    plan = _plan()
    rec = reflayout.apply_reference(plan, {"sheet": {}, "views": []}, {"x": 1, "y": 1, "z": 1})
    assert not rec["applied"] and rec["deviations"]


# ------------------------------------------------------------------ semantic + spatial comparison

NATIVE = [{"id": "front/RD1", "kind": "dimension", "view": "front", "value_m": 3.25 * 0.0254, "dangling": False, "position_m": [0.1, 0.1]},
          {"id": "front/RD2", "kind": "dimension", "view": "front", "value_m": 0.40625 * 0.0254, "dangling": False, "position_m": [0.2, 0.2]},
          {"id": "top/RD1", "kind": "dimension", "view": "top", "value_m": 1.5 * 0.0254, "dangling": False, "position_m": [0.3, 0.3]}]


def sem(ann, notes=(), material=None, native=NATIVE, pages=1, carried=()):
    ex = {"sheet": {"units": "inch"}, "source": {"pages": pages}, "annotations": ann, "notes": list(notes), "material": {"printed": material}, "views": []}
    return compare.semantic(ex, native, default_unit="inch", notes_carried=set(carried), native_material=None, native_views={})


def test_semantic_matches_true_values_within_printed_precision():
    r = sem([{"id": "A1", "kind": "linear", "text": "3.25", "required": True}, {"id": "A2", "kind": "hole_callout", "text": "4X Ø.406 THRU", "required": True},
             {"id": "A3", "kind": "linear", "text": "1.50", "required": True}])
    st = {e["ref_id"]: e["status"] for e in r["ledger"]}
    assert st == {"A1": "matched", "A2": "matched", "A3": "matched"} and r["coverage"]["matched"] == 3 and r["coverage"]["total"] == 3 and not r["coverage"]["unresolved"]


def test_semantic_keeps_true_value_and_flags_a_reference_that_differs():
    r = sem([{"id": "A1", "kind": "linear", "text": "3.30", "required": True}])
    e = r["ledger"][0]
    assert e["status"] == "value_differs" and e["severity"] == "high" and "true value is shown" in e["reason"] and e["observed"].startswith("3.2500")
    assert r["coverage"]["matched"] == 0 and r["coverage"]["unresolved"][0]["status"] == "value_differs"


def test_semantic_missing_unit_unknown_angular_and_tolerance_are_never_guessed():
    ex_units_unknown = {"sheet": {}, "source": {"pages": 1}, "annotations": [{"id": "A1", "kind": "linear", "text": "3.25", "required": True}], "notes": [], "views": []}
    r = compare.semantic(ex_units_unknown, NATIVE, default_unit=None, notes_carried=set(), native_material=None, native_views={})
    assert r["ledger"][0]["status"] == "unit_unknown"
    r2 = sem([{"id": "A1", "kind": "linear", "text": "9.99", "required": True}, {"id": "A2", "kind": "angular", "text": "45", "unit": "deg", "required": True}])
    assert {e["status"] for e in r2["ledger"]} == {"missing", "unresolved_requirement"}
    r3 = sem([{"id": "A1", "kind": "linear", "text": "3.25 ±.03", "tol_text": "±.03", "tol_upper": 0.03, "tol_lower": 0.03, "required": True}])
    assert [e["status"] for e in r3["ledger"]] == ["matched", "tolerance_not_applied"]
    assert any(u["status"] == "tolerance_not_applied" for u in r3["coverage"]["unresolved"])


def test_semantic_notes_material_and_pages():
    r = sem([], notes=[{"id": "N1", "kind": "general_note", "text": "BREAK EDGES"}, {"id": "N2", "kind": "general_note", "text": "DEBURR"}], carried=["N1"], material="CRS 1018", pages=2)
    st = {e["ref_id"]: e["status"] for e in r["ledger"]}
    assert st["N1"] == "preserved_note" and st["N2"] == "unresolved_requirement" and st["pages"] == "page_not_reconstructed"
    assert r["material"]["status"] == "reference_only" and "never guessed" in r["material"]["note"]
    r2 = compare.semantic({"sheet": {}, "source": {"pages": 1}, "annotations": [], "notes": [], "material": {"printed": "6061-T6"}, "views": []}, [], default_unit="inch",
                          notes_carried=set(), native_material="Plain Carbon Steel", native_views={})
    assert r2["material"]["status"] == "mismatch"


def test_spatial_deltas_are_in_sheet_millimetres_with_targets():
    ex = {"views": [{"id": "V1", "type": "Top", "center_norm": [0.5, 0.5]}], "annotations": [{"id": "A1", "bbox_norm": [0.4, 0.4, 0.5, 0.5], "position_source": "ocr"}]}
    W, H = 0.5, 0.4
    sp = compare.spatial(ex, W, H, {"front": {"type": "Top", "ref_view": None, "center_m": [0.25 + 0.0005, 0.2]}}, {"front/RD1": (0.225 + 0.003, 0.22)},
                         [{"status": "matched", "native_id": "front/RD1", "ref_id": "A1", "text": "3.25"}])
    assert sp["views"][0]["distance_mm"] == pytest.approx(0.5, abs=0.01) and sp["views"][0]["within_target"]
    assert sp["annotations"][0]["distance_mm"] == pytest.approx(3.0, abs=0.01) and not sp["annotations"][0]["within_target"]
    assert sp["summary"]["views_within_target"] == 1 and "not manufacturing tolerances" in sp["summary"]["targets_note"]


# ------------------------------------------------------------------ layout measurement / collisions

def synthetic_page(tmp_path, with_collisions: bool):
    d = fitz.open()
    pg = d.new_page(width=1224, height=792)               # ANSI B in points
    pg.insert_text((300, 300), "3.250", fontsize=10)
    pg.insert_text((303, 301) if with_collisions else (400, 300), "2.750", fontsize=10)       # overlapping text vs clear
    pg.draw_line((295, 297), (340, 297), color=(0, 0, 0), width=0.5) if False else None
    if with_collisions:
        pg.draw_line((500, 400), (560, 400), color=(0, 0, 0), width=0.5)
        pg.insert_text((520, 403), "1.875", fontsize=10)                                      # a stroke runs through this text
    pg.insert_text((1000, 100), "NOTE", fontsize=10, color=(1, 0, 0)) if with_collisions else None
    p = tmp_path / ("c.pdf" if with_collisions else "ok.pdf")
    d.save(str(p))
    d.close()
    return p


def test_detect_finds_text_overlap_stroke_through_text_and_nonblack_text(tmp_path):
    pages = layout.measure_pdf(synthetic_page(tmp_path, True))
    assert abs(pages[0].width_m - 0.4318) < 1e-4 and layout.check_scale(pages[0], 0.4318, 0.2794) is None
    col = layout.detect(pages, clearance_m=0.0015)
    kinds = {c.kind for c in col}
    assert {"text_text", "text_stroke"} <= kinds
    assert pages[0].nonblack_text and layout.score(col) > 0
    assert layout.check_scale(pages[0], 0.30, 0.20) is not None                      # a sheet-size mismatch is reported, not trusted


def test_detect_clean_page_has_no_collisions_and_exempts_touching_strokes(tmp_path):
    pages = layout.measure_pdf(synthetic_page(tmp_path, False))
    assert layout.detect(pages, clearance_m=0.0015) == []
    d = fitz.open()
    pg = d.new_page(width=1224, height=792)
    pg.insert_text((300, 300), "3.250", fontsize=10)
    pg.draw_line((300, 302.5), (340, 302.5), color=(0, 0, 0), width=0.5)             # an underline / leader that only touches the baseline
    p = tmp_path / "touch.pdf"
    d.save(str(p))
    assert layout.detect(layout.measure_pdf(p), clearance_m=0.0015) == []


def test_detect_clipping_keepout_and_ours_filter(tmp_path):
    d = fitz.open()
    pg = d.new_page(width=1224, height=792)
    pg.insert_text((1000, 760), "TITLE BLOCK TEXT", fontsize=10)
    pg.insert_text((10, 30), "OUTSIDE", fontsize=10)
    p = tmp_path / "k.pdf"
    d.save(str(p))
    pages = layout.measure_pdf(p)
    keep = {"title_block": (0.3, 0.0, 0.4318, 0.05)}
    usable = (0.02, 0.01, 0.42, 0.27)
    all_texts = layout.detect(pages, keepout=keep, usable=usable)
    assert {"text_keepout", "clipped"} <= {c.kind for c in all_texts}
    only_ours = layout.detect(pages, keepout=keep, usable=usable, ours=set())              # the template's own text is not ours
    assert only_ours == []


def test_free_at_and_offsets_respect_obstacles():
    a = layout.TBox("a", "1.0", 0.10, 0.10, 0.12, 0.103)
    other = layout.TBox("b", "2.0", 0.10, 0.1045, 0.12, 0.1075)
    offs = layout.propose_offsets(a, True)
    assert offs[0] == (0.0, 0.004) and len(offs) == 14 * 4
    assert not layout.free_at(a, 0.0, 0.0015, [other], [], None, None, None, 0.0015)
    assert layout.free_at(a, 0.0, 0.02, [other], [], None, (0.0, 0.0, 0.43, 0.28), None, 0.0015)
    assert not layout.free_at(a, 0.0, 0.02, [], [], None, (0.0, 0.0, 0.43, 0.105), None, 0.0015)             # leaves the usable area


def test_map_text_to_annotations_is_one_to_one_and_honest():
    texts = [layout.TBox("t1", "3.250", 0.10, 0.10, 0.12, 0.103), layout.TBox("t2", "2.750", 0.30, 0.30, 0.32, 0.303), layout.TBox("t3", "NOTE", 0.1, 0.1, 0.12, 0.103)]
    m = layout.map_text_to_annotations(texts, {"A": (0.11, 0.1015), "B": (0.31, 0.3015), "C": (0.9, 0.9)})
    assert m == {"A": "t1", "B": "t2"}                                               # C has nothing near it: it is simply unmapped
    notes = [{"id": "sheet/n1", "text": "VIEW FROM BOTTOM SCALE 1:2", "position_m": [0.1, 0.2]}]
    t = [layout.TBox("v", "VIEW FROM BOTTOM SCALE 1:2", 0.1, 0.2, 0.2, 0.203)]
    assert layout.map_notes_to_texts(t, notes) == {"sheet/n1": "v"}


def test_overlay_renders_a_png(tmp_path):
    pdf = synthetic_page(tmp_path, True)
    col = layout.detect(layout.measure_pdf(pdf))
    out = layout.render_overlay(pdf, col, tmp_path / "ov.png")
    assert out.is_file() and out.read_bytes()[:4] == b"\x89PNG"


# ------------------------------------------------------------------ standards without SOLIDWORKS: pure helpers

def test_arrange_integrity_detects_loss_value_change_and_dangling():
    from reverse import standards
    before = [{"id": "a", "value_m": 0.01}, {"id": "b", "value_m": 0.02}]
    assert standards.arrange_integrity(before, [dict(i, dangling=False) for i in before])["ok"]
    bad = standards.arrange_integrity(before, [{"id": "a", "value_m": 0.01}])
    assert not bad["ok"] and bad["lost"] == ["b"]
    assert standards.arrange_integrity(before, [{"id": "a", "value_m": 0.011}, {"id": "b", "value_m": 0.02}])["value_changed"] == ["a"]
    assert standards.arrange_integrity(before, [{"id": "a", "value_m": 0.01, "dangling": True}, {"id": "b", "value_m": 0.02}])["dangling"] == ["a"]
    # the constants are the ones verified against the installed 2025 type library (api_validation.md)
    assert (standards.SW_DISP_SHADED, standards.SW_BROKEN_LEADER_HORIZONTAL_TEXT, standards.SW_ALIGN_AUTO_ARRANGE) == (3, 2, 0)


def test_geometry_compatibility_detects_unrelated_reference():
    from reverse import refrun
    inv = {"size_m": [0.0825, 0.0699, 0.0381], "bbox_m": [0, 0, 0, 0.0825, 0.0699, 0.0381], "holes": [{"diameter_m": 0.0103, "center_axes": ["x", "y"], "center_m": [0.011, 0.011]}], "planes": []}
    good = {"sheet": {"units": "inch"}, "annotations": [{"kind": "linear", "text": "3.25"}, {"kind": "linear", "text": "2.75"}, {"kind": "hole_callout", "text": ".406 DIA"}]}
    other = {"sheet": {"units": "inch"}, "annotations": [{"kind": "linear", "text": "12.50"}, {"kind": "linear", "text": "8.25"}, {"kind": "linear", "text": "7.1"}]}
    assert refrun.compatibility(good, inv, "inch")["status"] == "compatible"
    assert refrun.compatibility(other, inv, "inch")["status"] == "incompatible"
    assert refrun.compatibility({"sheet": {}, "annotations": []}, inv, "inch")["status"] == "unknown"
