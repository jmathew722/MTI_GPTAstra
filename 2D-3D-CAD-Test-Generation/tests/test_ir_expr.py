"""Feature IR v2, Task 1: plan expressions."""
import pytest

from pipeline.ir.expr import ExprError, dim_ids, evaluate, literals, parse, ungrounded_literals

DIMS = {"D001": 10.5, "D002": 9.002, "D003": 1.062, "D010": 0.0}


@pytest.mark.parametrize("src, value, ids", [
    ("D001", 10.5, {"D001"}),
    ("D001 / 2", 5.25, {"D001"}),
    ("(D001 - D002) / 2", (10.5 - 9.002) / 2, {"D001", "D002"}),
    ("-D003 / 2", -0.531, {"D003"}),
    ("0", 0.0, set()),
    (2, 2.0, set()),
    ("360 / 3", 120.0, set()),
    ("D001 * 0.5 + D003", 6.312, {"D001", "D003"}),
])
def test_evaluates_and_captures_dim_ids(src, value, ids):
    r = evaluate(src, DIMS)
    assert r.value == pytest.approx(value)
    assert r.dim_ids == frozenset(ids)
    assert dim_ids(src) == frozenset(ids)


@pytest.mark.parametrize("bad", [
    "", "__import__('os')", "D001 ** 2", "abs(D001)", "x + 1", "D1", "D001.real",
    "D001 if D002 else 0", "[D001]", "D001 // 2", "D001 % 2", "'5'", "True", "D001; D002",
])
def test_rejects_anything_outside_the_grammar(bad):
    with pytest.raises(ExprError):
        parse(bad)


def test_unknown_dimension_id():
    with pytest.raises(ExprError, match="unknown dimension id D999"):
        evaluate("D999 + 1", DIMS)


def test_division_by_zero():
    with pytest.raises(ExprError, match="division by zero"):
        evaluate("D001 / D010", DIMS)


def test_literals_and_grounding_rule():
    assert literals("D001 / 2 + 0.06") == {2.0, 0.06}
    assert ungrounded_literals("D001 / 2") == frozenset()
    assert ungrounded_literals("D001 / 2 + 0.06") == {0.06}
    assert ungrounded_literals("-1 * D003") == frozenset()
    # 1 and 2 are free only as scale factors; added/subtracted they are invented lengths
    assert ungrounded_literals("D002 / 2 - 1") == {1.0}
    assert ungrounded_literals("(D001 - D002) / 2 + 2") == {2.0}
    assert ungrounded_literals("1") == {1.0} and ungrounded_literals("0") == frozenset()
    assert ungrounded_literals("2 * D010 - 0") == frozenset()
