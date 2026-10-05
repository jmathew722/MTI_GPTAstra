"""BuildPlan: Feature IR v2 (spec: docs/superpowers/specs/2026-09-28-feature-ir-v2-design.md).

The LLM (or the deterministic ``plan_from_v1``) *plans*. Compilers build. Every number
is an :mod:`pipeline.ir.expr` expression over drawing dimension IDs.

Conventions (decisions recorded in docs/superpowers/plans/2026-10-04-feature-ir-v2.md):

* **One part frame**, drawing units. ``corner``: the envelope's min corner at the
  origin (plates). ``axis_end``: the part axis is +Z, with the origin at the center
  of one end face (turned parts).
* **Refs are strings**: ``plane(front|top|right)``, ``face(F001,+Z)`` (planar face of F
  whose outward normal is that axis), ``axis(F001)``, ``wall(F002)`` (the curved side
  faces of F), ``axis(part)``. Edge queries: ``edge_between(<ref>,<ref>)``.
* **Sketch coordinates (u, v)** are the two GLOBAL axes in the sketch plane:
  front/±Z → (x, y), top/±Y → (x, z), right/±X → (y, z). Never a local frame.
* **Direction:** from a face, ``op: add`` extrudes outward and ``op: cut`` goes into
  the material. From a base plane, both go along +normal (front +Z, top +Y,
  right +X). ``offset`` moves the start plane along that normal.
* A turned part's necks, grooves and shoulders are steps in its ``revolve``
  stations, not separate cuts.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from pipeline.ir.expr import ExprError, dim_ids, evaluate, parse, ungrounded_literals

IR_VERSION = "2.0"


def _to_expr(v):
    if isinstance(v, bool):
        raise ValueError("booleans are not expressions")
    if isinstance(v, (int, float)):
        return repr(v) if isinstance(v, float) else str(v)
    if not isinstance(v, str):
        raise ValueError(f"expected an expression string, got {type(v).__name__}")
    try:
        parse(v)
    except ExprError as e:
        raise ValueError(str(e)) from e
    return v.strip()


Expr = Annotated[str, BeforeValidator(_to_expr)]

_AXIS = r"[+-][XYZ]"
_FID = r"F\d{3,}"
_REF_RES = {
    "plane": re.compile(r"^plane\((front|top|right)\)$"),
    # optional 3rd arg: the face's coordinate along the axis (expression), needed when
    # a stepped body has several faces pointing the same way (SB11033's flange faces)
    "face": re.compile(rf"^face\(({_FID}),\s*({_AXIS})(?:,(.+))?\)$"),
    "axis": re.compile(rf"^axis\(({_FID}|part)\)$"),
    # optional 2nd arg: radius (expression) to pick one curved face of a stepped body
    "wall": re.compile(rf"^wall\(({_FID})(?:,(.+))?\)$"),
}
_EDGE_RE = re.compile(r"^edge_between\((.+?),\s*((?:plane|face|axis|wall)\(.+\))\)$")


def parse_ref(ref: str) -> tuple[str, tuple[str, ...]]:
    """``"face(F001,+Z)"`` -> ``("face", ("F001", "+Z"))``. Raises ValueError."""
    s = ref.replace(" ", "")
    for kind, rx in _REF_RES.items():
        m = rx.match(s)
        if m:
            groups = tuple(g for g in m.groups() if g is not None)
            if kind in ("face", "wall") and len(groups) == (3 if kind == "face" else 2):
                try:
                    parse(groups[-1])
                except ExprError as e:
                    raise ValueError(f"bad expression in {ref!r}: {e}") from e
            return kind, groups
    raise ValueError(f"not a valid ref: {ref!r}")


def parse_edge_query(q: str) -> tuple[str, str]:
    m = _EDGE_RE.match(q.replace(" ", ""))
    if not m:
        raise ValueError(f"not a valid edge query: {q!r} (use edge_between(<ref>,<ref>))")
    a, b = m.groups()
    parse_ref(a)
    parse_ref(b)
    return a, b


def ref_exprs(ref: str) -> list[str]:
    """Expressions embedded in a ref (face coordinate, wall radius)."""
    kind, args = parse_ref(ref)
    if (kind == "face" and len(args) == 3) or (kind == "wall" and len(args) == 2):
        return [args[-1]]
    return []


def resolve_ref(ref: str, dims: dict[str, float]) -> str:
    """The ref with its embedded expression evaluated: ``face(F001,+Z,0.565)``."""
    kind, args = parse_ref(ref)
    ex = ref_exprs(ref)
    if not ex:
        return ref.replace(" ", "")
    v = round(evaluate(ex[0], dims).value, 9)
    return f"{kind}({','.join(list(args[:-1]) + [repr(v)])})"


def resolve_edge_query(q: str, dims: dict[str, float]) -> str:
    a, b = parse_edge_query(q)
    return f"edge_between({resolve_ref(a, dims)},{resolve_ref(b, dims)})"


def ref_features(ref: str) -> set[str]:
    kind, args = parse_ref(ref)
    return {args[0]} if kind in ("face", "axis", "wall") and args[0] != "part" else set()


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- #
# Profiles (sketch coordinates u, v; see module doc)
# --------------------------------------------------------------------------- #
class Rect(_Base):
    shape: Literal["rect"] = "rect"
    w: Expr
    h: Expr
    anchor: Literal["corner", "center"] = "corner"
    u: Expr = "0"
    v: Expr = "0"


class Circle(_Base):
    shape: Literal["circle"] = "circle"
    d: Expr
    u: Expr = "0"
    v: Expr = "0"


class Slot(_Base):
    shape: Literal["slot"] = "slot"
    length: Expr  # center-to-center
    width: Expr
    angle: Expr = "0"  # degrees from +u
    u: Expr = "0"
    v: Expr = "0"


class Polygon(_Base):
    shape: Literal["polygon"] = "polygon"
    points: list[tuple[Expr, Expr]] = Field(min_length=3)


Profile = Annotated[Union[Rect, Circle, Slot, Polygon], Field(discriminator="shape")]


# --------------------------------------------------------------------------- #
# Features
# --------------------------------------------------------------------------- #
class _Feature(_Base):
    id: str = Field(pattern=r"^F\d{3,}$")
    rationale: str = ""
    source_callouts: list[str] = Field(default_factory=list)
    status: Literal["planned", "unresolved", "unsupported"] = "planned"
    justification: str = ""   # required when an expression uses a literal outside {0, 1, 2}

    def exprs(self) -> list[tuple[str, str]]:
        """(field path, expression) for every expression in the feature."""
        out: list[tuple[str, str]] = []

        def walk(obj, path):
            if isinstance(obj, BaseModel):
                for name in type(obj).model_fields:
                    walk(getattr(obj, name), f"{path}.{name}" if path else name)
            elif isinstance(obj, (list, tuple)):
                for i, x in enumerate(obj):
                    walk(x, f"{path}[{i}]")
            elif (isinstance(obj, str) and path and obj not in ("thru", "equal")
                  and self._is_expr_field(path)):
                out.append((path, obj))

        walk(self, "")
        return out

    _NON_EXPR = {"id", "kind", "rationale", "status", "justification", "on", "op", "shape",
                 "anchor", "type", "thread", "seed", "mode", "dir", "dir1", "dir2", "axis",
                 "edges", "source_callouts", "operation"}

    def _is_expr_field(self, path: str) -> bool:
        leaf = re.sub(r"\[\d+\]", "", path.rsplit(".", 1)[-1])
        return leaf not in self._NON_EXPR

    def refs(self) -> list[str]:
        return []


class Prism(_Feature):
    kind: Literal["prism"] = "prism"
    on: str = "plane(front)"
    offset: Expr = "0"
    profile: Profile
    depth: Union[Expr, Literal["thru"]]
    op: Literal["add", "cut"] = "add"

    @field_validator("on")
    @classmethod
    def _on(cls, v):
        parse_ref(v)
        return v

    def refs(self):
        return [self.on]


class Station(_Base):
    z: Expr
    r: Expr


class Revolve(_Feature):
    kind: Literal["revolve"] = "revolve"
    axis: str = "axis(part)"
    outer: list[Station] = Field(min_length=2)
    inner: list[Station] = Field(default_factory=list)   # bore profile (empty = solid)
    op: Literal["add", "cut"] = "add"

    @field_validator("axis")
    @classmethod
    def _axis(cls, v):
        if parse_ref(v)[0] != "axis":
            raise ValueError("revolve.axis must be an axis(...) ref")
        return v

    def refs(self):
        return [self.axis]


class HoleSpec(_Base):
    type: Literal["thru", "blind", "cbore", "csink", "tapped"] = "thru"
    d: Expr
    depth: Optional[Expr] = None          # blind/tapped
    cbore_d: Optional[Expr] = None
    cbore_depth: Optional[Expr] = None
    csink_d: Optional[Expr] = None
    csink_angle: Optional[Expr] = None    # degrees
    thread: str = ""                      # cosmetic only (CLAUDE.md rule 7)


class Hole(_Feature):
    kind: Literal["hole"] = "hole"
    on: str                               # start face (or plane) and into-material direction
    u: Expr
    v: Expr
    spec: HoleSpec

    @field_validator("on")
    @classmethod
    def _on(cls, v):
        parse_ref(v)
        return v

    def refs(self):
        return [self.on]


class Pattern(_Feature):
    kind: Literal["pattern"] = "pattern"
    seed: str = Field(pattern=r"^F\d{3,}$")
    mode: Literal["linear", "grid", "circular"]
    dir: str = "+X"
    count: Expr = "1"
    pitch: Expr = "0"
    dir2: str = "+Y"
    count2: Expr = "1"
    pitch2: Expr = "0"
    axis: str = "axis(part)"
    start_angle: Expr = "0"               # degrees; literal allowed when the drawing implies it
    step: Union[Literal["equal"], Expr] = "equal"
    skip: list[int] = Field(default_factory=list)

    def refs(self):
        return [self.axis] if self.mode == "circular" else []


class EdgeOp(_Feature):
    kind: Literal["edge_op"] = "edge_op"
    operation: Literal["fillet", "chamfer"]
    size: Expr
    angle: Expr = "45"                    # chamfer angle, degrees
    edges: list[str] = Field(min_length=1)

    @field_validator("edges")
    @classmethod
    def _edges(cls, v):
        for q in v:
            parse_edge_query(q)
        return v

    def refs(self):
        return [r for q in self.edges for r in parse_edge_query(q)]


FeatureIR = Annotated[Union[Prism, Revolve, Hole, Pattern, EdgeOp], Field(discriminator="kind")]


class Frame(_Base):
    origin_kind: Literal["corner", "axis_end"]
    units: Literal["inch", "mm"]
    view_map: dict[str, str] = Field(default_factory=dict)   # e.g. {"front": "-Z", "side": "+X"}


class Finding(_Base):
    severity: Literal["error", "warning", "info"]
    code: str
    feature: str = ""
    message: str


class BuildPlan(_Base):
    ir_version: str = IR_VERSION
    part: str
    frame: Frame
    features: list[FeatureIR]
    notes: list[str] = Field(default_factory=list)

    def feature(self, fid: str):
        return next((f for f in self.features if f.id == fid), None)

    def check(self, dims: dict[str, float], reference_ids: frozenset[str] = frozenset()) -> list[Finding]:
        """The deterministic core of Gate 1 (PRD B1). Errors can't be overruled (B3)."""
        found: list[Finding] = []
        seen: set[str] = set()
        used: set[str] = set()
        for f in self.features:
            if f.id in seen:
                found.append(Finding(severity="error", code="duplicate_id", feature=f.id,
                                     message=f"feature id {f.id} is used twice"))
            if f.status == "unresolved":
                found.append(Finding(severity="error", code="unresolved", feature=f.id,
                                     message=f"{f.id} is unresolved: {f.rationale or 'no grounded geometry'}"))
            elif f.status == "unsupported":
                found.append(Finding(severity="info", code="unsupported", feature=f.id,
                                     message=f"{f.id} is unsupported and will not be built"))
            for path, e in f.exprs():
                try:
                    used |= evaluate(e, dims).dim_ids
                except ExprError as err:
                    found.append(Finding(severity="error", code="bad_expr", feature=f.id,
                                         message=f"{path} = {e!r}: {err}"))
                    continue
                # Counts ("4X") and angles ("EQ SP") come from callouts, not lengths.
                if (ungrounded_literals(e) and not f.justification
                        and not path.endswith(("angle", "start_angle", "count", "count2", "step"))):
                    found.append(Finding(severity="error", code="ungrounded_literal", feature=f.id,
                                         message=f"{path} = {e!r} uses literal(s) "
                                                 f"{sorted(ungrounded_literals(e))} without a justification"))
            for r in f.refs():
                for e in ref_exprs(r):
                    try:
                        used |= evaluate(e, dims).dim_ids
                    except ExprError as err:
                        found.append(Finding(severity="error", code="bad_expr", feature=f.id,
                                             message=f"{r}: {err}"))
                for rf in ref_features(r):
                    if rf not in seen:
                        found.append(Finding(severity="error", code="dangling_ref", feature=f.id,
                                             message=f"{r} refers to {rf}, which is not an earlier feature"))
            if isinstance(f, Pattern) and f.seed not in seen:
                found.append(Finding(severity="error", code="dangling_ref", feature=f.id,
                                     message=f"pattern seed {f.seed} is not an earlier feature"))
            seen.add(f.id)
        for d in sorted(set(dims) - used - set(reference_ids)):
            found.append(Finding(severity="warning", code="unused_dimension",
                                 message=f"{d} is not used by any feature"))
        return found


def plan_dim_ids(plan: BuildPlan) -> frozenset[str]:
    return frozenset(i for f in plan.features for _, e in f.exprs() for i in dim_ids(e))
