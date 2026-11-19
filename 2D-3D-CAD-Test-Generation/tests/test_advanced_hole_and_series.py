"""Advanced Hole / Hole Series domains, the 2025 status vocabulary, catalog cache and ranking (Stage 4, D/E/I)."""
import json

import pytest

from pipeline.ir.solidworks import advanced_hole as ah
from pipeline.ir.solidworks import hole_capabilities as caps
from pipeline.ir.solidworks import hole_catalog as cat
from pipeline.ir.solidworks import hole_series as hs
from pipeline.ir.solidworks import hole_status as st
from pipeline.ir.solidworks import sw_preflight as pf


# ---- Advanced Hole ------------------------------------------------------------------------------------------------
def test_advanced_hole_keeps_near_and_far_stacks_and_never_becomes_a_basic_hole():
    i = ah.from_callout_text("NEAR SIDE Ø6 X 8 DEEP, FAR SIDE Ø4 X 5 DEEP", "mm")
    assert [(e.diameter, e.depth) for e in i.near] == [(6.0, 8.0)] and [(e.diameter, e.depth) for e in i.far] == [(4.0, 5.0)]
    r = ah.plan(i)
    assert r["status"] == "UNSUPPORTED_WITH_REASON" and r["code"] == "HW_ADVANCED_HOLE_NOT_IMPLEMENTED"
    assert r["feature_created"] is False and r["substitute_allowed"] is False and r["intent"]["near"][0]["diameter"] == 6.0
    assert "AdvancedHole2" in r["api_surface"]


def test_advanced_hole_missing_side_is_unresolved_not_filled_in():
    i = ah.from_callout_text("JUST SOME TEXT", "mm")
    assert i.near == [] and i.far == [] and "near_or_far_elements" in i.unresolved


def test_advanced_hole_and_series_have_no_import_route_to_the_basic_adapter():
    import ast
    import inspect
    for mod in (ah, hs):
        tree = ast.parse(inspect.getsource(mod))
        imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not any("hole_adapter" in m or "compile_solidworks" in m for m in imported)


# ---- Hole Series ---------------------------------------------------------------------------------------------------
def test_hole_series_is_blocked_with_evidence_and_never_substituted():
    r = hs.plan(hs.HoleSeriesIntent(size_designation="M6", source_text="M6 THRU STACK"))
    assert r["status"] == "BLOCKED_BY_CONFIRMED_SOLIDWORKS_2025_LIMITATION" and r["substitute_allowed"] is False
    assert r["feature_created"] is False and r["evidence"]["checked"] and r["intent"]["size_designation"] == "M6"


def test_the_hole_series_claim_is_rechecked_against_the_installed_type_library():
    """If SOLIDWORKS 2025 ever gains a creation path, this fails and the BLOCKED status must be reviewed."""
    pytest.importorskip("pythoncom")
    try:
        import tools.read_sw_typelib as t
        paths = t.tlb_paths()
        feat = t.enum_members("swFeatureNameID_e")
        names = dict(feat) if not isinstance(feat, dict) else feat
        fm = t.iface_members("IFeatureManager")
    except Exception as e:      # noqa: BLE001 - no SolidWorks type library on this machine
        pytest.skip(f"no installed type library: {type(e).__name__}")
    if not paths:
        pytest.skip("no installed type library")
    assert not [n for n in names if "holeseries" in n.lower()]
    assert not [m for m in fm if "holeseries" in json.dumps(m).lower()]


# ---- status vocabulary ---------------------------------------------------------------------------------------------
def test_vocabulary_is_exactly_the_five_states_and_the_mapping_fails_closed():
    assert st.STATUSES_2025 == ("SUPPORTED_AND_LIVE_VERIFIED", "SUPPORTED_BY_ADAPTER_NOT_INSTALLED", "UNSUPPORTED_WITH_REASON",
                                "NOT_APPLICABLE_TO_INSTALLED_CATALOG", "BLOCKED_BY_CONFIRMED_SOLIDWORKS_2025_LIMITATION")
    for internal in caps.STATUSES:
        assert st.map_status(internal) in st.STATUSES_2025
    assert st.map_status("verified") == "SUPPORTED_AND_LIVE_VERIFIED"
    assert st.map_status("not_implemented") == "UNSUPPORTED_WITH_REASON"
    assert st.map_status("something_new") == "UNSUPPORTED_WITH_REASON"          # fail closed
    assert st.map_status("implemented_not_live_verified") != "SUPPORTED_AND_LIVE_VERIFIED"


