"""Extraction-to-Model Fidelity rubric (bench/fidelity.py): real meshes (CadQuery -> STL), no SolidWorks, no API."""
from __future__ import annotations

import json
import time

import pytest

cq = pytest.importorskip("cadquery")
np = pytest.importorskip("numpy")

from bench import fidelity as fx  # noqa: E402

CFG = fx.load_config()
IN = 25.4


def plate(holes=((1.0, 1.0), (5.0, 1.0), (1.0, 3.0), (5.0, 3.0)), d=0.344, size=(6.0, 4.0, 0.5), cbore=None, blind=None, skip=()):
    """A plate in inches built in mm, with Z-axis holes. Holes: through, optionally counterbored or blind."""
    L, W, T = [v * IN for v in size]
    p = cq.Workplane("XY").box(L, W, T, centered=False)
    for k, (x, y) in enumerate(holes):
        if k in skip:
            continue
        pts = [(x * IN, y * IN)]
        if blind:
            p = p.faces(">Z").workplane(origin=(0, 0, T)).pushPoints(pts).hole(d * IN, blind * IN)
        else:
            p = p.faces(">Z").workplane(origin=(0, 0, T)).pushPoints(pts).hole(d * IN)
        if cbore:
            p = p.faces(">Z").workplane(origin=(0, 0, T)).pushPoints(pts).cboreHole(d * IN, cbore[0] * IN, cbore[1] * IN) if False else p
    return p


def write_part(tmp_path, solid, *, extraction=None, report=None, fmap=None, stl_from=None, name="PLATE"):
    d = tmp_path / name
    d.mkdir()
    (d / "x_ir.SLDPRT").write_bytes(b"sldprt")
    cq.exporters.export(stl_from if stl_from is not None else solid, str(d / "x_ir.STL"), exportType="STL", tolerance=0.001, angularTolerance=0.05)
    bb = solid.val().BoundingBox()
    ext = extraction or {
        "units": "inch", "confidence": 0.95, "warnings": [], "features": [{"id": "F001", "type": "extrude_boss", "description": "plate"}, {"id": "F002", "type": "hole", "description": "4 holes"}],
        "dimensions": [{"id": "D001", "type": "linear", "value": 6.0, "applies_to": "overall_length", "feature_ref": "F001", "tolerance_plus": 0.01, "tolerance_minus": 0.01},
                       {"id": "D002", "type": "linear", "value": 4.0, "applies_to": "overall_width", "feature_ref": "F001", "tolerance_plus": 0.01, "tolerance_minus": 0.01},
                       {"id": "D003", "type": "linear", "value": 0.5, "applies_to": "plate_thickness", "feature_ref": "F001", "tolerance_plus": 0.01, "tolerance_minus": 0.01}],
        "hole_callouts": [{"id": "H001", "type": "thru", "diameter": 0.344, "thru": True, "depth": 0.0, "qty": 4, "position_known": True, "pattern": "linear",
                           "instance_positions": [[1.0, 1.0], [5.0, 1.0], [1.0, 3.0], [5.0, 3.0]]}]}
    (d / "x_extraction.json").write_text(json.dumps(ext))
    (d / "ir_report.json").write_text(json.dumps(report or {"sw_ok": True, "sw_features": {"F001": "built", "F002": "built"}, "defaults": [], "questions": [], "flagged": []}))
    (d / "feature_map.json").write_text(json.dumps(fmap or {"units": "inch", "bbox": [0, 0, 0, 6, 4, 0.5], "volume": solid.val().Volume() / IN ** 3}))
    return d


def codes(r):
    return {i["code"] for i in r["issues"]}


def test_config_is_consistent():
    assert sum(c["weight"] for c in CFG["categories"].values()) == 100
    assert sum(CFG["integrity_checks"].values()) == CFG["categories"]["model_integrity"]["weight"]
    assert sum(CFG["trust_checks"].values()) == CFG["categories"]["extraction_trust"]["weight"]
    assert fx.fingerprint().startswith("emf-") and fx.fingerprint() == fx.fingerprint()
    mins = [b["min"] for b in CFG["bands"]]
    assert mins == sorted(mins, reverse=True) and mins[-1] == 0


