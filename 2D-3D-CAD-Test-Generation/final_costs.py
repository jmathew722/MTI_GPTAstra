#!/usr/bin/env python
"""Rewrite FINAL_OUTPUTs/costs.txt from the usage + budget ledgers.

Every model completion is appended to <output>/usage/usage_ledger.jsonl by
pipeline.token_tracker, and every paid call is charged against the budget
ledger (~/.mti-2d-3d/budget_ledger.jsonl). This reads both and renders one
plain-text report: cost per part, cost per run, and the running total.

    python final_costs.py                     # scan FINAL_OUTPUTs + output/
    python final_costs.py --out <dir> ...     # extra output dirs to scan

Rows whose model has a null price in config/pricing.json are reported as
UNPRICED and listed separately -- a price is never guessed (CLAUDE.md).
Run it after each part; `make_part.py` already does that for you.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
FINAL = PROJECT / "FINAL_OUTPUTs"
REPORT = FINAL / "costs.txt"
BUDGET_LEDGER = Path.home() / ".mti-2d-3d" / "budget_ledger.jsonl"


def _prices() -> dict:
    """Unused placeholder kept so the signature of row_cost stays stable."""
    return {}


def row_cost(row: dict, _prices_unused: dict | None = None) -> float | None:
    """The ledger's own cost, else re-derived at the rate the budget guard charges.

    `pipeline.budget.budget_rates` is the single source of truth: a model with a
    real price in config/pricing.json is billed at it, and an unpriced one falls
    back to the highest listed rate for that model name (CLAUDE.md: the cap is
    deliberately conservative, and no price is ever invented). Using it here means
    costs.txt agrees with the budget ledger instead of guessing separately.

    Returns None only when no rate can be established at all.
    """
    v = row.get("cost_usd")
    if isinstance(v, (int, float)):
        return float(v)
    try:
        from pipeline import budget
        inp_rate, out_rate, _basis = budget.budget_rates(
            row.get("provider") or "", row.get("model") or "")
    except Exception:
        return None
    if inp_rate is None or out_rate is None:
        return None
    inp = int(row.get("input_tokens") or 0)
    out = int(row.get("output_tokens") or 0)
    return (inp * float(inp_rate) + out * float(out_rate)) / 1_000_000


def row_basis(row: dict) -> str:
    """"priced" or the budget guard's "unpriced: ..." explanation, for the report."""
    if isinstance(row.get("cost_usd"), (int, float)):
        return "priced (ledger)"
    try:
        from pipeline import budget
        return budget.budget_rates(row.get("provider") or "", row.get("model") or "")[2]
    except Exception:
        return "no rate"


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue          # a half-written final line is not fatal
    return rows


def usage_rows(out_dirs: list[Path]) -> list[dict]:
    rows: list[dict] = []
    seen: set[Path] = set()
    for d in out_dirs:
        if not d.is_dir():
            continue
        for led in d.rglob("usage_ledger.jsonl"):
            led = led.resolve()
            if led in seen:
                continue
            seen.add(led)
            rows.extend(read_jsonl(led))
    return rows


def budget_total() -> tuple[float, int]:
    rows = read_jsonl(BUDGET_LEDGER)
    total = 0.0
    for r in rows:
        for k in ("cost_usd", "amount_usd", "amount", "charge_usd"):
            v = r.get(k)
            if isinstance(v, (int, float)):
                total += float(v)
                break
    return total, len(rows)


def money(v: float) -> str:
    return f"${v:,.4f}"


