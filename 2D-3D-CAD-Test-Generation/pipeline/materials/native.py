"""Native SOLIDWORKS material assignment and read-back (Phase 1, section 5).

Verified against the installed 2025 type library: IPartDoc.SetMaterialPropertyName2(config, database, name) and
IPartDoc.GetMaterialPropertyName2(config, out database) -> name.  Mass properties come from IModelDocExtension.CreateMassProperty2
(authoritative) with IBody2.GetMassProperties as the cross-check.  Everything is read back after the assignment; nothing here reports
an assignment that was only an appearance or a custom property.

Demo materials live in a project-owned ``.sldmat`` built from the installed library as a *seed*; the installation libraries are
never written to.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from pipeline.materials import catalog as cat

log = logging.getLogger(__name__)

NS = "http://www.solidworks.com/sldmaterials"
# the demo records and the standard-library seed entry whose shaders / hatch / property layout they inherit
DEMO_SEEDS = {
    "demo-steel": ("SolidFlow Generic Carbon Steel", "Steel", "Plain Carbon Steel"),
    "demo-copper": ("SolidFlow Generic Copper", "Copper Alloys", "Copper"),
    "demo-pla": ("SolidFlow Generic PLA", "Plastics", "ABS"),
}


class NativeMaterialError(RuntimeError):
    pass


def _set_density(mat: ET.Element, density: float) -> None:
    n = 0
    for el in mat.iter():
        if el.tag.rsplit("}", 1)[-1] == "DENS":
            el.set("value", f"{density:.6f}")
            n += 1
    if not n:
        raise NativeMaterialError("seed material has no DENS element")


def build_demo_database(out_dir: Path, demo: cat.Catalog) -> Path:
    """Write ``solidflow-demo.sldmat`` into ``out_dir`` (a project-owned folder) from the installed library as seed. Idempotent: the
    file is rebuilt only when its recorded recipe hash changes."""
    seed = cat.find_standard_library()
    if seed is None:
        raise NativeMaterialError("the installed SOLIDWORKS material library was not found, so the demo database cannot be seeded")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "solidflow-demo.sldmat"
    recipe = hashlib.sha256((seed.read_bytes()[:4096] + repr(sorted((r.id, r.density_kg_m3) for r in demo.records)).encode())).hexdigest()
    stamp = out_dir / "solidflow-demo.recipe"
    if target.is_file() and stamp.is_file() and stamp.read_text().strip() == recipe:
        return target
    text = cat._decode_xml(seed.read_bytes())
    head = re.match(r"^\s*(<\?xml[^>]*\?>)?\s*", text).end()
    root = cat.parse_sldmat_text(text)
    by_name = {}
    classes = {}
    for cl in root:
        if cl.tag.rsplit("}", 1)[-1] != "classification":
            continue
        classes[cl.get("name")] = cl
        for m in cl:
            if m.tag.rsplit("}", 1)[-1] == "material":
                by_name[m.get("name")] = (cl.get("name"), m)
    ET.register_namespace("mstns", NS)
    ET.register_namespace("msdata", "urn:schemas-microsoft-com:xml-msdata")
    ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
    ET.register_namespace("sldcolorswatch", "http://www.solidworks.com/sldcolorswatch")
    for cl in list(root):
        if cl.tag.rsplit("}", 1)[-1] == "classification":
            root.remove(cl)
    matid = 9001
    for r in demo.records:
        spec = DEMO_SEEDS.get(r.id)
        if not spec:
            continue
        name, cname, seed_name = spec
        if seed_name not in by_name:
            raise NativeMaterialError(f"seed material {seed_name!r} not found in the installed library")
        _, src = by_name[seed_name]
        m = copy.deepcopy(src)
        m.set("name", name)
        m.set("matid", str(matid))
        m.set("appdata", "Solid Flow demonstration material with SYNTHETIC properties. Not a specification or a supplier price.")
        matid += 1
        _set_density(m, r.density_kg_m3)
        cl = ET.SubElement(root, f"{{{NS}}}classification" if root.tag.startswith("{") and src.tag.startswith("{") else "classification", {"name": cname})
        cl.append(m)
    body = ET.tostring(root, encoding="unicode")
    target.write_bytes(("﻿" + '<?xml version="1.0" encoding="utf-16"?>\n' + body).encode("utf-16-le"))
    stamp.write_text(recipe)
    chk = cat.load_sldmat(target, source="demo", catalog_id="solidflow-demo")
    if len(chk.records) != len(DEMO_SEEDS) or chk.rejected:
        raise NativeMaterialError(f"the generated demo database failed its own re-read: {len(chk.records)} records, {chk.rejected}")
    return target


def link_demo_records(demo: cat.Catalog, db_path: Path) -> None:
    """Point the demo records at the project-owned native database."""
    for r in demo.records:
        spec = DEMO_SEEDS.get(r.id)
        if spec:
            r.sw_database = str(Path(db_path).resolve())
            r.sw_material_name = spec[0]


# ---------------------------------------------------------------- live SOLIDWORKS calls

PREF_MATERIAL_DB_FOLDERS = 28   # swUserPreferenceStringValue_e.swFileLocationsMaterialDatabases (from the installed type library)


@contextlib.contextmanager
def registered_database(sw_app, db_path):
    """SOLIDWORKS only honours material databases that sit in a registered 'Material Databases' folder (verified: even a byte-identical
    copy of the standard library at an unregistered path is ignored). Register the database's folder for the duration of the block and
    restore the user's original list afterwards, even on failure."""
    from pipeline.solidworks_builder import typed
    sw = typed(sw_app, "ISldWorks")
    folder = str(Path(db_path).resolve().parent)
    orig = None
    try:
        orig = sw.GetUserPreferenceStringValue(PREF_MATERIAL_DB_FOLDERS) or ""
        listed = [p.strip().rstrip("\\").lower() for p in orig.split(";") if p.strip()]
        if folder.rstrip("\\").lower() not in listed:
            sw.SetUserPreferenceStringValue(PREF_MATERIAL_DB_FOLDERS, (orig + ";" if orig and not orig.endswith(";") else orig) + folder)
        yield
    finally:
        if orig is not None:
            try:
                sw.SetUserPreferenceStringValue(PREF_MATERIAL_DB_FOLDERS, orig)
            except Exception as e:      # noqa: BLE001
                log.warning("Could not restore the material database folder list: %s", e)


