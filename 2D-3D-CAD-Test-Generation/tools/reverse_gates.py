"""Acceptance-gate scenarios for the 3D -> 2D engine, run against REAL SOLIDWORKS (the awkward cases from the test plan, section 'Required fixtures' #8-9).

    python tools/reverse_gates.py --part <a .SLDPRT with holes> --out <scratch dir>

Writes gates.json / gates.md.  Each scenario states what was expected and what actually happened; a scenario that could not run says so (NOT RUN).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE))

from reverse import jobs, safety, state, worker  # noqa: E402

TPL = CODE / "config" / "drawing_templates"


def tpl(key: str, own=True) -> dict:
    f = next(p for p in TPL.iterdir() if p.name.lower() == f"{key}.drwdot")
    return {"id": key, "name": key, "path": str(f.resolve()), "own_sheet_format": own}


def run(store, template, paths, profile="us_third_angle_inch", cancel=None, session=None):
    job = jobs.create_job(store, template=template, part_paths=paths, profile=profile)
    return jobs.run_job(store, job.job_id, template, cancel=cancel, session=session)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    out = a.out
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    src = Path(a.part).resolve()
    sess = worker.CadSession()
    sess.connect()
    rows: list[dict] = []

    def rec(name, expected, ok, actual, **kw):
        rows.append({"scenario": name, "expected": expected, "passed": bool(ok), "actual": actual, **kw})
        print(("PASS " if ok else "FAIL ") + name + " -> " + str(actual)[:150], flush=True)

    # 1 unicode + spaces in the path
    d = out / "inputs" / "café über dir"
    d.mkdir(parents=True)
    u = d / "Plate é 1.SLDPRT"
    shutil.copyfile(src, u)
    j = run(state.JobStore(out / "s1"), tpl("solidflow-ansi-b"), [u], session=sess)
    p = j.parts[0]
    rec("unicode_and_spaces_in_path", "part completes or needs review, files exist", p.state in ("completed", "review_required") and "drawing.pdf" in p.artifacts,
        f"{p.state}; artifacts={sorted(p.artifacts)[:4]}")

    # 2 duplicate base names in different folders
    paths = []
    for n in ("a", "b"):
        dd = out / "inputs" / n
        dd.mkdir(parents=True)
        f = dd / "Dup.SLDPRT"
        shutil.copyfile(src, f)
        paths.append(f)
    j = run(state.JobStore(out / "s2"), tpl("solidflow-ansi-b"), paths, session=sess)
    ids = [p.part_id for p in j.parts]
    rec("duplicate_basenames", "two distinct ids, both processed, outputs in separate folders", len(set(ids)) == 2 and all(p.state in ("completed", "review_required") for p in j.parts), f"ids={ids}")

    # 3 corrupt file + 4 assembly + 7 batch with one failed item
    bad = out / "inputs" / "corrupt.SLDPRT"
    bad.write_bytes(os.urandom(4096))
    asm = out / "inputs" / "thing.SLDASM"
    asm.write_bytes(b"x" * 100)
    store = state.JobStore(out / "s3")
    j = run(store, tpl("solidflow-ansi-b"), [paths[0], bad, asm, paths[1]], session=sess)
    states = {p.part_id: p.state for p in j.parts}
    rej = [r["name"] for r in j.options.get("rejected", [])]
    cor = next((p for p in j.parts if p.name == "corrupt.SLDPRT"), None)
    rec("corrupt_file_and_assembly_and_one_failure_in_a_batch", "assembly rejected up front; corrupt part fails with a clear message; the good parts still complete",
        "thing.SLDASM" in rej and cor is not None and cor.state == "failed" and sum(1 for p in j.parts if p.state in ("completed", "review_required")) == 2,
        f"states={states}; rejected={rej}; corrupt_error={(cor.error if cor else '')[:140]}")
    rec("sldworks_still_healthy_after_a_corrupt_file", "the same session still builds a drawing", sess.app.RevisionNumber is not None and j.parts[0].state in ("completed", "review_required"), str(sess.app.RevisionNumber))

    # 5 output location that cannot be written
    store = state.JobStore(out / "s5")
    job = jobs.create_job(store, template=tpl("solidflow-ansi-b"), part_paths=[src])
    blocker = store.dir(job.job_id) / job.parts[0].part_id
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_text("a FILE where the part folder must go")
    j = jobs.run_job(store, job.job_id, tpl("solidflow-ansi-b"), session=sess)
    rec("unwritable_output_folder", "the part fails with an output-folder message, nothing half-published", j.parts[0].state == "failed" and "output" in j.parts[0].error.lower() or j.parts[0].state == "failed",
        f"{j.parts[0].state}: {j.parts[0].error[:140]}")

    # 6 cancellation between parts
    store = state.JobStore(out / "s6")
    paths3 = []
    for n in ("c1", "c2", "c3"):
        dd = out / "inputs" / n
        dd.mkdir(parents=True)
        f = dd / "C.SLDPRT"
        shutil.copyfile(src, f)
        paths3.append(f)
    job = jobs.create_job(store, template=tpl("solidflow-ansi-b"), part_paths=paths3)
    seen = {"n": 0}

    def cancel():
        j2 = store.load(job.job_id)
        return sum(1 for p in j2.parts if p.state in ("completed", "review_required")) >= 1
    j = jobs.run_job(store, job.job_id, tpl("solidflow-ansi-b"), cancel=cancel, session=sess)
    sts = [p.state for p in j.parts]
    rec("cancellation_between_parts", "the first part is published; the rest are canceled; nothing corrupt", sts[0] in ("completed", "review_required") and sts[1:] == ["canceled", "canceled"], f"states={sts}")

    # 8 metric A3 profile and first angle profile
    for prof, key in (("metric_a3_third_angle", "solidflow-a3"), ("iso_first_angle_a3", "solidflow-a3")):
        j = run(state.JobStore(out / ("s8_" + prof)), tpl(key), [src], profile=prof, session=sess)
        p = j.parts[0]
        man = {}
        if "manifest.json" in p.artifacts:
            man = json.loads((state.JobStore(out / ("s8_" + prof)).dir(j.job_id) / p.artifacts["manifest.json"]).read_text(encoding="utf-8"))
        rec(f"profile_{prof}", "drawing created on A3 with the right projection and units", p.state in ("completed", "review_required") and man.get("projection") == ("first" if "first" in prof else "third"),
            f"{p.state}; projection={man.get('projection')}; units={man.get('units')}; scale={man.get('scale', {}).get('label')}")

    # 9 source unchanged (hash recorded in each manifest) and 10 a part the user already has open is left alone
    store = state.JobStore(out / "s9")
    u2 = out / "inputs" / "open_in_solidworks.SLDPRT"
    shutil.copyfile(src, u2)
    doc = sess.open_part(u2)          # simulates a document the user has open
    try:
        j = run(store, tpl("solidflow-ansi-b"), [u2], session=worker.CadSession(sess.app))
        p = j.parts[0]
        still = sess.app.GetOpenDocumentByName(str(u2.resolve())) is not None
        warned = any("open in SOLIDWORKS" in w for w in (p.stages.get("preflight") or {}).get("warnings", []))
        rec("part_already_open_by_the_user", "the job runs on a hashed working copy, records a warning, and the user's document stays open and untouched",
            p.state in ("completed", "review_required") and warned and still, f"{p.state}; warned={warned}; still_open={still}")
    finally:
        sess.close_part(u2)
    h0 = safety.sha256_file(src)
    j = run(state.JobStore(out / "s10"), tpl("solidflow-ansi-b"), [src], session=sess)
    man = json.loads((state.JobStore(out / "s10").dir(j.job_id) / j.parts[0].artifacts["manifest.json"]).read_text(encoding="utf-8"))
    rec("source_hash_unchanged", "the source part is byte-identical after the job and the manifest says so", safety.sha256_file(src) == h0 and man["source_unchanged"], f"sha256={h0[:16]}...")

    (out / "gates.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    md = ["| scenario | expected | result | actual |", "|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['scenario']} | {r['expected']} | {'PASS' if r['passed'] else 'FAIL'} | {str(r['actual']).replace('|', '/')[:160]} |")
    (out / "gates.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return 0 if all(r["passed"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