def render(rows: list[dict], scanned: list[Path]) -> str:
    L: list[str] = []
    add = L.append
    now = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    add("=" * 78)
    add(" MTI 2D -> 3D PIPELINE : API COST LOG")
    add(f" updated {now}")
    add("=" * 78)
    add("")

    if not rows:
        add("No model calls recorded yet.")
        add("")
        add("Scanned for usage_ledger.jsonl in:")
        for d in scanned:
            add(f"  - {d}")
        add("")
        add("A ledger appears the first time a PAID run completes a model call.")
        return "\n".join(L) + "\n"

    prices = _prices()
    costs = {id(r): row_cost(r, prices) for r in rows}
    unpriced = [r for r in rows if costs[id(r)] is None]
    total = sum(c for c in costs.values() if c is not None)

    # ---- per part -------------------------------------------------------
    per_part: dict[str, dict] = defaultdict(
        lambda: {"calls": 0, "inp": 0, "out": 0, "cost": 0.0, "unpriced": 0}
    )
    for r in rows:
        p = per_part[r.get("part") or "(no part)"]
        p["calls"] += 1
        p["inp"] += int(r.get("input_tokens") or 0)
        p["out"] += int(r.get("output_tokens") or 0)
        c = costs[id(r)]
        if c is None:
            p["unpriced"] += 1
        else:
            p["cost"] += c

    add("COST PER PART")
    add("-" * 78)
    add(f"{'part':<22}{'calls':>6}{'in tok':>10}{'out tok':>10}{'cost':>14}  note")
    for name in sorted(per_part):
        v = per_part[name]
        note = f"{v['unpriced']} unpriced" if v["unpriced"] else ""
        shown = money(v["cost"]) if v["cost"] or not v["unpriced"] else "UNPRICED"
        add(f"{name:<22}{v['calls']:>6}{v['inp']:>10,}{v['out']:>10,}{shown:>14}  {note}")
    add("-" * 78)
    add(f"{'TOTAL':<22}{len(rows):>6}"
        f"{sum(p['inp'] for p in per_part.values()):>10,}"
        f"{sum(p['out'] for p in per_part.values()):>10,}"
        f"{money(total):>14}")
    add("")

    # ---- per run --------------------------------------------------------
    per_run: dict[str, dict] = defaultdict(
        lambda: {"calls": 0, "cost": 0.0, "parts": set(), "first": "", "last": ""}
    )
    for r in rows:
        v = per_run[r.get("run_id") or "(no run id)"]
        v["calls"] += 1
        c = costs[id(r)]
        if c is not None:
            v["cost"] += c
        if r.get("part"):
            v["parts"].add(r["part"])
        ts = r.get("ts") or ""
        v["first"] = min(v["first"] or ts, ts) if ts else v["first"]
        v["last"] = max(v["last"], ts) if ts else v["last"]

    add("COST PER RUN")
    add("-" * 78)
    add(f"{'run_id':<26}{'when':<21}{'calls':>6}{'parts':>7}{'cost':>14}")
    for rid in sorted(per_run, key=lambda k: per_run[k]["first"]):
        v = per_run[rid]
        when = (v["first"] or "")[:19].replace("T", " ")
        add(f"{rid:<26}{when:<21}{v['calls']:>6}{len(v['parts']):>7}{money(v['cost']):>14}")
    add("")

    # ---- budget ---------------------------------------------------------
    spent, charges = budget_total()
    add("BUDGET GUARD")
    add("-" * 78)
    add(f"  ledger          {BUDGET_LEDGER}")
    add(f"  charges logged  {charges}")
    add(f"  spent           {money(spent)}")
    add("")

    if unpriced:
        models = sorted({f"{r.get('provider')}/{r.get('model')}" for r in unpriced})
        add("NO RATE AVAILABLE")
        add("-" * 78)
        add(f"  {len(unpriced)} of {len(rows)} call(s) could not be priced at all:")
        for m in models:
            add(f"    - {m}")
        add("")

    # How each model in this report was rated, so the numbers are never mysterious.
    bases: dict[str, str] = {}
    for r in rows:
        bases.setdefault(f"{r.get('provider')}/{r.get('model')}", row_basis(r))
    add("HOW THESE COSTS WERE RATED")
    add("-" * 78)
    for m, b in sorted(bases.items()):
        add(f"  {m:<28} {b}")
    add("")
    add("  Rates come from pipeline.budget.budget_rates -- the same logic the $20")
    add("  budget guard charges against, so this file agrees with the budget ledger.")
    add("  An \"unpriced\" model is billed at the highest listed rate for that model")
    add("  name, which is deliberately conservative: the real cost is <= what's shown.")
    add("")

    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Rewrite FINAL_OUTPUTs/costs.txt from the ledgers.")
    ap.add_argument("--out", action="append", default=[],
                    help="extra output directory to scan (repeatable)")
    args = ap.parse_args()

    scan = [FINAL, HERE / "output"] + [Path(p) for p in args.out]
    rows = usage_rows(scan)
    FINAL.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render(rows, scan), encoding="utf-8")
    print(f"wrote {REPORT}  ({len(rows)} ledger row(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
