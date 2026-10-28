# Benchmark Dataset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `bench/`, the tooling that turns MTI's 14 clean drawing–model pairs into a frozen, confidential benchmark: PDFs, reference STEPs, answer keys checked against the DWG dimensions, review sheets, and a feature-type profile, at no API cost.

**Architecture:** Small single-purpose modules under `2D-3D-CAD-Test-Generation/bench/`:
- pure-Python core, tested on any OS: `features`, `keygen`, `callouts`, `dxfread`, `crosscheck`, `split`, `profile`, `review`
- thin tool wrappers: `sw_tasks` (SolidWorks, Windows) and `oda` (ODA File Converter)
- one resumable CLI: `prep`

MTI files live outside git in `MTI_BENCH_DATA` (read via python-dotenv). The split is a committed literal in `bench/manifest.yaml`, and `split.py` proves it reproduces from seed 20261023.

**Tech Stack:** Python 3.14, CadQuery 2.8 / OCP (STEP reading, B-rep analysis), ezdxf 1.4 (DXF dimensions), PyMuPDF (PDF crop, render), pywin32 (SolidWorks COM, lazy import), python-dotenv, pytest.

**Spec:** `docs/superpowers/specs/2026-10-23-benchmark-dataset-design.md`

---

## Conventions for every task

- **Worktree:** `C:\Users\USER\mti-2d-3d\.claude\worktrees\combined-sw2024`, branch `bench/dataset`. Run commands from `2D-3D-CAD-Test-Generation\`.
- **Python:** `$PY = "C:\Users\USER\mti-2d-3d\.claude\worktrees\repro-sw2024\2D-3D-CAD-Test-Generation\.venv\Scripts\python.exe"` (this worktree has no venv; same requirements).
- **Environment:** always set `$env:PYTHONUTF8=1`. Blank API keys while testing: `$env:OPENAI_API_KEY=''; $env:ANTHROPIC_API_KEY=''`. Nothing in this plan calls an API.
- **Commits:** local only, with the attribution line. **Never push.** Never `git add -A`. Add the exact files listed.
  - **Do not stage** the pre-existing uncommitted files: `pipeline/solidworks_builder.py`, `docs/solidworks-macro-error-log.md`, `tests/test_save_model.py` (the E025 save fix, deliberately left uncommitted).
  - **Do not stage** anything under `output/sw2024_check/`.
- **SolidWorks** (Tasks 10, 13): start `SLDWORKS.exe` by hand-off (`Start-Process`) and wait until `GetActiveObject('SldWorks.Application')` succeeds before running. COM drops after idle minutes, so run batches promptly.
- **Confidential data:** never copy anything from `MTI_BENCH_DATA` into the repo.

## File map

| File | Responsibility |
|---|---|
| `bench/__init__.py` | package marker |
| `bench/config.py` | resolve `MTI_BENCH_DATA` / `ODA_CONVERTER` from env or `.env`; clear errors |
| `bench/features.py` | answer-key data model (`Feature`, `Flag`, `Key`), JSON I/O, feature-type vocabulary |
| `bench/keygen.py` | STEP/solid → `Key` (holes, counterbores, countersinks, bores, turned diameters, bosses, slots, flats, steps, chamfers, fillets, patterns, envelope) |
| `bench/callouts.py` | parse drafting hole callouts (`.500-13 TAP THRU (3) HLS.`) |
| `bench/dxfread.py` | DXF → `Drawing` (dimensions with shown values, callouts, general tolerance, units hint) |
| `bench/crosscheck.py` | key ↔ drawing match → flags; sign-off rules |
| `bench/split.py` | the 21 pairs as data; seeded format-dev pick; manifest helpers |
| `bench/profile.py` | feature-type counts, comparisons, bias flags, `profile.html` |
| `bench/review.py` | one-page `review.html` per part |
| `bench/sw_tasks.py` | SolidWorks: DWG→PDF (+crop), SLDPRT→STEP (+png). Lazy `win32com` |
| `bench/oda.py` | DWG→DXF via ODA File Converter |
| `bench/prep.py` | CLI: `copy pdf dxf step keys check review profile signoff status` |
| `bench/manifest.yaml` | **modify:** add the format-dev, held-out and parked entries |
| `tests/test_bench_*.py` | one test file per module |
| `tests/test_bench_manifest.py` | **modify:** support data-root parts |
| `.env.template` | **modify:** document `MTI_BENCH_DATA`, `ODA_CONVERTER` |

---

### Task 1: Package skeleton and data-root configuration

**Files:**
- Create: `bench/__init__.py`, `bench/config.py`
- Test: `tests/test_bench_config.py`
- Modify: `.env.template` (append)

- [ ] **Step 1: Write the failing test**

`tests/test_bench_config.py`:
```python
"""bench.config: data root / ODA path from env or .env, never hard-coded."""
import pytest

from bench import config


def test_env_var_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("MTI_BENCH_DATA", str(tmp_path))
    assert config.data_root() == tmp_path


def test_missing_root_raises_with_instructions(monkeypatch, tmp_path):
    monkeypatch.setenv("MTI_BENCH_DATA", str(tmp_path / "nope"))
    with pytest.raises(config.BenchConfigError) as e:
        config.data_root()
    msg = str(e.value)
    assert "MTI_BENCH_DATA" in msg and ".env" in msg


def test_optional_returns_none(monkeypatch):
    monkeypatch.delenv("MTI_BENCH_DATA", raising=False)
    monkeypatch.setattr(config, "_load_dotenv", lambda: None)
    assert config.data_root(required=False) is None


def test_dotenv_is_read(tmp_path, monkeypatch):
    monkeypatch.delenv("MTI_BENCH_DATA", raising=False)
    env = tmp_path / ".env"
    env.write_text(f"MTI_BENCH_DATA={tmp_path}\n", encoding="utf-8")
    monkeypatch.setattr(config, "DOTENV", env)
    assert config.data_root() == tmp_path


def test_part_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MTI_BENCH_DATA", str(tmp_path))
    assert config.part_dir("A050071E") == tmp_path / "A050071E"


def test_oda_converter(tmp_path, monkeypatch):
    exe = tmp_path / "ODAFileConverter.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("ODA_CONVERTER", str(exe))
    assert config.oda_converter() == exe
    monkeypatch.setenv("ODA_CONVERTER", str(tmp_path / "missing.exe"))
    with pytest.raises(config.BenchConfigError, match="ODA_CONVERTER"):
        config.oda_converter()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `& $PY -m pytest tests/test_bench_config.py -q -p no:cacheprovider`
Expected: FAIL, `ModuleNotFoundError: No module named 'bench'`.

- [ ] **Step 3: Implement**

`bench/__init__.py`:
```python
"""MTI benchmark dataset tooling (spec: docs/superpowers/specs/2026-10-23-benchmark-dataset-design.md)."""
```

`bench/config.py`:
```python
"""Where the confidential benchmark data lives. Nothing machine-specific is hard-coded:
the data root comes from MTI_BENCH_DATA (a real environment variable wins over .env)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

CODE_ROOT = Path(__file__).resolve().parent.parent
DOTENV = CODE_ROOT / ".env"
DATA_ENV = "MTI_BENCH_DATA"
ODA_ENV = "ODA_CONVERTER"


class BenchConfigError(RuntimeError):
    """A required benchmark setting is missing or points nowhere."""


def _load_dotenv() -> None:
    from dotenv import load_dotenv
    load_dotenv(DOTENV, override=False)


def _setting(name: str, example: str, required: bool, want_dir: bool) -> Optional[Path]:
    _load_dotenv()
    raw = os.getenv(name)
    path = Path(raw) if raw else None
    ok = path is not None and (path.is_dir() if want_dir else path.is_file())
    if ok:
        return path
    if not required:
        return None
    where = f"'{raw}' does not exist" if raw else "it is not set"
    raise BenchConfigError(
        f"{name}: {where}. Add a line like\n    {name}={example}\n"
        f"to {DOTENV} (git-ignored) or set it as an environment variable.")


def data_root(required: bool = True) -> Optional[Path]:
    return _setting(DATA_ENV, r"C:\path\to\MTI Example Drawings\bench", required, want_dir=True)


def part_dir(part: str) -> Path:
    return data_root() / part


def oda_converter(required: bool = True) -> Optional[Path]:
    return _setting(ODA_ENV, r"C:\Program Files\ODA\ODAFileConverter 26.x\ODAFileConverter.exe",
                    required, want_dir=False)
```

Append to `.env.template`:
```
# Benchmark data (confidential MTI drawings/models; NEVER inside the repo).
# Folder holding <part>/drawing.pdf, reference.step, key.json, ... (spec 2026-10-23).
# MTI_BENCH_DATA=C:\path\to\MTI Example Drawings\bench
# ODA File Converter (free, opendesign.com) for DWG -> DXF.
# ODA_CONVERTER=C:\Program Files\ODA\ODAFileConverter <version>\ODAFileConverter.exe
```

- [ ] **Step 4: Run the tests**

Run: `& $PY -m pytest tests/test_bench_config.py -q -p no:cacheprovider`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```powershell
git add bench/__init__.py bench/config.py tests/test_bench_config.py .env.template
git commit -m "feat(bench): data-root configuration from MTI_BENCH_DATA (.env or env var)`n`nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Answer-key data model

**Files:**
- Create: `bench/features.py`
- Test: `tests/test_bench_features.py`

- [ ] **Step 1: Write the failing test**

`tests/test_bench_features.py`:
```python
"""bench.features: answer-key model round-trips through JSON; counts and sign-off state."""
from bench.features import FEATURE_TYPES, Feature, Flag, Key


def _key():
    return Key(part="P1", units="inch", source="reference.step", envelope=[4.0, 3.0, 1.0],
               features=[Feature(id="K001", type="thru_hole", axis=[0, 0, 1], center=[1, 1, 0], d=0.25,
                                 depth=1.0, thru=True),
                         Feature(id="K002", type="thru_hole", axis=[0, 0, 1], center=[3, 1, 0], d=0.25,
                                 depth=1.0, thru=True),
                         Feature(id="K003", type="hole_pattern", members=["K001", "K002"],
                                 pattern={"mode": "line", "count": 2})],
               flags=[Flag(kind="unexplained_key_value", detail="d 0.25", feature="K001")])


def test_roundtrip(tmp_path):
    k = _key()
    p = tmp_path / "key.json"
    k.save(p)
    assert Key.load(p) == k


def test_counts_exclude_nothing_and_types_are_known():
    c = _key().counts()
    assert c == {"thru_hole": 2, "hole_pattern": 1}
    assert set(c) <= set(FEATURE_TYPES)


def test_signed_and_open_flags():
    k = _key()
    assert not k.signed and k.open_flags() == k.flags
    k.flags[0].resolution = "accepted: drawing gives tap size"
    assert k.open_flags() == []
    k.signoff = {"kind": "human", "by": "smcanuff", "date": "2026-10-24"}
    assert k.signed


def test_unknown_type_rejected():
    import pytest
    with pytest.raises(ValueError):
        Feature(id="K9", type="spline_thing")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `& $PY -m pytest tests/test_bench_features.py -q -p no:cacheprovider`
Expected: FAIL, `ModuleNotFoundError: No module named 'bench.features'`.

- [ ] **Step 3: Implement**

`bench/features.py`:
```python
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
```

- [ ] **Step 4: Run the tests**

Run: `& $PY -m pytest tests/test_bench_features.py -q -p no:cacheprovider`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```powershell
git add bench/features.py tests/test_bench_features.py
git commit -m "feat(bench): answer-key data model (Feature, Flag, Key)`n`nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: keygen, round features (holes, counterbores, bores, turned diameters)

**Files:**
- Create: `bench/keygen.py`
- Test: `tests/test_bench_keygen.py`

The test oracle is the CadQuery reference build of the existing golden plans. `build(...).model.measure_holes()` reports each planned hole's diameter, axis and depth in drawing units (verified 2026-10-23):
- `demo_plate` (mm): four Ø8 thru holes on a 2×2 grid, plus a Ø20 thru bore
- `SB11033` (inch): four Ø0.218 thru holes on an r = 0.781 circle
- `A040911E` (inch): three Ø0.281 thru holes with Ø0.438 × 0.38 counterbores, two Ø0.3125 × 1.0 blind holes, a Ø4.5 bore and a Ø6.498 outside diameter

- [ ] **Step 1: Write the failing test**

`tests/test_bench_keygen.py`:
```python
"""bench.keygen recovers the planned round features of the golden plans (CadQuery reference)."""
import itertools
import json
import math
from pathlib import Path

import pytest

cq = pytest.importorskip("cadquery")
from bench.keygen import extract  # noqa: E402
from pipeline.ir.compile_cadquery import build  # noqa: E402
from pipeline.ir.model import BuildPlan  # noqa: E402

GOLD = Path(__file__).resolve().parent / "golden" / "ir"


def _golden(part):
    g = json.loads((GOLD / f"{part}.json").read_text(encoding="utf-8"))
    m = build(BuildPlan.model_validate(g["plan"]), {k: float(v) for k, v in g["dims"].items()},
              strict=False).model
    return m.solid, g["plan"]["frame"]["units"]


def _of(key, t):
    return [f for f in key.features if f.type == t]


def _dist(a, b):
    return math.dist(a, b)


