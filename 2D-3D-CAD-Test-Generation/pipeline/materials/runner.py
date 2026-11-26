"""Pipeline glue for the material upgrade: pick catalogs -> resolve -> (compiler assigns) -> verify, cost, appearance, persist.

Material work never fails a geometry build.  Every step here is wrapped so that an error becomes a recorded ``review`` item and the part
is still produced (unless the user explicitly sets the strict release policy, which only blocks *release*, not the geometry file).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pipeline.materials import catalog as cat
from pipeline.materials import costing, native, resolver
from pipeline.materials.extraction import MaterialExtraction, normalize, validate_citations

log = logging.getLogger(__name__)

SETTINGS_ENV = "SOLIDFLOW_MATERIAL_SETTINGS"       # path of the JSON the UI/server writes: {"catalog_path", "use_demo", "yield_fraction", "strict"}
OVERRIDE_FILE = "material_override.json"           # written next to a part's outputs by the review UI
FILES = ("material_resolution.json", "material_native.json", "material_costing.json", "appearance.json")
NEUTRAL = {"color": "#9AA0A8", "metalness": 0.2, "roughness": 0.6}


def load_settings() -> dict:
    s = {"catalog_path": "", "use_demo": True, "use_standard": True, "yield_fraction": None, "strict": False}
    p = os.environ.get(SETTINGS_ENV)
    if p and Path(p).is_file():
        try:
            s.update({k: v for k, v in json.loads(Path(p).read_text(encoding="utf-8")).items() if k in s})
        except (OSError, json.JSONDecodeError) as e:
            log.warning("Ignoring unreadable material settings %s: %s", p, e)
    return s


def build_catalogs(settings: Optional[dict] = None, native_dir: Optional[Path] = None) -> dict:
    """{"company", "demo", "standard", "warnings"}; the demo catalog is linked to its project-owned native database when SOLIDWORKS is installed."""
    s = settings or load_settings()
    out: dict = {"company": None, "demo": None, "standard": None, "warnings": []}
    if s.get("catalog_path"):
        try:
            out["company"] = cat.load_folder(Path(s["catalog_path"]))
            out["warnings"] += out["company"].errors
        except cat.CatalogError as e:
            out["warnings"].append(f"Company material library not usable ({e}); falling back to the demo catalog.")
    if s.get("use_demo", True) or out["company"] is None:
        try:
            out["demo"] = cat.load_demo()
            try:
                native.link_demo_records(out["demo"], native.build_demo_database(native_dir or _native_dir(), out["demo"]))
            except native.NativeMaterialError as e:
                out["warnings"].append(f"Demo materials cannot be assigned natively: {e}")
        except cat.CatalogError as e:
            out["warnings"].append(f"Demo catalog unavailable: {e}")
    if s.get("use_standard", True):
        try:
            out["standard"] = cat.load_standard()
        except cat.CatalogError as e:
            out["warnings"].append(f"Installed SOLIDWORKS material library not readable: {e}")
    return out


def _native_dir() -> Path:
    base = os.environ.get("MCAGENT_DATA") or str(Path.home() / ".mti-2d-3d")
    return Path(base) / "materials"


def read_override(out: Path) -> Optional[dict]:
    p = Path(out) / OVERRIDE_FILE
    if p.is_file():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) and d.get("material_id") else None
        except (OSError, json.JSONDecodeError):
            return None
    return None


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def resolve_for_part(raw_extraction: dict, out: Path, *, page_texts: Optional[dict] = None, settings: Optional[dict] = None,
                     catalogs: Optional[dict] = None) -> dict:
    """Resolve the part's material from its extraction dict and write ``material_resolution.json``. Never raises."""
    out = Path(out)
    try:
        me_raw = raw_extraction.get("material_extraction")
        me = MaterialExtraction.model_validate(me_raw) if me_raw else None
        legacy = str(raw_extraction.get("material") or "")
        me = normalize(me, legacy)
        if page_texts:
            me = validate_citations(me, page_texts)
        cs = catalogs or build_catalogs(settings)
        res = resolver.resolve(me, company=cs["company"], demo=cs["demo"], standard=cs["standard"], override=read_override(out))
        res["catalog_warnings"] = cs["warnings"]
        res["strict_release"] = bool((settings or load_settings()).get("strict"))
    except Exception as e:      # noqa: BLE001 - recorded, geometry continues
        log.warning("Material resolution failed: %s", e)
        res = {"status": "unmatched", "assignable": False, "chosen": None, "label": "Material resolution failed", "review_required": True,
               "review_reasons": [f"{type(e).__name__}: {e}"], "drawing": {"status": "unreadable"}, "catalogs": []}
    try:
        out.mkdir(parents=True, exist_ok=True)
        _atomic_write(out / "material_resolution.json", res)
    except OSError as e:
        log.warning("Could not write material_resolution.json: %s", e)
    return res


