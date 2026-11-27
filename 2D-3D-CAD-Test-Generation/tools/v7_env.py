"""Test / acceptance environment for the v7 reverse service: a throw-away data directory whose template catalog is the repo's three generated Solid Flow
templates (config/drawing_templates), so a run needs no template generation and never touches FINAL_UI/data.

    from tools.v7_env import make_service
    svc = make_service(Path(scratch) / "v7data")
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEMPLATE_DIR = ROOT / "config" / "drawing_templates"


def template_entries() -> list[dict]:
    out = []
    for mf in sorted(TEMPLATE_DIR.glob("*.manifest.json")):
        d = json.loads(mf.read_text(encoding="utf-8"))
        stem = mf.name.replace(".manifest.json", "")
        drw = next(TEMPLATE_DIR.glob(stem + ".[dD][rR][wW][dD][oO][tT]"), None)
        if drw is None:
            continue
        d["path"] = str(drw)
        slddrt = TEMPLATE_DIR / (stem + ".slddrt")
        if slddrt.is_file():
            d["sheet_format_path"] = str(slddrt)
        pv = TEMPLATE_DIR / (stem + "_preview.pdf")
        if pv.is_file():
            d["preview_pdf"] = str(pv)
        d["available"] = True
        out.append(d)
    return out


def make_service(data_dir: Path, *, reference_roots=None, client=None, roots=None):
    from reverse.service import ReverseService
    data_dir = Path(data_dir)
    (data_dir / "templates").mkdir(parents=True, exist_ok=True)
    (data_dir / "templates" / "index.json").write_text(json.dumps({"schema_version": 1, "templates": template_entries()}, indent=2), encoding="utf-8")
    return ReverseService(data_dir, authorized_roots=roots or [REPO, Path.home() / "Downloads"], reference_roots=reference_roots, reference_client=client)


def run_sync(svc, *, part_paths, template_id="solidflow-ansi-b", profile="us_third_angle_inch", configs=None, reference=None, options=None):
    """submit() + run on THIS thread (COM initialised here); returns the finished job view. Same code path as the worker thread."""
    import pythoncom
    from reverse import jobs
    pythoncom.CoInitialize()
    tpl = svc.templates.get(template_id)
    job = jobs.create_job(svc.store, template=tpl, part_paths=[Path(p) for p in part_paths], profile=profile, configs=configs, options=dict(options or {}),
                          reference=reference, refs=svc.refs, authorized_roots=svc.roots + [svc.upload_dir])
    jobs.run_job(svc.store, job.job_id, tpl, refs=svc.refs)
    return job.job_id, svc.job_view(job.job_id)
