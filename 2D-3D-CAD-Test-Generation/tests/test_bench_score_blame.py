"""blame: the first stage at fault, one test per category."""
from bench.blame import blame_part, extracted_values, rollup
from bench.features import Feature, Key
from bench.score_config import load
from bench.scoring import Extra, PartScore, Row

C = load()


def _key(**kw):
    f = Feature(id="K1", type=kw.get("type", "thru_hole"), axis=[0, 0, 1], center=[1, 1, 0], d=0.344,
                depth=0.5, links=kw.get("links", {"size": [0.344], "position": [1.0]}), tol=kw.get("tol", {}),
                cbore_d=kw.get("cbore_d"))
    return Key(part="P", units="inch", source="s", envelope=[4, 3, 0.5], features=[f],
               overrides=kw.get("overrides", []), flags=kw.get("flags", []))


LOSSY = {"type": 1.0, "position": 0.4, "size": 0.4}


def _ps(credit, status="matched", attrs=None, fid="K1"):
    ac = {} if status == "missing" else (attrs if attrs is not None else
                                         ({} if credit == 1.0 else dict(LOSSY)))
    return PartScore("P", 100 * credit, credit == 1.0,
                     [Row("BASE", "base_body", 10, 10, "matched", "BASE", credit=1.0),
                      Row(fid, "thru_hole", 3, 0.9, status, "G1" if status == "matched" else None,
                          attr_credits=ac, credit=credit, points_lost=5.0)],
                     [], [])


EXT_OK = {"dimensions": [{"id": "D1", "value": 0.344}, {"id": "D2", "value": 1.0}]}


def test_ground_truth_when_the_override_touches_a_lossy_attribute():
    lossy_depth = {"type": 1.0, "position": 1.0, "depth": 0.3}
    b = blame_part(_ps(0.4, attrs=lossy_depth), _ps(0.4, attrs=lossy_depth),
                   _key(overrides=[{"feature": "K1", "attr": "depth", "value": 0.1}]), EXT_OK, {"cq_skipped": {}}, C)
    assert b["K1"].stage == "ground_truth"


def test_override_on_another_attribute_does_not_hide_the_loss():
    lossy_pos = {"type": 1.0, "position": 0.4, "size": 1.0}
    k = _key(overrides=[{"feature": "K1", "attr": "depth", "silent": True}])
    b = blame_part(_ps(0.4, attrs=lossy_pos), _ps(0.4, attrs=lossy_pos), k, EXT_OK, {}, C)
    assert b["K1"].stage == "planner"


def test_ground_truth_from_a_derived_resolution():
    from bench.features import Flag
    flag = Flag("unexplained_key_value", "thru_hole d=0.3440 not stated", "K1",
                "drawing-silent: model detail not stated on the drawing; do not score it")
    lossy_size = {"type": 1.0, "position": 1.0, "size": 0.2}
    b = blame_part(_ps(0.4, attrs=lossy_size), _ps(0.4, attrs=lossy_size), _key(flags=[flag]), EXT_OK, {}, C)
    assert b["K1"].stage == "ground_truth"


def test_expect_rows_are_ground_truth():
    sw = _ps(0.0, "missing", fid="EXPECT-countersink-1")
    b = blame_part(sw, _ps(0.0, "missing", fid="EXPECT-countersink-1"), _key(), EXT_OK, {}, C)
    assert b["EXPECT-countersink-1"].stage == "ground_truth"


def test_unsupported():
    assert blame_part(_ps(0.4), _ps(0.4), _key(type="countersink"), EXT_OK, {}, C)["K1"].stage == "unsupported"


def test_extraction():
    ext = {"dimensions": [{"id": "D2", "value": 1.0}]}          # .344 never extracted
    b = blame_part(_ps(0.4), _ps(0.4), _key(), ext, {}, C)["K1"]
    assert b.stage == "extraction" and "0.344" in b.reason and b.points == 5.0


