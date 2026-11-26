"""v5: material library, per-part material review, batch totals, appearance guard. No SolidWorks, no paid call."""
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

REPO = Path(__file__).resolve().parents[3] / "2D-3D-CAD-Test-Generation"
_TMP = tempfile.mkdtemp(prefix="mcagent_v5_")
os.environ.setdefault("MCAGENT_REPO", str(REPO))
os.environ.setdefault("MCAGENT_DATA", os.path.join(_TMP, "data"))
os.environ.setdefault("MCAGENT_FINAL_OUTPUTS", os.path.join(_TMP, "final"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
sys.path.insert(0, str(REPO))
import app as appmod  # noqa: E402
import materials_api as mat  # noqa: E402
from pipeline.materials import catalog as catmod  # noqa: E402

client = TestClient(appmod.app)
SESSION = "v5" + "b" * 10


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    root = Path(tempfile.mkdtemp(prefix="mcagent_v5_iso_"))
    monkeypatch.setattr(appmod, "FINAL_OUTPUTS_DIR", root / "final")
    monkeypatch.setattr(appmod, "PARTS_DIR", root / "parts")
    monkeypatch.setattr(appmod, "DATA_DIR", root / "data")
    for d in ("final", "parts", "data"):
        (root / d).mkdir()
    monkeypatch.setattr(catmod, "find_standard_library", lambda: None)   # never parse the 25 MB installed library
    mat._CACHE.clear()
    yield root


def add_part(name):
    (appmod._session_dir(SESSION) / name).mkdir(parents=True, exist_ok=True)
    out = appmod.FINAL_OUTPUTS_DIR / name
    out.mkdir(parents=True, exist_ok=True)
    return out


def library(root, mats=None, name="lib"):
    d = root / name
    d.mkdir()
    mats = mats or [{"id": "co-6061", "label": "6061-T6 Aluminium", "aliases": ["6061-T6"], "density_kg_m3": 2700, "price_per_kg": 4.0}]
    (d / "materials.json").write_text(json.dumps({"schema_version": 1, "catalog_id": "co", "label": "Co", "currency": "USD",
                                                  "price_basis": "quote", "materials": mats}), encoding="utf-8")
    return d


def up(name, data):
    return ("files", (name, data, "application/octet-stream"))


def test_settings_roundtrip_and_validation():
    r = client.get("/api/materials/settings").json()
    assert r["settings"]["use_demo"] is True and r["library"]["active"] is False and r["active_source"] == "demo"
    assert client.put("/api/materials/settings", json={"yield_fraction": 0.8, "strict": True}).json()["settings"]["yield_fraction"] == 0.8
    assert client.put("/api/materials/settings", json={"yield_fraction": 1.5}).status_code == 400
    assert client.put("/api/materials/settings", json={"clear_yield": True}).json()["settings"]["yield_fraction"] is None
    saved = json.loads(mat.settings_path().read_text())
    assert saved["strict"] is True and "catalog_path" in saved
    assert mat.env_for_runs()["SOLIDFLOW_MATERIAL_SETTINGS"] == str(mat.settings_path())


def test_catalog_preview_demo_search_and_paging():
    r = client.get("/api/materials/catalog?source=demo").json()
    assert r["total"] == 3 and {m["id"] for m in r["materials"]} == {"demo-steel", "demo-copper", "demo-pla"}
    assert all(m["price_per_kg"] is not None and m["currency"] == "USD" for m in r["materials"])
    assert client.get("/api/materials/catalog?source=demo&q=copper").json()["total"] == 1
    assert len(client.get("/api/materials/catalog?source=demo&limit=1").json()["materials"]) == 1
    assert client.get("/api/materials/catalog?source=company").status_code == 404
    assert client.get("/api/materials/catalog?source=standard").status_code == 404
    assert client.get("/api/materials/catalog?source=nope").status_code == 400


def test_library_by_server_path_and_clear_never_touches_files(isolated):
    d = library(isolated)
    r = client.post("/api/materials/library", json={"path": str(d)})
    assert r.status_code == 200, r.text
    lib = r.json()["library"]
    assert lib["active"] and lib["entries"] == 1 and lib["rejected"] == 0 and lib["origin"] == "path"
    prev = client.get("/api/materials/catalog?source=company").json()
    assert prev["materials"][0]["id"] == "co-6061"
    assert client.post("/api/materials/library/refresh").status_code == 200
    r = client.delete("/api/materials/library")
    assert r.json()["library"]["active"] is False and (d / "materials.json").is_file()


def test_library_path_errors_are_clear_and_sanitized(isolated):
    r = client.post("/api/materials/library", json={"path": str(isolated / "nope")})
    assert r.status_code == 400 and "not a folder" in r.json()["detail"]
    empty = isolated / "empty"
    empty.mkdir()
    r = client.post("/api/materials/library", json={"path": str(empty)})
    assert r.status_code == 400 and "no materials.json" in r.json()["detail"]
    assert client.post("/api/materials/library", json={"path": "  "}).status_code == 400
    assert client.post("/api/materials/library/refresh").status_code == 409


def test_folder_upload_copies_under_data_and_loads(isolated):
    body = json.dumps({"schema_version": 1, "catalog_id": "u", "label": "U", "currency": "EUR", "price_basis": "x",
                       "materials": [{"id": "u-1", "label": "U one", "density_kg_m3": 1000, "price_per_kg": 2}]}).encode()
    r = client.post("/api/materials/library", files=[up("MyLib/materials.json", body), up("MyLib/readme.txt", b"x"), up("MyLib/sub/deep/a.json", b"{}")],
                    data={"folder_name": "MyLib"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["library"]["name"] == "MyLib" and j["library"]["origin"] == "upload" and j["library"]["entries"] == 1
    assert j["library"]["path"] == "" and j["uploaded"] == {"files": 1, "ignored": 2}
    saved = Path(mat.read_settings()["catalog_path"])
    assert mat._library_root().resolve() in saved.resolve().parents
    r2 = client.post("/api/materials/library", files=[up("L2/materials.json", body)], data={"folder_name": "L2"})
    assert r2.status_code == 200 and not saved.exists()          # the previous upload copy is replaced
    saved2 = Path(mat.read_settings()["catalog_path"])
    client.delete("/api/materials/library")
    assert not saved2.exists()


def test_folder_upload_caps_extensions_and_traversal(isolated, monkeypatch):
    assert client.post("/api/materials/library", files=[up("L/notes.exe", b"x")], data={"folder_name": "L"}).status_code == 400
    r = client.post("/api/materials/library", files=[up("L/../../evil.json", b"{}")], data={"folder_name": "L"})
    assert r.status_code == 400
    assert not (isolated / "evil.json").exists() and not (isolated / "data" / "evil.json").exists()
    monkeypatch.setitem(mat.MAX_FILE_BYTES, ".json", 100)
    r = client.post("/api/materials/library", files=[up("L/materials.json", b"x" * 500)], data={"folder_name": "L"})
    assert r.status_code == 400 and "larger than" in r.json()["detail"]
    monkeypatch.setattr(mat, "MAX_FILES", 1)
    r = client.post("/api/materials/library", files=[up("L/a.json", b"{}"), up("L/b.csv", b"id\n")], data={"folder_name": "L"})
    assert r.status_code == 400 and "Too many" in r.json()["detail"]
    r = client.post("/api/materials/library", files=[up("L/materials.json", b"not json")], data={"folder_name": "L"})
    assert r.status_code == 400
    root = mat._library_root()
    assert not root.exists() or not any(root.iterdir())          # failed uploads leave nothing behind
    assert client.post("/api/materials/library", content="x", headers={"content-type": "text/plain"}).status_code == 400


def write_resolution(out, status="matched", mid="demo-steel", catalogs=None, source="drawing"):
    demo = mat._load_demo()
    res = {"status": status, "label": "Generic carbon steel", "selection_source": source, "review_required": False, "review_reasons": [],
           "drawing": {"status": "specified", "raw_text": "STEEL", "evidence": [{"page": 1, "region": "title_block", "quote": "STEEL"}]},
           "chosen": {"material_id": mid, "label": "Generic carbon steel", "catalog_source": "demo", "catalog_id": "solidflow-demo"},
           "catalogs": catalogs if catalogs is not None else [demo.snapshot()]}
    (out / "material_resolution.json").write_text(json.dumps(res))
    return res


def test_part_material_not_evaluated_state():
    add_part("OLD1")
    r = client.get(f"/api/parts/{SESSION}/OLD1/material").json()
    assert r["evaluated"] is False and r["resolution"] is None and r["stale"] is False and r["files"]["material_resolution.json"] is False
    assert client.get(f"/api/parts/{SESSION}/NOPE/material").status_code == 404


def test_part_material_composes_files_and_flags_stale(isolated):
    out = add_part("P1")
    write_resolution(out)
    (out / "material_native.json").write_text(json.dumps({"status": "assigned_verified", "actual": {"name": "x"}}))
    (out / "material_costing.json").write_text(json.dumps({"available": True, "net_material_cost": 1.5, "currency": "USD", "display": {"net_material_cost": "1.50 USD"},
                                                           "label": "Illustrative material estimate - not a supplier quote"}))
    r = client.get(f"/api/parts/{SESSION}/P1/material").json()
    assert r["evaluated"] and r["native"]["status"] == "assigned_verified" and r["from_saved_extraction"] is False and r["stale"] is False
    assert r["demo_prices"] is True
    d = library(isolated)                                          # a company library appears after the result was produced -> stale
    client.post("/api/materials/library", json={"path": str(d)})
    r = client.get(f"/api/parts/{SESSION}/P1/material").json()
    assert r["stale"] and "company" in r["stale_reasons"][0]
    out2 = add_part("P2")                                          # a changed demo hash is stale too
    write_resolution(out2, catalogs=[{"catalog_id": "solidflow-demo", "source": "demo", "sha256": "0" * 64}])
    client.delete("/api/materials/library")
    assert client.get(f"/api/parts/{SESSION}/P2/material").json()["stale"] is True


def test_override_validation_and_effect():
    out = add_part("P3")
    base = f"/api/parts/{SESSION}/P3/material/override"
    assert client.post(base, json={"material_id": "demo-copper", "reason": "  "}).status_code == 400
    assert client.post(base, json={"material_id": "ghost", "reason": "because"}).status_code == 400
    assert client.post(base, json={"material_id": "demo-copper", "reason": "x" * 501}).status_code == 400
    assert not (out / "material_override.json").exists()
    r = client.post(base, json={"material_id": "demo-copper", "reason": "Customer email 2026-11-02", "user": "Joe <b>"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["override"]["reason"].startswith("Customer") and "<" not in j["override"]["user"]
    res = j["resolution"]
    assert res["selection_source"] == "manual_override" and res["chosen"]["material_id"] == "demo-copper" and res["override"]["diverges_from_drawing"]
    assert j["needs_rebuild"] is True
    d = client.delete(base).json()
    assert d["override"] is None and not (out / "material_override.json").exists()
    assert d["resolution"]["status"] == "not_specified"


def test_refresh_without_solidworks_uses_saved_extraction():
    out = add_part("P4")
    (out / "P4_extraction.json").write_text(json.dumps({"material": "Steel", "material_extraction": {
        "status": "specified", "raw_text": "STEEL", "normalized_candidate": "steel",
        "evidence": [{"page": 1, "region": "title_block", "quote": "STEEL"}]}}))
    r = client.post(f"/api/parts/{SESSION}/P4/material/refresh")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["evaluated"] and j["from_saved_extraction"] is True and j["has_extraction"]
    assert j["resolution"]["status"] == "matched" and j["resolution"]["chosen"]["material_id"] == "demo-steel"
    assert j["costing"] is None and j["native"] is None                # nothing is invented without a build


def test_refresh_keeps_last_build_verdict():
    out = add_part("P5")
    (out / "P5_extraction.json").write_text(json.dumps({"material": "Steel", "material_extraction": {
        "status": "specified", "raw_text": "STEEL", "normalized_candidate": "steel",
        "evidence": [{"page": 1, "region": "title_block", "quote": "STEEL"}]}}))
    write_resolution(out, status="assigned_verified", mid="demo-steel")
    (out / "material_native.json").write_text(json.dumps({"status": "assigned_verified"}))
    j = client.post(f"/api/parts/{SESSION}/P5/material/refresh").json()
    assert j["resolution"]["chosen"]["material_id"] == "demo-steel"
    assert j["resolution"]["status"] == "assigned_verified"


def test_batch_totals_unknown_is_not_zero():
    a, b = add_part("B1"), add_part("B2")
    add_part("B3")
    for o in (a, b):
        write_resolution(o)
    (a / "material_costing.json").write_text(json.dumps({"available": True, "net_material_cost": 2.0, "currency": "USD"}))
    (b / "material_costing.json").write_text(json.dumps({"available": False, "reason": "No material is verified", "net_material_cost": None, "currency": "USD"}))
    r = client.get("/api/materials/batch", params={"parts": [f"{SESSION}|B1", f"{SESSION}|B2", f"{SESSION}|B3"]}).json()
    assert r["priced_parts"] == 1 and r["unpriced_parts"] == 2 and r["partial"] is True
    assert r["totals"]["USD"]["value"] == 2.0 and r["evaluated_parts"] == 2 and r["total_parts"] == 3
    assert r["parts"][f"{SESSION}|B3"]["evaluated"] is False
    assert "separately" in r["api_cost"]["note"] and "api_cost_usd" in r["parts"][f"{SESSION}|B1"]
    r2 = client.get("/api/materials/batch", params={"parts": [f"{SESSION}|B3"]}).json()     # nothing priced: no totals, never a zero total
    assert r2["totals"] == {} and r2["priced_parts"] == 0 and r2["unpriced_parts"] == 1


def test_appearance_404_then_hash_guard():
    out = add_part("A1")
    assert client.get(f"/api/parts/{SESSION}/A1/appearance").status_code == 404
    stl = out / "A1_ir.STL"
    stl.write_bytes(b"solid x\nendsolid x\n")
    sha = hashlib.sha256(stl.read_bytes()).hexdigest()
    side = {"artifact": stl.name, "artifact_sha256": sha, "verified": True, "color": "#A5ABB4", "metalness": 0.8, "roughness": 0.35}
    (out / "appearance.json").write_text(json.dumps(side))
    j = client.get(f"/api/parts/{SESSION}/A1/appearance").json()
    assert j["stl_matches"] and j["viewer_apply"] and j["stl_current_sha256"] == sha
    stl.write_bytes(b"solid y\nendsolid y\n")                       # a re-run replaced the STL: the old colour must not apply
    j = client.get(f"/api/parts/{SESSION}/A1/appearance").json()
    assert j["stl_matches"] is False and j["viewer_apply"] is False
    (out / "appearance.json").write_text(json.dumps(dict(side, artifact_sha256=hashlib.sha256(stl.read_bytes()).hexdigest(), verified=False)))
    assert client.get(f"/api/parts/{SESSION}/A1/appearance").json()["viewer_apply"] is False


def test_errors_do_not_leak_server_paths(isolated):
    r = client.post("/api/materials/library", json={"path": str(isolated / "data" / "x")})
    assert str(appmod.PROJECT_DIR) not in r.text
    assert "<data>" in mat._scrub(str(appmod.DATA_DIR / "materials" / "x"))
    assert str(appmod.PROJECT_DIR) not in mat._scrub(f"boom {appmod.PROJECT_DIR}/pipeline/x.py")


def test_refresh_never_erases_an_earlier_result_and_refuses_when_nothing_exists():
    out = add_part("R1")
    write_resolution(out, status="assigned_verified", mid="demo-steel")        # no extraction file, a resolution with a drawing reading
    (out / "material_native.json").write_text(json.dumps({"status": "assigned_verified"}))
    j = client.post(f"/api/parts/{SESSION}/R1/material/refresh").json()
    assert j["resolution"]["chosen"]["material_id"] == "demo-steel" and j["resolution"]["status"] == "assigned_verified"
    add_part("R2")
    assert client.post(f"/api/parts/{SESSION}/R2/material/refresh").status_code == 409
    assert not (appmod.FINAL_OUTPUTS_DIR / "R2" / "material_resolution.json").exists()
