"""Hole-intent IR, variant selection, catalog resolution (Stage 4, tasks 4.3, 4.5, 4.6)."""
import pytest

from pipeline.hole_callouts import parse
from pipeline.ir.model import HoleSpec
from pipeline.ir.solidworks import hole_catalog as cat
from pipeline.ir.solidworks import hole_intent as hi
from pipeline.ir.solidworks.hole_capabilities import BY_NAME, VARIANTS
from tools.run_hole_wizard_matrix import exemplar


@pytest.fixture(autouse=True)
def _synthetic_mti_table(tmp_path, monkeypatch):
    from tools.run_hole_wizard_matrix import use_synthetic_standard
    use_synthetic_standard(tmp_path)
    monkeypatch.setenv("MTI_STANDARD_PATH", str(tmp_path / "synthetic_standard.local.json"))


# ---- 4.3: versioned IR + migration ---------------------------------------------------------------------------------
def test_round_trip_through_a_dict_and_unknown_versions_are_rejected():
    i = hi.from_callout(parse("2X Ø.266 THRU"), "inch")
    d = i.to_dict()
    assert d["schema_version"] == 1 and hi.from_dict(d) == i
    with pytest.raises(hi.IntentError) as e:
        hi.from_dict({**d, "schema_version": 2})
    assert e.value.code == "HW_INTENT_VERSION"
    with pytest.raises(hi.IntentError) as e2:
        hi.from_dict({**d, "surprise": 1})
    assert e2.value.code == "HW_INTENT_FIELD"
    with pytest.raises(hi.IntentError):
        hi.from_dict({**d, "family": "nope"})


@pytest.mark.parametrize("spec,family,end", [
    (HoleSpec(type="thru", d="D001"), "hole", "through"),
    (HoleSpec(type="blind", d="D001", depth="D002"), "hole", "blind"),
    (HoleSpec(type="cbore", d="D001", cbore_d="D003", cbore_depth="D002"), "counterbore", "through"),
    (HoleSpec(type="csink", d="D001", csink_d="D003", csink_angle="90"), "countersink", "through"),
    (HoleSpec(type="tapped", d="D001", thread="1/4-20 UNC", depth="D002"), "straight_tap", "blind"),
    (HoleSpec(type="tapped", d="D001", thread="1/4 NPT"), "pipe_tap", "through"),
])
def test_holespec_migration_preserves_the_family_and_values(spec, family, end):
    i = hi.from_holespec(spec, {"D001": 6.0, "D002": 12.0, "D003": 11.0}, "mm")
    assert i.family == family and i.end == end and i.source == "v1_holespec" and i.schema_version == 1
    assert i.diameter == 6.0
    if end == "blind":
        assert i.depth == 12.0


def test_migration_flags_an_unreadable_thread_and_a_blind_hole_without_depth():
    i = hi.from_holespec(HoleSpec(type="tapped", d="D001", thread="???"), {"D001": 5.0}, "mm")
    assert "thread_unreadable" in i.ambiguities
    assert not hi.select_variant(i).ok and hi.select_variant(i).code == "HW_THREAD_UNREADABLE"
    j = hi.from_holespec(HoleSpec(type="blind", d="D001"), {"D001": 5.0}, "mm")
    assert "blind_depth_missing" in j.ambiguities


# ---- 4.6: selection -------------------------------------------------------------------------------------------------
def test_every_non_legacy_variant_round_trips_exemplar_intent_to_exactly_itself():
    bad = []
    for v in VARIANTS.values():
        if v.legacy:
            continue
        sel = hi.select_variant(exemplar(v))
        if not sel.ok or sel.variant.value != v.value:
            bad.append((v.name, sel.code, sel.candidates))
    assert bad == []
    assert sum(1 for v in VARIANTS.values() if not v.legacy) == 71


