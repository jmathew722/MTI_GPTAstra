"""Cost scopes from the ledger (Stage 1, task 1.4)."""
import json
from decimal import Decimal

from pipeline.token_tracker import Pricing, TokenTracker, cost_snapshot, scope

PRICING = Pricing({"providers": {"p": {
    "m": {"input": 1.0, "output": 2.0, "cache_read": 0.5, "cache_write": 0.0},
}}})


def _tracker(tmp_path):
    return TokenTracker(tmp_path / "usage_ledger.jsonl", PRICING)


def _call(t, part, run, attempt, inp=1_000_000, out=0, cread=0, model="m"):
    with t.activate(part=part, run_id=run, run_attempt=attempt):
        return t.record({"input_tokens": inp, "output_tokens": out, "cache_read_tokens": cread},
                        role="planner", model=model, provider="p")


def test_rows_carry_run_attempt_and_unique_row_id(tmp_path):
    t = _tracker(tmp_path)
    a = _call(t, "P1", "run_a", 1)
    b = _call(t, "P1", "run_a", 1)
    assert a.run_attempt == 1 and a.run_id == "run_a"
    assert a.row_id and a.row_id != b.row_id


def test_retry_scopes_reconcile_exactly(tmp_path):
    t = _tracker(tmp_path)
    _call(t, "P1", "run_a", 1, inp=1_000_000)                   # $1.000000
    _call(t, "P1", "run_a", 1, out=500_000)                     # $1 + $1 = 2.000000 (input also 1M)
    _call(t, "P1", "run_b", 2, inp=250_000, cread=2_000_000)    # 0.25 + 1.00 = 1.25
    _call(t, "OTHER", "run_c", 1, inp=1_000_000)                # 1.00
    snap = cost_snapshot(t.ledger_path, run_id="run_b", part="P1")
    assert Decimal(snap["run_cost_usd"]) == Decimal("1.25")
    assert Decimal(snap["part_total_cost_usd"]) == Decimal("4.25")      # all P1 attempts
    assert Decimal(snap["session_total_cost_usd"]) == Decimal("5.25")
    rows = [json.loads(l) for l in t.ledger_path.read_text(encoding="utf-8").splitlines()]
    assert Decimal(snap["session_total_cost_usd"]) == sum(Decimal(repr(r["cost_usd"])) for r in rows)
    assert snap["cached_input_tokens"] == 2_000_000 and snap["api_calls"] == 1
    assert snap["pricing_status"] == "priced"


def test_unpriced_rows_are_visible_not_zero(tmp_path):
    t = _tracker(tmp_path)
    _call(t, "P1", "run_a", 1)
    _call(t, "P1", "run_a", 1, model="unknown-model")
    snap = cost_snapshot(t.ledger_path, run_id="run_a", part="P1")
    assert snap["pricing_status"] == "partial" and snap["unpriced_calls"] == 1
    only = TokenTracker(tmp_path / "u.jsonl", PRICING)
    _call(only, "P2", "run_u", 1, model="unknown-model")
    s2 = cost_snapshot(only.ledger_path, run_id="run_u", part="P2")
    assert s2["pricing_status"] == "unpriced" and s2["run_cost_usd"] is None


def test_duplicate_rows_are_not_double_counted_and_legacy_rows_read(tmp_path):
    t = _tracker(tmp_path)
    _call(t, "P1", "run_a", 1)
    line = t.ledger_path.read_text(encoding="utf-8").splitlines()[0]
    legacy = {"ts": "2026-01-01T00:00:00+00:00", "run_id": "old", "role": "extractor", "provider": "p",
              "model": "m", "part": "P1", "input_tokens": 1_000_000, "output_tokens": 0,
              "cache_read_tokens": 0, "cache_write_tokens": 0, "cost_usd": 1.0, "priced": True}
    with t.ledger_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")                      # exact duplicate (same row_id)
        f.write(json.dumps(legacy) + "\n")        # pre-telemetry row, no row_id / run_attempt
    snap = cost_snapshot(t.ledger_path, run_id="run_a", part="P1")
    assert Decimal(snap["run_cost_usd"]) == Decimal("1")
    assert Decimal(snap["part_total_cost_usd"]) == Decimal("2")
    assert snap["legacy_rows"] == 1


def test_zero_token_call_and_listener_fires_after_durable_append(tmp_path):
    t = _tracker(tmp_path)
    seen = []
    t.add_listener(lambda rec: seen.append((rec.row_id, t.ledger_path.read_text(encoding="utf-8").count("\n"))))
    r = _call(t, "P1", "run_a", 1, inp=0)
    assert r.cost_usd == 0.0 and seen == [(r.row_id, 1)]   # ledger already had the row


def test_attached_telemetry_emits_cost_snapshot_after_each_ledger_write(tmp_path):
    from pipeline.run_events import parse_event_line
    from pipeline.telemetry import RunTelemetry, attach_cost_events
    lines = []
    tel = RunTelemetry.create(part_id="P1", out_dir=tmp_path, stdout=lines.append)
    t = _tracker(tmp_path)
    detach = attach_cost_events(tel, t, "P1")
    with t.activate(part="P1", run_id=tel.run_id, run_attempt=tel.attempt):
        t.record({"input_tokens": 1_000_000}, role="planner", model="m", provider="p")
        t.record({"input_tokens": 1_000_000}, role="planner", model="m", provider="p")
    detach()
    t.record({"input_tokens": 1_000_000}, role="planner", model="m", provider="p")   # after detach: silent
    costs = [parse_event_line(l) for l in lines]
    costs = [e["payload"] for e in costs if e and e["kind"] == "cost.updated"]
    assert [Decimal(c["run_cost_usd"]) for c in costs] == [Decimal("1"), Decimal("2")]