def test_demo_plate_holes():
    solid, units = _golden("demo_plate")
    key = extract(solid, units=units, part="demo_plate", source="memory")
    holes = _of(key, "thru_hole")
    assert sorted(round(h.d, 6) for h in holes) == [8.0, 8.0, 8.0, 8.0, 20.0]
    small = [h for h in holes if abs(h.d - 8) < 1e-6]
    # frame-free check: the 4 corner holes form an 80 x 40 rectangle (pairwise distances)
    ds = sorted(round(_dist(a.center[:2], b.center[:2]), 6) for a, b in itertools.combinations(small, 2))
    assert ds == pytest.approx([40.0, 40.0, 80.0, 80.0, math.hypot(80, 40), math.hypot(80, 40)], abs=1e-5)
    assert all(h.thru for h in holes)
    assert key.envelope == pytest.approx([100.0, 60.0, 10.0], abs=1e-6)
    pats = _of(key, "hole_pattern")
    assert len(pats) == 1 and pats[0].pattern["mode"] == "grid" and len(pats[0].members) == 4


def test_sb11033_bolt_circle():
    solid, units = _golden("SB11033")
    key = extract(solid, units=units, part="SB11033", source="memory")
    holes = [h for h in _of(key, "thru_hole") if abs(h.d - 0.218) < 1e-6]
    assert len(holes) == 4
    pats = [p for p in _of(key, "hole_pattern") if p.pattern["mode"] == "circle"]
    assert len(pats) == 1 and pats[0].pattern["radius"] == pytest.approx(0.781, abs=1e-5)
    assert _of(key, "turned_diameter"), "the flange OD is a turned diameter"


def test_a040911e_counterbores_blind_holes_bore():
    solid, units = _golden("A040911E")
    key = extract(solid, units=units, part="A040911E", source="memory")
    cb = _of(key, "counterbore")
    assert len(cb) == 3
    for f in cb:
        assert f.d == pytest.approx(0.281, abs=1e-5)
        assert f.cbore_d == pytest.approx(0.438, abs=1e-5)
        assert f.cbore_depth == pytest.approx(0.38, abs=1e-5)
        assert f.thru is True
    blind = _of(key, "blind_hole")
    assert sorted(round(f.d, 5) for f in blind) == [0.3125, 0.3125]
    assert all(f.depth == pytest.approx(1.0, abs=1e-5) for f in blind)
    assert [round(f.d, 4) for f in _of(key, "bore")] == [4.5]
    assert 6.498 in [round(f.d, 4) for f in _of(key, "turned_diameter")]


def test_rejects_multi_solid():
    a = cq.Workplane().box(1, 1, 1).val()
    b = cq.Workplane().box(1, 1, 1).translate((5, 0, 0)).val()
    from bench.keygen import KeygenError
    with pytest.raises(KeygenError, match="2 solids"):
        extract(cq.Compound.makeCompound([a, b]), units="mm", part="x", source="memory")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `& $PY -m pytest tests/test_bench_keygen.py -q -p no:cacheprovider`
Expected: FAIL, `ModuleNotFoundError: No module named 'bench.keygen'`.

- [ ] **Step 3: Implement**

`bench/keygen.py`:
```python
"""Reference body -> answer key (spec 2026-10-23, "Answer keys").

Works on the B-rep with OCP. Round features come from cylindrical and conical faces grouped
by axis line. Each cylinder group is classified as concave (material outside it: a hole or
bore) or convex (a boss or turned diameter) by testing a point just outside the surface
against the solid. Heuristics are deliberate and documented. The cross-check and the review
sheet catch what they miss.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Optional

from bench.features import HOLE_TYPES, Feature, Key

MM_PER = {"mm": 1.0, "inch": 25.4}
LIN_TOL = 1e-4          # mm: same axis line / radius
FULL_TURN = 2 * math.pi - 1e-6


class KeygenError(RuntimeError):
    pass


def _v(p) -> tuple[float, float, float]:
    return (p.X(), p.Y(), p.Z())


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    n = math.sqrt(_dot(a, a))
    return _mul(a, 1 / n)


def _canon(d):
    """Direction with its first non-zero component positive (so +Z and -Z group)."""
    for c in d:
        if abs(c) > 1e-9:
            return d if c > 0 else _mul(d, -1)
    return d


@dataclass
class _Round:
    """Cylinders/cones sharing one axis line and radius."""
    kind: str                 # "cyl" | "cone"
    origin: tuple             # point on the axis line (closest to the global origin)
    axis: tuple               # canonical unit direction
    r: float                  # cylinder radius, or cone's larger radius
    r2: float = 0.0           # cone's smaller radius
    span: float = 0.0         # summed angular span (radians)
    t0: float = math.inf      # axial interval along axis from origin
    t1: float = -math.inf
    concave: Optional[bool] = None

    def same_line(self, origin, axis) -> bool:
        if abs(abs(_dot(self.axis, axis)) - 1) > 1e-6:
            return False
        d = _sub(origin, self.origin)
        off = _sub(d, _mul(self.axis, _dot(d, self.axis)))
        return math.sqrt(_dot(off, off)) < LIN_TOL


@dataclass
class _Plane:
    normal: tuple
    offset: float
    area: float
    bbox: tuple               # (xmin, ymin, zmin, xmax, ymax, zmax)


def _line_origin(loc, axis):
    """Point on the line closest to the global origin: a stable id for the line."""
    return _sub(loc, _mul(axis, _dot(loc, axis)))


def _solid_of(shape):
    solids = shape.Solids() if hasattr(shape, "Solids") else [shape]
    if len(solids) != 1:
        raise KeygenError(f"reference has {len(solids)} solids; a benchmark part must be one solid")
    return solids[0]


def _scan(solid):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane
    import cadquery as cq

    rounds: list[_Round] = []
    planes: list[_Plane] = []
    for face in solid.Faces():
        a = BRepAdaptor_Surface(face.wrapped)
        t = a.GetType()
        u0, u1, v0, v1 = a.FirstUParameter(), a.LastUParameter(), a.FirstVParameter(), a.LastVParameter()
        if t in (GeomAbs_Cylinder, GeomAbs_Cone):
            g = a.Cylinder() if t == GeomAbs_Cylinder else a.Cone()
            ax = g.Axis()
            loc, raw_dir = _v(ax.Location()), _norm(_v(ax.Direction()))
            axis = _canon(raw_dir)
            origin = _line_origin(loc, axis)
            # axial interval and radius from surface samples
            pts = [_v(a.Value(u, v)) for u in (u0, (u0 + u1) / 2) for v in (v0, v1)]
            ts = [_dot(_sub(p, origin), axis) for p in pts]
            radii = []
            for p, tt in zip(pts, ts):
                foot = _add(origin, _mul(axis, tt))
                radii.append(math.dist(p, foot))
            r, r2 = max(radii), min(radii)
            kind = "cyl" if t == GeomAbs_Cylinder else "cone"
            # concave test at the middle of the face
            pm = _v(a.Value((u0 + u1) / 2, (v0 + v1) / 2))
            tm = _dot(_sub(pm, origin), axis)
            radial = _norm(_sub(pm, _add(origin, _mul(axis, tm))))
            eps = max(min(0.01, 0.01 * r), 1e-4)
            concave = solid.isInside(cq.Vector(*_add(pm, _mul(radial, eps))))
            grp = next((g_ for g_ in rounds if g_.kind == kind and g_.same_line(origin, axis)
                        and abs(g_.r - r) < LIN_TOL and abs(g_.r2 - (r2 if kind == "cone" else 0)) < LIN_TOL
                        and g_.concave == concave), None)
            if grp is None:
                grp = _Round(kind, origin, axis, r, r2 if kind == "cone" else 0.0, concave=concave)
                rounds.append(grp)
            grp.span += abs(u1 - u0)
            grp.t0, grp.t1 = min(grp.t0, *ts), max(grp.t1, *ts)
        elif t == GeomAbs_Plane:
            pl = a.Plane()
            n = _canon(_norm(_v(pl.Axis().Direction())))
            p = _v(pl.Location())
            bb = face.BoundingBox()
            planes.append(_Plane(n, _dot(p, n), face.Area(), (bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax)))
    return rounds, planes


def _closed_beyond(solid, origin, axis, t, outward):
    """True if the material closes the axis just beyond t (a blind bottom or shoulder)."""
    import cadquery as cq
    p = _add(origin, _mul(axis, t + outward * 1e-3))
    return solid.isInside(cq.Vector(*p))


def extract(shape, *, units: str, part: str, source: str) -> Key:
    """Reference body (cadquery Shape, millimetres) -> Key in drawing units."""
    if units not in MM_PER:
        raise KeygenError(f"unknown units {units!r}")
    k = MM_PER[units]
    solid = _solid_of(shape)
    bb = solid.BoundingBox()
    lo = (bb.xmin, bb.ymin, bb.zmin)
    env = [bb.xlen / k, bb.ylen / k, bb.zlen / k]
    rounds, planes = _scan(solid)

    feats: list[Feature] = []
    nid = iter(range(1, 10_000))

    def new(type_, **kw) -> Feature:
        f = Feature(id=f"K{next(nid):03d}", type=type_, **kw)
        feats.append(f)
        return f

    def frame(p):                       # mm global -> part frame, drawing units
        return [(p[i] - lo[i]) / k for i in range(3)]

    full = [g for g in rounds if g.kind == "cyl" and g.span >= FULL_TURN]
    partial = [g for g in rounds if g.kind == "cyl" and g.span < FULL_TURN]
    cones = [g for g in rounds if g.kind == "cone"]

    # turned axis: the largest convex full cylinder that forms the outer envelope
    turned = None
    convex = sorted((g for g in full if not g.concave), key=lambda g: -g.r)
    if convex:
        g = convex[0]
        perp = [e * k for e, c in zip(env, g.axis) if abs(c) < 0.5]
        if perp and 2 * g.r >= 0.9 * max(perp):
            turned = g

    # group concave full cylinders by axis line -> holes / counterbores / bores
    lines: list[list[_Round]] = []
    for g in (g for g in full if g.concave):
        for ln in lines:
            if ln[0].same_line(g.origin, g.axis):
                ln.append(g)
                break
        else:
            lines.append([g])
    for ln in lines:
        ln.sort(key=lambda g: g.r)
        drill = ln[0]
        on_turned_axis = turned is not None and turned.same_line(drill.origin, drill.axis)
        lo_open = not _closed_beyond(solid, drill.origin, drill.axis, drill.t0, -1)
        hi_open = not _closed_beyond(solid, drill.origin, drill.axis, drill.t1, +1)
        # the counterbore (if any) extends the opening on one side
        cb = ln[1] if len(ln) >= 2 else None
        if cb is not None:
            if abs(cb.t1 - drill.t0) < 1e-3 or abs(cb.t0 - drill.t1) < 1e-3:
                lo_open = lo_open or abs(cb.t1 - drill.t0) < 1e-3
                hi_open = hi_open or abs(cb.t0 - drill.t1) < 1e-3
            else:
                cb = None
        thru = lo_open and hi_open
        start_t = drill.t0 if lo_open else drill.t1
        if cb is not None:
            start_t = cb.t0 if abs(cb.t1 - drill.t0) < 1e-3 else cb.t1
        center = frame(_add(drill.origin, _mul(drill.axis, start_t)))
        kw = dict(axis=list(drill.axis), center=center, d=2 * drill.r / k,
                  depth=(drill.t1 - drill.t0) / k, thru=thru)
        if on_turned_axis:
            new("bore", **kw)
        elif cb is not None:
            new("counterbore", cbore_d=2 * cb.r / k, cbore_depth=(cb.t1 - cb.t0) / k, **kw)
        else:
            new("thru_hole" if thru else "blind_hole", **kw)
        for extra in ln[2 if cb is not None else 1:]:
            new("bore", axis=list(extra.axis), center=frame(_add(extra.origin, _mul(extra.axis, extra.t0))),
                d=2 * extra.r / k, depth=(extra.t1 - extra.t0) / k, note="further step on the same axis")

    # convex full cylinders -> turned diameters (on the turned axis) or bosses
    for g in (g for g in full if not g.concave):
        kw = dict(axis=list(g.axis), center=frame(_add(g.origin, _mul(g.axis, g.t0))),
                  d=2 * g.r / k, depth=(g.t1 - g.t0) / k)
        if turned is not None and turned.same_line(g.origin, g.axis):
            new("turned_diameter", **kw)
        else:
            new("boss", **kw)

    _cones_and_partials(new, frame, k, cones, partial, feats)
    _planar(new, k, lo, env, planes, turned)
    _patterns(new, feats)
    return Key(part=part, units=units, source=source, envelope=env, features=feats)


def _cones_and_partials(new, frame, k, cones, partial, feats):
    """Cones: countersink when on a hole axis and >1.25x the hole; else chamfer.
    Partial cylinders: <= quarter turn -> fillet; about a half turn -> slot end."""
    holes = [f for f in feats if f.type in HOLE_TYPES or f.type == "bore"]
    for c in cones:
        host = next((h for h in holes if abs(abs(_dot(tuple(h.axis), c.axis)) - 1) < 1e-6
                     and _on_axis(h, c, frame)), None)
        big = 2 * c.r / k
        if host is not None and c.concave and big > 1.25 * host.d and host.type in HOLE_TYPES:
            host.type = "countersink" if host.type != "counterbore" else host.type
            host.csink_d = big
        else:
            new("chamfer", axis=list(c.axis), center=frame(_add(c.origin, _mul(c.axis, c.t0))),
                d=big, depth=(c.t1 - c.t0) / k, note="conical edge break")
    for p in partial:
        if p.span <= math.pi / 2 + 1e-3:
            new("fillet", axis=list(p.axis), d=2 * p.r / k, depth=(p.t1 - p.t0) / k,
                center=frame(_add(p.origin, _mul(p.axis, p.t0))))
        elif p.concave:
            new("slot", axis=list(p.axis), d=2 * p.r / k, depth=(p.t1 - p.t0) / k,
                center=frame(_add(p.origin, _mul(p.axis, p.t0))), size=[0.0, 2 * p.r / k],
                note="round slot/notch end (width = d)")


def _on_axis(hole: Feature, c: _Round, frame) -> bool:
    h0 = [hole.center[i] for i in range(3)]
    p = frame(c.origin)
    d = [p[i] - h0[i] for i in range(3)]
    ax = hole.axis
    t = sum(d[i] * ax[i] for i in range(3))
    off = [d[i] - ax[i] * t for i in range(3)]
    return math.sqrt(sum(x * x for x in off)) < 1e-3


def _planar(new, k, lo, env, planes, turned):
    """Planar faces that are not on the bounding box: flats (on turned parts, parallel to the
    turned axis) or pocket/step faces. Grouped by (normal, offset)."""
    bbox_offsets = {}
    for i in range(3):
        bbox_offsets[i] = (lo[i], lo[i] + env[i] * k)
    seen = []
    for pl in planes:
        axis_i = next((i for i in range(3) if abs(abs(pl.normal[i]) - 1) < 1e-6), None)
        if axis_i is not None and any(abs(pl.offset * (1 if pl.normal[axis_i] > 0 else -1) - b) < 1e-4
                                      for b in bbox_offsets[axis_i]):
            continue                       # an outer envelope face
        keyv = (tuple(round(c, 6) for c in pl.normal), round(pl.offset, 4))
        if keyv in seen:
            continue
        seen.append(keyv)
        ext = [(pl.bbox[i + 3] - pl.bbox[i]) / k for i in range(3)]
        if turned is not None and turned.concave is False and abs(_dot(pl.normal, turned.axis)) < 1e-6:
            new("flat", normal=list(pl.normal), offset=pl.offset / k, size=ext)
        elif turned is not None and abs(abs(_dot(pl.normal, turned.axis)) - 1) < 1e-6:
            continue                       # shoulder faces of a turned part: implied by diameters
        else:
            new("pocket_step", normal=list(pl.normal), offset=pl.offset / k, size=ext)


def _patterns(new, feats):
    """Same-type, same-size holes on parallel axes: grid (4 at rectangle corners), circle (3+
    concyclic), line (3+ collinear), else set (2+)."""
    holes = [f for f in feats if f.type in HOLE_TYPES]
    groups: list[list[Feature]] = []
    for h in holes:
        for g in groups:
            if g[0].type == h.type and abs(g[0].d - h.d) < 1e-6 and \
                    abs(abs(sum(a * b for a, b in zip(g[0].axis, h.axis))) - 1) < 1e-6:
                g.append(h)
                break
        else:
            groups.append([h])
    for g in groups:
        if len(g) < 2:
            continue
        pts = _project(g)
        mode, extra = "set", {}
        if len(pts) == 4 and _is_rectangle(pts):
            mode = "grid"
        elif len(pts) >= 3 and (circ := _circle(pts)) is not None:
            mode, extra = "circle", {"radius": circ[1], "center_2d": list(circ[0])}
        elif len(pts) >= 3 and _collinear(pts):
            mode = "line"
        new("hole_pattern", members=[h.id for h in g], pattern={"mode": mode, "count": len(g), **extra},
            d=g[0].d)


def _project(g: list[Feature]) -> list[tuple[float, float]]:
    ax = g[0].axis
    ref = (1.0, 0.0, 0.0) if abs(ax[0]) < 0.9 else (0.0, 1.0, 0.0)
    e1 = _norm(_sub(ref, _mul(tuple(ax), _dot(ref, tuple(ax)))))
    e2 = (ax[1] * e1[2] - ax[2] * e1[1], ax[2] * e1[0] - ax[0] * e1[2], ax[0] * e1[1] - ax[1] * e1[0])
    return [(_dot(tuple(h.center), e1), _dot(tuple(h.center), e2)) for h in g]


def _is_rectangle(p) -> bool:
    c = (sum(x for x, _ in p) / 4, sum(y for _, y in p) / 4)
    r = [math.dist(c, q) for q in p]
    if max(r) - min(r) > 1e-6:
        return False
    ds = sorted(math.dist(a, b) for a, b in combinations(p, 2))
    return abs(ds[0] - ds[1]) < 1e-6 and abs(ds[2] - ds[3]) < 1e-6 and abs(ds[4] - ds[5]) < 1e-6


def _circle(p):
    (ax, ay), (bx, by), (cx, cy) = p[:3]
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    ux = ((ax**2 + ay**2) * (by - cy) + (bx**2 + by**2) * (cy - ay) + (cx**2 + cy**2) * (ay - by)) / d
    uy = ((ax**2 + ay**2) * (cx - bx) + (bx**2 + by**2) * (ax - cx) + (cx**2 + cy**2) * (bx - ax)) / d
    r = math.dist((ux, uy), p[0])
    return ((ux, uy), r) if all(abs(math.dist((ux, uy), q) - r) < 1e-5 for q in p) else None


def _collinear(p) -> bool:
    (x1, y1), (x2, y2) = p[0], p[-1]
    L = math.dist((x1, y1), (x2, y2)) or 1.0
    return all(abs((x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)) / L < 1e-5 for x, y in p)


def from_step(step: Path, *, units: str, part: str) -> Key:
    import cadquery as cq
    shape = cq.importers.importStep(str(step)).val()
    return extract(shape, units=units, part=part, source=Path(step).name)
```

