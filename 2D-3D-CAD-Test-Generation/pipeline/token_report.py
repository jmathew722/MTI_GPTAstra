"""Token and cost report over the per-completion ledger.

Reads every ``usage_ledger.jsonl`` written by :mod:`pipeline.token_tracker` and
answers "what does a run cost?": totals, cost per converted part, cost by role
(extractor / planner / auditor_reviewer / jev), by model and provider, by benchmark
arm, and the cost of retries (gate x attempt).

    python -m pipeline.token_report ./output
    python -m pipeline.token_report ./output --html output/usage/usage_report.html --csv output/usage/usage.csv
    python -m pipeline.token_report ./output --role planner --since 2026-10-01 --reprice

``--reprice`` recomputes every row from the current ``config/pricing.json`` (use it
after filling in a price that was unknown at run time). The HTML dashboard is a
single self-contained file: inline CSS/SVG/JS, no network requests.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence, Union

from pipeline.token_tracker import LEDGER_NAME, Pricing

TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
CSV_FIELDS = (
    "ts", "run_id", "part", "arm", "role", "gate", "attempt", "provider", "model",
    *TOKEN_KEYS, "latency_ms", "cache_hit", "cost_usd", "priced", "ok", "note", "extra",
)


# --------------------------------------------------------------------------- #
# Loading, filtering, re-pricing
# --------------------------------------------------------------------------- #
def load_rows(paths: Iterable[Union[str, Path]]) -> list[dict]:
    """Rows from ledger files, or from every ``usage_ledger.jsonl`` under a directory."""
    rows: list[dict] = []
    for p in paths:
        p = Path(p)
        files = sorted(p.rglob(LEDGER_NAME)) if p.is_dir() else [p] if p.exists() else []
        for f in files:
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def filter_rows(rows: Sequence[dict], part: Optional[str] = None, arm: Optional[str] = None,
                role: Optional[str] = None, since: Optional[str] = None) -> list[dict]:
    """Keep rows matching every given filter (``since`` = ISO date, inclusive)."""
    out = []
    for r in rows:
        if part and r.get("part") != part:
            continue
        if arm and r.get("arm") != arm:
            continue
        if role and r.get("role") != role:
            continue
        if since and str(r.get("ts", ""))[:10] < since:
            continue
        out.append(r)
    return out


def reprice(rows: Sequence[dict], pricing: Pricing) -> list[dict]:
    """Copies of ``rows`` with cost recomputed from ``pricing`` (cache hits stay $0)."""
    out = []
    for r in rows:
        r = dict(r)
        norm = {k: int(r.get(k) or 0) for k in TOKEN_KEYS}
        cost = 0.0 if r.get("cache_hit") else pricing.cost(r.get("provider", ""), r.get("model", ""), norm)
        r["cost_usd"] = round(cost, 6) if cost is not None else None
        r["priced"] = cost is not None
        out.append(r)
    return out


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #
def _tokens(r: dict) -> int:
    return sum(int(r.get(k) or 0) for k in TOKEN_KEYS)


def aggregate(rows: Sequence[dict], keys: tuple[str, ...]) -> list[dict]:
    """Group by ``keys``; sum tokens and PRICED cost, count unpriced rows; sort by cost."""
    groups: dict[tuple, dict] = {}
    latencies: dict[tuple, list[float]] = defaultdict(list)
    for r in rows:
        k = tuple(r.get(key) for key in keys)
        g = groups.setdefault(k, {**dict(zip(keys, k)), "completions": 0, "cost_usd": 0.0,
                                  "unpriced": 0, "cache_hits": 0, "total_tokens": 0,
                                  **{t: 0 for t in TOKEN_KEYS}})
        g["completions"] += 1
        for t in TOKEN_KEYS:
            g[t] += int(r.get(t) or 0)
        g["total_tokens"] += _tokens(r)
        if r.get("cache_hit"):
            g["cache_hits"] += 1
        if r.get("cost_usd") is None:
            g["unpriced"] += 1
        else:
            g["cost_usd"] += float(r["cost_usd"])
        if r.get("latency_ms") is not None and not r.get("cache_hit"):
            latencies[k].append(float(r["latency_ms"]))
    for k, g in groups.items():
        lat = latencies.get(k)
        g["avg_latency_ms"] = sum(lat) / len(lat) if lat else None
    return sorted(groups.values(), key=lambda g: (-g["cost_usd"], -g["completions"]))


def summary(rows: Sequence[dict]) -> dict:
    parts = {r.get("part") for r in rows if r.get("part")}
    priced = [r for r in rows if r.get("cost_usd") is not None]
    cost = sum(float(r["cost_usd"]) for r in priced)
    return {
        "completions": len(rows),
        "parts": len(parts),
        "runs": len({r.get("run_id") for r in rows}),
        "cost_usd": cost,
        "unpriced": len(rows) - len(priced),
        "cache_hits": sum(1 for r in rows if r.get("cache_hit")),
        "total_tokens": sum(_tokens(r) for r in rows),
        **{t: sum(int(r.get(t) or 0) for r in rows) for t in TOKEN_KEYS},
        "cost_per_part": cost / len(parts) if parts else 0.0,
        "cost_per_completion": cost / len(priced) if priced else 0.0,
        "first_ts": min((str(r.get("ts", "")) for r in rows), default=""),
        "last_ts": max((str(r.get("ts", "")) for r in rows), default=""),
    }


def write_csv(rows: Sequence[dict], path: Union[str, Path]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({**r, "extra": json.dumps(r.get("extra") or {})})
    return path


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #
def fmt_usd(x: Optional[float]) -> str:
    if x is None:
        return "unpriced"
    if x >= 0.01 or x == 0:
        return f"${x:,.2f}"
    return f"${x:.4f}"


def fmt_int(n: int) -> str:
    return f"{n:,}"


def fmt_compact(n: float) -> str:
    for div, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= div:
            return f"{n / div:.1f}{suffix}"
    return f"{int(n)}"


def group_cost(g: dict) -> str:
    """Priced cost of a group; "unpriced" when no row in it has a confirmed price."""
    if g["unpriced"] and g["unpriced"] == g["completions"] - g.get("cache_hits", 0):
        return "unpriced"
    return fmt_usd(g["cost_usd"])


def _key_label(v) -> str:
    return "—" if v in (None, "") else str(v)


# Tables shown in both the terminal and the dashboard: (title, group keys).
VIEWS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("By role", ("role",)),
    ("By role, model and provider", ("role", "model", "provider")),
    ("By part (cost per conversion)", ("part",)),
    ("Retries: by role, gate and attempt", ("role", "gate", "attempt")),
    ("By benchmark arm", ("arm",)),
    ("By run", ("run_id",)),
)


def render_text(rows: Sequence[dict]) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    s = summary(rows)
    console.print(
        f"[bold]Total {fmt_usd(s['cost_usd'])}[/bold] over {s['completions']} completions, "
        f"{s['parts']} part(s), {s['runs']} run(s) · {fmt_int(s['total_tokens'])} tokens · "
        f"avg {fmt_usd(s['cost_per_part'])} per part"
        + (f" · [yellow]{s['unpriced']} unpriced[/yellow]" if s["unpriced"] else "")
    )
    for title, keys in VIEWS:
        groups = aggregate(rows, keys)
        if keys == ("arm",) and all(not g["arm"] for g in groups):
            continue
        t = Table(title=title)
        for k in keys:
            t.add_column(k)
        for col in ("calls", "input", "output", "cache rd", "cache wr", "cost", "unpriced"):
            t.add_column(col, justify="right")
        for g in groups:
            t.add_row(*[_key_label(g[k]) for k in keys], str(g["completions"]),
                      fmt_int(g["input_tokens"]), fmt_int(g["output_tokens"]),
                      fmt_int(g["cache_read_tokens"]), fmt_int(g["cache_write_tokens"]),
                      group_cost(g), str(g["unpriced"] or ""))
        console.print(t)


# --------------------------------------------------------------------------- #
# HTML dashboard (self-contained)
# --------------------------------------------------------------------------- #
_CSS = """
.viz-root{color-scheme:light;--surface-0:#f6f6f4;--surface-1:#fcfcfb;--border:#e4e3df;
--text-primary:#0b0b0b;--text-secondary:#52514e;--text-muted:#6f6e69;--grid:#e7e6e2;
--series-1:#2a78d6;--warning:#fab219}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .viz-root{color-scheme:dark;
--surface-0:#121211;--surface-1:#1a1a19;--border:#33332f;--text-primary:#ffffff;--text-secondary:#c3c2b7;
--text-muted:#9a998f;--grid:#2c2c29;--series-1:#3987e5;--warning:#fab219}}
:root[data-theme="dark"] .viz-root{color-scheme:dark;--surface-0:#121211;--surface-1:#1a1a19;
--border:#33332f;--text-primary:#ffffff;--text-secondary:#c3c2b7;--text-muted:#9a998f;--grid:#2c2c29;
--series-1:#3987e5;--warning:#fab219}
*{box-sizing:border-box}
body{margin:0;background:var(--surface-0,#f6f6f4)}
.viz-root{background:var(--surface-0);color:var(--text-primary);min-height:100vh;
font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;padding:24px 16px}
.wrap{max-width:1080px;margin:0 auto}
h1{font-size:20px;margin:0 0 4px}
h2{font-size:15px;margin:0 0 12px}
.sub{color:var(--text-secondary);margin:0 0 20px}
.hero{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:16px}
.hero .label{color:var(--text-secondary)}
.hero .value{font-size:48px;font-weight:600;line-height:1.1}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:16px}
.tile{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:14px}
.tile .label{color:var(--text-secondary);font-size:13px}
.tile .value{font-size:22px;font-weight:600}
.warn{display:inline-flex;gap:6px;align-items:center;color:var(--text-primary)}
.warn::before{content:"";width:10px;height:10px;border-radius:50%;background:var(--warning)}
.charts{display:grid;grid-template-columns:1fr;gap:16px;margin-bottom:16px}
.charts svg{display:block;width:100%;max-width:720px;height:auto}
.card{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:16px;overflow-x:auto}
svg text{fill:var(--text-primary);font-size:13px}
svg .muted{fill:var(--text-muted)}
svg .bar{fill:var(--series-1)}
svg .bar:hover{opacity:.8}
svg .base{stroke:var(--grid);stroke-width:1}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:right;padding:6px 8px;border-bottom:1px solid var(--grid);white-space:nowrap}
th{color:var(--text-secondary);font-weight:600}
th.k,td.k{text-align:left}
td{font-variant-numeric:tabular-nums}
details{margin-bottom:16px}
summary{cursor:pointer;font-weight:600;margin-bottom:8px}
#tip{position:fixed;pointer-events:none;background:var(--surface-1);color:var(--text-primary);
border:1px solid var(--border);border-radius:8px;padding:6px 10px;font-size:12px;display:none;
box-shadow:0 2px 8px rgba(0,0,0,.12);max-width:320px}
.foot{color:var(--text-muted);font-size:12px;margin-top:24px}
"""

_JS = """
(function(){var tip=document.getElementById('tip');
document.addEventListener('mousemove',function(e){var t=e.target.closest('[data-tip]');
if(!t){tip.style.display='none';return;}tip.textContent=t.getAttribute('data-tip');
tip.style.display='block';tip.style.left=Math.min(e.clientX+14,window.innerWidth-330)+'px';
tip.style.top=(e.clientY+14)+'px';});})();
"""


def _bar_chart(groups: Sequence[dict], label_of, title: str, limit: int = 12) -> str:
    """Horizontal single-series bars of priced cost; value at the tip, tooltip per bar."""
    groups = list(groups)[:limit]
    if not groups:
        return ""
    e = html.escape
    row_h, bar_h, label_w, plot_w = 30, 18, 200, 360
    width = label_w + plot_w + 160  # 720: rendered at 1:1 (max-width 720px)
    height = row_h * len(groups) + 8
    peak = max((g["cost_usd"] for g in groups), default=0.0) or 1.0
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{e(title)}">']
    parts.append(f'<line class="base" x1="{label_w}" y1="0" x2="{label_w}" y2="{height}"/>')
    for i, g in enumerate(groups):
        y = i * row_h + 6
        w = max(g["cost_usd"] / peak * plot_w, 0.0)
        label = label_of(g)
        short = label if len(label) <= 28 else label[:27] + "…"
        tip = (f"{label}: {fmt_usd(g['cost_usd'])} · {g['completions']} completions · "
               f"{fmt_int(g['total_tokens'])} tokens"
               + (f" · {g['unpriced']} unpriced" if g["unpriced"] else ""))
        parts.append(f'<text x="{label_w - 8}" y="{y + bar_h - 4}" text-anchor="end">{e(short)}</text>')
        if w >= 1:
            r = min(4.0, w / 2)
            x0, x1, y1 = label_w, label_w + w, y + bar_h
            parts.append(
                f'<path class="bar" data-tip="{e(tip)}" d="M{x0},{y} H{x1 - r:.1f} '
                f'Q{x1:.1f},{y} {x1:.1f},{y + r:.1f} V{y1 - r:.1f} Q{x1:.1f},{y1} {x1 - r:.1f},{y1} '
                f'H{x0} Z"/>')
        else:
            parts.append(f'<rect x="{label_w}" y="{y}" width="{plot_w}" height="{bar_h}" '
                         f'fill="transparent" data-tip="{e(tip)}"/>')
        value = group_cost(g)
        if g["unpriced"] and value != "unpriced":
            value += f"  +{g['unpriced']} unpriced"
        muted = ' class="muted"' if w < 1 else ""
        parts.append(f'<text x="{label_w + w + 8:.1f}" y="{y + bar_h - 4}"{muted}>{e(value)}</text>')
    parts.append("</svg>")
    return f'<div class="card"><h2>{e(title)}</h2>{"".join(parts)}</div>'


def _table(groups: Sequence[dict], keys: tuple[str, ...]) -> str:
    e = html.escape
    head = "".join(f'<th class="k">{e(k)}</th>' for k in keys)
    head += "".join(f"<th>{c}</th>" for c in
                    ("completions", "input", "output", "cache read", "cache write",
                     "total tokens", "cost", "unpriced", "avg latency"))
    body = []
    for g in groups:
        lat = f"{g['avg_latency_ms'] / 1000:.1f}s" if g.get("avg_latency_ms") is not None else "—"
        cells = "".join(f'<td class="k">{e(_key_label(g[k]))}</td>' for k in keys)
        cells += "".join(f"<td>{v}</td>" for v in (
            g["completions"], fmt_int(g["input_tokens"]), fmt_int(g["output_tokens"]),
            fmt_int(g["cache_read_tokens"]), fmt_int(g["cache_write_tokens"]),
            fmt_int(g["total_tokens"]), group_cost(g), g["unpriced"] or "", lat))
        body.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def render_html(rows: Sequence[dict], title: str = "Token & cost report") -> str:
    e = html.escape
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if not rows:
        content = (f"<h1>{e(title)}</h1><p class='sub'>No completions recorded yet. Run the "
                   "pipeline, then re-run <code>python -m pipeline.token_report</code>.</p>")
    else:
        s = summary(rows)
        unpriced = (f'<span class="warn">{s["unpriced"]} unpriced</span>' if s["unpriced"]
                    else "0")
        tiles = [
            ("Completions", fmt_int(s["completions"])),
            ("Parts", fmt_int(s["parts"])),
            ("Average cost per part", fmt_usd(s["cost_per_part"])),
            ("Average cost per completion", fmt_usd(s["cost_per_completion"])),
            ("Total tokens", fmt_compact(s["total_tokens"])),
            ("Cache hits", fmt_int(s["cache_hits"])),
            ("Unpriced completions", unpriced),
        ]
        tile_html = "".join(f'<div class="tile"><div class="label">{e(l)}</div>'
                            f'<div class="value">{v}</div></div>' for l, v in tiles)
        charts = "".join([
            _bar_chart(aggregate(rows, ("role",)), lambda g: _key_label(g["role"]), "Cost by role"),
            _bar_chart(aggregate(rows, ("model", "provider")),
                       lambda g: f"{_key_label(g['model'])} ({_key_label(g['provider'])})",
                       "Cost by model and provider"),
            _bar_chart(aggregate(rows, ("part",)), lambda g: _key_label(g["part"]),
                       "Cost per part (top 12)"),
            _bar_chart(aggregate([r for r in rows if r.get("attempt") is not None],
                                 ("role", "attempt")),
                       lambda g: f"{g['role']} · attempt {g['attempt']}",
                       "Retry cost (role · attempt)"),
        ])
        tables = "".join(
            f"<details{' open' if i < 3 else ''}><summary>{e(t)}</summary>"
            f'<div class="card">{_table(aggregate(rows, keys), keys)}</div></details>'
            for i, (t, keys) in enumerate(VIEWS)
            if not (keys == ("arm",) and all(not r.get("arm") for r in rows))
        )
        span = f"{s['first_ts'][:16].replace('T', ' ')} → {s['last_ts'][:16].replace('T', ' ')} UTC"
        content = (
            f"<h1>{e(title)}</h1><p class='sub'>{s['runs']} run(s) · {e(span)}</p>"
            f'<div class="hero"><div class="label">Total spend (priced completions)</div>'
            f'<div class="value">{fmt_usd(s["cost_usd"])}</div></div>'
            f'<div class="tiles">{tile_html}</div>'
            f'<div class="charts">{charts}</div>{tables}'
        )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{e(title)}</title><style>{_CSS}</style></head>"
        f"<body><div class='viz-root'><div class='wrap'>{content}"
        f"<p class='foot'>Generated {generated} by pipeline/token_report.py. Prices: "
        "config/pricing.json (USD per 1M tokens); unpriced = no confirmed rate for that "
        "provider/model.</p></div></div><div id='tip'></div><script>{_JS}</script></body></html>"
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Token & cost report over usage_ledger.jsonl files.")
    ap.add_argument("paths", nargs="*", default=["./output"],
                    help="Output dirs (searched recursively) or ledger files. Default ./output")
    ap.add_argument("--html", help="Write the HTML dashboard to this path.")
    ap.add_argument("--csv", help="Write the (filtered) raw rows to this CSV path.")
    ap.add_argument("--part")
    ap.add_argument("--arm")
    ap.add_argument("--role", help="extractor | planner | auditor_reviewer | jev | other")
    ap.add_argument("--since", help="ISO date, inclusive (e.g. 2026-10-01)")
    ap.add_argument("--reprice", action="store_true",
                    help="Recompute every row's cost from the current pricing file.")
    ap.add_argument("--pricing", help="Alternate pricing.json path (with --reprice).")
    ap.add_argument("--title", default="Token & cost report")
    args = ap.parse_args(argv)

    rows = load_rows(args.paths)
    rows = filter_rows(rows, part=args.part, arm=args.arm, role=args.role, since=args.since)
    if args.reprice:
        rows = reprice(rows, Pricing.load(args.pricing))

    if not rows:
        print(f"No completions recorded in {', '.join(map(str, args.paths))} "
              f"(looked for {LEDGER_NAME}).")
    else:
        render_text(rows)
    if args.html:
        out = Path(args.html)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_html(rows, title=args.title), encoding="utf-8")
        print(f"Dashboard: {out}")
    if args.csv:
        print(f"CSV: {write_csv(rows, args.csv)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
