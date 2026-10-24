"""One-page review sheet per part: drawing, model picture, key table, flags (spec 2026-10-23).

Flags are numbered from 1 in key.json order ("flag 3" = key.json flags[2]), so a person can
refer to them while writing resolutions; `prep signoff` uses the same numbers.
"""
from __future__ import annotations

import base64
import html as _h
from pathlib import Path
from typing import Optional

from bench.features import Feature, Flag, Key

COLS = ("id", "type", "d", "depth", "thru", "cbore_d", "cbore_depth", "csink_d", "thread",
        "center", "axis", "normal", "offset", "size", "members", "pattern", "note")


def _img(p: Optional[Path]) -> str:
    if not p or not Path(p).is_file():
        return "<p><em>no image</em></p>"
    b64 = base64.b64encode(Path(p).read_bytes()).decode()
    return f'<img style="max-width:100%;border:1px solid #ccc" src="data:image/png;base64,{b64}">'


def _num(x) -> str:
    return f"{x:.4f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)


def _fmt(v) -> str:
    if v is None or v == "" or v == []:
        return ""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.4f}"
    if isinstance(v, dict):                       # hole_pattern: {"mode": ..., ...}
        return _h.escape(" ".join(f"{k}={_num(x) if not isinstance(x, list) else _fmt(x)}"
                                  for k, x in v.items()))
    if isinstance(v, list):
        if all(isinstance(x, str) for x in v):    # hole_pattern members
            return _h.escape(", ".join(v))
        return "(" + ", ".join(f"{x:.3f}" if isinstance(x, float) else _h.escape(str(x)) for x in v) + ")"
    return _h.escape(str(v))


def flag_line(i: int, f: Flag) -> str:
    """Plain-text form of flag number i (1-based), shared with the prep CLI."""
    s = f"flag {i}: {f.kind} {f.detail}"
    if f.feature:
        s += f" ({f.feature})"
    return s


def _flag_item(i: int, f: Flag) -> str:
    feat = f" ({_h.escape(f.feature)})" if f.feature else ""
    res = (f" &rarr; <i>{_h.escape(f.resolution)}</i>" if f.resolution
           else ' <span class="open">open</span>')
    return f'<li id="flag-{i}"><b>flag {i}</b> &middot; <b>{_h.escape(f.kind)}</b> {_h.escape(f.detail)}{feat}{res}</li>'


def _row(f: Feature) -> str:
    cls = ' class="group"' if f.type == "hole_pattern" else ""
    return f"<tr{cls}>" + "".join(f"<td>{_fmt(getattr(f, c))}</td>" for c in COLS) + "</tr>"


def render(key: Key, drawing_png: Optional[Path], model_png: Optional[Path]) -> str:
    rows = "".join(_row(f) for f in key.features)
    flags = "".join(_flag_item(i, f) for i, f in enumerate(key.flags, 1)) or "<li>none</li>"
    n_open = len(key.open_flags())
    if key.signed:
        so = key.signoff
        sign = _h.escape(" ".join(str(so.get(k)) for k in ("kind", "by", "date", "tool") if so.get(k)))
    else:
        sign = "not signed"
    counts = ", ".join(f"{t} {n}" for t, n in sorted(key.counts().items()))
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{_h.escape(key.part)} key review</title>
<style>body{{font-family:system-ui,sans-serif;margin:20px}}table{{border-collapse:collapse;font-size:13px}}
td,th{{border:1px solid #bbb;padding:3px 6px}}tr.group td{{background:#f3f3f3;font-style:italic}}
.open{{color:#b00;font-weight:bold}}.cols{{display:grid;grid-template-columns:2fr 1fr;gap:16px}}</style>
</head><body><h1>{_h.escape(key.part)}: answer-key review</h1>
<p>units {_h.escape(key.units)} &middot; envelope {_fmt(key.envelope)} &middot; source {_h.escape(key.source)}
&middot; sign-off: {sign}</p>
<p>features: {_h.escape(counts) or "none"}</p>
<h2>Flags ({len(key.flags)}, {n_open} open)</h2>
<p><small>Flag n is <code>flags[n-1]</code> in key.json. Write a resolution ("accepted: ..." or
"fixed key: ...") on each, then run <code>python -m bench.prep signoff {_h.escape(key.part)} --by NAME</code>.</small></p>
<ul>{flags}</ul>
<div class="cols"><div><h2>Drawing</h2>{_img(drawing_png)}</div><div><h2>Model</h2>{_img(model_png)}</div></div>
<h2>Key</h2><table><tr>{''.join(f'<th>{c}</th>' for c in COLS)}</tr>{rows}</table></body></html>"""
