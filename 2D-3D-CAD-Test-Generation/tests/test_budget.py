"""API spend cap: preflight reserve, charging, conservative rates, run stop."""
import json
from types import SimpleNamespace as NS

import pytest

from pipeline import budget


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "budget.jsonl"
    monkeypatch.setenv("API_BUDGET_LEDGER", str(path))
    monkeypatch.setenv("API_BUDGET_USD", "1.00")
    return path


def _resp(inp, out):
    return NS(usage=NS(input_tokens=inp, output_tokens=out))


def test_priced_model_uses_exact_rate():
    i, o, basis = budget.budget_rates("anthropic", "claude-sonnet-4-6")
    assert (i, o, basis) == (3.0, 15.0, "priced")


def test_unpriced_model_uses_max_listed_rate_for_that_model():
    # Bedrock gpt-6-astra is still unpriced; Azure lists 10/50 -> budget uses 10/50 (openai was priced 2026-11-19, see tests/test_pricing_config.py)
    i, o, basis = budget.budget_rates("bedrock", "gpt-6-astra")
    assert (i, o) == (10.0, 50.0) and basis.startswith("unpriced")


def test_unknown_model_uses_max_rate_in_file():
    i, o, _ = budget.budget_rates("nobody", "mystery")
    assert i >= 10.0 and o >= 50.0


def test_charge_accumulates_spend(ledger):
    budget.charge(_resp(100_000, 0), "bedrock", "gpt-6-astra")   # 0.1M input x $10/M = $1.00
    assert budget.spent_usd() == pytest.approx(1.0)
    row = json.loads(ledger.read_text().splitlines()[0])
    assert row["cost_usd"] == pytest.approx(1.0) and row["basis"].startswith("unpriced")


def test_preflight_blocks_when_worst_case_crosses_cap(ledger):
    budget.charge(_resp(50_000, 0), "bedrock", "gpt-6-astra")    # $0.50 spent of $1.00
    with pytest.raises(budget.BudgetExceeded, match=r"spent \$0\.50 of \$1\.00"):
        budget.preflight("bedrock", "gpt-6-astra", 10_000, 16_000)  # reserve $0.10 + $0.80


def test_preflight_allows_when_it_fits(ledger):
    assert budget.preflight("bedrock", "gpt-6-astra", 1_000, 1_000) == pytest.approx(0.06)


def test_image_estimate_uses_fixed_allowance():
    msgs = [{"role": "user", "content": [
        {"type": "image", "source": {"data": "x" * 3_000_000}}, {"type": "text", "text": "hi"}]}]
    est = budget.estimate_input_tokens("", msgs)
    assert budget.IMAGE_TOKEN_ALLOWANCE <= est < budget.IMAGE_TOKEN_ALLOWANCE + 100


def test_extractor_stops_before_calling_api_when_over_budget(ledger, monkeypatch):
    from pipeline import extractor
    monkeypatch.setenv("API_BUDGET_USD", "0.01")
    called = []
    client = NS(messages=NS(create=lambda **k: called.append(k)))
    with pytest.raises(budget.BudgetExceeded):
        extractor._call(client, "claude-sonnet-4-6", [{"role": "user", "content": "x"}])
    assert called == []  # no request was sent


def test_batch_does_not_swallow_budget_stop(tmp_path, monkeypatch, ledger):
    from pipeline import batch
    drawing = tmp_path / "in" / "a.png"
    drawing.parent.mkdir()
    drawing.write_bytes(b"x")

    def boom(_path):
        raise budget.BudgetExceeded("stop")

    with pytest.raises(budget.BudgetExceeded):
        batch.run_batch(drawing.parent, tmp_path / "out", extract_fn=boom)
