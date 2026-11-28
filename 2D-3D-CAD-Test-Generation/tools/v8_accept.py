"""v8 live acceptance driver: drawing replication in real SOLIDWORKS 2025. Evidence lands in docs/solidflow-upgrades/v8-evidence/<scenario>/ (files < 5 MB).

    python tools/v8_accept.py ring                 # A001651E flywheel ring (scan, dominant circular view, notes, leaders)
    python tools/v8_accept.py block holes batch2   # more parts (extractions are read from the cache when present; otherwise ONE paid call each)
    python tools/v8_accept.py list

Run from 2D-3D-CAD-Test-Generation with PYTHONUTF8=1. Source parts and PDFs are hashed before and after: a changed input fails the scenario. Paid calls only happen
when no cached extraction exists for a PDF (they go through the budget guard; this driver prints the ledger before and after).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.v7_env import REPO, make_service  # noqa: E402
from reverse import safety  # noqa: E402

EVID = REPO / "docs" / "solidflow-upgrades" / "v8-evidence"
FO = REPO / "FINAL_OUTPUTs"
SP = REPO / "data" / "inputs" / "simple_parts"
SMALL = 5 * 1024 * 1024

CASES = {
    "ring": {"part": FO / "A001651E" / "165-C_ir.SLDPRT", "pdf": SP / "A001651E.PDF"},
    "block": {"part": FO / "A001151E" / "115C_ir.SLDPRT", "pdf": SP / "A001151E.PDF"},
    "cbore": {"part": FO / "A001171E" / "117-C_ir.SLDPRT", "pdf": SP / "A001171E.PDF"},
    "b4028": {"part": FO / "A040281E" / "4028-B_ir.SLDPRT", "pdf": SP / "A040281E.PDF"},
    "multipage": {"part": FO / "A001651E" / "165-C_ir.SLDPRT", "pdf": EVID / "_fixtures" / "ring_2page.pdf"},
    "p116": {"part": FO / "A001161E" / "116-C_ir.SLDPRT", "pdf": SP / "A001161E.PDF"},
}


def budget_spent() -> float:
    from pipeline import budget
    return budget.spent_usd()


def collect(svc, job_id: str, name: str, extra: dict | None = None) -> dict:
    out = EVID / name
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    view = svc.job_view(job_id)
    base = svc.store.dir(job_id)
    summary = {"scenario": name, "job_id": job_id, "state": view["summary_state"], "parts": []}
    for p in view["parts"]:
        pdir = out / p["part_id"]
        rec = {"part": p["part_id"], "state": p["state"], "error": p["error"], "seconds": p.get("seconds"), "stages": {k: v.get("status") for k, v in p["stages"].items()},
               "replication": p.get("replication"), "usage": p.get("usage"), "timing": p.get("timing"), "estimate": p.get("estimate")}
        copied = []
        for key, f in p["files"].items():
            if not isinstance(f, dict) or "url_path" not in f:
                continue
            rel = f["url_path"]
            src = base / rel
            if not src.is_file() or src.suffix.lower() in (".sldprt", ".stl") or src.stat().st_size > SMALL:
                continue
            parts_ = rel.split("/", 2)
            dst = pdir / (parts_[2] if len(parts_) == 3 else rel)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            copied.append(str(dst.relative_to(out)))
        led = base / "usage" / "usage_ledger.jsonl"
        if led.is_file():
            (pdir / "usage").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(led, pdir / "usage" / "usage_ledger.jsonl")
        rec["files"] = copied
        summary["parts"].append(rec)
    (out / "job_view.json").write_text(json.dumps(view, indent=2, default=str), encoding="utf-8")
    summary.update(extra or {})
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    big = [str(f) for f in out.rglob("*") if f.is_file() and f.stat().st_size > SMALL]
    for b in big:
        Path(b).unlink()
    summary["removed_oversize"] = big
    return summary


def run_cases(names: list[str], scenario: str, work: Path, seed_cache: Path | None, options: dict | None = None) -> dict:
    import pythoncom
    from reverse import jobs
    pythoncom.CoInitialize()
    shutil.rmtree(work, ignore_errors=True)
    svc = make_service(work / "data", reference_roots=[])
    if seed_cache and seed_cache.is_dir():
        shutil.copytree(seed_cache, svc.refs.cache_root, dirs_exist_ok=True)
    parts, per, hashes = [], {}, {}
    for n in names:
        c = CASES[n]
        parts.append(c["part"])
        saved = svc.save_reference_pdf(str(c["pdf"]))
        assert saved["ok"], saved
        per[str(c["part"])] = {"source": "upload", "pdf_path": saved["pdf_path"]}
        hashes[str(c["part"])] = safety.sha256_file(c["part"])
        hashes[str(c["pdf"])] = safety.sha256_file(c["pdf"])
    reference = {"mode": "match", "per_part": per}
    est = svc.estimate_run(parts, reference)
    spent0 = budget_spent()
    tpl = svc.templates.get("solidflow-ansi-c")
    t0 = time.monotonic()
    job = jobs.create_job(svc.store, template=tpl, part_paths=parts, profile="us_third_angle_inch_c", options=dict(options or {}), reference=reference, refs=svc.refs,
                          authorized_roots=svc.roots + [svc.upload_dir])
    job.options["estimates"] = {p.part_id: svc._estimate_part_state(p) for p in job.parts if not (p.reference or {}).get("_blocked")}
    svc.store.save(job)
    jobs.run_job(svc.store, job.job_id, tpl, refs=svc.refs)
    wall = time.monotonic() - t0
    after = {k: safety.sha256_file(Path(k)) for k in hashes}
    summ = collect(svc, job.job_id, scenario, {"wall_s": round(wall, 1), "budget_before": spent0, "budget_after": budget_spent(), "inputs_unchanged": after == hashes,
                                              "estimate_run": est})
    return summ


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", nargs="*")
    ap.add_argument("--work", default=str(Path(os.environ.get("TEMP", ".")) / "v8_work"))
    ap.add_argument("--cache", default=str(EVID / "_cache"))
    ap.add_argument("--no-sections", action="store_true")
    a = ap.parse_args(argv)
    if not a.scenario or a.scenario == ["list"]:
        print(list(CASES))
        return 0
    opts = {"sections": not a.no_sections}
    names = [n for n in a.scenario if n in CASES]
    label = "_".join(names) if len(names) > 1 else names[0]
    summ = run_cases(names, label, Path(a.work) / label, Path(a.cache), opts)
    for p in summ["parts"]:
        rep = p.get("replication") or {}
        print(p["part"], p["state"], rep.get("status"), "-", rep.get("reason"))
    print("budget", summ["budget_before"], "->", summ["budget_after"], "| inputs unchanged:", summ["inputs_unchanged"], "| wall", summ["wall_s"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
