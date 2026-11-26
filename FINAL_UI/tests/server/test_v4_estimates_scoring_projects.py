"""v4: run estimates, the Scoring tab backend, PDF previews and newest-first projects. No paid calls, no SolidWorks."""
import json
import math
import os
import sys
import tempfile
import time
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
fitz = pytest.importorskip("fitz")
from fastapi.testclient import TestClient  # noqa: E402

REPO = Path(__file__).resolve().parents[3] / "2D-3D-CAD-Test-Generation"
_TMP = tempfile.mkdtemp(prefix="mcagent_v4_")
os.environ["MCAGENT_REPO"] = str(REPO)
os.environ["MCAGENT_DATA"] = os.path.join(_TMP, "data")
os.environ["MCAGENT_FINAL_OUTPUTS"] = os.path.join(_TMP, "final")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
sys.path.insert(0, str(REPO))
import app as appmod  # noqa: E402
import estimates as est  # noqa: E402
import scoring_hub as sh  # noqa: E402

client = TestClient(appmod.app)
SESSION = "v4" + "a" * 10


@pytest.fixture(autouse=True, scope="module")
def isolated_dirs():
    """appmod is imported once per pytest run, with whichever env came first. Point its folders at a private
    temp tree so these tests never read or write the real FINAL_OUTPUTs."""
    root = Path(tempfile.mkdtemp(prefix="mcagent_v4_iso_"))
    saved = {k: getattr(appmod, k) for k in ("FINAL_OUTPUTS_DIR", "PARTS_DIR", "DATA_DIR", "SCORING_DIR")}
    appmod.FINAL_OUTPUTS_DIR, appmod.PARTS_DIR, appmod.DATA_DIR = root / "final", root / "parts", root / "data"
    appmod.SCORING_DIR = root / "data" / "scoring"
    for d in (appmod.FINAL_OUTPUTS_DIR, appmod.PARTS_DIR, appmod.DATA_DIR):
        d.mkdir(parents=True, exist_ok=True)
    yield
    for k, v in saved.items():
        setattr(appmod, k, v)


def make_pdf(path: Path, pages=1):
    doc = fitz.open()
    for i in range(pages):
        pg = doc.new_page(width=842, height=595)
        pg.insert_text((72, 72), f"DRAWING page {i + 1}", fontsize=24)
        pg.draw_rect(fitz.Rect(60, 100, 700, 500))
    doc.save(str(path))
    doc.close()


def add_part(name, pdf_pages=1, fmt="pdf"):
    sdir = appmod._session_dir(SESSION)
    (sdir / appmod.ORIGINALS_DIRNAME).mkdir(parents=True, exist_ok=True)
    (sdir / name).mkdir(parents=True, exist_ok=True)
    if fmt == "pdf":
        make_pdf(sdir / appmod.ORIGINALS_DIRNAME / f"{name}.pdf", pdf_pages)
    appmod._touch_meta(sdir / name)
    (sdir / name / "00_full.jpg").write_bytes(b"x")
    return sdir / name


def events(part, runs):
    d = appmod.FINAL_OUTPUTS_DIR / part
    d.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, (start, end, kind) in enumerate(runs, start=1):
        rid = f"run_{part}_{i}"
        lines.append({"run_id": rid, "attempt": 1, "part_id": part, "kind": "run.started", "occurred_at": start})
        lines.append({"run_id": rid, "attempt": 1, "part_id": part, "kind": kind, "occurred_at": end})
    (d / "run_events.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")


# ── estimates ────────────────────────────────────────────────────────────────────────────────
def test_durations_use_completed_runs_only(tmp_path):
    events("EA", [("2026-11-01T10:00:00Z", "2026-11-01T10:03:00Z", "run.completed"),
                  ("2026-11-01T11:00:00Z", "2026-11-01T11:00:30Z", "run.failed")])
    d = est.run_durations(appmod.FINAL_OUTPUTS_DIR)
    mine = [x for x in d if x["part"] == "EA"]
    assert [x["seconds"] for x in mine] == [180.0]


def test_cost_history_skips_runs_with_any_unpriced_row():
    rows = [{"run_id": "r1", "run_attempt": 1, "cost_usd": 0.25, "priced": True},
            {"run_id": "r1", "run_attempt": 1, "cost_usd": 0.5, "priced": True},
            {"run_id": "r2", "run_attempt": 1, "cost_usd": 0.4, "priced": True},
            {"run_id": "r2", "run_attempt": 1, "cost_usd": None, "priced": False}]
    c = est.run_costs(rows)
    assert c == {("r1", 1): Decimal("0.75")}


