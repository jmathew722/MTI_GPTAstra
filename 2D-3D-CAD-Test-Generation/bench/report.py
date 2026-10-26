"""Scorer run outputs (spec 2026-10-24, 'Run outputs'): scores.json and a self-contained report.html.

`results` is a list of per-part dicts (bench.score builds them); `summary` is the run rollup.
Non-finite floats (an outright attribute failure has error = inf) are written as the strings
"inf" / "-inf" / "nan" so scores.json stays strict JSON."""
from __future__ import annotations

import html as _h
import json
import math
from pathlib import Path


def _clean(v):
    if isinstance(v, float) and not math.isfinite(v):
        return "nan" if math.isnan(v) else ("inf" if v > 0 else "-inf")
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    return v


def write_json(path: Path, results: list, summary: dict, skipped_unsigned=(), no_key=()) -> None:
    data = {"summary": summary, "parts": results,
            "skipped_unsigned": list(skipped_unsigned), "no_key": list(no_key)}
    Path(path).write_text(json.dumps(_clean(data), indent=2, allow_nan=False), encoding="utf-8")


def _e(x) -> str:
    return _h.escape(str(x))


def _n(x, nd: int = 2) -> str:
    if x is None:
        return ""
    if isinstance(x, float):
        return "inf" if math.isinf(x) else f"{x:.{nd}f}"
    return _e(x)


def _errors(errs: dict) -> str:
    out = []
    for attr, v in (errs or {}).items():
        err, mult = (list(v) + [None, None])[:2] if isinstance(v, (list, tuple)) else (v, None)
        out.append(f"{_e(attr)} {_n(err, 4)}" + (f" ({_n(mult, 1)}&times;tol)" if mult is not None else ""))
    return "<br>".join(out)


def _table(head: list, rows: list) -> str:
    th = "".join(f"<th>{_e(h)}</th>" for h in head)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><tr>{th}</tr>{body}</table>"


def _rollup(title: str, d: dict) -> str:
    rows = [[_e(k), _n(v)] for k, v in sorted((d or {}).items(), key=lambda kv: -kv[1])]
    return f"<h3>{_e(title)}</h3>" + (_table(["", "points lost"], rows) if rows else "<p>none</p>")


def _practices(pr: dict) -> str:
    """The per-part MTI practices table (spec 2b): a separate score, never blended."""
    if not pr:
        return ""
    head = (f"<h3>MTI practices: {_n(pr.get('score'), 1) or 'n/a'}</h3><p>A separate score, never blended into "
            "the geometry score. <i>self-reported</i> rows read the compiler's own report."
            + ("" if pr.get("checked") else " SLDPRT checks: not checked.")
            + (f" {_e(pr['note'])}" if pr.get("note") else "") + "</p>")
    rows = [[_e(r.get("id")), _e(r.get("name")), _n(r.get("credit")) if r.get("applicable") else "n/a",
             _e(r.get("source")), _e(r.get("stage") or ""), _e(r.get("reason") or "")]
            for r in pr.get("rows") or []]
    return head + _table(["check", "practice", "credit", "source", "blame", "reason"], rows)


