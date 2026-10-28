"""bench/manifest.yaml: the benchmark split is fixed and well-formed (PRD C4)."""
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parent
M = yaml.safe_load((ROOT / "bench" / "manifest.yaml").read_text(encoding="utf-8"))


def _parts(split):
    return [p["part"] for p in (M["splits"].get(split) or [])]


def test_no_part_in_two_splits():
    all_parts = _parts("dev") + _parts("held_out") + _parts("parked")
    assert len(all_parts) == len(set(all_parts))


def test_2026_10_04_decision_recorded():
    assert set(_parts("dev")) >= {"A040911E", "A040921E", "SB11033", "SB11780", "SB11842",
                                  "115-C", "116-C", "117-C", "135-A"}
    assert M["split_decided"] == "2026-10-04"


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


def test_held_out_parts_need_a_reference_step():
    for p in M["splits"].get("held_out") or []:
        assert p.get("reference_step"), f"held-out part {p['part']} has no reference STEP"
