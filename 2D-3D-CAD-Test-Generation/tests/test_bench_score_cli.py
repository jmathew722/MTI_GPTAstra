"""bench.score CLI end-to-end on tiny CadQuery parts (no SolidWorks)."""
import json
import os
import time

import pytest

cq = pytest.importorskip("cadquery")
from bench import keygen, report, score, sw_tasks  # noqa: E402


def _plate(tmp, name, holes):
    wp = cq.Workplane().box(60, 40, 10).faces(">Z").workplane().pushPoints(holes).hole(8.0)
    p = tmp / name
    wp.val().exportStep(str(p))
    return p


def _signed_key(keys, part, holes=((-20, -10), (20, -10))):
    (keys / part).mkdir(parents=True)
    ref = _plate(keys / part, "ref.step", list(holes))
    k = keygen.from_step(ref, units="mm", part=part)
    k.signoff = {"kind": "auto", "by": "test", "date": "2026-10-24"}
    k.save(keys / part / "key.json")
    return k


def _out(run):
    return json.loads((run / "scores.json").read_text(encoding="utf-8"))


def test_cli_identity_and_planted_error(tmp_path):
    run, keys = tmp_path / "run", tmp_path / "keys"
    for part, gen_holes in (("PA", [(-20, -10), (20, -10)]), ("PB", [(-20, -10), (21.0, -10)])):
        (run / part).mkdir(parents=True)
        _signed_key(keys, part)
        _plate(run / part, "generated.step", gen_holes)
        _plate(run / part, "reference.step", gen_holes)
    assert score.main([str(run), "--keys-dir", str(keys), "--no-sw"]) == 0
    out = _out(run)
    by = {p["part"]: p for p in out["parts"]}
    assert by["PA"]["score"] == pytest.approx(100.0) and by["PA"]["exact"]
    assert by["PB"]["score"] < 100.0 and not by["PB"]["exact"]
    assert any(b["stage"] == "planner" for b in by["PB"]["blame"].values())   # CQ reference has the error too
    assert len(by["PA"]["pose_rotation"]) == 3 and len(by["PA"]["pose_translation"]) == 3
    s = out["summary"]
    assert s["n_scored"] == 2 and s["exact_rate"] == pytest.approx(0.5)
    assert s["mean"] == pytest.approx((by["PA"]["score"] + by["PB"]["score"]) / 2)
    assert s["rollup"]["by_stage"]["planner"] > 0
    html = (run / "report.html").read_text(encoding="utf-8")
    assert html.count("PB") >= 1 and "planner" in html


def test_cli_skips_unsigned_and_handles_missing_generated(tmp_path):
    run, keys = tmp_path / "run", tmp_path / "keys"
    (run / "PC").mkdir(parents=True)
    (keys / "PC").mkdir(parents=True)
    ref = _plate(keys / "PC", "ref.step", [(0, 0)])
    k = keygen.from_step(ref, units="mm", part="PC")
    k.save(keys / "PC" / "key.json")                     # unsigned
    assert score.main([str(run), "--keys-dir", str(keys), "--no-sw"]) in (0, 2)
    out = _out(run)
    assert "PC" in out["skipped_unsigned"]


def test_no_generated_part_scores_zero_with_blame_from_ir_report(tmp_path):
    run, keys = tmp_path / "run", tmp_path / "keys"
    for part, rep in (("PD", {"cq_skipped": {}, "sw_ok": False, "error": "SW crashed", "planned": 3}),
                      ("PE", {"cq_skipped": {"F002": "failed: StdFail_NotDone"}, "planned": 3}),
                      ("PF", None)):
        (run / part).mkdir(parents=True)
        _signed_key(keys, part)
        if rep is not None:
            (run / part / "ir_report.json").write_text(json.dumps(rep), encoding="utf-8")
            (run / part / "plan.json").write_text("{}", encoding="utf-8")
    assert score.main([str(run), "--keys-dir", str(keys), "--no-sw"]) == 0
    by = {p["part"]: p for p in _out(run)["parts"]}
    for part, stage in (("PD", "solidworks"), ("PE", "cadquery"), ("PF", "planner")):
        p = by[part]
        assert p["score"] == 0.0 and not p["exact"]
        assert all(r["status"] == "missing" for r in p["rows"])
        assert {b["stage"] for b in p["blame"].values()} == {stage}, part
    assert "SW crashed" in by["PD"]["blame"]["BASE"]["reason"]


def test_unreadable_step_is_an_error_row(tmp_path):
    run, keys = tmp_path / "run", tmp_path / "keys"
    (run / "PG").mkdir(parents=True)
    _signed_key(keys, "PG")
    (run / "PG" / "generated.step").write_text("not a step file", encoding="utf-8")
    assert score.main([str(run), "--keys-dir", str(keys), "--no-sw"]) == 1
    out = _out(run)
    p = out["parts"][0]
    assert p["part"] == "PG" and p["error"] and p["score"] is None
    assert out["summary"]["errors"] == ["PG"]


