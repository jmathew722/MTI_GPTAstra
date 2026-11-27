"""Per-part orchestration of the v7 stages that sit on top of the existing engine: reference resolution, extraction, planning from a reference, native
standards, the measured layout loop, comparison and the QA gate. Functions take the ``PartRunner`` (``r``) and keep their state on it.

Nothing here edits geometry or invents annotation content. Every correction is a bounded move of an existing annotation, measured before and after on the
exported PDF, and the best revision wins (never deleting a required annotation to improve a score).
"""
from __future__ import annotations

import json
import logging
import math
import os
import shutil
import statistics
import time
from pathlib import Path
from typing import Optional

from reverse import compare, layout, planner, qa, refextract, reflayout, safety, standards, state, worker

log = logging.getLogger(__name__)

SHEET_TEMPLATE_ID = {"ANSI_B": "solidflow-ansi-b", "ANSI_C": "solidflow-ansi-c", "A3": "solidflow-a3"}
DEFAULT_ITERATIONS = 3
UNIT_TO_M = {"inch": 0.0254, "mm": 0.001}


def _w(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


# ------------------------------------------------------------------ reference resolution / extraction

def ref_mode_active(part: state.PartState) -> bool:
    r = part.reference or {}
    return r.get("mode") == "match" and r.get("status") in ("resolved", "pending") and bool(r.get("_pdf"))


def stage_reference_resolution(r) -> None:
    """Re-validate the resolved PDF, copy it immutably next to the artifacts and write the provenance record."""
    ref = r.part.reference
    pdf = Path(ref["_pdf"])
    from reverse import reference as refmod
    v = refmod.validate_pdf(pdf)
    if not v["ok"]:
        raise worker.CadError(f"REFERENCE_PDF_REJECTED: {v['error']}")
    if ref.get("sha256") and v["sha256"] != ref["sha256"]:
        raise worker.CadError("REFERENCE_PDF_REJECTED: the reference file changed after it was resolved (hash mismatch).")
    dest = r.stage_dir / "reference" / "source.pdf"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(pdf, dest)
    if safety.sha256_file(dest) != v["sha256"]:
        raise worker.CadError("The working copy of the reference PDF does not match its source (copy failed).")
    r.ref_pdf = dest
    r.ref_sha = v["sha256"]
    ref.update(status="resolved", sha256=v["sha256"], pages=v["pages"])
    _w(r.stage_dir / "reference" / "resolution.json", {"schema": "ReferenceResolution/1", **{k: val for k, val in ref.items() if not k.startswith("_")},
                                                       "source_kind": ref.get("source_kind"), "part_sha256": r.src_hash, "configuration": getattr(r, "config_used", ""),
                                                       "pdfSha256": v["sha256"]})


def stage_extraction(r) -> None:
    """Prior extraction reuse or fresh / supplemental extraction through the configured OpenAI client (budgeted and tracked)."""
    from pipeline import budget
    from pipeline.token_tracker import TokenTracker
    ref = r.part.reference
    refs = r.refs
    prior = refs.index.prior_extractions(r.ref_sha, r.src_hash)
    ledger = r.store.dir(r.job.job_id) / "usage" / "usage_ledger.jsonl"
    tracker = TokenTracker(ledger, run_id=r.job.job_id)
    msgs: list[str] = []
    try:
        with tracker.activate(part=r.part.part_id, arm="reverse-reference"):
            res = refextract.extract_reference(r.ref_pdf, cache_root=refs.cache_root, prior=prior, refresh=bool(r.job.options.get("refresh_reference")),
                                               client=refs.client, part=r.part.part_id, progress=msgs.append,
                                               tiles=int(r.job.options.get("tiles_per_page") or 0))
    except budget.BudgetExceeded:
        raise
    ex = res["extraction"]
    use = res["usage"]
    r.ref_ex = ex
    r.ref_pages = res.get("pages") or [ex]
    r.spec = res.get("spec")
    ref["extraction_cache"] = res["cache"]
    ref["extraction_id"] = ex.get("extraction_id", "")
    ref["extraction_schema"] = ex.get("schema_version", "")
    ref["api_usage"] = {"tokens": int(use.get("input_tokens", 0)) + int(use.get("output_tokens", 0)), "input_tokens": int(use.get("input_tokens", 0)),
                        "output_tokens": int(use.get("output_tokens", 0)), "usd": round(float(use.get("usd", 0.0)), 4), "calls": int(use.get("calls", 0)), "incremental": True,
                        "historical_usd": use.get("historical_usd"), "model": use.get("model")}
    for w_ in res.get("warnings", []):
        if w_ not in ref["warnings"]:
            ref["warnings"].append(w_)
    ref["quality"] = ex.get("quality")
    if res["cache"] == "hit":
        r.part.stages["extraction"]["note"] = "cached reference extraction reused: zero incremental API calls"
    ex_path = r.stage_dir / "reference" / "reference_extraction.json"
    _w(ex_path, ex)
    if r.spec:
        _w(r.stage_dir / "reference" / "drawing_spec.json", r.spec)
        ref["spec"] = {"schema": r.spec["schema_version"], "pages": r.spec["pages_extracted"], "completeness": r.spec["completeness"], "pages_missing": r.spec["pages_missing"]}


# ------------------------------------------------------------------ geometry compatibility (unrelated / wrong reference detection)

def _inv_values(inv: dict) -> list[float]:
    vals: list[float] = list(inv.get("size_m") or [])
    coords: dict[str, list[float]] = {}
    for h in inv.get("holes", []):
        for k in ("diameter_m", "depth_m"):
            if h.get(k):
                vals.append(h[k])
        if (h.get("counterbore") or {}).get("diameter_m"):
            vals.append(h["counterbore"]["diameter_m"])
        for ax, c in zip(h.get("center_axes", []), h.get("center_m", [])):
            coords.setdefault(ax, []).append(c)
    size = dict(zip("xyz", inv.get("size_m") or [0, 0, 0]))
    box = inv.get("bbox_m") or [0, 0, 0, 0, 0, 0]
    for ax, cs in coords.items():
        i = "xyz".index(ax)
        lo = box[i]
        for c in cs:
            vals += [abs(c), abs(c - lo), abs(box[i + 3] - c)]
        for a_ in cs:
            for b_ in cs:
                if a_ != b_:
                    vals.append(abs(a_ - b_))
    for p in inv.get("planes", []):
        bx = p.get("box_m")
        if bx:
            vals += [abs(bx[3] - bx[0]), abs(bx[4] - bx[1]), abs(bx[5] - bx[2])]
    return [v for v in vals if v and v > 1e-6]


def compatibility(ex: dict, inv: dict, default_unit: Optional[str]) -> dict:
    """Do the reference's numeric dimensions look like THIS model? (overall size and hole sizes), never a proof of identity, only a mismatch detector."""
    vals = _inv_values(inv)
    size = sorted(inv.get("size_m") or [])
    unit = compare.norm_unit(ex.get("sheet", {}).get("units", "")) or default_unit
    items = []
    for a in ex.get("annotations", []):
        if a.get("kind") in ("linear", "diameter", "radius", "hole_callout", "chamfer"):
            num = compare.parse_annotation(a)
            u = compare.norm_unit(a.get("unit", "")) or unit
            if num.value is not None and u in UNIT_TO_M:
                items.append((num, u))
    if not items:
        return {"status": "unknown", "reason": "the reference extraction has no numeric dimensions to compare", "compared": 0, "matched": 0}
    matched = 0
    for num, u in items:
        exp = num.value * UNIT_TO_M[u]
        tol = max(compare.tol_m(num, u), 1e-6)
        if any(abs(v - exp) <= tol for v in vals):
            matched += 1
    overall_hit = 0
    for sz in size:
        if any(abs(num.value * UNIT_TO_M[u] - sz) <= max(compare.tol_m(num, u), 1e-6) for num, u in items):
            overall_hit += 1
    ratio = matched / len(items)
    if overall_hit == 0 and ratio < 0.5:
        status = "incompatible"
    elif ratio >= 0.5 or overall_hit >= 2:
        status = "compatible"
    else:
        status = "uncertain"
    return {"status": status, "compared": len(items), "matched": matched, "ratio": round(ratio, 3), "overall_extents_found": overall_hit, "overall_extents_total": len(size),
            "note": "A mismatch detector, not proof of identity: it checks that printed dimensions exist among the model's sizes, hole diameters and hole positions."}


# ------------------------------------------------------------------ planning from the reference

def plan_with_reference(r) -> dict:
    """The view/sheet plan. In reference mode: sheet format, scale and view centres come from the reference where feasible; every deviation is recorded."""
    p, inv = r.part, r.inv
    prof = r.job.profile
    dev: list[str] = []
    scale_override = None
    ref_active = r.ref_applied
    if ref_active:
        from reverse import replicate as _rep
        if _rep.active(r):
            rp = plan_replication(r)
            if rp is not None:
                return rp
    if ref_active:
        prof2, d1 = reflayout.pick_profile(r.ref_ex, prof, inv_units(r))
        dev += d1
        if prof2 != prof:
            want_sheet = planner.PROFILES[prof2]["sheet"]
            alt = None
            tid = SHEET_TEMPLATE_ID.get(want_sheet)
            tpl = r.template
            if tid and (tpl.get("id", "").startswith("solidflow-")) and tpl.get("id") != tid and r.refs is not None and getattr(r.refs, "template_lookup", None):
                try:
                    alt = r.refs.template_lookup(tid)
                    if not (alt and alt.get("path") and Path(alt["path"]).is_file()):
                        alt = None
                except Exception:      # noqa: BLE001
                    alt = None
            if alt is not None:
                r.template = alt
                prof = prof2
                dev.append(f"Template changed to {alt.get('name', tid)} so the sheet format matches the reference.")
            else:
                dev.append(f"The reference suggests {want_sheet} but the matching Solid Flow template is not available here; the selected template's sheet format was kept.")
        ss = reflayout.reference_scale(r.ref_ex)
        scale_override = ss
    plan = planner.plan_views(tuple(inv["size_m"]), prof, hole_axes=inv["hole_axes"], scale_override=scale_override)
    if ref_active and scale_override and not plan["scale_fits"]:
        dev.append(f"The reference scale {scale_override[0]}:{scale_override[1]} does not fit the model's views on this sheet; the largest scale that fits was used.")
        plan = planner.plan_views(tuple(inv["size_m"]), prof, hole_axes=inv["hole_axes"])
    elif ref_active and scale_override is None:
        dev.append("The reference scale could not be read; the largest scale that fits was used.")
    r.profile_used = prof
    if ref_active:
        rec = reflayout.apply_reference(plan, r.ref_ex, dict(zip("xyz", inv["size_m"])))
        rec["sheet_deviations"] = dev
        rec["deviations"] = dev + rec["deviations"]
    return plan


def inv_units(r) -> str:
    base = r.ref_ex.get("base_extraction") if r.ref_ex else None
    return ""


# ------------------------------------------------------------------ reference notes (verbatim, provenance, never invented)

def add_reference_notes(r, dd) -> set:
    """The reference's manufacturing notes, verbatim, in one block in the sheet's notes zone, headed with their provenance. Returns the carried note ids."""
    ex = r.ref_ex
    carried: set[str] = set()
    if not ex:
        return carried
    notes = [n for n in ex.get("notes", []) if n.get("kind") in compare.GENERAL_NOTE_KINDS and (n.get("text") or "").strip()]
    if not notes:
        return carried
    reg = {k: planner.Rect(*v) for k, v in r.plan["regions_m"].items()}
    nz = reg["notes"]
    import textwrap
    width_chars = max(20, int((nz.w - 0.008) / 0.0026))          # ~2.6 mm per character at the note font; the zone is narrower than the title block
    lines = textwrap.wrap(f"REFERENCE NOTES FROM SOURCE DRAWING ({ex['source']['filename']}); FOR REVIEW:", width_chars)
    for n in notes:
        lines += textwrap.wrap(" ".join(n["text"].split()), width_chars) or [""]
        carried.add(n["id"])
    text = "\n".join(lines)
    # a note block taller than the zone would collide with the border: place it in free sheet space instead and say so
    height = len(lines) * 0.0045 + 0.004
    x, y = nz.x0 + 0.003, nz.y1 - 0.0165            # below the template's own "NOTES:" label
    if height > (y - nz.y0 - 0.002):
        r.part.reference["warnings"].append("The reference notes are longer than the sheet's notes zone; they were placed in free space on the sheet.")
        spot = planner.find_spot(width_chars * 0.0026 + 0.004, height, [planner.Rect(*v).grow(0.02) for v in r.outlines.values()], [reg["title_block"], nz], reg["usable"], 0.01)
        if spot is None:
            for n in notes:
                carried.discard(n["id"])
            r.issues.append(qa.issue("high", "REFERENCE_NOTES_NO_ROOM", "The reference's manufacturing notes do not fit on the sheet.", part_id=r.part.part_id,
                                     next_action="Use a larger sheet or add a notes sheet; the note text is in reference_extraction.json."))
            return carried
        x, y = spot.x0, spot.y1 - 0.005
    an = dd.note(text, x, y)
    if an is None:
        carried.clear()
        r.issues.append(qa.issue("medium", "REFERENCE_NOTES_FAILED", "The reference notes could not be inserted.", part_id=r.part.part_id))
        return carried
    r.ref_notes_box = (x, y - height, x + 0.14, y + 0.004)
    return carried


# ------------------------------------------------------------------ measurement helpers

def sheet_dims(r) -> tuple[float, float]:
    s = r.plan["regions_m"]["sheet"]
    return s[2] - s[0], s[3] - s[1]


def outlines(r, dd) -> dict:
    out = {}
    for role in dd.views:
        try:
            out[role] = tuple(dd.view_outline(role))
        except Exception:      # noqa: BLE001
            continue
    return out


def export_measure(r, dd, st, tag: str):
    pdf = r.stage_dir / "_iter" / f"{tag}.pdf"
    dd.export_pdf(pdf)
    pages = layout.measure_pdf(pdf)
    W, H = sheet_dims(r)
    msg = layout.check_scale(pages[0], W, H) if pages else "the export has no pages"
    return pdf, pages, msg


def annotation_positions(st) -> dict:
    pos = {i["id"]: tuple(i["position_m"]) for i in st.inventory() if "error" not in i}
    return pos


def snapshot(st) -> list[dict]:
    """Dimensions plus OUR notes (view labels, reference notes); the template's own title-block notes are not ours and are never moved."""
    items = [i for i in st.inventory() if "error" not in i]
    zones = getattr(st, "template_zones", [])
    for n in st.notes_inventory():
        if "error" in n or "view_name" not in n:
            continue
        x, y = n["position_m"]
        if any(z[0] <= x <= z[2] and z[1] <= y <= z[3] for z in zones):
            continue
        items.append(n)
    return items


def map_all(texts, snap) -> dict:
    dims = {i["id"]: tuple(i["position_m"]) for i in snap if i.get("kind") == "dimension"}
    m = layout.map_text_to_annotations(texts, dims)
    m.update(layout.map_notes_to_texts([t for t in texts if t.id not in set(m.values())], [i for i in snap if i.get("kind") == "note"]))
    return m


def detect_now(r, dd, st, pages, outl, ours_ids) -> list:
    reg = {k: planner.Rect(*v) for k, v in r.plan["regions_m"].items()}
    t = reg["title_block"]
    u = reg["usable"]
    keep = {"title_block": (t.x0, t.y0, t.x1, t.y1)}
    cl = float(r.job.options.get("clearance_mm", layout.DEFAULT_CLEARANCE_MM)) / 1000.0
    return layout.detect(pages, clearance_m=cl, view_outlines=outl, keepout=keep, usable=(u.x0, u.y0, u.x1, u.y1), ours=ours_ids)


def move_note(dd, st, view_name: str, index: int, new_xy: tuple[float, float]) -> bool:
    T = dd.s.typed
    for tv in standards.all_views(dd):
        if standards.vname_of(tv) != view_name:
            continue
        for i, nn in enumerate(tv.GetNotes() or ()):
            if i == index:
                an = T(T(nn, "INote").GetAnnotation(), "IAnnotation")
                return bool(an.SetPosition2(new_xy[0], new_xy[1], 0))
    return False


def move_annotation(dd, st, select_name: str, view_name: str, new_xy: tuple[float, float]) -> bool:
    T = dd.s.typed
    for vname, tv in st.iter_views():
        if vname != view_name:
            continue
        for d in (tv.GetDisplayDimensions() or ()):
            td = T(d, "IDisplayDimension")
            if str(td.GetNameForSelection()) == select_name:
                an = T(td.GetAnnotation(), "IAnnotation")
                return bool(an.SetPosition2(new_xy[0], new_xy[1], 0))
    return False


def restore_snapshot(dd, st, snap: list[dict]) -> int:
    return standards.restore_positions(dd, snap)


# ------------------------------------------------------------------ layout loop (dimensioning_layout)

def separate_views(r, dd) -> dict:
    """Overlapping view outlines (SOLIDWORKS' real outline, centre-mark overshoot included): move the FREE view (section / extra / isometric) to the nearest clear
    position, verified by outline read-back. A view whose position SOLIDWORKS locks (aligned to its parent) is left where it is and reported."""
    from reverse.drawing import com_doubles
    rep = {"moved": [], "unresolved": []}
    reg = {k: planner.Rect(*v) for k, v in r.plan["regions_m"].items()}
    usable = reg["usable"]
    keep = [reg["title_block"], reg["notes"]]
    gap = 0.004
    for _ in range(4):
        outl = {k: planner.Rect(*v) for k, v in outlines(r, dd).items()}
        sh = layout.ENVELOPE_ALLOWANCE_M
        pair = next(((a, b) for a in outl for b in outl if a < b and planner.Rect(outl[a].x0 + sh, outl[a].y0 + sh, outl[a].x1 - sh, outl[a].y1 - sh).overlaps(
            planner.Rect(outl[b].x0 + sh, outl[b].y0 + sh, outl[b].x1 - sh, outl[b].y1 - sh))), None)
        if pair is None:
            break
        a, b = pair
        rank = lambda n: 0 if n.startswith("section") else 1 if n.startswith("extra") else 2 if n == "iso" else 9
        mover, fixed = (a, b) if rank(a) <= rank(b) else (b, a)
        if rank(mover) == 9:
            rep["unresolved"].append({"views": [a, b], "why": "neither view is free to move (aligned orthographic views)"})
            break
        m, f = outl[mover], outl[fixed]
        cands = [(f.x1 - m.x0 + gap, 0.0), (f.x0 - m.x1 - gap, 0.0), (0.0, f.y1 - m.y0 + gap), (0.0, f.y0 - m.y1 - gap)]
        cands.sort(key=lambda d: abs(d[0]) + abs(d[1]))
        done = False
        tv = dd.s.typed(dd.views[mover], "IView")
        px, py = [float(c) for c in tv.Position]
        for dx, dy in cands:
            nr = planner.Rect(m.x0 + dx, m.y0 + dy, m.x1 + dx, m.y1 + dy)
            # room for the view's own dimension lanes and labels: 12 mm from the title block / notes, 8 mm from other views
            if not nr.inside(usable) or any(nr.grow(0.012).overlaps(k) for k in keep) or any(nr.grow(0.008).overlaps(o) for n_, o in outl.items() if n_ != mover):
                continue
            tv.Position = com_doubles(px + dx, py + dy)
            got = planner.Rect(*dd.view_outline(mover))
            if abs(got.x0 - nr.x0) < 2e-3 and abs(got.y0 - nr.y0) < 2e-3:
                rep["moved"].append({"view": mover, "delta_mm": [round(dx * 1000, 1), round(dy * 1000, 1)], "because": f"outline overlapped {fixed}"})
                done = True
                break
            tv.Position = com_doubles(px, py)              # locked (aligned to its parent): put it back
        if not done:
            rep["unresolved"].append({"views": [a, b], "why": "no clear position for the free view that SOLIDWORKS allows (alignment locked or no room)"})
            break
    return rep


def layout_loop(r, dd, st) -> dict:
    """Measured, bounded correction: native Auto Arrange evaluated on its own merits, then collision-aware moves; the best revision is kept."""
    max_iter = int(r.job.options.get("max_iterations", DEFAULT_ITERATIONS))
    rep: dict = {"max_iterations": max_iter, "history": [], "arrange": {}, "moves": []}
    rep["views"] = separate_views(r, dd)
    outl = outlines(r, dd)
    # three views of the same truth: native inventory, exported PDF text, native outlines
    snap0 = snapshot(st)
    pdf0, pages0, scale_err = export_measure(r, dd, st, "iter0")
    if scale_err:
        rep["error"] = scale_err
        r.issues.append(qa.issue("high", "LAYOUT_UNMEASURED", scale_err, part_id=r.part.part_id, next_action="Review the PDF layout manually."))
        return rep
    t2a = map_all(pages0[0].texts, snap0)
    ours = set(t2a.values())
    col0 = detect_now(r, dd, st, pages0, outl, ours)
    s0 = layout.score(col0)
    rep["history"].append({"iteration": 0, "what": "as generated", "collisions": len(col0), "score": s0})
    best = {"score": s0, "snap": snap0, "col": col0, "pages": pages0, "pdf": pdf0, "label": "as generated"}
    rep["before"] = layout.summarize(col0, float(r.job.options.get("clearance_mm", layout.DEFAULT_CLEARANCE_MM)))
    # native auto arrange: accepted only if the measured layout is not worse AND the inventory is intact (ids, values, attachments)
    try:
        ar = st.arrange(0.0)
        pdfa, pagesa, errA = export_measure(r, dd, st, "iter_arrange")
        t2a_a = map_all(pagesa[0].texts, snapshot(st))
        ours_a = set(t2a_a.values())
        cola = detect_now(r, dd, st, pagesa, outl, ours_a)
        sa = layout.score(cola)
        integ = ar["integrity"]
        accept = bool(integ["ok"]) and sa <= s0 and not errA
        rep["arrange"] = {"views": ar["views"], "moved": ar["moved"], "integrity": integ, "collisions_before": len(col0), "collisions_after": len(cola),
                          "score_before": s0, "score_after": sa, "accepted": accept,
                          "decision": ("kept: measured collisions did not increase and every dimension id, value and attachment is intact" if accept else
                                       "rejected and positions restored: " + ("inventory changed" if not integ["ok"] else "measured collision score would increase" if sa > s0 else str(errA))),
                          "inventory_before": [{k: i[k] for k in ("id", "value_m", "position_m", "attached_entities", "dangling")} for i in ar["before"]],
                          "inventory_after": [{k: i[k] for k in ("id", "value_m", "position_m", "attached_entities", "dangling")} for i in ar["after"]]}
        rep["history"].append({"iteration": 0, "what": "native Auto Arrange", "collisions": len(cola), "score": sa, "accepted": accept})
        if accept:
            best = {"score": sa, "snap": snapshot(st), "col": cola, "pages": pagesa, "pdf": pdfa, "label": "native Auto Arrange", "ours": ours_a, "t2a": t2a_a}
            t2a, ours = t2a_a, ours_a
        else:
            restore_snapshot(dd, st, snap0)
    except Exception as e:      # noqa: BLE001
        rep["arrange"] = {"accepted": False, "error": f"{type(e).__name__}: {e}"}
        restore_snapshot(dd, st, snap0)
    # own collision-aware correction rounds
    seen = {_pos_key(best["snap"])}
    stagnant = 0
    for it in range(1, max_iter + 1):
        if not [c for c in best["col"] if c.severity != "low"]:
            break
        r._check_cancel()
        pm = best["pages"][0]
        ann_by_tid = {tid: aid for aid, tid in (best.get("t2a") or t2a).items()}
        cur_snap = {i["id"]: i for i in best["snap"]}
        boxes = {t.id: t for t in pm.texts}
        strokes = _model_strokes(pm, outl)
        usable = planner.Rect(*r.plan["regions_m"]["usable"])
        reg = {k: planner.Rect(*v) for k, v in r.plan["regions_m"].items()}
        keep = {"title_block": (reg["title_block"].x0, reg["title_block"].y0, reg["title_block"].x1, reg["title_block"].y1)}
        cl = float(r.job.options.get("clearance_mm", layout.DEFAULT_CLEARANCE_MM)) / 1000.0
        moved_boxes: dict[str, layout.TBox] = {}
        moves = []
        targets: list[str] = []
        for c in best["col"]:
            for tid in (c.b if c.kind == "text_text" and c.b in ann_by_tid else None, c.a if c.a in ann_by_tid else None):
                if tid and tid not in targets and tid in ann_by_tid:
                    targets.append(tid)
                    break
        for tid in targets:
            aid = ann_by_tid[tid]
            rec = cur_snap.get(aid)
            tb = boxes.get(tid)
            if rec is None or tb is None:
                continue
            others = [b for k, b in boxes.items() if k != tid and k not in moved_boxes] + list(moved_boxes.values())
            for dx, dy in layout.propose_offsets(tb, tb.horizontal):
                if layout.free_at(tb, dx, dy, others, strokes, {k: v for k, v in outl.items() if k != rec["view"] and rec.get("kind") != "note"}, (usable.x0, usable.y0, usable.x1, usable.y1), keep, cl, rec["view"]):
                    nb = layout.TBox(tb.id, tb.text, tb.x0 + dx, tb.y0 + dy, tb.x1 + dx, tb.y1 + dy)
                    moved_boxes[tid] = nb
                    moves.append({"annotation": aid, "text": tb.text, "delta_mm": [round(dx * 1000, 1), round(dy * 1000, 1)], "kind": rec.get("kind", "dimension"),
                                  "to": (round(rec["position_m"][0] + dx, 6), round(rec["position_m"][1] + dy, 6)), "select_name": rec.get("select_name"), "view_name": rec["view_name"],
                                  "note_index": rec.get("note_index")})
                    break
        if not moves:
            rep["history"].append({"iteration": it, "what": "no free position found for the colliding annotations", "collisions": len(best["col"]), "score": best["score"]})
            break
        applied = 0
        for m in moves:
            ok_ = (move_note(dd, st, m["view_name"], m["note_index"], m["to"]) if m["kind"] == "note" else move_annotation(dd, st, m["select_name"], m["view_name"], m["to"]))
            if ok_:
                applied += 1
        pdfi, pagesi, errI = export_measure(r, dd, st, f"iter{it}")
        t2a_i = map_all(pagesi[0].texts, snapshot(st))
        ours_i = set(t2a_i.values())
        coli = detect_now(r, dd, st, pagesi, outl, ours_i)
        si = layout.score(coli)
        snap_i = snapshot(st)
        key = _pos_key(snap_i)
        entry = {"iteration": it, "what": "collision-aware moves", "moved": applied, "moves": [{k: v for k, v in m.items() if k not in ("select_name", "view_name", "to", "note_index")} for m in moves],
                 "collisions": len(coli), "score": si}
        rep["history"].append(entry)
        rep["moves"] += entry["moves"]
        if si < best["score"] and key not in seen and not errI:
            best = {"score": si, "snap": snap_i, "col": coli, "pages": pagesi, "pdf": pdfi, "label": f"correction {it}", "t2a": t2a_i, "ours": ours_i}
            seen.add(key)
            stagnant = 0
        else:
            entry["rejected"] = "did not improve the measured layout (or repeated an earlier arrangement); positions restored to the best revision"
            restore_snapshot(dd, st, best["snap"])
            stagnant += 1
            if stagnant >= 2:
                break
    restore_snapshot(dd, st, best["snap"])        # the document ends on the best measured revision
    r.best_ours = best.get("ours", ours)
    r.best_t2a = best.get("t2a", t2a)
    rep["after"] = layout.summarize(best["col"], float(r.job.options.get("clearance_mm", layout.DEFAULT_CLEARANCE_MM)))
    rep["best"] = best["label"]
    rep["iterations_used"] = len([h for h in rep["history"] if h["iteration"] > 0])
    rep["unresolved"] = [c.as_dict() for c in best["col"] if c.severity != "low"]
    return rep


def _pos_key(snap: list[dict]) -> str:
    return "|".join(f"{i['id']}:{i['position_m'][0]:.4f},{i['position_m'][1]:.4f}" for i in sorted(snap, key=lambda x: x["id"]))


def _model_strokes(pm, outl: dict) -> list:
    """Stroke segments that lie inside some view outline (model edges); the dimensions' own lines are excluded from move prediction (the next measurement decides)."""
    out = []
    for sg in pm.strokes:
        mx, my = (sg[0] + sg[2]) / 2, (sg[1] + sg[3]) / 2
        if any(o[0] - 0.001 <= mx <= o[2] + 0.001 and o[1] - 0.001 <= my <= o[3] + 0.001 for o in outl.values()):
            out.append(sg)
    return out


# ------------------------------------------------------------------ comparison + correction (reference mode)

def native_views_info(r, dd) -> tuple[dict, dict]:
    plan = r.plan
    typ: dict = {}
    centers: dict = {}
    for role, sw in plan["views"].items():
        if not sw or role not in dd.views:
            continue
        t = "Isometric" if role == "iso" else (sw or "").strip("*")
        rv = ((plan.get("reference_layout") or {}).get("views", {}).get(role) or {}).get("reference_view")
        typ[role] = {"type": t, "ref_view": rv}
        try:
            o = dd.view_outline(role)
            centers[role] = {"type": t, "ref_view": rv, "center_m": [(o[0] + o[2]) / 2, (o[1] + o[3]) / 2], "outline_m": o}
        except Exception:      # noqa: BLE001
            pass
    return typ, centers


def run_comparison(r, dd, st, pages, notes_carried: set, source_notes: Optional[set] = None) -> dict:
    """Semantic + spatial comparison of the generated drawing against the reference extraction (all in sheet metres / mm)."""
    ex = r.ref_ex
    W, H = sheet_dims(r)
    dims = [i for i in st.inventory() if "error" not in i]
    typ, centers = native_views_info(r, dd)
    default_unit = "inch" if r.plan.get("units") == "inch" else "mm"
    sem = compare.semantic(ex, dims, default_unit=default_unit, notes_carried=notes_carried, native_material=(r.material or {}).get("name"), native_views=typ,
                       source_notes=source_notes, replicate=source_notes is not None)
    texts = pages[0].texts if pages else []
    ann_text = {}
    t2a = getattr(r, "best_t2a", None) or layout.map_text_to_annotations(texts, {i["id"]: tuple(i["position_m"]) for i in dims})
    byid = {t.id: t for t in texts}
    for aid, tid in t2a.items():
        if tid in byid:
            ann_text[aid] = byid[tid].center
    sp = compare.spatial(ex, W, H, centers, ann_text, sem["ledger"])
    return {"semantic": sem, "spatial": sp}


def reposition_toward_reference(r, dd, st, sem: dict, sp: dict, pages) -> dict:
    """Move matched annotations toward their reference anchors where that stays collision-free (bounded; collisions take priority over copying the source)."""
    rep = {"moves": [], "skipped": []}
    if not pages:
        return rep
    pm = pages[0]
    by_text = {t.id: t for t in pm.texts}
    t2a = getattr(r, "best_t2a", {}) or {}
    a2t = t2a
    inv = {i["id"]: i for i in st.inventory() if "error" not in i}
    outl = outlines(r, dd)
    reg = {k: planner.Rect(*v) for k, v in r.plan["regions_m"].items()}
    usable = reg["usable"]
    keep = {"title_block": (reg["title_block"].x0, reg["title_block"].y0, reg["title_block"].x1, reg["title_block"].y1)}
    cl = float(r.job.options.get("clearance_mm", layout.DEFAULT_CLEARANCE_MM)) / 1000.0
    strokes = _model_strokes(pm, outl)
    W, H = sheet_dims(r)
    by_ref = {a["id"]: a for a in r.ref_ex.get("annotations", [])}
    moved_boxes: dict[str, layout.TBox] = {}
    for item in sorted(sp["annotations"], key=lambda x: -x["distance_mm"]):
        if item["within_target"] or item["position_source"] == "model_estimate":
            continue          # model-estimated boxes are too rough to chase; OCR / text-layer positions are exact
        aid, tid = item["native"], a2t.get(item["native"])
        tb = by_text.get(tid) if tid else None
        a = by_ref.get(item["ref_id"])
        if not tb or not a or not a.get("bbox_norm"):
            continue
        bx = a["bbox_norm"]
        cx, cy = (bx[0] + bx[2]) / 2 * W, (1 - (bx[1] + bx[3]) / 2) * H
        dx, dy = cx - tb.center[0], cy - tb.center[1]
        others = [b for k, b in by_text.items() if k != tid and k not in moved_boxes] + list(moved_boxes.values())
        rec = inv.get(aid)
        if rec is None:
            continue
        if layout.free_at(tb, dx, dy, others, strokes, {k: v for k, v in outl.items() if k != rec["view"]}, (usable.x0, usable.y0, usable.x1, usable.y1), keep, cl, rec["view"]):
            if move_annotation(dd, st, rec["select_name"], rec["view_name"], (rec["position_m"][0] + dx, rec["position_m"][1] + dy)):
                moved_boxes[tid] = layout.TBox(tb.id, tb.text, tb.x0 + dx, tb.y0 + dy, tb.x1 + dx, tb.y1 + dy)
                rep["moves"].append({"annotation": aid, "ref": item["ref_id"], "delta_mm": [round(dx * 1000, 1), round(dy * 1000, 1)]})
        else:
            rep["skipped"].append({"annotation": aid, "ref": item["ref_id"], "why": "the reference position would collide with other text, a view or the title block; relocated placement kept"})
    return rep


# ------------------------------------------------------------------ replication mode (v8)

def infer_scale(ex: dict, ext: dict, units_hint: str = "") -> Optional[dict]:
    """Scale from MEASURABLE geometry when the source states none: a source view's drawn size vs the model's extents, snapped to a standard ratio within 3 %.
    Returns {num, den, basis:'inferred', error_pct} or None. An inferred scale is always labelled; it is never silently treated as explicit."""
    from reverse import srcmap
    sheet = ex.get("sheet", {})
    w_pt, h_pt = float(sheet.get("width_pt") or 0), float(sheet.get("height_pt") or 0)
    if not (w_pt and h_pt):
        return None
    dims = sorted(ext.values())
    cands = []
    for v in ex.get("views", []):
        bb = v.get("bbox_norm")
        if not bb or v.get("type") in ("Isometric", "Detail"):
            continue
        bw, bh = (bb[2] - bb[0]) * w_pt * srcmap.PT_TO_M, (bb[3] - bb[1]) * h_pt * srcmap.PT_TO_M
        for d in dims:
            for side in (bw, bh):
                if d > 0 and side > 0:
                    cands.append(side / d)
    best = None
    for num, den in planner.SCALES_INCH + planner.SCALES_METRIC:
        s = num / den
        hits = sum(1 for c in cands if abs(c - s) / s <= 0.03)
        if hits >= 2 and (best is None or hits > best[0]):
            best = (hits, num, den, statistics.fmean(abs(c - s) / s for c in cands if abs(c - s) / s <= 0.03) * 100)
    return {"num": best[1], "den": best[2], "basis": "inferred", "error_pct": round(best[3], 2), "evidence_pairs": best[0]} if best else None


def plan_replication(r) -> Optional[dict]:
    """Plan the sheet from the SOURCE: physical size, scale, view centres, keep-outs and title block. Returns None when replication cannot start (the caller
    then runs the standard reference path and says so)."""
    from reverse import replicate, templates
    ex, inv = r.ref_ex, r.inv
    dev: list[str] = []
    tgt = replicate.sheet_target(ex["sheet"])
    if not tgt.get("ok"):
        r.part.reference["warnings"].append(f"Replication could not size the sheet ({tgt.get('reason')}); the reference layout path was used.")
        return None
    stock = templates.stock_entry()
    if not stock:
        r.part.reference["warnings"].append("The stock SOLIDWORKS drawing template is not installed, so a blank sheet for replication cannot be created; the reference layout path was used.")
        return None
    prof, d1 = reflayout.pick_profile(ex, r.job.profile, "")
    dev += d1
    ss = reflayout.reference_scale(ex)
    basis = "explicit"
    ext = dict(zip("xyz", inv["size_m"]))
    if ss is None:
        inf = infer_scale(ex, ext)
        if inf:
            ss, basis = (inf["num"], inf["den"]), "inferred"
            dev.append(f"The source states no scale; {inf['num']}:{inf['den']} was INFERRED from measured view sizes (error {inf['error_pct']} %). Confirm it.")
        else:
            dev.append("The source states no scale and none could be inferred from its views; the largest standard scale that fits was used (needs review).")
    plan = planner.plan_views(tuple(inv["size_m"]), prof, hole_axes=inv["hole_axes"], scale_override=ss, force_scale=ss is not None)
    plan["scale_basis"] = basis if ss is not None else "planner_default"
    plan["scale"]["basis"] = plan["scale_basis"]
    frame = replicate.make_frame(ex["sheet"], tgt)
    try:
        lines = replicate.detect_lines(r.ref_pdf, 0)
    except Exception as e:      # noqa: BLE001
        lines = None
        dev.append(f"Sheet linework could not be detected ({type(e).__name__}); no border / title block geometry was drawn.")
    tb = replicate.title_block_bbox(ex, lines)
    segs, srep = replicate.sheet_segments(lines, tb, frame, ex)
    replicate.override_regions(plan, frame, tgt, tb)
    r.template = dict(stock, own_sheet_format=False)
    r.frame, r.sheet_target, r.sheet_segments, r.sheet_seg_report, r.tb_pt = frame, tgt, segs, srep, tb
    r.profile_used = prof
    dev.append(f"Blank stock sheet used (not a Solid Flow template): {tgt['note']}.")
    rec = reflayout.apply_reference(plan, ex, ext, frame=frame, replicate=True)
    # mixed scales: a source view that states its OWN scale keeps it (detail / section / reduced views); the sheet scale stays the title block's
    vscales = {}
    for role, info in (rec.get("views") or {}).items():
        v = next((x for x in ex.get("views", []) if x["id"] == info.get("reference_view")), None)
        own = reflayout.parse_scale((v or {}).get("scale_text", "")) if v else None
        if own and own != (plan["scale"]["num"], plan["scale"]["den"]):
            vscales[role] = own
    plan["view_scales"] = {k: list(v) for k, v in vscales.items()}
    if vscales:
        dev.append("Views with their own printed scale keep it: " + ", ".join(f"{k} {v[0]}:{v[1]}" for k, v in vscales.items()))
    rec["sheet_deviations"] = dev
    rec["deviations"] = dev + rec["deviations"]
    rec["replicate"] = True
    return plan


def place_source_notes(r, dd, st) -> set:
    """Replication: every source text that is not an associative dimension, verbatim and editable, at its source position (no placeholder / heading text)."""
    from reverse import replicate
    ex = r.ref_ex
    dims = [i for i in st.inventory() if "error" not in i]
    default_unit = "inch" if r.plan.get("units") == "inch" else "mm"
    sem0 = compare.semantic(ex, dims, default_unit=default_unit, notes_carried=set(), native_material=(r.material or {}).get("name"), native_views={}, replicate=True)
    notes = replicate.collect_notes(ex, sem0["ledger"])
    recs = replicate.place_notes(r, dd, r.frame, notes)
    r.note_recs = recs
    r.source_notes = {x["id"] for x in recs if x.get("placed") and x["source"] == "annotation"}
    r.carried = {x["id"] for x in recs if x.get("placed") and x["source"] == "note"}
    failed = [x for x in recs if not x.get("placed")]
    for x in failed:
        r.issues.append(qa.issue("high", "SOURCE_NOTE_NOT_PLACED", f"The source text could not be placed as a note: {x['text'][:60]!r}", part_id=r.part.part_id, source_ref=x["id"],
                                 next_action="Add this text manually; it is preserved in drawing_spec.json."))
    return r.carried


def _view_positions(dd) -> dict:
    return {role: [float(v) for v in dd.s.typed(tv, "IView").Position] for role, tv in dd.views.items()}


def _restore_views(dd, pos: dict) -> None:
    from reverse.drawing import com_doubles
    for role, p in pos.items():
        try:
            dd.s.typed(dd.views[role], "IView").Position = com_doubles(*p)
        except Exception:      # noqa: BLE001
            pass


def view_center_deviation(r, dd) -> list[dict]:
    """Native outline centre vs the matched source view's centre, in sheet mm (frame-registered)."""
    out = []
    ex = r.ref_ex
    for role, info in ((r.plan.get("reference_layout") or {}).get("views") or {}).items():
        rv = info.get("reference_view")
        if not rv or role not in dd.views:
            continue
        v = next((x for x in ex.get("views", []) if x["id"] == rv), None)
        if not v:
            continue
        tx, ty = r.frame.norm_to_sheet(*v["center_norm"])
        try:
            o = dd.view_outline(role)
        except Exception:      # noqa: BLE001
            continue
        cx, cy = (o[0] + o[2]) / 2, (o[1] + o[3]) / 2
        d = math.hypot(cx - tx, cy - ty) * 1000
        out.append({"role": role, "ref_view": rv, "target_m": [round(tx, 6), round(ty, 6)], "actual_m": [round(cx, 6), round(cy, 6)], "dx_mm": round((cx - tx) * 1000, 2),
                    "dy_mm": round((cy - ty) * 1000, 2), "distance_mm": round(d, 2)})
    return out


def correct_view_centres(r, dd, th: dict) -> dict:
    """Move each view so its measured outline centre sits on the source centre (base first: projected views keep their alignment, so only their free axis can
    move). Verified by outline read-back; a move that SOLIDWORKS refuses or that leaves the sheet is undone and reported."""
    from reverse.drawing import com_doubles
    rep = {"moves": [], "locked": []}
    order = [x for x in ("front", "top", "right", "iso") if x in dd.views] + [x for x in dd.views if x not in ("front", "top", "right", "iso")]
    for role in order:
        dev = {d["role"]: d for d in view_center_deviation(r, dd)}.get(role)
        if not dev or dev["distance_mm"] <= th["view_center_mm"] * 0.5:
            continue
        tv = dd.s.typed(dd.views[role], "IView")
        p0 = [float(v) for v in tv.Position]
        dx, dy = -dev["dx_mm"] / 1000.0, -dev["dy_mm"] / 1000.0
        tv.Position = com_doubles(p0[0] + dx, p0[1] + dy)
        after = {d["role"]: d for d in view_center_deviation(r, dd)}.get(role)
        if after and after["distance_mm"] < dev["distance_mm"] - 0.05:
            rep["moves"].append({"role": role, "from_mm": dev["distance_mm"], "to_mm": after["distance_mm"], "delta_mm": [round(dx * 1000, 2), round(dy * 1000, 2)], "reason": "source centre"})
        else:
            tv.Position = com_doubles(*p0)
            rep["locked"].append({"role": role, "distance_mm": dev["distance_mm"], "why": "SOLIDWORKS keeps this view aligned to its parent (or the move did not reduce the deviation)"})
    return rep


def annotation_pairs(r, snap, pages, sem) -> list[dict]:
    """Matched (reference annotation, native dimension, measured text box) triples with the source target centre in sheet metres."""
    byt = {t.id: t for t in pages[0].texts} if pages else {}
    t2a = map_all(pages[0].texts, snap) if pages else {}
    a2t = {aid: tid for aid, tid in t2a.items()}
    by_ref = {a["id"]: a for a in r.ref_ex.get("annotations", [])}
    inv = {i["id"]: i for i in snap if i.get("kind") == "dimension"}
    out = []
    for e in sem["ledger"]:
        if e.get("status") not in ("matched", "matched_shared") or not e.get("native_id"):
            continue
        a = by_ref.get(e["ref_id"])
        rec = inv.get(e["native_id"])
        tb = byt.get(a2t.get(e["native_id"])) if rec else None
        if not a or not a.get("bbox_pt") or rec is None or tb is None:
            continue
        cx, cy = r.frame.to_sheet((a["bbox_pt"][0] + a["bbox_pt"][2]) / 2, (a["bbox_pt"][1] + a["bbox_pt"][3]) / 2)
        out.append({"ref_id": e["ref_id"], "native_id": e["native_id"], "text": e.get("text", ""), "tbox": tb, "tid": tb.id, "rec": rec, "target": (cx, cy),
                    "position_source": a.get("position_source"), "dev_mm": math.hypot(tb.center[0] - cx, tb.center[1] - cy) * 1000})
    return out


def place_annotations_from_source(r, dd, st, pages, sem, outl, th) -> dict:
    """Source-coordinate placement: every matched dimension text is moved to the centre of its source annotation (hard preference), then ONLY measured
    collisions displace an item, by the smallest free offset; every displacement and its reason is recorded. The result is accepted only when the measured
    collision score is no worse than the layout it started from."""
    rep = {"applied": [], "displaced": [], "kept": [], "skipped": []}
    snap0 = snapshot(st)
    pairs = [p for p in annotation_pairs(r, snap0, pages, sem)]
    base_col = detect_now(r, dd, st, pages, outl, set(map_all(pages[0].texts, snap0).values()) | getattr(r, "note_text_ids", set()))
    base_score = layout.score(base_col)
    rep["baseline"] = {"collisions": len(base_col), "score": base_score}
    moved = []
    for p in sorted(pairs, key=lambda x: -x["dev_mm"]):
        if p["position_source"] == "model_estimate":
            rep["skipped"].append({"ref_id": p["ref_id"], "why": "the source position is a model estimate (no text evidence); not chased"})
            continue
        dx, dy = p["target"][0] - p["tbox"].center[0], p["target"][1] - p["tbox"].center[1]
        if math.hypot(dx, dy) < 0.0003:
            rep["kept"].append({"ref_id": p["ref_id"], "deviation_mm": round(p["dev_mm"], 2)})
            continue
        rec = p["rec"]
        if move_annotation(dd, st, rec["select_name"], rec["view_name"], (rec["position_m"][0] + dx, rec["position_m"][1] + dy)):
            moved.append(p)
            rep["applied"].append({"ref_id": p["ref_id"], "native": p["native_id"], "delta_mm": [round(dx * 1000, 1), round(dy * 1000, 1)], "from_mm": round(p["dev_mm"], 1)})
    if not moved:
        return rep
    pdf1, pages1, err1 = export_measure(r, dd, st, "rep_src")
    snap1 = snapshot(st)
    t2a1 = map_all(pages1[0].texts, snap1)
    ours1 = set(t2a1.values()) | getattr(r, "note_text_ids", set())
    col1 = detect_now(r, dd, st, pages1, outl, ours1)
    # minimal displacement for the colliding ones only
    byt = {t.id: t for t in pages1[0].texts}
    a2t = {aid: tid for aid, tid in t2a1.items()}
    strokes = _model_strokes(pages1[0], outl)
    reg = {k: planner.Rect(*v) for k, v in r.plan["regions_m"].items()}
    usable = reg["usable"]
    keep = {"title_block": (reg["title_block"].x0, reg["title_block"].y0, reg["title_block"].x1, reg["title_block"].y1)}
    cl = float(r.job.options.get("clearance_mm", layout.DEFAULT_CLEARANCE_MM)) / 1000.0
    inv1 = {i["id"]: i for i in snap1 if i.get("kind") == "dimension"}
    by_native = {p["native_id"]: p for p in moved}
    why_for: dict[str, str] = {}
    for c in col1:
        for tid in (c.a, c.b):
            aid = next((a for a, t in a2t.items() if t == tid), None)
            if aid in by_native and aid not in why_for:
                why_for[aid] = f"{c.kind} collision (measured) at the source position: {c.a_text} / {c.b_text}".strip(" /")
    moved_boxes: dict[str, layout.TBox] = {}
    for aid, why in why_for.items():
        tid = a2t[aid]
        tb = byt.get(tid)
        rec = inv1.get(aid)
        if tb is None or rec is None:
            continue
        others = [b for k, b in byt.items() if k != tid and k not in moved_boxes] + list(moved_boxes.values())
        for dx, dy in layout.propose_offsets(tb, tb.horizontal):
            if layout.free_at(tb, dx, dy, others, strokes, {k: v for k, v in outl.items() if k != rec["view"]}, (usable.x0, usable.y0, usable.x1, usable.y1), keep, cl, rec["view"]):
                if move_annotation(dd, st, rec["select_name"], rec["view_name"], (rec["position_m"][0] + dx, rec["position_m"][1] + dy)):
                    moved_boxes[tid] = layout.TBox(tb.id, tb.text, tb.x0 + dx, tb.y0 + dy, tb.x1 + dx, tb.y1 + dy)
                    rep["displaced"].append({"native": aid, "ref_id": by_native[aid]["ref_id"], "text": by_native[aid]["text"], "displacement_mm": round(math.hypot(dx, dy) * 1000, 1),
                                             "delta_mm": [round(dx * 1000, 1), round(dy * 1000, 1)], "reason": why})
                break
    pdf2, pages2, err2 = export_measure(r, dd, st, "rep_src2")
    snap2 = snapshot(st)
    t2a2 = map_all(pages2[0].texts, snap2)
    col2 = detect_now(r, dd, st, pages2, outl, set(t2a2.values()) | getattr(r, "note_text_ids", set()))
    s2 = layout.score(col2)
    rep["after"] = {"collisions": len(col2), "score": s2}
    if s2 <= base_score and not err2:
        rep["accepted"] = True
        r.best_t2a, r.best_ours = t2a2, set(t2a2.values())
    else:
        rep["accepted"] = False
        rep["decision"] = (f"source positions rejected: measured collision score {s2} would be worse than the generated layout's {base_score}; positions restored. "
                           "Every annotation keeps its generated position and is reported as a position deviation.")
        restore_snapshot(dd, st, snap0)
    return rep


def annotation_anchor_deviation(r, st, pages, sem) -> list[dict]:
    """Final measured distance (mm) of each matched dimension text from its source box centre."""
    snap = snapshot(st)
    return [{"ref_id": p["ref_id"], "native": p["native_id"], "text": p["text"], "distance_mm": round(p["dev_mm"], 2), "position_source": p["position_source"]}
            for p in annotation_pairs(r, snap, pages, sem)]


def replication_loop(r, dd, st) -> dict:
    """Bounded closed loop (default 3 iterations): measure -> correct views, note offsets, annotation positions -> re-export -> compare; keep the best candidate.
    Stops on pass, no improvement, the iteration cap or a budget stop (no model call is made here, so the budget cannot be the stop in practice)."""
    from reverse import replicate
    th = replicate.thresholds(r.job.options.get("replication_thresholds") and {"replication_thresholds": r.job.options["replication_thresholds"]})
    max_iter = int(r.job.options.get("max_iterations", DEFAULT_ITERATIONS))
    hist: list[dict] = []
    stop = "iteration_cap"
    best = None
    sem_final = None
    pages = None
    for it in range(0, max_iter + 1):
        r._check_cancel()
        pdf, pages, err = export_measure(r, dd, st, f"rep{it}")
        if err:
            raise worker.CadError(err)
        if it == 0 or True:
            note_rep = replicate.refine_note_positions(r, dd, r.note_recs, pages, r.frame)
            if note_rep["shifted"]:
                pdf, pages, err = export_measure(r, dd, st, f"rep{it}n")
        r.note_text_ids = _note_text_ids(r, pages)
        outl = outlines(r, dd)
        cmp_ = run_comparison(r, dd, st, pages, r.carried, source_notes=r.source_notes)
        vdev = view_center_deviation(r, dd)
        adev = annotation_anchor_deviation(r, st, pages, cmp_["semantic"])
        col = detect_now(r, dd, st, pages, outl, set(map_all(pages[0].texts, snapshot(st)).values()) | r.note_text_ids)
        obj = sum(v["distance_mm"] for v in vdev) * 3 + sum(a["distance_mm"] for a in adev) + layout.score(col) * 20
        entry = {"iteration": it, "view_dev_max_mm": max((v["distance_mm"] for v in vdev), default=None), "annotation_dev_median_mm": round(statistics.median([a["distance_mm"] for a in adev]), 2) if adev else None,
                 "annotation_dev_max_mm": max((a["distance_mm"] for a in adev), default=None), "collisions": len(col), "objective": round(obj, 2), "notes_shifted": note_rep["shifted"]}
        hist.append(entry)
        cur = {"obj": obj, "views": _view_positions(dd), "snap": snapshot(st), "pages": pages, "pdf": pdf, "cmp": cmp_, "vdev": vdev, "adev": adev, "col": col, "it": it}
        improved = best is None or obj < best["obj"] - 0.05
        if improved:
            best = cur
        else:
            entry["rejected"] = "no measured improvement; the best earlier revision was restored"
            _restore_views(dd, best["views"])
            restore_snapshot(dd, st, best["snap"])
            stop = "no_improvement"
            break
        within = (not vdev or max(v["distance_mm"] for v in vdev) <= th["view_center_mm"]) and (not adev or max(a["distance_mm"] for a in adev) <= th["annotation_anchor_mm"]) \
            and not [c for c in col if c.severity != "low"]
        if within:
            stop = "passed"
            break
        if it == max_iter:
            break
        vrep = correct_view_centres(r, dd, th)
        entry["views_moved"] = vrep["moves"]
        entry["views_locked"] = vrep["locked"]
        pdf1, pages1, err1 = export_measure(r, dd, st, f"rep{it}v")
        outl1 = outlines(r, dd)
        cmp1 = run_comparison(r, dd, st, pages1, r.carried, source_notes=r.source_notes)
        arep = place_annotations_from_source(r, dd, st, pages1, cmp1["semantic"], outl1, th)
        entry["annotation_placement"] = {k: arep.get(k) for k in ("baseline", "after", "accepted", "decision")} | {"moved": len(arep["applied"]), "displaced": len(arep["displaced"]), "skipped": len(arep["skipped"])}
        r.displacements = getattr(r, "displacements", []) + arep["displaced"]
        r.placement_reports = getattr(r, "placement_reports", []) + [arep]
    # final state = the best candidate
    _restore_views(dd, best["views"])
    restore_snapshot(dd, st, best["snap"])
    pdf_f, pages_f, err_f = export_measure(r, dd, st, "rep_final")
    r.note_text_ids = _note_text_ids(r, pages_f)
    t2a_f = map_all(pages_f[0].texts, snapshot(st))
    r.best_t2a, r.best_ours = t2a_f, set(t2a_f.values())
    outl_f = outlines(r, dd)
    cmp_f = run_comparison(r, dd, st, pages_f, r.carried, source_notes=r.source_notes)
    r.comparison = cmp_f
    r.comparison["iterations"] = {"used": max(0, len(hist) - 1), "max": max_iter, "best": best["it"], "history": hist, "stop_reason": stop}
    r.rep_state = {"vdev": view_center_deviation(r, dd), "adev": annotation_anchor_deviation(r, st, pages_f, cmp_f["semantic"]), "pages": pages_f, "pdf": pdf_f,
                   "col": detect_now(r, dd, st, pages_f, outl_f, set(t2a_f.values()) | r.note_text_ids)}
    return r.comparison["iterations"]


def _note_text_ids(r, pages) -> set:
    """Text boxes of the source notes that are NOT inside the source title block (title-block text is intentionally inside its keep-out)."""
    if not pages:
        return set()
    from reverse import replicate
    tb = r.plan["regions_m"]["title_block"]
    ids: set = set()
    for rec in getattr(r, "note_recs", []):
        tx, ty = rec.get("target_center_m") or (None, None)
        if tx is None or (tb[0] <= tx <= tb[2] and tb[1] <= ty <= tb[3]):
            continue
        lines = {replicate.norm_text(t) for t in rec["text"].split("\n") if replicate.norm_text(t)}
        ids.update(t.id for t in pages[0].texts if replicate.norm_text(t.text) in lines and math.hypot(t.center[0] - tx, t.center[1] - ty) <= 0.25)
    return ids


# ------------------------------------------------------------------ additional source pages (multi-sheet replication)

STD_VIEW_FOR = {"Front": "*Front", "Top": "*Top", "Right": "*Right", "Left": "*Left", "Back": "*Back", "Bottom": "*Bottom", "Isometric": "*Isometric"}


def build_extra_sheets(r, dd) -> list[dict]:
    """Every source page after the first becomes its own sheet, in order: sheet size from the page, sheet scale from its title block (or the first page's, labelled),
    border / title-block geometry, standard views (named orientation of the model, source scale and centre), and ALL of the page's text as verbatim editable
    notes at the source positions. Dimensions are not generated on these sheets (no per-sheet dimensioner), so every dimension-like item is a non-associative source
    note that needs review; section / detail / auxiliary views are not rebuilt and are reported."""
    from reverse import replicate
    from reverse.drawing import com_doubles
    out: list[dict] = []
    base_sc = (r.plan["scale"]["num"], r.plan["scale"]["den"])
    for i, ex_i in enumerate(r.ref_pages[1:], start=2):
        rec = {"page": i, "status": "built", "views": [], "views_not_reproduced": [], "warnings": []}
        out.append(rec)
        tgt = replicate.sheet_target(ex_i["sheet"])
        if not tgt.get("ok"):
            rec.update(status="failed", error="the source page size is unknown")
            continue
        sc = reflayout.reference_scale(ex_i)
        rec["scale_basis"] = "explicit" if sc else "first_page_scale_assumed"
        if sc is None:
            sc = base_sc
            rec["warnings"].append("This page states no scale; the first page's scale was used (needs review).")
        frame = replicate.make_frame(ex_i["sheet"], tgt)
        name = f"Sheet{i}"
        try:
            dd.add_sheet(name, tgt["w_m"], tgt["h_m"], sc, r.plan["projection"] == "first")
        except Exception as e:      # noqa: BLE001
            rec.update(status="failed", error=f"{type(e).__name__}: {e}")
            continue
        rec.update(name=name, frame=frame, target=tgt, scale=list(sc))
        try:
            lines = replicate.detect_lines(r.ref_pdf, i - 1)
            tb = replicate.title_block_bbox(ex_i, lines)
            segs, srep = replicate.sheet_segments(lines, tb, frame, ex_i)
            rec["sheet_geometry"] = {"segments_drawn": dd.sheet_lines(segs, scale=sc[0] / sc[1]), **srep}
        except Exception as e:      # noqa: BLE001
            rec["warnings"].append(f"sheet geometry: {type(e).__name__}: {e}")
        # views
        for v in ex_i.get("views", []):
            sw = STD_VIEW_FOR.get(v["type"])
            if sw is None:
                rec["views_not_reproduced"].append({"id": v["id"], "type": v["type"], "why": "section / detail / auxiliary views are not rebuilt"})
                continue
            vs = reflayout.parse_scale(v.get("scale_text", "")) or sc
            cx, cy = frame.norm_to_sheet(*v["center_norm"])
            try:
                tv = dd.add_view_on_sheet(sw, (cx, cy), vs[0] / vs[1])
                o = [float(x) for x in tv.GetOutline()]
                dx, dy = cx - (o[0] + o[2]) / 2, cy - (o[1] + o[3]) / 2
                if abs(dx) > 1e-4 or abs(dy) > 1e-4:
                    p0 = [float(x) for x in tv.Position]
                    tv.Position = com_doubles(p0[0] + dx, p0[1] + dy)
                o = [float(x) for x in tv.GetOutline()]
                rec["views"].append({"id": v["id"], "type": v["type"], "sw_view": sw, "scale": list(vs), "target_m": [cx, cy],
                                     "dev_mm": round(math.hypot((o[0] + o[2]) / 2 - cx, (o[1] + o[3]) / 2 - cy) * 1000, 2)})
            except Exception as e:      # noqa: BLE001
                rec["views_not_reproduced"].append({"id": v["id"], "type": v["type"], "why": f"{type(e).__name__}: {e}"})
        dd.set_sheet_scale((sc[0], sc[1]))
        # text: everything, verbatim, editable
        notes = replicate.collect_notes(ex_i, None)
        rec["note_recs"] = replicate.place_notes(r, dd, frame, notes)
    dd.activate_sheet("Sheet1")
    return out


def refine_extra_sheet_notes(r, dd, pages) -> None:
    from reverse import replicate
    for rec in getattr(r, "extra_pages", []):
        if rec.get("status") != "built" or not rec.get("note_recs"):
            continue
        dd.activate_sheet(rec["name"])
        rec["refine"] = replicate.refine_note_positions(r, dd, rec["note_recs"], pages, rec["frame"], page=rec["page"] - 1)
    dd.activate_sheet("Sheet1")
