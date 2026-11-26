"""Phase 1 material upgrade: catalogs, extraction contract, resolver, costing, appearance. No SolidWorks needed (live checks: tools/material_e2e.py)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.materials import catalog as cat
from pipeline.materials import costing, resolver, runner
from pipeline.materials.extraction import (MaterialEvidence, MaterialExtraction, from_legacy_text, is_absent_text, normalize,
                                          not_specified, validate_citations)


def ex(text, status="specified", **kw):
    return MaterialExtraction(status=status, raw_text=text, normalized_candidate=text,
                              evidence=[MaterialEvidence(page=1, region="title_block", quote=text)], **kw)


# ------------------------------------------------------------------ catalogs

def test_demo_catalog_matches_the_spec_manifest():
    d = cat.load_demo()
    assert [r.id for r in d.records] == ["demo-steel", "demo-copper", "demo-pla"]
    assert d.currency == "USD" and d.price_basis == "synthetic_demo_usd_per_kg" and not d.rejected
    assert d.by_id("demo-pla").density_kg_m3 == 1240 and d.by_id("demo-pla").price_per_kg == 25.0
    assert d.snapshot()["sha256"] and d.snapshot()["entries"] == 3


def write_manifest(folder: Path, materials, **over):
    m = {"schema_version": 1, "catalog_id": "co", "currency": "USD", "price_basis": "quote_2026", "materials": materials}
    m.update(over)
    (folder / "materials.json").write_text(json.dumps(m), encoding="utf-8")


def rec(i, **kw):
    r = {"id": i, "label": i, "density_kg_m3": 7800, "price_per_kg": 2.0, "aliases": []}
    r.update(kw)
    return r


def test_company_folder_loads_and_rejects_bad_records_with_reasons(tmp_path):
    write_manifest(tmp_path, [rec("a"), rec("a"), rec("bad-density", density_kg_m3=-5), rec("bad-price", price_per_kg=-1),
                              rec("nan", density_kg_m3="abc"), rec("cur", currency="usd1"), rec("noprice", price_per_kg=None)])
    c = cat.load_folder(tmp_path)
    assert {r.id for r in c.records} == {"a", "noprice"}
    reasons = {x["id"]: x["reason"] for x in c.rejected}
    assert "duplicate" in reasons["a"] and "density" in reasons["bad-density"] and "price" in reasons["bad-price"]
    assert c.by_id("noprice").price_per_kg is None                       # a missing price is None, never 0


def test_unsupported_schema_version_and_malformed_json_are_clear_errors(tmp_path):
    (tmp_path / "materials.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(cat.CatalogError, match="no valid material records|not valid JSON"):
        cat.load_folder(tmp_path)
    write_manifest(tmp_path, [rec("a")], schema_version=99)
    with pytest.raises(cat.CatalogError):
        cat.load_folder(tmp_path)


def test_empty_and_missing_folders_are_refused(tmp_path):
    with pytest.raises(cat.CatalogError):
        cat.load_folder(tmp_path / "nope")
    with pytest.raises(cat.CatalogError, match="holds no"):
        cat.load_folder(tmp_path)


def test_oversized_file_is_refused(tmp_path, monkeypatch):
    write_manifest(tmp_path, [rec("a")])
    monkeypatch.setattr(cat, "MAX_JSON_BYTES", 10)
    with pytest.raises(cat.CatalogError):
        cat.load_folder(tmp_path)


def test_csv_needs_explicit_density_units(tmp_path):
    (tmp_path / "m.csv").write_text("id,label,density,price_per_kg\nx,X,7800,1\n", encoding="utf-8")
    with pytest.raises(cat.CatalogError):
        cat.load_folder(tmp_path)
    (tmp_path / "m.csv").write_text("id,label,density_kg_m3,price_per_kg,aliases\nx,X,7800,1.25,foo;bar\n", encoding="utf-8")
    c = cat.load_folder(tmp_path)
    assert c.by_id("x").aliases == ["foo", "bar"] and c.by_id("x").price_per_kg == 1.25


def test_sldmat_with_entities_or_doctype_is_refused_not_expanded(tmp_path):
    evil = ('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a SYSTEM "file:///C:/Windows/win.ini">]>'
            '<materials><classification name="Steel"><material name="&a;"/></classification></materials>')
    (tmp_path / "evil.sldmat").write_text(evil, encoding="utf-8")
    with pytest.raises(cat.CatalogError):
        cat.load_folder(tmp_path)


def test_malformed_sldmat_is_refused(tmp_path):
    (tmp_path / "bad.sldmat").write_text("<materials><classification", encoding="utf-8")
    with pytest.raises(cat.CatalogError):
        cat.load_folder(tmp_path)


def test_sldmat_parse_reads_density_and_names(tmp_path):
    xml = ('<?xml version="1.0"?><mstns:materials xmlns:mstns="http://www.solidworks.com/sldmaterials"><classification name="Steel">'
           '<material name="Test Steel (SS)"><physicalproperties><DENS displayname="Mass density" value="7850.0"/></physicalproperties></material>'
           '<material name="No Density"/></classification></mstns:materials>')
    (tmp_path / "lib.sldmat").write_bytes(("\ufeff" + xml).encode("utf-16-le"))
    c = cat.load_folder(tmp_path)
    assert [r.label for r in c.records] == ["Test Steel (SS)"] and c.records[0].density_kg_m3 == 7850.0
    assert any("no mass density" in x["reason"] for x in c.rejected)


def test_symlink_or_outside_path_in_manifest_is_rejected(tmp_path):
    write_manifest(tmp_path, [rec("a", sw_database="..\\..\\Windows\\evil.sldmat")])
    with pytest.raises(cat.CatalogError):
        cat.load_folder(tmp_path)        # the only record is rejected -> no valid records


def test_standard_library_loads_when_installed():
    s = cat.load_standard()
    if s is None:
        pytest.skip("SOLIDWORKS material library not installed")
    assert len(s.records) > 200 and any(r.label == "Plain Carbon Steel" and r.density_kg_m3 == 7800 for r in s.records)
    assert all(r.price_per_kg is None for r in s.records)               # the library states no prices


# ------------------------------------------------------------------ extraction contract

def test_not_specified_has_no_text_no_evidence():
    me = normalize(MaterialExtraction(status="not_specified", raw_text="steel?", normalized_candidate="steel",
                                      evidence=[MaterialEvidence(quote="steel")], alternatives=["x"]))
    assert me.raw_text is None and me.normalized_candidate is None and me.evidence == [] and me.alternatives == []


@pytest.mark.parametrize("txt", ["", "-", "N/A", " n/a ", "NONE", "TBD", "---", "Not specified"])
def test_blank_dash_or_na_is_absence_not_a_grade(txt):
    assert is_absent_text(txt)
    assert normalize(ex(txt)).status == "not_specified"
    assert from_legacy_text(txt).status == "not_specified"


def test_specified_without_evidence_is_flagged_for_review():
    me = normalize(MaterialExtraction(status="specified", raw_text="6061-T6", normalized_candidate="6061-T6"))
    assert me.status == "specified" and "No drawing text was cited" in me.review_reason


def test_unreadable_is_not_the_same_as_absent():
    me = normalize(MaterialExtraction(status="unreadable", normalized_candidate="steel"))
    assert me.status == "unreadable" and me.normalized_candidate is None


def test_legacy_material_field_still_works_and_is_marked_unverified():
    me = normalize(None, "AISI 1045 STEEL")
    assert me.status == "specified" and "pre-upgrade" in me.review_reason
    assert normalize(None, "").status == "not_specified"


def test_citation_not_on_the_drawing_is_flagged_and_downgraded():
    me = ex("MATERIAL: 4140")
    out = validate_citations(me, {1: "TITLE BLOCK  MATERIAL: 1045 STEEL  SCALE 1:1"})
    assert out.status == "ambiguous" and "not found" in out.review_reason and out.confidence is None
    ok = validate_citations(me, {1: "x MATERIAL:  4140  y"})
    assert ok.status == "specified"


def test_extraction_schema_rejects_unknown_status_and_extra_keys():
    with pytest.raises(Exception):
        MaterialExtraction(status="probably steel")
    with pytest.raises(Exception):
        MaterialExtraction(status="specified", surprise=1)


def test_drawingdata_carries_material_extraction_and_old_json_still_validates():
    from pipeline.schema import DrawingData
    base = {"units": "inch", "confidence": 0.9}
    assert DrawingData.model_validate(base).material_extraction is None
    d = DrawingData.model_validate({**base, "material_extraction": {"status": "not_specified"}})
    assert d.material_extraction.status == "not_specified"
    assert "material_extraction" in DrawingData.model_json_schema()["properties"]


# ------------------------------------------------------------------ resolver

@pytest.fixture()
def demo():
    return cat.load_demo()


@pytest.fixture()
def company(tmp_path):
    write_manifest(tmp_path, [rec("co-1045", label="AISI 1045 Steel", spec="AISI 1045", aliases=["1045 steel"]),
                              rec("co-6061", label="6061-T6 Aluminum", aliases=["6061-T6"], density_kg_m3=2700),
                              rec("co-dup-a", label="Brass A", aliases=["brass"]), rec("co-dup-b", label="Brass B", aliases=["brass"])])
    return cat.load_folder(tmp_path)


@pytest.mark.parametrize("text,mid", [("STEEL", "demo-steel"), ("Carbon Steel", "demo-steel"), ("copper", "demo-copper"), ("PLA", "demo-pla"),
                                      ("Polylactic Acid", "demo-pla"), ("MATERIAL: PLA", "demo-pla")])
def test_generic_callouts_match_the_demo_catalog(demo, text, mid):
    r = resolver.resolve(ex(text), demo=demo)
    assert r["status"] == "matched" and r["chosen"]["material_id"] == mid and r["selection_source"] == "drawing"
    assert any("demo" in x.lower() for x in r["review_reasons"])        # never presented as an approved company material


def test_pls_is_not_an_alias_for_pla(demo):
    r = resolver.resolve(ex("PLS"), demo=demo)
    assert r["status"] == "unmatched" and r["chosen"] is None
    assert all(not s["auto_assignable"] for s in r["suggestions"])


def test_grade_and_temper_are_never_swapped(company):
    r = resolver.resolve(ex("AISI 4140 STEEL"), company=company)
    assert r["status"] == "unmatched" and r["chosen"] is None and r["review_required"]
    t = resolver.resolve(ex("6061"), company=company)
    assert t["status"] == "unmatched"                                   # 6061 is not 6061-T6
    assert resolver.resolve(ex("6061-T6"), company=company)["chosen"]["material_id"] == "co-6061"


def test_company_exact_match_beats_demo_and_standard(company, demo):
    r = resolver.resolve(ex("1045 steel"), company=company, demo=demo, standard=cat.load_standard())
    assert r["status"] == "matched" and r["chosen"]["catalog_source"] == "company" and r["chosen"]["material_id"] == "co-1045"


def test_company_without_a_match_offers_standard_candidates_for_approval_only(company, demo):
    std = cat.load_standard()
    if std is None:
        pytest.skip("no standard library")
    r = resolver.resolve(ex("Plain Carbon Steel"), company=company, demo=demo, standard=std)
    assert r["status"] == "unmatched" and r["chosen"] is None and not r["assignable"]
    assert any(c["label"] == "Plain Carbon Steel" and c["needs_explicit_approval"] for c in r["standard_candidates"])


def test_multiple_exact_company_matches_need_review(company):
    r = resolver.resolve(ex("brass"), company=company)
    assert r["status"] == "ambiguous" and r["chosen"] is None


def test_not_specified_stays_unassigned_with_the_required_label(demo):
    r = resolver.resolve(not_specified(), demo=demo)
    assert r["status"] == "not_specified" and r["chosen"] is None and not r["assignable"]
    assert r["label"] == "No material specified on drawing"


def test_conflicting_unreadable_and_multibody_are_ambiguous_and_apply_nothing(demo):
    for me in (MaterialExtraction(status="conflicting", raw_text="STEEL", alternatives=["COPPER"]),
               MaterialExtraction(status="unreadable"),
               ex("STEEL", body_scope="shaft only")):
        r = resolver.resolve(me, demo=demo)
        assert r["status"] == "ambiguous" and r["chosen"] is None and r["review_required"], me


def test_manual_override_is_labelled_and_warns_when_it_diverges(demo):
    r = resolver.resolve(not_specified(), demo=demo, override={"material_id": "demo-copper", "reason": "customer email", "user": "jo"})
    assert r["status"] == "override_pending" and r["selection_source"] == "manual_override" and r["assignable"]
    assert r["override"]["diverges_from_drawing"] and r["override"]["user"] == "jo" and r["override"]["at"]
    assert r["review_required"] and any("not what the drawing says" in x for x in r["review_reasons"])
    same = resolver.resolve(ex("copper"), demo=demo, override={"material_id": "demo-copper", "reason": "confirm"})
    assert not same["override"]["diverges_from_drawing"]


def test_override_needs_a_reason_and_a_known_material(demo):
    assert resolver.resolve(not_specified(), demo=demo, override={"material_id": "demo-copper"})["assignable"] is False
    assert resolver.resolve(not_specified(), demo=demo, override={"material_id": "nope", "reason": "x"})["status"] == "unmatched"


def test_resolution_records_the_catalog_snapshot(demo):
    r = resolver.resolve(ex("steel"), demo=demo)
    assert r["catalogs"][0]["sha256"] == demo.sha256 and r["catalogs"][0]["catalog_id"] == "solidflow-demo"
    assert r["chosen"]["catalog_sha256"] == demo.sha256


def test_normalisation_is_conservative():
    assert resolver.norm("MATERIAL:  AISI\u20131045  STEEL.") == "aisi-1045 steel"
    assert resolver.norm("6061-T6") != resolver.norm("6061")


# ------------------------------------------------------------------ costing (the spec's worked fixtures)

@pytest.mark.parametrize("dens,price,mass,disp", [(7850, 1.5, 0.785, "1.18"), (8960, 10.0, 0.896, "8.96"), (1240, 25.0, 0.124, "3.10")])
def test_worked_fixtures_100_cm3(dens, price, mass, disp):
    e = costing.estimate(volume_m3=1e-4, density_kg_m3=dens, price_per_kg=price, density_verified=True, demo=True)
    assert e["available"] and e["mass_kg"] == pytest.approx(mass) and costing.money(e["net_material_cost"]) == disp
    assert e["label"] == costing.ILLUSTRATIVE and "machining" in e["excludes"]


def test_steel_net_is_1_1775_and_rounds_half_up_to_1_18():
    e = costing.estimate(volume_m3=1e-4, density_kg_m3=7850, price_per_kg=1.5, density_verified=True)
    assert e["net_material_cost"] == pytest.approx(1.1775) and e["display"]["net_material_cost"] == "1.18 USD"


@pytest.mark.parametrize("kw,word", [(dict(density_kg_m3=None), "density"), (dict(density_verified=False), "not verified"),
                                     (dict(volume_m3=0), "volume"), (dict(volume_m3=None), "volume"), (dict(price_per_kg=None), "no price")])
def test_unknowns_are_unavailable_never_zero(kw, word):
    base = dict(volume_m3=1e-4, density_kg_m3=7850, price_per_kg=1.5, density_verified=True)
    base.update(kw)
    e = costing.estimate(**base)
    assert not e["available"] and e["net_material_cost"] is None and word in e["reason"]


def test_native_mass_is_authoritative_within_tolerance_and_rejected_beyond_it():
    ok = costing.estimate(volume_m3=1e-4, density_kg_m3=7850, price_per_kg=1.5, density_verified=True, native_mass_kg=0.7855)
    assert ok["available"] and ok["mass_kg"] == 0.7855
    bad = costing.estimate(volume_m3=1e-4, density_kg_m3=7850, price_per_kg=1.5, density_verified=True, native_mass_kg=0.9)
    assert not bad["available"] and "disagree" in bad["reason"]


def test_yield_is_optional_and_validated():
    e = costing.estimate(volume_m3=1e-4, density_kg_m3=7850, price_per_kg=1.5, density_verified=True, yield_fraction=0.5)
    assert e["stock_cost"] == pytest.approx(2.355)
    none = costing.estimate(volume_m3=1e-4, density_kg_m3=7850, price_per_kg=1.5, density_verified=True)
    assert none["stock_cost"] is None                                   # no default waste assumption
    assert costing.estimate(volume_m3=1e-4, density_kg_m3=7850, price_per_kg=1.5, density_verified=True, yield_fraction=1.5)["stock_cost"] is None


def test_batch_totals_count_unpriced_and_never_mix_currencies():
    a = costing.estimate(volume_m3=1e-4, density_kg_m3=7850, price_per_kg=1.5, density_verified=True)
    b = costing.estimate(volume_m3=1e-4, density_kg_m3=8960, price_per_kg=10, density_verified=True, currency="EUR")
    u = costing.estimate(volume_m3=1e-4, density_kg_m3=None, price_per_kg=None)
    t = costing.batch_totals([a, b, u])
    assert t["priced_parts"] == 2 and t["unpriced_parts"] == 1 and t["partial"]
    assert set(t["totals"]) == {"USD", "EUR"} and t["totals"]["USD"]["display"] == "1.18 USD"


# ------------------------------------------------------------------ appearance sidecar + runner

def test_appearance_is_neutral_unless_the_native_assignment_is_verified(demo, tmp_path):
    stl = tmp_path / "p.stl"
    stl.write_bytes(b"solid x\nendsolid x\n")
    res = resolver.resolve(ex("copper"), demo=demo)
    unverified = runner.appearance_for(res, {"status": "assignment_failed"}, stl, "run_1")
    assert unverified["verified"] is False and unverified["color"] == runner.NEUTRAL["color"] and unverified["material_id"] is None
    verified = runner.appearance_for(res, {"status": "assigned_verified", "config": "Default"}, stl, "run_1")
    assert verified["color"] == "#B87333" and verified["material_id"] == "demo-copper" and verified["artifact_sha256"]
    assert verified["job_id"] == "run_1" and "not a finish specification" in verified["caption"]
    nothing = runner.appearance_for(resolver.resolve(not_specified(), demo=demo), None, stl)
    assert nothing["verified"] is False and nothing["status"] == "not_specified"


def test_resolve_for_part_writes_json_and_never_raises(tmp_path):
    out = tmp_path / "A1"
    res = runner.resolve_for_part({"material": "COPPER", "units": "inch"}, out, settings={"catalog_path": "", "use_demo": True, "use_standard": False})
    assert res["status"] == "matched" and (out / "material_resolution.json").is_file()
    bad = runner.resolve_for_part({"material_extraction": {"status": "bogus"}}, out, settings={"use_standard": False})
    assert bad["review_required"] and bad["chosen"] is None             # a broken extraction is a review item, not a crash


def test_override_file_is_picked_up(tmp_path):
    out = tmp_path / "A2"
    out.mkdir()
    (out / runner.OVERRIDE_FILE).write_text(json.dumps({"material_id": "demo-pla", "reason": "customer approved", "user": "qa"}))
    res = runner.resolve_for_part({"material_extraction": {"status": "not_specified"}}, out, settings={"use_standard": False})
    assert res["status"] == "override_pending" and res["chosen"]["material_id"] == "demo-pla"


def test_finalize_without_solidworks_leaves_cost_unavailable_not_zero(tmp_path):
    res = runner.resolve_for_part({"material": "STEEL"}, tmp_path, settings={"use_standard": False})
    summary = runner.finalize(tmp_path, res, None, run_id="r1")
    assert summary["cost_available"] is False
    est = json.loads((tmp_path / "material_costing.json").read_text())
    assert est["available"] is False and est["net_material_cost"] is None and est["reason"]
    app = json.loads((tmp_path / "appearance.json").read_text())
    assert app["verified"] is False


def test_extraction_cache_key_changes_with_the_prompt_and_schema(monkeypatch):
    """A cache hit made before the prompt/schema changed (no material_extraction) must not be served after it (found by the live PDF run)."""
    from pipeline import extractor
    k1 = extractor._cache_key("IMG", "m")
    assert k1 == extractor._cache_key("IMG", "m") and k1 != extractor._cache_key("IMG2", "m") and k1 != extractor._cache_key("IMG", "m2")
    monkeypatch.setattr(extractor, "SYSTEM_PROMPT", extractor.SYSTEM_PROMPT + "\nnew instruction")
    assert extractor._cache_key("IMG", "m") != k1