def test_bands_boundaries_are_inclusive():
    assert [fx.band_of(s, CFG)["id"] for s in (100, 90, 89.9, 75, 74.9, 60, 59.9, 0)] == ["green", "green", "amber", "amber", "orange", "orange", "red", "red"]
    assert fx.band_of(None, CFG)["id"] == "none"


def test_credit_curve():
    assert fx.credit(0.005, 0.005, CFG) == 1.0 and fx.credit(0.0, 0.0, CFG) == 1.0
    assert fx.credit(0.010, 0.005, CFG) == pytest.approx(0.4, abs=0.001)
    assert fx.credit(0.05, 0.005, CFG) < 0.07


def test_a_faithful_model_scores_green(tmp_path):
    r = fx.evaluate_dir(write_part(tmp_path, plate()))
    assert r["state"] == "scored" and r["score"] >= 98 and r["band"]["id"] == "green"
    assert not [i for i in r["issues"] if i["severity"] in ("critical", "high")]
    cats = {c["id"]: c for c in r["categories"]}
    assert cats["envelope"]["score"] == 100 and cats["hole_accuracy"]["score"] == 100 and cats["placement"]["score"] == 100
    assert r["coverage"] == 1.0 and len(r["measured"]["holes"]) == 4


def test_a_wrong_hole_diameter_costs_points_and_is_reported(tmp_path):
    r = fx.evaluate_dir(write_part(tmp_path, plate(d=0.40)))
    assert "HOLE_DIAMETER" in codes(r)
    h = next(c for c in r["categories"] if c["id"] == "hole_accuracy")
    assert h["score"] < 70
    assert r["score"] < fx.evaluate_dir(write_part(tmp_path, plate(), name="OK"))["score"]


def test_a_missing_hole_is_high_severity(tmp_path):
    r = fx.evaluate_dir(write_part(tmp_path, plate(skip=(3,))))
    assert "HOLE_MISSING" in codes(r)
    assert next(i for i in r["issues"] if i["code"] == "HOLE_MISSING")["severity"] == "high"
    assert next(c for c in r["categories"] if c["id"] == "hole_accuracy")["score"] == pytest.approx(75, abs=1)


def test_a_wrong_pattern_pitch_is_caught_without_any_frame(tmp_path):
    r = fx.evaluate_dir(write_part(tmp_path, plate(holes=((1.0, 1.0), (5.0, 1.0), (1.0, 3.0), (4.5, 3.0)))))
    assert "PATTERN_SPACING" in codes(r)
    assert next(c for c in r["categories"] if c["id"] == "placement")["score"] < 100


def test_a_blind_hole_where_a_through_hole_was_called_out(tmp_path):
    r = fx.evaluate_dir(write_part(tmp_path, plate(blind=0.25)))
    assert "HOLE_NOT_THROUGH" in codes(r)


def test_overall_size_deviation_and_the_critical_cap(tmp_path):
    r = fx.evaluate_dir(write_part(tmp_path, plate(size=(7.0, 4.0, 0.5)), fmap={"units": "inch", "bbox": [0, 0, 0, 7, 4, 0.5]}))
    assert "ENVELOPE_OFF" in codes(r)
    assert r["score"] <= CFG["gates"]["critical_cap"] and r["band"]["id"] == "red" and r["caps"]


def test_a_stale_or_wrong_stl_is_critical(tmp_path):
    other = plate(size=(4.375, 5.0, 2.25))                                    # a different part's mesh
    r = fx.evaluate_dir(write_part(tmp_path, plate(), stl_from=other))
    assert "STL_NOT_THIS_BUILD" in codes(r)
    assert r["score"] <= CFG["gates"]["critical_cap"] and r["band"]["id"] == "red"
    assert next(i for i in r["issues"] if i["code"] == "STL_NOT_THIS_BUILD")["severity"] == "critical"


def test_an_stl_older_than_the_sldprt_is_stale(tmp_path):
    d = write_part(tmp_path, plate())
    import os
    old = time.time() - 600
    os.utime(d / "x_ir.STL", (old, old))
    assert "STL_NOT_THIS_BUILD" in codes(fx.evaluate_dir(d))


