"""v8 cost / usage / runtime accounting (SolidFlow_API_Cost.md). Offline; mocks only."""
from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace

from pipeline import token_tracker as tt
from reverse import costs

RATE = {"provider": "openai", "model": "m", "input": Decimal("2.5"), "output": Decimal("10"), "cached": Decimal("0.25"), "extra": Decimal(0), "tier": "standard",
        "as_of": "2026-01-01", "effective_date": None, "source": "t", "version": "v1"}


def test_spec_illustrative_calculation():
    # SolidFlow_API_Cost.md illustrative numbers: 20k in + 4k out = $0.09
    assert costs.request_cost(20000, 0, 4000, RATE) == Decimal("0.09")
    assert costs.request_cost(8000, 0, 2000, RATE) == Decimal("0.04")
    assert costs.request_cost(12000, 0, 2000, RATE) == Decimal("0.05")


def test_cached_input_priced_at_cached_rate_and_not_double_counted():
    # 10k input of which 8k cached: 2k*2.5 + 8k*0.25 = 7000 / 1e6
    assert costs.request_cost(10000, 8000, 0, RATE) == Decimal("0.007")


def test_unknown_rate_is_unavailable_not_zero():
    assert costs.request_cost(10, 0, 10, None) is None
    assert costs.load_rate("no-such-model") is None


def _mk(tmp_path, rows):
    p = tmp_path / "usage_ledger.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return costs.read_rows(p)


def _row(**kw):
    base = {"row_id": kw.pop("row_id", "r1"), "role": "extractor", "provider": "openai", "model": "gpt-6-astra", "part": "P", "input_tokens": 1000, "output_tokens": 100,
            "cache_read_tokens": 0, "cache_write_tokens": 0, "cache_hit": False, "ok": True, "extra": {"response_id": kw.pop("rid", "resp1")}}
    base.update(kw)
    return base


def test_aggregate_prices_from_config_and_dedupes_by_response_id(tmp_path):
    rows = _mk(tmp_path, [_row(row_id="a", rid="resp1"), _row(row_id="b", rid="resp1"), _row(row_id="c", rid="resp2", attempt=1)])
    u = costs.aggregate(rows, part="P")
    assert u["calls"] == 2                                     # duplicate event ignored
    one = costs.request_cost(1000, 0, 100, costs.load_rate("gpt-6-astra"))
    assert u["cost_usd"] == float(one * 2) and u["cost_status"] == "priced"
    assert [a["attempt"] for a in u["attempts"]] == [None, 1]  # attempts are separate entries
    assert u["by_stage"]["extraction"]["calls"] == 2


def test_cache_hit_is_free_and_not_a_call(tmp_path):
    rows = _mk(tmp_path, [_row(cache_hit=True, input_tokens=0, output_tokens=0)])
    u = costs.aggregate(rows, part="P")
    assert u["calls"] == 0 and u["cache_hits"] == 1 and u["cost_usd"] == 0.0 and u["cost_status"] == "none"


def test_missing_usage_is_unknown_not_free(tmp_path):
    rows = _mk(tmp_path, [_row(row_id="a", extra={"response_id": "x", "usage_missing": True}, input_tokens=0, output_tokens=0)])
    u = costs.aggregate(rows, part="P")
    assert u["calls"] == 1 and u["unknown_usage_calls"] == 1 and u["cost_usd"] is None and u["cost_status"] == "unpriced"


def test_partial_when_one_model_unpriced(tmp_path):
    rows = _mk(tmp_path, [_row(row_id="a", rid="x"), _row(row_id="b", rid="y", model="mystery-model")])
    u = costs.aggregate(rows, part="P")
    assert u["cost_status"] == "partial" and u["cost_usd"] is not None and u["unpriced_calls"] == 1


def test_multiple_models_priced_each_by_own_rate(tmp_path):
    rows = _mk(tmp_path, [_row(row_id="a", rid="x"), _row(row_id="b", rid="y", provider="anthropic", model="claude-sonnet-4-6")])
    u = costs.aggregate(rows, part="P")
    r1, r2 = costs.load_rate("gpt-6-astra"), costs.load_rate("claude-sonnet-4-6", "anthropic")
    assert Decimal(repr(u["cost_usd"])) == costs.request_cost(1000, 0, 100, r1) + costs.request_cost(1000, 0, 100, r2)


def test_rate_change_reprices_history(tmp_path, monkeypatch):
    rows = _mk(tmp_path, [_row()])
    a = costs.aggregate(rows, part="P")["cost_usd"]
    pricing = tmp_path / "p.json"
    pricing.write_text(json.dumps({"providers": {"openai": {"gpt-6-astra": {"input": 1.0, "output": 1.0, "cache_read": 1.0, "as_of": "2030-01-01"}}}}), encoding="utf-8")
    monkeypatch.setattr(tt, "DEFAULT_PRICING_PATH", pricing)
    b = costs.aggregate(rows, part="P")
    assert b["cost_usd"] != a and b["rate_version"] == "2030-01-01"


