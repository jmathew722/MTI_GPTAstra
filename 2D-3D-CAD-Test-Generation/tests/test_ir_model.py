"""Feature IR v2, Task 2: BuildPlan model + deterministic Gate-1 checks."""
import json

import pytest
from pydantic import ValidationError

from pipeline.ir.model import BuildPlan, parse_edge_query, parse_ref, plan_dim_ids

# A040921E (dev): Ø10.50 x Ø9.002 x 3.000 ring with a 1.062-wide end slot at
# 12 o'clock, .75 deep from datum A, through the wall; .09 x 45 chamfers.
DIMS = {"D001": 10.5, "D002": 9.002, "D003": 1.062, "D004": 3.0, "D005": 0.75, "D006": 0.09}
RING = {
    "part": "A040921E",
    "frame": {"origin_kind": "axis_end", "units": "inch", "view_map": {"front": "-Z", "side": "+X"}},
    "features": [
        {"kind": "revolve", "id": "F001", "rationale": "ring",
         "outer": [{"z": "0", "r": "D001 / 2"}, {"z": "D004", "r": "D001 / 2"}],
         "inner": [{"z": "0", "r": "D002 / 2"}, {"z": "D004", "r": "D002 / 2"}]},
        {"kind": "prism", "id": "F002", "op": "cut", "on": "face(F001,-Z)",
         "rationale": "end slot from datum A through the wall",
         "profile": {"shape": "rect", "anchor": "corner", "u": "-D003 / 2", "v": "D002 / 2 - 1",
                     "w": "D003", "h": "(D001 - D002) / 2 + 2"},
         "depth": "D005",
         "justification": "v start/height overshoot the wall by 1 in on each side so the cut clears it"},
        {"kind": "edge_op", "id": "F003", "operation": "chamfer", "size": "D006",
         "edges": ["edge_between(face(F001,-Z), wall(F001))", "edge_between(face(F001,+Z), wall(F001))"]},
    ],
}


def plan(**over) -> BuildPlan:
    d = json.loads(json.dumps(RING))
    d.update(over)
    return BuildPlan.model_validate(d)


def test_valid_plan_round_trips_and_checks_clean():
    p = plan()
    again = BuildPlan.model_validate_json(p.model_dump_json())
    assert again == p
    assert [f.severity for f in p.check(DIMS)] == []
    assert plan_dim_ids(p) == frozenset(DIMS)


def test_json_schema_is_generated_for_the_planner_tool():
    schema = BuildPlan.model_json_schema()
    kinds = json.dumps(schema)
    for k in ("prism", "revolve", "hole", "pattern", "edge_op"):
        assert f'"{k}"' in kinds


def test_numbers_become_expressions_and_bad_expressions_are_rejected():
    d = json.loads(json.dumps(RING))
    d["features"][1]["depth"] = 0.75
    assert BuildPlan.model_validate(d).features[1].depth == "0.75"
    d["features"][1]["depth"] = "__import__('os')"
    with pytest.raises(ValidationError):
        BuildPlan.model_validate(d)


def test_ungrounded_literal_needs_justification():
    d = json.loads(json.dumps(RING))
    d["features"][1]["justification"] = ""
    f = BuildPlan.model_validate(d).check(DIMS)
    assert any(x.code == "ungrounded_literal" and x.feature == "F002" for x in f)


def test_unresolved_unknown_dim_dangling_ref_and_unused_dim():
    d = json.loads(json.dumps(RING))
    d["features"][0]["status"] = "unresolved"
    d["features"][1]["on"] = "face(F009,-Z)"
    d["features"][2]["size"] = "D099"
    codes = {(x.code, x.feature) for x in BuildPlan.model_validate(d).check({**DIMS, "D007": 1.0})}
    assert ("unresolved", "F001") in codes
    assert ("dangling_ref", "F002") in codes
    assert ("bad_expr", "F003") in codes
    assert ("unused_dimension", "") in codes


def test_reference_dims_are_not_reported_unused():
    p = plan()
    assert not [x for x in p.check({**DIMS, "D007": 1.0}, reference_ids=frozenset({"D007"}))
                if x.code == "unused_dimension"]


@pytest.mark.parametrize("ref", ["plane(front)", "face(F001,+Z)", "face(F012, -X)", "axis(part)",
                                 "axis(F003)", "wall(F002)"])
def test_refs_parse(ref):
    parse_ref(ref)


@pytest.mark.parametrize("ref", ["plane(side)", "face(F001)", "face(F1,+Z)", "axis()", "edge(F001)"])
def test_bad_refs_rejected(ref):
    with pytest.raises(ValueError):
        parse_ref(ref)


def test_edge_query_parse():
    assert parse_edge_query("edge_between(face(F001,+Z), wall(F002))") == ("face(F001,+Z)", "wall(F002)")
    with pytest.raises(ValueError):
        parse_edge_query("edges_of(F001)")
