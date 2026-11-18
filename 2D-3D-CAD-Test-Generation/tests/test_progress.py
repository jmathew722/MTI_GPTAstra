"""Observable-work progress engine (Stage 1, task 1.2)."""
import pytest

from pipeline.progress import Op, Phase, ProgressEngine


def _engine():
    events = []
    return ProgressEngine(events.append), events


def test_indeterminate_until_denominator_known():
    eng, ev = _engine()
    eng.begin(Phase.INGEST, Op.INGEST_DRAWING)
    snap = eng.snapshot()
    assert snap["indeterminate"] is True and snap["percent"] is None


def test_discovery_then_units_drive_percent():
    eng, _ = _engine()
    eng.plan(Phase.EXTRACTION, units=2, weight_per_unit=1, unit="views")
    eng.plan(Phase.SOLIDWORKS_GENERATION, units=4, weight_per_unit=2, unit="features")
    assert eng.snapshot()["percent"] == 0.0
    eng.complete(Phase.EXTRACTION, Op.EXTRACT_VIEW)          # 1 of 10 weight
    assert eng.snapshot()["percent"] == 10.0
    eng.complete(Phase.SOLIDWORKS_GENERATION, Op.CREATE_FEATURE)  # +2
    assert eng.snapshot()["percent"] == 30.0


def test_percent_never_decreases_when_denominator_grows():
    eng, _ = _engine()
    eng.plan(Phase.EXTRACTION, units=2, weight_per_unit=1, unit="views")
    eng.complete(Phase.EXTRACTION, Op.EXTRACT_VIEW)
    before = eng.snapshot()["percent"]
    eng.plan(Phase.SOLIDWORKS_GENERATION, units=10, weight_per_unit=2, unit="features")  # late discovery
    assert eng.snapshot()["percent"] >= before


def test_rejects_overcompletion_and_negative_units():
    eng, _ = _engine()
    eng.plan(Phase.VERIFICATION, units=1, weight_per_unit=1, unit="checks")
    eng.complete(Phase.VERIFICATION, Op.VERIFY_CHECK)
    with pytest.raises(ValueError):
        eng.complete(Phase.VERIFICATION, Op.VERIFY_CHECK)
    with pytest.raises(ValueError):
        eng.plan(Phase.EXTRACTION, units=-1, weight_per_unit=1, unit="views")


def test_duplicate_unit_id_is_idempotent():
    eng, _ = _engine()
    eng.plan(Phase.SOLIDWORKS_GENERATION, units=2, weight_per_unit=1, unit="features")
    eng.complete(Phase.SOLIDWORKS_GENERATION, Op.CREATE_FEATURE, unit_id="hole_1")
    p = eng.snapshot()["percent"]
    eng.complete(Phase.SOLIDWORKS_GENERATION, Op.CREATE_FEATURE, unit_id="hole_1")
    assert eng.snapshot()["percent"] == p


def test_failure_and_cancel_keep_last_truthful_percent():
    for terminal in ("fail", "cancel"):
        eng, _ = _engine()
        eng.plan(Phase.EXTRACTION, units=4, weight_per_unit=1, unit="views")
        eng.complete(Phase.EXTRACTION, Op.EXTRACT_VIEW)
        getattr(eng, terminal)("boom")
        snap = eng.snapshot()
        assert snap["percent"] == 25.0 and snap["terminal"] == ("failed" if terminal == "fail" else "cancelled")


def test_only_finalization_reaches_exactly_100():
    eng, _ = _engine()
    eng.plan(Phase.EXTRACTION, units=1, weight_per_unit=1, unit="views")
    eng.plan(Phase.ARTIFACT_FINALIZATION, units=1, weight_per_unit=1, unit="artifacts")
    eng.complete(Phase.EXTRACTION, Op.EXTRACT_VIEW)
    assert eng.snapshot()["percent"] == 50.0
    eng.complete(Phase.ARTIFACT_FINALIZATION, Op.FINALIZE_ARTIFACT)
    assert eng.snapshot()["percent"] == 99.9 and eng.snapshot()["terminal"] is None
    eng.finish()
    assert eng.snapshot()["percent"] == 100.0 and eng.snapshot()["terminal"] == "completed"


def test_finish_before_all_work_done_is_refused():
    eng, _ = _engine()
    eng.plan(Phase.EXTRACTION, units=2, weight_per_unit=1, unit="views")
    with pytest.raises(ValueError):
        eng.finish()


def test_events_are_emitted_and_serializable():
    import json
    eng, ev = _engine()
    eng.plan(Phase.EXTRACTION, units=1, weight_per_unit=1, unit="views")
    eng.complete(Phase.EXTRACTION, Op.EXTRACT_VIEW)
    assert ev and all(json.dumps(e) for e in ev)
    assert ev[-1]["percent"] == 99.9  # held below 100 until finish()
