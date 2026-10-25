# Benchmark Scorer and Stage Blame Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **User preference: one implementer + one combined review per task; fix only blocking issues.**

**Goal:** Score each generated SolidWorks part from 0 to 100 against its answer key (drawing = ground truth): importance-weighted features, tolerance-relative credit, structured drawing overrides. Blame every lost point on the pipeline stage that caused it. Everything is tested at no API cost.

**Architecture:**
- **Pure-Python core** in `bench/` (any OS):
  - `score_config` (constants)
  - `credit` (curve)
  - `weights` (tier × size)
  - `overrides` (drawing-wins / drawing-silent)
  - `align` (24 rotations + translation)
  - `match` (Hungarian)
  - `scoring` (part score)
  - `blame` (stage at fault)
  - `report` (json/html)
- **Thin CLI:** `bench/score.py`. It exports the SolidWorks part to STEP via the existing `bench/sw_tasks`, reads features with the existing `bench/keygen`, and scores.
- **Feature links:** `crosscheck` gains `link()` to record each feature's drawing values and tolerances.

**Tech stack:** Python 3.14, scipy (`linear_sum_assignment`), numpy, CadQuery/OCP (STEP, planted-error parts), PyYAML, pytest.

**Spec:** `docs/superpowers/specs/2026-10-24-benchmark-scorer-design.md`

---

## Conventions for every task

- **Worktree:** `C:\Users\USER\mti-2d-3d\.claude\worktrees\combined-sw2024`, branch `feat/mti-benchmark`. Work from `2D-3D-CAD-Test-Generation\`.
- **Python:** `$PY = "C:\Users\USER\mti-2d-3d\.claude\worktrees\repro-sw2024\2D-3D-CAD-Test-Generation\.venv\Scripts\python.exe"`. Set `$env:PYTHONUTF8=1`. Run pytest with `-p no:cacheprovider`. Baseline: **676 passed**.
- **Encoding:** ASCII source, UTF-8 without BOM. Write files with the file tool, not PowerShell `Set-Content`.
- **Commits:** local only, **never push**. Stage only the task's files.
- **Never stage:**
  - `pipeline/solidworks_builder.py`
  - `../docs/solidworks-macro-error-log.md`
  - `tests/test_save_model.py`
  - `output/`
  - `swxJRNL.*`
- **Commit trailer:** `-m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`.
- **Real MTI data:** `C:\Users\USER\mti-bench-data` (`MTI_BENCH_DATA` in `.env`). It is confidential: read only, except where a task says to run a `bench.prep` step. Tests needing it use `config.data_root(required=False)` and skip when it is `None`.
- **No API calls anywhere.** SolidWorks is needed only in Task 12. Start `SLDWORKS.exe` and wait for COM first; COM drops after idle minutes.

## Data model additions (used throughout)

- `Feature.tol: dict[str, float]` (default `{}`), with keys `"position"`, `"size"`, `"depth"`: the tolerance for that attribute, from the linked drawing value.
- `Feature.links: dict[str, list[float]]` (default `{}`), with the same keys: the drawing values that explain that attribute. Blame uses these.
- `Key.overrides: list[dict]` (default `[]`). Forms:
  - `{"feature": "K004", "attr": "depth", "value": 0.098, "note": "..."}`: replace a value with the drawing's
  - `{"feature": "K004", "attr": "depth", "silent": true, "note": "..."}`: the drawing doesn't state it, so don't score it
  - `{"type": "countersink", "expected_count": 12, "note": "..."}`: the drawing calls for more instances than the model has
  - `{"drawing_only": "linear 0.375", "note": "..."}`: a drawing value tied to no feature; reported, not scored

## File map

| File | Responsibility |
|---|---|
| `bench/features.py` | **modify:** add `tol`, `links`, `overrides` |
| `bench/score_config.yaml` + `bench/score_config.py` | constants plus a typed loader |
| `bench/credit.py` | the credit curve and attribute/feature credit |
| `bench/weights.py` | tiers, size factor, the synthetic base-body feature |
| `bench/overrides.py` | convert resolutions to structured overrides; apply them |
| `bench/align.py` | 24 proper rotations, transform features, best fit |
| `bench/match.py` | feature families, pair cost, gate, Hungarian |
| `bench/scoring.py` | `score_part()`: the part score and per-feature rows |
| `bench/blame.py` | stage blame and rollups |
| `bench/report.py` | `scores.json` + `report.html` |
| `bench/score.py` | CLI `python -m bench.score` |
| `bench/plant.py` | planted-error geometry (CadQuery) for tests and calibration |
| `bench/crosscheck.py` | **modify:** `link(key, drawing)` |
| `bench/prep.py` | **modify:** `link` step; `_hand_edited` ignores `tol`/`links` |
| `requirements.txt` | **modify:** add `scipy` |
| `tests/test_bench_score_*.py` | one test file per module |

---

### Task 1: Data model, config and loader

**Files:**
- Modify: `bench/features.py`, `requirements.txt`
- Create: `bench/score_config.yaml`, `bench/score_config.py`
- Test: `tests/test_bench_score_config.py`

- [ ] **Step 1: Failing tests** in `tests/test_bench_score_config.py`:

```python
"""Scorer config + data-model additions (tol, links, overrides)."""
from bench.features import Feature, Key
from bench.score_config import load


def test_defaults_load_and_are_sane():
    c = load()
    assert c.credit.drop == 0.5 and 4.0 < c.credit.k < 5.0
    assert abs(sum(c.shares.values()) - 1.0) < 1e-9
    assert c.tiers["base_body"] == 10 and c.tiers["thru_hole"] == 3 and c.tiers["tapped_hole"] == 1
    assert c.size_floor == 0.3 and c.extra_penalty == 0.5
    assert c.fallback_tol == {"inch": 0.005, "mm": 0.1}
    assert "countersink" in c.unsupported_types


