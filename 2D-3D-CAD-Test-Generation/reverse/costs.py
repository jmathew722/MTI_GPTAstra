"""API cost, token and runtime accounting for the 3D -> 2D drawing workflow (v8, SolidFlow_API_Cost.md).

* Actual usage is aggregated from the per-request ledger (``<job>/usage/usage_ledger.jsonl``) with Decimal arithmetic, de-duplicated by provider response id,
  attempts kept separate; a local cache hit is $0 with no call; a response that reported no usage is *unknown*, never free; a missing rate is *unavailable*, never $0.
* Rates come from ``config/pricing.json`` (versioned: effective date, source URL, tier). Nothing is hard-coded here.
* Estimates are labelled: history when comparable rows exist, otherwise a conservative fallback. They are ranges (low / expected / high).
* Runtime figures use durations measured on monotonic clocks (``state.begin_stage`` / ``end_stage``); queue time is separate; stages are never summed into elapsed.
"""
from __future__ import annotations

import json
import math
import statistics
import time
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Optional

from pipeline import token_tracker as tt

PROVIDER = "openai"
SCHEMA_VERSION = 1
MODEL_STAGES = ("extraction", "tiles", "validation", "correction")
GATE_STAGE = {"reference_layout": "extraction", "reference_tile": "tiles", "tiles": "tiles", "validation": "validation", "correction": "correction"}
MILLION = Decimal(1_000_000)

# ---- fallback estimation constants (used, and labelled, only when no comparable history exists)
FALLBACK_SYSTEM_TOKENS = 2400          # system prompt + tool schema
FALLBACK_TEXT_ITEM_TOKENS = 30         # one {id,text,box} JSON item
FALLBACK_TEXT_ITEMS = 150              # a typical scan / dense page when the page has not been read yet
FALLBACK_OUTPUT_TOKENS = 3500          # observed 2.1k - 5.1k on 8-30 annotation sheets
FALLBACK_STAGE_SECONDS = {"standard": (60.0, 120.0, 300.0), "match": (120.0, 240.0, 600.0)}
MAX_LONG_EDGE_PX = 2576


def dec(x) -> Optional[Decimal]:
    return None if x is None else Decimal(repr(x)) if isinstance(x, float) else Decimal(x)


def money(x: Optional[Decimal]) -> Optional[float]:
    """JSON-safe money: None stays None (unknown is never 0)."""
    return None if x is None else float(x)


# ------------------------------------------------------------------ rates

def resolve_alias(provider: str, model: str, data: Optional[dict] = None) -> str:
    return ((data or {}).get("model_aliases", {}).get(provider, {}) or {}).get(model, model)


def load_rate(model: str, provider: str = PROVIDER, pricing_path: Optional[Path] = None) -> Optional[dict]:
    """The configured per-million-token rate row, Decimal-valued, or None (unknown => cost unavailable)."""
    path = Path(pricing_path) if pricing_path else tt.DEFAULT_PRICING_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    model = resolve_alias(provider, model, data)
    row = (data.get("providers", {}).get(provider, {}) or {}).get(model)
    if not row or row.get("input") is None or row.get("output") is None:
        return None
    cached = row.get("cache_read")
    return {"provider": provider, "model": model, "input": dec(row["input"]), "output": dec(row["output"]), "cached": dec(cached) if cached is not None else None,
            "tier": row.get("tier", "standard"), "effective_date": row.get("effective_date"), "as_of": row.get("as_of"), "source": row.get("source"),
            "extra": dec(row.get("extra_charges_usd", 0) or 0), "version": str(row.get("as_of") or row.get("effective_date") or "unversioned")}


def request_cost(input_tokens: int, cached_tokens: int, output_tokens: int, rate: Optional[dict]) -> Optional[Decimal]:
    """uncached_input * in + cached * cached_rate + output * out (per million) + extra. Reasoning tokens are inside output_tokens: not added again."""
    if rate is None:
        return None
    if cached_tokens and rate.get("cached") is None:
        return None
    uncached = max(int(input_tokens) - int(cached_tokens), 0)
    total = (Decimal(uncached) * rate["input"] + Decimal(int(cached_tokens)) * (rate["cached"] or Decimal(0)) + Decimal(int(output_tokens)) * rate["output"]) / MILLION
    return total + (rate.get("extra") or Decimal(0))


# ------------------------------------------------------------------ actual usage

