"""Benchmark scorer CLI (spec 2026-10-24): score a pipeline run against the signed answer keys.

    python -m bench.score RUN_DIR [--parts P ...] [--keys-dir DIR] [--no-sw] [--config FILE]

Per part folder RUN_DIR/<part>/: the generated part (generated.step, or *_ir.SLDPRT exported to
it through SolidWorks when the STEP is missing or older), the CadQuery reference
(reference.step), the extraction JSON and ir_report.json. Writes RUN_DIR/scores.json and
RUN_DIR/report.html.

Exit codes: 0 ok; 1 some part errored (an error row, never a silent 0); 2 config / no parts;
3 SolidWorks needed for an export but unavailable (checked before anything is scored).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from bench import blame as blame_mod
from bench import config, keygen, report, score_config, sw_tasks
from bench.features import Feature, Key
from bench.scoring import PartScore, add_extras, score_part

GENERATED = "generated.step"
REFERENCE = "reference.step"


def read_step(step: Path, *, units: str, part: str) -> tuple[Key, list[Feature], int]:
    """-> (key of the largest solid by volume, features of every other solid, solid count).
    Other bodies' feature ids are prefixed "B<n>:" (n = 2.. by decreasing volume)."""
    import cadquery as cq
    vals = cq.importers.importStep(str(step)).vals()
    solids = [s for v in vals for s in (v.Solids() if hasattr(v, "Solids") else [v])]
    if not solids:
        raise ValueError(f"{Path(step).name}: no solid in the STEP file")
    solids.sort(key=lambda s: s.Volume(), reverse=True)
    key = keygen.extract(solids[0], units=units, part=part, source=Path(step).name)
    others: list[Feature] = []
    for i, s in enumerate(solids[1:], 2):
        for f in keygen.extract(s, units=units, part=part, source=Path(step).name).features:
            f.id = f"B{i}:{f.id}"
            others.append(f)
    return key, others, len(solids)


def _json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, ValueError):
        return {}


def _extraction(d: Path) -> dict:
    found = sorted(d.glob("*_extraction.json"))
    return _json(found[0]) if found else {}


def _sldprt(d: Path) -> Optional[Path]:
    found = sorted(d.glob("*_ir.SLDPRT"))
    return found[0] if found else None


def _empty(key: Key) -> Key:
    return Key(part=key.part, units=key.units, source="(none)", envelope=[], features=[])


def _no_generated_stage(d: Path, ir: dict) -> tuple[str, str]:
    """No generated part: blame the stage that failed (from ir_report.json)."""
    err = f" ({ir['error']})" if ir.get("error") else ""
    skipped = ir.get("cq_skipped") or {}
    if not (d / "plan.json").is_file() and not ir.get("planned"):
        return "planner", "no plan" + err
    if skipped:
        return "cadquery", "reference skipped " + "; ".join(f"{k}: {v}" for k, v in sorted(skipped.items())) + err
    return "solidworks", "no SolidWorks part" + err


def _part_result(ps: PartScore, bl: dict, ref: Optional[PartScore]) -> dict:
    pose = ps.pose
    return {"part": ps.part, "score": ps.score, "exact": ps.exact, "error": None,
            "reference_score": ref.score if ref else None,
            "rows": [asdict(r) for r in ps.rows], "extras": [asdict(e) for e in ps.extras],
            "blame": {k: asdict(b) for k, b in bl.items()}, "drawing_only": list(ps.drawing_only),
            "pose_rotation": pose.R.tolist() if pose is not None else None,
            "pose_translation": pose.t.tolist() if pose is not None else None}


def score_one(part: str, d: Path, key: Key, generated: Optional[Path], cfg) -> tuple[dict, PartScore, dict]:
    ir = _json(d / "ir_report.json")
    ref_step = d / REFERENCE
    ref = None
    if ref_step.is_file():
        rk, rothers, _ = read_step(ref_step, units=key.units, part=part)
        ref = add_extras(score_part(key, rk, cfg), rothers, key, cfg)
    if generated is None:
        ps = score_part(key, _empty(key), cfg)
        stage, reason = _no_generated_stage(d, ir)
        bl = {}
        for r in ps.rows:
            r.blame, r.reason = stage, reason
            bl[r.feature_id] = blame_mod.Blame(stage, reason, r.points_lost)
        ps.score, ps.exact = 0.0, False
        res = _part_result(ps, bl, ref)
        res["generated"] = None
        return res, ps, bl
    gk, others, n = read_step(generated, units=key.units, part=part)
    ps = add_extras(score_part(key, gk, cfg), others, key, cfg)
    cq_ps = ref if ref is not None else score_part(key, _empty(key), cfg)
    bl = blame_mod.blame_part(ps, cq_ps, key, _extraction(d), ir, cfg)
    res = _part_result(ps, bl, ref)
    res["generated"] = generated.name
    if n > 1:
        res["multi_body"] = n
    return res, ps, bl


