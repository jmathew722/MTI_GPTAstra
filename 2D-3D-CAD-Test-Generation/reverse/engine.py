"""Per-part 3D -> 2D engine: preflight -> STL -> inventory -> plan -> native drawing -> dimensions -> verification -> publish.

The source SLDPRT is never modified (hash compared before and after); the drawing references a COPY held in the job folder so the reference stays
resolvable; everything is built in ``_staging`` and only moved into place when it exists and was verified.  A part that finishes with any unresolved or
review-required item is ``review_required`` (software pass is not engineering approval).
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import statistics
import time
from pathlib import Path
from typing import Callable, Optional

from reverse import compare, dimension, drawing, inventory, layout, planner, qa, refrun, safety, section_views, standards, state, worker

log = logging.getLogger(__name__)

# COM errors that mean "the session dropped", worth ONE clean restart of the part (never a retry on a half-mutated document)
TRANSIENT_HRESULTS = {-2147417848, -2147023170, -2147023174, -2147417851, -2147418113}


class Canceled(Exception):
    pass


try:
    from pipeline.budget import BudgetExceeded as _BudgetExceeded
except Exception:      # noqa: BLE001 - the pipeline package is always present in the repo; this only guards odd import paths
    class _BudgetExceeded(Exception):      # type: ignore[no-redef]
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
                 cancel: Callable[[], bool] = lambda: False, source_authorized: Optional[Path] = None, refs=None):
        self.s, self.store, self.job, self.part, self.template = session, store, job, part, template
        self.refs = refs
        self.ref_ex: Optional[dict] = None
        self.ref_pages: list = []
        self.replicating = False
        self.frame = None
        self.note_recs: list = []
        self.source_notes: set = set()
        self.note_text_ids: set = set()
        self.sheet_segments: list = []
        self.displacements: list = []
        self.rep_state: dict = {}
        self.replication: dict = {}
        self.extra_pages: list = []
        self.spec: Optional[dict] = None
        self.ref_pdf: Optional[Path] = None
        self.ref_sha = ""
        self.ref_applied = False
        self.comparison: Optional[dict] = None
        self.layout_rep: dict = {}
        self.final_measure: dict = {}
        self.carried: set = set()
        self.std = None
        self.profile_used = job.profile
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
        state.mark_started(p)
        p.attempts += 1
        try:
            self._run_once()
        except Canceled:
            self._cleanup()
            state.finish(p, "canceled")
            self._ev("canceled")
        except _BudgetExceeded as e:       # rule 12: the API budget stops the WHOLE run (this part fails, every remaining part is cancelled)
            self._cleanup()
            state.finish(p, "failed", f"API_BUDGET_STOP: {e}"[:400])
            self.job.cancel_requested = True
            self._ev("budget_stop", error=str(e))
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
        try:
            self.stage_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise worker.CadError(f"The output folder for this part could not be created or written ({type(e).__name__}). Check the output location and its permissions.") from None
        base = safety.safe_id(self.src.stem)
        try:
            titles = self.s.open_titles() if hasattr(self.s, "open_titles") else set()
        except Exception:      # noqa: BLE001
            titles = set()
        if base.lower() in titles:
            base = f"{base}__sf{self.job.job_id[-6:]}"        # the user has a part with this title open: a same-titled copy could not be opened
        copy = self.stage_dir / "source" / (base + ".SLDPRT")

        # ---- 1 preflight
        def preflight():
            info = safety.check_part_file(self.src)
            why = safety.writable_dir(out)
            if why:
                raise worker.CadError(why)
            if not self.s.info.is_2025:
                p.stages["preflight"]["warnings"].append(f"SOLIDWORKS {self.s.info.revision} detected; this tool is validated on 2025 (major 33).")
            self.src_hash = safety.sha256_file(self.src)
            try:     # the source is never opened by us (a hashed working copy is), but a user's open window may hold edits that are not on disk
                live = self.s.app.GetOpenDocumentByName(str(self.src.resolve()))
                if live is not None:
                    dirty = bool(self.s.typed(live, "IModelDoc2").GetSaveFlag())
                    msg = ("This part is open in SOLIDWORKS" + (" WITH UNSAVED CHANGES" if dirty else "") +
                           ": the drawing is made from the SAVED file on disk, and your open window was not touched.")
                    p.stages["preflight"]["warnings"].append(msg)
                    if dirty:
                        self.issues.append(qa.issue("high", "SOURCE_UNSAVED", msg, part_id=p.part_id, next_action="Save the part and run again if the edits should be drawn."))
            except Exception:      # noqa: BLE001
                pass
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
                    p.stages["stl_export"]["warnings"].append(f"{len(cfgs)} configurations exist; only the active one ('{self.config_used}') is drawn. Run again for the others.")
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
            self._stage("stl_export", mesh)

            # ---- 3 inventory
            self.inv = inventory.build_inventory(self.s, doc, self.config_used)          # part of the stl_export stage: same open document
            _write_json(self.stage_dir / "inventory.json", self.inv)
            p.stages["stl_export"]["inventory"] = {"holes": len(self.inv.get("holes", [])), "size_m": self.inv.get("size_m")}
            self.s.close_part(copy)
            doc = None
        finally:
            if doc is not None:
                self.s.close_part(copy)
                doc = None

        # ---- reference stages (v7): resolution + extraction, or "not applicable" in Standard mode
        ref_mode = refrun.ref_mode_active(p)
        self.ref_applied = False
        if not ref_mode:
            for st_ in state.REFERENCE_STAGES:
                state.mark_not_applicable(p, st_, "Standard mode: no reference drawing" if p.reference.get("status") != "fallback_standard" else "Standard mode (fallback): see reference warnings")
            self.store.save(self.job)
        else:
            if self.refs is None:
                raise worker.CadError("REFERENCE_BLOCKED: reference matching is not configured on this server.")
            self._stage("reference_resolution", lambda: refrun.stage_reference_resolution(self))
            self._stage("extraction", lambda: refrun.stage_extraction(self))
            self.job.actual_api_cost_usd = round(float(self.job.actual_api_cost_usd or 0) + float((p.reference.get("api_usage") or {}).get("usd", 0.0)), 4)
            default_unit = "inch" if self.job.profile in ("us_third_angle_inch", "us_third_angle_inch_c") else "mm"
            chk = refrun.compatibility(self.ref_ex, self.inv, default_unit)
            p.reference["geometry_check"] = chk
            if chk["status"] == "incompatible":
                p.reference["status"] = "rejected_unrelated"
                p.reference["warnings"].append("The reference drawing does not look like this part (its printed dimensions are not found among the model's sizes); "
                                               "it was not used for layout. Check that the right drawing was selected.")
                self.issues.append(qa.issue("high", "REFERENCE_UNRELATED", f"The reference drawing does not match this part: {chk['matched']} of {chk['compared']} printed dimensions "
                                            "exist on the model and none of its overall sizes.", part_id=p.part_id, next_action="Select the correct drawing, or run in Standard mode."))
                self.ref_applied = False
            else:
                self.ref_applied = True
                if chk["status"] == "uncertain":
                    p.reference["warnings"].append(f"Only {chk['matched']} of {chk['compared']} printed dimensions were found on the model; verify this is the right drawing.")
            _write_json(self.stage_dir / "reference" / "geometry_check.json", chk)

        # ---- 4 planning
        def plan_stage():
            self.plan = refrun.plan_with_reference(self)
            self.extra = [] if self.plan.get("replication") else extra_views_needed(self.inv, self.plan)       # replication: only the source's views
            self.plan["extra_views"] = self.extra
            for ev in self.extra:
                if not ev["fits"]:
                    self.issues.append(qa.issue("high", "EXTRA_VIEW_NO_ROOM", f"The {ev['sw_view']} view needed for opposite-side holes does not fit on sheet 1.", part_id=p.part_id,
                                                next_action="Use a larger sheet or add a second sheet."))
            if not self.plan["scale_fits"]:
                self.issues.append(qa.issue("high", "NO_SCALE_FITS", "No standard scale fits the views on this sheet.", part_id=p.part_id, next_action="Choose a larger sheet profile."))
            _write_json(self.stage_dir / "drawing_plan.json", self.plan)
        self._stage("view_planning", plan_stage)
        from reverse import replicate
        self.replicating = bool(self.ref_applied and replicate.active(self) and (self.plan.get("replication") is not None))

        # ---- 5 drawing
        dd = drawing.DrawingDoc(self.s, copy, self.plan, Path(self.template["path"]), units=self.plan["units"], config=self.config_used,
                                own_sheet_format=bool(self.template.get("own_sheet_format")))
        try:
            def draw_stage():
                dd.create()
                if self.plan.get("replication") and self.sheet_segments:
                    # BEFORE any view exists: with a view active a sketch is created in the VIEW's frame (scaled and offset), not on the sheet
                    n_lines = dd.sheet_lines(self.sheet_segments)
                    p.stages["native_drawing"]["sheet_geometry"] = {"segments_drawn": n_lines, "segments_planned": len(self.sheet_segments), **self.sheet_seg_report}
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
                p.stages["native_drawing"]["warnings"] += perrs
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
                dd.set_sheet_scale()          # AFTER the views exist: creating a view resets the sheet scale (title block SCALE field)
                base = self.plan["scale"]["num"] / self.plan["scale"]["den"]
                self.secs = []
                if self.job.options.get("sections", True) and not self.plan.get("replication"):
                    placed = dict(rects)
                    self.secs = section_views.create_sections(dd, self.inv, self.plan, placed, self.issues, p.part_id)
                    for s_ in self.secs:
                        if s_.get("fits") and s_["role"] in dd.views:
                            rects[s_["role"]] = placed[s_["role"]]
                self.plan["sections"] = [{k: v for k, v in s_.items() if k != "plan"} | {"cut": {k: s_["plan"][k] for k in ("axis", "entry_side", "cut_along", "at_axis", "at_m")}} for s_ in self.secs]
                for ev in self.extra:
                    if ev["fits"] and ev["role"] in dd.views:
                        r = rects[ev["role"]]
                        lbl = f"VIEW FROM {ev['sw_view'].strip('*').upper()}" + (f"  SCALE {drawing._ratio(ev['scale'])}" if abs(ev["scale"] - base) > 1e-9 else "")
                        dd.note(lbl, r.x0, r.y1 + 0.004)
                # v7 standard: the isometric is Shaded With Edges (verified by read-back here and by the PDF later)
                self.std = standards.Standards(dd)
                rz = {k: planner.Rect(*v) for k, v in self.plan["regions_m"].items()}
                self.std.template_zones = [(rz["title_block"].x0, rz["title_block"].y0, rz["title_block"].x1, rz["title_block"].y1),
                                           (rz["notes"].x0, rz["notes"].y0, rz["notes"].x1, rz["notes"].y1)]
                iso = self.std.apply_iso_style()
                p.stages["native_drawing"]["iso"] = iso
                for v_ in iso["views"]:
                    if not v_.get("applied"):
                        self.issues.append(qa.issue("high", "ISO_NOT_SHADED_WITH_EDGES", f"The isometric view could not be set to Shaded With Edges ({v_.get('error') or v_.get('label')}).", part_id=p.part_id))
                p.stages["native_drawing"]["warnings"] += dd.warnings
                _write_json(self.stage_dir / "drawing_plan.json", self.plan)          # now including the sections that were actually created
            self._stage("native_drawing", draw_stage)

            # ---- 6 dimensions + leaders + layout (measured, bounded)
            def dim_stage():
                dm = dimension.Dimensioner(dd, self.inv, self.plan, part_id=p.part_id)
                dm.sections = getattr(self, "secs", [])
                dm.section_cover = {hid for s_ in dm.sections if s_.get("fits") for hid in s_["hole_ids"]}
                res = dm.run()
                reg_u = planner.Rect(*self.plan["regions_m"]["usable"])
                res["layout_repair"] = dm.repair_layout(reg_u)
                _write_json(self.stage_dir / "layout_repair.json", res["layout_repair"])
                self.ledger_json = res["ledger"]
                self.issues += res["issues"]
                self.annotations = res["annotations"]
                p.coverage_pct = res["ledger"]["coverage"]["percent"]
                _write_json(self.stage_dir / "dimension_coverage.json", res["ledger"])
                p.stages["dimensioning_layout"]["warnings"] += dd.warnings
                # standards: leader text style on leadered dimensions, black annotations
                lead = self.std.apply_leader_style()
                for f_ in lead["failed"]:
                    self.issues.append(qa.issue("medium", "LEADER_STYLE_NOT_APPLIED", f"Broken leader / horizontal text could not be verified on {f_.get('id')}.", part_id=p.part_id))
                blk = self.std.ensure_black()
                for bid in blk["failed"]:
                    self.issues.append(qa.issue("medium", "ANNOTATION_NOT_BLACK", f"Annotation {bid} was not black.", part_id=p.part_id))
                self.inv_before_layout = self.std.inventory()
                if self.replicating:
                    self.carried = refrun.place_source_notes(self, dd, self.std)
                else:
                    self.carried = refrun.add_reference_notes(self, dd) if self.ref_applied else set()
                self.layout_rep = refrun.layout_loop(self, dd, self.std)
                _write_json(self.stage_dir / "layout_report.json", self.layout_rep)
                for c in self.layout_rep.get("unresolved", []):
                    self.issues.append(qa.issue("high", "COLLISION_" + c["kind"].upper(), f"{c['kind']}: {c.get('a_text', '')} {c.get('b_text', '')} {c.get('detail', '')}".strip(),
                                                part_id=p.part_id, next_action="Move the annotation manually; evidence is in layout_report.json."))
                p.stages["dimensioning_layout"]["standards"] = self.std.report
            self._stage("dimensioning_layout", dim_stage)

            # ---- 7 comparison + bounded correction (reference mode only)
            if self.ref_applied:
                self._stage("comparison_correction", (lambda: self._replication(dd)) if self.replicating else (lambda: self._comparison(dd)))
            else:
                state.mark_not_applicable(p, "comparison_correction", "Standard mode: nothing to compare against" if p.reference.get("mode") != "match" else
                                          "No reference was applied to this part")
                self.comparison = None

            # ---- 8 verification
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
                self._final_measure(dd, self.stage_dir / "drawing.pdf")
                if self.replicating:
                    self._replication_live_reads(dd)          # BEFORE the reopen: reopening the saved file returns the already-open document and closing it disconnects ours
                self.reopen_info = self._reopen_check(self.stage_dir / "drawing.slddrw", copy)
                if self.replicating:
                    self._replication_report(dd, self.stage_dir / "drawing.pdf")
                if safety.sha256_file(self.src) != self.src_hash:
                    raise worker.CadError("The source part changed while the job ran (hash mismatch).")
                p.stages["verification"]["warnings"] += dd.warnings
            self._stage("verification", verify)
        finally:
            dd.close()
            self.s.close_all_owned()
            shutil.rmtree(self.stage_dir / "_iter", ignore_errors=True)

        # ---- 9 publish
        self._stage("publish", self._publish)

    # ------------------------------------------------------------ v7 helpers
    def _comparison(self, dd) -> None:
        """Semantic + spatial comparison, then bounded repositioning toward the reference (collisions take priority; best revision kept)."""
        p, st = self.part, self.std
        max_iter = int(self.job.options.get("max_iterations", refrun.DEFAULT_ITERATIONS))
        pdf, pages, err = refrun.export_measure(self, dd, st, "cmp0")
        if err:
            raise worker.CadError(err)
        outl = refrun.outlines(self, dd)
        cmp_ = refrun.run_comparison(self, dd, st, pages, self.carried)
        ours = getattr(self, "best_ours", None)
        col = refrun.detect_now(self, dd, st, pages, outl, ours)
        best = {"cs": layout.score(col), "ss": compare.spatial_score(cmp_["spatial"]), "snap": refrun.snapshot(st), "cmp": cmp_, "col": col, "pdf": pdf, "pages": pages}
        hist = [{"iteration": 0, "what": "as laid out", "collisions": len(col), "spatial_mean_mm": round(best["ss"], 2)}]
        for it in range(1, max_iter + 1):
            self._check_cancel()
            mv = refrun.reposition_toward_reference(self, dd, st, best["cmp"]["semantic"], best["cmp"]["spatial"], best["pages"])
            if not mv["moves"]:
                hist.append({"iteration": it, "what": "no safe reposition available", "skipped": mv["skipped"][:10]})
                break
            pdf2, pages2, err2 = refrun.export_measure(self, dd, st, f"cmp{it}")
            if err2:
                refrun.restore_snapshot(dd, st, best["snap"])
                break
            snap2 = refrun.snapshot(st)
            t2a = refrun.map_all(pages2[0].texts, snap2)
            self.best_t2a = t2a
            self.best_ours = set(t2a.values()) | (ours or set())
            cmp2 = refrun.run_comparison(self, dd, st, pages2, self.carried)
            col2 = refrun.detect_now(self, dd, st, pages2, outl, self.best_ours)
            cs2, ss2 = layout.score(col2), compare.spatial_score(cmp2["spatial"])
            entry = {"iteration": it, "what": "moved toward reference anchors", "moved": len(mv["moves"]), "collisions": len(col2), "spatial_mean_mm": round(ss2, 2),
                     "moves": mv["moves"][:20], "skipped": mv["skipped"][:10]}
            hist.append(entry)
            if cs2 <= best["cs"] and ss2 < best["ss"] - 0.05:
                best = {"cs": cs2, "ss": ss2, "snap": snap2, "cmp": cmp2, "col": col2, "pdf": pdf2, "pages": pages2}
            else:
                entry["rejected"] = "no measured improvement without adding collisions; positions restored to the best revision"
                refrun.restore_snapshot(dd, st, best["snap"])
                self.best_t2a = refrun.map_all(best["pages"][0].texts, best["snap"])
                break
        refrun.restore_snapshot(dd, st, best["snap"])
        self.comparison = best["cmp"]
        self.comparison["iterations"] = {"used": len([h for h in hist if h["iteration"] > 0]), "max": max_iter, "history": hist}
        # evidence images
        cdir = self.stage_dir / "comparison"
        W, H = refrun.sheet_dims(self)
        try:
            pdf3, pages3, _ = refrun.export_measure(self, dd, st, "cmp_final")
            col3 = refrun.detect_now(self, dd, st, pages3, outl, getattr(self, "best_ours", None))
            compare.render_side_by_side(self.ref_pdf, pdf3, cdir / "page-001.png", ref_ex=self.ref_ex, collisions_boxes_mm=[c.box_a_mm for c in col3 if c.box_a_mm], W=W, H=H)
        except Exception as e:      # noqa: BLE001
            p.stages["comparison_correction"]["warnings"].append(f"comparison image: {type(e).__name__}: {e}")
        led = self.comparison["semantic"]
        _write_json(cdir / "comparison.json", {"semantic": led, "spatial": self.comparison["spatial"], "iterations": self.comparison["iterations"], "reference_layout": self.plan.get("reference_layout")})
        for e in led["ledger"]:
            if e.get("required") and e["status"] in ("value_differs",):
                self.issues.append(qa.issue("high", "REFERENCE_VALUE_DIFFERS", f"{e['text']}: {e['reason']}", part_id=p.part_id, source_ref=e.get("ref_id", ""), expected=e.get("expected") or "",
                                            observed=e.get("observed") or "", next_action="The drawing shows the model's true value. Confirm which is right (the model or the reference)."))
        unresolved_req = [e for e in led["ledger"] if e.get("required") and e["status"] in ("missing", "unresolved_requirement", "unit_unknown", "page_not_reconstructed")]
        if unresolved_req:
            self.issues.append(qa.issue("high", "REFERENCE_ITEMS_UNRESOLVED", f"{len(unresolved_req)} required reference item(s) are not on the generated drawing; see the comparison ledger.", part_id=p.part_id,
                                        next_action="Review comparison/comparison.json; add the missing dimensions manually or confirm they are not needed."))
        if any(e["status"] == "tolerance_not_applied" for e in led["ledger"]):
            self.issues.append(qa.issue("medium", "REFERENCE_TOLERANCES_NOT_APPLIED", "The reference prints tolerances; tolerances are never invented or applied automatically.", part_id=p.part_id,
                                        next_action="An engineer applies tolerances deliberately; the printed text is in the ledger."))
        if led["material"]["status"] == "mismatch":
            self.issues.append(qa.issue("high", "REFERENCE_MATERIAL_MISMATCH", led["material"].get("note", "Material mismatch"), part_id=p.part_id))
        elif led["material"]["status"] == "reference_only":
            self.issues.append(qa.issue("medium", "REFERENCE_MATERIAL_UNASSIGNED", led["material"].get("note", ""), part_id=p.part_id))
        for dev in (self.plan.get("reference_layout") or {}).get("deviations", []):
            self.issues.append(qa.issue("low", "REFERENCE_LAYOUT_DEVIATION", dev, part_id=p.part_id))

    def _replication(self, dd) -> None:
        """Closed loop in replication mode: source-coordinate placement, measured correction (default 3 iterations), evidence. See reverse/replicate.py."""
        p, st = self.part, self.std
        hist = refrun.replication_loop(self, dd, st)
        if len(self.ref_pages) > 1:
            self.extra_pages = refrun.build_extra_sheets(self, dd)
            pdf_x, pages_x, err_x = refrun.export_measure(self, dd, st, "rep_pages")
            refrun.refine_extra_sheet_notes(self, dd, pages_x)
            p.stages["comparison_correction"]["extra_sheets"] = [{k: v for k, v in x.items() if k in ("page", "status", "error", "scale_basis")} for x in self.extra_pages]
        led = self.comparison["semantic"]
        cdir = self.stage_dir / "comparison"
        _write_json(cdir / "comparison.json", {"semantic": led, "spatial": self.comparison["spatial"], "iterations": self.comparison["iterations"], "reference_layout": self.plan.get("reference_layout"),
                                               "displacements": self.displacements})
        p.stages["comparison_correction"]["iterations"] = {k: hist.get(k) for k in ("used", "max", "best", "stop_reason")}
        for e in led["ledger"]:
            if e.get("required") and e["status"] in ("value_differs",):
                self.issues.append(qa.issue("high", "REFERENCE_VALUE_DIFFERS", f"{e['text']}: {e['reason']}", part_id=p.part_id, source_ref=e.get("ref_id", ""), expected=e.get("expected") or "",
                                            observed=e.get("observed") or "", next_action="The drawing shows the model's true value. Confirm which is right (the model or the reference)."))
        miss = [e for e in led["ledger"] if e.get("required") and e["status"] in ("missing", "unit_unknown")]
        if miss:
            self.issues.append(qa.issue("high", "REFERENCE_ITEMS_UNRESOLVED", f"{len(miss)} required source item(s) are not on the generated drawing; see comparison/comparison.json.", part_id=p.part_id,
                                        next_action="Review the ledger; add the missing dimensions manually or confirm they are not needed."))
        srcn = [e for e in led["ledger"] if e["status"] == "source_note" and e.get("severity") in ("medium", "high")]
        if srcn:
            self.issues.append(qa.issue("medium", "SOURCE_ONLY_CALLOUTS", f"{len(srcn)} source callout(s) were reproduced as editable non-associative notes (hole / GD&T / finish / unmatched dimensions); "
                                        "an engineer must confirm them against the model.", part_id=p.part_id, next_action="Review comparison/comparison.json (status source_note)."))
        if any(e["status"] == "tolerance_not_applied" for e in led["ledger"]):
            self.issues.append(qa.issue("medium", "REFERENCE_TOLERANCES_NOT_APPLIED", "The source prints tolerances; tolerances are never invented or applied automatically (the printed text is on the sheet as a note).",
                                        part_id=p.part_id, next_action="An engineer applies tolerances deliberately."))
        if led["material"]["status"] == "mismatch":
            self.issues.append(qa.issue("high", "REFERENCE_MATERIAL_MISMATCH", led["material"].get("note", "Material mismatch"), part_id=p.part_id))
        elif led["material"]["status"] == "reference_only":
            self.issues.append(qa.issue("medium", "REFERENCE_MATERIAL_UNASSIGNED", led["material"].get("note", ""), part_id=p.part_id))
        for dev in (self.plan.get("reference_layout") or {}).get("deviations", []):
            self.issues.append(qa.issue("low", "REFERENCE_LAYOUT_DEVIATION", dev, part_id=p.part_id))

    def _replication_live_reads(self, dd) -> None:
        """Everything the report needs from the live document: per-view generated scales and every sheet's scale (read back from SOLIDWORKS)."""
        from reverse import replicate
        live = {"view_scales": [], "sheet_scales": {}}
        try:
            dd.activate_sheet("Sheet1")
            live["view_scales"] = replicate.view_scale_checks(self.ref_ex, dd, self.plan)
            for xr in self.extra_pages:
                if xr.get("status") == "built":
                    dd.activate_sheet(xr["name"])
                    pr_ = self.s.typed(dd.drw.GetCurrentSheet(), "ISheet").GetProperties2()
                    live["sheet_scales"][xr["name"]] = [pr_[2], pr_[3]]
            dd.activate_sheet("Sheet1")
        except Exception as e:      # noqa: BLE001
            live["error"] = f"{type(e).__name__}: {e}"
        self.live_reads = live

    def _replication_report(self, dd, pdf: Path) -> None:
        """Measured replication report on the EXPORTED pdf and the reopened drawing: scales, view centres, annotation anchors, verbatim notes, clipping, sheets,
        evidence images, and the status decision (verified only from measured evidence)."""
        from reverse import replicate
        from reverse.reflayout import parse_scale
        p, ex = self.part, self.ref_ex
        th = replicate.thresholds({"replication_thresholds": self.job.options.get("replication_thresholds")})
        pages = layout.measure_pdf(pdf)
        rs = self.rep_state or {}
        vdev, adev = rs.get("vdev", []), rs.get("adev", [])
        col = rs.get("col", [])
        med = lambda xs: round(statistics.median(xs), 2) if xs else None
        # ---- scales
        src_sheet = parse_scale(ex.get("sheet", {}).get("scale_text", ""))
        rec_ = dd.sheet_scale_record or {}
        gen_sheet = tuple(rec_.get("readback") or ()) or None
        reop = getattr(self, "reopen_info", {}) or {}
        if reop.get("sheet_scale"):
            gen_sheet = (reop["sheet_scale"][0], reop["sheet_scale"][1])            # the REOPENED drawing's value is the evidence
        tb_text = replicate.title_block_scale_from_pdf(pdf)
        scale_note = next((x for x in self.note_recs if re.search(r"\bSCALE\b", x["text"], re.I)), None)
        tb_scale = (re.sub(r"\s+", "", scale_note["text"].split("SCALE", 1)[-1]) if scale_note else None) or tb_text
        tb_parsed = parse_scale(tb_scale or "")
        exact = None
        if src_sheet and gen_sheet:
            exact = abs(gen_sheet[0] - src_sheet[0]) < 1e-9 and abs(gen_sheet[1] - src_sheet[1]) < 1e-9 and (tb_parsed is None or tb_parsed == src_sheet)
        live = getattr(self, "live_reads", {}) or {}
        vscales = live.get("view_scales", [])
        # ---- views present
        want = [v for v in ex.get("views", [])]
        rv = (self.plan.get("reference_layout") or {}).get("views", {})
        have = {i.get("reference_view") for i in rv.values() if i.get("reference_view")}
        missing_views = [{"id": v["id"], "type": v["type"]} for v in want if v["id"] not in have]
        mism_types = []
        for role, i in rv.items():
            vv = next((x for x in want if x["id"] == i.get("reference_view")), None)
            native_t = "Isometric" if role == "iso" else (self.plan["views"].get(role) or "").strip("*")
            if vv and vv["type"] != native_t:
                mism_types.append({"role": role, "source_type": vv["type"], "generated_type": native_t})
        # ---- notes verbatim (from the exported PDF)
        nv = replicate.note_verbatim_check(self.note_recs, pages)
        imgs_x = {"side_by_side": [], "overlay": [], "difference": []}
        clip = [c for c in col if c.kind == "clipped"]
        led = (self.comparison or {}).get("semantic", {}).get("ledger", [])
        crit = [e for e in led if e.get("required") and e["kind"] in replicate.CRITICAL_KINDS and e["status"] in ("value_differs", "missing", "unit_unknown")]
        unresolved_src = [e for e in led if e["status"] in ("source_note", "missing", "value_differs", "unit_unknown") and e.get("required")]
        n_pages = int((ex.get("source") or {}).get("pages") or 1)
        done_pages = len(self.ref_pages) if self.ref_pages else 1
        built = int(reop.get("sheets") or 1)
        pages_missing = [i for i in range(built + 1, n_pages + 1)]
        extra_rep = []
        xnv_bad, xnv_sym, xmiss, xunres, xdev = [], [], [], 0, []
        for xr in self.extra_pages:
            e_ = {"page": xr["page"], "status": xr["status"], "error": xr.get("error"), "warnings": xr.get("warnings", []), "scale_basis": xr.get("scale_basis")}
            if xr["status"] == "built":
                pr_ = (live.get("sheet_scales") or {}).get(xr["name"])
                if pr_:
                    e_["generated_scale"] = f"{pr_[0]:g}:{pr_[1]:g}"
                    e_["scale_match"] = (abs(pr_[0] - xr["scale"][0]) < 1e-9 and abs(pr_[1] - xr["scale"][1]) < 1e-9)
                else:
                    e_["scale_error"] = live.get("error") or "not read"
                nvx = replicate.note_verbatim_check(xr["note_recs"], pages, page=xr["page"] - 1)
                e_["notes_verbatim"] = {"matched": nvx["matched"], "total": nvx["total"]}
                xnv_bad += nvx["mismatched"]
                xnv_sym += nvx["symbols_unverified"]
                e_["views"], e_["views_not_reproduced"] = xr["views"], xr["views_not_reproduced"]
                xmiss += [dict(m_, page=xr["page"]) for m_ in xr["views_not_reproduced"]]
                xdev += [v_["dev_mm"] for v_ in xr["views"]]
                xunres += sum(1 for n_ in xr["note_recs"] if n_.get("source") == "annotation")
                try:
                    evx = replicate.render_evidence(self.ref_pdf, pdf, xr["frame"], self.stage_dir / "comparison", xr["page"] - 1, xr["page"] - 1, tag=f"page-{xr['page']:03d}")
                    for k_ in imgs_x:
                        imgs_x[k_].append("comparison/" + Path(evx["paths"][k_]).name)
                except Exception as ex_:      # noqa: BLE001
                    e_["evidence_error"] = str(ex_)
            extra_rep.append(e_)
        nv = {"matched": nv["matched"], "total": nv["total"], "mismatched": nv["mismatched"] + xnv_bad, "symbols_unverified": nv.get("symbols_unverified", []) + xnv_sym}
        missing_views = missing_views + xmiss
        metrics = {"sheet_scale_exact": exact, "view_scales": vscales, "view_center_dev_mm": {"median": med([v["distance_mm"] for v in vdev]), "max": max((v["distance_mm"] for v in vdev), default=None), "items": vdev},
                   "annotation_anchor_dev_mm": {"median": med([a["distance_mm"] for a in adev]), "max": max((a["distance_mm"] for a in adev), default=None), "n": len(adev)},
                   "notes_verbatim": nv, "unintended_clipping": len(clip), "critical_mismatches": len(crit), "missing_views": missing_views, "view_type_mismatches": mism_types,
                   "pages_missing": pages_missing, "unresolved_source_items": len(unresolved_src) + xunres}
        if xdev:
            metrics["view_center_dev_mm"]["max"] = max([metrics["view_center_dev_mm"]["max"] or 0.0] + xdev)
        status, reason = replicate.decide_status(metrics, th)
        if reop and not reop.get("opened", True):
            status, reason = "failed", "the saved drawing could not be reopened"
        # ---- issues
        issues = []
        def add(kind, sev, text, detail="", page=1):
            issues.append({"id": f"R{len(issues) + 1:03d}", "kind": kind, "severity": sev, "page": page, "text": text, "detail": detail})
        if exact is not True:
            add("scale_mismatch", "critical", f"sheet scale {gen_sheet} vs source {src_sheet}", f"title block prints {tb_scale!r}")
        for v in vscales:
            if v.get("match") is False:
                add("scale_mismatch", "critical", f"view {v['role']} scale {v['generated_decimal']:g} vs source {v['source_scale']}")
        for m_ in missing_views:
            add("view_missing", "high", f"source view {m_['id']} ({m_['type']}) was not reproduced", "the pipeline creates standard projected views; section / detail views of the source are not rebuilt")
        for m_ in mism_types:
            add("view_missing", "medium", f"source {m_['source_type']} view stands in as a plain {m_['generated_type']} view", "orientation matches; the cut / detail is not reproduced")
        for b in nv["mismatched"]:
            add("text_mismatch", "high", f"note not verbatim in the export: {b.get('text')!r}", b.get("why", ""))
        for d in (rs.get("adev") or []):
            if d["distance_mm"] > th["annotation_anchor_mm"]:
                add("position_deviation", "low", f"{d['text'][:30]!r} is {d['distance_mm']:.1f} mm from its source position")
        for e in unresolved_src:
            add({"source_note": "unresolved_source_item", "value_differs": "value_mismatch"}.get(e["status"], "missing_annotation"), "medium" if e["status"] == "source_note" else "high",
                f"{e['text'][:40]!r}: {e['status']}", e.get("reason", ""))
        for c in clip:
            add("clipping", "high", f"clipped / off-sheet text: {c.a_text}")
        for pg in pages_missing:
            add("page_missing", "high", f"source page {pg} was not reconstructed", "multi-sheet reconstruction", page=pg)
        # ---- evidence
        cdir = self.stage_dir / "comparison"
        imgs = {"side_by_side": [], "overlay": [], "difference": []}
        pix_sim = None
        try:
            ev = replicate.render_evidence(self.ref_pdf, pdf, self.frame, cdir, 0, 0, tag="page-001")
            for k in imgs:
                imgs[k].append("comparison/" + Path(ev["paths"][k]).name)
            pix_sim = ev["pixel_similarity"]
        except Exception as e:      # noqa: BLE001
            p.stages["verification"]["warnings"].append(f"evidence images: {type(e).__name__}: {e}")
        for k_ in imgs:
            imgs[k_] += imgs_x[k_]
        self.replication = {"schema": "ReplicationReport/1", "pages": extra_rep, "status": status, "status_label": replicate.STATUS_LABEL[status], "reason": reason,
                            "spec": {"schema": (self.spec or {}).get("schema_version"), "pages": n_pages, "pages_extracted": done_pages, "extraction_reuse": p.reference.get("extraction_cache"),
                                     "completeness": (self.spec or {}).get("completeness")},
                            "sheets": [{"page": 1, "source": {"width_mm": self.sheet_target.get("page_w_mm"), "height_mm": self.sheet_target.get("page_h_mm"),
                                                              "rotation": ex["sheet"].get("rotation", 0), "scale": ex["sheet"].get("scale_text") or None},
                                        "generated": {"width_mm": round(self.frame.sheet_w_m * 1000, 2), "height_mm": round(self.frame.sheet_h_m * 1000, 2), "name": self.sheet_target.get("name"),
                                                      "scale": f"{gen_sheet[0]:g}:{gen_sheet[1]:g}" if gen_sheet else None, "title_block_scale": tb_scale},
                                        "view_count": {"source": len(want), "generated": len(self.outlines or {})},
                                        "annotations": {"source": len(ex.get("annotations", [])), "generated": sum(1 for e in led if e["status"] in ("matched", "matched_shared")),
                                                        "matched": sum(1 for e in led if e["status"] in ("matched", "matched_shared")), "source_notes": sum(1 for e in led if e["status"] == "source_note"),
                                                        "missing": sum(1 for e in led if e["status"] in ("missing", "unit_unknown")), "extra": 0,
                                                        "mismatched": sum(1 for e in led if e["status"] == "value_differs")}}],
                            "scales": {"sheet": {"source": f"{src_sheet[0]}:{src_sheet[1]}" if src_sheet else None, "generated": f"{gen_sheet[0]:g}:{gen_sheet[1]:g}" if gen_sheet else None,
                                                 "title_block": tb_scale, "match": exact, "basis": (self.plan.get("scale") or {}).get("basis")}, "views": vscales},
                            "iterations": {k: (self.comparison or {}).get("iterations", {}).get(k) for k in ("used", "max", "best", "stop_reason")}, "thresholds": th,
                            "metrics": {"view_center_dev_mm": {"median": metrics["view_center_dev_mm"]["median"], "max": metrics["view_center_dev_mm"]["max"]},
                                        "annotation_anchor_dev_mm": {"median": metrics["annotation_anchor_dev_mm"]["median"], "max": metrics["annotation_anchor_dev_mm"]["max"]},
                                        "notes_verbatim": {"matched": nv["matched"], "total": nv["total"]}, "unintended_clipping": len(clip), "critical_mismatches": len(crit),
                                        "pixel_similarity_diagnostic_only": pix_sim},
                            "displacements": len(self.displacements), "displacement_records": self.displacements[:200], "issues": issues, "images": imgs,
                            "sheet_geometry": (p.stages.get("native_drawing") or {}).get("sheet_geometry"), "reopen": {k: reop.get(k) for k in ("opened", "sheets", "sheet_scale", "notes", "dimensions", "sheets_info")},
                            "view_center_items": vdev, "annotation_items": adev[:200], "note_records": [{k: v for k, v in x.items() if k != "_an"} for x in self.note_recs],
                            "fidelity_diagnostics_separate_from_scoring": True,
                            "note": "Drawing-fidelity diagnostics only. scoring.MD (if present) remains the authoritative score; nothing here is a score. PRELIMINARY / FOR REVIEW."}
        self.replication["sheets"] += [{"page": e["page"], "source": {"scale": (self.ref_pages[e["page"] - 1]["sheet"].get("scale_text") or None)}, "generated": {"scale": e.get("generated_scale")},
                                        "status": e["status"], "notes_verbatim": e.get("notes_verbatim"), "views_not_reproduced": e.get("views_not_reproduced"), "error": e.get("error")} for e in extra_rep]
        _write_json(self.stage_dir / "replication" / "report.json", self.replication)
        for x in self.note_recs:
            x.pop("_an", None)

    def _final_measure(self, dd, pdf: Path) -> None:
        """Measure the EXPORTED drawing.pdf: collisions on the real deliverable, shading evidence for the isometric, black text and lines, licence watermark."""
        st = self.std
        pages = layout.measure_pdf(pdf)
        W, H = refrun.sheet_dims(self)
        err = layout.check_scale(pages[0], W, H) if pages else "the export has no pages"
        outl = refrun.outlines(self, dd)
        snap = refrun.snapshot(st)
        t2a = refrun.map_all(pages[0].texts, snap) if pages else {}
        ours = set(t2a.values())
        col = refrun.detect_now(self, dd, st, pages, outl, ours) if pages and not err else []
        iso_ok = None
        try:
            import fitz
            d_ = fitz.open(str(pdf))
            pg = d_.load_page(0)
            io = outl.get("iso")
            if io:
                imgs = [pg.get_image_bbox(i) for i in pg.get_images(full=True)]
                H_pt = pg.rect.height
                iso_ok = any((r.x0 * layout.PT_M <= (io[2] + 0.002) and r.x1 * layout.PT_M >= (io[0] - 0.002) and (H_pt - r.y1) * layout.PT_M <= (io[3] + 0.002)
                              and (H_pt - r.y0) * layout.PT_M >= (io[1] - 0.002)) for r in imgs if not r.is_empty) or (pages[0].shaded_fills > 0)
            d_.close()
        except Exception as e:      # noqa: BLE001
            self.part.stages["verification"]["warnings"].append(f"isometric shading check: {type(e).__name__}: {e}")
        self.final_measure = {"scale_error": err, "collisions": layout.summarize(col, float(self.job.options.get("clearance_mm", layout.DEFAULT_CLEARANCE_MM)),
                                                                                  {"texts": len(pages[0].texts) if pages else 0, "strokes": len(pages[0].strokes) if pages else 0}),
                              "iso_shading_in_pdf": iso_ok, "nonblack_text": len(pages[0].nonblack_text) if pages else None, "nonblack_strokes": pages[0].nonblack_strokes if pages else None,
                              "licence_watermark": bool(pages and pages[0].watermark), "mapped_annotations": len(t2a)}
        if err:
            self.issues.append(qa.issue("high", "LAYOUT_UNMEASURED", err, part_id=self.part.part_id))
        if iso_ok is False:
            self.issues.append(qa.issue("high", "ISO_NO_SHADING_IN_PDF", "The exported PDF shows no shaded image in the isometric view.", part_id=self.part.part_id))
        # a collision seen in the final export that the loop did not already report is a new finding
        known = {(i["code"], i["message"]) for i in self.issues}
        for c in [c_ for c_ in col if c_.severity != "low"]:
            code = "COLLISION_" + c.kind.upper()
            msg = f"{c.kind}: {c.a_text} {c.b_text} {c.detail}".strip()
            if (code, msg) not in known:
                self.issues.append(qa.issue("high", code, msg, part_id=self.part_id if hasattr(self, "part_id") else self.part.part_id, next_action="Move the annotation manually; evidence is in verification.json."))
        try:
            layout.render_overlay(pdf, col, self.stage_dir / "comparison" / "collisions-overlay.png") if col else None
        except Exception:      # noqa: BLE001
            pass

    def _reopen_check(self, slddrw: Path, model_copy: Path) -> dict:
        """Reopen the saved drawing: it must open, its views must reference the model (not dangling), and dimensions must still be attached."""
        T = self.s.typed
        res = T(self.s.app, "ISldWorks").OpenDoc6(str(slddrw), drawing.SW_DOC_DRW if hasattr(drawing, "SW_DOC_DRW") else 3, 1, "", 0, 0)
        d = res[0] if isinstance(res, tuple) else res
        info = {"opened": d is not None, "views": [], "dimensions": 0, "errors": []}
        if d is None:
            self.issues.append(qa.issue("critical", "REOPEN_FAILED", "The saved drawing could not be reopened.", part_id=self.part.part_id,
                                        next_action="Do not use this drawing; rerun."))
            _write_json(self.stage_dir / "reopen_check.json", info)
            return info
        try:
            title = str(T(d, "IModelDoc2").GetTitle())
            self.s.opened[str(slddrw.resolve()).lower()] = title
            drw = T(d, "IDrawingDoc")
            v = drw.GetFirstView()          # the sheet itself
            v = T(v, "IView").GetNextView() if v is not None else None
            while v is not None:
                tv = T(v, "IView")
                ref = str(tv.GetReferencedModelName() or "")
                try:
                    sc_ = float(tv.ScaleDecimal)
                except Exception:      # noqa: BLE001
                    sc_ = None
                info["views"].append({"name": str(tv.GetName2()), "references": Path(ref).name, "ok": Path(ref).name.lower() == model_copy.name.lower(), "scale_decimal": sc_})
                try:
                    info["notes"] = info.get("notes", 0) + len(tv.GetNotes() or ())
                except Exception:      # noqa: BLE001
                    pass
                try:
                    dds = tv.GetDisplayDimensions() or ()
                    info["dimensions"] += len(dds)
                except Exception:      # noqa: BLE001
                    pass
                v = tv.GetNextView()
            if not info["views"] or not all(x["ok"] for x in info["views"]):
                self.issues.append(qa.issue("critical", "DANGLING_VIEW", "A view does not reference the part after reopening.", part_id=self.part.part_id))
            info["sheets"] = int(drw.GetSheetCount())
            info["sheets_info"] = []
            for nm_ in (drw.GetSheetNames() or ()):
                try:
                    drw.ActivateSheet(nm_)
                    pr2_ = T(drw.GetCurrentSheet(), "ISheet").GetProperties2()
                    info["sheets_info"].append({"name": str(nm_), "scale": [pr2_[2], pr2_[3]], "size_m": [pr2_[5], pr2_[6]]})
                except Exception as e2_:      # noqa: BLE001
                    info["errors"].append(f"sheet {nm_}: {e2_}")
            try:
                drw.ActivateSheet("Sheet1")
            except Exception:      # noqa: BLE001
                pass
            try:
                sh_ = T(drw.GetCurrentSheet(), "ISheet")
                pr_ = sh_.GetProperties2()
                info["sheet_scale"] = [pr_[2], pr_[3]]
                info["sheet_size_m"] = [pr_[5], pr_[6]]
                info["sheet_notes"] = len(T(drw.GetFirstView(), "IView").GetNotes() or ())      # sheet-level notes live on the views they were created in (see "notes")
            except Exception as e_:      # noqa: BLE001
                info["errors"].append(f"sheet read-back: {e_}")
        except Exception as e:      # noqa: BLE001
            info["errors"].append(f"{type(e).__name__}: {e}")
        finally:
            try:
                self.s.app.CloseDoc(title)
            except Exception:      # noqa: BLE001
                pass
            self.s.opened.pop(str(slddrw.resolve()).lower(), None)
        _write_json(self.stage_dir / "reopen_check.json", info)
        return info

    def _verification(self, hard: list, review: bool) -> dict:
        """The QA gate: never a pass while anything unresolved remains. ``failed`` only when the deliverable could not be produced or verified."""
        p = self.part
        cmp_ = self.comparison
        if cmp_:
            sem = cmp_["semantic"]
            coverage = {"matched": sem["coverage"]["matched"], "total": sem["coverage"]["total"], "unresolved": sem["coverage"]["unresolved"][:80],
                        "basis": "required reference items (dimensions, hole callouts, notes) vs the generated drawing"}
        else:
            items = [it for it in (self.ledger_json or {}).get("items", []) if it.get("status") != "not_applicable"]
            coverage = {"matched": sum(1 for it in items if it.get("status") == "covered"), "total": len(items),
                        "unresolved": [{"id": it.get("id"), "kind": it.get("characteristic"), "text": it.get("characteristic"), "reason": it.get("reason", ""), "severity": "medium"}
                                       for it in items if it.get("status") != "covered"][:80],
                        "basis": "model features that need a dimension (Standard mode: geometry-derived, no reference)"}
        fm = self.final_measure or {}
        col = fm.get("collisions") or self.layout_rep.get("after") or {"count": 0, "items": [], "clearance_mm": float(self.job.options.get("clearance_mm", layout.DEFAULT_CLEARANCE_MM))}
        sev = [i["severity"] for i in self.issues]
        critical = [i for i in self.issues if i["severity"] == "critical" or i["code"] in ("REOPEN_FAILED", "DANGLING_VIEW", "PDF_PAGES")]
        if critical:
            status = "failed"
        elif hard or review or coverage["unresolved"] or col.get("count"):
            status = "review_required"
        else:
            status = "passed"
        if self.replication and status == "passed" and self.replication.get("status") != "verified":
            status = "review_required"
        iso = (p.stages.get("native_drawing") or {}).get("iso", {})
        std = (self.std.report if self.std else {})
        arr = self.layout_rep.get("arrange") or {}
        return {"status": status, "coverage": coverage, "collisions": col,
                "comparison": ({"semantic": {"counts": self.comparison["semantic"]["counts"], "material": self.comparison["semantic"]["material"], "views": self.comparison["semantic"]["views"]},
                                "spatial": self.comparison["spatial"]["summary"]} if self.comparison else {"semantic": None, "spatial": None, "note": "not applicable (Standard mode or no reference applied)"}),
                "iterations": ({**((self.comparison or {}).get("iterations") or {}), "layout": {k: self.layout_rep.get(k) for k in ("max_iterations", "iterations_used", "best", "history")}} if self.layout_rep else {}),
                "standards": {"iso_shaded_with_edges": (all(v.get("applied") for v in iso.get("views", [])) if iso.get("views") else None),
                              "iso_shading_in_pdf": fm.get("iso_shading_in_pdf"),
                              "black_text": (not fm.get("nonblack_text") and not (std.get("black") or {}).get("failed")) if fm else None,
                              "broken_leaders": {"applied": len((std.get("leaders") or {}).get("applied", [])), "failed": len((std.get("leaders") or {}).get("failed", [])),
                                                 "not_applicable": len((std.get("leaders") or {}).get("not_applicable", [])), "note": (std.get("notes") or {}).get("note")},
                              "arrange": {k: arr.get(k) for k in ("accepted", "decision", "moved", "integrity", "collisions_before", "collisions_after")} if arr else None,
                              "licence_watermark": fm.get("licence_watermark")},
                "replication": self.replication or None,
                "issues_by_severity": {s_: sev.count(s_) for s_ in sorted(set(sev))}, "hard_failures": [h["code"] for h in hard],
                "note": "Software QA is not engineering approval. A reference match is not an approval either; the drawing stays PRELIMINARY / FOR REVIEW."}

    def _publish(self) -> None:
        p = self.part
        out = self.out
        sd = self.stage_dir
        ledger = self.ledger_json.get("coverage", {})
        hard = [i for i in self.issues if i["severity"] in ("critical",) or i["code"] in ("VALUE_MISMATCH", "PDF_PAGES", "DANGLING_VIEW", "REOPEN_FAILED", "VIEW_OVERLAP", "TEXT_OVERLAPS")
                or i["code"].startswith("COLLISION_") or i["code"] in ("ISO_NOT_SHADED_WITH_EDGES", "ISO_NO_SHADING_IN_PDF", "REFERENCE_UNRELATED", "LAYOUT_UNMEASURED")]
        review = [i for i in self.issues if i["severity"] in ("critical", "high", "medium")] or any(
            it["status"] in ("review_required", "unresolved") for it in self.ledger_json.get("items", []))
        verification = self._verification(hard, bool(review))
        p.verification = verification
        # artifact set: only what exists
        names = {"model.stl": "model.stl", "drawing.slddrw": "drawing.slddrw", "drawing.pdf": "drawing.pdf", "inventory.json": "inventory.json",
                 "drawing_plan.json": "drawing_plan.json", "dimension_coverage.json": "dimension_coverage.json", "stl_validation.json": "stl_validation.json",
                 "pdf_check.json": "pdf_check.json", "reopen_check.json": "reopen_check.json", "layout_report.json": "layout_report.json"}
        for n in names:
            src = sd / n
            if src.is_file():
                os.replace(src, out / n)
        if (sd / "preview").is_dir():
            shutil.rmtree(out / "preview", ignore_errors=True)
            os.replace(sd / "preview", out / "preview")
        for sub in ("reference", "comparison", "replication"):
            if (sd / sub).is_dir():
                shutil.rmtree(out / sub, ignore_errors=True)
                os.replace(sd / sub, out / sub)
        for mp in sorted((sd / "source").glob("*.SLDPRT")) if (sd / "source").is_dir() else []:
            # the drawing's referenced model travels with it (same folder, same file name: SOLIDWORKS searches the drawing's own folder), so the
            # published SLDDRW can be reopened with its views resolved. It is the hashed working copy, never the user's file.
            os.replace(mp, out / mp.name)
            self.linked_model = mp.name
        pub_ref = {k: v for k, v in p.reference.items() if not k.startswith("_")}
        qa_doc = {"part": p.part_id, "issues": self.issues, "coverage": ledger, "hard_failures": hard, "pdf": {k: v for k, v in getattr(self, "pdfq", {}).items() if k != "previews"},
                  "review_required": bool(review) or verification["status"] != "passed", "verification": verification, "reference": pub_ref,
                  "note": "Software QA is not engineering approval. This drawing is PRELIMINARY / FOR REVIEW until an authorized engineer dispositions the issues."}
        _write_json(out / "qa.json", qa_doc)
        _write_json(out / "verification.json", {"schema": "VerificationReport/1", **verification, "reference": pub_ref, "final_measure": self.final_measure})
        files = {}
        for n in list(names) + ["qa.json", "verification.json"]:
            fp = out / n
            if fp.is_file():
                files[n] = {"bytes": fp.stat().st_size, "sha256": safety.sha256_file(fp)}
        if getattr(self, "linked_model", None) and (out / self.linked_model).is_file():
            files[self.linked_model] = {"bytes": (out / self.linked_model).stat().st_size, "sha256": safety.sha256_file(out / self.linked_model)}
        try:        # this part's rows of the per-request usage ledger travel with it (secrets-free: tokens, ids, cost)
            from reverse import costs as _costs
            rows = [r_ for r_ in _costs.read_rows(self.store.dir(self.job.job_id) / "usage" / "usage_ledger.jsonl") if r_.get("part") == p.part_id]
            if rows:
                (out / "usage").mkdir(parents=True, exist_ok=True)
                (out / "usage" / "usage_ledger.jsonl").write_text(chr(10).join(json.dumps(r_) for r_ in rows) + chr(10), encoding="utf-8")
                files["usage/usage_ledger.jsonl"] = {"bytes": (out / "usage" / "usage_ledger.jsonl").stat().st_size, "sha256": safety.sha256_file(out / "usage" / "usage_ledger.jsonl")}
        except Exception as e_:      # noqa: BLE001
            log.warning("usage log copy failed: %s", e_)
        for sub in ("reference", "comparison", "replication"):
            for fp in sorted((out / sub).rglob("*")) if (out / sub).is_dir() else []:
                if fp.is_file() and not fp.name.endswith(".tmp"):
                    files[f"{sub}/{fp.relative_to(out / sub).as_posix()}"] = {"bytes": fp.stat().st_size, "sha256": safety.sha256_file(fp)}
        for pv in sorted((out / "preview").glob("*.png")) if (out / "preview").is_dir() else []:
            files[f"preview/{pv.name}"] = {"bytes": pv.stat().st_size, "sha256": safety.sha256_file(pv)}
        not_ok = bool(review) or bool(hard) or verification["status"] != "passed"
        manifest = {"schema_version": 2, "job_id": self.job.job_id, "part_id": p.part_id, "source_name": self.src.name, "source_sha256": self.src_hash,
                    "source_unchanged": safety.sha256_file(self.src) == self.src_hash, "configuration": getattr(self, "config_used", ""),
                    "solidworks": self.s.info.as_dict(), "template": {k: self.template.get(k) for k in ("id", "name", "sha256", "own_sheet_format")},
                    "profile": self.job.profile, "units": self.plan.get("units"), "projection": self.plan.get("projection"), "scale": self.plan.get("scale"),
                    "stl": {"unit": "mm", "transform": "none (the part is exported in its own coordinate system)"}, "material": self.material,
                    "reference": {k: pub_ref.get(k) for k in ("mode", "status", "source_kind", "filename", "sha256", "pages", "link", "extraction_cache", "extraction_id", "api_usage")},
                    "verification_status": verification["status"],
                    "stage_seconds": {k: v.get("seconds") for k, v in p.stages.items()}, "files": files, "review_status": "required" if not_ok else "none",
                    "status": "review_required" if not_ok else "completed", "draft": True,
                    "note": "Draft output. Not approved for manufacture."}
        _write_json(out / "manifest.json", manifest)
        shutil.rmtree(sd, ignore_errors=True)
        rel = lambda n: str((Path(p.part_id) / safety.safe_id(p.config or "active", "active") / n).as_posix())
        p.artifacts = {n: rel(n) for n in files} | {"manifest.json": rel("manifest.json")}
        p.issues = self.issues
        p.material = self.material
        p.review_status = "required" if not_ok else "none"
        state.finish(p, "review_required" if not_ok else "completed")       # a failed verification is itself the review item: it never reads as green
        self._ev("published", status=p.state, files=len(files), verification=verification["status"])