def appearance_for(resolution: dict, verification: Optional[dict], stl: Optional[Path], run_id: str = "", config: str = "") -> dict:
    """Viewer appearance sidecar. Verified assignment -> the record's colour; anything else -> neutral and labelled a preview."""
    ch = resolution.get("chosen") or {}
    verified = bool(verification and verification.get("status") == "assigned_verified")
    sha = hashlib.sha256(Path(stl).read_bytes()).hexdigest() if stl and Path(stl).is_file() else None
    app = ch.get("appearance") or {}
    use = verified and bool(app.get("color"))
    return {"schema_version": 1, "artifact": Path(stl).name if stl else None, "artifact_sha256": sha, "job_id": run_id, "configuration": config,
            "material_id": ch.get("material_id") if verified else None, "material_label": ch.get("label") if verified else None,
            "status": "assigned_verified" if verified else (resolution.get("status") or "unmatched"), "verified": verified,
            "color": app["color"] if use else NEUTRAL["color"], "metalness": app["metalness"] if use else NEUTRAL["metalness"],
            "roughness": app["roughness"] if use else NEUTRAL["roughness"],
            "source": "catalog" if use else "neutral",
            "caption": ("Illustrative appearance, not a finish specification." if use else
                        "Preview only: the material is not verified on the native part, so the model is shown in neutral grey."),
            "per_body": None}


def finalize(out: Path, resolution: Optional[dict], sw_report, *, run_id: str = "", settings: Optional[dict] = None) -> dict:
    """After the build: write the native verification, costing and appearance files and fold the final status back into the resolution.
    Returns the summary stored in ir_report.json. Never raises."""
    out = Path(out)
    try:
        if resolution is None:
            return {}
        s = settings or load_settings()
        ver = getattr(sw_report, "material", None) if sw_report is not None else None
        status = resolution.get("status")
        if ver and ver.get("status") in ("assigned_verified", "assignment_failed"):
            status = ver["status"]
        resolution = dict(resolution, status=status)
        _atomic_write(out / "material_resolution.json", resolution)
        _atomic_write(out / "material_native.json", ver or {"status": status, "note": "No native material step ran."})
        ch = resolution.get("chosen") or {}
        verified = bool(ver and ver.get("status") == "assigned_verified")
        mass = (ver or {}).get("mass") or {}
        est = costing.estimate(volume_m3=getattr(sw_report, "volume_m3", None), density_kg_m3=(ver or {}).get("density_kg_m3") or ch.get("density_kg_m3"),
                               price_per_kg=ch.get("price_per_kg") if verified else None, currency=ch.get("currency") or "USD",
                               native_mass_kg=mass.get("mass_kg"), density_verified=verified, yield_fraction=s.get("yield_fraction"),
                               price_basis=ch.get("price_basis") or "", catalog_version=str(ch.get("catalog_sha256") or "")[:12],
                               demo=(ch.get("catalog_source") == "demo"))
        if not verified and not est.get("reason"):
            est["reason"] = "No material is verified on the native part, so the cost is unavailable."
        _atomic_write(out / "material_costing.json", est)
        stl = Path(sw_report.stl) if sw_report is not None and getattr(sw_report, "stl", None) else None
        _atomic_write(out / "appearance.json", appearance_for(resolution, ver, stl, run_id, (ver or {}).get("config") or ""))
        return {"status": status, "label": resolution.get("label"), "material_id": ch.get("material_id") if verified else None,
                "selection_source": resolution.get("selection_source"), "review_required": bool(resolution.get("review_required")) or (
                    ch and not verified), "cost_available": bool(est.get("available")), "net_material_cost": est.get("net_material_cost"),
                "currency": est.get("currency"), "mass_kg": est.get("mass_kg"), "files": list(FILES)}
    except Exception as e:      # noqa: BLE001
        log.warning("Material finalize failed: %s", e)
        return {"status": "assignment_failed", "error": f"{type(e).__name__}: {e}"}


def load_summary(part_dir: Path) -> dict:
    """What the UI shows for a part: the four JSON files that exist, plus a compact header. Missing files are simply absent."""
    part_dir = Path(part_dir)
    out: dict = {}
    for name, key in (("material_resolution.json", "resolution"), ("material_native.json", "native"), ("material_costing.json", "costing"),
                      ("appearance.json", "appearance")):
        p = part_dir / name
        if p.is_file():
            try:
                out[key] = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                out[key] = None
    return out