def test_correct_reference_beats_the_extraction_check():
    ext = {"dimensions": [{"id": "D2", "value": 1.0}]}          # .344 never extracted, yet CQ is right
    assert blame_part(_ps(0.4), _ps(1.0), _key(), ext, {}, C)["K1"].stage == "solidworks"


def test_only_lossy_attributes_are_checked_against_the_extraction():
    ext = {"dimensions": [{"id": "D2", "value": 1.0}]}          # size link missing, but size is right
    lossy_pos = {"type": 1.0, "position": 0.4, "size": 1.0}
    assert blame_part(_ps(0.4, attrs=lossy_pos), _ps(0.4, attrs=lossy_pos), _key(), ext, {}, C)["K1"].stage         == "planner"


def test_linked_values_of_one_attribute_are_alternatives():
    k = _key(links={"size": [0.344], "position": [1.0, 2.5]})
    ext = {"dimensions": [{"id": "D1", "value": 0.344}, {"id": "D2", "value": 2.5}]}   # 1.0 absent
    assert blame_part(_ps(0.4), _ps(0.4), k, ext, {}, C)["K1"].stage == "planner"


def test_each_size_field_needs_one_extracted_value():
    k = _key(type="counterbore", cbore_d=0.5, links={"size": [0.344, 0.5]})
    only_drill = {"dimensions": [{"id": "D1", "value": 0.344}]}
    b = blame_part(_ps(0.4), _ps(0.4), k, only_drill, {}, C)["K1"]
    assert b.stage == "extraction" and "0.5" in b.reason
    both = {"dimensions": [{"id": "D1", "value": 0.344}, {"id": "D3", "value": 0.5}]}
    assert blame_part(_ps(0.4), _ps(0.4), k, both, {}, C)["K1"].stage == "planner"


def test_extraction_compare_is_tolerance_relative():
    near = {"dimensions": [{"id": "D1", "value": 0.348}, {"id": "D2", "value": 1.0}]}   # within .005
    assert blame_part(_ps(0.4), _ps(0.4), _key(), near, {}, C)["K1"].stage == "planner"
    off = {"dimensions": [{"id": "D1", "value": 0.36}, {"id": "D2", "value": 1.0}]}
    assert blame_part(_ps(0.4), _ps(0.4), _key(), off, {}, C)["K1"].stage == "extraction"
    loose = _key(tol={"size": 0.02})                            # the feature's own tolerance
    assert blame_part(_ps(0.4), _ps(0.4), loose, off, {}, C)["K1"].stage == "planner"


def test_extracted_values_reads_real_extraction_shape():
    ext = {"dimensions": [{"id": "D1", "type": "radial", "value": 0.172},
                          {"id": "D2", "type": "linear", "value": 1.0, "possible_values": [1.0, 1.06]},
                          {"id": "D3", "type": "linear", "value": "bad"}],
           "hole_callouts": [{"id": "H1", "diameter": 0.40625, "depth": 0.0, "cbore_diameter": 0.6875,
                              "cbore_depth": 0.25, "x_position": 0.435, "y_position": 2.31,
                              "pattern_spacing": 2.375, "instance_positions": [[2.81, 0.435]]}]}
    vals = extracted_values(ext)
    for v in (0.172, 0.344, 1.0, 1.06, 0.40625, 0.6875, 0.25, 0.435, 2.31, 2.375, 2.81):
        assert any(abs(v - e) < 1e-9 for e in vals), v
    assert 0.0 not in vals
    assert extracted_values({}) == [] and extracted_values(None) == []


def test_hole_callout_diameter_counts_as_extracted():
    ext = {"dimensions": [{"id": "D2", "value": 1.0}], "hole_callouts": [{"id": "H1", "diameter": 0.344}]}
    assert blame_part(_ps(0.4), _ps(0.4), _key(), ext, {}, C)["K1"].stage == "planner"


def test_planner():
    assert blame_part(_ps(0.4), _ps(0.4), _key(), EXT_OK, {"cq_skipped": {}}, C)["K1"].stage == "planner"


