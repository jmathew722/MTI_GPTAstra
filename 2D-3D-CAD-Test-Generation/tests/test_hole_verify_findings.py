"""Verification report, Hole Wizard findings, and their path into the engineering findings (Stage 4, F-H, J)."""
import json
import math

from pipeline import findings as F
from pipeline import hole_findings as hf
from pipeline.hole_callouts import parse
from pipeline.ir.solidworks import hole_adapter as ad
from pipeline.ir.solidworks import hole_intent_v2 as v2
from pipeline.ir.solidworks import hole_verify as hv

K = 0.0254
NO_CLEARANCE = lambda d, u: False   # noqa: E731


def intent(text, **kw):
    return v2.from_parsed(parse(text), "inch", clearance_match=NO_CLEARANCE, feature_id=kw.pop("feature_id", "F007"), **kw).to_dict()


# ---- verification report -------------------------------------------------------------------------------------------
def test_verified_needs_all_five_checks_and_the_callout_round_trip_is_not_implemented():
    r = hv.build_report("F007", expected={"CounterBoreDepth": 0.123 * K}, readback={"CounterBoreDepth": 0.123 * K}, removed=1.0, reference=1.0,
                        feature_errors=[], reopened={"CounterBoreDepth": 0.123 * K}, reopened_requested=True)
    assert [c.status for c in r.checks] == ["pass", "pass", "pass", "pass", "not_implemented"]
    assert r.ok is False and r.internal_status() == "implemented_not_live_verified"     # cannot say verified today
    all_pass = hv.VerificationReport("F", [hv.Check(n, "pass") for n in hv.REQUIRED])
    assert all_pass.internal_status() == "verified"                                      # the rule itself is intact


def test_an_unmeasured_check_is_not_run_never_a_pass():
    r = hv.build_report("F1", expected={"Diameter": 0.01}, readback=None)
    assert [c.status for c in r.checks[:4]] == ["not_run"] * 4 and r.internal_status() == "implemented_not_live_verified"


def test_failures_set_failed_verification_and_name_the_mismatch():
    r = hv.build_report("F007", expected={"CounterBoreDepth": 0.123 * K}, readback={"CounterBoreDepth": 0.120 * K}, removed=1.0, reference=1.2,
                        feature_errors=["Rebuild error"], reopened=None, reopened_requested=True)
    assert r.internal_status() == "failed_verification"
    assert {c.name for c in r.failed} == {"definition", "geometry", "rebuild", "persistence"}
    assert r.check("definition").mismatches[0]["property"] == "CounterBoreDepth"


def test_persistence_detects_a_changed_definition_and_volume_after_reopen():
    ok = hv.verify_persistence({"Diameter": 0.01}, {"Diameter": 0.01}, 5.0, 5.0)
    bad = hv.verify_persistence({"Diameter": 0.01}, {"Diameter": 0.01}, 5.0, 4.0)
    assert ok.status == "pass" and bad.status == "fail" and bad.mismatches[0]["property"] == "volume"


# ---- findings from Hole Wizard problems -----------------------------------------------------------------------------
FX1 = "DRILL .44 - 2.1 DP.\nTAP .25 NPT\n2 - PLACES"
FX4 = "DR & TAP .50-13 THD.\n.8 DEEP\n4 PLACES"
FX2 = "DRILL .50 DIA. - 1.1 DEEP\nC'BORE 1.001 DIA ±.001 X .123 +.000/-.003 DEEP\n2 - PLACES"


def test_parse_ambiguity_findings_say_exactly_what_is_missing_and_carry_the_callout():
    recs = hf.from_intent(intent(FX1, feature_id="F003"))
    titles = [r["title"] for r in recs]
    assert "Thread depth not specified" in titles
    r = next(x for x in recs if x["title"] == "Thread depth not specified")
    assert r["code"] == "HW_REQUIRED_FIELD_MISSING" and r["feature_ids"] == ["F003"]
    assert r["source_callouts"] == ["DRILL .44 - 2.1 DP. TAP .25 NPT 2 - PLACES"]
    assert "Thread class not specified" in [x["title"] for x in hf.from_intent(intent(FX4))]


def test_database_mismatch_finding_uses_the_required_wording_and_all_callouts():
    pre = {"status": "failed", "code": "HW_DATABASE_VERSION_MISMATCH", "database_version": "29.01", "database_expected_version": "28.00",
           "user_action": "Point SOLIDWORKS 2025 to the 2025 data folder."}
    recs = hf.from_preflight(pre, ["DRILL .44", "DRILL .44", ".344 DIA THRU"], ["F001", "F002"])
    assert len(recs) == 1 and recs[0]["title"] == "Hole Wizard database 29.01 is incompatible with expected 28.00"
    assert recs[0]["source_callouts"] == ["DRILL .44", ".344 DIA THRU"] and recs[0]["feature_ids"] == ["F001", "F002"]
    assert hf.from_preflight({"status": "ready"}) == []


