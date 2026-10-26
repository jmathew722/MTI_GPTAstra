"""MTI practices score (spec 2026-10-25, 2b): pure checks over hand-made feature trees,
ir_reports and plans. No SolidWorks."""
import pytest

from bench import practices, score_config
from bench.practices import check_part


def F(name, typ, *subs, status=None):
    return {"name": name, "type": typ, "index": 0, "status": status, "subs": list(subs)}


def S(name, typ="ProfileFeature", status=3):
    return {"name": name, "type": typ, "status": status}


ORIGIN = [F("Origin", "OriginProfileFeature"), F("Front Plane", "RefPlane"), F("Top Plane", "RefPlane")]


def good_tree():
    return ORIGIN + [
        F("Boss-Extrude1", "Extrusion", S("Sketch1")),
        F("Cut-Extrude1", "Cut", S("Sketch2")),
        F("M8 Tapped Hole1", "HoleWzd", S("Sketch3"), S("Sketch4"), S("CosmeticThread1", "CosmeticThread", None)),
        F("Fillet1", "Fillet"),
        F("Chamfer1", "Chamfer"),
    ]


def hole(fid, on="face(F001,+Z)", d="0.25", typ="thru", u="0", status="planned"):
    return {"id": fid, "kind": "hole", "on": on, "u": u, "v": "0", "status": status,
            "spec": {"type": typ, "d": d}}


def plan_of(*features, dims=None):
    return {"dims": dims or {}, "plan": {"features": [{"id": "F001", "kind": "prism", "op": "add",
                                                         "status": "planned"}, *features]}}


def rows(ps):
    return {r.id: r for r in ps.rows}


CFG = score_config.load()


def test_config_has_practices_section():
    p = CFG.practices
    assert set(p["weights"]) == {f"C{i}" for i in range(1, 8)} and set(p["weights"].values()) == {1}
    assert p["edge_ops"] == ["Fillet", "Chamfer"]
    assert "HoleWzd" in p["solid_ops"] and "Sweep" in p["avoid"]
    assert p["three_d_sketch"] == "3DProfileFeature"


def test_all_pass():
    ir = {"conventions": ["origin centered: True", "F001: base sketch on the Top plane, Mid Plane extrude",
                          "sketches fully defined: 4/4"]}
    ps = check_part(good_tree(), ir, plan_of(hole("F002"), hole("F003", u="1")), CFG)
    r = rows(ps)
    assert all(x.applicable and x.credit == 1.0 for x in ps.rows), [(x.id, x.reason) for x in ps.rows]
    assert ps.score == pytest.approx(100.0) and ps.checked
    assert r["C1"].source == "self-reported" and r["C2"].source == "self-reported"
    assert r["C3"].source == "sldprt" and r["C6"].source == "plan"
    assert all(x.stage is None for x in ps.rows)


def test_c1_origin():
    assert rows(check_part([], {"conventions": ["origin centered: False"]}, {}, CFG))["C1"].credit == 0.0
    r = rows(check_part([], {"conventions": ["origin centered: False"]}, {}, CFG))["C1"]
    assert r.applicable and r.stage == "solidworks" and "origin" in r.reason
    assert not rows(check_part([], {}, {}, CFG))["C1"].applicable                  # no report
    assert not rows(check_part([], {"conventions": ["origin centered: None"]}, {}, CFG))["C1"].applicable


def test_c2_top_plane_mid_plane():
    ok = check_part([], {"conventions": ["F001: base sketch on the Top plane, Mid Plane extrude"]}, {}, CFG)
    assert rows(ok)["C2"].credit == 1.0
    bad = rows(check_part([], {"conventions": ["F001: Mid Plane did not match; used an offset start"]}, {}, CFG))["C2"]
    assert bad.applicable and bad.credit == 0.0 and bad.stage == "solidworks" and "F001" in bad.reason
    assert not rows(check_part([], {}, {}, CFG))["C2"].applicable
    # a revolve base reports neither: nothing to judge
    assert not rows(check_part([], {"conventions": ["origin centered: True"]}, {}, CFG))["C2"].applicable


def test_c3_fraction_fully_defined():
    tree = ORIGIN + [F("Boss-Extrude1", "Extrusion", S("Sketch1")), F("Cut-Extrude1", "Cut", S("Sketch2", status=2)),
                     F("Sketch9", "ProfileFeature", status=3), F("Cut-Extrude2", "Cut", S("Sketch3", status=4))]
    r = rows(check_part(tree, {}, {}, CFG))["C3"]
    assert r.credit == pytest.approx(0.5) and r.stage == "solidworks"
    assert "Sketch2" in r.reason and "Sketch3" in r.reason and "Sketch1" not in r.reason
    assert not rows(check_part(ORIGIN, {}, {}, CFG))["C3"].applicable


def test_c4_edge_ops_after_solid_ops():
    tree = ORIGIN + [F("Boss-Extrude1", "Extrusion"), F("Fillet1", "Fillet"), F("Cut-Extrude3", "Cut"),
                     F("Chamfer1", "Chamfer")]
    r = rows(check_part(tree, {}, {}, CFG))["C4"]
    assert r.credit == 0.0 and r.stage == "planner" and r.reason == "Fillet1 before Cut-Extrude3"
    assert not rows(check_part(ORIGIN + [F("Boss-Extrude1", "Extrusion")], {}, {}, CFG))["C4"].applicable


