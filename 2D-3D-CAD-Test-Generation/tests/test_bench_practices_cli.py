"""bench.score with the practices column (spec 2b, task 2): cached feature_tree.json, no SolidWorks."""
import json
import os
import time

import pytest

cq = pytest.importorskip("cadquery")
from bench import keygen, report, score, sw_tasks, sw_tree  # noqa: E402

HOLES = [(-20, -10), (20, -10)]
GOOD_TREE = [
    {"name": "Origin", "type": "OriginProfileFeature", "index": 0, "status": None, "subs": []},
    {"name": "Boss-Extrude1", "type": "Extrusion", "index": 1, "status": None,
     "subs": [{"name": "Sketch1", "type": "ProfileFeature", "status": 3}]},
    {"name": "Cut-Extrude1", "type": "Cut", "index": 2, "status": None,
     "subs": [{"name": "Sketch2", "type": "ProfileFeature", "status": 3}]},
    {"name": "Fillet1", "type": "Fillet", "index": 3, "status": None, "subs": []},
]
BAD_TREE = [GOOD_TREE[0], GOOD_TREE[1], GOOD_TREE[3],
            {"name": "Cut-Extrude1", "type": "Cut", "index": 3, "status": None,
             "subs": [{"name": "Sketch2", "type": "ProfileFeature", "status": 2}]}]


def _plate(d, name, holes):
    p = d / name
    cq.Workplane().box(60, 40, 10).faces(">Z").workplane().pushPoints(holes).hole(8.0).val().exportStep(str(p))
    return p


def _part(run, keys, part, tree=None, sldprt=False, ir=None):
    (run / part).mkdir(parents=True)
    (keys / part).mkdir(parents=True)
    k = keygen.from_step(_plate(keys / part, "ref.step", HOLES), units="mm", part=part)
    k.signoff = {"kind": "auto", "by": "test", "date": "2026-10-25"}
    k.save(keys / part / "key.json")
    d = run / part
    if sldprt:
        sld = d / f"{part}_ir.SLDPRT"
        sld.write_bytes(b"sldprt")
        old = time.time() - 100
        os.utime(sld, (old, old))
    _plate(d, "generated.step", HOLES)
    if tree is not None:
        (d / sw_tree.CACHE).write_text(json.dumps(tree), encoding="utf-8")
    if ir is not None:
        (d / "ir_report.json").write_text(json.dumps(ir), encoding="utf-8")
    return d


def _out(run):
    return json.loads((run / "scores.json").read_text(encoding="utf-8"))


def test_practices_column_from_cached_tree(tmp_path, monkeypatch):
    run, keys = tmp_path / "run", tmp_path / "keys"
    _part(run, keys, "PA", GOOD_TREE, sldprt=True, ir={"conventions": ["origin centered: True"]})
    _part(run, keys, "PB", BAD_TREE, sldprt=True)
    monkeypatch.setattr(sw_tasks, "connect", lambda *a, **k: pytest.fail("SolidWorks must not be needed"))
    assert score.main([str(run), "--keys-dir", str(keys)]) == 0
    out = _out(run)
    by = {p["part"]: p for p in out["parts"]}
    assert by["PA"]["score"] == pytest.approx(100.0) and by["PB"]["score"] == pytest.approx(100.0)  # geometry unchanged
    pa, pb = by["PA"]["practices"], by["PB"]["practices"]
    assert pa["checked"] and pa["score"] == pytest.approx(100.0)
    rows = {r["id"]: r for r in pb["rows"]}
    assert rows["C4"]["credit"] == 0.0 and rows["C4"]["reason"] == "Fillet1 before Cut-Extrude1"
    assert rows["C3"]["credit"] == pytest.approx(0.5)
    assert pb["score"] == pytest.approx(100 * 1.5 / 3)                     # C3 0.5, C4 0, C7 1
    assert out["summary"]["practices_mean"] == pytest.approx((100 + 50) / 2)
    assert out["summary"]["mean"] == pytest.approx(100.0)                   # never blended
    html = (run / "report.html").read_text(encoding="utf-8")
    assert "practices" in html and "Fillet1 before Cut-Extrude1" in html and "self-reported" in html


