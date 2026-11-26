"""3D -> 2D (reverse) pipeline: everything that does not need SOLIDWORKS. Live evidence: tools in docs/phase2-evidence and `python -m reverse.cli`."""
from __future__ import annotations

import json
import os
import struct
from pathlib import Path

import pytest

from reverse import inventory, jobs, planner, qa, safety, service, state, templates, worker
from reverse.planner import Rect


# ------------------------------------------------------------------ safety

def test_authorize_accepts_inside_and_refuses_outside_traversal_and_relative(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    f = root / "a.SLDPRT"
    f.write_bytes(b"x")
    assert safety.authorize(f, [root]) == Path(os.path.realpath(f))
    with pytest.raises(safety.SafetyError):
        safety.authorize(tmp_path / "other.SLDPRT", [root])
    with pytest.raises(safety.SafetyError):
        safety.authorize(root / ".." / "other.SLDPRT", [root])
    with pytest.raises(safety.SafetyError):
        safety.authorize("relative/a.SLDPRT", [root])
    with pytest.raises(safety.SafetyError):
        safety.authorize("C:\\x\x00y", [root])


def test_symlink_escape_is_refused(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "out"
    root.mkdir()
    outside.mkdir()
    (outside / "p.SLDPRT").write_bytes(b"x")
    link = root / "link"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted here")
    with pytest.raises(safety.SafetyError):
        safety.authorize(link / "p.SLDPRT", [root])


@pytest.mark.parametrize("name,ok", [("a.SLDPRT", True), ("a.sldprt", True), ("A.SldPrt", True), ("a.SLDASM", False), ("a.SLDDRW", False), ("a.step", False),
                                     ("a.stl", False), ("a.txt", False), ("~$a.SLDPRT", False)])
def test_part_file_checks(tmp_path, name, ok):
    f = tmp_path / name
    f.write_bytes(b"data")
    if ok:
        assert safety.check_part_file(f)["name"] == name
    else:
        with pytest.raises(safety.SafetyError):
            safety.check_part_file(f)


def test_empty_and_missing_parts_refused(tmp_path):
    e = tmp_path / "e.SLDPRT"
    e.write_bytes(b"")
    with pytest.raises(safety.SafetyError):
        safety.check_part_file(e)
    with pytest.raises(safety.SafetyError):
        safety.check_part_file(tmp_path / "missing.SLDPRT")


def test_duplicate_basenames_get_distinct_ids_and_unicode_spaces_are_safe(tmp_path):
    ps = [tmp_path / "a" / "Plate A.SLDPRT", tmp_path / "b" / "Plate A.SLDPRT", tmp_path / "c" / "Plate A.SLDPRT", tmp_path / "caf\u00e9 \u00fcber.SLDPRT"]
    ids = [i for _, i in safety.dedupe_ids(ps)]
    assert ids[:3] == ["Plate_A", "Plate_A-2", "Plate_A-3"] and len(set(ids)) == 4
    assert all(safety.ID_RE.match(i) for i in ids)
    assert safety.safe_id("../../etc/passwd") == "etc_passwd" and safety.safe_id("") == "part"


def test_discover_parts_is_case_insensitive_recursive_and_skips_lock_files(tmp_path):
    (tmp_path / "sub").mkdir()
    for n in ("a.SLDPRT", "b.sldprt", "~$c.SLDPRT", "d.SLDASM", "sub/e.SLDPRT"):
        (tmp_path / n).write_bytes(b"x")
    flat = [p.name for p in safety.discover_parts(tmp_path)]
    deep = [p.name for p in safety.discover_parts(tmp_path, recursive=True)]
    assert flat == ["a.SLDPRT", "b.sldprt"] and deep == ["a.SLDPRT", "b.sldprt", "e.SLDPRT"]


def test_readonly_output_dir_is_reported(tmp_path):
    f = tmp_path / "file"
    f.write_text("x")
    assert safety.writable_dir(f / "sub") is not None            # a path under a FILE cannot be created
    assert safety.writable_dir(tmp_path / "ok") is None


# ------------------------------------------------------------------ state machine / store

def test_state_transitions():
    assert state.can_move("queued", "preflight") and not state.can_move("queued", "drawing")
    assert state.can_move("mesh_export", "inventory") and not state.can_move("drawing", "mesh_export")
    assert not state.can_move("completed", "failed") and state.can_move("drawing", "failed") and state.can_move("drawing", "canceled")
    assert not state.can_move("queued", "completed")


def make_job(n=2):
    j = state.Job(job_id="r3d_test", template_id="t")
    j.parts = [state.PartState(part_id=f"p{i}", source=f"C:/x/p{i}.SLDPRT", name=f"p{i}.SLDPRT") for i in range(n)]
    return j


def test_store_roundtrip_is_atomic_and_events_append(tmp_path):
    st = state.JobStore(tmp_path)
    j = make_job()
    st.save(j)
    assert not list((tmp_path / j.job_id).glob("*.tmp"))
    again = st.load(j.job_id)
    assert [p.part_id for p in again.parts] == ["p0", "p1"]
    st.event(j.job_id, "a")
    st.event(j.job_id, "b", "p0", x=1)
    ev = st.events(j.job_id)
    assert [e["kind"] for e in ev] == ["a", "b"] and ev[1]["x"] == 1 and st.events(j.job_id, after=1)[0]["kind"] == "b"


def test_progress_is_measured_stage_completion_not_time():
    j = make_job(2)
    assert state.progress(j)["fraction"] == 0
    state.begin_stage(j.parts[0], "preflight")
    state.end_stage(j.parts[0], "preflight")
    pr = state.progress(j)
    assert pr["stages_done"] == 1 and pr["stages_total"] == 2 * len(state.STAGES) and 0 < pr["fraction"] < 1
    state.finish(j.parts[0], "review_required")
    assert state.progress(j)["stages_done"] == len(state.STAGES)


def test_summary_state_mixed_results_stay_visible():
    j = make_job(3)
    state.finish(j.parts[0], "completed")
    state.finish(j.parts[1], "failed", "boom")
    state.finish(j.parts[2], "review_required")
    assert j.summary_state() == "completed_with_failures"
    j2 = make_job(2)
    state.finish(j2.parts[0], "failed", "x")
    state.finish(j2.parts[1], "failed", "y")
    assert j2.summary_state() == "failed"


def test_recover_marks_interrupted_parts_failed_and_keeps_finished_ones(tmp_path):
    st = state.JobStore(tmp_path)
    j = make_job(2)
    j.parts[0].state = "drawing"
    j.parts[1].state = "review_required"
    st.save(j)
    assert st.recover() == [j.job_id]
    r = st.load(j.job_id)
    assert r.parts[0].state == "failed" and "restarted" in r.parts[0].error and r.parts[1].state == "review_required"


# ------------------------------------------------------------------ job creation (batch isolation)

def test_create_job_rejects_bad_files_but_keeps_good_ones(tmp_path):
    good, asm, empty = tmp_path / "a.SLDPRT", tmp_path / "b.SLDASM", tmp_path / "c.SLDPRT"
    good.write_bytes(b"x")
    asm.write_bytes(b"x")
    empty.write_bytes(b"")
    st = state.JobStore(tmp_path / "out")
    j = jobs.create_job(st, template={"id": "t"}, part_paths=[good, asm, empty, tmp_path / "missing.SLDPRT"])
    assert [p.name for p in j.parts] == ["a.SLDPRT"]
    assert {r["name"] for r in j.options["rejected"]} == {"b.SLDASM", "c.SLDPRT", "missing.SLDPRT"}
    with pytest.raises(safety.SafetyError, match="No valid"):
        jobs.create_job(st, template={"id": "t"}, part_paths=[asm])
    with pytest.raises(safety.SafetyError, match="profile"):
        jobs.create_job(st, template={"id": "t"}, part_paths=[good], profile="nope")


# ------------------------------------------------------------------ planner

def test_scale_is_the_largest_standard_one_that_fits_and_layout_has_no_collisions():
    for bb in [(0.0762, 0.0508, 0.0254), (0.3, 0.2, 0.1), (0.02, 0.02, 0.2), (0.1, 0.1, 0.1)]:
        pl = planner.plan_views(bb)
        assert pl["scale_fits"]
        reg = {k: Rect(*v) for k, v in pl["regions_m"].items()}
        rects = {k: Rect(*v) for k, v in pl["rects_m"].items()}
        names = list(rects)
        for r in rects.values():
            assert r.inside(reg["usable"]) and not r.overlaps(reg["title_block"]) and not r.overlaps(reg["notes"])
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                assert not rects[names[i]].overlaps(rects[names[j]])
        # a larger standard scale must not have fit
        larger = [s for s in planner.SCALES_INCH if s[0] / s[1] > pl["scale"]["num"] / pl["scale"]["den"]]
        if larger:
            nxt = larger[-1]
            assert planner.layout_at_scale(pl["front_view"], planner.extents(bb), nxt[0] / nxt[1], "third", {k: Rect(*v) for k, v in pl["regions_m"].items()}) is None


def test_third_angle_puts_top_above_and_right_beside_first_angle_swaps():
    t = planner.plan_views((0.08, 0.05, 0.03), "us_third_angle_inch")
    r = {k: Rect(*v) for k, v in t["rects_m"].items()}
    assert r["top"].y0 >= r["front"].y1 and r["right"].x0 >= r["front"].x1
    f = planner.plan_views((0.08, 0.05, 0.03), "iso_first_angle_a3")
    r = {k: Rect(*v) for k, v in f["rects_m"].items()}
    assert r["top"].y1 <= r["front"].y0 and r["right"].x1 <= r["front"].x0


def test_front_view_choice_prefers_the_busiest_silhouette_and_ties_prefer_front():
    assert planner.choose_front({"x": 0.08, "y": 0.04, "z": 0.07}, {}) == "*Top"
    assert planner.choose_front({"x": 0.05, "y": 0.05, "z": 0.05}, {}) == "*Front"
    assert planner.choose_front({"x": 0.08, "y": 0.04, "z": 0.07}, {}, override="*Right") == "*Right"


def test_part_too_big_for_any_scale_says_so_instead_of_crowding():
    pl = planner.plan_views((20.0, 20.0, 20.0))
    assert pl["scale_fits"] is False and pl["notes"]


def test_isometric_steps_down_in_scale_instead_of_vanishing():
    pl = planner.plan_views((0.08255, 0.0381, 0.06985))
    assert "iso" in pl["rects_m"] and pl["iso_scale"] <= pl["scale"]["num"] / pl["scale"]["den"]


@pytest.mark.parametrize("bad", [(0, 1, 1), (-1, 1, 1), (float("nan"), 1, 1), (1, 1)])
def test_bad_bounding_box_is_refused(bad):
    with pytest.raises(ValueError):
        planner.plan_views(bad)


def test_profiles_set_sheet_and_scale_family():
    assert planner.plan_views((0.1, 0.1, 0.1), "metric_a3_third_angle")["paper"].startswith("A3")
    assert planner.plan_views((0.1, 0.1, 0.1), "us_third_angle_inch_c")["paper"].startswith("ANSI C")
    with pytest.raises(ValueError):
        planner.plan_views((0.1, 0.1, 0.1), "nope")


# ------------------------------------------------------------------ inventory clustering (synthetic B-rep dicts)

def cyl(face, origin, axis, radius, box, concave=True):
    return {"face": face, "origin": origin, "axis": axis, "radius": radius, "box_m": box, "concave": concave, "area_m2": 1e-4, "edges": 2}


BBOX = (-0.04, -0.02, -0.03, 0.04, 0.02, 0.03)


def test_through_hole_and_grid_pattern_are_recognised():
    c = []
    for i, (x, z) in enumerate([(-0.03, -0.02), (0.03, -0.02), (-0.03, 0.02), (0.03, 0.02)]):
        c.append(cyl(i, [x, 0, z], [0, 1, 0], 0.005, [x - 0.005, -0.02, z - 0.005, x + 0.005, 0.02, z + 0.005]))
    cl = inventory.cluster_holes({"cylinders": c, "cones": [], "bbox_m": BBOX})
    assert len(cl["holes"]) == 4 and all(h["through"] and h["axis"] == "y" and abs(h["diameter_m"] - 0.01) < 1e-9 for h in cl["holes"])
    pats = inventory.hole_patterns(cl["holes"])
    assert len(pats) == 1 and pats[0]["rectangular_grid"] and pats[0]["count"] == 4 and abs(pats[0]["u_pitch_m"] - 0.06) < 1e-4 and abs(pats[0]["v_pitch_m"] - 0.04) < 1e-4


def test_blind_counterbored_hole_is_one_stack_with_the_counterbore_and_entry_side():
    c = [cyl(0, [0, 0, 0], [0, 1, 0], 0.012, [-0.012, -0.02, -0.012, 0.012, -0.017, 0.012]), cyl(1, [0, 0, 0], [0, 1, 0], 0.007, [-0.007, -0.017, -0.007, 0.007, 0.005, 0.007])]
    h = inventory.cluster_holes({"cylinders": c, "cones": [], "bbox_m": BBOX})["holes"][0]
    assert not h["through"] and h["entry_side"] == "-" and h["counterbore"] and abs(h["counterbore"]["diameter_m"] - 0.024) < 1e-9
    assert abs(h["diameter_m"] - 0.014) < 1e-9 and abs(h["depth_m"] - 0.025) < 1e-9


def test_two_holes_on_one_axis_line_with_a_gap_stay_two_holes():
    c = [cyl(0, [0, 0, 0], [0, 1, 0], 0.004, [-0.004, -0.02, -0.004, 0.004, -0.01, 0.004]), cyl(1, [0, 0, 0], [0, 1, 0], 0.004, [-0.004, 0.01, -0.004, 0.004, 0.02, 0.004])]
    assert len(inventory.cluster_holes({"cylinders": c, "cones": [], "bbox_m": BBOX})["holes"]) == 2


def test_bosses_and_off_axis_cylinders_are_not_holes_and_are_flagged():
    c = [cyl(0, [0, 0, 0], [0, 1, 0], 0.01, [-0.01, -0.02, -0.01, 0.01, 0.02, 0.01], concave=False),
         cyl(1, [0, 0, 0], [0.7071, 0.7071, 0], 0.003, [0, 0, 0, 0.01, 0.01, 0.01])]
    cl = inventory.cluster_holes({"cylinders": c, "cones": [], "bbox_m": BBOX})
    assert cl["holes"] == [] and len(cl["bosses"]) == 1 and cl["unsupported"][0]["kind"] == "cylinder_off_axis"


def test_irregular_holes_are_not_called_a_grid():
    c = [cyl(i, [x, 0, z], [0, 1, 0], 0.005, [x - 0.005, -0.02, z - 0.005, x + 0.005, 0.02, z + 0.005]) for i, (x, z) in enumerate([(-0.03, -0.02), (0.03, 0.0), (0.0, 0.02)])]
    pats = inventory.hole_patterns(inventory.cluster_holes({"cylinders": c, "cones": [], "bbox_m": BBOX})["holes"])
    assert pats and not pats[0]["rectangular_grid"]


def test_axis_name():
    assert inventory.axis_name([0, 0, -1]) == "z" and inventory.axis_name([0.7, 0.7, 0]) is None


# ------------------------------------------------------------------ STL validation

def write_binary_stl(path, tris):
    with open(path, "wb") as f:
        f.write(b"\0" * 80)
        f.write(struct.pack("<I", len(tris)))
        for t in tris:
            f.write(struct.pack("<12f", 0, 0, 1, *[c for v in t for c in v]) + b"\0\0")


def test_stl_validation_binary_ascii_corrupt_and_scale(tmp_path):
    tris = [((0, 0, 0), (82.55, 0, 0), (0, 38.1, 0)), ((0, 0, 69.85), (82.55, 0, 0), (0, 38.1, 69.85))]
    b = tmp_path / "b.stl"
    write_binary_stl(b, tris)
    rec = worker.validate_stl(b)
    assert rec["ok"] and rec["triangles"] == 2 and rec["size_mm"] == [82.55, 38.1, 69.85]
    cmp_ = worker.compare_stl_to_native(rec, (0, 0, 0, 0.08255, 0.0381, 0.06985))
    assert cmp_["ok"] and cmp_["worst_relative_error"] < 1e-6
    wrong = worker.compare_stl_to_native(rec, (0, 0, 0, 0.0033, 0.0015, 0.00275))          # an inch/mm scale mistake
    assert not wrong["ok"]
    a = tmp_path / "a.stl"
    a.write_text("solid x\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 1\nendloop\nendfacet\nendsolid x\n")
    assert worker.validate_stl(a)["format"] == "ascii" and worker.validate_stl(a)["ok"]
    bad = tmp_path / "bad.stl"
    bad.write_bytes(b"\0" * 80 + struct.pack("<I", 5) + b"\0" * 10)
    assert not worker.validate_stl(bad)["ok"]
    assert not worker.validate_stl(tmp_path / "nope.stl")["ok"]
    nan = tmp_path / "nan.stl"
    write_binary_stl(nan, [((0, 0, 0), (float("nan"), 0, 0), (0, 1, 0))])
    assert not worker.validate_stl(nan)["ok"]


# ------------------------------------------------------------------ QA: ledger, collisions, PDF

def test_coverage_is_none_not_100_when_nothing_was_identified_and_exclusions_stay_visible():
    L = qa.Ledger()
    assert L.coverage()["percent"] is None
    L.add(qa.LedgerItem(id="1", characteristic="a", category="size", source="geometry_derived", status="covered"))
    L.add(qa.LedgerItem(id="2", characteristic="b", category="size", source="geometry_derived", status="review_required"))
    L.add(qa.LedgerItem(id="3", characteristic="c", category="size", source="geometry_derived", status="not_applicable", reason="cosmetic"))
    c = L.coverage()
    assert c["percent"] == 50.0 and c["applicable"] == 2 and c["excluded"][0]["reason"] == "cosmetic"


def test_duplicate_is_semantic_not_numeric():
    L = qa.Ledger()
    L.add(qa.LedgerItem(id="1", characteristic="H1:diameter", category="feature", source="geometry_derived", value=0.01, annotation_id="D1", status="covered"))
    L.add(qa.LedgerItem(id="2", characteristic="H2:diameter", category="feature", source="geometry_derived", value=0.01, annotation_id="D2", status="covered"))
    assert L.duplicates() == []                                   # same number, different feature
    L.add(qa.LedgerItem(id="3", characteristic="H1:diameter", category="feature", source="geometry_derived", value=0.01, annotation_id="D3", status="covered"))
    assert L.duplicates()[0]["annotations"] == ["D1", "D3"]


def test_box_collisions_overlap_clearance_title_block_and_outside():
    usable = Rect(0, 0, 1, 1)
    tb = Rect(0.6, 0, 1, 0.2)
    boxes = [qa.TextBox("a", Rect(0.1, 0.1, 0.2, 0.15)), qa.TextBox("b", Rect(0.15, 0.12, 0.25, 0.17)), qa.TextBox("c", Rect(0.2005, 0.1, 0.3, 0.15)),
             qa.TextBox("d", Rect(0.7, 0.05, 0.8, 0.1)), qa.TextBox("e", Rect(0.95, 0.5, 1.1, 0.55)), qa.TextBox("f", Rect(0.5, 0.5, 0.6, 0.55), sheet=2)]
    kinds = {(c["kind"], c.get("a"), c.get("b")) for c in qa.box_collisions(boxes, 0.002, [tb], usable)}
    assert ("text_overlap", "a", "b") in kinds and ("text_too_close", "a", "c") in kinds and ("title_block_collision", "d", None) in kinds and ("outside_sheet", "e", None) in kinds
    assert not any("f" in (k[1], k[2]) for k in kinds)


def make_pdf(path, items):
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=600, height=400)
    for txt, pos, color in items:
        page.insert_text(pos, txt, fontsize=12, color=color)
    page.draw_line((10, 10), (200, 10), color=(0, 0, 0))
    doc.save(str(path))


def test_pdf_checks_accept_black_flag_colour_overlap_and_wrong_page_count(tmp_path):
    ok = tmp_path / "ok.pdf"
    make_pdf(ok, [("3.250", (50, 100), (0, 0, 0)), ("2.375", (50, 200), (0, 0, 0))])
    r = qa.pdf_checks(ok, 1, tmp_path / "pv")
    assert r["ok"] and r["pages"] == 1 and (tmp_path / "pv" / "page-001.png").is_file()
    col = tmp_path / "col.pdf"
    make_pdf(col, [("RED", (50, 100), (1, 0, 0))])
    assert qa.pdf_checks(col, 1)["nonblack_text"] and not qa.pdf_checks(col, 1)["ok"]
    ov = tmp_path / "ov.pdf"
    make_pdf(ov, [("ABCDEFG", (50, 100), (0, 0, 0)), ("1234567", (52, 101), (0, 0, 0))])
    assert qa.pdf_checks(ov, 1)["text_overlaps"]
    assert not qa.pdf_checks(ok, 2)["ok"]                                  # a sheet is missing from the PDF
    assert not qa.pdf_checks(tmp_path / "none.pdf", 1)["exists"]


def test_review_issue_has_the_fields_the_ui_needs():
    i = qa.issue("high", "X", "msg", source_ref="D001", view="front", sheet=1, observed="1", expected="2", next_action="fix", part_id="p")
    assert {"id", "severity", "code", "message", "source_ref", "view", "sheet", "observed", "expected", "next_action", "history"} <= set(i)


# ------------------------------------------------------------------ service: artifacts, review audit, estimate (no SolidWorks)

@pytest.fixture()
def svc(tmp_path):
    s = service.ReverseService(tmp_path / "data", [tmp_path / "data" / "in"])
    return s


def seed_job(s, with_file=True):
    j = make_job(1)
    j.job_id = "r3d_seed"
    p = j.parts[0]
    base = s.store.dir(j.job_id) / "p0" / "active"
    base.mkdir(parents=True)
    (base / "drawing.pdf").write_bytes(b"%PDF-1.4 x")
    (base / "qa.json").write_text(json.dumps({"issues": []}))
    p.artifacts = {"drawing.pdf": "p0/active/drawing.pdf", "qa.json": "p0/active/qa.json", "drawing.slddrw": "p0/active/drawing.slddrw"}   # the .slddrw does NOT exist
    p.issues = [qa.issue("high", "VALUE_MISMATCH", "m", part_id="p0"), qa.issue("info", "DESIGN_INTENT", "i", part_id="p0")]
    p.state, p.review_status = "review_required", "required"
    s.store.save(j)
    return j, p


def test_job_view_lists_only_existing_files_and_never_server_paths(svc):
    j, p = seed_job(svc)
    v = svc.job_view(j.job_id)
    files = v["parts"][0]["files"]
    assert set(files) == {"drawing.pdf", "qa.json"}                                # the absent SLDDRW is not advertised
    assert "source" not in v["parts"][0] and "output_root" not in v and str(svc.data) not in json.dumps(v)


def test_artifact_download_is_limited_to_listed_artifacts_of_the_job(svc):
    j, p = seed_job(svc)
    assert svc.artifact_path(j.job_id, "p0/active/drawing.pdf").is_file()
    for bad in ("../../job.json", "p0/active/../../job.json", "p0/active/secret.txt", "job.json", "p0/active/drawing.slddrw"):
        with pytest.raises(safety.SafetyError):
            svc.artifact_path(j.job_id, bad)


def test_review_needs_a_note_is_audited_and_never_releases(svc):
    j, p = seed_job(svc)
    hi = p.issues[0]["id"]
    with pytest.raises(safety.SafetyError):
        svc.review_action(j.job_id, "p0", hi, "accept", user="u", note="  ")
    out = svc.review_action(j.job_id, "p0", hi, "accept", user="eng1", note="checked against the model")
    assert out["issue"]["history"][-1]["user"] == "eng1" and out["issue"]["disposition"] == "accepted"
    assert out["part_state"] == "completed" and out["review_status"] == "resolved"     # 'completed' = reviewed, not released
    again = svc.review_action(j.job_id, "p0", hi, "reopen", user="eng2")
    assert again["part_state"] == "review_required"
    with pytest.raises(safety.SafetyError):
        svc.review_action(j.job_id, "p0", "nope", "accept", note="x")
    assert json.loads((svc.store.dir(j.job_id) / "p0/active/qa.json").read_text())["review_status"] == "required"


def test_rejected_issue_keeps_the_part_in_review(svc):
    j, p = seed_job(svc)
    out = svc.review_action(j.job_id, "p0", p.issues[0]["id"], "reject", user="e", note="wrong value")
    assert out["part_state"] == "review_required"


def test_estimate_is_not_enough_data_until_three_parts_finished(svc):
    assert svc.estimate(5)["available"] is False
    j = make_job(4)
    for p, sec in zip(j.parts, (10.0, 20.0, 30.0, 40.0)):
        p.state, p.seconds = "review_required", sec
    svc.store.save(j)
    e = svc.estimate(2)
    assert e["available"] and e["low_s"] <= e["high_s"] and "percentile" in e["basis"]


def test_running_job_cannot_be_deleted(svc):
    j = make_job(1)
    j.parts[0].state = "drawing"
    svc.store.save(j)
    with pytest.raises(safety.SafetyError):
        svc.delete_job(j.job_id)


def test_template_catalog_refuses_non_drwdot_and_sheet_format_alone(tmp_path):
    cat = templates.TemplateCatalog(tmp_path / "t")
    for name in ("a.txt", "a.slddrt"):
        f = tmp_path / name
        f.write_bytes(b"x")
        with pytest.raises(templates.TemplateError):
            cat.add_uploaded(None, f)                      # refused before SOLIDWORKS is ever asked
    with pytest.raises(templates.TemplateError):
        cat.get("nope")


def test_generated_templates_shipped_with_the_repo_are_real_files():
    d = Path(__file__).resolve().parents[1] / "config" / "drawing_templates"
    if not d.is_dir():
        pytest.skip("templates not generated on this machine")
    for key in ("solidflow-ansi-b", "solidflow-ansi-c", "solidflow-a3"):
        m = json.loads((d / f"{key}.manifest.json").read_text(encoding="utf-8"))
        assert m["validation"]["ok"] and m["validation"]["views"] == 0 and m["own_sheet_format"]
        f = next(p for p in d.iterdir() if p.name.lower() == f"{key}.drwdot")
        assert f.stat().st_size > 5000 and f.read_bytes()[:8] != b"NOT A TE"       # a real native file, not text renamed
        assert (d / f"{key}_preview.pdf").is_file()


# ------------------------------------------------------------------ sections + bolt circles (pure geometry)

def _hole(i, axis, entry, thru, cx, cy, axes, cb=None, d=0.01, depth=0.02):
    return {"id": i, "axis": axis, "entry_side": entry, "through": thru, "center_axes": axes, "center_m": [cx, cy], "counterbore": cb, "diameter_m": d, "depth_m": depth}


def test_section_plan_cuts_through_the_row_with_the_most_holes_and_leaves_through_holes_alone():
    from reverse import sections
    hs = [_hole("H1", "y", "-", False, -0.017, 0.0, ["x", "z"], cb={"diameter_m": 0.025}), _hole("H2", "y", "-", False, 0.017, 0.0, ["x", "z"], cb={"diameter_m": 0.025}),
          _hole("H3", "y", "-", False, 0.017, 0.03, ["x", "z"], cb={"diameter_m": 0.025}), _hole("H4", "y", "both", True, 0.03, 0.02, ["x", "z"]),
          _hole("H5", "x", "+", False, 0.0, 0.0, ["y", "z"])]
    p = sections.plan_sections(hs)
    assert [s["label"] for s in p] == ["A", "B"]
    a = p[0]
    assert a["axis"] == "y" and a["cut_along"] == "x" and a["at_axis"] == "z" and a["covers"] == ["H1", "H2"] and a["at_m"] == 0.0
    assert sections.uncovered(hs, p) == ["H3"]                    # off the cutting line: stays a review item, never silently dropped
    assert all(not sections.needs_section(h) for h in hs if h["id"] == "H4")


def test_no_sections_when_every_hole_is_a_plain_through_hole():
    from reverse import sections
    assert sections.plan_sections([_hole("H1", "y", "both", True, 0, 0, ["x", "z"])]) == []


def test_bolt_circle_equal_spacing_pcd_and_opposite_pairs():
    import math
    hs = [_hole(f"H{i}", "z", "+", True, 0.1 * math.cos(2 * math.pi * i / 8), 0.1 * math.sin(2 * math.pi * i / 8), ["x", "y"]) for i in range(8)]
    c = inventory.circular_patterns(hs)
    assert len(c) == 1 and c[0]["count"] == 8 and c[0]["equal_spacing"] and abs(c[0]["pcd_m"] - 0.2) < 1e-9 and len(c[0]["opposite_pairs"]) == 4


def test_unequal_ring_and_off_circle_holes_are_not_called_a_bolt_circle():
    import math
    ring = [_hole(f"H{i}", "z", "+", True, 0.1 * math.cos(a), 0.1 * math.sin(a), ["x", "y"]) for i, a in enumerate([0, 0.5, 2.0, 4.0])]
    # the centre comes from the centroid of the holes, so a lopsided ring is NOT claimed as a bolt circle: its holes keep individual callouts and locations
    assert inventory.circular_patterns(ring) == []
    # a symmetric ring with an unequal step (holes in opposite pairs) IS a circle, and is reported as not equally spaced
    pairs = [_hole(f"P{i}", "z", "+", True, 0.1 * math.cos(a), 0.1 * math.sin(a), ["x", "y"]) for i, a in enumerate([0.0, 0.5, math.pi, math.pi + 0.5])]
    c = inventory.circular_patterns(pairs)
    assert c and not c[0]["equal_spacing"] and len(c[0]["opposite_pairs"]) == 2
    scatter = [_hole(f"H{i}", "z", "+", True, x, y, ["x", "y"]) for i, (x, y) in enumerate([(0, 0.05), (0.07, 0.0), (0.0, 0.11), (0.12, 0.12)])]
    assert inventory.circular_patterns(scatter) == []
    assert inventory.circular_patterns(ring[:2]) == []                 # fewer than three holes is not a pattern


# ------------------------------------------------------------------ store robustness found by the UI integration

def test_a_cancel_survives_a_stale_save_and_only_clear_cancel_removes_it(tmp_path):
    st = state.JobStore(tmp_path)
    j = make_job(2)
    st.save(j)
    worker_copy = st.load(j.job_id)                    # the running worker's in-memory Job (cancel_requested False)
    api = st.load(j.job_id)
    api.cancel_requested = True
    st.save(api)                                       # the API cancels while the worker is busy
    worker_copy.parts[0].state = "drawing"
    st.save(worker_copy)                               # the worker re-saves its stale copy
    assert st.load(j.job_id).cancel_requested is True  # the cancel was NOT lost
    st.clear_cancel(j.job_id)
    assert st.load(j.job_id).cancel_requested is False


def test_retry_shows_the_parts_as_queued_at_once_and_clears_the_cancel(svc):
    j = make_job(2)
    j.job_id = "r3d_retry"
    state.finish(j.parts[0], "failed", "boom")
    state.finish(j.parts[1], "completed")
    j.cancel_requested = True
    svc.store.save(j)
    svc.queue.submit = lambda *a, **k: None            # no CAD worker in this test
    svc.retry(j.job_id)
    r = svc.store.load(j.job_id)
    assert r.parts[0].state == "queued" and r.parts[0].error == "" and r.parts[1].state == "completed" and r.cancel_requested is False


def test_history_rows_carry_thumbnail_and_solidworks_info(svc):
    j, p = seed_job(svc)
    pv = svc.store.dir(j.job_id) / "p0" / "active" / "preview"
    pv.mkdir(parents=True)
    (pv / "page-001.png").write_bytes(b"\x89PNG")
    p.artifacts["preview/page-001.png"] = "p0/active/preview/page-001.png"
    j.solidworks = {"revision": "33.5.0"}
    svc.store.save(j)
    row = svc.history()[0]
    assert row["solidworks"]["revision"] == "33.5.0" and row["parts"][0]["thumbnail"].endswith("page-001.png")