def test_selection_follows_the_drawing_not_a_default():
    sel = hi.select_variant(hi.from_callout(parse("Ø.266 THRU ⌴ Ø.438 X .25 DEEP"), "inch"))
    assert sel.ok and sel.variant.name == "swCounterBoreThru"
    assert hi.select_variant(hi.from_callout(parse("M6 X 1 - 6H"), "mm")).code == "HW_MISSING_INTENT"   # no end: never assumed
    sel = hi.select_variant(hi.from_callout(parse("M6 X 1 - 6H THRU"), "mm"))
    assert sel.variant.name == "swTapThruCosmeticThread"               # MTI default: cosmetic threads
    i = hi.from_callout(parse("M6 X 1 - 6H THRU"), "mm")
    i.thread_mode = "plain"
    assert hi.select_variant(i).variant.name == "swTapThru"
    i.thread_mode = "thread_through"
    assert hi.select_variant(i).variant.name == "swTapThruThreadThru"


def test_missing_and_ambiguous_intent_are_reported_not_filled_in():
    sel = hi.select_variant(hi.HoleIntent(family="counterbore", end="through", diameter=6.0))
    assert sel.code == "HW_MISSING_INTENT" and set(sel.missing) >= {"cbore_diameter", "cbore_depth"}
    assert hi.select_variant(hi.HoleIntent(family="hole", diameter=6.0)).code == "HW_MISSING_INTENT"
    blind = hi.select_variant(hi.HoleIntent(family="hole", end="blind", diameter=6.0))
    assert blind.code == "HW_MISSING_INTENT" and "depth" in blind.missing
    assert hi.select_variant(hi.HoleIntent(family="countersink", end="through", diameter=6.0,
                                           treatments={"middle": {"diameter": 9, "angle": 90}}, csink_diameter=9,
                                           csink_angle=90)).code == "HW_NO_VARIANT"


def test_legacy_advanced_hole_and_hole_series_never_resolve_to_a_basic_variant():
    assert hi.select_variant(hi.HoleIntent(family="legacy", end="through")).code == "HW_LEGACY_POLICY"
    adv = hi.from_callout(parse("NEAR SIDE Ø6 X 8 DEEP, FAR SIDE Ø4 X 5 DEEP"), "mm")
    assert adv.mode == "advanced_hole" and hi.select_variant(adv).code == "HW_ADVANCED_HOLE"
    assert hi.select_variant(hi.HoleIntent(family="hole", end="through", mode="hole_series")).code == "HW_HOLE_SERIES_NO_API"


def test_head_clearance_false_picks_the_without_head_clearance_variant():
    i = hi.HoleIntent(family="countersink", end="through", diameter=6.0, csink_diameter=12, csink_angle=82, head_clearance=False)
    assert hi.select_variant(i).variant.name == "swCounterSinkThruWithoutHeadClearance"
    i.head_clearance = None
    assert hi.select_variant(i).variant.name == "swCounterSinkThru"


# ---- 4.5: catalog ---------------------------------------------------------------------------------------------------
class _Data:
    def __init__(self, result):
        self.result = result

    def GetHoleStandards(self):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _App:
    def __init__(self, by_general):
        self.by_general = by_general

    def GetHoleStandardsData(self, g):
        return self.by_general.get(g)


def test_discovery_reports_unavailable_and_never_an_empty_catalog_as_fine():
    snap = cat.discover(_App({g: _Data((False, ())) for g in range(9)}))
    assert not snap.available and snap.code == "HW_CATALOG_ENUMERATION_UNAVAILABLE" and "no standards" in snap.detail
    assert not cat.discover(_App({})).available                      # no standards objects at all
    assert not cat.discover(_App({2: _Data(RuntimeError("boom"))}), generals=[2]).available


def test_discovery_keeps_what_it_finds_and_notes_what_failed():
    snap = cat.discover(_App({2: _Data((True, (0, 1))), 4: _Data((False, ()))}), generals=[2, 4])
    assert snap.available and snap.families[2]["standards"] == [0, 1] and "general 4" in snap.detail