def test_tracker_records_response_id_and_missing_usage(tmp_path):
    tr = tt.TokenTracker(tmp_path / "l.jsonl")
    with tr.activate(part="P"):
        tt.record_completion(SimpleNamespace(id="resp_9", usage=SimpleNamespace(input_tokens=10, output_tokens=5)), model="gpt-6-astra", provider="openai", role="extractor")
        tt.record_completion(SimpleNamespace(id="resp_10", usage=None), model="gpt-6-astra", provider="openai", role="extractor")
    rows = costs.read_rows(tmp_path / "l.jsonl")
    u = costs.aggregate(rows, part="P")
    assert u["calls"] == 2 and u["unknown_usage_calls"] == 1 and u["cost_status"] == "partial"
    assert rows[0]["extra"]["response_id"] == "resp_9"


def test_merge_usage_unknown_part_makes_total_partial(tmp_path):
    a = costs.aggregate(_mk(tmp_path, [_row()]), part="P")
    b = {**costs.aggregate([]), "calls": 1, "cost_usd": None, "cost_status": "unpriced"}
    m = costs.merge_usage([a, b])
    assert m["cost_status"] == "partial" and m["calls"] == 2


def test_image_tokens_rule():
    assert costs.image_tokens(2576, 1980) == 85 + 170 * 4 * 3 or costs.image_tokens(2576, 1980) > 85


def test_estimate_standard_has_no_model_cost():
    e = costs.estimate_part(mode="standard", facts=None, rate=None, cache="none", token_hist=None, dur_hist=None)
    assert e["cost"]["expected"] == 0.0 and e["cost"]["unavailable_reason"] is None
    assert e["duration"]["source"] == "fallback" and "fallback_duration" in e["labels"]


def test_estimate_match_ranges_and_unavailable_rate():
    facts = {"pages": [{"px": (2576, 1980), "text_blocks": 0, "scanned": True, "width_pt": 1580, "height_pt": 1216}], "page_count": 1}
    e = costs.estimate_part(mode="match", facts=facts, rate=costs.load_rate("gpt-6-astra"), cache="fresh", token_hist=None, dur_hist=None)
    c = e["cost"]
    assert 0 < c["low"] < c["expected"] < c["high"] and "fallback_tokens" in e["labels"]
    e2 = costs.estimate_part(mode="match", facts=facts, rate=None, cache="fresh", token_hist=None, dur_hist=None)
    assert e2["cost"]["expected"] is None and e2["cost"]["unavailable_reason"]
    e3 = costs.estimate_part(mode="match", facts=facts, rate=costs.load_rate("gpt-6-astra"), cache="hit", token_hist=None, dur_hist=None)
    assert e3["cost"]["expected"] == 0.0


def test_estimate_scales_with_pages_and_tiles():
    pg = {"px": (2576, 1980), "text_blocks": 0, "scanned": True, "width_pt": 1580, "height_pt": 1216}
    r = costs.load_rate("gpt-6-astra")
    one = costs.estimate_part(mode="match", facts={"pages": [pg], "page_count": 1}, rate=r, cache="fresh", token_hist=None, dur_hist=None)
    two = costs.estimate_part(mode="match", facts={"pages": [pg, pg], "page_count": 2}, rate=r, cache="fresh", token_hist=None, dur_hist=None)
    tiled = costs.estimate_part(mode="match", facts={"pages": [pg], "page_count": 1}, rate=r, cache="fresh", token_hist=None, dur_hist=None, tiles_per_page=4)
    assert two["cost"]["expected"] > one["cost"]["expected"] * 1.9 and tiled["cost"]["expected"] > one["cost"]["expected"]


def test_history_overrides_fallback_and_is_labelled():
    hist = {"n": 5, "input": (9000, 10000, 12000), "output": (2000, 3000, 5000)}
    e = costs.estimate_part(mode="match", facts={"pages": [{"px": (1000, 800), "text_blocks": 0, "scanned": True}], "page_count": 1}, rate=costs.load_rate("gpt-6-astra"),
                            cache="fresh", token_hist=hist, dur_hist={"n": 4, "low": 50, "expected": 80, "high": 200})
    assert e["duration"]["source"] == "history" and "fallback_tokens" not in e["labels"]
    assert e["tokens"]["output"]["expected"] == 3000


def test_timing_queue_separate_and_monotonic_elapsed():
    from reverse import state
    j = state.Job(job_id="j", template_id="t")
    j.created = "2026-01-01T00:00:00+00:00"
    p = state.PartState(part_id="a", source="x", name="a")
    p.started = "2026-01-01T00:00:05+00:00"
    p.state, p.seconds, p.ended = "completed", 42.5, "2026-01-01T00:01:00+00:00"
    p.stages = {"extraction": {"status": "succeeded", "seconds": 10.0}, "native_drawing": {"status": "succeeded", "seconds": 20.0}}
    t = costs.timing_for(j, p)
    assert t["queued_s"] == 5.0 and t["elapsed_s"] == 42.5 and t["by_stage"] == {"extraction": 10.0, "native_drawing": 20.0} and not t["running"]


def test_budget_blocks_new_call_when_projected_exceeds_remaining(monkeypatch, tmp_path):
    from pipeline import budget
    monkeypatch.setenv("API_BUDGET_LEDGER", str(tmp_path / "b.jsonl"))
    monkeypatch.setenv("API_BUDGET_USD", "0.10")
    try:
        budget.preflight("openai", "gpt-6-astra", 5000, 16000)
        raised = False
    except budget.BudgetExceeded:
        raised = True
    assert raised
