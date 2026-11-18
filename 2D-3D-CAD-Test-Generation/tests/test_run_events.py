"""Run-event contract (Stage 1, task 1.1)."""
import json
from datetime import datetime

import pytest

from pipeline.run_events import (
    EVENT_PREFIX, SCHEMA_VERSION, RunEventEmitter, SequenceGuard, parse_event_line,
)


def _emitter(tmp_path=None, **kw):
    lines = []
    em = RunEventEmitter(run_id="run_t1", part_id="P1", attempt=2,
                         stdout=lines.append,
                         jsonl_path=(tmp_path / "run_events.jsonl") if tmp_path else None, **kw)
    return em, lines


def test_envelope_fields_and_monotonic_seq():
    em, lines = _emitter()
    a = em.emit("progress.updated", {"percent": 1.0})
    b = em.emit("progress.updated", {"percent": 2.0})
    assert [a["seq"], b["seq"]] == [1, 2]
    assert a["event_id"] != b["event_id"]
    assert (a["schema_version"], a["run_id"], a["part_id"], a["attempt"]) == (SCHEMA_VERSION, "run_t1", "P1", 2)
    assert a["occurred_at"].endswith("Z")
    datetime.fromisoformat(a["occurred_at"].replace("Z", "+00:00"))
    assert len(lines) == 2 and all(l.startswith(EVENT_PREFIX) for l in lines)


def test_parse_round_trip_and_prefix_exactness():
    em, lines = _emitter()
    ev = em.emit("run.started", {"x": "Ø6 ±0.1"})
    assert parse_event_line(lines[0]) == ev
    assert parse_event_line("  " + lines[0]) is None  # prefix must be exact
    assert parse_event_line("[gptastra-evnt] {}") is None
    assert parse_event_line("ordinary log line") is None


def test_malformed_json_returns_none():
    assert parse_event_line(EVENT_PREFIX + "{not json") is None
    assert parse_event_line(EVENT_PREFIX + "[1,2]") is None
    assert parse_event_line(EVENT_PREFIX + json.dumps({"kind": "x"})) is None  # missing envelope


def test_jsonl_is_durable_and_versioned(tmp_path):
    em, _ = _emitter(tmp_path)
    em.emit("run.started", {})
    em.emit("run.completed", {})
    em.close()
    rows = [json.loads(l) for l in (tmp_path / "run_events.jsonl").read_text("utf-8").splitlines()]
    assert [r["seq"] for r in rows] == [1, 2]
    assert all(r["schema_version"] == SCHEMA_VERSION for r in rows)


def test_payload_must_be_explicit_mapping_of_json_values():
    em, _ = _emitter()
    with pytest.raises(TypeError):
        em.emit("x", object())
    with pytest.raises(TypeError):
        em.emit("x", {"secret": object()})


def test_sequence_guard_rejects_duplicates_and_replays():
    g = SequenceGuard()
    mk = lambda run, seq: {"run_id": run, "seq": seq}
    assert g.accept(mk("r1", 1)) and g.accept(mk("r1", 2))
    assert not g.accept(mk("r1", 2))   # duplicate
    assert not g.accept(mk("r1", 1))   # replay
    assert g.accept(mk("r2", 1))       # new run is independent