- [ ] **Step 4: Run the tests and iterate**

Run: `& $PY -m pytest tests/test_bench_keygen.py -q -p no:cacheprovider`
Expected: 4 passed. If an assertion fails, print the key and adjust the classification. Do not loosen the oracle values, which come from the golden plans:
`& $PY -c "import json; from tests.test_bench_keygen import _golden; from bench.keygen import extract; s,u=_golden('A040911E'); print(json.dumps(extract(s,units=u,part='x',source='m').to_dict(), indent=1)[:4000])"`

- [ ] **Step 5: Commit**

```powershell
git add bench/keygen.py tests/test_bench_keygen.py
git commit -m "feat(bench): keygen recovers holes, counterbores, bores, turned diameters, patterns from a reference body`n`nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: keygen, planar features and countersinks

**Files:**
- Modify: `bench/keygen.py` (only if a test fails)
- Test: `tests/test_bench_keygen.py` (append)

- [ ] **Step 1: Append failing tests**

```python
def test_countersink_vs_chamfer():
    plate = (cq.Workplane().box(40, 30, 6)
             .faces(">Z").workplane().pushPoints([(-10, 0)]).cskHole(5.0, 10.0, 82)
             .faces(">Z").workplane().pushPoints([(10, 0)]).hole(5.0)
             .faces(">Z").edges("%CIRCLE").chamfer(0.3))
    key = extract(plate.val(), units="mm", part="t", source="memory")
    cs = [f for f in key.features if f.type == "countersink"]
    assert len(cs) == 1 and cs[0].csink_d == pytest.approx(10.0, abs=0.05)
    holes = [f for f in key.features if f.type == "thru_hole"]
    assert len(holes) == 1 and holes[0].d == pytest.approx(5.0)


def test_flat_on_turned_shaft_and_pocket_on_plate():
    shaft = cq.Workplane("XY").circle(10).extrude(50).cut(
        cq.Workplane("XY").box(30, 30, 20).translate((0, 24, 25)))  # flat at y = 9
    key = extract(shaft.val(), units="mm", part="s", source="memory")
    flats = [f for f in key.features if f.type == "flat"]
    assert len(flats) == 1 and abs(abs(flats[0].normal[1]) - 1) < 1e-6
    plate = cq.Workplane().box(50, 30, 10).cut(cq.Workplane().box(20, 10, 4).translate((0, 0, 3)))
    k2 = extract(plate.val(), units="mm", part="p", source="memory")
    assert any(f.type == "pocket_step" for f in k2.features)
```

- [ ] **Step 2: Run, then implement until green**

Run: `& $PY -m pytest tests/test_bench_keygen.py -q -p no:cacheprovider`
Expected: all pass with Task 3's code. If `test_countersink_vs_chamfer` fails because the chamfer on the plain hole also became a countersink, check the 1.25× ratio in `_cones_and_partials` (a 0.3 mm chamfer on Ø5 gives Ø5.6 = 1.12×, so it should stay a chamfer). If `cskHole`'s cone and cylinder land on different axis lines, print `_scan` output and fix `_on_axis`.

- [ ] **Step 3: Commit**

```powershell
git add bench/keygen.py tests/test_bench_keygen.py
git commit -m "test(bench): keygen countersinks, chamfers, flats and pockets`n`nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Hole-callout parser

**Files:**
- Create: `bench/callouts.py`
- Test: `tests/test_bench_callouts.py`

- [ ] **Step 1: Write the failing test**

These are real callouts from the MTI drawings.

