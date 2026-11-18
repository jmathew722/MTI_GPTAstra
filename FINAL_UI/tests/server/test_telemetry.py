"""Server-side structured telemetry (Stage 1, task 1.5). Pure functions, no FastAPI needed."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))

import telemetry as T  # noqa: E402

P = "[gptastra-event] "


def ev(seq, kind, payload=None, run="run_a", attempt=1, part="P1"):
    return P + json.dumps({"schema_version": 1, "event_id": f"e{run}{seq}", "run_id": run, "attempt": attempt,
                           "part_id": part, "seq": seq, "occurred_at": "2026-11-18T00:00:00.000Z",
                           "kind": kind, "payload": payload or {}})


def prog(pct, **kw):
    return {"phase": "extraction", "operation": "extract_view", "label": "x", "percent": pct,
            "indeterminate": pct is None, "completed_units": 1, "total_units": 4, "unit": "views",
            "terminal": None, **kw}


def test_applies_progress_and_cost_and_tracks_seq():
    s = T.new_state()
    assert T.apply_line(s, ev(1, "run.started"))
    assert T.apply_line(s, ev(2, "progress.updated", prog(25.0)))
    assert T.apply_line(s, ev(3, "cost.updated", {"run_cost_usd": "1.5", "pricing_status": "priced"}))
    assert (s["run_id"], s["attempt"], s["last_seq"], s["source"]) == ("run_a", 1, 3, "structured")
    assert s["progress"]["percent"] == 25.0 and s["cost"]["run_cost_usd"] == "1.5"


def test_ordinary_and_malformed_lines_are_ignored():
    s = T.new_state()
    assert not T.apply_line(s, "[stage] extraction: reading")
    assert not T.apply_line(s, P + "{bad json")
    assert not T.apply_line(s, P + json.dumps({"kind": "x"}))
    assert s["last_seq"] == 0 and s["progress"] is None


def test_duplicate_and_out_of_order_events_do_not_move_state():
    s = T.new_state()
    T.apply_line(s, ev(1, "run.started"))
    T.apply_line(s, ev(3, "progress.updated", prog(50.0)))
    assert not T.apply_line(s, ev(3, "progress.updated", prog(60.0)))   # duplicate
    assert not T.apply_line(s, ev(2, "progress.updated", prog(10.0)))   # late
    assert s["progress"]["percent"] == 50.0


def test_stale_run_cannot_overwrite_active_attempt_but_a_new_start_can():
    s = T.new_state()
    T.apply_line(s, ev(1, "run.started", run="run_b", attempt=2))
    T.apply_line(s, ev(2, "progress.updated", prog(40.0), run="run_b", attempt=2))
    assert not T.apply_line(s, ev(9, "progress.updated", prog(99.0), run="run_a", attempt=1))  # stale
    assert s["run_id"] == "run_b" and s["progress"]["percent"] == 40.0
    assert T.apply_line(s, ev(1, "run.started", run="run_c", attempt=3))   # a retry begins
    assert s["run_id"] == "run_c" and s["attempt"] == 3 and s["progress"] is None and s["last_seq"] == 1
    assert not T.apply_line(s, ev(1, "run.started", run="run_old", attempt=1))  # older attempt can't take over


def test_terminal_state_and_no_regression_after_failure():
    s = T.new_state()
    T.apply_line(s, ev(1, "run.started"))
    T.apply_line(s, ev(2, "progress.updated", prog(63.0)))
    T.apply_line(s, ev(3, "run.failed", {"reason": "boom"}))
    assert s["terminal"] == "failed" and s["progress"]["percent"] == 63.0


def test_percent_regression_is_rejected_defensively():
    s = T.new_state()
    T.apply_line(s, ev(1, "progress.updated", prog(50.0)))
    assert not T.apply_line(s, ev(2, "progress.updated", prog(20.0)))
    assert s["progress"]["percent"] == 50.0


def test_payload_is_whitelisted_bounded_and_text_stays_text():
    s = T.new_state()
    T.apply_line(s, ev(1, "progress.updated", prog(5.0, label="<img src=x onerror=alert(1)>" + "A" * 900, secret="K")))
    assert "secret" not in s["progress"] and len(s["progress"]["label"]) <= 300
    assert s["progress"]["label"].startswith("<img")   # stored verbatim; the UI escapes on render


def test_replay_file_rebuilds_state_and_snapshot_is_bounded(tmp_path):
    f = tmp_path / "run_events.jsonl"
    lines = [ev(i, "progress.updated", prog(float(i))) for i in range(1, 400)]
    f.write_text("\n".join(l[len(P):] for l in lines), encoding="utf-8")
    s = T.replay_file(f)
    assert s["last_seq"] == 399 and "events" not in s
    assert len(json.dumps(s)) < 4000


def test_missing_or_empty_replay_returns_none(tmp_path):
    assert T.replay_file(tmp_path / "nope.jsonl") is None
    (tmp_path / "e.jsonl").write_text("", encoding="utf-8")
    assert T.replay_file(tmp_path / "e.jsonl") is None


def test_find_events_file_searches_part_subfolder(tmp_path):
    (tmp_path / "A1").mkdir()
    (tmp_path / "A1" / "run_events.jsonl").write_text("x", encoding="utf-8")
    assert T.find_events_file(tmp_path).name == "run_events.jsonl"
    assert T.find_events_file(tmp_path / "A1").name == "run_events.jsonl"
    assert T.find_events_file(tmp_path / "A1" / "..").name == "run_events.jsonl"


def test_legacy_state_is_labeled():
    assert T.legacy_state() == {"schema_version": 1, "source": "legacy_log_parser", "run_id": None,
                                "attempt": None, "progress": None, "cost": None, "last_seq": 0, "terminal": None}
