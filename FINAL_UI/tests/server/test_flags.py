"""Server-side validation of engineering-flag artifacts (Stage 3, task 3.4)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
import flags as F  # noqa: E402

SHA = "a" * 64


def finding(i=1, **kw):
    d = {"schema_version": 1, "finding_id": f"flag_{i:012x}", "part": "P1", "run_id": "run_a", "severity": "error",
         "category": "feature_not_built", "title": f"Finding {i}", "expected": "E", "actual": "A", "consequence": "C",
         "recommended_action": "R", "feature_ids": ["F003"], "source_callouts": ["M6 X 1"], "evidence_ids": ["plan:F003"]}
    d.update(kw)
    return d


def overlay(i=1, **kw):
    d = {"overlay_id": f"ov_{i}", "finding_id": f"flag_{i:012x}", "number": i, "severity": "error", "label": f"{i}: Finding {i}",
         "page_index": 0, "shape": "rect", "rect_normalized": {"x": 0.1, "y": 0.2, "width": 0.1, "height": 0.05},
         "label_anchor_normalized": {"x": 0.21, "y": 0.2}, "mapping_method": "exact_tokens", "mapping_confidence": 0.97,
         "matched_text": "M6 X 1", "rotation_degrees": 0, "source_callout": "M6 X 1", "provenance": "automatic"}
    d.update(kw)
    return d


def write(out, findings=None, overlays=None, run="run_a", sha=SHA, schema=1, unlocated=None):
    out.mkdir(parents=True, exist_ok=True)
    (out / "engineering_findings.json").write_text(json.dumps({"schema_version": schema, "run_id": run, "part": "P1",
                                                               "findings": findings if findings is not None else [finding()]}), encoding="utf-8")
    (out / "engineering_flag_overlays.json").write_text(json.dumps({
        "schema_version": schema, "source_pdf_sha256": sha, "run_id": run, "source_name": "d.pdf",
        "pages": [{"page_index": 0, "width": 600, "height": 400, "rotation": 0, "text_source": "text_layer"}],
        "overlays": overlays if overlays is not None else [overlay()], "unlocated_findings": unlocated or []}), encoding="utf-8")


def test_no_artifacts_means_not_present(tmp_path):
    assert F.load_flags(tmp_path, current_sha=SHA, latest_run_id="run_a") == {"present": False, "reason": "none"}


def test_a_verified_current_run_serves_findings_and_overlays(tmp_path):
    write(tmp_path)
    r = F.load_flags(tmp_path, current_sha=SHA, latest_run_id="run_a")
    assert r["present"] and r["hash_verified"] and not r["stale"] and r["run_id"] == "run_a" and r["source_sha256"] == SHA
    assert [f["title"] for f in r["findings"]] == ["Finding 1"] and len(r["overlays"]) == 1
    assert r["counts"] == {"findings": 1, "located": 1, "unlocated": 0}
    assert r["artifacts"]["annotated_pdf"] is None                       # only advertised when the file exists
    (tmp_path / "engineering_flags_annotated.pdf").write_bytes(b"%PDF-1.4")
    assert F.load_flags(tmp_path, current_sha=SHA, latest_run_id="run_a")["artifacts"]["annotated_pdf"] == "engineering_flags_annotated.pdf"


def test_a_changed_drawing_revision_withholds_overlays_but_keeps_the_findings(tmp_path):
    write(tmp_path)
    r = F.load_flags(tmp_path, current_sha="b" * 64, latest_run_id="run_a")
    assert r["present"] and r["stale"] and r["reason"] == "drawing_revision_changed"
    assert r["overlays"] == [] and r["withheld_overlays"] == 1 and len(r["findings"]) == 1


def test_an_older_run_is_stale(tmp_path):
    write(tmp_path)
    r = F.load_flags(tmp_path, current_sha=SHA, latest_run_id="run_newer")
    assert r["stale"] and r["reason"] == "older_run" and r["overlays"] == []


def test_an_unverifiable_drawing_is_not_drawn_on(tmp_path):
    write(tmp_path)
    r = F.load_flags(tmp_path, current_sha=None, latest_run_id=None)
    assert r["present"] and r["hash_verified"] is False and r["overlays"] == [] and r["reason"] == "drawing_unavailable"


def test_unsupported_schema_and_garbage_are_refused(tmp_path):
    write(tmp_path, schema=2)
    assert F.load_flags(tmp_path, current_sha=SHA, latest_run_id="run_a") == {"present": False, "reason": "unsupported_schema"}
    (tmp_path / "engineering_flag_overlays.json").write_text("{nope", encoding="utf-8")
    assert F.load_flags(tmp_path, current_sha=SHA, latest_run_id="run_a") == {"present": False, "reason": "unreadable"}


def test_overlays_without_a_finding_are_dropped(tmp_path):
    write(tmp_path, findings=[finding(1)], overlays=[overlay(1), overlay(2)])            # overlay 2 has no finding
    r = F.load_flags(tmp_path, current_sha=SHA, latest_run_id="run_a")
    assert [o["finding_id"] for o in r["overlays"]] == [finding(1)["finding_id"]]


def test_only_known_keys_survive_and_text_stays_text(tmp_path):
    write(tmp_path, findings=[finding(1, html="<img src=x onerror=alert(1)>", title="<b>hole</b>\x00")],
          overlays=[overlay(1, onclick="alert(1)", label="<script>1</script>")])
    r = F.load_flags(tmp_path, current_sha=SHA, latest_run_id="run_a")
    assert "html" not in r["findings"][0] and "onclick" not in r["overlays"][0]
    assert r["findings"][0]["title"] == "<b>hole</b>"                       # control char gone, markup kept as inert text
    assert r["overlays"][0]["label"] == "<script>1</script>"


def test_geometry_is_validated_not_trusted(tmp_path):
    bad = [overlay(1, rect_normalized={"x": -1, "y": 0.2, "width": 0.1, "height": 0.05}),
           overlay(2, rect_normalized={"x": 0.9, "y": 0.2, "width": 0.5, "height": 0.05}),
           overlay(3, rect_normalized={"x": "NaN", "y": 0, "width": 1, "height": 1}),
           overlay(4, page_index=99), overlay(5)]
    write(tmp_path, findings=[finding(i) for i in range(1, 6)], overlays=bad)
    r = F.load_flags(tmp_path, current_sha=SHA, latest_run_id="run_a")
    assert [o["number"] for o in r["overlays"]] == [5]                      # only the sane box on a real page is served
    assert r["counts"]["unlocated"] == 4


def test_payload_is_bounded(tmp_path):
    n = 1000
    write(tmp_path, findings=[finding(i) for i in range(1, n + 1)], overlays=[overlay(i) for i in range(1, n + 1)])
    r = F.load_flags(tmp_path, current_sha=SHA, latest_run_id="run_a")
    assert r["truncated"] is True and len(r["findings"]) == F.MAX_FLAGS and len(r["overlays"]) <= F.MAX_FLAGS
    assert r["counts"]["findings"] == n


def test_artifact_names_are_an_allowlist_and_cannot_traverse(tmp_path):
    write(tmp_path)
    assert F.artifact_path(tmp_path, "engineering_flag_overlays.json").name == "engineering_flag_overlays.json"
    for bad in ("../secret.txt", "..\\x", "ir_report.json", "engineering_flags_annotated.pdf/../../x", "/etc/passwd", ""):
        assert F.artifact_path(tmp_path, bad) is None


def test_review_state_is_validated_and_never_edits_the_findings(tmp_path):
    write(tmp_path)
    fid = finding()["finding_id"]
    before = (tmp_path / "engineering_findings.json").read_bytes()
    st = F.set_review(tmp_path, fid, "acknowledged", "")
    assert st["state"] == "acknowledged"
    assert (tmp_path / "engineering_findings.json").read_bytes() == before         # immutable pipeline evidence
    assert F.get_review(tmp_path)[fid]["state"] == "acknowledged"
    for bad in ("fixed!", "", None, "OPEN; DROP"):
        try:
            F.set_review(tmp_path, fid, bad, "")
            assert False, bad
        except ValueError:
            pass
    try:
        F.set_review(tmp_path, fid, "dismissed_with_reason", "  ")
        assert False
    except ValueError:
        pass                                                                            # a dismissal needs a reason
    assert F.set_review(tmp_path, fid, "dismissed_with_reason", "Handled on the shop floor")["reason"] == "Handled on the shop floor"
    try:
        F.set_review(tmp_path, "flag_not_a_finding", "acknowledged", "")
        assert False
    except ValueError:
        pass


def test_a_corrected_flag_disappears_only_when_the_rerun_no_longer_produces_it(tmp_path):
    write(tmp_path, findings=[finding(1), finding(2)], overlays=[overlay(1), overlay(2)])
    f1, f2 = finding(1)["finding_id"], finding(2)["finding_id"]
    F.set_review(tmp_path, f1, "corrected_pending_rerun", "")
    F.set_review(tmp_path, f2, "acknowledged", "")
    r = F.load_flags(tmp_path, current_sha=SHA, latest_run_id="run_a")          # still produced: still shown, still pending
    assert {f["finding_id"] for f in r["findings"]} == {f1, f2} and r["resolved_history"] == []
    assert r["review"][f1]["state"] == "corrected_pending_rerun"
    write(tmp_path, findings=[finding(2)], overlays=[overlay(2)], run="run_b")  # the re-run no longer produces flag 1
    r2 = F.load_flags(tmp_path, current_sha=SHA, latest_run_id="run_b")
    assert [f["finding_id"] for f in r2["findings"]] == [f2]
    assert r2["resolved_history"] == [{"finding_id": f1, "state": "verified_corrected", "verified_in_run": "run_b"}]
    assert F.get_review(tmp_path)[f1]["state"] == "verified_corrected"
    try:
        F.set_review(tmp_path, f2, "verified_corrected", "")                    # a person cannot declare it verified
        assert False
    except ValueError:
        pass
