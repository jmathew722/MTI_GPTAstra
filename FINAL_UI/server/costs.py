"""Cost summary from the pipeline's normalized ledger (usage_ledger.jsonl).

Pure functions (no FastAPI, no pipeline import: the server runs ANY pipeline repo). The
ledger is the single source of truth; this module sums it with Decimal and labels pricing
honestly. It holds NO prices: an unpriced row (``cost_usd: null``) stays unpriced and the
scope says so, it never becomes ``0``.

The sum logic mirrors ``pipeline.token_tracker.cost_snapshot`` on purpose (test-covered on
both sides) so live telemetry and the Results table cannot disagree.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Optional

LEDGER_NAME = "usage_ledger.jsonl"
MAX_ROWS = 2000


def ledger_paths(out: Path) -> list[Path]:
    """Ledger files that can hold ``out``'s rows: its own, and the shared one beside the part folder."""
    out = Path(out)
    cands = [out / "usage" / LEDGER_NAME, out / LEDGER_NAME, out.parent / "usage" / LEDGER_NAME]
    seen, found = set(), []
    for c in cands:
        try:
            key = c.resolve()
        except OSError:
            continue
        if key not in seen and c.is_file():
            seen.add(key)
            found.append(c)
    return found


def read_rows(paths: Iterable[Path]) -> list[dict]:
    rows: list[dict] = []
    for p in paths:
        try:
            text = Path(p).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict):
                rows.append(r)
    return dedupe(rows)


def dedupe(rows: list[dict]) -> list[dict]:
    """Drop exact repeats by ``row_id``; legacy rows (no id) are kept as they are."""
    seen: set[str] = set()
    out = []
    for r in rows:
        rid = r.get("row_id")
        if rid:
            if rid in seen:
                continue
            seen.add(rid)
        out.append(r)
    return out


def _money(d: Decimal) -> str:
    return format(d.normalize(), "f")


def _dec(v) -> Optional[Decimal]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return Decimal(repr(v)) if isinstance(v, float) else Decimal(str(v))
    except Exception:
        return None


def _int(v) -> int:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def _totals(rows: list[dict]) -> dict:
    priced = [r for r in rows if r.get("priced") and _dec(r.get("cost_usd")) is not None]
    unpriced = len(rows) - len(priced)
    status = "priced" if not rows or not unpriced else ("partial" if priced else "unpriced")
    total = sum((_dec(r["cost_usd"]) for r in priced), Decimal(0))
    return {
        "cost_usd": None if status == "unpriced" else _money(total),
        "pricing_status": status,
        "api_calls": sum(1 for r in rows if not r.get("cache_hit")),
        "unpriced_calls": unpriced,
        "input_tokens": sum(_int(r.get("input_tokens")) for r in rows),
        "cached_input_tokens": sum(_int(r.get("cache_read_tokens")) for r in rows),
        "cache_write_tokens": sum(_int(r.get("cache_write_tokens")) for r in rows),
        "output_tokens": sum(_int(r.get("output_tokens")) for r in rows),
    }


def _row(r: dict) -> dict:
    cost = _dec(r.get("cost_usd")) if r.get("priced") else None
    return {
        "row_id": r.get("row_id") or None,
        "ts": str(r.get("ts") or "")[:40],
        "run_id": str(r.get("run_id") or "")[:80],
        "run_attempt": r.get("run_attempt") if isinstance(r.get("run_attempt"), int) else None,
        "stage": str(r.get("role") or "other")[:60],
        "role": str(r.get("role") or "other")[:60],
        "provider": str(r.get("provider") or "")[:60],
        "model": str(r.get("model") or "")[:160],
        "gate": r.get("gate") if isinstance(r.get("gate"), int) else None,
        "plan_attempt": r.get("attempt") if isinstance(r.get("attempt"), int) else None,
        "calls": 0 if r.get("cache_hit") else 1,
        "input_tokens": _int(r.get("input_tokens")),
        "cache_read_tokens": _int(r.get("cache_read_tokens")),
        "cache_write_tokens": _int(r.get("cache_write_tokens")),
        "output_tokens": _int(r.get("output_tokens")),
        "cost_usd": None if cost is None else _money(cost),
        "pricing_status": "priced" if cost is not None else "unpriced",
        "cache_hit": bool(r.get("cache_hit")),
        "ok": r.get("ok") is not False,
        "note": str(r.get("note") or "")[:200],
    }


def summarize(rows: list[dict], part: str, max_rows: int = MAX_ROWS) -> dict:
    """Run / part scopes plus per-attempt groups for ``part``. ``rows`` may hold other parts."""
    mine = [r for r in rows if r.get("part") == part]
    # attempt groups, in order of first appearance (ledger order is chronological)
    order: list[str] = []
    groups: dict[str, list[dict]] = {}
    for r in mine:
        key = str(r.get("run_id") or "")
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(r)
    latest = order[-1] if order else None
    keep_ids = {id(r) for r in mine[-max_rows:]}
    attempts = []
    for key in order:
        g = groups[key]
        att = next((r["run_attempt"] for r in g if isinstance(r.get("run_attempt"), int)), None)
        t = _totals(g)
        attempts.append({"run_id": key, "run_attempt": att, "label": "legacy" if att is None else f"attempt {att}",
                         "cost_usd": t["cost_usd"], "pricing_status": t["pricing_status"], "api_calls": t["api_calls"],
                         "rows": [_row(r) for r in g if id(r) in keep_ids]})
    return {
        "present": bool(mine),
        "scopes": {"run": {"run_id": latest, **_totals(groups[latest])} if latest else {"run_id": None, **_totals([])},
                   "part": _totals(mine)},
        "attempts": attempts,
        "total_rows": len(mine),
        "truncated": len(mine) > max_rows,
        "legacy_rows": sum(1 for r in mine if not r.get("row_id")),
        "pricing_source": "backend_price_table",
        "ledger_name": LEDGER_NAME,
    }
