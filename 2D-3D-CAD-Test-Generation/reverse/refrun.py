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
                                               client=refs.client, part=r.part.part_id, progress=msgs.append)
    except budget.BudgetExceeded:
        raise
    ex = res["extraction"]
    use = res["usage"]
    r.ref_ex = ex
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


def run_comparison(r, dd, st, pages, notes_carried: set) -> dict:
    """Semantic + spatial comparison of the generated drawing against the reference extraction (all in sheet metres / mm)."""
    ex = r.ref_ex
    W, H = sheet_dims(r)
    dims = [i for i in st.inventory() if "error" not in i]
    typ, centers = native_views_info(r, dd)
    default_unit = "inch" if r.plan.get("units") == "inch" else "mm"
    sem = compare.semantic(ex, dims, default_unit=default_unit, notes_carried=notes_carried, native_material=(r.material or {}).get("name"), native_views=typ)
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
