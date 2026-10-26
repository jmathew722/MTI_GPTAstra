"""Benchmark scorer CLI (spec 2026-10-24): score a pipeline run against the signed answer keys.

    python -m bench.score RUN_DIR [--parts P ...] [--keys-dir DIR] [--no-sw] [--config FILE]

Per part folder RUN_DIR/<part>/: the generated part (generated.step, or *_ir.SLDPRT exported to
it through SolidWorks when the STEP is missing or older), the CadQuery reference
(reference.step), the extraction JSON and ir_report.json. Writes RUN_DIR/scores.json and
RUN_DIR/report.html.

Each part also gets an MTI practices score (spec 2026-10-25, 2b), a separate column that is never
blended into the geometry score. Its SLDPRT checks read the feature tree, cached as
<part>/feature_tree.json; the tree is read through SolidWorks in the same pass as the STEP
exports. --no-sw uses a cached tree when there is one, otherwise those checks are "not checked".

Exit codes: 0 ok; 1 some part errored (an error row, never a silent 0); 2 config / no parts;
3 SolidWorks needed for an export but unavailable (checked before anything is scored).
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from bench import blame as blame_mod
from bench import config, keygen, practices, report, score_config, sw_tasks, sw_tree
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


_EXTRACTION_PATH = re.compile(r"(\S+_extraction\.json)\s*$")


def find_extraction(d: Path, ir: dict) -> Optional[Path]:
    """The part's extraction JSON: in the run folder, else the path ir_report.json "extraction"
    names ("reused output\\...\\P_extraction.json", "extracted with ... -> <path>"), resolved
    against the run folder's ancestors, the working directory and the code root."""
    found = sorted(d.glob("*_extraction.json"))
    if found:
        return found[0]
    m = _EXTRACTION_PATH.search(str((ir or {}).get("extraction") or ""))
    if not m:
        return None
    rel = Path(m.group(1).replace("\\", "/"))
    if rel.is_absolute():
        return rel if rel.is_file() else None
    for base in [*Path(d).resolve().parents, Path.cwd(), config.CODE_ROOT]:
        if (base / rel).is_file():
            return base / rel
    return None


def _sldprt(d: Path) -> Optional[Path]:
    found = sorted(d.glob("*_ir.SLDPRT"))
    return found[0] if found else None


def _empty(key: Key) -> Key:
    return Key(part=key.part, units=key.units, source="(none)", envelope=[], features=[])


def _no_generated_stage(ir: dict, plan: dict, typ: str) -> tuple[str, str]:
    """No generated part: blame the stage that failed (from ir_report.json / plan.json): no
    plan -> planner; a skipped plan feature that could be this row -> cadquery; else solidworks."""
    err = f" ({ir['error']})" if ir.get("error") else ""
    if not plan and not ir.get("planned"):
        return "planner", "no plan" + err
    sk = blame_mod.compatible_skips(typ, ir.get("cq_skipped") or {}, plan)
    if sk:
        stage, reason = blame_mod.skip_blame(sk)
        return stage, reason + err
    return "solidworks", "no SolidWorks part" + err


def _part_result(ps: PartScore, bl: dict, ref: Optional[PartScore]) -> dict:
    pose = ps.pose
    return {"part": ps.part, "score": ps.score, "exact": ps.exact, "error": None,
            "reference_score": ref.score if ref else None,
            "rows": [asdict(r) for r in ps.rows], "extras": [asdict(e) for e in ps.extras],
            "blame": {k: asdict(b) for k, b in bl.items()}, "drawing_only": list(ps.drawing_only),
            "pose_rotation": pose.R.tolist() if pose is not None else None,
            "pose_translation": pose.t.tolist() if pose is not None else None}


def practices_result(tree: Optional[list], ir: dict, plan: dict, cfg, note: str = "") -> dict:
    out = asdict(practices.check_part(tree, ir, plan, cfg))
    if note:
        out["note"] = note
    return out


def score_one(part: str, d: Path, key: Key, generated: Optional[Path], cfg,
              tree: Optional[list] = None, tree_note: str = "") -> tuple[dict, PartScore, dict]:
    ir = _json(d / "ir_report.json")
    plan = _json(d / "plan.json")
    prac = practices_result(tree, ir, plan, cfg, tree_note)
    ext_path = find_extraction(d, ir)
    ref_step = d / REFERENCE
    ref = None
    if ref_step.is_file():
        rk, rothers, _ = read_step(ref_step, units=key.units, part=part)
        ref = add_extras(score_part(key, rk, cfg), rothers, key, cfg)
    if generated is None:
        ps = score_part(key, _empty(key), cfg)
        bl = {}
        for r in ps.rows:
            stage, reason = _no_generated_stage(ir, plan, r.type)
            r.blame, r.reason = stage, reason
            bl[r.feature_id] = blame_mod.Blame(stage, reason, r.points_lost)
        ps.score, ps.exact = 0.0, False
        res = _part_result(ps, bl, ref)
        res["generated"] = None
        res["extraction_found"] = ext_path is not None
        res["unresolved"] = blame_mod.unresolved_features(ir, plan)
        res["practices"] = prac
        return res, ps, bl
    gk, others, n = read_step(generated, units=key.units, part=part)
    ps = add_extras(score_part(key, gk, cfg), others, key, cfg)
    cq_ps = ref if ref is not None else score_part(key, _empty(key), cfg)
    bl = blame_mod.blame_part(ps, cq_ps, key, _json(ext_path) if ext_path else {}, ir, cfg, plan=plan)
    res = _part_result(ps, bl, ref)
    res["generated"] = generated.name
    res["extraction_found"] = ext_path is not None
    res["unresolved"] = blame_mod.unresolved_features(ir, plan)
    res["practices"] = prac
    if n > 1:
        res["multi_body"] = n
    return res, ps, bl


