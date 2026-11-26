"""Reproducible command line for 3D -> 2D drawing generation (same code path as the UI).

    python -m reverse.cli run --parts a.SLDPRT b.SLDPRT --out outputs/3d-to-2d [--profile us_third_angle_inch] [--template path.drwdot]
    python -m reverse.cli run --folder parts/ [--recursive] --out ...
    python -m reverse.cli fixtures --out outputs/3d-to-2d-fixtures   # every authorized fixture, with summary.json / summary.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from reverse import jobs, safety, state


def stock_template() -> dict:
    """The installed stock drawing template, used until a generated template is selected."""
    from reverse import worker
    s = worker.CadSession()
    s.connect()
    p = s.typed(s.app, "ISldWorks").GetUserPreferenceStringValue(10)       # swDefaultTemplateDrawing
    return {"id": "stock-default", "name": "SOLIDWORKS stock drawing template", "path": p, "own_sheet_format": False, "sha256": safety.sha256_file(Path(p)) if p and Path(p).is_file() else ""}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="reverse.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--parts", nargs="*", default=[])
    r.add_argument("--folder")
    r.add_argument("--recursive", action="store_true")
    r.add_argument("--out", required=True)
    r.add_argument("--profile", default="us_third_angle_inch")
    r.add_argument("--template")
    r.add_argument("--own-sheet-format", action="store_true", help="the template is a Solid Flow generated one (keep its sheet format)")
    f = sub.add_parser("fixtures")
    f.add_argument("--src", required=True, help="folder of authorized .SLDPRT fixtures")
    f.add_argument("--out", required=True)
    f.add_argument("--profile", default="us_third_angle_inch")
    f.add_argument("--template")
    f.add_argument("--own-sheet-format", action="store_true")
    g = sub.add_parser("template")
    g.add_argument("--out", required=True)
    g.add_argument("--variant", default="solidflow-ansi-b")
    r.add_argument("--config", default="")
    a = ap.parse_args(argv)
    if a.cmd == "fixtures":
        a.cmd, a.parts, a.folder, a.recursive, a.config = "run", [], a.src, False, ""
    if a.cmd == "run":
        paths = [Path(p) for p in a.parts]
        if a.folder:
            paths += safety.discover_parts(Path(a.folder), a.recursive)
        store = state.JobStore(Path(a.out))
        tpl = ({"id": "cli-template", "name": Path(a.template).name, "path": a.template, "own_sheet_format": a.own_sheet_format} if a.template else stock_template())
        job = jobs.create_job(store, template=tpl, part_paths=paths, profile=a.profile, configs={str(p): a.config for p in paths})
        job = jobs.run_job(store, job.job_id, tpl)
        rows = [{"part": p.part_id, "state": p.state, "coverage_pct": p.coverage_pct, "error": p.error, "issues": len(p.issues),
                 "seconds": p.seconds, "artifacts": sorted(p.artifacts)} for p in job.parts]
        summ = {"job_id": job.job_id, "state": job.state, "solidworks": job.solidworks, "parts": rows}
        (store.dir(job.job_id) / "summary.json").write_text(json.dumps(summ, indent=2), encoding="utf-8")
        lines = ["| part | state | coverage % | issues | seconds | note |", "|---|---|---|---|---|---|"]
        for r in rows:
            cov = "n/a" if r["coverage_pct"] is None else f"{r['coverage_pct']:.1f}"
            lines.append(f"| {r['part']} | {r['state']} | {cov} | {r['issues']} | {r['seconds']} | {(r['error'] or '')[:80]} |")
        (store.dir(job.job_id) / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(json.dumps(summ, indent=2))
        return 0 if all(p.state in ("completed", "review_required") for p in job.parts) else 1
    if a.cmd == "template":
        from reverse import template_gen, worker
        s = worker.CadSession()
        s.connect()
        e = template_gen.generate(s, Path(a.out), a.variant)
        print(json.dumps({k: e[k] for k in ("id", "path", "sheet_format_path", "preview_pdf", "slddrt_saved", "warnings", "validation")}, indent=2, default=str))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