def summarise(results: list, scored: list) -> dict:
    ok = [r for r in results if not r.get("error")]
    scores = [r["score"] for r in ok]
    return {"n_scored": len(ok),
            "mean": statistics.fmean(scores) if scores else None,
            "median": statistics.median(scores) if scores else None,
            "exact_rate": (sum(1 for r in ok if r["exact"]) / len(ok)) if ok else None,
            "errors": [r["part"] for r in results if r.get("error")],
            "rollup": blame_mod.rollup(scored)}


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m bench.score", description=__doc__.split("\n")[0])
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--parts", nargs="+")
    ap.add_argument("--keys-dir", type=Path, help="default: MTI_BENCH_DATA (bench.config.data_root)")
    ap.add_argument("--no-sw", action="store_true", help="never export: use generated.step only")
    ap.add_argument("--config", type=Path, help="score_config override file")
    return ap


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        cfg = score_config.load(args.config)
        keys_dir = args.keys_dir or config.data_root()
    except (config.BenchConfigError, OSError, ValueError, KeyError) as e:
        print(f"config error: {e}")
        return 2
    run: Path = args.run_dir
    if not run.is_dir():
        print(f"{run} is not a directory")
        return 2
    names = args.parts or sorted(p.name for p in run.iterdir() if p.is_dir())
    no_key = [p for p in names if not (keys_dir / p / "key.json").is_file()]
    names = [p for p in names if p not in no_key]
    if not names:
        print(f"no parts with a key in {keys_dir}" + (f" (no key: {', '.join(no_key)})" if no_key else ""))
        return 2

    keys: dict[str, Key] = {}
    unsigned: list[str] = []
    for p in names:
        k = Key.load(keys_dir / p / "key.json")
        if k.signed:
            keys[p] = k
        else:
            unsigned.append(p)

    # Where each generated part comes from; SolidWorks exports happen before anything is scored.
    generated: dict[str, Optional[Path]] = {}
    errors: dict[str, str] = {}
    exports: list[tuple[str, Path, Path]] = []
    for p in keys:
        d = run / p
        gen, sld = d / GENERATED, _sldprt(d)
        stale = sld is not None and (not gen.is_file() or gen.stat().st_mtime < sld.stat().st_mtime)
        if stale and not args.no_sw:
            exports.append((p, sld, gen))
            generated[p] = gen
        elif gen.is_file():
            generated[p] = gen
        elif sld is not None:
            errors[p] = f"{sld.name} present but no {GENERATED} and --no-sw given"
        else:
            generated[p] = None
    if exports:
        try:
            app = sw_tasks.connect()
        except sw_tasks.SwUnavailable as e:
            print(f"SolidWorks needed to export {len(exports)} part(s) to STEP: {e}")
            return 3
        for p, sld, gen in exports:
            try:
                sw_tasks.sldprt_to_step(app, sld, gen, gen.with_suffix(".png"))
            except Exception as e:           # one bad part never stops the run
                errors[p] = f"STEP export failed: {type(e).__name__}: {e}"

    results, scored = [], []
    for p, key in keys.items():
        if p in errors:
            results.append({"part": p, "score": None, "exact": False, "error": errors[p]})
            continue
        try:
            res, ps, bl = score_one(p, run / p, key, generated[p], cfg)
        except Exception as e:               # unreadable STEP etc.: an error row, never a silent 0
            results.append({"part": p, "score": None, "exact": False, "error": f"{type(e).__name__}: {e}"})
            continue
        results.append(res)
        scored.append((ps, bl))

    summary = summarise(results, scored)
    report.write_json(run / "scores.json", results, summary, unsigned, no_key)
    report.write_html(run / "report.html", results, summary, unsigned, no_key)
    for r in results:
        print(f"{r['part']:<14} " + (f"ERROR {r['error']}" if r.get("error")
                                     else f"{r['score']:6.1f}{'  exact' if r['exact'] else ''}"))
    if unsigned:
        print(f"skipped (unsigned key): {', '.join(unsigned)}")
    if summary["n_scored"]:
        print(f"mean {summary['mean']:.1f}  median {summary['median']:.1f}  exact {summary['exact_rate']:.0%}")
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
