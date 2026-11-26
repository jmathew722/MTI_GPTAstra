"""Run time and cost estimates for the Run Pipeline area (one backend source of truth).

Pure functions, no FastAPI. Nothing here is a hard-coded price or duration: both ranges come from
runs that already finished on this machine.

* Time: seconds between ``run.started`` and the matching ``run.completed`` in each part's
  ``run_events.jsonl`` (failed and cancelled attempts are not used: they do not predict a good run).
* Cost: the sum of ``cost_usd`` for the same run in the pipeline's ``usage_ledger.jsonl``. A run with
  ANY unpriced row is left out of the cost history, so an unpriced model yields "unavailable", never
  a low or $0 figure. Rows are never repriced here.
* Batches run one part at a time (SolidWorks automation is serialized), so a batch is the SUM of its
  parts. Nothing is divided by a concurrency factor.

Units: seconds (float) and USD as a string with 6 decimals (Decimal arithmetic, JSON-safe).
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Optional

SERIALIZED_REASON = "SolidWorks automation runs one part at a time, so a batch is the sum of its parts."
MIN_FOR_RANGE = 3          # with fewer finished runs the range is min..max and flagged as limited history
_Q = Decimal("0.000001")


def _parse_ts(s: str) -> Optional[float]:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def _jsonl(path: Path) -> Iterable[dict]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for line in text.splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict):
            yield r


def run_durations(final_dir: Path) -> list[dict]:
    """[{part, run_id, attempt, seconds}] for every completed run found under ``final_dir``."""
    out: list[dict] = []
    if not Path(final_dir).is_dir():
        return out
    for ev_path in sorted(Path(final_dir).glob("*/run_events.jsonl")):
        started: dict[tuple, float] = {}
        for e in _jsonl(ev_path):
            key = (e.get("run_id"), e.get("attempt"))
            t = _parse_ts(e.get("occurred_at"))
            if t is None:
                continue
            kind = e.get("kind")
            if kind == "run.started":
                started[key] = t
            elif kind == "run.completed" and key in started and t >= started[key]:
                out.append({"part": e.get("part_id") or ev_path.parent.name, "run_id": key[0], "attempt": key[1],
                            "seconds": t - started[key]})
                started.pop(key, None)
            elif kind in ("run.failed", "run.cancelled"):
                started.pop(key, None)
    return out


def run_costs(ledger_rows: Iterable[dict]) -> dict[tuple, Decimal]:
    """{(run_id, attempt): USD} for runs whose every ledger row is priced."""
    sums: dict[tuple, Decimal] = {}
    bad: set[tuple] = set()
    for r in ledger_rows:
        key = (r.get("run_id"), r.get("run_attempt"))
        c = r.get("cost_usd")
        if c is None or not r.get("priced", True):
            bad.add(key)
            continue
        try:
            sums[key] = sums.get(key, Decimal(0)) + Decimal(str(c))
        except Exception:
            bad.add(key)
    return {k: v for k, v in sums.items() if k not in bad}


def _quantile(sorted_vals: list, q: float):
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    if isinstance(sorted_vals[lo], Decimal):
        frac = Decimal(str(frac))
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def band(samples: list) -> Optional[dict]:
    """{low, high, n, limited} for one input, or None with no history. 25th..75th percentile with
    enough runs, min..max with fewer (flagged limited)."""
    vals = sorted(samples)
    if not vals:
        return None
    if len(vals) >= MIN_FOR_RANGE:
        lo, hi = _quantile(vals, 0.25), _quantile(vals, 0.75)
        limited = False
    else:
        lo, hi, limited = vals[0], vals[-1], True
    return {"low": lo, "high": hi, "n": len(vals), "limited": limited}


def _money(d: Decimal) -> str:
    return str(d.quantize(_Q))


def estimate(n_inputs: int, durations: list[float], costs: list[Decimal]) -> dict:
    """Totals for ``n_inputs`` parts run one after another. Unknown stays unknown (``available`` false)."""
    n = max(0, int(n_inputs))
    tb, cb = band(durations), band(costs)
    time = {"available": bool(tb and n), "unit": "seconds"}
    if tb and n:
        time.update(low=round(tb["low"] * n, 1), high=round(tb["high"] * n, 1), per_input_low=round(tb["low"], 1),
                    per_input_high=round(tb["high"], 1), n_runs=tb["n"], limited=tb["limited"])
    else:
        time["reason"] = "No finished runs to estimate from yet." if not tb else "No inputs selected."
    cost = {"available": bool(cb and n), "unit": "USD"}
    if cb and n:
        cost.update(low=_money(cb["low"] * n), high=_money(cb["high"] * n), per_input_low=_money(cb["low"]),
                    per_input_high=_money(cb["high"]), n_runs=cb["n"], limited=cb["limited"])
    else:
        cost["reason"] = ("No priced runs to estimate from yet (cost is unavailable, not zero)."
                          if not cb else "No inputs selected.")
    return {"inputs": n, "time": time, "cost": cost, "concurrency": 1, "serialized_reason": SERIALIZED_REASON}


def build(final_dir: Path, ledger_rows: Iterable[dict], n_inputs: int) -> dict:
    """Estimate from what is on disk now."""
    durs = run_durations(final_dir)
    priced = run_costs(ledger_rows)
    cost_vals = []
    seen = set()
    for d in durs:
        k = (d["run_id"], d["attempt"])
        if k in priced and k not in seen:
            seen.add(k)
            cost_vals.append(priced[k])
    return estimate(n_inputs, [d["seconds"] for d in durs], cost_vals)


# MuPDF is not thread-safe: FastAPI runs sync endpoints on a thread pool, and the browser asks for many previews and page counts at once.
# Two threads inside MuPDF (especially on a malformed PDF) can crash the whole server process, so every PyMuPDF call in the server holds this lock.
FITZ_LOCK = threading.RLock()


def pdf_pages(path: Path) -> tuple[Optional[int], Optional[str]]:
    """(page count, error). A corrupt or encrypted PDF gives (None, reason)."""
    try:
        import fitz  # PyMuPDF
    except Exception:
        return None, "PyMuPDF is not installed, so the page count is unknown."
    try:
        with FITZ_LOCK, fitz.open(str(path)) as doc:
            if doc.needs_pass:
                return None, "The PDF is password protected."
            if doc.page_count < 1:
                return None, "The PDF has no pages."
            return doc.page_count, None
    except Exception:  # noqa: BLE001 - any parser failure is an unreadable PDF; the raw error can name server paths, so it is not echoed
        return None, "The PDF could not be read. It looks corrupt or truncated: re-export it from the source and try again."


def last_run(part_dir: Path, ledger_rows: Iterable[dict]) -> Optional[dict]:
    """The most recent run of a part: {run_id, attempt, state, started_at, finished_at, seconds, cost_usd, cost_status}.
    ``seconds`` and ``cost_usd`` are None when unknown (never 0). A run still going has no finished_at."""
    ev = Path(part_dir) / "run_events.jsonl"
    if not ev.is_file():
        return None
    runs: dict[tuple, dict] = {}
    order: list[tuple] = []
    for e in _jsonl(ev):
        key = (e.get("run_id"), e.get("attempt"))
        t = _parse_ts(e.get("occurred_at"))
        if t is None or e.get("kind") not in ("run.started", "run.completed", "run.failed", "run.cancelled"):
            continue
        if key not in runs:
            runs[key] = {"run_id": key[0], "attempt": key[1], "state": "running", "started": None, "finished": None}
            order.append(key)
        r = runs[key]
        if e["kind"] == "run.started":
            r["started"] = t
        else:
            r["finished"] = t
            r["state"] = {"run.completed": "succeeded", "run.failed": "failed", "run.cancelled": "cancelled"}[e["kind"]]
    order = [k for k in order if runs[k]["started"] is not None]
    if not order:
        return None
    r = runs[max(order, key=lambda k: runs[k]["started"])]
    rows = [x for x in ledger_rows if x.get("run_id") == r["run_id"] and x.get("run_attempt") in (None, r["attempt"])]
    unpriced = any(x.get("cost_usd") is None for x in rows)
    cost = None
    if rows and not unpriced:
        cost = _money(sum((Decimal(str(x["cost_usd"])) for x in rows), Decimal(0)))
    iso = lambda t: datetime.fromtimestamp(t, tz=__import__("datetime").timezone.utc).isoformat(timespec="seconds") if t else None
    return {"run_id": r["run_id"], "attempt": r["attempt"], "state": r["state"], "started_at": iso(r["started"]),
            "finished_at": iso(r["finished"]),
            "seconds": round(r["finished"] - r["started"], 1) if r["finished"] else None,
            "cost_usd": cost, "cost_status": "priced" if cost is not None else ("unpriced" if rows else "none"),
            "api_calls": len(rows)}
