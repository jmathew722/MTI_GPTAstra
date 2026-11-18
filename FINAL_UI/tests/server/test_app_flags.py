"""FastAPI wiring for engineering flags (Stage 3, tasks 3.4 and 3.6)."""
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

os.environ.setdefault("MCAGENT_REPO", str(Path(__file__).resolve().parents[3] / "2D-3D-CAD-Test-Generation"))
os.environ.setdefault("MCAGENT_DATA", tempfile.mkdtemp(prefix="mcagent_test_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
import app as appmod  # noqa: E402

SESSION = "t" + "8" * 11


def _setup(part, *, original_bytes=b"%PDF-1.4 original", artifact_sha=None, run="run_a", events_run=None):
    """A part with an uploaded original and flag artifacts computed for it."""
    sdir = appmod._session_dir(SESSION)
    pdir = sdir / part
    out = pdir / "output"
    (sdir / appmod.ORIGINALS_DIRNAME).mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    orig = sdir / appmod.ORIGINALS_DIRNAME / f"{part}.pdf"
    orig.write_bytes(original_bytes)
    sha = artifact_sha or hashlib.sha256(original_bytes).hexdigest()
    fid = "flag_" + "1" * 12
    (out / "engineering_findings.json").write_text(json.dumps({"schema_version": 1, "run_id": run, "part": part, "findings": [{
        "finding_id": fid, "part": part, "run_id": run, "severity": "error", "category": "feature_not_built", "title": "Hole not built",
        "expected": "E", "actual": "A", "consequence": "C", "recommended_action": "R", "feature_ids": ["F003"],
        "source_callouts": ["M6"], "evidence_ids": ["plan:F003"]}]}), encoding="utf-8")
    (out / "engineering_flag_overlays.json").write_text(json.dumps({
        "schema_version": 1, "source_pdf_sha256": sha, "run_id": run, "source_name": orig.name,
        "pages": [{"page_index": 0, "width": 600, "height": 400, "rotation": 0, "text_source": "text_layer"}],
        "overlays": [{"overlay_id": "ov_1", "finding_id": fid, "number": 1, "severity": "error", "label": "1: Hole not built", "page_index": 0,
                      "shape": "rect", "rect_normalized": {"x": 0.1, "y": 0.2, "width": 0.1, "height": 0.05},
                      "label_anchor_normalized": {"x": 0.21, "y": 0.2}, "mapping_method": "exact_tokens", "mapping_confidence": 0.97,
                      "matched_text": "M6", "rotation_degrees": 0, "source_callout": "M6", "provenance": "automatic"}],
        "unlocated_findings": []}), encoding="utf-8")
    if events_run:
        ev = {"schema_version": 1, "event_id": "e1", "run_id": events_run, "attempt": 1, "part_id": part, "seq": 1,
              "occurred_at": "2026-11-18T00:00:00.000Z", "kind": "run.started", "payload": {}}
        (out / "run_events.jsonl").write_text(json.dumps(ev) + "\n", encoding="utf-8")
    return out, fid


def test_flags_are_in_the_part_payload_and_verified_against_the_current_original():
    out, fid = _setup("ZZFLAG1")
    flags = appmod._categorize_output(out, session=SESSION)["categories"]["flags"]
    assert flags["present"] and flags["hash_verified"] and not flags["stale"]
    assert [o["finding_id"] for o in flags["overlays"]] == [fid]


def test_a_new_drawing_revision_makes_the_overlays_stale():
    out, _ = _setup("ZZFLAG2")
    (appmod._session_dir(SESSION) / appmod.ORIGINALS_DIRNAME / "ZZFLAG2.pdf").write_bytes(b"%PDF-1.4 a NEW revision")
    flags = appmod._categorize_output(out, session=SESSION)["categories"]["flags"]
    assert flags["stale"] and flags["reason"] == "drawing_revision_changed" and flags["overlays"] == [] and flags["withheld_overlays"] == 1


def test_overlays_from_an_older_run_are_stale():
    out, _ = _setup("ZZFLAG3", run="run_a", events_run="run_newer")
    flags = appmod._categorize_output(out, session=SESSION)["categories"]["flags"]
    assert flags["stale"] and flags["reason"] == "older_run" and flags["overlays"] == []


def test_without_a_session_the_drawing_cannot_be_verified_so_nothing_is_drawn():
    out, _ = _setup("ZZFLAG4")
    flags = appmod._categorize_output(out)["categories"]["flags"]
    assert flags["present"] and flags["hash_verified"] is False and flags["overlays"] == []


def test_no_artifacts_is_not_present():
    out = appmod._session_dir(SESSION) / "ZZFLAG5" / "output"
    out.mkdir(parents=True, exist_ok=True)
    assert appmod._categorize_output(out, session=SESSION)["categories"]["flags"] == {"present": False, "reason": "none"}


def test_flags_endpoint_and_review_round_trip_without_touching_the_findings():
    out, fid = _setup("ZZFLAG6")
    c = TestClient(appmod.app)
    before = (out / "engineering_findings.json").read_bytes()
    r = c.get(f"/api/parts/{SESSION}/ZZFLAG6/flags")
    assert r.status_code == 200 and r.json()["present"] and len(r.json()["overlays"]) == 1
    ok = c.post(f"/api/parts/{SESSION}/ZZFLAG6/flags/{fid}/review", json={"state": "acknowledged", "reason": ""})
    assert ok.status_code == 200 and ok.json()["state"] == "acknowledged"
    assert c.get(f"/api/parts/{SESSION}/ZZFLAG6/flags").json()["review"][fid]["state"] == "acknowledged"
    assert (out / "engineering_findings.json").read_bytes() == before


def test_review_endpoint_validates_everything():
    out, fid = _setup("ZZFLAG7")
    c = TestClient(appmod.app)
    url = f"/api/parts/{SESSION}/ZZFLAG7/flags/{fid}/review"
    assert c.post(url, json={"state": "fixed!", "reason": ""}).status_code == 400
    assert c.post(url, json={"state": "dismissed_with_reason", "reason": ""}).status_code == 400
    assert c.post(url, json={"state": "verified_corrected", "reason": ""}).status_code == 400
    assert c.post(f"/api/parts/{SESSION}/ZZFLAG7/flags/flag_nope/review", json={"state": "acknowledged"}).status_code == 400
    assert c.post(f"/api/parts/{SESSION}/NOPE/flags/{fid}/review", json={"state": "acknowledged"}).status_code == 404
    assert c.post(url, content=b"not json", headers={"content-type": "application/json"}).status_code in (400, 422)


def test_the_server_offers_no_way_to_post_overlay_geometry_or_html():
    paths = {r.path for r in appmod.app.routes}
    assert not any("overlay" in p and "post" in p for p in paths)
    post_paths = {r.path for r in appmod.app.routes if "POST" in getattr(r, "methods", set())}
    assert [p for p in post_paths if "flag" in p] == ["/api/parts/{session}/{part}/flags/{finding_id}/review"]


def test_child_process_gets_the_auto_flags_feature_flag(tmp_path):
    import time
    rid = appmod._start_run([sys.executable, "-c", "import os;print('F='+os.environ.get('GPTASTRA_AUTO_ENGINEERING_FLAGS',''))"], tmp_path)
    t0 = time.time()
    while not appmod.RUNS[rid]["done"] and time.time() - t0 < 15:
        time.sleep(0.05)
    assert "F=1" in appmod.RUNS[rid]["lines"]