def test_no_sw_without_cache_marks_not_checked(tmp_path):
    run, keys = tmp_path / "run", tmp_path / "keys"
    _part(run, keys, "PC", None, sldprt=True, ir={"conventions": ["origin centered: False"]})
    assert score.main([str(run), "--keys-dir", str(keys), "--no-sw"]) == 0
    p = _out(run)["parts"][0]["practices"]
    rows = {r["id"]: r for r in p["rows"]}
    assert not p["checked"]
    assert all(not rows[c]["applicable"] and "not checked" in rows[c]["reason"] for c in ("C3", "C4", "C5", "C7"))
    assert p["score"] == 0.0 and rows["C1"]["stage"] == "solidworks"
    assert "not checked" in (run / "report.html").read_text(encoding="utf-8")


def test_no_sw_with_stale_cache_is_used_and_flagged(tmp_path):
    run, keys = tmp_path / "run", tmp_path / "keys"
    d = _part(run, keys, "PD", GOOD_TREE, sldprt=True)
    old = time.time() - 200
    os.utime(d / sw_tree.CACHE, (old, old))
    assert score.main([str(run), "--keys-dir", str(keys), "--no-sw"]) == 0
    p = _out(run)["parts"][0]["practices"]
    assert p["checked"] and "stale" in p["note"]


def test_tree_read_in_the_export_pass(tmp_path, monkeypatch):
    run, keys = tmp_path / "run", tmp_path / "keys"
    d = _part(run, keys, "PE", None)
    (d / "generated.step").unlink()
    (d / "PE_ir.SLDPRT").write_bytes(b"sldprt")
    monkeypatch.setattr(sw_tasks, "connect", lambda *a, **k: "APP")
    monkeypatch.setattr(sw_tasks, "sldprt_to_step", lambda app, s, out, png: _plate(out.parent, out.name, HOLES))
    reads = []

    def read(app, sld):
        reads.append((app, sld.name))
        return GOOD_TREE

    monkeypatch.setattr(sw_tree, "read_tree", read)
    assert score.main([str(run), "--keys-dir", str(keys)]) == 0
    assert reads == [("APP", "PE_ir.SLDPRT")]
    assert json.loads((d / sw_tree.CACHE).read_text(encoding="utf-8")) == GOOD_TREE
    assert _out(run)["parts"][0]["practices"]["checked"]


def test_tree_only_need_connects_best_effort(tmp_path, monkeypatch):
    run, keys = tmp_path / "run", tmp_path / "keys"
    _part(run, keys, "PF", None, sldprt=True)                 # STEP fresh, no tree cache

    def boom(*a, **k):
        raise sw_tasks.SwUnavailable("no SolidWorks")

    monkeypatch.setattr(sw_tasks, "connect", boom)
    assert score.main([str(run), "--keys-dir", str(keys)]) == 0   # not exit 3: only the tree needed SW
    p = _out(run)["parts"][0]
    assert p["score"] == pytest.approx(100.0) and not p["practices"]["checked"]
    assert "SolidWorks" in p["practices"]["note"]


def test_tree_read_failure_is_not_an_error_row(tmp_path, monkeypatch):
    run, keys = tmp_path / "run", tmp_path / "keys"
    _part(run, keys, "PG", None, sldprt=True)
    monkeypatch.setattr(sw_tasks, "connect", lambda *a, **k: "APP")
    monkeypatch.setattr(sw_tree, "read_tree", lambda app, s: (_ for _ in ()).throw(RuntimeError("COM died")))
    assert score.main([str(run), "--keys-dir", str(keys)]) == 0
    p = _out(run)["parts"][0]
    assert not p.get("error") and not p["practices"]["checked"] and "COM died" in p["practices"]["note"]


def test_report_practices_escapes(tmp_path):
    results = [{"part": "P", "score": 50.0, "exact": False, "error": None, "rows": [], "extras": [], "blame": {},
                "drawing_only": [], "practices": {"score": 0.0, "checked": True, "note": "<b>n</b>", "rows": [
                    {"id": "C7", "name": "no avoided features", "credit": 0.0, "applicable": True,
                     "source": "sldprt", "stage": "solidworks", "reason": "<script>x</script>"}]}}]
    summary = {"n_scored": 1, "mean": 50.0, "median": 50.0, "exact_rate": 0.0, "errors": [],
               "practices_mean": 0.0, "rollup": {"by_stage": {}, "by_type": {}, "by_tier": {}}}
    report.write_html(tmp_path / "r.html", results, summary)
    html = (tmp_path / "r.html").read_text(encoding="utf-8")
    assert "<script>" not in html and "&lt;script&gt;" in html and "&lt;b&gt;" in html
