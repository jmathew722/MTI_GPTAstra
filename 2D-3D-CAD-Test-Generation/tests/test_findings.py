"""Engineering findings: the evidence-linked contract (Stage 3, task 3.1)."""
import json

import pytest

from pipeline.findings import (
    CATEGORIES, SCHEMA_VERSION, SEVERITIES, Finding, dedupe, findings_from_run, migrate_legacy, validate,
)


def mk(**kw):
    base = dict(part="P1", run_id="run_a", severity="error", category="feature_not_built",
                title="Tapped hole was not built", expected="M6 \u00d7 1 tapped 12 mm deep", actual="skipped: no depth",
                consequence="The thread is missing.", recommended_action="Add the tapped hole manually.",
                feature_ids=["F003"], source_callouts=["M6 X 1 - 12 DEEP"], evidence_ids=["plan:F003"])
    base.update(kw)
    return Finding.create(**base)


def test_id_is_stable_across_runs_and_changes_with_meaning():
    a, b = mk(run_id="run_a"), mk(run_id="run_b")
    assert a.finding_id == b.finding_id and a.finding_id.startswith("flag_")        # same defect, new run: same id
    assert mk(actual="skipped: other").finding_id != a.finding_id
    assert mk(feature_ids=["F004"]).finding_id != a.finding_id
    assert mk(feature_ids=["F003", "F001"]).finding_id == mk(feature_ids=["F001", "F003"]).finding_id   # order-insensitive


def test_contract_fields_and_json_round_trip():
    f = mk()
    d = f.to_dict()
    assert d["schema_version"] == SCHEMA_VERSION
    assert set(d) >= {"finding_id", "run_id", "severity", "category", "title", "expected", "actual", "consequence",
                      "recommended_action", "feature_ids", "source_callouts", "evidence_ids"}
    assert Finding.from_dict(json.loads(json.dumps(d))) == f


def test_validation_rejects_missing_evidence_and_bad_enums():
    with pytest.raises(ValueError, match="evidence"):
        mk(evidence_ids=[])
    with pytest.raises(ValueError, match="severity"):
        mk(severity="catastrophic")
    with pytest.raises(ValueError, match="title"):
        mk(title="  ")
    assert mk(category="not-a-category").category == "other"        # unknown categories degrade, never crash
    assert "error" in SEVERITIES and "feature_not_built" in CATEGORIES
    assert validate(mk()) == []


def test_unicode_symbols_survive_and_markup_stays_inert_text():
    f = mk(expected="\u00d86.5 \u00b10.1 \u2300 \u2220 90\u00b0", title="<script>alert(1)</script> hole",
           actual="a\x00b\x07c")
    assert "\u00d86.5 \u00b10.1" in f.expected                           # engineering symbols untouched
    assert f.title == "<script>alert(1)</script> hole"                   # stored as text; the UI escapes on render
    assert "\x00" not in f.actual and "\x07" not in f.actual             # control characters removed


def test_long_text_is_bounded():
    assert len(mk(expected="x" * 5000).expected) <= 1000


def test_duplicates_collapse_and_keep_first():
    a, b = mk(run_id="run_a"), mk(run_id="run_a")
    assert [f.finding_id for f in dedupe([a, b, mk(feature_ids=["F009"])])] == [a.finding_id, mk(feature_ids=["F009"]).finding_id]


def _run_dir(tmp_path, **rep):
    out = tmp_path / "P1"
    out.mkdir()
    report = {"part": "P1", "gate1": "OK", "questions": [], "cq_skipped": {}, "sw_features": {}, "mti_review": [], "sw_ok": True, "error": ""}
    report.update(rep)
    (out / "ir_report.json").write_text(json.dumps(report), encoding="utf-8")
    plan = {"plan": {"features": [{"id": "F003", "kind": "hole", "source_callouts": ["M6 X 1 - 12 DEEP"]},
                                  {"id": "F004", "kind": "hole", "source_callouts": ["\u00d8.250 THRU"]}]}}
    (out / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    return out


def test_findings_from_a_run_link_features_callouts_and_evidence(tmp_path):
    out = _run_dir(tmp_path, cq_skipped={"F003": "no depth given"}, questions=["F004: diameter unreadable"],
                   sw_features={"F003": "failed (COM error)", "F004": "built"}, mti_review=["[mti_edge_ops_last] fillet before holes"],
                   sw_ok=False)
    fs = findings_from_run(out, "run_x")
    by = {(f.category, tuple(f.feature_ids)): f for f in fs}
    skipped = by[("feature_not_built", ("F003",))]
    assert skipped.severity == "error" and skipped.source_callouts == ["M6 X 1 - 12 DEEP"]
    assert "plan:F003" in skipped.evidence_ids and any(e.startswith("ir_report:") for e in skipped.evidence_ids)
    assert skipped.actual and skipped.expected and skipped.consequence and skipped.recommended_action
    q = by[("feature_unresolved", ("F004",))]
    assert q.severity == "warning" and q.source_callouts == ["\u00d8.250 THRU"]
    assert any(f.category == "volume_mismatch" for f in fs)                       # sw_ok False
    assert any(f.category == "practice_advisory" and f.severity == "info" for f in fs)
    assert len({f.finding_id for f in fs}) == len(fs)
    assert all(f.run_id == "run_x" for f in fs)
    assert all(validate(f) == [] for f in fs)


def test_clean_run_has_no_findings(tmp_path):
    assert findings_from_run(_run_dir(tmp_path), "r") == []


def test_unknown_repairs_are_not_invented(tmp_path):
    fs = findings_from_run(_run_dir(tmp_path, sw_features={"F003": "failed (weird)"}), "r")
    action = fs[0].recommended_action.lower()
    assert "review" in action and "edit holewzd" not in action


def test_legacy_discrepancy_json_migrates_without_touching_the_file(tmp_path):
    out = _run_dir(tmp_path)
    legacy = {"part": "P1", "iou": 0.97, "gap_pct": 3.0, "explained_pct": 2.9, "reliable": True,
              "pieces": [{"kind": "ring", "side": "ours", "share_of_union_pct": 1.2, "volume_in3": 0.1,
                          "cause": "general note ALL CHAMFERS not applied"},
                         {"kind": "slab", "side": "mti", "share_of_union_pct": 0.4, "volume_in3": 0.02,
                          "cause": "open question F004: diameter unreadable"}],
              "questions": ["F004: diameter unreadable"], "general_notes": ["ALL CHAMFERS .06 X 45"]}
    p = out / "discrepancies.json"
    p.write_text(json.dumps(legacy), encoding="utf-8")
    before = p.read_bytes()
    fs = migrate_legacy(legacy, part="P1", run_id="r")
    assert p.read_bytes() == before
    assert len(fs) == 2 and {f.category for f in fs} == {"geometry_extra_material", "geometry_missing_material"}
    assert fs[0].source_callouts == ["ALL CHAMFERS"] or "ALL CHAMFERS" in " ".join(fs[0].source_callouts)
    assert all(f.evidence_ids for f in fs)
    assert any("F004" in f.feature_ids for f in fs)
