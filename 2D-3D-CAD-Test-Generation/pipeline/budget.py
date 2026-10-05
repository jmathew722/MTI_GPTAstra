"""Hard API spend cap, shared by every run on this machine.

Every paid model call goes through two steps:

1. :func:`preflight` before the request. It reserves the call's WORST-CASE cost
   (estimated input + the full ``max_tokens`` of output) and raises
   :class:`BudgetExceeded` if spent + reserve would pass the cap. So the cap holds
   even if the call uses every token it is allowed.
2. :func:`charge` after the response. It appends the actual cost to the budget
   ledger.

The ledger is one JSONL file shared by all runs (``API_BUDGET_LEDGER``, default
``<code root>/usage/budget_ledger.jsonl``), independent of the per-run token
ledger in ``pipeline.token_tracker``. The cap is ``API_BUDGET_USD`` (default 20).

Unpriced models (a ``null`` price in ``config/pricing.json``) are charged at the
HIGHEST rate any provider lists for that model, else the highest rate in the file.
The budget therefore over-counts rather than under-counts. That conservative
number is used only for the budget. The token report still shows the row as unpriced.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pipeline.token_tracker import DEFAULT_PRICING_PATH, normalize_usage
from utils.logger import get_logger

log = get_logger()

DEFAULT_CAP_USD = 20.0
DEFAULT_LEDGER = Path(__file__).resolve().parent.parent / "usage" / "budget_ledger.jsonl"
IMAGE_TOKEN_ALLOWANCE = 10_000   # per image, input-side reserve (observed ~1-2k)
CHARS_PER_TOKEN = 3              # conservative text estimate


class BudgetExceeded(RuntimeError):
    """The API spend cap would be exceeded; the whole run must stop."""


def cap_usd() -> float:
    raw = os.getenv("API_BUDGET_USD")
    if raw:
        try:
            return float(raw)
        except ValueError:
            log.warning("Ignoring non-numeric API_BUDGET_USD=%r", raw)
    return DEFAULT_CAP_USD


def ledger_path() -> Path:
    return Path(os.getenv("API_BUDGET_LEDGER") or DEFAULT_LEDGER)


def spent_usd() -> float:
    path = ledger_path()
    if not path.exists():
        return 0.0
    total = 0.0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            total += float(json.loads(line).get("cost_usd") or 0.0)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
    return total


# --------------------------------------------------------------------------- #
# Conservative rates
# --------------------------------------------------------------------------- #
def _load_providers() -> dict:
    try:
        return json.loads(DEFAULT_PRICING_PATH.read_text(encoding="utf-8")).get("providers", {})
    except (OSError, json.JSONDecodeError):
        return {}


def budget_rates(provider: str, model: str) -> tuple[float, float, str]:
    """(input $/1M, output $/1M, basis). Exact price when known, else the max known."""
    providers = _load_providers()
    exact = providers.get(provider, {}).get(model) or {}
    if exact.get("input") is not None and exact.get("output") is not None:
        return float(exact["input"]), float(exact["output"]), "priced"

    def _max(rows: list[dict]) -> tuple[float, float]:
        ins = [float(r["input"]) for r in rows if r.get("input") is not None]
        outs = [float(r["output"]) for r in rows if r.get("output") is not None]
        return (max(ins) if ins else 0.0), (max(outs) if outs else 0.0)

    same_model = [p.get(model) for p in providers.values() if isinstance(p.get(model), dict)]
    i, o = _max([r for r in same_model if r])
    if i and o:
        return i, o, f"unpriced: using max listed rate for {model}"
    every = [r for p in providers.values() for r in p.values() if isinstance(r, dict)]
    i, o = _max(every)
    return i, o, "unpriced: using max rate in pricing.json"


def _cost(provider: str, model: str, input_tokens: int, output_tokens: int) -> tuple[float, str]:
    i, o, basis = budget_rates(provider, model)
    return input_tokens / 1e6 * i + output_tokens / 1e6 * o, basis


# --------------------------------------------------------------------------- #
# Guard
# --------------------------------------------------------------------------- #
def estimate_input_tokens(system: Any, messages: list[dict[str, Any]]) -> int:
    """Rough upper estimate of a request's input tokens (images at a fixed allowance)."""
    chars = len(json.dumps(system, default=str)) if system else 0
    images = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            chars += len(content)
            continue
        for b in content or []:
            if isinstance(b, dict) and b.get("type") == "image":
                images += 1
            elif isinstance(b, dict):
                chars += len(json.dumps(b, default=str))
            else:  # SDK/adapter content block objects from a previous assistant turn
                chars += len(str(getattr(b, "input", "")) + str(getattr(b, "text", "")))
    return chars // CHARS_PER_TOKEN + images * IMAGE_TOKEN_ALLOWANCE


def preflight(provider: str, model: str, input_tokens_est: int, max_output_tokens: int) -> float:
    """Raise BudgetExceeded unless the worst case of this call fits. Returns the reserve."""
    reserve, basis = _cost(provider, model, input_tokens_est, max_output_tokens)
    spent, cap = spent_usd(), cap_usd()
    if spent + reserve > cap:
        raise BudgetExceeded(
            f"API budget stop: spent ${spent:.2f} of ${cap:.2f}; the next {model} call could "
            f"cost up to ${reserve:.2f} ({basis}). Raise API_BUDGET_USD or reset "
            f"{ledger_path()} to continue."
        )
    return reserve


def charge(response: Any, provider: str, model: str, *, role: str = "", part: str = "") -> float:
    """Record a completed call's cost in the budget ledger and return it."""
    n = normalize_usage(response)
    # cache_read is billed below the input rate; counting it at full input rate
    # keeps the budget conservative.
    cost, basis = _cost(provider, model, n["input_tokens"] + n["cache_read_tokens"]
                        + n["cache_write_tokens"], n["output_tokens"])
    row = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "provider": provider, "model": model, "role": role, "part": part,
           **n, "cost_usd": round(cost, 6), "basis": basis}
    path = ledger_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except OSError as e:  # the guard must not silently lose spend: surface loudly
        log.error("Budget ledger write failed (%s): %s", path, e)
    spent, cap = spent_usd(), cap_usd()
    log.info("[budget] this call $%.4f (%s) | spent $%.2f of $%.2f", cost, basis, spent, cap)
    return cost
