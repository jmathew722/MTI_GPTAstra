"""Phase 1 material upgrade: HTTP surface for the material library, per-part material review and batch totals.

The pipeline half lives in <repo>/pipeline/materials (catalog, resolver, costing, runner). This module only
  * persists the user's choice (<data>/material_settings.json) and hands its path to every pipeline run
    (SOLIDFLOW_MATERIAL_SETTINGS),
  * previews catalogs (read-only),
  * lets the user point at / upload a company library folder,
  * composes what the UI shows for one part from the files the pipeline wrote,
  * writes a manual override file and re-resolves WITHOUT SolidWorks or any API call,
  * reports batch material totals separately from API run cost.

Nothing here runs SolidWorks or a paid call. It is wired from app.py with one include_router line; the app module is passed in
so folders that tests monkeypatch (DATA_DIR, FINAL_OUTPUTS_DIR, PARTS_DIR) are always read at request time.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

SETTINGS_FILE = "material_settings.json"
LIBRARY_DIRNAME = "library"                       # <data>/materials/library/<id>/
ALLOWED_EXT = {".json", ".csv", ".sldmat"}
MAX_FILES = 50
MAX_FILE_BYTES = {".json": 5 * 1024 * 1024, ".csv": 5 * 1024 * 1024, ".sldmat": 25 * 1024 * 1024}
MAX_TOTAL_BYTES = 60 * 1024 * 1024
PREVIEW_MAX = 500
DEFAULTS = {"catalog_path": "", "use_demo": True, "use_standard": True, "yield_fraction": None, "strict": False,
            "library_name": "", "library_origin": ""}

_APP = None                                        # the app module (set by make_router)
_LOCK = threading.Lock()
_CACHE: dict = {}                                  # catalog cache: key -> (signature, Catalog | None)
_STL_HASH: dict = {}                               # (path, mtime_ns, size) -> sha256


# ------------------------------------------------------------------ plumbing

def _a():
    if _APP is None:
        raise RuntimeError("materials_api is not initialised")
    return _APP


def _pipeline():
    """Import pipeline.materials lazily (the repo is chosen at launch, so it is not on sys.path at import time)."""
    repo = str(_a().PROJECT_DIR)
    if repo not in sys.path:
        sys.path.insert(0, repo)
    from pipeline.materials import catalog, costing, runner     # noqa: WPS433
    return catalog, costing, runner


def _data() -> Path:
    return Path(_a().DATA_DIR)


def settings_path() -> Path:
    return _data() / SETTINGS_FILE


def _library_root() -> Path:
    return _data() / "materials" / LIBRARY_DIRNAME


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read_settings() -> dict:
    s = dict(DEFAULTS)
    p = settings_path()
    if p.is_file():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                s.update({k: raw[k] for k in DEFAULTS if k in raw})
        except (OSError, json.JSONDecodeError):
            pass
    return s


def write_settings(s: dict) -> dict:
    clean = {k: s.get(k, DEFAULTS[k]) for k in DEFAULTS}
    _atomic_write(settings_path(), clean)
    return clean


def env_for_runs() -> dict:
    """Environment entries every pipeline subprocess must receive. Writes the settings file first so the path always exists."""
    try:
        if not settings_path().is_file():
            write_settings(read_settings())
        return {"SOLIDFLOW_MATERIAL_SETTINGS": str(settings_path())}
    except Exception:           # noqa: BLE001 - material settings must never block a run
        return {}


def _scrub(text: str) -> str:
    """Hide server-internal absolute paths in anything sent to the browser (the folder the user chose is allowed through)."""
    t = str(text)
    a = _a()
    for label, p in (("<data>", a.DATA_DIR), ("<repo>", a.PROJECT_DIR), ("<outputs>", a.FINAL_OUTPUTS_DIR), ("<home>", Path.home())):
        for variant in {str(p), str(p).replace("\\", "/")}:
            if variant:
                t = t.replace(variant, label)
    return t[:400]


def _fail(status: int, text: str) -> HTTPException:
    return HTTPException(status, _scrub(text))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ catalogs (cached; the standard library is large)

def _folder_signature(folder: Path) -> tuple:
    sig = []
    try:
        for p in sorted(folder.iterdir()):
            if p.is_file():
                st = p.stat()
                sig.append((p.name, st.st_size, st.st_mtime_ns))
    except OSError:
        pass
    return tuple(sig)


def _load_company(settings: dict, force: bool = False):
    path = settings.get("catalog_path") or ""
    if not path:
        return None, None
    catalog, _c, _r = _pipeline()
    folder = Path(path)
    sig = _folder_signature(folder) if folder.is_dir() else ("missing",)
    key = ("company", path)
    hit = _CACHE.get(key)
    if hit and hit[0] == sig and not force:
        return hit[1], hit[2]
    try:
        cat, err = catalog.load_folder(folder), None
    except catalog.CatalogError as e:
        cat, err = None, str(e)
    _CACHE[key] = (sig, cat, err)
    return cat, err


def _load_demo():
    catalog, _c, _r = _pipeline()
    hit = _CACHE.get("demo")
    if hit:
        return hit[1]
    cat = catalog.load_demo()
    _CACHE["demo"] = (None, cat)
    return cat


def _load_standard():
    catalog, _c, _r = _pipeline()
    try:
        p = catalog.find_standard_library()
    except Exception:       # noqa: BLE001
        p = None
    if p is None:
        return None
    st = p.stat()
    sig = (str(p), st.st_size, st.st_mtime_ns)
    hit = _CACHE.get("standard")
    if hit and hit[0] == sig:
        return hit[1]
    try:
        cat = catalog.load_standard()
    except catalog.CatalogError:
        cat = None
    _CACHE["standard"] = (sig, cat)
    return cat


def _standard_available() -> bool:
    catalog, _c, _r = _pipeline()
    try:
        return catalog.find_standard_library() is not None
    except Exception:       # noqa: BLE001
        return False


def active_catalogs(settings: dict, with_standard: bool = True) -> dict:
    """The same shape runner.build_catalogs returns (company, demo, standard, warnings) without linking the native demo database."""
    company, err = _load_company(settings)
    warnings: list = []
    if settings.get("catalog_path") and company is None:
        warnings.append(f"Company material library not usable ({err or 'unknown error'}); falling back to the demo catalog.")
    elif company is not None:
        warnings += list(company.errors)
    demo = _load_demo() if (settings.get("use_demo", True) or company is None) else None
    standard = _load_standard() if (with_standard and settings.get("use_standard", True)) else None
    return {"company": company, "demo": demo, "standard": standard, "warnings": warnings}


def _library_info(settings: dict) -> dict:
    path = settings.get("catalog_path") or ""
    if not path:
        return {"active": False, "name": "", "origin": "", "path": "", "entries": 0, "rejected": 0, "files": [], "error": None}
    cat, err = _load_company(settings)
    info = {"active": cat is not None, "name": settings.get("library_name") or Path(path).name, "origin": settings.get("library_origin") or "path",
            "path": path if settings.get("library_origin") != "upload" else "", "entries": 0, "rejected": 0, "files": [], "error": _scrub(err) if err else None}
    if cat is not None:
        info.update(entries=len(cat.records), rejected=len(cat.rejected), files=[Path(f).name for f in cat.files], sha256=cat.sha256,
                    warnings=[_scrub(x) for x in cat.errors])
    return info


def settings_payload() -> dict:
    s = read_settings()
    return {"settings": {k: s[k] for k in ("use_demo", "use_standard", "yield_fraction", "strict")},
            "library": _library_info(s), "standard_available": _standard_available(),
            "demo": {"label": "Solid Flow demo catalog (synthetic prices)", "entries": len(_load_demo().records)},
            "active_source": "company" if _library_info(s)["active"] else "demo"}


def _preview(cat, offset: int, limit: int, q: str) -> dict:
    mats = [r.public() for r in cat.records]
    if q:
        ql = q.lower()
        mats = [m for m in mats if ql in (m["id"] + " " + m["label"] + " " + " ".join(m["aliases"]) + " " + m.get("spec", "")).lower()]
    total = len(mats)
    out = cat.snapshot()
    out.update({"label": cat.label, "total": total, "offset": offset, "limit": limit, "materials": mats[offset:offset + limit],
                "truncated": max(0, total - offset - limit), "rejected_records": cat.rejected[:50], "errors": [_scrub(e) for e in cat.errors],
                "path": cat.path if cat.source == "company" and read_settings().get("library_origin") != "upload" else ""})
    out["files"] = [Path(f).name for f in cat.files]
    return out


# ------------------------------------------------------------------ per-part helpers

def _part_paths(session: str, part: str) -> tuple[Path, Path]:
    a = _a()
    pdir = a._session_dir(session) / a._sanitize(part)
    out = a._part_output_dir(session, part)
    if not pdir.is_dir() and not out.is_dir():
        raise HTTPException(404, "Unknown part")
    return pdir, out


def _read_json(p: Path) -> Optional[dict]:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _extraction(out: Path) -> Optional[dict]:
    a = _a()
    if not out.is_dir():
        return None
    p = a._first(out, ["*_extraction.json", "*extraction*.json"], exclude=["resolved"])
    return _read_json(p) if p else None


def _sha_of(path: Path) -> Optional[str]:
    try:
        st = path.stat()
    except OSError:
        return None
    key = (str(path), st.st_mtime_ns, st.st_size)
    if key not in _STL_HASH:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if len(_STL_HASH) > 64:
            _STL_HASH.clear()
        _STL_HASH[key] = h.hexdigest()
    return _STL_HASH[key]


def stale_reasons(resolution: Optional[dict], settings: dict) -> list[str]:
    """Why the saved resolution may no longer match the catalogs in force now (only the cheap, local catalogs are compared)."""
    if not resolution:
        return []
    out: list[str] = []
    snaps = {c.get("source"): c for c in (resolution.get("catalogs") or []) if isinstance(c, dict)}
    company, _err = _load_company(settings)
    if company is not None:
        s = snaps.get("company")
        if s is None:
            out.append("A company material library is set now but was not used for this result.")
        elif s.get("sha256") != company.sha256:
            out.append("The company material library changed since this result was produced.")
    elif "company" in snaps:
        out.append("The company material library used for this result is no longer set.")
    if "demo" in snaps:
        demo = _load_demo()
        if snaps["demo"].get("sha256") != demo.sha256:
            out.append("The demo catalog changed since this result was produced.")
    return out


_PATH_KEYS = {"database", "sw_database", "catalog_path", "path", "source_file"}


def _redact(obj):
    """Absolute server paths inside pipeline JSON are reduced to their file name before they reach the browser."""
    if isinstance(obj, dict):
        return {k: (Path(str(v).replace("\\", "/")).name if k in _PATH_KEYS and isinstance(v, str) and v else _redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    return obj


def _file_flags(out: Path) -> dict:
    _c, _co, runner = _pipeline()
    names = list(runner.FILES) + [runner.OVERRIDE_FILE]
    return {n: (out / n).is_file() for n in names}


def compose(session: str, part: str) -> dict:
    catalog, costing, runner = _pipeline()
    _pdir, out = _part_paths(session, part)
    settings = read_settings()
    summary = runner.load_summary(out) if out.is_dir() else {}
    resolution, native, cost, appearance = (_redact(summary.get(k)) for k in ("resolution", "native", "costing", "appearance"))
    flags = _file_flags(out) if out.is_dir() else {}
    stale = stale_reasons(resolution, settings)
    override = _redact(runner.read_override(out)) if out.is_dir() else None
    from_saved = bool(resolution) and native is None
    needs_rebuild = False
    if resolution:
        chosen = resolution.get("chosen") or {}
        built = (appearance or {}).get("material_id")
        needs_rebuild = resolution.get("status") == "override_pending" or bool(built and chosen.get("material_id") and built != chosen["material_id"])
    return {
        "part": part, "evaluated": bool(resolution), "files": flags, "resolution": resolution, "native": native, "costing": cost,
        "appearance": appearance, "override": override, "from_saved_extraction": from_saved, "needs_rebuild": needs_rebuild,
        "stale": bool(stale), "stale_reasons": stale, "has_extraction": _extraction(out) is not None,
        "library": _library_info(settings), "settings": {k: settings[k] for k in ("use_demo", "use_standard", "yield_fraction", "strict")},
        "catalogs_used": (resolution or {}).get("catalogs") or [],
        "demo_prices": bool(cost and "Illustrative" in str(cost.get("label") or "")) or bool(((resolution or {}).get("chosen") or {}).get("catalog_source") == "demo"),
        "build_files_note": ("Mass, cost, native read-back and appearance come from the last SolidWorks build." if native else
                             ("Resolved from the saved extraction; not built yet." if resolution else "")),
    }


def compact(out: Path) -> dict:
    """The small per-part record used by Projects, Recent and batch totals."""
    _c, _co, runner = _pipeline()
    summary = runner.load_summary(out) if out.is_dir() else {}
    res, cost, native = summary.get("resolution"), summary.get("costing"), summary.get("native")
    if not res:
        return {"evaluated": False}
    ch = res.get("chosen") or {}
    return {"evaluated": True, "status": res.get("status"), "label": res.get("label"), "material_label": ch.get("label"),
            "selection_source": res.get("selection_source"), "review_required": bool(res.get("review_required")),
            "from_saved_extraction": native is None, "native_status": (native or {}).get("status"),
            "cost": {"available": bool(cost and cost.get("available") and cost.get("net_material_cost") is not None),
                     "display": ((cost or {}).get("display") or {}).get("net_material_cost"), "currency": (cost or {}).get("currency"),
                     "label": (cost or {}).get("label"), "reason": (cost or {}).get("reason")}}


_DRAWING_KEYS = ("status", "raw_text", "normalized_candidate", "evidence", "alternatives", "confidence", "review_reason", "specification",
                 "condition_or_temper", "coating", "heat_treatment", "finish", "hardness", "stock_form", "body_scope")


def _reresolve(session: str, part: str, allow_empty: bool = False) -> dict:
    """Re-resolve from the saved extraction with the current catalogs. No SolidWorks, no API.
    Without a saved extraction the earlier result's own drawing reading is reused, so a refresh never erases what the drawing said.
    With neither, only an override may resolve (allow_empty); a plain refresh is refused instead of inventing 'not specified'."""
    _catalog, _costing, runner = _pipeline()
    _pdir, out = _part_paths(session, part)
    settings = read_settings()
    prev = _read_json(out / "material_resolution.json") if out.is_dir() else None
    native = _read_json(out / "material_native.json") if out.is_dir() else None
    raw = _extraction(out)
    if raw is None:
        drawing = (prev or {}).get("drawing")
        if isinstance(drawing, dict) and drawing:
            raw = {"material_extraction": {k: drawing[k] for k in _DRAWING_KEYS if k in drawing}}
        elif allow_empty:
            raw = {}
        else:
            raise HTTPException(409, "Nothing to re-read: this part has no saved extraction and no earlier material result.")
    cs = active_catalogs(settings)
    res = runner.resolve_for_part(raw, out, settings=settings, catalogs=cs)
    # resolve_for_part rewrites the file with the pre-build status; keep the last build's verdict while the choice is unchanged.
    try:
        pc, nc = ((prev or {}).get("chosen") or {}).get("material_id"), (res.get("chosen") or {}).get("material_id")
        if native and native.get("status") in ("assigned_verified", "assignment_failed") and pc and pc == nc \
                and (prev or {}).get("selection_source") == res.get("selection_source"):
            res = dict(res, status=native["status"])
            runner._atomic_write(out / "material_resolution.json", res)
    except Exception:       # noqa: BLE001
        pass
    return res


# ------------------------------------------------------------------ request models

class SettingsBody(BaseModel):
    use_demo: Optional[bool] = None
    use_standard: Optional[bool] = None
    yield_fraction: Optional[float] = None
    clear_yield: bool = False
    strict: Optional[bool] = None


class LibraryBody(BaseModel):
    path: str


class OverrideBody(BaseModel):
    material_id: str
    catalog_id: Optional[str] = None
    reason: str = ""
    user: str = ""


# ------------------------------------------------------------------ router

def make_router(app_module) -> APIRouter:
    global _APP
    _APP = app_module
    r = APIRouter()

    @r.get("/api/materials/settings")
    def get_settings():
        return settings_payload()

    @r.put("/api/materials/settings")
    def put_settings(body: SettingsBody):
        s = read_settings()
        if body.use_demo is not None:
            s["use_demo"] = bool(body.use_demo)
        if body.use_standard is not None:
            s["use_standard"] = bool(body.use_standard)
        if body.strict is not None:
            s["strict"] = bool(body.strict)
        if body.clear_yield:
            s["yield_fraction"] = None
        elif body.yield_fraction is not None:
            y = float(body.yield_fraction)
            if not (0.0 < y <= 1.0) or y != y:
                raise HTTPException(400, "yield_fraction must be greater than 0 and at most 1")
            s["yield_fraction"] = y
        write_settings(s)
        return settings_payload()

    @r.get("/api/materials/catalog")
    def catalog_preview(source: str = Query("demo"), q: str = Query("", max_length=80), offset: int = Query(0, ge=0, le=100000),
                        limit: int = Query(100, ge=1, le=PREVIEW_MAX)):
        s = read_settings()
        if source == "demo":
            return _preview(_load_demo(), offset, limit, q.strip())
        if source == "company":
            if not s.get("catalog_path"):
                raise HTTPException(404, "No company material library is set.")
            cat, err = _load_company(s)
            if cat is None:
                raise _fail(400, f"The company material library cannot be read: {err}")
            return _preview(cat, offset, limit, q.strip())
        if source == "standard":
            if not _standard_available():
                raise HTTPException(404, "The installed SolidWorks material library was not found on this machine.")
            cat = _load_standard()
            if cat is None:
                raise HTTPException(400, "The installed SolidWorks material library could not be read.")
            return _preview(cat, offset, limit, q.strip())
        raise HTTPException(400, "source must be demo, company or standard")

    def _activate(folder: Path, name: str, origin: str) -> dict:
        catalog, _c, _r = _pipeline()
        try:
            cat = catalog.load_folder(folder)
        except catalog.CatalogError as e:
            raise _fail(400, str(e))
        s = read_settings()
        old = s.get("catalog_path") or ""
        s.update(catalog_path=str(cat.path or folder), library_name=name or folder.name, library_origin=origin)
        write_settings(s)
        _CACHE.pop(("company", old), None)
        _drop_upload(old, keep=str(cat.path or folder))
        return settings_payload()

    def _drop_upload(old: str, keep: str = "") -> None:
        """Delete a previously uploaded copy (only ever inside <data>/materials/library); never a user's own folder."""
        if not old or old == keep:
            return
        try:
            root = _library_root().resolve()
            p = Path(old).resolve()
            if root in p.parents and p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass

    @r.post("/api/materials/library")
    async def set_library(request: Request):
        ctype = (request.headers.get("content-type") or "").lower()
        if ctype.startswith("application/json"):
            try:
                body = LibraryBody(**(await request.json()))
            except Exception:       # noqa: BLE001
                raise HTTPException(400, "Send {\"path\": \"<folder>\"} or upload the folder's files.")
            raw = body.path.strip().strip('"')
            if not raw:
                raise HTTPException(400, "Enter the path of a folder that holds materials.json, .csv or .sldmat files.")
            folder = Path(os.path.expandvars(raw)).expanduser()
            if not folder.is_dir():
                raise _fail(400, f"{folder} is not a folder on the machine that runs the server.")
            return _activate(folder.resolve(), folder.name, "path")
        if not ctype.startswith("multipart/form-data"):
            raise HTTPException(400, "Unsupported request. Choose a folder or enter its path.")
        form = await request.form()
        uploads = [f for f in form.getlist("files") if hasattr(f, "filename") and hasattr(f, "read")]
        if not uploads:
            raise HTTPException(400, "No files were uploaded.")
        if len(uploads) > 2000:
            raise HTTPException(400, "That folder holds too many files (limit 2000). Choose the folder that holds the material files.")
        folder_name = re.sub(r"[^\w .()\-]+", "_", str(form.get("folder_name") or "").strip())[:80] or "Uploaded library"
        dest = _library_root() / uuid.uuid4().hex[:12]
        dest.mkdir(parents=True, exist_ok=True)
        saved, skipped, total = 0, 0, 0
        try:
            for up in uploads:
                rel = str(up.filename or "").replace("\\", "/")
                parts = [p for p in rel.split("/") if p not in ("", ".")]
                if not parts or any(p == ".." for p in parts):
                    skipped += 1
                    continue
                if len(parts) > 2:                        # the library is the picked folder itself; deeper files are not read
                    skipped += 1
                    continue
                base = parts[-1]
                ext = Path(base).suffix.lower()
                if ext not in ALLOWED_EXT or re.search(r'[<>:"|?*\x00-\x1f]', base) or base in (".", ".."):
                    skipped += 1
                    continue
                if saved >= MAX_FILES:
                    raise HTTPException(400, f"Too many material files (limit {MAX_FILES}).")
                data = await up.read(MAX_FILE_BYTES[ext] + 1)
                if len(data) > MAX_FILE_BYTES[ext]:
                    raise HTTPException(400, f"{base} is larger than the {MAX_FILE_BYTES[ext] // (1024 * 1024)} MB limit for {ext} files.")
                total += len(data)
                if total > MAX_TOTAL_BYTES:
                    raise HTTPException(400, "The material files together are larger than the 60 MB limit.")
                target = (dest / base).resolve()
                if dest.resolve() not in target.parents:
                    skipped += 1
                    continue
                target.write_bytes(data)
                saved += 1
            if not saved:
                raise HTTPException(400, "The folder holds no materials.json, .csv or .sldmat file.")
            payload = _activate(dest.resolve(), folder_name, "upload")
        except HTTPException:
            shutil.rmtree(dest, ignore_errors=True)
            raise
        except Exception as e:       # noqa: BLE001
            shutil.rmtree(dest, ignore_errors=True)
            raise HTTPException(400, f"The folder could not be read ({type(e).__name__}).")
        payload["uploaded"] = {"files": saved, "ignored": skipped}
        return payload

    @r.post("/api/materials/library/refresh")
    def refresh_library():
        s = read_settings()
        if not s.get("catalog_path"):
            raise HTTPException(409, "No company material library is set.")
        cat, err = _load_company(s, force=True)
        if cat is None:
            raise _fail(400, f"The company material library cannot be read: {err}")
        return settings_payload()

    @r.delete("/api/materials/library")
    def clear_library():
        s = read_settings()
        old = s.get("catalog_path") or ""
        s.update(catalog_path="", library_name="", library_origin="", use_demo=True)
        write_settings(s)
        _CACHE.pop(("company", old), None)
        _drop_upload(old)               # only a copy this server made; a user's own folder is never touched
        return settings_payload()

    @r.get("/api/parts/{session}/{part}/material")
    def part_material(session: str, part: str):
        return compose(session, part)

    @r.post("/api/parts/{session}/{part}/material/override")
    def set_override(session: str, part: str, body: OverrideBody):
        _catalog, _costing, runner = _pipeline()
        _pdir, out = _part_paths(session, part)
        reason = (body.reason or "").strip()
        if not reason:
            raise HTTPException(400, "A reason is required for a manual material override.")
        if len(reason) > 500:
            raise HTTPException(400, "The reason is limited to 500 characters.")
        mid = (body.material_id or "").strip()
        if not mid or len(mid) > 200:
            raise HTTPException(400, "Choose a material from the catalog.")
        settings = read_settings()
        cs = active_catalogs(settings)
        found = None
        for c in (cs["company"], cs["demo"], cs["standard"]):
            if c is None or (body.catalog_id and c.catalog_id != body.catalog_id):
                continue
            rec = c.by_id(mid)
            if rec is not None:
                found = (c, rec)
                break
        if found is None:
            raise HTTPException(400, "That material is not in the active catalogs.")
        user = re.sub(r"[^\w .@\-]+", "", (body.user or "").strip())[:60] or "local user"
        out.mkdir(parents=True, exist_ok=True)
        _atomic_write(out / runner.OVERRIDE_FILE, {"material_id": found[1].id, "catalog_id": found[0].catalog_id, "reason": reason, "user": user, "at": _now()})
        _reresolve(session, part, allow_empty=True)
        return compose(session, part)

    @r.delete("/api/parts/{session}/{part}/material/override")
    def clear_override(session: str, part: str):
        _catalog, _costing, runner = _pipeline()
        _pdir, out = _part_paths(session, part)
        f = out / runner.OVERRIDE_FILE
        if f.is_file():
            try:
                f.unlink()
            except OSError:
                raise HTTPException(500, "The override could not be removed.")
        _reresolve(session, part, allow_empty=True)
        return compose(session, part)

    @r.post("/api/parts/{session}/{part}/material/refresh")
    def refresh_part(session: str, part: str):
        _reresolve(session, part)
        return compose(session, part)

    @r.get("/api/parts/{session}/{part}/appearance")
    def part_appearance(session: str, part: str):
        a = _a()
        _pdir, out = _part_paths(session, part)
        side = _read_json(out / "appearance.json") if out.is_dir() else None
        if side is None:
            raise HTTPException(404, "No appearance sidecar for this part")
        stl, _src = a._active_stl(out)
        cur = _sha_of(stl) if stl else None
        res = dict(side)
        res.update(stl_current_sha256=cur, stl_name=stl.name if stl else None,
                   stl_matches=bool(cur and side.get("artifact_sha256") == cur),
                   viewer_apply=bool(cur and side.get("artifact_sha256") == cur and side.get("verified") is True))
        return res

    @r.get("/api/materials/batch")
    def batch(parts: list[str] = Query(default=[]), session: str = Query("")):
        a = _a()
        _c, costing, _r = _pipeline()
        rows: dict = {}
        estimates: list = []
        api_total, api_known = 0.0, 0
        for key in parts[:500]:
            sid, _, pname = key.rpartition("|")
            sid = sid or session
            if not sid or not pname:
                continue
            try:
                out = a._part_output_dir(sid, pname)
            except HTTPException:
                continue
            c = compact(out)
            try:
                api = a._usage_summary(out).get("total_cost_usd") if out.is_dir() else None
            except Exception:       # noqa: BLE001
                api = None
            c["api_cost_usd"] = api if isinstance(api, (int, float)) else None
            if c["api_cost_usd"] is not None:
                api_total += c["api_cost_usd"]
                api_known += 1
            rows[key if "|" in key else f"{sid}|{pname}"] = c
            est = _read_json(out / "material_costing.json") if out.is_dir() and c.get("evaluated") else None
            estimates.append(est)
        totals = costing.batch_totals(estimates)
        totals.update(parts=rows, evaluated_parts=sum(1 for c in rows.values() if c.get("evaluated")), total_parts=len(rows),
                      api_cost={"total_usd": round(api_total, 6), "parts_with_cost": api_known,
                                "note": "API run cost is reported separately and is never added to material cost."})
        return totals

    return r


def install(app, app_module) -> None:
    """Add the material routes directly to ``app`` (not via include_router, whose lazy wrapper hides route paths from code and tests
    that inspect ``app.routes``)."""
    for route in make_router(app_module).routes:
        app.router.routes.append(route)