def _part(p: dict) -> str:
    head = f'<h2 id="part-{_e(p["part"])}">{_e(p["part"])}</h2>'
    if p.get("error"):
        return head + f'<p class="err">error: {_e(p["error"])}</p>'
    meta = [f"score {_n(p.get('score'))}", "exact" if p.get("exact") else "not exact"]
    if p.get("reference_score") is not None:
        meta.append(f"CadQuery reference {_n(p['reference_score'])}")
    if p.get("multi_body"):
        meta.append(f"multi-body: {_e(p['multi_body'])} solids (largest scored)")
    if p.get("generated"):
        meta.append(f"generated {_e(p['generated'])}")
    if "extraction_found" in p:
        meta.append("extraction found" if p["extraction_found"]
                    else "extraction not found (extraction blame not checked)")
    if p.get("stale"):
        meta.append('<span class="err">stale: generated.step is older than the SLDPRT (--no-sw)</span>')
    rows = [[_e(r["feature_id"]), _e(r["type"]), _n(r.get("tier_weight"), 0), _n(r.get("weight")),
             _e(r.get("status", "")), _e(r.get("matched_id") or ""), _errors(r.get("errors")),
             _n(r.get("credit")), _n(r.get("points_lost")), _e(r.get("blame", "")), _e(r.get("reason", ""))]
            for r in p.get("rows", [])]
    out = head + f"<p>{' &middot; '.join(meta)}</p>" + _table(
        ["key id", "type", "tier", "weight", "status", "matched", "errors", "credit", "points lost", "blame",
         "reason"], rows)
    if p.get("extras"):
        out += "<h3>Extras</h3>" + _table(["id", "type", "weight", "points lost", "blame"], [
            [_e(x["feature_id"]), _e(x["type"]), _n(x.get("weight")), _n(x.get("points_lost")), _e(x.get("blame", ""))]
            for x in p["extras"]])
    if p.get("unresolved"):
        out += ("<h3>Left unbuilt as uncertain by the pipeline</h3><p>The planner flagged these and asked "
                "instead of guessing. The drawing still calls for them: when the key has the feature it is "
                "scored missing (blame <i>unresolved</i>); when it doesn't, it is listed here only.</p>") + _table(
            ["plan id", "kind", "question"],
            [[_e(u.get("id")), _e(u.get("kind")), _e(u.get("question"))] for u in p["unresolved"]])
    out += _practices(p.get("practices"))
    if p.get("drawing_only"):
        out += "<h3>Drawing-only values (reported, not scored)</h3><ul>" + "".join(
            f"<li>{_e(x)}</li>" for x in p["drawing_only"]) + "</ul>"
    return out


def _note(p: dict) -> str:
    if p.get("error"):
        return _e(p["error"])
    notes = []
    if p.get("multi_body"):
        notes.append(f"multi-body ({_e(p['multi_body'])})")
    if p.get("stale"):
        notes.append('<span class="err">stale generated.step</span>')
    if p.get("unresolved"):
        notes.append(f"{len(p['unresolved'])} left unbuilt as uncertain")
    return ", ".join(notes)


def write_html(path: Path, results: list, summary: dict, skipped_unsigned=(), no_key=()) -> None:
    s = summary or {}
    summ = _table(["part", "score", "practices", "exact", "reference", "extraction", "note"], [
        [f'<a href="#part-{_e(p["part"])}">{_e(p["part"])}</a>', _n(p.get("score")),
         _n((p.get("practices") or {}).get("score"), 1),
         "yes" if p.get("exact") else "no", _n(p.get("reference_score")),
         {True: "found", False: "not found"}.get(p.get("extraction_found"), ""), _note(p)]
        for p in results])
    roll = s.get("rollup") or {}
    skipped = ""
    if skipped_unsigned:
        skipped += f"<p>skipped (unsigned key): {_e(', '.join(skipped_unsigned))}</p>"
    if no_key:
        skipped += f"<p>skipped (no key): {_e(', '.join(no_key))}</p>"
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>Benchmark scores</title>
<style>body{{font-family:system-ui,sans-serif;margin:20px}}table{{border-collapse:collapse;font-size:13px;margin-bottom:8px}}
td,th{{border:1px solid #bbb;padding:3px 6px;vertical-align:top}}th{{background:#f3f3f3}}.err{{color:#b00;font-weight:bold}}
.cols{{display:flex;gap:24px;flex-wrap:wrap}}</style></head><body>
<h1>Benchmark scores</h1>
<p>parts scored {_n(s.get('n_scored'), 0)} &middot; mean {_n(s.get('mean'))} &middot; median {_n(s.get('median'))}
&middot; exact-part rate {_n(s.get('exact_rate'))}
&middot; practices mean {_n(s.get('practices_mean'))} (separate, never blended) &middot; errors {_e(', '.join(s.get('errors') or []) or 'none')}</p>
{skipped}{summ}
<h2>Points lost</h2><div class="cols"><div>{_rollup('by stage', roll.get('by_stage'))}</div>
<div>{_rollup('by feature type', roll.get('by_type'))}</div><div>{_rollup('by tier', roll.get('by_tier'))}</div></div>
{''.join(_part(p) for p in results)}
</body></html>"""
    Path(path).write_text(doc, encoding="utf-8")
