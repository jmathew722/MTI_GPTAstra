"""Expressions over drawing dimension IDs, e.g. ``"D003 / 2"`` or ``"D012 - D009"``.

Every number in a BuildPlan is one of these strings, so each coordinate can be traced
back to the drawing dimensions it came from (PRD A1, NFR traceability).

Grammar: numbers, dimension IDs (``D`` + 3 or more digits), ``+ - * /``, unary
minus and parentheses. Nothing else. The string is parsed with Python's ``ast`` and
walked against a whitelist. It is never passed to ``eval``.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Union

_DIM_ID = re.compile(r"^D\d{3,}$")
_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div)
GROUNDED_LITERALS = frozenset({0.0, 1.0, 2.0})

Number = Union[int, float]


class ExprError(ValueError):
    """The expression is not in the grammar, or cannot be evaluated."""


@dataclass(frozen=True)
class Evaluated:
    value: float
    dim_ids: frozenset[str] = field(default_factory=frozenset)


def _check(node: ast.AST, src: str) -> None:
    if isinstance(node, ast.Expression):
        return _check(node.body, src)
    if isinstance(node, ast.BinOp) and isinstance(node.op, _BINOPS):
        _check(node.left, src)
        _check(node.right, src)
        return None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return _check(node.operand, src)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return None
    if isinstance(node, ast.Name) and _DIM_ID.match(node.id):
        return None
    raise ExprError(f"not allowed in a plan expression: {ast.dump(node)[:60]} (in {src!r})")


def parse(expr: Union[str, Number]) -> ast.Expression:
    """Parse and validate an expression (a bare number is accepted as its literal)."""
    src = str(expr).strip()
    if not src:
        raise ExprError("empty expression")
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError as e:
        raise ExprError(f"syntax error in {src!r}: {e.msg}") from e
    _check(tree, src)
    return tree


def _eval(node: ast.AST, dims: dict[str, float], used: set[str]) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body, dims, used)
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in dims:
            raise ExprError(f"unknown dimension id {node.id}")
        used.add(node.id)
        return float(dims[node.id])
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, dims, used)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp):
        a, b = _eval(node.left, dims, used), _eval(node.right, dims, used)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if b == 0:
            raise ExprError("division by zero")
        return a / b
    raise ExprError(f"unexpected node {type(node).__name__}")  # unreachable after _check


def evaluate(expr: Union[str, Number], dims: dict[str, float]) -> Evaluated:
    """Value of ``expr`` given dimension values, plus the D-IDs it used."""
    used: set[str] = set()
    value = _eval(parse(expr), dims, used)
    return Evaluated(value, frozenset(used))


def dim_ids(expr: Union[str, Number]) -> frozenset[str]:
    """Dimension IDs referenced by ``expr`` (no values needed)."""
    return frozenset(n.id for n in ast.walk(parse(expr)) if isinstance(n, ast.Name))


def literals(expr: Union[str, Number]) -> frozenset[float]:
    """Numeric literals in ``expr``. Any outside {0, 1, 2} needs a justification."""
    return frozenset(float(n.value) for n in ast.walk(parse(expr)) if isinstance(n, ast.Constant))


def ungrounded_literals(expr: Union[str, Number]) -> frozenset[float]:
    """Literals that need a justification under the grounding rule (PRD A1).

    0, 1 and 2 are structural only as *scale factors* (``D003 / 2``, ``2 * D010``).
    A nonzero literal that is ADDED or SUBTRACTED is a length the drawing didn't
    give (``D002 / 2 - 1`` invents 1 inch), so it always needs a justification. This
    tightens the spec's plain {0, 1, 2} rule. A bare literal expression ``"1"`` is
    likewise a length unless it is 0.
    """
    tree = parse(expr)
    out: set[float] = {v for v in literals(expr) if v not in GROUNDED_LITERALS}
    body = tree.body
    if isinstance(body, ast.Constant) and float(body.value) != 0.0:
        out.add(float(body.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
            for side in (node.left, node.right):
                inner = side.operand if isinstance(side, ast.UnaryOp) else side
                if isinstance(inner, ast.Constant) and float(inner.value) != 0.0:
                    out.add(float(inner.value))
    return frozenset(out)
