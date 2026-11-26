"""Material catalogs: the bundled demo catalog, a company folder (materials.json / CSV / .sldmat) and the installed
standard SOLIDWORKS library.

Nothing here executes a file or follows an XML entity; every file is size-capped, parsed as data and kept inside the
authorized root.  A rejected record never silently disappears: it is listed in ``Catalog.rejected`` with the reason.
Prices are ``None`` unless a catalog states one (an unknown price is never 0).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = 1
MAX_JSON_BYTES = 5 * 1024 * 1024
MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_SLDMAT_BYTES = 25 * 1024 * 1024
MAX_RECORDS = 5000
DENSITY_MIN, DENSITY_MAX = 0.1, 25000.0           # kg/m3: lighter than a gas / heavier than osmium is a data error
PRICE_MAX = 1.0e6                                   # per kg
ID_RE = re.compile(r"^[ -;=?-~\u00a0-\uffff]{1,200}$")   # printable; SOLIDWORKS names hold commas, parentheses and slashes
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

DEMO_DIR = Path(__file__).resolve().parents[2] / "config" / "materials"
DEMO_MANIFEST = DEMO_DIR / "solidflow-demo.json"
STD_LIB_DIRS = (
    Path(r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\lang\english\sldmaterials"),
)
# Illustrative viewer colours per SOLIDWORKS classification (appearance only; never a finish specification).
CLASS_APPEARANCE = {
    "Steel": ("#A5ABB4", 0.8, 0.35), "Iron": ("#8E9299", 0.8, 0.45), "Aluminium Alloys": ("#C4C9D0", 0.85, 0.35),
    "Copper Alloys": ("#B87333", 0.8, 0.35), "Titanium Alloys": ("#9AA0A8", 0.8, 0.4), "Zinc Alloys": ("#B4BBC4", 0.8, 0.4),
    "Other Alloys": ("#A9AEB6", 0.8, 0.4), "Plastics": ("#D1D5DB", 0.0, 0.65), "Other Metals": ("#B0B5BD", 0.8, 0.4),
}
NEUTRAL_APPEARANCE = ("#9AA0A8", 0.2, 0.6)


class CatalogError(ValueError):
    """The catalog (or one of its files) cannot be used at all."""


@dataclass
class MaterialRecord:
    id: str
    label: str
    density_kg_m3: float
    price_per_kg: Optional[float] = None
    aliases: list[str] = field(default_factory=list)
    spec: str = ""                          # drawing specification text, e.g. "AISI 1045"
    classification: str = ""
    sw_database: Optional[str] = None       # absolute path of the .sldmat that holds the native material
    sw_material_name: Optional[str] = None
    appearance: dict = field(default_factory=dict)
    source: str = "demo"                    # demo | company | standard
    source_file: str = ""
    currency: str = "USD"
    price_basis: str = ""

    def public(self) -> dict:
        return {"id": self.id, "label": self.label, "aliases": self.aliases, "spec": self.spec, "classification": self.classification,
                "density_kg_m3": self.density_kg_m3, "price_per_kg": self.price_per_kg, "currency": self.currency,
                "price_basis": self.price_basis, "sw_material_name": self.sw_material_name, "source": self.source,
                "appearance": self.appearance, "native": bool(self.sw_database and self.sw_material_name)}


@dataclass
class Catalog:
    catalog_id: str
    source: str                              # demo | company | standard
    label: str = ""
    path: str = ""
    sha256: str = ""
    currency: str = "USD"
    price_basis: str = ""
    records: list[MaterialRecord] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)

    def by_id(self, mid: str) -> Optional[MaterialRecord]:
        return next((r for r in self.records if r.id == mid), None)

    def snapshot(self) -> dict:
        """What a job records: enough to prove which catalog version a decision used, without the full table."""
        return {"catalog_id": self.catalog_id, "source": self.source, "path": self.path, "sha256": self.sha256,
                "currency": self.currency, "price_basis": self.price_basis, "entries": len(self.records),
                "rejected": len(self.rejected), "files": self.files}

    def preview(self, limit: int = 200) -> dict:
        out = self.snapshot()
        out.update({"label": self.label, "materials": [r.public() for r in self.records[:limit]],
                    "truncated": max(0, len(self.records) - limit), "rejected_records": self.rejected[:50], "errors": self.errors})
        return out


# ---------------------------------------------------------------- validation helpers

def _num(v, name: str) -> float:
    if isinstance(v, bool) or v is None:
        raise ValueError(f"{name} must be a number")
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number, got {v!r}") from None
    if not math.isfinite(x):
        raise ValueError(f"{name} must be finite")
    return x


def _validate_record(raw: dict, *, source: str, source_file: str, default_currency: str, default_basis: str) -> MaterialRecord:
    if not isinstance(raw, dict):
        raise ValueError("record is not an object")
    mid = str(raw.get("id", "")).strip()
    if not ID_RE.match(mid):
        raise ValueError(f"invalid id {mid!r}")
    label = str(raw.get("label", "") or mid).strip()[:200]
    dens = _num(raw.get("density_kg_m3"), "density_kg_m3")
    if not (DENSITY_MIN <= dens <= DENSITY_MAX):
        raise ValueError(f"density {dens} kg/m3 outside {DENSITY_MIN:g}..{DENSITY_MAX:g}")
    price = raw.get("price_per_kg")
    if price in (None, ""):
        price = None
    else:
        price = _num(price, "price_per_kg")
        if price < 0 or price > PRICE_MAX:
            raise ValueError(f"price_per_kg {price} outside 0..{PRICE_MAX:g}")
    cur = str(raw.get("currency") or default_currency).strip().upper()
    if not CURRENCY_RE.match(cur):
        raise ValueError(f"invalid currency {cur!r}")
    aliases = raw.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [a.strip() for a in aliases.split(";") if a.strip()]
    if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
        raise ValueError("aliases must be a list of strings")
    app = raw.get("appearance") or {}
    if not isinstance(app, dict):
        raise ValueError("appearance must be an object")
    color = str(app.get("color") or "").strip()
    if color and not re.match(r"^#[0-9A-Fa-f]{6}$", color):
        raise ValueError(f"appearance.color must be #RRGGBB, got {color!r}")
    appearance = {}
    if color:
        appearance = {"color": color.upper(), "metalness": float(max(0.0, min(1.0, _num(app.get("metalness", 0.0), "metalness")))),
                      "roughness": float(max(0.0, min(1.0, _num(app.get("roughness", 0.6), "roughness"))))}
    db = raw.get("sw_database")
    name = raw.get("sw_material_name")
    return MaterialRecord(id=mid, label=label, density_kg_m3=dens, price_per_kg=price, aliases=[a.strip() for a in aliases if a.strip()][:40],
                          spec=str(raw.get("spec", "") or "")[:200], classification=str(raw.get("classification", "") or "")[:80],
                          sw_database=str(db) if db else None, sw_material_name=str(name) if name else None, appearance=appearance,
                          source=source, source_file=source_file, currency=cur, price_basis=str(raw.get("price_basis") or default_basis)[:120])


def _read_capped(path: Path, cap: int) -> bytes:
    size = path.stat().st_size
    if size > cap:
        raise CatalogError(f"{path.name} is {size} bytes; the limit is {cap}")
    return path.read_bytes()


def _inside(root: Path, p: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return not p.is_symlink()
    except (ValueError, OSError):
        return False


def _decode_xml(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16")
    elif raw.startswith(b"\xef\xbb\xbf"):
        text = raw[3:].decode("utf-8")
    else:
        text = raw.decode("utf-8")
    return text.lstrip("\ufeff")


def parse_sldmat_text(text: str):
    """Parse .sldmat XML text safely; returns the root element. DOCTYPE/ENTITY declarations are refused outright."""
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", text, re.I):
        raise CatalogError("XML DOCTYPE/ENTITY declarations are not allowed")
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)
    try:
        return ET.fromstring(text)
    except ET.ParseError as e:
        raise CatalogError(f"malformed XML: {e}") from None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


# ---------------------------------------------------------------- loaders

def load_sldmat(path: Path, *, source: str, catalog_id: str = "", root_dir: Optional[Path] = None) -> Catalog:
    path = Path(path)
    cat = Catalog(catalog_id=catalog_id or path.stem, source=source, label=path.stem, path=str(path), files=[path.name])
    raw = _read_capped(path, MAX_SLDMAT_BYTES)
    cat.sha256 = hashlib.sha256(raw).hexdigest()
    root = parse_sldmat_text(_decode_xml(raw))
    seen: set[str] = set()
    for cl in root:
        if _local(cl.tag) != "classification":
            continue
        cname = cl.get("name", "")
        for m in cl:
            if _local(m.tag) != "material":
                continue
            name = m.get("name", "")
            dens = None
            for el in m.iter():
                if _local(el.tag) == "DENS":
                    dens = el.get("value")
            try:
                if dens is None:
                    raise ValueError("no mass density (DENS)")
                if name in seen:
                    raise ValueError(f"duplicate material name {name!r}")
                seen.add(name)
                col, met, rough = CLASS_APPEARANCE.get(cname, NEUTRAL_APPEARANCE)
                rec = _validate_record({"id": f"{catalog_id or path.stem}:{name}", "label": name, "density_kg_m3": float(dens), "classification": cname,
                                        "spec": name, "aliases": [], "appearance": {"color": col, "metalness": met, "roughness": rough},
                                        "sw_database": str(path.resolve()), "sw_material_name": name},
                                       source=source, source_file=path.name, default_currency="USD", default_basis="")
                cat.records.append(rec)
            except (ValueError, TypeError) as e:
                cat.rejected.append({"file": path.name, "id": name, "reason": str(e)})
    return cat


def load_manifest(path: Path, *, source: str, root_dir: Optional[Path] = None) -> Catalog:
    path = Path(path)
    raw = _read_capped(path, MAX_JSON_BYTES)
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise CatalogError(f"{path.name}: not valid JSON ({e})") from None
    if not isinstance(data, dict) or not isinstance(data.get("materials"), list):
        raise CatalogError(f"{path.name}: expected an object with a 'materials' list")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise CatalogError(f"{path.name}: unsupported schema_version {data.get('schema_version')!r} (this build reads {SCHEMA_VERSION})")
    cur = str(data.get("currency") or "USD").upper()
    if not CURRENCY_RE.match(cur):
        raise CatalogError(f"{path.name}: invalid currency {cur!r}")
    basis = str(data.get("price_basis") or "")
    cat = Catalog(catalog_id=str(data.get("catalog_id") or path.stem), source=source, label=str(data.get("label") or data.get("catalog_id") or path.stem),
                  path=str(path), sha256=hashlib.sha256(raw).hexdigest(), currency=cur, price_basis=basis, files=[path.name])
    if len(data["materials"]) > MAX_RECORDS:
        raise CatalogError(f"{path.name}: {len(data['materials'])} records exceeds the limit {MAX_RECORDS}")
    seen: set[str] = set()
    for i, r in enumerate(data["materials"]):
        rid = r.get("id") if isinstance(r, dict) else None
        try:
            rec = _validate_record(r, source=source, source_file=path.name, default_currency=cur, default_basis=basis)
            if rec.id in seen:
                raise ValueError(f"duplicate id {rec.id!r}")
            if rec.sw_database and root_dir is not None:
                p = (root_dir / rec.sw_database).resolve()
                if not _inside(root_dir, p):
                    raise ValueError("sw_database points outside the authorized folder")
                rec.sw_database = str(p)
            seen.add(rec.id)
            cat.records.append(rec)
        except (ValueError, TypeError) as e:
            cat.rejected.append({"file": path.name, "index": i, "id": str(rid), "reason": str(e)})
    return cat


def load_csv(path: Path, *, source: str) -> Catalog:
    """CSV import with explicit units: the header must say ``density_kg_m3`` (a bare 'density' column is refused)."""
    path = Path(path)
    raw = _read_capped(path, MAX_CSV_BYTES)
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    cols = [c.strip() for c in (reader.fieldnames or [])]
    if "id" not in cols or "density_kg_m3" not in cols:
        raise CatalogError(f"{path.name}: CSV needs 'id' and 'density_kg_m3' columns (density units must be explicit)")
    cat = Catalog(catalog_id=path.stem, source=source, label=path.stem, path=str(path), sha256=hashlib.sha256(raw).hexdigest(), files=[path.name])
    seen: set[str] = set()
    for i, row in enumerate(reader):
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        try:
            rec = _validate_record(row, source=source, source_file=path.name, default_currency="USD", default_basis="")
            if rec.id in seen:
                raise ValueError(f"duplicate id {rec.id!r}")
            seen.add(rec.id)
            cat.records.append(rec)
        except (ValueError, TypeError) as e:
            cat.rejected.append({"file": path.name, "index": i, "id": row.get("id", ""), "reason": str(e)})
        if len(cat.records) + len(cat.rejected) > MAX_RECORDS:
            raise CatalogError(f"{path.name}: more than {MAX_RECORDS} rows")
    return cat


def load_demo() -> Catalog:
    cat = load_manifest(DEMO_MANIFEST, source="demo")
    cat.label = "Solid Flow demo catalog (synthetic prices)"
    return cat


def load_folder(folder: Path, *, source: str = "company") -> Catalog:
    """A company library folder. ``materials.json`` is read first; ``.csv`` and ``.sldmat`` files add to it. Duplicate ids across files
    are rejected, never merged. Files that are symlinks or resolve outside the folder are skipped with a message."""
    folder = Path(folder)
    if not folder.is_dir():
        raise CatalogError(f"{folder} is not a folder")
    root = folder.resolve()
    parts: list[Catalog] = []
    errors: list[str] = []
    files = sorted(p for p in folder.iterdir() if p.is_file())
    order = [p for p in files if p.name.lower() == "materials.json"] + [p for p in files if p.suffix.lower() in (".csv", ".sldmat")]
    if not order:
        raise CatalogError("the folder holds no materials.json, .csv or .sldmat file")
    for p in order:
        if not _inside(root, p):
            errors.append(f"{p.name}: skipped (outside the authorized folder or a symbolic link)")
            continue
        try:
            if p.suffix.lower() == ".json":
                parts.append(load_manifest(p, source=source, root_dir=root))
            elif p.suffix.lower() == ".csv":
                parts.append(load_csv(p, source=source))
            else:
                parts.append(load_sldmat(p, source=source, catalog_id=p.stem))
        except CatalogError as e:
            errors.append(str(e))
        except (OSError, UnicodeDecodeError) as e:
            errors.append(f"{p.name}: {e}")
    h = hashlib.sha256()
    for c in parts:
        h.update(c.sha256.encode())
    cat = Catalog(catalog_id=root.name, source=source, label=root.name, path=str(root), sha256=h.hexdigest(), errors=errors,
                  currency=parts[0].currency if parts else "USD", price_basis=parts[0].price_basis if parts else "",
                  files=[f for c in parts for f in c.files])
    seen: dict[str, str] = {}
    for c in parts:
        cat.rejected += c.rejected
        for r in c.records:
            if r.id in seen:
                cat.rejected.append({"file": r.source_file, "id": r.id, "reason": f"duplicate id (already defined in {seen[r.id]})"})
                continue
            seen[r.id] = r.source_file
            cat.records.append(r)
    if not cat.records:
        raise CatalogError("no valid material records: " + ("; ".join(errors) or "; ".join(f"{x['id']}: {x['reason']}" for x in cat.rejected[:5])))
    return cat


def find_standard_library() -> Optional[Path]:
    for d in STD_LIB_DIRS:
        p = d / "solidworks materials.sldmat"
        if p.is_file():
            return p
    return None


def load_standard() -> Optional[Catalog]:
    """The installed standard SOLIDWORKS library, discovered on this machine (None when it is not installed)."""
    p = find_standard_library()
    if p is None:
        return None
    cat = load_sldmat(p, source="standard", catalog_id="sw-standard")
    cat.label = "Installed SOLIDWORKS materials"
    return cat