def test_override_file(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("credit: {drop: 0.6}\n", encoding="utf-8")
    c = load(p)
    assert c.credit.drop == 0.6 and c.tiers["base_body"] == 10     # unspecified keys keep defaults


def test_feature_and_key_new_fields_roundtrip(tmp_path):
    f = Feature(id="K1", type="thru_hole", d=0.25, tol={"size": 0.005}, links={"size": [0.25]})
    k = Key(part="P", units="inch", source="s", envelope=[1, 1, 1], features=[f],
            overrides=[{"feature": "K1", "attr": "depth", "silent": True}])
    k.save(tmp_path / "k.json")
    assert Key.load(tmp_path / "k.json") == k


def test_old_key_without_new_fields_still_loads(tmp_path):
    import json
    d = {"part": "P", "units": "inch", "source": "s", "envelope": [1, 1, 1],
         "features": [{"id": "K1", "type": "thru_hole"}], "flags": [], "signoff": None, "version": 1}
    (tmp_path / "k.json").write_text(json.dumps(d), encoding="utf-8")
    k = Key.load(tmp_path / "k.json")
    assert k.overrides == [] and k.features[0].tol == {} and k.features[0].links == {}
```

- [ ] **Step 2:** `& $PY -m pytest tests/test_bench_score_config.py -q -p no:cacheprovider` → FAIL (no `bench.score_config`).

- [ ] **Step 3:** In `bench/features.py`:
  - **`Feature`:** add these two fields right after `note`:

```python
    tol: dict = field(default_factory=dict)      # {"position"|"size"|"depth": tolerance} from linked drawing values
    links: dict = field(default_factory=dict)    # {"position"|"size"|"depth": [drawing values]} (crosscheck.link)
```

  - **`Key`:** add `overrides: list = field(default_factory=list)` after `signoff` and before `version`. `from_dict` already passes unknown-free dicts, and the defaults make old files load.

Create `bench/score_config.yaml`:

```yaml
# Benchmark scorer constants (spec 2026-10-24). Change numbers here, never in code.
credit:
  drop: 0.5          # credit just past tolerance
  k: 4.48            # decay: credit = drop * exp(-(e - 1) / k) for e = error/tolerance > 1  (2x->0.40, 5x->0.20, 10x->0.07)
shares:              # attribute shares inside a feature's credit (renormalised over present attributes)
  position: 0.40
  size: 0.30
  depth: 0.15
  type: 0.15
tiers:               # importance tier weights by feature type
  base_body: 10
  bore: 3
  turned_diameter: 3
  thru_hole: 3
  slot: 3
  pocket_step: 3
  flat: 3
  boss: 3
  tapped_hole: 1
  counterbore: 1
  countersink: 1
  blind_hole: 1
  chamfer: 1
  fillet: 1
size_floor: 0.3      # size factor = clamp(sqrt(feature size / part size), size_floor, 1)
extra_penalty: 0.5   # an extra (unmatched generated) feature costs this x its own weight
type_mismatch_cost: 2.0   # added to the pair cost when matched types differ
gate:
  tol_multiple: 20   # pairs farther than min(20 x tol, 10% of part size) never match
  part_fraction: 0.10
fallback_tol: {inch: 0.005, mm: 0.1}
unsupported_types: [countersink]   # cannot be expressed in the IR today (blame = unsupported)
```

Create `bench/score_config.py`:

```python
"""Typed loader for bench/score_config.yaml (defaults + optional override file)."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

DEFAULT_PATH = Path(__file__).resolve().parent / "score_config.yaml"


@dataclass(frozen=True)
class Credit:
    drop: float
    k: float


@dataclass(frozen=True)
class Config:
    credit: Credit
    shares: dict
    tiers: dict
    size_floor: float
    extra_penalty: float
    type_mismatch_cost: float
    gate_tol_multiple: float
    gate_part_fraction: float
    fallback_tol: dict
    unsupported_types: tuple


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load(path: Optional[Path] = None) -> Config:
    raw = yaml.safe_load(DEFAULT_PATH.read_text(encoding="utf-8"))
    if path is not None:
        raw = _merge(raw, yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})
    return Config(credit=Credit(**raw["credit"]), shares=dict(raw["shares"]), tiers=dict(raw["tiers"]),
                  size_floor=float(raw["size_floor"]), extra_penalty=float(raw["extra_penalty"]),
                  type_mismatch_cost=float(raw["type_mismatch_cost"]),
                  gate_tol_multiple=float(raw["gate"]["tol_multiple"]),
                  gate_part_fraction=float(raw["gate"]["part_fraction"]),
                  fallback_tol=dict(raw["fallback_tol"]), unsupported_types=tuple(raw["unsupported_types"]))
```

Add the line `scipy>=1.11` to `requirements.txt`.

- [ ] **Step 4:** Run the tests: 4 pass. Then run the full suite: 0 failures.
- [ ] **Step 5:** Commit `bench/features.py bench/score_config.yaml bench/score_config.py requirements.txt tests/test_bench_score_config.py` with the message `feat(bench): scorer config and key fields (tol, links, overrides)`.

---

### Task 2: Credit curve

**Files:** Create `bench/credit.py`. Test: `tests/test_bench_score_credit.py`.

- [ ] **Step 1: Failing tests**

```python
"""Credit: full inside tolerance, a 0.5 drop just past it, then exponential decay."""
import math

import pytest

from bench.credit import attr_credit, feature_credit
from bench.score_config import load

C = load()


@pytest.mark.parametrize("e, expected", [(0, 1.0), (0.5, 1.0), (1.0, 1.0), (2, 0.40), (5, 0.20), (10, 0.067)])
def test_curve_points(e, expected):
    assert attr_credit(e * 0.005, 0.005, C) == pytest.approx(expected, abs=0.005)


def test_drop_just_past_tolerance():
    assert attr_credit(0.005 * 1.0001, 0.005, C) == pytest.approx(0.5, abs=1e-3)


def test_monotone_non_increasing():
    vals = [attr_credit(x / 1000, 0.005, C) for x in range(0, 200)]
    assert all(a >= b - 1e-12 for a, b in zip(vals, vals[1:]))
    assert all(0.0 <= v <= 1.0 for v in vals)


def test_zero_tolerance_is_guarded():
    assert attr_credit(0.0, 0.0, C) == 1.0 and attr_credit(1e-9, 0.0, C) < 1.0


def test_feature_credit_renormalises_missing_attributes():
    # only size and type present: shares 0.30 and 0.15 renormalise to 2/3 and 1/3
    assert feature_credit({"size": 0.5, "type": 1.0}, C) == pytest.approx(0.5 * 2 / 3 + 1 / 3)
    assert feature_credit({}, C) == 1.0
    assert feature_credit({"position": 1.0, "size": 1.0, "depth": 1.0, "type": 1.0}, C) == 1.0
```

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** `bench/credit.py`:

```python
"""Attribute error -> credit (spec 2026-10-24, 'Credit')."""
from __future__ import annotations

import math

from bench.score_config import Config

_EPS = 1e-12


def attr_credit(error: float, tol: float, cfg: Config) -> float:
    """1 within tolerance; drop * exp(-(e - 1) / k) beyond it, with e = |error| / tol."""
    error = abs(error)
    if tol <= _EPS:
        return 1.0 if error <= _EPS else cfg.credit.drop * math.exp(-1.0 / cfg.credit.k)
    e = error / tol
    if e <= 1.0 + 1e-9:
        return 1.0
    return cfg.credit.drop * math.exp(-(e - 1.0) / cfg.credit.k)


def feature_credit(attr_credits: dict, cfg: Config) -> float:
    """Weighted mix of the attributes present; shares renormalise over them."""
    present = {a: c for a, c in attr_credits.items() if a in cfg.shares}
    total = sum(cfg.shares[a] for a in present)
    if total <= 0:
        return 1.0
    return sum(cfg.shares[a] * c for a, c in present.items()) / total
```

- [ ] **Step 4:** Run: 10 pass. Then the full suite.
- [ ] **Step 5:** Commit `bench/credit.py tests/test_bench_score_credit.py` with the message `feat(bench): scorer credit curve`.

---

### Task 3: Weights and the base-body feature

**Files:** Create `bench/weights.py`. Test: `tests/test_bench_score_weights.py`.

- [ ] **Step 1: Failing tests**

```python
"""Importance = tier x clamp(sqrt(feature size / part size), floor, 1); base body synthesised from the key."""
import pytest

from bench.features import Feature, Key
from bench.score_config import load
from bench.weights import BASE_ID, base_body, feature_size, weight

C = load()
KEY = Key(part="P", units="inch", source="s", envelope=[6.0, 4.0, 0.5], features=[
    Feature(id="K1", type="thru_hole", d=0.25, depth=0.5),
    Feature(id="K2", type="bore", d=3.0, depth=0.5),
    Feature(id="K3", type="tapped_hole", d=0.2, depth=0.4),
    Feature(id="K4", type="hole_pattern", members=["K1"])])


def test_base_body_from_envelope():
    b = base_body(KEY)
    assert b.id == BASE_ID and b.type == "base_body" and b.size == [6.0, 4.0, 0.5]


def test_sizes():
    assert feature_size(KEY.feature("K2")) == 3.0
    assert feature_size(base_body(KEY)) == 6.0


def test_weights_tier_times_size_with_floor():
    part = 6.0
    assert weight(base_body(KEY), part, C) == pytest.approx(10.0)
    assert weight(KEY.feature("K2"), part, C) == pytest.approx(3 * (3.0 / 6.0) ** 0.5)
    assert weight(KEY.feature("K1"), part, C) == pytest.approx(3 * 0.3)       # floored
    assert weight(KEY.feature("K3"), part, C) == pytest.approx(1 * 0.3)


def test_patterns_have_no_weight():
    assert weight(KEY.feature("K4"), 6.0, C) == 0.0
```

- [ ] **Step 2:** Run → FAIL. (Note: `Feature` validates `type` against `FEATURE_TYPES`, so `base_body` must be added to `FEATURE_TYPES` in `bench/features.py`, appended at the end. Keygen never emits it.)
- [ ] **Step 3:** Append `"base_body"` to `FEATURE_TYPES` in `bench/features.py`, then create `bench/weights.py`:

```python
"""Importance weights (spec 2026-10-24, 'Weights')."""
from __future__ import annotations

import math

from bench.features import Feature, Key
from bench.score_config import Config

BASE_ID = "BASE"


def base_body(key: Key) -> Feature:
    """Synthetic tier-1 feature: the envelope (plus, implicitly, the main profile) of the part."""
    return Feature(id=BASE_ID, type="base_body", size=[float(x) for x in key.envelope],
                   note="synthetic: part envelope")


def feature_size(f: Feature) -> float:
    vals = [v for v in (f.d, f.cbore_d, f.csink_d) if v]
    if f.size:
        vals += [v for v in f.size if v]
    if f.type not in ("base_body",) and f.depth:
        vals.append(f.depth)
    return max(vals) if vals else 0.0


def weight(f: Feature, part_size: float, cfg: Config) -> float:
    tier = cfg.tiers.get(f.type, 0.0)
    if tier == 0.0:
        return 0.0                                   # e.g. hole_pattern: scored through its members
    if f.type == "base_body" or part_size <= 0:
        return float(tier)
    factor = math.sqrt(max(feature_size(f), 0.0) / part_size)
    return float(tier) * min(1.0, max(cfg.size_floor, factor))
```

Check against the test values: `feature_size` takes the max of d and depth, so K1 = 0.5 (√(0.5/6) = 0.289 → floor 0.3), K3 = 0.4 (→ 0.3), K2 = 3.0 (√0.5).

- [ ] **Step 4:** Run, then the full suite.
- [ ] **Step 5:** Commit `bench/features.py bench/weights.py tests/test_bench_score_weights.py` with the message `feat(bench): scorer importance weights and base-body feature`.

---

### Task 4: Feature links (drawing values + tolerances) and the `link` prep step

**Files:**
- Modify: `bench/crosscheck.py` (add `link`)
- Modify: `bench/prep.py` (add a `link` step; `_hand_edited` ignores `tol`/`links`)
- Test: `tests/test_bench_score_link.py`

- [ ] **Step 1: Failing tests**

```python
"""crosscheck.link records, per key feature attribute, the drawing values that explain it and their tolerance."""
from bench.callouts import parse
from bench.crosscheck import link
from bench.dxfread import Dim, Drawing
from bench.features import Feature, Key


def _key():
    return Key(part="P", units="inch", source="s", envelope=[4.0, 3.0, 0.5], features=[
        Feature(id="K1", type="thru_hole", axis=[0, 0, 1], center=[0.5, 0.5, 0], d=0.344, depth=0.5, thru=True),
        Feature(id="K2", type="thru_hole", axis=[0, 0, 1], center=[3.5, 0.5, 0], d=0.344, depth=0.5, thru=True)])


def _drawing():
    return Drawing(dims=[Dim("linear", 4.0, 4.0, "<>", False, 3), Dim("linear", 0.5, 0.5, "<>", False, 2),
                         Dim("linear", 3.0, 3.0, "<>", False, 3)],
                   callouts=[parse(".344 DIA. THRU (2) HLS.")], general_tol={3: 0.005, 2: 0.01}, units_hint="inch")


def test_link_records_values_and_tolerances():
    k = _key()
    link(k, _drawing())
    f = k.feature("K1")
    assert 0.344 in f.links["size"] and f.tol["size"] == 0.005          # callout .344 = 3 decimals
    assert 0.5 in f.links["position"] and f.tol["position"] == 0.01     # .50 dim = 2 decimals
    assert k.feature("K2").links["position"]                            # 3.0 between holes / 0.5 to edge


def test_link_is_idempotent_and_touches_nothing_else():
    k = _key()
    link(k, _drawing())
    before = k.to_dict()
    link(k, _drawing())
    assert k.to_dict() == before
    assert k.flags == [] and k.signoff is None


def test_unlinked_attribute_gets_fallback_tolerance():
    k = _key()
    link(k, Drawing(dims=[], callouts=[], general_tol={}, units_hint="inch"))
    assert k.feature("K1").links == {} and k.feature("K1").tol == {}     # scorer uses fallback_tol
```

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Add `link()` to `bench/crosscheck.py`. Reuse the module's existing helpers (`_hole_diameters`, `_positions`, `_dim_values`, `_tol`, `_callout_decimals`, `_near`). Read them first. It must:
  - **Recompute links:** for each key feature with a `center` (holes, bores, slots, turned features), clear `f.links`/`f.tol`, then build:
    - **`size`:** stated diameter values (for holes, `_hole_diameters`; for others, any diameter dim) within tolerance of `f.d`, `f.cbore_d` or `f.csink_d`
    - **`position`:** stated distances within tolerance of the feature's position candidates. Use the same candidate list `_check_positions` builds; refactor that list into a helper `_position_candidates(key, holes, f)` and use it in both places.
    - **`depth`:** stated values within tolerance of `f.depth` / `f.cbore_depth`
  - **Record tolerance:** for each attribute with at least one link, store the tightest tolerance among the linked values (each value carries its tolerance in the `Stated` pairs).
  - **Leave everything else alone:** flags, signoff, types and geometry are untouched; it is idempotent.

In `bench/prep.py`:
  - add `step_link`: for each part, load `key.json`, run `crosscheck.link(key, dxfread.read(d / "drawing.dxf"))`, save, and log `ok: <n> features linked`. It is allowed on human-signed keys because it only adds `tol`/`links`.
  - register `"link"` in `STEPS`.
  - make `_hand_edited` compare features with `tol` and `links` removed, so linking never makes `check` think a key was hand-edited.

Add a prep test to the same file:

```python
def test_prep_link_keeps_signoff(tmp_path, monkeypatch):
    import json
    from bench import dxfread, prep
    monkeypatch.setenv("MTI_BENCH_DATA", str(tmp_path))
    part = "A050381E"
    d = tmp_path / part
    d.mkdir()
    k = _key()
    k.part = part
    k.signoff = {"kind": "human", "by": "x", "date": "2026-10-24"}
    k.save(d / "key.json")
    (d / "drawing.dxf").write_text("", encoding="utf-8")
    monkeypatch.setattr(dxfread, "read", lambda p: _drawing())
    assert prep.main(["link", "--parts", part]) == 0
    k2 = Key.load(d / "key.json")
    assert k2.signoff["kind"] == "human" and k2.feature("K1").links
```

- [ ] **Step 4:** Run the new tests and the full suite. Existing crosscheck tests must still pass, since the `_check_positions` refactor must not change its behaviour.
- [ ] **Step 5:** Commit `bench/crosscheck.py bench/prep.py tests/test_bench_score_link.py` with the message `feat(bench): crosscheck.link records drawing values + tolerances per feature; prep link`.

---

### Task 5: Overrides (drawing-wins / drawing-silent → structured)

**Files:** Create `bench/overrides.py`. Test: `tests/test_bench_score_overrides.py`.

- [ ] **Step 1: Failing tests**

```python
"""Structured overrides: convert policy resolutions; apply to an effective key."""
from bench.features import Feature, Flag, Key
from bench.overrides import apply, from_resolutions


def _key():
    return Key(part="P", units="inch", source="s", envelope=[3, 3, 0.625], features=[
        Feature(id="K004", type="bore", d=0.985, depth=0.22, center=[1.5, 1.5, 0], axis=[0, 0, 1]),
        Feature(id="K005", type="counterbore", d=0.281, depth=0.245, cbore_d=0.4375, cbore_depth=0.044,
                center=[0.5, 0.5, 0.625], axis=[0, 0, 1]),
        Feature(id="K006", type="countersink", d=0.28, csink_d=0.5, center=[2, 2, 0], axis=[0, 0, 1])],
        flags=[Flag("unexplained_key_value", "counterbore cbore_depth=0.0437 not stated", "K005",
                    "drawing-silent: model detail not stated on the drawing; do not score it (...)"),
               Flag("count_mismatch", "callout '... 12-HOLES' says 12, key has 8", None,
                    "drawing-wins: score against the drawing, not the model (...)"),
               Flag("unexplained_drawing_value", "linear 0.375 (.375) matches no key quantity", None,
                    "drawing-wins: score against the drawing, not the model (...)")])


def test_from_resolutions():
    ov = from_resolutions(_key())
    assert {"feature": "K005", "attr": "depth", "silent": True} in [
        {k: o[k] for k in ("feature", "attr", "silent") if k in o} for o in ov]
    assert any(o.get("type") == "countersink" and o.get("expected_count") == 12 for o in ov)
    assert any(o.get("drawing_only") == "linear 0.375" for o in ov)


def test_apply_value_and_silent_and_counts():
    k = _key()
    k.overrides = [{"feature": "K004", "attr": "depth", "value": 0.098},
                   {"feature": "K005", "attr": "depth", "silent": True},
                   {"type": "countersink", "expected_count": 3}]
    eff = apply(k)
    assert eff.key.feature("K004").depth == 0.098
    assert ("K005", "depth") in eff.silent
    assert eff.expected_counts == {"countersink": 3}
    assert k.feature("K004").depth == 0.22                    # original key untouched
```

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** `bench/overrides.py`:

```python
"""Drawing-is-ground-truth overrides (spec 2026-10-24, 'Key additions' 2)."""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

from bench.features import Key

_ATTR = {"cbore_depth": "depth", "depth": "depth", "d": "size", "cbore_d": "size", "csink_d": "size",
         "position": "position"}
_SAYS = re.compile(r"says (\d+), key has (\d+)")
_COUNT_TYPE = (("C'SINK", "countersink"), ("CSK", "countersink"), ("C'BORE", "counterbore"),
               ("CBORE", "counterbore"), ("TAP", "tapped_hole"))


@dataclass
class Effective:
    key: Key
    silent: set = field(default_factory=set)            # {(feature_id, attr)}
    expected_counts: dict = field(default_factory=dict)  # {feature type: count}
    drawing_only: list = field(default_factory=list)     # [str]


def _attr_of(detail: str) -> str:
    for name, attr in _ATTR.items():
        if f"{name}=" in detail:
            return attr
    return "position" if "position" in detail or "located" in detail else "size"


def from_resolutions(key: Key) -> list[dict]:
    """Structured overrides implied by policy resolutions (prep accept / human)."""
    out = []
    for f in key.flags:
        r = (f.resolution or "")
        if r.startswith("drawing-silent") and f.feature:
            out.append({"feature": f.feature, "attr": _attr_of(f.detail), "silent": True, "note": f.detail})
        elif r.startswith("drawing-wins") and f.kind == "count_mismatch":
            m = _SAYS.search(f.detail)
            typ = next((t for tag, t in _COUNT_TYPE if tag in f.detail.upper()), "thru_hole")
            if m:
                out.append({"type": typ, "expected_count": int(m.group(1)), "note": f.detail})
        elif r.startswith("drawing-wins") and f.kind == "unexplained_drawing_value":
            out.append({"drawing_only": " ".join(f.detail.split()[:2]), "note": f.detail})
    return out


def apply(key: Key) -> Effective:
    k = copy.deepcopy(key)
    eff = Effective(key=k)
    for o in list(k.overrides) + [x for x in from_resolutions(k) if x not in k.overrides]:
        if "drawing_only" in o:
            eff.drawing_only.append(o["drawing_only"])
        elif "expected_count" in o:
            eff.expected_counts[o["type"]] = int(o["expected_count"])
        elif o.get("silent"):
            eff.silent.add((o["feature"], o["attr"]))
        elif "value" in o:
            setattr(k.feature(o["feature"]), o["attr"], o["value"])
    return eff
```

(`from_resolutions` deduplicates against explicit overrides by exact dict equality. That's good enough, because explicit overrides take precedence when applied in order: explicit ones come first.)

- [ ] **Step 4:** Run, then the full suite.
- [ ] **Step 5:** Commit `bench/overrides.py tests/test_bench_score_overrides.py` with the message `feat(bench): structured drawing-wins / drawing-silent overrides`.

---

### Task 6: Alignment

**Files:** Create `bench/align.py`. Test: `tests/test_bench_score_align.py`.

Both keys are in their own bounding-box-minimum frames (`keygen`). The generated part may be rotated by one of the 24 axis-aligned proper rotations.

- [ ] **Step 1: Failing tests**

```python
"""align: 24 proper rotations; transforming a key keeps it in a bbox-min frame; best fit recovers the pose."""
import random

import numpy as np
import pytest

from bench.align import ROTATIONS, best_fit, transform
from bench.features import Feature, Key


def _key():
    return Key(part="P", units="inch", source="s", envelope=[6.0, 4.0, 1.0], features=[
        Feature(id="K1", type="thru_hole", axis=[0, 0, 1], center=[1.0, 1.0, 0.0], d=0.25, depth=1.0),
        Feature(id="K2", type="thru_hole", axis=[0, 0, 1], center=[5.0, 1.0, 0.0], d=0.25, depth=1.0),
        Feature(id="K3", type="blind_hole", axis=[1, 0, 0], center=[0.0, 3.0, 0.5], d=0.2, depth=0.6),
        Feature(id="K4", type="pocket_step", normal=[0, 0, 1], offset=0.7, size=[2.0, 1.0, 0.0])])


def test_24_proper_rotations():
    assert len(ROTATIONS) == 24
    assert all(round(np.linalg.det(R)) == 1 for R in ROTATIONS)


@pytest.mark.parametrize("i", range(24))
def test_best_fit_recovers_every_rotation(i):
    key = _key()
    moved = transform(key, ROTATIONS[i])
    fit = best_fit(key, moved)
    back = fit.apply(moved)
    for f in key.features:
        g = next(x for x in back.features if x.id == f.id)
        if f.center:
            assert np.allclose(g.center, f.center, atol=1e-9)
        if f.axis:
            assert np.allclose(np.abs(g.axis), np.abs(f.axis), atol=1e-9)
    assert np.allclose(back.envelope, key.envelope)
```

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** `bench/align.py`:

```python
"""Rigid fit of a generated key onto the answer key (spec 2026-10-24, 'Architecture: align').

Keys live in their own bbox-min frames. A pose = one of the 24 proper axis-aligned rotations,
applied about the origin, followed by the shift that puts the rotated bbox back at the origin,
then a small translation refined from matched feature centres."""
from __future__ import annotations

import copy
import itertools
from dataclasses import dataclass

import numpy as np

from bench.features import Feature, Key


def _rotations() -> list[np.ndarray]:
    out = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            R = np.zeros((3, 3))
            for row, (col, s) in enumerate(zip(perm, signs)):
                R[row, col] = s
            if round(np.linalg.det(R)) == 1:
                out.append(R)
    return out


ROTATIONS = _rotations()


def _canon(v: np.ndarray) -> list[float]:
    for c in v:
        if abs(c) > 1e-9:
            return [float(x) for x in (v if c > 0 else -v)]
    return [float(x) for x in v]


def transform(key: Key, R: np.ndarray, t=(0.0, 0.0, 0.0)) -> Key:
    """Rotate about the origin, shift the rotated bbox back to the origin, then translate by t."""
    k = copy.deepcopy(key)
    env = np.asarray(key.envelope, float)
    corners = np.array([[x, y, z] for x in (0, env[0]) for y in (0, env[1]) for z in (0, env[2])])
    rc = corners @ R.T
    shift = -rc.min(axis=0) + np.asarray(t, float)
    k.envelope = [float(v) for v in (rc.max(axis=0) - rc.min(axis=0))]
    for f in k.features:
        if f.center is not None:
            f.center = [float(v) for v in (R @ np.asarray(f.center, float) + shift)]
        if f.axis is not None:
            f.axis = _canon(R @ np.asarray(f.axis, float))
        if f.normal is not None:
            n = R @ np.asarray(f.normal, float)
            # offset of a plane n.x = o moves with the shift; keep the canonical normal sign
            o = float(f.offset or 0.0)
            point = n * o + shift
            cn = np.asarray(_canon(n))
            f.normal, f.offset = [float(x) for x in cn], float(cn @ point)
        if f.size is not None and f.type in ("base_body",):
            f.size = list(k.envelope)
    return k


@dataclass
class Fit:
    R: np.ndarray
    t: np.ndarray
    cost: float

    def apply(self, key: Key) -> Key:
        return transform(key, self.R, self.t)


def _centres(key: Key) -> dict:
    return {f.id: np.asarray(f.center, float) for f in key.features if f.center is not None}


def best_fit(target: Key, moving: Key, pair=None) -> Fit:
    """Try all 24 rotations; for each, pair features (pair(target, candidate) -> [(tid, mid)]),
    refine the translation by mean centre offset, and keep the lowest mean pair distance plus a
    large penalty per unpaired feature. Default pairing: nearest same-type centre."""
    pair = pair or _nearest_same_type
    best = None
    for R in ROTATIONS:
        cand = transform(moving, R)
        if np.max(np.abs(np.asarray(cand.envelope) - np.asarray(target.envelope))) > 0.25 * max(target.envelope):
            continue                                       # envelope shape disagrees badly: wrong pose
        t = np.zeros(3)
        for _ in range(2):
            pairs = pair(target, transform(moving, R, t))
            tc, mc = _centres(target), _centres(transform(moving, R, t))
            d = [tc[a] - mc[b] for a, b in pairs if a in tc and b in mc]
            if d:
                t = t + np.mean(d, axis=0)
        moved = transform(moving, R, t)
        pairs = pair(target, moved)
        tc, mc = _centres(target), _centres(moved)
        dist = [float(np.linalg.norm(tc[a] - mc[b])) for a, b in pairs if a in tc and b in mc]
        unpaired = len(target.features) + len(moved.features) - 2 * len(pairs)
        cost = (np.mean(dist) if dist else 0.0) + unpaired * max(target.envelope) \
            + float(np.abs(np.asarray(moved.envelope) - np.asarray(target.envelope)).sum())
        if best is None or cost < best.cost - 1e-12:
            best = Fit(R, t, cost)
    return best or Fit(np.eye(3), np.zeros(3), float("inf"))


def _nearest_same_type(target: Key, moving: Key) -> list[tuple[str, str]]:
    used, out = set(), []
    for f in target.features:
        if f.center is None:
            continue
        cands = [g for g in moving.features if g.center is not None and g.type == f.type and g.id not in used]
        if cands:
            g = min(cands, key=lambda g: np.linalg.norm(np.asarray(g.center) - np.asarray(f.center)))
            used.add(g.id)
            out.append((f.id, g.id))
    return out
```

- [ ] **Step 4:** Run. All 24 parametrised cases must pass. If a symmetric configuration gives an equal-cost alternative pose, the assertion on centres will fail, so make the test key asymmetric (it is: K3 sits on one side). Then run the full suite.
- [ ] **Step 5:** Commit `bench/align.py tests/test_bench_score_align.py` with the message `feat(bench): scorer alignment over 24 proper rotations`.

---

### Task 7: Matching

**Files:** Create `bench/match.py`. Test: `tests/test_bench_score_match.py`.

- [ ] **Step 1: Failing tests**

```python
"""match: families, tolerance-scaled cost, gate, optimal one-to-one assignment."""
from bench.features import Feature
from bench.match import family, match
from bench.score_config import load

C = load()


def _h(i, x, y, d=0.25, t="thru_hole"):
    return Feature(id=i, type=t, axis=[0, 0, 1], center=[x, y, 0.0], d=d, depth=0.5)


def test_families():
    assert family("counterbore") == family("thru_hole") == "hole"
    assert family("bore") == family("turned_diameter") == "round"
    assert family("flat") == family("pocket_step") == "planar"


def test_optimal_assignment_beats_greedy():
    key = [_h("K1", 0, 0), _h("K2", 1.0, 0)]
    gen = [_h("G1", 0.6, 0), _h("G2", 1.05, 0)]
    pairs, missing, extra = match(key, gen, part_size=10.0, tol_of=lambda f, a: 0.005, cfg=C)
    assert sorted(pairs) == [("K1", "G1"), ("K2", "G2")]
    assert missing == [] and extra == []


def test_gate_makes_far_features_missing_and_extra():
    key = [_h("K1", 0, 0)]
    gen = [_h("G1", 5.0, 0)]                     # 5" away on a 10" part: beyond min(20*0.005, 1.0)
    pairs, missing, extra = match(key, gen, part_size=10.0, tol_of=lambda f, a: 0.005, cfg=C)
    assert pairs == [] and missing == ["K1"] and extra == ["G1"]


def test_type_mismatch_still_pairs_within_family():
    pairs, _, _ = match([_h("K1", 0, 0, t="counterbore")], [_h("G1", 0, 0)], 10.0, lambda f, a: 0.005, C)
    assert pairs == [("K1", "G1")]


def test_patterns_and_base_body_are_not_matched_here():
    pairs, missing, extra = match([Feature(id="K9", type="hole_pattern", members=["K1"])],
                                  [Feature(id="G9", type="hole_pattern", members=["G1"])], 10.0,
                                  lambda f, a: 0.005, C)
    assert pairs == [] and missing == [] and extra == []
```

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** `bench/match.py`:

```python
"""Feature matching (spec 2026-10-24, 'Matching')."""
from __future__ import annotations

import math
from typing import Callable

import numpy as np
from scipy.optimize import linear_sum_assignment

from bench.features import HOLE_TYPES, Feature
from bench.score_config import Config

_FAMILY = {**{t: "hole" for t in HOLE_TYPES}, "bore": "round", "turned_diameter": "round", "boss": "round",
           "slot": "slot", "flat": "planar", "pocket_step": "planar", "chamfer": "edge", "fillet": "edge"}
INF = 1e9


def family(t: str):
    return _FAMILY.get(t)


def position_error(a: Feature, b: Feature) -> float:
    """Distance between centres, ignoring the offset along a shared axis (a hole may start at either end)."""
    if a.center is None or b.center is None:
        if a.normal is not None and b.normal is not None:
            return abs((a.offset or 0.0) - (b.offset or 0.0))
        return 0.0
    d = np.asarray(a.center, float) - np.asarray(b.center, float)
    if a.axis is not None:
        ax = np.asarray(a.axis, float)
        d = d - ax * float(d @ ax)
    return float(np.linalg.norm(d))


def size_error(a: Feature, b: Feature) -> float:
    pairs = [(a.d, b.d), (a.cbore_d, b.cbore_d), (a.csink_d, b.csink_d)]
    errs = [abs(x - y) for x, y in pairs if x is not None and y is not None]
    if a.size and b.size:
        errs.append(max(abs(x - y) for x, y in zip(sorted(a.size), sorted(b.size))))
    return max(errs) if errs else 0.0


def match(key: list[Feature], gen: list[Feature], part_size: float,
          tol_of: Callable[[Feature, str], float], cfg: Config):
    """-> (pairs [(key_id, gen_id)], missing key ids, extra gen ids)."""
    pairs, missing, extra = [], [], []
    for fam in sorted({family(f.type) for f in key + gen} - {None}):
        ks = [f for f in key if family(f.type) == fam]
        gs = [g for g in gen if family(g.type) == fam]
        if not ks or not gs:
            missing += [f.id for f in ks]
            extra += [g.id for g in gs]
            continue
        cost = np.full((len(ks), len(gs)), INF)
        for i, f in enumerate(ks):
            tp, ts = tol_of(f, "position"), tol_of(f, "size")
            gate = min(cfg.gate_tol_multiple * tp, cfg.gate_part_fraction * part_size)
            for j, g in enumerate(gs):
                pe = position_error(f, g)
                if pe > gate:
                    continue
                cost[i, j] = pe / tp + size_error(f, g) / ts + (0 if f.type == g.type else cfg.type_mismatch_cost)
        rows, cols = linear_sum_assignment(cost)
        used_k, used_g = set(), set()
        for r, c in zip(rows, cols):
            if cost[r, c] < INF:
                pairs.append((ks[r].id, gs[c].id))
                used_k.add(r)
                used_g.add(c)
        missing += [f.id for i, f in enumerate(ks) if i not in used_k]
        extra += [g.id for j, g in enumerate(gs) if j not in used_g]
    return pairs, missing, extra
```

- [ ] **Step 4:** Run, then the full suite.
- [ ] **Step 5:** Commit `bench/match.py tests/test_bench_score_match.py` with the message `feat(bench): scorer feature matching (Hungarian, gated)`.

---

### Task 8: Part score

**Files:** Create `bench/scoring.py`. Test: `tests/test_bench_score_part.py`.

- [ ] **Step 1: Failing tests** (identity, planted errors at feature level, extras, overrides, expected counts, bounds):

```python
"""score_part: identity = 100; planted errors cost exactly what the curve and weights say."""
import copy

import numpy as np
import pytest

from bench.align import ROTATIONS, transform
from bench.features import Feature, Key
from bench.score_config import load
from bench.scoring import score_part
from bench.weights import base_body, weight

C = load()


def _key():
    return Key(part="P", units="inch", source="s", envelope=[6.0, 4.0, 1.0], features=[
        Feature(id="K1", type="thru_hole", axis=[0, 0, 1], center=[1.0, 1.0, 0.0], d=0.5, depth=1.0, thru=True),
        Feature(id="K2", type="thru_hole", axis=[0, 0, 1], center=[5.0, 1.0, 0.0], d=0.5, depth=1.0, thru=True),
        Feature(id="K3", type="tapped_hole", axis=[1, 0, 0], center=[0.0, 3.0, 0.5], d=0.2, depth=0.6),
        Feature(id="K4", type="bore", axis=[0, 0, 1], center=[3.0, 2.5, 0.0], d=1.5, depth=1.0, thru=True)])


def test_identity_is_100_and_exact():
    s = score_part(_key(), _key(), C)
    assert s.score == pytest.approx(100.0) and s.exact


@pytest.mark.parametrize("i", [0, 5, 13, 23])
def test_identity_under_rotation(i):
    s = score_part(_key(), transform(_key(), ROTATIONS[i], (0.0, 0.0, 0.0)), C)
    assert s.score == pytest.approx(100.0) and s.exact


@pytest.mark.parametrize("k, credit", [(0.5, 1.0), (2.0, 0.40), (5.0, 0.20)])
def test_moved_hole_costs_exactly_the_curve(k, credit):
    gen = _key()
    gen.feature("K1").center[0] += k * 0.005            # fallback tol 0.005 in
    s = score_part(_key(), gen, C)
    row = s.row("K1")
    assert row.attr_credits["position"] == pytest.approx(credit, abs=0.005)
    W = sum(r.weight for r in s.rows)
    expected = 100 * (1 - row.weight * (1 - row.credit) / W)
    assert s.score == pytest.approx(expected, abs=1e-6)


def test_missing_feature_costs_its_weight_share():
    gen = _key()
    gen.features = [f for f in gen.features if f.id != "K4"]
    s = score_part(_key(), gen, C)
    W = sum(r.weight for r in s.rows)
    assert s.row("K4").status == "missing"
    assert s.score == pytest.approx(100 * (1 - s.row("K4").weight / W), abs=1e-6)


def test_extra_feature_penalty():
    gen = _key()
    gen.features.append(Feature(id="K9", type="thru_hole", axis=[0, 0, 1], center=[3.0, 0.5, 0.0], d=0.5, depth=1.0))
    s = score_part(_key(), gen, C)
    W = sum(r.weight for r in s.rows)
    assert s.extras and s.score == pytest.approx(100 * (1 - 0.5 * s.extras[0].weight / W), abs=1e-6)
    assert not s.exact


def test_type_error_costs_only_the_type_share():
    gen = _key()
    gen.feature("K3").type = "blind_hole"
    s = score_part(_key(), gen, C)
    assert s.row("K3").attr_credits["type"] == 0.0
    assert s.row("K3").credit == pytest.approx(1 - 0.15 / 1.0)   # all four attributes present


def test_silent_attribute_not_scored_and_value_override_used():
    key = _key()
    key.overrides = [{"feature": "K4", "attr": "depth", "silent": True},
                     {"feature": "K1", "attr": "d", "value": 0.6}]
    gen = _key()
    gen.feature("K4").depth = 0.3
    gen.feature("K1").d = 0.6
    s = score_part(key, gen, C)
    assert "depth" not in s.row("K4").attr_credits and s.row("K1").credit == pytest.approx(1.0)


def test_expected_count_adds_drawing_only_instances():
    key = _key()
    key.overrides = [{"type": "thru_hole", "expected_count": 3}]
    s_missing = score_part(key, _key(), C)                        # generated has 2 thru holes too
    assert any(r.status == "missing" and r.feature_id.startswith("EXPECT") for r in s_missing.rows)
    gen = _key()
    gen.features.append(Feature(id="G9", type="thru_hole", axis=[0, 0, 1], center=[3, 3.5, 0], d=0.5, depth=1.0))
    s_found = score_part(key, gen, C)
    assert s_found.score > s_missing.score and not s_found.extras


def test_score_bounds():
    gen = _key()
    gen.features = [Feature(id=f"X{i}", type="thru_hole", axis=[0, 0, 1], center=[0.1 * i, 3.9, 0], d=0.1,
                            depth=1.0) for i in range(40)]
    s = score_part(_key(), gen, C)
    assert 0.0 <= s.score <= 100.0
```

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** `bench/scoring.py`:

```python
"""Part score (spec 2026-10-24, 'Scoring')."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from bench import align, overrides
from bench.credit import attr_credit, feature_credit
from bench.features import Feature, Key
from bench.match import family, match, position_error
from bench.score_config import Config
from bench.weights import BASE_ID, base_body, feature_size, weight

SCORED = lambda f: f.type != "hole_pattern"  # noqa: E731


@dataclass
class Row:
    feature_id: str
    type: str
    tier_weight: float
    weight: float
    status: str                       # matched | missing | drawing_only_missing
    matched_id: Optional[str] = None
    errors: dict = field(default_factory=dict)        # attr -> (abs error, error / tol)
    attr_credits: dict = field(default_factory=dict)
    credit: float = 0.0
    points_lost: float = 0.0
    blame: str = ""
    reason: str = ""


@dataclass
class Extra:
    feature_id: str
    type: str
    weight: float
    points_lost: float = 0.0
    blame: str = ""


@dataclass
class PartScore:
    part: str
    score: float
    exact: bool
    rows: list
    extras: list
    drawing_only: list
    pose: object = None
    practices: Optional[float] = None    # spec 2b

    def row(self, fid: str) -> Row:
        return next(r for r in self.rows if r.feature_id == fid)


def _tol(f: Feature, attr: str, units: str, cfg: Config) -> float:
    return float((f.tol or {}).get(attr) or cfg.fallback_tol[units])


def _attr_errors(k: Feature, g: Feature) -> dict:
    out = {"type": 0.0 if k.type == g.type else 1.0}
    if k.type == "base_body":
        out["size"] = max(abs(a - b) for a, b in zip(sorted(k.size), sorted(g.size)))
        return out
    if k.center is not None or k.normal is not None:
        out["position"] = position_error(k, g)
    sizes = [(k.d, g.d), (k.cbore_d, g.cbore_d), (k.csink_d, g.csink_d)]
    sz = [abs(a - (b if b is not None else 0.0)) for a, b in sizes if a is not None]
    if k.size and g.size:
        sz.append(max(abs(a - b) for a, b in zip(sorted(k.size), sorted(g.size))))
    if sz:
        out["size"] = max(sz)
    dp = []
    if k.thru is None or not k.thru:
        dp += [abs(a - (b if b is not None else 0.0)) for a, b in ((k.depth, g.depth),) if a is not None]
    if k.cbore_depth is not None:
        dp.append(abs(k.cbore_depth - (g.cbore_depth or 0.0)))
    if k.thru is not None and g.thru is not None and k.thru != g.thru:
        dp.append(float("inf"))
    if dp:
        out["depth"] = max(dp)
    return out


def score_part(key: Key, generated: Key, cfg: Config) -> PartScore:
    eff = overrides.apply(key)
    k = eff.key
    part_size = max(k.envelope)
    fit = align.best_fit(k, generated)
    gen = fit.apply(generated)
    tol_of = lambda f, a: _tol(f, a, k.units, cfg)  # noqa: E731
    kf = [f for f in k.features if SCORED(f)]
    gf = [f for f in gen.features if SCORED(f)]
    pairs, missing, extra = match(kf, gf, part_size, tol_of, cfg)
    by_k = {f.id: f for f in kf}
    by_g = {f.id: f for f in gf}
    rows = []
    # base body
    kb, gb = base_body(k), base_body(gen)
    rows.append(_row(kb, gb, eff, part_size, k.units, cfg))
    for kid, gid in pairs:
        rows.append(_row(by_k[kid], by_g[gid], eff, part_size, k.units, cfg))
    for kid in missing:
        f = by_k[kid]
        w = weight(f, part_size, cfg)
        rows.append(Row(kid, f.type, cfg.tiers.get(f.type, 0), w, "missing", credit=0.0))
    # drawing-only expected instances (count overrides)
    extras_left = list(extra)
    for typ, n in eff.expected_counts.items():
        have = sum(1 for f in kf if f.type == typ)
        proto = next((f for f in kf if f.type == typ), Feature(id="P", type=typ))
        for i in range(max(0, n - have)):
            cand = next((gid for gid in extras_left if by_g[gid].type == typ
                         and abs((by_g[gid].d or 0) - (proto.d or 0)) <= tol_of(proto, "size")), None)
            w = weight(proto, part_size, cfg)
            if cand:
                extras_left.remove(cand)
                rows.append(Row(f"EXPECT-{typ}-{i + 1}", typ, cfg.tiers.get(typ, 0), w, "matched", cand,
                                credit=1.0, reason="drawing-only instance (count override); position not scored"))
            else:
                rows.append(Row(f"EXPECT-{typ}-{i + 1}", typ, cfg.tiers.get(typ, 0), w, "missing",
                                reason="drawing calls for it (count override)"))
    W = sum(r.weight for r in rows) or 1.0
    extras = [Extra(gid, by_g[gid].type, weight(by_g[gid], part_size, cfg)) for gid in extras_left]
    for r in rows:
        r.points_lost = 100.0 * r.weight * (1.0 - r.credit) / W
    for e in extras:
        e.points_lost = 100.0 * cfg.extra_penalty * e.weight / W
    raw = 100.0 - sum(r.points_lost for r in rows) - sum(e.points_lost for e in extras)
    score = max(0.0, min(100.0, raw))
    exact = not extras and all(r.credit >= 1.0 - 1e-12 for r in rows)
    return PartScore(k.part, score, exact, rows, extras, list(eff.drawing_only), pose=fit)


def _row(kf: Feature, gf: Feature, eff, part_size: float, units: str, cfg: Config) -> Row:
    errs = _attr_errors(kf, gf)
    credits, shown = {}, {}
    for attr, err in errs.items():
        if (kf.id, attr) in eff.silent:
            continue
        if attr == "type":
            credits["type"] = 1.0 if err == 0.0 else 0.0
            continue
        t = float((kf.tol or {}).get(attr) or cfg.fallback_tol[units])
        credits[attr] = 0.0 if err == float("inf") else attr_credit(err, t, cfg)
        shown[attr] = (err, err / t if t else float("inf"))
    return Row(kf.id, kf.type, cfg.tiers.get(kf.type, 0), weight(kf, part_size, cfg), "matched", gf.id,
               errors=shown, attr_credits=credits, credit=feature_credit(credits, cfg))
```

Implementation notes for the engineer:
- `best_fit` must handle an empty or near-empty generated key, with no exception. Add a guard so an empty generated key returns identity, and a test.
- Make sure the test expectation `credit == 1 - 0.15` holds: for K3 (tapped, blind) the present attributes are position, size, depth and type, so the shares total 1.0.

- [ ] **Step 4:** Run. All tests pass. Then the full suite.
- [ ] **Step 5:** Commit `bench/scoring.py bench/align.py tests/test_bench_score_part.py` with the message `feat(bench): part score (weighted credits, extras, overrides, exact)`.

---

### Task 9: Stage blame

**Files:** Create `bench/blame.py`. Test: `tests/test_bench_score_blame.py`.

**Inputs:**
- `PartScore` for the SolidWorks part (`sw`)
- `PartScore` for the CadQuery reference (`cq`), scored by the same `score_part` against the same key
- the effective key
- `extraction` (dict, the saved extraction JSON)
- `ir_report` (dict, with `cq_skipped`)
- `cfg`

- [ ] **Step 1: Failing tests** with fabricated inputs, one per category:

```python
"""blame: the first stage at fault, one test per category."""
from bench.blame import blame_part
from bench.features import Feature, Key
from bench.score_config import load
from bench.scoring import Extra, PartScore, Row

C = load()


def _key(**kw):
    f = Feature(id="K1", type=kw.get("type", "thru_hole"), axis=[0, 0, 1], center=[1, 1, 0], d=0.344,
                depth=0.5, links={"size": [0.344], "position": [1.0]})
    return Key(part="P", units="inch", source="s", envelope=[4, 3, 0.5], features=[f],
               overrides=kw.get("overrides", []))


def _ps(credit, status="matched"):
    return PartScore("P", 100 * credit, credit == 1.0,
                     [Row("BASE", "base_body", 10, 10, "matched", "BASE", credit=1.0),
                      Row("K1", "thru_hole", 3, 0.9, status, "G1" if status == "matched" else None, credit=credit)],
                     [], [])


EXT_OK = {"dimensions": [{"id": "D1", "value": 0.344}, {"id": "D2", "value": 1.0}]}


def test_ground_truth():
    b = blame_part(_ps(0.4), _ps(0.4), _key(overrides=[{"feature": "K1", "attr": "depth", "value": 0.1}]),
                   EXT_OK, {"cq_skipped": {}}, C)
    assert b["K1"].stage == "ground_truth"


def test_unsupported():
    assert blame_part(_ps(0.4), _ps(0.4), _key(type="countersink"), EXT_OK, {}, C)["K1"].stage == "unsupported"


def test_extraction():
    ext = {"dimensions": [{"id": "D2", "value": 1.0}]}          # .344 never extracted
    assert blame_part(_ps(0.4), _ps(0.4), _key(), ext, {}, C)["K1"].stage == "extraction"


def test_planner():
    assert blame_part(_ps(0.4), _ps(0.4), _key(), EXT_OK, {"cq_skipped": {}}, C)["K1"].stage == "planner"


def test_cadquery():
    b = blame_part(_ps(0.0, "missing"), _ps(0.0, "missing"), _key(), EXT_OK,
                   {"cq_skipped": {"F004": "CompileError: ..."}}, C)
    assert b["K1"].stage == "cadquery"


def test_solidworks():
    assert blame_part(_ps(0.4), _ps(1.0), _key(), EXT_OK, {}, C)["K1"].stage == "solidworks"


def test_full_credit_has_no_blame():
    assert "K1" not in blame_part(_ps(1.0), _ps(1.0), _key(), EXT_OK, {}, C)


def test_extras_blamed_where_they_first_appear():
    sw = _ps(1.0)
    sw.extras = [Extra("G9", "thru_hole", 0.9, 2.0)]
    cq = _ps(1.0)
    assert blame_part(sw, cq, _key(), EXT_OK, {}, C)["extra:G9"].stage == "solidworks"
    cq.extras = [Extra("C9", "thru_hole", 0.9, 2.0)]
    assert blame_part(sw, cq, _key(), EXT_OK, {}, C)["extra:G9"].stage == "planner"
```

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** `bench/blame.py`:

```python
"""Stage blame (spec 2026-10-24, 'Stage blame'): the first stage at fault for each lost point."""
from __future__ import annotations

from dataclasses import dataclass

from bench.features import Key
from bench.score_config import Config

STAGES = ("ground_truth", "unsupported", "extraction", "planner", "cadquery", "solidworks")


@dataclass
class Blame:
    stage: str
    reason: str
    points: float


def _extracted_values(extraction: dict) -> list[float]:
    vals = []
    for d in (extraction or {}).get("dimensions", []):
        try:
            vals.append(float(d.get("value")))
        except (TypeError, ValueError):
            pass
    return vals


def _overridden(key: Key, fid: str) -> bool:
    return any(o.get("feature") == fid for o in key.overrides) or fid.startswith("EXPECT")


def blame_part(sw, cq, key: Key, extraction: dict, ir_report: dict, cfg: Config) -> dict:
    """-> {feature_id or 'extra:<id>': Blame} for every row with credit < 1 and every SW extra."""
    out = {}
    extracted = _extracted_values(extraction)
    cq_rows = {r.feature_id: r for r in cq.rows}
    skipped = (ir_report or {}).get("cq_skipped") or {}
    feats = {f.id: f for f in key.features}
    for r in sw.rows:
        if r.credit >= 1.0 - 1e-12:
            continue
        f = feats.get(r.feature_id)
        if _overridden(key, r.feature_id):
            out[r.feature_id] = Blame("ground_truth", "drawing override / model-drawing difference", r.points_lost)
        elif r.type in cfg.unsupported_types:
            out[r.feature_id] = Blame("unsupported", f"{r.type} cannot be expressed in the IR", r.points_lost)
        elif f is not None and any(not any(abs(v - e) <= 1e-3 * max(1.0, abs(v)) + 1e-9 for e in extracted)
                                   for vals in f.links.values() for v in vals):
            miss = sorted({v for vals in f.links.values() for v in vals
                           if not any(abs(v - e) <= 1e-3 * max(1.0, abs(v)) + 1e-9 for e in extracted)})
            out[r.feature_id] = Blame("extraction", f"drawing value(s) {miss} not in the extraction", r.points_lost)
        else:
            c = cq_rows.get(r.feature_id)
            if c is not None and c.credit >= 1.0 - 1e-12:
                out[r.feature_id] = Blame("solidworks", "CadQuery reference correct; SolidWorks part differs",
                                          r.points_lost)
            elif r.status == "missing" and skipped:
                out[r.feature_id] = Blame("cadquery", f"reference skipped {sorted(skipped)}", r.points_lost)
            else:
                out[r.feature_id] = Blame("planner", "the plan's CadQuery reference already has this error",
                                          r.points_lost)
        r.blame, r.reason = out[r.feature_id].stage, out[r.feature_id].reason
    cq_extra_types = [e.type for e in cq.extras]
    for e in sw.extras:
        stage = "planner" if e.type in cq_extra_types else "solidworks"
        if stage == "planner":
            cq_extra_types.remove(e.type)
        out[f"extra:{e.feature_id}"] = Blame(stage, "extra feature not on the drawing", e.points_lost)
        e.blame = stage
    return out


def rollup(parts: list) -> dict:
    """parts: [(PartScore, {id: Blame})] -> points lost by stage, by type, by tier."""
    by_stage, by_type, by_tier = {}, {}, {}
    for ps, bl in parts:
        rows = {r.feature_id: r for r in ps.rows}
        for fid, b in bl.items():
            by_stage[b.stage] = by_stage.get(b.stage, 0.0) + b.points
            r = rows.get(fid)
            typ = r.type if r else fid.split(":")[0]
            by_type[typ] = by_type.get(typ, 0.0) + b.points
            tier = str(r.tier_weight) if r else "extra"
            by_tier[tier] = by_tier.get(tier, 0.0) + b.points
    return {"by_stage": by_stage, "by_type": by_type, "by_tier": by_tier}
```

- [ ] **Step 4:** Run, then the full suite.
- [ ] **Step 5:** Commit `bench/blame.py tests/test_bench_score_blame.py` with the message `feat(bench): stage blame and rollups`.

---

### Task 10: Report and CLI

**Files:** Create `bench/report.py`, `bench/score.py`. Test: `tests/test_bench_score_cli.py`.

**CLI:** `python -m bench.score RUN_DIR [--parts ...] [--keys-dir DIR] [--no-sw] [--config FILE]`.

**Per part,** in `RUN_DIR/<part>/`:
- **The generated part:** use `generated.step` if it is newer than the SLDPRT (or `--no-sw` is given); otherwise export `*_ir.SLDPRT` with `sw_tasks.sldprt_to_step` (one `connect()` per run; exit 3 if SolidWorks is unavailable and any export is needed).
- **The CadQuery reference:** `reference.step`.
- **The key:** `--keys-dir/<part>/key.json` if given, else `config.data_root()/<part>/key.json`. Unsigned keys are skipped and listed.
- **Read features:** `keygen.from_step(step, units=key.units, part=part)` for both the generated part and the reference.
- **Stage outputs:** the extraction JSON is `<part>_extraction.json` if present, else `{}`; `ir_report.json` is used if present.
- **Score:** `score_part(key, generated, cfg)`, `score_part(key, reference, cfg)`, `blame_part(...)`.

**Run outputs:**
- `RUN_DIR/scores.json`: per part score, exact, rows, extras, blame, drawing_only; run summary (mean, median, exact rate, rollup)
- `RUN_DIR/report.html`: summary table, per-part feature tables, rollups

Use the `html.escape` patterns from `bench/review.py`.

**Exit codes:**
- 0: ok
- 1: some part errored. An unreadable STEP gives an error row, never a silent 0.
- 2: config / no parts
- 3: SolidWorks needed but unavailable

**A multi-body generated STEP:** score the largest solid by volume (pass it to `keygen.extract`); run `keygen.extract` on every other solid and append its features to the score's extras; set `"multi_body": n` on the part row. Add a test with two disjoint CadQuery boxes.

**A part with no generated SLDPRT and no `generated.step`:** score 0. Every key row is missing, with blame from `ir_report.json`: if `cq_skipped` or the plan is missing, then `planner` or `cadquery`; else `solidworks`.

- [ ] **Step 1: Failing tests** use a tmp run dir with tiny CadQuery parts (no SolidWorks; `--no-sw` with a `generated.step`):

```python
"""bench.score CLI end-to-end on tiny CadQuery parts (no SolidWorks)."""
import json

import pytest

cq = pytest.importorskip("cadquery")
from bench import keygen, score  # noqa: E402


def _plate(tmp, name, holes):
    wp = cq.Workplane().box(60, 40, 10).faces(">Z").workplane().pushPoints(holes).hole(8.0)
    p = tmp / name
    wp.val().exportStep(str(p))
    return p


def test_cli_identity_and_planted_error(tmp_path):
    run, keys = tmp_path / "run", tmp_path / "keys"
    for part, gen_holes in (("PA", [(-20, -10), (20, -10)]), ("PB", [(-20, -10), (21.0, -10)])):
        (run / part).mkdir(parents=True)
        (keys / part).mkdir(parents=True)
        ref = _plate(keys / part, "ref.step", [(-20, -10), (20, -10)])
        k = keygen.from_step(ref, units="mm", part=part)
        k.signoff = {"kind": "auto", "by": "test", "date": "2026-10-24"}
        k.save(keys / part / "key.json")
        _plate(run / part, "generated.step", gen_holes)
        _plate(run / part, "reference.step", gen_holes)
    assert score.main([str(run), "--keys-dir", str(keys), "--no-sw"]) == 0
    out = json.loads((run / "scores.json").read_text(encoding="utf-8"))
    by = {p["part"]: p for p in out["parts"]}
    assert by["PA"]["score"] == pytest.approx(100.0) and by["PA"]["exact"]
    assert by["PB"]["score"] < 100.0 and not by["PB"]["exact"]
    assert any(b["stage"] == "planner" for b in by["PB"]["blame"].values())   # CQ reference has the error too
    assert (run / "report.html").read_text(encoding="utf-8").count("PB") >= 1


def test_cli_skips_unsigned_and_handles_missing_generated(tmp_path):
    run, keys = tmp_path / "run", tmp_path / "keys"
    (run / "PC").mkdir(parents=True)
    (keys / "PC").mkdir(parents=True)
    ref = _plate(keys / "PC", "ref.step", [(0, 0)])
    k = keygen.from_step(ref, units="mm", part="PC")
    k.save(keys / "PC" / "key.json")                     # unsigned
    assert score.main([str(run), "--keys-dir", str(keys), "--no-sw"]) in (0, 2)
    out = json.loads((run / "scores.json").read_text(encoding="utf-8"))
    assert "PC" in out["skipped_unsigned"]
```

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement `bench/report.py` (`write_json(path, results, summary)`, `write_html(path, results, summary)`) and `bench/score.py` (`main(argv) -> int`, the `if __name__ == "__main__":` hook) as described above. Keep `score.py` to argument parsing, file discovery and orchestration; the logic lives in `scoring`/`blame`. Serialise dataclasses with `dataclasses.asdict`. `pose` is not serialised: store `pose_rotation` as a nested list and `pose_translation` instead.
- [ ] **Step 4:** Run, then the full suite.
- [ ] **Step 5:** Commit `bench/report.py bench/score.py tests/test_bench_score_cli.py` with the message `feat(bench): scorer CLI, scores.json and report.html`.

---

### Task 11: Planted-error geometry and the real-data identity / planted tests

**Files:** Create `bench/plant.py`. Test: `tests/test_bench_score_planted.py`.

`bench/plant.py` edits a reference STEP solid with CadQuery. Positions come from the key (part frame, drawing units) and are converted to the STEP's global mm frame: `global = bbox_min + value * MM_PER[units]`.

```python
"""Planted errors on a reference solid (tests + calibration). Geometry edits via CadQuery booleans."""
from __future__ import annotations

from pathlib import Path

import cadquery as cq

from bench.features import Feature, Key
from bench.keygen import MM_PER


def _solid(step: Path):
    return cq.importers.importStep(str(step)).val().Solids()[0]


def _cyl(f: Feature, key: Key, lo, d=None, extra_len=2.0):
    k = MM_PER[key.units]
    ax = cq.Vector(*f.axis)
    c = cq.Vector(*[lo[i] + f.center[i] * k for i in range(3)])
    depth = (f.depth or max(key.envelope)) * k
    r = (d if d is not None else f.d) * k / 2
    return cq.Solid.makeCylinder(r, depth + 2 * extra_len, c - ax * extra_len, ax)


def fill_hole(step: Path, key: Key, fid: str, out: Path) -> Path:
    s = _solid(step)
    bb = s.BoundingBox()
    lo = (bb.xmin, bb.ymin, bb.zmin)
    f = key.feature(fid)
    plug = _cyl(f, key, lo, d=(f.cbore_d or f.csink_d or f.d) * 1.001, extra_len=0.0)
    s.fuse(plug).clean().exportStep(str(out))
    return out


def move_hole(step: Path, key: Key, fid: str, delta, out: Path) -> Path:
    """Fill the hole, then drill the same diameter at center + delta (drawing units)."""
    tmp = fill_hole(step, key, fid, out.with_suffix(".tmp.step"))
    s = _solid(tmp)
    bb = s.BoundingBox()
    lo = (bb.xmin, bb.ymin, bb.zmin)
    f = key.feature(fid)
    moved = Feature(**{**f.__dict__, "center": [f.center[i] + delta[i] for i in range(3)]})
    s.cut(_cyl(moved, key, lo)).clean().exportStep(str(out))
    tmp.unlink()
    return out


def add_hole(step: Path, key: Key, center, d: float, axis, out: Path) -> Path:
    s = _solid(step)
    bb = s.BoundingBox()
    lo = (bb.xmin, bb.ymin, bb.zmin)
    f = Feature(id="X", type="thru_hole", axis=list(axis), center=list(center), d=d, depth=max(key.envelope))
    s.cut(_cyl(f, key, lo)).clean().exportStep(str(out))
    return out
```

- [ ] **Step 1: Failing tests:**
  - **Synthetic planted errors (always run).** On a CadQuery plate with holes, build the key with keygen, then:
    - move a hole by k ∈ {0.5, 1, 1.5, 2, 5, 10}× the fallback tolerance (mm part: 0.1 mm). Rescore with `keygen.from_step` + `score_part`. Assert the moved hole's position credit equals `attr_credit(k*tol)` within 0.01 (STEP round-trip rounding; the feature-level tests in Task 8 hold the 1e-6 bound), and the other features keep credit 1. For k = 1, move by 0.99× so rounding can't push it over.
    - turn a counterbore into a plain hole (CadQuery `cboreHole` vs `hole` on the same plate): only the type share is lost, credit = 0.85.
    - add ±0.5×tol seeded noise to every hole position: score still 100.
    - **properties** (seeded, feature-level `Key` edits, no CadQuery): 50 random keys; a larger error on one feature never raises the score; shuffling feature order gives the same score; the score always stays in [0, 100].
    - fill a hole: that feature is `missing`, and the score equals `100 × (1 − w/W)` within 1e-6.
    - add a hole: one extra, with the exact penalty.
    - make a mirror-symmetric plate and mirror it with CadQuery `.mirror("YZ")`: score 100.
    - make an asymmetric plate and mirror it: score < 100. A mirror is a real error.
  - **Real data (skip without `MTI_BENCH_DATA`).** For each of the 19 parts:
    - load `key.json` and `reference.step`
    - `score_part(key, keygen.from_step(reference.step), cfg)` == 100 and exact
    - the same after `transform(..., ROTATIONS[i], t)` for 3 seeded random rotations and non-axis translations, e.g. (0.37, -1.2, 0.05)
    - **Important:** use a copy of the key with `overrides` emptied. The identity check is model vs model; overrides deliberately make the model wrong vs the drawing.
  - **Real-data planted error.** On 3 parts with thru holes (A050211E, A050381E, A050471E): `move_hole` by 2× tolerance and `fill_hole` one hole. The score drops by the expected amounts within 0.5 points (geometry rounding), and blame is not computed here.
- [ ] **Step 2:** Run → FAIL. Then implement `plant.py` as above and fix the real issues the tests expose in `scoring`/`align`/`match`. Keep a list of every fix for the report.
- [ ] **Step 3:** Run the full suite.
- [ ] **Step 4:** Commit `bench/plant.py tests/test_bench_score_planted.py` plus any fixed modules, with the message `test(bench): scorer identity and planted-error tests (synthetic + 19 real parts)`.

---

### Task 12: Real-data prep, golden dry run, calibration (needs the user for step 4)

No new modules, except a small script `bench/calibrate.py` (below).

- [ ] **Step 1: Link the 19 keys.** Run `& $PY -m bench.prep link`. Expect 19 ok. Then `& $PY -m bench.prep status`: still all signed.
- [ ] **Step 2: Explicit overrides.** Add the user's two explicit drawing-wins decisions to the keys, using a small Python one-liner with `Key.load/save` (no hand edits of geometry):
  - A050481E: `{"feature": "K004", "attr": "depth", "value": 0.098, "note": "drawing: inner step 0.098 (model 0.220)"}`
  - A050411E: `{"type": "countersink", "expected_count": 12, "note": "drawing: 12 countersinks (model 8)"}`

  Re-run the identity test file: it must still pass, because it empties the overrides.
- [ ] **Step 3: Golden dry run** at $0, with real SolidWorks parts from earlier IR runs.
  - Build keys from the 4 golden plans (`tests/golden/ir/{SB11033,A040911E,A040921E,SB11780}.json`): compile the plan with `pipeline.ir.compile_cadquery.build`, run `keygen.extract(model.solid, units=...)`, auto-sign, and save to the scratchpad `golden_keys/<part>/key.json`.
  - The run dir is `output/sw2024_check/combined/` (from 2026-10-23: SLDPRT, reference.step, plan.json, extraction). Start SolidWorks and wait for COM, then run `& $PY -m bench.score output/sw2024_check/combined --keys-dir <scratchpad>/golden_keys`. Without SolidWorks, export `generated.step` beforehand or use `--no-sw` with the reference copied as `generated.step`, and say so in the report.
  - Record the scores and blame rollup.
- [ ] **Step 4: Calibration with the user.** Create `bench/calibrate.py`, which takes 2 real parts (A050211E retainer disc, A050381E mounting pad) and writes six planted variants into the scratchpad:
  - one hole moved 1.5× tolerance
  - one hole moved 5×
  - one hole filled
  - an extra hole
  - the bore Ø made 3× tolerance oversize
  - a counterbore made into a plain hole (pick a part that has one; else skip)

  It scores each and prints a table: part, edit, score, points lost, feature, credit. **Show the table to the user** and ask whether the numbers feel right. Tune only `score_config.yaml` values on request, re-run, and repeat until the user agrees. Commit `bench/calibrate.py` and any config changes.
- [ ] **Step 5: Docs.**
  - **STATE.md:** a short dated entry covering what the scorer does, the golden dry-run numbers and the calibration outcome.
  - **CLAUDE.md commands:** `python -m bench.score <run_dir> [--keys-dir DIR] [--no-sw]` (no API cost).
  - Commit.
