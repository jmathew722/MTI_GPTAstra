"""Answer-key data model, shared by keygen, crosscheck, profile and (later) the scorer.

Units are the drawing's units. Positions are in the part frame: origin at the reference
body's bounding-box minimum, axes as in the STEP file.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

KEY_VERSION = 1
FEATURE_TYPES = (
    "thru_hole", "blind_hole", "tapped_hole", "counterbore", "countersink", "bore",
    "turned_diameter", "boss", "slot", "pocket_step", "flat", "chamfer", "fillet", "hole_pattern",
)
HOLE_TYPES = ("thru_hole", "blind_hole", "tapped_hole", "counterbore", "countersink")


@dataclass
class Feature:
    id: str
    type: str
    axis: Optional[list[float]] = None      # unit vector (round features)
    center: Optional[list[float]] = None    # axis point at the open/start end
    d: Optional[float] = None               # (drill) diameter
    depth: Optional[float] = None           # axial length of the main diameter
    thru: Optional[bool] = None
    cbore_d: Optional[float] = None
    cbore_depth: Optional[float] = None
    csink_d: Optional[float] = None
    normal: Optional[list[float]] = None    # planar features
    offset: Optional[float] = None          # plane offset along normal
    size: Optional[list[float]] = None      # planar extents / slot [length, width]
    thread: str = ""                        # filled by crosscheck from a TAP callout
    members: list[str] = field(default_factory=list)   # hole_pattern member ids
    pattern: Optional[dict] = None          # hole_pattern: {"mode": circle|line|grid|set, ...}
    note: str = ""
    tol: dict = field(default_factory=dict)      # {"position"|"size"|"depth": tolerance} from linked drawing values
    links: dict = field(default_factory=dict)    # {"position"|"size"|"depth": [drawing values]} (crosscheck.link)

    def __post_init__(self):
        if self.type not in FEATURE_TYPES:
            raise ValueError(f"unknown feature type {self.type!r}")


@dataclass
class Flag:
    kind: str                     # e.g. unexplained_key_value, unexplained_drawing_value, count_mismatch
    detail: str
    feature: Optional[str] = None
    resolution: Optional[str] = None   # set by a person: "accepted: ..." / "fixed key: ..."


@dataclass
class Key:
    part: str
    units: str
    source: str
    envelope: list[float]
    features: list[Feature]
    flags: list[Flag] = field(default_factory=list)
    signoff: Optional[dict] = None     # {"kind": "auto"|"human", "by": ..., "date": ..., "tool": ...}
    overrides: list = field(default_factory=list)   # structured drawing overrides (see bench.overrides)
    version: int = KEY_VERSION

    @property
    def signed(self) -> bool:
        return bool(self.signoff and self.signoff.get("kind") in ("auto", "human"))

    def open_flags(self) -> list[Flag]:
        return [f for f in self.flags if not f.resolution]

    def counts(self) -> dict[str, int]:
        return dict(Counter(f.type for f in self.features))

    def feature(self, fid: str) -> Feature:
        return next(f for f in self.features if f.id == fid)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Key":
        d = dict(d)
        d["features"] = [Feature(**f) for f in d.get("features", [])]
        d["flags"] = [Flag(**f) for f in d.get("flags", [])]
        return cls(**d)

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Key":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
