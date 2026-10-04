"""Feature IR v2, Tasks 4-5: CadQuery reference compiler on golden plans (dev parts only)."""
import json
import math
from pathlib import Path

import pytest

pytest.importorskip("cadquery")

from pipeline.ir.compile_cadquery import build, emit_script, run_script  # noqa: E402
from pipeline.ir.model import BuildPlan  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "ir"


def load(name):
    g = json.loads((GOLDEN / f"{name}.json").read_text(encoding="utf-8"))
    return BuildPlan.model_validate(g["plan"]), {k: float(v) for k, v in g["dims"].items()}


# --- demo plate: the known answer ------------------------------------------- #
def test_demo_plate_matches_ground_truth_exactly():
    plan, dims = load("demo_plate")
    assert not [f for f in plan.check(dims) if f.severity == "error"]
    r = build(plan, dims)
    fm = r.feature_map
    truth = json.loads((Path(__file__).parent.parent / "demo" / "simple_plate" / "ground_truth.json")
                       .read_text(encoding="utf-8"))["expected"]
    assert fm["bbox"] == [0, 0, 0, 100, 60, 10]
    assert fm["volume"] == pytest.approx(truth["volume_mm3"], rel=1e-4)   # chamfers included
    holes = [h for fid in ("F002", "F003", "F004") for h in fm["holes"][fid]]
    assert all(h["measured"] for h in holes)
    got = sorted((tuple(h["center"]), h["d"]) for h in holes)
    want = sorted((tuple(map(float, c["center"])), float(c["diameter"])) for c in truth["cylinders"])
    assert got == want
    assert len(fm["edge_points"]["F005"]) == 2                            # both bore mouths


def test_script_is_deterministic_and_traceable():
    plan, dims = load("demo_plate")
    a, b = emit_script(plan, dims), emit_script(plan, dims)
    assert a == b
    assert "pitch=80" in a and "# count=2, pitch=D006 - D005" in a
    assert "\\" not in a and ":\\" not in a                               # no absolute paths


def test_subprocess_run_writes_step_and_feature_map(tmp_path):
    plan, dims = load("demo_plate")
    r = run_script(emit_script(plan, dims), tmp_path, timeout=300)
    assert r.step_path.exists() and r.step_path.stat().st_size > 1000
    assert r.feature_map["volume"] == pytest.approx(54782.9, rel=1e-4)


# --- A040921E: the end slot no earlier path could build -------------------- #
def test_ring_with_end_slot_through_the_wall():
    plan, dims = load("A040921E")
    findings = plan.check(dims)
    assert [f.code for f in findings if f.severity == "error"] == ["unresolved"]   # F003 TYP edges
    r = build(plan, dims)
    m, fm = r.model, r.feature_map
    R, rb = 10.5 / 2, 9.002 / 2
    mid = (R + rb) / 2
    assert fm["bbox"] == pytest.approx([-R, -R, 0, R, R, 3.0], abs=1e-6)
    assert not m.contains(0, mid, 0.375)          # slot: wall removed at 12 o'clock within .75
    assert m.contains(0, mid, 1.5)                # beyond the slot depth: wall intact
    assert m.contains(0, -mid, 0.375)             # 6 o'clock: no slot
    assert m.contains(0.6, mid, 0.375)            # just outside the 1.062 width
    ring = math.pi * (R ** 2 - rb ** 2) * 3.0
    assert fm["volume"] < ring and fm["volume"] == pytest.approx(ring - 1.062 * 0.75 * (R - rb), rel=0.01)
    assert "F003" in fm["skipped"]