def test_missing_evidence_is_incomplete_never_zero(tmp_path):
    d = write_part(tmp_path, plate())
    (d / "x_ir.STL").unlink()
    r = fx.evaluate_dir(d)
    assert r["state"] == "incomplete" and r["score"] is None and r["reason"] == "no_mesh"
    d2 = write_part(tmp_path, plate(), name="P2")
    (d2 / "x_extraction.json").unlink()
    r2 = fx.evaluate_dir(d2)
    assert r2["state"] == "incomplete" and r2["score"] is None and r2["reason"] == "no_extraction"


def test_a_failed_build_is_no_model_not_a_score(tmp_path):
    d = write_part(tmp_path, plate(), report={"sw_ok": False, "sw_features": {}})
    r = fx.evaluate_dir(d)
    assert r["state"] == "no_model" and r["score"] is None
    assert r["issues"][0]["severity"] == "critical"


def test_a_placeholder_callout_is_not_scored_and_its_holes_are_not_extras(tmp_path):
    ext = {"units": "inch", "confidence": 0.9, "features": [{"id": "F001", "type": "extrude_boss"}],
           "warnings": ["H002 diameter=0.500 is ONLY a placeholder and must NOT drive a build."],
           "dimensions": [{"id": "D001", "type": "linear", "value": 6.0, "applies_to": "overall_length", "feature_ref": "F001"},
                          {"id": "D002", "type": "linear", "value": 4.0, "applies_to": "overall_width", "feature_ref": "F001"}],
           "hole_callouts": [{"id": "H002", "type": "thru", "diameter": 0.5, "thru": True, "qty": 4, "position_known": True}]}
    r = fx.evaluate_dir(write_part(tmp_path, plate(), extraction=ext, report={"sw_ok": True, "sw_features": {"F001": "built"}}))
    assert "CALLOUT_NOT_SCORABLE" in codes(r) and "HOLE_EXTRA" not in codes(r)
    assert not any(c["id"] == "hole_accuracy" and c["checked"] for c in r["categories"])


def test_unbuilt_and_unresolved_features_are_reported(tmp_path):
    ext = json.loads(json.dumps({"units": "inch", "confidence": 0.9, "warnings": [], "features": [
        {"id": "F001", "type": "extrude_boss"}, {"id": "F002", "type": "hole"}, {"id": "F003", "type": "fillet"}],
        "dimensions": [], "hole_callouts": []}))
    rep = {"sw_ok": True, "sw_features": {"F001": "built", "F002": "skipped"}, "questions": ["F003: which edges?"], "flagged": [], "defaults": []}
    r = fx.evaluate_dir(write_part(tmp_path, plate(), extraction=ext, report=rep))
    assert {"FEATURE_SKIPPED", "FEATURE_UNRESOLVED"} <= codes(r)
    cov = next(c for c in r["categories"] if c["id"] == "feature_coverage")
    assert cov["score"] < 70


def test_extraction_trust_penalises_low_confidence_and_assumptions(tmp_path):
    ext = {"units": "inch", "confidence": 0.55, "warnings": ["POSITION ASSUMED for F002"], "features": [{"id": "F001", "type": "extrude_boss"}],
           "dimensions": [{"id": "D001", "type": "linear", "value": 6.0, "applies_to": "overall_length", "feature_ref": "F001", "value_unclear": True},
                          {"id": "D002", "type": "linear", "value": 4.0, "applies_to": "overall_width", "feature_ref": "F001"}], "hole_callouts": []}
    rep = {"sw_ok": True, "sw_features": {"F001": "built"}, "defaults": ["D7 default"], "questions": ["q?"], "flagged": []}
    r = fx.evaluate_dir(write_part(tmp_path, plate(), extraction=ext, report=rep))
    assert {"LOW_CONFIDENCE", "POSITION_ASSUMED", "DEFAULTS_APPLIED", "OPEN_QUESTIONS"} <= codes(r)
    assert next(c for c in r["categories"] if c["id"] == "extraction_trust")["score"] < 40


