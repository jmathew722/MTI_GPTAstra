"""Per-completion token and cost tracker.

Every model completion in the pipeline (extractor, planner/builder, auditor
reviewer, Jev, ...) appends ONE row to an append-only JSONL ledger, tagged with
who made the call and why: role, model, provider, part, benchmark arm, audit gate
and retry attempt. ``pipeline/token_report.py`` turns the ledger into cost-per-part
and cost-per-role reports.

Typical use::

    tracker = TokenTracker(output_dir / "usage" / LEDGER_NAME)
    with tracker.activate(part="SB11033", arm="opus-audited"):
        with scope(role="planner", gate=1, attempt=0):
            t0 = time.perf_counter()
            resp = client.messages.create(...)
            record_completion(resp, model="claude-opus-5-5", provider="anthropic",
                              latency_ms=(time.perf_counter() - t0) * 1000)

``record_completion`` / ``record_cache_hit`` are no-ops when no tracker is active,
so library code can call them unconditionally. Recording never raises: a failed
ledger write is logged as a warning (a cost report must never break a build).

Prices come from ``config/pricing.json`` (USD per 1M tokens, per provider and
model). A price that is missing or ``null`` makes the row UNPRICED
(``cost_usd = None``, ``priced = False``) instead of guessing.
"""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional, Union

from utils.logger import get_logger

log = get_logger()

LEDGER_NAME = "usage_ledger.jsonl"
DEFAULT_PRICING_PATH = Path(__file__).resolve().parent.parent / "config" / "pricing.json"

# Normalized token classes -> pricing.json rate keys.
_RATE_KEYS = {
    "input_tokens": "input",
    "output_tokens": "output",
    "cache_read_tokens": "cache_read",
    "cache_write_tokens": "cache_write",
}

# Fields a record carries besides the token counts; anything else goes in ``extra``.
_CONTEXT_FIELDS = ("run_id", "part", "arm", "role", "gate", "attempt")


# --------------------------------------------------------------------------- #
# Usage normalization
# --------------------------------------------------------------------------- #
def _get(obj: Any, *names: str) -> Any:
    """First non-None attribute/key among ``names`` (dicts and objects alike)."""
    if obj is None:
        return None
    for name in names:
        value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
        if value is not None:
            return value
    return None


def _num(obj: Any, *names: str) -> int:
    """Integer token count, or 0. Ignores non-numbers (e.g. MagicMock attributes)."""
    value = _get(obj, *names)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def normalize_usage(response_or_usage: Any) -> dict[str, int]:
    """Map any provider's usage report onto one shape.

    Accepts a full response (``.usage`` / ``["usage"]``) or the usage object itself:
    Anthropic / Foundry / Bedrock-Mantle (``input_tokens``,
    ``cache_read_input_tokens``, ``cache_creation_input_tokens``), Bedrock Converse
    (``inputTokens``, ``cacheReadInputTokens``, ...), OpenAI Responses
    (``input_tokens`` + ``input_tokens_details.cached_tokens``), OpenAI Chat
    (``prompt_tokens`` + ``prompt_tokens_details.cached_tokens``), or an
    already-normalized dict.

    ``input_tokens`` in the result is always UNCACHED input: OpenAI counts cached
    tokens inside its input total, so they are moved to ``cache_read_tokens``.
    """
    obj = response_or_usage
    if isinstance(obj, dict):
        usage = obj.get("usage", obj)
    else:
        usage = getattr(obj, "usage", obj) if obj is not None else None

    inp = _num(usage, "input_tokens", "inputTokens", "prompt_tokens")
    out = _num(usage, "output_tokens", "outputTokens", "completion_tokens")
    cread = _num(usage, "cache_read_input_tokens", "cacheReadInputTokens", "cache_read_tokens")
    cwrite = _num(usage, "cache_creation_input_tokens", "cacheWriteInputTokens", "cache_write_tokens")

    details = _get(usage, "input_tokens_details", "prompt_tokens_details")
    cached = _num(details, "cached_tokens")
    if cached:
        inp = max(inp - cached, 0)
        cread += cached

    return {"input_tokens": inp, "output_tokens": out,
            "cache_read_tokens": cread, "cache_write_tokens": cwrite}


# --------------------------------------------------------------------------- #
# Pricing
# --------------------------------------------------------------------------- #
class Pricing:
    """USD-per-1M-token rates keyed by provider, then model."""

    def __init__(self, data: Optional[dict] = None):
        self._providers: dict[str, dict[str, dict]] = (data or {}).get("providers", {})

    @classmethod
    def load(cls, path: Optional[Union[str, Path]] = None) -> "Pricing":
        path = Path(path) if path else DEFAULT_PRICING_PATH
        try:
            return cls(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as e:
            log.warning("Could not load pricing from %s (%s); every row will be unpriced.", path, e)
            return cls()

    def price_for(self, provider: str, model: str) -> Optional[dict]:
        return self._providers.get(provider or "", {}).get(model or "")

    def cost(self, provider: str, model: str, norm: dict[str, int]) -> Optional[float]:
        """USD cost, or None when any token class that was used has no confirmed rate."""
        if not any(norm.get(k, 0) for k in _RATE_KEYS):
            return 0.0
        price = self.price_for(provider, model)
        if price is None:
            return None
        total = 0.0
        for token_key, rate_key in _RATE_KEYS.items():
            tokens = norm.get(token_key, 0)
            if not tokens:
                continue
            rate = price.get(rate_key)
            if rate is None:
                return None
            total += tokens / 1e6 * float(rate)
        return total


# --------------------------------------------------------------------------- #
# Record + tracker
# --------------------------------------------------------------------------- #
@dataclass
class UsageRecord:
    ts: str
    run_id: str
    role: str
    provider: str
    model: str
    part: str = ""
    arm: str = ""
    gate: Optional[int] = None
    attempt: Optional[int] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: Optional[float] = None
    cache_hit: bool = False
    cost_usd: Optional[float] = None
    priced: bool = False
    ok: bool = True
    note: str = ""
    extra: dict = field(default_factory=dict)


# (active tracker, merged scope fields) for the current context.
_CTX: ContextVar[tuple[Optional["TokenTracker"], dict]] = ContextVar(
    "token_tracker_ctx", default=(None, {})
)


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]


