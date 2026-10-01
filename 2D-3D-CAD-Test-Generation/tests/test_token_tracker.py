"""Tests for the per-completion token tracker (pipeline.token_tracker)."""
import json
from types import SimpleNamespace

import pytest

from pipeline.token_tracker import (
    Pricing,
    TokenTracker,
    current_tracker,
    normalize_usage,
    record_cache_hit,
    record_completion,
    scope,
)


def _anthropic_response(inp=0, out=0, cread=0, cwrite=0):
    return SimpleNamespace(usage=SimpleNamespace(
        input_tokens=inp, output_tokens=out,
        cache_read_input_tokens=cread, cache_creation_input_tokens=cwrite,
    ))


# --------------------------------------------------------------------------- #
# normalize_usage
# --------------------------------------------------------------------------- #
class TestNormalizeUsage:
    def test_anthropic_response_object(self):
        n = normalize_usage(_anthropic_response(1000, 200, 300, 50))
        assert n == {"input_tokens": 1000, "output_tokens": 200,
                     "cache_read_tokens": 300, "cache_write_tokens": 50}

    def test_openai_responses_api_subtracts_cached_from_input(self):
        # OpenAI reports cached tokens INSIDE input_tokens; the record keeps uncached only.
        resp = SimpleNamespace(usage=SimpleNamespace(
            input_tokens=1000, output_tokens=100,
            input_tokens_details=SimpleNamespace(cached_tokens=400),
        ))
        n = normalize_usage(resp)
        assert n["input_tokens"] == 600
        assert n["cache_read_tokens"] == 400
        assert n["output_tokens"] == 100

    def test_openai_chat_completions_shape(self):
        resp = SimpleNamespace(usage=SimpleNamespace(
            prompt_tokens=500, completion_tokens=50,
            prompt_tokens_details=SimpleNamespace(cached_tokens=100),
        ))
        n = normalize_usage(resp)
        assert (n["input_tokens"], n["cache_read_tokens"], n["output_tokens"]) == (400, 100, 50)

    def test_bedrock_converse_dict(self):
        resp = {"usage": {"inputTokens": 900, "outputTokens": 90,
                          "cacheReadInputTokens": 10, "cacheWriteInputTokens": 5}}
        n = normalize_usage(resp)
        assert n == {"input_tokens": 900, "output_tokens": 90,
                     "cache_read_tokens": 10, "cache_write_tokens": 5}

    def test_plain_normalized_dict_passes_through(self):
        d = {"input_tokens": 7, "output_tokens": 3}
        n = normalize_usage(d)
        assert n["input_tokens"] == 7 and n["output_tokens"] == 3
        assert n["cache_read_tokens"] == 0 and n["cache_write_tokens"] == 0

    def test_none_and_missing_usage_are_zero(self):
        zero = {"input_tokens": 0, "output_tokens": 0,
                "cache_read_tokens": 0, "cache_write_tokens": 0}
        assert normalize_usage(None) == zero
        assert normalize_usage(SimpleNamespace()) == zero


# --------------------------------------------------------------------------- #
# Pricing
# --------------------------------------------------------------------------- #
@pytest.fixture
def pricing():
    return Pricing({
        "providers": {
            "anthropic": {
                "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_write": 5.0, "cache_read": 0.2},
            },
            "foundry": {
                "gpt-6-astra": {"input": 10.0, "output": 50.0, "cache_write": None, "cache_read": None},
            },
        }
    })


class TestPricing:
    def test_priced_cost_is_exact(self, pricing):
        n = {"input_tokens": 1_000_000, "output_tokens": 1_000_000,
             "cache_read_tokens": 1_000_000, "cache_write_tokens": 1_000_000}
        assert pricing.cost("anthropic", "claude-opus-5-5", n) == pytest.approx(29.2)

    def test_unknown_model_is_unpriced(self, pricing):
        n = {"input_tokens": 10, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}
        assert pricing.cost("bedrock", "claude-opus-5-5", n) is None

    def test_null_price_with_tokens_in_that_class_is_unpriced(self, pricing):
        n = {"input_tokens": 100, "output_tokens": 10, "cache_read_tokens": 50, "cache_write_tokens": 0}
        assert pricing.cost("foundry", "gpt-6-astra", n) is None

    def test_null_price_with_zero_tokens_in_that_class_is_fine(self, pricing):
        n = {"input_tokens": 1_000_000, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}
        assert pricing.cost("foundry", "gpt-6-astra", n) == pytest.approx(10.0)

    def test_zero_tokens_cost_zero_even_if_unknown_model(self, pricing):
        n = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}
        assert pricing.cost("nowhere", "nothing", n) == 0.0

    def test_shipped_pricing_file_loads_and_prices_opus_5_5(self):
        p = Pricing.load()
        assert p.price_for("anthropic", "claude-opus-5-5")["input"] == 4.0
        assert p.price_for("anthropic", "claude-sonnet-4-6")["output"] == 15.0


