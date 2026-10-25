"""Drawing-is-ground-truth overrides (spec 2026-10-24, 'Key additions' 2).

Two sources, applied to a copy of the key (the effective key the scorer uses):
  * explicit ``Key.overrides`` written by a person (value / silent / expected_count / drawing_only);
  * ``from_resolutions``: what the policy resolutions on the key's flags imply
    (bench.prep.drawing_wins_resolution writes them; the prefix is what counts):
      - ``drawing-silent`` on a feature flag -> that attribute is not scored;
      - ``drawing-wins`` on ``count_mismatch`` -> the drawing's instance count for that type;
      - ``drawing-wins`` on ``unexplained_drawing_value`` -> a drawing-only value, reported only.
An explicit override beats a derived one aimed at the same target.
"""
from __future__ import annotations

import copy
import dataclasses
import re
from dataclasses import dataclass, field

from bench.callouts import parse
from bench.features import Feature, Key

# key attribute named in a flag detail ("counterbore cbore_depth=0.0437 ...") -> scored attribute
_ATTR = {"d": "size", "cbore_d": "size", "csink_d": "size", "depth": "depth", "cbore_depth": "depth"}
_ATTR_RX = re.compile(r"\b(cbore_depth|cbore_d|csink_d|depth|d)=")
_COUNT = re.compile(r"callout '(.*)' says (\d+), key has (\d+)", re.DOTALL)
_KIND_TYPE = {"tap": "tapped_hole", "cbore": "counterbore", "csink": "countersink"}
_TAG_TYPE = (("C'SINK", "countersink"), ("CSK", "countersink"), ("COUNTERSINK", "countersink"),
             ("C'BORE", "counterbore"), ("CBORE", "counterbore"), ("COUNTERBORE", "counterbore"),
             ("TAP", "tapped_hole"))
_DRAWING_VALUE = re.compile(r"^(.+?)\s+\(")       # "linear 0.375 (.375) matches ..." -> "linear 0.375"


@dataclass
class Effective:
    key: Key
    silent: set = field(default_factory=set)            # {(feature_id, attr)}
    expected_counts: dict = field(default_factory=dict)  # {feature type: count}
    drawing_only: list = field(default_factory=list)     # [str]


def _attr_of(kind: str, detail: str) -> str:
    if kind == "unexplained_position":
        return "position"
    m = _ATTR_RX.search(detail)
    return _ATTR[m.group(1)] if m else "size"


def _callout_type(text: str) -> str:
    c = parse(text)
    if c is not None:
        if c.kind in _KIND_TYPE:
            return _KIND_TYPE[c.kind]
        return "blind_hole" if c.depth and not c.thru else "thru_hole"
    up = text.upper()
    return next((t for tag, t in _TAG_TYPE if tag in up), "thru_hole")


def from_resolutions(key: Key) -> list[dict]:
    """Structured overrides implied by policy resolutions (prep accept / human).

    Count flags of one type add up: expected = the sum of the flagged callouts' counts. Not the
    key's count plus each shortfall: "key has 0" usually means the key's holes of that type do
    not fit the callout (a metric twin, a wrong thread), not that they are absent, so adding
    would double count. The scorer only ever adds instances (expected - have, at least 0)."""
    out: list[dict] = []
    called: dict[str, int] = {}
    notes: dict[str, list[str]] = {}
    for f in key.flags:
        r = f.resolution or ""
        if r.startswith("drawing-silent") and f.feature:
            out.append({"feature": f.feature, "attr": _attr_of(f.kind, f.detail), "silent": True, "note": f.detail})
        elif r.startswith("drawing-wins") and f.kind == "count_mismatch":
            m = _COUNT.search(f.detail)
            if m:
                typ = _callout_type(m.group(1))
                called[typ] = called.get(typ, 0) + int(m.group(2))
                notes.setdefault(typ, []).append(f.detail)
        elif r.startswith("drawing-wins") and f.kind == "unexplained_drawing_value":
            m = _DRAWING_VALUE.match(f.detail)
            out.append({"drawing_only": m.group(1) if m else f.detail, "note": f.detail})
    for typ, n in called.items():
        out.append({"type": typ, "expected_count": n, "note": "; ".join(notes[typ])})
    return out


_SCORED = ("size", "depth", "position", "type")
_FIELDS = {f.name for f in dataclasses.fields(Feature)}


def scored_attr(attr: str) -> str:
    """A key field (d, cbore_d, csink_d, depth, cbore_depth) or a scored attribute -> the scored
    attribute it belongs to (size / depth / position / type)."""
    if attr in _ATTR:
        return _ATTR[attr]
    if attr in _SCORED:
        return attr
    raise ValueError(f"override attr {attr!r} is neither a key field ({', '.join(_ATTR)}) "
                     f"nor a scored attribute ({', '.join(_SCORED)})")


def _normalised(o: dict) -> dict:
    """Silent entries name the scored attribute; value entries keep (and must name) a key field."""
    if o.get("silent") and "feature" in o:
        return {**o, "attr": scored_attr(o.get("attr"))}
    if "value" in o:
        attr = o.get("attr")
        if attr in ("size", "position"):
            raise ValueError(f"value override on {o.get('feature')}: attr {attr!r} is a scored attribute, "
                             f"not a key field; name the field to replace ({', '.join(_ATTR)})")
        if attr not in _FIELDS:
            raise ValueError(f"value override on {o.get('feature')}: unknown key field {attr!r}")
    return o


def _target(o: dict) -> tuple:
    if "drawing_only" in o:
        return ("drawing_only", o["drawing_only"])
    if "expected_count" in o:
        return ("count", o["type"])
    if "value" in o:
        return ("value", o.get("feature"), o.get("attr"))
    return ("attr", o.get("feature"), o.get("attr"))


def _value_of(label: str):
    try:
        return float(label.split()[-1])
    except (ValueError, IndexError):
        return None


def apply(key: Key) -> Effective:
    """The effective key: a deep copy with value overrides applied, plus the silent attributes,
    expected instance counts and drawing-only values. The original key is not changed."""
    k = copy.deepcopy(key)
    eff = Effective(key=k)
    explicit_values = {o["value"] for o in k.overrides if "value" in o}
    explicit = [_normalised(o) for o in k.overrides]
    # a person's value for a field beats derived silence on the scored attribute it belongs to
    valued = {(o.get("feature"), _ATTR.get(o["attr"], o["attr"])) for o in explicit if "value" in o}
    merged: dict[tuple, dict] = {}
    for o in from_resolutions(k):
        if "drawing_only" in o and _value_of(o["drawing_only"]) in explicit_values:
            continue                          # the person tied this value to a feature
        if o.get("silent") and (o.get("feature"), o.get("attr")) in valued:
            continue
        merged[_target(o)] = o
    for o in explicit:                        # explicit last: it wins
        merged[_target(o)] = o
    for o in merged.values():
        if "drawing_only" in o:
            eff.drawing_only.append(o["drawing_only"])
        elif "expected_count" in o:
            eff.expected_counts[o["type"]] = int(o["expected_count"])
        elif o.get("silent"):
            eff.silent.add((o["feature"], o["attr"]))
        elif "value" in o:
            setattr(k.feature(o["feature"]), o["attr"], o["value"])
    return eff
