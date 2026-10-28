"""Feature-type profile of the benchmark, so later changes can be checked for bias toward
common feature types (spec 2026-10-23, "Feature profile")."""
from __future__ import annotations

import html as _html
import re
from collections import Counter
from pathlib import Path

from bench.features import FEATURE_TYPES, Key

# hole_pattern groups holes that are already counted individually; keep it out of shares.
GROUP_TYPES = ("hole_pattern",)

ARCHIVE_KEYWORDS = {
    "tap": r"\bTAP\b|-\d+\s*UN[CF]|\bM\d+\s*X\s*\d",
    "counterbore": r"C'?BORE|CBORE",
    "countersink": r"C'?SINK|CSK",
    "thru/drill": r"\bDR\.|\bDRILL|\bTHRU\b",
    "hole pattern": r"\d+\s*-?\s*HOLES|\bB\.?\s*C\.|EQ\.?\s*SP",
    "slot": r"\bSLOT",
    "keyway": r"KEYWAY|KEY\s*SEAT",
    "chamfer": r"CHAM|X\s*45",
    "radius/fillet": r"\d\s*R\.|RADII|FILLET",
}


def type_counts(keys: list[Key]) -> dict[str, int]:
    c: Counter = Counter()
    for k in keys:
        c.update(k.counts())
    return dict(c)


def plan_type_counts(plan: dict) -> dict[str, int]:
    """IR plan (old dev parts) -> approximate feature types (planned features only;
    unresolved or otherwise non-planned features are excluded)."""
    c: Counter = Counter()
    for f in plan.get("features", []):
        if f.get("status", "planned") != "planned":
            continue
        k = f.get("kind")
        if k == "revolve":
            c["turned_diameter"] += 1
        elif k == "hole":
            c[{"cbore": "counterbore", "csink": "countersink", "tapped": "tapped_hole",
               "blind": "blind_hole"}.get((f.get("spec") or {}).get("type"), "thru_hole")] += 1
        elif k == "edge_op":
            c["fillet" if f.get("operation") == "fillet" else "chamfer"] += 1
        elif k == "pattern":
            c["hole_pattern"] += 1
        elif k == "prism" and f.get("op") == "cut":
            c["pocket_step"] += 1
    return dict(c)


def archive_keyword_counts(dataset_dir: Path) -> dict[str, int]:
    """Drawings (of all DWGs under dataset_dir) whose readable text mentions each keyword.
    Approximate: compressed DWGs expose little text."""
    c: Counter = Counter()
    for p in Path(dataset_dir).rglob("*"):
        if p.suffix.lower() != ".dwg":
            continue
        b = p.read_bytes()
        t = "\n".join(x.decode("ascii", "ignore") for x in re.findall(rb"[ -~]{4,}", b)).upper()
        for name, rx in ARCHIVE_KEYWORDS.items():
            if re.search(rx, t):
                c[name] += 1
    return dict(c)


def _shares(dev: dict, held: dict) -> tuple[Counter, int]:
    total = Counter(dev) + Counter(held)
    n = sum(v for t, v in total.items() if t not in GROUP_TYPES) or 1
    return total, n


def bias_flags(dev: dict, held: dict, threshold: float = 0.30) -> list[str]:
    total, n = _shares(dev, held)
    out = [f"{t}: {v / n:.0%} of all features (over {threshold:.0%})"
           for t, v in total.most_common() if t not in GROUP_TYPES and v / n > threshold]
    out += [f"{t}: in held-out but not in format dev" for t in held if t not in dev]
    out += [f"{t}: in format dev but not in held-out" for t in dev if t not in held]
    return out


def render_html(dev: dict, held: dict, old_dev: dict, archive: dict, flags: list[str]) -> str:
    total, n = _shares(dev, held)

    def row(t: str) -> str:
        if t in GROUP_TYPES:
            name, share = f"{t} (groups)", "-"
        else:
            name, share = t, f"{total.get(t, 0) / n:.0%}"
        return (f"<tr><td>{name}</td><td>{dev.get(t, 0)}</td><td>{held.get(t, 0)}</td>"
                f"<td>{total.get(t, 0)}</td><td>{share}</td><td>{old_dev.get(t, 0)}</td></tr>")

    rows = "".join(row(t) for t in FEATURE_TYPES if total.get(t) or old_dev.get(t))
    arch = "".join(f"<tr><td>{_html.escape(k)}</td><td>{v}</td></tr>" for k, v in sorted(archive.items()))
    fl = "".join(f"<li>{_html.escape(f)}</li>" for f in flags) or "<li>none</li>"
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Benchmark profile</title>
<style>body{{font-family:system-ui,sans-serif;margin:24px}}table{{border-collapse:collapse}}
td,th{{border:1px solid #bbb;padding:4px 8px;text-align:right}}td:first-child{{text-align:left}}</style></head>
<body><h1>Benchmark feature profile</h1><h2>Bias flags</h2><ul>{fl}</ul>
<h2>Feature types (from answer keys)</h2><table><tr><th>type</th><th>format dev</th><th>held-out</th>
<th>total</th><th>share</th><th>old 9 dev (plans)</th></tr>{rows}</table>
<h2>Whole MTI archive (DWG keyword scan, approximate)</h2><table><tr><th>keyword</th><th>drawings</th></tr>{arch}</table>
</body></html>"""