def summarise(results: list, scored: list) -> dict:
    ok = [r for r in results if not r.get("error")]
    scores = [r["score"] for r in ok]
    prac = [r["practices"]["score"] for r in ok if (r.get("practices") or {}).get("score") is not None]
    return {"n_scored": len(ok),
            "mean": statistics.fmean(scores) if scores else None,
            "median": statistics.median(scores) if scores else None,
            "exact_rate": (sum(1 for r in ok if r["exact"]) / len(ok)) if ok else None,
            "practices_mean": statistics.fmean(prac) if prac else None,   # separate; never blended
            "errors": [r["part"] for r in results if r.get("error")],
            "rollup": blame_mod.rollup(scored)}


def _prac_text(r: dict) -> str:
    s = (r.get("practices") or {}).get("score")
    return f"  practices {s:5.1f}" if s is not None else ""


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
    errors: dict[str, str] = {}
    for p in names:
        try:
            k = Key.load(keys_dir / p / "key.json")
        except Exception as e:               # malformed key: an error row, not a traceback
            errors[p] = f"unreadable key.json: {type(e).__name__}: {e}"
            continue
        if k.signed:
            keys[p] = k
        else:
            unsigned.append(p)

    # Where each generated part comes from; SolidWorks exports happen before anything is scored.
    generated: dict[str, Optional[Path]] = {}
    stale_parts: set = set()
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
            if stale:
                stale_parts.add(p)           # --no-sw: scored, but the SLDPRT is newer
        elif sld is not None:
            errors[p] = f"{sld.name} present but no {GENERATED} and --no-sw given"
        else:
            generated[p] = None
    # Feature trees for the practices score: read in the same SolidWorks pass as the exports.
    sldprts = {p: _sldprt(run / p) for p in keys if p not in errors}
    tree_need = [p for p, sld in sldprts.items() if sld is not None and sw_tree.is_stale(run / p, sld)]
    app, sw_note = None, ""
    if exports or (tree_need and not args.no_sw):
        try:
            app = sw_tasks.connect()
        except sw_tasks.SwUnavailable as e:
            if exports:
                print(f"SolidWorks needed to export {len(exports)} part(s) to STEP: {e}")
                return 3
            sw_note = f"SolidWorks unavailable, feature tree not read: {e}"   # practices only: not fatal
            print(sw_note)
        for p, sld, gen in exports:
            try:
                sw_tasks.sldprt_to_step(app, sld, gen, gen.with_suffix(".png"))
            except Exception as e:           # one bad part never stops the run
                errors[p] = f"STEP export failed: {type(e).__name__}: {e}"
    trees: dict[str, tuple[Optional[list], str]] = {}
    for p, sld in sldprts.items():
        if p in errors:
            continue
        if sld is None:
            trees[p] = (None, "no SLDPRT")
            continue
        try:
            tree = sw_tree.cached_tree(run / p, sld, None if args.no_sw else app)
        except Exception as e:               # a tree read failure never stops the run (practices only)
            trees[p] = (None, f"feature tree read failed: {type(e).__name__}: {e}")
            continue
        note = ""
        if tree is None:
            note = sw_note or "no cached feature tree (--no-sw)"
        elif sw_tree.is_stale(run / p, sld):
            note = f"stale {sw_tree.CACHE}: older than the SLDPRT"
        trees[p] = (tree, note)

    results, scored = [], []
    for p in names:
        if p in errors:
            results.append({"part": p, "score": None, "exact": False, "error": errors[p]})
            continue
        if p not in keys:
            continue
        key = keys[p]
        try:
            tree, tree_note = trees.get(p, (None, ""))
            res, ps, bl = score_one(p, run / p, key, generated[p], cfg, tree, tree_note)
        except Exception as e:               # unreadable STEP etc.: an error row, never a silent 0
            results.append({"part": p, "score": None, "exact": False, "error": f"{type(e).__name__}: {e}"})
            continue
        if p in stale_parts:
            res["stale"] = True
        results.append(res)
        scored.append((ps, bl))

    summary = summarise(results, scored)
    report.write_json(run / "scores.json", results, summary, unsigned, no_key)
    report.write_html(run / "report.html", results, summary, unsigned, no_key)
    for r in results:
        print(f"{r['part']:<14} " + (f"ERROR {r['error']}" if r.get("error")
                                     else f"{r['score']:6.1f}{'  exact' if r['exact'] else ''}"
                                     + _prac_text(r)))
    if unsigned:
        print(f"skipped (unsigned key): {', '.join(unsigned)}")
    if summary["n_scored"]:
        print(f"mean {summary['mean']:.1f}  median {summary['median']:.1f}  exact {summary['exact_rate']:.0%}"
              + (f"  practices mean {summary['practices_mean']:.1f}" if summary["practices_mean"] is not None
                 else ""))
    if summary["errors"]:
        return 1
    return 0 if results else 2               # every key unsigned: nothing scored


if __name__ == "__main__":
    sys.exit(main())
