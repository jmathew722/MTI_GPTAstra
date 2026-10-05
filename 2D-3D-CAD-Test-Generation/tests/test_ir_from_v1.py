"""Feature IR v2, Task 3: plan_from_v1 (migration + baseline planner)."""
import json
from pathlib import Path

import pytest

from pipeline.ir.from_v1 import dims_of, plan_from_v1, reference_ids
from pipeline.schema import DrawingData
from run_models import resolve_unknowns

ROOT = Path(__file__).resolve().parent.parent
EXTRACTIONS = sorted(p for p in (ROOT / "output").rglob("*_extraction.json"))
DEMO = ROOT / "demo" / "simple_plate"


def _plan(path: Path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    resolve_unknowns(raw, path.stem.replace("_extraction", ""))
    m = DrawingData.model_validate(raw)
    return plan_from_v1(m), m


def test_there_are_extractions_to_migrate():
    assert len(EXTRACTIONS) >= 10


@pytest.mark.parametrize("path", EXTRACTIONS, ids=lambda p: f"{p.parent.parent.name}/{p.parent.name}")
def test_every_extraction_migrates_with_no_structural_errors(path):
    plan, m = _plan(path)
    codes = {f.code for f in plan.check(dims_of(m), reference_ids(m))}
    assert not codes & {"bad_expr", "dangling_ref", "duplicate_id", "ungrounded_literal"}, codes


def test_round_parts_get_the_axis_frame_and_plates_the_corner_frame():
    assert _plan(ROOT / "output" / "SB11842" / "SB11842_extraction.json")[0].frame.origin_kind == "axis_end"
    raw = json.loads((DEMO / "extraction_no_api.json").read_text(encoding="utf-8"))
    assert plan_from_v1(DrawingData.model_validate(raw)).frame.origin_kind == "corner"


def test_values_are_traced_to_dimension_ids():
    raw = json.loads((DEMO / "extraction_astra.json").read_text(encoding="utf-8"))
    resolve_unknowns(raw, "DEMO")
    plan = plan_from_v1(DrawingData.model_validate(raw))
    base = plan.feature("F001")
    assert base.profile.w.startswith("D") and base.profile.h.startswith("D") and base.depth.startswith("D")
    holes = [f for f in plan.features if f.kind == "hole"]
    assert len(holes) == 5 and all(h.u[0] in "D0-" and h.v[0] in "D0-" for h in holes)


def test_turned_groove_and_revolve_are_unresolved_not_guessed():
    plan, _ = _plan(ROOT / "output" / "astra_2026-10-04" / "SB11780" / "SB11780_extraction.json")
    st = {f.id: f.status for f in plan.features}
    assert st["F003"] == "unresolved" and st["F004"] == "unresolved"   # necks need stations


@pytest.mark.skipif(pytest.importorskip("cadquery") is None, reason="cadquery")
@pytest.mark.parametrize("name", ["extraction_no_api.json", "extraction_astra.json"])
def test_demo_plate_baseline_plan_compiles_to_the_exact_answer(name):
    from pipeline.ir.compile_cadquery import build
    raw = json.loads((DEMO / name).read_text(encoding="utf-8"))
    resolve_unknowns(raw, "DEMO")
    m = DrawingData.model_validate(raw)
    fm = build(plan_from_v1(m), dims_of(m)).feature_map
    truth = json.loads((DEMO / "ground_truth.json").read_text(encoding="utf-8"))["expected"]
    assert fm["volume"] == pytest.approx(truth["volume_mm3"], rel=1e-4)
    got = sorted((tuple(h["center"]), h["d"]) for hs in fm["holes"].values() for h in hs)
    assert got == sorted((tuple(map(float, c["center"])), float(c["diameter"])) for c in truth["cylinders"])