PLAN = {"dims": {}, "plan": {"features": [
    {"id": "F001", "kind": "prism", "op": "add"},
    {"id": "F004", "kind": "hole", "spec": {"type": "thru"}},
    {"id": "F005", "kind": "pattern", "seed": "F004"},
    {"id": "F007", "kind": "edge_op", "operation": "fillet"}]}}


def test_cadquery_when_a_compatible_plan_feature_was_skipped():
    for fid in ("F004", "F005"):                                # the hole, or a pattern of it
        b = blame_part(_ps(0.0, "missing"), _ps(0.0, "missing"), _key(), EXT_OK,
                       {"cq_skipped": {fid: "failed: StdFail_NotDone"}}, C, plan=PLAN)
        assert b["K1"].stage == "cadquery" and fid in b["K1"].reason


def test_feature_left_unbuilt_as_uncertain_is_unresolved_not_cadquery():
    q = "unresolved: which face is the .344 hole drilled from?"
    b = blame_part(_ps(0.0, "missing"), _ps(0.0, "missing"), _key(), EXT_OK, {"cq_skipped": {"F004": q}}, C,
                   plan=PLAN)["K1"]
    assert b.stage == "unresolved" and "which face" in b.reason and b.points == 5.0
    b = blame_part(_ps(0.0, "missing"), _ps(0.0, "missing"), _key(), EXT_OK,
                   {"cq_skipped": {"F004": "unsupported: tapered thread"}}, C, plan=PLAN)["K1"]
    assert b.stage == "unsupported"


def test_unresolved_features_lists_every_uncertain_skip():
    from bench.blame import unresolved_features
    ir = {"cq_skipped": {"F007": "unresolved: what corner radius?", "F004": "failed: StdFail_NotDone"}}
    assert unresolved_features(ir, PLAN) == [{"id": "F007", "kind": "edge_op fillet",
                                             "question": "what corner radius?"}]
    assert unresolved_features({}, None) == []


def test_unrelated_skip_is_not_cadquery():
    b = blame_part(_ps(0.0, "missing"), _ps(0.0, "missing"), _key(), EXT_OK,
                   {"cq_skipped": {"F007": "unresolved: what corner radius?"}}, C, plan=PLAN)
    assert b["K1"].stage == "planner"
    b = blame_part(_ps(0.0, "missing"), _ps(0.0, "missing"), _key(), EXT_OK,      # no plan: unknown kind
                   {"cq_skipped": {"F004": "failed"}}, C)
    assert b["K1"].stage == "planner"


def test_solidworks():
    sw = _ps(0.4)
    b = blame_part(sw, _ps(1.0), _key(), EXT_OK, {}, C)
    assert b["K1"].stage == "solidworks"
    assert sw.row("K1").blame == "solidworks" and sw.row("K1").reason


def test_full_credit_has_no_blame():
    assert "K1" not in blame_part(_ps(1.0), _ps(1.0), _key(), EXT_OK, {}, C)


def test_extras_blamed_where_they_first_appear():
    sw = _ps(1.0)
    sw.extras = [Extra("G9", "thru_hole", 0.9, 2.0)]
    cq = _ps(1.0)
    assert blame_part(sw, cq, _key(), EXT_OK, {}, C)["extra:G9"].stage == "solidworks"
    cq.extras = [Extra("C9", "thru_hole", 0.9, 2.0)]
    assert blame_part(sw, cq, _key(), EXT_OK, {}, C)["extra:G9"].stage == "planner"
    assert sw.extras[0].blame == "planner"


def test_rollup():
    sw = _ps(0.4)
    sw.extras = [Extra("G9", "slot", 0.9, 2.0)]
    bl = blame_part(sw, _ps(1.0), _key(), EXT_OK, {}, C)
    r = rollup([(sw, bl)])
    assert r["by_stage"] == {"solidworks": 7.0}
    assert r["by_type"] == {"thru_hole": 5.0, "slot": 2.0}
    assert r["by_tier"] == {"3": 5.0, "extra": 2.0}
