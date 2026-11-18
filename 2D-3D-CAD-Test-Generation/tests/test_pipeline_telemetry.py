"""Pipeline instrumentation (Stage 1, task 1.3): deterministic event sequence, no wall-clock asserts."""
import json
from pathlib import Path

import pytest

from pipeline.progress import Op, Phase
from pipeline.run_events import parse_event_line
from pipeline.telemetry import NullTelemetry, RunTelemetry

ROOT = Path(__file__).resolve().parent.parent


def _tel(tmp_path):
    lines = []
    return RunTelemetry.create(part_id="P1", out_dir=tmp_path, stdout=lines.append), lines


def test_attempt_increments_across_runs_and_run_id_is_new(tmp_path):
    t1, _ = _tel(tmp_path); t1.start(); t1.close()
    t2, _ = _tel(tmp_path); t2.start(); t2.close()
    assert (t1.attempt, t2.attempt) == (1, 2) and t1.run_id != t2.run_id


def test_terminal_events_and_percent_stop_on_failure(tmp_path):
    t, lines = _tel(tmp_path)
    t.start()
    t.plan(Phase.EXTRACTION, 4, 1, "views")
    t.complete(Phase.EXTRACTION, Op.EXTRACT_VIEW)
    t.fail("boom")
    t.close()
    evs = [parse_event_line(l) for l in lines]
    assert evs[-1]["kind"] == "run.failed"
    last_prog = [e for e in evs if e["kind"] == "progress.updated"][-1]["payload"]
    assert last_prog["percent"] == 25.0 and last_prog["terminal"] == "failed"


def test_null_telemetry_is_inert():
    n = NullTelemetry()
    n.start(); n.plan(Phase.EXTRACTION, 1, 1, "v"); n.complete(Phase.EXTRACTION, Op.EXTRACT_VIEW)
    n.fail("x"); n.finish(); n.close()


def test_run_part_emits_ordered_events_for_a_reused_plan(tmp_path):
    pytest.importorskip("yaml"); pytest.importorskip("cadquery")
    from pipeline.ir_pipeline import dev_parts, run_part
    spec = next(s for s in dev_parts() if s.part == "A040921E")
    gold = json.loads((ROOT / "tests" / "golden" / "ir" / "A040921E.json").read_text(encoding="utf-8"))
    (tmp_path / "A040921E").mkdir()
    (tmp_path / "A040921E" / "plan.json").write_text(json.dumps({"plan": gold["plan"]}), encoding="utf-8")
    lines = []
    tel = RunTelemetry.create(part_id="A040921E", out_dir=tmp_path / "A040921E", stdout=lines.append)
    run_part(spec, tmp_path, [ROOT / "output" / "astra_2026-10-04"], reuse_plan=True, telemetry=tel)
    evs = [parse_event_line(l) for l in lines]
    assert all(evs)
    assert [e["seq"] for e in evs] == list(range(1, len(evs) + 1))
    assert evs[0]["kind"] == "run.started"
    assert evs[-1]["kind"] in ("run.completed", "run.failed")
    phases = [e["payload"]["phase"] for e in evs if e["kind"] == "progress.updated" and e["payload"]["phase"]]
    order = [p.value for p in Phase]
    assert [order.index(p) for p in phases] == sorted(order.index(p) for p in phases)  # phases never go backward
    pct = [e["payload"]["percent"] for e in evs if e["kind"] == "progress.updated" and e["payload"]["percent"] is not None]
    assert pct == sorted(pct)
    assert (tmp_path / "A040921E" / "run_events.jsonl").is_file()