def test_estimate_unknown_is_unavailable_never_zero():
    e = est.estimate(3, [], [])
    assert e["time"]["available"] is False and e["cost"]["available"] is False
    assert "low" not in e["time"] and "low" not in e["cost"]
    assert est.estimate(0, [10.0], [Decimal("1")])["time"]["available"] is False


def test_estimate_batch_is_the_sum_because_solidworks_is_serialized():
    one = est.estimate(1, [100.0, 200.0, 300.0], [Decimal("0.10"), Decimal("0.20"), Decimal("0.30")])
    four = est.estimate(4, [100.0, 200.0, 300.0], [Decimal("0.10"), Decimal("0.20"), Decimal("0.30")])
    assert four["concurrency"] == 1
    assert four["time"]["low"] == pytest.approx(one["time"]["low"] * 4)
    assert Decimal(four["cost"]["high"]) == Decimal(one["cost"]["high"]) * 4
    assert one["time"]["limited"] is False and one["time"]["low"] == 150.0 and one["time"]["high"] == 250.0


def test_limited_history_is_flagged_and_small_costs_keep_precision():
    e = est.estimate(1, [60.0], [Decimal("0.000123")])
    assert e["time"]["limited"] and e["cost"]["limited"]
    assert e["cost"]["low"] == "0.000123"


def test_estimate_endpoint_reconciles_with_part_count():
    events("EB", [("2026-11-02T10:00:00Z", "2026-11-02T10:04:00Z", "run.completed")] * 1)
    add_part("EB")
    r1 = client.get("/api/estimate", params={"session": SESSION, "parts": ["EB"]}).json()
    r2 = client.get("/api/estimate", params={"session": SESSION, "parts": ["EB", "EB", "EB"]}).json()
    assert r1["inputs"] == 1 and r2["inputs"] == 3
    assert r2["time"]["available"] and r2["time"]["low"] == pytest.approx(r1["time"]["low"] * 3, abs=0.2)
    assert r1["parts"][0]["pages"] == 1


def test_pdf_pages_counts_and_rejects_corrupt(tmp_path):
    p = tmp_path / "a.pdf"
    make_pdf(p, 3)
    assert est.pdf_pages(p) == (3, None)
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4\nthis is not a pdf")
    pages, err = est.pdf_pages(bad)
    assert pages is None and err


def test_preflight_pdf_endpoint(tmp_path):
    p = tmp_path / "good.pdf"
    make_pdf(p, 2)
    ok = client.post("/api/preflight/pdf", files={"file": ("good.pdf", p.read_bytes(), "application/pdf")}).json()
    assert ok == {"ok": True, "pages": 2, "error": None}
    for body in (b"MZ not a pdf", b"%PDF-1.4 broken"):
        bad = client.post("/api/preflight/pdf", files={"file": ("x.pdf", body, "application/pdf")}).json()
        assert bad["ok"] is False and bad["error"]