def test_resolution_uses_installed_enum_names_and_the_thread_for_taps():
    v = BY_NAME["swTapThruCosmeticThread"]
    i = hi.from_callout(parse("1/4-20 UNC-2B"), "inch")
    r = cat.resolve(i, v)
    assert r.ok and r.standard_name == "swStandardAnsiInch" and r.fastener_name == "swStandardAnsiInchTappedHole"
    assert r.standard == 0 and r.fastener == 27 and r.size == "1/4-20"
    assert r.catalog_confirmed is False and r.warnings == ["HW_CATALOG_NOT_CONSULTED"]
    m = cat.resolve(hi.from_callout(parse("M6 X 1 - 6H"), "mm"), BY_NAME["swTapThruCosmeticThread"])
    assert m.standard_name == "swStandardAnsiMetric" and m.size == "M6x1" and m.fastener_name.endswith("TappedHole")


def test_a_catalog_that_lacks_the_standard_blocks_resolution():
    snap = cat.CatalogSnapshot(True, None, "", {4: {"standards": [1], "fasteners": {}}})
    i = hi.from_callout(parse("1/4-20 UNC-2B"), "inch")
    r = cat.resolve(i, BY_NAME["swTapThruCosmeticThread"], snapshot=snap)
    assert r.code == "HW_CATALOG_MISSING"
    ok = cat.resolve(i, BY_NAME["swTapThruCosmeticThread"], snapshot=cat.CatalogSnapshot(True, None, "", {4: {"standards": [0, 1], "fasteners": {}}}))
    assert ok.ok and ok.catalog_confirmed
    unavailable = cat.resolve(i, BY_NAME["swTapThruCosmeticThread"], snapshot=cat.CatalogSnapshot(False, "HW_CATALOG_ENUMERATION_UNAVAILABLE"))
    assert unavailable.ok and unavailable.warnings == ["HW_CATALOG_ENUMERATION_UNAVAILABLE"] and not unavailable.catalog_confirmed


def test_pipe_standard_unknown_standard_and_slot_fastener_are_never_guessed():
    pipe = hi.from_callout(parse("1/4 PIPE TAP"), "inch")
    pipe.end = "through"
    v = hi.select_variant(pipe)
    assert v.ok and cat.resolve(pipe, v.variant).code == "HW_SIZE_UNRESOLVED"
    npt = hi.from_callout(parse("1/4 NPT"), "inch")
    npt.end = "through"
    assert cat.resolve(npt, hi.select_variant(npt).variant).ok
    odd = hi.HoleIntent(family="hole", end="through", diameter=6.4, units="mm", standard="Klingon")
    assert cat.resolve(odd, hi.select_variant(odd).variant).code == "HW_STANDARD_UNKNOWN"
    slot = exemplar(BY_NAME["swSlotThru"])
    assert cat.resolve(slot, BY_NAME["swSlotThru"]).code == "HW_FASTENER_UNMAPPED"


def test_countersink_fastener_follows_the_angle():
    i = hi.HoleIntent(family="countersink", end="through", diameter=6.4, units="mm", csink_diameter=12, csink_angle=82)
    r = cat.resolve(i, hi.select_variant(i).variant)
    assert r.ok and "82" in r.fastener_name


def test_matrix_plan_covers_all_81_and_can_never_report_verified_without_live_evidence():
    from tools.run_hole_wizard_matrix import build_plan, finalize
    plan = finalize(build_plan())
    assert plan["total"] == 81 and plan["status_counts"] == {"implemented_not_live_verified": 47, "not_implemented": 34}
    assert all(r["live"]["callout_roundtrip"] == "not_implemented" for r in plan["rows"])
    assert not any(r["status"] == "verified" for r in plan["rows"])
    slots = [r for r in plan["rows"] if r["family"].endswith("slot") or r["family"] == "slot"]
    assert len(slots) == 24 and {r["status"] for r in slots} == {"not_implemented"}
