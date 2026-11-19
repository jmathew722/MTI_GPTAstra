"""The live matrix never starts a SolidWorks child when the environment gate fails (Stage 4, slice K)."""
import pytest

from tools import run_hole_wizard_matrix as m


@pytest.fixture(autouse=True)
def _synthetic(tmp_path):
    m.use_synthetic_standard(tmp_path)


FAILED = {"status": "failed", "code": "HW_DATABASE_VERSION_MISMATCH", "message": "SOLIDWORKS 2025 expects Hole Wizard database 28.00, but the configured database is 29.01.",
          "database_version": "29.01", "database_expected_version": "28.00"}


def test_failed_preflight_starts_no_child_and_blocks_every_candidate_row(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a child process must not start when preflight fails")
    monkeypatch.setattr(m, "run_child", boom)
    plan = m.finalize(m.run_live(m.build_plan(), 5.0, preflight=FAILED))
    cands = [r for r in plan["rows"] if r["status"] == "implemented_not_live_verified"]
    assert len(cands) == 47
    for r in cands:
        assert r["live"]["created"] == "blocked_by_preflight" and r["live"]["error"]["code"] == "HW_DATABASE_VERSION_MISMATCH"
        assert r["environment_reason"] == "HW_DATABASE_VERSION_MISMATCH" and r["status_2025"] == "SUPPORTED_BY_ADAPTER_NOT_INSTALLED"
        assert "HW_DATABASE_VERSION_MISMATCH" in r["status_reason"]
    assert plan["live_preflight"]["code"] == "HW_DATABASE_VERSION_MISMATCH" and plan["preflight"]["status"] == "failed"


def test_every_row_ends_in_exactly_one_of_the_five_states_and_nothing_is_verified():
    from pipeline.ir.solidworks.hole_status import STATUSES_2025
    plan = m.finalize(m.run_live(m.build_plan(), 5.0, preflight=FAILED))
    assert plan["total"] == 81 and all(r["status_2025"] in STATUSES_2025 for r in plan["rows"])
    assert sum(plan["status_2025_counts"].values()) == 81 and "SUPPORTED_AND_LIVE_VERIFIED" not in plan["status_2025_counts"]
    assert all(r["status_reason"] for r in plan["rows"])


def test_ready_preflight_runs_children_and_still_cannot_reach_verified(monkeypatch):
    seen = []

    def fake_child(value, timeout):
        seen.append(value)
        return {"created": "ok", "readback": "ok", "geometry": "ok", "reopen": "ok", "callout_roundtrip": "not_implemented"}
    monkeypatch.setattr(m, "run_child", fake_child)
    plan = m.finalize(m.run_live(m.build_plan(), 5.0, preflight={"status": "ready"}))
    assert len(seen) == 47 and plan["live_preflight"] == {"code": None}
    assert plan["status_2025_counts"].get("SUPPORTED_AND_LIVE_VERIFIED", 0) == 0          # callout round trip is not implemented


def test_a_blocked_first_child_still_blocks_the_rest(monkeypatch):
    calls = []

    def hang(value, timeout):
        calls.append(value)
        return {**m.live_columns_blank(), "error": {"code": "HW_DIALOG_BLOCKED", "detail": "no return"}}
    monkeypatch.setattr(m, "run_child", hang)
    plan = m.run_live(m.build_plan(), 1.0, preflight={"status": "ready"})
    assert len(calls) == 1 and plan["live_preflight"]["code"] == "HW_DIALOG_BLOCKED"