`tests/test_bench_callouts.py`:
```python
"""bench.callouts parses legacy hole callouts from the MTI drawings."""
import pytest

from bench.callouts import parse


@pytest.mark.parametrize("text, kind, d, thread, depth, thru, count", [
    (".500-13 TAP THRU (3) HLS.", "tap", None, ".500-13", None, True, 3),
    (".375-16 TAP .81 DP.", "tap", None, ".375-16", 0.81, False, 1),
    ("TAP M10X1.5 - .75 DP.\n4-HOLES", "tap", None, "M10X1.5", 0.75, False, 4),
    (".344 DR. THRU & .562 C'BORE\n.47 DP. 4 HOLES", "cbore", 0.344, "", 0.47, True, 4),
    ("DR. & C'BORE .38 DP. FOR .250 S.H.C.S. 6-HLS.", "cbore", None, "", 0.38, False, 6),
    (".281 DR. THRU", "drill", 0.281, "", None, True, 1),
    ("DR. & C'SINK FOR .250 FLAT HD. SCR. 12-HOLES", "csink", None, "", None, False, 12),
    (".344 DIA. THRU (6) HLS.", "drill", 0.344, "", None, True, 6),
])
def test_parse(text, kind, d, thread, depth, thru, count):
    c = parse(text)
    assert c is not None
    assert (c.kind, c.d, c.thread, c.depth, c.thru, c.count) == (kind, d, thread, depth, thru, count)


def test_screw_size():
    assert parse("DR. & C'BORE FOR #10 SOC. HD. CAP SCR. 8-HOLES AS SHOWN").screw == "#10"
    assert parse("DR. & C'BORE .38 DP. FOR .250 S.H.C.S. 6-HLS.").screw == ".250"


def test_not_a_callout():
    assert parse("4140 STL.") is None
    assert parse("BREAK SHARP EDGES") is None


def test_nominal_diameter_of_thread():
    assert parse(".500-13 TAP THRU").nominal == 0.5
    assert parse("TAP M10X1.5").nominal == pytest.approx(10 / 25.4)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `& $PY -m pytest tests/test_bench_callouts.py -q -p no:cacheprovider`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`bench/callouts.py`:
```python
"""Parse drafting hole callouts (legacy MTI style) into structured facts.

Depth is a value followed by DP; the "C'BORE .38 DP." form gives the counterbore depth.
A count comes from "(3) HLS", "6-HLS", "4 HOLES", "12-HOLES", "4X". Nominal thread size
is in inches.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

NUM = r"(\d*\.\d+|\d+(?:/\d+)?)"
_THREAD_IN = re.compile(r"(#\d+|\d*\.\d+|\d+/\d+|\d+)\s*-\s*(\d+)(?:\s*UN[CF])?\s*TAP")
_THREAD_M = re.compile(r"M(\d+(?:\.\d+)?)\s*X\s*(\d+(?:\.\d+)?)")
_COUNT = re.compile(r"\((\d+)\)\s*HLS?|(\d+)\s*-\s*HLS?|(\d+)\s*-?\s*HOLES?|\b(\d+)\s*X\b")
_DEPTH = re.compile(NUM + r"\s*DP")
_DRILL = re.compile(NUM + r"\s*(?:DR\b|DR\.|DRILL|DIA\.?|%%C|Ø)")
_SCREW = re.compile(r"FOR\s+(#\d+|\d*\.\d+|\d+/\d+)\s*(?:SOC|S\.?H\.?C\.?S|FLAT|SHCS|CAP)")
_SCREW_NO = {"#4": 0.112, "#5": 0.125, "#6": 0.138, "#8": 0.164, "#10": 0.190, "#12": 0.216}


def _num(s: str) -> float:
    if "/" in s:
        a, b = s.split("/")
        return float(a) / float(b)
    return float(s)


@dataclass
class Callout:
    kind: str                 # tap | cbore | csink | drill
    text: str
    d: Optional[float] = None
    thread: str = ""
    depth: Optional[float] = None
    thru: bool = False
    count: int = 1
    screw: str = ""

    @property
    def nominal(self) -> Optional[float]:
        """Thread major diameter in inches (None if not a tap)."""
        if not self.thread:
            return None
        if self.thread.startswith("M"):
            return float(_THREAD_M.match(self.thread).group(1)) / 25.4
        size = self.thread.split("-")[0]
        return _SCREW_NO[size] if size.startswith("#") else _num(size)


def parse(text: str) -> Optional[Callout]:
    t = " ".join(text.upper().replace("\\P", " ").split())
    is_cbore = "C'BORE" in t or "CBORE" in t or "COUNTERBORE" in t
    is_csink = "C'SINK" in t or "CSINK" in t or "CSK" in t or "COUNTERSINK" in t
    m_in, m_m = _THREAD_IN.search(t), _THREAD_M.search(t)
    if m_m and "TAP" in t:
        kind, thread = "tap", f"M{m_m.group(1)}X{m_m.group(2)}"
    elif m_in:
        kind, thread = "tap", f"{m_in.group(1)}-{m_in.group(2)}"
    elif is_cbore:
        kind, thread = "cbore", ""
    elif is_csink:
        kind, thread = "csink", ""
    elif _DRILL.search(t) or ("THRU" in t and re.search(NUM, t)):
        kind, thread = "drill", ""
    else:
        return None
    m = _COUNT.search(t)
    count = int(next(g for g in m.groups() if g)) if m else 1
    dm = _DEPTH.search(t)
    depth = _num(dm.group(1)) if dm else None
    dr = _DRILL.search(t)
    d = _num(dr.group(1)) if dr and kind != "tap" else None
    sm = _SCREW.search(t)
    return Callout(kind=kind, text=text, d=d, thread=thread, depth=depth, thru="THRU" in t,
                   count=count, screw=sm.group(1) if sm else "")
```

- [ ] **Step 4: Run the tests**

Run: `& $PY -m pytest tests/test_bench_callouts.py -q -p no:cacheprovider`
Expected: 11 passed. If a regex misses a case, fix the regex. Do not change the expected values: they are the drawings' own text.

- [ ] **Step 5: Commit**

```powershell
git add bench/callouts.py tests/test_bench_callouts.py
git commit -m "feat(bench): parse legacy MTI hole callouts`n`nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: DXF reader (dimensions, callouts, general tolerance)

**Files:**
- Create: `bench/dxfread.py`
- Test: `tests/test_bench_dxfread.py`

ezdxf facts (verified 2026-10-23, ezdxf 1.4.4):
- `DIMENSION.dimtype & 7`: 0 linear, 1 aligned, 2 angular, 3 diameter, 4 radius, 5 angular 3-point, 6 ordinate.
- `get_measurement()` returns the true value.
- `dxf.text` is `''` or `'<>'` when the text is not overridden.
- `MTEXT.plain_text()` gives the text.

- [ ] **Step 1: Write the failing test**

`tests/test_bench_dxfread.py`:
```python
"""bench.dxfread: dimensions (shown value, override, scale), callouts, general tolerance."""
import pytest

ezdxf = pytest.importorskip("ezdxf")
from bench.dxfread import read  # noqa: E402


def _dxf(tmp_path, override=None):
    doc = ezdxf.new(setup=True)
    m = doc.modelspace()
    d = m.add_linear_dim(base=(0, 4), p1=(0, 0), p2=(4, 0), dimstyle="EZDXF",
                         override={} if override is None else {})
    if override is not None:
        d.dimension.dxf.text = override
    d.render()
    m.add_diameter_dim(center=(1, 1), radius=0.25, angle=45, dimstyle="EZDXF").render()
    m.add_mtext(".500-13 TAP THRU (3) HLS.")
    m.add_text("DECIMAL DIMENSIONS TO BE:")
    m.add_text(".000 %%P.010")
    m.add_text(".00 %%P.030")
    m.add_text("DIMENSIONS ARE IN INCHES")
    p = tmp_path / "t.dxf"
    doc.saveas(p)
    return p


def test_dimensions_and_callouts(tmp_path):
    dr = read(_dxf(tmp_path))
    kinds = sorted((x.kind, round(x.shown, 4)) for x in dr.dims)
    assert kinds == [("diameter", 0.5), ("linear", 4.0)]
    assert [c.thread for c in dr.callouts] == [".500-13"]
    assert dr.general_tol == {3: 0.010, 2: 0.030}
    assert dr.units_hint == "inch"


def test_override_text_is_what_the_drawing_says(tmp_path):
    dr = read(_dxf(tmp_path, override="4.250"))
    lin = next(x for x in dr.dims if x.kind == "linear")
    assert lin.shown == 4.25 and lin.measured == pytest.approx(4.0) and lin.not_to_scale


def test_decimals_of_shown_text(tmp_path):
    dr = read(_dxf(tmp_path, override="<> TYP."))
    lin = next(x for x in dr.dims if x.kind == "linear")
    assert lin.shown == pytest.approx(4.0) and not lin.not_to_scale and lin.text == "<> TYP."
```

- [ ] **Step 2: Run it to verify it fails**

Run: `& $PY -m pytest tests/test_bench_dxfread.py -q -p no:cacheprovider`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`bench/dxfread.py`:
```python
"""DXF (converted from MTI's DWG by ODA) -> what the drawing states.

A dimension's displayed text is what the drawing says. Legacy drawings often override the
text (not-to-scale views), so `shown` is the overridden number when there is one, else the
measurement times DIMLFAC.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from bench.callouts import Callout, parse

DIMTYPES = {0: "linear", 1: "aligned", 2: "angular", 3: "diameter", 4: "radius", 5: "angular", 6: "ordinate"}
_NUM = re.compile(r"(?<![\d.])(\d*\.\d+|\d+)(?![\d.])")
_GTOL = re.compile(r"\.(0{1,4}|X{1,4})\s*=?\s*(?:%%P|±|\+/-|\+-)\s*(\.\d+)")


@dataclass
class Dim:
    kind: str
    measured: float
    shown: Optional[float]
    text: str
    not_to_scale: bool
    decimals: Optional[int]


@dataclass
class Drawing:
    dims: list[Dim] = field(default_factory=list)
    callouts: list[Callout] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    general_tol: dict[int, float] = field(default_factory=dict)
    units_hint: Optional[str] = None


def _decimals(s: str) -> Optional[int]:
    m = re.search(r"\.(\d+)", s)
    return len(m.group(1)) if m else None


def _dim(e) -> Optional[Dim]:
    kind = DIMTYPES.get(e.dimtype & 7)
    if kind is None:
        return None
    try:
        lfac = float(e.override().get("dimlfac", 1.0) or 1.0)
    except Exception:
        lfac = 1.0
    measured = float(e.get_measurement()) * lfac
    raw = (e.dxf.get("text") or "").strip()
    if raw in ("", "<>") or "<>" in raw:
        return Dim(kind, measured, measured, raw, False, None)
    plain = re.sub(r"\\[A-Za-z][^;]*;|[{}]|%%[CcPpDd]", "", raw)
    m = _NUM.search(plain)
    shown = float(m.group(1)) if m else None
    nts = shown is not None and abs(shown - measured) > 1e-6
    return Dim(kind, measured, shown, raw, nts, _decimals(m.group(1)) if m else None)


def read(path: Path) -> Drawing:
    import ezdxf
    doc = ezdxf.readfile(str(path))
    dr = Drawing()
    for e in doc.entitydb.values():
        t = e.dxftype()
        if t == "DIMENSION":
            d = _dim(e)
            if d is not None:
                dr.dims.append(d)
        elif t in ("TEXT", "ATTRIB"):
            dr.texts.append(e.dxf.text)
        elif t == "MTEXT":
            dr.texts.append(e.plain_text())
    for s in dr.texts:
        c = parse(s)
        if c is not None:
            dr.callouts.append(c)
        for m in _GTOL.finditer(s.upper()):
            dr.general_tol[len(m.group(1))] = float(m.group(2))
    blob = " ".join(dr.texts).upper()
    if "MILLIMET" in blob or "DIMENSIONS ARE IN MM" in blob:
        dr.units_hint = "mm"
    elif "INCH" in blob:
        dr.units_hint = "inch"
    return dr
```

- [ ] **Step 4: Run the tests**

Run: `& $PY -m pytest tests/test_bench_dxfread.py -q -p no:cacheprovider`
Expected: 3 passed. If `override=` in `add_linear_dim` raises, drop that argument (the test sets `dxf.text` afterwards anyway).

- [ ] **Step 5: Commit**

```powershell
git add bench/dxfread.py tests/test_bench_dxfread.py
git commit -m "feat(bench): read DXF dimensions (shown vs measured), callouts and general tolerance`n`nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Cross-check and sign-off

**Files:**
- Create: `bench/crosscheck.py`
- Test: `tests/test_bench_crosscheck.py`

- [ ] **Step 1: Write the failing test**

`tests/test_bench_crosscheck.py`:
```python
"""bench.crosscheck: a clean pair gives no flags; one seeded change gives exactly one flag."""
from bench.callouts import parse
from bench.crosscheck import ALWAYS_REVIEW, check, sign_auto, sign_human
from bench.dxfread import Dim, Drawing
from bench.features import Feature, Key


def _key():
    holes = [Feature(id=f"K{i}", type="thru_hole", axis=[0, 0, 1], center=[x, y, 0], d=0.344,
                     depth=0.5, thru=True)
             for i, (x, y) in enumerate([(0.5, 0.5), (3.5, 0.5), (0.5, 2.5), (3.5, 2.5)], 1)]
    return Key(part="P", units="inch", source="s", envelope=[4.0, 3.0, 0.5], features=holes)


def _drawing(width=4.0, count=4):
    dims = [Dim("linear", width, width, "<>", False, None), Dim("linear", 3.0, 3.0, "<>", False, None),
            Dim("linear", 0.5, 0.5, "<>", False, None), Dim("linear", 3.0, 3.0, "<>", False, None),
            Dim("linear", 2.0, 2.0, "<>", False, None)]
    return Drawing(dims=dims, callouts=[parse(f".344 DIA. THRU ({count}) HLS.")],
                   general_tol={3: 0.005, 2: 0.01}, units_hint="inch")


def test_clean_pair_has_no_flags():
    assert check(_key(), _drawing()) == []


def test_changed_dimension_gives_exactly_one_flag():
    flags = check(_key(), _drawing(width=4.25))
    assert [f.kind for f in flags] == ["unexplained_drawing_value"]


def test_unplaced_hole_is_flagged():
    k = _key()
    k.features[0].center = [1.234, 1.789, 0]       # a position no drawing distance explains
    flags = check(k, _drawing())
    assert [(f.kind, f.feature) for f in flags if f.kind == "unexplained_position"] == [("unexplained_position", "K1")]


def test_count_mismatch_flag():
    flags = check(_key(), _drawing(count=3))
    assert [f.kind for f in flags] == ["count_mismatch"]


def test_units_mismatch_flag():
    d = _drawing()
    d.units_hint = "mm"
    assert "units_mismatch" in {f.kind for f in check(_key(), d)}


def test_signoff_rules():
    k = _key()
    k.flags = []
    assert sign_auto(k, tool="bench 1") and k.signoff["kind"] == "auto"
    k2 = _key()
    k2.part = next(iter(ALWAYS_REVIEW))
    assert not sign_auto(k2, tool="bench 1") and not k2.signed
    k3 = _key()
    k3.flags = check(k3, _drawing(count=3))
    assert not sign_human(k3, by="smcanuff")
    k3.flags[0].resolution = "accepted: 4th hole is on the section view"
    assert sign_human(k3, by="smcanuff") and k3.signoff["kind"] == "human"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `& $PY -m pytest tests/test_bench_crosscheck.py -q -p no:cacheprovider`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`bench/crosscheck.py`:
```python
"""Answer key <-> drawing cross-check (spec 2026-10-23). Flags, never fixes.

- key -> drawing: every hole diameter must be stated (dimension or callout); every hole
  position must be explained by a drawing distance (from an envelope face, from another hole,
  from the part center, or a pattern radius/diameter).
- drawing -> key: every linear/diameter/radius value must equal some key quantity.
- callout counts must equal the number of matching key holes.
"""
from __future__ import annotations

import datetime as _dt
from itertools import combinations
from typing import Iterable

from bench.dxfread import Drawing
from bench.features import HOLE_TYPES, Flag, Key

FALLBACK_TOL = {"inch": 0.005, "mm": 0.1}
ALWAYS_REVIEW = {"1807408E"}       # provisional pairing (spec): a person always reviews it


def _tol(drawing: Drawing, units: str, decimals=None) -> float:
    if decimals is not None and decimals in drawing.general_tol:
        return drawing.general_tol[decimals]
    return FALLBACK_TOL[units]


def _key_quantities(key: Key) -> list[float]:
    q = list(key.envelope)
    holes = [f for f in key.features if f.center is not None]
    for f in key.features:
        for v in (f.d, f.depth, f.cbore_d, f.cbore_depth, f.csink_d):
            if v:
                q.append(v)
                if f.type in ("bore", "turned_diameter", "boss", "fillet", "slot"):
                    q.append(v / 2)
        if f.pattern and f.pattern.get("radius"):
            q += [f.pattern["radius"], 2 * f.pattern["radius"]]
        if f.size:
            q += [s for s in f.size if s]
    for f in holes:
        for i in range(3):
            q += [f.center[i], key.envelope[i] - f.center[i], abs(f.center[i] - key.envelope[i] / 2)]
    for a, b in combinations(holes, 2):
        q += [abs(a.center[i] - b.center[i]) for i in range(3)]
    return [x for x in q if x > 1e-9]


def _near(v: float, pool: Iterable[float], tol: float) -> bool:
    return any(abs(v - p) <= tol for p in pool)


def _near_any(values: list[float], pool: list[float], tol: float) -> bool:
    return any(_near(v, pool, tol) for v in values)


def check(key: Key, drawing: Drawing) -> list[Flag]:
    flags: list[Flag] = []
    tol = _tol(drawing, key.units)
    if drawing.units_hint and drawing.units_hint != key.units:
        flags.append(Flag("units_mismatch", f"drawing says {drawing.units_hint}, key is {key.units}"))
    stated = [d.shown for d in drawing.dims if d.shown is not None and d.kind != "angular"]
    stated += [d.shown * 2 for d in drawing.dims if d.kind == "radius" and d.shown is not None]
    for c in drawing.callouts:
        stated += [v for v in (c.d, c.depth) if v]
    quantities = _key_quantities(key)

    holes = [f for f in key.features if f.type in HOLE_TYPES]
    for h in holes:
        tapped = [c for c in drawing.callouts if c.kind == "tap" and c.nominal and 0.65 * c.nominal <= h.d <= c.nominal]
        if tapped:
            h.thread, h.type = tapped[0].thread, "tapped_hole" if h.type in ("thru_hole", "blind_hole") else h.type
            continue
        screwed = [c for c in drawing.callouts if c.kind in ("cbore", "csink") and c.screw]
        if screwed and h.type in ("counterbore", "countersink"):
            continue                    # size comes from the screw standard, not printed
        if not _near(h.d, stated, tol):
            flags.append(Flag("unexplained_key_value", f"{h.type} d={h.d:.4f} not stated on the drawing", h.id))

    for h in holes:                       # position: some drawing distance must locate the hole
        cands = []
        for i in range(3):
            if abs(h.axis[i]) > 0.5:
                continue                  # along the hole axis: depth, not position
            c, e = h.center[i], key.envelope[i]
            cands += [c, e - c, abs(c - e / 2)]
            cands += [abs(c - o.center[i]) for o in holes if o is not h]
        for p in key.features:
            if p.type == "hole_pattern" and h.id in p.members and p.pattern and p.pattern.get("radius"):
                cands += [p.pattern["radius"], 2 * p.pattern["radius"]]
        if not _near_any([x for x in cands if x > 1e-9], stated, tol):
            flags.append(Flag("unexplained_position", f"{h.type} at {[round(x, 4) for x in h.center]} "
                              "is not located by any drawing distance", h.id))

    for d in drawing.dims:
        if d.kind == "angular" or d.shown is None or d.shown <= tol:
            continue
        if not _near(d.shown, quantities, _tol(drawing, key.units, d.decimals)):
            flags.append(Flag("unexplained_drawing_value",
                              f"{d.kind} {d.shown:g} ({d.text or 'measured'}) matches no key quantity"))

    for c in drawing.callouts:
        if c.count <= 1:
            continue
        if c.kind == "tap":
            n = sum(1 for h in holes if h.thread == c.thread)
        elif c.d:
            n = sum(1 for h in holes if abs(h.d - c.d) <= tol)
        else:
            n = sum(1 for h in holes if h.type == {"cbore": "counterbore", "csink": "countersink"}.get(c.kind))
        if n != c.count:
            flags.append(Flag("count_mismatch", f"callout '{c.text.strip()}' says {c.count}, key has {n}"))
    return flags


def _today() -> str:
    return _dt.date.today().isoformat()


def sign_auto(key: Key, tool: str) -> bool:
    """Auto sign-off: no flags at all and not a part that must be reviewed by a person."""
    if key.flags or key.part in ALWAYS_REVIEW:
        return False
    key.signoff = {"kind": "auto", "by": "crosscheck", "tool": tool, "date": _today()}
    return True


def sign_human(key: Key, by: str) -> bool:
    """Human sign-off: every flag must carry a resolution."""
    if key.open_flags():
        return False
    key.signoff = {"kind": "human", "by": by, "date": _today()}
    return True
```

- [ ] **Step 4: Run the tests**

Run: `& $PY -m pytest tests/test_bench_crosscheck.py -q -p no:cacheprovider`
Expected: 6 passed. A seeded change must produce exactly one flag. If a test sees extra flags, fix `check`, not the test.

- [ ] **Step 5: Commit**

```powershell
git add bench/crosscheck.py tests/test_bench_crosscheck.py
git commit -m "feat(bench): key<->drawing cross-check with flags and auto/human sign-off`n`nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: The 21 pairs, the seeded split, and the manifest

**Files:**
- Create: `bench/split.py`
- Modify: `bench/manifest.yaml` (append entries), `tests/test_bench_manifest.py`
- Test: `tests/test_bench_split.py`

- [ ] **Step 1: Write the failing test**

`tests/test_bench_split.py`:
```python
"""bench.split: the format-dev pick reproduces from the recorded seed; manifest agrees."""
from pathlib import Path

import yaml

from bench.split import CLEAN, PARKED, SEED, choose_format_dev, mti_entries

M = yaml.safe_load((Path(__file__).resolve().parent.parent / "bench" / "manifest.yaml").read_text(encoding="utf-8"))


def test_seeded_pick():
    assert choose_format_dev() == ["A050291E", "A050381E", "A050511E"]
    assert SEED == 20261023


def test_near_duplicates_never_dev():
    assert not {"A050471E", "A050481E"} & set(choose_format_dev())


def test_14_clean_7_parked():
    assert len(CLEAN) == 14 and len(PARKED) == 7
    assert not {p.part for p in CLEAN} & {p.part for p in PARKED}


def test_manifest_matches_split():
    mti = mti_entries(M)
    dev = {e["part"] for e in mti["dev"]}
    held = {e["part"] for e in mti["held_out"]}
    parked = {e["part"] for e in M["splits"]["parked"]}
    assert dev == set(choose_format_dev())
    assert held == {p.part for p in CLEAN} - dev
    assert parked == {p.part for p in PARKED}
    assert all(e["reason"] for e in M["splits"]["parked"])
    assert M["mti_bench"]["seed"] == SEED
```

- [ ] **Step 2: Run it to verify it fails**

Run: `& $PY -m pytest tests/test_bench_split.py -q -p no:cacheprovider`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement `bench/split.py`**

```python
"""The MTI drawing-model pairs (2026-10-11 delivery) and the frozen benchmark split.

Paths are relative to the dataset folder's `New Dataset/AutoCAD/` (DWG) and
`New Dataset/AutoCAD/Corresponding Models/` (SLDPRT). Nothing here is confidential.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

SEED = 20261023
NEAR_DUPLICATES = ("A050471E", "A050481E")
DWG_ROOT = "New Dataset/AutoCAD"
MODEL_ROOT = "New Dataset/AutoCAD/Corresponding Models"


@dataclass(frozen=True)
class Pair:
    part: str
    dwg: str          # relative to DWG_ROOT
    model: str        # relative to MODEL_ROOT
    complexity: str   # simple | complex
    family: str
    reason: str = ""  # parked only


def _s(part, family):
    return Pair(part, f"Simple Parts/{part}.DWG", f"Simple Parts/{part}.SLDPRT", "simple", family)


CLEAN = (
    _s("A050071E", "rod with flat, tapped ends"),
    _s("A050181E", "mounting pad bar, 2 tapped thru"),
    _s("A050211E", "retainer disc, 6 thru holes, U-notch"),
    _s("A050221E", "flanged disc, bore, hole pattern"),
    _s("A050291E", "large plate/bracket, holes and taps"),
    _s("A050311E", "collet actuator ring"),
    _s("A050381E", "mounting pad block, 4 tapped blind"),
    _s("A050411E", "tank cover plate, 12 countersinks"),
    _s("A050471E", "locator (Wuxi), 3 counterbores"),
    _s("A050481E", "locator (Wuxi), 3 counterbores"),
    _s("A050511E", "key (Wuxi), counterbore"),
    Pair("1801901E", "Complex Parts (not weldments)/1801901E.DWG",
         "Complex Parts (Not Weldments)/1801901.SLDPRT", "complex", "collet pad serrated (Morton)"),
    Pair("1807408E", "Complex Parts (not weldments)/1807408E.DWG",
         "Complex Parts (Not Weldments)/1807408-021(A).SLDPRT", "complex",
         "tailstock ring, hole table (Rolls Royce); PROVISIONAL pairing"),
    Pair("1901001E", "Complex Parts (not weldments)/1901001E.dwg",
         "Complex Parts (Not Weldments)/1901001E.SLDPRT", "complex", "master collet (Emerson)"),
)

_TWIN = "M twin: re-drawn for metric hardware; only the inch (E) model exists, hole sizes differ"
_OBS = "OBSOLETE sheet ('SEE SOLIDWORKS DRAWING'); model may be a later revision"
PARKED = (
    Pair("A050031M", "Simple Parts/A050031M.DWG", "Simple Parts/A050031E.SLDPRT", "simple", "adapter", _TWIN),
    Pair("A050081M", "Simple Parts/A050081M.DWG", "Simple Parts/A050081E_OLD.SLDPRT", "simple", "wear plate", _TWIN),
    Pair("A050381M", "Simple Parts/A050381M.DWG", "Simple Parts/A050381E.SLDPRT", "simple", "mounting pad", _TWIN),
    Pair("A050031E", "Simple Parts/A050031E.DWG", "Simple Parts/A050031E.SLDPRT", "simple", "adapter", _OBS),
    Pair("A050061E", "Simple Parts/A050061E.DWG", "Simple Parts/A050061E.SLDPRT", "simple", "bushing", _OBS),
    Pair("A050081E_OLD", "Simple Parts/A050081E_OLD.dwg", "Simple Parts/A050081E_OLD.SLDPRT", "simple",
         "wear plate", _OBS),
    Pair("A050131M", "Simple Parts/A050131M.DWG", "Simple Parts/A050131M.SLDPRT", "simple", "key", _OBS),
)


def choose_format_dev() -> list[str]:
    cands = sorted(p.part for p in CLEAN if p.complexity == "simple" and p.part not in NEAR_DUPLICATES)
    return sorted(random.Random(SEED).sample(cands, 3))


def pair(part: str) -> Pair:
    return next(p for p in CLEAN + PARKED if p.part == part)


def mti_entries(manifest: dict) -> dict[str, list[dict]]:
    """The manifest's MTI-dataset entries per split (source: mti_bench)."""
    return {s: [e for e in (manifest["splits"].get(s) or []) if e.get("source") == "mti_bench"]
            for s in ("dev", "held_out", "parked")}


def bench_parts(manifest: dict) -> list[str]:
    """Scored MTI parts (format dev + held-out), in manifest order."""
    m = mti_entries(manifest)
    return [e["part"] for e in m["dev"] + m["held_out"]]
```

- [ ] **Step 4: Append the entries to `bench/manifest.yaml`**

Add the `mti_bench` block after `tolerance_default:` and before `splits:`:
```yaml
mti_bench:
  spec: docs/superpowers/specs/2026-10-23-benchmark-dataset-design.md
  delivered: "2026-10-11"
  split_decided: "2026-10-23"
  split_decided_by: "smcanuff (with Claude)"
  seed: 20261023
  rule: >
    14 clean drawing-model pairs. Format dev = random.Random(20261023).sample of the 9 simple
    parts excluding the near-duplicate pair A050471E/A050481E (bench/split.py). The other 11,
    including all 3 complex parts, are held-out. Files live outside git under MTI_BENCH_DATA/<part>/.
```

Append these three entries at the end of `splits.dev`:
```yaml
    - {part: A050291E, source: mti_bench, family: "large plate/bracket, holes and taps", units: inch, complexity: simple, reference_step: reference.step}
    - {part: A050381E, source: mti_bench, family: "mounting pad block, 4 tapped blind", units: inch, complexity: simple, reference_step: reference.step}
    - {part: A050511E, source: mti_bench, family: "key (Wuxi), counterbore", units: inch, complexity: simple, reference_step: reference.step}
```

Replace `held_out: []` (and the PENDING comment above it) with:
```yaml
  # FROZEN 2026-10-23 (spec 2026-10-23). Never tune, debug or take prompt examples from these.
  held_out:
    - {part: A050071E, source: mti_bench, family: "rod with flat, tapped ends", units: inch, complexity: simple, reference_step: reference.step}
    - {part: A050181E, source: mti_bench, family: "mounting pad bar, 2 tapped thru", units: inch, complexity: simple, reference_step: reference.step}
    - {part: A050211E, source: mti_bench, family: "retainer disc, 6 thru holes, U-notch", units: inch, complexity: simple, reference_step: reference.step}
    - {part: A050221E, source: mti_bench, family: "flanged disc, bore, hole pattern", units: inch, complexity: simple, reference_step: reference.step}
    - {part: A050311E, source: mti_bench, family: "collet actuator ring", units: inch, complexity: simple, reference_step: reference.step}
    - {part: A050411E, source: mti_bench, family: "tank cover plate, 12 countersinks", units: inch, complexity: simple, reference_step: reference.step}
    - {part: A050471E, source: mti_bench, family: "locator (Wuxi), 3 counterbores", units: inch, complexity: simple, reference_step: reference.step}
    - {part: A050481E, source: mti_bench, family: "locator (Wuxi), 3 counterbores", units: inch, complexity: simple, reference_step: reference.step}
    - {part: 1801901E, source: mti_bench, family: "collet pad serrated (Morton)", units: inch, complexity: complex, reference_step: reference.step}
    - {part: 1807408E, source: mti_bench, family: "tailstock ring, hole table (Rolls Royce)", units: inch, complexity: complex, reference_step: reference.step, pairing: provisional}
    - {part: 1901001E, source: mti_bench, family: "master collet (Emerson)", units: inch, complexity: complex, reference_step: reference.step}
  parked:
    - {part: A050031M, source: mti_bench, reason: "M twin: only the inch (E) model exists, hole sizes differ"}
    - {part: A050081M, source: mti_bench, reason: "M twin: only the inch (E) model exists, hole sizes differ"}
    - {part: A050381M, source: mti_bench, reason: "M twin: only the inch (E) model exists, hole sizes differ"}
    - {part: A050031E, source: mti_bench, reason: "OBSOLETE sheet; model may be a later revision"}
    - {part: A050061E, source: mti_bench, reason: "OBSOLETE sheet; model may be a later revision"}
    - {part: A050081E_OLD, source: mti_bench, reason: "OBSOLETE sheet; model may be a later revision"}
    - {part: A050131M, source: mti_bench, reason: "OBSOLETE sheet; model may be a later revision"}
```

- [ ] **Step 5: Update `tests/test_bench_manifest.py`**

Replace `test_no_part_in_two_splits` and `test_every_view_path_exists_with_exact_case`, and append the data-root test:
```python
def test_no_part_in_two_splits():
    all_parts = _parts("dev") + _parts("held_out") + _parts("parked")
    assert len(all_parts) == len(set(all_parts))


def test_every_view_path_exists_with_exact_case():
    for split in ("dev", "held_out"):
        for p in M["splits"].get(split) or []:
            if p.get("source") == "mti_bench":
                continue                      # checked under the data root below
            path = REPO / p["views"]
            assert path.exists(), p["views"]
            assert path.name in {c.name for c in path.parent.iterdir()}, f"case mismatch: {p['views']}"


def test_mti_parts_have_data_files():
    from bench import config
    root = config.data_root(required=False)
    if root is None:
        pytest.skip("MTI_BENCH_DATA not set (benchmark data is outside git)")
    for split in ("dev", "held_out"):
        for p in M["splits"].get(split) or []:
            if p.get("source") != "mti_bench":
                continue
            d = root / p["part"]
            for name in ("drawing.pdf", "drawing.dxf", "reference.step"):
                assert (d / name).is_file(), f"{p['part']}: missing {name}"


def test_benchmark_data_is_outside_the_repo():
    from bench import config
    root = config.data_root(required=False)
    if root is None:
        pytest.skip("MTI_BENCH_DATA not set")
    assert REPO.resolve() not in root.resolve().parents and root.resolve() != REPO.resolve(), \
        "MTI_BENCH_DATA must be outside the repository (confidential MTI data)"
```

Note: the spec has `prep` writing the split into the manifest. The plan instead commits the split as a literal, reviewed once, and `test_bench_split.py` proves it reproduces from the seed. That is a stronger freeze, and `prep` only reads the manifest.

- [ ] **Step 6: Run the tests**

Run: `& $PY -m pytest tests/test_bench_split.py tests/test_bench_manifest.py -q -p no:cacheprovider`
Expected: all pass. `test_mti_parts_have_data_files` skips until Task 13.

- [ ] **Step 7: Commit**

```powershell
git add bench/split.py bench/manifest.yaml tests/test_bench_split.py tests/test_bench_manifest.py
git commit -m "feat(bench): freeze the MTI split (3 format dev, 11 held-out, 7 parked) from seed 20261023`n`nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Feature profile

**Files:**
- Create: `bench/profile.py`
- Test: `tests/test_bench_profile.py`

- [ ] **Step 1: Write the failing test**

`tests/test_bench_profile.py`:
```python
"""bench.profile: counts per split, shares, bias flags, HTML."""
from bench.features import Feature, Key
from bench.profile import bias_flags, plan_type_counts, render_html, type_counts


def _k(part, types):
    return Key(part=part, units="inch", source="s", envelope=[1, 1, 1],
               features=[Feature(id=f"K{i}", type=t) for i, t in enumerate(types)])


def test_counts_and_flags():
    dev = [_k("D1", ["tapped_hole", "tapped_hole", "chamfer"])]
    held = [_k("H1", ["tapped_hole", "counterbore", "thru_hole", "thru_hole", "chamfer"])]
    cd, ch = type_counts(dev), type_counts(held)
    assert cd == {"tapped_hole": 2, "chamfer": 1}
    assert ch["thru_hole"] == 2
    flags = bias_flags(cd, ch, threshold=0.30)
    assert any("tapped_hole" in f and "30%" in f for f in flags)          # 3 of 8 = 37.5%
    assert any("counterbore" in f and "dev" in f for f in flags)          # in held-out, absent from dev


def test_plan_type_counts_maps_ir_kinds():
    plan = {"features": [
        {"kind": "revolve", "status": "planned"},
        {"kind": "hole", "status": "planned", "spec": {"type": "cbore"}},
        {"kind": "hole", "status": "planned", "spec": {"type": "tapped"}},
        {"kind": "edge_op", "status": "planned", "operation": "chamfer"},
        {"kind": "edge_op", "status": "unresolved", "operation": "fillet"},
        {"kind": "pattern", "status": "planned", "count": "4"},
        {"kind": "prism", "status": "planned", "op": "cut"},
    ]}
    assert plan_type_counts(plan) == {"turned_diameter": 1, "counterbore": 1, "tapped_hole": 1,
                                      "chamfer": 1, "hole_pattern": 1, "pocket_step": 1}


def test_html_mentions_every_type():
    html = render_html({"tapped_hole": 2}, {"thru_hole": 1}, {"chamfer": 3}, {"tap": 10}, ["flag x"])
    for s in ("tapped_hole", "thru_hole", "chamfer", "flag x", "approximate"):
        assert s in html
```

- [ ] **Step 2: Run it to verify it fails**

Run: `& $PY -m pytest tests/test_bench_profile.py -q -p no:cacheprovider`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`bench/profile.py`:
```python
"""Feature-type profile of the benchmark, so later changes can be checked for bias toward
common feature types (spec 2026-10-23, "Feature profile")."""
from __future__ import annotations

import html as _html
import re
from collections import Counter
from pathlib import Path

from bench.features import FEATURE_TYPES, Key

ARCHIVE_KEYWORDS = {
    "tap": r"\bTAP\b|-\d+\s*UN[CF]|\bM\d+\s*X\s*\d",
    "counterbore": r"C'?BORE|CBORE",
    "countersink": r"C'?SINK|CSK",
    "thru/drill": r"\bDR\.|\bDRILL|\bTHRU\b",
    "hole pattern": r"\d+\s*-?\s*HOLES|\bB\.?\s*C\.|EQ\.?\s*SP",
    "slot": r"\bSLOT",
    "keyway": r"KEYWAY|KEY\s*SEAT",
    "chamfer": r"CHAM|X\s*45",
    "radius/fillet": r"\d\s*R\.|RADII|FILLET",
}


def type_counts(keys: list[Key]) -> dict[str, int]:
    c: Counter = Counter()
    for k in keys:
        c.update(k.counts())
    return dict(c)


def plan_type_counts(plan: dict) -> dict[str, int]:
    """IR plan (old dev parts) -> approximate feature types. Unresolved features count too:
    they are on the drawing."""
    c: Counter = Counter()
    for f in plan.get("features", []):
        k = f.get("kind")
        if k == "revolve":
            c["turned_diameter"] += 1
        elif k == "hole":
            c[{"cbore": "counterbore", "csink": "countersink", "tapped": "tapped_hole",
               "blind": "blind_hole"}.get((f.get("spec") or {}).get("type"), "thru_hole")] += 1
        elif k == "edge_op":
            c["fillet" if f.get("operation") == "fillet" else "chamfer"] += 1
        elif k == "pattern":
            c["hole_pattern"] += 1
        elif k == "prism" and f.get("op") == "cut":
            c["pocket_step"] += 1
    return dict(c)


def archive_keyword_counts(dataset_dir: Path) -> dict[str, int]:
    """Drawings (of all DWGs under dataset_dir) whose readable text mentions each keyword.
    Approximate: compressed DWGs expose little text."""
    c: Counter = Counter()
    for p in Path(dataset_dir).rglob("*"):
        if p.suffix.lower() != ".dwg":
            continue
        b = p.read_bytes()
        t = "\n".join(x.decode("ascii", "ignore") for x in re.findall(rb"[ -~]{4,}", b)).upper()
        for name, rx in ARCHIVE_KEYWORDS.items():
            if re.search(rx, t):
                c[name] += 1
    return dict(c)


def bias_flags(dev: dict, held: dict, threshold: float = 0.30) -> list[str]:
    total = Counter(dev) + Counter(held)
    n = sum(total.values()) or 1
    out = [f"{t}: {v / n:.0%} of all features (over {threshold:.0%})"
           for t, v in total.most_common() if v / n > threshold]
    out += [f"{t}: in held-out but not in format dev" for t in held if t not in dev]
    out += [f"{t}: in format dev but not in held-out" for t in dev if t not in held]
    return out


def render_html(dev: dict, held: dict, old_dev: dict, archive: dict, flags: list[str]) -> str:
    total = Counter(dev) + Counter(held)
    n = sum(total.values()) or 1
    rows = "".join(
        f"<tr><td>{t}</td><td>{dev.get(t, 0)}</td><td>{held.get(t, 0)}</td><td>{total.get(t, 0)}</td>"
        f"<td>{total.get(t, 0) / n:.0%}</td><td>{old_dev.get(t, 0)}</td></tr>"
        for t in FEATURE_TYPES if total.get(t) or old_dev.get(t))
    arch = "".join(f"<tr><td>{_html.escape(k)}</td><td>{v}</td></tr>" for k, v in sorted(archive.items()))
    fl = "".join(f"<li>{_html.escape(f)}</li>" for f in flags) or "<li>none</li>"
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Benchmark profile</title>
<style>body{{font-family:system-ui,sans-serif;margin:24px}}table{{border-collapse:collapse}}
td,th{{border:1px solid #bbb;padding:4px 8px;text-align:right}}td:first-child{{text-align:left}}</style></head>
<body><h1>Benchmark feature profile</h1><h2>Bias flags</h2><ul>{fl}</ul>
<h2>Feature types (from answer keys)</h2><table><tr><th>type</th><th>format dev</th><th>held-out</th>
<th>total</th><th>share</th><th>old 9 dev (plans)</th></tr>{rows}</table>
<h2>Whole MTI archive (DWG keyword scan, approximate)</h2><table><tr><th>keyword</th><th>drawings</th></tr>{arch}</table>
</body></html>"""
```

- [ ] **Step 4: Run the tests**

Run: `& $PY -m pytest tests/test_bench_profile.py -q -p no:cacheprovider`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```powershell
git add bench/profile.py tests/test_bench_profile.py
git commit -m "feat(bench): feature-type profile with bias flags`n`nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: SolidWorks tasks (DWG→PDF with crop, SLDPRT→STEP)

**Files:**
- Create: `bench/sw_tasks.py`
- Test: `tests/test_bench_sw_tasks.py`

API facts, all verified in `sldworks.tlb`/`swconst.tlb` on 2026-10-12/23:

| Call / constant | Value |
|---|---|
| `GetImportFileData(FileName)` → `IImportDxfDwgData` | |
| `ImportMethod[Sheet]` (property put) | 1 = swImportDxfDwg_ImportToDrawing |
| `SetPaperSize(Sheet, Size, H, W)` | Size 12 = swDwgPapersUserDefined |
| `SetSheetScale(Sheet, Num, Den)` | |
| `SetPosition(Sheet, Pos, X, Y)` | Pos 1 = swDwgEntitiesCentered |
| `LoadFile4(FileName, ArgString, ImportData, Errors)` | |
| `OpenDoc6(Name, Type, Options, Config, Errors, Warnings)` | Options: 1 Silent, 2 ReadOnly |
| swPDFExportInColor / swPDFExportHighQuality | 323 / 325 |
| swStepAP | 75 |

- [ ] **Step 1: Verify `swDocPART` before writing code** (CLAUDE.md rule 1)

Run:
```powershell
& $PY -c "import pythoncom; tl=pythoncom.LoadTypeLib(r'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\swconst.tlb'); [print([(tl.GetTypeInfo(i).GetNames(tl.GetTypeInfo(i).GetVarDesc(j).memid)[0], tl.GetTypeInfo(i).GetVarDesc(j).value) for j in range(tl.GetTypeInfo(i).GetTypeAttr().cVars)]) for i in range(tl.GetTypeInfoCount()) if tl.GetDocumentation(i)[0]=='swDocumentTypes_e']"
```
Expected: the list contains `('swDocPART', 1)`. If not, use the printed value for `SW_DOC_PART` below.

- [ ] **Step 2: Write the failing test** (pure parts only: the crop, and preference restore with a fake app)

`tests/test_bench_sw_tasks.py`:
```python
"""bench.sw_tasks: PDF crop and preference restore (no SolidWorks needed)."""
import pytest

fitz = pytest.importorskip("fitz")
from bench.sw_tasks import crop_to_content, temporary_prefs  # noqa: E402


def test_crop_to_content(tmp_path):
    p = tmp_path / "x.pdf"
    doc = fitz.open()
    page = doc.new_page(width=3000, height=3000)
    page.draw_rect(fitz.Rect(1000, 1200, 1400, 1500))
    page.insert_text((10, 2990), "SOLIDWORKS Educational Product. For Instructional Use Only.")
    doc.new_page(width=3000, height=3000)          # empty sheet -> dropped
    doc.save(p)
    crop_to_content(p, margin_pt=10)
    out = fitz.open(p)
    assert len(out) == 1
    cb = out[0].cropbox
    assert 985 <= cb.x0 <= 995 and 1405 <= cb.x1 <= 1415


def test_prefs_restored_even_on_error():
    class App:
        def __init__(self):
            self.p = {323: True, 325: False}

        def GetUserPreferenceToggle(self, k):
            return self.p[k]

        def SetUserPreferenceToggle(self, k, v):
            self.p[k] = v

    app = App()
    with pytest.raises(RuntimeError):
        with temporary_prefs(app, {323: False, 325: True}):
            assert app.p == {323: False, 325: True}
            raise RuntimeError("boom")
    assert app.p == {323: True, 325: False}
```

- [ ] **Step 3: Run it to verify it fails**

Run: `& $PY -m pytest tests/test_bench_sw_tasks.py -q -p no:cacheprovider`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 4: Implement**

`bench/sw_tasks.py`:
```python
"""SolidWorks steps of benchmark prep (Windows + SolidWorks only; win32com imported lazily).

DWG -> PDF: import at 1:1, centered, on a 4.5 m user-defined sheet (SolidWorks' own choice
of paper/scale broke 9 of 21 drawings on 2026-10-12), export black & white, crop to content.
SLDPRT -> STEP: open a COPY read-only, export STEP AP214 and a PNG picture.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path

SHEET_M = 4.5
PDF_COLOR, PDF_HIGH_QUALITY, STEP_AP = 323, 325, 75
SW_DOC_PART = 1
OPEN_SILENT, OPEN_READONLY = 1, 2
IMPORT_TO_DRAWING, PAPER_USER, POS_CENTERED = 1, 12, 1


class SwUnavailable(RuntimeError):
    pass


def connect(retries: int = 6, wait_s: float = 5.0):
    import pythoncom
    import win32com.client as w
    pythoncom.CoInitialize()
    last = None
    for _ in range(retries):
        try:
            return w.GetActiveObject("SldWorks.Application")
        except Exception as e:        # "Operation unavailable": COM registration dropped
            last = e
            time.sleep(wait_s)
    raise SwUnavailable(f"SolidWorks is not reachable over COM ({last}). Start SLDWORKS.exe, "
                        "wait ~25 s, and run again (COM drops after idle minutes on this machine).")


@contextmanager
def temporary_prefs(app, prefs: dict[int, bool]):
    saved = {k: app.GetUserPreferenceToggle(k) for k in prefs}
    for k, v in prefs.items():
        app.SetUserPreferenceToggle(k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            app.SetUserPreferenceToggle(k, v)


def _g(obj, name):
    a = getattr(obj, name)
    return a() if callable(a) else a


def _invoke(obj, name, kind, *args):
    import pythoncom
    o = obj._oleobj_
    return o.Invoke(o.GetIDsOfNames(name), 0, kind, kind != pythoncom.DISPATCH_PROPERTYPUT, *args)


def crop_to_content(pdf: Path, margin_pt: float = 18.0) -> None:
    import fitz
    doc = fitz.open(pdf)
    empty = []
    for page in doc:
        rects = [d["rect"] for d in page.get_drawings() if d["rect"].width < page.rect.width * 0.99]
        rects += [fitz.Rect(b[:4]) for b in page.get_text("blocks") if "Educational Product" not in b[4]]
        if not rects:
            empty.append(page.number)
            continue
        box = rects[0]
        for r in rects[1:]:
            box |= r
        page.set_cropbox((box + (-margin_pt, -margin_pt, margin_pt, margin_pt)) & page.rect)
    if empty and len(empty) < len(doc):
        doc.delete_pages(empty)
    tmp = Path(pdf).with_suffix(".tmp.pdf")
    doc.save(tmp, garbage=3, deflate=True)
    doc.close()
    tmp.replace(pdf)


def dwg_to_pdf(app, dwg: Path, out_pdf: Path) -> None:
    import pythoncom
    import win32com.client as w
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    with temporary_prefs(app, {PDF_COLOR: False, PDF_HIGH_QUALITY: True}):
        data = app.GetImportFileData(str(dwg))
        for sheet in ("", "Model"):
            _invoke(data, "ImportMethod", pythoncom.DISPATCH_PROPERTYPUT, sheet, IMPORT_TO_DRAWING)
            _invoke(data, "SetPaperSize", pythoncom.DISPATCH_METHOD, sheet, PAPER_USER, SHEET_M, SHEET_M)
            _invoke(data, "SetSheetScale", pythoncom.DISPATCH_METHOD, sheet, 1.0, 1.0)
            _invoke(data, "SetPosition", pythoncom.DISPATCH_METHOD, sheet, POS_CENTERED, 0.0, 0.0)
        err = w.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        doc = app.LoadFile4(str(dwg), "", data, err)
        if doc is None:
            raise RuntimeError(f"LoadFile4 failed for {dwg} (error {err.value})")
        try:
            code = doc.SaveAs3(str(out_pdf), 0, 1)
            if code != 0 or not out_pdf.exists():
                raise RuntimeError(f"PDF export failed for {dwg} (SaveAs3 {code})")
        finally:
            app.CloseDoc(_g(doc, "GetTitle"))
    crop_to_content(out_pdf)


def sldprt_to_step(app, sldprt: Path, out_step: Path, out_png: Path) -> None:
    """Open a copy read-only, export STEP AP214 (+ a picture). Never saves the part."""
    import pythoncom
    import win32com.client as w
    out_step.parent.mkdir(parents=True, exist_ok=True)
    err = w.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warn = w.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    doc = app.OpenDoc6(str(sldprt), SW_DOC_PART, OPEN_SILENT | OPEN_READONLY, "", err, warn)
    if doc is None:
        raise RuntimeError(f"OpenDoc6 failed for {sldprt} (error {err.value})")
    try:
        old_ap = app.GetUserPreferenceIntegerValue(STEP_AP)
        app.SetUserPreferenceIntegerValue(STEP_AP, 214)
        try:
            code = doc.SaveAs3(str(out_step), 0, 1)
        finally:
            app.SetUserPreferenceIntegerValue(STEP_AP, old_ap)
        if code != 0 or not out_step.exists():
            raise RuntimeError(f"STEP export failed for {sldprt} (SaveAs3 {code})")
        try:
            doc.ShowNamedView2("*Isometric", 7)
            doc.ViewZoomtofit2()
            doc.SaveAs3(str(out_png), 0, 1)
        except Exception:
            pass                      # the picture is best effort (review sheet only)
    finally:
        app.CloseDoc(_g(doc, "GetTitle"))
```

- [ ] **Step 5: Run the tests**

Run: `& $PY -m pytest tests/test_bench_sw_tasks.py -q -p no:cacheprovider`
Expected: 2 passed.

- [ ] **Step 6: Live check of `SaveAs3` → STEP and the read-only open** (SolidWorks running)

This exports one model into a scratch folder:
```powershell
& $PY -c "from pathlib import Path; import shutil, tempfile; from bench.sw_tasks import connect, sldprt_to_step; src=Path(r'<MTI dataset>\New Dataset\AutoCAD\Corresponding Models\Simple Parts\A050511E.SLDPRT'); d=Path(tempfile.mkdtemp()); c=d/src.name; shutil.copy2(src,c); sldprt_to_step(connect(), c, d/'reference.step', d/'model.png'); print(d, (d/'reference.step').stat().st_size)"
```
Replace `<MTI dataset>` with the dataset folder. Expected: a non-zero STEP size. Then open it with `cadquery.importers.importStep` and confirm one solid.

- [ ] **Step 7: Commit**

```powershell
git add bench/sw_tasks.py tests/test_bench_sw_tasks.py
git commit -m "feat(bench): SolidWorks DWG->PDF (cropped, B&W) and read-only SLDPRT->STEP`n`nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: ODA DWG→DXF wrapper

**Files:**
- Create: `bench/oda.py`
- Test: `tests/test_bench_oda.py`

ODA File Converter command line: `ODAFileConverter <in dir> <out dir> <out version> <out type> <recurse 0|1> <audit 0|1> [<input filter>]`. It converts folders, so the wrapper stages one file in a temporary input folder.

- [ ] **Step 1: Write the failing test** (a fake converter written in Python)

`tests/test_bench_oda.py`:
```python
"""bench.oda: stages one DWG, calls the converter, moves the DXF; errors are clear."""
import sys

import pytest

from bench.oda import OdaError, convert

FAKE = r'''
import sys, pathlib
src, dst, ver, typ, rec, aud = sys.argv[1:7]
for p in pathlib.Path(src).iterdir():
    (pathlib.Path(dst) / (p.stem + "." + typ.lower())).write_text("0\nEOF\n")
'''


def test_convert(tmp_path):
    fake = tmp_path / "fake_oda.py"
    fake.write_text(FAKE, encoding="utf-8")
    dwg = tmp_path / "A050511E.DWG"
    dwg.write_bytes(b"AC1015")
    out = tmp_path / "out" / "drawing.dxf"
    convert(dwg, out, cmd=[sys.executable, str(fake)])
    assert out.read_text() == "0\nEOF\n"


def test_converter_produces_nothing(tmp_path):
    noop = tmp_path / "noop.py"
    noop.write_text("pass", encoding="utf-8")
    dwg = tmp_path / "x.dwg"
    dwg.write_bytes(b"AC1015")
    with pytest.raises(OdaError, match="no DXF"):
        convert(dwg, tmp_path / "o.dxf", cmd=[sys.executable, str(noop)])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `& $PY -m pytest tests/test_bench_oda.py -q -p no:cacheprovider`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`bench/oda.py`:
```python
"""DWG -> DXF with the ODA File Converter (free; path from ODA_CONVERTER)."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

OUT_VERSION = "ACAD2018"


class OdaError(RuntimeError):
    pass


def convert(dwg: Path, out_dxf: Path, cmd: Optional[list[str]] = None, timeout_s: int = 300) -> Path:
    if cmd is None:
        from bench.config import oda_converter
        cmd = [str(oda_converter())]
    out_dxf.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tin, tempfile.TemporaryDirectory() as tout:
        staged = Path(tin) / ("drawing" + Path(dwg).suffix.lower())
        shutil.copy2(dwg, staged)
        r = subprocess.run(cmd + [tin, tout, OUT_VERSION, "DXF", "0", "1"],
                           capture_output=True, text=True, timeout=timeout_s)
        produced = list(Path(tout).glob("*.dxf"))
        if not produced:
            raise OdaError(f"ODA converter wrote no DXF for {dwg} (exit {r.returncode}): {r.stderr[-300:]}")
        shutil.move(str(produced[0]), out_dxf)
    return out_dxf
```

- [ ] **Step 4: Run the tests**

Run: `& $PY -m pytest tests/test_bench_oda.py -q -p no:cacheprovider`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```powershell
git add bench/oda.py tests/test_bench_oda.py
git commit -m "feat(bench): DWG->DXF via ODA File Converter`n`nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Review sheet and the `prep` CLI

**Files:**
- Create: `bench/review.py`, `bench/prep.py`
- Test: `tests/test_bench_review.py`, `tests/test_bench_prep.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_bench_review.py`:
```python
from bench.features import Feature, Flag, Key
from bench.review import render


def test_review_html():
    k = Key(part="P9", units="inch", source="reference.step", envelope=[1, 2, 3],
            features=[Feature(id="K001", type="thru_hole", d=0.25, center=[0.5, 0.5, 0], axis=[0, 0, 1])],
            flags=[Flag("count_mismatch", "says 3, key has 4")])
    html = render(k, drawing_png=None, model_png=None)
    for s in ("P9", "K001", "thru_hole", "count_mismatch", "says 3, key has 4", "not signed"):
        assert s in html
```

`tests/test_bench_prep.py`:
```python
"""bench.prep: resumable steps, per-part logging, failures don't stop the batch."""
import json

from bench import prep


def test_run_step_skips_done_and_logs_failures(tmp_path):
    calls = []

    def ok(part, d):
        calls.append(part)
        (d / "out.txt").write_text("x")

    def boom(part, d):
        raise RuntimeError("bad file")

    log = tmp_path / "prep_log.jsonl"
    res = prep.run_step("demo", ["A", "B"], tmp_path, lambda d: d / "out.txt", ok, log, force=False)
    assert res == {"A": "ok", "B": "ok"} and calls == ["A", "B"]
    res2 = prep.run_step("demo", ["A", "B"], tmp_path, lambda d: d / "out.txt", ok, log, force=False)
    assert res2 == {"A": "skipped", "B": "skipped"} and calls == ["A", "B"]
    res3 = prep.run_step("demo2", ["A", "C"], tmp_path, lambda d: d / "never.txt", boom, log, force=False)
    assert res3["A"].startswith("failed") and res3["C"].startswith("failed")
    lines = [json.loads(x) for x in log.read_text().splitlines()]
    assert {(x["step"], x["part"], x["status"].split(":")[0]) for x in lines} >= {
        ("demo", "A", "ok"), ("demo", "A", "skipped"), ("demo2", "C", "failed")}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `& $PY -m pytest tests/test_bench_review.py tests/test_bench_prep.py -q -p no:cacheprovider`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement `bench/review.py`**

```python
"""One-page review sheet per part: drawing, model picture, key table, flags."""
from __future__ import annotations

import base64
import html as _h
from pathlib import Path
from typing import Optional

from bench.features import Key

COLS = ("id", "type", "d", "depth", "thru", "cbore_d", "cbore_depth", "csink_d", "thread", "center", "axis", "note")


def _img(p: Optional[Path]) -> str:
    if not p or not Path(p).exists():
        return "<p><em>no image</em></p>"
    b64 = base64.b64encode(Path(p).read_bytes()).decode()
    return f'<img style="max-width:100%;border:1px solid #ccc" src="data:image/png;base64,{b64}">'


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.4f}"
    if isinstance(v, list):
        return "(" + ", ".join(f"{x:.3f}" if isinstance(x, float) else str(x) for x in v) + ")"
    return "" if v is None else _h.escape(str(v))


def render(key: Key, drawing_png: Optional[Path], model_png: Optional[Path]) -> str:
    rows = "".join("<tr>" + "".join(f"<td>{_fmt(getattr(f, c))}</td>" for c in COLS) + "</tr>"
                   for f in key.features)
    flags = "".join(f"<li><b>{_h.escape(f.kind)}</b> {_h.escape(f.detail)}"
                    f"{' (' + _h.escape(f.feature) + ')' if f.feature else ''}"
                    f"{' → <i>' + _h.escape(f.resolution) + '</i>' if f.resolution else ''}</li>"
                    for f in key.flags) or "<li>none</li>"
    sign = _h.escape(str(key.signoff)) if key.signed else "not signed"
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{_h.escape(key.part)} key review</title>
<style>body{{font-family:system-ui,sans-serif;margin:20px}}table{{border-collapse:collapse;font-size:13px}}
td,th{{border:1px solid #bbb;padding:3px 6px}}.cols{{display:grid;grid-template-columns:2fr 1fr;gap:16px}}</style>
</head><body><h1>{_h.escape(key.part)}: answer-key review</h1>
<p>units {key.units} · envelope {_fmt(key.envelope)} · sign-off: {sign}</p>
<h2>Flags</h2><ul>{flags}</ul>
<div class="cols"><div><h2>Drawing</h2>{_img(drawing_png)}</div><div><h2>Model</h2>{_img(model_png)}</div></div>
<h2>Key</h2><table><tr>{''.join(f'<th>{c}</th>' for c in COLS)}</tr>{rows}</table></body></html>"""
```

- [ ] **Step 4: Implement `bench/prep.py`**

```python
"""Benchmark prep CLI (spec 2026-10-23). Resumable; every step logs one line per part.

    python -m bench.prep copy --source "<MTI Example Drawings folder>"
    python -m bench.prep pdf | dxf | step | keys | check | review | profile | status
    python -m bench.prep signoff A050071E --by smcanuff
Options: --parts P1 P2 ... (default: all format-dev + held-out parts), --force.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path
from typing import Callable

import yaml

from bench import config, split
from bench.features import Key

TOOL = "bench-prep 1"
MANIFEST = Path(__file__).resolve().parent / "manifest.yaml"


def run_step(step: str, parts: list[str], root: Path, output: Callable[[Path], Path],
             fn: Callable[[str, Path], None], log: Path, force: bool) -> dict[str, str]:
    res = {}
    for part in parts:
        d = root / part
        d.mkdir(parents=True, exist_ok=True)
        if output(d).exists() and not force:
            status = "skipped"
        else:
            try:
                fn(part, d)
                status = "ok"
            except Exception as e:      # one bad part never stops the batch
                status = f"failed: {type(e).__name__}: {e}"[:300]
        res[part] = status
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"time": dt.datetime.now().isoformat(timespec="seconds"), "step": step,
                                 "part": part, "status": status, "tool": TOOL}) + "\n")
        print(f"{step:8s} {part:10s} {status}")
    return res


def _manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def _units(m: dict, part: str) -> str:
    for s in ("dev", "held_out"):
        for e in m["splits"].get(s) or []:
            if e["part"] == part:
                return e.get("units", "inch")
    return "inch"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["copy", "pdf", "dxf", "step", "keys", "check", "review", "profile",
                                     "signoff", "status"])
    ap.add_argument("part", nargs="?")
    ap.add_argument("--parts", nargs="*")
    ap.add_argument("--source", type=Path)
    ap.add_argument("--by")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)

    root = config.data_root()
    m = _manifest()
    parts = a.parts or split.bench_parts(m)
    log = root / "prep_log.jsonl"
    src = root / "source"

    if a.step == "copy":
        if not a.source:
            ap.error("copy needs --source <MTI Example Drawings folder>")
        def fn(part, d):
            p = split.pair(part)
            (src / part).mkdir(parents=True, exist_ok=True)
            shutil.copy2(a.source / split.DWG_ROOT / p.dwg, src / part / Path(p.dwg).name)
            shutil.copy2(a.source / split.MODEL_ROOT / p.model, src / part / Path(p.model).name)
        run_step("copy", parts, root, lambda d: src / d.name, fn, log, a.force)
    elif a.step in ("pdf", "step"):
        from bench import sw_tasks
        app = sw_tasks.connect()
        if a.step == "pdf":
            run_step("pdf", parts, root, lambda d: d / "drawing.pdf",
                     lambda part, d: sw_tasks.dwg_to_pdf(app, src / part / Path(split.pair(part).dwg).name,
                                                         d / "drawing.pdf"), log, a.force)
        else:
            run_step("step", parts, root, lambda d: d / "reference.step",
                     lambda part, d: sw_tasks.sldprt_to_step(
                         app, src / part / Path(split.pair(part).model).name, d / "reference.step",
                         d / "model.png"), log, a.force)
    elif a.step == "dxf":
        from bench import oda
        run_step("dxf", parts, root, lambda d: d / "drawing.dxf",
                 lambda part, d: oda.convert(src / part / Path(split.pair(part).dwg).name, d / "drawing.dxf"),
                 log, a.force)
    elif a.step == "keys":
        from bench import keygen
        run_step("keys", parts, root, lambda d: d / "key.json",
                 lambda part, d: keygen.from_step(d / "reference.step", units=_units(m, part), part=part)
                 .save(d / "key.json"), log, a.force)
    elif a.step == "check":
        from bench import crosscheck, dxfread
        def fn(part, d):
            k = Key.load(d / "key.json")
            if k.signoff and k.signoff.get("kind") == "human" and not a.force:
                return                    # never overwrite a person's review
            k.flags = crosscheck.check(k, dxfread.read(d / "drawing.dxf"))
            k.signoff = None
            crosscheck.sign_auto(k, TOOL)
            k.save(d / "key.json")
        run_step("check", parts, root, lambda d: d / "never", fn, log, True)
    elif a.step == "review":
        from bench import review
        def fn(part, d):
            import fitz
            png = d / "drawing.png"
            page = fitz.open(d / "drawing.pdf")[0]
            z = 1600 / max(page.rect.width, page.rect.height)
            page.get_pixmap(matrix=fitz.Matrix(z, z)).save(png)
            (d / "review.html").write_text(review.render(Key.load(d / "key.json"), png, d / "model.png"),
                                           encoding="utf-8")
        run_step("review", parts, root, lambda d: d / "never", fn, log, True)
    elif a.step == "profile":
        from bench import profile
        mti = split.mti_entries(m)
        load = lambda ps: [Key.load(root / e["part"] / "key.json") for e in ps if (root / e["part"] / "key.json").exists()]
        dev_c, held_c = profile.type_counts(load(mti["dev"])), profile.type_counts(load(mti["held_out"]))
        old = {}
        code = Path(__file__).resolve().parent.parent
        for e in m["splits"]["dev"]:
            if e.get("source") != "mti_bench":
                plan = code / "output" / "ir_runs" / e["part"] / "plan.json"
                if plan.exists():
                    for t, n in profile.plan_type_counts(json.loads(plan.read_text(encoding="utf-8"))["plan"]).items():
                        old[t] = old.get(t, 0) + n
        archive = profile.archive_keyword_counts(a.source) if a.source else {}
        flags = profile.bias_flags(dev_c, held_c)
        (root / "profile.html").write_text(profile.render_html(dev_c, held_c, old, archive, flags), encoding="utf-8")
        print(f"profile.html written; {len(flags)} bias flag(s)")
    elif a.step == "signoff":
        from bench import crosscheck
        if not (a.part and a.by):
            ap.error("signoff needs PART and --by NAME")
        k = Key.load(root / a.part / "key.json")
        if not crosscheck.sign_human(k, a.by):
            print(f"{a.part}: {len(k.open_flags())} open flag(s); set 'resolution' on each in key.json first")
            return 1
        k.save(root / a.part / "key.json")
        print(f"{a.part}: signed by {a.by}")
    elif a.step == "status":
        for part in parts:
            d = root / part
            have = [n for n in ("drawing.pdf", "drawing.dxf", "reference.step", "key.json", "review.html") if (d / n).exists()]
            k = Key.load(d / "key.json") if (d / "key.json").exists() else None
            print(f"{part:10s} {len(have)}/5 files  flags={len(k.open_flags()) if k else '-'}  "
                  f"signed={k.signoff['kind'] if k and k.signed else 'no'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests**

Run: `& $PY -m pytest tests/test_bench_review.py tests/test_bench_prep.py -q -p no:cacheprovider`
Expected: 2 passed.

- [ ] **Step 6: Full suite**

Run: `& $PY -m pytest tests/ -q -p no:cacheprovider`
Expected: everything passes (the earlier 415 plus the new bench tests). No test needs SolidWorks or MTI data.

- [ ] **Step 7: Commit**

```powershell
git add bench/review.py bench/prep.py tests/test_bench_review.py tests/test_bench_prep.py
git commit -m "feat(bench): review sheets and the resumable prep CLI`n`nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Real data. Install ODA, configure, prepare the 14 parts

No code. Real runs on this machine. **Ask the user before installing anything.**

- [ ] **Step 1: ODA File Converter.** Ask the user to approve the download, then install the free ODA File Converter from https://www.opendesign.com/guestfiles/oda_file_converter. Find the exe:
  `Get-ChildItem 'C:\Program Files\ODA' -Recurse -Filter ODAFileConverter.exe | Select -First 1 FullName`
- [ ] **Step 2: `.env`.** Create `2D-3D-CAD-Test-Generation/.env` (git-ignored) with:
  ```
  MTI_BENCH_DATA=<chosen data folder, e.g. the dataset folder>\bench
  ODA_CONVERTER=<exe path from step 1>
  ```
  Create the data folder. Confirm with `git status` that `.env` is not listed.
- [ ] **Step 3: Copy sources.**
  `& $PY -m bench.prep copy --source "<MTI Example Drawings folder>"`
  Expected: 14 parts `ok`.
- [ ] **Step 4: DXF.** `& $PY -m bench.prep dxf`. Expected: 14 `ok`. Spot-check one with `& $PY -c "from bench.dxfread import read; d=read(r'<root>\A050381E\drawing.dxf'); print(len(d.dims), d.callouts[:3], d.general_tol)"`. Expected: dimensions present, the `.38-16 TAP` callout, and a general tolerance table.
- [ ] **Step 5: SolidWorks.** Start SolidWorks and wait for COM, then run `& $PY -m bench.prep pdf` and `& $PY -m bench.prep step`. Expected: 14 `ok` each. Re-run any `failed` part after restarting SolidWorks (the steps resume).
- [ ] **Step 6: Visual check of the PDFs.** Render all 14 `drawing.pdf` into one contact sheet (as on 2026-10-12) and look at it. Every drawing must be complete, with nothing cropped or tiny.
- [ ] **Step 7: Data test.** `& $PY -m pytest tests/test_bench_manifest.py -q -p no:cacheprovider`. Expected: `test_mti_parts_have_data_files` now runs and passes.

---

### Task 14: Keys, cross-check, review, spot-check, profile

- [ ] **Step 1: Keys.** `& $PY -m bench.prep keys`. Expected: 14 `ok`. A `KeygenError` "n solids" means the model is a multi-body part. Record it and flag it for the user; do not hack around it.
- [ ] **Step 2: Cross-check + review sheets.** `& $PY -m bench.prep check` then `& $PY -m bench.prep review`, then `& $PY -m bench.prep status`.
- [ ] **Step 3: Tune the heuristics on format-dev parts only.** If keygen or crosscheck produce systematic noise, fix the code using A050291E, A050381E or A050511E. Example noise: every drawing's title-block tolerance values flagged. Add a regression test for each fix, commit, and re-run. These tools are benchmark *instruments*, not the pipeline, so held-out keys may be *looked at* to confirm a fix. They must never be used to tune the pipeline.
- [ ] **Step 4: Spot-check with the user.** Open each flagged part's `review.html`, including 1807408E, which is always reviewed. Go through the flags with the user. Record each decision as a `resolution` in `key.json`. Fix wrong keys in `key.json` by hand, noting it in the resolution. Then run `& $PY -m bench.prep signoff <part> --by smcanuff`.
  - **If the user rejects the 1807408E pairing:** move the entry from `held_out` to `parked` in `bench/manifest.yaml` with reason "pairing rejected at key review", and commit.
- [ ] **Step 5: Profile.** `& $PY -m bench.prep profile --source "<MTI Example Drawings folder>"`. Open `profile.html` with the user and note the bias flags.
- [ ] **Step 6: Status.** `& $PY -m bench.prep status`. Expected: all 14 (or 13) signed.

---

### Task 15: Record the milestone

**Files:**
- Modify: `STATE.md`, `CLAUDE.md` (Commands section)

- [ ] **Step 1: STATE.md.** Add a short dated section: sub-project 1 (benchmark dataset) done. Include the counts (parts signed, flags resolved), the split, the profile's bias flags, where the data lives (`MTI_BENCH_DATA`), and the next step (sub-project 2: scorer + stage blame).
- [ ] **Step 2: CLAUDE.md Commands.** Add:
  ```bash
  python -m bench.prep status                                   # benchmark data (needs MTI_BENCH_DATA in .env)
  python -m bench.prep <copy|dxf|pdf|step|keys|check|review|profile>
  ```
- [ ] **Step 3: Full suite and commit.**
  Run: `& $PY -m pytest tests/ -q -p no:cacheprovider`. Expected: all pass.
  ```powershell
  git add STATE.md CLAUDE.md
  git commit -m "docs: benchmark dataset (sub-project 1) built and signed off`n`nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
  ```
