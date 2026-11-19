"""A cost-limit stop keeps the first paid extraction (CLAUDE.md rule 9) and is named as the run's failure."""
import json

import pytest

from pipeline import budget, ir_pipeline
from pipeline.extractor import _keep_initial
from pipeline.schema import DrawingData


def test_keep_initial_rides_the_first_extraction_on_the_exception_and_flags_it():
    data = DrawingData.model_validate({"part_name": "P", "units": "inch", "dimensions": [], "features": [], "confidence": 0.66})
    exc = budget.BudgetExceeded("cap")
    _keep_initial(exc, data)
    assert exc.partial_extraction["part_name"] == "P" and exc.partial_extraction["confidence"] == 0.66
    assert any("cost limit" in w for w in exc.partial_extraction["warnings"])


def test_get_extraction_saves_the_partial_before_the_run_stops(tmp_path, monkeypatch):
    spec = ir_pipeline.PartSpec("PX", tmp_path, "inch")
    exc = budget.BudgetExceeded("would cross the cap")
    exc.partial_extraction = {"part_name": "PX", "dimensions": [], "features": [], "confidence": 0.66, "warnings": ["w"]}
    import pipeline.extractor as ex

    def boom(*a, **k):
        raise exc
    monkeypatch.setattr(ex, "extract_drawing_data", boom)
    out = tmp_path / "out"
    with pytest.raises(budget.BudgetExceeded):
        ir_pipeline.get_extraction(spec, [("FULL SHEET", "full", "x")], out, [])
    saved = json.loads((out / "PX_extraction.json").read_text(encoding="utf-8"))
    assert saved["confidence"] == 0.66                                          # the paid result is not lost


def test_a_budget_stop_is_named_cost_limit_in_the_report_and_the_run_event(tmp_path, monkeypatch):
    spec = ir_pipeline.PartSpec("PY", tmp_path, "inch")
    monkeypatch.setattr(ir_pipeline, "images_for", lambda s: [("FULL SHEET", "full", "x")])

    def stop(*a, **k):
        raise budget.BudgetExceeded("spent $18.91 of $20.00")
    monkeypatch.setattr(ir_pipeline, "get_extraction", stop)
    out_root = tmp_path / "o"
    with pytest.raises(budget.BudgetExceeded):
        ir_pipeline.run_part(spec, out_root, [])
    rep = json.loads((out_root / "PY" / "ir_report.json").read_text(encoding="utf-8"))
    assert rep["error"].startswith("COST_LIMIT:extraction:")