def test_creation_failure_and_readback_mismatch_findings():
    i = intent(FX1, feature_id="F003")
    out = ad.HoleOutcome("failed", "HW_CREATE_NULL", "CreateFeature returned None")
    rec = hf.from_outcome(out, i)[0]
    assert rec["title"] == "Expected native 1/4 NPT feature; feature creation failed" and rec["code"] == "HW_CREATE_NULL"
    cb = intent(FX2, feature_id="F007")
    rep = hv.build_report("F007", expected={"CounterBoreDepth": 0.123 * K}, readback={"CounterBoreDepth": 0.120 * K})
    rec2 = hf.from_verification(rep.to_dict(), cb)[0]
    assert rec2["title"] == "Counterbore depth expected .123 in; read back .12 in" and rec2["code"] == "HW_READBACK_MISMATCH"
    assert "set counterbore depth to .123 in" in rec2["recommended_action"]
    assert hf.from_outcome(ad.HoleOutcome("created"), i) == []


def test_catalog_and_advanced_hole_records():
    i = intent(FX1)
    rec = hf.from_catalog("HW_CATALOG_NO_MATCH", "no exact row; nearest: 1/4-18", i)[0]
    assert rec["title"] == "No installed catalog row matches 1/4 NPT" and rec["source_callouts"]
    adv = v2.from_parsed(parse("NEAR SIDE Ø6 X 8 DEEP, FAR SIDE Ø4 X 5 DEEP"), "mm", feature_id="F9").to_dict()
    assert any(r["code"] == "HW_ADVANCED_HOLE_NOT_IMPLEMENTED" for r in hf.from_intent(adv))


def test_records_become_engineering_findings_with_evidence_and_categories():
    recs = hf.from_intent(intent(FX1, feature_id="F003")) + hf.from_preflight(
        {"status": "failed", "code": "HW_DATABASE_VERSION_MISMATCH", "database_version": "29.01", "database_expected_version": "28.00"}, ["x"])
    fs = hf.to_findings(recs, part="P", run_id="r1")
    assert {f.category for f in fs} == {"hole_callout_unresolved", "hole_wizard_environment"}
    assert all(f.evidence_ids and not F.validate(f) for f in fs) and all(f.severity in F.SEVERITIES for f in fs)


# ---- sidecar -> findings_from_run ---------------------------------------------------------------------------------------
def test_build_records_attach_each_affected_callout_once_and_other_substitutions_individually(tmp_path):
    class Rep:
        hole_wizard_substitutions = [{"fid": "F001", "code": "HW_DATABASE_VERSION_MISMATCH", "detail": "x"},
                                     {"fid": "F002", "code": "HW_DATABASE_VERSION_MISMATCH", "detail": "x"},
                                     {"fid": "F003", "code": "HW_VOLUME_MISMATCH", "detail": "volume"}]
        hole_wizard_preflight = {"status": "failed", "code": "HW_DATABASE_VERSION_MISMATCH", "database_version": "29.01",
                                 "database_expected_version": "28.00"}

    class Feat:
        def __init__(self, i, c):
            self.id, self.source_callouts = i, c

    class Plan:
        features = [Feat("F001", ["2X Ø.266 THRU"]), Feat("F002", ["Ø.50 THRU"]), Feat("F003", ["Ø.20 X .5 DEEP"])]

    recs = hf.records_for_build(Rep, Plan)
    assert [r["code"] for r in recs] == ["HW_DATABASE_VERSION_MISMATCH", "HW_VOLUME_MISMATCH"]
    assert recs[0]["source_callouts"] == ["2X Ø.266 THRU", "Ø.50 THRU"]
    assert hf.write_sidecar(tmp_path, recs) and (tmp_path / hf.SIDECAR).is_file()
    assert hf.write_sidecar(tmp_path, []) is None and not (tmp_path / hf.SIDECAR).exists()    # no stale sidecar


def test_findings_from_run_reads_the_sidecar(tmp_path):
    (tmp_path / "ir_report.json").write_text(json.dumps({"part": "P1"}), encoding="utf-8")
    recs = hf.from_preflight({"status": "failed", "code": "HW_DATABASE_VERSION_MISMATCH", "database_version": "29.01",
                              "database_expected_version": "28.00"}, ["Ø.266 THRU"], ["F001"])
    hf.write_sidecar(tmp_path, recs)
    fs = F.findings_from_run(tmp_path, "run1")
    assert len(fs) == 1 and fs[0].title == "Hole Wizard database 29.01 is incompatible with expected 28.00"
    assert fs[0].source_callouts == ["Ø.266 THRU"] and fs[0].category == "hole_wizard_environment"


def test_units_formatting_is_engineering_style():
    assert hf.fmt(0.123) == ".123 in" and hf.fmt(2.1) == "2.1 in" and hf.fmt(6.4, "mm") == "6.4 mm" and hf.fmt(None) == "not specified"
    assert hf._read("CounterSinkAngle", math.radians(82), "inch") == "82 deg"


def test_custom_tolerances_are_kept_and_reported_as_not_modeled_never_dropped():
    recs = hf.from_intent(intent(FX2, feature_id="F007"))
    tol = [r for r in recs if r["code"] == "HW_TOLERANCE_NOT_APPLIED"]
    assert len(tol) == 2 and all(r["severity"] == "info" and r["source_callouts"] for r in tol)
    assert "±.001 in" in tol[0]["title"] and "-.003 in" in tol[1]["title"]
    assert {f.category for f in hf.to_findings(tol, part="P", run_id="r")} == {"hole_callout_unresolved"}