def _stage_of(row: dict) -> str:
    ex = row.get("extra") or {}
    st = ex.get("stage") or GATE_STAGE.get(str(row.get("gate") or ex.get("gate") or ""), None)
    return st or ("extraction" if row.get("role") == "extractor" else row.get("role") or "other")


def read_rows(ledger: Path) -> list[dict]:
    return tt.read_ledger_rows(ledger) if Path(ledger).is_file() else []


def aggregate(rows: Iterable[dict], *, part: Optional[str] = None, rate: Optional[dict] = None, model: str = "") -> dict:
    """Aggregate per-request rows into the contract's ``usage`` object.

    Costs are recomputed from the recorded token classes with the configured rate (so a rate change re-prices history); a row recorded with a different
    model is priced by its own model. ``rate`` is only the default for rows without a model."""
    seen: set = set()
    stages: dict[str, dict] = {}
    attempts: list[dict] = []
    calls = hits = unpriced = unknown = 0
    tot_in = tot_cached = tot_out = 0
    total = Decimal(0)
    any_unknown_cost = False
    any_priced = False
    models: set = set()
    versions: set = set()
    hist = Decimal(0)
    for r in rows:
        if part is not None and r.get("part") != part:
            continue
        ex = r.get("extra") or {}
        key = ex.get("response_id") or r.get("row_id")
        if key:
            if key in seen:
                continue
            seen.add(key)
        st = _stage_of(r)
        s = stages.setdefault(st, {"calls": 0, "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0, "_cost": Decimal(0), "_unknown": False, "attempts": 0})
        if r.get("cache_hit"):
            hits += 1
            attempts.append({"stage": st, "attempt": r.get("attempt"), "response_id": None, "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
                             "ok": True, "cache_hit": True})
            continue
        calls += 1
        s["calls"] += 1
        s["attempts"] += 1
        cached = int(r.get("cache_read_tokens") or 0)
        inp = int(r.get("input_tokens") or 0) + cached              # tracker stores UNCACHED input; provider total = uncached + cached
        out = int(r.get("output_tokens") or 0)
        s["input_tokens"] += inp
        s["cached_tokens"] += cached
        s["output_tokens"] += out
        tot_in += inp
        tot_cached += cached
        tot_out += out
        if r.get("model"):
            models.add(r["model"])
        rt = load_rate(r.get("model") or model, r.get("provider") or PROVIDER) if (r.get("model") or model) else rate
        cost: Optional[Decimal]
        if ex.get("usage_missing"):
            cost = None
            unknown += 1
        else:
            cost = request_cost(inp, cached, out, rt)
        if cost is None:
            any_unknown_cost = True
            s["_unknown"] = True
            unpriced += 0 if ex.get("usage_missing") else 1
        else:
            any_priced = True
            s["_cost"] += cost
            total += cost
            versions.add(rt["version"] if rt else "")
        attempts.append({"stage": st, "attempt": r.get("attempt"), "response_id": ex.get("response_id"), "input_tokens": inp, "cached_tokens": cached, "output_tokens": out,
                         "cost_usd": money(cost), "ok": bool(r.get("ok", True)), "cache_hit": False})
    by_stage = {}
    for st, s in stages.items():
        by_stage[st] = {"calls": s["calls"], "input_tokens": s["input_tokens"], "cached_tokens": s["cached_tokens"], "output_tokens": s["output_tokens"],
                        "cost_usd": None if s["_unknown"] else float(s["_cost"]), "attempts": s["attempts"]}
    if calls == 0:
        status, cost_usd = "none", 0.0                       # no model call was made: $0 is a fact here, not an unknown
    elif any_unknown_cost and any_priced:
        status, cost_usd = "partial", float(total)
    elif any_unknown_cost:
        status, cost_usd = "unpriced", None
    else:
        status, cost_usd = "priced", float(total)
    rt0 = rate or (load_rate(next(iter(models))) if models else None)
    return {"calls": calls, "cache_hits": hits, "unpriced_calls": unpriced, "unknown_usage_calls": unknown, "input_tokens": tot_in, "cached_tokens": tot_cached,
            "output_tokens": tot_out, "cost_usd": cost_usd, "cost_status": status, "currency": "USD", "model": next(iter(models)) if len(models) == 1 else (model or None),
            "rate_version": (sorted(versions)[0] if len(versions) == 1 else (rt0["version"] if rt0 else None)), "by_stage": by_stage, "attempts": attempts,
            "historical_usd": None}


def merge_usage(usages: list[dict]) -> dict:
    """Job-level usage = the parts' usage merged (money summed with Decimal; any unknown part makes the total partial/unpriced)."""
    if not usages:
        return aggregate([])
    out = aggregate([])
    total = Decimal(0)
    statuses = []
    for u in usages:
        for k in ("calls", "cache_hits", "unpriced_calls", "unknown_usage_calls", "input_tokens", "cached_tokens", "output_tokens"):
            out[k] += u.get(k, 0)
        if u.get("cost_usd") is not None:
            total += dec(u["cost_usd"])
        statuses.append(u.get("cost_status"))
        for st, s in (u.get("by_stage") or {}).items():
            d = out["by_stage"].setdefault(st, {"calls": 0, "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "attempts": 0})
            for k in ("calls", "input_tokens", "cached_tokens", "output_tokens", "attempts"):
                d[k] += s.get(k, 0)
            d["cost_usd"] = None if (d["cost_usd"] is None or s.get("cost_usd") is None) else float(dec(d["cost_usd"]) + dec(s["cost_usd"]))
        out["attempts"] += u.get("attempts", [])
        out["model"] = out["model"] or u.get("model")
        out["rate_version"] = out["rate_version"] or u.get("rate_version")
    real = [s for s in statuses if s != "none"]
    if not real:
        out["cost_status"], out["cost_usd"] = "none", 0.0
    elif all(s == "priced" for s in real):
        out["cost_status"], out["cost_usd"] = "priced", float(total)
    elif any(s in ("priced", "partial") for s in real):
        out["cost_status"], out["cost_usd"] = "partial", float(total)
    else:
        out["cost_status"], out["cost_usd"] = "unpriced", None
    return out


# ------------------------------------------------------------------ history (tokens and durations)

def history_rows(job_dirs: Iterable[Path]) -> list[dict]:
    rows: list[dict] = []
    for d in job_dirs:
        rows += read_rows(Path(d) / "usage" / "usage_ledger.jsonl")
    return rows


def _median(xs: list[float]) -> Optional[float]:
    return statistics.median(xs) if xs else None


def token_history(rows: list[dict], stage: str = "extraction") -> Optional[dict]:
    calls = [r for r in rows if not r.get("cache_hit") and _stage_of(r) == stage and (r.get("input_tokens") or r.get("cache_read_tokens")) and not (r.get("extra") or {}).get("usage_missing")]
    if len(calls) < 3:
        return None
    ins = sorted(int(r.get("input_tokens") or 0) + int(r.get("cache_read_tokens") or 0) for r in calls)
    outs = sorted(int(r.get("output_tokens") or 0) for r in calls)
    q = lambda xs, f: xs[min(len(xs) - 1, int(f * (len(xs) - 1)))]
    return {"n": len(calls), "input": (q(ins, 0.1), _median(ins), q(ins, 0.9)), "output": (q(outs, 0.1), _median(outs), q(outs, 0.9))}


def image_tokens(width_px: int, height_px: int) -> int:
    """Documented high-detail tile rule: fit in 2048^2, shortest side to 768, 85 base + 170 per 512 px tile. An estimate for the configured model, labelled as such."""
    w, h = float(width_px), float(height_px)
    f = min(1.0, 2048.0 / max(w, h))
    w, h = w * f, h * f
    g = 768.0 / min(w, h)
    if g < 1.0:
        w, h = w * g, h * g
    return 85 + 170 * math.ceil(w / 512) * math.ceil(h / 512)


def page_facts(pdf: Path, max_pages: int = 20) -> dict:
    """Cheap page facts for an estimate: page sizes, rendered pixel sizes (long edge capped), text-layer item count (0 for scans). No model call, no OCR."""
    import fitz
    pages = []
    with fitz.open(str(pdf)) as d:
        for i, pg in enumerate(d):
            if i >= max_pages:
                break
            r = pg.rect
            long_px = min(MAX_LONG_EDGE_PX, max(r.width, r.height) * 300 / 72)
            f = long_px / max(r.width, r.height)
            n_text = sum(1 for b in pg.get_text("blocks") if b[4].strip()) if pg.get_text("text").strip() else 0
            pages.append({"width_pt": r.width, "height_pt": r.height, "px": (int(r.width * f), int(r.height * f)), "text_blocks": n_text, "scanned": n_text < 8, "images": len(pg.get_images())})
        n = d.page_count
    return {"pages": pages, "page_count": n}


# ------------------------------------------------------------------ estimates

def _range(lo, ex, hi) -> dict:
    return {"low": lo, "expected": ex, "high": hi}


def estimate_extraction(facts: Optional[dict], rate: Optional[dict], *, cache: str, hist: Optional[dict], tiles_per_page: int = 0) -> dict:
    """One extraction stage (all pages). cache == 'hit': zero calls. Scenarios: low = history p10 / one clean call, expected = median, high = p90 + one schema repair."""
    labels: list[str] = []
    pages = (facts or {}).get("pages") or []
    n_pages = len(pages) or 1
    if cache == "hit":
        return {"calls": _range(0, 0, 0), "tokens": {"input": _range(0, 0, 0), "output": _range(0, 0, 0)}, "cost": _range(0.0, 0.0, 0.0), "labels": [],
                "assumption": "extraction reused from cache (hash + schema version + completeness match): no model call"}
    in_lo = in_ex = in_hi = 0
    out_lo = out_ex = out_hi = 0
    for i in range(n_pages):
        pg = pages[i] if i < len(pages) else None
        img = image_tokens(*pg["px"]) if pg else image_tokens(2576, 1980)
        items = (pg["text_blocks"] * 3 if pg and not pg["scanned"] else FALLBACK_TEXT_ITEMS)
        if pg is None or pg["scanned"]:
            labels.append("fallback_text_items")
        base = FALLBACK_SYSTEM_TOKENS + img + items * FALLBACK_TEXT_ITEM_TOKENS
        if hist:
            labels_h = None
            in_lo += int(hist["input"][0] * 0.85); in_ex += int(hist["input"][1]); in_hi += int(hist["input"][2] * 1.15)
            out_lo += int(hist["output"][0]); out_ex += int(hist["output"][1]); out_hi += int(hist["output"][2])
        else:
            labels.append("fallback_tokens")
            in_lo += int(base * 0.8); in_ex += base; in_hi += int(base * 1.4)
            out_lo += int(FALLBACK_OUTPUT_TOKENS * 0.5); out_ex += FALLBACK_OUTPUT_TOKENS; out_hi += int(FALLBACK_OUTPUT_TOKENS * 1.8)
        # tiles: each tile is a full image call in addition
        if tiles_per_page:
            t_in = tiles_per_page * (FALLBACK_SYSTEM_TOKENS + image_tokens(1024, 1024) + 40 * FALLBACK_TEXT_ITEM_TOKENS)
            t_out = tiles_per_page * 900
            in_lo += t_in; in_ex += t_in; in_hi += int(t_in * 1.2)
            out_lo += t_out // 2; out_ex += t_out; out_hi += t_out * 2
    calls_lo, calls_ex, calls_hi = n_pages + n_pages * tiles_per_page, n_pages + n_pages * tiles_per_page, 2 * (n_pages + n_pages * tiles_per_page)   # high: every call repaired once
    in_hi_total = in_hi * 2                  # a repair resends the conversation
    out_hi_total = out_hi * 2
    res = {"calls": _range(calls_lo, calls_ex, calls_hi), "tokens": {"input": _range(in_lo, in_ex, in_hi_total), "output": _range(out_lo, out_ex, out_hi_total)}, "labels": sorted(set(labels))}
    res["cost"] = {k: money(request_cost(res["tokens"]["input"][k], 0, res["tokens"]["output"][k], rate)) for k in ("low", "expected", "high")}
    res["assumption"] = (f"{n_pages} page(s)" + (f", {tiles_per_page} tile(s) per page" if tiles_per_page else ", no tiling") + "; " +
                         (f"tokens from {hist['n']} comparable past calls" if hist else "tokens from a conservative fallback (no comparable history)"))
    return res


def duration_history(jobs: Iterable, mode: str) -> Optional[dict]:
    secs = []
    for j in jobs:
        for p in j.parts:
            if not p.seconds or p.state not in ("completed", "review_required"):
                continue
            m = (p.reference or {}).get("mode", "standard")
            if m == mode:
                secs.append(float(p.seconds))
    if len(secs) < 3:
        return None
    secs.sort()
    q = lambda f: secs[min(len(secs) - 1, int(f * (len(secs) - 1)))]
    return {"n": len(secs), "low": q(0.1), "expected": statistics.median(secs), "high": q(0.9)}


def estimate_part(*, mode: str, facts: Optional[dict], rate: Optional[dict], cache: str, token_hist: Optional[dict], dur_hist: Optional[dict], tiles_per_page: int = 0,
                  pages_for_time: int = 1) -> dict:
    """The contract's ``<Estimate>`` for one part."""
    labels: list[str] = []
    if mode == "match":
        ex = estimate_extraction(facts, rate, cache=cache, hist=token_hist, tiles_per_page=tiles_per_page)
        labels += ex["labels"]
    else:
        zero = _range(0, 0, 0)
        ex = {"calls": zero, "tokens": {"input": zero, "output": zero}, "cost": _range(0.0, 0.0, 0.0), "labels": [],
              "assumption": "standard mode makes no model call"}
    unavailable = None
    if mode == "match" and rate is None and cache != "hit":
        unavailable = "no confirmed rate for the configured model in config/pricing.json"
        ex["cost"] = {"low": None, "expected": None, "high": None}
    lo, exs, hi = (dur_hist["low"], dur_hist["expected"], dur_hist["high"]) if dur_hist else FALLBACK_STAGE_SECONDS[mode]
    if not dur_hist:
        labels.append("fallback_duration")
    if mode == "match" and not dur_hist and pages_for_time > 1:
        lo, exs, hi = lo * pages_for_time, exs * pages_for_time, hi * pages_for_time
    if mode == "match" and cache != "hit":
        # local OCR + model round trip are in the history when present; the fallback adds them explicitly
        if not dur_hist:
            lo, exs, hi = lo + 10, exs + 25, hi + 90
    local = exs
    stage_cost = {"extraction": {"cost": ex["cost"], "tokens": ex["tokens"], "calls": ex["calls"]},
                  "tiles": {"cost": _range(0.0, 0.0, 0.0) if not tiles_per_page else ex["cost"], "tokens": {"input": _range(0, 0, 0), "output": _range(0, 0, 0)}, "calls": _range(0, 0, 0)},
                  "validation": {"cost": _range(0.0, 0.0, 0.0), "tokens": {"input": _range(0, 0, 0), "output": _range(0, 0, 0)}, "calls": _range(0, 0, 0),
                                 "note": "deterministic text/geometry comparison first; no model call is planned"},
                  "correction": {"cost": _range(0.0, 0.0, 0.0), "tokens": {"input": _range(0, 0, 0), "output": _range(0, 0, 0)}, "calls": _range(0, 0, 0),
                                 "note": "bounded local correction iterations (default 3); no model call is planned"},
                  "local_generation": {"cost": _range(0.0, 0.0, 0.0), "duration_s": _range(lo, exs, hi), "note": "SolidWorks COM and PDF processing incur no OpenAI charge"}}
    return {"duration": {"low_s": round(lo, 1), "expected_s": round(exs, 1), "high_s": round(hi, 1), "source": "history" if dur_hist else "fallback",
                         "basis": (f"10th/median/90th percentile of {dur_hist['n']} completed {mode} parts" if dur_hist else f"fallback for {mode} mode (no comparable completed parts yet)")},
            "cost": {**ex["cost"], "currency": "USD", "rate_version": rate["version"] if rate else None, "model": rate["model"] if rate else None, "unavailable_reason": unavailable},
            "tokens": {"input": ex["tokens"]["input"], "output": ex["tokens"]["output"], "cached_input": 0},
            "by_stage": stage_cost, "assumptions": [ex["assumption"], "rates: " + (f"{rate['model']} ${rate['input']}/M in, ${rate['cached'] if rate['cached'] is not None else 'n/a'}/M cached, ${rate['output']}/M out (as of {rate['as_of']}, {rate['tier']} tier)" if rate else "unavailable")],
            "labels": sorted(set(labels))}


def sum_estimates(ests: list[dict]) -> Optional[dict]:
    ests = [e for e in ests if e]
    if not ests:
        return None
    out = json.loads(json.dumps(ests[0]))
    for e in ests[1:]:
        for k, f in (("low_s", "low_s"), ("expected_s", "expected_s"), ("high_s", "high_s")):
            out["duration"][k] = round(out["duration"][k] + e["duration"][k], 1)
        for k in ("low", "expected", "high"):
            a, b = out["cost"][k], e["cost"][k]
            out["cost"][k] = None if (a is None or b is None) else float(dec(a) + dec(b))
            for side in ("input", "output"):
                out["tokens"][side][k] += e["tokens"][side][k]
        if e["duration"]["source"] == "fallback":
            out["duration"]["source"] = "fallback"
        out["labels"] = sorted(set(out["labels"]) | set(e["labels"]))
        out["assumptions"] += [a for a in e["assumptions"] if a not in out["assumptions"]]
        if e["cost"].get("unavailable_reason") and not out["cost"].get("unavailable_reason"):
            out["cost"]["unavailable_reason"] = e["cost"]["unavailable_reason"]
        for st, d in e["by_stage"].items():
            o = out["by_stage"].setdefault(st, d)
            if o is d:
                continue
            for k in ("low", "expected", "high"):
                a, b = o["cost"][k], d["cost"][k]
                o["cost"][k] = None if (a is None or b is None) else float(dec(a) + dec(b))
    return out


# ------------------------------------------------------------------ runtime / timing

def timing_for(job, part, now_wall: Optional[float] = None, estimate: Optional[dict] = None) -> dict:
    """Queue time, wall elapsed and per-stage durations persisted by the state machine (monotonic). ``remaining_s`` is given only when an estimate exists."""
    from datetime import datetime
    def ts(s):
        try:
            return datetime.fromisoformat(s).timestamp()
        except (TypeError, ValueError):
            return None
    created, started, ended = ts(job.created), ts(part.started), ts(part.ended)
    now = now_wall if now_wall is not None else time.time()
    queued = max(0.0, started - created) if (created and started) else (max(0.0, now - created) if created and part.state == "queued" else None)
    running = part.state not in ("queued",) and part.state not in ("completed", "review_required", "failed", "canceled")
    if part.seconds is not None and not running:
        elapsed = float(part.seconds)
    elif started:
        elapsed = max(0.0, (ended or now) - started)
    else:
        elapsed = None
    by_stage = {k: v.get("seconds") for k, v in (part.stages or {}).items() if v.get("seconds") is not None}
    for k, v in (part.stages or {}).items():
        if v.get("status") == "running" and v.get("t0") is not None:
            by_stage[k] = round(max(0.0, time.monotonic() - v["t0"]), 2) if v["t0"] < time.monotonic() else None
    remaining = None
    if estimate and running and elapsed is not None:
        d = estimate["duration"]
        remaining = {"low": max(0.0, round(d["low_s"] - elapsed, 1)), "expected": max(0.0, round(d["expected_s"] - elapsed, 1)), "high": max(0.0, round(d["high_s"] - elapsed, 1)),
                     "source": d["source"]}
    return {"queued_s": None if queued is None else round(queued, 1), "elapsed_s": None if elapsed is None else round(elapsed, 1), "running": bool(running),
            "by_stage": by_stage, "remaining_s": remaining}


def merge_timing(timings: list[dict]) -> dict:
    """Job level: parts are serialized on one SolidWorks session, but the job's elapsed is the span, not a sum, when starts are known."""
    qs = [t["queued_s"] for t in timings if t.get("queued_s") is not None]
    out = {"queued_s": min(qs) if qs else None, "elapsed_s": None, "running": any(t.get("running") for t in timings), "by_stage": {}, "remaining_s": None}
    es = [t["elapsed_s"] for t in timings if t.get("elapsed_s") is not None]
    if es:
        out["elapsed_s"] = round(sum(es), 1)        # serialized queue: parts do not overlap, so elapsed work time adds up
    for t in timings:
        for k, v in (t.get("by_stage") or {}).items():
            if v is not None:
                out["by_stage"][k] = round(out["by_stage"].get(k, 0.0) + v, 2)
    rem = [t["remaining_s"] for t in timings if t.get("remaining_s")]
    if rem:
        out["remaining_s"] = {k: round(sum(r[k] for r in rem), 1) for k in ("low", "expected", "high")}
        out["remaining_s"]["source"] = "fallback" if any(r["source"] == "fallback" for r in rem) else "history"
    return out


def estimate_vs_actual(estimate: Optional[dict], usage: dict, timing: dict) -> dict:
    out = {"cost_usd": None, "duration_s": None}
    if estimate and usage and usage.get("cost_usd") is not None and estimate["cost"].get("expected") is not None and usage.get("cost_status") in ("priced", "none"):
        c = estimate["cost"]
        out["cost_usd"] = {"expected": c["expected"], "actual": usage["cost_usd"], "within_range": c["low"] <= usage["cost_usd"] <= c["high"]}
    if estimate and timing and timing.get("elapsed_s") is not None and not timing.get("running"):
        d = estimate["duration"]
        out["duration_s"] = {"expected": d["expected_s"], "actual": timing["elapsed_s"], "within_range": d["low_s"] <= timing["elapsed_s"] <= d["high_s"]}
    return out
