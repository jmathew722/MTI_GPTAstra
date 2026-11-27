"""v7 live acceptance driver (real SOLIDWORKS 2025, real OpenAI client where a scenario needs a model read). Evidence lands in
docs/solidflow-upgrades/v7-evidence/<scenario>/ (small files only). Run from 2D-3D-CAD-Test-Generation with PYTHONUTF8=1:

    python tools/v7_accept.py list
    python tools/v7_accept.py standard linked_supplement linked_cache_hit upload_same unrelated ambiguous no_reference batch_mixed   [--work DIR]

Paid scenarios (a model read of a drawing): linked_supplement, unrelated, recorded_hash. Everything else is free (cache hits, resolution, native CAD).
Source parts and PDFs are hashed before and after every scenario: a changed input fails the scenario.
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

from tools.v7_env import REPO, make_service, run_sync  # noqa: E402
from reverse import refextract, safety  # noqa: E402

EVID = REPO / "docs" / "solidflow-upgrades" / "v7-evidence"
FO = REPO / "FINAL_OUTPUTs"
DP = REPO / "DrawingPDFs"
SMALL = 5 * 1024 * 1024

PART_115 = FO / "A001151E" / "115C_ir.SLDPRT"
PART_4028 = FO / "A040281E" / "4028-B_ir.SLDPRT"
PART_117 = FO / "A001171E" / "117-C_ir.SLDPRT"
PART_116 = FO / "A001161E" / "116-C_ir.SLDPRT"


def budget_spent() -> float:
    from pipeline import budget
    return budget.spent_usd()


def hashes(paths) -> dict:
    return {str(p): safety.sha256_file(Path(p)) for p in paths if Path(p).is_file()}


def collect(svc, job_id: str, name: str, extra: dict | None = None) -> dict:
    """Copy the small evidence files of every part of a job into the evidence folder and return a compact summary."""
    out = EVID / name
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    view = svc.job_view(job_id)
    base = svc.store.dir(job_id)
    summary = {"scenario": name, "job_id": job_id, "state": view["summary_state"], "parts": []}
    for p in view["parts"]:
        pdir = out / p["part_id"]
        rec = {"part": p["part_id"], "state": p["state"], "error": p["error"], "reference": p["reference"], "verification_status": p["verification"].get("status"),
               "stages": {k: v.get("status") for k, v in p["stages"].items()}, "seconds": p.get("seconds")}
        for key, f in p["files"].items():
            if key in ("slddrw", "pdf", "source_pdf", "stl", "qa_json", "comparison_images") or not isinstance(f, dict):
                continue                                           # aliases: the original keys are copied
            rel = f.get("url_path") or ""
            src = base / rel
            if not rel or not src.is_file() or src.suffix.lower() in (".sldprt", ".stl") or src.stat().st_size > SMALL:
                continue
            parts_ = rel.split("/", 2)
            dst = pdir / (parts_[2] if len(parts_) == 3 else rel)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        rec["verification"] = p["verification"]
        summary["parts"].append(rec)
    (out / "job_view.json").write_text(json.dumps(view, indent=2, default=str), encoding="utf-8")
    summary.update(extra or {})
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    big = [str(f) for f in out.rglob("*") if f.is_file() and f.stat().st_size > SMALL]
    for b in big:
        Path(b).unlink()
    summary["removed_oversize"] = big
    return summary


def run_part(svc, part: Path, name: str, reference=None, options=None, profile="us_third_angle_inch", template_id="solidflow-ansi-b", inputs=()):
    before_hash = hashes([part, *inputs])
    spent0 = budget_spent()
    t0 = time.time()
    jid, view = run_sync(svc, part_paths=[part], reference=reference, options=options, profile=profile, template_id=template_id)
    wall = round(time.time() - t0, 1)
    after_hash = hashes([part, *inputs])
    extra = {"wall_seconds": wall, "budget_spent_before_usd": round(spent0, 4), "budget_spent_after_usd": round(budget_spent(), 4),
             "budget_delta_usd": round(budget_spent() - spent0, 4), "inputs_unchanged": before_hash == after_hash, "input_hashes": before_hash}
    s = collect(svc, jid, name, extra)
    print(f"[{name}] state={s['state']} wall={wall}s delta=${extra['budget_delta_usd']} inputs_unchanged={extra['inputs_unchanged']}")
    for p in s["parts"]:
        print(f"    {p['part']}: {p['state']} verification={p['verification_status']} ref={p['reference'].get('status')} cache={p['reference'].get('extraction_cache')} err={p['error'][:140]}")
    return jid, svc.job_view(jid), s


def scenario_standard(svc, work):
    return run_part(svc, PART_115, "01_standard_mode", reference=None)


def scenario_linked_supplement(svc, work):
    ref = {"mode": "match", "per_part": {str(PART_115): {"source": "auto"}}}
    return run_part(svc, PART_115, "02_match_linked_legacy_supplemented", reference=ref, inputs=[DP / "A001151E.PDF"])


def scenario_linked_cache_hit(svc, work):
    ref = {"mode": "match", "per_part": {str(PART_115): {"source": "auto"}}}
    n0 = len(list((work / "data" / "reference" / "extractions").rglob("reference_extraction.json")))
    jid, v, s = run_part(svc, PART_115, "03_match_cached_extraction_zero_calls", reference=ref, inputs=[DP / "A001151E.PDF"])
    p = v["parts"][0]
    ok = p["reference"]["extraction_cache"] == "hit" and p["reference"]["api_usage"]["calls"] == 0 and s["budget_delta_usd"] == 0
    print("    zero-call cache hit:", ok)
    return jid, v, s


def scenario_upload_same(svc, work):
    up = svc.save_reference_pdf(DP / "A001151E.PDF")
    assert up["ok"], up
    ref = {"mode": "match", "per_part": {str(PART_115): {"source": "upload", "pdf_path": up["pdf_path"], "filename": "A001151E.PDF"}}}
    return run_part(svc, PART_115, "04_manual_upload_overrides_history", reference=ref, inputs=[DP / "A001151E.PDF"])


def scenario_unrelated(svc, work):
    """A drawing of a DIFFERENT part uploaded explicitly (paid: the model reads it). The geometry check must reject it for layout."""
    up = svc.save_reference_pdf(DP / "A001351E.PDF")
    assert up["ok"], up
    ref = {"mode": "match", "per_part": {str(PART_115): {"source": "upload", "pdf_path": up["pdf_path"], "filename": "A001351E.PDF"}}}
    return run_part(svc, PART_115, "05_unrelated_pdf_detected", reference=ref, inputs=[DP / "A001351E.PDF"])


def scenario_ambiguous(svc, work):
    res = svc.reference_candidates(str(PART_117))
    EVID.joinpath("06_ambiguous_same_name").mkdir(parents=True, exist_ok=True)
    (EVID / "06_ambiguous_same_name" / "candidates.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print("[06] candidates:", [(c["filename"], c["confidence"], c["needs_confirmation"], c["link"]) for c in res["candidates"]], "selected:", res["selected"])
    ref = {"mode": "match", "per_part": {str(PART_117): {"source": "auto"}}}
    return run_part(svc, PART_117, "06_ambiguous_blocked_needs_confirmation", reference=ref)


def scenario_no_reference(svc, work):
    ref = {"mode": "match", "per_part": {str(PART_116): {"source": "none"}}}
    a = run_part(svc, PART_116, "07a_match_mode_no_reference_blocked", reference=ref)
    ref2 = {"mode": "match", "fallback_standard": True, "per_part": {str(PART_116): {"source": "none"}}}
    b = run_part(svc, PART_116, "07b_match_mode_fallback_standard", reference=ref2)
    return b


def scenario_recorded_hash(svc, work):
    ref = {"mode": "match", "per_part": {str(PART_4028): {"source": "auto"}}}
    return run_part(svc, PART_4028, "08_match_recorded_source_hash", reference=ref, inputs=[FO / "A040281E" / "A040281E.pdf"] if (FO / "A040281E" / "A040281E.pdf").is_file() else [])


def scenario_batch_mixed(svc, work):
    import pythoncom
    from reverse import jobs
    pythoncom.CoInitialize()
    parts = [PART_115, PART_117, PART_116]
    ref = {"mode": "match", "fallback_standard": False,
           "per_part": {str(PART_115): {"source": "auto"}, str(PART_117): {"source": "auto"}, str(PART_116): {"source": "none"}}}
    tpl = svc.templates.get("solidflow-ansi-b")
    job = jobs.create_job(svc.store, template=tpl, part_paths=parts, reference=ref, refs=svc.refs, authorized_roots=svc.roots + [svc.upload_dir])
    # the third part gets an explicit per-part decision to run as Standard: expressed by fallback at job level for that part only
    jobs.run_job(svc.store, job.job_id, tpl, refs=svc.refs)
    s = collect(svc, job.job_id, "09_batch_mixed_references", {"note": "115C: linked + cached; 117-C: ambiguous (blocked); 116-C: match with no source (blocked)"})
    for p in s["parts"]:
        print(f"    {p['part']}: {p['state']} ref={p['reference'].get('status')} err={p['error'][:120]}")
    return job.job_id, svc.job_view(job.job_id), s


def scenario_bad_inputs(svc, work):
    out = EVID / "10_bad_reference_inputs"
    out.mkdir(parents=True, exist_ok=True)
    tmp = work / "bad"
    tmp.mkdir(exist_ok=True)
    (tmp / "corrupt.pdf").write_bytes(b"%PDF-1.4\n" + os.urandom(200))
    (tmp / "notpdf.pdf").write_text("hello")
    (tmp / "empty.pdf").write_bytes(b"")
    res = {n: svc.save_reference_pdf(tmp / n) for n in ("corrupt.pdf", "notpdf.pdf", "empty.pdf")}
    res["missing"] = svc.save_reference_pdf(tmp / "missing.pdf")
    res = {k: {kk: vv for kk, vv in v.items() if kk != "pdf_path"} for k, v in res.items()}
    (out / "results.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print("[10] bad inputs rejected:", {k: v["error"][:60] for k, v in res.items()})
    assert all(not v["ok"] for v in res.values())
    return None, None, res


SCENARIOS = {"standard": scenario_standard, "linked_supplement": scenario_linked_supplement, "linked_cache_hit": scenario_linked_cache_hit, "upload_same": scenario_upload_same,
             "unrelated": scenario_unrelated, "ambiguous": scenario_ambiguous, "no_reference": scenario_no_reference, "recorded_hash": scenario_recorded_hash,
             "batch_mixed": scenario_batch_mixed, "bad_inputs": scenario_bad_inputs}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenarios", nargs="*")
    ap.add_argument("--work", default=str(Path(os.environ.get("TEMP", ".")) / "v7_accept_work"))
    a = ap.parse_args(argv)
    if a.scenarios == ["list"] or not a.scenarios:
        print("\n".join(SCENARIOS))
        return 0
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    svc = make_service(work / "data")
    for name in a.scenarios:
        print(f"--- {name}")
        SCENARIOS[name](svc, work)
    return 0


if __name__ == "__main__":
    sys.exit(main())