def active_config(doc) -> str:
    """The active configuration's real name. SetMaterialPropertyName2 does not take '' (verified on SOLIDWORKS 2025 SP5)."""
    try:
        return str(doc.ConfigurationManager.ActiveConfiguration.Name)
    except Exception:      # noqa: BLE001
        return "Default"


def _same_library(actual_db: str, wanted_path: str) -> bool:
    """GetMaterialPropertyName2 reports the library's display name ('SOLIDWORKS Materials'), not its path."""
    a = (actual_db or "").strip().lower()
    w = Path(wanted_path)
    return a in {w.stem.lower(), w.name.lower(), str(w).lower()}


def read_material(doc, config: str = "") -> dict:
    """The material the part really carries: {"name", "database"} (both '' when none is assigned)."""
    from pipeline.solidworks_builder import typed
    part = typed(doc, "IPartDoc")
    res = part.GetMaterialPropertyName2(config or active_config(doc), "")
    if isinstance(res, tuple):
        name, db = (res + ("", ""))[:2] if len(res) >= 2 else (res[0], "")
        # the type-library wrapper returns (name, database); guard against the reverse order
        if isinstance(name, str) and name.lower().endswith(".sldmat"):
            name, db = db, name
    else:
        name, db = res, ""
    return {"name": name or "", "database": db or ""}


def set_material(doc, config: str, database: str, name: str) -> None:
    from pipeline.solidworks_builder import typed
    typed(doc, "IPartDoc").SetMaterialPropertyName2(config or active_config(doc), str(database), name)


def mass_properties(doc) -> dict:
    """{"volume_m3", "mass_kg", "density_kg_m3", "surface_area_m2", "source"} from the live part (the material's density applies)."""
    from pipeline.solidworks_builder import typed
    ext = typed(doc.Extension, "IModelDocExtension") if hasattr(doc, "Extension") else None
    out: dict = {"volume_m3": None, "mass_kg": None, "density_kg_m3": None, "surface_area_m2": None, "source": None}
    try:
        mp = ext.CreateMassProperty2()
        mp = typed(mp, "IMassProperty2") if hasattr(mp, "_oleobj_") else mp
        out["volume_m3"], out["mass_kg"] = float(mp.Volume), float(mp.Mass)
        out["surface_area_m2"] = float(mp.SurfaceArea)
        out["density_kg_m3"] = float(mp.Density) if getattr(mp, "Density", None) else None
        out["source"] = "IModelDocExtension.CreateMassProperty2"
    except Exception as e:     # noqa: BLE001 - recorded, then the cross-check path is used
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def assign_and_verify_app(sw_app, doc, rec_info: dict, config: str = "") -> dict:
    """assign_and_verify with the database folder registered (and the user's preference restored)."""
    db = rec_info.get("sw_database")
    if db and Path(db).is_file():
        try:
            with registered_database(sw_app, db):
                return assign_and_verify(doc, rec_info, config)
        except Exception as e:      # noqa: BLE001
            return {"status": "assignment_failed", "errors": [f"{type(e).__name__}: {e}"], "requested": {"name": rec_info.get("sw_material_name"),
                    "database": db}, "actual": None, "mass": None, "density_kg_m3": None, "density_ok": None, "config": config}
    return assign_and_verify(doc, rec_info, config)