# ── previews and ordering ────────────────────────────────────────────────────────────────────
def test_preview_renders_the_real_first_page_and_regenerates_when_the_source_changes():
    add_part("PV1", pdf_pages=2)
    r = client.get(f"/api/parts/{SESSION}/PV1/preview.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"
    cache = appmod._session_dir(SESSION) / ".thumbs" / "previews"
    first = sorted(p.name for p in cache.glob("PV1-*.png"))
    assert len(first) == 1
    make_pdf(appmod._session_dir(SESSION) / appmod.ORIGINALS_DIRNAME / "PV1.pdf", 5)      # new content -> new fingerprint
    assert client.get(f"/api/parts/{SESSION}/PV1/preview.png").status_code == 200
    second = sorted(p.name for p in cache.glob("PV1-*.png"))
    assert len(second) == 1 and second != first                                           # stale one removed


def test_preview_unavailable_cases_do_not_crash():
    add_part("PV2")
    (appmod._session_dir(SESSION) / appmod.ORIGINALS_DIRNAME / "PV2.pdf").write_bytes(b"%PDF-1.4 corrupt")
    r = client.get(f"/api/parts/{SESSION}/PV2/preview.png")
    assert r.status_code == 204 and "could not be rendered" in r.headers["x-preview-reason"]
    assert "C:" not in r.headers["x-preview-reason"] and "Temp" not in r.headers["x-preview-reason"]     # no server paths leak
    nope = client.get(f"/api/parts/{SESSION}/NOPE/preview.png")
    assert nope.status_code == 204 and "no original" in nope.headers["x-preview-reason"]
    assert client.get(f"/api/parts/{SESSION}/%2e%2e/preview.png").status_code in (204, 404, 422)
    parts = {p["name"]: p for p in appmod._list_parts(appmod._session_dir(SESSION))}
    assert parts["PV2"]["has_original"] is True and parts["PV2"]["has_thumb"] is False


def test_parts_are_newest_activity_first_with_a_stable_tiebreak_and_timestamps_survive_reload():
    sess = "v4order" + "b" * 5
    sdir = appmod._session_dir(sess)
    for name, stamp in (("Zeta", "2026-01-01T00:00:00+00:00"), ("Alpha", "2026-03-01T00:00:00+00:00"), ("Mid", "2026-02-01T00:00:00+00:00")):
        (sdir / name).mkdir(parents=True, exist_ok=True)
        (sdir / name / appmod.META_NAME).write_text(json.dumps({"created_at": stamp}), encoding="utf-8")
        (sdir / name / "00_full.jpg").write_bytes(b"x")
    names = [p["name"] for p in appmod._list_parts(sdir)]
    assert names == ["Alpha", "Mid", "Zeta"]                                               # not alphabetical
    again = [p["name"] for p in appmod._list_parts(sdir)]                                  # a "reload": re-read from disk
    assert again == names
    first = appmod._list_parts(sdir)[0]
    assert first["created_at"] == pytest.approx(1772323200.0) and first["created_source"] == "recorded"
    (sdir / "Zeta" / appmod.META_NAME).write_text(json.dumps({"created_at": "2026-01-01T00:00:00+00:00", "last_run_at": "2026-04-01T00:00:00+00:00"}), encoding="utf-8")
    assert [p["name"] for p in appmod._list_parts(sdir)][0] == "Zeta"                      # a rerun moves it to the top at once
    # created_at is kept separately from activity
    z = next(p for p in appmod._list_parts(sdir) if p["name"] == "Zeta")
    assert z["last_activity"] > z["created_at"]


def test_unknown_creation_time_is_none_not_invented():
    sess = "v4unk" + "c" * 7
    sdir = appmod._session_dir(sess)
    (sdir / "Ghost").mkdir(parents=True, exist_ok=True)
    (sdir / "Ghost" / "front.png").write_bytes(b"x")
    g = appmod._list_parts(sdir)[0]
    assert g["created_at"] is None and g["last_activity"] is None and g["created_source"] == "unknown"


def test_preview_and_thumbnail_activity_does_not_change_ordering():
    sess = "v4act" + "d" * 7
    sdir = appmod._session_dir(sess)
    (sdir / "Old").mkdir(parents=True, exist_ok=True)
    (sdir / "Old" / appmod.META_NAME).write_text(json.dumps({"created_at": "2026-01-01T00:00:00+00:00"}), encoding="utf-8")
    (sdir / "Old" / "00_full.jpg").write_bytes(b"x")
    before = appmod._list_parts(sdir)[0]["last_activity"]
    time.sleep(0.05)
    (sdir / ".thumbs").mkdir(exist_ok=True)
    (sdir / ".thumbs" / "Old.jpg").write_bytes(b"t")
    assert appmod._list_parts(sdir)[0]["last_activity"] == before


# ── scoring ──────────────────────────────────────────────────────────────────────────────────
def test_credit_curve_matches_the_scorer_module():
    bench = pytest.importorskip("bench.credit")
    from bench import score_config, weights  # noqa: F401
    cfg = score_config.load()
    raw = sh.load_config(REPO)
    for err in (0.0, 0.004, 0.005, 0.0075, 0.01, 0.025, 0.05, 0.1):
        assert sh.attr_credit(err, 0.005, raw) == pytest.approx(bench.attr_credit(err, 0.005, cfg))
    attrs = {"position": 0.4, "size": 1.0, "depth": 1.0, "type": 1.0}
    assert sh.feature_credit(attrs, raw) == pytest.approx(bench.feature_credit(attrs, cfg))
    assert sh.feature_credit({"size": 0.5}, raw) == pytest.approx(0.5)                     # shares renormalise


def test_weights_match_the_scorer_module():
    from bench.features import Feature
    from bench import score_config, weights
    cfg, raw = score_config.load(), sh.load_config(REPO)
    f = Feature(id="H1", type="thru_hole", center=(0, 0, 0), axis=(0, 0, 1), d=0.344, depth=1.0, thru=True)
    assert sh.feature_weight("thru_hole", 0.344, 6.0, raw) == pytest.approx(weights.weight(f, 6.0, cfg))
    assert sh.feature_weight("base_body", 6.0, 6.0, raw) == 10.0
    assert sh.feature_weight("hole_pattern", 1.0, 6.0, raw) == 0.0


def test_worked_example_recomputes_from_the_documented_arithmetic():
    ex = sh.worked_example(REPO)
    assert ex["illustrative"] is True and "not a measured part" in ex["label"]
    W = ex["part"]["total_weight_W"]
    assert W == pytest.approx(10 + 4 * 2.5)
    by = {c["case"]: c for c in ex["cases"]}
    assert by["Nothing wrong"]["score"] == 100.0 and by["Nothing wrong"]["exact"] is True
    c2 = by["One hole 0.010 in off (2x tolerance)"]
    pos = 0.5 * math.exp(-1 / 4.48)
    credit = 0.55 * pos + 0.25 + 0.10 + 0.10
    assert c2["feature_credit"] == pytest.approx(credit, abs=1e-4)
    assert c2["points_lost"] == pytest.approx(100 * 2.5 * (1 - credit) / W, abs=1e-3)
    assert by["One through hole built blind"]["points_lost"] == pytest.approx(1.25, abs=1e-3)
    assert by["One hole missing"]["score"] == 87.5
    assert by["One extra hole"]["score"] == 93.75 and by["One extra hole"]["exact"] is False
    for c in ex["cases"]:
        assert 0 <= c["score"] <= 100
        assert c["score"] == pytest.approx(100 - c["points_lost"], abs=0.01)


def test_methodology_reads_the_live_config():
    m = sh.methodology(REPO)
    assert m["total_possible"] == 100
    assert {c["id"] for c in m["criteria"]} == {"position", "size", "depth", "type"}
    assert sum(c["share"] for c in m["criteria"]) == pytest.approx(1.0)
    assert m["version"].startswith("cfg-") and m["version"] == sh.rubric_version(REPO)
    curve = {c["e"]: c["credit"] for c in m["credit_curve"]}
    assert curve[1] == 1.0 and curve[2] == pytest.approx(0.4, abs=0.001) and curve[5] == pytest.approx(0.2, abs=0.01)


def test_boundary_and_inconsistent_records_are_flagged_not_hidden():
    assert sh.consistency_flags({"score": 100, "exact": True, "rows": [{"points_lost": 0}]}) == []
    assert sh.consistency_flags({"score": 120, "rows": []})
    assert sh.consistency_flags({"score": 90, "exact": True, "rows": [{"points_lost": 10}]})
    assert sh.consistency_flags({"score": 90, "rows": [{"points_lost": 3}]})                # lost points do not add up
    assert sh.consistency_flags({"score": 0, "rows": [{"points_lost": 100}]}) == []


def test_missing_evidence_is_incomplete_never_zero_and_failures_are_distinct():
    inc = sh.record_from_scorer({"part": "P", "status": "not scored (no key)"}, run_id="r", version="v1")
    assert inc["state"] == "incomplete" and inc["score"] is None and inc["explanation"]
    fail = sh.record_from_scorer({"part": "P", "error": "unreadable STEP"}, run_id="r", version="v1")
    assert fail["state"] == "scoring_failed" and fail["score"] is None
    ok = sh.record_from_scorer({"part": "P", "score": 0.0, "exact": False, "rows": [{"points_lost": 100}], "extras": []}, run_id="r", version="v1")
    assert ok["state"] == "scored" and ok["score"] == 0.0                                    # a real zero stays a real zero


def test_average_counts_only_completed_valid_scores():
    latest = {"A": {"state": "scored", "score": 80.0}, "B": {"state": "scored", "score": 100.0},
              "C": {"state": "incomplete", "score": None}, "D": {"state": "scoring_failed"}, "E": None,
              "F": {"state": "scored", "score": 140.0}}
    s = sh.summarize(latest, list("ABCDEF"))
    assert s["average"] == 90.0 and s["scored"] == 2 and s["pending"] == 1 and s["incomplete"] == 1 and s["scoring_failed"] == 1
    assert sh.summarize({}, [])["average"] is None


def test_history_is_append_only_and_a_rubric_change_does_not_rewrite_it(tmp_path):
    sh.append(tmp_path, "P", {"state": "scored", "score": 91.0, "rubric_version": "cfg-old"})
    sh.append(tmp_path, "P", {"state": "scored", "score": 84.5, "rubric_version": "cfg-new"})
    h = sh.history(tmp_path, "P")
    assert [x["score"] for x in h] == [91.0, 84.5] and h[0]["rubric_version"] == "cfg-old"
    assert sh.latest(tmp_path, "P")["rubric_version"] == "cfg-new"


def box_stl(path: Path, dims_mm):
    """A closed binary STL box (12 triangles)."""
    import struct
    x, y, z = dims_mm
    v = [(0, 0, 0), (x, 0, 0), (x, y, 0), (0, y, 0), (0, 0, z), (x, 0, z), (x, y, z), (0, y, z)]
    f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    with open(path, "wb") as fh:
        fh.write(b"\0" * 80 + struct.pack("<I", len(f)))
        for a_, b_, c_ in f:
            fh.write(struct.pack("<12fH", 0, 0, 0, *v[a_], *v[b_], *v[c_], 0))


def seed_scorable(part, *, stl_dims_in=(6.0, 4.0, 0.5), overall=(6.0, 4.0, 0.5)):
    """A part folder with an extraction, a build record and a real exported mesh (inches -> mm)."""
    out = appmod.FINAL_OUTPUTS_DIR / part
    out.mkdir(parents=True, exist_ok=True)
    (out / "x_ir.SLDPRT").write_bytes(b"sldprt")
    box_stl(out / "x_ir.STL", [v * 25.4 for v in stl_dims_in])
    (out / f"{part}_extraction.json").write_text(json.dumps({
        "units": "inch", "confidence": 0.95, "warnings": [], "features": [{"id": "F001", "type": "extrude_boss"}],
        "dimensions": [{"id": f"D00{i}", "type": "linear", "value": v, "applies_to": n, "feature_ref": "F001", "tolerance_plus": 0.01, "tolerance_minus": 0.01}
                       for i, (n, v) in enumerate(zip(("overall_length", "overall_width", "plate_thickness"), overall), 1)], "hole_callouts": []}))
    (out / "ir_report.json").write_text(json.dumps({"sw_ok": True, "sw_features": {"F001": "built"}, "defaults": [], "questions": [], "flagged": []}))
    (out / "feature_map.json").write_text(json.dumps({"units": "inch", "bbox": [0, 0, 0, *overall]}))
    return out


def test_evaluate_scores_the_real_part_and_keeps_every_evaluation():
    seed_scorable("FID1")
    r = client.post("/api/scoring/evaluate", json={"parts": ["FID1", "DOES_NOT_EXIST"]}).json()
    by = {x["part"]: x for x in r["results"]}
    assert by["DOES_NOT_EXIST"]["state"] == "no_output"
    assert by["FID1"]["state"] == "scored" and by["FID1"]["score"] >= 90 and by["FID1"]["band"] == "green"
    client.post("/api/scoring/evaluate", json={"parts": ["FID1"]})
    d = client.get("/api/scoring/parts/FID1").json()
    assert len(d["history"]) == 2 and d["latest"]["rubric"]["id"] == "emf"                       # appended, never overwritten
    cats = {c["id"]: c for c in d["latest"]["categories"]}
    assert cats["envelope"]["score"] == 100 and cats["envelope"]["items"][0]["measured"] is not None


def test_a_stale_stl_is_red_with_a_critical_issue_through_the_api():
    seed_scorable("FID2")
    box_stl(appmod.FINAL_OUTPUTS_DIR / "FID2" / "x_ir.STL", [4.375 * 25.4, 5.0 * 25.4, 2.25 * 25.4])     # another part's mesh
    client.post("/api/scoring/evaluate", json={"parts": ["FID2"]})
    row = next(r for r in client.get("/api/scoring").json()["parts"] if r["part"] == "FID2")
    assert row["state"] == "scored" and row["band"]["id"] == "red" and row["score"] <= 49.9
    assert row["counts"]["critical"] >= 1 and row["caps"]
    latest = client.get("/api/scoring/parts/FID2").json()["latest"]
    assert any(i["code"] == "STL_NOT_THIS_BUILD" and i["severity"] == "critical" for i in latest["issues"])


def test_a_pipeline_written_score_is_ingested_once():
    out = seed_scorable("FID3")
    import subprocess
    subprocess.run([sys.executable, "-m", "bench.fidelity", str(out)], cwd=str(REPO), check=True, capture_output=True, env={**os.environ, "PYTHONUTF8": "1"})
    assert (out / "fidelity_score.json").is_file()
    for _ in range(3):
        client.get("/api/scoring")
    assert len(client.get("/api/scoring/parts/FID3").json()["history"]) == 1


def test_missing_evidence_is_incomplete_and_a_failed_build_is_its_own_state():
    out = seed_scorable("FID4")
    (out / "x_ir.STL").unlink()
    (appmod.FINAL_OUTPUTS_DIR / "FID5").mkdir(parents=True, exist_ok=True)
    seed_scorable("FID5")
    (appmod.FINAL_OUTPUTS_DIR / "FID5" / "ir_report.json").write_text(json.dumps({"sw_ok": False, "sw_features": {}}))
    client.post("/api/scoring/evaluate", json={"parts": ["FID4", "FID5"]})
    rows = {r["part"]: r for r in client.get("/api/scoring").json()["parts"]}
    assert rows["FID4"]["state"] == "incomplete" and rows["FID4"]["reason"] == "no_mesh" and rows["FID4"]["score"] is None
    assert rows["FID5"]["state"] == "no_model" and rows["FID5"]["score"] is None


def test_overview_summary_counts_bands_and_averages_scored_parts_only():
    seed_scorable("FID6")
    client.post("/api/scoring/evaluate", json={"parts": ["FID6"]})
    ov = client.get("/api/scoring").json()
    s = ov["summary"]
    assert s["scored"] >= 1 and 0 <= s["average"] <= 100 and set(s["distribution"]) == {"green", "amber", "orange", "red"}
    assert sum(s["distribution"].values()) == s["scored"]
    assert ov["rubric"] == "Extraction-to-Model Fidelity" and ov["version"].startswith("emf-")


def test_methodology_endpoint_describes_the_fidelity_rubric_and_its_example():
    m = client.get("/api/scoring/methodology").json()
    meth, ex = m["methodology"], m["example"]
    assert meth["total_possible"] == 100 and sum(c["weight"] for c in meth["categories"]) == 100
    assert [b["id"] for b in meth["bands"]] == ["green", "amber", "orange", "red"]
    assert ex["illustrative"] is True and "not a measured part" in ex["label"]
    assert ex["cases"][0]["score"] == 100
    assert m["benchmark"] is None or m["benchmark"]["methodology"]["total_possible"] == 100


def test_many_parallel_pdf_requests_never_crash_the_server_process():
    """The browser asks for a preview and a page count of every part at once. MuPDF is not thread-safe, so the server serialises it;
    without that a burst over malformed PDFs killed the whole process (found by the browser tests)."""
    from concurrent.futures import ThreadPoolExecutor
    names = []
    for i in range(6):
        n = f"Par{i}"
        add_part(n, pdf_pages=2)
        names.append(n)
    for i in range(6):
        n = f"Bad{i}"
        add_part(n)
        (appmod._session_dir(SESSION) / appmod.ORIGINALS_DIRNAME / f"{n}.pdf").write_bytes(b"%PDF-1.4 x" if i % 2 else b"%PDF-1.4 corrupt " + bytes(range(60)))
        names.append(n)

    def hit(n):
        a = client.get(f"/api/parts/{SESSION}/{n}/preview.png").status_code
        b = client.get("/api/estimate", params={"session": SESSION, "parts": [n]}).status_code
        return a, b
    with ThreadPoolExecutor(max_workers=16) as ex:
        results = list(ex.map(hit, names * 4))
    assert all(a in (200, 204) and b == 200 for a, b in results)
