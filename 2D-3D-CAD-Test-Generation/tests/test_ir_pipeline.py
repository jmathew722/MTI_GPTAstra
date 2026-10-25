"""IR v2 Task 8: the end-to-end pipeline's no-API parts (part list, images, reuse)."""
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("yaml")

from pipeline.ir_pipeline import PartSpec, dev_parts, get_extraction, images_for, run_part  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def test_dev_split_has_the_nine_parts():
    parts = {s.part for s in dev_parts()}
    assert parts == {"A040911E", "A040921E", "SB11033", "SB11780", "SB11842", "115-C", "116-C", "117-C", "135-A"}


def test_multiview_part_sends_the_full_sheet_first():
    spec = next(s for s in dev_parts() if s.part == "SB11033")
    labels = [label for label, _, _ in images_for(spec)]
    assert labels[0] == "FULL SHEET" and len(labels) == 3


def test_pdf_part_is_one_full_sheet():
    spec = next(s for s in dev_parts() if s.part == "135-A")
    assert [label for label, _, _ in images_for(spec)] == ["FULL SHEET"]


def test_saved_extraction_is_reused_without_an_api_call(tmp_path):
    spec = next(s for s in dev_parts() if s.part == "SB11033")
    data, how = get_extraction(spec, [], tmp_path, [ROOT / "output" / "astra_2026-10-04"])
    assert how.startswith("reused") and data["dimensions"]


def test_reuse_plan_rebuilds_without_calling_the_planner(tmp_path, monkeypatch):
    pytest.importorskip("cadquery")
    import pipeline.planner as planner
    monkeypatch.setattr(planner.OpenAIPlanner, "_complete",
                        lambda *a, **k: pytest.fail("planner must not be called"))
    spec = next(s for s in dev_parts() if s.part == "A040921E")
    gold = json.loads((ROOT / "tests" / "golden" / "ir" / "A040921E.json").read_text(encoding="utf-8"))
    (tmp_path / "A040921E").mkdir()
    (tmp_path / "A040921E" / "plan.json").write_text(json.dumps({"plan": gold["plan"]}), encoding="utf-8")
    r = run_part(spec, tmp_path, [ROOT / "output" / "astra_2026-10-04"], reuse_plan=True)
    assert r.plan_attempts == 0 and r.cost_usd == 0.0
    # The golden plan's D-IDs differ from the extraction's, so Gate 1 may reject it.
    # The point is that the saved plan was used and nothing was paid.
    assert r.gate1 in ("OK", "REJECT")


def test_mti_bench_parts_are_skipped_but_reported():
    from pipeline.ir_pipeline import external_parts
    assert dev_parts(split="held_out") == []
    assert not {s.part for s in dev_parts()} & set(external_parts("dev"))
    assert len(external_parts("held_out")) == 10
    assert len(external_parts("dev")) == 3


def test_ir_run_fails_on_empty_split_without_writing_summary(tmp_path, monkeypatch, capsys):
    import ir_run
    import pipeline.ir_pipeline as ip
    monkeypatch.setattr(ip, "connect_sw", lambda: (_ for _ in ()).throw(AssertionError("connect_sw called")))
    monkeypatch.setattr(sys, "argv", ["ir_run.py", "--split", "held_out", "--solidworks", "--output", str(tmp_path)])
    assert ir_run.main() == 2
    assert not (tmp_path / "ir_run_summary.json").exists()
    assert "10 mti_bench part(s) in split held_out skipped" in capsys.readouterr().out