# --------------------------------------------------------------------------- #
# TokenTracker + scopes
# --------------------------------------------------------------------------- #
def _rows(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


class TestTokenTracker:
    def test_record_appends_one_json_row(self, tmp_path, pricing):
        ledger = tmp_path / "usage" / "usage_ledger.jsonl"
        t = TokenTracker(ledger, pricing=pricing, run_id="r1")
        rec = t.record(normalize_usage(_anthropic_response(1_000_000, 0)),
                       role="planner", model="claude-opus-5-5", provider="anthropic",
                       part="SB11033", latency_ms=1234)
        rows = _rows(ledger)
        assert len(rows) == 1
        r = rows[0]
        assert r["run_id"] == "r1" and r["role"] == "planner" and r["part"] == "SB11033"
        assert r["cost_usd"] == pytest.approx(4.0) and r["priced"] is True
        assert r["latency_ms"] == 1234
        assert rec.cost_usd == pytest.approx(4.0)

    def test_unpriced_row_has_null_cost(self, tmp_path, pricing):
        t = TokenTracker(tmp_path / "l.jsonl", pricing=pricing)
        t.record({"input_tokens": 5}, role="planner", model="mystery", provider="bedrock")
        r = _rows(tmp_path / "l.jsonl")[0]
        assert r["cost_usd"] is None and r["priced"] is False

    def test_scopes_merge_and_inner_overrides(self, tmp_path, pricing):
        t = TokenTracker(tmp_path / "l.jsonl", pricing=pricing)
        with t.activate(part="P1", arm="opus-audited"):
            with scope(role="auditor_reviewer", gate=1, attempt=0):
                with scope(attempt=1):
                    record_completion(_anthropic_response(10, 5), model="claude-opus-5-5",
                                      provider="anthropic")
        r = _rows(tmp_path / "l.jsonl")[0]
        assert (r["part"], r["arm"], r["role"], r["gate"], r["attempt"]) == \
            ("P1", "opus-audited", "auditor_reviewer", 1, 1)

    def test_explicit_kwargs_override_scope(self, tmp_path, pricing):
        t = TokenTracker(tmp_path / "l.jsonl", pricing=pricing)
        with t.activate(role="extractor"):
            record_completion(_anthropic_response(1, 1), model="claude-opus-5-5",
                              provider="anthropic", role="planner")
        assert _rows(tmp_path / "l.jsonl")[0]["role"] == "planner"

    def test_helpers_are_noops_without_active_tracker(self, tmp_path):
        assert current_tracker() is None
        assert record_completion(_anthropic_response(1, 1), model="m", provider="anthropic") is None
        assert record_cache_hit(model="m", provider="anthropic") is None
        assert not list(tmp_path.iterdir())

    def test_tracker_deactivates_after_block(self, tmp_path, pricing):
        t = TokenTracker(tmp_path / "l.jsonl", pricing=pricing)
        with t.activate():
            assert current_tracker() is t
        assert current_tracker() is None

    def test_cache_hit_row_is_free(self, tmp_path, pricing):
        t = TokenTracker(tmp_path / "l.jsonl", pricing=pricing)
        with t.activate(part="P"):
            record_cache_hit(model="claude-opus-5-5", provider="anthropic", role="extractor")
        r = _rows(tmp_path / "l.jsonl")[0]
        assert r["cache_hit"] is True and r["cost_usd"] == 0.0 and r["input_tokens"] == 0

    def test_write_failure_does_not_raise(self, tmp_path, pricing):
        # Ledger path is a directory -> open() fails; recording must not break the run.
        bad = tmp_path / "is_a_dir"
        bad.mkdir()
        t = TokenTracker(bad, pricing=pricing)
        rec = t.record({"input_tokens": 1}, role="planner", model="claude-opus-5-5",
                       provider="anthropic")
        assert rec.input_tokens == 1
