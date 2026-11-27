"""Writes v7 3D -> 2D fixture jobs into an ISOLATED data dir (never the real one): python make_v7_fixture.py <data_dir> [reset]

What is real and what is not (kept honest on purpose):
  * model.stl, drawing.pdf and drawing.slddrw are COPIES of a real SOLIDWORKS-generated run found under FINAL_UI/data/outputs/3d-to-2d (a run made by a
    person on this machine; the originals are only read). If none exists the labelled fixture stand-ins from tests/server/reverse_fixtures.py are used
    and the manifest says so. The copies are used ONLY in this test seed and are never shipped.
  * the SOURCE (reference) PDFs are hand-generated test PDFs whose text says ORIGINAL SOURCE <part> (they are not real MTI drawings).
  * the job/part JSON (reference / verification blocks) is a TEST SEED shaped like docs/solidflow-upgrades/V7_CONTRACT.md section 4. It is not a
    result of the backend and proves only the UI's handling of such payloads.

Jobs (fixed ids so the specs can open them by URL):
  r3d_7000000000000001  flange completed+match(history, cached extraction, verification passed), bracket review_required+match(upload),
                        plate completed+standard (verification not run), cover failed (reference blocked), gone canceled
  r3d_7000000000000002  running: one part at native drawing (STL only) and one queued
  r3d_7000000000000003  one completed part with a PDF but NO SLDDRW (verification passed)
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
import reverse_fixtures as fx  # noqa: E402
from reverse import state  # noqa: E402

UI = Path(__file__).resolve().parents[3]
STAGES = list(state.STAGES)


def real_run() -> Path | None:
    for d in sorted((UI / "data" / "outputs" / "3d-to-2d").glob("*/*/active")):
        if all((d / n).is_file() for n in ("model.stl", "drawing.pdf", "drawing.slddrw")):
            return d
    return None


REAL = real_run()
T = "2026-11-27T09:00:00+00:00"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def stages(done: int, *, na=(), running=None, failed=None) -> dict:
    out = {}
    for i, s in enumerate(STAGES):
        if s in na:
            out[s] = {"status": "not_applicable", "warnings": [], "errors": [], "seconds": 0.0}
        elif failed == s:
            out[s] = {"status": "failed", "started": T, "ended": T, "warnings": [], "errors": ["REFERENCE_BLOCKED: no reference could be resolved"], "seconds": 0.4}
            break
        elif i < done:
            out[s] = {"status": "succeeded", "started": T, "ended": T, "warnings": [], "errors": [], "seconds": 3.0 + i}
        elif running == s:
            out[s] = {"status": "running", "started": T, "warnings": [], "errors": []}
    return out


def put_real(job_dir: Path, pid: str, *, slddrw=True, pdf=True, stl=True) -> None:
    base = job_dir / pid / "active"
    if REAL is None:
        return
    for name, on in (("model.stl", stl), ("drawing.pdf", pdf), ("drawing.slddrw", slddrw)):
        if on and (base / name).exists():
            shutil.copyfile(REAL / name, base / name)


def add_source(job_dir: Path, part: state.PartState, pages=2) -> bytes:
    data = fx.tiny_pdf(label=f"ORIGINAL SOURCE {part.part_id}", pages=pages)
    f = job_dir / part.part_id / "active" / "reference" / "source.pdf"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    part.artifacts["reference/source.pdf"] = f"{part.part_id}/active/reference/source.pdf"
    return data


def add_comparison(job_dir: Path, part: state.PartState) -> None:
    f = job_dir / part.part_id / "active" / "comparison" / "page-001.png"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(fx.tiny_png(240, 160))
    part.artifacts["comparison/page-001.png"] = f"{part.part_id}/active/comparison/page-001.png"


def drop_artifact(job_dir: Path, part: state.PartState, name: str) -> None:
    rel = part.artifacts.pop(name, None)
    if rel:
        (job_dir / rel).unlink(missing_ok=True)


def build(data: Path) -> None:
    store = state.JobStore(data / "outputs" / "3d-to-2d")
    # ---- job 1
    job = fx.write_job(data, "r3d_7000000000000001", [("flange.SLDPRT", "completed"), ("bracket.SLDPRT", "review"), ("plate.SLDPRT", "completed"), ("cover.SLDPRT", "failed"), ("gone.SLDPRT", "canceled")], created=T)
    jd = store.dir(job.job_id)
    for p in job.parts:
        pid = p.part_id
        if pid in ("flange", "bracket", "plate"):
            put_real(jd, pid)
    flange, bracket, plate, cover, gone = (job.part(x) for x in ("flange", "bracket", "plate", "cover", "gone"))
    flange.stages = stages(10)
    sf = add_source(jd, flange)
    flange.reference = {"mode": "match", "status": "resolved", "source_kind": "history", "filename": "flange-original.pdf", "sha256": sha(sf), "pages": 2, "link": "part_hash", "confidence": 0.98,
                        "reasons": ["Same SLDPRT SHA-256 as the forward run part"], "extraction_cache": "hit", "extraction_id": "ex1", "extraction_schema": "ref/1",
                        "api_usage": {"tokens": 0, "input_tokens": 0, "output_tokens": 0, "usd": 0.0, "calls": 0, "incremental": True, "historical_usd": 0.0412}, "warnings": []}
    flange.verification = {"status": "passed", "coverage": {"matched": 14, "total": 14, "unresolved": []}, "collisions": {"count": 0, "items": [], "clearance_mm": 1.5},
                           "iterations": {"used": 1, "max": 3, "best": 1, "history": []}}
    flange.state = "completed"
    bracket.stages = stages(10)
    bracket.stages["verification"]["status"] = "warning"
    sb = add_source(jd, bracket, pages=1)
    add_comparison(jd, bracket)
    bracket.reference = {"mode": "match", "status": "resolved", "source_kind": "upload", "filename": "bracket-customer.pdf", "sha256": sha(sb), "pages": 1, "extraction_cache": "fresh",
                         "api_usage": {"tokens": 5300, "input_tokens": 5000, "output_tokens": 300, "usd": 0.0317, "calls": 2, "incremental": True}, "warnings": ["Note N3 overlaps a view in the source drawing"]}
    bracket.verification = {"status": "review_required", "coverage": {"matched": 9, "total": 10, "unresolved": [{"id": "D7", "kind": "dimension", "text": "R12 not found in the model", "reason": "no matching geometry", "severity": "high"}]},
                            "collisions": {"count": 0, "items": [], "clearance_mm": 1.5}, "iterations": {"used": 3, "max": 3, "best": 2, "history": []}}
    plate.stages = stages(10, na=("reference_resolution", "extraction", "comparison_correction"))
    plate.reference = {"mode": "standard", "status": "not_applicable", "source_kind": "none", "warnings": []}
    plate.verification = {"status": "not_run"}
    cover.stages = stages(3, failed="reference_resolution")
    cover.stages["reference_resolution"]["status"] = "failed"
    cover.error = "REFERENCE_BLOCKED: no reference could be resolved for this part (2 candidates need confirmation)"
    cover.reference = {"mode": "match", "status": "blocked", "source_kind": "none", "warnings": ["Two same-name revisions need confirmation"]}
    cover.verification = {"status": "not_run"}
    for p in (flange, bracket, plate, cover, gone):
        p.artifacts = {k: v for k, v in p.artifacts.items() if (jd / v).is_file()}
    store.save(job)
    # ---- job 2 (running)
    job2 = fx.write_job(data, "r3d_7000000000000002", [("busy.SLDPRT", "processing"), ("later.SLDPRT", "queued")], created="2026-11-27T10:00:00+00:00")
    jd2 = store.dir(job2.job_id)
    put_real(jd2, "busy", slddrw=False, pdf=False)
    b = job2.part("busy")
    b.stages = stages(5, running="native_drawing")
    b.state = "native_drawing"
    b.reference = {"mode": "match", "status": "resolved", "source_kind": "history", "filename": "busy.pdf", "pages": 1, "extraction_cache": "supplemented", "api_usage": {"usd": 0.0102, "calls": 1}}
    store.save(job2)
    # ---- job 3 (PDF only)
    job3 = fx.write_job(data, "r3d_7000000000000003", [("pdfonly.SLDPRT", "completed")], created="2026-11-27T11:00:00+00:00")
    jd3 = store.dir(job3.job_id)
    po = job3.part("pdfonly")
    put_real(jd3, "pdfonly")
    drop_artifact(jd3, po, "drawing.slddrw")
    po.stages = stages(10, na=("reference_resolution", "extraction", "comparison_correction"))
    po.reference = {"mode": "standard", "status": "not_applicable", "source_kind": "none", "warnings": []}
    po.verification = {"status": "passed", "coverage": {"matched": 6, "total": 6, "unresolved": []}, "collisions": {"count": 0, "items": []}}
    store.save(job3)
    (data / "V7_SEED.json").write_text(json.dumps({"real_files_from": str(REAL.relative_to(UI)) if REAL else None,
        "note": "TEST SEED. Reference/verification blocks are shaped like V7_CONTRACT.md section 4; source PDFs are hand-generated test PDFs."}, indent=2), encoding="utf-8")


def main() -> int:
    data = Path(sys.argv[1])
    if len(sys.argv) > 2 and sys.argv[2] == "reset":
        shutil.rmtree(data / "outputs" / "3d-to-2d", ignore_errors=True)
    build(data)
    print("ok", "real files" if REAL else "fixture stand-ins")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
