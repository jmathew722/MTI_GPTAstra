"""Per-part 3D -> 2D engine: preflight -> STL -> inventory -> plan -> native drawing -> dimensions -> verification -> publish.

The source SLDPRT is never modified (hash compared before and after); the drawing references a COPY held in the job folder so the reference stays
resolvable; everything is built in ``_staging`` and only moved into place when it exists and was verified.  A part that finishes with any unresolved or
review-required item is ``review_required`` (software pass is not engineering approval).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Callable, Optional

from reverse import dimension, drawing, inventory, planner, qa, safety, state, worker

log = logging.getLogger(__name__)

# COM errors that mean "the session dropped", worth ONE clean restart of the part (never a retry on a half-mutated document)
TRANSIENT_HRESULTS = {-2147417848, -2147023170, -2147023174, -2147417851, -2147418113}


class Canceled(Exception):
    pass


def _is_transient(e: BaseException) -> bool:
    return getattr(e, "hresult", None) in TRANSIENT_HRESULTS or (e.args and e.args[0] in TRANSIENT_HRESULTS)


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def part_dir(job_dir: Path, part_id: str, config: str) -> Path:
    return Path(job_dir) / part_id / safety.safe_id(config or "active", "active")


def extra_views_needed(inv: dict, plan: dict) -> list[dict]:
    """Opposite-side hole views (Bottom/Back/Left) not already among front/top/right; each gets a rectangle in free sheet space."""
    have = {plan["views"].get("front"), plan["views"].get("top"), plan["views"].get("right")}
    need: list[str] = []
    for h in inv["holes"]:
        side = h["entry_side"] if h["entry_side"] in ("+", "-") else "+"
        v = dimension.VIEW_FOR_AXIS[(h["axis"], side)]
        if v not in have and v not in need:
            need.append(v)
    if not need:
        return []
    regions = {k: planner.Rect(*v) for k, v in plan["regions_m"].items()}
    scale = plan["scale"]["num"] / plan["scale"]["den"]
    ext = dict(zip("xyz", inv["size_m"]))
    placed = {k: planner.Rect(*v) for k, v in plan["rects_m"].items()}
    out = []
    gap = planner.GAP_MIN
    usable = regions["usable"]
    keep = [regions["title_block"].grow(gap * 0.3), regions["notes"].grow(gap * 0.3)]
    for sw_view in need:
        h_ax, v_ax, _ = planner.VIEWS[sw_view]
        spot, used = None, scale
        for factor in (1.0, 0.5, 0.25):       # a view at a smaller, labelled scale beats a missing view or a second sheet
            w, hh = ext[h_ax] * scale * factor + 2 * planner.VIEW_PAD, ext[v_ax] * scale * factor + 2 * planner.VIEW_PAD
            spot = planner.find_spot(w, hh, [r.grow(gap * 0.4) for r in placed.values()], keep, usable, gap)    # room for dimension lanes around every view
            if spot is not None:
                used = scale * factor
                break
        role = "extra_" + sw_view.strip("*").lower()
        if spot is None:
            out.append({"role": role, "sw_view": sw_view, "center": None, "fits": False})
            continue
        placed["extra_" + sw_view] = spot
        out.append({"role": role, "sw_view": sw_view, "center": ((spot.x0 + spot.x1) / 2, (spot.y0 + spot.y1) / 2), "fits": True, "rect": spot.as_list(), "scale": used})
    return out


class PartRunner:
    def __init__(self, session: worker.CadSession, store: state.JobStore, job: state.Job, part: state.PartState, template: dict,
                 cancel: Callable[[], bool] = lambda: False, source_authorized: Optional[Path] = None):
        self.s, self.store, self.job, self.part, self.template = session, store, job, part, template
        self.cancel = cancel
        self.src = Path(part.source)
        self.out = part_dir(store.dir(job.job_id), part.part_id, part.config)
        self.stage_dir = self.out / "_staging"
        self.inv: dict = {}
        self.plan: dict = {}
        self.issues: list[dict] = []
        self.ledger_json: dict = {}
        self.src_hash = ""
        self.material: dict = {}

    # ------------------------------------------------------------ helpers
    def _ev(self, kind: str, **kw) -> None:
        self.store.event(self.job.job_id, kind, self.part.part_id, **kw)

    def _check_cancel(self) -> None:
        if self.cancel():
            raise Canceled()

    def _stage(self, name: str, fn):
        self._check_cancel()
        state.begin_stage(self.part, name)
        self.store.save(self.job)
        self._ev("stage_start", stage=name)
        try:
            res = fn()
        except Canceled:
            state.end_stage(self.part, name, "failed", errors=["canceled"])
            raise
        except Exception as e:      # noqa: BLE001
            state.end_stage(self.part, name, "failed", errors=[f"{type(e).__name__}: {e}"])
            self._ev("stage_failed", stage=name, error=f"{type(e).__name__}: {e}")
            self.store.save(self.job)
            raise
        warn = list(self.part.stages.get(name, {}).get("warnings", []))
        state.end_stage(self.part, name, "warning" if warn else "succeeded")
        self._ev("stage_end", stage=name, status="warning" if warn else "succeeded")
        self.store.save(self.job)
        return res

    # ------------------------------------------------------------ the run
    def run(self) -> None:
        p = self.part
        p.started = state.now()
        p.attempts += 1
        try:
            self._run_once()
        except Canceled:
            self._cleanup()
            state.finish(p, "canceled")
            self._ev("canceled")
        except Exception as e:      # noqa: BLE001
            self._cleanup()
            if _is_transient(e) and p.attempts < 2:
                self._ev("transient_failure", error=str(e))
                shutil.rmtree(self.out, ignore_errors=True)
                p.stages.clear()
                p.state = "queued"
                self.run()          # one clean restart from scratch
                return
            log.exception("part %s failed", p.part_id)
            state.finish(p, "failed", f"{type(e).__name__}: {e}"[:400])
            self._ev("failed", error=p.error)
        self.store.save(self.job)

    def _cleanup(self) -> None:
        try:
            self.s.close_all_owned()
        except Exception:      # noqa: BLE001
            pass

    def _run_once(self) -> None:
        p = self.part
        out = self.out
        shutil.rmtree(out, ignore_errors=True)
        self.stage_dir.mkdir(parents=True, exist_ok=True)
        copy = self.stage_dir / "source" / (safety.safe_id(self.src.stem) + ".SLDPRT")

        # ---- 1 preflight
        def preflight():
            info = safety.check_part_file(self.src)
            why = safety.writable_dir(out)
            if why:
                raise worker.CadError(why)
            if not self.s.info.is_2025:
                p.stages["preflight"]["warnings"].append(f"SOLIDWORKS {self.s.info.revision} detected; this tool is validated on 2025 (major 33).")
            self.src_hash = safety.sha256_file(self.src)
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.src, copy)
            copy.chmod(0o444) if os.name != "nt" else None
            if safety.sha256_file(copy) != self.src_hash:
                raise worker.CadError("The working copy of the part does not match the source (copy failed).")
            return info
        self._stage("preflight", preflight)

        doc = None
        try:
            # ---- 2 mesh export
            def mesh():
                nonlocal doc
                doc = self.s.open_part(copy)
                cfgs = self.s.configurations(doc)
                self.s.activate_configuration(doc, p.config)
                self.config_used = self.s.active_configuration(doc)
                if p.config == "" and len(cfgs) > 1:
                    p.stages["mesh_export"]["warnings"].append(f"{len(cfgs)} configurations exist; only the active one ('{self.config_used}') is drawn. Run again for the others.")
                stl_path = self.stage_dir / "model.stl"
                rec = self.s.export_stl(doc, stl_path)
                self.box = self.s.body_box(doc)
                cmp_ = worker.compare_stl_to_native(rec, self.box)
                rec["native_comparison"] = cmp_
                _write_json(self.stage_dir / "stl_validation.json", rec)
                if not rec["ok"] or not cmp_["ok"]:
                    raise worker.CadError(f"The STL failed validation: {rec.get('errors') or cmp_}")
                try:   # Phase 1 provenance: the verified native material of the part, never invented
                    from pipeline.materials import native as nm
                    mat = nm.read_material(doc)
                    mp = nm.mass_properties(doc)
                    self.material = {"name": mat.get("name") or None, "library": mat.get("database") or None, "density_kg_m3": mp.get("density_kg_m3") if mat.get("name") else None,
                                     "mass_kg": mp.get("mass_kg") if mat.get("name") else None, "source": "native part (SetMaterialPropertyName2 read-back)",
                                     "status": "assigned" if mat.get("name") else "not_specified"}
                except Exception as e:      # noqa: BLE001
                    self.material = {"name": None, "status": "unread", "error": str(e)}
                return rec
            self._stage("mesh_export", mesh)

            # ---- 3 inventory
            def inv_stage():
                self.inv = inventory.build_inventory(self.s, doc, self.config_used)
                _write_json(self.stage_dir / "inventory.json", self.inv)
            self._stage("inventory", inv_stage)
            self.s.close_part(copy)
            doc = None
        finally:
            if doc is not None:
                self.s.close_part(copy)
                doc = None

        # ---- 4 planning
        def plan_stage():
            prof = self.job.profile
            self.plan = planner.plan_views(tuple(self.inv["size_m"]), prof, hole_axes=self.inv["hole_axes"])
            self.extra = extra_views_needed(self.inv, self.plan)
            self.plan["extra_views"] = self.extra
            for ev in self.extra:
                if not ev["fits"]:
                    self.issues.append(qa.issue("high", "EXTRA_VIEW_NO_ROOM", f"The {ev['sw_view']} view needed for opposite-side holes does not fit on sheet 1.", part_id=p.part_id,
                                                next_action="Use a larger sheet or add a second sheet."))
            if not self.plan["scale_fits"]:
                self.issues.append(qa.issue("high", "NO_SCALE_FITS", "No standard scale fits the views on this sheet.", part_id=p.part_id, next_action="Choose a larger sheet profile."))
            _write_json(self.stage_dir / "drawing_plan.json", self.plan)
        self._stage("planning", plan_stage)

        # ---- 5 drawing
        dd = drawing.DrawingDoc(self.s, copy, self.plan, Path(self.template["path"]), units=self.plan["units"], config=self.config_used,
                                own_sheet_format=bool(self.template.get("own_sheet_format")))
        try:
            def draw_stage():
                dd.create()
                import datetime
                nsp = "NOT SPECIFIED"
                mat = self.material.get("name") if self.material.get("status") == "assigned" else None
                perrs = dd.set_properties({
                    "SF_Company": str(self.job.options.get("company") or nsp), "SF_PartName": self.src.stem, "SF_PartNumber": self.src.stem,
                    "SF_Material": mat or nsp, "SF_Finish": nsp, "SF_Revision": nsp,
                    "SF_Units": "INCH" if self.plan["units"] == "inch" else "MILLIMETERS",
                    "SF_Projection": "THIRD ANGLE" if self.plan["projection"] == "third" else "FIRST ANGLE",
                    "SF_Status": "PRELIMINARY / FOR REVIEW", "SF_DrawnBy": nsp, "SF_CheckedBy": nsp, "SF_Date": datetime.date.today().isoformat(),
                    "SF_Source": self.src.name, "SF_Config": self.config_used})
                p.stages["drawing"]["warnings"] += perrs
                dd.set_sheet_scale()
                outlines = dd.build_plan_views([e for e in self.extra if e["fits"]])
                self.outlines = outlines
                # real view outlines must not overlap each other (hard fail, not silently accepted)
                rects = {k: planner.Rect(*v) for k, v in outlines.items()}
                names = list(rects)
                for i in range(len(names)):
                    for j in range(i + 1, len(names)):
                        if rects[names[i]].overlaps(rects[names[j]]):
                            self.issues.append(qa.issue("high", "VIEW_OVERLAP", f"Views {names[i]} and {names[j]} overlap on the sheet.", part_id=p.part_id,
                                                        next_action="Rescale or add a sheet."))
                reg = {k: planner.Rect(*v) for k, v in self.plan["regions_m"].items()}
                for k, r in rects.items():
                    if r.overlaps(reg["title_block"]) or r.overlaps(reg["notes"]):
                        self.issues.append(qa.issue("high", "VIEW_IN_TITLE_BLOCK", f"View {k} intrudes into the title block or notes area.", part_id=p.part_id))
                base = self.plan["scale"]["num"] / self.plan["scale"]["den"]
                for ev in self.extra:
                    if ev["fits"] and ev["role"] in dd.views:
                        r = rects[ev["role"]]
                        lbl = f"VIEW FROM {ev['sw_view'].strip('*').upper()}" + (f"  SCALE {drawing._ratio(ev['scale'])}" if abs(ev["scale"] - base) > 1e-9 else "")
                        dd.note(lbl, r.x0, r.y1 + 0.004)
                p.stages["drawing"]["warnings"] += dd.warnings
            self._stage("drawing", draw_stage)

            # ---- 6 dimensions
            def dim_stage():
                dm = dimension.Dimensioner(dd, self.inv, self.plan, part_id=p.part_id)
                res = dm.run()
                self.ledger_json = res["ledger"]
                self.issues += res["issues"]
                self.annotations = res["annotations"]
                p.coverage_pct = res["ledger"]["coverage"]["percent"]
                _write_json(self.stage_dir / "dimension_coverage.json", res["ledger"])
                p.stages["dimensioning"]["warnings"] += dd.warnings
            self._stage("dimensioning", dim_stage)

            # ---- 7 verification
            def verify():
                dd.save_drawing(self.stage_dir / "drawing.slddrw")
                dd.export_pdf(self.stage_dir / "drawing.pdf")
                sheets = dd.sheet_count()
                pdfq = qa.pdf_checks(self.stage_dir / "drawing.pdf", sheets, self.stage_dir / "preview")
                self.pdfq = pdfq
                if not pdfq["ok"]:
                    for k in ("nonblack_text", "text_overlaps", "text_clipped"):
                        for item in pdfq[k][:5]:
                            self.issues.append(qa.issue("high" if k != "nonblack_text" else "medium", k.upper(), f"PDF check {k}: {item}", part_id=p.part_id,
                                                        next_action="Fix the annotation style / layout."))
                    if pdfq["pages"] != sheets:
                        self.issues.append(qa.issue("high", "PDF_PAGES", f"PDF has {pdfq['pages']} pages for {sheets} sheets", part_id=p.part_id))
                    if pdfq["nonblack_strokes"]:
                        self.issues.append(qa.issue("medium", "NONBLACK_LINES", f"{pdfq['nonblack_strokes']} non-black strokes in the PDF", part_id=p.part_id,
                                                    next_action="Print is monochrome: review line colours."))
                _write_json(self.stage_dir / "pdf_check.json", {k: v for k, v in pdfq.items() if k != "previews"} | {"previews": pdfq["previews"]})
                self._reopen_check(self.stage_dir / "drawing.slddrw", copy)
                if safety.sha256_file(self.src) != self.src_hash:
                    raise worker.CadError("The source part changed while the job ran (hash mismatch).")
                p.stages["verification"]["warnings"] += dd.warnings
            self._stage("verification", verify)
        finally:
            dd.close()
            self.s.close_all_owned()

        # ---- 8 publish
        self._stage("publishing", self._publish)

    def _reopen_check(self, slddrw: Path, model_copy: Path) -> None:
        """Reopen the saved drawing: it must open, its views must reference the model (not dangling), and dimensions must still be attached."""
        T = self.s.typed
        res = T(self.s.app, "ISldWorks").OpenDoc6(str(slddrw), drawing.SW_DOC_DRW if hasattr(drawing, "SW_DOC_DRW") else 3, 1, "", 0, 0)
        d = res[0] if isinstance(res, tuple) else res
        info = {"opened": d is not None, "views": [], "dimensions": 0, "errors": []}
        if d is None:
            self.issues.append(qa.issue("critical", "REOPEN_FAILED", "The saved drawing could not be reopened.", part_id=self.part.part_id,
                                        next_action="Do not use this drawing; rerun."))
            _write_json(self.stage_dir / "reopen_check.json", info)
            return
        try:
            title = str(T(d, "IModelDoc2").GetTitle())
            self.s.opened[str(slddrw.resolve()).lower()] = title
            drw = T(d, "IDrawingDoc")
            v = drw.GetFirstView()          # the sheet itself
            v = T(v, "IView").GetNextView() if v is not None else None
            while v is not None:
                tv = T(v, "IView")
                ref = str(tv.GetReferencedModelName() or "")
                info["views"].append({"name": str(tv.GetName2()), "references": Path(ref).name, "ok": Path(ref).name.lower() == model_copy.name.lower()})
                try:
                    dds = tv.GetDisplayDimensions() or ()
                    info["dimensions"] += len(dds)
                except Exception:      # noqa: BLE001
                    pass
                v = tv.GetNextView()
            if not info["views"] or not all(x["ok"] for x in info["views"]):
                self.issues.append(qa.issue("critical", "DANGLING_VIEW", "A view does not reference the part after reopening.", part_id=self.part.part_id))
            info["sheets"] = int(drw.GetSheetCount())
        except Exception as e:      # noqa: BLE001
            info["errors"].append(f"{type(e).__name__}: {e}")
        finally:
            try:
                self.s.app.CloseDoc(title)
            except Exception:      # noqa: BLE001
                pass
            self.s.opened.pop(str(slddrw.resolve()).lower(), None)
        _write_json(self.stage_dir / "reopen_check.json", info)

    def _publish(self) -> None:
        p = self.part
        out = self.out
        sd = self.stage_dir
        ledger = self.ledger_json.get("coverage", {})
        hard = [i for i in self.issues if i["severity"] in ("critical",) or i["code"] in ("VALUE_MISMATCH", "PDF_PAGES", "DANGLING_VIEW", "REOPEN_FAILED", "VIEW_OVERLAP", "TEXT_OVERLAPS")]
        review = [i for i in self.issues if i["severity"] in ("critical", "high", "medium")] or any(
            it["status"] in ("review_required", "unresolved") for it in self.ledger_json.get("items", []))
        # artifact set: only what exists
        names = {"model.stl": "model.stl", "drawing.slddrw": "drawing.slddrw", "drawing.pdf": "drawing.pdf", "inventory.json": "inventory.json",
                 "drawing_plan.json": "drawing_plan.json", "dimension_coverage.json": "dimension_coverage.json", "stl_validation.json": "stl_validation.json",
                 "pdf_check.json": "pdf_check.json", "reopen_check.json": "reopen_check.json"}
        for n in names:
            src = sd / n
            if src.is_file():
                os.replace(src, out / n)
        if (sd / "preview").is_dir():
            shutil.rmtree(out / "preview", ignore_errors=True)
            os.replace(sd / "preview", out / "preview")
        qa_doc = {"part": p.part_id, "issues": self.issues, "coverage": ledger, "hard_failures": hard, "pdf": {k: v for k, v in getattr(self, "pdfq", {}).items() if k != "previews"},
                  "review_required": bool(review), "note": "Software QA is not engineering approval. This drawing is PRELIMINARY / FOR REVIEW until an authorized engineer dispositions the issues."}
        _write_json(out / "qa.json", qa_doc)
        files = {}
        for n in list(names) + ["qa.json"]:
            fp = out / n
            if fp.is_file():
                files[n] = {"bytes": fp.stat().st_size, "sha256": safety.sha256_file(fp)}
        for pv in sorted((out / "preview").glob("*.png")) if (out / "preview").is_dir() else []:
            files[f"preview/{pv.name}"] = {"bytes": pv.stat().st_size, "sha256": safety.sha256_file(pv)}
        manifest = {"schema_version": 1, "job_id": self.job.job_id, "part_id": p.part_id, "source_name": self.src.name, "source_sha256": self.src_hash,
                    "source_unchanged": safety.sha256_file(self.src) == self.src_hash, "configuration": getattr(self, "config_used", ""),
                    "solidworks": self.s.info.as_dict(), "template": {k: self.template.get(k) for k in ("id", "name", "sha256", "own_sheet_format")},
                    "profile": self.job.profile, "units": self.plan.get("units"), "projection": self.plan.get("projection"), "scale": self.plan.get("scale"),
                    "stl": {"unit": "mm", "transform": "none (the part is exported in its own coordinate system)"}, "material": self.material,
                    "stage_seconds": {k: v.get("seconds") for k, v in p.stages.items()}, "files": files, "review_status": "required" if review else "none",
                    "status": "review_required" if (review or hard) else "completed", "draft": True,
                    "note": "Draft output. Not approved for manufacture."}
        _write_json(out / "manifest.json", manifest)
        shutil.rmtree(sd, ignore_errors=True)
        rel = lambda n: str((Path(p.part_id) / safety.safe_id(p.config or "active", "active") / n).as_posix())
        p.artifacts = {n: rel(n) for n in files} | {"manifest.json": rel("manifest.json")}
        p.issues = self.issues
        p.material = self.material
        p.review_status = "required" if review else "none"
        state.finish(p, "review_required" if (review or hard) else "completed")
        self._ev("published", status=p.state, files=len(files))