def test_aggregate_rescales_over_the_categories_that_could_be_checked():
    item = lambda w, c: {"id": "i", "label": "i", "weight": w, "credit": c}   # noqa: E731
    full = {k: [item(1, 1.0)] for k in fx.CAT_ORDER}
    assert fx.aggregate(full, [], CFG)["score"] == 100 and fx.aggregate(full, [], CFG)["coverage"] == 1.0
    half = {**full, "placement": [], "hole_accuracy": [], "envelope": [item(1, 0.0)]}
    r = fx.aggregate(half, [], CFG)
    assert r["coverage"] == pytest.approx(0.65)
    assert r["score"] == pytest.approx(100 * (15 + 20 + 10) / 65, abs=0.2)                # envelope (20) earns nothing
    assert fx.aggregate({k: [] for k in fx.CAT_ORDER}, [], CFG)["score"] is None


def test_low_coverage_gives_no_score(tmp_path):
    ext = {"units": "inch", "confidence": 0.95, "warnings": [], "features": [], "dimensions": [], "hole_callouts": []}
    r = fx.evaluate_dir(write_part(tmp_path, plate(), extraction=ext))
    assert r["state"] == "incomplete" and r["score"] is None and r["reason"] == "low_coverage"


def test_hole_detection_reads_counterbore_blind_and_through():
    p = cq.Workplane("XY").box(2 * IN, 2 * IN, 1 * IN, centered=False)
    p = p.faces(">Z").workplane(origin=(0, 0, 1 * IN)).pushPoints([(0.5 * IN, 0.5 * IN)]).cboreHole(0.25 * IN, 0.5 * IN, 0.25 * IN)
    p = p.faces(">Z").workplane(origin=(0, 0, 1 * IN)).pushPoints([(1.5 * IN, 1.5 * IN)]).hole(0.3 * IN, 0.5 * IN)
    p = p.faces(">Z").workplane(origin=(0, 0, 1 * IN)).pushPoints([(1.5 * IN, 0.5 * IN)]).circle(0.1 * IN).extrude(0.2 * IN)   # a boss, not a hole
    import tempfile, pathlib
    f = pathlib.Path(tempfile.mkdtemp()) / "m.stl"
    cq.exporters.export(p, str(f), exportType="STL", tolerance=0.001, angularTolerance=0.05)
    holes = fx.find_holes(fx.load_stl(f))
    assert len(holes) == 2
    cb = next(h for h in holes if h["cbore"])
    assert cb["through"] and cb["d"] / IN == pytest.approx(0.25, abs=0.002) and cb["cbore"]["d"] / IN == pytest.approx(0.5, abs=0.002)
    bl = next(h for h in holes if not h["cbore"])
    assert not bl["through"] and bl["d"] / IN == pytest.approx(0.3, abs=0.002) and bl["length"] / IN == pytest.approx(0.5, abs=0.01)


def test_worked_example_uses_the_same_aggregate():
    ex = fx.worked_example(CFG)
    by = {c["case"]: c for c in ex["cases"]}
    assert ex["illustrative"] and "not a measured part" in ex["label"]
    assert by["Everything matches the drawing"]["score"] == 100
    assert by["One hole missing"]["score"] < by["Everything matches the drawing"]["score"]
    capped = by["Exported mesh is not this build (critical gate)"]
    assert capped["score"] == CFG["gates"]["critical_cap"] and capped["caps"]
    for c in ex["cases"]:
        assert 0 <= c["score"] <= 100


def test_methodology_matches_the_config():
    m = fx.methodology(CFG)
    assert m["total_possible"] == 100 and [c["id"] for c in m["categories"]] == list(fx.CAT_ORDER)
    assert {c["e"]: c["credit"] for c in m["credit_curve"]}[1] == 1.0


def test_cli_writes_fidelity_score_json(tmp_path, capsys):
    d = write_part(tmp_path, plate())
    assert fx.main([str(d)]) == 0
    saved = json.loads((d / "fidelity_score.json").read_text())
    assert saved["state"] == "scored" and saved["rubric"]["id"] == "emf"