def test_c5_hole_wizard_3d_sketch():
    tree = ORIGIN + [F("Boss-Extrude1", "Extrusion"), F("CBORE1", "HoleWzd", S("3DSketch1", "3DProfileFeature"),
                                                         S("Sketch2"))]
    r = rows(check_part(tree, {}, {}, CFG))["C5"]
    assert r.credit == 0.0 and r.stage == "solidworks" and "CBORE1" in r.reason
    assert rows(check_part(good_tree(), {}, {}, CFG))["C5"].credit == 1.0
    assert not rows(check_part(ORIGIN + [F("Boss-Extrude1", "Extrusion")], {}, {}, CFG))["C5"].applicable


def test_c6_hole_grouping_from_plan():
    # F002 and F004 are the same hole on the same face but not consecutive -> 2 features, 1 group
    p = plan_of(hole("F002"), hole("F003", d="0.5"), hole("F004", u="2"))
    r = rows(check_part([], {}, p, CFG))["C6"]
    assert r.credit == pytest.approx(1 - 1 / 3) and r.stage == "planner"
    assert "F002" in r.reason and "F004" in r.reason
    # consecutive identical holes become one feature (the compiler merges them)
    assert rows(check_part([], {}, plan_of(hole("F002"), hole("F003", u="1")), CFG))["C6"].credit == 1.0
    # another face is another group
    q = plan_of(hole("F002"), hole("F003", d="0.5"), hole("F004", on="face(F001,-Z)"))
    assert rows(check_part([], {}, q, CFG))["C6"].credit == 1.0
    # expressions over dims are evaluated (D001 / 2 == 0.25), with the compiler's hole_signature
    e = plan_of(hole("F002", d="D001 / 2"), hole("F003", d="0.5"), hole("F004"), dims={"D001": 0.5})
    assert rows(check_part([], {}, e, CFG))["C6"].credit == pytest.approx(2 / 3)
    assert not rows(check_part([], {}, plan_of(), CFG))["C6"].applicable
    assert not rows(check_part([], {}, {}, CFG))["C6"].applicable


def test_c6_uses_built_grouping_and_skips_unbuilt():
    p = plan_of(hole("F002"), hole("F003", d="0.5"), hole("F004", u="2"), hole("F005", status="unresolved"))
    ir = {"sw_features": {"F002": "built (one feature for F002, F004)", "F003": "built",
                          "F004": "built (in F002 (one feature))"}}
    assert rows(check_part([], ir, p, CFG))["C6"].credit == 1.0
    ir2 = {"cq_skipped": {"F004": "failed: x"}}
    assert rows(check_part([], ir2, p, CFG))["C6"].credit == 1.0


def test_c6_mti_review_fallback_without_plan():
    ir = {"mti_review": ["[mti_hole_grouping] F003, F004: identical holes on face(F001,-Z) -> one Hole Wizard "
                         "feature with several sketch points"]}
    r = rows(check_part([], ir, {}, CFG))["C6"]
    assert r.applicable and r.credit == pytest.approx(0.5) and r.source == "self-reported"
    ir["sw_features"] = {"F003": "built (one feature for F003, F004)", "F004": "built (in F003 (one feature))"}
    assert rows(check_part([], ir, {}, CFG))["C6"].credit == 1.0


def test_c7_avoid_and_blame():
    tree = good_tree() + [F("Shell1", "Shell"), F("Sweep1", "Sweep")]
    r = rows(check_part(tree, {}, {}, CFG))["C7"]
    assert r.credit == 0.0 and r.stage == "solidworks" and "Shell1" in r.reason and "Sweep1" in r.reason
    planned = plan_of({"id": "F009", "kind": "shell", "status": "planned"})
    assert rows(check_part(tree, {}, planned, CFG))["C7"].stage == "planner"
    assert rows(check_part(good_tree(), {}, {}, CFG))["C7"].credit == 1.0
    assert rows(check_part(ORIGIN, {}, {}, CFG))["C7"].applicable           # always, with a tree


def test_no_tree_marks_sldprt_checks_not_checked():
    ps = check_part(None, {"conventions": ["origin centered: True"]}, {}, CFG)
    r = rows(ps)
    assert not ps.checked
    for cid in ("C3", "C4", "C5", "C7"):
        assert not r[cid].applicable and "not checked" in r[cid].reason
    assert ps.score == pytest.approx(100.0)                                  # C1 alone


def test_nothing_applies_scores_none():
    ps = check_part(None, {}, {}, CFG)
    assert ps.score is None and len(ps.rows) == 7


def test_weights():
    tree = ORIGIN + [F("Boss-Extrude1", "Extrusion", S("Sketch1")), F("Fillet1", "Fillet"), F("Cut1", "Cut")]
    # C3 pass, C4 fail, C7 pass (C1, C2, C5, C6 not applicable)
    assert check_part(tree, {}, {}, CFG).score == pytest.approx(100 * 2 / 3)
    w = {**CFG.practices, "weights": {**CFG.practices["weights"], "C4": 2}}
    assert check_part(tree, {}, {}, w).score == pytest.approx(100 * 2 / 4)


def test_asdict_roundtrip():
    from dataclasses import asdict
    d = asdict(check_part(good_tree(), {}, {}, CFG))
    assert set(d) == {"score", "rows", "checked"}
    assert set(d["rows"][0]) == {"id", "name", "credit", "applicable", "source", "stage", "reason"}
    assert practices.CHECK_IDS == ("C1", "C2", "C3", "C4", "C5", "C6", "C7")