def test_multi_body_scores_largest_and_counts_others_as_extras(tmp_path):
    run, keys = tmp_path / "run", tmp_path / "keys"
    (run / "PM").mkdir(parents=True)
    _signed_key(keys, "PM")
    plate = cq.Workplane().box(60, 40, 10).faces(">Z").workplane().pushPoints([(-20, -10), (20, -10)]).hole(8.0)
    stray = cq.Workplane().box(10, 10, 10).faces(">Z").workplane().hole(3.0).translate((100, 0, 0))
    cq.Compound.makeCompound([plate.val(), stray.val()]).exportStep(str(run / "PM" / "generated.step"))
    plate.val().exportStep(str(run / "PM" / "reference.step"))
    assert score.main([str(run), "--keys-dir", str(keys), "--no-sw"]) == 0
    p = _out(run)["parts"][0]
    assert p["multi_body"] == 2
    assert p["extras"] and all(e["feature_id"].startswith("B2:") for e in p["extras"])
    assert p["score"] < 100.0 and not p["exact"]
    assert all(r["credit"] == pytest.approx(1.0) for r in p["rows"])           # the plate itself is right
    assert any(k.startswith("extra:B2:") and b["stage"] == "solidworks" for k, b in p["blame"].items())


def test_sldprt_export_needs_solidworks(tmp_path, monkeypatch):
    run, keys = tmp_path / "run", tmp_path / "keys"
    (run / "PH").mkdir(parents=True)
    _signed_key(keys, "PH")
    (run / "PH" / "PH_ir.SLDPRT").write_bytes(b"sldprt")

    def boom(*a, **k):
        raise sw_tasks.SwUnavailable("no SolidWorks")

    monkeypatch.setattr(sw_tasks, "connect", boom)
    assert score.main([str(run), "--keys-dir", str(keys)]) == 3
    assert not (run / "scores.json").exists()


def test_fresh_generated_step_skips_export(tmp_path, monkeypatch):
    run, keys = tmp_path / "run", tmp_path / "keys"
    (run / "PI").mkdir(parents=True)
    _signed_key(keys, "PI")
    sld = run / "PI" / "PI_ir.SLDPRT"
    sld.write_bytes(b"sldprt")
    old = time.time() - 100
    os.utime(sld, (old, old))
    _plate(run / "PI", "generated.step", [(-20, -10), (20, -10)])
    _plate(run / "PI", "reference.step", [(-20, -10), (20, -10)])
    monkeypatch.setattr(sw_tasks, "connect", lambda *a, **k: pytest.fail("SolidWorks must not be needed"))
    assert score.main([str(run), "--keys-dir", str(keys)]) == 0
    assert _out(run)["parts"][0]["score"] == pytest.approx(100.0)


def test_sldprt_export_with_fake_solidworks(tmp_path, monkeypatch):
    run, keys = tmp_path / "run", tmp_path / "keys"
    (run / "PJ").mkdir(parents=True)
    _signed_key(keys, "PJ")
    (run / "PJ" / "PJ_ir.SLDPRT").write_bytes(b"sldprt")
    _plate(run / "PJ", "reference.step", [(-20, -10), (20, -10)])
    calls = []
    monkeypatch.setattr(sw_tasks, "connect", lambda *a, **k: "APP")

    def export(app, sldprt, out_step, out_png):
        calls.append((app, sldprt.name))
        _plate(out_step.parent, out_step.name, [(-20, -10), (20, -10)])

    monkeypatch.setattr(sw_tasks, "sldprt_to_step", export)
    assert score.main([str(run), "--keys-dir", str(keys)]) == 0
    assert calls == [("APP", "PJ_ir.SLDPRT")]
    assert _out(run)["parts"][0]["score"] == pytest.approx(100.0)


def test_no_parts_exits_2(tmp_path):
    (tmp_path / "run").mkdir()
    (tmp_path / "keys").mkdir()
    assert score.main([str(tmp_path / "run"), "--keys-dir", str(tmp_path / "keys"), "--no-sw"]) == 2
    assert score.main([str(tmp_path / "nope"), "--keys-dir", str(tmp_path / "keys"), "--no-sw"]) == 2


def test_report_html_escapes(tmp_path):
    results = [{"part": "<P&1>", "score": 50.0, "exact": False, "error": None,
                "rows": [{"feature_id": "K<1>", "type": "thru_hole", "tier_weight": 3, "weight": 1.0,
                          "status": "missing", "matched_id": None, "errors": {"size": [float("inf"), float("inf")]},
                          "attr_credits": {}, "credit": 0.0, "points_lost": 50.0, "blame": "planner",
                          "reason": "<script>x</script>"}],
                "extras": [], "blame": {}, "drawing_only": ["linear <0.3>"]}]
    summary = {"n_scored": 1, "mean": 50.0, "median": 50.0, "exact_rate": 0.0, "errors": [],
               "rollup": {"by_stage": {"planner": 50.0}, "by_type": {}, "by_tier": {}}}
    report.write_html(tmp_path / "r.html", results, summary)
    html = (tmp_path / "r.html").read_text(encoding="utf-8")
    assert "<script>" not in html and "&lt;P&amp;1&gt;" in html and "&lt;script&gt;" in html
    assert "http" not in html                                    # self-contained
    report.write_json(tmp_path / "s.json", results, summary)
    data = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))   # strict JSON: no Infinity
    assert data["parts"][0]["rows"][0]["errors"]["size"] == ["inf", "inf"]