def test_reason_names_the_environment_code_and_never_claims_verification():
    row = {"status": "implemented_not_live_verified", "family": "hole"}
    txt = st.reason_for(row, {"code": "HW_DATABASE_VERSION_MISMATCH"})
    assert "HW_DATABASE_VERSION_MISMATCH" in txt and "verified" not in txt.replace("not-live", "")


def test_unknown_future_enum_members_fail_closed():
    live = {n: v for v, n in caps.SPECIFIC.items()}
    live["swBrandNewHole"] = 91
    rows = caps.fail_closed_rows(live)
    assert [(r["value"], r["name"], r["status_2025"], r["reason"]) for r in rows] == [(91, "swBrandNewHole", "UNSUPPORTED_WITH_REASON", "unknown_variant")]
    assert caps.classify(91)["known"] is False and caps.fail_closed_rows({n: v for v, n in caps.SPECIFIC.items()}) == []


# ---- catalog cache and ranked matching -----------------------------------------------------------------------------------
class _Probe:
    def __init__(self, db="28.00", rev="33.5.0"):
        self.db, self.rev = db, rev

    def revision(self): return self.rev
    def hole_wizard_root(self): return "r"
    def db_exists(self, r): return True
    def db_version(self, r): return self.db
    def expected_db_version(self): return "28.00"
    def toolbox_file_version(self, r): return "33.5.0.0053"
    def index_version(self, r): return "33.5.0.53"
    def modal_windows(self): return []
    def catalog_standards(self): return [0, 1]


def test_cache_is_keyed_by_fingerprint_and_a_changed_environment_is_stale(tmp_path):
    fp = pf.run_preflight(_Probe()).fingerprint
    other = pf.fingerprint("33.5.0", "28.01", "33.5.0.53", "33.5.0.0053")
    c = cat.CatalogCache(tmp_path)
    snap = cat.CatalogSnapshot(True, None, "", {2: {"standards": [0, 1], "fasteners": {}}})
    c.save(fp, snap)
    got = c.load(fp)
    assert got is not None and got.available and got.families[2]["standards"] == [0, 1]
    assert c.load(other) is None                                   # a different database version never reuses it
    p = tmp_path / f"{fp}.json"
    d = json.loads(p.read_text())
    d["discovery_version"] = 0
    p.write_text(json.dumps(d))
    assert c.load(fp) is None                                      # a changed discovery-code version is stale
    with pytest.raises(ValueError):
        c.load("../escape")


def test_fingerprint_changes_with_every_component_and_never_contains_a_path():
    base = pf.fingerprint("33.5.0", "28.00", "33.5.0.53", "33.5.0.0053")
    assert len({base, pf.fingerprint("33.4.0", "28.00", "33.5.0.53", "33.5.0.0053"), pf.fingerprint("33.5.0", "28.01", "33.5.0.53", "33.5.0.0053"),
                pf.fingerprint("33.5.0", "28.00", "33.5.0.54", "33.5.0.0053"), pf.fingerprint("33.5.0", "28.00", "33.5.0.53", "33.5.0.0053", "acme")}) == 5
    assert len(base) == 64 and all(ch in "0123456789abcdef" for ch in base)


def test_ranked_sizes_never_pick_the_first_approximate_row():
    rows = [("1/4", 0.266), ("5/16", 0.330), ("9/32", 0.281), ("#10", 0.201)]
    exact = cat.select_size(cat.rank_sizes(0.266, rows, 0.0005))
    assert exact[0].label == "1/4" and exact[1] is None
    near = cat.select_size(cat.rank_sizes(0.268, rows, 0.0005))
    assert near[0] is None and near[1] == "HW_CATALOG_NO_MATCH" and "1/4" in near[2]            # nearest named, not selected
    dup = cat.select_size(cat.rank_sizes(0.3, [("A", 0.3), ("B", 0.3001)], 0.0005))
    assert dup[0] is None and dup[1] == "HW_CATALOG_AMBIGUOUS" and "A" in dup[2] and "B" in dup[2]
    assert cat.select_size([])[1] == "HW_CATALOG_NO_MATCH"
