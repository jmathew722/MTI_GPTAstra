"""SOLIDWORKS 2025 environment gate (Stage 4, Slice A). Pure logic with fakes: nothing here touches SolidWorks."""
import time

import pytest

from pipeline.ir.solidworks import sw_preflight as pf


class FakeProbe:
    def __init__(self, **kw):
        self.d = dict(revision="33.5.0", root=r"C:\SW Data (2)", db_version="28.00", expected_db="28.00",
                      toolbox_file="33.5.0.0053", index="33.5.0.53", db_exists=True, modal=[], standards=(1, 2),
                      catalog_raises=None)
        self.d.update(kw)
        self.calls = []

    def revision(self):
        self.calls.append("revision")
        return self.d["revision"]

    def hole_wizard_root(self):
        return self.d["root"]

    def db_exists(self, root):
        return self.d["db_exists"]

    def db_version(self, root):
        return self.d["db_version"]

    def expected_db_version(self):
        return self.d["expected_db"]

    def toolbox_file_version(self, root):
        return self.d["toolbox_file"]

    def index_version(self, root):
        return self.d["index"]

    def modal_windows(self):
        self.calls.append("modal")
        return self.d["modal"]

    def catalog_standards(self):
        self.calls.append("catalog")
        if self.d["catalog_raises"]:
            raise self.d["catalog_raises"]
        return self.d["standards"]


def test_a_correct_2025_configuration_is_ready_and_fingerprinted_without_paths():
    r = pf.run_preflight(FakeProbe())
    assert r.ok and r.code is None and r.status == "ready"
    assert r.revision == "33.5.0" and r.db_version == "28.00" and r.fingerprint and len(r.fingerprint) == 64
    assert "SW Data" not in str(r.to_dict()) and r.to_dict()["standards_found"] == 2


def test_the_supplied_29_01_vs_28_00_mismatch_stops_before_the_catalog_and_is_not_retryable():
    p = FakeProbe(db_version="29.01", toolbox_file="34.3.2.0003", index="32.5.0.48")
    r = pf.run_preflight(p)
    assert r.code == "HW_DATABASE_VERSION_MISMATCH" and r.retryable is False and r.stage == "environment_preflight"
    assert "29.01" in r.message and "28.00" in r.message
    assert "catalog" not in p.calls                          # nothing that could open the modal dialog ran
    assert "Point SOLIDWORKS 2025" in r.user_action


def test_wrong_application_version_is_rejected_first():
    p = FakeProbe(revision="34.1.0", db_version="29.01")
    r = pf.run_preflight(p)
    assert r.code == "SW_VERSION_UNSUPPORTED" and "33" in r.message and p.calls == ["revision"]


def test_missing_database_and_unreadable_version():
    assert pf.run_preflight(FakeProbe(db_exists=False)).code == "HW_DATABASE_MISSING"
    assert pf.run_preflight(FakeProbe(root="")).code == "HW_DATABASE_MISSING"
    assert pf.run_preflight(FakeProbe(db_version=None)).code == "HW_DATABASE_MISSING"


def test_a_toolbox_index_from_another_release_family_is_a_mismatch():
    r = pf.run_preflight(FakeProbe(index="32.5.0.48"))
    assert r.code == "HW_DATABASE_VERSION_MISMATCH" and "index" in r.message.lower()


def test_modal_dialog_blocks_before_any_com_catalog_call():
    p = FakeProbe(modal=[{"title": "SOLIDWORKS", "class": "#32770"}])
    r = pf.run_preflight(p)
    assert r.code == "SW_MODAL_DIALOG_BLOCKED" and "catalog" not in p.calls and r.details["windows"][0]["class"] == "#32770"


def test_empty_or_failing_catalog_is_a_lookup_failure():
    assert pf.run_preflight(FakeProbe(standards=())).code == "HW_CATALOG_LOOKUP_FAILED"
    r = pf.run_preflight(FakeProbe(catalog_raises=RuntimeError("Parameter not optional")))
    assert r.code == "HW_CATALOG_LOOKUP_FAILED" and "Parameter not optional" in r.details["error"]


def test_require_ready_raises_a_structured_error_and_passes_a_ready_result():
    ok = pf.run_preflight(FakeProbe())
    assert pf.require_ready(ok) is ok
    bad = pf.run_preflight(FakeProbe(db_version="29.01"))
    with pytest.raises(pf.PreflightError) as e:
        pf.require_ready(bad)
    assert e.value.code == "HW_DATABASE_VERSION_MISMATCH"


def test_expected_version_unknown_falls_back_to_the_2025_family_not_to_a_guess():
    ok = pf.run_preflight(FakeProbe(expected_db=None, db_version="28.02"))
    assert ok.ok                                              # 28.x family accepted when no exact expectation exists
    bad = pf.run_preflight(FakeProbe(expected_db=None, db_version="29.01"))
    assert bad.code == "HW_DATABASE_VERSION_MISMATCH"
    assert pf.run_preflight(FakeProbe(expected_db="28.00", db_version="28.02")).code == "HW_DATABASE_VERSION_MISMATCH"   # exact when known


# ---- timeout / heartbeat ----------------------------------------------------------------------------------------
def test_bounded_job_times_out_with_a_structured_code_and_beats_while_it_waits():
    beats = []
    t0 = time.monotonic()
    r = pf.run_bounded(lambda: time.sleep(5), timeout=0.3, heartbeat=lambda s: beats.append(s), beat_every=0.05)
    assert r.code == "SW_JOB_TIMEOUT" and r.retryable is False and time.monotonic() - t0 < 2 and len(beats) >= 2


def test_bounded_job_returns_its_value_or_its_exception():
    assert pf.run_bounded(lambda: 7, timeout=2).value == 7
    r = pf.run_bounded(lambda: 1 / 0, timeout=2)
    assert r.code == "SW_JOB_ERROR" and "ZeroDivisionError" in r.message


# ---- modal detection from a window list ------------------------------------------------------------------------
def test_modal_detection_flags_disabled_main_window_and_dialog_class_only_for_the_sw_process():
    wins = [{"hwnd": 1, "pid": 10, "title": "SOLIDWORKS", "class": "Afx:X", "visible": True, "enabled": False, "owner": 0},
            {"hwnd": 2, "pid": 10, "title": "Hole Wizard", "class": "#32770", "visible": True, "enabled": True, "owner": 1},
            {"hwnd": 3, "pid": 11, "title": "Other", "class": "#32770", "visible": True, "enabled": True, "owner": 0},
            {"hwnd": 4, "pid": 10, "title": "", "class": "Hidden", "visible": False, "enabled": True, "owner": 0}]
    got = pf.detect_modal(wins, pid=10)
    assert {w["hwnd"] for w in got} == {2}                    # the dialog; the disabled main window is its evidence
    assert pf.detect_modal([wins[0]], pid=10) == []           # a disabled window alone is not asserted as a dialog
    assert pf.detect_modal([], pid=10) == []