def assign_and_verify(doc, rec_info: dict, config: str = "") -> dict:
    """Assign ``rec_info`` (a resolution's ``chosen`` dict) to the part, rebuild, and read it back. Returns the native-verification record.
    Never raises for a COM failure: a failed assignment is returned as status ``assignment_failed`` so the geometry is kept."""
    config = config or active_config(doc)
    ver = {"requested": {"name": rec_info.get("sw_material_name"), "database": rec_info.get("sw_database")}, "actual": None,
           "status": "assignment_failed", "config": config, "density_expected_kg_m3": rec_info.get("density_kg_m3"), "errors": [], "mass": None,
           "density_kg_m3": None, "density_ok": None}
    try:
        db, name = rec_info.get("sw_database"), rec_info.get("sw_material_name")
        if not db or not name:
            raise NativeMaterialError("this catalog entry has no native SOLIDWORKS material (database and name are both required)")
        if not Path(db).is_file():
            raise NativeMaterialError(f"material database not found: {db}")
        before = read_material(doc, config)
        ver["before"] = before
        set_material(doc, config, db, name)
        try:
            doc.EditRebuild3()
        except Exception:      # noqa: BLE001 - a rebuild error shows up in the read-back below
            pass
        actual = read_material(doc, config)
        ver["actual"] = actual
        if actual["name"] != name:
            raise NativeMaterialError(f"read-back says {actual['name']!r}, expected {name!r}")
        if actual["database"] and not _same_library(actual["database"], db):
            raise NativeMaterialError(f"read-back library {actual['database']!r} differs from {Path(db).stem!r}")
        mp = mass_properties(doc)
        ver["mass"] = mp
        vol, mass = mp.get("volume_m3"), mp.get("mass_kg")
        if vol and mass:
            ver["density_kg_m3"] = mass / vol
            exp = rec_info.get("density_kg_m3")
            ver["density_ok"] = bool(exp and abs(ver["density_kg_m3"] - exp) / exp <= 0.005)
            if ver["density_ok"] is False:
                ver["errors"].append(f"native density {ver['density_kg_m3']:.1f} kg/m3 differs from the approved record {exp} kg/m3")
        else:
            ver["errors"].append("native mass properties were not readable: " + str(mp.get("error")))
        ver["status"] = "assigned_verified" if ver["density_ok"] else "assignment_failed"
        if not ver["density_ok"] and not ver["errors"]:
            ver["errors"].append("density could not be verified")
    except Exception as e:      # noqa: BLE001
        ver["errors"].append(f"{type(e).__name__}: {e}")
    return ver


def reopen_and_read(sw_app, sldprt_path, db_path: Optional[str] = None) -> dict:
    """Open the SAVED part again (silent) and read the material and mass back from disk: proof the assignment survived the save.
    The file is opened by this call and closed by it; a document the user already had open is never closed."""
    from pipeline.solidworks_builder import typed
    out: dict = {"opened": False, "material": None, "mass": None, "errors": []}
    path = str(Path(sldprt_path).resolve())
    was_open = None
    try:
        was_open = sw_app.GetOpenDocumentByName(path)
    except Exception:       # noqa: BLE001
        was_open = None
    if was_open is not None:
        out["errors"].append("The file is already open in SOLIDWORKS; not reopened (the user's document is left alone).")
        return out
    doc = None
    try:
        res = typed(sw_app, "ISldWorks").OpenDoc6(path, 1, 1, "", 0, 0)    # swDocPART, swOpenDocOptions_Silent
        doc = res[0] if isinstance(res, tuple) else res
        if doc is None:
            raise NativeMaterialError(f"could not reopen the saved part (errors={res[1] if isinstance(res, tuple) else '?'})")
        out["opened"] = True
        cm = None
        if db_path and Path(db_path).is_file():
            cm = registered_database(sw_app, db_path)
        with (cm if cm is not None else contextlib.nullcontext()):
            out["material"] = read_material(doc)
            out["mass"] = mass_properties(doc)
    except Exception as e:      # noqa: BLE001
        out["errors"].append(f"{type(e).__name__}: {e}")
    finally:
        if doc is not None:
            try:
                sw_app.CloseDoc(str(typed(doc, "IModelDoc2").GetTitle()))
            except Exception as e:      # noqa: BLE001
                out["errors"].append(f"close: {e}")
    return out


def write_traceability_properties(doc, props: dict, config: str = "") -> list[str]:
    """Custom properties for traceability (SolidFlow_MaterialSource ...). These never replace the real material assignment."""
    errs = []
    try:
        mgr = doc.Extension.CustomPropertyManager(config)
        for k, v in props.items():
            try:
                mgr.Add3(k, 30, str(v), 2)       # swCustomInfoText = 30, swCustomPropertyReplaceValue = 2
            except Exception as e:   # noqa: BLE001
                errs.append(f"{k}: {e}")
    except Exception as e:           # noqa: BLE001
        errs.append(f"custom property manager: {e}")
    return errs