# --- SB11780: turned tie rod; necks were refused (F6b), keyway had no profile --- #
def test_tie_rod_revolve_necks_and_keyway():
    plan, dims = load("SB11780")
    assert sorted(f.feature for f in plan.check(dims) if f.code == "unresolved") == ["F003", "F004"]
    r = build(plan, dims)
    m, fm = r.model, r.feature_map
    R, rn = 2.4985 / 2, 1.734 / 2
    assert fm["bbox"] == pytest.approx([-R, -R, 0, R, R, 76.88], abs=1e-6)
    assert m.contains(1.0, 0, 0.44)                    # left collar is full diameter
    assert not m.contains(1.0, 0, 0.88 + 0.5)          # left neck turned down
    assert m.contains(0.5, 0, 0.88 + 0.5)              #   ... to Ø1.734
    assert not m.contains(1.0, 0, 76.005 - 0.5)        # right neck
    assert m.contains(1.0, 0, 76.88 - 0.44)            # right collar (.875)
    assert not m.contains(1.1, 0, 38.0)                # keyway: floor at x = 2.218 - R
    assert m.contains(0.9, 0, 38.0)                    #   ... below the floor is solid
    assert m.contains(1.1, 0, 0.44) and m.contains(-1.1, 0, 38.0)   # collars and far side intact
    body = math.pi * R ** 2 * 76.88
    necks = 2 * math.pi * (R ** 2 - rn ** 2) * 1.016
    assert fm["volume"] < body - necks                 # keyway removed material too
    assert set(fm["skipped"]) == {"F003", "F004"}


def load_ref(name):
    g = json.loads((GOLDEN / f"{name}.json").read_text(encoding="utf-8"))
    return frozenset(g.get("reference_ids", []))


# --- SB11033: stepped revolve, bolt circle, faces picked by coordinate --------- #
def test_work_backup_pilot_flange_boss_holes_and_edges():
    plan, dims = load("SB11033")
    errs = [f for f in plan.check(dims, load_ref("SB11033")) if f.severity == "error"]
    assert [(f.code, f.feature) for f in errs] == [("unresolved", "F005")]   # .015 MAX R
    r = build(plan, dims)
    m, fm = r.model, r.feature_map
    assert fm["bbox"] == pytest.approx([-0.969, -0.969, 0, 0.969, 0.969, 1.971], abs=1e-6)
    assert m.contains(0, 0, 1.0) and m.contains(0, 0, 0.1)        # no bore (section fully hatched)
    assert m.contains(0.3, 0, 0.1) and not m.contains(0.4, 0, 0.1)  # pilot Ø.686
    assert m.contains(0.45, 0, 1.5) and not m.contains(0.55, 0, 1.5)  # boss Ø1.000
    holes = fm["holes"]["F002"] + fm["holes"]["F003"]
    assert len(holes) == 4 and all(h["measured"] and h["d"] == pytest.approx(0.218) for h in holes)
    assert sorted(round(math.hypot(*h["center"]), 6) for h in holes) == [0.781] * 4
    assert len(fm["edge_points"]["F004"]) == 1                      # .094 R: boss root only
    assert len(fm["edge_points"]["F006"]) == 2                      # .03: both flange OD edges
    assert len(fm["edge_points"]["F007"]) == 1                      # .06: boss end
    assert "F005" in fm["skipped"]


# --- A040911E: 3 counterbored + 2 tapped holes, chamfers TYP --------------------- #
def test_bearing_counterbores_taps_and_chamfers():
    plan, dims = load("A040911E")
    assert not [f for f in plan.check(dims, load_ref("A040911E")) if f.severity != "info"]
    r = build(plan, dims)
    m, fm = r.model, r.feature_map
    R = 6.498 / 2
    assert fm["bbox"] == pytest.approx([-R, -R, 0, R, R, 1.5], abs=1e-6)
    cb = [fm["holes"][f][0] for f in ("F002", "F003", "F004")]
    assert all(h["measured"] for h in cb)
    assert sorted((round(h["center"][0], 3), round(h["center"][1], 3)) for h in cb) == \
        [(-2.49, -1.438), (0.0, 2.875), (2.49, -1.438)]
    assert not m.contains(0, 2.875 + 0.19, 0.2)      # inside Ø.438 counterbore, .38 deep
    assert m.contains(0, 2.875 + 0.19, 0.6)          #   ... below it, only the Ø.281 drill
    assert not m.contains(0, 2.875, 1.4)             # drill goes through
    taps = [fm["holes"][f][0] for f in ("F005", "F006")]
    assert all(h["measured"] and h["depth"] == pytest.approx(1.0, abs=1e-6) for h in taps)
    assert m.contains(2.75, 0, 1.2)                  # tapped hole is blind (1.00 DP of 1.500)
    assert len(fm["edge_points"]["F007"]) == 4
