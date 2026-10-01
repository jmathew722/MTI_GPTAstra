"""Token-usage and Claude API cost ledger.

Appends one row per extraction run to a human-readable ``token_usage_log.txt``
(and a machine-readable ``token_usage_log.jsonl`` used to recompute the running
total) at the output root, so the cost of every API call is tracked over time.

Prices are USD per MILLION tokens, read from ``config/pricing.json`` (the
"anthropic" provider section) — edit prices there, not here. This per-run summary
is kept for continuity; the per-completion ledger in ``pipeline/token_tracker.py``
(by role, model, provider, part, gate, attempt) is the source of truth for cost
reporting (``python -m pipeline.token_report``).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

# USD per 1,000,000 tokens — the "anthropic" provider rates from config/pricing.json,
# the single price table shared with the per-completion tracker
# (pipeline/token_tracker.py, which supersedes this per-run summary).
_PRICING_PATH = Path(__file__).resolve().parent.parent / "config" / "pricing.json"


def _load_anthropic_pricing() -> dict[str, dict[str, float]]:
    try:
        providers = json.loads(_PRICING_PATH.read_text(encoding="utf-8")).get("providers", {})
    except (OSError, json.JSONDecodeError):
        providers = {}
    keys = ("input", "output", "cache_write", "cache_read")
    return {
        model: {k: float(p[k]) for k in keys}
        for model, p in providers.get("anthropic", {}).items()
        if all(p.get(k) is not None for k in keys)
    }


PRICING: dict[str, dict[str, float]] = _load_anthropic_pricing()
# Used when the model isn't in PRICING (keeps the ledger working, flags unknown).
_FALLBACK = {"input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30}

LEDGER_TXT = "token_usage_log.txt"
LEDGER_JSONL = "token_usage_log.jsonl"


def estimate_cost(usage: dict[str, int], model: str) -> float:
    """USD cost of one run's token usage. Cache hits (no tokens) cost $0."""
    p = PRICING.get(model, _FALLBACK)
    return (
        usage.get("input_tokens", 0) / 1e6 * p["input"]
        + usage.get("output_tokens", 0) / 1e6 * p["output"]
        + usage.get("cache_creation_input_tokens", 0) / 1e6 * p["cache_write"]
        + usage.get("cache_read_input_tokens", 0) / 1e6 * p["cache_read"]
    )


def record_run(output_dir: Path | str, part: str, model: str, usage: dict[str, int]) -> Path:
    """Append one run to the ledger and rewrite the human-readable total.

    Returns the path to the human-readable ``token_usage_log.txt``.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cost = estimate_cost(usage, model)
    cache_hit = usage.get("cache_hits", 0) > 0 and not usage.get("input_tokens", 0)

    row = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "part": part or "?",
        "model": model,
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
        "cache_write_tokens": usage.get("cache_creation_input_tokens", 0),
        "api_calls": usage.get("calls", 0),
        "cache_hit": cache_hit,
        "cost_usd": round(cost, 4),
        "model_priced": model in PRICING,
    }

    # Append the machine-readable row, then recompute totals from all rows.
    jsonl_path = output_dir / LEDGER_JSONL
    with jsonl_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")

    rows = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    total_cost = sum(r.get("cost_usd", 0.0) for r in rows)
    total_in = sum(r.get("input_tokens", 0) for r in rows)
    total_out = sum(r.get("output_tokens", 0) for r in rows)
    total_cread = sum(r.get("cache_read_tokens", 0) for r in rows)

    lines = [
        "CLAUDE API TOKEN & COST LEDGER",
        "==============================",
        "Prices USD per 1M tokens (sonnet-4-6 $3/$15, opus-4-8 $5/$25; "
        "cache write 1.25x input, cache read 0.10x input).",
        "Only extraction runs hit the API; --from-json and cache hits cost $0.",
        "",
        f"{'TIMESTAMP':<20}  {'PART':<16}  {'MODEL':<18}  "
        f"{'IN':>9}  {'OUT':>8}  {'CACHE_RD':>9}  {'CALLS':>5}  {'COST_USD':>9}",
        "-" * 110,
    ]
    for r in rows:
        note = "  (cache hit)" if r.get("cache_hit") else ""
        note += "  [unpriced model]" if not r.get("model_priced", True) else ""
        lines.append(
            f"{r.get('timestamp',''):<20}  {str(r.get('part',''))[:16]:<16}  "
            f"{str(r.get('model',''))[:18]:<18}  {r.get('input_tokens',0):>9,}  "
            f"{r.get('output_tokens',0):>8,}  {r.get('cache_read_tokens',0):>9,}  "
            f"{r.get('api_calls',0):>5}  {r.get('cost_usd',0.0):>9.4f}{note}"
        )
    lines += [
        "-" * 110,
        f"{'TOTAL':<20}  {len(rows)} run(s){'':<8}  {'':<18}  "
        f"{total_in:>9,}  {total_out:>8,}  {total_cread:>9,}  {'':>5}  {total_cost:>9.4f}",
        "",
        f"TOTAL API COST TO DATE: ${total_cost:.4f}",
    ]
    txt_path = output_dir / LEDGER_TXT
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return txt_path