class TokenTracker:
    """Appends one :class:`UsageRecord` per completion to a JSONL ledger."""

    def __init__(self, ledger_path: Union[str, Path], pricing: Optional[Pricing] = None,
                 run_id: Optional[str] = None):
        self.ledger_path = Path(ledger_path)
        self.pricing = pricing if pricing is not None else Pricing.load()
        self.run_id = run_id or _new_run_id()
        self.running_cost = 0.0   # priced rows only, this tracker's lifetime
        self.running_unpriced = 0

    @contextmanager
    def activate(self, **fields: Any) -> Iterator["TokenTracker"]:
        """Make this the current tracker; ``fields`` tag every row recorded inside."""
        token = _CTX.set((self, dict(fields)))
        try:
            yield self
        finally:
            _CTX.reset(token)

    def record(self, norm: dict[str, int], *, role: str, model: str, provider: str,
               latency_ms: Optional[float] = None, cache_hit: bool = False, ok: bool = True,
               note: str = "", **fields: Any) -> UsageRecord:
        """Price and append one completion. Scope fields apply when this tracker is active."""
        active, ctx = _CTX.get()
        merged = {**(ctx if active is self else {}), **fields}
        merged.pop("role", None)
        tokens = {k: int(norm.get(k, 0) or 0) for k in _RATE_KEYS}
        cost = 0.0 if cache_hit else self.pricing.cost(provider, model, tokens)
        rec = UsageRecord(
            ts=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            run_id=str(merged.pop("run_id", None) or self.run_id),
            role=role or "other",
            provider=provider or "",
            model=model or "",
            part=str(merged.pop("part", "") or ""),
            arm=str(merged.pop("arm", "") or ""),
            gate=merged.pop("gate", None),
            attempt=merged.pop("attempt", None),
            latency_ms=round(latency_ms, 1) if latency_ms is not None else None,
            cache_hit=cache_hit,
            cost_usd=round(cost, 6) if cost is not None else None,
            priced=cost is not None,
            ok=ok,
            note=note,
            extra=merged,
            **tokens,
        )
        self._append(rec)
        self._announce(rec)
        return rec

    def _announce(self, rec: UsageRecord) -> None:
        """One live console line per completion, with the running total."""
        if rec.priced:
            self.running_cost += rec.cost_usd or 0.0
        else:
            self.running_unpriced += 1
        if rec.cache_hit:
            log.info("[usage] %s %s: cache hit, $0", rec.role, rec.part or "-")
            return
        cost = f"${rec.cost_usd:.4f}" if rec.priced else "unpriced"
        total = f"${self.running_cost:.4f}" + (
            f" (+{self.running_unpriced} unpriced)" if self.running_unpriced else "")
        log.info("[usage] %s %s %s: in=%d out=%d cache_rd=%d -> %s | run total %s",
                 rec.role, rec.part or "-", rec.model, rec.input_tokens, rec.output_tokens,
                 rec.cache_read_tokens, cost, total)

    def _append(self, rec: UsageRecord) -> None:
        try:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with self.ledger_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(rec), default=str) + "\n")
        except OSError as e:
            log.warning("Token ledger write failed (%s): %s", self.ledger_path, e)


# --------------------------------------------------------------------------- #
# Context helpers (safe to call from any library code)
# --------------------------------------------------------------------------- #
def current_tracker() -> Optional[TokenTracker]:
    return _CTX.get()[0]


@contextmanager
def scope(**fields: Any) -> Iterator[None]:
    """Add/override tags (role, gate, attempt, part, arm, ...) for rows recorded inside."""
    tracker, ctx = _CTX.get()
    token = _CTX.set((tracker, {**ctx, **fields}))
    try:
        yield
    finally:
        _CTX.reset(token)


def record_completion(response: Any, *, model: str, provider: str, role: Optional[str] = None,
                      latency_ms: Optional[float] = None, ok: bool = True, note: str = "",
                      **fields: Any) -> Optional[UsageRecord]:
    """Record one model response against the active tracker (no-op if none)."""
    tracker, ctx = _CTX.get()
    if tracker is None:
        return None
    return tracker.record(normalize_usage(response), role=role or ctx.get("role") or "other",
                          model=model, provider=provider, latency_ms=latency_ms, ok=ok,
                          note=note, **fields)


def record_cache_hit(*, model: str, provider: str, role: Optional[str] = None,
                     note: str = "served from local extraction cache",
                     **fields: Any) -> Optional[UsageRecord]:
    """Record a call that was answered from a local cache (no tokens, $0)."""
    tracker, ctx = _CTX.get()
    if tracker is None:
        return None
    return tracker.record({}, role=role or ctx.get("role") or "other", model=model,
                          provider=provider, cache_hit=True, note=note, **fields)
